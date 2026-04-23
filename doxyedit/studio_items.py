"""Studio graphics items, undo commands, and context-menu helpers.

Everything below StudioEditor that the main editor file depends on:
the overlay / censor / handle QGraphicsItem subclasses, the StudioTool
enum, layout / tag-color constants, shared helpers, and the undo command
subclasses. Kept as a separate module because studio.py exceeded 15k lines.

Layered QGraphicsScene:
  Z   0       Base image pixmap (not editable)
  Z 100-199   Censor rects (persist to asset.censors)
  Z 200-299   Overlay items — watermark/text/logo (persist to asset.overlays)
  Z 300+      Annotations — text/line/box (ephemeral, lost on asset change)
"""
from enum import Enum, auto
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsScene, QGraphicsView, QGraphicsRectItem, QGraphicsPixmapItem,
    QGraphicsTextItem, QGraphicsLineItem, QGraphicsItem,
    QComboBox, QFileDialog, QSlider,
    QFontComboBox, QSpinBox, QColorDialog, QInputDialog, QMenu,
    QListWidget, QListWidgetItem, QSplitter, QScrollArea, QCheckBox,
    QGridLayout, QApplication, QFormLayout, QLineEdit, QDialog,
    QDialogButtonBox, QTabWidget, QTextBrowser, QMessageBox,
    QWidgetAction, QDoubleSpinBox, QPlainTextEdit,
    QGraphicsDropShadowEffect, QGraphicsPathItem, QProgressDialog,
)
from PySide6.QtCore import (
    Qt, QRectF, QPointF, QLineF, Signal, QSettings, QSize,
    QEvent, QMimeData, QObject, QRunnable, QThreadPool,
    QMetaObject, Q_ARG, Slot,
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QBrush, QPen, QFont, QWheelEvent,
    QKeyEvent, QTransform, QUndoCommand, QUndoStack, QIcon,
    QPolygonF, QPainterPath, QImage, QShortcut, QKeySequence,
    QTextCursor, QLinearGradient, QRadialGradient, QTextOption,
    QTextBlockFormat, QPalette, QAbstractTextDocumentLayout,
)
import copy
import json
import math
import re
import uuid
from PIL import Image

from doxyedit.models import Asset, Project, CensorRegion, CanvasOverlay, CropRegion, PLATFORMS
from doxyedit.exporter import apply_censors, apply_overlays
from doxyedit.imaging import pil_to_qimage, qimage_to_pil
from doxyedit.preview import NoteRectItem, ResizableCropItem
from doxyedit.themes import THEMES, DEFAULT_THEME


# ── Layout constants ──────────────────────────────────────────────
STUDIO_GRID_SPACING = 50          # snap grid spacing in pixels
STUDIO_GRID_PEN_ALPHA = 40        # grid line opacity
STUDIO_GRID_PEN_WIDTH = 0.5       # grid line thickness
STUDIO_RESIZE_HANDLE_SIZE = 6     # resize handle square size
STUDIO_ZOOM_BTN_WIDTH_RATIO = 3.0  # zoom button width × font_size
STUDIO_ZOOM_LABEL_WIDTH_RATIO = 3.3  # zoom % label width × font_size
STUDIO_LAYER_PANEL_WIDTH = 200    # layer panel max width


# ── Layer tag colors ──────────────────────────────────────────────
# Finder/macOS-style semantic labels for overlays. Hex literals are
# intentional: users expect "Red" to render red regardless of theme,
# so these bypass the theme token system (same spirit as crop handle
# and censor accent exceptions documented in CLAUDE.md).
TAG_COLORS = [
    # (id,      label,    hex,        sort_order)
    ("red",    "Red",    "#d93838", 0),
    ("orange", "Orange", "#d98a38", 1),
    ("yellow", "Yellow", "#d9c638", 2),
    ("green",  "Green",  "#4cb85b", 3),
    ("blue",   "Blue",   "#4c7fe0", 4),
    ("purple", "Purple", "#9a56d9", 5),
    ("pink",   "Pink",   "#e063b5", 6),
    ("gray",   "Gray",   "#888888", 7),
]
TAG_COLOR_HEX = {tid: h for tid, _, h, _ in TAG_COLORS}
TAG_COLOR_ORDER = {tid: o for tid, _, _, o in TAG_COLORS}


# ---------------------------------------------------------------------------
# Context menu theming helper
# ---------------------------------------------------------------------------

def _attach_ctx_menu(label, populate_fn):
    """Wire a themed right-click context menu to a QLabel (status-bar idiom).

    populate_fn(menu) adds QActions and wires each action's .triggered
    signal. This helper handles the boilerplate: setContextMenuPolicy,
    QMenu construction, mapToGlobal, and exec.
    """
    label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    def _ctx(pos):
        m = _themed_menu(label)
        populate_fn(m)
        m.exec(label.mapToGlobal(pos))
    label.customContextMenuRequested.connect(_ctx)


def _themed_menu(parent=None) -> QMenu:
    """Create a QMenu styled from the current theme (same pattern as window.py)."""
    t = THEMES[DEFAULT_THEME]
    menu = QMenu(parent)
    rad = max(3, t.font_size // 4)
    pad = max(4, t.font_size // 3)
    pad_lg = max(6, t.font_size // 2)
    menu.setStyleSheet(f"""
        QMenu {{
            background: {t.bg_raised}; color: {t.text_primary};
            border: 1px solid {t.border}; border-radius: {rad}px;
            padding: {pad}px 0;
        }}
        QMenu::item {{ padding: {pad}px {pad_lg * 3}px; color: {t.text_primary}; }}
        QMenu::item:selected {{ background: {t.accent_dim}; color: {t.text_on_accent}; }}
        QMenu::item:disabled {{ color: {t.text_muted}; }}
        QMenu::separator {{ background: {t.border}; height: 1px; margin: {pad}px {pad_lg}px; }}
        QMenu::indicator {{ width: {pad_lg * 2}px; height: {pad_lg * 2}px; margin-left: {pad}px; }}
        QMenu::indicator:checked {{ background: {t.accent}; border: 1px solid {t.accent_bright}; border-radius: {rad}px; }}
        QMenu::indicator:unchecked {{ background: {t.bg_input}; border: 1px solid {t.border}; border-radius: {rad}px; }}
    """)
    return menu


def _add_platform_submenu(menu: QMenu, current_platforms: list[str], editor) -> QMenu:
    """Add a 'Platforms...' submenu with checkable entries. Returns the submenu."""
    if not editor or not editor._project:
        return menu
    sub = _themed_menu()
    sub.setTitle("Platforms...")
    menu.addMenu(sub)
    all_act = sub.addAction("All Platforms")
    all_act.setCheckable(True)
    all_act.setChecked(not current_platforms)
    sub.addSeparator()
    plat_actions = {}
    for pid in editor._project.platforms:
        p = PLATFORMS.get(pid)
        label = p.name if p else pid
        act = sub.addAction(label)
        act.setCheckable(True)
        act.setChecked(pid in current_platforms)
        plat_actions[act] = pid
    return sub, all_act, plat_actions


def _resolve_platform_menu(chosen, all_act, plat_actions, current_platforms: list[str]) -> list[str]:
    """Resolve platform submenu selection into updated platforms list."""
    if chosen is all_act:
        return []
    if chosen in plat_actions:
        pid = plat_actions[chosen]
        new = list(current_platforms)
        if pid in new:
            new.remove(pid)
        else:
            new.append(pid)
        return new
    return current_platforms


# ---------------------------------------------------------------------------
# Tool state machine
# ---------------------------------------------------------------------------

class StudioTool(Enum):
    SELECT = auto()
    CENSOR = auto()
    WATERMARK = auto()
    TEXT_OVERLAY = auto()
    CROP = auto()
    NOTE = auto()
    EYEDROPPER = auto()
    ARROW = auto()
    SHAPE_RECT = auto()
    SHAPE_ELLIPSE = auto()
    ANNOTATE_TEXT = auto()
    ANNOTATE_LINE = auto()
    ANNOTATE_BOX = auto()


# ---------------------------------------------------------------------------
# Graphics items
# ---------------------------------------------------------------------------

# E1 from canvas-architecture-deep-dive.md: _ResizeHandle and
# _RotateHandle are GONE. Handles are now drawn inline in
# CensorRectItem.paint when isSelected(), hit-tested via
# _handle_at_pos, and dragged through CensorRectItem's own mouse
# events. This drops 9 scene items per selected censor and removes
# the prepareGeometryChange / position-update cascade to each child
# on every parent move.


class CensorRectItem(QGraphicsRectItem):
    """Draggable censor rectangle — overlay exception: hardcoded colors OK."""

    # Handle geometry constants (local coords, rendered in paint)
    _HANDLE_HALF = 4      # half-side of resize-handle square (screen px)
    _ROTATE_RADIUS = 5    # radius of rotate circle (screen px)
    _ROTATE_OFFSET = 20   # scene-px above top edge
    _HIT_PAD = 3          # extra px around handle for easier click hits

    def __init__(self, rect: QRectF, style: str = "black", platforms: list[str] | None = None):
        super().__init__(rect)
        self.style = style
        self.platforms: list[str] = platforms or []
        self._editor = None  # set by StudioEditor after creation
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        # Rotate around rect center from the start; resize handlers keep
        # this invariant by re-centering after every setRect.
        self.setTransformOriginPoint(rect.center())
        self._apply_style()
        # Active handle drag state (None = dragging body / not dragging)
        self._active_handle: str | None = None  # "tl","t",...,"rotate"

    def _apply_style(self):
        _dt = THEMES[DEFAULT_THEME]
        pen_w = _dt.studio_censor_pen_width
        if self.style == "black":
            fill = QColor(_dt.studio_censor_blackout_fill)
            fill.setAlpha(_dt.studio_censor_blackout_fill_alpha)
            self.setBrush(QBrush(fill))
            self.setPen(QPen(QColor(_dt.studio_censor_blackout_pen), pen_w,
                             Qt.PenStyle.DashLine))
        elif self.style == "blur":
            fill = QColor(_dt.studio_censor_blur_fill)
            fill.setAlpha(_dt.studio_censor_blur_fill_alpha)
            self.setBrush(QBrush(fill))
            self.setPen(QPen(QColor(_dt.studio_censor_blur_pen), pen_w,
                             Qt.PenStyle.DashLine))
        elif self.style == "pixelate":
            fill = QColor(_dt.studio_censor_pixelate_fill)
            fill.setAlpha(_dt.studio_censor_pixelate_fill_alpha)
            self.setBrush(QBrush(fill))
            self.setPen(QPen(QColor(_dt.studio_censor_pixelate_pen), pen_w,
                             Qt.PenStyle.DashLine))

    def _handle_points_local(self) -> dict:
        """Return {handle_key: QPointF} for every handle in LOCAL coords.
        Used by both paint (to draw) and _handle_at_pos (to hit-test)."""
        r = self.rect()
        return {
            "tl": QPointF(r.left(), r.top()),
            "t":  QPointF(r.center().x(), r.top()),
            "tr": QPointF(r.right(), r.top()),
            "l":  QPointF(r.left(), r.center().y()),
            "r":  QPointF(r.right(), r.center().y()),
            "bl": QPointF(r.left(), r.bottom()),
            "b":  QPointF(r.center().x(), r.bottom()),
            "br": QPointF(r.right(), r.bottom()),
            "rotate": QPointF(r.center().x(),
                               r.top() - self._ROTATE_OFFSET),
        }

    def _handle_at_pos(self, local_pos: QPointF) -> str | None:
        """Hit-test against handles in local coords. Returns the handle
        key if hit, otherwise None."""
        pts = self._handle_points_local()
        hit_r = self._HANDLE_HALF + self._HIT_PAD
        for key, pt in pts.items():
            rr = self._ROTATE_RADIUS + self._HIT_PAD if key == "rotate" else hit_r
            if (abs(local_pos.x() - pt.x()) <= rr
                    and abs(local_pos.y() - pt.y()) <= rr):
                return key
        return None

    def _on_rotate_handle_moved(self, scene_pos):
        """Compute angle from rect center to the handle position and apply setRotation."""
        center_scene = self.mapToScene(self.rect().center())
        dx = scene_pos.x() - center_scene.x()
        dy = scene_pos.y() - center_scene.y()
        # Handle is at 12 o'clock (dy < 0) at 0°. Angle grows clockwise.
        angle = math.degrees(math.atan2(dy, dx)) + 90.0
        # Shift snaps to 15-degree increments (Photoshop convention)
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            angle = round(angle / 15.0) * 15.0
        self.setTransformOriginPoint(self.rect().center())
        self.setRotation(angle)
        # Persist to CensorRegion (add rotation field if present; fall back silently)
        cr = getattr(self, "_censor_region", None)
        if cr is not None and hasattr(cr, "rotation"):
            cr.rotation = float(angle)

    def _opposite_anchor_local(self, position: str, r: QRectF) -> QPointF:
        """Local-frame point on the rect that should stay fixed when
        dragging the given handle. For 'tl' → bottom-right corner, for
        't' → bottom-edge midpoint, etc."""
        if position == "tl": return QPointF(r.right(), r.bottom())
        if position == "tr": return QPointF(r.left(), r.bottom())
        if position == "bl": return QPointF(r.right(), r.top())
        if position == "br": return QPointF(r.left(), r.top())
        if position == "t":  return QPointF(r.center().x(), r.bottom())
        if position == "b":  return QPointF(r.center().x(), r.top())
        if position == "l":  return QPointF(r.right(), r.center().y())
        if position == "r":  return QPointF(r.left(), r.center().y())
        return r.center()

    def _on_handle_moved(self, position: str, scene_pos):
        # When the censor is rotated, changing its rect shifts both the
        # rotation pivot (transformOriginPoint == rect center) and the
        # visual position of every corner. Lock the opposite anchor in
        # scene space across the edit so the user's drag feels anchored.
        old_rect = self.rect()
        anchor_scene = self.mapToScene(
            self._opposite_anchor_local(position, old_rect))

        local = self.mapFromScene(scene_pos)
        r = QRectF(old_rect)
        if "l" in position:
            r.setLeft(min(local.x(), r.right() - 10))
        if "r" in position:
            r.setRight(max(local.x(), r.left() + 10))
        if "t" in position:
            r.setTop(min(local.y(), r.bottom() - 10))
        if "b" in position:
            r.setBottom(max(local.y(), r.top() + 10))
        self.setRect(r)
        # Keep rotation pivot centered on the (new) rect.
        self.setTransformOriginPoint(r.center())
        # Shift position so the opposite anchor stays put in scene space.
        new_anchor_scene = self.mapToScene(
            self._opposite_anchor_local(position, r))
        self.setPos(self.pos() + (anchor_scene - new_anchor_scene))
        # No _update_handle_positions — handles are drawn inline from
        # the current rect, so a simple update() schedules a repaint.
        self.update()
        if self._editor:
            self._editor._sync_censors_to_asset()

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.GraphicsItemChange.ItemSelectedHasChanged:
            # Tell Qt the paint region is about to change (handles
            # appear when selected, disappear when deselected) and
            # schedule a repaint.
            self.prepareGeometryChange()
            self.update()
        return super().itemChange(change, value)

    def boundingRect(self) -> QRectF:
        """Expand the default rect bounds to include the rotate handle
        when selected, so Qt allocates paint space for it."""
        r = super().boundingRect()
        if self.isSelected():
            # Include rotate handle offset above top edge + half radius
            # + hit padding so nothing gets clipped during hover.
            pad = self._HANDLE_HALF + self._HIT_PAD
            r = r.adjusted(
                -pad, -(self._ROTATE_OFFSET + self._ROTATE_RADIUS + pad),
                pad, pad)
        return r

    def paint(self, painter, option, widget=None):
        """Paint the censor rect (via super) then inline handles."""
        # Suppress Qt's default selection rectangle — we draw our own
        # selection decor to match QGraphicsShapeItem's look.
        from PySide6.QtWidgets import QStyle
        opt = option
        try:
            opt.state &= ~QStyle.StateFlag.State_Selected
        except Exception:
            pass
        super().paint(painter, opt, widget)
        if not self.isSelected():
            return
        _dt = THEMES[DEFAULT_THEME]
        # 8-point resize handles — square with dark border.
        fill = QBrush(QColor(_dt.studio_resize_handle_fill))
        border = QPen(QColor(_dt.studio_overlay_handle_border),
                      _dt.studio_overlay_handle_pen_width)
        painter.setBrush(fill)
        painter.setPen(border)
        pts = self._handle_points_local()
        hh = self._HANDLE_HALF
        for key, pt in pts.items():
            if key == "rotate":
                continue
            painter.drawRect(QRectF(
                pt.x() - hh, pt.y() - hh, hh * 2, hh * 2))
        # Connector line from top-center to the rotate handle.
        rot_pt = pts["rotate"]
        r = self.rect()
        top_mid = QPointF(r.center().x(), r.top())
        painter.setPen(QPen(
            QColor(_dt.studio_rotate_connector or
                   _dt.studio_overlay_handle_border),
            _dt.studio_overlay_handle_pen_width,
            Qt.PenStyle.DashLine))
        painter.drawLine(top_mid, rot_pt)
        # Rotate handle — green filled circle.
        painter.setBrush(QBrush(QColor(_dt.studio_rotate_handle_fill)))
        painter.setPen(border)
        painter.drawEllipse(rot_pt, self._ROTATE_RADIUS, self._ROTATE_RADIUS)

    def mousePressEvent(self, event):
        """Detect handle click when selected; fall back to body drag."""
        if self.isSelected() and event.button() == Qt.MouseButton.LeftButton:
            key = self._handle_at_pos(event.pos())
            if key is not None:
                self._active_handle = key
                # Disable ItemIsMovable so Qt doesn't translate the
                # item while we're sizing/rotating it.
                self.setFlag(
                    QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable,
                    False)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._active_handle is not None:
            if self._active_handle == "rotate":
                self._on_rotate_handle_moved(event.scenePos())
            else:
                self._on_handle_moved(self._active_handle,
                                       event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._active_handle is not None:
            self._active_handle = None
            self.setFlag(
                QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event):
        """Swap cursor when hovering a handle so the affordance matches
        the old child-handle behavior."""
        if self.isSelected():
            key = self._handle_at_pos(event.pos())
            if key == "rotate":
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif key in ("tl", "br"):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif key in ("tr", "bl"):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif key in ("t", "b"):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif key in ("l", "r"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def contextMenuEvent(self, event):
        _parent = self._editor._view if self._editor else None
        menu = _themed_menu(_parent)
        styles = {"black": "Change to Black", "blur": "Change to Blur",
                   "pixelate": "Change to Pixelate"}
        for key, label in styles.items():
            if key != self.style:
                act = menu.addAction(label)
                act.setData(key)
        blur_radius_act = None
        pixelate_ratio_act = None
        if self.style == "blur":
            blur_radius_act = menu.addAction("Blur Radius...")
        elif self.style == "pixelate":
            pixelate_ratio_act = menu.addAction("Pixelate Ratio...")
        menu.addSeparator()
        dup_act = menu.addAction("Duplicate  (Ctrl+D)")
        save_default_act = menu.addAction("Save as Default Censor Style")
        menu.addSeparator()
        front_act = menu.addAction("Bring to Front  (Ctrl+Shift+])")
        fwd_act = menu.addAction("Bring Forward  (Ctrl+])")
        bwd_act = menu.addAction("Send Backward  (Ctrl+[)")
        back_act = menu.addAction("Send to Back  (Ctrl+Shift+[)")
        menu.addSeparator()
        plat_sub = all_act = plat_actions = None
        if self._editor and self._editor._project:
            plat_sub, all_act, plat_actions = _add_platform_submenu(menu, self.platforms, self._editor)
            menu.addSeparator()
        delete_act = menu.addAction("Delete")

        chosen = menu.exec(event.screenPos())
        if not chosen:
            return
        if chosen is delete_act:
            if self._editor:
                self._editor._remove_censor_item(self)
        elif chosen is blur_radius_act and self._editor:
            cr = getattr(self, "_censor_region", None)
            cur = cr.blur_radius if cr else 20
            value, ok = QInputDialog.getInt(
                self._editor, "Blur radius",
                "Gaussian blur radius (px):",
                value=cur, minValue=1, maxValue=200)
            if ok and cr:
                cr.blur_radius = value
                self._editor.info_label.setText(
                    f"Blur radius set to {value}px")
        elif chosen is pixelate_ratio_act and self._editor:
            cr = getattr(self, "_censor_region", None)
            cur = cr.pixelate_ratio if cr else 10
            value, ok = QInputDialog.getInt(
                self._editor, "Pixelate ratio",
                "Downscale factor (larger = blockier):",
                value=cur, minValue=2, maxValue=100)
            if ok and cr:
                cr.pixelate_ratio = value
                self._editor.info_label.setText(
                    f"Pixelate ratio set to {value}")
        elif chosen is dup_act and self._editor:
            # Duplicate: clone region with 20px offset; reuse existing append + scene add pattern
            cr_src = getattr(self, "_censor_region", None)
            if cr_src is not None:
                new_cr = CensorRegion(
                    x=cr_src.x + 20, y=cr_src.y + 20,
                    w=cr_src.w, h=cr_src.h,
                    style=cr_src.style,
                    blur_radius=cr_src.blur_radius,
                    pixelate_ratio=cr_src.pixelate_ratio,
                    rotation=getattr(cr_src, "rotation", 0.0),
                    platforms=list(cr_src.platforms),
                )
                self._editor._asset.censors.append(new_cr)
                new_item = CensorRectItem(
                    QRectF(new_cr.x, new_cr.y, new_cr.w, new_cr.h),
                    new_cr.style, list(new_cr.platforms),
                )
                new_item._censor_region = new_cr
                new_item._editor = self._editor
                new_item.setZValue(100 + len(self._editor._censor_items))
                self._editor._scene.addItem(new_item)
                self._editor._censor_items.append(new_item)
                self._editor._refresh_layer_panel()
        elif chosen is save_default_act and self._editor:
            cr = getattr(self, "_censor_region", None)
            qs = QSettings("DoxyEdit", "DoxyEdit")
            qs.setValue("studio_censor_default_style", self.style)
            if cr is not None:
                qs.setValue("studio_censor_default_blur", int(cr.blur_radius or 20))
                qs.setValue("studio_censor_default_pixel",
                            int(cr.pixelate_ratio or 10))
            self._editor.info_label.setText(
                f"Saved default censor style: {self.style}")
        elif chosen is fwd_act and self._editor:
            cmd = SetZValueCmd(self, self.zValue(), self.zValue() + 1, "Bring forward")
            self._editor._undo_stack.push(cmd)
        elif chosen is bwd_act and self._editor:
            cmd = SetZValueCmd(self, self.zValue(), max(100, self.zValue() - 1), "Send backward")
            self._editor._undo_stack.push(cmd)
        elif chosen is front_act and self._editor:
            cmd = SetZValueCmd(self, self.zValue(), self.zValue() + 999, "Bring to front")
            self._editor._undo_stack.push(cmd)
        elif chosen is back_act and self._editor:
            cmd = SetZValueCmd(self, self.zValue(), 100, "Send to back")
            self._editor._undo_stack.push(cmd)
        elif plat_actions and (chosen is all_act or chosen in plat_actions):
            new_plats = _resolve_platform_menu(chosen, all_act, plat_actions, self.platforms)
            if self._editor:
                cr = getattr(self, "_censor_region", None)
                if cr is not None:
                    cmd = SetAttrCmd(
                        cr, "platforms", list(cr.platforms), new_plats,
                        apply_cb=lambda _t, v, _s=self: setattr(_s, "platforms", v)
                            or _s._editor._refresh_layer_panel(),
                        description="Change censor platforms",
                    )
                    self._editor._undo_stack.push(cmd)
                    self.platforms = new_plats
                    self._editor._sync_censors_to_asset()
                else:
                    self.platforms = new_plats
                    self._editor._sync_censors_to_asset()
                    self._editor._refresh_layer_panel()
            else:
                self.platforms = new_plats
        elif chosen.data():
            new_style = chosen.data()
            if self._editor:
                cr = getattr(self, "_censor_region", None)
                if cr is not None:
                    def _apply_style(t, v, _s=self):
                        _s.style = v
                        _s._apply_style()
                    cmd = SetAttrCmd(
                        cr, "style", cr.style, new_style,
                        apply_cb=_apply_style,
                        description=f"Change censor style to {new_style}",
                    )
                    self._editor._undo_stack.push(cmd)
                    self._editor._sync_censors_to_asset()
                else:
                    self.style = new_style
                    self._apply_style()
                    self._editor._sync_censors_to_asset()
            else:
                self.style = new_style
                self._apply_style()


class OverlayImageItem(QGraphicsPixmapItem):
    """Movable watermark/logo image — syncs position back to CanvasOverlay."""

    def __init__(self, pixmap: QPixmap, overlay: CanvasOverlay):
        super().__init__(pixmap)
        self.overlay = overlay
        self._editor = None  # set by StudioEditor after creation
        self.setFlags(
            QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsPixmapItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        # Cache the rendered item in device pixels so drag only blits the
        # cached copy and doesn't rescale the source pixmap every frame.
        self.setCacheMode(
            QGraphicsPixmapItem.CacheMode.DeviceCoordinateCache)
        self.setOpacity(overlay.opacity)
        self.setPos(overlay.x, overlay.y)
        # Rotate from center
        self.setTransformOriginPoint(pixmap.width() / 2, pixmap.height() / 2)
        if getattr(overlay, "flip_h", False) or getattr(overlay, "flip_v", False):
            t = QTransform()
            t.scale(-1.0 if overlay.flip_h else 1.0,
                    -1.0 if overlay.flip_v else 1.0)
            self.setTransform(t)
        if overlay.rotation:
            self.setRotation(overlay.rotation)
        if getattr(overlay, "locked", False):
            self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable, False)
            self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable, False)

    def itemChange(self, change, value):
        if change == QGraphicsPixmapItem.GraphicsItemChange.ItemPositionHasChanged:
            self.overlay.x = int(value.x())
            self.overlay.y = int(value.y())
            self.overlay.position = "custom"
        return super().itemChange(change, value)

    _BLEND_MODE_MAP = {
        "normal": QPainter.CompositionMode.CompositionMode_SourceOver,
        "multiply": QPainter.CompositionMode.CompositionMode_Multiply,
        "screen": QPainter.CompositionMode.CompositionMode_Screen,
        "overlay": QPainter.CompositionMode.CompositionMode_Overlay,
        "darken": QPainter.CompositionMode.CompositionMode_Darken,
        "lighten": QPainter.CompositionMode.CompositionMode_Lighten,
    }

    def paint(self, painter, option, widget=None):
        mode = self._BLEND_MODE_MAP.get(
            getattr(self.overlay, "blend_mode", "normal"),
            QPainter.CompositionMode.CompositionMode_SourceOver)
        if mode != QPainter.CompositionMode.CompositionMode_SourceOver:
            painter.setCompositionMode(mode)
        super().paint(painter, option, widget)

    def contextMenuEvent(self, event):
        _parent = self._editor._view if self._editor else None
        menu = _themed_menu(_parent)
        replace_act = menu.addAction("Replace Image...")
        dup_act = menu.addAction("Duplicate  (Ctrl+D)")
        fit_canvas_act = menu.addAction("Fit to Canvas")
        menu.addSeparator()
        save_style_act = menu.addAction("Save as Default Watermark Style")
        reset_style_act = menu.addAction("Reset Default Watermark Style")
        copy_style_act = menu.addAction("Copy Style")
        paste_style_act = menu.addAction("Paste Style")
        menu.addSeparator()
        filter_menu = menu.addMenu("Filter")
        filter_none_act = filter_menu.addAction("None")
        filter_gray_act = filter_menu.addAction("Grayscale")
        filter_invert_act = filter_menu.addAction("Invert Colors")
        filter_blur_act = filter_menu.addAction("Blur (soft)")
        filter_blur_hard_act = filter_menu.addAction("Blur (heavy)")
        current_filter = getattr(self.overlay, "filter_mode", "") or ""
        for a, v in ((filter_none_act, ""),
                      (filter_gray_act, "grayscale"),
                      (filter_invert_act, "invert"),
                      (filter_blur_act, "blur3"),
                      (filter_blur_hard_act, "blur8")):
            a.setCheckable(True)
            a.setChecked(current_filter == v)
        menu.addSeparator()
        blend_menu = menu.addMenu("Blend Mode")
        blend_acts = {}
        for bm in ("normal", "multiply", "screen", "overlay", "darken", "lighten"):
            a = blend_menu.addAction(bm.title())
            a.setCheckable(True)
            a.setChecked(getattr(self.overlay, "blend_mode", "normal") == bm)
            blend_acts[a] = bm
        select_same_blend_act = menu.addAction(
            f"Select All with {getattr(self.overlay, 'blend_mode', 'normal').title()} Blend")
        menu.addSeparator()
        flip_h_act = menu.addAction("Flip Horizontal  (Ctrl+Shift+H)")
        flip_v_act = menu.addAction("Flip Vertical  (Ctrl+Shift+V)")
        rot_cw_act = menu.addAction("Rotate 90° CW")
        rot_ccw_act = menu.addAction("Rotate 90° CCW")
        rot_180_act = menu.addAction("Rotate 180°")
        reset_xform_act = menu.addAction("Reset Transform")
        menu.addSeparator()
        front_act = menu.addAction("Bring to Front  (Ctrl+Shift+])")
        fwd_act = menu.addAction("Bring Forward  (Ctrl+])")
        bwd_act = menu.addAction("Send Backward  (Ctrl+[)")
        back_act = menu.addAction("Send to Back  (Ctrl+Shift+[)")
        menu.addSeparator()
        plat_sub = all_act = plat_actions = None
        if self._editor and self._editor._project:
            plat_sub, all_act, plat_actions = _add_platform_submenu(menu, self.overlay.platforms, self._editor)
            menu.addSeparator()
        del_act = menu.addAction("Delete")

        chosen = menu.exec(event.screenPos())
        if not chosen:
            return
        if chosen is replace_act and self._editor:
            self._editor._replace_overlay_image(self)
        elif chosen is dup_act and self._editor:
            self._editor._duplicate_overlay_item(self)
        elif chosen is fit_canvas_act and self._editor:
            # Rescale + reposition to cover the full image
            if self._editor._pixmap_item is not None:
                pm_rect = self._editor._pixmap_item.boundingRect()
                self.overlay.scale = 1.0
                self.overlay.x = int(pm_rect.left())
                self.overlay.y = int(pm_rect.top())
                self.overlay.position = "custom"
                # Reload the pixmap at the new scale
                self._editor._refresh_overlay_image(self)
                self.setPos(self.overlay.x, self.overlay.y)
                self._editor._sync_overlays_to_asset()
        elif chosen is save_style_act and self._editor:
            self._editor._save_watermark_style_as_default(self.overlay)
        elif chosen is reset_style_act and self._editor:
            self._editor._reset_watermark_style_defaults()
        elif chosen is copy_style_act and self._editor:
            self._editor._copy_style(self.overlay)
        elif chosen is paste_style_act and self._editor:
            self._editor._paste_style(self.overlay, self)
        elif chosen in blend_acts:
            self.overlay.blend_mode = blend_acts[chosen]
            self.update()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen in (filter_none_act, filter_gray_act,
                         filter_invert_act, filter_blur_act, filter_blur_hard_act):
            target = (
                "" if chosen is filter_none_act else
                "grayscale" if chosen is filter_gray_act else
                "invert" if chosen is filter_invert_act else
                "blur3" if chosen is filter_blur_act else "blur8")
            self.overlay.filter_mode = target
            # Re-render the pixmap with the filter applied
            if self._editor:
                self._editor._refresh_overlay_image(self)
                self._editor._sync_overlays_to_asset()
        elif chosen is select_same_blend_act and self._editor:
            bm = getattr(self.overlay, "blend_mode", "normal")
            self._editor._scene.clearSelection()
            for it in self._editor._overlay_items:
                if getattr(getattr(it, "overlay", None), "blend_mode", "normal") == bm:
                    it.setSelected(True)
        elif chosen is flip_h_act:
            self.overlay.flip_h = not getattr(self.overlay, "flip_h", False)
            self._apply_flip()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is flip_v_act:
            self.overlay.flip_v = not getattr(self.overlay, "flip_v", False)
            self._apply_flip()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is reset_xform_act:
            # Reset rotation + flip_h + flip_v. Keep position + scale.
            self.overlay.rotation = 0.0
            self.overlay.flip_h = False
            self.overlay.flip_v = False
            self.setTransform(QTransform())
            self.setRotation(0)
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is rot_cw_act:
            self.overlay.rotation = (self.overlay.rotation + 90) % 360
            self._apply_flip()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is rot_ccw_act:
            self.overlay.rotation = (self.overlay.rotation - 90) % 360
            self._apply_flip()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is rot_180_act:
            self.overlay.rotation = (self.overlay.rotation + 180) % 360
            self._apply_flip()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif plat_actions and (chosen is all_act or chosen in plat_actions):
            new_plats = _resolve_platform_menu(chosen, all_act, plat_actions, self.overlay.platforms)
            if self._editor:
                cmd = SetAttrCmd(
                    self.overlay, "platforms", list(self.overlay.platforms), new_plats,
                    apply_cb=lambda _t, _v: self._editor._refresh_layer_panel(),
                    description="Change platforms",
                )
                self._editor._undo_stack.push(cmd)
                self._editor._sync_overlays_to_asset()
            else:
                self.overlay.platforms = new_plats
        elif chosen is fwd_act:
            if self._editor:
                cmd = SetZValueCmd(self, self.zValue(), self.zValue() + 1, "Bring forward")
                self._editor._undo_stack.push(cmd)
            else:
                self.setZValue(self.zValue() + 1)
        elif chosen is front_act:
            new_z = self.zValue() + 999
            if self._editor:
                cmd = SetZValueCmd(self, self.zValue(), new_z, "Bring to front")
                self._editor._undo_stack.push(cmd)
            else:
                self.setZValue(new_z)
        elif chosen is back_act:
            if self._editor:
                cmd = SetZValueCmd(self, self.zValue(), 200, "Send to back")
                self._editor._undo_stack.push(cmd)
            else:
                self.setZValue(200)
        elif chosen is bwd_act:
            new_z = max(200, self.zValue() - 1)
            if self._editor:
                cmd = SetZValueCmd(self, self.zValue(), new_z, "Send backward")
                self._editor._undo_stack.push(cmd)
            else:
                self.setZValue(new_z)
        elif chosen is del_act and self._editor:
            self._editor._remove_overlay_item(self)

    def _apply_flip(self):
        """Apply flip_h / flip_v via negative scale around item center."""
        self.setTransformOriginPoint(self.boundingRect().center())
        sx = -1.0 if getattr(self.overlay, "flip_h", False) else 1.0
        sy = -1.0 if getattr(self.overlay, "flip_v", False) else 1.0
        # Compose flip + existing rotation
        t = QTransform()
        t.scale(sx, sy)
        self.setTransform(t)
        self.setRotation(self.overlay.rotation)

    def mouseDoubleClickEvent(self, event):
        """Double-click shortcut for 'Replace Image...'"""
        if self._editor:
            self._editor._replace_overlay_image(self)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def _render_shape_to_image(overlay_snapshot, pad: int):
    """Return a closure that renders a shape snapshot into a QImage.

    The closure runs on a worker thread (no Qt event loop). It uses a
    local QPainter on the provided image — QPainter is documented as
    safe to use off the GUI thread as long as each QPaintDevice is
    owned by a single thread for the duration.

    Coordinates: the shape's body rect is drawn at origin (pad, pad).
    When the GUI thread adopts the image, it translates by (x-pad, y-pad)
    so the shape lands at the overlay's scene position.
    """
    from PySide6.QtGui import (
        QPainter, QColor, QPen, QBrush, QPainterPath, QPolygonF,
        QLinearGradient, QRadialGradient,
    )
    import math as _math

    def _run(img, params):
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ov = overlay_snapshot
        kind = getattr(ov, "shape_kind", "rect") or "rect"
        w = float(getattr(ov, "shape_w", 100) or 100)
        h = float(getattr(ov, "shape_h", 100) or 100)
        # Local rect at (pad, pad)
        body = QRectF(pad, pad, w, h)
        # Build path in local coords
        path = QPainterPath()
        if kind == "rect":
            radius = float(getattr(ov, "corner_radius", 0) or 0)
            if radius > 0:
                path.addRoundedRect(body, radius, radius)
            else:
                path.addRect(body)
        elif kind == "ellipse":
            path.addEllipse(body)
        elif kind == "star":
            n = max(3, int(getattr(ov, "star_points", 5) or 5))
            inner = max(0.1, min(0.95,
                float(getattr(ov, "inner_ratio", 0.4) or 0.4)))
            cx, cy = pad + w / 2, pad + h / 2
            rx, ry = w / 2, h / 2
            pts = []
            for i in range(n * 2):
                frac = (2 * _math.pi * i) / (n * 2) - _math.pi / 2
                s = 1.0 if i % 2 == 0 else inner
                pts.append(QPointF(cx + _math.cos(frac) * rx * s,
                                    cy + _math.sin(frac) * ry * s))
            path.addPolygon(QPolygonF(pts))
            path.closeSubpath()
        elif kind == "polygon":
            n = max(3, int(getattr(ov, "star_points", 6) or 6))
            cx, cy = pad + w / 2, pad + h / 2
            rx, ry = w / 2, h / 2
            pts = []
            for i in range(n):
                frac = (2 * _math.pi * i) / n - _math.pi / 2
                pts.append(QPointF(cx + _math.cos(frac) * rx,
                                    cy + _math.sin(frac) * ry))
            path.addPolygon(QPolygonF(pts))
            path.closeSubpath()
        elif kind == "burst":
            cx, cy = pad + w / 2, pad + h / 2
            rx, ry = w / 2, h / 2
            n = 14
            inner = 0.62
            pts = []
            for i in range(n * 2):
                frac = (2 * _math.pi * i) / (n * 2)
                s = 1.0 if i % 2 == 0 else inner
                pts.append(QPointF(
                    cx + _math.cos(frac - _math.pi / 2) * rx * s,
                    cy + _math.sin(frac - _math.pi / 2) * ry * s))
            path.addPolygon(QPolygonF(pts))
            path.closeSubpath()
        elif kind == "speech_bubble":
            roundness = max(0.0, min(1.0,
                getattr(ov, "bubble_roundness", 0.0) or 0.0))
            inner_pad = min(w, h) * 0.18
            eff_pad = inner_pad + (min(w, h) / 2 - inner_pad) * roundness
            path.addRoundedRect(body, eff_pad, eff_pad)
            tx = getattr(ov, "tail_x", 0) or 0
            ty = getattr(ov, "tail_y", 0) or 0
            if tx == 0 and ty == 0:
                tip_x = pad - w * 0.15
                tip_y = pad + h + h * 0.35
            else:
                tip_x = pad + (float(tx) - float(ov.x))
                tip_y = pad + (float(ty) - float(ov.y))
            base_len = min(w, h) * 0.25
            tail = QPainterPath()
            tail.moveTo(pad, pad + h * 0.5)
            tail.lineTo(tip_x, tip_y)
            tail.lineTo(pad, pad + h * 0.5 + base_len)
            tail.closeSubpath()
            path = path.united(tail)
        elif kind == "thought_bubble":
            # Central ellipse + 10 peripheral puff unions.
            cx, cy = pad + w / 2, pad + h / 2
            rx, ry = w / 2, h / 2
            path.addEllipse(QRectF(
                cx - rx * 0.78, cy - ry * 0.78,
                rx * 1.56, ry * 1.56))
            n_puffs = 10
            puff_r = min(rx, ry) * 0.28
            for i in range(n_puffs):
                ang = (2 * _math.pi * i) / n_puffs
                px = cx + _math.cos(ang) * (rx - puff_r * 0.4)
                py = cy + _math.sin(ang) * (ry - puff_r * 0.4)
                sub = QPainterPath()
                sub.addEllipse(QPointF(px, py), puff_r, puff_r)
                path = path.united(sub)
        else:
            path.addRect(body)
        # Fill — gradient first (for gradient_linear/gradient_radial),
        # then solid fill_color.
        if kind in ("gradient_linear", "gradient_radial"):
            def _parse_hex_grad(s, default):
                h = (s or default).lstrip("#")
                if len(h) == 8:
                    return QColor(int(h[0:2], 16), int(h[2:4], 16),
                                   int(h[4:6], 16), int(h[6:8], 16))
                return QColor(s or default)
            c0 = _parse_hex_grad(
                getattr(ov, "gradient_start_color", "") or "", "#000000")
            c1 = _parse_hex_grad(
                getattr(ov, "gradient_end_color", "") or "", "#ffffff")
            op = float(getattr(ov, "opacity", 1.0) or 1.0)
            c0.setAlphaF(c0.alphaF() * op)
            c1.setAlphaF(c1.alphaF() * op)
            if kind == "gradient_linear":
                ang = _math.radians(
                    float(getattr(ov, "gradient_angle", 0) or 0))
                cx, cy = pad + w / 2, pad + h / 2
                half_w = w / 2
                gx0 = cx - _math.cos(ang) * half_w
                gy0 = cy - _math.sin(ang) * half_w
                gx1 = cx + _math.cos(ang) * half_w
                gy1 = cy + _math.sin(ang) * half_w
                grad = QLinearGradient(gx0, gy0, gx1, gy1)
            else:
                grad = QRadialGradient(
                    QPointF(pad + w / 2, pad + h / 2),
                    max(w, h) / 2)
            grad.setColorAt(0.0, c0)
            grad.setColorAt(1.0, c1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRect(body)
        else:
            fill_hex = getattr(ov, "fill_color", "") or ""
            if fill_hex:
                c = QColor(fill_hex)
                c.setAlphaF(float(getattr(ov, "opacity", 1.0) or 1.0))
                p.setBrush(QBrush(c))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawPath(path)
        # Stroke
        stroke_w = float(getattr(ov, "stroke_width", 0) or 0)
        stroke_hex = (getattr(ov, "stroke_color", "")
                      or getattr(ov, "color", "") or "")
        if stroke_w > 0 and stroke_hex:
            sc = QColor(stroke_hex)
            sc.setAlphaF(float(getattr(ov, "opacity", 1.0) or 1.0))
            pen = QPen(sc, stroke_w)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.end()

    return _run


class _OverlayCacheSignals(QObject):
    """Signal object for the overlay cache worker — QObject so the
    signal can marshal back to the GUI thread via Qt::QueuedConnection.
    Carries the output QImage + the parameter snapshot that produced
    it so the item can reject stale results (e.g. another rebuild
    scheduled mid-flight won the race)."""
    done = Signal(int, object, QImage)   # (token, params_tuple, qimage)


class OverlayCacheBuilder(QRunnable):
    """Off-thread overlay pre-render (E3 from the deep-dive).

    Takes a render callable + parameter snapshot, executes on the
    QThreadPool, posts the resulting QImage back to the item via
    signal. The GUI thread's slot compares the snapshot against the
    item's current parameters; if they still match, the cached QImage
    is adopted. If they don't (user moved another slider during the
    build), the result is discarded and a fresh build is scheduled.

    Usage:
        signals = _OverlayCacheSignals()
        signals.done.connect(item._adopt_cached_render)
        builder = OverlayCacheBuilder(token, params, size, render_fn, signals)
        QThreadPool.globalInstance().start(builder)

    render_fn signature: (QImage, params_tuple) -> None
    It should paint into the provided QImage using a local QPainter.
    Running on a worker thread — MUST NOT touch scene items, only
    the image buffer and the params it was given.
    """

    def __init__(self, token: int, params: tuple, size: QSize,
                 render_fn, signals: _OverlayCacheSignals):
        super().__init__()
        self._token = token
        self._params = params
        self._size = size
        self._render_fn = render_fn
        self._signals = signals
        self.setAutoDelete(True)

    def run(self):
        try:
            img = QImage(
                max(1, self._size.width()),
                max(1, self._size.height()),
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            img.fill(Qt.GlobalColor.transparent)
            self._render_fn(img, self._params)
            self._signals.done.emit(self._token, self._params, img)
        except Exception:
            # Swallow — caller will fall back to live render.
            pass


class OverlayShapeItem(QGraphicsItem):
    """Non-destructive shape overlay (rectangle or ellipse).

    Top-left at (overlay.x, overlay.y), dimensions shape_w × shape_h.
    stroke_color + stroke_width describe the outline; fill_color (empty =
    hollow) fills the interior. Movable + selectable; corner handles when
    selected for click-drag resize (Photoshop convention)."""

    HANDLE_HIT_RADIUS = 10

    def __init__(self, overlay: "CanvasOverlay", parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        # No item-level cache: OverlayShapeItem calls prepareGeometryChange
        # on every drag frame (because paint reads overlay.x/y directly
        # and boundingRect depends on them), which invalidates any device
        # cache every frame. The cache would be pure allocation overhead
        # during drag. Path is cached separately (_cached_path, local
        # coords) so paint is fast without an item-level cache.
        self._editor = None
        self._dragging_handle = None  # 'tl', 'tr', 'bl', 'br', or None
        self.setZValue(200)
        # Path cache — (params_tuple, QPainterPath). Bubble paths go
        # through path.united() + a 72-sample wobble loop on every paint,
        # so rebuilding per frame murders perf during drag. Cache is
        # invalidated by the _shape_params_tuple() check inside paint.
        self._cached_path_key = None
        self._cached_path = None
        # E3: off-thread render cache. _cached_render is an ARGB32
        # QImage of the fully-rendered shape (fill + stroke) produced
        # on a worker thread; paint() blits it instead of re-running
        # drawPath. Invalidated by the _shape_params_tuple() check.
        # _render_token increments on every schedule so stale results
        # can be rejected.
        self._cached_render: QImage | None = None
        self._cached_render_key: tuple | None = None
        self._render_token: int = 0
        self._render_in_flight: bool = False
        self._render_signals: _OverlayCacheSignals | None = None
        # Apply persisted rotation. Transform origin is the rect center so
        # rotation pivots on the item.
        if getattr(overlay, "rotation", 0):
            self.setTransformOriginPoint(
                overlay.x + overlay.shape_w / 2,
                overlay.y + overlay.shape_h / 2)
            self.setRotation(overlay.rotation)

    def _ensure_render_signals(self):
        """Lazy-create the signals object + wire the adopt slot."""
        if self._render_signals is None:
            self._render_signals = _OverlayCacheSignals()
            self._render_signals.done.connect(self._adopt_cached_render)

    @Slot(int, object, QImage)
    def _adopt_cached_render(self, token: int, params: tuple,
                              qimage: QImage):
        """Worker thread finished. Adopt the QImage iff the params
        still match the current ones (user didn't change anything
        while we were rendering)."""
        self._render_in_flight = False
        if token != self._render_token:
            return  # superseded by a later schedule
        current = self._shape_render_params_tuple()
        if params != current:
            # User changed something after we kicked off — re-schedule
            # instead of adopting stale pixels.
            self._schedule_cached_render()
            return
        self._cached_render = qimage
        self._cached_render_key = params
        self.update()

    def _schedule_cached_render(self):
        """Queue an off-thread rebuild of the full-shape QImage cache.
        Safe to call repeatedly — if a build is already in flight a
        fresh one isn't queued until it completes; the completion
        handler re-checks params and re-schedules if needed."""
        if self._render_in_flight:
            return
        self._ensure_render_signals()
        params = self._shape_render_params_tuple()
        if params == self._cached_render_key and self._cached_render is not None:
            return  # cache already valid for these params
        w = int(max(1, getattr(self.overlay, "shape_w", 0) or 0))
        h = int(max(1, getattr(self.overlay, "shape_h", 0) or 0))
        # Include stroke pad so the render doesn't clip thick strokes.
        pad = int(max(4, getattr(self.overlay, "stroke_width", 0) or 0) * 2)
        size = QSize(w + pad * 2, h + pad * 2)
        self._render_token += 1
        token = self._render_token
        self._render_in_flight = True
        # Freeze a copy of the overlay so the worker doesn't see later
        # mutations from the GUI thread.
        snap = copy.copy(self.overlay)
        render_fn = _render_shape_to_image(snap, pad)
        QThreadPool.globalInstance().start(
            OverlayCacheBuilder(token, params, size, render_fn,
                                self._render_signals))

    def _shape_params_tuple(self) -> tuple:
        """Tuple of every parameter that affects the shape's painter path.
        Used as a cache key — if it's unchanged since the last paint, we
        can re-use the cached QPainterPath instead of rebuilding.

        x/y are intentionally NOT in the key. The cached path is stored
        in the shape's local coordinate system (origin = top-left of the
        body rect), translated on draw via painter.translate(). That way
        dragging the bubble — which only changes overlay.x/y — hits the
        cache on every frame instead of rebuilding path.united() + up to
        72 wobble samples.

        The tail offset *relative to* the body origin IS included so the
        cache invalidates when the tail moves independently (not during
        body drag, since itemChange updates body + tail in lock-step)."""
        ov = self.overlay
        tail_dx = getattr(ov, "tail_x", 0) - ov.x
        tail_dy = getattr(ov, "tail_y", 0) - ov.y
        return (
            ov.shape_kind,
            int(ov.shape_w), int(ov.shape_h),
            getattr(ov, "corner_radius", 0),
            getattr(ov, "bubble_roundness", 0.0),
            getattr(ov, "bubble_oval_stretch", 0.0),
            getattr(ov, "bubble_wobble", 0.0),
            getattr(ov, "tail_curve", 0.0),
            int(tail_dx), int(tail_dy),
            getattr(ov, "star_points", 0),
            getattr(ov, "inner_ratio", 0.0),
            getattr(ov, "polygon_vertices", 0),
        )

    def _shape_render_params_tuple(self) -> tuple:
        """Like _shape_params_tuple but includes every attribute the
        rendered bitmap depends on: fill / stroke colors, opacity,
        stroke_width, line_style, gradient endpoints, stroke_align.

        Used ONLY as the E3 off-thread cache key — the path cache
        still uses the geometry-only tuple so a color change doesn't
        need to rebuild the QPainterPath.

        Keys NOT in this tuple: x, y (position applied at draw time),
        rotation (applied via painter.rotate), blend_mode (applied
        at draw time; also the fast-blit path is skipped for non-
        normal blend modes anyway)."""
        ov = self.overlay
        return self._shape_params_tuple() + (
            getattr(ov, "fill_color", "") or "",
            getattr(ov, "stroke_color", "") or "",
            getattr(ov, "color", "") or "",
            float(getattr(ov, "opacity", 1.0) or 1.0),
            float(getattr(ov, "stroke_width", 0) or 0),
            getattr(ov, "line_style", "solid") or "solid",
            getattr(ov, "stroke_align", "center") or "center",
            getattr(ov, "gradient_start_color", "") or "",
            getattr(ov, "gradient_end_color", "") or "",
            float(getattr(ov, "gradient_angle", 0) or 0),
        )

    def hoverMoveEvent(self, event):
        # Swap cursor when hovering a handle so users know they can resize
        if self.isSelected():
            if self._rotate_handle_under(event.scenePos()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self._tail_handle_under(event.scenePos()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self._corner_radius_handle_under(event.scenePos()):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif self._star_inner_handle_under(event.scenePos()):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif self._polygon_vertex_handle_under(event.scenePos()):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                h = self._handle_under(event.scenePos())
                if h in ('tl', 'br'):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif h in ('tr', 'bl'):
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                else:
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def _handle_positions(self) -> dict:
        """Return {handle_key: QPointF} for the four corners."""
        x, y = self.overlay.x, self.overlay.y
        w, h = self.overlay.shape_w, self.overlay.shape_h
        return {
            'tl': QPointF(x, y),
            'tr': QPointF(x + w, y),
            'bl': QPointF(x, y + h),
            'br': QPointF(x + w, y + h),
        }

    def _tail_tip(self, r: QRectF) -> QPointF:
        """Tail tip scene pos. Default = below-left of the body if unset."""
        tx = self.overlay.tail_x
        ty = self.overlay.tail_y
        if tx == 0 and ty == 0:
            return QPointF(r.left() - r.width() * 0.15,
                            r.bottom() + r.height() * 0.35)
        return QPointF(tx, ty)

    def _paint_speech_bubble(self, painter, r: QRectF):
        """Rounded-rect body with a triangular tail anchored on the closest
        edge to tail_tip. Path is cached per parameter-tuple — stored in
        LOCAL coords and drawn via painter.translate() so dragging the
        bubble (which only shifts overlay.x/y) doesn't invalidate the
        cache. Cache hit = one translate + drawPath. Cache miss involves
        path.united() + up to 72 wobble samples."""
        key = ("speech", self._shape_params_tuple())
        if self._cached_path_key == key and self._cached_path is not None:
            painter.save()
            painter.translate(r.left(), r.top())
            painter.drawPath(self._cached_path)
            painter.restore()
            return
        pad = min(r.width(), r.height()) * 0.18
        tip = self._tail_tip(r)
        # Tail base: pick two points on the body edge closest to the tip
        cx, cy = r.center().x(), r.center().y()
        dx, dy = tip.x() - cx, tip.y() - cy
        horiz = abs(dx) > abs(dy)
        base_len = min(r.width(), r.height()) * 0.25
        # Overlap the tail base into the body interior so the union erases
        # the seam. ~8% of body short-side, clamped to a minimum so small
        # bubbles still merge cleanly.
        overlap = max(4.0, min(r.width(), r.height()) * 0.08)
        # Apply bubble_oval_stretch: >0 widens, <0 taller. Normalize
        # against a central pivot so the overall footprint stays similar.
        stretch = max(-0.6, min(0.6, getattr(self.overlay, "bubble_oval_stretch", 0.0)))
        if stretch != 0:
            sx = 1.0 + stretch
            sy = 1.0 - stretch * 0.5
            new_w = r.width() * sx
            new_h = r.height() * sy
            r = QRectF(cx - new_w / 2, cy - new_h / 2, new_w, new_h)
        if horiz:
            if dx > 0:
                edge_x = r.right() - overlap
            else:
                edge_x = r.left() + overlap
            mid_y = max(r.top() + pad,
                         min(r.bottom() - pad, tip.y() * 0.5 + cy * 0.5))
            b1 = QPointF(edge_x, mid_y - base_len / 2)
            b2 = QPointF(edge_x, mid_y + base_len / 2)
        else:
            if dy > 0:
                edge_y = r.bottom() - overlap
            else:
                edge_y = r.top() + overlap
            mid_x = max(r.left() + pad,
                         min(r.right() - pad, tip.x() * 0.5 + cx * 0.5))
            b1 = QPointF(mid_x - base_len / 2, edge_y)
            b2 = QPointF(mid_x + base_len / 2, edge_y)
        # Build path: roundness blends between pad-rounded rect (0.0)
        # and a pure ellipse (1.0).
        roundness = max(0.0, min(1.0,
            getattr(self.overlay, "bubble_roundness", 0.0)))
        path = QPainterPath()
        if roundness >= 0.99:
            path.addEllipse(r)
        else:
            effective_pad = pad + (min(r.width(), r.height()) / 2 - pad) * roundness
            path.addRoundedRect(r, effective_pad, effective_pad)
        tail = QPainterPath()
        tail.moveTo(b1)
        tail_curve = max(-1.0, min(1.0,
            float(getattr(self.overlay, "tail_curve", 0.0) or 0.0)))
        if abs(tail_curve) > 0.02:
            # Bezier tail: compute a control point perpendicular to the
            # b1 - tip line, offset by curve * base_len * 1.2. Sides of
            # the tail both curve in the same direction so the tail
            # swoops instead of going straight.
            def _perp_ctrl(src, dst, amount):
                mx = (src.x() + dst.x()) / 2
                my = (src.y() + dst.y()) / 2
                dx = dst.x() - src.x()
                dy = dst.y() - src.y()
                length = math.hypot(dx, dy) or 1.0
                nx = -dy / length
                ny = dx / length
                return QPointF(mx + nx * amount, my + ny * amount)
            amt = tail_curve * base_len * 1.2
            c1 = _perp_ctrl(b1, tip, amt)
            c2 = _perp_ctrl(tip, b2, amt)
            tail.quadTo(c1, tip)
            tail.quadTo(c2, b2)
        else:
            tail.lineTo(tip)
            tail.lineTo(b2)
        tail.closeSubpath()
        path = path.united(tail)
        # Wobble: walk the path at many points and push each one a small
        # amount along its normal using a sin function of its arc-length
        # parameter. Produces a hand-drawn look.
        wobble = max(0.0, min(1.0,
            getattr(self.overlay, "bubble_wobble", 0.0)))
        if wobble > 0.01:
            amp = wobble * min(r.width(), r.height()) * 0.04
            wobbled = QPainterPath()
            n = 72
            length = path.length() or 1.0
            for i in range(n + 1):
                t = (i / n) * length
                pct = t / length
                pt = path.pointAtPercent(pct)
                ang = path.angleAtPercent(pct)
                normal = math.radians(ang + 90)
                push = math.sin(pct * math.pi * 8) * amp
                nx = pt.x() + math.cos(normal) * push
                ny = pt.y() - math.sin(normal) * push
                if i == 0:
                    wobbled.moveTo(nx, ny)
                else:
                    wobbled.lineTo(nx, ny)
            wobbled.closeSubpath()
            path = wobbled
        # Store the path translated to local coords so cache hits survive
        # drag (which only shifts r.left()/r.top() each frame).
        self._cached_path_key = key
        self._cached_path = path.translated(-r.left(), -r.top())
        painter.drawPath(path)

    def _paint_thought_bubble(self, painter, r: QRectF):
        """Scalloped-cloud body + 2-3 trailing puff circles toward tail.
        Path cached per parameter-tuple in local coords — cloud puffs use
        path.united() in a loop which is the single most expensive path
        op in Qt. Translate on draw so drag keeps the cache."""
        key = ("thought", self._shape_params_tuple())
        if self._cached_path_key == key and self._cached_path is not None:
            painter.save()
            painter.translate(r.left(), r.top())
            painter.drawPath(self._cached_path)
            painter.restore()
            # Trailing puff circles use tail_tip which is in scene coords —
            # keep drawing in scene space (cheap, 3 drawEllipse calls).
            tip = self._tail_tip(r)
            cx, cy = r.center().x(), r.center().y()
            dx, dy = tip.x() - cx, tip.y() - cy
            length = math.hypot(dx, dy)
            if length > 4:
                rx, ry = r.width() / 2, r.height() / 2
                puff_r = min(rx, ry) * 0.28
                ux, uy = dx / length, dy / length
                start_offset = min(rx, ry) * 0.85
                for i, frac in enumerate((0.25, 0.55, 0.85)):
                    pr = puff_r * (0.55 - i * 0.15)
                    ppos = QPointF(
                        cx + ux * (start_offset + length * frac * 0.6),
                        cy + uy * (start_offset + length * frac * 0.6))
                    painter.drawEllipse(ppos, pr, pr)
            return
        path = QPainterPath()
        # Build the cloud by unioning a central ellipse with 8 edge puffs.
        cx, cy = r.center().x(), r.center().y()
        rx, ry = r.width() / 2, r.height() / 2
        path.addEllipse(r.adjusted(rx * 0.22, ry * 0.22, -rx * 0.22, -ry * 0.22))
        n_puffs = 10
        puff_r = min(rx, ry) * 0.28
        for i in range(n_puffs):
            ang = (2 * math.pi * i) / n_puffs
            px = cx + math.cos(ang) * (rx - puff_r * 0.4)
            py = cy + math.sin(ang) * (ry - puff_r * 0.4)
            sub = QPainterPath()
            sub.addEllipse(QPointF(px, py), puff_r, puff_r)
            path = path.united(sub)
        # Store in local coords (translated to origin) so drag hits cache.
        self._cached_path_key = key
        self._cached_path = path.translated(-r.left(), -r.top())
        painter.drawPath(path)
        # Trailing small circles toward the tail
        tip = self._tail_tip(r)
        dx, dy = tip.x() - cx, tip.y() - cy
        length = math.hypot(dx, dy)
        if length > 4:
            ux, uy = dx / length, dy / length
            start_offset = min(rx, ry) * 0.85
            for i, frac in enumerate((0.25, 0.55, 0.85)):
                pr = puff_r * (0.55 - i * 0.15)
                ppos = QPointF(cx + ux * (start_offset + length * frac * 0.6),
                                cy + uy * (start_offset + length * frac * 0.6))
                painter.drawEllipse(ppos, pr, pr)

    def _paint_burst(self, painter, r: QRectF):
        """Jagged star/burst polygon with alternating outer/inner radii."""
        cx, cy = r.center().x(), r.center().y()
        rx, ry = r.width() / 2, r.height() / 2
        points = []
        n_points = 14
        inner_scale = 0.62
        for i in range(n_points * 2):
            frac = (2 * math.pi * i) / (n_points * 2)
            s = 1.0 if i % 2 == 0 else inner_scale
            px = cx + math.cos(frac - math.pi / 2) * rx * s
            py = cy + math.sin(frac - math.pi / 2) * ry * s
            points.append(QPointF(px, py))
        painter.drawPolygon(QPolygonF(points))

    def _paint_star(self, painter, r: QRectF):
        """Regular n-pointed star. Controlled by overlay.star_points
        (number of outer points, default 5) and overlay.inner_ratio
        (inner/outer radius fraction, default 0.4)."""
        cx, cy = r.center().x(), r.center().y()
        rx, ry = r.width() / 2, r.height() / 2
        n_points = max(3, int(getattr(self.overlay, "star_points", 5) or 5))
        inner_scale = max(0.1, min(0.95,
            float(getattr(self.overlay, "inner_ratio", 0.4) or 0.4)))
        points = []
        for i in range(n_points * 2):
            frac = (2 * math.pi * i) / (n_points * 2)
            s = 1.0 if i % 2 == 0 else inner_scale
            px = cx + math.cos(frac - math.pi / 2) * rx * s
            py = cy + math.sin(frac - math.pi / 2) * ry * s
            points.append(QPointF(px, py))
        painter.drawPolygon(QPolygonF(points))

    def _paint_polygon(self, painter, r: QRectF):
        """Regular n-sided polygon. Controlled by overlay.star_points
        (vertex count, default 6 = hexagon). Rotated so a flat edge
        sits at the bottom for n=4,6,8 (a pointy top for n=3,5,7)."""
        cx, cy = r.center().x(), r.center().y()
        rx, ry = r.width() / 2, r.height() / 2
        n = max(3, int(getattr(self.overlay, "star_points", 6) or 6))
        points = []
        for i in range(n):
            frac = (2 * math.pi * i) / n - math.pi / 2
            px = cx + math.cos(frac) * rx
            py = cy + math.sin(frac) * ry
            points.append(QPointF(px, py))
        painter.drawPolygon(QPolygonF(points))

    def _handle_under(self, scene_pos: QPointF):
        # Map scene -> local so rotation / skew don't shift the hotspots
        # away from the handles the user actually sees. _handle_positions
        # returns local-space coords (overlay.x/y is local since item
        # itself lives at pos() == 0,0).
        local = self.mapFromScene(scene_pos)
        r = self.HANDLE_HIT_RADIUS
        for key, pt in self._handle_positions().items():
            if abs(local.x() - pt.x()) <= r and abs(local.y() - pt.y()) <= r:
                return key
        return None

    def _zoom_adaptive_radius(self, screen_px: int = 16) -> float:
        """Return a scene-space hit radius that always feels ~screen_px
        wide on-screen regardless of zoom level. At 100% zoom,
        `screen_px` scene-px == `screen_px` screen-px; at 25% zoom the
        radius grows to 4× screen-px so handles stay grabbable when the
        user is zoomed out."""
        try:
            m = self._editor._view.transform().m11() if self._editor else 1.0
        except Exception:
            m = 1.0
        if m <= 0.01:
            m = 1.0
        return screen_px / m

    def _tail_handle_under(self, scene_pos: QPointF) -> bool:
        """True if `scene_pos` is near the bubble tail tip handle.
        Uses a zoom-adaptive radius — the handle was notoriously finicky
        to grab when the view was zoomed out. scene_pos is mapped into
        local coords so rotation + skew don't misalign the hotspot."""
        if not self._is_bubble():
            return False
        local = self.mapFromScene(scene_pos)
        body = QRectF(self.overlay.x, self.overlay.y,
                      self.overlay.shape_w, self.overlay.shape_h)
        tip = self._tail_tip(body)
        r = self._zoom_adaptive_radius(18)
        return (abs(local.x() - tip.x()) <= r
                and abs(local.y() - tip.y()) <= r)

    def _polygon_vertex_handle_pos(self) -> QPointF:
        """Scene-space position of the polygon vertex-count handle.
        Sits on the east spoke of a polygon shape. Dragging horizontally
        adjusts star_points: further right / closer to center (relative
        to shape_w / 2) changes the vertex count. We'll map this to a
        simple interpretation: handle offset from center = n / 12 of
        shape_w."""
        ov = self.overlay
        cx = ov.x + ov.shape_w / 2
        cy = ov.y + ov.shape_h / 2
        # Anchor the handle at 80% of the east spoke so it's visibly
        # outside any polygon drawing.
        return QPointF(cx + ov.shape_w * 0.42, cy)

    def _polygon_vertex_handle_under(self, scene_pos: QPointF) -> bool:
        if self.overlay.shape_kind != "polygon":
            return False
        local = self.mapFromScene(scene_pos)
        hp = self._polygon_vertex_handle_pos()
        r = self._zoom_adaptive_radius(14)
        return (abs(local.x() - hp.x()) <= r
                and abs(local.y() - hp.y()) <= r)

    def _star_inner_handle_pos(self) -> QPointF:
        """Scene-space position of the star inner-radius handle. A point
        on the line from shape center to 12 o'clock, at distance
        inner_ratio * rx from center. Dragging toward the center
        shrinks inner_ratio (narrower star); outward widens it."""
        ov = self.overlay
        cx = ov.x + ov.shape_w / 2
        cy = ov.y + ov.shape_h / 2
        rx = ov.shape_w / 2
        ry = ov.shape_h / 2
        r = max(0.1, min(0.95, float(getattr(ov, "inner_ratio", 0.4) or 0.4)))
        # Place the handle straight up from center at the inner radius
        return QPointF(cx, cy - ry * r)

    def _star_inner_handle_under(self, scene_pos: QPointF) -> bool:
        if self.overlay.shape_kind != "star":
            return False
        local = self.mapFromScene(scene_pos)
        hp = self._star_inner_handle_pos()
        r = self._zoom_adaptive_radius(14)
        return (abs(local.x() - hp.x()) <= r
                and abs(local.y() - hp.y()) <= r)

    def _corner_radius_handle_pos(self) -> QPointF:
        """Scene-space position of the corner-radius handle. Appears
        offset from the top-left corner of a rect by `corner_radius`
        pixels on the X axis. Dragging right increases the radius,
        left decreases. Only meaningful for shape_kind == 'rect'."""
        x, y = self.overlay.x, self.overlay.y
        w = max(1, self.overlay.shape_w)
        radius = max(0, min(
            int(self.overlay.corner_radius or 0),
            w // 2))
        return QPointF(x + radius, y)

    def _corner_radius_handle_under(self, scene_pos: QPointF) -> bool:
        if self.overlay.shape_kind != "rect":
            return False
        local = self.mapFromScene(scene_pos)
        hp = self._corner_radius_handle_pos()
        r = self._zoom_adaptive_radius(14)
        return (abs(local.x() - hp.x()) <= r
                and abs(local.y() - hp.y()) <= r)

    def _rotate_handle_pos(self) -> QPointF:
        """Scene-space position of the rotate handle: above the top edge
        of the body, offset by a screen-space margin so it's always
        reachable regardless of zoom."""
        x, y = self.overlay.x, self.overlay.y
        w = self.overlay.shape_w
        # Scale the offset with zoom so the handle sits a consistent
        # ~22 screen-pixels above the body at any magnification.
        try:
            m = self._editor._view.transform().m11() if self._editor else 1.0
        except Exception:
            m = 1.0
        if m <= 0.01:
            m = 1.0
        return QPointF(x + w / 2, y - 22 / m)

    def _rotate_handle_under(self, scene_pos: QPointF) -> bool:
        local = self.mapFromScene(scene_pos)
        rh = self._rotate_handle_pos()
        r = self._zoom_adaptive_radius(18)
        return (abs(local.x() - rh.x()) <= r
                and abs(local.y() - rh.y()) <= r)

    def _is_bubble(self) -> bool:
        return self.overlay.shape_kind in ("speech_bubble", "thought_bubble")

    def boundingRect(self) -> QRectF:
        x, y = self.overlay.x, self.overlay.y
        w, h = self.overlay.shape_w, self.overlay.shape_h
        pad = max(4, (self.overlay.stroke_width or 1))
        r = QRectF(x - pad, y - pad, w + 2 * pad, h + 2 * pad)
        # Bubbles: extend bounding rect so the tail tip is part of the
        # paint region. Without this, dragging the tail outside the body
        # bounds leaves paint artifacts when the tail is cut off.
        if self._is_bubble():
            body = QRectF(self.overlay.x, self.overlay.y,
                          self.overlay.shape_w, self.overlay.shape_h)
            tip = self._tail_tip(body)
            tail_pad = 12
            min_x = min(r.left(), tip.x() - tail_pad)
            min_y = min(r.top(), tip.y() - tail_pad)
            max_x = max(r.right(), tip.x() + tail_pad)
            max_y = max(r.bottom(), tip.y() + tail_pad)
            r = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        # Expand upward so the rotate-handle circle is inside the paint
        # region when selected (otherwise dragging it leaves artifacts).
        rh = self._rotate_handle_pos()
        rh_pad = 10
        min_x = min(r.left(), rh.x() - rh_pad)
        min_y = min(r.top(), rh.y() - rh_pad)
        max_x = max(r.right(), rh.x() + rh_pad)
        max_y = max(r.bottom(), rh.y() + rh_pad)
        return QRectF(min_x, min_y, max_x - min_x, max_y - min_y)

    _BLEND_MODE_MAP = {
        "normal": QPainter.CompositionMode.CompositionMode_SourceOver,
        "multiply": QPainter.CompositionMode.CompositionMode_Multiply,
        "screen": QPainter.CompositionMode.CompositionMode_Screen,
        "overlay": QPainter.CompositionMode.CompositionMode_Overlay,
        "darken": QPainter.CompositionMode.CompositionMode_Darken,
        "lighten": QPainter.CompositionMode.CompositionMode_Lighten,
    }

    def paint(self, painter, option, widget=None):
        # E3: fast path — if we have a cached QImage for the current
        # parameter set, blit it and skip the expensive drawPath +
        # gradient / selection-handle reconstruction. Cache is built
        # off-thread so this path ONLY hits after the worker completes.
        # Selected state + handles are always drawn live (below) since
        # they change frequently with selection toggles.
        cache_key = self._shape_render_params_tuple()
        fast_blit_ok = (
            self._cached_render is not None
            and self._cached_render_key == cache_key
            # Blit fast-path only works when the overlay has a normal
            # blend mode; composite modes still need the live path to
            # avoid cached-image blending artifacts.
            and (getattr(self.overlay, "blend_mode", "normal") or "normal")
                == "normal"
        )
        if fast_blit_ok:
            painter.save()
            painter.setOpacity(1.0)  # cache already has alpha baked in
            # Cache was rendered at (pad, pad) origin; translate scene
            # coords (overlay.x - pad, overlay.y - pad) to place it.
            pad = int(max(4,
                (getattr(self.overlay, "stroke_width", 0) or 0)) * 2)
            painter.drawImage(
                QPointF(self.overlay.x - pad, self.overlay.y - pad),
                self._cached_render)
            painter.restore()
            # Fall through to the live path's selection-handle drawing.
            # Skip the expensive drawPath by early-returning from the
            # shape dispatch below.
        elif self._cached_render_key != cache_key:
            # Cache miss — schedule a rebuild so the NEXT paint hits
            # the fast path. Current frame renders live.
            self._schedule_cached_render()
        r = QRectF(self.overlay.x, self.overlay.y,
                    self.overlay.shape_w, self.overlay.shape_h)
        # Apply the overlay's blend mode so shapes / bubbles can layer
        # on top of the base art like image overlays already do.
        mode = self._BLEND_MODE_MAP.get(
            getattr(self.overlay, "blend_mode", "normal"),
            QPainter.CompositionMode.CompositionMode_SourceOver)
        if mode != QPainter.CompositionMode.CompositionMode_SourceOver:
            painter.setCompositionMode(mode)
        stroke = QColor(self.overlay.stroke_color or self.overlay.color)
        stroke.setAlphaF(self.overlay.opacity)
        pen = QPen(stroke, max(1, self.overlay.stroke_width or 2))
        style = getattr(self.overlay, "line_style", "solid")
        if style == "dash":
            pen.setStyle(Qt.PenStyle.DashLine)
        elif style == "dot":
            pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        if self.overlay.fill_color:
            fill = QColor(self.overlay.fill_color)
            fill.setAlphaF(self.overlay.opacity)
            painter.setBrush(QBrush(fill))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        # Stroke alignment: Qt's default is 'center' (pen straddles the
        # edge). 'inside' shrinks the draw rect by half a stroke so the
        # stroke sits entirely inside the user-drawn bounds; 'outside'
        # grows it. Matches Illustrator / Photoshop semantics.
        _align = getattr(self.overlay, "stroke_align", "center")
        _sw = self.overlay.stroke_width or 0
        if _align == "inside" and _sw > 0:
            _half = _sw / 2.0
            r = r.adjusted(_half, _half, -_half, -_half)
        elif _align == "outside" and _sw > 0:
            _half = _sw / 2.0
            r = r.adjusted(-_half, -_half, _half, _half)
        kind = self.overlay.shape_kind
        if fast_blit_ok:
            # Already blitted from cache above. Skip the live shape
            # dispatch but let the selection-handle block below run.
            pass
        elif kind == "speech_bubble":
            self._paint_speech_bubble(painter, r)
        elif kind == "thought_bubble":
            self._paint_thought_bubble(painter, r)
        elif kind == "burst":
            self._paint_burst(painter, r)
        elif kind == "star":
            self._paint_star(painter, r)
        elif kind == "polygon":
            self._paint_polygon(painter, r)
        elif kind == "ellipse":
            painter.drawEllipse(r)
        elif kind in ("gradient_linear", "gradient_radial"):
            def _parse_hex(s, default):
                """Accept #RRGGBB or #RRGGBBAA hex strings."""
                s = s or default
                h = s.lstrip("#")
                if len(h) == 8:
                    return QColor(int(h[0:2], 16), int(h[2:4], 16),
                                   int(h[4:6], 16), int(h[6:8], 16))
                return QColor(s)
            c0 = _parse_hex(self.overlay.gradient_start_color, "#000000")
            c1 = _parse_hex(self.overlay.gradient_end_color, "#ffffff")
            # Multiply stored alpha by overall opacity
            c0.setAlphaF(c0.alphaF() * self.overlay.opacity)
            c1.setAlphaF(c1.alphaF() * self.overlay.opacity)
            if kind == "gradient_linear":
                ang = math.radians(self.overlay.gradient_angle)
                cx, cy = r.center().x(), r.center().y()
                half_w = r.width() / 2
                gx0 = cx - math.cos(ang) * half_w
                gy0 = cy - math.sin(ang) * half_w
                gx1 = cx + math.cos(ang) * half_w
                gy1 = cy + math.sin(ang) * half_w
                grad = QLinearGradient(gx0, gy0, gx1, gy1)
            else:
                grad = QRadialGradient(r.center(),
                                         max(r.width(), r.height()) / 2)
            grad.setColorAt(0.0, c0)
            grad.setColorAt(1.0, c1)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawRect(r)
        elif not fast_blit_ok:
            radius = getattr(self.overlay, "corner_radius", 0)
            if radius > 0:
                painter.drawRoundedRect(r, radius, radius)
            else:
                painter.drawRect(r)
        if self.isSelected():
            _dt = THEMES[DEFAULT_THEME]
            # Size constants for the selection gizmo (local — unused elsewhere)
            CORNER_HANDLE_HALF = 4
            ROTATE_CIRCLE_RADIUS = 6
            BUBBLE_TIP_RADIUS = 6
            CORNER_RADIUS_DIAMOND_HALF = 5
            STAR_HANDLE_RADIUS = 5
            POLYGON_HANDLE_RADIUS = 10
            GRADIENT_END_RADIUS = 6
            PEN_WIDTH = _dt.studio_overlay_handle_pen_width
            border_color = QColor(_dt.studio_overlay_handle_border)
            sel_color = QColor(_dt.studio_selection_outline)
            painter.setPen(QPen(sel_color, PEN_WIDTH, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            # Corner handles
            painter.setPen(QPen(border_color, PEN_WIDTH))
            painter.setBrush(QBrush(QColor(_dt.studio_selection_handle_fill)))
            for pt in self._handle_positions().values():
                painter.drawRect(QRectF(
                    pt.x() - CORNER_HANDLE_HALF, pt.y() - CORNER_HANDLE_HALF,
                    2 * CORNER_HANDLE_HALF, 2 * CORNER_HANDLE_HALF))
            # Rotate handle: small green circle + connector line above the
            # top-center edge. Drag to rotate; the Ctrl+R / R shortcuts
            # still work but this makes the affordance discoverable.
            rh = self._rotate_handle_pos()
            top_mid = QPointF(r.center().x(), r.top())
            painter.setPen(QPen(QColor(_dt.studio_rotate_connector),
                                PEN_WIDTH, Qt.PenStyle.DashLine))
            painter.drawLine(top_mid, rh)
            painter.setBrush(QBrush(QColor(_dt.studio_rotate_circle_fill)))
            painter.setPen(QPen(border_color, PEN_WIDTH))
            painter.drawEllipse(rh, ROTATE_CIRCLE_RADIUS, ROTATE_CIRCLE_RADIUS)
            # Tail tip handle for speech / thought bubbles: a cyan-outlined
            # circle at the tail point. Drag to move where the bubble points.
            if self._is_bubble():
                tip = self._tail_tip(r)
                painter.setPen(QPen(border_color, PEN_WIDTH))
                painter.setBrush(QBrush(QColor(_dt.studio_bubble_tail_handle)))
                painter.drawEllipse(tip, BUBBLE_TIP_RADIUS, BUBBLE_TIP_RADIUS)
            # Corner-radius handle for rect shapes: magenta diamond on
            # the top edge, offset by corner_radius px. Drag right =
            # larger radius, left = smaller. Discoverable visual
            # affordance without needing the Shape Controls popup.
            if self.overlay.shape_kind == "rect":
                crh = self._corner_radius_handle_pos()
                painter.setPen(QPen(border_color, PEN_WIDTH))
                painter.setBrush(QBrush(QColor(_dt.studio_corner_radius_handle)))
                d = CORNER_RADIUS_DIAMOND_HALF
                painter.drawPolygon(QPolygonF([
                    QPointF(crh.x(), crh.y() - d),
                    QPointF(crh.x() + d, crh.y()),
                    QPointF(crh.x(), crh.y() + d),
                    QPointF(crh.x() - d, crh.y()),
                ]))
            # Star inner-radius handle: teal dot on the north spoke at
            # distance inner_ratio * ry from center. Drag toward center
            # narrows the star; drag out widens to near-polygon.
            if self.overlay.shape_kind == "star":
                sh = self._star_inner_handle_pos()
                painter.setPen(QPen(border_color, PEN_WIDTH))
                painter.setBrush(QBrush(QColor(_dt.studio_star_inner_handle)))
                painter.drawEllipse(sh, STAR_HANDLE_RADIUS, STAR_HANDLE_RADIUS)
            # Polygon vertex-count handle: orange circle with the
            # current vertex count written inside.
            if self.overlay.shape_kind == "polygon":
                ph = self._polygon_vertex_handle_pos()
                painter.setPen(QPen(border_color, PEN_WIDTH))
                painter.setBrush(QBrush(QColor(_dt.studio_polygon_vertex_handle)))
                painter.drawEllipse(ph, POLYGON_HANDLE_RADIUS, POLYGON_HANDLE_RADIUS)
                painter.setPen(QPen(border_color, PEN_WIDTH))
                font = painter.font()
                font.setPixelSize(10)
                painter.setFont(font)
                txt = str(max(3, int(self.overlay.star_points or 6)))
                painter.drawText(
                    QRectF(ph.x() - POLYGON_HANDLE_RADIUS, ph.y() - 8,
                           2 * POLYGON_HANDLE_RADIUS, 16),
                    Qt.AlignmentFlag.AlignCenter, txt)
            # For linear gradients, also show a direction line + two circles
            # representing the gradient start / end.
            if self.overlay.shape_kind == "gradient_linear":
                ang = math.radians(self.overlay.gradient_angle)
                cx = self.overlay.x + self.overlay.shape_w / 2
                cy = self.overlay.y + self.overlay.shape_h / 2
                radius = min(self.overlay.shape_w, self.overlay.shape_h) / 2
                sx = cx - math.cos(ang) * radius
                sy = cy - math.sin(ang) * radius
                ex = cx + math.cos(ang) * radius
                ey = cy + math.sin(ang) * radius
                grad_marker = QColor(_dt.studio_bubble_tail_handle)
                painter.setPen(QPen(grad_marker, PEN_WIDTH, Qt.PenStyle.DashLine))
                painter.drawLine(int(sx), int(sy), int(ex), int(ey))
                painter.setBrush(QBrush(grad_marker))
                painter.setPen(QPen(border_color, PEN_WIDTH))
                painter.drawEllipse(QPointF(sx, sy), GRADIENT_END_RADIUS, GRADIENT_END_RADIUS)
                painter.drawEllipse(QPointF(ex, ey), GRADIENT_END_RADIUS, GRADIENT_END_RADIUS)

    def mousePressEvent(self, event):
        # Fresh drag baseline so the delta tracker in itemChange doesn't
        # carry a stale previous value into a new drag session.
        self._drag_prev_value = QPointF(0, 0)
        if self.isSelected():
            # Rotate handle wins over body/tail/resize - it sits outside
            # the bbox and must be checked first or the tail/corner
            # checks would miss it.
            if self._rotate_handle_under(event.scenePos()):
                self._dragging_handle = 'rotate'
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                event.accept()
                return
            # Tail handle wins when the shape is a bubble, so dragging the
            # tail tip never accidentally starts a body resize.
            if self._tail_handle_under(event.scenePos()):
                self._dragging_handle = 'tail'
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                event.accept()
                return
            # Corner-radius handle for rect shapes.
            if self._corner_radius_handle_under(event.scenePos()):
                self._dragging_handle = 'corner_radius'
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                event.accept()
                return
            # Star inner-radius handle.
            if self._star_inner_handle_under(event.scenePos()):
                self._dragging_handle = 'star_inner'
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                event.accept()
                return
            # Polygon vertex-count handle.
            if self._polygon_vertex_handle_under(event.scenePos()):
                self._dragging_handle = 'polygon_verts'
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                event.accept()
                return
            # Gradient direction handle wins over corner handles when the
            # shape is a linear gradient.
            if self.overlay.shape_kind == "gradient_linear":
                h = self._gradient_handle_under(event.scenePos())
                if h is not None:
                    self._dragging_handle = h  # 'grad_start' or 'grad_end'
                    self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                    event.accept()
                    return
            h = self._handle_under(event.scenePos())
            if h is not None:
                self._dragging_handle = h
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                event.accept()
                return
        super().mousePressEvent(event)

    def _gradient_handle_under(self, scene_pos: QPointF):
        """Return 'grad_start' / 'grad_end' if pos is near the gradient
        direction handles; None otherwise."""
        ang = math.radians(self.overlay.gradient_angle)
        cx = self.overlay.x + self.overlay.shape_w / 2
        cy = self.overlay.y + self.overlay.shape_h / 2
        radius = min(self.overlay.shape_w, self.overlay.shape_h) / 2
        sx = cx - math.cos(ang) * radius
        sy = cy - math.sin(ang) * radius
        ex = cx + math.cos(ang) * radius
        ey = cy + math.sin(ang) * radius
        r = 9
        if abs(scene_pos.x() - sx) <= r and abs(scene_pos.y() - sy) <= r:
            return 'grad_start'
        if abs(scene_pos.x() - ex) <= r and abs(scene_pos.y() - ey) <= r:
            return 'grad_end'
        return None

    def mouseMoveEvent(self, event):
        if self._dragging_handle == 'rotate':
            # Rotate around body center toward the cursor. Shift snaps
            # to 15° increments (InDesign convention).
            cx = self.overlay.x + self.overlay.shape_w / 2
            cy = self.overlay.y + self.overlay.shape_h / 2
            sp = event.scenePos()
            dx = sp.x() - cx
            dy = sp.y() - cy
            ang = math.degrees(math.atan2(dy, dx)) + 90  # 0 = up
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                ang = round(ang / 15) * 15
            self.overlay.rotation = int(ang) % 360
            self.setTransformOriginPoint(cx, cy)
            self.setRotation(self.overlay.rotation)
            self.update()
            if self._editor:
                self._editor.info_label.setText(
                    f"Rotation: {self.overlay.rotation}°")
            event.accept()
            return
        if self._dragging_handle == 'corner_radius':
            # Cursor X distance from the shape's left edge = new radius.
            sp = event.scenePos()
            new_r = max(0, min(
                int(sp.x() - self.overlay.x),
                self.overlay.shape_w // 2))
            self.overlay.corner_radius = new_r
            self.update()
            if self._editor:
                self._editor.info_label.setText(
                    f"Corner radius: {new_r}px")
            event.accept()
            return
        if self._dragging_handle == 'star_inner':
            # Distance from shape center as a fraction of ry = new
            # inner_ratio. Clamped to [0.1, 0.95].
            sp = event.scenePos()
            cy = self.overlay.y + self.overlay.shape_h / 2
            ry = max(1.0, self.overlay.shape_h / 2)
            frac = max(0.1, min(0.95, abs(cy - sp.y()) / ry))
            self.overlay.inner_ratio = float(frac)
            self.prepareGeometryChange()
            self.update()
            if self._editor:
                self._editor.info_label.setText(
                    f"Star inner radius: {frac * 100:.0f}%")
            event.accept()
            return
        if self._dragging_handle == 'polygon_verts':
            # Cursor X offset from center -> vertex count via a
            # quantized ramp (-2x .. +2x shape_w/2 maps to 3..20).
            sp = event.scenePos()
            cx = self.overlay.x + self.overlay.shape_w / 2
            dx = sp.x() - cx
            # Normalize so ~half-width reaches 20 verts, negative half
            # drops toward 3.
            frac = max(-1.0, min(1.0, dx / max(1.0, self.overlay.shape_w / 2)))
            verts = int(round(3 + (frac + 1) * 8.5))  # 3 .. 20
            verts = max(3, min(50, verts))
            if verts != int(self.overlay.star_points or 0):
                self.overlay.star_points = verts
                self.prepareGeometryChange()
                self.update()
                if self._editor:
                    self._editor.info_label.setText(
                        f"Polygon vertices: {verts}")
            event.accept()
            return
        if self._dragging_handle == 'tail':
            sp = event.scenePos()
            tx, ty = sp.x(), sp.y()
            # Shift snaps the tail to the exact N/E/S/W axis through
            # the body center so the tail reads as straight. Useful
            # for characters standing directly above / below / beside
            # a bubble (common comic composition).
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                cx = self.overlay.x + self.overlay.shape_w / 2
                cy = self.overlay.y + self.overlay.shape_h / 2
                dx, dy = tx - cx, ty - cy
                if abs(dx) > abs(dy):
                    ty = cy
                else:
                    tx = cx
            self.overlay.tail_x = int(tx)
            self.overlay.tail_y = int(ty)
            self.prepareGeometryChange()
            self.update()
            event.accept()
            return
        if self._dragging_handle in ('grad_start', 'grad_end'):
            # Drag updates the gradient angle, pivoting on the rect center
            cx = self.overlay.x + self.overlay.shape_w / 2
            cy = self.overlay.y + self.overlay.shape_h / 2
            sp = event.scenePos()
            dx = sp.x() - cx
            dy = sp.y() - cy
            ang = math.degrees(math.atan2(dy, dx))
            if self._dragging_handle == 'grad_start':
                ang = (ang + 180) % 360
            self.overlay.gradient_angle = int(ang)
            self.update()
            event.accept()
            return
        if self._dragging_handle is not None:
            sp = event.scenePos()
            x, y = self.overlay.x, self.overlay.y
            w, h = self.overlay.shape_w, self.overlay.shape_h
            # Alt-drag resizes around the center instead of anchoring the
            # opposite corner (Photoshop convention).
            alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            if alt:
                cx, cy = x + w / 2.0, y + h / 2.0
                if self._dragging_handle in ('tl', 'tr'):
                    half_h = max(2, cy - int(sp.y()))
                else:
                    half_h = max(2, int(sp.y()) - cy)
                if self._dragging_handle in ('tl', 'bl'):
                    half_w = max(2, cx - int(sp.x()))
                else:
                    half_w = max(2, int(sp.x()) - cx)
                w = int(2 * half_w)
                h = int(2 * half_h)
                x = int(cx - half_w)
                y = int(cy - half_h)
            else:
                if self._dragging_handle in ('tl', 'tr'):
                    new_y = int(sp.y())
                    h = max(4, (y + h) - new_y)
                    y = new_y
                if self._dragging_handle in ('bl', 'br'):
                    h = max(4, int(sp.y()) - y)
                if self._dragging_handle in ('tl', 'bl'):
                    new_x = int(sp.x())
                    w = max(4, (x + w) - new_x)
                    x = new_x
                if self._dragging_handle in ('tr', 'br'):
                    w = max(4, int(sp.x()) - x)
            # Shift constrains to square; keep dragged corner anchored
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                s = max(w, h)
                if self._dragging_handle == 'tl':
                    x = (x + w) - s
                    y = (y + h) - s
                elif self._dragging_handle == 'tr':
                    y = (y + h) - s
                elif self._dragging_handle == 'bl':
                    x = (x + w) - s
                w = h = s
            self.overlay.x = x
            self.overlay.y = y
            self.overlay.shape_w = w
            self.overlay.shape_h = h
            self.prepareGeometryChange()
            self.update()
            if self._editor is not None:
                self._editor.info_label.setText(f"Size: {w}x{h}")
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # Body-drag path: flush the accumulated delta reference so the
        # next drag starts from zero. Also sync the overlay state
        # through to the undo / save pipeline.
        self._drag_prev_value = QPointF(0, 0)
        if self._dragging_handle is not None:
            self._dragging_handle = None
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            if self._editor:
                self._editor._sync_overlays_to_asset()
            event.accept()
            return
        if self._editor:
            self._editor._sync_overlays_to_asset()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Bubbles: double-click drops the user into the linked text overlay
        # for immediate editing. Comic-book standard workflow.
        if self._is_bubble() and self.overlay.linked_text_id and self._editor:
            for it in self._editor._overlay_items:
                if (isinstance(it, OverlayTextItem)
                        and it.overlay.label == self.overlay.linked_text_id):
                    self._editor._scene.clearSelection()
                    it.setSelected(True)
                    it.setTextInteractionFlags(
                        Qt.TextInteractionFlag.TextEditorInteraction)
                    it.setFocus(Qt.FocusReason.MouseFocusReason)
                    # Put the cursor at the end so new keystrokes append.
                    cursor = it.textCursor()
                    cursor.movePosition(cursor.MoveOperation.End)
                    it.setTextCursor(cursor)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Feedback-loop fix: keep the item anchored at (0,0) so
            # painting (which uses absolute overlay.x/y) never gets
            # double-offset by Qt's transform. Apply only the incremental
            # delta since the last itemChange to overlay.x/y so repeated
            # mouseMoves don't cumulatively multiply the motion.
            prev = getattr(self, "_drag_prev_value", QPointF(0, 0))
            # Shift-lock drag axis: read modifiers live from
            # QApplication since itemChange isn't an event. Lock to the
            # axis with the larger cumulative delta from drag start.
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
                if abs(value.x()) > abs(value.y()):
                    value = QPointF(value.x(), 0)
                else:
                    value = QPointF(0, value.y())
            dx = int(value.x() - prev.x())
            dy = int(value.y() - prev.y())
            if dx or dy:
                self.overlay.x += dx
                self.overlay.y += dy
                # Drag the tail with the body so the pointer stays anchored
                if self.overlay.tail_x or self.overlay.tail_y:
                    self.overlay.tail_x += dx
                    self.overlay.tail_y += dy
                # Paired text overlay tracks the bubble. Cache the linked
                # text item reference so we don't scan _overlay_items
                # (O(N)) on every drag mousemove. Invalidate the cache
                # whenever the linked_text_id changes.
                linked_id = self.overlay.linked_text_id
                if linked_id and self._editor is not None:
                    cached = getattr(self, "_linked_text_cache", None)
                    cached_for = getattr(self, "_linked_text_cache_id", None)
                    if cached is None or cached_for != linked_id:
                        cached = None
                        for it in self._editor._overlay_items:
                            if (isinstance(it, OverlayTextItem)
                                    and it.overlay.label == linked_id):
                                cached = it
                                break
                        self._linked_text_cache = cached
                        self._linked_text_cache_id = linked_id
                    if cached is not None:
                        cached.overlay.x += dx
                        cached.overlay.y += dy
                        cached.setPos(cached.overlay.x, cached.overlay.y)
                self.prepareGeometryChange()
            self._drag_prev_value = value
            # Refuse the position change so Qt leaves the item at (0,0).
            return QPointF(0, 0)
        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        _parent = self._editor._view if self._editor else None
        menu = _themed_menu(_parent)
        is_gradient = self.overlay.shape_kind in ("gradient_linear", "gradient_radial")
        start_color_act = end_color_act = swap_colors_act = angle_act = None
        if is_gradient:
            start_color_act = menu.addAction("Gradient Start Color...")
            end_color_act = menu.addAction("Gradient End Color...")
            swap_colors_act = menu.addAction("Swap Gradient Colors")
            if self.overlay.shape_kind == "gradient_linear":
                angle_act = menu.addAction("Gradient Angle...")
            menu.addSeparator()
        stroke_act = menu.addAction("Stroke Color...")
        fill_act = menu.addAction("Fill Color...")
        clear_fill_act = menu.addAction("Clear Fill")
        save_default_act = menu.addAction("Save as Default Shape Style")
        reset_default_act = menu.addAction("Reset Default Shape Style")
        radius_act = menu.addAction("Corner Radius...")
        convert_menu = menu.addMenu("Convert To")
        conv_rect_act = convert_menu.addAction("Rectangle")
        conv_ellipse_act = convert_menu.addAction("Ellipse")
        conv_speech_act = convert_menu.addAction("Speech Bubble")
        conv_thought_act = convert_menu.addAction("Thought Bubble")
        conv_burst_act = convert_menu.addAction("Burst / Shout")
        conv_star_act = convert_menu.addAction("Star")
        conv_poly_act = convert_menu.addAction("Polygon")
        conv_lingrad_act = convert_menu.addAction("Linear Gradient")
        conv_radgrad_act = convert_menu.addAction("Radial Gradient")
        for a, k in ((conv_rect_act, "rect"),
                       (conv_ellipse_act, "ellipse"),
                       (conv_speech_act, "speech_bubble"),
                       (conv_thought_act, "thought_bubble"),
                       (conv_burst_act, "burst"),
                       (conv_star_act, "star"),
                       (conv_poly_act, "polygon"),
                       (conv_lingrad_act, "gradient_linear"),
                       (conv_radgrad_act, "gradient_radial")):
            a.setCheckable(True)
            a.setChecked(self.overlay.shape_kind == k)
        style_menu = menu.addMenu("Stroke Style")
        solid_act = style_menu.addAction("Solid")
        dash_act = style_menu.addAction("Dashed")
        dot_act = style_menu.addAction("Dotted")
        for a, s in ((solid_act, "solid"), (dash_act, "dash"), (dot_act, "dot")):
            a.setCheckable(True)
            a.setChecked(getattr(self.overlay, "line_style", "solid") == s)
        # Bubble-only actions, kept grouped so the menu reads as one
        # logical block for comic workflows.
        fit_text_act = None
        unlink_text_act = None
        preset_comic_act = None
        preset_manga_act = None
        preset_whisper_act = None
        preset_shout_act = None
        preset_narrator_act = None
        if self._is_bubble():
            menu.addSeparator()
            if self.overlay.linked_text_id:
                fit_text_act = menu.addAction("Fit Bubble to Text")
                unlink_text_act = menu.addAction("Unlink Text")
            preset_menu = menu.addMenu("Bubble Preset")
            preset_comic_act = preset_menu.addAction("Comic (solid)")
            preset_manga_act = preset_menu.addAction("Manga (thin)")
            preset_whisper_act = preset_menu.addAction("Whisper (dashed)")
            preset_shout_act = preset_menu.addAction("Shout (thick)")
            preset_narrator_act = preset_menu.addAction("Narrator box (no tail)")
        menu.addSeparator()
        select_same_fill_act = menu.addAction("Select All Same Fill")
        select_same_stroke_act = menu.addAction("Select All Same Stroke")
        menu.addSeparator()
        dup_act = menu.addAction("Duplicate  (Ctrl+D)")
        del_act = menu.addAction("Delete")
        chosen = menu.exec(event.screenPos())
        if chosen is start_color_act and self._editor:
            _s = self.overlay.gradient_start_color or "#000000"
            new = QColorDialog.getColor(
                QColor(_s), self._editor, "Gradient start color",
                QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if new.isValid():
                # Preserve alpha by encoding as #RRGGBBAA
                self.overlay.gradient_start_color = (
                    f"#{new.red():02x}{new.green():02x}"
                    f"{new.blue():02x}{new.alpha():02x}")
                self.update()
                self._editor._sync_overlays_to_asset()
                self._editor._add_recent_color(new.name())
            return
        if chosen is end_color_act and self._editor:
            _s = self.overlay.gradient_end_color or "#ffffff"
            new = QColorDialog.getColor(
                QColor(_s), self._editor, "Gradient end color",
                QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if new.isValid():
                self.overlay.gradient_end_color = (
                    f"#{new.red():02x}{new.green():02x}"
                    f"{new.blue():02x}{new.alpha():02x}")
                self.update()
                self._editor._sync_overlays_to_asset()
                self._editor._add_recent_color(new.name())
            return
        if chosen is swap_colors_act and self._editor:
            self.overlay.gradient_start_color, self.overlay.gradient_end_color = (
                self.overlay.gradient_end_color,
                self.overlay.gradient_start_color)
            self.update()
            self._editor._sync_overlays_to_asset()
            return
        if chosen is angle_act and self._editor:
            value, ok = QInputDialog.getInt(
                self._editor, "Gradient angle",
                "Angle (0 = horizontal, 90 = vertical):",
                value=self.overlay.gradient_angle, minValue=-360, maxValue=360)
            if ok:
                self.overlay.gradient_angle = value
                self.update()
                self._editor._sync_overlays_to_asset()
            return
        if chosen is stroke_act and self._editor:
            new = QColorDialog.getColor(
                QColor(self.overlay.stroke_color or self.overlay.color),
                self._editor, "Shape stroke color",
                QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if new.isValid():
                self.overlay.stroke_color = new.name()
                self.update()
                self._editor._sync_overlays_to_asset()
                QSettings("DoxyEdit", "DoxyEdit").setValue(
                    "studio_shape_stroke_color", new.name())
                self._editor._add_recent_color(new.name())
        elif chosen is fill_act and self._editor:
            new = QColorDialog.getColor(
                QColor(self.overlay.fill_color or "#ffffff"),
                self._editor, "Shape fill color",
                QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if new.isValid():
                self.overlay.fill_color = new.name()
                self.update()
                self._editor._sync_overlays_to_asset()
                QSettings("DoxyEdit", "DoxyEdit").setValue(
                    "studio_shape_fill_color", new.name())
                self._editor._add_recent_color(new.name())
        elif chosen is clear_fill_act and self._editor:
            self.overlay.fill_color = ""
            self.update()
            self._editor._sync_overlays_to_asset()
        elif chosen is save_default_act and self._editor:
            qs = QSettings("DoxyEdit", "DoxyEdit")
            qs.setValue("studio_shape_stroke_color",
                         self.overlay.stroke_color or self.overlay.color or "#ffd700")
            qs.setValue("studio_shape_fill_color", self.overlay.fill_color or "")
            qs.setValue("studio_shape_stroke_width", self.overlay.stroke_width or 2)
            qs.setValue("studio_shape_corner_radius",
                         getattr(self.overlay, "corner_radius", 0))
            qs.setValue("studio_shape_line_style",
                         getattr(self.overlay, "line_style", "solid"))
            self._editor.info_label.setText("Saved default shape style")
        elif chosen is reset_default_act and self._editor:
            qs = QSettings("DoxyEdit", "DoxyEdit")
            for k in ("studio_shape_stroke_color", "studio_shape_fill_color",
                       "studio_shape_stroke_width", "studio_shape_corner_radius",
                       "studio_shape_line_style"):
                qs.remove(k)
            self._editor.info_label.setText("Reset default shape style")
        elif chosen is radius_act and self._editor:
            value, ok = QInputDialog.getInt(
                self._editor, "Corner radius",
                "Radius (px, 0 = sharp corners):",
                value=max(0, getattr(self.overlay, "corner_radius", 0)),
                minValue=0, maxValue=500)
            if ok:
                self.overlay.corner_radius = value
                self.update()
                self._editor._sync_overlays_to_asset()
        elif chosen in (conv_rect_act, conv_ellipse_act, conv_star_act,
                         conv_poly_act, conv_lingrad_act, conv_radgrad_act
                         ) and self._editor:
            target = (
                "rect" if chosen is conv_rect_act else
                "ellipse" if chosen is conv_ellipse_act else
                "star" if chosen is conv_star_act else
                "polygon" if chosen is conv_poly_act else
                "gradient_linear" if chosen is conv_lingrad_act else
                "gradient_radial")
            self.overlay.shape_kind = target
            # Seed default gradient colors when converting into a gradient
            if target.startswith("gradient") and not self.overlay.gradient_start_color:
                self.overlay.gradient_start_color = "#000000ff"
                self.overlay.gradient_end_color = "#00000000"
            # Seed star / polygon vertex count if missing
            if target in ("star", "polygon"):
                if not getattr(self.overlay, "star_points", 0):
                    self.overlay.star_points = 5 if target == "star" else 6
                if target == "star" and not getattr(self.overlay, "inner_ratio", 0.0):
                    self.overlay.inner_ratio = 0.4
            self.prepareGeometryChange()
            self.update()
            self._editor._sync_overlays_to_asset()
            self._editor._rebuild_layer_panel()
        elif chosen in (solid_act, dash_act, dot_act):
            self.overlay.line_style = (
                "dash" if chosen is dash_act
                else "dot" if chosen is dot_act
                else "solid")
            self.update()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif fit_text_act is not None and chosen is fit_text_act and self._editor:
            self._fit_to_linked_text()
        elif unlink_text_act is not None and chosen is unlink_text_act and self._editor:
            self.overlay.linked_text_id = ""
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen in (preset_comic_act, preset_manga_act, preset_whisper_act,
                        preset_shout_act, preset_narrator_act):
            # Each preset is a small dict applied to the current bubble.
            # Tail_x/tail_y of 0 means 'no tail' (the paint path skips it
            # when tail coords are zero and the narrator preset leans on
            # that to render as a plain rounded rect).
            presets = {
                preset_comic_act: dict(
                    stroke_color="#000000", fill_color="#ffffff",
                    stroke_width=3, line_style="solid", corner_radius=0),
                preset_manga_act: dict(
                    stroke_color="#000000", fill_color="#ffffff",
                    stroke_width=2, line_style="solid", corner_radius=0),
                preset_whisper_act: dict(
                    stroke_color="#000000", fill_color="#ffffff",
                    stroke_width=2, line_style="dash", corner_radius=0),
                preset_shout_act: dict(
                    stroke_color="#000000", fill_color="#ffffff",
                    stroke_width=5, line_style="solid", corner_radius=0),
                preset_narrator_act: dict(
                    stroke_color="#000000", fill_color="#ffffeb",
                    stroke_width=3, line_style="solid",
                    # Rect draws without a tail (no speech_bubble paint
                    # path) so it renders as a plain narrator caption box
                    shape_kind="rect", corner_radius=6),
            }
            fields = presets.get(chosen, {})
            for k, v in fields.items():
                setattr(self.overlay, k, v)
            self.prepareGeometryChange()
            self.update()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is dup_act and self._editor:
            self._editor._duplicate_shape_item(self)
        elif chosen is select_same_fill_act and self._editor:
            target = self.overlay.fill_color or ""
            self._editor._scene.clearSelection()
            count = 0
            for it in self._editor._overlay_items:
                if isinstance(it, OverlayShapeItem):
                    if getattr(it.overlay, "fill_color", "") == target:
                        it.setSelected(True)
                        count += 1
            self._editor.info_label.setText(
                f"Selected {count} shape"
                f"{'s' if count != 1 else ''} with fill "
                f"{target or '(none)'}")
        elif chosen is select_same_stroke_act and self._editor:
            target = self.overlay.stroke_color or ""
            self._editor._scene.clearSelection()
            count = 0
            for it in self._editor._overlay_items:
                if isinstance(it, OverlayShapeItem):
                    if getattr(it.overlay, "stroke_color", "") == target:
                        it.setSelected(True)
                        count += 1
            self._editor.info_label.setText(
                f"Selected {count} shape"
                f"{'s' if count != 1 else ''} with stroke "
                f"{target or '(none)'}")
        elif chosen is del_act and self._editor:
            self._editor._remove_overlay_item(self)

    def _fit_to_linked_text(self):
        """Resize the bubble body so the linked text fits with padding.
        Keeps the bubble center fixed so the tail anchor point stays
        visually natural."""
        if not (self._editor and self.overlay.linked_text_id):
            return
        text_item = None
        for it in self._editor._overlay_items:
            if (isinstance(it, OverlayTextItem)
                    and it.overlay.label == self.overlay.linked_text_id):
                text_item = it
                break
        if text_item is None:
            return
        # Measure the text with its current font / width settings.
        tbr = text_item.sceneBoundingRect()
        pad_x = max(16, int(tbr.width() * 0.15))
        pad_y = max(12, int(tbr.height() * 0.25))
        new_w = int(tbr.width() + 2 * pad_x)
        new_h = int(tbr.height() + 2 * pad_y)
        # Pivot around the current body center
        cx = self.overlay.x + self.overlay.shape_w / 2.0
        cy = self.overlay.y + self.overlay.shape_h / 2.0
        self.overlay.x = int(cx - new_w / 2)
        self.overlay.y = int(cy - new_h / 2)
        self.overlay.shape_w = new_w
        self.overlay.shape_h = new_h
        # Recenter the text inside the resized body.
        text_item.overlay.x = int(cx - tbr.width() / 2)
        text_item.overlay.y = int(cy - tbr.height() / 2)
        text_item.setPos(text_item.overlay.x, text_item.overlay.y)
        self.prepareGeometryChange()
        self.update()
        self._editor._sync_overlays_to_asset()


class OverlayArrowItem(QGraphicsItem):
    """Non-destructive arrow overlay: straight line with arrowhead at end.

    Stores its endpoints on the backing CanvasOverlay (x, y = tail,
    end_x, end_y = tip) so positions persist with the project file.
    Paint is deferred to produce a clean triangular arrowhead.
    """

    HANDLE_HIT_RADIUS = 10  # scene-px around each endpoint for handle hits

    def __init__(self, overlay: "CanvasOverlay", parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self._editor = None
        self._dragging_endpoint = None  # 'start', 'end', or None
        self.setZValue(200)

    def hoverMoveEvent(self, event):
        if self.isSelected():
            ep = self._endpoint_under(event.scenePos())
            if ep is not None:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def boundingRect(self) -> QRectF:
        x1, y1 = self.overlay.x, self.overlay.y
        x2, y2 = self.overlay.end_x, self.overlay.end_y
        hs = max(self.overlay.arrowhead_size, 6)
        r = QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized()
        return r.adjusted(-hs, -hs, hs, hs)

    def paint(self, painter, option, widget=None):
        x1, y1 = self.overlay.x, self.overlay.y
        x2, y2 = self.overlay.end_x, self.overlay.end_y
        color = QColor(self.overlay.color)
        color.setAlphaF(self.overlay.opacity)
        pen = QPen(color, max(1, self.overlay.stroke_width or 4))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        style = getattr(self.overlay, "line_style", "solid")
        if style == "dash":
            pen.setStyle(Qt.PenStyle.DashLine)
        elif style == "dot":
            pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(int(x1), int(y1), int(x2), int(y2))
        # Arrowhead — equilateral triangle at tip
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1:
            return
        head_style = getattr(self.overlay, "arrowhead_style", "filled")
        if head_style != "none":
            ux, uy = dx / length, dy / length  # unit vector along line
            hs = max(self.overlay.arrowhead_size, 6)
            # Perpendicular vector
            px, py = -uy, ux

            def _head(tip_x, tip_y, direction):
                base_x = tip_x - direction * ux * hs
                base_y = tip_y - direction * uy * hs
                p1 = QPointF(base_x + px * hs * 0.5, base_y + py * hs * 0.5)
                p2 = QPointF(base_x - px * hs * 0.5, base_y - py * hs * 0.5)
                path = QPainterPath()
                path.moveTo(tip_x, tip_y)
                path.lineTo(p1)
                path.lineTo(p2)
                path.closeSubpath()
                if head_style == "outline":
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(color, max(1, self.overlay.stroke_width or 2)))
                else:
                    painter.setBrush(QBrush(color))
                    painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPath(path)

            _head(x2, y2, 1)
            if getattr(self.overlay, "double_headed", False):
                _head(x1, y1, -1)
        # Selection highlight + endpoint handles
        if self.isSelected():
            _dt = THEMES[DEFAULT_THEME]
            ENDPOINT_RADIUS = 5
            sel_color = QColor(_dt.studio_selection_outline)
            painter.setPen(QPen(sel_color, _dt.studio_overlay_handle_pen_width,
                                Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(_dt.studio_selection_handle_fill)))
            painter.drawEllipse(QRectF(x1 - ENDPOINT_RADIUS, y1 - ENDPOINT_RADIUS,
                                        2 * ENDPOINT_RADIUS, 2 * ENDPOINT_RADIUS))
            painter.drawEllipse(QRectF(x2 - ENDPOINT_RADIUS, y2 - ENDPOINT_RADIUS,
                                        2 * ENDPOINT_RADIUS, 2 * ENDPOINT_RADIUS))

    def _endpoint_under(self, scene_pos: QPointF):
        """Return 'start' / 'end' / None if pos is near an endpoint."""
        r = self.HANDLE_HIT_RADIUS
        x1, y1 = self.overlay.x, self.overlay.y
        x2, y2 = self.overlay.end_x, self.overlay.end_y
        sx, sy = scene_pos.x(), scene_pos.y()
        if abs(sx - x1) <= r and abs(sy - y1) <= r:
            return 'start'
        if abs(sx - x2) <= r and abs(sy - y2) <= r:
            return 'end'
        return None

    def mousePressEvent(self, event):
        # Endpoint drag overrides body drag
        self._drag_prev_value = QPointF(0, 0)
        ep = self._endpoint_under(event.scenePos())
        if ep and self.isSelected():
            self._dragging_endpoint = ep
            # Disable ItemIsMovable while dragging an endpoint so the base
            # class doesn't move the whole item.
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_endpoint:
            sp = event.scenePos()
            if self._dragging_endpoint == 'start':
                self.overlay.x = int(sp.x())
                self.overlay.y = int(sp.y())
            else:
                self.overlay.end_x = int(sp.x())
                self.overlay.end_y = int(sp.y())
            self.prepareGeometryChange()
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_prev_value = QPointF(0, 0)
        if self._dragging_endpoint:
            self._dragging_endpoint = None
            # Restore ItemIsMovable and sync to the model
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            if self._editor:
                self._editor._sync_overlays_to_asset()
            event.accept()
            return
        if self._editor:
            self._editor._sync_overlays_to_asset()
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Same fix as OverlayShapeItem: refuse Qt's position change
            # and apply only the incremental delta to overlay endpoints,
            # so repeated ItemPositionChange deliveries during a single
            # drag don't multiply the motion (cumulative pressPos bug).
            prev = getattr(self, "_drag_prev_value", QPointF(0, 0))
            dx = int(value.x() - prev.x())
            dy = int(value.y() - prev.y())
            if dx or dy:
                self.overlay.x += dx
                self.overlay.y += dy
                self.overlay.end_x += dx
                self.overlay.end_y += dy
                self.prepareGeometryChange()
            self._drag_prev_value = value
            return QPointF(0, 0)
        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        _parent = self._editor._view if self._editor else None
        menu = _themed_menu(_parent)
        color_act = menu.addAction("Change Color...")
        style_menu = menu.addMenu("Line Style")
        solid_act = style_menu.addAction("Solid")
        dash_act = style_menu.addAction("Dashed")
        dot_act = style_menu.addAction("Dotted")
        for a, s in ((solid_act, "solid"), (dash_act, "dash"), (dot_act, "dot")):
            a.setCheckable(True)
            a.setChecked(getattr(self.overlay, "line_style", "solid") == s)
        head_menu = menu.addMenu("Arrow Head")
        head_filled_act = head_menu.addAction("Filled")
        head_outline_act = head_menu.addAction("Outline")
        head_none_act = head_menu.addAction("None (line only)")
        for a, s in ((head_filled_act, "filled"),
                      (head_outline_act, "outline"),
                      (head_none_act, "none")):
            a.setCheckable(True)
            a.setChecked(getattr(self.overlay, "arrowhead_style", "filled") == s)
        double_head_act = menu.addAction("Double-Headed")
        double_head_act.setCheckable(True)
        double_head_act.setChecked(bool(getattr(self.overlay, "double_headed", False)))
        flip_dir_act = menu.addAction("Flip Direction")
        straighten_act = menu.addAction("Straighten (snap to 15°)")
        select_all_arrows_act = menu.addAction("Select All Arrows")
        dup_act = menu.addAction("Duplicate  (Ctrl+D)")
        menu.addSeparator()
        copy_style_act = menu.addAction("Copy Style")
        paste_style_act = menu.addAction("Paste Style")
        menu.addSeparator()
        del_act = menu.addAction("Delete")
        chosen = menu.exec(event.screenPos())
        if chosen is color_act and self._editor:
            new = QColorDialog.getColor(
                QColor(self.overlay.color), self._editor,
                "Arrow color",
                QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if new.isValid():
                self.overlay.color = new.name()
                self.update()
                self._editor._sync_overlays_to_asset()
                # Remember this color for the next new arrow
                QSettings("DoxyEdit", "DoxyEdit").setValue(
                    "studio_arrow_color", new.name())
                self._editor._add_recent_color(new.name())
        elif chosen is dup_act and self._editor:
            self._editor._duplicate_arrow_item(self)
        elif chosen in (solid_act, dash_act, dot_act):
            self.overlay.line_style = (
                "dash" if chosen is dash_act
                else "dot" if chosen is dot_act
                else "solid")
            self.update()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen in (head_filled_act, head_outline_act, head_none_act):
            self.overlay.arrowhead_style = (
                "outline" if chosen is head_outline_act
                else "none" if chosen is head_none_act
                else "filled")
            self.update()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is double_head_act:
            self.overlay.double_headed = not getattr(
                self.overlay, "double_headed", False)
            self.update()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is flip_dir_act:
            # Swap arrow tail <-> tip so the point reverses without
            # moving the overall line position. Mirrors the Shape
            # Controls 'Flip arrow direction' button.
            self.overlay.x, self.overlay.end_x = (
                self.overlay.end_x, self.overlay.x)
            self.overlay.y, self.overlay.end_y = (
                self.overlay.end_y, self.overlay.y)
            self.prepareGeometryChange()
            self.update()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is straighten_act:
            # Snap the arrow's angle to the nearest 15°, preserving
            # length and tail anchor. Same math as the Shape Controls
            # button so the two stay in sync.
            ov_a = self.overlay
            dx = ov_a.end_x - ov_a.x
            dy = ov_a.end_y - ov_a.y
            length = math.hypot(dx, dy)
            if length >= 1:
                angle = math.degrees(math.atan2(dy, dx))
                snapped = round(angle / 15.0) * 15.0
                rad = math.radians(snapped)
                ov_a.end_x = int(round(ov_a.x + length * math.cos(rad)))
                ov_a.end_y = int(round(ov_a.y + length * math.sin(rad)))
                self.prepareGeometryChange()
                self.update()
                if self._editor:
                    self._editor._sync_overlays_to_asset()
                    self._editor.info_label.setText(
                        f"Arrow straightened to {int(snapped)}°")
        elif chosen is select_all_arrows_act and self._editor:
            # Select all arrow overlays at once for batch styling.
            self._editor._scene.clearSelection()
            for it in self._editor._overlay_items:
                if isinstance(it, OverlayArrowItem):
                    it.setSelected(True)
        elif chosen is copy_style_act and self._editor:
            self._editor._copy_style(self.overlay)
        elif chosen is paste_style_act and self._editor:
            self._editor._paste_style(self.overlay, self)
        elif chosen is del_act and self._editor:
            self._editor._remove_overlay_item(self)


class OverlayTextItem(QGraphicsTextItem):
    """Movable, double-click editable text overlay — syncs to CanvasOverlay."""

    def __init__(self, overlay: CanvasOverlay):
        super().__init__(overlay.text or "Your text")
        self.overlay = overlay
        self._editor = None  # set by StudioEditor after creation
        self.setFlags(
            QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsTextItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        # Cache rendered glyphs so drag doesn't re-rasterize the text
        # (shadow + outline passes + main glyph pass per move event).
        self.setCacheMode(
            QGraphicsTextItem.CacheMode.DeviceCoordinateCache)
        self._apply_font()
        self.setOpacity(overlay.opacity)
        self.setPos(overlay.x, overlay.y)
        if (getattr(overlay, "flip_h", False) or getattr(overlay, "flip_v", False)
                or overlay.rotation):
            self._apply_flip_text()
        if getattr(overlay, "locked", False):
            self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable, False)
            self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable, False)

    def _apply_font(self):
        font = QFont(self.overlay.font_family, self.overlay.font_size)
        if self.overlay.bold:
            font.setBold(True)
        if self.overlay.italic:
            font.setItalic(True)
        if getattr(self.overlay, "underline", False):
            font.setUnderline(True)
        if getattr(self.overlay, "strikethrough", False):
            font.setStrikeOut(True)
        if self.overlay.letter_spacing:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, self.overlay.letter_spacing)
        self.setFont(font)
        # Horizontal alignment via document option
        align_map = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
        }
        opt = QTextOption(align_map.get(
            getattr(self.overlay, "text_align", "left"),
            Qt.AlignmentFlag.AlignLeft))
        self.document().setDefaultTextOption(opt)
        self.setDefaultTextColor(QColor(self.overlay.color))
        if self.overlay.text_width > 0:
            self.setTextWidth(self.overlay.text_width)
        else:
            self.setTextWidth(-1)
        # Line height via block format
        lh = self.overlay.line_height or 1.2
        fmt = QTextBlockFormat()
        fmt.setLineHeight(lh * 100, 1)  # 1 = ProportionalHeight (percentage)
        # Add bottom margin to prevent last line from being clipped
        fmt.setBottomMargin(self.overlay.font_size * 0.3)
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeBlockFormat(fmt)
        self.setTextCursor(cursor)
        # Force document layout to recalculate size after line height change
        doc = self.document()
        doc.adjustSize()
        doc.setTextWidth(doc.idealWidth() if self.overlay.text_width <= 0 else self.overlay.text_width)
        # Rotate from center of bounding rect
        self.prepareGeometryChange()
        br = self.boundingRect()
        self.setTransformOriginPoint(br.center())
        self.setRotation(self.overlay.rotation)

    _BLEND_MODE_MAP = {
        "normal": QPainter.CompositionMode.CompositionMode_SourceOver,
        "multiply": QPainter.CompositionMode.CompositionMode_Multiply,
        "screen": QPainter.CompositionMode.CompositionMode_Screen,
        "overlay": QPainter.CompositionMode.CompositionMode_Overlay,
        "darken": QPainter.CompositionMode.CompositionMode_Darken,
        "lighten": QPainter.CompositionMode.CompositionMode_Lighten,
    }

    def _draw_document(self, painter, color: QColor):
        """Draw the text document directly with an override color.

        Using QAbstractTextDocumentLayout.draw() with a paint context lets
        us color the glyphs without mutating the item's defaultTextColor
        (which, if changed inside paint(), triggers a relayout and causes
        jitter on every frame during drag).
        """
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(QPalette.ColorRole.Text, color)
        self.document().documentLayout().draw(painter, ctx)

    def paint(self, painter, option, widget=None):
        mode = self._BLEND_MODE_MAP.get(
            getattr(self.overlay, "blend_mode", "normal"),
            QPainter.CompositionMode.CompositionMode_SourceOver)
        if mode != QPainter.CompositionMode.CompositionMode_SourceOver:
            painter.setCompositionMode(mode)
        # Optional background fill behind the text (sticker/callout effect)
        bg = getattr(self.overlay, "background_color", "")
        if bg:
            bg_color = QColor(bg)
            if bg_color.isValid():
                _pad = max(4, int(self.overlay.font_size * 0.2))
                br = self.boundingRect().adjusted(-_pad, -_pad, _pad, _pad)
                painter.save()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(bg_color)
                painter.drawRoundedRect(br, _pad, _pad)
                painter.restore()
        # Drop shadow: draw the document layout at offset in shadow color.
        # Never call setDefaultTextColor here - it relayouts the doc and
        # causes visible jitter while dragging.
        if self.overlay.shadow_color and self.overlay.shadow_offset:
            painter.save()
            off = self.overlay.shadow_offset
            painter.translate(off, off)
            self._draw_document(painter, QColor(self.overlay.shadow_color))
            painter.restore()
        # Text outline via 8-directional offset passes.
        if self.overlay.stroke_width > 0 and self.overlay.stroke_color:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            stroke_w = self.overlay.stroke_width
            stroke_c = QColor(self.overlay.stroke_color)
            for dx in (-stroke_w, 0, stroke_w):
                for dy in (-stroke_w, 0, stroke_w):
                    if dx == 0 and dy == 0:
                        continue
                    painter.save()
                    painter.translate(dx, dy)
                    self._draw_document(painter, stroke_c)
                    painter.restore()
            painter.restore()
        super().paint(painter, option, widget)

    def itemChange(self, change, value):
        if change == QGraphicsTextItem.GraphicsItemChange.ItemPositionHasChanged:
            self.overlay.x = int(value.x())
            self.overlay.y = int(value.y())
            self.overlay.position = "custom"
        return super().itemChange(change, value)

    def _apply_flip_text(self):
        """Apply flip_h/flip_v to a text item via negative QTransform scale."""
        self.setTransformOriginPoint(self.boundingRect().center())
        sx = -1.0 if getattr(self.overlay, "flip_h", False) else 1.0
        sy = -1.0 if getattr(self.overlay, "flip_v", False) else 1.0
        t = QTransform()
        t.scale(sx, sy)
        self.setTransform(t)
        self.setRotation(self.overlay.rotation)

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        super().mouseDoubleClickEvent(event)

    def sceneEvent(self, event):
        """Intercept ALL events before Qt's internal text control sees them."""
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            cursor = self.textCursor()
            cursor.clearSelection()
            self.setTextCursor(cursor)
            self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            self.overlay.text = self.toPlainText()
            self.clearFocus()
            if self._editor:
                self._editor._clear_escape_state()
            event.accept()
            return True  # consumed — Qt text control never sees it
        return super().sceneEvent(event)

    def focusOutEvent(self, event):
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.overlay.text = self.toPlainText()
        # If this text is the payload of a speech/thought bubble AND the
        # user has opted into auto-fit (studio_bubble_autofit setting,
        # default True), resize the bubble to wrap the new text. Keeps
        # comic pages tidy without a manual right-click.
        if self._editor is not None and self.overlay.label:
            autofit = QSettings("DoxyEdit", "DoxyEdit").value(
                "studio_bubble_autofit", True, type=bool)
            if autofit:
                for bubble_item in self._editor._overlay_items:
                    if (isinstance(bubble_item, OverlayShapeItem)
                            and bubble_item.overlay.linked_text_id
                                == self.overlay.label):
                        bubble_item._fit_to_linked_text()
                        break
        super().focusOutEvent(event)

    def contextMenuEvent(self, event):
        _parent = self._editor._view if self._editor else None
        menu = _themed_menu(_parent)
        edit_act = menu.addAction("Edit Text")
        color_act = menu.addAction("Change Color...")
        bg_act = menu.addAction("Change Background...")
        clear_bg_act = menu.addAction("Clear Background")
        underline_act = menu.addAction("Underline")
        underline_act.setCheckable(True)
        underline_act.setChecked(bool(getattr(self.overlay, "underline", False)))
        strike_act = menu.addAction("Strikethrough")
        strike_act.setCheckable(True)
        strike_act.setChecked(bool(getattr(self.overlay, "strikethrough", False)))
        align_menu = menu.addMenu("Align Text")
        align_left_act = align_menu.addAction("Left")
        align_center_act = align_menu.addAction("Center")
        align_right_act = align_menu.addAction("Right")
        cur_align = getattr(self.overlay, "text_align", "left")
        for a, v in ((align_left_act, "left"),
                     (align_center_act, "center"),
                     (align_right_act, "right")):
            a.setCheckable(True)
            a.setChecked(cur_align == v)
        shadow_menu = menu.addMenu("Drop Shadow")
        shadow_on = bool(self.overlay.shadow_color and self.overlay.shadow_offset)
        shadow_toggle_act = shadow_menu.addAction(
            "Disable Shadow" if shadow_on else "Enable Shadow (soft black)")
        shadow_color_act = shadow_menu.addAction("Shadow Color...")
        shadow_stronger_act = shadow_menu.addAction("Shadow Stronger")
        shadow_softer_act = shadow_menu.addAction("Shadow Softer")
        select_same_act = menu.addAction("Select All Text Overlays")
        apply_to_all_act = menu.addAction("Apply This Style to All Text")
        find_replace_act = menu.addAction("Find and Replace Text...")
        save_style_act = menu.addAction("Save as Default Text Style")
        reset_style_act = menu.addAction("Reset Default Text Style")
        copy_style_act = menu.addAction("Copy Style")
        paste_style_act = menu.addAction("Paste Style")
        menu.addSeparator()
        dup_act = menu.addAction("Duplicate  (Ctrl+D)")
        menu.addSeparator()
        flip_h_act = menu.addAction("Flip Horizontal  (Ctrl+Shift+H)")
        flip_v_act = menu.addAction("Flip Vertical  (Ctrl+Shift+V)")
        rot_cw_act = menu.addAction("Rotate 90° CW")
        rot_ccw_act = menu.addAction("Rotate 90° CCW")
        rot_180_act = menu.addAction("Rotate 180°")
        reset_xform_act = menu.addAction("Reset Transform")
        menu.addSeparator()
        front_act = menu.addAction("Bring to Front  (Ctrl+Shift+])")
        fwd_act = menu.addAction("Bring Forward  (Ctrl+])")
        bwd_act = menu.addAction("Send Backward  (Ctrl+[)")
        back_act = menu.addAction("Send to Back  (Ctrl+Shift+[)")
        menu.addSeparator()
        plat_sub = all_act = plat_actions = None
        if self._editor and self._editor._project:
            plat_sub, all_act, plat_actions = _add_platform_submenu(menu, self.overlay.platforms, self._editor)
            menu.addSeparator()
        del_act = menu.addAction("Delete")

        chosen = menu.exec(event.screenPos())
        if not chosen:
            return
        if chosen is edit_act:
            self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
            self.setFocus()
        elif chosen is color_act and self._editor:
            self._editor._pick_text_color(self)
        elif chosen is bg_act and self._editor:
            self._editor._pick_text_background(self)
        elif chosen is clear_bg_act and self._editor:
            self._editor._push_overlay_attr(
                self, "background_color", "",
                apply_cb=lambda it, _v: it.update(),
                description="Clear text background",
            )
            self._editor._sync_overlays_to_asset()
        elif chosen in (align_left_act, align_center_act, align_right_act) and self._editor:
            tgt = (
                "left" if chosen is align_left_act else
                "center" if chosen is align_center_act else "right")
            self._editor._push_overlay_attr(
                self, "text_align", tgt,
                apply_cb=lambda it, _v: it._apply_font(),
                description="Text alignment")
            self._editor._sync_overlays_to_asset()
        elif chosen is underline_act and self._editor:
            self._editor._push_overlay_attr(
                self, "underline", not getattr(self.overlay, "underline", False),
                apply_cb=lambda it, _v: it._apply_font(),
                description="Toggle underline")
            self._editor._sync_overlays_to_asset()
        elif chosen is strike_act and self._editor:
            self._editor._push_overlay_attr(
                self, "strikethrough",
                not getattr(self.overlay, "strikethrough", False),
                apply_cb=lambda it, _v: it._apply_font(),
                description="Toggle strikethrough")
            self._editor._sync_overlays_to_asset()
        elif chosen is shadow_toggle_act and self._editor:
            if shadow_on:
                for attr, val in (("shadow_color", ""),
                                   ("shadow_offset", 0),
                                   ("shadow_blur", 0)):
                    self._editor._push_overlay_attr(
                        self, attr, val,
                        apply_cb=lambda it, _v: it.update(),
                        description="Disable text shadow")
            else:
                for attr, val in (("shadow_color", "#000000"),
                                   ("shadow_offset", 3),
                                   ("shadow_blur", 3)):
                    self._editor._push_overlay_attr(
                        self, attr, val,
                        apply_cb=lambda it, _v: it.update(),
                        description="Enable text shadow")
            self._editor._sync_overlays_to_asset()
        elif chosen is shadow_color_act and self._editor:
            initial = QColor(self.overlay.shadow_color or "#000000")
            new = QColorDialog.getColor(
                initial, self._editor, "Text shadow color",
                QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if new.isValid():
                self._editor._push_overlay_attr(
                    self, "shadow_color", new.name(),
                    apply_cb=lambda it, _v: it.update(),
                    description="Change shadow color")
                self._editor._sync_overlays_to_asset()
        elif chosen is shadow_stronger_act and self._editor:
            self._editor._push_overlay_attr(
                self, "shadow_offset", self.overlay.shadow_offset + 2,
                apply_cb=lambda it, _v: it.update(),
                description="Stronger shadow")
            self._editor._push_overlay_attr(
                self, "shadow_blur", self.overlay.shadow_blur + 2,
                apply_cb=lambda it, _v: it.update(),
                description="Stronger shadow")
            if not self.overlay.shadow_color:
                self._editor._push_overlay_attr(
                    self, "shadow_color", "#000000",
                    apply_cb=lambda it, _v: it.update(),
                    description="Shadow color")
            self._editor._sync_overlays_to_asset()
        elif chosen is shadow_softer_act and self._editor:
            self._editor._push_overlay_attr(
                self, "shadow_offset", max(0, self.overlay.shadow_offset - 2),
                apply_cb=lambda it, _v: it.update(),
                description="Softer shadow")
            self._editor._push_overlay_attr(
                self, "shadow_blur", max(0, self.overlay.shadow_blur - 2),
                apply_cb=lambda it, _v: it.update(),
                description="Softer shadow")
            self._editor._sync_overlays_to_asset()
        elif chosen is select_same_act and self._editor:
            self._editor._scene.clearSelection()
            for it in self._editor._overlay_items:
                if isinstance(it, OverlayTextItem):
                    it.setSelected(True)
        elif chosen is apply_to_all_act and self._editor:
            self._editor._apply_text_style_to_all(self.overlay)
        elif chosen is find_replace_act and self._editor:
            self._editor._find_replace_text()
        elif chosen is save_style_act and self._editor:
            self._editor._save_text_style_as_default(self.overlay)
        elif chosen is reset_style_act and self._editor:
            self._editor._reset_text_style_defaults()
        elif chosen is copy_style_act and self._editor:
            self._editor._copy_style(self.overlay)
        elif chosen is paste_style_act and self._editor:
            self._editor._paste_style(self.overlay, self)
        elif chosen is dup_act and self._editor:
            self._editor._duplicate_overlay_item(self)
        elif chosen is flip_h_act:
            self.overlay.flip_h = not getattr(self.overlay, "flip_h", False)
            self._apply_flip_text()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is flip_v_act:
            self.overlay.flip_v = not getattr(self.overlay, "flip_v", False)
            self._apply_flip_text()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is reset_xform_act:
            self.overlay.rotation = 0.0
            self.overlay.flip_h = False
            self.overlay.flip_v = False
            self.setTransform(QTransform())
            self.setRotation(0)
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is rot_cw_act:
            self.overlay.rotation = (self.overlay.rotation + 90) % 360
            self._apply_flip_text()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is rot_ccw_act:
            self.overlay.rotation = (self.overlay.rotation - 90) % 360
            self._apply_flip_text()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif chosen is rot_180_act:
            self.overlay.rotation = (self.overlay.rotation + 180) % 360
            self._apply_flip_text()
            if self._editor:
                self._editor._sync_overlays_to_asset()
        elif plat_actions and (chosen is all_act or chosen in plat_actions):
            new_plats = _resolve_platform_menu(chosen, all_act, plat_actions, self.overlay.platforms)
            if self._editor:
                cmd = SetAttrCmd(
                    self.overlay, "platforms", list(self.overlay.platforms), new_plats,
                    apply_cb=lambda _t, _v: self._editor._refresh_layer_panel(),
                    description="Change platforms",
                )
                self._editor._undo_stack.push(cmd)
                self._editor._sync_overlays_to_asset()
            else:
                self.overlay.platforms = new_plats
        elif chosen is fwd_act:
            if self._editor:
                cmd = SetZValueCmd(self, self.zValue(), self.zValue() + 1, "Bring forward")
                self._editor._undo_stack.push(cmd)
            else:
                self.setZValue(self.zValue() + 1)
        elif chosen is front_act:
            new_z = self.zValue() + 999
            if self._editor:
                cmd = SetZValueCmd(self, self.zValue(), new_z, "Bring to front")
                self._editor._undo_stack.push(cmd)
            else:
                self.setZValue(new_z)
        elif chosen is back_act:
            if self._editor:
                cmd = SetZValueCmd(self, self.zValue(), 200, "Send to back")
                self._editor._undo_stack.push(cmd)
            else:
                self.setZValue(200)
        elif chosen is bwd_act:
            new_z = max(200, self.zValue() - 1)
            if self._editor:
                cmd = SetZValueCmd(self, self.zValue(), new_z, "Send backward")
                self._editor._undo_stack.push(cmd)
            else:
                self.setZValue(new_z)
        elif chosen is del_act and self._editor:
            self._editor._remove_overlay_item(self)


# ── Scene-item type tuples (for isinstance checks) ────────────────
# Defined once the four Overlay* classes are loaded. NoteRectItem and
# ResizableCropItem come from doxyedit.preview (imported at top).
_OVERLAY_ITEM_TYPES = (
    OverlayImageItem, OverlayTextItem, OverlayArrowItem, OverlayShapeItem,
)
_SELECTABLE_ITEM_TYPES = _OVERLAY_ITEM_TYPES + (CensorRectItem,)
_CANVAS_ITEM_TYPES = _SELECTABLE_ITEM_TYPES + (ResizableCropItem, NoteRectItem)


class AnnotationTextItem(QGraphicsTextItem):
    """Ephemeral text annotation — no model reference, lost on asset change."""

    def __init__(self, text: str = "Double-click to edit"):
        super().__init__(text)
        self.setFlags(
            QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable
        )
        _dt = THEMES[DEFAULT_THEME]
        self.setFont(QFont(_dt.font_family, _dt.font_size))
        self.setDefaultTextColor(QColor(_dt.text_primary))

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        super().focusOutEvent(event)


# ---------------------------------------------------------------------------
# Undo commands
# ---------------------------------------------------------------------------

class AddCensorCmd(QUndoCommand):
    def __init__(self, editor, censor_region, scene_item):
        super().__init__("Add Censor")
        self._editor = editor
        self._region = censor_region
        self._item = scene_item

    def redo(self):
        if self._region not in self._editor._asset.censors:
            self._editor._asset.censors.append(self._region)
        if self._item.scene() is None:
            self._editor._scene.addItem(self._item)

    def undo(self):
        if self._region in self._editor._asset.censors:
            self._editor._asset.censors.remove(self._region)
        if self._item.scene() is not None:
            self._editor._scene.removeItem(self._item)


class SetAttrCmd(QUndoCommand):
    """Generic undo command for `target.attr = value` mutations.

    After writing the new value, calls `apply_cb(target, new)` if provided
    so the scene item repaints, the overlay item re-transforms, etc.

    Supports merge-with-previous so that dragging a slider doesn't stack
    50 commands — consecutive SetAttrCmd on the same (target, attr) pair
    collapse into one.
    """

    _next_id = 1

    def __init__(self, target, attr, old_value, new_value,
                 apply_cb=None, description=""):
        super().__init__(description or f"Change {attr}")
        self._target = target
        self._attr = attr
        self._old = old_value
        self._new = new_value
        self._apply_cb = apply_cb
        self._merge_id = SetAttrCmd._next_id
        SetAttrCmd._next_id += 1

    def id(self) -> int:
        # One merge-id per (target, attr) pair so only identical mutations fuse
        return hash((id(self._target), self._attr)) & 0x7FFFFFFF

    def mergeWith(self, other) -> bool:
        if not isinstance(other, SetAttrCmd):
            return False
        if other._target is not self._target or other._attr != self._attr:
            return False
        # Collapse: keep original _old, adopt other's _new
        self._new = other._new
        return True

    def redo(self):
        setattr(self._target, self._attr, self._new)
        if self._apply_cb:
            try:
                self._apply_cb(self._target, self._new)
            except Exception:
                pass

    def undo(self):
        setattr(self._target, self._attr, self._old)
        if self._apply_cb:
            try:
                self._apply_cb(self._target, self._old)
            except Exception:
                pass


class SetZValueCmd(QUndoCommand):
    """Undoable Z-order shift on a scene item.

    QGraphicsItem.setZValue is a method, not a Python attribute, so the
    generic SetAttrCmd doesn't apply directly.
    """

    def __init__(self, item, old_z: float, new_z: float, description: str = "Change order"):
        super().__init__(description)
        self._item = item
        self._old = old_z
        self._new = new_z

    def redo(self):
        self._item.setZValue(self._new)

    def undo(self):
        self._item.setZValue(self._old)


class DeleteItemCmd(QUndoCommand):
    def __init__(self, editor, description="Delete"):
        super().__init__(description)
        self._editor = editor
        self._censors = []  # (region, item) pairs
        self._overlays = []  # (overlay, item) pairs

    def redo(self):
        for region, item in self._censors:
            if region in self._editor._asset.censors:
                self._editor._asset.censors.remove(region)
            if item.scene():
                self._editor._scene.removeItem(item)
        for overlay, item in self._overlays:
            if overlay in self._editor._asset.overlays:
                self._editor._asset.overlays.remove(overlay)
            if item.scene():
                self._editor._scene.removeItem(item)

    def undo(self):
        for region, item in self._censors:
            if region not in self._editor._asset.censors:
                self._editor._asset.censors.append(region)
            if item.scene() is None:
                self._editor._scene.addItem(item)
        for overlay, item in self._overlays:
            if overlay not in self._editor._asset.overlays:
                self._editor._asset.overlays.append(overlay)
            if item.scene() is None:
                self._editor._scene.addItem(item)
