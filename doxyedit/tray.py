"""Work tray — a collapsible right panel for quick-access images."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QAbstractItemView, QMenu,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QIcon, QFont


class WorkTray(QWidget):
    """Collapsible right panel — drag images here as a work area / quickslot."""
    asset_selected = Signal(str)   # asset_id clicked
    asset_preview = Signal(str)    # double-click

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("doxyedit_tray")
        self.setMinimumWidth(120)
        self.setMaximumWidth(300)
        self._asset_ids: list[str] = []
        self._pixmaps: dict[str, QPixmap] = {}
        self._paths: dict[str, str] = {}  # asset_id → source_path
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        title = QLabel("Work Tray")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()

        self._collapse_btn = QPushButton("\u25B6")  # ▶ collapsed, ▼ expanded
        self._collapse_btn.setFixedSize(22, 22)
        self._collapse_btn.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        header.addWidget(self._collapse_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedHeight(22)
        self._clear_btn.setStyleSheet("QPushButton { padding: 2px 8px; }")
        self._clear_btn.clicked.connect(self.clear)
        header.addWidget(self._clear_btn)
        layout.addLayout(header)
        self._collapsed = False
        self._collapse_btn.setText("\u25BC")  # ▼ expanded

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
        item.setText(name)
        item.setData(Qt.ItemDataRole.UserRole, asset_id)
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

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._list.setVisible(not self._collapsed)
        self._count_label.setVisible(not self._collapsed)
        self._clear_btn.setVisible(not self._collapsed)
        self._collapse_btn.setText("\u25B6" if self._collapsed else "\u25BC")

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
        menu.addAction("Copy Path", lambda: self._copy_path(asset_id))
        menu.addAction("Open in Explorer", lambda: self._open_explorer(asset_id))
        menu.addSeparator()
        menu.addAction("Remove from Tray", lambda: self.remove_asset(asset_id))
        menu.addAction("Clear All", self.clear)
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _copy_path(self, asset_id: str):
        from PySide6.QtWidgets import QApplication
        path = self._paths.get(asset_id, "")
        if path:
            QApplication.clipboard().setText(path)

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
