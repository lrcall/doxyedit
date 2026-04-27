"""File browser panel — QTreeView + QFileSystemModel for filesystem browsing."""
import os
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeView,
    QMenu, QFileSystemModel, QAbstractItemView, QApplication,
    QStyledItemDelegate, QStyleOptionViewItem, QLineEdit,
)
from PySide6.QtCore import Qt, Signal, QDir, QSettings, QModelIndex, QRect, QSize, QMimeData, QUrl
from PySide6.QtGui import QPainter, QColor, QDrag
from doxyedit.themes import ui_font_size, THEMES, DEFAULT_THEME


class FolderDelegate(QStyledItemDelegate):
    """Custom delegate that paints asset count badges on folder rows."""

    MIN_BADGE_FONT = 6

    def __init__(self, panel: 'FileBrowserPanel', parent=None):
        super().__init__(parent)
        self._panel = panel

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        model = index.model()
        path = model.filePath(index).replace("\\", "/")
        count = self._panel.get_folder_count(path)
        is_active = (path == self._panel._active_folder)

        # Active folder background highlight
        if is_active:
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            _dt = THEMES[DEFAULT_THEME]
            if getattr(self._panel, '_theme', None):
                bg = QColor(self._panel._theme.selection_bg)
                bg.setAlpha(self._panel._theme.filebrowser_active_alpha)
            else:
                bg = QColor(_dt.selection_bg)
                bg.setAlpha(_dt.filebrowser_folder_dim_alpha)
            painter.setBrush(bg)
            painter.drawRect(option.rect)
            painter.restore()

        # Dim folders with no assets
        if count == 0:
            painter.save()
            painter.setOpacity(0.4)
            super().paint(painter, option, index)
            painter.restore()
        else:
            super().paint(painter, option, index)

        # Badge
        if count <= 0:
            return

        painter.save()
        text = str(count)
        font = painter.font()
        _f = getattr(self._panel, '_f', 12)
        font.setPointSize(max(self.MIN_BADGE_FONT, int(_f * 0.67)))
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text) + 10
        th = fm.height() + 2

        badge_rect = QRect(
            option.rect.right() - tw - 6,
            option.rect.top() + (option.rect.height() - th) // 2,
            tw, th)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        panel = self._panel
        _dt = THEMES[DEFAULT_THEME]
        if getattr(panel, '_theme', None):
            if is_active:
                badge_bg = QColor(panel._theme.accent)
                badge_bg.setAlpha(panel._theme.filebrowser_badge_alpha)
            else:
                badge_bg = QColor(panel._theme.text_muted)
                badge_bg.setAlpha(panel._theme.filebrowser_folder_alpha)
            text_color = QColor(panel._theme.text_secondary)
        else:
            badge_bg = QColor(_dt.text_muted)
            badge_bg.setAlpha(_dt.filebrowser_folder_alpha)
            text_color = QColor(_dt.text_secondary)
        painter.setBrush(badge_bg)
        painter.drawRoundedRect(badge_rect, th // 2, th // 2)

        painter.setPen(text_color)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 24))


class FileBrowserPanel(QWidget):
    """Eagle-style filesystem tree with pinned folders and asset count badges."""

    folder_selected = Signal(str)       # folder path — filter main grid to this folder
    import_requested = Signal(str)      # folder path — import into project
    filter_cleared = Signal()           # clear folder filter
    remove_folder_requested = Signal(str, bool)  # folder path, recursive — remove its assets from project

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("file_browser_panel")
        self._project = None
        self._folder_counts: dict[str, int] = {}  # folder_path → count of project assets
        self._recursive_counts: dict[str, int] = {}  # pre-computed recursive totals
        self._pinned: list[str] = []
        self._settings = QSettings("DoxyEdit", "DoxyEdit")
        self._load_pinned()
        self._active_folder: str | None = None  # currently filtering on this folder
        self._build()

    def _load_pinned(self):
        saved = self._settings.value("pinned_folders", [])
        self._pinned = [str(p) for p in saved] if saved else []

    def _save_pinned(self):
        self._settings.setValue("pinned_folders", self._pinned)

    def _build(self):
        _f = ui_font_size()
        self._f = _f
        _cb = max(14, _f + 2)
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_pad)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(_pad_lg, _pad_lg, _pad_lg, max(2, _pad // 2))
        title = QLabel("Files")
        _bold = title.font(); _bold.setBold(True); title.setFont(_bold)
        header.addWidget(title)
        header.addStretch()

        clear_btn = QPushButton("Clear Filter")
        clear_btn.setFixedHeight(_cb)
        clear_btn.setToolTip("Clear folder filter on main grid")
        clear_btn.clicked.connect(lambda: self.filter_cleared.emit())
        header.addWidget(clear_btn)
        layout.addLayout(header)

        # Search filter
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter folders...")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(_cb + 2)
        self._search.setContentsMargins(_pad_lg, 0, _pad_lg, 0)
        self._search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search)

        # Pinned folders bar
        self._pin_bar = QVBoxLayout()
        self._pin_bar.setContentsMargins(_pad_lg, 0, _pad_lg, 0)
        self._pin_bar.setSpacing(max(2, _pad // 2))
        layout.addLayout(self._pin_bar)
        self._rebuild_pin_bar()

        # Tree view
        self._model = QFileSystemModel()
        self._model.setReadOnly(True)
        self._model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)
        # Show only directories — files are shown as counts, not listed
        self._model.setNameFilterDisables(False)

        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        # Hide Size, Type, Date Modified columns — show only Name
        for col in range(1, 4):
            self._tree.hideColumn(col)
        self._tree.setAnimated(True)
        self._tree.setIndentation(16)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._tree_context_menu)
        self._tree.clicked.connect(self._on_folder_clicked)
        self._tree.setStyleSheet("")
        self._tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        # Set root to drives on Windows
        root = self._model.setRootPath("")
        self._tree.setRootIndex(root)

        self._delegate = FolderDelegate(self)
        self._tree.setItemDelegate(self._delegate)

        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._tree.startDrag = self._start_drag

        layout.addWidget(self._tree, 1)

        self.setMinimumWidth(0)  # splitter handles collapsing

    def _rebuild_pin_bar(self):
        while self._pin_bar.count():
            item = self._pin_bar.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for folder in self._pinned:
            btn = QPushButton(f"📌 {Path(folder).name}")
            btn.setToolTip(folder)
            btn.setStyleSheet("QPushButton { text-align: left; }")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, f=folder: self._navigate_to(f))
            self._pin_bar.addWidget(btn)

    def _navigate_to(self, folder: str):
        """Expand the tree to a folder and select it."""
        idx = self._model.index(folder)
        if idx.isValid():
            self._tree.setCurrentIndex(idx)
            self._tree.scrollTo(idx)
            self._tree.expand(idx)
            self.folder_selected.emit(folder)

    def _on_folder_clicked(self, index: QModelIndex):
        path = self._model.filePath(index)
        if not path:
            return
        norm = path.replace("\\", "/")
        # Toggle: clicking the already-active folder clears the filter and
        # deselects the row, returning the grid to the whole-project view.
        if norm == self._active_folder:
            self._active_folder = None
            self._tree.selectionModel().clearSelection()
            self.filter_cleared.emit()
            self._tree.viewport().update()
            return
        self._active_folder = norm
        self.folder_selected.emit(path)
        self._tree.viewport().update()  # repaint badges

    def clear_active(self):
        """Clear the active folder highlight (called when filter is cleared)."""
        self._active_folder = None
        self._tree.viewport().update()

    def _on_search_changed(self, text: str):
        """Filter tree to folders matching the search text."""
        text = text.strip()
        if text:
            self._model.setNameFilters([f"*{text}*"])
            self._model.setNameFilterDisables(False)
        else:
            self._model.setNameFilters([])

    def _tree_context_menu(self, pos):
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        path = self._model.filePath(index)
        menu = QMenu(self._tree)

        menu.addAction("Filter Grid to This Folder",
                        lambda: self.folder_selected.emit(path))
        menu.addAction("Import This Folder",
                        lambda: self.import_requested.emit(path))

        # Removal options - only meaningful when this folder actually has
        # assets in the project. Show direct count vs recursive count
        # separately so the user knows exactly what they're acting on.
        norm = path.replace("\\", "/").rstrip("/")
        direct = self._folder_counts.get(norm, 0)
        recursive = self._recursive_counts.get(norm, 0)
        if direct or recursive:
            menu.addSeparator()
            if direct:
                menu.addAction(
                    f"Remove {direct} Asset(s) in This Folder from Project",
                    lambda: self.remove_folder_requested.emit(path, False))
            if recursive > direct:
                menu.addAction(
                    f"Remove All {recursive} Asset(s) in Folder + Subfolders",
                    lambda: self.remove_folder_requested.emit(path, True))

        menu.addSeparator()

        if path in self._pinned:
            menu.addAction("Unpin", lambda: self._unpin(path))
        else:
            menu.addAction("Pin as Root", lambda: self._pin(path))

        menu.addSeparator()
        menu.addAction("Open in Explorer", lambda: self._open_explorer(path))
        menu.addAction("Copy Path", lambda: QApplication.clipboard().setText(path))

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _pin(self, folder: str):
        if folder not in self._pinned:
            self._pinned.append(folder)
            self._save_pinned()
            self._rebuild_pin_bar()

    def _unpin(self, folder: str):
        if folder in self._pinned:
            self._pinned.remove(folder)
            self._save_pinned()
            self._rebuild_pin_bar()

    def _open_explorer(self, path: str):
        import subprocess
        win_path = path.replace("/", "\\")
        subprocess.Popen(f'explorer "{win_path}"')

    def set_project(self, project):
        """Update project reference for asset counts, then expand to project folders."""
        self._project = project
        self._update_folder_counts()
        self._auto_expand()
        self._tree.viewport().update()

    def _auto_expand(self):
        """Expand tree to reveal folders that contain project assets."""
        if not self._folder_counts:
            return

        folders = list(self._folder_counts.keys())
        if not folders:
            return

        # Navigate to first pinned folder if it has assets, else most-populated folder
        target = None
        for pin in self._pinned:
            pin_norm = pin.replace("\\", "/")
            if self.get_folder_count(pin_norm) > 0:
                target = pin
                break

        if not target:
            # Pick the folder with the most assets
            target = max(self._folder_counts, key=self._folder_counts.get)

        if target:
            idx = self._model.index(target)
            if idx.isValid():
                self._tree.setCurrentIndex(idx)
                self._tree.scrollTo(idx)
                # Expand this folder and its parent chain
                parent = idx
                while parent.isValid():
                    self._tree.expand(parent)
                    parent = parent.parent()

    def _update_folder_counts(self):
        """Recompute folder → direct count + recursive totals.

        Each folder contributes its direct_count to every ancestor up the
        parent chain. O(K * avg_depth) where K = unique folders, vs prior
        O(K^2) prefix-match implementation.
        """
        # Cache by (project identity, version) - set_project is called on
        # every rebind, but counts only change when assets actually change.
        if self._project:
            sig = (id(self._project), getattr(self._project, "version", 0))
            if getattr(self, "_folder_count_sig", None) == sig:
                return
        self._folder_counts.clear()
        self._recursive_counts: dict[str, int] = {}
        if not self._project:
            return
        # os.path.dirname is ~3x faster than Path().parent across 67k assets.
        _dn = os.path.dirname
        _fc = self._folder_counts
        for asset in self._project.assets:
            folder = asset.source_folder or _dn(asset.source_path)
            folder = folder.replace("\\", "/")
            _fc[folder] = _fc.get(folder, 0) + 1
        self._folder_count_sig = (id(self._project), getattr(self._project, "version", 0))

        # Propagate direct counts up each path's ancestor chain.
        for folder, direct in self._folder_counts.items():
            node = folder
            while node:
                self._recursive_counts[node] = self._recursive_counts.get(node, 0) + direct
                idx = node.rfind("/")
                if idx <= 0:
                    break
                node = node[:idx]

    def get_folder_count(self, folder_path: str) -> int:
        """Return pre-computed recursive asset count. O(1) lookup."""
        folder_path = folder_path.replace("\\", "/").rstrip("/")
        return self._recursive_counts.get(folder_path, 0)


    def _start_drag(self, supported_actions):
        """Start a drag with the selected folder as a file URL."""

        index = self._tree.currentIndex()
        if not index.isValid():
            return
        path = self._model.filePath(index)
        if not path:
            return

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        mime.setData("application/x-doxyedit-folder-import", path.encode("utf-8"))

        drag = QDrag(self._tree)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def highlight_folder(self, folder_path: str):
        """Highlight a folder in the tree without triggering a filter.
        Used for grid-to-tree sync — shows where the selected asset lives."""
        if not folder_path:
            return
        folder_path = folder_path.replace("\\", "/")
        idx = self._model.index(folder_path)
        if idx.isValid():
            # Block signals so we don't fire folder_selected (which would filter)
            self._tree.blockSignals(True)
            self._tree.setCurrentIndex(idx)
            self._tree.scrollTo(idx)
            self._tree.blockSignals(False)
