"""RL Map Manager — browse the celab.jetfox.ovh SteamWorkshop catalog and
install workshop maps into the BakkesMod WML CustomMaps folder.
"""
import json
import os
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

import backend

__version__ = "1.0.0"


# ----- FlowLayout: auto-reflow children based on available width ------------
# Adapted from the Qt FlowLayout example (BSD-licensed sample code).

class FlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=10, v_spacing=10):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self._items: list[QtWidgets.QLayoutItem] = []
        self._h_space = h_spacing
        self._v_space = v_spacing

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self):
        return self._h_space

    def verticalSpacing(self):
        return self._v_space

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QtCore.QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QtCore.QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = effective.x(), effective.y()
        line_height = 0
        for item in self._items:
            wid = item.widget()
            if wid is not None and not wid.isVisible():
                continue
            space_x = self._h_space
            space_y = self._v_space
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y() + m.bottom()


# ----- Theme: purple + grey, flat-modern ------------------------------------

PURPLE = "#9d4edd"
PURPLE_HOVER = "#b06fef"
PURPLE_PRESSED = "#7b2cbf"
PURPLE_DIM = "#5a3a86"
BG_WINDOW = "#16161c"
BG_SURFACE = "#22222a"
BG_SURFACE_HOVER = "#2a2a34"
BG_INPUT = "#1a1a22"
BORDER = "#34343c"
TEXT = "#e8e8ec"
TEXT_MUTED = "#9090a0"
TEXT_DIM = "#6a6a78"
SUCCESS = "#7cd99c"
WARN = "#e7c97c"
ERROR = "#e07c8e"


def _qss() -> str:
    return f"""
    QWidget {{
        background: {BG_WINDOW};
        color: {TEXT};
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 12px;
    }}
    QMainWindow, QDialog {{ background: {BG_WINDOW}; }}

    QLineEdit {{
        background: {BG_INPUT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 7px 10px;
        color: {TEXT};
        selection-background-color: {PURPLE};
    }}
    QLineEdit:focus {{
        border: 1px solid {PURPLE};
    }}

    QPushButton {{
        background: {PURPLE};
        color: white;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {PURPLE_HOVER}; }}
    QPushButton:pressed {{ background: {PURPLE_PRESSED}; }}
    QPushButton:disabled {{ background: #2e2e36; color: {TEXT_DIM}; }}

    QPushButton#secondary {{
        background: transparent;
        color: {TEXT};
        border: 1px solid {BORDER};
    }}
    QPushButton#secondary:hover {{
        border-color: {PURPLE};
        color: {PURPLE_HOVER};
    }}
    QPushButton#secondary:pressed {{
        background: {BG_SURFACE_HOVER};
    }}

    QComboBox {{
        background: {BG_INPUT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 10px;
        color: {TEXT};
    }}
    QComboBox:focus {{ border: 1px solid {PURPLE}; }}
    QComboBox QAbstractItemView {{
        background: {BG_SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        selection-background-color: {PURPLE_DIM};
        selection-color: white;
    }}

    QTextEdit {{
        background: {BG_INPUT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 8px;
        color: {TEXT};
    }}

    QScrollArea {{ border: none; background: {BG_WINDOW}; }}
    QScrollBar:vertical {{
        background: {BG_WINDOW}; width: 12px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: #3a3a44; min-height: 30px; border-radius: 5px; margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {PURPLE_DIM}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

    QSplitter::handle {{ background: {BG_WINDOW}; }}
    QSplitter::handle:horizontal {{ width: 3px; }}
    QSplitter::handle:hover {{ background: {PURPLE_DIM}; }}

    QProgressBar {{
        background: {BG_INPUT};
        border: 1px solid {BORDER};
        border-radius: 5px;
        height: 10px;
        text-align: center;
        color: {TEXT_MUTED};
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {PURPLE_PRESSED}, stop:1 {PURPLE_HOVER});
        border-radius: 4px;
    }}

    QMessageBox {{ background: {BG_SURFACE}; }}
    QMessageBox QLabel {{ color: {TEXT}; }}

    QLabel#title {{ font-size: 18px; font-weight: 700; color: {TEXT}; }}
    QLabel#h2 {{ font-size: 14px; font-weight: 600; color: {TEXT}; }}
    QLabel#muted {{ color: {TEXT_MUTED}; font-size: 11px; }}
    QLabel#good {{ color: {SUCCESS}; font-size: 11px; }}
    QLabel#warn {{ color: {WARN}; font-size: 11px; }}
    QLabel#error {{ color: {ERROR}; font-size: 11px; }}
    """


# ----- Concurrency helpers --------------------------------------------------

class _Signals(QtCore.QObject):
    finished = QtCore.Signal(object)
    error = QtCore.Signal(str)


class Job(QtCore.QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:
            self.signals.error.emit(f"{type(e).__name__}: {e}")
        else:
            self.signals.finished.emit(result)


# ----- Map card (grid tile) -------------------------------------------------

CARD_W, CARD_H = 252, 222
THUMB_W, THUMB_H = 232, 130


class MapCard(QtWidgets.QFrame):
    clicked = QtCore.Signal(dict)

    def __init__(self, project: dict, parent=None):
        super().__init__(parent)
        self.project = project
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setObjectName("MapCard")
        self._set_style(hover=False)

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        self.thumb = QtWidgets.QLabel(project["name"])
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(QtCore.Qt.AlignCenter)
        self.thumb.setWordWrap(True)
        self.thumb.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 #1c1c24, stop:1 {PURPLE_DIM});"
            f"color: {TEXT_MUTED}; border-radius: 4px; padding: 8px;"
            "font-size: 11px;"
        )
        v.addWidget(self.thumb)

        self.title = QtWidgets.QLabel(project["name"])
        self.title.setWordWrap(True)
        self.title.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 12px;")
        self.title.setMaximumHeight(34)
        v.addWidget(self.title)

        ns = project.get("namespace") or ""
        self.subtitle = QtWidgets.QLabel(("by " + ns) if ns else "")
        self.subtitle.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px;")
        v.addWidget(self.subtitle)
        v.addStretch()

        # Soft drop shadow that intensifies on hover
        self._shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        self._shadow.setColor(QtGui.QColor(0, 0, 0, 100))
        self._shadow.setBlurRadius(10)
        self._shadow.setOffset(0, 2)
        self.setGraphicsEffect(self._shadow)

        self._anim_blur = QtCore.QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._anim_blur.setDuration(180)
        self._anim_color = QtCore.QPropertyAnimation(self._shadow, b"color", self)
        self._anim_color.setDuration(180)

    def _set_style(self, hover: bool):
        border = PURPLE if hover else BORDER
        bg = BG_SURFACE_HOVER if hover else BG_SURFACE
        self.setStyleSheet(
            f"#MapCard {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; }}"
        )

    def enterEvent(self, event):
        self._set_style(hover=True)
        self._anim_blur.stop(); self._anim_blur.setStartValue(self._shadow.blurRadius()); self._anim_blur.setEndValue(28); self._anim_blur.start()
        self._anim_color.stop(); self._anim_color.setStartValue(self._shadow.color()); self._anim_color.setEndValue(QtGui.QColor(157, 78, 221, 140)); self._anim_color.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_style(hover=False)
        self._anim_blur.stop(); self._anim_blur.setStartValue(self._shadow.blurRadius()); self._anim_blur.setEndValue(10); self._anim_blur.start()
        self._anim_color.stop(); self._anim_color.setStartValue(self._shadow.color()); self._anim_color.setEndValue(QtGui.QColor(0, 0, 0, 100)); self._anim_color.start()
        super().leaveEvent(event)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit(self.project)

    def set_thumb_path(self, path: str | None):
        if not path:
            return
        pm = QtGui.QPixmap(path)
        if pm.isNull():
            return
        scaled = pm.scaled(THUMB_W, THUMB_H, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
        if scaled.width() > THUMB_W or scaled.height() > THUMB_H:
            x = (scaled.width() - THUMB_W) // 2
            y = (scaled.height() - THUMB_H) // 2
            scaled = scaled.copy(x, y, THUMB_W, THUMB_H)
        # Drop the styled gradient/text placeholder so the pixmap renders cleanly
        self.thumb.setStyleSheet("background:#0a0a10; border-radius:4px;")
        self.thumb.setPixmap(scaled)
        self.thumb.setText("")


# ----- Main window ----------------------------------------------------------

THUMB_WORKERS = 8
SETTINGS_FILE = backend.APP_DIR / "settings.json"


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_settings(d: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception:
        pass


class MainWindow(QtWidgets.QMainWindow):
    MIN_W, MIN_H = 720, 520

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"RL Map Manager v{__version__}")
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self.resize(1240, 800)

        self.pool = QtCore.QThreadPool.globalInstance()
        # Be polite to the small celab instance — keep concurrency moderate
        self.pool.setMaxThreadCount(THUMB_WORKERS + 2)

        self.mods_folder: Path | None = backend.find_mods_folder()
        self.catalog: list[dict] = backend.load_catalog()
        self.cards: list[MapCard] = []
        self.selected: dict | None = None
        self._active_thumb_jobs = 0
        self._thumb_index = 0
        # Keep Job objects alive until their signals fire — otherwise GC collects
        # them and the queued emit() never reaches the slot.
        self._live_jobs: set = set()

        self._build_ui()
        self._update_path_label()
        self._restore_geometry()

        if self.catalog:
            self._populate_grid(self.catalog)
            self._update_visible_count()
        else:
            self.refresh_catalog()

    # UI ---------------------------------------------------------------------

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(14, 14, 14, 10)
        outer.setSpacing(10)

        # Header row -----------------------------------------------------
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(10)
        brand = QtWidgets.QLabel("RL Map Manager")
        brand.setObjectName("title")
        brand.setStyleSheet(f"color:{PURPLE_HOVER}; font-size:20px; font-weight:700;")
        header.addWidget(brand)
        header.addStretch()
        outer.addLayout(header)

        # Toolbar row ----------------------------------------------------
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Search maps by name, description, or author...")
        self.search_box.textChanged.connect(self._filter)
        bar.addWidget(self.search_box, 2)

        self.sort_box = QtWidgets.QComboBox()
        self.sort_box.addItems(["Sort: Name", "Sort: Newest", "Sort: Popular (Steam)"])
        self.sort_box.currentIndexChanged.connect(self._on_sort_changed)
        bar.addWidget(self.sort_box)

        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_catalog)
        bar.addWidget(self.refresh_btn)

        self.pick_btn = QtWidgets.QPushButton("Change folder")
        self.pick_btn.setObjectName("secondary")
        self.pick_btn.clicked.connect(self._pick_mods_folder)
        bar.addWidget(self.pick_btn)

        self.open_folder_btn = QtWidgets.QPushButton("Open folder")
        self.open_folder_btn.setObjectName("secondary")
        self.open_folder_btn.clicked.connect(self._open_mods_folder)
        bar.addWidget(self.open_folder_btn)
        outer.addLayout(bar)

        # Path strip -----------------------------------------------------
        strip = QtWidgets.QFrame()
        strip.setStyleSheet(
            f"QFrame {{ background: {BG_SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; }}"
        )
        strip_l = QtWidgets.QHBoxLayout(strip)
        strip_l.setContentsMargins(12, 8, 12, 8)
        self.path_label = QtWidgets.QLabel()
        self.path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        strip_l.addWidget(self.path_label, 1)
        outer.addWidget(strip)

        # Body: grid | detail -------------------------------------------
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        outer.addWidget(split, 1)

        self.grid_scroll = QtWidgets.QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.verticalScrollBar().setSingleStep(28)
        self.grid_holder = QtWidgets.QWidget()
        self.grid_holder.setStyleSheet(f"background: {BG_WINDOW};")
        self.grid = FlowLayout(self.grid_holder, margin=4, h_spacing=14, v_spacing=14)
        self.grid_scroll.setWidget(self.grid_holder)
        split.addWidget(self.grid_scroll)

        split.addWidget(self._build_detail_panel())
        split.setSizes([840, 400])

        # Footer -------------------------------------------------------
        self.status = QtWidgets.QLabel("Ready")
        self.status.setObjectName("muted")
        outer.addWidget(self.status)

    def _build_detail_panel(self) -> QtWidgets.QWidget:
        wrap = QtWidgets.QFrame()
        wrap.setStyleSheet(
            f"QFrame {{ background: {BG_SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        v = QtWidgets.QVBoxLayout(wrap)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        self.d_thumb = QtWidgets.QLabel()
        self.d_thumb.setFixedHeight(220)
        self.d_thumb.setAlignment(QtCore.Qt.AlignCenter)
        self.d_thumb.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 #1c1c24, stop:1 {PURPLE_DIM});"
            f"color: {TEXT_DIM}; border-radius: 6px;"
        )
        self.d_thumb.setText("Select a map ←")
        v.addWidget(self.d_thumb)

        self.d_title = QtWidgets.QLabel("")
        self.d_title.setObjectName("title")
        self.d_title.setWordWrap(True)
        v.addWidget(self.d_title)

        self.d_meta = QtWidgets.QLabel("")
        self.d_meta.setObjectName("muted")
        v.addWidget(self.d_meta)

        self.d_desc = QtWidgets.QTextEdit()
        self.d_desc.setReadOnly(True)
        self.d_desc.setMinimumHeight(120)
        v.addWidget(self.d_desc, 1)

        self.d_filename = QtWidgets.QLabel("")
        self.d_filename.setObjectName("muted")
        self.d_filename.setWordWrap(True)
        v.addWidget(self.d_filename)

        self.d_install_status = QtWidgets.QLabel("")
        v.addWidget(self.d_install_status)

        self.d_install = QtWidgets.QPushButton("Download && Install")
        self.d_install.setEnabled(False)
        self.d_install.clicked.connect(self._install_clicked)
        v.addWidget(self.d_install)

        self.d_remove = QtWidgets.QPushButton("Remove from folder")
        self.d_remove.setObjectName("secondary")
        self.d_remove.setEnabled(False)
        self.d_remove.clicked.connect(self._remove_clicked)
        v.addWidget(self.d_remove)

        self.d_progress = QtWidgets.QProgressBar()
        self.d_progress.setRange(0, 100)
        self.d_progress.setValue(0)
        v.addWidget(self.d_progress)

        # Fade-in effect for detail content swap
        self._detail_opacity = QtWidgets.QGraphicsOpacityEffect(wrap)
        self._detail_opacity.setOpacity(1.0)
        wrap.setGraphicsEffect(self._detail_opacity)
        self._detail_anim = QtCore.QPropertyAnimation(self._detail_opacity, b"opacity", self)
        self._detail_anim.setDuration(220)
        self._detail_anim.setStartValue(0.0)
        self._detail_anim.setEndValue(1.0)

        return wrap

    # Path detection --------------------------------------------------------

    def _update_path_label(self):
        if self.mods_folder:
            count = len(backend.list_installed_mods(self.mods_folder))
            self.path_label.setText(
                f"<span style='color:{TEXT_MUTED};'>Maps folder · </span>"
                f"<span style='color:{TEXT};'>{self.mods_folder}</span>"
                f"<span style='color:{PURPLE_HOVER};'>  ·  {count} installed</span>"
            )
            self.open_folder_btn.setEnabled(True)
        else:
            self.path_label.setText(
                f"<span style='color:{ERROR};'>Maps folder not found — click 'Change folder' to pick it</span>"
            )
            self.open_folder_btn.setEnabled(False)
        self._refresh_install_status()

    def _pick_mods_folder(self):
        start = str(self.mods_folder) if self.mods_folder else ""
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Pick the Workshop Map Loader CustomMaps folder", start)
        if not d:
            return
        p = Path(d)
        self.mods_folder = p
        backend.save_mods_folder(p)
        self._update_path_label()

    def _open_mods_folder(self):
        if self.mods_folder and self.mods_folder.exists():
            os.startfile(str(self.mods_folder))

    # Geometry persistence + thread cleanup ---------------------------------

    def _restore_geometry(self):
        s = _load_settings()
        geo = s.get("geometry")
        if not geo:
            return
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = max(self.MIN_W, min(int(geo.get("w", 1240)), screen.width()))
        h = max(self.MIN_H, min(int(geo.get("h", 800)), screen.height()))
        x = max(screen.x(), min(int(geo.get("x", screen.x())), screen.x() + screen.width() - w))
        y = max(screen.y(), min(int(geo.get("y", screen.y())), screen.y() + screen.height() - h))
        self.setGeometry(x, y, w, h)
        sort_idx = s.get("sort_index")
        if isinstance(sort_idx, int) and 0 <= sort_idx < self.sort_box.count():
            self.sort_box.blockSignals(True)
            self.sort_box.setCurrentIndex(sort_idx)
            self.sort_box.blockSignals(False)

    def closeEvent(self, event):
        # Persist geometry + sort choice
        g = self.geometry()
        _save_settings({
            "geometry": {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()},
            "sort_index": self.sort_box.currentIndex(),
        })
        # Give pending workers a brief window to finish, then move on
        try:
            self.pool.clear()
            self.pool.waitForDone(2000)
        except Exception:
            pass
        super().closeEvent(event)

    def _refresh_install_status(self):
        if not self.selected or not self.mods_folder:
            self.d_install_status.setText("")
            self.d_remove.setEnabled(False)
            return
        name = backend.installed_folder_name_for(self.selected)
        if backend.is_installed(self.mods_folder, self.selected):
            self.d_install_status.setText(f"✓ Installed in folder: {name}\\")
            self.d_install_status.setObjectName("warn")
            self.d_install_status.setStyleSheet(f"color:{WARN}; font-size:11px;")
            self.d_remove.setEnabled(True)
        else:
            self.d_install_status.setText("Not installed")
            self.d_install_status.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
            self.d_remove.setEnabled(False)

    # Catalog ---------------------------------------------------------------

    def refresh_catalog(self):
        self.refresh_btn.setEnabled(False)
        self.status.setText("Fetching catalog from celab.jetfox.ovh ...")
        job = Job(backend.fetch_catalog)
        self._live_jobs.add(job)
        def done(p, _j=job): self._live_jobs.discard(_j); self._catalog_loaded(p)
        def err(m, _j=job): self._live_jobs.discard(_j); self._catalog_error(m)
        job.signals.finished.connect(done)
        job.signals.error.connect(err)
        self.pool.start(job)

    def _catalog_loaded(self, projects):
        backend.save_catalog(projects)
        self.catalog = projects
        self.status.setText(f"Loaded {len(projects)} maps · downloading previews in background")
        self.refresh_btn.setEnabled(True)
        self._populate_grid(projects)

    def _catalog_error(self, msg):
        self.status.setText(f"Catalog error: {msg}")
        self.status.setStyleSheet(f"color:{ERROR};")
        self.refresh_btn.setEnabled(True)

    def _populate_grid(self, projects):
        # Remove existing cards from the FlowLayout
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.cards.clear()

        for p in projects:
            card = MapCard(p)
            card.clicked.connect(self._show_detail)
            self.grid.addWidget(card)
            self.cards.append(card)

        self._thumb_index = 0
        self._active_thumb_jobs = 0
        for _ in range(THUMB_WORKERS):
            self._spawn_next_thumb_job()
        self._update_visible_count()

    def _spawn_next_thumb_job(self):
        if self._thumb_index >= len(self.cards):
            if self._active_thumb_jobs == 0:
                self.status.setText(f"Catalog ready · {len(self.catalog)} maps")
            return
        card = self.cards[self._thumb_index]
        self._thumb_index += 1
        self._active_thumb_jobs += 1

        proj = card.project
        job = Job(lambda: backend.get_grid_preview(proj))
        self._live_jobs.add(job)

        def done(path, _job=job):
            self._live_jobs.discard(_job)
            self._active_thumb_jobs -= 1
            if path:
                card.set_thumb_path(path)
            self._spawn_next_thumb_job()

        def err(_msg, _job=job):
            self._live_jobs.discard(_job)
            self._active_thumb_jobs -= 1
            self._spawn_next_thumb_job()

        job.signals.finished.connect(done)
        job.signals.error.connect(err)
        self.pool.start(job)

    def _filter(self, text: str):
        text = text.strip().lower()
        shown = 0
        for c in self.cards:
            blob = (c.project["name"] + " " + (c.project.get("description") or "") + " " + (c.project.get("namespace") or "")).lower()
            visible = text in blob if text else True
            c.setVisible(visible)
            if visible:
                shown += 1
        # FlowLayout reflows after visibility changes; trigger a re-layout
        self.grid.invalidate()
        self._update_visible_count(shown)

    def _update_visible_count(self, shown: int | None = None):
        total = len(self.cards)
        if shown is None:
            # Default to all-visible (no filter); filter callback always passes its own count
            shown = total
        age = backend.catalog_age_seconds()
        if age is None:
            age_str = "never refreshed"
        elif age < 3600:
            age_str = f"refreshed {age // 60}m ago"
        elif age < 86400:
            age_str = f"refreshed {age // 3600}h ago"
        else:
            age_str = f"refreshed {age // 86400}d ago"
        if shown == total:
            self.status.setText(f"{total} maps  ·  {age_str}")
        else:
            self.status.setText(f"{shown} of {total} maps shown  ·  {age_str}")

    def _on_sort_changed(self):
        if not self.catalog:
            return
        idx = self.sort_box.currentIndex()
        if idx == 0:
            sorted_cat = sorted(self.catalog, key=lambda p: p["name"].lower())
        elif idx == 1:
            sorted_cat = sorted(self.catalog, key=lambda p: p.get("last_activity_at") or "", reverse=True)
        else:
            # Popular = lifetime subscriptions from cached Steam meta, where known
            meta_cache = backend._load_steam_meta()
            ids_cache = backend._load_workshop_ids()
            def subs(p):
                wid = ids_cache.get(str(p["id"]))
                return -(meta_cache.get(wid, {}).get("lifetime_subscriptions", 0) if wid else 0)
            sorted_cat = sorted(self.catalog, key=subs)
        self._populate_grid(sorted_cat)

    # Detail / install ------------------------------------------------------

    def _show_detail(self, project: dict):
        self.selected = project
        self.d_title.setText(project["name"])
        bits = [f"#{project['id']}"]
        if project.get("last_activity_at"):
            bits.append(project["last_activity_at"][:10])
        ns = project.get("namespace")
        if ns:
            bits.append(f"by {ns}")
        self.d_meta.setText("  ·  ".join(bits))
        # Initial description = celab's; we'll replace with Steam's once fetched
        celab_desc = project.get("description") or "(loading description from Steam Workshop ...)"
        self.d_desc.setPlainText(celab_desc)
        name = backend.installed_folder_name_for(project)
        self.d_filename.setText(f"<span style='color:{TEXT_MUTED};'>Will install as:</span>  {name}\\{name}.upk")
        self.d_install.setEnabled(self.mods_folder is not None)
        self.d_thumb.setText("Loading preview...")
        self.d_thumb.setPixmap(QtGui.QPixmap())

        # Fade the detail content
        self._detail_anim.stop()
        self._detail_anim.start()

        def work():
            preview = backend.get_preview_path(project)
            description = backend.get_rich_description(project)
            stats = backend.get_steam_stats(project)
            return preview, description, stats

        job = Job(work)
        self._live_jobs.add(job)

        def done(result, _job=job):
            self._live_jobs.discard(_job)
            preview_path, description, stats = result
            # Make sure the user hasn't clicked another card while we were fetching
            if self.selected is not project:
                return
            if preview_path:
                pm = QtGui.QPixmap(preview_path)
                if not pm.isNull():
                    scaled = pm.scaled(self.d_thumb.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                    self.d_thumb.setPixmap(scaled)
                    self.d_thumb.setText("")
            if description:
                self.d_desc.setPlainText(description.replace("\r\n", "\n"))
            elif not (project.get("description") or "").strip():
                self.d_desc.setPlainText("(no description available)")
            if stats:
                extra = []
                if stats.get("subscriptions"):
                    extra.append(f"{stats['subscriptions']:,} subs")
                if stats.get("lifetime_subscriptions"):
                    extra.append(f"{stats['lifetime_subscriptions']:,} lifetime")
                if stats.get("views"):
                    extra.append(f"{stats['views']:,} views")
                if stats.get("file_size") and stats["file_size"] != "0":
                    try:
                        mb = int(stats["file_size"]) / (1024 * 1024)
                        extra.append(f"{mb:.1f} MB")
                    except Exception:
                        pass
                if extra:
                    self.d_meta.setText(self.d_meta.text() + "  ·  " + "  ·  ".join(extra))

        job.signals.finished.connect(done)
        self.pool.start(job)
        self._refresh_install_status()

    def _install_clicked(self):
        if not self.selected or not self.mods_folder:
            return
        proj = self.selected
        mods = self.mods_folder

        self.d_install.setEnabled(False)
        self.d_install.setText("Downloading...")
        self.d_progress.setValue(0)

        def work():
            zip_url, _, _ = backend.get_release_info(proj["id"])
            if not zip_url:
                raise RuntimeError("No release zip available for this map.")

            def progress(got, total):
                if total > 0:
                    pct = int(got * 100 / total)
                    QtCore.QMetaObject.invokeMethod(
                        self.d_progress, "setValue", QtCore.Qt.QueuedConnection,
                        QtCore.Q_ARG(int, pct),
                    )

            zip_path = backend.download_zip(proj["id"], zip_url, on_progress=progress)
            map_file = backend.extract_map_file(zip_path)
            return backend.install_to_custom_maps(mods, map_file, proj.get("path", ""), proj["name"])

        job = Job(work)
        self._live_jobs.add(job)

        def done(dest_path, _job=job):
            self._live_jobs.discard(_job)
            self.d_progress.setValue(100)
            self.d_install.setEnabled(True)
            self.d_install.setText("Download && Install")
            self._update_path_label()
            QtWidgets.QMessageBox.information(
                self, "Installed",
                f"Installed '{proj['name']}'\n→ {dest_path}\n\n"
                "Load it in Rocket League via the Workshop Map Loader plugin.",
            )

        def err(msg, _job=job):
            self._live_jobs.discard(_job)
            self.d_install.setEnabled(True)
            self.d_install.setText("Download && Install")
            QtWidgets.QMessageBox.critical(self, "Install failed", msg)

        job.signals.finished.connect(done)
        job.signals.error.connect(err)
        self.pool.start(job)

    def _remove_clicked(self):
        if not self.selected or not self.mods_folder:
            return
        name = backend.installed_folder_name_for(self.selected)
        r = QtWidgets.QMessageBox.question(
            self, "Remove map", f"Delete the '{name}' folder from CustomMaps?",
        )
        if r != QtWidgets.QMessageBox.Yes:
            return
        try:
            backend.remove_installed(self.mods_folder, self.selected)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Remove failed", str(e))
            return
        self._update_path_label()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(_qss())

    pal = app.palette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor(BG_WINDOW))
    pal.setColor(QtGui.QPalette.Base, QtGui.QColor(BG_INPUT))
    pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(BG_SURFACE))
    pal.setColor(QtGui.QPalette.Text, QtGui.QColor(TEXT))
    pal.setColor(QtGui.QPalette.WindowText, QtGui.QColor(TEXT))
    pal.setColor(QtGui.QPalette.Button, QtGui.QColor(PURPLE))
    pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#ffffff"))
    pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(PURPLE))
    pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
    app.setPalette(pal)

    w = MainWindow()
    # If no saved geometry, center on primary screen
    if not _load_settings().get("geometry"):
        primary = app.primaryScreen().availableGeometry()
        w.setGeometry(
            primary.x() + max(0, (primary.width() - 1240) // 2),
            primary.y() + max(0, (primary.height() - 800) // 2),
            1240, 800,
        )
    w.show()
    w.raise_()
    w.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
