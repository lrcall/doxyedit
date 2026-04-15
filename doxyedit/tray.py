"""Work tray — a collapsible right panel for quick-access images."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QAbstractItemView, QMenu, QApplication,
    QTabBar, QInputDialog,
)
from PySide6.QtCore import Qt, Signal, QSize, QUrl, QMimeData
from PySide6.QtGui import QPixmap, QIcon, QDrag


NAME_ROLE = Qt.ItemDataRole.UserRole + 1  # stores display name for view mode switching
PATH_ROLE = Qt.ItemDataRole.UserRole + 2  # stores source_path for drag-out


class DragOutListWidget(QListWidget):
    """QListWidget that supports dragging items out as file URLs and accepting drops."""

    drop_received = Signal(list)  # list of file paths dropped onto the tray

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def startDrag(self, supportedActions):
        items = self.selectedItems()
        if not items:
            return
        mime = QMimeData()
        urls = []
        for item in items:
            path = item.data(PATH_ROLE)
            if path:
                urls.append(QUrl.fromLocalFile(path))
        if not urls:
            return
        mime.setUrls(urls)
        drag = QDrag(self)
        drag.setMimeData(mime)
        # Use the first item's icon as drag pixmap
        icon = items[0].icon()
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(64, 64))
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("drag_over", True)
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.setProperty("drag_over", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            item = self.itemAt(event.pos())
            if item:
                path = item.data(PATH_ROLE)
                if path:
                    from doxyedit.preview import HoverPreview
                    from PySide6.QtGui import QCursor
                    HoverPreview.instance().show_for(path, QCursor.pos())
                    return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            from doxyedit.preview import HoverPreview
            HoverPreview.instance().hide_preview()
            return
        super().mouseReleaseEvent(event)

    def dropEvent(self, event):
        self.setProperty("drag_over", False)
        self.style().unpolish(self)
        self.style().polish(self)
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls()
                     if url.isLocalFile()]
            if paths:
                self.drop_received.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class WorkTray(QWidget):
    """Collapsible right panel — drag images here as a work area / quickslot."""
    asset_selected = Signal(str)
    asset_preview = Signal(str)
    asset_to_studio = Signal(str)   # send asset to Studio tab
    star_modified = Signal()
    tags_modified = Signal()
    toggle_requested = Signal()    # handle clicked — parent toggles visibility
    pixmaps_needed = Signal(list)  # list of asset_ids that need thumbnails

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("doxyedit_tray")
        from PySide6.QtCore import QSettings
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        TRAY_MIN_WIDTH_RATIO = 12.5        # work tray minimum width
        self.setMinimumWidth(int(_f * TRAY_MIN_WIDTH_RATIO))
        self._asset_ids: list[str] = []
        self._id_to_row: dict[str, int] = {}  # asset_id → list row index for O(1) lookup
        self._pixmaps: dict[str, QPixmap] = {}
        self._project = None
        self._paths: dict[str, str] = {}  # asset_id → source_path
        # Named trays: tray_name → list of asset_ids
        self._trays: dict[str, list[str]] = {"Tray 1": []}
        self._current_tray: str = "Tray 1"
        self._build()

    def _build(self):
        from PySide6.QtCore import QSettings
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _cb = max(14, _f + 2)
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Handle — clickable arrow on left edge
        self._handle = QPushButton("\u25C0")  # ◀
        self._handle.setObjectName("tray_handle")
        self._handle.setFixedWidth(max(12, int(_f * 1.33)))
        self._handle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._handle.setToolTip("Close tray (Ctrl+T)")
        self._handle.clicked.connect(lambda: self.toggle_requested.emit())
        outer.addWidget(self._handle)

        # Content (hideable)
        self._content = QWidget()
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(0, _pad, 0, 0)
        layout.setSpacing(_pad)
        outer.addWidget(self._content)

        # Header
        header = QHBoxLayout()
        title = QLabel("Work Tray")
        f = title.font(); f.setBold(True); title.setFont(f)
        header.addWidget(title)
        header.addStretch()

        self._view_btn = QPushButton("\u2630")  # ☰ hamburger
        self._view_btn.setObjectName("tray_small_btn")
        self._view_btn.setFixedSize(_cb, _cb)
        self._view_btn.setToolTip("Cycle view: list / 2-col / 3-col")
        self._view_btn.clicked.connect(self._cycle_view_mode)
        self._view_mode = 0  # 0=list, 1=2col, 2=3col
        header.addWidget(self._view_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setObjectName("tray_action_btn")
        self._clear_btn.setFixedHeight(_cb)
        self._clear_btn.clicked.connect(self.clear)
        header.addWidget(self._clear_btn)

        self._close_btn = QPushButton("\u2715")  # ✕
        self._close_btn.setObjectName("tray_small_btn")
        self._close_btn.setFixedSize(_cb, _cb)
        self._close_btn.setToolTip("Close tray (Ctrl+T)")
        self._close_btn.clicked.connect(lambda: self.toggle_requested.emit())
        header.addWidget(self._close_btn)
        layout.addLayout(header)

        # Tab bar for named trays
        self._tab_bar = QTabBar()
        self._tab_bar.setObjectName("tray_tab_bar")
        self._tab_bar.setExpanding(False)
        self._tab_bar.setTabsClosable(False)
        self._tab_bar.setMovable(True)
        self._tab_bar.addTab("Tray 1")
        self._add_tray_btn = QPushButton("+")
        self._add_tray_btn.setObjectName("tray_small_btn")
        self._add_tray_btn.setFixedSize(_cb, _cb)
        self._add_tray_btn.setToolTip("New tray")
        self._add_tray_btn.clicked.connect(self._add_tray)
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(max(2, _pad // 2))
        tab_row.addWidget(self._tab_bar, 1)
        tab_row.addWidget(self._add_tray_btn)
        layout.addLayout(tab_row)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        self._tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tab_bar.customContextMenuRequested.connect(self._tab_context_menu)

        # Count
        self._count_label = QLabel("0 items")
        self._count_label.setObjectName("tray_count")
        layout.addWidget(self._count_label)

        # List widget — shows thumbnails vertically
        self._list = DragOutListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setIconSize(QSize(80, 80))
        self._list.setSpacing(max(2, _pad // 2))
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._list.setDragEnabled(True)
        self._list.drop_received.connect(self._on_drop_received)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.setObjectName("tray_list")
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.verticalScrollBar().setSingleStep(20)
        layout.addWidget(self._list)

    def _rebuild_index(self):
        """Rebuild the id→row mapping from _asset_ids."""
        self._id_to_row = {aid: i for i, aid in enumerate(self._asset_ids)}

    def add_asset(self, asset_id: str, name: str, pixmap: QPixmap = None, path: str = ""):
        """Add an asset to the tray."""
        if asset_id in self._asset_ids:
            return
        self._asset_ids.append(asset_id)
        self._id_to_row[asset_id] = len(self._asset_ids) - 1
        if path:
            self._paths[asset_id] = path

        item = QListWidgetItem()
        item.setText(name if self._view_mode == 0 else "")
        item.setData(Qt.ItemDataRole.UserRole, asset_id)
        item.setData(NAME_ROLE, name)  # store name for mode switching
        item.setData(PATH_ROLE, path)  # store path for drag-out
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            item.setIcon(QIcon(scaled))
            self._pixmaps[asset_id] = pixmap
        self._list.addItem(item)
        self._update_count()

    def remove_asset(self, asset_id: str):
        """Remove an asset from the tray."""
        row = self._id_to_row.get(asset_id)
        if row is not None:
            self._list.takeItem(row)
            self._asset_ids.remove(asset_id)
            del self._id_to_row[asset_id]
            self._rebuild_index()  # reindex after removal shifts rows
        self._pixmaps.pop(asset_id, None)
        self._paths.pop(asset_id, None)
        self._update_count()

    def clear(self):
        self._list.clear()
        self._asset_ids.clear()
        self._id_to_row.clear()
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

    def _get_selected_ids(self) -> list[str]:
        """Return asset IDs of all selected tray items."""
        return [item.data(Qt.ItemDataRole.UserRole)
                for item in self._list.selectedItems()
                if item.data(Qt.ItemDataRole.UserRole)]

    def _on_context_menu(self, pos):
        item = self._list.itemAt(pos)
        if not item:
            return
        asset_id = item.data(Qt.ItemDataRole.UserRole)
        selected = self._get_selected_ids()
        if asset_id not in selected:
            selected = [asset_id]
        n_sel = len(selected)
        multi = n_sel > 1
        asset = self._project.get_asset(asset_id) if self._project else None

        menu = QMenu(self)

        menu.addAction("Preview", lambda: self.asset_preview.emit(asset_id))
        menu.addAction("Open in Studio", lambda: self.asset_to_studio.emit(asset_id))
        menu.addSeparator()

        # Star actions
        if asset:
            if asset.starred > 0:
                menu.addAction("Unstar", lambda: self._set_star(asset_id, 0))
                menu.addAction("Cycle Star Color", lambda: self._set_star(asset_id, (asset.starred % 5) + 1))
            else:
                menu.addAction("Star", lambda: self._set_star(asset_id, 1))

        menu.addSeparator()

        # Copy
        if multi:
            menu.addAction(f"Copy All Paths ({n_sel})", lambda: QApplication.clipboard().setText(
                "\n".join(self._paths.get(aid, aid) for aid in selected)))
        else:
            menu.addAction("Copy Path", lambda: self._copy_path(asset_id))
            menu.addAction("Copy Filename", lambda: self._copy_filename(asset_id))
            menu.addAction("Copy Name (no ext)", lambda: self._copy_stem(asset_id))
        menu.addAction("Open in Explorer", lambda: self._open_explorer(asset_id))

        if asset and asset.source_path:
            import os
            menu.addAction("Open in Native Editor", lambda: os.startfile(asset.source_path))

        menu.addSeparator()

        if not multi:
            menu.addAction("Move to Top", lambda: self._move_to_top(asset_id))
            menu.addAction("Move to Bottom", lambda: self._move_to_bottom(asset_id))

        # Quick Tag — user-defined tags only
        if self._project and asset:
            custom_ids = set(self._project.tag_definitions.keys())
            custom_tags = [t for t in self._project.get_tags().values() if t.id in custom_ids]
            if custom_tags:
                qt_menu = menu.addMenu("Quick Tag")
                for tag in custom_tags:
                    checked = tag.id in asset.tags
                    a = qt_menu.addAction(f"{'✓ ' if checked else '   '}{tag.label}")
                    if multi:
                        a.triggered.connect(lambda _, sids=list(selected), tid=tag.id: [
                            self._toggle_tray_tag(aid, tid) for aid in sids])
                    else:
                        a.triggered.connect(lambda _, aid=asset_id, tid=tag.id: self._toggle_tray_tag(aid, tid))

            # Current tags (click to remove)
            if asset.tags:
                cur_menu = menu.addMenu(f"Tags ({len(asset.tags)})")
                tag_defs = self._project.get_tags()
                for t in asset.tags:
                    label = tag_defs[t].label if t in tag_defs else t
                    cur_menu.addAction(f"\u2212 {label}",
                        lambda _, aid=asset_id, tid=t: self._remove_tray_tag(aid, tid))

        menu.addSeparator()

        # Send to other tray
        other_trays = [name for name in self._trays if name != self._current_tray]
        if other_trays:
            send_menu = menu.addMenu("Send to Tray")
            for tray_name in other_trays:
                if multi:
                    send_menu.addAction(f"{tray_name} ({n_sel})",
                        lambda _, sids=list(selected), tn=tray_name: [self._send_to_other_tray(aid, tn) for aid in sids])
                else:
                    send_menu.addAction(tray_name,
                        lambda _, aid=asset_id, tn=tray_name: self._send_to_other_tray(aid, tn))

        menu.addSeparator()
        if multi:
            menu.addAction(f"Remove {n_sel} from Tray", lambda: [self.remove_asset(aid) for aid in list(selected)])
        else:
            menu.addAction("Remove from Tray", lambda: self.remove_asset(asset_id))
        n = self._list.count()
        if n > 1:
            menu.addAction(f"Clear All ({n})", self.clear)
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _send_to_other_tray(self, asset_id: str, tray_name: str):
        """Move an asset from current tray to another tray."""
        if tray_name not in self._trays:
            return
        if asset_id not in self._trays[tray_name]:
            self._trays[tray_name].append(asset_id)
        self.remove_asset(asset_id)

    def _copy_filename(self, asset_id: str):
        from PySide6.QtWidgets import QApplication
        path = self._paths.get(asset_id, "")
        if path:
            QApplication.clipboard().setText(Path(path).name)

    def _copy_stem(self, asset_id: str):
        from PySide6.QtWidgets import QApplication
        path = self._paths.get(asset_id, "")
        if path:
            QApplication.clipboard().setText(Path(path).stem)

    def _move_to_top(self, asset_id: str):
        row = self._id_to_row.get(asset_id)
        if row is None:
            return
        item = self._list.takeItem(row)
        self._list.insertItem(0, item)
        self._asset_ids.remove(asset_id)
        self._asset_ids.insert(0, asset_id)
        self._rebuild_index()

    def _move_to_bottom(self, asset_id: str):
        row = self._id_to_row.get(asset_id)
        if row is None:
            return
        item = self._list.takeItem(row)
        self._list.addItem(item)
        self._asset_ids.remove(asset_id)
        self._asset_ids.append(asset_id)
        self._rebuild_index()

    def _copy_path(self, asset_id: str):
        from PySide6.QtWidgets import QApplication
        path = self._paths.get(asset_id, "")
        if path:
            QApplication.clipboard().setText(path)

    def _cycle_view_mode(self):
        from PySide6.QtCore import QSettings
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        self._view_mode = (self._view_mode + 1) % 3
        if self._view_mode == 0:
            # List mode — full filename + icon
            self._view_btn.setText("\u2630")
            self._list.setViewMode(QListWidget.ViewMode.ListMode)
            self._list.setIconSize(QSize(80, 80))
            self._list.setGridSize(QSize())  # auto
            self._list.setSpacing(max(2, _pad // 2))
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
            self._list.setSpacing(max(2, _pad // 2))
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

    def _remove_tray_tag(self, asset_id: str, tag_id: str):
        """Remove a specific tag from an asset."""
        if not self._project:
            return
        asset = self._project.get_asset(asset_id)
        if asset and tag_id in asset.tags:
            asset.tags.remove(tag_id)
            self.tags_modified.emit()

    def _set_star(self, asset_id: str, value: int):
        """Set star rating for an asset."""
        if not self._project:
            return
        asset = self._project.get_asset(asset_id)
        if asset:
            asset.starred = value
            self.star_modified.emit()

    def _on_drop_received(self, paths: list):
        """Handle files dropped onto the tray — resolve to project assets and add."""
        if not self._project:
            return
        # Build path→asset lookup
        path_map = {a.source_path.replace("\\", "/"): a
                    for a in self._project.assets}
        for path in paths:
            norm = path.replace("\\", "/")
            asset = path_map.get(norm)
            if asset and asset.id not in self._asset_ids:
                self.add_asset(asset.id, Path(path).name, path=path)
        # Request thumbnails for newly added items
        self.pixmaps_needed.emit(list(self._asset_ids))

    def _open_explorer(self, asset_id: str):
        import subprocess
        path = self._paths.get(asset_id, "").replace("/", "\\")
        if path:
            subprocess.Popen(f'explorer /select,"{path}"')

    # --- Tab management ---

    def _add_tray(self):
        n = self._tab_bar.count() + 1
        name = f"Tray {n}"
        self._trays[name] = []
        self._tab_bar.addTab(name)
        self._tab_bar.setCurrentIndex(self._tab_bar.count() - 1)

    def _on_tab_changed(self, index: int):
        if index < 0:
            return
        # Save current tray contents
        self._trays[self._current_tray] = list(self._asset_ids)
        # Switch to new tray
        new_name = self._tab_bar.tabText(index)
        self._current_tray = new_name
        # Reload list from stored data
        self._list.clear()
        self._asset_ids.clear()
        self._id_to_row.clear()
        self._pixmaps.clear()
        self._paths.clear()
        for aid in self._trays.get(new_name, []):
            if self._project:
                asset = self._project.get_asset(aid)
                if asset:
                    self.add_asset(aid, Path(asset.source_path).name, path=asset.source_path)
        # Request thumbnails for the newly visible items
        if self._asset_ids:
            self.pixmaps_needed.emit(list(self._asset_ids))

    def _tab_context_menu(self, pos):
        index = self._tab_bar.tabAt(pos)
        if index < 0:
            return
        name = self._tab_bar.tabText(index)
        menu = QMenu(self)
        menu.addAction("Rename", lambda: self._rename_tray(index))
        if self._tab_bar.count() > 1:
            menu.addAction("Close", lambda: self._close_tray(index))
        menu.exec(self._tab_bar.mapToGlobal(pos))

    def _rename_tray(self, index: int):
        old_name = self._tab_bar.tabText(index)
        new_name, ok = QInputDialog.getText(self, "Rename Tray", "Name:", text=old_name)
        if ok and new_name.strip() and new_name != old_name:
            new_name = new_name.strip()
            self._trays[new_name] = self._trays.pop(old_name, [])
            if self._current_tray == old_name:
                self._current_tray = new_name
            self._tab_bar.setTabText(index, new_name)

    def _close_tray(self, index: int):
        name = self._tab_bar.tabText(index)
        self._trays.pop(name, None)
        self._tab_bar.removeTab(index)
        # If we closed the active tray, switch to first remaining
        if name == self._current_tray:
            self._current_tray = self._tab_bar.tabText(0)

    # --- Save/Load ---

    def save_state(self):
        """Return tray data. Dict of tray_name → asset_ids for named trays."""
        # Save current tray before serializing
        self._trays[self._current_tray] = list(self._asset_ids)
        if len(self._trays) == 1 and "Tray 1" in self._trays:
            # Single default tray — save as plain list for backward compat
            return self._trays["Tray 1"]
        return dict(self._trays)

    def load_state(self, data, project):
        """Restore tray from saved data (list for compat, or dict for named trays)."""
        self._project = project
        self.clear()
        # Backward compat: plain list → single "Tray 1"
        if isinstance(data, list):
            tray_dict = {"Tray 1": data}
        elif isinstance(data, dict):
            tray_dict = data
        else:
            tray_dict = {"Tray 1": []}

        self._trays = tray_dict
        # Rebuild tab bar — keep signals blocked through setCurrentIndex
        # to prevent _on_tab_changed from wiping tray data
        self._tab_bar.blockSignals(True)
        while self._tab_bar.count():
            self._tab_bar.removeTab(0)
        for name in tray_dict:
            self._tab_bar.addTab(name)
        first_name = next(iter(tray_dict), "Tray 1")
        self._current_tray = first_name
        self._tab_bar.setCurrentIndex(0)
        self._tab_bar.blockSignals(False)
        for aid in tray_dict.get(first_name, []):
            asset = project.get_asset(aid)
            if asset:
                self.add_asset(aid, Path(asset.source_path).name, path=asset.source_path)

    def update_pixmap(self, asset_id: str, pixmap: QPixmap):
        """Update thumbnail for an item already in the tray."""
        row = self._id_to_row.get(asset_id)
        if row is None:
            return
        item = self._list.item(row)
        if item:
            scaled = pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            item.setIcon(QIcon(scaled))
            self._pixmaps[asset_id] = pixmap
