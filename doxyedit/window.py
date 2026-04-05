"""Main application window — tabbed layout with all panels."""
import tempfile
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QFileDialog, QStatusBar,
    QGraphicsTextItem, QGraphicsRectItem, QGraphicsLineItem,
    QGraphicsPixmapItem, QColorDialog, QMessageBox, QSplitter,
    QWidget, QVBoxLayout, QApplication, QLabel, QProgressBar,
)
from PySide6.QtCore import Qt, QTimer, QSettings, QSize
from PySide6.QtGui import (
    QAction, QKeySequence, QColor, QPen, QBrush, QShortcut, QImage,
)

from doxyedit.models import Project, PLATFORMS, TAG_ALL, TAG_SHORTCUTS, toggle_tags
from doxyedit.canvas import CanvasScene, CanvasView, Tool, EditableTextItem, TagItem
from doxyedit.browser import AssetBrowser, IMAGE_EXTS
from doxyedit.themes import THEMES, DEFAULT_THEME, generate_stylesheet, Theme
from doxyedit.censor import CensorEditor
from doxyedit.platforms import PlatformPanel
from doxyedit.tagpanel import TagPanel
from doxyedit.exporter import export_project
from doxyedit.preview import ImagePreviewDialog
from doxyedit.tray import WorkTray
from doxyedit.project import save_project, load_project, export_markdown, import_markdown

AUTOSAVE_INTERVAL_MS = 30_000


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DoxyEdit")
        self.resize(1400, 900)
        # Restore window geometry
        self._settings_early = QSettings("DoxyEdit", "DoxyEdit")
        w = self._settings_early.value("window_width", 1400, type=int)
        h = self._settings_early.value("window_height", 900, type=int)
        x = self._settings_early.value("window_x", -1, type=int)
        y = self._settings_early.value("window_y", -1, type=int)
        self.resize(w, h)
        if x >= 0 and y >= 0:
            self.move(x, y)
        self._project_path = None
        self.project = Project(name="Untitled")
        self._settings = QSettings("DoxyEdit", "DoxyEdit")
        self._current_theme_id = self._settings.value("theme", DEFAULT_THEME)
        self._apply_theme(self._current_theme_id)

        # --- Main layout: tabs + tray splitter ---
        self.tabs = QTabWidget()
        self.work_tray = WorkTray()
        self._tray_open = False
        self.work_tray._content.hide()
        self.work_tray.setMaximumWidth(16)
        self.work_tray.setMinimumWidth(16)

        self._main_split = QSplitter(Qt.Orientation.Horizontal)
        self._main_split.addWidget(self.tabs)
        self._main_split.addWidget(self.work_tray)
        self._main_split.setStretchFactor(0, 1)
        self._main_split.setStretchFactor(1, 0)
        self.setCentralWidget(self._main_split)

        # Tab 1: Left Sidebar (tags+info) | Asset Browser grid
        self.browser = AssetBrowser(self.project)
        self.tag_panel = TagPanel()
        self.tag_panel.setMinimumWidth(220)
        self.tag_panel.setMaximumWidth(400)
        self.tag_panel.tags_changed.connect(self._on_data_changed)
        self.tag_panel.tag_deleted.connect(self._on_tag_deleted)
        self.tag_panel.tag_renamed.connect(self._on_tag_renamed)
        self.tag_panel.shortcut_changed.connect(self._on_shortcut_changed)
        self.tag_panel.hidden_changed.connect(self._on_hidden_changed)
        self.tag_panel.filter_by_eye.connect(self._on_eye_filter)

        self.work_tray.asset_selected.connect(self._on_asset_selected)
        self.work_tray.asset_preview.connect(self._on_asset_preview)
        self.work_tray.toggle_requested.connect(self._toggle_work_tray)

        self._browse_split = QSplitter(Qt.Orientation.Horizontal)
        self._browse_split.addWidget(self.tag_panel)
        self._browse_split.addWidget(self.browser)
        self._browse_split.setStretchFactor(0, 0)
        self._browse_split.setStretchFactor(1, 1)
        saved_split = self._settings_early.value("splitter_sizes", None)
        if saved_split:
            sizes = [int(s) for s in saved_split]
            self._browse_split.setSizes(sizes[:2] if len(sizes) >= 2 else [260, 1000])
        else:
            self._browse_split.setSizes([260, 1000])
        self.tabs.addTab(self._browse_split, "Assets")

        # Tab 2: Canvas Editor
        self.scene = CanvasScene()
        self.view = CanvasView(self.scene)
        self.tabs.addTab(self.view, "Canvas")

        # Tab 3: Censor Editor
        self.censor_editor = CensorEditor()
        self.tabs.addTab(self.censor_editor, "Censor")

        # Tab 4: Platforms
        self.platform_panel = PlatformPanel(self.project)
        self.tabs.addTab(self.platform_panel, "Platforms")

        # --- Signals ---
        self.browser.asset_selected.connect(self._on_asset_selected)
        self.browser.asset_preview.connect(self._on_asset_preview)
        self.browser.asset_to_canvas.connect(self._send_to_canvas)
        self.browser.asset_to_censor.connect(self._send_to_censor)
        self.browser.selection_changed.connect(self._on_selection_changed)
        self.browser.folder_opened.connect(self._add_recent_folder)
        self.browser.thumb_loaded.connect(self._on_thumb_for_tray)
        self.browser.asset_to_tray.connect(self._send_single_to_tray)
        self.browser.tags_modified.connect(self._on_tags_modified)

        # --- Toolbar & menu ---
        self._build_toolbar()
        self._build_menu()
        self._setup_tag_shortcuts()

        # --- Status bar with progress ---
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimumWidth(250)
        self._progress_bar.setMaximumWidth(400)
        self._progress_bar.setFixedHeight(16)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setVisible(False)
        self.status.addPermanentWidget(self._progress_bar)

        self._progress_label = QLabel()
        self._progress_label.setStyleSheet("padding-right: 12px;")
        self.status.addPermanentWidget(self._progress_label)
        self._update_progress()
        self.status.showMessage("Ready — open a folder or drag images in")

        # --- Auto-save timer ---
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(AUTOSAVE_INTERVAL_MS)
        self._dirty = False

        # --- Progress update timer ---
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._update_progress)
        self._progress_timer.start(2000)

        # --- Restore saved state ---
        saved_gen = int(self._settings.value("thumb_gen_size", 512))
        from doxyedit import browser
        browser.THUMB_GEN_SIZE = saved_gen

        saved_font = int(self._settings.value("font_size", 12))
        if saved_font != 12:
            self._theme.font_size = saved_font
            self._apply_font()

        # Auto-load last project, or re-open last folder if no project
        last_project = self._settings.value("last_project", "")
        if last_project and Path(last_project).exists():
            self.project = Project.load(last_project)
            self._rebind_project()
            self._project_path = last_project
            self.setWindowTitle(f"DoxyEdit — {Path(last_project).name}")
            self.status.showMessage(f"Restored: {Path(last_project).name}")
        else:
            last_folder = self._settings.value("last_folder", "")
            if last_folder and Path(last_folder).exists():
                n = self.browser.import_folder(last_folder)
                if n:
                    self.status.showMessage(f"Reopened folder: {Path(last_folder).name} ({n} images)")

    def _apply_theme(self, theme_id: str):
        from dataclasses import replace
        self._current_theme_id = theme_id
        base = THEMES.get(theme_id, THEMES[DEFAULT_THEME])
        self._theme = replace(base, font_size=getattr(self, '_theme', base).font_size)
        self.setStyleSheet(generate_stylesheet(self._theme))
        self._settings.setValue("theme", theme_id)
        # Match Windows title bar to theme
        self._update_title_bar_color()

    def _update_title_bar_color(self):
        try:
            import ctypes
            bg = self._theme.bg_raised
            r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
            hwnd = int(self.winId())
            color = r | (g << 8) | (b << 16)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(ctypes.c_int(color)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass

    def _font_increase(self):
        self._theme.font_size = min(24, self._theme.font_size + 1)
        self._apply_font()

    def _font_decrease(self):
        self._theme.font_size = max(8, self._theme.font_size - 1)
        self._apply_font()

    def _font_reset(self):
        self._theme.font_size = 12
        self._apply_font()

    def _set_hover_size(self, pct: int):
        self.browser._hover_size_pct = pct
        self._settings.setValue("hover_size_pct", pct)
        self.status.showMessage(f"Hover preview: {pct}% of thumbnail size", 2000)

    def _set_thumb_gen_size(self, size: int):
        from doxyedit import browser
        browser.THUMB_GEN_SIZE = size
        self._settings.setValue("thumb_gen_size", size)
        self.status.showMessage(f"Thumbnail quality: {size}px (recache with F5)", 3000)

    def _apply_font(self):
        fs = self._theme.font_size
        self.setStyleSheet(generate_stylesheet(self._theme))
        self.browser.update_font_size(fs)
        self._settings.setValue("font_size", fs)
        self.status.showMessage(f"Font size: {fs}px", 2000)

    def _build_toolbar(self):
        # Left toolbar — general app actions, always visible
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)

        # Navigation
        tb.addAction(QAction("Assets", self, triggered=lambda: self.tabs.setCurrentIndex(0)))
        tb.addAction(QAction("Canvas", self, triggered=lambda: self.tabs.setCurrentIndex(1)))
        tb.addAction(QAction("Censor", self, triggered=lambda: self.tabs.setCurrentIndex(2)))
        tb.addAction(QAction("Platforms", self, triggered=lambda: self.tabs.setCurrentIndex(3)))
        tb.addSeparator()

        # File ops
        tb.addAction(QAction("Open", self, triggered=self._open_project))
        tb.addAction(QAction("Save", self, triggered=self._save_project))
        tb.addSeparator()

        # Tray toggle
        self._tray_btn = QAction("Tray", self)
        self._tray_btn.setCheckable(True)
        self._tray_btn.setChecked(False)
        self._tray_btn.triggered.connect(lambda checked: self._toggle_work_tray())
        tb.addAction(self._tray_btn)
        tb.addSeparator()

        # Asset ops
        tb.addAction(QAction("+ Folder", self, triggered=lambda: self.browser.open_folder_dialog()))
        tb.addAction(QAction("+ Files", self, triggered=lambda: self.browser.add_images_dialog()))
        tb.addSeparator()

        # Canvas tools (active when on Canvas tab)
        tools = [
            ("Select", Tool.SELECT, "V"),
            ("Text", Tool.TEXT, "T"),
            ("Line", Tool.LINE, "L"),
            ("Box", Tool.BOX, "B"),
            ("Marker", Tool.TAG, "G"),
        ]
        self._tool_actions = []
        for name, tool, shortcut in tools:
            action = QAction(name, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, t=tool: self._set_tool(t))
            tb.addAction(action)
            self._tool_actions.append((action, tool))
        self._tool_actions[0][0].setChecked(True)
        tb.addSeparator()

        tb.addAction(QAction("Delete", self, shortcut=QKeySequence("Delete"),
                     triggered=self._handle_delete))
        tb.addAction(QAction("Color", self, triggered=self._change_color))

    def _build_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        file_menu.addAction("&New Project", self._new_project, QKeySequence("Ctrl+N"))
        file_menu.addAction("&Open Project...", self._open_project, QKeySequence("Ctrl+O"))
        file_menu.addAction("&Save Project", self._save_project, QKeySequence("Ctrl+S"))
        file_menu.addAction("Save Project &As...", self._save_project_as, QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()

        # Recent projects submenu
        self._recent_projects_menu = file_menu.addMenu("Recent Projects")
        self._recent_folders_menu = file_menu.addMenu("Recent Folders")
        self._rebuild_recent_menus()
        file_menu.addSeparator()

        file_menu.addAction("Import &Markdown...", self._import_md)
        file_menu.addAction("Export Markdown...", self._export_md)
        file_menu.addSeparator()
        file_menu.addAction("&Export All Platforms...", self._export_all, QKeySequence("Ctrl+E"))
        file_menu.addSeparator()
        file_menu.addAction("Paste Image (Ctrl+V)", self._paste_from_clipboard, QKeySequence("Ctrl+V"))
        file_menu.addSeparator()
        file_menu.addAction("Reset All Tags (fresh start)", self._reset_all_tags)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close, QKeySequence("Alt+F4"))

        # Edit menu
        edit_menu = menu.addMenu("&Edit")
        edit_menu.addAction("Select &All", self._select_all, QKeySequence("Ctrl+A"))
        edit_menu.addAction("Select &None", self._select_none, QKeySequence("Ctrl+D"))
        edit_menu.addAction("&Invert Selection", self._invert_selection)
        edit_menu.addSeparator()
        edit_menu.addAction("&Delete Selected (Ignore)", self._handle_delete, QKeySequence("Delete"))
        edit_menu.addAction("&Remove from Project", self._remove_selected)
        edit_menu.addSeparator()
        edit_menu.addAction("Star Selected", lambda: self._batch_star(1))
        edit_menu.addAction("Unstar Selected", lambda: self._batch_star(0))
        edit_menu.addSeparator()
        edit_menu.addAction("Clear Tags on Selected", self._clear_tags_selected)
        edit_menu.addAction("Add Tag to Selected...", self._add_tag_to_selected)

        # Tools menu
        tools_menu = menu.addMenu("&Tools")
        tools_menu.addAction("&Refresh Thumbnails", self._refresh_thumbs, QKeySequence("F5"))
        tools_menu.addAction("Rebuild Tag Bar", lambda: self.browser.rebuild_tag_bar())
        tools_menu.addSeparator()
        tools_menu.addAction("Clear Thumbnail Cache", self._clear_thumb_cache)
        tools_menu.addSeparator()
        tools_menu.addAction("Project &Summary (CLI)", self._show_summary)
        tools_menu.addAction("Show Project File...", self._show_project_file)
        tools_menu.addSeparator()
        tools_menu.addAction("Set Cache Location...", self._set_cache_location)
        tools_menu.addAction("Open Cache Folder", self._open_cache_folder)

        # View menu
        view_menu = menu.addMenu("&View")
        self._toggle_tags_action = view_menu.addAction(
            "Hide Tag Panel", self._toggle_tag_panel, QKeySequence("Ctrl+L"))
        self._toggle_tray_action = view_menu.addAction(
            "Show Work Tray", self._toggle_work_tray, QKeySequence("Ctrl+T"))
        view_menu.addSeparator()
        view_menu.addAction("Increase Font Size", self._font_increase, QKeySequence("Ctrl+="))
        view_menu.addAction("Decrease Font Size", self._font_decrease, QKeySequence("Ctrl+-"))
        view_menu.addAction("Reset Font Size", self._font_reset, QKeySequence("Ctrl+0"))
        view_menu.addSeparator()
        gen_menu = view_menu.addMenu("Thumbnail Quality")
        for n in [128, 256, 512, 768, 1024]:
            gen_menu.addAction(f"{n}px", lambda size=n: self._set_thumb_gen_size(size))
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("Theme")
        for tid, theme in THEMES.items():
            theme_menu.addAction(theme.name, lambda t=tid: self._apply_theme(t))
        view_menu.addSeparator()
        hover_menu = view_menu.addMenu("Hover Preview Size")
        for pct in [125, 150, 200, 250, 300]:
            hover_menu.addAction(f"{pct}%", lambda p=pct: self._set_hover_size(p))
        view_menu.addSeparator()
        view_menu.addAction("Show All Hidden Tags", lambda: self.tag_panel._show_all_tags())
        view_menu.addAction("Refresh Grid", lambda: self.browser.refresh(), QKeySequence("F5"))

        # Help menu
        help_menu = menu.addMenu("&Help")
        help_menu.addAction("Keyboard Shortcuts", self._show_shortcuts)
        help_menu.addAction("About DoxyEdit", self._show_about)

    def _setup_tag_shortcuts(self):
        """Set up keyboard shortcuts for tagging — only active on Assets tab."""
        for key, tag_id in TAG_SHORTCUTS.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(
                lambda tid=tag_id: self._toggle_tag_shortcut(tid)
            )

    def _toggle_tag_shortcut(self, tag_id: str):
        # Only work when on the Assets tab
        if self.tabs.currentIndex() != 0:
            return
        # Don't trigger if search box has focus
        if self.browser.search_box.hasFocus():
            return
        assets = self.browser.get_selected_assets()
        if not assets:
            return
        added = toggle_tags(assets, tag_id)
        self.tag_panel.set_assets(assets)
        self._on_data_changed()
        if tag_id in self.browser._eye_hidden_tags:
            self.browser.refresh()
        preset = TAG_ALL.get(tag_id)
        label = preset.label if preset else tag_id
        action = "applied" if added else "removed"
        self.status.showMessage(f"Tag '{label}' {action} to {len(assets)} asset(s)", 2000)

    # --- Clipboard paste ---

    def _paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()

        # Try image data first
        if mime.hasImage():
            image = clipboard.image()
            if not image.isNull():
                tmp = Path(tempfile.gettempdir()) / "doxyedit_paste.png"
                image.save(str(tmp))
                from doxyedit.models import Asset
                asset = Asset(
                    id=f"pasted_{len(self.project.assets)}",
                    source_path=str(tmp),
                    source_folder="clipboard",
                )
                self.project.assets.append(asset)
                self.browser.refresh()
                self.status.showMessage("Pasted image from clipboard")
                return

        # Try file URLs
        if mime.hasUrls():
            files = []
            folders = []
            for u in mime.urls():
                p = u.toLocalFile()
                if Path(p).is_dir():
                    folders.append(p)
                elif Path(p).suffix.lower() in IMAGE_EXTS:
                    files.append(p)
            total = 0
            for folder in folders:
                total += self.browser.import_folder(folder)
            if files:
                total += self.browser.import_files(files)
            if total:
                self.status.showMessage(f"Pasted {total} image(s) from clipboard")
                return

        # Try plain text — might be file paths or folder paths (one per line)
        if mime.hasText():
            lines = [l.strip().strip('"') for l in mime.text().strip().splitlines() if l.strip()]
            files_to_add = []
            total = 0
            for line in lines:
                p = Path(line)
                if p.is_dir():
                    total += self.browser.import_folder(str(p))
                elif p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                    files_to_add.append(str(p))
            if files_to_add:
                total += self.browser.import_files(files_to_add)
            if total:
                self.status.showMessage(f"Pasted {total} image(s) from clipboard")
                return

        self.status.showMessage("No image or path in clipboard", 2000)

    # --- Progress counter ---

    def _update_progress(self):
        total = len(self.project.assets)
        if total == 0:
            self._progress_label.setText("")
            return
        tagged = starred = ignored = assigned = 0
        for a in self.project.assets:
            if a.tags:
                tagged += 1
            if a.starred > 0:
                starred += 1
            if "ignore" in a.tags:
                ignored += 1
            if a.assignments:
                assigned += 1

        parts = [f"{tagged}/{total} tagged"]
        if starred:
            parts.append(f"{starred} starred")
        if ignored:
            parts.append(f"{ignored} ignored")
        if assigned:
            parts.append(f"{assigned} assigned")

        self._progress_label.setText("  |  ".join(parts))

    # --- Progress bar ---

    def start_progress(self, label: str, total: int):
        """Show progress bar with a label and total count."""
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat(f"{label} %v/%m")
        self._progress_bar.setVisible(True)
        self.status.showMessage(label)
        QApplication.processEvents()

    def update_progress(self, value: int):
        """Update progress bar value."""
        self._progress_bar.setValue(value)
        if value % 10 == 0:
            QApplication.processEvents()

    def finish_progress(self, message: str = "Done"):
        """Hide progress bar and show completion message."""
        self._progress_bar.setVisible(False)
        self.status.showMessage(message, 3000)

    # --- Tag panel toggle ---

    def _toggle_tag_panel(self):
        if self.tag_panel.isVisible():
            self.tag_panel.hide()
            self._toggle_tags_action.setText("Show Tag Panel")
        else:
            self.tag_panel.show()
            self._toggle_tags_action.setText("Hide Tag Panel")

    # --- Recent files/folders ---

    def _get_recent(self, key: str) -> list[str]:
        val = self._settings.value(key, []) or []
        return val if isinstance(val, list) else [val]

    def _push_recent(self, key: str, path: str):
        recents = self._get_recent(key)
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        self._settings.setValue(key, recents[:10])
        self._rebuild_recent_menus()

    def _add_recent_project(self, path: str):
        self._push_recent("recent_projects", path)

    def _add_recent_folder(self, folder: str):
        self._push_recent("recent_folders", folder)

    def _rebuild_recent_menus(self):
        self._recent_projects_menu.clear()
        for p in self._get_recent("recent_projects"):
            if Path(p).exists():
                self._recent_projects_menu.addAction(
                    Path(p).name, lambda path=p: self._load_project_from(path))
        if self._recent_projects_menu.isEmpty():
            self._recent_projects_menu.addAction("(none)").setEnabled(False)

        self._recent_folders_menu.clear()
        for f in self._get_recent("recent_folders"):
            if Path(f).exists():
                self._recent_folders_menu.addAction(
                    Path(f).name, lambda folder=f: self._open_recent_folder(folder))
        if self._recent_folders_menu.isEmpty():
            self._recent_folders_menu.addAction("(none)").setEnabled(False)

    def _load_project_from(self, path: str):
        # Create backup before loading
        import shutil
        bak = path + ".bak"
        try:
            shutil.copy2(path, bak)
        except Exception:
            pass
        self.project = Project.load(path)
        self._rebind_project()
        self._project_path = path
        self._settings.setValue("last_project", path)
        self._add_recent_project(path)
        self.setWindowTitle(f"DoxyEdit — {Path(path).name}")
        self.status.showMessage(f"Opened {Path(path).name}")

    def _open_recent_folder(self, folder: str):
        n = self.browser.import_folder(folder)
        self._add_recent_folder(folder)
        self.status.showMessage(f"Opened folder: {Path(folder).name} ({n} images)")

    def _on_shortcut_changed(self, tag_id: str, key: str):
        """Register a new keyboard shortcut for a tag and save to project."""
        from doxyedit.models import TAG_SHORTCUTS
        # Remove any existing shortcut for this key
        for k, v in list(TAG_SHORTCUTS.items()):
            if v == tag_id:
                del TAG_SHORTCUTS[k]
        if key in TAG_SHORTCUTS:
            del TAG_SHORTCUTS[key]
        TAG_SHORTCUTS[key] = tag_id
        # Save to project immediately
        self.project.custom_shortcuts[key] = tag_id
        self._dirty = True
        if self._project_path:
            self.project.save(self._project_path)
        # Register the shortcut
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.activated.connect(lambda tid=tag_id: self._toggle_tag_shortcut(tid))
        self.status.showMessage(f"Shortcut '{key}' → {tag_id}", 2000)

    def _on_eye_filter(self, hidden_tag_ids: list):
        """Eye toggle — hide images that have any of these tags."""
        self.browser._eye_hidden_tags = set(hidden_tag_ids)
        self.project.eye_hidden_tags = hidden_tag_ids
        self._dirty = True
        self.browser.refresh()

    def _on_hidden_changed(self, hidden_list):
        self.project.hidden_tags = hidden_list
        self._dirty = True

    def _on_tags_modified(self):
        """Browser added/removed a custom tag — sync the side panel."""
        self.tag_panel.refresh_discovered_tags(self.project.assets, self.project)
        self._dirty = True

    def _toggle_work_tray(self):
        # Always keep the tray widget visible — just collapse/expand content
        if not self.work_tray.isVisible():
            self.work_tray.show()
        is_open = hasattr(self, '_tray_open') and self._tray_open
        if is_open:
            self._tray_open = False
            self.work_tray._content.hide()
            self.work_tray.setMaximumWidth(16)
            self.work_tray.setMinimumWidth(16)
            self.work_tray._handle.setText("\u25B6")  # ▶ closed
            self._toggle_tray_action.setText("Show Work Tray")
            self._tray_btn.setChecked(False)
        else:
            self._tray_open = True
            self.work_tray._content.show()
            self.work_tray.setMinimumWidth(150)
            self.work_tray.setMaximumWidth(400)
            self.work_tray._handle.setText("\u25C0")  # ◀ open
            sizes = self._main_split.sizes()
            if len(sizes) > 1 and sizes[1] < 150:
                sizes[1] = 200
                self._main_split.setSizes(sizes)
            self._toggle_tray_action.setText("Hide Work Tray")
            self._tray_btn.setChecked(True)

    def _send_to_tray(self):
        """Send selected assets to work tray."""
        assets = self.browser.get_selected_assets()
        if not assets:
            return
        if not self.work_tray.isVisible():
            self._toggle_work_tray()
        for a in assets:
            pm = self.browser._thumb_cache.get(a.id)
            self.work_tray.add_asset(a.id, a.name, pm, path=a.source_path)
        self.status.showMessage(f"Sent {len(assets)} to tray")

    def _on_thumb_for_tray(self, asset_id: str, pixmap):
        """Update tray thumbnail when thumb cache generates it."""
        self.work_tray.update_pixmap(asset_id, pixmap)

    def _send_single_to_tray(self, asset_id: str):
        asset = self.project.get_asset(asset_id)
        if asset:
            if not self.work_tray.isVisible():
                self._toggle_work_tray()
            pm = self.browser._thumb_cache.get(asset_id)
            self.work_tray.add_asset(asset_id, asset.name, pm, path=asset.source_path)

    # --- Tag management ---

    def _on_tag_deleted(self, tag_id: str):
        """Remove a tag from ALL assets in the project, not just selected."""
        for asset in self.project.assets:
            if tag_id in asset.tags:
                asset.tags.remove(tag_id)
        # Remove from custom tags if it's a custom one
        self.project.custom_tags = [
            ct for ct in self.project.custom_tags if ct.get("id") != tag_id
        ]
        self.browser.refresh()
        self._dirty = True
        self.status.showMessage(f"Deleted tag '{tag_id}' from all assets")

    def _on_tag_renamed(self, old_id: str, new_id: str, new_label: str):
        """Rename tag across ALL assets."""
        for asset in self.project.assets:
            if old_id in asset.tags:
                asset.tags.remove(old_id)
                if new_id not in asset.tags:
                    asset.tags.append(new_id)
        # Update custom tags
        for ct in self.project.custom_tags:
            if isinstance(ct, dict) and ct.get("id") == old_id:
                ct["id"] = new_id
                ct["label"] = new_label
        self.browser.rebuild_tag_bar()
        self.browser.refresh()
        self._dirty = True
        self.status.showMessage(f"Renamed tag '{old_id}' → '{new_label}'")

    def _reset_all_tags(self):
        """Nuke all tags from every asset — fresh start."""
        from PySide6.QtWidgets import QMessageBox
        n = len(self.project.assets)
        reply = QMessageBox.question(
            self, "Reset All Tags",
            f"Remove ALL tags from all {n} assets?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for asset in self.project.assets:
            asset.tags.clear()
        self.project.custom_tags.clear()
        self.tag_panel.set_assets([])
        self.browser.refresh()
        self._dirty = True
        self.status.showMessage(f"Cleared all tags from {n} assets")

    # --- Data flow ---

    def _on_data_changed(self):
        self._dirty = True
        self._update_progress()

    def _on_asset_selected(self, asset_id: str):
        asset = self.project.get_asset(asset_id)
        if asset:
            self.censor_editor.load_asset(asset)
            self.tag_panel.set_assets([asset])
            name = Path(asset.source_path).name
            n_tags = len(asset.tags)
            tag_hint = f" | {n_tags} tags" if n_tags else " | press 1-9 to tag, or use panel ->"
            self.status.showMessage(f"Selected: {name}{tag_hint}")

    def _on_asset_preview(self, asset_id: str):
        asset = self.project.get_asset(asset_id)
        if asset:
            dlg = ImagePreviewDialog(asset.source_path, asset=asset, parent=self)
            dlg.exec()

    def _send_to_canvas(self, asset_id: str):
        """Ctrl+click — load image onto canvas and switch to Canvas tab."""
        asset = self.project.get_asset(asset_id)
        if asset:
            self.scene.add_image(asset.source_path)
            self.tabs.setCurrentWidget(self.view)
            self.status.showMessage(f"Sent to canvas: {Path(asset.source_path).name}")

    def _send_to_censor(self, asset_id: str):
        """Alt+click — load image into censor editor and switch to Censor tab."""
        asset = self.project.get_asset(asset_id)
        if asset:
            self.censor_editor.load_asset(asset)
            self.tabs.setCurrentWidget(self.censor_editor)
            self.status.showMessage(f"Sent to censor: {Path(asset.source_path).name}")

    def _on_selection_changed(self, asset_ids: list):
        assets = [a for a in self.project.assets if a.id in asset_ids]
        self.tag_panel.set_assets(assets)
        n = len(assets)
        if n == 0:
            self.status.showMessage("No selection")
        elif n == 1:
            name = Path(assets[0].source_path).name
            self.status.showMessage(f"Selected: {name} | press 1-9 to tag")
        else:
            self.status.showMessage(f"{n} selected — press 1-9 to batch tag, Ctrl+click to add/remove")

    # --- Canvas tools ---

    def _set_tool(self, tool: Tool):
        self.scene.set_tool(tool)
        for action, t in self._tool_actions:
            action.setChecked(t == tool)
        self.status.showMessage(f"Tool: {tool.name}")

    def _add_image_to_canvas(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Add Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.svg);;All Files (*)"
        )
        if path:
            self.scene.add_image(path)
            self.tabs.setCurrentWidget(self.view)
            self.status.showMessage(f"Added to canvas: {Path(path).name}")

    def _handle_delete(self):
        """Delete key — context-aware. Assets tab: soft-delete. Canvas: remove items."""
        if self.tabs.currentIndex() == 0:
            # Assets tab — tag selected as "ignore" (soft delete)
            assets = self.browser.get_selected_assets()
            if not assets:
                return
            for a in assets:
                if "ignore" not in a.tags:
                    a.tags.append("ignore")
            self.browser.refresh()
            self._dirty = True
            n = len(assets)
            self.status.showMessage(f"Marked {n} asset(s) as ignored (Delete)")
        else:
            # Canvas/other tabs — remove selected items
            for item in self.scene.selectedItems():
                self.scene.removeItem(item)
            self.status.showMessage("Deleted selected items")

    def _select_all(self):
        if self.tabs.currentIndex() == 0:
            self.browser._list_view.selectAll()

    def _select_none(self):
        if self.tabs.currentIndex() == 0:
            self.browser._list_view.clearSelection()

    def _invert_selection(self):
        if self.tabs.currentIndex() != 0:
            return
        model = self.browser._model
        sel = self.browser._list_view.selectionModel()
        for i in range(model.rowCount()):
            idx = model.index(i)
            sel.select(idx, sel.SelectionFlag.Toggle)

    def _remove_selected(self):
        assets = self.browser.get_selected_assets()
        if not assets:
            return
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, "Remove",
            f"Remove {len(assets)} asset(s) from project?\n(Files are NOT deleted from disk)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            ids = {a.id for a in assets}
            self.project.assets = [a for a in self.project.assets if a.id not in ids]
            self.browser._selected_ids -= ids
            self.browser.refresh()
            self._dirty = True
            self.status.showMessage(f"Removed {len(assets)} asset(s)")

    def _batch_star(self, value: int):
        for a in self.browser.get_selected_assets():
            a.starred = value
        self.browser.refresh()
        self._dirty = True

    def _clear_tags_selected(self):
        assets = self.browser.get_selected_assets()
        for a in assets:
            a.tags.clear()
        self.tag_panel.set_assets(assets)
        self._dirty = True
        self.status.showMessage(f"Cleared tags on {len(assets)} asset(s)")

    def _add_tag_to_selected(self):
        from PySide6.QtWidgets import QInputDialog
        tag, ok = QInputDialog.getText(self, "Add Tag", "Tag to add to selected:")
        if not ok or not tag.strip():
            return
        tag_id = tag.strip().lower().replace(" ", "_")
        assets = self.browser.get_selected_assets()
        for a in assets:
            if tag_id not in a.tags:
                a.tags.append(tag_id)
        self._dirty = True
        self.status.showMessage(f"Added '{tag_id}' to {len(assets)} asset(s)")

    def _refresh_thumbs(self):
        self.browser._thumb_cache.clear()
        self.browser._delegate.invalidate_cache()
        self.browser.refresh()
        self.status.showMessage("Recaching thumbnails...", 2000)

    def _clear_thumb_cache(self):
        import shutil
        cache_dir = Path.home() / ".doxyedit" / "thumbcache"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        self.browser._thumb_cache.clear()
        self.browser._delegate.invalidate_cache()
        self.browser.refresh()
        self.status.showMessage("Thumbnail cache cleared")

    def _show_summary(self):
        s = self.project.summary()
        total = s.get("total_assets", 0)
        starred = s.get("starred", 0)
        censored = s.get("needs_censor", 0)
        tagged = sum(1 for a in self.project.assets if a.tags)
        ignored = sum(1 for a in self.project.assets if "ignore" in a.tags)
        customs = len(self.project.custom_tags)

        lines = [
            f"Assets: {total}  |  Tagged: {tagged}  |  Starred: {starred}  |  Ignored: {ignored}",
            f"Censored: {censored}  |  Custom Tags: {customs}",
            "",
        ]
        for pid, info in s.get("platforms", {}).items():
            name = info["name"]
            assigned = info["assigned"]
            posted = info["posted"]
            slots = info["slots_total"]
            lines.append(f"{name}: {assigned}/{slots} slots filled, {posted} posted")

        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Project Summary", "\n".join(lines))

    def _show_project_file(self):
        if self._project_path:
            import subprocess
            subprocess.Popen(f'notepad "{self._project_path}"')
        else:
            self.status.showMessage("Save the project first", 2000)

    def _set_cache_location(self):
        current = self._settings.value("cache_dir", str(Path.home() / ".doxyedit" / "thumbcache"))
        folder = QFileDialog.getExistingDirectory(self, "Set Cache Location", current)
        if folder:
            self._settings.setValue("cache_dir", folder)
            self.status.showMessage(f"Cache location set to: {folder} (restart to apply)")

    def _open_cache_folder(self):
        import subprocess
        cache_dir = self._settings.value("cache_dir", str(Path.home() / ".doxyedit" / "thumbcache"))
        subprocess.Popen(f'explorer "{cache_dir}"')

    def _show_shortcuts(self):
        from PySide6.QtWidgets import QMessageBox
        shortcuts = """
Ctrl+S — Save Project
Ctrl+O — Open Project
Ctrl+N — New Project
Ctrl+E — Export All Platforms
Ctrl+V — Paste Image/Path
Ctrl+A — Select All
Ctrl+D — Deselect All
Ctrl+T — Toggle Tag Panel
Ctrl+= — Increase Font
Ctrl+- — Decrease Font
Ctrl+0 — Reset Font
Ctrl+Scroll — Zoom Thumbnails
Delete — Soft-delete (tag as ignore)
F5 — Refresh Thumbnails

Preview:
N — Add Note
V — Toggle Notes Visible
Ctrl+0 — Fit to View
Esc — Close

Tags (Assets tab):
1-8 — Toggle content tags
0 — Toggle Ignore
Alt+Click tag — Search by tag
"""
        from doxyedit.models import TAG_SHORTCUTS
        for key, tid in self.project.custom_shortcuts.items():
            shortcuts += f"{key} — {tid}\n"
        QMessageBox.information(self, "Keyboard Shortcuts", shortcuts.strip())

    def _show_about(self):
        from PySide6.QtWidgets import QMessageBox
        from doxyedit import __version__
        QMessageBox.about(self, "About DoxyEdit",
            f"DoxyEdit v{__version__}\n\n"
            "Art Asset Manager\n"
            "Browse, tag, organize, and export art assets\n"
            "across multiple platforms.\n\n"
            "Built with PySide6 + PIL + psd-tools")

    def _change_color(self):
        items = self.scene.selectedItems()
        if not items:
            self.status.showMessage("Select an item first")
            return
        color = QColorDialog.getColor(QColor("#4fc3f7"), self, "Pick Color")
        if not color.isValid():
            return
        for item in items:
            if isinstance(item, QGraphicsTextItem):
                item.setDefaultTextColor(color)
            elif isinstance(item, (QGraphicsRectItem, QGraphicsLineItem)):
                pen = item.pen()
                pen.setColor(color)
                item.setPen(pen)
                if isinstance(item, QGraphicsRectItem) and not isinstance(item, TagItem):
                    item.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 30)))

    # --- Auto-save ---

    def _autosave(self):
        if self._dirty and self._project_path:
            self.project.save(self._project_path)
            self._dirty = False
            self.status.showMessage("Auto-saved", 3000)

    # --- Project file ops ---

    def _new_project(self):
        self.project = Project(name="Untitled")
        self.scene.clear()
        self._rebind_project()
        self._project_path = None
        self.setWindowTitle("DoxyEdit")
        self.status.showMessage("New project")

    def _rebind_project(self):
        self.browser.project = self.project
        self.browser.rebuild_tag_bar()
        self.browser.refresh()
        self.platform_panel.project = self.project
        self.platform_panel.refresh()
        self.tag_panel.set_assets([])
        self.tag_panel.refresh_discovered_tags(self.project.assets, self.project)
        self._update_progress()
        # Restore work tray
        if self.project.tray_items:
            self.work_tray.load_state(self.project.tray_items, self.project)
            if self.project.tray_items:
                self.work_tray.show()
                self._toggle_tray_action.setText("Hide Work Tray")

        # Restore sort mode
        if self.project.sort_mode:
            idx = self.browser.sort_combo.findText(self.project.sort_mode)
            if idx >= 0:
                self.browser.sort_combo.setCurrentIndex(idx)

        # Restore eye-hidden tags (grid filter)
        if self.project.eye_hidden_tags:
            self.browser._eye_hidden_tags = set(self.project.eye_hidden_tags)
            self.tag_panel._eye_hidden = set(self.project.eye_hidden_tags)
            # Update eye buttons on tag rows
            for tag_id in self.project.eye_hidden_tags:
                if tag_id in self.tag_panel._rows:
                    row = self.tag_panel._rows[tag_id]
                    row.eye_btn.blockSignals(True)
                    row.eye_btn.setChecked(False)
                    row.eye_btn.setText("\u25CB")
                    row.eye_btn.blockSignals(False)
            self.browser.refresh()

        # Restore hidden tags
        if self.project.hidden_tags:
            self.tag_panel.load_hidden_tags(self.project.hidden_tags)
        # Restore project-specific shortcuts
        from doxyedit.models import TAG_SHORTCUTS
        for key, tag_id in self.project.custom_shortcuts.items():
            TAG_SHORTCUTS[key] = tag_id
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda tid=tag_id: self._toggle_tag_shortcut(tid))
            # Update label on tag row if it exists
            if tag_id in self.tag_panel._rows:
                row = self.tag_panel._rows[tag_id]
                row.checkbox.setText(f"{row.tag.label} [{key}]")

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            "DoxyEdit Projects (*.doxyproj.json);;All Files (*)"
        )
        if path:
            self._load_project_from(path)

    def _save_project(self):
        if self._project_path:
            # Sync all UI state to project before saving
            self.project.sort_mode = self.browser.sort_combo.currentText()
            self.project.eye_hidden_tags = list(self.browser._eye_hidden_tags)
            self.project.hidden_tags = list(self.tag_panel._hidden_tags)
            self.project.tray_items = self.work_tray.save_state()
            self.project.save(self._project_path)
            self._dirty = False
            self._settings.setValue("last_project", self._project_path)
            self._add_recent_project(self._project_path)
            self.status.showMessage(f"Saved {Path(self._project_path).name}")
            # Brief green flash on status bar
            self.status.setStyleSheet(
                f"QStatusBar {{ background: {self._theme.accent}; color: {self._theme.text_on_accent}; }}")
            QTimer.singleShot(800, lambda: self.status.setStyleSheet(""))
        else:
            self._save_project_as()

    def _save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "project.doxyproj.json",
            "DoxyEdit Projects (*.doxyproj.json);;All Files (*)"
        )
        if path:
            self.project.save(path)
            self._project_path = path
            self._dirty = False
            self._settings.setValue("last_project", path)
            self._add_recent_project(path)
            self.setWindowTitle(f"DoxyEdit — {Path(path).name}")
            self.status.showMessage(f"Saved {Path(path).name}")

    def _import_md(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Markdown", "", "Markdown (*.md);;All Files (*)"
        )
        if path:
            import_markdown(self.scene, path)
            self.tabs.setCurrentWidget(self.view)
            self.status.showMessage(f"Imported {Path(path).name}")

    def _export_md(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Markdown", "export.md", "Markdown (*.md);;All Files (*)"
        )
        if path:
            export_markdown(self.scene, path)
            self.status.showMessage(f"Exported to {Path(path).name}")

    def _export_all(self):
        folder = QFileDialog.getExistingDirectory(self, "Export All Platforms To...")
        if not folder:
            return
        manifest = export_project(self.project, folder)
        n_exported = len(manifest["exports"])
        n_errors = len(manifest["errors"])
        msg = f"Exported {n_exported} files"
        if n_errors:
            msg += f" ({n_errors} errors)"
        self.status.showMessage(msg)
        QMessageBox.information(
            self, "Export Complete",
            f"Exported {n_exported} files to {folder}\n"
            f"Manifest saved to export_manifest.json\n"
            f"Errors: {n_errors}"
        )

    def closeEvent(self, event):
        if self._dirty and self._project_path:
            self.project.save(self._project_path)
        # Save splitter and window position/size
        self._settings.setValue("splitter_sizes", self._browse_split.sizes())
        self._settings.setValue("window_width", self.width())
        self._settings.setValue("window_height", self.height())
        self._settings.setValue("window_x", self.x())
        self._settings.setValue("window_y", self.y())
        self.browser.shutdown()
        event.accept()
