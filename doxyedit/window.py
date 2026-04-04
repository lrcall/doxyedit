"""Main application window — tabbed layout with all panels."""
import tempfile
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QFileDialog, QStatusBar,
    QGraphicsTextItem, QGraphicsRectItem, QGraphicsLineItem,
    QGraphicsPixmapItem, QColorDialog, QMessageBox, QSplitter,
    QWidget, QVBoxLayout, QApplication, QLabel,
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
from doxyedit.project import save_project, load_project, export_markdown, import_markdown

AUTOSAVE_INTERVAL_MS = 30_000


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DoxyEdit")
        self.resize(1400, 900)
        self._project_path = None
        self.project = Project(name="Untitled")
        self._settings = QSettings("DoxyEdit", "DoxyEdit")
        self._current_theme_id = self._settings.value("theme", DEFAULT_THEME)
        self._apply_theme(self._current_theme_id)

        # --- Tabs ---
        self.tabs = QTabWidget()
        # Tab styling inherited from theme
        self.setCentralWidget(self.tabs)

        # Tab 1: Left Sidebar (tags+info) | Asset Browser grid
        self.browser = AssetBrowser(self.project)
        self.tag_panel = TagPanel()
        self.tag_panel.setMinimumWidth(220)
        self.tag_panel.setMaximumWidth(400)
        self.tag_panel.tags_changed.connect(self._on_data_changed)
        self.tag_panel.tag_deleted.connect(self._on_tag_deleted)
        self.tag_panel.tag_renamed.connect(self._on_tag_renamed)
        self.tag_panel.shortcut_changed.connect(self._on_shortcut_changed)

        self._browse_split = QSplitter(Qt.Orientation.Horizontal)
        self._browse_split.addWidget(self.tag_panel)   # left side
        self._browse_split.addWidget(self.browser)     # right (main area)
        self._browse_split.setStretchFactor(0, 0)
        self._browse_split.setStretchFactor(1, 1)
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
        self.browser.tags_modified.connect(self._on_tags_modified)

        # --- Toolbar & menu ---
        self._build_toolbar()
        self._build_menu()
        self._setup_tag_shortcuts()

        # --- Status bar with progress ---
        self.status = QStatusBar()
        self.setStatusBar(self.status)
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
        tb.addAction(QAction("Open", self, shortcut=QKeySequence("Ctrl+O"),
                     triggered=self._open_project))
        tb.addAction(QAction("Save", self, shortcut=QKeySequence("Ctrl+S"),
                     triggered=self._save_project))
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

        # View menu
        view_menu = menu.addMenu("&View")
        self._toggle_tags_action = view_menu.addAction(
            "Hide Tag Panel", self._toggle_tag_panel, QKeySequence("Ctrl+T"))
        view_menu.addSeparator()
        view_menu.addAction("Increase Font Size", self._font_increase, QKeySequence("Ctrl+="))
        view_menu.addAction("Decrease Font Size", self._font_decrease, QKeySequence("Ctrl+-"))
        view_menu.addAction("Reset Font Size", self._font_reset, QKeySequence("Ctrl+0"))
        view_menu.addSeparator()
        page_menu = view_menu.addMenu("Thumbnails Per Page")
        for n in [50, 100, 150, 200, 300, 500]:
            page_menu.addAction(str(n), lambda size=n: self.browser.set_page_size(size))
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("Theme")
        for tid, theme in THEMES.items():
            theme_menu.addAction(theme.name, lambda t=tid: self._apply_theme(t))

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

        # Try plain text — might be a file path or folder path
        if mime.hasText():
            text = mime.text().strip().strip('"')
            p = Path(text)
            if p.is_dir():
                n = self.browser.import_folder(str(p))
                self.status.showMessage(f"Imported folder: {p.name} ({n} images)")
                return
            elif p.is_file():
                if p.suffix.lower() in IMAGE_EXTS:
                    n = self.browser.import_files([str(p)])
                    self.status.showMessage(f"Imported: {p.name}")
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
        """Register a new keyboard shortcut for a tag."""
        from doxyedit.models import TAG_SHORTCUTS
        # Remove any existing shortcut for this key
        for k, v in list(TAG_SHORTCUTS.items()):
            if v == tag_id:
                del TAG_SHORTCUTS[k]
        # Remove any tag that had this key
        if key in TAG_SHORTCUTS:
            del TAG_SHORTCUTS[key]
        TAG_SHORTCUTS[key] = tag_id
        # Register the shortcut
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.activated.connect(lambda tid=tag_id: self._toggle_tag_shortcut(tid))
        self.status.showMessage(f"Shortcut '{key}' → {tag_id}", 2000)

    def _on_tags_modified(self):
        """Browser added/removed a custom tag — sync the side panel."""
        self.tag_panel.refresh_discovered_tags(self.project.assets, self.project)
        self._dirty = True

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
        self.browser._rebuild_tag_bar()
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
        self.tag_panel.set_assets(self.tag_panel._assets)
        self.browser.refresh()
        self._dirty = True
        self.status.showMessage(f"Cleared all tags from {n} assets")

    # --- Data flow ---

    def _on_data_changed(self):
        self._dirty = True
        self._update_progress()
        self.browser.refresh()

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
        self.browser._rebuild_tag_bar()
        self.browser.refresh()
        self.platform_panel.project = self.project
        self.platform_panel.refresh()
        self.tag_panel.set_assets([])
        self.tag_panel.refresh_discovered_tags(self.project.assets, self.project)
        self._update_progress()

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            "DoxyEdit Projects (*.doxyproj.json);;All Files (*)"
        )
        if path:
            self._load_project_from(path)

    def _save_project(self):
        if self._project_path:
            self.project.save(self._project_path)
            self._dirty = False
            self._settings.setValue("last_project", self._project_path)
            self._add_recent_project(self._project_path)
            self.status.showMessage(f"Saved {Path(self._project_path).name}")
            # Brief green flash on status bar
            self.status.setStyleSheet("QStatusBar { background: rgba(80,180,80,0.8); }")
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
        self.browser.shutdown()
        event.accept()
