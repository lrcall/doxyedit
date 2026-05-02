"""Widgets and delegate used by the Work Tray.

Extracted from tray.py when that file crossed the 1500-line threshold
set by the tray-improvement plan. Contains:

  DragOutListWidget   QListWidget subclass with file-URL drag-out,
                        drop-onto-tray, and middle-click preview
  TrayItemDelegate    paints star / tag dots / platform badge /
                        pin indicator / T18 refresh pulse
  TrayTabBar          QTabBar subclass that accepts drops of tray
                        items (with Shift = copy)

No behavior change from the pre-split version. WorkTray is still
in tray.py; these classes hold a weak reference back to the tray
via constructor injection so paint / drop callbacks can read
live state (_project, _is_pinned, _pulse_until, _handle_tab_drop).
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal, QMimeData, QRect, QUrl
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QDrag, QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QListWidget, QStyledItemDelegate, QTabBar,
)

from doxyedit.themes import THEMES, DEFAULT_THEME
from doxyedit.preview import HoverPreview


# --- Shared constants ---------------------------------------------------

NAME_ROLE = Qt.ItemDataRole.UserRole + 1  # stores display name for view mode switching
PATH_ROLE = Qt.ItemDataRole.UserRole + 2  # stores source_path for drag-out
TRAY_ICON_SIZE = 80
MIN_HANDLE_WIDTH = 12
# Custom mime so tab-bar drops can recover asset IDs directly instead
# of having to reverse-map file URLs back to project asset IDs.
TRAY_IDS_MIME = "application/x-doxyedit-tray-ids"


# --- List widget --------------------------------------------------------

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

    def wheelEvent(self, event):
        """Ctrl+Wheel zooms the thumbnail size on the parent tray.
        Plain wheel scrolls as usual."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Find the parent tray and delegate the zoom step
            tray = self.parent()
            while tray is not None and not hasattr(tray, "_icon_size"):
                tray = tray.parent()
            if tray is not None:
                delta = event.angleDelta().y()
                step = 8 if delta > 0 else -8
                new_size = max(40, min(200, tray._icon_size + step))
                if hasattr(tray, "_zoom_slider"):
                    tray._zoom_slider.setValue(new_size)
                event.accept()
                return
        super().wheelEvent(event)

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


# --- Delegate -----------------------------------------------------------

class TrayItemDelegate(QStyledItemDelegate):
    """Paint star, tag dots, platform-assignment badge, pin indicator, and
    the T18 refresh pulse on top of the standard icon+text cell.

    Reads live Asset state from the tray's project reference so toggles
    apply without a rebuild. The tray passes itself in; the delegate
    duck-types off _project / _is_pinned / _pulse_until to avoid a
    circular import."""

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
                # Fade ring from full opacity to gone over the
                # remaining 0.4s; floor at 40 so it never disappears
                # before the timer is up.
                fade = min(1.0, remaining / 0.4)
                alpha = max(40, int(theme.tray_badge_alpha * fade))
                ring = QColor(theme.accent_bright or theme.accent)
                ring.setAlpha(alpha)
                painter.setPen(QPen(ring, theme.tray_pulse_pen_width))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                inset = theme.tray_pulse_inset
                radius = theme.tray_badge_corner_radius
                painter.drawRoundedRect(
                    rect.adjusted(inset, inset, -inset, -inset),
                    radius, radius)

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
            badge_bg.setAlpha(theme.tray_badge_alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(badge_bg))
            radius = theme.tray_badge_corner_radius
            painter.drawRoundedRect(br_x, br_y, bw, bh, radius, radius)
            painter.setPen(QPen(QColor(theme.text_on_accent)))
            painter.drawText(
                QRect(br_x, br_y, bw, bh),
                Qt.AlignmentFlag.AlignCenter, text)

        painter.restore()


# --- Tab bar ------------------------------------------------------------

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
