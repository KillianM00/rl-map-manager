# RL Map Manager

A clean desktop browser for Rocket League custom workshop maps. Picks up the BakkesMod **Workshop Map Loader** plugin's `CustomMaps` folder automatically and installs maps into it with one click — no Steam account, no SteamCMD, no `.upk` swapping.

## Why this exists

Rocket League's Steam Workshop went read-only when the game moved to Epic in 2020. Steam's own CDN no longer hands out workshop files anonymously, and `SteamWorkshopDownloader`-style tools fail with `ERROR! Download item ... failed (Failure)` because they try to use `+login anonymous`. This project uses the community GitLab mirror at `celab.jetfox.ovh`, which is the same backend the [Workshop Map Loader & Downloader](https://github.com/Vyncc/Workshop-Map-Loader-Downloader) plugin uses. This app exposes that mirror as a polished standalone browser with richer metadata pulled from Steam.

## Features

- Browses **a changing catalog of community maps** from the `celab.jetfox.ovh` community mirror (all namespaces, deduplicated).
- Every card has a preview image with a 3-tier fallback chain (Steam Workshop image → release asset → repo image → generated placeholder).
- Detail panel pulls **rich Steam Workshop metadata** when available — full description, lifetime subscriptions, views, file size — by parsing each project's `.vdf` manifest for its `publishedfileid` and hitting Steam's UGC API.
- **Auto-detects the WML CustomMaps folder** by reading `workshopmaploader.cfg`. Installs use the layout WML expects (`<CustomMaps>\<MapName>\<MapName>.upk`).
- Responsive flow layout — cards reflow to fit any window size.
- Sort by name, newest, or Steam popularity. Search across title, description, and author.
- Window geometry, sort choice, and folder picks persist between sessions.
- Local cache means subsequent launches are instant.

## Install

Requires Python 3.10+ on Windows.

```powershell
git clone https://github.com/KillianM00/rl-map-manager.git
cd rl-map-manager
pip install -r requirements.txt
pythonw rlmm.py
```

For a double-clickable launcher, create a shortcut to:

```
pythonw.exe "C:\path\to\rl-map-manager\rlmm.py"
```

## How install works

1. App reads `%APPDATA%\bakkesmod\bakkesmod\data\WorkshopMapLoader\workshopmaploader.cfg` to find your `MapsFolderPath`.
2. Falls back to `%USERPROFILE%\Documents\My Games\Rocket League\CustomMaps\` if the cfg is missing.
3. Click a map → "Download && Install" → app fetches the release zip from celab, extracts the `.upk`/`.udk`, and drops it into `<CustomMaps>\<SafeName>\<SafeName>.upk`.
4. WML's in-game UI lists it instantly. No restart needed.

The "Remove" button deletes only the specific subfolder this app created — it never touches maps you installed yourself by other means.

## Caches (under `%APPDATA%\RLMapManager\`)

| File | Purpose |
|---|---|
| `cache/catalog.json` | Full deduplicated map list (refreshed on demand) |
| `cache/releases.json` | Per-project zip + thumbnail URLs |
| `cache/trees.json` | Per-project file listings |
| `cache/workshop_ids.json` | celab project ID → Steam Workshop ID map |
| `cache/steam_meta.json` | Steam Workshop metadata (title, description, subs, etc.) |
| `cache/thumbs/` | Cached preview images (small) |
| `cache/thumbs/steam/` | Cached Steam Workshop preview images (large) |
| `settings.json` | Window geometry, sort choice |
| `mods_path.txt` | Saved override for the CustomMaps folder |
| `downloads/` | Downloaded release zips and extracted map files |

Deleting the `%APPDATA%\RLMapManager` folder is a clean uninstall.

## Caveats

- **HTTPS certificates are verified for catalog and archive downloads.** If the mirror has an expired or untrusted certificate, the request fails. Wait for the mirror operator to restore a valid certificate; do not disable verification.
- **The mirror does not have every workshop map.** It's community-curated. Maps not on Steam pre-2020 or that the maintainers haven't imported yet won't appear. Catalog size and availability depend on the community mirror.
- **You still need the [BakkesMod Workshop Map Loader plugin](https://bakkesplugins.com/plugin/223) installed to load maps in-game.** This app handles the download/install half of the workflow — WML handles the in-game launch half.

## Credits

- [celab.jetfox.ovh](https://celab.jetfox.ovh/SteamWorkshop) — the community GitLab instance that mirrors Steam Workshop map files. Without it this app couldn't exist.
- [Vyncc/Workshop-Map-Loader-Downloader](https://github.com/Vyncc/Workshop-Map-Loader-Downloader) — the BakkesMod plugin whose backend reverse-engineering pointed us at celab.
- BakkesMod team — making custom maps loadable in modern RL at all.

## License

MIT. See [LICENSE](LICENSE).

## Development checks

Install `pytest`, then run `python -m pytest tests -q`. Transport regression tests verify that invalid certificates fail without an insecure retry.
