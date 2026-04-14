"""Main application window — tabbed layout with all panels."""
import html as _html
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QTabBar, QToolBar, QFileDialog, QStatusBar,
    QGraphicsTextItem, QGraphicsRectItem, QGraphicsLineItem,
    QGraphicsPixmapItem, QColorDialog, QMessageBox, QSplitter,
    QWidget, QVBoxLayout, QHBoxLayout, QApplication, QLabel, QProgressBar, QPushButton,
    QSizePolicy, QMenu,
)
from PySide6.QtCore import Qt, QTimer, QSettings, QSize, QUrl, QMimeData, QAbstractNativeEventFilter
from PySide6.QtGui import (
    QAction, QKeySequence, QColor, QPen, QBrush, QShortcut, QImage,
)

from doxyedit.models import Project, PLATFORMS, TAG_ALL, TAG_SHORTCUTS, TAG_SHORTCUTS_DEFAULT, toggle_tags
from doxyedit import windroptarget
from doxyedit.canvas import CanvasScene, CanvasView, Tool, EditableTextItem, TagItem
from doxyedit.browser import AssetBrowser, IMAGE_EXTS, THUMB_GEN_SIZE
from doxyedit.themes import THEMES, DEFAULT_THEME, generate_stylesheet, Theme
from doxyedit.censor import CensorEditor
from doxyedit.platforms import PlatformPanel
from doxyedit.timeline import TimelineStream
from doxyedit.calendar_pane import CalendarPane
from doxyedit.composer import PostComposer
from doxyedit.tagpanel import TagPanel
from doxyedit.exporter import export_project
from doxyedit.preview import ImagePreviewDialog, PreviewPane
from doxyedit.filebrowser import FileBrowserPanel
from PySide6.QtWidgets import QPlainTextEdit as _QPlainTextEdit


class _CenteredTextEdit(_QPlainTextEdit):
    """QPlainTextEdit — centering handled by QSS padding only.
    No viewport margin tricks. Scrollbar stays at widget edge."""
    pass
from doxyedit.infopanel import InfoPanel
from doxyedit.tray import WorkTray
from doxyedit.project import save_project, load_project
from doxyedit.stats import StatsPanel
from doxyedit.checklist import ChecklistPanel
from doxyedit.health import HealthPanel
from doxyedit.kanban import KanbanPanel

AUTOSAVE_INTERVAL_MS = 30_000


class _RemovableMenu(QMenu):
    """QMenu where right-clicking an item (with .data() set) removes it from the list."""
    def __init__(self, remove_cb, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._remove_cb = remove_cb

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            action = self.actionAt(event.pos())
            if action and action.data():
                self._remove_cb(action.data())
                self.close()
                return
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    _open_windows: list["MainWindow"] = []  # keep extra windows alive (prevent GC)

    def __init__(self, _skip_autoload: bool = False):
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
        _f = self._settings.value("font_size", 12, type=int)
        _cb = max(14, _f + 2)
        self._current_theme_id = self._settings.value("theme", DEFAULT_THEME)
        self._apply_theme(self._current_theme_id)

        # --- Project tabs (one per open project) ---
        self._project_slots: list[dict] = []   # [{project, path, label}]
        self._current_slot: int = -1

        # --- Project tab bar (above inner tabs) ---
        self._proj_tab_bar = QTabBar()
        self._proj_tab_bar.setTabsClosable(True)
        self._proj_tab_bar.setMovable(True)
        self._proj_tab_bar.setExpanding(False)
        self._proj_tab_bar.setStyleSheet(
            "QTabBar { background: transparent; }"
            "QTabBar::tab { padding: 4px 12px; }"
            "QTabBar::tab:selected { font-weight: bold; }"
        )
        self._proj_tab_bar.currentChanged.connect(self._on_proj_tab_changed)
        self._proj_tab_bar.tabCloseRequested.connect(self._close_proj_tab)
        self._proj_tab_bar.tabMoved.connect(self._on_proj_tab_moved)
        self._proj_tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._proj_tab_bar.customContextMenuRequested.connect(
            lambda pos: self._preset_context_menu(
                self._proj_tab_bar.tabAt(pos),
                self._proj_tab_bar.mapToGlobal(pos)))

        # + button to open a new folder tab
        self._new_tab_btn = QPushButton("+")
        self._new_tab_btn.setFixedSize(_cb, _cb)
        self._new_tab_btn.setToolTip("New tab — open project, folder, or new project (Ctrl+T)")
        self._new_tab_btn.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: bold; border-radius: 4px;"
            " background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);"
            " color: rgba(200,200,200,0.8); padding: 0; }"
            " QPushButton:hover { background: rgba(255,255,255,0.18);"
            " color: white; border-color: rgba(255,255,255,0.3); }"
            " QPushButton:pressed { background: rgba(255,255,255,0.25); }")
        self._new_tab_btn.clicked.connect(self._add_folder_preset_dialog)

        _proj_bar_widget = QWidget()
        _proj_bar_widget.setObjectName("proj_tab_bar_row")
        _proj_bar_row = QHBoxLayout(_proj_bar_widget)
        _proj_bar_row.setContentsMargins(0, 0, 0, 0)
        _proj_bar_row.setSpacing(2)
        _proj_bar_row.addWidget(self._proj_tab_bar, 1)
        _proj_bar_row.addWidget(self._new_tab_btn)

        # --- Main layout: tabs + tray splitter ---
        self.tabs = QTabWidget()
        self.work_tray = WorkTray()
        self._tray_open = False
        self._saved_tray_sizes = None
        self.work_tray.hide()

        self._main_split = QSplitter(Qt.Orientation.Horizontal)
        self._main_split.addWidget(self.tabs)
        self._main_split.addWidget(self.work_tray)
        self._main_split.setStretchFactor(0, 1)
        self._main_split.setStretchFactor(1, 0)

        _center = QWidget()
        _center_layout = QVBoxLayout(_center)
        _center_layout.setContentsMargins(0, 0, 0, 0)
        _center_layout.setSpacing(0)
        _center_layout.addWidget(_proj_bar_widget)
        _center_layout.addWidget(self._main_split, 1)
        self.setCentralWidget(_center)

        # Tab 1: Left Sidebar (tags+info) | Asset Browser grid
        self.browser = AssetBrowser(self.project)
        self.tag_panel = TagPanel()
        self.tag_panel.setMinimumWidth(220)
        self.tag_panel.setMaximumWidth(400)
        self.tag_panel.tags_changed.connect(self._on_data_changed)
        self.tag_panel.tags_changed.connect(lambda: self.browser.refresh())
        self.tag_panel.tag_deleted.connect(self._on_tag_deleted)
        self.tag_panel.tag_renamed.connect(self._on_tag_renamed)
        self.tag_panel.shortcut_changed.connect(self._on_shortcut_changed)
        self.tag_panel.hidden_changed.connect(self._on_hidden_changed)
        self.tag_panel.filter_by_eye.connect(self._on_eye_filter)
        self.tag_panel.select_all_with_tag.connect(self._select_all_with_tag)
        self.tag_panel.tag_color_changed.connect(self._on_tag_color_changed)
        self.tag_panel.tag_reordered.connect(self._on_tag_reordered)
        self.tag_panel.tag_section_changed.connect(self._on_tag_section_changed)
        self.tag_panel.batch_apply_tags.connect(self._on_batch_apply_tags)
        self.browser.tag_bar_toggled.connect(self._on_browser_tag_bar_toggled)
        self.browser.files_toggled.connect(self._on_files_btn_toggled)

        self.work_tray.asset_selected.connect(self._on_asset_selected)
        self.work_tray.asset_preview.connect(self._on_asset_preview)
        self.work_tray.toggle_requested.connect(self._toggle_work_tray)
        self.work_tray.tags_modified.connect(self._on_tags_modified)
        self.work_tray.pixmaps_needed.connect(self._feed_tray_pixmaps)

        self._browse_split = QSplitter(Qt.Orientation.Horizontal)
        # File browser (left, hidden by default)
        self._file_browser = FileBrowserPanel()
        self._file_browser.folder_selected.connect(self._on_file_browser_folder)
        self._file_browser.import_requested.connect(
            lambda f: self.browser.import_folder(f))
        self._file_browser.filter_cleared.connect(self._clear_file_browser_filter)
        self._file_browser.hide()
        self._browse_split.addWidget(self._file_browser)
        self._browse_split.addWidget(self.tag_panel)
        self._browse_split.addWidget(self.browser)
        # Docked preview pane (right side, initially hidden)
        self._preview_pane = PreviewPane()
        self._preview_pane.navigated.connect(self._navigate_to_asset_in_browser)
        self._preview_pane.popout_requested.connect(self._popout_preview)
        self._preview_pane.hide()
        self._browse_split.addWidget(self._preview_pane)
        # Info panel — inside tag panel's vertical splitter (below tags)
        self._info_panel = InfoPanel()
        self._info_panel.tags_modified.connect(self._on_tags_modified)
        self.tag_panel._tag_notes_split.addWidget(self._info_panel)
        # Move notes widget from tag panel to bottom of work tray (resizable via splitter)
        notes_w = self.tag_panel._tag_notes_split.widget(1)  # notes_widget
        if notes_w:
            # Replace the list in the tray content layout with a splitter: list + notes
            tray_layout = self.work_tray._content.layout()
            tray_layout.removeWidget(self.work_tray._list)
            _tray_list_notes = QSplitter(Qt.Orientation.Vertical)
            _tray_list_notes.addWidget(self.work_tray._list)
            _tray_list_notes.addWidget(notes_w)
            _tray_list_notes.setSizes([400, 100])
            _tray_list_notes.setStretchFactor(0, 3)
            _tray_list_notes.setStretchFactor(1, 0)
            tray_layout.addWidget(_tray_list_notes)
        self.tag_panel._tag_notes_split.setSizes([300, 200])
        self._browse_split.setStretchFactor(0, 0)  # file browser
        self._browse_split.setStretchFactor(1, 0)  # tag panel
        self._browse_split.setStretchFactor(2, 1)  # browser (stretches)
        self._browse_split.setStretchFactor(3, 0)  # preview pane
        saved_split = self._settings_early.value("splitter_sizes", None)
        if saved_split:
            sizes = [int(s) for s in saved_split]
            # Strip 5th element from old layout (info_panel moved to sidebar)
            if len(sizes) == 5:
                sizes = sizes[:4]
            if len(sizes) == 4:
                self._browse_split.setSizes(sizes)
            else:
                self._browse_split.setSizes([0, 260, 1000, 400])
        else:
            self._browse_split.setSizes([0, 260, 1000, 400])
        if self._settings_early.value("preview_docked", False, type=bool):
            self._preview_pane.show()
        if self._settings_early.value("file_browser_visible", False, type=bool):
            self._file_browser.show()
        # Restore collapsed folders state
        # Collapsed/hidden folders restored in _restore_last_project (after _rebind_project)
        # Restore collapsed tag sections
        saved_tag_sections = self._settings_early.value("collapsed_tag_sections", [])
        if saved_tag_sections:
            self.tag_panel._collapsed_sections = set(str(s) for s in saved_tag_sections)
        # info_panel is now always visible inside the tag panel splitter
        # Restore tag-notes splitter
        saved_notes_split = self._settings_early.value("tag_notes_splitter", None)
        if saved_notes_split:
            self.tag_panel._tag_notes_split.setSizes([int(s) for s in saved_notes_split])
        # Project notes panel — collapsible below the browser grid
        from PySide6.QtWidgets import QTextEdit
        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText("Project notes…")
        self._notes_edit.setMaximumHeight(120)
        self._notes_edit.setVisible(False)
        self._notes_edit.textChanged.connect(self._on_project_notes_changed)

        # Wrap browser + notes in a vertical sub-splitter (notes under grid only, not full width)
        _browser_notes_split = QSplitter(Qt.Orientation.Vertical)
        # Remove browser from _browse_split, put it in the sub-splitter
        self._browse_split.insertWidget(2, _browser_notes_split)
        _browser_notes_split.addWidget(self.browser)
        _browser_notes_split.addWidget(self._notes_edit)
        _browser_notes_split.setStretchFactor(0, 1)
        _browser_notes_split.setStretchFactor(1, 0)
        _browser_notes_split.setSizes([600, 80])

        self.tabs.addTab(self._browse_split, "Assets")

        # Tab 2: Canvas Editor
        self.scene = CanvasScene()
        self.view = CanvasView(self.scene)
        self.tabs.addTab(self.view, "Canvas")

        # Tab 3: Censor Editor
        self.censor_editor = CensorEditor()
        self.tabs.addTab(self.censor_editor, "Censor")

        # Tab 4: Social — Calendar + Timeline + Checklist (posting pipeline)
        self._timeline = TimelineStream()
        self._timeline.set_thumb_cache(self.browser._thumb_cache)
        self._timeline.set_project(self.project)
        self._timeline.post_selected.connect(self._on_post_selected)
        self._timeline.new_post_requested.connect(self._on_new_post)
        self._timeline.sync_requested.connect(self._on_sync_oneup)
        # Show active OneUp account on sync button
        from doxyedit.oneup import get_active_account_label
        project_dir = str(Path(self._project_path).parent) if hasattr(self, '_project_path') and self._project_path else "."
        self._timeline.set_oneup_label(get_active_account_label(project_dir))

        self._calendar_pane = CalendarPane()
        self._calendar_pane.set_project(self.project)
        self._calendar_pane.day_selected.connect(self._on_calendar_day_selected)
        self._calendar_pane.day_cleared.connect(self._on_calendar_day_cleared)

        self.checklist_panel = ChecklistPanel(self.project)

        # Left side: calendar + checklist stacked vertically
        self._social_left_split = QSplitter(Qt.Orientation.Vertical)
        self._social_left_split.addWidget(self._calendar_pane)
        self._social_left_split.addWidget(self.checklist_panel)
        self._social_left_split.setSizes([350, 200])
        self._social_left_split.setStretchFactor(0, 1)
        self._social_left_split.setStretchFactor(1, 1)

        # Horizontal: calendar+checklist left, timeline right
        self._social_split = QSplitter(Qt.Orientation.Horizontal)
        self._social_split.addWidget(self._social_left_split)
        self._social_split.addWidget(self._timeline)
        self._social_split.setSizes([250, 600])
        self._social_split.setStretchFactor(0, 0)
        self._social_split.setStretchFactor(1, 1)

        # Restore saved social splitter sizes
        saved_social = self._settings_early.value("social_splitter", None)
        if saved_social:
            self._social_split.setSizes([int(s) for s in saved_social])
        saved_social_left = self._settings_early.value("social_left_splitter", None)
        if saved_social_left:
            self._social_left_split.setSizes([int(s) for s in saved_social_left])

        self.tabs.addTab(self._social_split, "Social")

        # Tab 5: Platforms — slot assignments + kanban (legacy)
        self.platform_panel = PlatformPanel(self.project)
        self.platform_panel.set_thumb_cache(self.browser._thumb_cache)

        self._kanban_panel = KanbanPanel()
        self._kanban_panel.status_changed.connect(self._on_data_changed)
        self._kanban_panel.status_changed.connect(lambda: self.platform_panel.refresh())
        self._kanban_panel.status_changed.connect(lambda: self._timeline.refresh())

        _plat_right = QSplitter(Qt.Orientation.Vertical)
        _plat_right.addWidget(self._kanban_panel)
        _plat_right.setSizes([500])
        # Platforms (left) + kanban (right)
        self._plat_top = QSplitter(Qt.Orientation.Horizontal)
        self._plat_top.addWidget(self.platform_panel)
        self._plat_top.addWidget(_plat_right)
        self._plat_top.setStretchFactor(0, 3)
        self._plat_top.setStretchFactor(1, 2)
        # Assigned art hive at bottom — full width
        self._plat_full = QSplitter(Qt.Orientation.Vertical)
        self._plat_full.addWidget(self._plat_top)
        if hasattr(self.platform_panel, '_hive_container'):
            self._plat_full.addWidget(self.platform_panel._hive_container)
        self._plat_full.setStretchFactor(0, 4)
        self._plat_full.setStretchFactor(1, 0)
        # Restore saved sizes
        saved_pt = self._settings_early.value("plat_top_splitter", None)
        if saved_pt:
            self._plat_top.setSizes([int(s) for s in saved_pt])
        else:
            self._plat_top.setSizes([600, 400])
        saved_pf = self._settings_early.value("plat_full_splitter", None)
        if saved_pf:
            self._plat_full.setSizes([int(s) for s in saved_pf])
        else:
            self._plat_full.setSizes([500, 180])
        self.tabs.addTab(self._plat_full, "Platforms")

        # Tab 5: Project Notes — tabbed sub-notes with preview + editor
        from PySide6.QtWidgets import QPlainTextEdit, QTextBrowser, QInputDialog
        self._notes_tabs = QTabWidget()
        self._notes_tabs.setObjectName("project_notes_tabs")
        self._notes_tabs.setTabsClosable(True)
        self._notes_tabs.tabCloseRequested.connect(self._on_notes_tab_close)
        self._notes_tabs.currentChanged.connect(self._on_notes_tab_switched)

        # Corner buttons: Preview/Edit toggle + Add tab
        _corner = QWidget()
        _corner_layout = QHBoxLayout(_corner)
        _corner_layout.setContentsMargins(0, 0, 4, 0)
        _corner_layout.setSpacing(4)

        self._notes_preview_btn = QPushButton("Preview")
        self._notes_preview_btn.setObjectName("notes_toggle_btn")
        self._notes_preview_btn.setCheckable(True)
        self._notes_preview_btn.setToolTip("Toggle between editor and rendered preview")
        self._notes_preview_btn.clicked.connect(self._toggle_notes_preview)
        _corner_layout.addWidget(self._notes_preview_btn)

        _add_tab_btn = QPushButton("+")
        _add_tab_btn.setObjectName("notes_add_tab_btn")
        _add_tab_btn.setFixedSize(24, 24)
        _add_tab_btn.setToolTip("Add new notes tab")
        _add_tab_btn.clicked.connect(self._on_add_notes_tab)
        _corner_layout.addWidget(_add_tab_btn)

        self._notes_tabs.setCornerWidget(_corner)

        # Storage for tab editors: tab_name → (preview, editor, splitter)
        self._notes_tab_widgets: dict[str, tuple] = {}

        # Create tabs from project data
        # "General" tab = project.notes (always first, not closable)
        # "Agent Primer" tab = permanent, not closable
        # Other tabs from project.sub_notes
        self._build_notes_tab("General", self.project.notes, closable=False)
        primer_text = self.project.sub_notes.get("Agent Primer", "")
        self._build_notes_tab("Agent Primer", primer_text, closable=False)
        for tab_name, content in self.project.sub_notes.items():
            if tab_name == "Agent Primer":
                continue  # already created
            self._build_notes_tab(tab_name, content, closable=True)
        # Tab 6: Overview — Stats (left) + Health (right)
        self.stats_panel = StatsPanel(self.project)
        self.health_panel = HealthPanel(self.project)

        # Project Info panel — selectable text with project metadata
        from PySide6.QtWidgets import QTextBrowser as _TB
        self._project_info_panel = _TB()
        self._project_info_panel.setObjectName("project_info_panel")
        self._project_info_panel.setOpenExternalLinks(False)

        # Right column: project info (top) + health (bottom)
        _info_health_split = QSplitter(Qt.Orientation.Vertical)
        _info_health_split.addWidget(self._project_info_panel)
        _info_health_split.addWidget(self.health_panel)
        _info_health_split.setSizes([300, 300])
        _info_health_split.setStretchFactor(0, 1)
        _info_health_split.setStretchFactor(1, 1)

        self._overview_split = QSplitter(Qt.Orientation.Horizontal)
        self._overview_split.addWidget(self.stats_panel)
        self._overview_split.addWidget(_info_health_split)
        self._overview_split.setSizes([500, 500])
        self._overview_split.setStretchFactor(0, 1)
        self._overview_split.setStretchFactor(1, 1)
        self.tabs.addTab(self._overview_split, "Overview")
        self.tabs.addTab(self._notes_tabs, "Notes")

        # (Kanban panel moved into Platforms tab above)

        # Refresh stats when Overview tab is activated
        self.tabs.currentChanged.connect(self._on_inner_tab_changed)

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
        self.platform_panel.request_asset_pick.connect(self._assign_selected_to_slot)
        self.platform_panel.asset_selected.connect(self._navigate_to_asset)
        self.checklist_panel.modified.connect(lambda: setattr(self, '_dirty', True))
        self.health_panel.asset_selected.connect(self._navigate_to_asset)
        self.health_panel.missing_removed.connect(self._on_missing_removed)

        # --- Toolbar & menu ---
        self._build_toolbar()
        self._build_menu()
        self._setup_tag_shortcuts()
        # Hide the QTabWidget's built-in tab bar
        self.tabs.tabBar().setVisible(False)

        # Tab toolbar — styled identical to the menu bar so both rows look like one bar
        _TAB_NAMES = ["Assets", "Canvas", "Censor", "Social", "Platforms", "Overview", "Notes"]
        self._tab_toolbar = QToolBar("Tabs")
        self._tab_toolbar.setObjectName("tab_toolbar")
        self._tab_toolbar.setMovable(False)
        self._tab_toolbar.setFloatable(False)
        self._tab_toolbar.setIconSize(QSize(0, 0))

        self._menubar_tab_btns: list[QPushButton] = []
        for i, name in enumerate(_TAB_NAMES):
            btn = QPushButton(name)
            btn.setObjectName("menubar_tab_btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, idx=i: self.tabs.setCurrentIndex(idx))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            btn.setMinimumWidth(60)
            self._tab_toolbar.addWidget(btn)
            self._menubar_tab_btns.append(btn)

        _spacer = QWidget()
        _spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        _spacer.setObjectName("tab_toolbar_spacer")
        self._tab_toolbar.addWidget(_spacer)

        self._menubar_tray_btn = QPushButton("Tray")
        self._menubar_tray_btn.setObjectName("menubar_tab_btn")
        self._menubar_tray_btn.setCheckable(True)
        self._menubar_tray_btn.setToolTip("Toggle Work Tray (Ctrl+Shift+W)")
        self._menubar_tray_btn.clicked.connect(self._toggle_work_tray)
        self._tab_toolbar.addWidget(self._menubar_tray_btn)

        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._tab_toolbar)

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.currentChanged.connect(self._sync_menubar_tabs)
        self._sync_menubar_tabs(0)
        self._on_tab_changed(0)  # hide canvas tools initially

        # Wire Tray and Tags toggle buttons (created by browser as first toolbar items)
        self.browser._tray_btn.toggled.connect(lambda checked: self._toggle_work_tray())
        self._tray_toolbar_btn = self.browser._tray_btn
        self.browser._tags_btn.toggled.connect(self._toggle_tag_panel_btn)
        self._tags_toolbar_btn = self.browser._tags_btn

        # Sync toolbar button states with actual panel visibility
        self.browser._tags_btn.setChecked(self.tag_panel.isVisible())
        self.browser._tray_btn.setChecked(self._tray_open)
        if hasattr(self.browser, '_files_btn'):
            self.browser._files_btn.setChecked(self._file_browser.isVisible())

        # Tab key — toggle all side panels (hide/restore)
        QShortcut(QKeySequence(Qt.Key.Key_Tab), self).activated.connect(self._toggle_all_panels)

        # Escape to deselect, Ctrl+F to focus search
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._select_none)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            lambda: (self.browser.search_box.setFocus(), self.browser.search_box.selectAll()))
        # Alt+H temporary hide/unhide
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(self._temp_hide_toggle)
        # ` (backtick) — compact mode: toggle tag panel + tray + tag bar all at once
        self._compact_mode = False
        self._pre_compact: dict = {}
        QShortcut(QKeySequence("`"), self).activated.connect(self._toggle_compact_mode)
        # Ctrl+C copy as files (Explorer-style), Ctrl+Shift+C copy full path text
        QShortcut(QKeySequence("Ctrl+C"), self).activated.connect(self._copy_as_files)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self).activated.connect(self._copy_full_path)
        # Shift+E notes overlay
        QShortcut(QKeySequence("Shift+E"), self).activated.connect(self._show_notes_overlay)

        # --- Status bar with progress ---
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimumWidth(250)
        self._progress_bar.setMaximumWidth(400)
        self._progress_bar.setFixedHeight(max(12, _f))
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setVisible(False)
        self.status.addPermanentWidget(self._progress_bar)

        self._progress_label = QLabel()
        self._progress_label.setStyleSheet("padding-right: 12px;")
        self.status.addPermanentWidget(self._progress_label)
        self.status.addPermanentWidget(self.browser.count_label)
        self._update_progress()
        self.status.showMessage("Ready — open a folder or drag images in")

        # --- File watcher for external changes (Claude CLI) ---
        from PySide6.QtCore import QFileSystemWatcher
        self._file_watcher = QFileSystemWatcher(self)
        self._file_watcher.fileChanged.connect(self._on_project_file_changed_raw)

        # --- Asset file watcher — detect edits to source images ---
        self._asset_watcher = QFileSystemWatcher(self)
        self._asset_watcher.fileChanged.connect(self._on_asset_file_changed)

        # --- Import folder watcher — detect new files in import sources ---
        self._folder_watcher = QFileSystemWatcher(self)
        self._folder_watcher.directoryChanged.connect(self._on_watched_folder_changed)
        self._reload_debounce = QTimer(self)
        self._reload_debounce.setSingleShot(True)
        self._reload_debounce.setInterval(500)
        self._reload_debounce.timeout.connect(self._do_reload)

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
        if not _skip_autoload:
            self._restore_last_session()
        else:
            self._register_initial_slot(None, "New Project")

    def _restore_last_session(self):
        """Restore last collection if one was saved, otherwise restore last project."""
        last_coll = self._settings.value("last_collection", "")
        if last_coll and Path(last_coll).exists():
            if self._restore_collection(last_coll):
                self._restore_folder_state()
                return
            self.status.showMessage("Collection projects not found, restoring last project…")
        self._restore_last_project()

    def _restore_folder_state(self):
        """Restore collapsed/hidden folders from QSettings into the browser."""
        saved_collapsed = self._settings.value("collapsed_folders", [])
        if saved_collapsed:
            self.browser._collapsed_folders = set(str(f).replace("\\", "/") for f in saved_collapsed)
        saved_hidden = self._settings.value("hidden_folders", [])
        if saved_hidden:
            self.browser._hidden_folders = set(str(f).replace("\\", "/") for f in saved_hidden)
        if saved_collapsed or saved_hidden:
            self.browser.refresh()
        # Apply tag panel collapsed sections
        self.tag_panel.apply_collapsed_state()

    def _restore_last_project(self):
        """Restore last single project, or last folder, or blank slate."""
        last_project = self._settings.value("last_project", "")
        if last_project and Path(last_project).exists():
            self.project = Project.load(last_project)
            self._project_path = last_project
            self._register_initial_slot(last_project, Path(last_project).stem)
            self._rebind_project()
            self._restore_folder_state()
            self.setWindowTitle(f"DoxyEdit — {Path(last_project).name}")
            self.status.showMessage(f"Restored: {Path(last_project).name}")
            return
        self._register_initial_slot(None, "New Project")
        last_folder = self._settings.value("last_folder", "")
        if last_folder and Path(last_folder).exists():
            n = self.browser.import_folder(last_folder)
            if n:
                self.status.showMessage(
                    f"Reopened folder: {Path(last_folder).name} ({n} images)")

    def _restore_collection(self, coll_path: str) -> bool:
        """Load all projects from a collection file as tabs. Returns True on success."""
        try:
            data = json.loads(Path(coll_path).read_text(encoding="utf-8"))
        except Exception:
            return False
        all_paths = data.get("projects", [])
        paths = [p for p in all_paths if Path(p).exists()]
        missing = [p for p in all_paths if not Path(p).exists()]
        if not paths:
            return False
        # Load first project into the initial slot
        first = paths[0]
        self.project = Project.load(first)
        self._project_path = first
        self._register_initial_slot(first, Path(first).stem)
        self._rebind_project(clear_folder_state=True)
        self.setWindowTitle(f"DoxyEdit — {Path(first).name}")
        # Load remaining projects as additional tabs
        failed = []
        for path in paths[1:]:
            try:
                project = Project.load(path)
                self._add_project_tab(project, path, Path(path).stem)
            except Exception:
                failed.append(path)
        # Switch back to first tab
        self._proj_tab_bar.setCurrentIndex(0)
        self._switch_to_slot(0)
        # Report results
        loaded = len(paths) - len(failed)
        msg = f"Restored collection: {loaded} project(s)"
        if missing:
            msg += f" | {len(missing)} missing"
        if failed:
            msg += f" | {len(failed)} failed to load"
        self.status.showMessage(msg, 5000)
        # Show warning dialog if anything was lost
        if missing or failed:
            from PySide6.QtWidgets import QMessageBox
            details = []
            if missing:
                details.append("Missing files (not found on disk):")
                details.extend(f"  • {p}" for p in missing)
            if failed:
                details.append("Failed to load:")
                details.extend(f"  • {p}" for p in failed)
            QMessageBox.warning(self, "Collection",
                                f"Some projects could not be loaded:\n\n" + "\n".join(details))
        return True

    # ── Project tab management ──────────────────────────────────────────────

    def _register_initial_slot(self, path: str | None, label: str):
        self._project_slots = [{"project": self.project, "path": path, "label": label}]
        self._current_slot = 0
        self._proj_tab_bar.blockSignals(True)
        while self._proj_tab_bar.count():
            self._proj_tab_bar.removeTab(0)
        self._proj_tab_bar.addTab(label)
        self._proj_tab_bar.blockSignals(False)

    def _add_project_tab(self, project, path: str | None, label: str):
        self._save_current_slot()
        slot = {"project": project, "path": path, "label": label}
        self._project_slots.append(slot)
        idx = len(self._project_slots) - 1
        self._proj_tab_bar.blockSignals(True)
        self._proj_tab_bar.addTab(label)
        self._proj_tab_bar.blockSignals(False)
        self._proj_tab_bar.setCurrentIndex(idx)
        self._switch_to_slot(idx)

    def _save_current_slot(self):
        if 0 <= self._current_slot < len(self._project_slots):
            slot = self._project_slots[self._current_slot]
            slot["project"] = self.project
            if self._dirty and slot["path"]:
                self._own_save_pending = getattr(self, '_own_save_pending', 0) + 1
                self.project.save(slot["path"])
                self._dirty = False

    def _on_proj_tab_changed(self, idx: int):
        if idx < 0 or idx >= len(self._project_slots) or idx == self._current_slot:
            return
        self._save_current_slot()
        self._switch_to_slot(idx)

    def _switch_to_slot(self, idx: int):
        slot = self._project_slots[idx]
        self._current_slot = idx
        self.project = slot["project"]
        self._project_path = slot["path"]
        self._rebind_project(clear_folder_state=True)
        self.setWindowTitle(f"DoxyEdit — {slot['label']}")
        self._proj_tab_bar.setTabText(idx, slot["label"])

    def _close_proj_tab(self, idx: int):
        if len(self._project_slots) <= 1:
            self._new_project_blank()
            return
        slot = self._project_slots[idx]
        if slot["path"] and self._dirty and self._current_slot == idx:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                f"Save '{slot['label']}' before closing?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                self._own_save_pending = getattr(self, '_own_save_pending', 0) + 1
                self.project.save(slot["path"])
        self._project_slots.pop(idx)
        self._proj_tab_bar.blockSignals(True)
        self._proj_tab_bar.removeTab(idx)
        self._proj_tab_bar.blockSignals(False)
        new_idx = min(idx, len(self._project_slots) - 1)
        self._current_slot = -1
        self._proj_tab_bar.setCurrentIndex(new_idx)
        self._switch_to_slot(new_idx)

    def _on_proj_tab_moved(self, from_idx: int, to_idx: int):
        slot = self._project_slots.pop(from_idx)
        self._project_slots.insert(to_idx, slot)
        if self._current_slot == from_idx:
            self._current_slot = to_idx
        elif from_idx < self._current_slot <= to_idx:
            self._current_slot -= 1
        elif to_idx <= self._current_slot < from_idx:
            self._current_slot += 1

    def _rename_proj_tab(self, label: str):
        if 0 <= self._current_slot < len(self._project_slots):
            self._project_slots[self._current_slot]["label"] = label
            self._proj_tab_bar.setTabText(self._current_slot, label)

    def _add_folder_preset_dialog(self):
        """+ button or Ctrl+T: open a project or folder in a new tab."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("Open Project…", lambda: self._open_project_in_tab())
        menu.addAction("Open Folder…", lambda: self._open_folder_in_tab())
        menu.addAction("New Empty Project", self._new_project_blank_tab)
        menu.exec(self._new_tab_btn.mapToGlobal(self._new_tab_btn.rect().bottomLeft()))

    def _open_project_in_tab(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", self._dialog_dir(),
            "DoxyEdit Projects (*.doxyproj.json)")
        if not path:
            return
        self._remember_dir(path)
        for i, slot in enumerate(self._project_slots):
            if slot["path"] == path:
                self._proj_tab_bar.setCurrentIndex(i)
                return
        project = Project.load(path)
        self._add_project_tab(project, path, Path(path).stem)

    def _open_folder_in_tab(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Folder", self._dialog_dir())
        if not folder:
            return
        self._remember_dir(folder)
        project = Project(name=Path(folder).name)
        self._add_project_tab(project, None, Path(folder).name)
        self.browser.import_folder(folder)
        self._dirty = True
        self._refresh_file_browser()

    def _new_project_blank_tab(self):
        project = Project(name="New Project")
        self._add_project_tab(project, None, "New Project")

    # ── end project tab management ───────────────────────────────────────────

    def _dialog_dir(self, hint_path: str = "") -> str:
        """Return the best starting directory for a file dialog."""
        # Prefer last-used dialog directory
        saved = self._settings.value("last_dialog_dir", "")
        if saved and Path(saved).is_dir():
            return saved
        # Fall back to the directory of the hint path
        if hint_path:
            p = Path(hint_path)
            d = p.parent if p.is_file() else p
            if d.is_dir():
                return str(d)
        return ""

    def _remember_dir(self, path: str):
        """Persist the parent directory of path as the last-used dialog directory."""
        p = Path(path)
        d = p.parent if p.is_file() else p
        if d.is_dir():
            self._settings.setValue("last_dialog_dir", str(d))

    def _apply_theme(self, theme_id: str):
        from dataclasses import replace
        self._current_theme_id = theme_id
        base = THEMES.get(theme_id, THEMES[DEFAULT_THEME])
        overrides = {"font_size": getattr(self, '_theme', base).font_size}
        # Apply project accent color if set
        proj_accent = getattr(getattr(self, 'project', None), 'accent_color', '')
        if proj_accent:
            overrides.update({"accent": proj_accent, "accent_bright": proj_accent,
                               "selection_border": proj_accent})
        self._theme = replace(base, **overrides)
        self.setStyleSheet(generate_stylesheet(self._theme))
        self._settings.setValue("theme", theme_id)
        self._settings.sync()
        self._tint_titlebar(proj_accent)
        # Panels with deeply nested widgets that need explicit theme
        if hasattr(self, '_kanban_panel'):
            self._kanban_panel.apply_theme(self._theme)
        if hasattr(self, 'browser') and hasattr(self.browser, '_delegate'):
            self.browser._delegate.set_theme(self._theme)
        if hasattr(self, '_file_browser'):
            self._file_browser._theme = self._theme
        if hasattr(self, '_preview_pane'):
            self._preview_pane.update_theme(self._theme)

    def _tint_titlebar(self, hex_color: str = ""):
        """Apply accent color to Windows 11 title bar via DwmSetWindowAttribute."""
        try:
            import ctypes
            DWMWA_CAPTION_COLOR = 35
            DWMWA_COLOR_DEFAULT = 0xFFFFFFFF
            hwnd = int(self.winId())
            if hex_color:
                c = QColor(hex_color)
                colorref = (c.blue() << 16) | (c.green() << 8) | c.red()
            else:
                colorref = DWMWA_COLOR_DEFAULT
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_CAPTION_COLOR,
                ctypes.byref(ctypes.c_int(colorref)), 4)
        except Exception:
            pass

    def _flash_taskbar(self):
        """Flash the taskbar button when a long operation completes (Windows only)."""
        try:
            import ctypes, ctypes.wintypes
            class _FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.wintypes.HWND),
                             ("dwFlags", ctypes.c_uint), ("uCount", ctypes.c_uint),
                             ("dwTimeout", ctypes.c_uint)]
            fi = _FLASHWINFO()
            fi.cbSize  = ctypes.sizeof(_FLASHWINFO)
            fi.hwnd    = int(self.winId())
            fi.dwFlags = 0x0C | 0x02  # FLASHW_TIMERNOFG | FLASHW_TRAY
            fi.uCount  = 3
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(fi))
        except Exception:
            pass
        # Re-render HTML panels with new theme colors
        if hasattr(self, '_project_notes_preview'):
            self._render_notes_preview(self.project.notes)
        if hasattr(self, '_project_info_panel'):
            self._refresh_project_info()
        # Match Windows title bar to theme
        self._update_title_bar_color()

    def _update_title_bar_color(self):
        proj_accent = getattr(getattr(self, 'project', None), 'accent_color', '')
        if proj_accent:
            self._tint_titlebar(proj_accent)
        else:
            self._theme_dialog_titlebar(self)

    def _theme_dialog_titlebar(self, widget):
        try:
            import ctypes
            bg = self._theme.bg_raised
            r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
            hwnd = int(widget.winId())
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

    def _set_project_color(self):
        color = QColorDialog.getColor(
            QColor(self.project.accent_color or self._theme.accent),
            self, "Project Accent Color")
        if not color.isValid():
            return
        self.project.accent_color = color.name()
        self._apply_theme(self._current_theme_id)
        self._dirty = True
        if self._project_path:
            self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1; self.project.save(self._project_path)
            self._dirty = False
        self.status.showMessage(f"Project accent: {color.name()}", 2000)

    def _toggle_project_notes(self, visible: bool):
        self._notes_edit.setVisible(visible)
        if visible:
            self._notes_edit.blockSignals(True)
            self._notes_edit.setPlainText(self.project.notes)
            self._notes_edit.blockSignals(False)

    def _on_project_notes_changed(self):
        text = self._notes_edit.toPlainText()
        self.project.notes = text
        self._dirty = True
        # Keep the full Notes tab in sync
        self._project_notes_edit.blockSignals(True)
        self._project_notes_edit.setPlainText(text)
        self._project_notes_edit.blockSignals(False)

    # ------------------------------------------------------------------
    # Tabbed notes system
    # ------------------------------------------------------------------

    def _build_notes_tab(self, name: str, content: str, closable: bool = True):
        """Create a notes sub-tab with preview + editor splitter."""
        from PySide6.QtWidgets import QPlainTextEdit, QTextBrowser, QStackedWidget

        # Container with stacked editor/preview (toggle is in corner widget)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Stacked: editor (default, index 0) / preview (index 1)
        stack = QStackedWidget()

        editor = _CenteredTextEdit()
        editor.setObjectName("project_notes_tab")
        editor.setPlainText(content)
        editor.textChanged.connect(lambda: self._on_sub_note_changed(name))

        # Right-click context menu with Claude actions
        editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        editor.customContextMenuRequested.connect(
            lambda pos, e=editor, n=name: self._show_notes_context_menu(pos, e, n))

        preview = QTextBrowser()
        preview.setObjectName("project_notes_preview")
        preview.setOpenExternalLinks(True)

        stack.addWidget(editor)
        stack.addWidget(preview)

        container_layout.addWidget(stack, 1)

        idx = self._notes_tabs.addTab(container, name)
        self._notes_tab_widgets[name] = (preview, editor, stack)

        # Make permanent tabs non-closable
        if not closable:
            self._notes_tabs.tabBar().setTabButton(
                idx, QTabBar.ButtonPosition.RightSide, None)

        # Render initial content (show editor by default)
        if name == "General":
            self._project_notes_edit = editor
            self._project_notes_preview = preview

    def _on_sub_note_changed(self, tab_name: str):
        """Handle text change in a sub-note tab."""
        widgets = self._notes_tab_widgets.get(tab_name)
        if not widgets:
            return
        _, editor, _ = widgets
        text = editor.toPlainText()

        if tab_name == "General":
            self.project.notes = text
            # Sync small notes panel
            if hasattr(self, '_notes_edit') and self._notes_edit.isVisible():
                self._notes_edit.blockSignals(True)
                self._notes_edit.setPlainText(text)
                self._notes_edit.blockSignals(False)
        else:
            self.project.sub_notes[tab_name] = text

        self._dirty = True
        self._render_sub_note_preview(tab_name, text)

    def _render_sub_note_preview(self, tab_name: str, text: str):
        """Render markdown preview for a specific sub-note tab."""
        widgets = self._notes_tab_widgets.get(tab_name)
        if not widgets:
            return
        preview, _, _ = widgets
        self._render_notes_preview_to(preview, text)

    def _on_notes_tab_close(self, index: int):
        """Close a notes sub-tab (permanent tabs can't be closed)."""
        name = self._notes_tabs.tabText(index)
        if name in ("General", "Agent Primer"):
            return  # permanent tabs
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(
            self, "Delete Tab",
            f"Delete the '{name}' notes tab? Content will be lost.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._notes_tabs.removeTab(index)
        self._notes_tab_widgets.pop(name, None)
        self.project.sub_notes.pop(name, None)
        self._dirty = True

    def _on_add_notes_tab(self):
        """Add a new notes sub-tab."""
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Tab", "Tab name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self._notes_tab_widgets:
            self._notes_tabs.setCurrentIndex(
                self._notes_tabs.indexOf(self._notes_tab_widgets[name][2]))
            return
        self._build_notes_tab(name, "", closable=True)
        self.project.sub_notes[name] = ""
        self._dirty = True
        # Switch to new tab
        self._notes_tabs.setCurrentIndex(self._notes_tabs.count() - 1)

    def _toggle_notes_preview(self, checked: bool):
        """Toggle current notes tab between editor and preview."""
        if not hasattr(self, '_notes_tabs'):
            return
        tab_name = self._notes_tabs.tabText(self._notes_tabs.currentIndex())
        widgets = self._notes_tab_widgets.get(tab_name)
        if not widgets:
            return
        preview, editor, stack = widgets
        if checked:
            text = editor.toPlainText()
            self._render_notes_preview_to(preview, text)
            stack.setCurrentIndex(1)
            self._notes_preview_btn.setText("Edit")
        else:
            stack.setCurrentIndex(0)
            self._notes_preview_btn.setText("Preview")

    def _on_notes_tab_switched(self, index: int):
        """Reset preview/edit state when switching tabs."""
        if not hasattr(self, '_notes_preview_btn'):
            return
        self._notes_preview_btn.setChecked(False)
        self._notes_preview_btn.setText("Preview")
        # Make sure the new tab shows the editor
        tab_name = self._notes_tabs.tabText(index)
        widgets = self._notes_tab_widgets.get(tab_name)
        if widgets:
            _, _, stack = widgets
            stack.setCurrentIndex(0)

    def _show_notes_context_menu(self, pos, editor, tab_name: str):
        """Show right-click menu with Claude actions for notes editors."""
        menu = editor.createStandardContextMenu()
        # Force theme on the popup menu (top-level widgets don't inherit on Windows)
        t = self._theme
        rad = max(3, t.font_size // 4)
        pad = max(4, t.font_size // 3)
        pad_lg = max(6, t.font_size // 2)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {t.bg_raised}; color: {t.text_primary};
                border: 1px solid {t.border}; border-radius: {rad}px;
                padding: {pad}px 0;
            }}
            QMenu::item {{ padding: {pad}px {pad_lg * 3}px; }}
            QMenu::item:selected {{ background: {t.accent_dim}; color: {t.text_on_accent}; }}
            QMenu::item:disabled {{ color: {t.text_muted}; }}
            QMenu::separator {{ background: {t.border}; height: 1px; margin: {pad}px {pad_lg}px; }}
        """)
        selected = editor.textCursor().selectedText()

        if selected.strip():
            menu.addSeparator()

            # Check if selection contains [bracketed instructions]
            import re
            bracket_match = re.search(r'\[(.+?)\]', selected)
            if bracket_match:
                instruction = bracket_match.group(1)
                instruct_action = menu.addAction(f"Claude: {instruction[:40]}")
                instruct_action.triggered.connect(
                    lambda: self._refine_with_claude(editor, tab_name, selected, "instruct"))
                menu.addSeparator()

            refine_action = menu.addAction("Refine with Claude")
            refine_action.triggered.connect(
                lambda: self._refine_with_claude(editor, tab_name, selected, "refine"))
            expand_action = menu.addAction("Expand with Claude")
            expand_action.triggered.connect(
                lambda: self._refine_with_claude(editor, tab_name, selected, "expand"))
            research_action = menu.addAction("Research with Claude")
            research_action.triggered.connect(
                lambda: self._refine_with_claude(editor, tab_name, selected, "research"))
            simplify_action = menu.addAction("Simplify with Claude")
            simplify_action.triggered.connect(
                lambda: self._refine_with_claude(editor, tab_name, selected, "simplify"))

        menu.exec(editor.mapToGlobal(pos))

    def _refine_with_claude(self, editor, tab_name: str, selected: str, mode: str):
        """Send selected text to Claude for refinement, replace in editor."""
        import subprocess, sys

        full_text = editor.toPlainText()

        # For "instruct" mode, extract the [bracketed instruction] from the selection
        import re
        if mode == "instruct":
            bracket_match = re.search(r'\[(.+?)\]', selected)
            instruction = bracket_match.group(1) if bracket_match else selected
            mode_desc = f"Follow this instruction: {instruction}"
        else:
            mode_desc = {
                "refine": "Improve this text. Fix any issues, clarify wording, make it more actionable. Keep the same length and format.",
                "expand": "Expand this into more detail. Add examples, edge cases, or specifics. Keep the same style.",
                "research": "Research this topic using web search. Find current, accurate, actionable information. Replace the selected text with your findings formatted as concise bullet points. Cite no URLs, just the facts.",
                "simplify": "Make this shorter and more direct. Remove fluff. Keep only what matters.",
            }[mode]

        prompt = f"""You are editing a document for a social media art posting pipeline.

The user selected this text and wants you to act on it:

SELECTED TEXT:
{selected}

FULL DOCUMENT CONTEXT (for reference, don't rewrite the whole thing):
{full_text[:2000]}

INSTRUCTION: {mode_desc}

Return ONLY the replacement text. No explanation, no markdown fences, no preamble. Just the improved text that will replace the selection."""

        # Modal progress dialog
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QThread, Signal as _Signal

        self._refine_progress = QProgressDialog(
            f"Claude is working on: {mode}...", None, 0, 0, self)
        self._refine_progress.setObjectName("claude_progress")
        self._refine_progress.setWindowTitle("Claude")
        self._refine_progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._refine_progress.setCancelButton(None)
        self._refine_progress.setMinimumDuration(0)
        self._refine_progress.setMinimumWidth(300)
        self._refine_progress.show()
        self._theme_dialog_titlebar(self._refine_progress)

        class _Worker(QThread):
            finished = _Signal(str)
            def __init__(self, p):
                super().__init__()
                self._prompt = p
            def run(self):
                try:
                    kwargs = dict(capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=60)
                    if sys.platform == "win32":
                        kwargs["creationflags"] = 0x08000000
                    result = subprocess.run(
                        ["claude", "-p", self._prompt], **kwargs)
                    self.finished.emit(result.stdout.strip() if result.returncode == 0 else "")
                except Exception:
                    self.finished.emit("")

        self._refine_worker = _Worker(prompt)
        self._refine_worker.finished.connect(
            lambda result: self._on_refine_done(editor, tab_name, selected, result))
        self._refine_worker.start()

    def _on_refine_done(self, editor, tab_name: str, original: str, replacement: str):
        """Replace selected text with Claude's refinement."""
        # Close progress dialog
        if hasattr(self, '_refine_progress'):
            self._refine_progress.close()

        if not replacement:
            self.status.showMessage("Claude returned empty response", 3000)
            return

        # Replace via cursor so Ctrl+Z undo works
        cursor = editor.textCursor()
        if cursor.hasSelection():
            # Selection still active — replace it directly
            cursor.insertText(replacement)
        else:
            # Selection lost (dialog stole focus) — find and replace in text
            current = editor.toPlainText()
            original_normalized = original.replace("\u2029", "\n")
            start = current.find(original_normalized)
            if start >= 0:
                cursor.setPosition(start)
                cursor.setPosition(start + len(original_normalized),
                                   cursor.MoveMode.KeepAnchor)
                cursor.insertText(replacement)
            else:
                # Can't find original — insert at end
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.insertText("\n" + replacement)
        self.status.showMessage("Text refined by Claude", 3000)

    def _on_project_notes_tab_changed(self):
        """Legacy handler — redirects to sub-note system."""
        self._on_sub_note_changed("General")

    def _render_notes_preview(self, text: str):
        """Render to the General tab preview (backward compat)."""
        self._render_notes_preview_to(self._project_notes_preview, text)

    def _render_notes_preview_to(self, widget, text: str):
        """Render markdown preview into a specific QTextBrowser widget."""
        try:
            import markdown as _md
            html_body = _md.markdown(text, extensions=["tables", "fenced_code", "nl2br"])
        except Exception:
            html_body = f"<pre>{text}</pre>"
        bg = self._theme.bg_deep
        fg = self._theme.text_primary
        fg2 = self._theme.text_secondary
        accent = self._theme.accent
        border = self._theme.border_light
        bg_raised = self._theme.bg_raised
        html = f"""<html><head><style>
            body {{ background:{bg}; color:{fg}; font-family:'Segoe UI',sans-serif;
                   padding:8px 120px;
                   line-height:1.2; }}
            h1 {{ color:{accent}; margin:8px 0 2px 0; }}
            h2 {{ color:{accent}; margin:8px 0 2px 0; }}
            h3 {{ color:{accent}; margin:6px 0 1px 0; }}
            h4,h5,h6 {{ color:{accent}; margin:4px 0 1px 0; }}
            a {{ color:{accent}; }}
            p {{ margin:2px 0; }}
            ul, ol {{ padding-left:16px; margin:1px 0; }}
            li {{ margin:0; padding:0; line-height:1.15; }}
            img {{ max-width:100%; border-radius:4px; }}
            code {{ background:{bg_raised}; padding:1px 4px;
                    border-radius:3px; font-family:Consolas,monospace; }}
            pre {{ background:{bg_raised}; padding:8px 12px;
                   border-radius:4px; overflow-x:auto; }}
            pre code {{ background:transparent; padding:0; }}
            blockquote {{ border-left:3px solid {accent}; margin:0; padding:2px 12px;
                          color:{fg2}; }}
            table {{ border-collapse:collapse; width:100%; }}
            th,td {{ border:1px solid {border}; padding:4px 8px; text-align:left; }}
            th {{ background:{bg_raised}; }}
            hr {{ border:none; height:2px; background:{accent}30; margin:8px 0; }}
        </style></head><body>{html_body}</body></html>"""
        widget.setHtml(html)

    def _clear_project_color(self):
        self.project.accent_color = ""
        self._apply_theme(self._current_theme_id)
        self._dirty = True
        if self._project_path:
            self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1; self.project.save(self._project_path)
            self._dirty = False
        self.status.showMessage("Project accent cleared", 2000)

    def _set_hover_size(self, pct: int):
        self.browser._hover_size_pct = pct
        self.browser._hover_fixed_px = 0
        self._settings.setValue("hover_size_pct", pct)
        self._settings.setValue("hover_fixed_px", 0)
        self.status.showMessage(f"Hover preview: {pct}% of thumbnail size", 2000)

    def _set_hover_fixed_px(self, px: int):
        self.browser._hover_fixed_px = px
        self._settings.setValue("hover_fixed_px", px)
        self.status.showMessage(f"Hover preview: fixed {px}px", 2000)

    def _set_hover_delay(self, ms: int):
        self.browser._hover_timer.setInterval(ms)
        self._settings.setValue("hover_delay_ms", ms)
        self.status.showMessage(f"Hover preview delay: {ms}ms", 2000)

    def _set_thumb_gen_size(self, size: int):
        from doxyedit import browser
        browser.THUMB_GEN_SIZE = size
        self._settings.setValue("thumb_gen_size", size)
        self.status.showMessage(f"Thumbnail quality: {size}px (recache with F5)", 3000)

    def _apply_font(self):
        fs = self._theme.font_size
        self.setStyleSheet(generate_stylesheet(self._theme))
        self.browser.update_font_size(fs)
        self.tag_panel.update_font_size(fs)
        self._settings.setValue("font_size", fs)
        self.status.showMessage(f"Font size: {fs}px", 2000)
        self._refresh_project_info()
        self._render_notes_preview(self.project.notes)

    def _build_toolbar(self):
        # Left toolbar — hidden, canvas tools only
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)
        tb.hide()
        self._left_toolbar = tb

        # Tray/Tags toggle buttons — created here, added to browser toolbar
        self._tray_btn = QAction("Tray", self)
        self._tray_btn.setCheckable(True)
        self._tray_btn.setChecked(False)
        self._tray_btn.triggered.connect(lambda checked: self._toggle_work_tray())

        # Canvas tools (active when on Canvas tab)
        self._canvas_sep_before = tb.addSeparator()
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

        self._color_action = QAction("Color", self, triggered=self._change_color)
        tb.addAction(self._color_action)
        self._canvas_sep_after = tb.addSeparator()

        tb.addAction(QAction("Delete", self, triggered=self._handle_delete))

    def _build_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        file_menu.addAction("&New Project", self._new_project, QKeySequence("Ctrl+N"))
        file_menu.addAction("&Open Project...", self._open_project, QKeySequence("Ctrl+O"))
        file_menu.addAction("&Save Project", self._save_project, QKeySequence("Ctrl+S"))
        file_menu.addAction("Save Project &As...", self._save_project_as, QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()

        # Recent projects submenu (right-click an entry to remove it)
        self._recent_projects_menu = _RemovableMenu(self._remove_recent_project, "Recent Projects", self)
        file_menu.addMenu(self._recent_projects_menu)
        self._recent_folders_menu = _RemovableMenu(self._remove_recent_folder, "Recent Folders", self)
        file_menu.addMenu(self._recent_folders_menu)
        self._rebuild_recent_menus()
        file_menu.addSeparator()

        # Import / Export submenu
        ie_sub = file_menu.addMenu("Import / Export")
        ie_sub.addAction("Import Project...", self._open_project_in_tab)
        ie_sub.addAction("&Export All Platforms...", self._export_all, QKeySequence("Ctrl+E"))
        ie_sub.addAction("Paste Image (Ctrl+V)", self._paste_from_clipboard, QKeySequence("Ctrl+V"))
        ie_sub.addAction("Paste Folder", self._paste_folder_from_clipboard)

        # Collections submenu
        coll_sub = file_menu.addMenu("Collections")
        coll_sub.addAction("Save Collection", self._save_collection_quick)
        coll_sub.addAction("Save Collection As...", self._save_collection)
        coll_sub.addAction("Open Collection...", self._open_collection)
        coll_sub.addAction("Reload Collection", self._reload_collection)
        coll_sub.addAction("Locate Last Collection", self._locate_last_collection)

        # Project Settings submenu
        ps_sub = file_menu.addMenu("Project Settings")
        ps_sub.addAction("New Folder &Tab", self._add_folder_preset_dialog, QKeySequence("Ctrl+T"))
        ps_sub.addAction("Set Project Accent Color...", self._set_project_color)
        ps_sub.addAction("Clear Project Accent Color", self._clear_project_color)
        self._local_mode_action = ps_sub.addAction("Local Mode (Repo-Relative Paths)")
        self._local_mode_action.setCheckable(True)
        self._local_mode_action.setToolTip(
            "Store asset paths relative to the project file.\n"
            "Use for projects in a git repo shared across multiple PCs.")
        self._local_mode_action.toggled.connect(self._on_local_mode_toggled)
        ps_sub.addAction("Reset All Tags (fresh start)", self._reset_all_tags)

        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close, QKeySequence("Alt+F4"))

        # Bookmarks menu
        bm_menu = menu.addMenu("&Bookmarks")
        bm_menu.addAction("Bookmark This Project", self._bookmark_current_project)
        bm_menu.addAction("Bookmark Current Collection", self._bookmark_current_collection)
        bm_menu.addSeparator()
        self._bm_projects_menu = bm_menu.addMenu("Projects")
        self._bm_collections_menu = bm_menu.addMenu("Collections")
        bm_menu.addSeparator()
        bm_menu.addAction("Manage Bookmarks…", self._manage_bookmarks)
        self._rebuild_bookmarks_menu()

        # Edit menu
        edit_menu = menu.addMenu("&Edit")
        edit_menu.addAction("Select &All", self._select_all, QKeySequence("Ctrl+A"))
        edit_menu.addAction("Select &None", self._select_none, QKeySequence("Ctrl+Shift+D"))
        edit_menu.addAction("&Invert Selection", self._invert_selection)
        edit_menu.addSeparator()
        edit_menu.addAction("&Rename File on Disk", self._rename_selected, QKeySequence("F2"))
        edit_menu.addAction("&Delete Selected (Ignore)", self._handle_delete, QKeySequence("Delete"))
        edit_menu.addAction("&Remove from Project", self._remove_selected)
        edit_menu.addSeparator()
        edit_menu.addAction("Move to Another Project...", self._move_to_project)
        edit_menu.addAction("Move to New Project...", self._move_to_new_project)
        edit_menu.addSeparator()
        edit_menu.addAction("Star Selected", lambda: self._batch_star(1))
        edit_menu.addAction("Unstar Selected", lambda: self._batch_star(0))
        edit_menu.addAction("Clear Tags on Selected", self._clear_tags_selected)
        edit_menu.addAction("Add Tag to Selected...", self._add_tag_to_selected, QKeySequence("Alt+A"))
        edit_menu.addSeparator()
        edit_menu.addAction("Save Filter as Smart Folder...", self._save_smart_folder)

        # Tools menu
        tools_menu = menu.addMenu("&Tools")

        # — Top-level most-used —
        tools_menu.addAction("&Reload Project from Disk", self._reload_project, QKeySequence("F5"))
        tools_menu.addAction("Refresh Thumbnails", self._refresh_thumbs, QKeySequence("Shift+F5"))
        tools_menu.addAction("Cycle Drag Fix (F8)", lambda: self.browser.cycle_drag_fix(), QKeySequence("F8"))
        tools_menu.addAction("Remove Missing Files", self._remove_missing_files)
        tools_menu.addAction("Find Duplicate Files...", self._find_duplicates)
        tools_menu.addAction("Find Similar Images (Perceptual)...", self._find_similar)
        tools_menu.addSeparator()

        # — Cache submenu —
        cache_menu = tools_menu.addMenu("Cache")
        cache_menu.addAction("Clear Thumbnail Cache", self._clear_thumb_cache)
        cache_menu.addAction("Set Cache Location...", self._set_cache_location)
        cache_menu.addAction("Open Cache Folder", self._open_cache_folder)
        self._shared_cache_action = cache_menu.addAction("Shared Cache (all projects)")
        self._shared_cache_action.setCheckable(True)
        shared = self._settings.value("shared_cache", "true") == "true"
        self._shared_cache_action.setChecked(shared)
        self._shared_cache_action.toggled.connect(self._on_shared_cache_toggled)
        self._fast_cache_action = cache_menu.addAction("Fast Cache Mode (BMP, larger files)")
        self._fast_cache_action.setCheckable(True)
        self._fast_cache_action.setChecked(bool(self._settings.value("fast_cache", 0, type=int)))
        self._fast_cache_action.setToolTip(
            "Store thumbnails as uncompressed BMP for faster reads at the cost of disk space")
        self._fast_cache_action.toggled.connect(self._on_fast_cache_toggled)
        # Memory cache size
        mem_menu = cache_menu.addMenu("Memory Cache Size")
        from doxyedit.thumbcache import _LRU_MAX
        saved_lru = self._settings.value("lru_max", _LRU_MAX, type=int)
        self.browser._thumb_cache.set_lru_max(saved_lru)
        from PySide6.QtGui import QActionGroup
        lru_group = QActionGroup(self)
        for n in [500, 1000, 2000, 5000, 10000]:
            a = mem_menu.addAction(f"{n} thumbnails")
            a.setCheckable(True)
            a.setChecked(saved_lru == n)
            a.triggered.connect(lambda _, v=n: self._set_lru_max(v))
            lru_group.addAction(a)

        # — Tags submenu —
        tags_menu = tools_menu.addMenu("Tags")
        tags_menu.addAction("Rebuild Tag Bar", lambda: self.browser.rebuild_tag_bar())
        tags_menu.addAction("Clear Unused Tags", self._clear_unused_tags)
        tags_menu.addAction("Tag Usage Stats...", self._show_tag_stats)
        self._auto_tag_action = tags_menu.addAction("Auto-Tag on Import")
        self._auto_tag_action.setCheckable(True)
        self._auto_tag_action.setChecked(False)
        self._auto_tag_action.toggled.connect(lambda on: setattr(self.browser, 'auto_tag_enabled', on))

        # — Import / Export submenu —
        importexport_menu = tools_menu.addMenu("Import / Export")
        importexport_menu.addAction("Refresh Import Sources", self._refresh_import_sources, QKeySequence("Ctrl+R"))
        importexport_menu.addAction("Show Import Sources...", self._show_import_sources)
        importexport_menu.addAction("Configure Editors...", self._configure_editors)
        self._launch_menu = importexport_menu.addMenu("Launch In")
        self._rebuild_launch_menu()
        importexport_menu.addAction("Mass Tag Editor (AI Training)...", self._mass_tag_editor)
        importexport_menu.addAction("Edit Project Config (YAML)...", self._edit_project_config)

        # — Project Info submenu —
        projinfo_menu = tools_menu.addMenu("Project Info")
        projinfo_menu.addAction("Project &Summary (CLI)", self._show_summary)
        projinfo_menu.addAction("Show Project File...", self._show_project_file)
        projinfo_menu.addAction("Open Project File Location", self._open_project_location)
        projinfo_menu.addAction("Posting Checklist...", self._show_checklist)

        tools_menu.addSeparator()

        # — Folder Scan at bottom —
        self._folder_scan_action = tools_menu.addAction("Folder Scan")
        self._folder_scan_action.setCheckable(True)
        self._folder_scan_action.setChecked(self.browser.folder_scan_check.isChecked())
        self._folder_scan_action.toggled.connect(self.browser.folder_scan_check.setChecked)
        self.browser.folder_scan_check.toggled.connect(self._folder_scan_action.setChecked)

        # View menu
        view_menu = menu.addMenu("&View")
        self._toggle_tags_action = view_menu.addAction(
            "Hide Tag Panel", self._toggle_tag_panel, QKeySequence("Ctrl+L"))
        self._toggle_tray_action = view_menu.addAction(
            "Show Work Tray", self._toggle_work_tray, QKeySequence("Ctrl+Shift+W"))
        self._toggle_dock_preview_action = view_menu.addAction(
            "Docked Preview", self._toggle_dock_preview, QKeySequence("Ctrl+D"))
        self._toggle_dock_preview_action.setCheckable(True)
        self._toggle_dock_preview_action.setChecked(self._preview_pane.isVisible())
        self._toggle_file_browser_action = view_menu.addAction(
            "File Browser", self._toggle_file_browser, QKeySequence("Ctrl+B"))
        self._toggle_file_browser_action.setCheckable(True)
        self._toggle_file_browser_action.setChecked(self._file_browser.isVisible())
        view_menu.addAction("Info Panel", self._toggle_info_panel, QKeySequence("Ctrl+I"))
        self._toggle_project_notes_action = view_menu.addAction("Project Notes Panel")
        self._toggle_project_notes_action.setCheckable(True)
        self._toggle_project_notes_action.setChecked(False)
        self._toggle_project_notes_action.toggled.connect(self._toggle_project_notes)
        view_menu.addSeparator()
        view_menu.addAction("Refresh Grid", lambda: self.browser.refresh())
        view_menu.addAction("Show Hidden Folders", lambda: self.browser.show_all_hidden_folders())
        view_menu.addSeparator()

        # Display submenu
        display_sub = view_menu.addMenu("Display")
        self._show_dims_action = display_sub.addAction("Show Resolution")
        self._show_dims_action.setCheckable(True)
        self._show_dims_action.setChecked(True)
        self._show_dims_action.toggled.connect(self._toggle_dims)
        self._toggle_tag_bar_action = display_sub.addAction("Show Tag Bar")
        self._toggle_tag_bar_action.setCheckable(True)
        self._toggle_tag_bar_action.setChecked(True)
        self._toggle_tag_bar_action.toggled.connect(self._on_toggle_tag_bar)
        self._show_hidden_only = display_sub.addAction("Show Hidden Only")
        self._show_hidden_only.setCheckable(True)
        self._show_hidden_only.toggled.connect(self._toggle_show_hidden_only)
        display_sub.addAction("Show All Hidden Tags", lambda: self.tag_panel._show_all_tags())
        filenames_menu = display_sub.addMenu("Filenames")
        for label, val in [("Always", "always"), ("Hover Only", "hover"), ("Never", "never")]:
            act = filenames_menu.addAction(label, lambda v=val: self._set_filename_display(v))
            act.setCheckable(True)
            act.setChecked(val == "always")
        self._filenames_actions = {a.text(): a for a in filenames_menu.actions()}
        self._fill_mode_action = display_sub.addAction("Fill Thumbnails (Crop)")
        self._fill_mode_action.setCheckable(True)
        self._fill_mode_action.setChecked(False)
        self._fill_mode_action.toggled.connect(self._toggle_fill_mode)

        # Font & Size submenu
        fontsize_sub = view_menu.addMenu("Font && Size")
        fontsize_sub.addAction("Increase Font Size", self._font_increase, QKeySequence("Ctrl+="))
        fontsize_sub.addAction("Decrease Font Size", self._font_decrease, QKeySequence("Ctrl+-"))
        fontsize_sub.addAction("Reset Font Size", self._font_reset, QKeySequence("Ctrl+0"))
        gen_menu = fontsize_sub.addMenu("Thumbnail Quality")
        for n in [64, 128, 256, 512, 768, 1024]:
            gen_menu.addAction(f"{n}px", lambda size=n: self._set_thumb_gen_size(size))

        # Theme submenu (kept as-is)
        theme_menu = view_menu.addMenu("Theme")
        for tid, theme in THEMES.items():
            theme_menu.addAction(theme.name, lambda t=tid: self._apply_theme(t))

        # Hover Preview submenu (merged size + delay)
        hover_sub = view_menu.addMenu("Hover Preview")
        self._hover_action = hover_sub.addAction("Enabled")
        self._hover_action.setCheckable(True)
        self._hover_action.setChecked(self.browser.hover_check.isChecked())
        self._hover_action.toggled.connect(self.browser.hover_check.setChecked)
        self.browser.hover_check.toggled.connect(self._hover_action.setChecked)
        hover_sub.addSeparator()
        hover_size_menu = hover_sub.addMenu("Size")
        for pct in [125, 150, 200, 250, 300]:
            hover_size_menu.addAction(f"{pct}% (of thumbnail)", lambda p=pct: self._set_hover_size(p))
        hover_size_menu.addSeparator()
        for px in [200, 300, 400, 500, 600, 800]:
            hover_size_menu.addAction(f"{px}px (fixed)", lambda p=px: self._set_hover_fixed_px(p))
        delay_menu = hover_sub.addMenu("Delay")
        for ms in [200, 300, 400, 600, 800, 1200]:
            delay_menu.addAction(f"{ms}ms", lambda d=ms: self._set_hover_delay(d))

        view_menu.addSeparator()
        self._recursive_action = view_menu.addAction("Recursive Import")
        self._recursive_action.setCheckable(True)
        self._recursive_action.setChecked(self.browser.recursive_check.isChecked())
        self._recursive_action.toggled.connect(self.browser.recursive_check.setChecked)
        self.browser.recursive_check.toggled.connect(self._recursive_action.setChecked)

        self._cache_all_action = view_menu.addAction("Cache All Thumbnails")
        self._cache_all_action.setCheckable(True)
        self._cache_all_action.setChecked(self.browser.cache_all_check.isChecked())
        self._cache_all_action.toggled.connect(self.browser.cache_all_check.setChecked)
        self.browser.cache_all_check.toggled.connect(self._cache_all_action.setChecked)
        view_menu.addSeparator()
        self._smart_folder_menu = view_menu.addMenu("Smart Folders")
        self._rebuild_smart_folder_menu()

        # Help menu
        help_menu = menu.addMenu("&Help")
        help_menu.addAction("Keyboard Shortcuts", self._show_shortcuts)
        help_menu.addAction("What's New (v2.2)", self._show_whats_new)
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
                self.browser.scroll_to_asset(asset.id)
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

    def _paste_folder_from_clipboard(self):
        """Import a folder whose path is on the clipboard (text or file URL)."""
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        folders = []
        if mime.hasUrls():
            for u in mime.urls():
                p = Path(u.toLocalFile())
                if p.is_dir():
                    folders.append(str(p))
        if not folders and mime.hasText():
            for line in mime.text().strip().splitlines():
                p = Path(line.strip().strip('"'))
                if p.is_dir():
                    folders.append(str(p))
        if not folders:
            self.status.showMessage("No folder path in clipboard", 2000)
            return
        total = 0
        for f in folders:
            total += self.browser.import_folder(f)
        self.status.showMessage(f"Imported {total} image(s) from folder", 2000)
        self._refresh_file_browser()

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
        self.status.setStyleSheet(
            f"QStatusBar {{ background: {self._theme.statusbar_bg}; color: {self._theme.statusbar_text}; }}")
        self.status.showMessage(label)

    def update_progress(self, value: int):
        """Update progress bar value."""
        self._progress_bar.setValue(value)

    def finish_progress(self, message: str = "Done"):
        """Hide progress bar and show completion message."""
        self._progress_bar.setVisible(False)
        self.status.setStyleSheet("")  # reset to theme default
        self.status.showMessage(message, 3000)
        self._flash_taskbar()

    # --- Tag panel toggle ---

    def _toggle_compact_mode(self):
        """Tab shortcut — hide/show tag panel + tray + tag bar together."""
        self._compact_mode = not self._compact_mode
        if self._compact_mode:
            # Save state then hide everything
            self._pre_compact = {
                "tag_panel": self.tag_panel.isVisible(),
                "tray": self._tray_open,
                "tag_bar": self.browser._tag_bar_frame.isVisible(),
            }
            self.tag_panel.hide()
            if hasattr(self, '_tags_toolbar_btn'):
                self._tags_toolbar_btn.blockSignals(True)
                self._tags_toolbar_btn.setChecked(False)
                self._tags_toolbar_btn.blockSignals(False)
            if self._tray_open:
                self._toggle_work_tray()
            self.browser._tag_bar_frame.setVisible(False)
            if hasattr(self.browser, '_tag_bar_toggle_btn'):
                btn = self.browser._tag_bar_toggle_btn
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.setText("▶ Filters")
                btn.blockSignals(False)
        else:
            pre = getattr(self, '_pre_compact', {})
            if pre.get("tag_panel", True):
                self.tag_panel.show()
                if hasattr(self, '_tags_toolbar_btn'):
                    self._tags_toolbar_btn.blockSignals(True)
                    self._tags_toolbar_btn.setChecked(True)
                    self._tags_toolbar_btn.blockSignals(False)
            if pre.get("tray", False):
                self._toggle_work_tray()
            if pre.get("tag_bar", True):
                self.browser._tag_bar_frame.setVisible(True)
                if hasattr(self.browser, '_tag_bar_toggle_btn'):
                    btn = self.browser._tag_bar_toggle_btn
                    btn.blockSignals(True)
                    btn.setChecked(True)
                    btn.setText("▼ Filters")
                    btn.blockSignals(False)

    def _toggle_all_panels(self):
        """Tab key — hide all side panels, or restore them if already hidden."""
        any_visible = (self.tag_panel.isVisible() or self._tray_open
                       or self._file_browser.isVisible())
        if any_visible:
            # Save state and hide all
            self._panels_were = {
                'tags': self.tag_panel.isVisible(),
                'tray': self._tray_open,
                'files': self._file_browser.isVisible(),
            }
            if self.tag_panel.isVisible():
                self._toggle_tag_panel()
            if self._tray_open:
                self._toggle_work_tray()
            if self._file_browser.isVisible():
                self._toggle_file_browser()
        else:
            # Restore previous state
            prev = getattr(self, '_panels_were', {'tags': True, 'tray': False, 'files': False})
            if prev.get('tags') and not self.tag_panel.isVisible():
                self._toggle_tag_panel()
            if prev.get('tray') and not self._tray_open:
                self._toggle_work_tray()
            if prev.get('files') and not self._file_browser.isVisible():
                self._toggle_file_browser()

    def _toggle_tag_panel(self):
        if self.tag_panel.isVisible():
            self.tag_panel.hide()
            self._toggle_tags_action.setText("Show Tag Panel")
            if hasattr(self, '_tags_toolbar_btn'):
                self._tags_toolbar_btn.setChecked(False)
        else:
            self.tag_panel.show()
            self._toggle_tags_action.setText("Hide Tag Panel")
            if hasattr(self, '_tags_toolbar_btn'):
                self._tags_toolbar_btn.setChecked(True)

    def _toggle_tag_panel_btn(self, checked):
        if checked != self.tag_panel.isVisible():
            self._toggle_tag_panel()

    def _on_toggle_tag_bar(self, on: bool):
        btn = self.browser._tag_bar_toggle_btn
        if btn.isChecked() != on:
            btn.setChecked(on)  # triggers _on_tag_bar_toggle which sets frame visibility

    def _on_browser_tag_bar_toggled(self, on: bool):
        if hasattr(self, '_toggle_tag_bar_action'):
            if self._toggle_tag_bar_action.isChecked() != on:
                self._toggle_tag_bar_action.blockSignals(True)
                self._toggle_tag_bar_action.setChecked(on)
                self._toggle_tag_bar_action.blockSignals(False)

    def _on_files_btn_toggled(self, checked):
        self._file_browser.setVisible(checked)
        self._settings.setValue("file_browser_visible", checked)
        self._toggle_file_browser_action.setChecked(checked)
        if checked and self._file_browser._project is None and self.project:
            self._file_browser.set_project(self.project)

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
                act = self._recent_projects_menu.addAction(
                    Path(p).name, lambda path=p: self._load_project_from(path))
                act.setData(p)
                act.setToolTip("Right-click to remove from list")
        if self._recent_projects_menu.isEmpty():
            self._recent_projects_menu.addAction("(none)").setEnabled(False)

        self._recent_folders_menu.clear()
        for f in self._get_recent("recent_folders"):
            if Path(f).exists():
                act = self._recent_folders_menu.addAction(
                    Path(f).name, lambda folder=f: self._open_recent_folder(folder))
                act.setData(f)
                act.setToolTip("Right-click to remove from list")
        if self._recent_folders_menu.isEmpty():
            self._recent_folders_menu.addAction("(none)").setEnabled(False)

    def _remove_recent_project(self, path: str):
        recents = self._get_recent("recent_projects")
        if path in recents:
            recents.remove(path)
            self._settings.setValue("recent_projects", recents)
            self._rebuild_recent_menus()

    def _remove_recent_folder(self, folder: str):
        recents = self._get_recent("recent_folders")
        if folder in recents:
            recents.remove(folder)
            self._settings.setValue("recent_folders", recents)
            self._rebuild_recent_menus()

    # ── Bookmarks ──────────────────────────────────────────────────────────

    def _get_bookmarks(self, key: str) -> list[str]:
        v = self._settings.value(key, [])
        return v if isinstance(v, list) else ([v] if v else [])

    def _rebuild_bookmarks_menu(self):
        self._bm_projects_menu.clear()
        for p in self._get_bookmarks("bookmarked_projects"):
            if Path(p).exists():
                self._bm_projects_menu.addAction(
                    Path(p).stem, lambda path=p: self._open_project_in_tab_from(path))
            else:
                act = self._bm_projects_menu.addAction(f"✕ {Path(p).stem}")
                act.setEnabled(False)
        if self._bm_projects_menu.isEmpty():
            self._bm_projects_menu.addAction("(none)").setEnabled(False)

        self._bm_collections_menu.clear()
        for c in self._get_bookmarks("bookmarked_collections"):
            if Path(c).exists():
                self._bm_collections_menu.addAction(
                    Path(c).stem, lambda path=c: self._restore_collection_interactive(path))
            else:
                act = self._bm_collections_menu.addAction(f"✕ {Path(c).stem}")
                act.setEnabled(False)
        if self._bm_collections_menu.isEmpty():
            self._bm_collections_menu.addAction("(none)").setEnabled(False)

    def _bookmark_current_project(self):
        if not self._project_path:
            self.status.showMessage("Save the project first before bookmarking", 3000)
            return
        bms = self._get_bookmarks("bookmarked_projects")
        if self._project_path not in bms:
            bms.append(self._project_path)
            self._settings.setValue("bookmarked_projects", bms)
            self._rebuild_bookmarks_menu()
        self.status.showMessage(f"Bookmarked: {Path(self._project_path).stem}", 2000)

    def _bookmark_current_collection(self):
        last = self._settings.value("last_collection", "")
        if not last or not Path(last).exists():
            self.status.showMessage("No saved collection to bookmark", 3000)
            return
        bms = self._get_bookmarks("bookmarked_collections")
        if last not in bms:
            bms.append(last)
            self._settings.setValue("bookmarked_collections", bms)
            self._rebuild_bookmarks_menu()
        self.status.showMessage(f"Bookmarked collection: {Path(last).stem}", 2000)

    def _open_project_in_tab_from(self, path: str):
        for i, slot in enumerate(self._project_slots):
            if slot["path"] == path:
                self._proj_tab_bar.setCurrentIndex(i)
                return
        project = Project.load(path)
        self._add_project_tab(project, path, Path(path).stem)

    def _restore_collection_interactive(self, path: str):
        if not self._restore_collection(path):
            QMessageBox.warning(self, "Open Collection",
                f"Could not load collection — some project files may be missing:\n{path}")

    def _manage_bookmarks(self):
        """Dialog to remove stale or unwanted bookmarks."""
        from PySide6.QtWidgets import QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("Manage Bookmarks")
        dlg.resize(500, 400)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("Projects:"))
        proj_list = QListWidget()
        for p in self._get_bookmarks("bookmarked_projects"):
            item = QListWidgetItem(f"{'✓' if Path(p).exists() else '✕'} {Path(p).stem}  —  {p}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            proj_list.addItem(item)
        layout.addWidget(proj_list)

        layout.addWidget(QLabel("Collections:"))
        coll_list = QListWidget()
        for c in self._get_bookmarks("bookmarked_collections"):
            item = QListWidgetItem(f"{'✓' if Path(c).exists() else '✕'} {Path(c).stem}  —  {c}")
            item.setData(Qt.ItemDataRole.UserRole, c)
            coll_list.addItem(item)
        layout.addWidget(coll_list)

        layout.addWidget(QLabel("Select items and press Delete to remove, or use the buttons below."))

        remove_btn = QPushButton("Remove Selected")
        def _remove():
            for lst, key in [(proj_list, "bookmarked_projects"), (coll_list, "bookmarked_collections")]:
                for item in lst.selectedItems():
                    bms = self._get_bookmarks(key)
                    p = item.data(Qt.ItemDataRole.UserRole)
                    if p in bms:
                        bms.remove(p)
                    self._settings.setValue(key, bms)
                    lst.takeItem(lst.row(item))
            self._rebuild_bookmarks_menu()
        remove_btn.clicked.connect(_remove)
        layout.addWidget(remove_btn)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.accept)
        layout.addWidget(btns)
        dlg.exec()

    def _load_project_from(self, path: str):
        # Create backup before loading
        import shutil
        bak = path + ".bak"
        try:
            shutil.copy2(path, bak)
        except Exception:
            pass
        self.project = Project.load(path)
        self._rebind_project(clear_folder_state=True)
        self._project_path = path
        self._watch_project()
        self._settings.setValue("last_project", path)
        self._add_recent_project(path)
        label = Path(path).stem
        self.setWindowTitle(f"DoxyEdit — {Path(path).name}")
        self._rename_proj_tab(label)
        if 0 <= self._current_slot < len(self._project_slots):
            self._project_slots[self._current_slot]["project"] = self.project
            self._project_slots[self._current_slot]["path"] = path
        self.status.showMessage(f"Opened {Path(path).name}")

    def _open_recent_folder(self, folder: str):
        n = self.browser.import_folder(folder)
        self._add_recent_folder(folder)
        self.status.showMessage(f"Opened folder: {Path(folder).name} ({n} images)")

    def _on_shortcut_changed(self, tag_id: str, key: str):
        """Register or clear a keyboard shortcut for a tag and save to project + global config."""
        from doxyedit.models import TAG_SHORTCUTS, TAG_ALL
        from doxyedit.config import get_config
        # Remove any existing binding for this tag
        for k, v in list(TAG_SHORTCUTS.items()):
            if v == tag_id:
                del TAG_SHORTCUTS[k]
        for k, v in list(self.project.custom_shortcuts.items()):
            if v == tag_id:
                del self.project.custom_shortcuts[k]
        if not key:
            if tag_id in TAG_ALL:
                cfg = get_config()
                cfg.set_shortcut(key="", tag_id=tag_id)
                cfg.save()
            self._dirty = True
            if self._project_path:
                self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1; self.project.save(self._project_path)
            self.status.showMessage(f"Shortcut cleared for {tag_id}", 2000)
            return
        if key in TAG_SHORTCUTS:
            del TAG_SHORTCUTS[key]
        TAG_SHORTCUTS[key] = tag_id
        self.project.custom_shortcuts[key] = tag_id
        # Persist to global config for built-in tags so it survives new projects
        if tag_id in TAG_ALL:
            cfg = get_config()
            cfg.set_shortcut(key, tag_id)
            cfg.save()
        self._dirty = True
        if self._project_path:
            self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1; self.project.save(self._project_path)
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

    def _refresh_all_tags(self):
        """Rebuild both tag locations: browser tag bar + side panel."""
        self.browser.rebuild_tag_bar()
        self.tag_panel.refresh_discovered_tags(self.project.assets, self.project)
        self.tag_panel.update_tag_counts(self.project.assets)
        if hasattr(self, '_info_panel'):
            tag_ids = sorted(self.project.get_tags().keys()) if self.project else []
            self._info_panel.set_available_tags(tag_ids)

    def _on_tags_modified(self):
        """Browser added/removed a custom tag — sync both tag locations."""
        self._refresh_all_tags()
        self._dirty = True

    def _toggle_work_tray(self):
        is_open = self._tray_open
        if is_open:
            self._tray_open = False
            self._saved_tray_sizes = self._main_split.sizes()
            self.work_tray.hide()
            self._toggle_tray_action.setText("Show Work Tray")
            self._tray_btn.setChecked(False)
            if hasattr(self, '_tray_toolbar_btn'):
                self._tray_toolbar_btn.blockSignals(True)
                self._tray_toolbar_btn.setChecked(False)
                self._tray_toolbar_btn.blockSignals(False)
            if hasattr(self, '_menubar_tray_btn'):
                self._menubar_tray_btn.setChecked(False)
        else:
            self._tray_open = True
            self.work_tray.setMinimumWidth(150)
            self.work_tray.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX — no limit
            self.work_tray._content.show()
            self.work_tray.show()
            if self._saved_tray_sizes:
                self._main_split.setSizes(self._saved_tray_sizes)
            else:
                sizes = self._main_split.sizes()
                if len(sizes) > 1 and sizes[1] < 150:
                    sizes[1] = 200
                    self._main_split.setSizes(sizes)
            self._toggle_tray_action.setText("Hide Work Tray")
            self._tray_btn.setChecked(True)
            if hasattr(self, '_tray_toolbar_btn'):
                self._tray_toolbar_btn.blockSignals(True)
                self._tray_toolbar_btn.setChecked(True)
                self._tray_toolbar_btn.blockSignals(False)
            if hasattr(self, '_menubar_tray_btn'):
                self._menubar_tray_btn.setChecked(True)

    def _toggle_dock_preview(self):
        vis = not self._preview_pane.isVisible()
        self._preview_pane.setVisible(vis)
        self._settings.setValue("preview_docked", vis)
        self._toggle_dock_preview_action.setChecked(vis)

    def _popout_preview(self):
        """Pop out the docked preview to a floating window."""
        asset = self._preview_pane._asset
        if not asset:
            return
        # Hide docked pane
        self._preview_pane.hide()
        self._settings.setValue("preview_docked", False)
        self._toggle_dock_preview_action.setChecked(False)
        # Open floating preview with same asset
        self._on_asset_preview(asset.id)

    def _toggle_info_panel(self):
        """Ctrl+I — toggle info panel visibility in the sidebar."""
        vis = not self._info_panel.isVisible()
        self._info_panel.setVisible(vis)

    def _toggle_file_browser(self):
        vis = not self._file_browser.isVisible()
        self._file_browser.setVisible(vis)
        self._settings.setValue("file_browser_visible", vis)
        self._toggle_file_browser_action.setChecked(vis)
        if vis and self._file_browser._project is None and self.project:
            self._file_browser.set_project(self.project)
        if hasattr(self.browser, '_files_btn'):
            self.browser._files_btn.setChecked(self._file_browser.isVisible())

    def _on_file_browser_folder(self, folder: str):
        """Filter main grid to show assets from this folder and all subfolders."""
        folder = folder.replace("\\", "/").rstrip("/")
        prefix = folder + "/"
        # Collect this folder + any subfolders that have assets
        matching = [folder]
        if self.project:
            for asset in self.project.assets:
                af = (asset.source_folder or str(Path(asset.source_path).parent)).replace("\\", "/")
                if af.startswith(prefix) and af not in matching:
                    matching.append(af)
        self.browser.set_folder_filter(matching)

    def _clear_file_browser_filter(self):
        """Clear any folder filter on the main grid."""
        self.browser.set_folder_filter(None)
        self._file_browser.clear_active()

    def _refresh_file_browser(self):
        """Refresh file browser counts after project data changes."""
        if hasattr(self, '_file_browser') and self._file_browser.isVisible() and self.project:
            self._file_browser._update_folder_counts()
            self._file_browser._tree.viewport().update()

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

    def _feed_tray_pixmaps(self, asset_ids: list):
        """Feed cached pixmaps to tray items after tab switch."""
        for aid in asset_ids:
            pm = self.browser._thumb_cache.get(aid)
            if pm:
                self.work_tray.update_pixmap(aid, pm)

    def _send_single_to_tray(self, asset_id: str):
        asset = self.project.get_asset(asset_id)
        if asset:
            if not self.work_tray.isVisible():
                self._toggle_work_tray()
            pm = self.browser._thumb_cache.get(asset_id)
            self.work_tray.add_asset(asset_id, asset.name, pm, path=asset.source_path)

    # --- Tag management ---

    def _on_tag_color_changed(self, tag_id: str, hex_color: str):
        if tag_id in self.project.tag_definitions:
            self.project.tag_definitions[tag_id]["color"] = hex_color
        else:
            self.project.tag_definitions[tag_id] = {"label": tag_id, "color": hex_color}
        for ct in self.project.custom_tags:
            if isinstance(ct, dict) and ct.get("id") == tag_id:
                ct["color"] = hex_color
        # If this is a built-in tag, also persist to global config
        from doxyedit.models import TAG_ALL
        from doxyedit.config import get_config
        if tag_id in TAG_ALL:
            cfg = get_config()
            cfg.set_tag_preset(tag_id, color=hex_color)
            cfg.save()
        self.browser.rebuild_tag_bar()
        self._dirty = True

    def _on_tag_reordered(self, tag_id: str, new_order: int):
        """Persist reorder index to tag_definitions so section order survives reload."""
        if tag_id not in self.project.tag_definitions:
            self.project.tag_definitions[tag_id] = {"label": tag_id}
        self.project.tag_definitions[tag_id]["order"] = new_order
        self._dirty = True

    def _on_tag_section_changed(self, tag_id: str, new_section: str):
        """Persist section assignment when a tag is dragged between groups."""
        if tag_id not in self.project.tag_definitions:
            self.project.tag_definitions[tag_id] = {"label": tag_id}
        self.project.tag_definitions[tag_id]["section"] = new_section
        self._dirty = True

    def _on_batch_apply_tags(self, tag_ids: list):
        """Apply a list of tag IDs to all currently selected assets."""
        sel = self.browser.selected_ids()
        if not sel or not tag_ids:
            return
        asset_map = {a.id: a for a in self.project.assets if a.id in sel}
        for asset in asset_map.values():
            for tid in tag_ids:
                if tid not in asset.tags:
                    asset.tags.append(tid)
        self.tag_panel.set_assets(list(asset_map.values()))
        self.browser.refresh()
        self._dirty = True

    def _on_tag_deleted(self, tag_id: str):
        """Remove a tag from ALL assets in the project, not just selected."""
        for asset in self.project.assets:
            if tag_id in asset.tags:
                asset.tags.remove(tag_id)
        # Remove from custom tags and tag_definitions
        self.project.custom_tags = [
            ct for ct in self.project.custom_tags if ct.get("id") != tag_id
        ]
        self.project.tag_definitions.pop(tag_id, None)
        self._refresh_all_tags()
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
        # Update custom tags and tag_definitions
        for ct in self.project.custom_tags:
            if isinstance(ct, dict) and ct.get("id") == old_id:
                ct["id"] = new_id
                ct["label"] = new_label
        if old_id in self.project.tag_definitions:
            defn = self.project.tag_definitions.pop(old_id)
            defn["label"] = new_label
            self.project.tag_definitions[new_id] = defn
        # Add alias so old references resolve on next load
        self.project.tag_aliases[old_id] = new_id
        # Remap any keyboard shortcut pointing at the old ID
        for key, tid in list(TAG_SHORTCUTS.items()):
            if tid == old_id:
                TAG_SHORTCUTS[key] = new_id
        for key, tid in list(self.project.custom_shortcuts.items()):
            if tid == old_id:
                self.project.custom_shortcuts[key] = new_id
        self._refresh_all_tags()
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
        self.project.tag_definitions.clear()
        self.tag_panel.set_assets([])
        self._refresh_all_tags()
        self.browser.refresh()
        self._dirty = True
        self.status.showMessage(f"Cleared all tags from {n} assets")

    # --- Data flow ---

    def _on_data_changed(self):
        self._dirty = True
        self._update_progress()

    # ---- Social media timeline handlers ----

    def _on_post_selected(self, post_id: str):
        """Open composer to edit an existing post."""
        post = self.project.get_post(post_id)
        if not post:
            return
        dlg = PostComposer(self.project, post=post, parent=self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.finished.connect(lambda result: self._on_composer_done(dlg, is_new=False))
        dlg.show()
        self._theme_dialog_titlebar(dlg)

    def _on_new_post(self):
        """Open composer to create a new post."""
        dlg = PostComposer(self.project, parent=self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.finished.connect(lambda result: self._on_composer_done(dlg, is_new=True))
        dlg.show()
        self._theme_dialog_titlebar(dlg)

    def _on_composer_done(self, dlg, is_new: bool):
        """Handle composer close — add or update post."""
        if dlg.result_post:
            if is_new:
                self.project.posts.append(dlg.result_post)
            self._dirty = True
            self._timeline.refresh()
            self._calendar_pane.refresh()
            self.platform_panel.refresh()

    def _on_sync_oneup(self):
        """Sync post statuses from OneUp API."""
        from doxyedit.oneup import get_client_from_config, OneUpClient
        from doxyedit.models import SocialPostStatus
        project_dir = str(Path(self._project_path).parent) if hasattr(self, '_project_path') else "."

        client = get_client_from_config(project_dir)
        if not client:
            key = (self.project.oneup_config or {}).get("api_key", "")
            if key:
                client = OneUpClient(key)
        if not client:
            self.statusBar().showMessage("No OneUp API key configured", 5000)
            return

        updated = 0
        for post in self.project.posts:
            if post.status == SocialPostStatus.QUEUED and post.oneup_post_id:
                result = client.get_post(post.oneup_post_id)
                if result.success:
                    rs = result.data.get("status", "")
                    if rs == "published":
                        post.status = SocialPostStatus.POSTED
                        updated += 1
                    elif rs == "failed":
                        post.status = SocialPostStatus.FAILED
                        updated += 1

        if updated:
            self._dirty = True
            self._timeline.refresh()
            self._calendar_pane.refresh()
        self.statusBar().showMessage(f"Synced: {updated} post(s) updated", 3000)

    def _on_calendar_day_selected(self, iso_date: str):
        """Filter timeline to show only posts for the selected day."""
        self._timeline.set_day_filter(iso_date)

    def _on_calendar_day_cleared(self):
        """Clear timeline day filter — show all posts."""
        self._timeline.set_day_filter(None)

    def _on_asset_selected(self, asset_id: str):
        asset = self.project.get_asset(asset_id)
        if asset:
            self.censor_editor.load_asset(asset)
            self.tag_panel.set_assets([asset])
            # Update docked preview if visible
            if self._preview_pane.isVisible():
                filtered = self.browser._filtered_assets
                try:
                    idx = next(i for i, a in enumerate(filtered) if a.id == asset_id)
                except StopIteration:
                    idx = 0
                self._preview_pane.show_asset(asset, filtered, idx)
            if self._file_browser.isVisible():
                folder = asset.source_folder or str(Path(asset.source_path).parent)
                self._file_browser.highlight_folder(folder)
            self._info_panel.set_assets([asset])
            name = Path(asset.source_path).name
            n_tags = len(asset.tags)
            tag_hint = f" | {n_tags} tags" if n_tags else " | press 1-9 to tag, or use panel ->"
            self.status.showMessage(f"Selected: {name}{tag_hint}")

    def _assign_selected_to_slot(self, platform_id: str, slot_name: str):
        """Assign the selected asset (tray first, then browser) to a platform slot."""
        asset_id = None
        tray_items = self.work_tray._list.selectedItems()
        if tray_items:
            asset_id = tray_items[0].data(Qt.ItemDataRole.UserRole)
        if not asset_id and self.browser._selected_ids:
            asset_id = next(iter(self.browser._selected_ids))
        if not asset_id:
            self.status.showMessage("Select an asset in the tray or browser first", 3000)
            return
        asset = self.project.get_asset(asset_id)
        if not asset:
            return
        self.platform_panel.assign_asset(asset, platform_id, slot_name)
        self._dirty = True
        self.status.showMessage(
            f"Assigned {Path(asset.source_path).name} → {slot_name}", 2000)

    def _on_inner_tab_changed(self, idx: int):
        widget = self.tabs.widget(idx)
        if widget is self._overview_split:
            self.stats_panel.folder_bar_color = self._theme.accent_bright
            self.stats_panel.refresh()
            self._refresh_project_info()

    def _refresh_project_info(self):
        p = self.project
        t = self._theme

        bg   = t.bg_deep
        fg   = t.text_primary
        fg2  = t.text_secondary
        muted = t.text_muted
        accent = t.accent_bright
        code_bg = "rgba(255,255,255,0.07)"

        def esc(s):
            return _html.escape(str(s))

        def section(title, count=None):
            c = f" <span style='color:{muted}'>({count})</span>" if count is not None else ""
            return (f"<p style='margin:14px 0 4px; font-weight:bold; color:{accent};"
                    f" border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:3px'>"
                    f"{esc(title)}{c}</p>")

        def code(s):
            return (f"<code style='font-family:Consolas,monospace; font-size:11px;"
                    f" background:{code_bg}; padding:1px 4px; border-radius:3px;"
                    f" word-break:break-all'>{esc(s)}</code>")

        body = []

        # ── Summary ─────────────────────────────────────────────────────
        body.append(section("Project"))
        body.append(f"<table style='border-spacing:0 2px'>")
        body.append(f"<tr><td style='color:{fg2}; padding-right:12px'>Name</td>"
                    f"<td>{code(p.name)}</td></tr>")
        if self._project_path:
            body.append(f"<tr><td style='color:{fg2}; padding-right:12px'>File</td>"
                        f"<td>{code(self._project_path)}</td></tr>")
        body.append(f"<tr><td style='color:{fg2}; padding-right:12px'>Assets</td>"
                    f"<td><b>{len(p.assets)}</b></td></tr>")
        body.append("</table>")

        # ── Source folders ───────────────────────────────────────────────
        folder_assets: dict[str, list] = defaultdict(list)
        solo_files = []
        for a in p.assets:
            if a.source_folder:
                folder_assets[a.source_folder].append(a)
            else:
                solo_files.append(a)

        if folder_assets:
            # Build import-source roots for hierarchy
            import_roots = [src["path"] for src in p.import_sources
                            if src.get("type") == "folder"]

            def find_root(folder):
                best, best_len = None, 0
                for root in import_roots:
                    try:
                        Path(folder).relative_to(root)
                        if len(Path(root).parts) > best_len:
                            best, best_len = root, len(Path(root).parts)
                    except ValueError:
                        pass
                return best

            # Group folders under their import root
            root_children: dict[str, list] = defaultdict(list)
            orphans = []
            for folder in sorted(folder_assets):
                root = find_root(folder)
                if root:
                    root_children[root].append(folder)
                else:
                    orphans.append(folder)

            body.append(section("Source Folders", len(folder_assets)))
            body.append("<table style='border-spacing:0 1px; width:100%'>")

            # Roots with children
            for root in import_roots:
                children = root_children.get(root, [])
                if not children:
                    continue
                root_total = sum(len(folder_assets[f]) for f in children)
                root_name = esc(Path(root).name)
                body.append(
                    f"<tr><td colspan='2' style='padding:6px 0 2px; font-weight:bold;"
                    f" color:{accent}'>{root_name}"
                    f" <span style='color:{muted}; font-weight:normal'>"
                    f"· {root_total} assets</span></td></tr>")
                for folder in children:
                    count = len(folder_assets[folder])
                    try:
                        rel = str(Path(folder).relative_to(root))
                    except ValueError:
                        rel = Path(folder).name
                    body.append(
                        f"<tr><td style='padding:1px 10px 1px 16px; color:{fg2}'>"
                        f"{code(rel)}</td>"
                        f"<td style='color:{muted}; white-space:nowrap'>{count} file(s)</td></tr>")

            # Orphan folders (no matching import root)
            for folder in orphans:
                count = len(folder_assets[folder])
                body.append(
                    f"<tr><td style='padding:1px 10px 1px 0'>{code(folder)}</td>"
                    f"<td style='color:{muted}; white-space:nowrap'>{count} file(s)</td></tr>")
            body.append("</table>")

        if solo_files:
            body.append(section("Individual Files", len(solo_files)))
            for a in solo_files:
                body.append(f"{code(a.source_path)}<br>")

        # ── Tags ─────────────────────────────────────────────────────────
        tags = p.tag_definitions
        if tags:
            body.append(section("Tags", len(tags)))
            body.append("<table style='border-spacing:0 1px'>")
            for tid, defn in tags.items():
                label = defn.get('label', tid) if isinstance(defn, dict) else tid
                body.append(
                    f"<tr><td style='padding-right:12px'>{code(tid)}</td>"
                    f"<td style='color:{fg2}'>{esc(label)}</td></tr>")
            body.append("</table>")

        # ── Platforms ────────────────────────────────────────────────────
        if p.platforms:
            body.append(section("Platforms", len(p.platforms)))
            body.append(f"<p style='margin:2px 0'>" +
                        "  ".join(code(pl) for pl in p.platforms) + "</p>")

        fs = self._theme.font_size
        html = (f"<html><head><style>"
                f"body{{background:{bg};color:{fg};font-family:'Segoe UI',sans-serif;"
                f"padding:16px 20px;font-size:{fs}px;line-height:1.5}}"
                f"</style></head><body>{''.join(body)}</body></html>")
        self._project_info_panel.setHtml(html)

    def _navigate_to_asset(self, asset_id: str):
        """Switch to Assets tab and scroll to the given asset."""
        self.tabs.setCurrentWidget(self._browse_split)
        self.browser.scroll_to_asset(asset_id)

    def _remove_missing_files(self):
        """Remove all asset records whose source file no longer exists."""
        missing = [a for a in self.project.assets if not Path(a.source_path).exists()]
        if not missing:
            self.status.showMessage("No missing files found.", 3000)
            return
        n = len(missing)
        reply = QMessageBox.question(
            self, "Remove Missing Files",
            f"Remove {n} asset record(s) whose source file no longer exists?\n\n"
            "This cannot be undone. Source files themselves are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        missing_ids = {a.id for a in missing}
        self.project.assets = [a for a in self.project.assets if a.id not in missing_ids]
        self.project.invalidate_index()
        self._after_missing_removed(n)

    def _on_missing_removed(self, count: int):
        self._after_missing_removed(count)

    def _after_missing_removed(self, count: int):
        self.browser.refresh()
        self._dirty = True
        self.status.showMessage(f"Removed {count} missing asset record(s).", 4000)

    def _on_asset_preview(self, asset_id: str):
        asset = self.project.get_asset(asset_id)
        if not asset:
            return
        filtered = self.browser._filtered_assets
        try:
            idx = next(i for i, a in enumerate(filtered) if a.id == asset_id)
        except StopIteration:
            idx = 0
        # Reuse existing dialog if still open
        dlg = getattr(self, '_preview_dlg', None)
        if dlg is not None:
            try:
                if dlg.isVisible():
                    dlg.jump_to(asset, filtered, idx)
                    return
            except RuntimeError:
                # C++ object was deleted without firing finished signal
                self._preview_dlg = None
                dlg = None
        dlg = ImagePreviewDialog(
            asset.source_path, asset=asset, parent=self,
            assets=filtered, current_index=idx)
        dlg.setStyleSheet(self.styleSheet())
        dlg.update_theme(self._theme)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.finished.connect(self._on_preview_closed)
        dlg.navigated.connect(self._navigate_to_asset_in_browser)
        self._preview_dlg = dlg
        dlg.show()
        self._theme_dialog_titlebar(dlg)

    def _on_preview_closed(self):
        self._preview_dlg = None

    def _on_fast_cache_toggled(self, on: bool):
        self._settings.setValue("fast_cache", int(on))
        self.browser._thumb_cache._disk_cache.set_fast_cache(on)

    def _set_lru_max(self, n: int):
        self._settings.setValue("lru_max", n)
        self.browser._thumb_cache.set_lru_max(n)
        self.status.showMessage(f"Memory cache set to {n} thumbnails", 3000)

    def _navigate_to_asset_in_browser(self, asset_id: str):
        """Select an asset in the browser while preview dialog is open."""
        self.browser.scroll_to_asset(asset_id)

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
        assets = [a for aid in asset_ids if (a := self.project.get_asset(aid))]
        self.tag_panel.set_assets(assets)
        self._info_panel.set_assets(assets)
        n = len(assets)
        if n == 0:
            self.status.showMessage("No selection")
        elif n == 1:
            name = Path(assets[0].source_path).name
            self.status.showMessage(f"Selected: {name} | press 1-9 to tag")
        else:
            self.status.showMessage(f"{n} selected — press 1-9 to batch tag, Ctrl+click to add/remove")

    # --- Canvas tools ---

    def _sync_menubar_tabs(self, index: int):
        for i, btn in enumerate(self._menubar_tab_btns):
            btn.setChecked(i == index)

    def _on_tab_changed(self, index: int):
        """Show/hide canvas tools based on active tab."""
        on_canvas = index == 1  # Canvas tab
        self._canvas_sep_before.setVisible(on_canvas)
        for action, _ in self._tool_actions:
            action.setVisible(on_canvas)
        self._color_action.setVisible(on_canvas)
        self._canvas_sep_after.setVisible(on_canvas)

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

    def _rename_selected(self):
        """F2 — rename the selected file on disk and update the project."""
        if self.tabs.currentIndex() != 0:
            return
        assets = self.browser.get_selected_assets()
        if len(assets) != 1:
            self.status.showMessage("Select exactly one asset to rename", 2000)
            return
        asset = assets[0]
        old_path = Path(asset.source_path)
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "Rename File", "New filename:", text=old_path.name)
        if not ok or not new_name.strip() or new_name.strip() == old_path.name:
            return
        new_path = old_path.parent / new_name.strip()
        try:
            os.rename(old_path, new_path)
        except OSError as e:
            QMessageBox.warning(self, "Rename Failed", str(e))
            return
        asset.source_path = str(new_path)
        self.browser._thumb_cache.invalidate(asset.id)
        self.browser.refresh()
        self._dirty = True
        self.status.showMessage(f"Renamed → {new_path.name}", 3000)

    def _handle_delete(self):
        """Delete key — context-aware. Assets tab: soft-delete. Canvas: remove items."""
        if self.tabs.currentIndex() == 0:
            # Assets tab — tag selected as "ignore" (soft delete) and permanently exclude
            assets = self.browser.get_selected_assets()
            if not assets:
                return
            for a in assets:
                if "ignore" not in a.tags:
                    a.tags.append("ignore")
                self.project.excluded_paths.add(a.source_path)
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
            self.browser.active_view.selectAll()

    def _copy_as_files(self):
        """Ctrl+C — copy selected assets as file objects (Explorer-compatible)."""
        if self.tabs.currentIndex() != 0:
            return
        assets = self.browser.get_selected_assets()
        if not assets:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(a.source_path) for a in assets])
        QApplication.clipboard().setMimeData(mime)
        n = len(assets)
        self.status.showMessage(f"Copied {n} file{'s' if n != 1 else ''}", 2000)

    def _copy_full_path(self):
        """Ctrl+Shift+C — copy selected asset paths as plain text."""
        if self.tabs.currentIndex() != 0:
            return
        assets = self.browser.get_selected_assets()
        if not assets:
            return
        paths = "\n".join(a.source_path for a in assets)
        QApplication.clipboard().setText(paths)
        n = len(assets)
        self.status.showMessage(f"Copied {n} path{'s' if n != 1 else ''}", 2000)

    def _select_none(self):
        if self.tabs.currentIndex() == 0:
            self.browser.active_view.clearSelection()

    def _clear_unused_tags(self):
        """Remove tag definitions and custom tags not used by any asset."""
        from doxyedit.models import TAG_PRESETS, TAG_SIZED
        used = {t for a in self.project.assets for t in a.tags}
        removed = []
        # Clean tag_definitions
        for tid in list(self.project.tag_definitions.keys()):
            if tid not in used:
                del self.project.tag_definitions[tid]
                removed.append(tid)
        # Clean custom_tags list
        self.project.custom_tags = [
            ct for ct in self.project.custom_tags
            if not isinstance(ct, dict) or ct.get("id") in used
        ]
        # Also remove panel rows for auto-discovered tags not in any asset
        # (tags that exist in the panel but never made it into tag_definitions)
        for tid in list(self.tag_panel._rows.keys()):
            if tid not in used and tid not in TAG_PRESETS and tid not in TAG_SIZED:
                if tid not in removed:
                    removed.append(tid)
        if removed:
            self.tag_panel.remove_tag_rows(removed)
            self.browser.rebuild_tag_bar()
            self._dirty = True
            self.status.showMessage(f"Removed {len(removed)} unused tag(s): {', '.join(removed)}")
        else:
            self.status.showMessage("No unused tags found")

    def _refresh_import_sources(self):
        """Re-scan all recorded folder sources and import any new files found since last import."""
        sources = self.project.import_sources
        folder_sources = [s for s in sources if s.get("type") == "folder"]
        if not folder_sources:
            self.status.showMessage("No folder sources recorded — import a folder first", 3000)
            return
        total = 0
        for rec in folder_sources:
            path = rec.get("path", "")
            recursive = rec.get("recursive", False)
            if not Path(path).exists():
                continue
            n = self.browser.import_folder(path, recursive=recursive)
            total += n
        if total:
            self._refresh_all_tags()
            self._dirty = True
            self.status.showMessage(f"Refresh: added {total} new file(s) from {len(folder_sources)} source(s)")
        else:
            self.status.showMessage("Refresh: no new files found")
        self._watch_import_folders()

    def _show_import_sources(self):
        """Show a dialog listing all recorded import sources."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QHBoxLayout, QHeaderView
        sources = self.project.import_sources
        dlg = QDialog(self)
        dlg.setWindowTitle("Import Sources")
        dlg.resize(700, 400)
        layout = QVBoxLayout(dlg)
        table = QTableWidget(len(sources), 5)
        table.setHorizontalHeaderLabels(["Type", "Path", "Recursive", "Last Imported", "Date Filter"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i, rec in enumerate(sources):
            table.setItem(i, 0, QTableWidgetItem(rec.get("type", "")))
            table.setItem(i, 1, QTableWidgetItem(rec.get("path", "")))
            table.setItem(i, 2, QTableWidgetItem("Yes" if rec.get("recursive") else "No"))
            table.setItem(i, 3, QTableWidgetItem(rec.get("last_imported", rec.get("added_at", ""))))
            df = rec.get("filter_newer_than", "")
            table.setItem(i, 4, QTableWidgetItem(f"Since {df[:10]}" if df else ""))
        layout.addWidget(table)
        btn_row = QHBoxLayout()
        btn_remove = QPushButton("Remove Selected")
        def _remove():
            rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
            for r in rows:
                self.project.import_sources.pop(r)
                table.removeRow(r)
            self._dirty = True
        btn_remove.clicked.connect(_remove)
        btn_row.addWidget(btn_remove)
        btn_set_filter = QPushButton("Set Date Filter...")
        def _set_filter():
            rows = sorted({idx.row() for idx in table.selectedIndexes()})
            if not rows:
                return
            from doxyedit.browser import _ImportOptionsDialog
            fdlg = _ImportOptionsDialog(dlg)
            if fdlg.exec() != QDialog.DialogCode.Accepted:
                return
            new_filter = fdlg.filter_date
            for r in rows:
                sources[r]["filter_newer_than"] = new_filter
                table.setItem(r, 4, QTableWidgetItem(f"Since {new_filter[:10]}" if new_filter else ""))
            self._dirty = True
        btn_set_filter.clicked.connect(_set_filter)
        btn_row.addWidget(btn_set_filter)
        btn_refresh = QPushButton("Refresh Now")
        btn_refresh.clicked.connect(lambda: (dlg.accept(), self._refresh_import_sources()))
        btn_row.addWidget(btn_refresh)
        btn_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)
        dlg.exec()

    def _remove_assets_by_ids(self, ids: set):
        """Remove assets from current project by ID and refresh."""
        self.project.assets = [a for a in self.project.assets if a.id not in ids]
        self.project.invalidate_index()
        self._refresh_all_tags()
        self.browser.refresh()
        self._dirty = True
        self._refresh_file_browser()

    def _move_to_project(self):
        """Move selected assets to another .doxyproj.json file."""
        assets = self.browser.get_selected_assets()
        if not assets:
            self.status.showMessage("Select assets to move first", 2000)
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Move to Project", "", "DoxyEdit Projects (*.doxyproj.json)")
        if not path:
            return
        try:
            target = Project.load(path)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not load project:\n{e}")
            return
        existing_paths = {a.source_path for a in target.assets}
        moved = 0
        ids_to_remove = set()
        for a in assets:
            if a.source_path not in existing_paths:
                target.assets.append(a)
                moved += 1
            ids_to_remove.add(a.id)
            self.project.excluded_paths.add(a.source_path)
        target.save(path)
        self._remove_assets_by_ids(ids_to_remove)
        self.status.showMessage(f"Moved {moved} asset(s) to {Path(path).name}")

    def _move_to_new_project(self):
        """Create a new .doxyproj.json and move selected assets into it."""
        assets = self.browser.get_selected_assets()
        if not assets:
            self.status.showMessage("Select assets to move first", 2000)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Create New Project", "", "DoxyEdit Projects (*.doxyproj.json)")
        if not path:
            return
        if not path.endswith(".doxyproj.json"):
            path += ".doxyproj.json"
        name = Path(path).stem.replace(".doxyproj", "")
        target = Project(name=name)
        ids_to_remove = {a.id for a in assets}
        for a in assets:
            self.project.excluded_paths.add(a.source_path)
        target.assets.extend(assets)
        target.save(path)
        self._remove_assets_by_ids(ids_to_remove)
        self.status.showMessage(f"Created '{name}' with {len(assets)} asset(s)")

    def _show_notes_overlay(self):
        """Shift+E: centered notes popup for the selected asset."""
        if self.tabs.currentIndex() != 0:
            return
        assets = self.browser.get_selected_assets()
        if len(assets) != 1:
            self.status.showMessage("Select a single asset to edit notes", 2000)
            return
        asset = assets[0]
        from PySide6.QtWidgets import QDialog, QTextEdit, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Notes — {asset.name}")
        dlg.resize(500, 300)
        lay = QVBoxLayout(dlg)
        edit = QTextEdit()
        edit.setPlainText(asset.notes or "")
        lay.addWidget(edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec():
            asset.notes = edit.toPlainText()
            self.tag_panel.set_assets([asset])
            self._dirty = True
            self.status.showMessage("Notes updated")

    def _select_all_with_tag(self, tag_id: str):
        """Select all assets in the grid that have the given tag."""
        sel = self.browser.active_view.selectionModel()
        sel.clearSelection()
        model = self.browser._model
        count = 0
        for i in range(model.rowCount()):
            idx = model.index(i)
            asset = model.get_asset(idx)
            if asset and tag_id in asset.tags:
                sel.select(idx, sel.SelectionFlag.Select)
                count += 1
        self.status.showMessage(f"Selected {count} asset(s) with tag '{tag_id}'")

    def _set_filename_display(self, mode: str):
        self.browser._delegate.show_filenames = mode
        for label, act in getattr(self, '_filenames_actions', {}).items():
            act.setChecked(act.text().lower().replace(" ", "_") == mode or
                           (mode == "always" and act.text() == "Always") or
                           (mode == "hover" and act.text() == "Hover Only") or
                           (mode == "never" and act.text() == "Never"))
        self.browser.active_view.viewport().update()
        for section in self.browser._folder_sections:
            section.view.viewport().update()

    def _toggle_dims(self, on: bool):
        self.browser._delegate.show_dims = on
        self.browser.active_view.viewport().update()

    def _toggle_fill_mode(self, on: bool):
        self.browser._delegate.fill_mode = on
        self.browser._delegate.invalidate_cache()
        self.browser.active_view.viewport().update()

    def _toggle_show_hidden_only(self, checked: bool):
        self.browser.show_hidden_only = checked
        self.browser._refresh_grid()

    def _temp_hide_toggle(self):
        """Alt+H: hide selected assets temporarily, or unhide all if nothing selected."""
        if self.tabs.currentIndex() != 0:
            return
        assets = self.browser.get_selected_assets()
        if assets:
            ids = {a.id for a in assets}
            self.browser._temp_hidden_ids |= ids
            self.browser.active_view.clearSelection()
            self.browser._refresh_grid()
            n = len(ids)
            self.status.showMessage(f"Temporarily hidden {n} asset(s) — Alt+H with nothing selected to restore")
        elif self.browser._temp_hidden_ids:
            n = len(self.browser._temp_hidden_ids)
            self.browser._temp_hidden_ids.clear()
            self.browser._refresh_grid()
            self.status.showMessage(f"Restored {n} temporarily hidden asset(s)")

    def _invert_selection(self):
        if self.tabs.currentIndex() != 0:
            return
        model = self.browser._model
        sel = self.browser.active_view.selectionModel()
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
        tag_label = tag.strip()
        tag_id = tag_label  # preserve user's casing and spaces
        assets = self.browser.get_selected_assets()
        for a in assets:
            if tag_id not in a.tags:
                a.tags.append(tag_id)
        self._refresh_all_tags()
        self.tag_panel.set_assets(assets)
        self._dirty = True
        self.status.showMessage(f"Added '{tag_id}' to {len(assets)} asset(s)")

    def _reload_project(self):
        """Reload the current project file from disk (F5)."""
        if not self._project_path or not Path(self._project_path).exists():
            self.browser.refresh()
            self.status.showMessage("No project file to reload — refreshed grid", 2000)
            return
        # Preserve UI state across reload
        saved_filters = self.browser.get_filter_state()
        self.project = Project.load(self._project_path)
        self._rebind_project()
        self.browser.set_filter_state(saved_filters)
        self._dirty = False
        self.status.showMessage(f"Reloaded project from disk", 2000)

    def _refresh_thumbs(self):
        """Force-regenerate all thumbnails, bypassing disk cache."""
        cache = self.browser._thumb_cache
        cache.clear_queue()
        cache._pixmaps.clear()
        cache._gen_sizes.clear()
        cache._dims.clear()
        self.browser._delegate.invalidate_cache()
        # Re-request visible items with force=True so disk cache is bypassed
        assets = self.browser._filtered_assets
        batch = [(a.id, a.source_path) for a in assets]
        cache.request_batch(batch, size=self.browser._thumb_size, force=True)
        self.status.showMessage("Refreshing thumbnails (bypassing cache)...", 2000)

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

    def _edit_project_config(self):
        """Open or create config.yaml for the current project."""
        if not self._project_path:
            self.status.showMessage("Save the project first", 3000)
            return
        from doxyedit.models import CONFIG_TEMPLATE
        config_path = Path(self._project_path).parent / "config.yaml"
        if not config_path.exists():
            config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
            self.status.showMessage(f"Created {config_path.name} — edit and reload project", 3000)
        import os
        os.startfile(str(config_path))

    def _open_project_location(self):
        if self._project_path:
            import subprocess
            path = self._project_path.replace("/", "\\")
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            self.status.showMessage("Save the project first", 2000)

    def _on_local_mode_toggled(self, on: bool):
        self.project.local_mode = on
        self._dirty = True
        self.status.showMessage(
            "Local mode ON — paths saved relative to project file (repo-safe)" if on
            else "Local mode OFF — paths saved as absolute", 4000)

    def _on_shared_cache_toggled(self, shared: bool):
        self._settings.setValue("shared_cache", "true" if shared else "false")
        # Re-apply immediately
        name = "shared" if shared else self.project.name
        self.browser._thumb_cache.set_project(name)
        self.status.showMessage(
            "Cache: shared (all projects use one folder)" if shared
            else "Cache: per-project (each project has its own folder)", 4000)

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

    def _find_duplicates(self):
        """Hash all project assets and show a dialog of duplicate groups with action options."""
        import hashlib
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel

        self.status.showMessage("Scanning for duplicates...", 0)
        QApplication.processEvents()

        # Build hash → [asset] map
        hashes: dict[str, list] = {}
        for asset in self.project.assets:
            p = Path(asset.source_path)
            if not p.exists():
                continue
            try:
                h = hashlib.md5(p.read_bytes()).hexdigest()
            except OSError:
                continue
            hashes.setdefault(h, []).append(asset)

        dupe_groups = [assets for assets in hashes.values() if len(assets) > 1]
        total_dupes = sum(len(g) - 1 for g in dupe_groups)  # extras beyond the first in each group
        self.status.showMessage(
            f"Found {len(dupe_groups)} duplicate group(s) ({total_dupes} extras)"
            if dupe_groups else "No duplicates found", 3000)

        dlg = QDialog(self)
        dlg.setWindowTitle("Duplicate Files")
        dlg.resize(640, 460)
        layout = QVBoxLayout(dlg)

        summary = QLabel(
            f"{len(dupe_groups)} duplicate group(s) — {total_dupes} extra copies"
            if dupe_groups else "No duplicate files found.")
        summary.setProperty("role", "muted")
        layout.addWidget(summary)

        text = QTextEdit()
        text.setReadOnly(True)
        if dupe_groups:
            lines = []
            for i, group in enumerate(dupe_groups, 1):
                lines.append(f"Group {i}  (keep: {Path(group[0].source_path).name})")
                for j, asset in enumerate(group):
                    marker = "  ✓ keep" if j == 0 else "  ✗ dupe"
                    lines.append(f"    {marker}  {asset.source_path}")
            text.setPlainText("\n".join(lines))
        else:
            text.setPlainText("No duplicate files found.")
        layout.addWidget(text, 1)

        if dupe_groups:
            note = QLabel("Actions apply to all extras (all but the first in each group).")
            note.setProperty("role", "muted")
            layout.addWidget(note)

        btn_row = QHBoxLayout()

        if dupe_groups:
            tag_btn = QPushButton("Tag as 'duplicate'")
            tag_btn.setToolTip("Add a 'duplicate' tag to every extra copy")
            def _tag_dupes():
                # Ensure the tag exists
                if "duplicate" not in self.project.tag_definitions:
                    self.project.tag_definitions["duplicate"] = {"label": "Duplicate", "color": "#e06c6c"}
                n = 0
                for group in dupe_groups:
                    for asset in group[1:]:
                        if "duplicate" not in asset.tags:
                            asset.tags.append("duplicate")
                            n += 1
                self.project.invalidate_index()
                self.browser._refresh_grid()
                self._dirty = True
                self.status.showMessage(f"Tagged {n} assets as 'duplicate'", 3000)
                dlg.accept()
            tag_btn.clicked.connect(_tag_dupes)
            btn_row.addWidget(tag_btn)

            remove_btn = QPushButton("Remove Extras from Project")
            remove_btn.setToolTip("Remove all but the first copy of each duplicate from the project (files stay on disk)")
            def _remove_dupes():
                extra_ids = {asset.id for group in dupe_groups for asset in group[1:]}
                reply = QMessageBox.question(
                    dlg, "Remove Duplicates",
                    f"Remove {len(extra_ids)} extra asset record(s) from the project?\n\n"
                    "The files themselves will NOT be deleted from disk.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
                if reply != QMessageBox.StandardButton.Yes:
                    return
                self.project.assets = [a for a in self.project.assets if a.id not in extra_ids]
                self.project.invalidate_index()
                self.browser._refresh_grid()
                self._dirty = True
                self.status.showMessage(f"Removed {len(extra_ids)} duplicate asset records", 3000)
                dlg.accept()
            remove_btn.clicked.connect(_remove_dupes)
            btn_row.addWidget(remove_btn)

        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dlg.exec()

    def _find_similar(self):
        """Find visually similar images using perceptual hash comparison."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel, QMessageBox

        # Collect phash values
        hashmap = []  # (asset, phash_int)
        missing = 0
        for asset in self.project.assets:
            ph = asset.specs.get("phash")
            if ph is not None:
                hashmap.append((asset, ph))
            else:
                missing += 1

        if not hashmap:
            QMessageBox.information(self, "Find Similar",
                "No perceptual hashes computed yet.\nBrowse through your thumbnails first — hashes are computed during thumbnail generation.")
            return

        # Hamming distance
        def hamming(a, b):
            return bin(a ^ b).count('1')

        # Union-find grouping with threshold of 8 bits
        threshold = 8
        n = len(hashmap)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            a, b = find(a), find(b)
            if a != b:
                parent[a] = b

        for i in range(n):
            for j in range(i + 1, n):
                if hamming(hashmap[i][1], hashmap[j][1]) <= threshold:
                    union(i, j)

        # Collect groups
        groups_dict = {}
        for i in range(n):
            root = find(i)
            groups_dict.setdefault(root, []).append(hashmap[i][0])

        similar_groups = [g for g in groups_dict.values() if len(g) > 1]
        total_variants = sum(len(g) - 1 for g in similar_groups)

        if not similar_groups:
            msg = f"No similar images found among {len(hashmap)} assets (threshold: {threshold} bits)."
            if missing:
                msg += f"\n{missing} assets have no hash yet — browse thumbnails to compute them."
            QMessageBox.information(self, "Find Similar", msg)
            return

        # Build results text
        lines = [f"Found {len(similar_groups)} group(s) with {total_variants} variant(s)\n"]
        if missing:
            lines.append(f"({missing} assets not yet hashed — browse thumbnails to include them)\n")
        variant_ids = set()
        for gi, group in enumerate(similar_groups, 1):
            # Sort by file size descending — largest is likely canonical
            group.sort(key=lambda a: -os.path.getsize(a.source_path) if os.path.exists(a.source_path) else 0)
            lines.append(f"--- Group {gi} ({len(group)} files) ---")
            for ai, asset in enumerate(group):
                marker = "✓ keep" if ai == 0 else "✗ variant"
                lines.append(f"  [{marker}] {Path(asset.source_path).name}")
                if ai > 0:
                    variant_ids.add(asset.id)
            lines.append("")

        # Dialog
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Similar Images — {len(similar_groups)} group(s)")
        dlg.resize(600, 450)
        layout = QVBoxLayout(dlg)

        summary = QLabel(f"{len(similar_groups)} group(s) · {total_variants} variant(s) · {len(hashmap)} hashed")
        summary.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(summary)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n".join(lines))
        text.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        layout.addWidget(text)

        btn_row = QHBoxLayout()

        tag_btn = QPushButton(f"Tag {total_variants} as 'variant'")
        def do_tag():
            # Create tag if needed
            if "variant" not in self.project.tag_definitions:
                self.project.tag_definitions["variant"] = {"label": "Variant", "color": "#c49b5c"}
                self.project.custom_tags.append({"id": "variant", "label": "Variant", "color": "#c49b5c"})
            for asset in self.project.assets:
                if asset.id in variant_ids and "variant" not in asset.tags:
                    asset.tags.append("variant")
            self._dirty = True
            self._refresh_all_tags()
            self.browser.refresh()
            self.status.showMessage(f"Tagged {len(variant_ids)} assets as 'variant'", 3000)
            dlg.accept()
        tag_btn.clicked.connect(do_tag)
        btn_row.addWidget(tag_btn)

        remove_btn = QPushButton(f"Remove {total_variants} variants from project")
        def do_remove():
            if QMessageBox.question(self, "Remove Variants",
                f"Remove {len(variant_ids)} variant assets from project?\n(Files remain on disk)") != QMessageBox.StandardButton.Yes:
                return
            self.project.assets = [a for a in self.project.assets if a.id not in variant_ids]
            self.project.invalidate_index()
            self._dirty = True
            self._refresh_all_tags()
            self.browser.refresh()
            self.status.showMessage(f"Removed {len(variant_ids)} variants", 3000)
            dlg.accept()
        remove_btn.clicked.connect(do_remove)
        btn_row.addWidget(remove_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)
        dlg.exec()

    def _mass_tag_editor(self):
        """Bulk edit tags on selected (or all) assets as comma-separated strings."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
            QTableWidgetItem, QDialogButtonBox, QLabel, QPushButton, QCheckBox)
        assets = self.browser.get_selected_assets() or self.project.assets
        if not assets:
            self.status.showMessage("No assets to edit", 2000)
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Mass Tag Editor — {len(assets)} assets")
        dlg.resize(700, 500)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Edit comma-separated tags per asset. Changes apply on Save."))

        table = QTableWidget(len(assets), 2)
        table.setHorizontalHeaderLabels(["File", "Tags (comma-separated)"])
        table.horizontalHeader().setSectionResizeMode(0, table.horizontalHeader().ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, table.horizontalHeader().ResizeMode.Stretch)
        for i, a in enumerate(assets):
            table.setItem(i, 0, QTableWidgetItem(Path(a.source_path).name))
            table.item(i, 0).setFlags(table.item(i, 0).flags() & ~table.item(i, 0).flags().__class__.ItemIsEditable)
            table.setItem(i, 1, QTableWidgetItem(", ".join(a.tags)))
        layout.addWidget(table)

        export_row = QHBoxLayout()
        export_btn = QPushButton("Export .txt sidecar files")
        export_btn.setToolTip("Write one .txt per image with its tags (AI training format)")
        export_row.addWidget(export_btn)
        export_row.addStretch()
        layout.addLayout(export_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                QDialogButtonBox.StandardButton.Close)
        layout.addWidget(btns)

        def _save():
            for i, a in enumerate(assets):
                cell = table.item(i, 1)
                if cell:
                    raw = [t.strip() for t in cell.text().split(",") if t.strip()]
                    a.tags = raw
            self._refresh_all_tags()
            self.browser.refresh()
            self._dirty = True
            dlg.accept()

        def _export_txt():
            exported = 0
            for i, a in enumerate(assets):
                cell = table.item(i, 1)
                tags_str = cell.text() if cell else ", ".join(a.tags)
                txt_path = Path(a.source_path).with_suffix(".txt")
                try:
                    txt_path.write_text(tags_str, encoding="utf-8")
                    exported += 1
                except OSError:
                    pass
            self.status.showMessage(f"Exported {exported} .txt sidecar files", 3000)

        btns.accepted.connect(_save)
        btns.rejected.connect(dlg.reject)
        export_btn.clicked.connect(_export_txt)
        dlg.exec()

    def _show_checklist(self):
        """Per-project posting checklist — items prefixed [ ] or [x]."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
            QListWidget, QListWidgetItem, QDialogButtonBox, QLineEdit, QPushButton)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Posting Checklist — {self.project.name}")
        dlg.resize(480, 400)
        layout = QVBoxLayout(dlg)

        lst = QListWidget()
        lst.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        for item_text in self.project.checklist:
            done = item_text.startswith("[x]")
            label = item_text[4:] if item_text.startswith("[x] ") or item_text.startswith("[ ] ") else item_text
            wi = QListWidgetItem(label)
            wi.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
            lst.addItem(wi)
        layout.addWidget(lst)

        # Add / remove row
        add_row = QHBoxLayout()
        entry = QLineEdit()
        entry.setPlaceholderText("New checklist item…")
        add_row.addWidget(entry, 1)
        add_btn = QPushButton("Add")
        add_row.addWidget(add_btn)
        del_btn = QPushButton("Remove")
        add_row.addWidget(del_btn)
        layout.addLayout(add_row)

        def _add():
            text = entry.text().strip()
            if not text:
                return
            wi = QListWidgetItem(text)
            wi.setCheckState(Qt.CheckState.Unchecked)
            lst.addItem(wi)
            entry.clear()

        def _remove():
            row = lst.currentRow()
            if row >= 0:
                lst.takeItem(row)

        add_btn.clicked.connect(_add)
        del_btn.clicked.connect(_remove)
        entry.returnPressed.connect(_add)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                QDialogButtonBox.StandardButton.Close)
        layout.addWidget(btns)

        def _save():
            items = []
            for i in range(lst.count()):
                wi = lst.item(i)
                prefix = "[x] " if wi.checkState() == Qt.CheckState.Checked else "[ ] "
                items.append(prefix + wi.text())
            self.project.checklist = items
            self._dirty = True
            dlg.accept()

        btns.accepted.connect(_save)
        btns.rejected.connect(dlg.reject)
        dlg.exec()

    def _show_tag_stats(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QDialogButtonBox
        counts: dict[str, int] = {}
        for a in self.project.assets:
            for t in a.tags:
                counts[t] = counts.get(t, 0) + 1
        all_tags = self.project.get_tags()
        rows = sorted(counts.items(), key=lambda x: x[1], reverse=True)

        dlg = QDialog(self)
        dlg.setWindowTitle("Tag Usage Stats")
        dlg.resize(400, 500)
        layout = QVBoxLayout(dlg)
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["Tag", "Label", "Count"])
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(1, table.horizontalHeader().ResizeMode.Stretch)
        for i, (tid, cnt) in enumerate(rows):
            label = all_tags[tid].label if tid in all_tags else tid
            table.setItem(i, 0, QTableWidgetItem(tid))
            table.setItem(i, 1, QTableWidgetItem(label))
            item = QTableWidgetItem(str(cnt))
            table.setItem(i, 2, item)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        layout.addWidget(table)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        dlg.exec()

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
Escape — Deselect All
Alt+A — Add Tag to Selected
Ctrl+H — Temporary Hide (nothing selected = restore all)
Ctrl+T — Toggle Tag Panel
Ctrl+= — Increase Font
Ctrl+- — Decrease Font
Ctrl+0 — Reset Font
Ctrl+Scroll — Zoom Thumbnails
Delete — Soft-delete (tag as ignore)
F5 — Reload Project from Disk
Shift+F5 — Refresh Thumbnails
Ctrl+F — Focus Search Box
Shift+E — Notes Overlay (edit notes popup)

Preview:
N — Add Note
V — Toggle Notes Visible
Ctrl+0 — Fit to View
Esc — Close

Tags (Assets tab):
1-8 — Toggle content tags
0 — Toggle Ignore
Ctrl+Click tag — Search by tag
"""
        from doxyedit.models import TAG_SHORTCUTS
        for key, tid in self.project.custom_shortcuts.items():
            shortcuts += f"{key} — {tid}\n"
        QMessageBox.information(self, "Keyboard Shortcuts", shortcuts.strip())

    def _show_whats_new(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle("What's New in v2.2")
        dlg.resize(520, 480)
        layout = QVBoxLayout(dlg)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setMarkdown(
            "# What's New in v2.2\n\n"
            "## New Panels & Views\n"
            "- **File Browser** (Ctrl+B) — folder tree with asset counts, search, pinned folders, drag-to-import\n"
            "- **Info Panel** (sidebar) — asset metadata with inline tag editing (pill widgets + autocomplete) and notes\n"
            "- **Schedule tab** — Kanban board with drag-drop status columns (Pending/Ready/Posted/Skip)\n"
            "- **Smart Folders** (View menu) — save and load filter presets\n\n"
            "## Preview Enhancements\n"
            "- **Pop-out button** — float docked preview into a full dialog\n"
            "- **Resizable crop handles** — 8 drag handles on crop regions for post-drawing editing\n"
            "- **Grouped crop presets** — dropdown organized by platform with section headers\n"
            "- **Multi-monitor fix** — preview remembers position correctly across monitors\n\n"
            "## Tools\n"
            "- **Find Similar Images** (Tools menu) — perceptual hash grouping for variant detection\n"
            "- **Edit Project Config** (Tools menu) — YAML config for custom platform definitions\n"
            "- **Reload Collection** (File menu) — reload last saved collection with missing-file warnings\n\n"
            "## Visual & Performance\n"
            "- **Color palette swatches** — dominant colors extracted during thumbnail generation, shown in Info Panel\n"
            "- **Toolbar declutter** — Recursive, Hover Preview, Cache All, Folder Scan moved to View/Tools menus\n"
            "- **Folder view fix** — no more overlapping folder sections in By Folder sort\n"
            "- **Tray performance** — O(1) asset lookup replaces linear scans\n"
            "- **Nuitka build** — 11 new exclusions for smaller executable\n"
            "- **Theme audit** — all new panels respect theme colors\n\n"
            "## Keyboard Shortcuts\n"
            "| Shortcut | Action |\n"
            "|----------|--------|\n"
            "| Ctrl+B | File Browser |\n"
            "| | (Info Panel now in sidebar) |\n"
            "| Ctrl+D | Docked Preview |\n"
            "| C | Crop tool (in preview) |\n"
        )
        layout.addWidget(text)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        layout.addWidget(close)
        dlg.exec()

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

    def _on_asset_file_changed(self, path: str):
        """Source image changed on disk — regenerate its thumbnail."""
        # Re-add to watcher (Qt removes on some platforms)
        if path not in self._asset_watcher.files():
            self._asset_watcher.addPath(path)
        # Find the asset and invalidate its cached thumb
        path_norm = path.replace("\\", "/")
        for asset in self.project.assets:
            if asset.source_path.replace("\\", "/") == path_norm:
                self.browser._thumb_cache.invalidate(asset.id)
                self.browser._thumb_cache.request_batch(
                    [(asset.id, asset.source_path)], size=THUMB_GEN_SIZE)
                self.status.showMessage(f"Regenerating thumbnail: {Path(path).name}", 2000)
                break

    def _watch_asset_files(self):
        """Watch all asset source files for changes."""
        old = self._asset_watcher.files()
        if old:
            self._asset_watcher.removePaths(old)
        paths = [a.source_path for a in self.project.assets if Path(a.source_path).exists()]
        if paths:
            self._asset_watcher.addPaths(paths)

    def _watch_import_folders(self):
        """Watch all import source folders for new files.
        Folders with date filters also get a 3-second poll timer for rapid dev cycles."""
        old = self._folder_watcher.directories()
        if old:
            self._folder_watcher.removePaths(old)
        folders = [s["path"] for s in self.project.import_sources
                   if s.get("type") == "folder" and Path(s["path"]).is_dir()]
        if folders:
            self._folder_watcher.addPaths(folders)
        # Start/stop poll timer based on whether any source has a date filter
        has_date_filter = any(s.get("filter_newer_than") for s in self.project.import_sources
                             if s.get("type") == "folder")
        if not hasattr(self, '_folder_poll_timer'):
            self._folder_poll_timer = QTimer(self)
            self._folder_poll_timer.setInterval(3000)
            self._folder_poll_timer.timeout.connect(self._do_folder_rescan)
        if has_date_filter:
            self._folder_poll_timer.start()
        else:
            self._folder_poll_timer.stop()

    def _on_watched_folder_changed(self, folder_path: str):
        """A watched import folder changed — debounce then rescan."""
        if not hasattr(self, '_folder_change_timer'):
            from PySide6.QtCore import QTimer
            self._folder_change_timer = QTimer(self)
            self._folder_change_timer.setSingleShot(True)
            self._folder_change_timer.setInterval(1000)
            self._folder_change_timer.timeout.connect(self._do_folder_rescan)
        self._folder_change_timer.start()

    def _do_folder_rescan(self):
        """Rescan all import sources for new files."""
        total = 0
        for source in self.project.import_sources:
            if source.get("type") == "folder":
                n = self.browser.import_folder(source["path"], source.get("recursive", False))
                total += n
        if total:
            self._refresh_all_tags()
            self._dirty = True
            self.status.showMessage(f"Auto-imported {total} new file(s)", 3000)

    def _on_project_file_changed_raw(self, path: str):
        """Debounce — wait 500ms before reloading to avoid partial writes."""
        # Re-add to watcher (Qt removes it after change on some platforms)
        if path not in self._file_watcher.files():
            self._file_watcher.addPath(path)
        if path == self._project_path:
            self._reload_debounce.start()

    def _do_reload(self):
        """Actually reload the project after debounce."""
        if not self._project_path:
            return
        # Skip if we triggered this change ourselves (our own save)
        if getattr(self, '_own_save_pending', 0) > 0:
            self._own_save_pending -= 1
            return
        try:
            fresh = Project.load(self._project_path)
        except Exception:
            return
        if self._dirty:
            # Merge: pick up new/changed posts from the external file
            # while keeping everything else from the in-memory version
            existing_ids = {p.id for p in self.project.posts}
            new_posts = [p for p in fresh.posts if p.id not in existing_ids]
            # Merge fields that can change externally (CLI, Claude)
            if fresh.identity and not self.project.identity:
                self.project.identity = fresh.identity
            if fresh.oneup_config and not self.project.oneup_config:
                self.project.oneup_config = fresh.oneup_config
            # Always pick up notes changes from external edits
            if fresh.notes and fresh.notes != self.project.notes:
                self.project.notes = fresh.notes
                # Refresh notes UI if visible
                if hasattr(self, '_project_notes_edit'):
                    self._project_notes_edit.setPlainText(fresh.notes)
                if hasattr(self, '_project_notes_preview'):
                    try:
                        import markdown
                        self._project_notes_preview.setHtml(
                            markdown.markdown(fresh.notes, extensions=["tables", "fenced_code"]))
                    except Exception:
                        self._project_notes_preview.setPlainText(fresh.notes)
                if hasattr(self, '_notes_edit'):
                    self._notes_edit.setPlainText(fresh.notes)
            if new_posts:
                self.project.posts.extend(new_posts)
                # Save merged state immediately so autosave won't clobber
                if self._project_path:
                    self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1
                    self.project.save(self._project_path)
                    self._dirty = False
                if hasattr(self, '_timeline'):
                    self._timeline.refresh()
                self.status.showMessage(f"Merged {len(new_posts)} new post(s) from CLI", 3000)
            else:
                self.status.showMessage("External change detected — save first or reopen", 3000)
            return
        self.project = fresh
        self._rebind_project()
        self.status.showMessage("Project reloaded (external change detected)", 3000)

    def _watch_project(self):
        """Start watching the current project file for external changes."""
        # Clear old watches
        old = self._file_watcher.files()
        if old:
            self._file_watcher.removePaths(old)
        if self._project_path and Path(self._project_path).exists():
            self._file_watcher.addPath(self._project_path)

    def _autosave(self):
        if self._dirty and self._project_path:
            self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1; self.project.save(self._project_path)
            self._dirty = False
            self.status.showMessage("Auto-saved", 3000)
            self._autosave_collection()

    # --- Project file ops ---

    def _new_project(self):
        """Open a fresh project in a new window."""
        win = MainWindow(_skip_autoload=True)
        MainWindow._open_windows.append(win)
        win.show()

    def _new_project_blank(self):
        """Replace current window with a blank project (used internally)."""
        self.project = Project(name="Untitled")
        self.scene.clear()
        self._project_path = None
        self._rebind_project(clear_folder_state=True)
        self.setWindowTitle("DoxyEdit — New Project")
        self.status.showMessage("New project")

    def _rebind_project(self, clear_folder_state: bool = False):
        # Clear per-project browser state
        self.browser._bar_tag_filters.clear()
        self.browser._clear_filter_btn.setVisible(False)
        self.browser._temp_hidden_ids.clear()
        if clear_folder_state:
            self.browser._collapsed_folders.clear()
            self.browser._hidden_folders.clear()
        self.browser._selected_ids.clear()
        self.browser._eye_hidden_tags.clear()
        self.browser._folder_filter = None
        # Clear previous project's custom shortcuts from the global TAG_SHORTCUTS dict
        for key in list(TAG_SHORTCUTS.keys()):
            if key not in TAG_SHORTCUTS_DEFAULT:
                del TAG_SHORTCUTS[key]

        # Sync local mode toggle to the loaded project's setting
        if hasattr(self, '_local_mode_action'):
            self._local_mode_action.blockSignals(True)
            self._local_mode_action.setChecked(self.project.local_mode)
            self._local_mode_action.blockSignals(False)

        # Keep the slot in sync with the current project object
        if 0 <= getattr(self, '_current_slot', -1) < len(getattr(self, '_project_slots', [])):
            self._project_slots[self._current_slot]["project"] = self.project

        # Re-apply theme so project accent color takes effect
        # Always read from settings in case it was changed externally
        self._current_theme_id = self._settings.value("theme", DEFAULT_THEME)
        self._apply_theme(self._current_theme_id)
        shared = self._settings.value("shared_cache", "true") == "true"
        cache_name = "shared" if shared else self.project.name
        self.browser._thumb_cache.set_project(cache_name)
        self.browser.project = self.project
        self.work_tray._project = self.project
        self.browser.rebuild_tag_bar()
        self.browser.refresh()
        self.platform_panel.project = self.project
        self.platform_panel.refresh()
        self.stats_panel.project = self.project
        self.stats_panel.folder_bar_color = self._theme.accent_bright
        self.checklist_panel.project = self.project
        self.checklist_panel.refresh()
        self.health_panel.project = self.project
        self.health_panel.refresh()
        self._file_browser.set_project(self.project)
        if hasattr(self, '_kanban_panel'):
            self._kanban_panel.set_project(self.project)
        if hasattr(self, '_timeline'):
            self._timeline.set_project(self.project)
        if hasattr(self, '_calendar_pane'):
            self._calendar_pane.set_project(self.project)
        if hasattr(self, '_smart_folder_menu'):
            self._rebuild_smart_folder_menu()
        if hasattr(self, '_info_panel'):
            tag_ids = sorted(self.project.get_tags().keys()) if self.project else []
            self._info_panel.set_available_tags(tag_ids)
        self.tag_panel.set_assets([])
        self.tag_panel.refresh_discovered_tags(self.project.assets, self.project)
        self.tag_panel.update_tag_counts(self.project.assets)
        if self._notes_edit.isVisible():
            self._notes_edit.blockSignals(True)
            self._notes_edit.setPlainText(self.project.notes)
            self._notes_edit.blockSignals(False)
        # Refresh all notes tabs
        for tab_name, (preview, editor, _) in self._notes_tab_widgets.items():
            if tab_name == "General":
                text = self.project.notes
            else:
                text = self.project.sub_notes.get(tab_name, "")
            editor.blockSignals(True)
            editor.setPlainText(text)
            editor.blockSignals(False)
            self._render_notes_preview_to(preview, text)
        self._update_progress()
        self._watch_asset_files()
        self._watch_import_folders()
        # Restore work tray
        if self.project.tray_items:
            self.work_tray.load_state(self.project.tray_items, self.project)
            # Feed any already-cached pixmaps to the tray
            tray_data = self.project.tray_items
            all_aids = tray_data if isinstance(tray_data, list) else [
                aid for ids in tray_data.values() for aid in ids]
            for aid in all_aids:
                pm = self.browser._thumb_cache.get(aid)
                if pm:
                    self.work_tray.update_pixmap(aid, pm)
                else:
                    # Not cached yet — request generation
                    asset = self.project.get_asset(aid)
                    if asset and asset.source_path:
                        self.browser._thumb_cache.request(aid, asset.source_path)
            if all_aids:
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
            self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1; self.project.save(self._project_path)
            self._dirty = False
            self._settings.setValue("last_project", self._project_path)
            self._add_recent_project(self._project_path)
            self.status.showMessage(f"Saved {Path(self._project_path).name}")
            # Brief green flash on status bar
            self.status.setStyleSheet(
                f"QStatusBar {{ background: {self._theme.accent}; color: {self._theme.text_on_accent}; }}")
            QTimer.singleShot(800, lambda: self.status.setStyleSheet(""))
            self._autosave_collection()
        else:
            self._save_project_as()

    def _save_project_as(self):
        hint = self._project_path or (
            str(Path(self._dialog_dir()) / "project.doxyproj.json")
            if self._dialog_dir() else "project.doxyproj.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", hint,
            "DoxyEdit Projects (*.doxyproj.json);;All Files (*)"
        )
        if path:
            self._remember_dir(path)
            self._own_save_pending = getattr(self, '_own_save_pending', 0) + 1
            self.project.save(path)
            self._project_path = path
            self._watch_project()
            self._dirty = False
            self._settings.setValue("last_project", path)
            self._add_recent_project(path)
            self.setWindowTitle(f"DoxyEdit — {Path(path).name}")
            self._proj_tab_bar.setTabText(0, Path(path).stem)
            if 0 <= self._current_slot < len(self._project_slots):
                self._project_slots[self._current_slot]["path"] = path
                self._project_slots[self._current_slot]["label"] = Path(path).stem
            self.status.showMessage(f"Saved {Path(path).name}")
            self._autosave_collection()

    def _collect_open_project_paths(self) -> list[str]:
        """Return paths of all saved projects across all open windows and slots."""
        paths = []
        seen = set()
        # Always include the current window's active project path first
        if self._project_path and self._project_path not in seen:
            paths.append(self._project_path)
            seen.add(self._project_path)
        # Gather from all slots in this window
        for slot in self._project_slots:
            p = slot.get("path")
            if p and p not in seen:
                paths.append(p)
                seen.add(p)
        # Gather from other MainWindow instances
        for w in MainWindow._open_windows:
            if w is not self and w.isVisible():
                if getattr(w, '_project_path', None) and w._project_path not in seen:
                    paths.append(w._project_path)
                    seen.add(w._project_path)
                for slot in getattr(w, "_project_slots", []):
                    p = slot.get("path")
                    if p and p not in seen:
                        paths.append(p)
                        seen.add(p)
        return paths

    def _autosave_collection(self):
        """Silently overwrite the last-saved collection file if one exists."""
        coll_path = self._settings.value("last_collection", "")
        if not coll_path:
            return
        projects = self._collect_open_project_paths()
        if not projects:
            return
        try:
            Path(coll_path).write_text(
                json.dumps({"_type": "doxycoll", "projects": projects}, indent=2),
                encoding="utf-8")
        except Exception:
            pass

    def _locate_last_collection(self):
        """Show where the last saved collection is (or was) on disk."""
        path = self._settings.value("last_collection", "")
        if not path:
            QMessageBox.information(self, "Last Collection", "No collection has been saved yet.")
            return
        if Path(path).exists():
            import subprocess
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            QMessageBox.warning(self, "Last Collection",
                f"File no longer exists:\n{path}\n\n"
                "Use 'Save Collection…' to create a new one.")

    def _save_collection_quick(self):
        """Quick save — overwrite the last collection file, or fall back to Save As."""
        last = self._settings.value("last_collection", "")
        if not last or not Path(last).parent.exists():
            self._save_collection()
            return
        projects = self._collect_open_project_paths()
        if not projects:
            self.status.showMessage("No saved projects open", 3000)
            return
        try:
            Path(last).write_text(
                json.dumps({"_type": "doxycoll", "projects": projects}, indent=2),
                encoding="utf-8")
            self.status.showMessage(f"Collection saved → {Path(last).name}", 3000)
        except Exception as e:
            self.status.showMessage(f"Save failed: {e}", 5000)

    def _save_collection(self):
        """Save all open project tabs/windows as a named collection (.doxycoll.json)."""
        projects = self._collect_open_project_paths()
        if not projects:
            QMessageBox.information(self, "Save Collection",
                "No saved projects are open. Save each project to disk first (Ctrl+S).")
            return
        last = self._settings.value("last_collection", "")
        # Default to project directory so user knows where it's going
        if last and Path(last).parent.exists():
            default_path = last
        elif projects:
            default_path = str(Path(projects[0]).parent / "workspace.doxycoll.json")
        else:
            default_path = str(Path(self._dialog_dir()) / "workspace.doxycoll.json") \
                if self._dialog_dir() else "workspace.doxycoll.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Collection", default_path,
            "DoxyEdit Collection (*.doxycoll.json);;All Files (*)")
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps({"_type": "doxycoll", "projects": projects}, indent=2),
                encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Save Collection", f"Failed to write file:\n{e}")
            return
        self._remember_dir(path)
        self._settings.setValue("last_collection", path)
        names = ", ".join(Path(p).stem for p in projects)
        QMessageBox.information(self, "Collection Saved",
            f"Saved {len(projects)} project(s) to:\n{path}\n\n{names}")
        self.status.showMessage(f"Collection saved → {path}")

    def _reload_collection(self):
        """Reload the last saved collection file."""
        coll_path = self._settings.value("last_collection", "")
        if not coll_path or not Path(coll_path).exists():
            self.status.showMessage("No collection to reload", 3000)
            return
        # Close all tabs except the first
        while self._proj_tab_bar.count() > 1:
            self._close_proj_tab(self._proj_tab_bar.count() - 1)
        # Restore from file
        if not self._restore_collection(coll_path):
            self.status.showMessage("Collection reload failed", 3000)

    def _open_collection(self):
        """Open a saved collection — each project opens in its own window."""
        last = self._settings.value("last_collection", "")
        start = last if last and Path(last).exists() else self._dialog_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Collection", start,
            "DoxyEdit Collection (*.doxycoll.json);;All Files (*)")
        if not path:
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        proj_paths = data.get("projects", [])
        all_wins = [self] + [w for w in MainWindow._open_windows if w.isVisible()]
        already_open = {w._project_path for w in all_wins if w._project_path}
        opened = 0
        for proj_path in proj_paths:
            if not Path(proj_path).exists():
                continue
            if proj_path in already_open:
                continue
            win = MainWindow(_skip_autoload=True)
            MainWindow._open_windows.append(win)
            win._load_project_from(proj_path)
            win.show()
            already_open.add(proj_path)
            opened += 1
        self._settings.setValue("last_collection", path)
        self.status.showMessage(
            f"Collection loaded: {opened} new window(s), {len(proj_paths) - opened} already open")

    def _export_all(self):
        # Gap detection — warn about unassigned required slots before export
        from doxyedit.models import PLATFORMS
        gaps = []
        assigned_slots = {(pa.platform, pa.slot)
                          for a in self.project.assets for pa in a.assignments}
        for pid in self.project.platforms:
            platform = PLATFORMS.get(pid)
            if not platform:
                continue
            for slot in platform.slots:
                if slot.required and (pid, slot.name) not in assigned_slots:
                    gaps.append(f"  {platform.name} → {slot.label} ({slot.name})")
        if gaps:
            msg = "The following required platform slots have no assigned asset:\n\n"
            msg += "\n".join(gaps[:20])
            if len(gaps) > 20:
                msg += f"\n  …and {len(gaps) - 20} more"
            msg += "\n\nExport anyway?"
            reply = QMessageBox.question(self, "Export Gaps Found", msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

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

    def showEvent(self, event):
        super().showEvent(event)
        # After window is fully shown, request thumbs — folder sections now have real heights
        QTimer.singleShot(100, self.browser._request_visible_thumbs)
        QTimer.singleShot(400, self.browser._request_visible_thumbs)
        if not getattr(self, '_hotkey_registered', False):
            if windroptarget.register_hotkey(int(self.winId())):
                self._hotkey_registered = True

                class _HotkeyFilter(QAbstractNativeEventFilter):
                    def __init__(self_, callback):
                        super().__init__()
                        self_._cb = callback
                    def nativeEventFilter(self_, event_type, message):
                        if windroptarget.is_hotkey_message(bytes(event_type), int(message)):
                            self_._cb()
                            return True, 0
                        return False, 0

                self._hotkey_filter = _HotkeyFilter(self._on_drop_hotkey)
                QApplication.instance().installNativeEventFilter(self._hotkey_filter)
            else:
                self.status.showMessage("Warning: could not register Ctrl+Alt+Shift+V hotkey", 4000)

    def _on_drop_hotkey(self):
        text = QApplication.clipboard().text()
        ok, msg = windroptarget.simulate_drop_from_clipboard(text)
        self.status.showMessage(msg, 3000)

    # --- Configure Editors / Quick-Launch ---

    def _configure_editors(self):
        """Tools > Configure Editors — map file extensions to custom executables."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
            QTableWidgetItem, QDialogButtonBox, QLabel, QPushButton, QHeaderView)

        dlg = QDialog(self)
        dlg.setWindowTitle("Configure Editors")
        dlg.resize(620, 400)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            "Map file extensions to custom executables. Leave path blank to use the system default.\n"
            "These editors are also available in the 'Launch In' menu."))

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Extension", "Executable Path"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        # Load existing entries
        self._settings.beginGroup("native_editor")
        for ext in self._settings.childKeys():
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(ext))
            table.setItem(row, 1, QTableWidgetItem(self._settings.value(ext, "")))
        self._settings.endGroup()

        layout.addWidget(table, 1)

        add_row_layout = QHBoxLayout()
        add_btn = QPushButton("+ Add Row")
        def _add_row():
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(".ext"))
            table.setItem(row, 1, QTableWidgetItem(""))
            table.editItem(table.item(row, 0))
        add_btn.clicked.connect(_add_row)
        add_row_layout.addWidget(add_btn)

        browse_btn = QPushButton("Browse…")
        def _browse():
            row = table.currentRow()
            if row < 0:
                return
            path, _ = QFileDialog.getOpenFileName(dlg, "Select Executable", "",
                                                   "Executables (*.exe);;All Files (*)")
            if path:
                table.setItem(row, 1, QTableWidgetItem(path))
        browse_btn.clicked.connect(_browse)
        add_row_layout.addWidget(browse_btn)

        remove_btn = QPushButton("Remove Row")
        def _remove_row():
            rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
            for r in rows:
                table.removeRow(r)
        remove_btn.clicked.connect(_remove_row)
        add_row_layout.addWidget(remove_btn)
        add_row_layout.addStretch()
        layout.addLayout(add_row_layout)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # Save back — clear group then re-write
        self._settings.beginGroup("native_editor")
        for key in self._settings.childKeys():
            self._settings.remove(key)
        self._settings.endGroup()
        # Store multiple editors per extension: native_editor/.psd/0, .psd/1, etc.
        ext_counts: dict[str, int] = {}
        for row in range(table.rowCount()):
            ext_item = table.item(row, 0)
            path_item = table.item(row, 1)
            if ext_item and ext_item.text().strip():
                ext = ext_item.text().strip().lower()
                if not ext.startswith("."):
                    ext = "." + ext
                idx = ext_counts.get(ext, 0)
                ext_counts[ext] = idx + 1
                key = f"native_editor/{ext}" if idx == 0 else f"native_editor/{ext}/{idx}"
                self._settings.setValue(key, path_item.text().strip() if path_item else "")
        self._rebuild_launch_menu()
        self.status.showMessage("Editor configuration saved", 2000)

    def _save_smart_folder(self):
        """Save the current browser filter state as a named smart folder."""
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Smart Folder", "Name for this filter preset:")
        if not ok or not name.strip():
            return
        state = self.browser.get_filter_state()
        preset = {
            "name": name.strip(),
            "icon": "🔍",
            "state": state,
        }
        self.project.filter_presets.append(preset)
        self._dirty = True
        self._rebuild_smart_folder_menu()
        self.status.showMessage(f"Smart folder saved: {name.strip()}", 3000)

    def _rebuild_smart_folder_menu(self):
        """Rebuild the Smart Folders submenu from project presets."""
        menu = self._smart_folder_menu
        menu.clear()
        menu.addAction("Save Current Filter...", self._save_smart_folder)
        if not self.project or not self.project.filter_presets:
            return
        menu.addSeparator()
        for i, preset in enumerate(self.project.filter_presets):
            name = preset.get("name", f"Preset {i+1}")
            icon = preset.get("icon", "🔍")
            menu.addAction(f"{icon} {name}",
                            lambda _, idx=i: self._load_smart_folder(idx))
        menu.addSeparator()
        menu.addAction("Clear All Smart Folders", self._clear_smart_folders)

    def _load_smart_folder(self, index: int):
        """Load a smart folder preset by index."""
        if not self.project or index >= len(self.project.filter_presets):
            return
        preset = self.project.filter_presets[index]
        state = preset.get("state", {})
        self.browser.set_filter_state(state)
        name = preset.get("name", "Untitled")
        self.status.showMessage(f"Smart folder loaded: {name}", 3000)

    def _clear_smart_folders(self):
        """Remove all smart folder presets."""
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "Clear Smart Folders",
                                 "Remove all saved filter presets?") != QMessageBox.StandardButton.Yes:
            return
        self.project.filter_presets.clear()
        self._dirty = True
        self._rebuild_smart_folder_menu()

    def _get_all_editors(self) -> list[tuple[str, str]]:
        """Return all configured editors as [(ext, exe_path), ...] including numbered duplicates."""
        editors = []
        all_keys = [k for k in self._settings.allKeys() if k.startswith("native_editor/")]
        for key in sorted(all_keys):
            exe = self._settings.value(key, "")
            if not exe:
                continue
            # Extract extension: "native_editor/.psd" or "native_editor/.psd/1"
            parts = key.replace("native_editor/", "").split("/")
            ext = parts[0]
            editors.append((ext, exe))
        return editors

    def _rebuild_launch_menu(self):
        """Rebuild Tools > Launch In submenu from configured editors."""
        self._launch_menu.clear()
        editors = self._get_all_editors()
        for ext, exe in editors:
            name = Path(exe).stem if exe else "system default"
            label = f"{name} ({ext})"
            action = self._launch_menu.addAction(label)
            action.setToolTip(exe)
            action.triggered.connect(lambda _=False, e=ext, x=exe: self._launch_in(e, x))
        if not editors:
            placeholder = self._launch_menu.addAction("(no editors configured)")
            placeholder.setEnabled(False)
        self._launch_menu.addSeparator()
        self._launch_menu.addAction("Configure Editors...", self._configure_editors)

    def _launch_in(self, ext: str, exe: str):
        """Open selected assets matching ext in the specified exe (or system default)."""
        import subprocess, os
        assets = self.browser.get_selected_assets()
        if not assets:
            self.status.showMessage("No assets selected", 2000)
            return
        targets = [a for a in assets
                   if Path(a.source_path).suffix.lower() == ext.lower()]
        if not targets:
            self.status.showMessage(f"No selected assets match {ext}", 2000)
            return
        for asset in targets:
            if exe and os.path.exists(exe):
                subprocess.Popen([exe, asset.source_path])
            else:
                try:
                    os.startfile(asset.source_path)
                except Exception:
                    pass
        self.status.showMessage(f"Opened {len(targets)} file(s)", 2000)

    def closeEvent(self, event):
        if getattr(self, '_hotkey_registered', False):
            windroptarget.unregister_hotkey(int(self.winId()))
            if hasattr(self, '_hotkey_filter'):
                QApplication.instance().removeNativeEventFilter(self._hotkey_filter)
        if self._dirty and self._project_path:
            self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1; self.project.save(self._project_path)
        # Save splitter and window position/size
        self._settings.setValue("splitter_sizes", self._browse_split.sizes())
        self._settings.setValue("social_splitter", self._social_split.sizes())
        self._settings.setValue("social_left_splitter", self._social_left_split.sizes())
        self._settings.setValue("plat_top_splitter", self._plat_top.sizes())
        self._settings.setValue("plat_full_splitter", self._plat_full.sizes())
        self._settings.setValue("tag_notes_splitter", self.tag_panel._tag_notes_split.sizes())
        self._settings.setValue("collapsed_folders", sorted(self.browser._collapsed_folders))
        self._settings.setValue("hidden_folders", sorted(self.browser._hidden_folders))
        self._settings.setValue("collapsed_tag_sections", sorted(self.tag_panel._collapsed_sections))
        self._settings.setValue("window_width", self.width())
        self._settings.setValue("window_height", self.height())
        self._settings.setValue("window_x", self.x())
        self._settings.setValue("window_y", self.y())
        self.browser.shutdown()
        event.accept()
