"""Work tray — a collapsible right panel for quick-access images."""
import os
import time
from collections import deque
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QAbstractItemView, QMenu, QApplication,
    QTabBar, QInputDialog, QStyledItemDelegate, QSplitter,
)
from PySide6.QtCore import (
    Qt, Signal, QSize, QUrl, QMimeData, QSettings, QEvent, QRect, QTimer,
)
from PySide6.QtGui import QPixmap, QIcon, QDrag, QCursor, QColor, QBrush, QPen
from doxyedit.themes import ui_font_size, THEMES, DEFAULT_THEME
from doxyedit.preview import HoverPreview
from doxyedit.models import toggle_tags


NAME_ROLE = Qt.ItemDataRole.UserRole + 1  # stores display name for view mode switching
PATH_ROLE = Qt.ItemDataRole.UserRole + 2  # stores source_path for drag-out
TRAY_ICON_SIZE = 80
MIN_HANDLE_WIDTH = 12
# Custom mime so tab-bar drops can recover asset IDs directly instead
# of having to reverse-map file URLs back to project asset IDs.
TRAY_IDS_MIME = "application/x-doxyedit-tray-ids"


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
        ids = []
        for item in items:
            path = item.data(PATH_ROLE)
            aid = item.data(Qt.ItemDataRole.UserRole)
            if path:
                urls.append(QUrl.fromLocalFile(path))
            if aid:
                ids.append(aid)
        if not urls and not ids:
            return
        if urls:
            mime.setUrls(urls)
        if ids:
            # Custom mime lets tab-bar drops identify assets without having
            # to reverse-resolve URLs back to asset IDs.
            mime.setData(TRAY_IDS_MIME, ",".join(ids).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        # Use the first item's icon as drag pixmap
        icon = items[0].icon()
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(64, 64))
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)

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
                    HoverPreview.instance().show_for(path, QCursor.pos())
                    return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
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


class TrayItemDelegate(QStyledItemDelegate):
    """Paint star, tag dots, and platform-assignment badge on top of the
    standard icon+text cell. Reads live Asset state from the tray's
    project reference so toggles apply without a rebuild."""

    STAR_CHAR = "★"  # BLACK STAR
    TAG_DOT_RADIUS = 4
    TAG_DOT_MAX = 5
    BADGE_PAD = 4

    def __init__(self, tray, parent=None):
        super().__init__(parent)
        self._tray = tray

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        aid = index.data(Qt.ItemDataRole.UserRole)
        project = getattr(self._tray, "_project", None)
        if not aid or project is None:
            return
        asset = project.get_asset(aid)
        if asset is None:
            return
        theme = THEMES[DEFAULT_THEME]
        rect = option.rect
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)

        # Pulse ring (T18) — drawn first so other overlays sit on top
        pulse_until = self._tray._pulse_until.get(aid)
        if pulse_until:
            remaining = pulse_until - time.monotonic()
            if remaining > 0:
                # Fade alpha from 220 -> 0 over the remaining time
                alpha = max(40, int(220 * min(1.0, remaining / 0.4)))
                ring = QColor(theme.accent_bright or theme.accent)
                ring.setAlpha(alpha)
                pen = QPen(ring, 3)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(
                    rect.adjusted(2, 2, -2, -2), 4, 4)

        # Pin indicator top-right (T16) — painted before platform badge
        # so the badge (bottom-right) doesn't fight it.
        if self._tray._is_pinned(aid):
            pad = 4
            size = 10
            pin_x = rect.right() - size - pad
            pin_y = rect.top() + pad
            pin_color = QColor(theme.accent_bright or theme.accent)
            painter.setPen(QPen(QColor(theme.border), 1))
            painter.setBrush(QBrush(pin_color))
            painter.drawEllipse(pin_x, pin_y, size, size)

        # Star overlay top-left
        if getattr(asset, "starred", 0) > 0:
            size = max(12, option.decorationSize.width() // 6)
            f = painter.font()
            f.setPixelSize(size)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(QPen(QColor(theme.star)))
            painter.drawText(
                QRect(rect.left() + 4, rect.top() + 2, size * 2, size + 2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                self.STAR_CHAR)

        # Tag dots bottom-left
        tag_defs = project.tag_definitions or {}
        if asset.tags:
            dot_r = self.TAG_DOT_RADIUS
            dy = rect.bottom() - dot_r - 3
            dx = rect.left() + 6
            shown = asset.tags[:self.TAG_DOT_MAX]
            for tid in shown:
                hex_color = tag_defs.get(tid, {}).get("color", theme.accent)
                painter.setPen(QPen(QColor(theme.border), 1))
                painter.setBrush(QBrush(QColor(hex_color)))
                painter.drawEllipse(dx, dy - dot_r, dot_r * 2, dot_r * 2)
                dx += dot_r * 2 + 2
            if len(asset.tags) > self.TAG_DOT_MAX:
                # "+N" indicator
                painter.setPen(QPen(QColor(theme.text_muted)))
                f = painter.font()
                f.setPixelSize(9)
                f.setBold(True)
                painter.setFont(f)
                painter.drawText(dx, dy + 4,
                                  f"+{len(asset.tags) - self.TAG_DOT_MAX}")

        # Platform badge bottom-right
        assignments = getattr(asset, "assignments", None) or []
        if assignments:
            count = len(assignments)
            text = f"{count}P"
            pad = self.BADGE_PAD
            f = painter.font()
            f.setPixelSize(10)
            f.setBold(True)
            painter.setFont(f)
            metrics = painter.fontMetrics()
            bw = metrics.horizontalAdvance(text) + pad * 2
            bh = metrics.height() + 2
            br_x = rect.right() - bw - 4
            br_y = rect.bottom() - bh - 4
            badge_bg = QColor(theme.accent)
            badge_bg.setAlpha(220)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(badge_bg))
            painter.drawRoundedRect(br_x, br_y, bw, bh, 4, 4)
            painter.setPen(QPen(QColor(theme.text_on_accent)))
            painter.drawText(
                QRect(br_x, br_y, bw, bh),
                Qt.AlignmentFlag.AlignCenter, text)

        painter.restore()


class TrayTabBar(QTabBar):
    """QTabBar that accepts drops of tray items so the user can drag items
    from the list onto a target tab to move them. Shift held during drop
    copies instead of moving."""

    def __init__(self, tray, parent=None):
        super().__init__(parent)
        self._tray = tray
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(TRAY_IDS_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(TRAY_IDS_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasFormat(TRAY_IDS_MIME):
            super().dropEvent(event)
            return
        try:
            point = event.position().toPoint()
        except AttributeError:
            point = event.pos()
        target_idx = self.tabAt(point)
        if target_idx < 0:
            event.ignore()
            return
        target_name = self.tabData(target_idx) or self.tabText(target_idx)
        raw = bytes(mime.data(TRAY_IDS_MIME)).decode("utf-8", errors="ignore")
        asset_ids = [i for i in raw.split(",") if i]
        if not asset_ids:
            event.ignore()
            return
        copy = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self._tray._handle_tab_drop(asset_ids, target_name, copy=copy):
            event.acceptProposedAction()
        else:
            event.ignore()


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
        _f = ui_font_size()
        self.setMinimumWidth(0)  # main splitter handles collapsing
        self._asset_ids: list[str] = []
        self._id_to_row: dict[str, int] = {}  # asset_id → list row index for O(1) lookup
        self._pixmaps: dict[str, QPixmap] = {}
        self._project = None
        self._paths: dict[str, str] = {}  # asset_id → source_path
        # Named trays: tray_name → list of asset_ids
        self._trays: dict[str, list[str]] = {"Tray 1": []}
        self._current_tray: str = "Tray 1"
        # Per-tray undo stacks. Each entry: (op, payload) where op is
        # "remove" or "clear" and payload is a list of (asset_id, row)
        # tuples recording where they came from.
        self._undo: dict[str, deque] = {}
        # T18 refresh pulse — asset_id -> monotonic() deadline in seconds.
        # Delegate draws an accent ring while entry is active; a shared
        # QTimer ticks the viewport until the dict empties.
        self._pulse_until: dict[str, float] = {}
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(60)
        self._pulse_timer.timeout.connect(self._on_pulse_tick)
        # T16 pin state (session-only, not persisted). Per tray so the
        # same asset can be pinned in one tray and loose in another.
        self._pinned: dict[str, set[str]] = {}
        self._build()

    def _build(self):
        _f = ui_font_size()
        _cb = max(14, _f + 2)
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Handle — clickable arrow on left edge
        self._handle = QPushButton("\u25C0")  # ◀
        self._handle.setObjectName("tray_handle")
        self._handle.setFixedWidth(max(MIN_HANDLE_WIDTH, int(_f * 1.33)))
        self._handle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._handle.setToolTip("Close tray (Ctrl+Shift+W)")
        self._handle.clicked.connect(lambda: self.toggle_requested.emit())
        outer.addWidget(self._handle)

        # Content (hideable)
        self._content = QWidget()
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(0, _pad, 0, 0)
        layout.setSpacing(_pad)
        outer.addWidget(self._content)

        # Header — title and count label share a "Tray Options" right-click
        header = QHBoxLayout()
        self._title_label = QLabel("Work Tray")
        f = self._title_label.font(); f.setBold(True); self._title_label.setFont(f)
        self._title_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._title_label.setToolTip("Right-click for tray options")
        self._title_label.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._title_label.customContextMenuRequested.connect(
            lambda pos, w=self._title_label: self._header_menu(w, pos))
        header.addWidget(self._title_label)
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
        self._close_btn.setToolTip("Close tray (Ctrl+Shift+W)")
        self._close_btn.clicked.connect(lambda: self.toggle_requested.emit())
        header.addWidget(self._close_btn)
        layout.addLayout(header)

        # Tab bar for named trays. tabData(i) holds the CLEAN tray name;
        # tabText(i) may include a count suffix like "Tray 1 (12)".
        self._tab_bar = TrayTabBar(self)
        self._tab_bar.setObjectName("tray_tab_bar")
        self._tab_bar.setExpanding(False)
        self._tab_bar.setTabsClosable(False)
        self._tab_bar.setMovable(True)
        self._tab_bar.addTab("Tray 1")
        self._tab_bar.setTabData(0, "Tray 1")
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

        # Count — also a right-click handle for Tray Options
        self._count_label = QLabel("0 items")
        self._count_label.setObjectName("tray_count")
        self._count_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._count_label.setToolTip("Right-click for tray options")
        self._count_label.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._count_label.customContextMenuRequested.connect(
            lambda pos, w=self._count_label: self._header_menu(w, pos))
        layout.addWidget(self._count_label)

        # List widget — shows thumbnails vertically
        self._list = DragOutListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setIconSize(QSize(TRAY_ICON_SIZE, TRAY_ICON_SIZE))
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
        # Persist reorder after internal DnD. QListWidget.model().rowsMoved
        # fires after the drop settles; rebuild _asset_ids from the list
        # widget's current row order so save_state writes the new order.
        self._list.model().rowsMoved.connect(
            lambda *_a: self._sync_order_from_list())
        # Keyboard layer: arrows navigate (QListWidget default), Space
        # previews, Enter sends to Studio, Delete removes, 0-5 set stars,
        # Ctrl+D deselects. Ctrl+A (select-all) is native.
        self._list.installEventFilter(self)
        self._list.viewport().installEventFilter(self)
        # Item delegate paints star / tag dots / platform badge on top
        # of the standard icon + name cell.
        self._list.setItemDelegate(TrayItemDelegate(self, self._list))
        # Empty-state hint label — child of the viewport so it covers
        # the scroll area exactly.
        self._empty_label = QLabel(
            "Drag assets here\n\n"
            "Right-click: paste path  /  import folder\n"
            "Ctrl+Shift+W: toggle tray",
            self._list.viewport())
        self._empty_label.setObjectName("tray_empty_state")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.hide()
        layout.addWidget(self._list)

    def _rebuild_index(self):
        """Rebuild the id→row mapping from _asset_ids."""
        self._id_to_row = {aid: i for i, aid in enumerate(self._asset_ids)}

    def _sync_order_from_list(self):
        """Read current row order out of the QListWidget and rewrite
        _asset_ids to match. Called after internal drag-reorder so the
        new order survives save_state."""
        new_order = []
        for i in range(self._list.count()):
            aid = self._list.item(i).data(Qt.ItemDataRole.UserRole)
            if aid:
                new_order.append(aid)
        self._asset_ids = new_order
        self._rebuild_index()

    # --- Keyboard layer ---------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._list and event.type() == QEvent.Type.KeyPress:
            if self._handle_list_key(event):
                return True
        # Keep the empty-state hint sized to the viewport
        if (hasattr(self, "_list")
                and obj is self._list.viewport()
                and event.type() == QEvent.Type.Resize):
            self._update_empty_state()
        return super().eventFilter(obj, event)

    def _handle_list_key(self, event) -> bool:
        """Return True if we consumed the key; False to fall through to the
        list widget's default handling (arrow navigation, etc.)."""
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        if alt:
            return False

        selected = self._get_selected_ids()
        current_item = self._list.currentItem()
        current_aid = (current_item.data(Qt.ItemDataRole.UserRole)
                       if current_item else None)
        targets = selected or ([current_aid] if current_aid else [])

        # Space — preview current item (hover preview)
        if key == Qt.Key.Key_Space and not ctrl and not shift:
            if current_aid:
                self.asset_preview.emit(current_aid)
            return True

        # Enter / Return — send current item to Studio
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not ctrl and not shift:
            if current_aid:
                self.asset_to_studio.emit(current_aid)
            return True

        # Delete — remove all selected (or current). Batch into one
        # undo entry so Ctrl+Z restores the whole selection at once.
        if key == Qt.Key.Key_Delete and not ctrl and not shift:
            if targets:
                payload = [(aid, self._id_to_row.get(aid, 0))
                            for aid in targets if aid in self._id_to_row]
                if payload:
                    self._push_undo("remove", payload)
                for aid in list(targets):
                    self.remove_asset(aid, _record_undo=False)
            return bool(targets)

        # 0-5 — set star rating on all selected (or current)
        if (not ctrl and not shift and
                Qt.Key.Key_0 <= key <= Qt.Key.Key_5):
            star = key - Qt.Key.Key_0  # 0 = unstar, 1-5 = colors
            if targets:
                for aid in targets:
                    self._set_star(aid, star)
                return True
            return False

        # Ctrl+D — deselect all
        if ctrl and not shift and key == Qt.Key.Key_D:
            self._list.clearSelection()
            return True

        # Ctrl+Z — undo last Remove / Clear on this tray
        if ctrl and not shift and key == Qt.Key.Key_Z:
            self._do_undo()
            return True

        return False

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
            scaled = pixmap.scaled(TRAY_ICON_SIZE, TRAY_ICON_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            item.setIcon(QIcon(scaled))
            self._pixmaps[asset_id] = pixmap
        self._list.addItem(item)
        self._update_count()

    def remove_asset(self, asset_id: str, _record_undo: bool = True):
        """Remove an asset from the tray. _record_undo=False skips the
        undo stack so internal callers (undo itself, move-on-close) can
        delete without filling the stack."""
        row = self._id_to_row.get(asset_id)
        if row is not None:
            if _record_undo:
                self._push_undo("remove", [(asset_id, row)])
            self._list.takeItem(row)
            self._asset_ids.remove(asset_id)
            del self._id_to_row[asset_id]
            self._rebuild_index()  # reindex after removal shifts rows
        self._pixmaps.pop(asset_id, None)
        self._paths.pop(asset_id, None)
        self._update_count()

    def clear(self, _record_undo: bool = True):
        """Empty the tray — but keep pinned items in place. Only the
        unpinned set hits the undo stack."""
        pinned = self._pinned.get(self._current_tray, set())
        to_remove = [(aid, i) for i, aid in enumerate(self._asset_ids)
                      if aid not in pinned]
        if not to_remove:
            # Nothing un-pinned; clear is a no-op
            return
        if _record_undo:
            self._push_undo("clear", to_remove)
        # Remove from bottom to top so row indices stay valid
        for aid, _row in sorted(to_remove, key=lambda t: -t[1]):
            row = self._id_to_row.get(aid)
            if row is not None:
                self._list.takeItem(row)
            self._pixmaps.pop(aid, None)
            self._paths.pop(aid, None)
        self._asset_ids = [aid for aid in self._asset_ids if aid in pinned]
        self._rebuild_index()
        self._update_count()

    # --- Undo (T15) ------------------------------------------------------

    def _push_undo(self, op: str, payload: list):
        """Append an undo entry for the active tray, bounded to 10."""
        stack = self._undo.setdefault(self._current_tray, deque(maxlen=10))
        stack.append((op, payload))

    # --- T16 pin ----------------------------------------------------------

    def _is_pinned(self, asset_id: str) -> bool:
        return asset_id in self._pinned.get(self._current_tray, set())

    def _toggle_pin(self, asset_id: str):
        s = self._pinned.setdefault(self._current_tray, set())
        if asset_id in s:
            s.discard(asset_id)
        else:
            s.add(asset_id)
        self._list.viewport().update()

    def _bulk_set_pin(self, asset_ids: list, pinned: bool):
        s = self._pinned.setdefault(self._current_tray, set())
        if pinned:
            s.update(asset_ids)
        else:
            for aid in asset_ids:
                s.discard(aid)
        self._list.viewport().update()

    def _bulk_send_to_studio(self, asset_ids: list):
        """Emit asset_to_studio for each selected id. The window owns the
        actual tab-switching and dispatch."""
        for aid in asset_ids:
            self.asset_to_studio.emit(aid)

    def _bulk_set_star(self, asset_ids: list, value: int):
        """Set star rating on every selected asset (0 unstars, 1-5 colors).
        Uses _set_star so the viewport repaint fires once per asset; then
        a final viewport update covers the batch."""
        if not self._project:
            return
        for aid in asset_ids:
            asset = self._project.get_asset(aid)
            if asset is not None:
                asset.starred = value
        if asset_ids:
            self.star_modified.emit()
            self._list.viewport().update()

    def _export_selection_zip(self, asset_ids: list):
        """Same zip writer as the full-tray export but scoped to the
        given asset id list."""
        if not asset_ids:
            return
        from PySide6.QtWidgets import QFileDialog
        import zipfile
        default_name = f"{self._current_tray.replace(' ', '_')}_sel.zip"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Export selection as ZIP", default_name, "ZIP (*.zip)")
        if not out_path:
            return
        written = 0
        seen_names: dict[str, int] = {}
        try:
            with zipfile.ZipFile(out_path, "w",
                                 compression=zipfile.ZIP_DEFLATED) as zf:
                for aid in asset_ids:
                    src = self._paths.get(aid)
                    if not src or not Path(src).exists():
                        continue
                    arc = Path(src).name
                    seen_names[arc] = seen_names.get(arc, 0) + 1
                    if seen_names[arc] > 1:
                        stem = Path(src).stem
                        ext = Path(src).suffix
                        arc = f"{stem}_{seen_names[arc]}{ext}"
                    zf.write(src, arc)
                    written += 1
        except Exception as e:
            import logging
            logging.error(f"Selection export failed: {e}")
            return
        if written:
            import subprocess
            win_path = out_path.replace("/", "\\")
            subprocess.Popen(f'explorer /select,"{win_path}"')

    def _remove_assets_bulk(self, asset_ids: list):
        """Remove a batch of assets and record one undo entry for the
        whole batch."""
        payload = [(aid, self._id_to_row.get(aid, 0))
                    for aid in asset_ids if aid in self._id_to_row]
        if not payload:
            return
        self._push_undo("remove", payload)
        for aid in list(asset_ids):
            self.remove_asset(aid, _record_undo=False)

    def _do_undo(self):
        """Pop the most recent destructive op for the active tray and
        re-add the affected assets. No-op if the stack is empty."""
        stack = self._undo.get(self._current_tray)
        if not stack:
            return False
        op, payload = stack.pop()
        if not self._project:
            return False
        # Sort by original row so multi-item clears restore in order
        payload_sorted = sorted(payload, key=lambda t: t[1])
        restored = 0
        for aid, row in payload_sorted:
            if aid in self._asset_ids:
                continue
            asset = self._project.get_asset(aid)
            if asset is None:
                continue
            # Re-add using add_asset (appends at end). Post-insert reorder
            # could be done but is lossy vs manual drag; keep simple.
            self.add_asset(
                aid, Path(asset.source_path).name,
                path=asset.source_path)
            restored += 1
        if restored:
            self.pixmaps_needed.emit(list(self._asset_ids))
        return restored > 0

    def get_asset_ids(self) -> list[str]:
        return list(self._asset_ids)

    def _update_count(self):
        n = len(self._asset_ids)
        self._count_label.setText(f"{n} item{'s' if n != 1 else ''}")
        self._refresh_tab_counts()
        self._update_empty_state()

    def _update_empty_state(self):
        """Show / hide the 'Drag assets here' hint based on item count."""
        if not hasattr(self, "_empty_label"):
            return
        vp = self._list.viewport()
        self._empty_label.setGeometry(0, 0, vp.width(), vp.height())
        self._empty_label.setVisible(len(self._asset_ids) == 0)

    def _refresh_tab_counts(self):
        """Update each tab's display text to include a live item count.
        Clean name stays in tabData so rename / context-menu logic can
        fetch it without parsing the '(N)' suffix out. Tooltip gets a
        richer per-tray breakdown (T11)."""
        # Make sure the current tray's internal counter matches the mirror
        if self._current_tray in self._trays:
            # Only the active tray has live _asset_ids; inactive trays
            # hold their count in self._trays[name]
            self._trays[self._current_tray] = list(self._asset_ids)
        for i in range(self._tab_bar.count()):
            name = self._tab_bar.tabData(i) or self._tab_bar.tabText(i)
            count = len(self._trays.get(name, []))
            label = f"{name} ({count})" if count else name
            if self._tab_bar.tabText(i) != label:
                self._tab_bar.setTabText(i, label)
            self._tab_bar.setTabToolTip(i, self._tab_stats_tooltip(name))

    def _tab_stats_tooltip(self, name: str) -> str:
        """Compute a breakdown for tray `name` (starred / tagged /
        untagged / assigned). Returns plain text so native Qt tooltip
        handles wrapping; no QSS needed."""
        ids = self._trays.get(name, [])
        n = len(ids)
        if not n:
            return f"{name}\n(empty)"
        if not self._project:
            return f"{name}: {n} items"
        starred = tagged = untagged = assigned = 0
        for aid in ids:
            asset = self._project.get_asset(aid)
            if asset is None:
                continue
            if asset.starred > 0:
                starred += 1
            if asset.tags:
                tagged += 1
            else:
                untagged += 1
            if asset.assignments:
                assigned += 1
        return (f"{name}: {n} item{'s' if n != 1 else ''}\n"
                f"Starred: {starred}\n"
                f"Tagged: {tagged}   Untagged: {untagged}\n"
                f"Platform-assigned: {assigned}\n"
                f"Right-click tab for actions")

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
            self._empty_area_menu(pos)
            return
        asset_id = item.data(Qt.ItemDataRole.UserRole)
        selected = self._get_selected_ids()
        if asset_id not in selected:
            selected = [asset_id]
        n_sel = len(selected)
        multi = n_sel > 1
        asset = self._project.get_asset(asset_id) if self._project else None

        menu = QMenu(self)

        # Bulk section (only when more than one is selected) — placed
        # first so the power-user path is one scroll-free click away.
        if multi:
            menu.addAction(f"Send {n_sel} to Studio",
                           lambda _c=False, ids=list(selected):
                               self._bulk_send_to_studio(ids))
            bulk_star = menu.addMenu(f"Bulk Star ({n_sel})")
            bulk_star.addAction("Unstar all",
                                 lambda _c=False, ids=list(selected):
                                     self._bulk_set_star(ids, 0))
            for s in range(1, 6):
                bulk_star.addAction(f"Star {s}",
                                     lambda _c=False, ids=list(selected), v=s:
                                         self._bulk_set_star(ids, v))
            # Bulk pin / unpin (toggle based on current state — if any
            # are un-pinned, Pin All pins them all)
            pinned_all = all(self._is_pinned(a) for a in selected)
            pin_verb = "Unpin" if pinned_all else "Pin"
            menu.addAction(f"{pin_verb} {n_sel} Selected",
                           lambda _c=False, ids=list(selected), p=not pinned_all:
                               self._bulk_set_pin(ids, p))
            menu.addAction(f"Export Selection as ZIP... ({n_sel})",
                           lambda _c=False, ids=list(selected):
                               self._export_selection_zip(ids))
            menu.addSeparator()

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
            menu.addAction("Open in Native Editor", lambda: os.startfile(asset.source_path))

        menu.addSeparator()

        if not multi:
            menu.addAction("Move to Top", lambda: self._move_to_top(asset_id))
            menu.addAction("Move to Bottom", lambda: self._move_to_bottom(asset_id))
            # Single-item pin toggle
            pin_label = "Unpin" if self._is_pinned(asset_id) else "Pin"
            menu.addAction(pin_label,
                           lambda _c=False, aid=asset_id: self._toggle_pin(aid))

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
            menu.addAction(f"Remove {n_sel} from Tray",
                            lambda _c=False, ids=list(selected):
                                self._remove_assets_bulk(ids))
        else:
            menu.addAction("Remove from Tray", lambda: self.remove_asset(asset_id))
        n = self._list.count()
        if n > 1:
            menu.addAction(f"Clear All ({n})", self.clear)
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _empty_area_menu(self, pos):
        """Right-click on the empty list area — tray-wide actions."""
        menu = self._build_tray_options_menu(include_view=False)
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _header_menu(self, anchor_widget, pos):
        """Right-click on the header title or count label — same options
        plus a View submenu."""
        menu = self._build_tray_options_menu(include_view=True)
        menu.exec(anchor_widget.mapToGlobal(pos))

    def _build_tray_options_menu(self, include_view: bool) -> QMenu:
        """Shared Tray Options menu body. include_view adds a View submenu
        at the top (used for the header right-click where the hamburger
        button is not in reach)."""
        menu = QMenu(self)
        n = self._list.count()
        if include_view:
            view_menu = menu.addMenu("View")
            labels = [("List (with names)", 0),
                       ("2 Columns", 1),
                       ("3 Columns", 2)]
            for label, mode in labels:
                act = view_menu.addAction(label)
                act.setCheckable(True)
                act.setChecked(self._view_mode == mode)
                act.triggered.connect(
                    lambda _c=False, m=mode: self._set_view_mode(m))
            menu.addSeparator()
        menu.addAction("Paste Path from Clipboard", self._paste_path_from_clipboard)
        menu.addAction("Import Folder...", self._import_folder)
        menu.addSeparator()
        if n:
            menu.addAction(f"Select All ({n})",
                           lambda: self._list.selectAll())
            sort_menu = menu.addMenu("Sort")
            sort_menu.addAction("By Name (A-Z)",
                                lambda: self._sort_items("name"))
            sort_menu.addAction("By Name (Z-A)",
                                lambda: self._sort_items("name_desc"))
            sort_menu.addAction("By Date Added (newest first)",
                                lambda: self._sort_items("recent"))
            sort_menu.addAction("By Stars (high to low)",
                                lambda: self._sort_items("stars"))
            menu.addAction(f"Export Tray as ZIP... ({n})",
                           self._export_tray_zip)
            menu.addSeparator()
            menu.addAction(f"Clear Tray ({n})", self.clear)
        else:
            act = menu.addAction("(empty - drop files or paste a path above)")
            act.setEnabled(False)
        return menu

    def _paste_path_from_clipboard(self):
        """Take whatever is on the clipboard, treat each line as a path,
        add any that resolve to a project asset."""
        if not self._project:
            return
        text = QApplication.clipboard().text()
        if not text:
            return
        candidates = [p.strip().strip('"').strip("'")
                      for p in text.splitlines() if p.strip()]
        if not candidates:
            return
        path_map = {a.source_path.replace("\\", "/"): a
                    for a in self._project.assets}
        added = 0
        for path in candidates:
            norm = path.replace("\\", "/")
            asset = path_map.get(norm)
            if asset and asset.id not in self._asset_ids:
                self.add_asset(asset.id, Path(path).name, path=path)
                added += 1
        if added:
            self.pixmaps_needed.emit(list(self._asset_ids))

    def _import_folder(self):
        """Pick a folder and add every project asset whose source lives
        under that path. Non-project files are ignored."""
        if not self._project:
            return
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(
            self, "Import folder into tray")
        if not folder:
            return
        folder_norm = folder.replace("\\", "/").rstrip("/") + "/"
        added = 0
        for asset in self._project.assets:
            src = asset.source_path.replace("\\", "/")
            if src.startswith(folder_norm) and asset.id not in self._asset_ids:
                self.add_asset(asset.id,
                               Path(asset.source_path).name,
                               path=asset.source_path)
                added += 1
        if added:
            self.pixmaps_needed.emit(list(self._asset_ids))

    def _sort_items(self, mode: str):
        """Sort the current tray's items in place. Rebuilds the list widget
        from the new _asset_ids order; does NOT touch other trays."""
        if not self._project:
            return
        def key_name(aid):
            a = self._project.get_asset(aid)
            return (Path(a.source_path).name.lower() if a else aid)
        def key_stars(aid):
            a = self._project.get_asset(aid)
            return -(a.starred if a else 0)
        def key_recent(aid):
            # Most recently added == end of current _asset_ids
            return -self._id_to_row.get(aid, 0)
        keyfn = {
            "name": key_name,
            "name_desc": lambda a: tuple(-ord(c) for c in key_name(a)),
            "stars": key_stars,
            "recent": key_recent,
        }.get(mode, key_name)
        # Pinned items always float to the top, keeping their relative
        # order within the pinned group stable under the chosen sort.
        pinned = self._pinned.get(self._current_tray, set())
        pinned_ids = [a for a in self._asset_ids if a in pinned]
        loose_ids = [a for a in self._asset_ids if a not in pinned]
        pinned_sorted = sorted(pinned_ids, key=keyfn)
        loose_sorted = sorted(loose_ids, key=keyfn)
        new_order = pinned_sorted + loose_sorted
        if new_order == self._asset_ids:
            return
        # Rebuild list widget in the new order without losing pixmaps
        ids_before = list(self._asset_ids)
        pixmaps_before = dict(self._pixmaps)
        paths_before = dict(self._paths)
        self._list.clear()
        self._asset_ids.clear()
        self._id_to_row.clear()
        for aid in new_order:
            asset = self._project.get_asset(aid)
            if asset:
                self.add_asset(aid, Path(asset.source_path).name,
                               pixmaps_before.get(aid),
                               paths_before.get(aid, asset.source_path))

    def _export_tray_zip(self):
        """Zip every file in the current tray to a user-chosen path."""
        if not self._asset_ids:
            return
        from PySide6.QtWidgets import QFileDialog
        import zipfile
        default_name = f"{self._current_tray.replace(' ', '_')}.zip"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Export tray as ZIP", default_name, "ZIP (*.zip)")
        if not out_path:
            return
        written = 0
        skipped = 0
        seen_names: dict[str, int] = {}
        try:
            with zipfile.ZipFile(out_path, "w",
                                 compression=zipfile.ZIP_DEFLATED) as zf:
                for aid in self._asset_ids:
                    src = self._paths.get(aid)
                    if not src or not Path(src).exists():
                        skipped += 1
                        continue
                    # De-dupe filenames across subfolders
                    arc = Path(src).name
                    seen_names[arc] = seen_names.get(arc, 0) + 1
                    if seen_names[arc] > 1:
                        stem = Path(src).stem
                        ext = Path(src).suffix
                        arc = f"{stem}_{seen_names[arc]}{ext}"
                    zf.write(src, arc)
                    written += 1
        except Exception as e:
            # Silent log-only; the user sees a button press and the file
            # either appears or doesn't.
            import logging
            logging.error(f"Tray export failed: {e}")
            return
        # Reveal in explorer if anything landed
        if written:
            import subprocess
            win_path = out_path.replace("/", "\\")
            subprocess.Popen(f'explorer /select,"{win_path}"')

    def _handle_tab_drop(self, asset_ids: list, target_name: str,
                          copy: bool) -> bool:
        """Called by TrayTabBar after a drop lands on a tab. Moves (default)
        or copies (Shift) the dragged asset_ids into target_name. Returns
        True if anything changed."""
        if target_name not in self._trays:
            return False
        if target_name == self._current_tray:
            # Dropping on self is a no-op — user probably meant reorder,
            # which happens via QListWidget internal DnD, not the tab bar.
            return False
        # Target is always an inactive tray (can't be current per the check
        # above), so we append directly to its list.
        dst = self._trays.setdefault(target_name, [])
        dst_set = set(dst)
        added = 0
        for aid in asset_ids:
            if aid not in dst_set:
                dst.append(aid)
                dst_set.add(aid)
                added += 1
        if not copy:
            for aid in asset_ids:
                self.remove_asset(aid)
        self._refresh_tab_counts()
        return added > 0 or not copy

    def _send_to_other_tray(self, asset_id: str, tray_name: str):
        """Move an asset from current tray to another tray."""
        if tray_name not in self._trays:
            return
        if asset_id not in self._trays[tray_name]:
            self._trays[tray_name].append(asset_id)
        self.remove_asset(asset_id)

    def _copy_filename(self, asset_id: str):
        path = self._paths.get(asset_id, "")
        if path:
            QApplication.clipboard().setText(Path(path).name)

    def _copy_stem(self, asset_id: str):
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
        path = self._paths.get(asset_id, "")
        if path:
            QApplication.clipboard().setText(path)

    def _cycle_view_mode(self):
        self._set_view_mode((self._view_mode + 1) % 3)

    def _set_view_mode(self, mode: int):
        """Jump directly to a view mode (0=list, 1=2col, 2=3col) without
        cycling. Header right-click uses this."""
        _f = ui_font_size()
        _pad = max(4, _f // 3)
        self._view_mode = mode % 3
        if self._view_mode == 0:
            # List mode — full filename + icon
            self._view_btn.setText("\u2630")
            self._list.setViewMode(QListWidget.ViewMode.ListMode)
            self._list.setIconSize(QSize(TRAY_ICON_SIZE, TRAY_ICON_SIZE))
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
        asset = self._project.get_asset(asset_id)
        if asset:
            toggle_tags([asset], tag_id)
            self.tags_modified.emit()
            self._list.viewport().update()

    def _remove_tray_tag(self, asset_id: str, tag_id: str):
        """Remove a specific tag from an asset."""
        if not self._project:
            return
        asset = self._project.get_asset(asset_id)
        if asset and tag_id in asset.tags:
            asset.tags.remove(tag_id)
            self.tags_modified.emit()
            self._list.viewport().update()

    def _set_star(self, asset_id: str, value: int):
        """Set star rating for an asset."""
        if not self._project:
            return
        asset = self._project.get_asset(asset_id)
        if asset:
            asset.starred = value
            self.star_modified.emit()
            self._list.viewport().update()

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
        # Pick a name that doesn't collide even after reorder/rename
        n = self._tab_bar.count() + 1
        name = f"Tray {n}"
        while name in self._trays:
            n += 1
            name = f"Tray {n}"
        self._trays[name] = []
        idx = self._tab_bar.addTab(name)
        self._tab_bar.setTabData(idx, name)
        self._tab_bar.setCurrentIndex(idx)
        self._refresh_tab_counts()

    def _on_tab_changed(self, index: int):
        if index < 0:
            return
        # Save current tray contents
        self._trays[self._current_tray] = list(self._asset_ids)
        # Switch to new tray (use tabData so the count suffix doesn't get
        # treated as part of the tray name).
        new_name = self._tab_bar.tabData(index) or self._tab_bar.tabText(index)
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
        self._refresh_tab_counts()

    def _tab_context_menu(self, pos):
        index = self._tab_bar.tabAt(pos)
        if index < 0:
            return
        name = self._tab_bar.tabData(index) or self._tab_bar.tabText(index)
        count = len(self._trays.get(name, []))
        settings = QSettings("DoxyEdit", "DoxyEdit")
        is_default = settings.value("tray_default_name", "") == name

        menu = QMenu(self)
        menu.addAction("Rename", lambda: self._rename_tray(index))
        menu.addAction("Duplicate", lambda: self._duplicate_tray(index))
        if count:
            menu.addAction(f"Clear ({count})",
                           lambda: self._clear_tray_by_index(index))
            menu.addAction(f"Export as ZIP... ({count})",
                           lambda: self._export_tray_zip_by_name(name))
        # Merge into another tray
        other = [self._tab_bar.tabData(i) or self._tab_bar.tabText(i)
                  for i in range(self._tab_bar.count()) if i != index]
        if other and count:
            merge_menu = menu.addMenu("Merge Into")
            for other_name in other:
                merge_menu.addAction(
                    other_name,
                    lambda _c=False, src=name, dst=other_name:
                        self._merge_tray(src, dst))
        menu.addSeparator()
        # Set-as-default toggle
        default_act = menu.addAction("Default Tray on Load")
        default_act.setCheckable(True)
        default_act.setChecked(is_default)
        default_act.triggered.connect(
            lambda _c=False, n=name, cur=is_default:
                self._toggle_default_tray(n, not cur))
        if self._tab_bar.count() > 1:
            menu.addSeparator()
            menu.addAction("Close", lambda: self._close_tray(index))
        menu.exec(self._tab_bar.mapToGlobal(pos))

    def _duplicate_tray(self, index: int):
        """Clone the tray at index with " copy" appended."""
        src = self._tab_bar.tabData(index) or self._tab_bar.tabText(index)
        base = f"{src} copy"
        name = base
        n = 2
        while name in self._trays:
            name = f"{base} {n}"
            n += 1
        # Copy the source items — if src is active, use live _asset_ids
        items = (list(self._asset_ids) if src == self._current_tray
                 else list(self._trays.get(src, [])))
        self._trays[name] = items
        new_idx = self._tab_bar.addTab(name)
        self._tab_bar.setTabData(new_idx, name)
        self._refresh_tab_counts()

    def _clear_tray_by_index(self, index: int):
        """Empty a specific tray. If it's the active one, also clears
        the live list widget."""
        name = self._tab_bar.tabData(index) or self._tab_bar.tabText(index)
        if name == self._current_tray:
            self.clear()
        else:
            self._trays[name] = []
        self._refresh_tab_counts()

    def _export_tray_zip_by_name(self, name: str):
        """Export a tray that may not be active. Resolves asset paths
        from the project instead of self._paths."""
        if name not in self._trays or not self._project:
            return
        ids = self._trays[name]
        if not ids:
            return
        from PySide6.QtWidgets import QFileDialog
        import zipfile
        default_name = f"{name.replace(' ', '_')}.zip"
        out_path, _ = QFileDialog.getSaveFileName(
            self, f"Export '{name}' as ZIP", default_name, "ZIP (*.zip)")
        if not out_path:
            return
        written = 0
        seen_names: dict[str, int] = {}
        try:
            with zipfile.ZipFile(out_path, "w",
                                 compression=zipfile.ZIP_DEFLATED) as zf:
                for aid in ids:
                    asset = self._project.get_asset(aid)
                    if not asset or not Path(asset.source_path).exists():
                        continue
                    src = asset.source_path
                    arc = Path(src).name
                    seen_names[arc] = seen_names.get(arc, 0) + 1
                    if seen_names[arc] > 1:
                        stem = Path(src).stem
                        ext = Path(src).suffix
                        arc = f"{stem}_{seen_names[arc]}{ext}"
                    zf.write(src, arc)
                    written += 1
        except Exception as e:
            import logging
            logging.error(f"Tray export failed: {e}")
            return
        if written:
            import subprocess
            win_path = out_path.replace("/", "\\")
            subprocess.Popen(f'explorer /select,"{win_path}"')

    def _merge_tray(self, src: str, dst: str):
        """Move all items from src into dst (preserving order, de-duped),
        then close src. If src is active, switch to dst first."""
        if src == dst or src not in self._trays or dst not in self._trays:
            return
        src_items = (list(self._asset_ids) if src == self._current_tray
                     else list(self._trays[src]))
        dst_set = set(self._trays[dst])
        for aid in src_items:
            if aid not in dst_set:
                self._trays[dst].append(aid)
                dst_set.add(aid)
        # If src was active, switch to dst before removing its tab
        if src == self._current_tray:
            # Find dst index
            for i in range(self._tab_bar.count()):
                if (self._tab_bar.tabData(i) or
                        self._tab_bar.tabText(i)) == dst:
                    self._tab_bar.setCurrentIndex(i)
                    break
        # Remove src tab
        for i in range(self._tab_bar.count()):
            if (self._tab_bar.tabData(i) or
                    self._tab_bar.tabText(i)) == src:
                self._tab_bar.removeTab(i)
                break
        self._trays.pop(src, None)
        self._refresh_tab_counts()

    def _toggle_default_tray(self, name: str, make_default: bool):
        """QSettings-backed default tray. load_state activates this one
        if it exists; otherwise falls back to the first tray in the file."""
        settings = QSettings("DoxyEdit", "DoxyEdit")
        if make_default:
            settings.setValue("tray_default_name", name)
        else:
            settings.remove("tray_default_name")
        settings.sync()

    def _rename_tray(self, index: int):
        old_name = self._tab_bar.tabData(index) or self._tab_bar.tabText(index)
        new_name, ok = QInputDialog.getText(self, "Rename Tray", "Name:", text=old_name)
        if ok and new_name.strip() and new_name != old_name:
            new_name = new_name.strip()
            if new_name in self._trays and new_name != old_name:
                # Collision — bail silently rather than clobbering
                return
            self._trays[new_name] = self._trays.pop(old_name, [])
            if self._current_tray == old_name:
                self._current_tray = new_name
            self._tab_bar.setTabData(index, new_name)
            self._refresh_tab_counts()

    def _close_tray(self, index: int):
        name = self._tab_bar.tabData(index) or self._tab_bar.tabText(index)
        self._trays.pop(name, None)
        self._tab_bar.removeTab(index)
        # If we closed the active tray, switch to first remaining
        if name == self._current_tray:
            self._current_tray = (self._tab_bar.tabData(0)
                                   or self._tab_bar.tabText(0))
        self._refresh_tab_counts()

    # --- Save/Load ---

    def save_state(self):
        """Return tray data. Dict of tray_name → asset_ids for named trays.

        Iterates the QTabBar in display order (using tabData for clean
        names, since tabText now carries a '(N)' count suffix) so user
        reorder and rename round-trip correctly. Python dicts preserve
        insertion order.
        """
        # Save current tray before serializing
        self._trays[self._current_tray] = list(self._asset_ids)
        if len(self._trays) == 1 and "Tray 1" in self._trays:
            # Single default tray — save as plain list for backward compat
            return self._trays["Tray 1"]
        ordered = {}
        for i in range(self._tab_bar.count()):
            name = self._tab_bar.tabData(i) or self._tab_bar.tabText(i)
            ordered[name] = self._trays.get(name, [])
        # Include any trays that somehow aren't on the tab bar (shouldn't happen)
        for name, items in self._trays.items():
            if name not in ordered:
                ordered[name] = items
        return ordered

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
        active_idx = 0
        default_name = QSettings(
            "DoxyEdit", "DoxyEdit").value("tray_default_name", "")
        for i, name in enumerate(tray_dict):
            idx = self._tab_bar.addTab(name)
            self._tab_bar.setTabData(idx, name)
            if default_name and name == default_name:
                active_idx = i
        first_name = (default_name if default_name in tray_dict
                      else next(iter(tray_dict), "Tray 1"))
        self._current_tray = first_name
        self._tab_bar.setCurrentIndex(active_idx)
        self._tab_bar.blockSignals(False)
        for aid in tray_dict.get(first_name, []):
            asset = project.get_asset(aid)
            if asset:
                self.add_asset(aid, Path(asset.source_path).name, path=asset.source_path)
        self._refresh_tab_counts()

    def attach_notes_widget(self, notes_widget: QWidget,
                             sizes: tuple[int, int] = (400, 100)):
        """Install a notes widget below the list inside a vertical
        splitter. Replaces the layout-mutation hack that previously
        lived in window.py.

        Safe to call once. Idempotent for no-op re-adds of the same
        widget (subsequent calls replace the widget)."""
        if notes_widget is None:
            return
        # Already attached? Replace and rebalance sizes.
        if getattr(self, "_notes_widget", None) is not None:
            self._notes_widget.setParent(None)
            self._notes_widget = None
        tray_layout = self._content.layout()
        # Remove the list from the plain layout; put list + notes in a
        # vertical splitter, then put the splitter in the tray layout.
        if not hasattr(self, "_list_notes_split"):
            tray_layout.removeWidget(self._list)
            split = QSplitter(Qt.Orientation.Vertical)
            split.addWidget(self._list)
            split.setStretchFactor(0, 3)
            split.setStretchFactor(1, 0)
            tray_layout.addWidget(split)
            self._list_notes_split = split
        self._list_notes_split.addWidget(notes_widget)
        self._list_notes_split.setSizes(list(sizes))
        self._notes_widget = notes_widget

    def update_pixmap(self, asset_id: str, pixmap: QPixmap):
        """Update thumbnail for an item already in the tray."""
        row = self._id_to_row.get(asset_id)
        if row is None:
            return
        item = self._list.item(row)
        if item:
            scaled = pixmap.scaled(TRAY_ICON_SIZE, TRAY_ICON_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            item.setIcon(QIcon(scaled))
            self._pixmaps[asset_id] = pixmap
            self._mark_pulse(asset_id)

    def _mark_pulse(self, asset_id: str, duration: float = 0.4):
        """Flag asset_id for a brief accent-ring pulse in the delegate.
        Starts the shared tick timer on first pulse."""
        self._pulse_until[asset_id] = time.monotonic() + duration
        if not self._pulse_timer.isActive():
            self._pulse_timer.start()

    def _on_pulse_tick(self):
        now = time.monotonic()
        expired = [aid for aid, end in self._pulse_until.items() if end <= now]
        for aid in expired:
            self._pulse_until.pop(aid, None)
        if not self._pulse_until:
            self._pulse_timer.stop()
        self._list.viewport().update()
