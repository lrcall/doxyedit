"""Work tray — a collapsible right panel for quick-access images."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QAbstractItemView, QMenu,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QIcon, QFont


NAME_ROLE = Qt.ItemDataRole.UserRole + 1  # stores display name for view mode switching


class WorkTray(QWidget):
    """Collapsible right panel — drag images here as a work area / quickslot."""
    asset_selected = Signal(str)
    asset_preview = Signal(str)
    tags_modified = Signal()
    toggle_requested = Signal()    # handle clicked — parent toggles visibility

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("doxyedit_tray")
        self.setMinimumWidth(150)
        self.setMaximumWidth(400)
        self._asset_ids: list[str] = []
        self._pixmaps: dict[str, QPixmap] = {}
        self._project = None
        self._paths: dict[str, str] = {}  # asset_id → source_path
        self._build()

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Handle — clickable arrow on left edge
        self._handle = QPushButton("\u25C0")  # ◀
        self._handle.setFixedWidth(16)
        self._handle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._handle.setToolTip("Close tray (Ctrl+T)")
        self._handle.setStyleSheet(
            "QPushButton { background: rgba(128,128,128,0.15); border: none;"
            " border-radius: 0; font-size: 10px; color: rgba(128,128,128,0.6); }"
            "QPushButton:hover { background: rgba(128,128,128,0.3); }")
        self._handle.clicked.connect(lambda: self.toggle_requested.emit())
        outer.addWidget(self._handle)

        # Content (hideable)
        self._content = QWidget()
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        outer.addWidget(self._content)

        # Header
        header = QHBoxLayout()
        title = QLabel("Work Tray")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()

        self._view_btn = QPushButton("\u2630")  # ☰ hamburger
        self._view_btn.setFixedSize(22, 22)
        self._view_btn.setToolTip("Cycle view: list / 2-col / 3-col")
        self._view_btn.setStyleSheet("QPushButton { padding: 2px; }")
        self._view_btn.clicked.connect(self._cycle_view_mode)
        self._view_mode = 0  # 0=list, 1=2col, 2=3col
        header.addWidget(self._view_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedHeight(22)
        self._clear_btn.setStyleSheet("QPushButton { padding: 2px 8px; }")
        self._clear_btn.clicked.connect(self.clear)
        header.addWidget(self._clear_btn)

        self._close_btn = QPushButton("\u2715")  # ✕
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setToolTip("Close tray (Ctrl+T)")
        self._close_btn.setStyleSheet("QPushButton { padding: 2px; }")
        self._close_btn.clicked.connect(lambda: self.toggle_requested.emit())
        header.addWidget(self._close_btn)
        layout.addLayout(header)

        # Count
        self._count_label = QLabel("0 items")
        self._count_label.setStyleSheet("color: rgba(128,128,128,0.6);")
        layout.addWidget(self._count_label)

        # List widget — shows thumbnails vertically
        self._list = QListWidget()
        self._list.setIconSize(QSize(80, 80))
        self._list.setSpacing(2)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self._list.setAcceptDrops(True)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.setStyleSheet("QListWidget { border: none; }")
        layout.addWidget(self._list)

    def add_asset(self, asset_id: str, name: str, pixmap: QPixmap = None, path: str = ""):
        """Add an asset to the tray."""
        if asset_id in self._asset_ids:
            return
        self._asset_ids.append(asset_id)
        if path:
            self._paths[asset_id] = path

        item = QListWidgetItem()
        item.setText(name if self._view_mode == 0 else "")
        item.setData(Qt.ItemDataRole.UserRole, asset_id)
        item.setData(NAME_ROLE, name)  # store name for mode switching
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            item.setIcon(QIcon(scaled))
            self._pixmaps[asset_id] = pixmap
        self._list.addItem(item)
        self._update_count()

    def remove_asset(self, asset_id: str):
        """Remove an asset from the tray."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == asset_id:
                self._list.takeItem(i)
                break
        if asset_id in self._asset_ids:
            self._asset_ids.remove(asset_id)
        self._pixmaps.pop(asset_id, None)
        self._paths.pop(asset_id, None)
        self._update_count()

    def clear(self):
        self._list.clear()
        self._asset_ids.clear()
        self._pixmaps.clear()
        self._update_count()

    def get_asset_ids(self) -> list[str]:
        return list(self._asset_ids)

    def _update_count(self):
        n = len(self._asset_ids)
        self._count_label.setText(f"{n} item{'s' if n != 1 else ''}")

    def _on_item_clicked(self, item):
        asset_id = item.data(Qt.ItemDataRole.UserRole)
        if asset_id:
            self.asset_selected.emit(asset_id)

    def _on_item_double_clicked(self, item):
        asset_id = item.data(Qt.ItemDataRole.UserRole)
        if asset_id:
            self.asset_preview.emit(asset_id)

    def _on_context_menu(self, pos):
        item = self._list.itemAt(pos)
        if not item:
            return
        asset_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("Preview", lambda: self.asset_preview.emit(asset_id))
        menu.addSeparator()
        menu.addAction("Copy Path", lambda: self._copy_path(asset_id))
        menu.addAction("Copy Filename", lambda: self._copy_filename(asset_id))
        menu.addAction("Open in Explorer", lambda: self._open_explorer(asset_id))
        menu.addSeparator()
        menu.addAction("Move to Top", lambda: self._move_to_top(asset_id))
        menu.addAction("Move to Bottom", lambda: self._move_to_bottom(asset_id))
        # Quick Tag
        if self._project:
            asset = self._project.get_asset(asset_id)
            if asset:
                all_tags = list(self._project.get_tags().values())
                if all_tags:
                    qt_menu = menu.addMenu("Quick Tag")
                    for tag in all_tags:
                        checked = tag.id in asset.tags
                        a = qt_menu.addAction(f"{'✓ ' if checked else '   '}{tag.label}")
                        a.triggered.connect(lambda _, aid=asset_id, tid=tag.id: self._toggle_tray_tag(aid, tid))
        menu.addSeparator()
        menu.addAction("Remove from Tray", lambda: self.remove_asset(asset_id))
        n = self._list.count()
        if n > 1:
            menu.addAction(f"Clear All ({n})", self.clear)
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _copy_filename(self, asset_id: str):
        from PySide6.QtWidgets import QApplication
        path = self._paths.get(asset_id, "")
        if path:
            QApplication.clipboard().setText(Path(path).name)

    def _move_to_top(self, asset_id: str):
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == asset_id:
                taken = self._list.takeItem(i)
                self._list.insertItem(0, taken)
                self._asset_ids.remove(asset_id)
                self._asset_ids.insert(0, asset_id)
                break

    def _move_to_bottom(self, asset_id: str):
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == asset_id:
                taken = self._list.takeItem(i)
                self._list.addItem(taken)
                self._asset_ids.remove(asset_id)
                self._asset_ids.append(asset_id)
                break

    def _copy_path(self, asset_id: str):
        from PySide6.QtWidgets import QApplication
        path = self._paths.get(asset_id, "")
        if path:
            QApplication.clipboard().setText(path)

    def _cycle_view_mode(self):
        self._view_mode = (self._view_mode + 1) % 3
        if self._view_mode == 0:
            # List mode — full filename + icon
            self._view_btn.setText("\u2630")
            self._list.setViewMode(QListWidget.ViewMode.ListMode)
            self._list.setIconSize(QSize(80, 80))
            self._list.setGridSize(QSize())  # auto
            self._list.setSpacing(2)
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item and item.data(NAME_ROLE):
                    item.setText(item.data(NAME_ROLE))
        else:
            # Grid modes — icon only, no text
            cell = 120 if self._view_mode == 1 else 80
            icon = cell - 10
            self._view_btn.setText(f"{self._view_mode + 1}col")
            self._list.setViewMode(QListWidget.ViewMode.IconMode)
            self._list.setIconSize(QSize(icon, icon))
            self._list.setGridSize(QSize(cell, cell))
            self._list.setSpacing(2)
            # Store name and clear text so grid is clean
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item:
                    if not item.data(NAME_ROLE):
                        item.setData(NAME_ROLE, item.text())
                    item.setText("")

    def _toggle_tray_tag(self, asset_id: str, tag_id: str):
        if not hasattr(self, '_project') or not self._project:
            return
        from doxyedit.models import toggle_tags
        asset = self._project.get_asset(asset_id)
        if asset:
            toggle_tags([asset], tag_id)
            self.tags_modified.emit()

    def _open_explorer(self, asset_id: str):
        import subprocess
        path = self._paths.get(asset_id, "").replace("/", "\\")
        if path:
            subprocess.Popen(f'explorer /select,"{path}"')

    # --- Save/Load ---

    def save_state(self) -> list[str]:
        return list(self._asset_ids)

    def load_state(self, asset_ids: list[str], project):
        """Restore tray from saved asset IDs."""
        self.clear()
        for aid in asset_ids:
            asset = project.get_asset(aid)
            if asset:
                self.add_asset(aid, Path(asset.source_path).name, path=asset.source_path)

    def update_pixmap(self, asset_id: str, pixmap: QPixmap):
        """Update thumbnail for an item already in the tray."""
        if asset_id not in self._asset_ids:
            return
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == asset_id:
                scaled = pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                item.setIcon(QIcon(scaled))
                self._pixmaps[asset_id] = pixmap
                break
