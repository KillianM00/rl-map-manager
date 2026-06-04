"""Data + filesystem layer for RL Map Manager.

Catalog source: celab.jetfox.ovh GitLab, namespace `SteamWorkshop`.
This is the same backend the BakkesMod Workshop Map Loader plugin uses.
"""
import json
import os
import re
import shutil
import ssl
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

# celab.jetfox.ovh's TLS cert is currently expired. For a personal-use tool
# pointed at a known community map mirror, accept that and skip verification.
_SSL_CTX = ssl._create_unverified_context()

GITLAB_BASE = "https://celab.jetfox.ovh/api/v4"
UA = "RLMapManager/0.2"

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / "RLMapManager"
CACHE_DIR = APP_DIR / "cache"
THUMB_DIR = CACHE_DIR / "thumbs"
DOWNLOAD_DIR = APP_DIR / "downloads"
CATALOG_FILE = CACHE_DIR / "catalog.json"
RELEASES_FILE = CACHE_DIR / "releases.json"
TREES_FILE = CACHE_DIR / "trees.json"
WORKSHOP_IDS_FILE = CACHE_DIR / "workshop_ids.json"
STEAM_META_FILE = CACHE_DIR / "steam_meta.json"
STEAM_PREVIEW_DIR = THUMB_DIR / "steam"
PATH_FILE = APP_DIR / "rl_path.txt"
MODS_PATH_FILE = APP_DIR / "mods_path.txt"

for d in (APP_DIR, CACHE_DIR, THUMB_DIR, DOWNLOAD_DIR, STEAM_PREVIEW_DIR):
    d.mkdir(parents=True, exist_ok=True)

STEAM_UGC_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"


def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return r.read()


# --- Catalog ---

def _normalize_title(s: str) -> str:
    """Collapse a map title to a comparison key so dupes can be detected."""
    s = re.sub(r"[^A-Za-z0-9]+", "", s).lower()
    s = re.sub(r"(?:by|made|map|the)", "", s)
    return s


def _dedupe_projects(projects: list[dict]) -> list[dict]:
    """Same map uploaded to multiple namespaces (user + SteamWorkshop scrape) appears
    twice in the raw catalog. Collapse those — prefer the SteamWorkshop entry since
    it's the canonical scrape with .vdf metadata."""
    by_key: dict[str, dict] = {}
    for p in projects:
        key = _normalize_title(p["name"])
        if not key:
            by_key[f"_id_{p['id']}"] = p
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = p
            continue
        # Same map name — pick the SteamWorkshop entry over user uploads
        if p.get("namespace") == "SteamWorkshop" and existing.get("namespace") != "SteamWorkshop":
            by_key[key] = p
    return list(by_key.values())


def fetch_catalog(progress=None) -> list[dict]:
    """Paginate through every project on the celab instance (~740 raw, ~733 after dedup)."""
    projects: list[dict] = []
    page = 1
    while True:
        url = f"{GITLAB_BASE}/projects?per_page=100&page={page}&order_by=name&sort=asc"
        try:
            data = json.loads(_http_get(url))
        except Exception as e:
            if progress:
                progress(f"Page {page} failed: {e}")
            break
        if not data:
            break
        for p in data:
            projects.append({
                "id": p["id"],
                "name": p["name"],
                "path": p["path"],
                "description": p.get("description") or "",
                "web_url": p["web_url"],
                "last_activity_at": p.get("last_activity_at"),
                "namespace": (p.get("namespace") or {}).get("name", ""),
            })
        if progress:
            progress(f"Loaded {len(projects)} maps...")
        if len(data) < 100:
            break
        page += 1
    deduped = _dedupe_projects(projects)
    if progress and len(deduped) < len(projects):
        progress(f"Deduped {len(projects) - len(deduped)} entries")
    deduped.sort(key=lambda p: p["name"].lower())
    return deduped


def catalog_age_seconds() -> int | None:
    """Seconds since catalog was last refreshed; None if never."""
    if not CATALOG_FILE.exists():
        return None
    return int(time.time() - CATALOG_FILE.stat().st_mtime)


def save_catalog(projects: list[dict]) -> None:
    CATALOG_FILE.write_text(json.dumps(projects, indent=2), encoding="utf-8")


def load_catalog() -> list[dict]:
    if CATALOG_FILE.exists():
        try:
            return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


# --- Per-project release info (zip + thumbnail URL), cached ---

def _load_releases_cache() -> dict:
    if RELEASES_FILE.exists():
        try:
            return json.loads(RELEASES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_releases_cache(cache: dict) -> None:
    RELEASES_FILE.write_text(json.dumps(cache), encoding="utf-8")


_releases_cache: dict | None = None


def get_release_info(project_id: int) -> tuple[str | None, str | None, str | None]:
    """Return (zip_url, thumb_url, version_tag). Cached on disk per project."""
    global _releases_cache
    if _releases_cache is None:
        _releases_cache = _load_releases_cache()
    key = str(project_id)
    if key in _releases_cache:
        ent = _releases_cache[key]
        return ent.get("zip"), ent.get("thumb"), ent.get("tag")
    try:
        data = json.loads(_http_get(f"{GITLAB_BASE}/projects/{project_id}/releases", timeout=15))
    except Exception:
        return None, None, None
    if not data:
        _releases_cache[key] = {"zip": None, "thumb": None, "tag": None}
        _save_releases_cache(_releases_cache)
        return None, None, None
    rel = data[0]
    zip_url = thumb_url = None
    for link in rel.get("assets", {}).get("links", []):
        url = link.get("direct_asset_url") or link.get("url")
        if not url:
            continue
        low = url.lower()
        if low.endswith(".zip") and not zip_url:
            zip_url = url
        elif low.endswith((".jpg", ".jpeg", ".png")) and not thumb_url:
            thumb_url = url
    tag = rel.get("tag_name")
    _releases_cache[key] = {"zip": zip_url, "thumb": thumb_url, "tag": tag}
    _save_releases_cache(_releases_cache)
    return zip_url, thumb_url, tag


def fetch_thumbnail(project_id: int, thumb_url: str | None) -> str | None:
    if not thumb_url:
        return None
    ext = ".jpg"
    low = thumb_url.lower()
    if low.endswith(".png"):
        ext = ".png"
    elif low.endswith(".jpeg"):
        ext = ".jpeg"
    dest = THUMB_DIR / f"{project_id}{ext}"
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    try:
        data = _http_get(thumb_url, timeout=20)
        dest.write_bytes(data)
        return str(dest)
    except Exception:
        return None


# Files we'll consider as map preview images, in priority order
_PREVIEW_NAMES_PRIO = ("RLMPreview.jpg", "preview.png", "preview.jpg", "thumbnail.jpg", "thumbnail.png", "screenshot.png", "screenshot.jpg")
_IMG_EXTS = (".jpg", ".jpeg", ".png")


# --- Repo tree cache (single fetch per project, shared by preview + .vdf lookup) ----

_trees_cache: dict | None = None


def _load_trees() -> dict:
    global _trees_cache
    if _trees_cache is None:
        if TREES_FILE.exists():
            try:
                _trees_cache = json.loads(TREES_FILE.read_text(encoding="utf-8"))
            except Exception:
                _trees_cache = {}
        else:
            _trees_cache = {}
    return _trees_cache


def _save_trees() -> None:
    if _trees_cache is not None:
        TREES_FILE.write_text(json.dumps(_trees_cache), encoding="utf-8")


def get_project_files(project_id: int) -> list[str]:
    """Return a cached list of blob filenames in the project root."""
    cache = _load_trees()
    key = str(project_id)
    if key in cache:
        return cache[key]
    try:
        tree = json.loads(_http_get(f"{GITLAB_BASE}/projects/{project_id}/repository/tree?per_page=100", timeout=15))
    except Exception:
        cache[key] = []
        _save_trees()
        return []
    files = [e["name"] for e in tree if isinstance(e, dict) and e.get("type") == "blob"]
    cache[key] = files
    _save_trees()
    return files


# --- Steam Workshop ID lookup (parse .vdf from repo) -----------------------

_workshop_ids: dict | None = None


def _load_workshop_ids() -> dict:
    global _workshop_ids
    if _workshop_ids is None:
        if WORKSHOP_IDS_FILE.exists():
            try:
                _workshop_ids = json.loads(WORKSHOP_IDS_FILE.read_text(encoding="utf-8"))
            except Exception:
                _workshop_ids = {}
        else:
            _workshop_ids = {}
    return _workshop_ids


def _save_workshop_ids() -> None:
    if _workshop_ids is not None:
        WORKSHOP_IDS_FILE.write_text(json.dumps(_workshop_ids), encoding="utf-8")


def get_workshop_id(project_id: int) -> str | None:
    """Find the Steam Workshop publishedfileid by parsing the project's .vdf manifest."""
    ids = _load_workshop_ids()
    key = str(project_id)
    if key in ids:
        return ids[key]
    files = get_project_files(project_id)
    vdf_name = next((n for n in files if n.lower().endswith(".vdf")), None)
    if not vdf_name:
        ids[key] = None
        _save_workshop_ids()
        return None
    encoded = urllib.request.quote(vdf_name, safe="")
    for ref in ("master", "main"):
        try:
            raw = _http_get(f"{GITLAB_BASE}/projects/{project_id}/repository/files/{encoded}/raw?ref={ref}", timeout=15)
        except Exception:
            continue
        m = re.search(rb'"publishedfileid"\s*"(\d+)"', raw)
        if m:
            wid = m.group(1).decode()
            ids[key] = wid
            _save_workshop_ids()
            return wid
    ids[key] = None
    _save_workshop_ids()
    return None


# --- Steam UGC metadata cache ----------------------------------------------

_steam_meta: dict | None = None


def _load_steam_meta() -> dict:
    global _steam_meta
    if _steam_meta is None:
        if STEAM_META_FILE.exists():
            try:
                _steam_meta = json.loads(STEAM_META_FILE.read_text(encoding="utf-8"))
            except Exception:
                _steam_meta = {}
        else:
            _steam_meta = {}
    return _steam_meta


def _save_steam_meta() -> None:
    if _steam_meta is not None:
        STEAM_META_FILE.write_text(json.dumps(_steam_meta, ensure_ascii=False), encoding="utf-8")


def get_steam_metadata(workshop_id: str) -> dict | None:
    """Fetch title/description/preview_url/etc from Steam's UGC API (cached)."""
    meta = _load_steam_meta()
    if workshop_id in meta:
        return meta[workshop_id] or None
    try:
        body = f"itemcount=1&publishedfileids[0]={workshop_id}".encode()
        req = urllib.request.Request(
            STEAM_UGC_URL,
            data=body,
            headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            payload = json.loads(r.read())
        d = payload["response"]["publishedfiledetails"][0]
    except Exception:
        return None
    if d.get("result") != 1:
        meta[workshop_id] = {}
        _save_steam_meta()
        return None
    meta[workshop_id] = {
        "title": d.get("title", ""),
        "description": d.get("description", ""),
        "preview_url": d.get("preview_url", ""),
        "subscriptions": d.get("subscriptions", 0),
        "lifetime_subscriptions": d.get("lifetime_subscriptions", 0),
        "views": d.get("views", 0),
        "time_created": d.get("time_created", 0),
        "time_updated": d.get("time_updated", 0),
        "file_size": d.get("file_size", "0"),
    }
    _save_steam_meta()
    return meta[workshop_id]


def fetch_steam_preview(workshop_id: str, preview_url: str) -> str | None:
    if not preview_url:
        return None
    dest = STEAM_PREVIEW_DIR / f"{workshop_id}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    try:
        data = _http_get(preview_url, timeout=20)
        dest.write_bytes(data)
        return str(dest)
    except Exception:
        return None


def get_rich_description(project: dict) -> str:
    """Steam Workshop description (richer) if we can map this project to one, else celab's."""
    wid = get_workshop_id(project["id"])
    if wid:
        meta = get_steam_metadata(wid)
        if meta and meta.get("description"):
            return meta["description"]
    return project.get("description") or ""


def get_steam_stats(project: dict) -> dict | None:
    wid = get_workshop_id(project["id"])
    if not wid:
        return None
    return get_steam_metadata(wid)


def _find_repo_preview(project_id: int) -> str | None:
    """Hit the cached tree and pick the best image file in the repo root."""
    files_list = get_project_files(project_id)
    if not files_list:
        return None
    files = {n: True for n in files_list}
    # Try canonical names first, then any image
    chosen = None
    for name in _PREVIEW_NAMES_PRIO:
        if name in files:
            chosen = name
            break
    if not chosen:
        for name in files:
            if name.lower().endswith(_IMG_EXTS):
                chosen = name
                break
    if not chosen:
        return None
    # Try default branch (master then main)
    for ref in ("master", "main"):
        raw_url = f"{GITLAB_BASE}/projects/{project_id}/repository/files/{urllib.request.quote(chosen, safe='')}/raw?ref={ref}"
        try:
            data = _http_get(raw_url, timeout=20)
        except Exception:
            continue
        ext = ".jpg"
        low = chosen.lower()
        for e in _IMG_EXTS:
            if low.endswith(e):
                ext = e
                break
        dest = THUMB_DIR / f"{project_id}{ext}"
        dest.write_bytes(data)
        return str(dest)
    return None


def _placeholder_thumb(project_id: int, project_name: str) -> str:
    """Generate an on-theme placeholder image so every card has a preview."""
    dest = THUMB_DIR / f"{project_id}_placeholder.png"
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    # Avoid importing Qt in the backend; generate a minimal PNG with PIL if available,
    # otherwise hand back a 1x1 transparent PNG and let the UI render text on top.
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
        W, H = 420, 236
        palettes = [
            ((30, 30, 38), (76, 36, 130)),
            ((30, 30, 38), (110, 60, 170)),
            ((26, 26, 32), (60, 30, 110)),
            ((34, 30, 42), (90, 50, 150)),
        ]
        c1, c2 = palettes[project_id % len(palettes)]
        # Build a fast diagonal gradient via two small interpolated stripes + scale
        # (~20× faster than per-pixel putpixel for a 420×236 canvas)
        line = Image.new("RGB", (W, 1))
        for x in range(W):
            t = x / (W - 1)
            line.putpixel((x, 0), (
                int(c1[0] * (1 - t) + c2[0] * t),
                int(c1[1] * (1 - t) + c2[1] * t),
                int(c1[2] * (1 - t) + c2[2] * t),
            ))
        img = line.resize((W, H))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("segoeui.ttf", 22)
        except Exception:
            font = ImageFont.load_default()
        # Word-wrap title roughly
        words = (project_name or "Map").split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textlength(test, font=font) > W - 40 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = test
        if cur:
            lines.append(cur)
        lines = lines[:3]
        line_h = 28
        y0 = (H - line_h * len(lines)) // 2
        for i, ln in enumerate(lines):
            w_text = draw.textlength(ln, font=font)
            draw.text(((W - w_text) // 2, y0 + i * line_h), ln, fill=(230, 220, 245), font=font)
        img.save(dest, "PNG", optimize=True)
        return str(dest)
    except Exception:
        # No PIL → 1x1 transparent png as last resort
        dest.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return str(dest)


def get_grid_preview(project: dict) -> str | None:
    """Cheap preview source for the grid: only the celab release thumbnail.

    One API call per project (release info, cached). Returns None if the
    project has no release image — the UI keeps its styled placeholder card
    in that case rather than waiting on a slow chain.
    """
    pid = project["id"]
    _, thumb_url, _ = get_release_info(pid)
    if thumb_url:
        return fetch_thumbnail(pid, thumb_url)
    return None


def get_preview_path(project: dict) -> str:
    """High-quality preview for the detail panel.

    Fallback chain: Steam Workshop preview → celab release asset → repo-root
    image → on-theme placeholder. Always returns *some* path, never None.
    """
    pid = project["id"]
    # 1) Steam Workshop preview (biggest + best quality)
    wid = get_workshop_id(pid)
    if wid:
        meta = get_steam_metadata(wid)
        if meta and meta.get("preview_url"):
            p = fetch_steam_preview(wid, meta["preview_url"])
            if p:
                return p
    # 2) celab release asset thumbnail
    _, thumb_url, _ = get_release_info(pid)
    if thumb_url:
        p = fetch_thumbnail(pid, thumb_url)
        if p:
            return p
    # 3) image in the git repo
    p = _find_repo_preview(pid)
    if p:
        return p
    # 4) generated placeholder so every map shows *something*
    return _placeholder_thumb(pid, project.get("name", ""))


# --- Download + extract ---

def download_zip(project_id: int, zip_url: str, on_progress=None) -> Path:
    dest = DOWNLOAD_DIR / f"{project_id}.zip"
    if dest.exists() and dest.stat().st_size > 1024:
        if on_progress:
            on_progress(dest.stat().st_size, dest.stat().st_size)
        return dest
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(zip_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as r:
        total = int(r.headers.get("Content-Length", "0"))
        got = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if on_progress:
                    on_progress(got, total)
    tmp.replace(dest)
    return dest


def extract_map_file(zip_path: Path) -> Path:
    """Pull the first .upk or .udk out of the zip; return the extracted path."""
    out_dir = DOWNLOAD_DIR / f"{zip_path.stem}_extracted"
    out_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        name = next(
            (n for n in z.namelist() if n.lower().endswith((".upk", ".udk"))),
            None,
        )
        if not name:
            raise RuntimeError("No .upk or .udk file found inside the zip")
        z.extract(name, out_dir)
        return out_dir / name


# --- Rocket League install detection ---

def _saved_path() -> Path | None:
    if PATH_FILE.exists():
        p = Path(PATH_FILE.read_text(encoding="utf-8").strip())
        if p.exists():
            return p
    return None


def save_install_path(path: Path) -> None:
    PATH_FILE.write_text(str(path), encoding="utf-8")


def cooked_dir(install_path: Path) -> Path:
    return Path(install_path) / "TAGame" / "CookedPCConsole"


def is_valid_rl_install(path: Path) -> bool:
    return cooked_dir(path).exists()


def find_rl_install() -> Path | None:
    saved = _saved_path()
    if saved and is_valid_rl_install(saved):
        return saved

    # Epic Games manifests
    epic_dir = Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests")
    if epic_dir.exists():
        for item in epic_dir.glob("*.item"):
            try:
                m = json.loads(item.read_text(encoding="utf-8"))
            except Exception:
                continue
            if m.get("DisplayName") == "Rocket League" or m.get("AppName") == "Sugar":
                loc = m.get("InstallLocation")
                if loc:
                    p = Path(loc)
                    if is_valid_rl_install(p):
                        return p

    # Steam (rare for RL post-2020, but check anyway)
    try:
        import winreg
        for hk, sub in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        ]:
            try:
                with winreg.OpenKey(hk, sub) as key:
                    steam_path = Path(winreg.QueryValueEx(key, "InstallPath")[0])
            except OSError:
                continue
            vdf = steam_path / "steamapps" / "libraryfolders.vdf"
            if vdf.exists():
                text = vdf.read_text(encoding="utf-8", errors="replace")
                for lib in re.findall(r'"path"\s*"([^"]+)"', text):
                    candidate = Path(lib.replace("\\\\", "\\")) / "steamapps" / "common" / "rocketleague"
                    if is_valid_rl_install(candidate):
                        return candidate
            break
    except Exception:
        pass

    # Common fallback paths
    for c in [
        r"C:\Program Files\Epic Games\rocketleague",
        r"C:\Program Files (x86)\Epic Games\rocketleague",
        r"D:\Epic Games\rocketleague",
        r"E:\Epic Games\rocketleague",
    ]:
        p = Path(c)
        if is_valid_rl_install(p):
            return p
    return None


# --- Workshop Map Loader's CustomMaps folder (additive, subfolder-per-map) -
# WML config: %APPDATA%\bakkesmod\bakkesmod\data\WorkshopMapLoader\workshopmaploader.cfg
# Layout:  <CustomMaps>\<MapName>\<MapName>.upk (or .udk)

WML_CFG_PATH = Path(os.environ.get("APPDATA", "")) / "bakkesmod" / "bakkesmod" / "data" / "WorkshopMapLoader" / "workshopmaploader.cfg"


def _read_wml_maps_folder() -> Path | None:
    """Parse WML's workshopmaploader.cfg for its MapsFolderPath setting."""
    if not WML_CFG_PATH.exists():
        return None
    try:
        text = WML_CFG_PATH.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    m = re.search(r'MapsFolderPath\s*=\s*"([^"]+)"', text)
    if not m:
        return None
    # cfg has mixed slashes like "C:/Users\360ol\Documents\..."; let Path normalize
    p = Path(m.group(1))
    return p if p.exists() else None


def saved_mods_folder() -> Path | None:
    if MODS_PATH_FILE.exists():
        p = Path(MODS_PATH_FILE.read_text(encoding="utf-8").strip())
        if p.exists():
            return p
    return None


def save_mods_folder(path: Path) -> None:
    MODS_PATH_FILE.write_text(str(path), encoding="utf-8")


def find_mods_folder() -> Path | None:
    """User-saved override → WML config → <RL>\\Documents\\...\\CustomMaps fallback → None."""
    saved = saved_mods_folder()
    if saved:
        return saved
    wml = _read_wml_maps_folder()
    if wml:
        return wml
    # Fall back to the common Documents path
    docs = Path.home() / "Documents" / "My Games" / "Rocket League" / "CustomMaps"
    if docs.exists():
        return docs
    docs_alt = Path.home() / "Documents" / "My games" / "Rocket League" / "CustomMaps"
    if docs_alt.exists():
        return docs_alt
    return None


_MAP_EXTS = (".upk", ".udk")


def list_installed_mods(maps_folder: Path) -> list[str]:
    """Return subfolder names that contain a .upk/.udk file."""
    if not maps_folder.exists():
        return []
    out = []
    for sub in maps_folder.iterdir():
        if not sub.is_dir():
            continue
        if any(f.is_file() and f.suffix.lower() in _MAP_EXTS for f in sub.iterdir()):
            out.append(sub.name)
    return sorted(out)


def _safe_name(project_path: str, project_name: str) -> str:
    """Use the GitLab project path (already URL-safe) when present, else clean the name."""
    base = project_path or project_name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "", base.replace(" ", ""))
    if not cleaned:
        cleaned = "WorkshopMap"
    return cleaned


def install_to_custom_maps(maps_folder: Path, map_file: Path, project_path: str, project_name: str) -> Path:
    """Create <maps_folder>\\<name>\\ and copy the .upk/.udk inside as <name><ext>."""
    name = _safe_name(project_path, project_name)
    ext = map_file.suffix.lower()
    if ext not in _MAP_EXTS:
        ext = ".upk"
    sub = maps_folder / name
    sub.mkdir(parents=True, exist_ok=True)
    dest = sub / f"{name}{ext}"
    shutil.copy2(map_file, dest)
    return dest


def installed_folder_name_for(project: dict) -> str:
    return _safe_name(project.get("path", ""), project.get("name", ""))


def is_installed(maps_folder: Path, project: dict) -> bool:
    sub = maps_folder / installed_folder_name_for(project)
    if not sub.is_dir():
        return False
    return any(f.is_file() and f.suffix.lower() in _MAP_EXTS for f in sub.iterdir())


def remove_installed(maps_folder: Path, project: dict) -> None:
    sub = maps_folder / installed_folder_name_for(project)
    if sub.exists() and sub.is_dir():
        shutil.rmtree(sub)
