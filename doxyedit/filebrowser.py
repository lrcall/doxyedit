"""File browser panel — QTreeView + QFileSystemModel for filesystem browsing."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeView,
    QMenu, QFileSystemModel, QAbstractItemView, QApplication,
    QStyledItemDelegate, QStyleOptionViewItem,
)
from PySide6.QtCore import Qt, Signal, QDir, QSettings, QModelIndex, QRect, QSize
from PySide6.QtGui import QFont, QPainter, QColor

from doxyedit.browser import IMAGE_EXTS


class FolderDelegate(QStyledItemDelegate):
    """Custom delegate that paints asset count badges on folder rows."""

    def __init__(self, panel: 'FileBrowserPanel', parent=None):
        super().__init__(parent)
        self._panel = panel

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        # Draw the default folder name + icon
        super().paint(painter, option, index)

        model = index.model()
        path = model.filePath(index).replace("\\", "/")
        count = self._panel.get_folder_count(path)
        if count <= 0:
            return

        painter.save()
        text = str(count)
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text) + 10
        th = fm.height() + 2

        # Badge rect — right-aligned, vertically centered
        badge_rect = QRect(
            option.rect.right() - tw - 6,
            option.rect.top() + (option.rect.height() - th) // 2,
            tw, th)

        # Draw pill background
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 30))
        painter.drawRoundedRect(badge_rect, th // 2, th // 2)

        # Draw count text
        painter.setPen(QColor(200, 200, 200))
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("file_browser_panel")
        self._project = None
        self._folder_counts: dict[str, int] = {}  # folder_path → count of project assets
        self._pinned: list[str] = []
        self._settings = QSettings("DoxyEdit", "DoxyEdit")
        self._load_pinned()
        self._build()

    def _load_pinned(self):
        saved = self._settings.value("pinned_folders", [])
        self._pinned = [str(p) for p in saved] if saved else []

    def _save_pinned(self):
        self._settings.setValue("pinned_folders", self._pinned)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(8, 6, 8, 2)
        title = QLabel("Files")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()

        clear_btn = QPushButton("Clear Filter")
        clear_btn.setFixedHeight(20)
        clear_btn.setStyleSheet("QPushButton { padding: 1px 6px; font-size: 10px; }")
        clear_btn.setToolTip("Clear folder filter on main grid")
        clear_btn.clicked.connect(lambda: self.filter_cleared.emit())
        header.addWidget(clear_btn)
        layout.addLayout(header)

        # Pinned folders bar
        self._pin_bar = QVBoxLayout()
        self._pin_bar.setContentsMargins(8, 0, 8, 0)
        self._pin_bar.setSpacing(2)
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
        self._tree.setStyleSheet("QTreeView { border: none; }")
        self._tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        # Set root to drives on Windows
        root = self._model.setRootPath("")
        self._tree.setRootIndex(root)

        self._delegate = FolderDelegate(self)
        self._tree.setItemDelegate(self._delegate)

        layout.addWidget(self._tree, 1)

        self.setMinimumWidth(180)

    def _rebuild_pin_bar(self):
        while self._pin_bar.count():
            item = self._pin_bar.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for folder in self._pinned:
            btn = QPushButton(f"📌 {Path(folder).name}")
            btn.setToolTip(folder)
            btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 2px 6px; border: none; }"
                "QPushButton:hover { background: rgba(255,255,255,0.08); }")
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
        if path:
            self.folder_selected.emit(path)

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
        """Update project reference for asset counts."""
        self._project = project
        self._update_folder_counts()

    def _update_folder_counts(self):
        """Recompute folder → asset count mapping from project data."""
        self._folder_counts.clear()
        if not self._project:
            return
        for asset in self._project.assets:
            folder = asset.source_folder or str(Path(asset.source_path).parent)
            folder = folder.replace("\\", "/")
            self._folder_counts[folder] = self._folder_counts.get(folder, 0) + 1

    def get_folder_count(self, folder_path: str) -> int:
        """Return asset count for a folder (recursive — includes subfolders)."""
        folder_path = folder_path.replace("\\", "/").rstrip("/")
        count = self._folder_counts.get(folder_path, 0)
        # Add counts from subfolders
        prefix = folder_path + "/"
        for path, c in self._folder_counts.items():
            if path.startswith(prefix):
                count += c
        return count
