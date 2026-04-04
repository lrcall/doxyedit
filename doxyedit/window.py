"""Main application window — tabbed layout with all panels."""
import tempfile
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QFileDialog, QStatusBar,
    QGraphicsTextItem, QGraphicsRectItem, QGraphicsLineItem,
    QGraphicsPixmapItem, QColorDialog, QMessageBox, QSplitter,
    QWidget, QVBoxLayout, QApplication, QLabel,
)
from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtGui import (
    QAction, QKeySequence, QColor, QPen, QBrush, QShortcut, QImage,
)

from doxyedit.models import Project, PLATFORMS, TAG_PRESETS, TAG_SHORTCUTS, toggle_tags
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
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: #1e1e1e; }
            QTabBar::tab {
                background: #252526; color: #888; border: none;
                padding: 8px 20px; font-size: 12px; font-family: "Segoe UI";
                min-width: 100px;
            }
            QTabBar::tab:selected { background: #1e1e1e; color: #fff; }
            QTabBar::tab:hover { color: #ccc; }
        """)
        self.setCentralWidget(self.tabs)

        # Tab 1: Asset Browser + Tag Panel (splitter)
        self.browser = AssetBrowser(self.project)
        self.tag_panel = TagPanel()
        self.tag_panel.setMinimumWidth(200)
        self.tag_panel.setMaximumWidth(400)
        self.tag_panel.tags_changed.connect(self._on_data_changed)

        self._browse_split = QSplitter(Qt.Orientation.Horizontal)
        self._browse_split.addWidget(self.browser)
        self._browse_split.addWidget(self.tag_panel)
        self._browse_split.setStretchFactor(0, 1)
        self._browse_split.setStretchFactor(1, 0)
        self._browse_split.setSizes([900, 280])
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

        # --- Toolbar & menu ---
        self._build_toolbar()
        self._build_menu()
        self._setup_tag_shortcuts()

        # --- Status bar with progress ---
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._progress_label = QLabel()
        self._progress_label.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 11px; padding-right: 12px;")
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
                n = self.browser._import_folder(last_folder)
                if n:
                    self.status.showMessage(f"Reopened folder: {Path(last_folder).name} ({n} images)")

    def _apply_theme(self, theme_id: str):
        self._current_theme_id = theme_id
        theme = THEMES.get(theme_id, THEMES[DEFAULT_THEME])
        self._theme = theme
        self.setStyleSheet(generate_stylesheet(theme))
        QSettings("DoxyEdit", "DoxyEdit").setValue("theme", theme_id)

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
        QSettings("DoxyEdit", "DoxyEdit").setValue("font_size", fs)
        self.status.showMessage(f"Font size: {fs}px", 2000)

    def _build_toolbar(self):
        tb = QToolBar("Tools")
        tb.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)

        tools = [
            ("Select", Tool.SELECT, "V"),
            ("Text", Tool.TEXT, "T"),
            ("Line", Tool.LINE, "L"),
            ("Box", Tool.BOX, "B"),
            ("Tag", Tool.TAG, "G"),
        ]
        self._tool_actions = []
        for name, tool, shortcut in tools:
            action = QAction(name, self)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda checked, t=tool: self._set_tool(t))
            tb.addAction(action)
            self._tool_actions.append((action, tool))

        self._tool_actions[0][0].setChecked(True)

        tb.addSeparator()

        add_img = QAction("+ Image", self)
        add_img.setShortcut(QKeySequence("I"))
        add_img.triggered.connect(self._add_image_to_canvas)
        tb.addAction(add_img)

        del_action = QAction("Delete", self)
        del_action.setShortcut(QKeySequence("Delete"))
        del_action.triggered.connect(self._delete_selected)
        tb.addAction(del_action)

        color_action = QAction("Color", self)
        color_action.triggered.connect(self._change_color)
        tb.addAction(color_action)

    def _build_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        file_menu.addAction("&New Project", self._new_project, QKeySequence("Ctrl+N"))
        file_menu.addAction("&Open Project...", self._open_project, QKeySequence("Ctrl+O"))
        file_menu.addAction("&Save Project", self._save_project, QKeySequence("Ctrl+S"))
        file_menu.addAction("Save Project &As...", self._save_project_as, QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()
        file_menu.addAction("Import &Markdown...", self._import_md)
        file_menu.addAction("Export Markdown...", self._export_md)
        file_menu.addSeparator()
        file_menu.addAction("&Export All Platforms...", self._export_all, QKeySequence("Ctrl+E"))
        file_menu.addSeparator()
        file_menu.addAction("Paste Image (Ctrl+V)", self._paste_from_clipboard, QKeySequence("Ctrl+V"))

        # View menu
        view_menu = menu.addMenu("&View")
        self._toggle_tags_action = view_menu.addAction(
            "Hide Tag Panel", self._toggle_tag_panel, QKeySequence("Ctrl+T"))
        view_menu.addSeparator()
        view_menu.addAction("Increase Font Size", self._font_increase, QKeySequence("Ctrl+="))
        view_menu.addAction("Decrease Font Size", self._font_decrease, QKeySequence("Ctrl+-"))
        view_menu.addAction("Reset Font Size", self._font_reset, QKeySequence("Ctrl+0"))
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
        preset = TAG_PRESETS.get(tag_id)
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
            files = [u.toLocalFile() for u in mime.urls()
                     if Path(u.toLocalFile()).suffix.lower() in IMAGE_EXTS]
            if files:
                n = self.browser._import_files(files)
                self.status.showMessage(f"Pasted {n} image(s) from clipboard")
                return

        self.status.showMessage("No image in clipboard", 2000)

    # --- Progress counter ---

    def _update_progress(self):
        total = len(self.project.assets)
        if total == 0:
            self._progress_label.setText("")
            return
        tagged = sum(1 for a in self.project.assets if a.tags)
        starred = sum(1 for a in self.project.assets if a.starred > 0)
        ignored = sum(1 for a in self.project.assets if "ignore" in a.tags)
        assigned = sum(1 for a in self.project.assets if a.assignments)

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
            dlg = ImagePreviewDialog(asset.source_path, self)
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

    def _delete_selected(self):
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
        self.browser.refresh()
        self.platform_panel.project = self.project
        self.platform_panel.refresh()
        self.tag_panel.set_assets([])
        self._update_progress()

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            "DoxyEdit Projects (*.doxyproj.json);;All Files (*)"
        )
        if path:
            self.project = Project.load(path)
            self._rebind_project()
            self._project_path = path
            self._settings.setValue("last_project", path)
            self.setWindowTitle(f"DoxyEdit — {Path(path).name}")
            self.status.showMessage(f"Opened {Path(path).name}")

    def _save_project(self):
        if self._project_path:
            self.project.save(self._project_path)
            self._dirty = False
            self.status.showMessage(f"Saved {Path(self._project_path).name}")
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
