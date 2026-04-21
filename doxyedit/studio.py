"""StudioEditor — unified censor + overlay + annotation workspace.

Layered QGraphicsScene:
  Z   0       Base image pixmap (not editable)
  Z 100-199   Censor rects (persist to asset.censors)
  Z 200-299   Overlay items — watermark/text/logo (persist to asset.overlays)
  Z 300+      Annotations — text/line/box (ephemeral, lost on asset change)
"""
from enum import Enum, auto
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsScene, QGraphicsView, QGraphicsRectItem, QGraphicsPixmapItem,
    QGraphicsTextItem, QGraphicsLineItem, QComboBox, QFileDialog, QSlider,
    QFontComboBox, QSpinBox, QColorDialog, QInputDialog, QMenu,
    QListWidget, QListWidgetItem, QSplitter, QScrollArea, QCheckBox,
)
from PySide6.QtCore import Qt, QRectF, QPointF, QLineF, Signal
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QBrush, QPen, QFont, QWheelEvent,
    QKeyEvent, QTransform, QUndoCommand, QUndoStack,
)
import copy
from PIL import Image

from doxyedit.models import Asset, Project, CensorRegion, CanvasOverlay, CropRegion, PLATFORMS
from doxyedit.exporter import apply_censors, apply_overlays
from doxyedit.preview import NoteRectItem, ResizableCropItem


# ── Layout constants ──────────────────────────────────────────────
STUDIO_GRID_SPACING = 50          # snap grid spacing in pixels
STUDIO_GRID_PEN_ALPHA = 40        # grid line opacity
STUDIO_GRID_PEN_WIDTH = 0.5       # grid line thickness
STUDIO_RESIZE_HANDLE_SIZE = 6     # resize handle square size
STUDIO_ZOOM_BTN_WIDTH_RATIO = 3.0  # zoom button width × font_size
STUDIO_ZOOM_LABEL_WIDTH_RATIO = 3.3  # zoom % label width × font_size
STUDIO_LAYER_PANEL_WIDTH = 200    # layer panel max width


# ---------------------------------------------------------------------------
# Context menu theming helper
# ---------------------------------------------------------------------------

def _themed_menu(parent=None) -> QMenu:
    """Create a QMenu styled from the current theme (same pattern as window.py)."""
    from doxyedit.themes import THEMES, DEFAULT_THEME
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
    from doxyedit.models import PLATFORMS
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
    ANNOTATE_TEXT = auto()
    ANNOTATE_LINE = auto()
    ANNOTATE_BOX = auto()


# ---------------------------------------------------------------------------
# Graphics items
# ---------------------------------------------------------------------------

class _ResizeHandle(QGraphicsRectItem):
    """Small square handle for resizing a CensorRectItem."""

    def __init__(self, parent_censor, position: str):
        super().__init__(-3, -3, 6, 6, parent_censor)
        self._parent = parent_censor
        self._position = position  # "tl", "tr", "bl", "br", "t", "b", "l", "r"
        self.setBrush(QBrush(QColor(255, 255, 255)))
        self.setPen(QPen(QColor(0, 0, 0), 1))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if position in ("tl", "br")
                       else Qt.CursorShape.SizeBDiagCursor if position in ("tr", "bl")
                       else Qt.CursorShape.SizeVerCursor if position in ("t", "b")
                       else Qt.CursorShape.SizeHorCursor)
        self.setZValue(1000)
        self.setVisible(False)

    def mouseMoveEvent(self, event):
        self._parent._on_handle_moved(self._position, event.scenePos())
        super().mouseMoveEvent(event)


class _RotateHandle(QGraphicsRectItem):
    """Small circular handle rendered above the top edge for rotating a censor."""

    def __init__(self, parent_censor):
        super().__init__(-4, -4, 8, 8, parent_censor)
        self._parent = parent_censor
        self.setBrush(QBrush(QColor(200, 220, 255)))
        self.setPen(QPen(QColor(0, 0, 0), 1))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(1001)
        self.setVisible(False)

    def mouseMoveEvent(self, event):
        self._parent._on_rotate_handle_moved(event.scenePos())
        super().mouseMoveEvent(event)


class CensorRectItem(QGraphicsRectItem):
    """Draggable censor rectangle — overlay exception: hardcoded colors OK."""

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
        self._apply_style()
        # Resize handles (8-point) + rotate handle (above top edge)
        self._handles = {}
        for pos in ("tl", "t", "tr", "l", "r", "bl", "b", "br"):
            h = _ResizeHandle(self, pos)
            self._handles[pos] = h
        self._rotate_handle = _RotateHandle(self)
        self._update_handle_positions()

    def _apply_style(self):
        if self.style == "black":
            self.setBrush(QBrush(QColor(0, 0, 0, 220)))
            self.setPen(QPen(QColor("#ff4444"), 1.5, Qt.PenStyle.DashLine))
        elif self.style == "blur":
            self.setBrush(QBrush(QColor(100, 100, 255, 80)))
            self.setPen(QPen(QColor("#6666ff"), 1.5, Qt.PenStyle.DashLine))
        elif self.style == "pixelate":
            self.setBrush(QBrush(QColor(100, 255, 100, 80)))
            self.setPen(QPen(QColor("#66ff66"), 1.5, Qt.PenStyle.DashLine))

    def _update_handle_positions(self):
        r = self.rect()
        positions = {
            "tl": (r.left(), r.top()),
            "t": (r.center().x(), r.top()),
            "tr": (r.right(), r.top()),
            "l": (r.left(), r.center().y()),
            "r": (r.right(), r.center().y()),
            "bl": (r.left(), r.bottom()),
            "b": (r.center().x(), r.bottom()),
            "br": (r.right(), r.bottom()),
        }
        for pos, (x, y) in positions.items():
            self._handles[pos].setPos(x, y)
        # Rotate handle: 20px above top-center
        if hasattr(self, "_rotate_handle"):
            self._rotate_handle.setPos(r.center().x(), r.top() - 20)

    def _on_rotate_handle_moved(self, scene_pos):
        """Compute angle from rect center to the handle position and apply setRotation."""
        import math
        center_scene = self.mapToScene(self.rect().center())
        dx = scene_pos.x() - center_scene.x()
        dy = scene_pos.y() - center_scene.y()
        # Handle is at 12 o'clock (dy < 0) at 0°. Angle grows clockwise.
        angle = math.degrees(math.atan2(dy, dx)) + 90.0
        self.setTransformOriginPoint(self.rect().center())
        self.setRotation(angle)
        # Persist to CensorRegion (add rotation field if present; fall back silently)
        cr = getattr(self, "_censor_region", None)
        if cr is not None and hasattr(cr, "rotation"):
            cr.rotation = float(angle)

    def _on_handle_moved(self, position: str, scene_pos):
        local = self.mapFromScene(scene_pos)
        r = self.rect()
        if "l" in position:
            r.setLeft(min(local.x(), r.right() - 10))
        if "r" in position:
            r.setRight(max(local.x(), r.left() + 10))
        if "t" in position:
            r.setTop(min(local.y(), r.bottom() - 10))
        if "b" in position:
            r.setBottom(max(local.y(), r.top() + 10))
        self.setRect(r)
        self._update_handle_positions()
        # Update model
        if self._editor:
            self._editor._sync_censors_to_asset()

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.GraphicsItemChange.ItemSelectedHasChanged:
            for h in self._handles.values():
                h.setVisible(bool(value))
            if hasattr(self, "_rotate_handle"):
                self._rotate_handle.setVisible(bool(value))
        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        _parent = self._editor._view if self._editor else None
        menu = _themed_menu(_parent)
        styles = {"black": "Change to Black", "blur": "Change to Blur",
                   "pixelate": "Change to Pixelate"}
        for key, label in styles.items():
            if key != self.style:
                act = menu.addAction(label)
                act.setData(key)
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
        elif plat_actions and (chosen is all_act or chosen in plat_actions):
            self.platforms = _resolve_platform_menu(chosen, all_act, plat_actions, self.platforms)
            if self._editor:
                self._editor._sync_censors_to_asset()
                self._editor._refresh_layer_panel()
        elif chosen.data():
            self.style = chosen.data()
            self._apply_style()
            if self._editor:
                self._editor._sync_censors_to_asset()


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
        self.setOpacity(overlay.opacity)
        self.setPos(overlay.x, overlay.y)
        # Rotate from center
        self.setTransformOriginPoint(pixmap.width() / 2, pixmap.height() / 2)
        # Apply flip via QTransform (scale -1 on affected axis). setRotation
        # still works after setTransform in Qt.
        if getattr(overlay, "flip_h", False) or getattr(overlay, "flip_v", False):
            from PySide6.QtGui import QTransform
            t = QTransform()
            t.scale(-1.0 if overlay.flip_h else 1.0,
                    -1.0 if overlay.flip_v else 1.0)
            self.setTransform(t)
        if overlay.rotation:
            self.setRotation(overlay.rotation)

    def itemChange(self, change, value):
        if change == QGraphicsPixmapItem.GraphicsItemChange.ItemPositionHasChanged:
            self.overlay.x = int(value.x())
            self.overlay.y = int(value.y())
            self.overlay.position = "custom"
        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        _parent = self._editor._view if self._editor else None
        menu = _themed_menu(_parent)
        dup_act = menu.addAction("Duplicate")
        menu.addSeparator()
        flip_h_act = menu.addAction("Flip Horizontal")
        flip_v_act = menu.addAction("Flip Vertical")
        menu.addSeparator()
        fwd_act = menu.addAction("Bring Forward")
        bwd_act = menu.addAction("Send Backward")
        menu.addSeparator()
        plat_sub = all_act = plat_actions = None
        if self._editor and self._editor._project:
            plat_sub, all_act, plat_actions = _add_platform_submenu(menu, self.overlay.platforms, self._editor)
            menu.addSeparator()
        del_act = menu.addAction("Delete")

        chosen = menu.exec(event.screenPos())
        if not chosen:
            return
        if chosen is dup_act and self._editor:
            self._editor._duplicate_overlay_item(self)
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
        from PySide6.QtGui import QTransform
        self.setTransformOriginPoint(self.boundingRect().center())
        sx = -1.0 if getattr(self.overlay, "flip_h", False) else 1.0
        sy = -1.0 if getattr(self.overlay, "flip_v", False) else 1.0
        # Compose flip + existing rotation
        t = QTransform()
        t.scale(sx, sy)
        self.setTransform(t)
        self.setRotation(self.overlay.rotation)


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
        self._apply_font()
        self.setOpacity(overlay.opacity)
        self.setPos(overlay.x, overlay.y)

    def _apply_font(self):
        font = QFont(self.overlay.font_family, self.overlay.font_size)
        if self.overlay.bold:
            font.setBold(True)
        if self.overlay.italic:
            font.setItalic(True)
        if self.overlay.letter_spacing:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, self.overlay.letter_spacing)
        self.setFont(font)
        self.setDefaultTextColor(QColor(self.overlay.color))
        if self.overlay.text_width > 0:
            self.setTextWidth(self.overlay.text_width)
        else:
            self.setTextWidth(-1)
        # Line height via block format
        lh = self.overlay.line_height or 1.2
        from PySide6.QtGui import QTextBlockFormat, QTextCursor
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

    def paint(self, painter, option, widget=None):
        # Draw text outline if stroke is configured
        if self.overlay.stroke_width > 0 and self.overlay.stroke_color:
            from PySide6.QtGui import QPainterPath, QPainterPathStroker
            painter.save()
            doc = self.document()
            ctx = doc.documentLayout()
            # Build a path from all text in the document
            path = QPainterPath()
            block = doc.begin()
            while block.isValid():
                layout = block.layout()
                if layout:
                    for i in range(layout.lineCount()):
                        line = layout.lineAt(i)
                        for j in range(line.textStart(), line.textStart() + line.textLength()):
                            pass  # We need a different approach
                block = block.next()
            # Simpler approach: draw the text twice — outline then fill
            # Use QTextDocument rendering with a stroke pen
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Draw outline by rendering text offset in 8 directions
            stroke_w = self.overlay.stroke_width
            stroke_c = QColor(self.overlay.stroke_color)
            orig_color = self.defaultTextColor()
            self.setDefaultTextColor(stroke_c)
            for dx in (-stroke_w, 0, stroke_w):
                for dy in (-stroke_w, 0, stroke_w):
                    if dx == 0 and dy == 0:
                        continue
                    painter.save()
                    painter.translate(dx, dy)
                    super().paint(painter, option, widget)
                    painter.restore()
            self.setDefaultTextColor(orig_color)
            painter.restore()
        super().paint(painter, option, widget)

    def itemChange(self, change, value):
        if change == QGraphicsTextItem.GraphicsItemChange.ItemPositionHasChanged:
            self.overlay.x = int(value.x())
            self.overlay.y = int(value.y())
            self.overlay.position = "custom"
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        super().mouseDoubleClickEvent(event)

    def sceneEvent(self, event):
        """Intercept ALL events before Qt's internal text control sees them."""
        from PySide6.QtCore import QEvent
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
        super().focusOutEvent(event)

    def contextMenuEvent(self, event):
        _parent = self._editor._view if self._editor else None
        menu = _themed_menu(_parent)
        edit_act = menu.addAction("Edit Text")
        menu.addSeparator()
        dup_act = menu.addAction("Duplicate")
        menu.addSeparator()
        fwd_act = menu.addAction("Bring Forward")
        bwd_act = menu.addAction("Send Backward")
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
        elif chosen is dup_act and self._editor:
            self._editor._duplicate_overlay_item(self)
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
        elif chosen is bwd_act:
            new_z = max(200, self.zValue() - 1)
            if self._editor:
                cmd = SetZValueCmd(self, self.zValue(), new_z, "Send backward")
                self._editor._undo_stack.push(cmd)
            else:
                self.setZValue(new_z)
        elif chosen is del_act and self._editor:
            self._editor._remove_overlay_item(self)


class AnnotationTextItem(QGraphicsTextItem):
    """Ephemeral text annotation — no model reference, lost on asset change."""

    def __init__(self, text: str = "Double-click to edit"):
        super().__init__(text)
        self.setFlags(
            QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable
        )
        from doxyedit.themes import THEMES, DEFAULT_THEME
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


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------

class StudioScene(QGraphicsScene):
    """Scene with tool-aware mouse handling for censor/annotation drawing."""

    # Smart-guide tuning
    SNAP_THRESHOLD_PX = 5   # snap when any tracked edge is within this many scene px

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid_visible = False
        self._grid_spacing = STUDIO_GRID_SPACING
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        self.setBackgroundBrush(QBrush(QColor(_dt.bg_deep)))

        self.current_tool = StudioTool.SELECT
        self._draw_start: QPointF | None = None
        self._temp_item = None
        self._censor_style = "black"

        # Smart snap guides — populated during drag, drawn in drawForeground,
        # cleared on release.
        self._snap_guides: list[tuple[float, float, float, float]] = []

        # Callbacks set by StudioEditor
        self.on_censor_finished = None   # callable(CensorRectItem)
        self.on_annotation_placed = None  # callable(item)
        self.on_crop_finished = None     # callable(QRectF)
        self.on_note_finished = None     # callable(QRectF, NoteRectItem)
        self.on_text_overlay_placed = None  # callable(QPointF)
        self.get_crop_aspect = None      # callable() -> float | None

    def set_theme(self, theme):
        self.setBackgroundBrush(QBrush(QColor(theme.bg_deep)))

    def set_tool(self, tool: StudioTool):
        self.current_tool = tool

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            # Clear any text item editing
            focus = self.focusItem()
            if focus and isinstance(focus, OverlayTextItem):
                cursor = focus.textCursor()
                cursor.clearSelection()
                focus.setTextCursor(cursor)
                focus.clearFocus()
                focus.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                focus.overlay.text = focus.toPlainText()
            # Clear scene selection
            self.clearSelection()
            # Forward to editor for crop mask cleanup
            if self.views():
                view = self.views()[0]
                if hasattr(view, '_studio_editor') and view._studio_editor:
                    view._studio_editor._clear_escape_state()
            return
        super().keyPressEvent(event)

    def drawForeground(self, painter, rect):
        """Draw snap grid and smart-guide overlay."""
        super().drawForeground(painter, rect)
        if self._grid_visible:
            pen = QPen(QColor(128, 128, 128, STUDIO_GRID_PEN_ALPHA), STUDIO_GRID_PEN_WIDTH)
            painter.setPen(pen)
            gs = self._grid_spacing
            left = int(rect.left()) - (int(rect.left()) % gs)
            top = int(rect.top()) - (int(rect.top()) % gs)
            x = left
            while x < rect.right():
                painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
                x += gs
            y = top
            while y < rect.bottom():
                painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
                y += gs

        # Smart snap guides: dashed magenta lines drawn during drag
        if self._snap_guides:
            guide_pen = QPen(QColor(255, 0, 200, 200), 1, Qt.PenStyle.DashLine)
            painter.setPen(guide_pen)
            for x1, y1, x2, y2 in self._snap_guides:
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def set_censor_style(self, style: str):
        self._censor_style = style

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        pos = event.scenePos()

        # Commit any in-progress text edit if the click lands outside the
        # currently-editing text item. Without this, Qt's QTextControl keeps
        # the text in edit mode and eats subsequent Escape keystrokes, which
        # was the root cause of "Esc doesn't clear" reports.
        focus = self.focusItem()
        if isinstance(focus, OverlayTextItem):
            if not focus.contains(focus.mapFromScene(pos)):
                cursor = focus.textCursor()
                cursor.clearSelection()
                focus.setTextCursor(cursor)
                focus.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                focus.overlay.text = focus.toPlainText()
                focus.clearFocus()

        # Click on empty space — clear everything (same as F10)
        if self.current_tool == StudioTool.SELECT:
            item_under = self.itemAt(pos, self.views()[0].transform() if self.views() else QTransform())
            if item_under is None:
                if self.views() and hasattr(self.views()[0], '_studio_editor'):
                    self.views()[0]._studio_editor._nuclear_clear()
            return super().mousePressEvent(event)

        if self.current_tool == StudioTool.CENSOR:
            self._draw_start = pos
            self._temp_item = CensorRectItem(
                QRectF(pos, pos), self._censor_style
            )
            self._temp_item.setZValue(150)
            self.addItem(self._temp_item)
            return

        if self.current_tool == StudioTool.CROP:
            self._draw_start = pos
            self._temp_item = QGraphicsRectItem(QRectF(pos, pos))
            from doxyedit.themes import THEMES, DEFAULT_THEME
            _dt = THEMES[DEFAULT_THEME]
            _cc = QColor(_dt.crop_border)
            _cc.setAlpha(_dt.studio_handle_alpha)
            self._temp_item.setPen(QPen(_cc, _dt.crop_border_width))
            self._temp_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            self._temp_item.setZValue(400)
            self.addItem(self._temp_item)
            return

        if self.current_tool == StudioTool.NOTE:
            self._draw_start = pos
            self._temp_item = NoteRectItem(QRectF(pos, pos), "")
            self._temp_item.setZValue(400)
            self.addItem(self._temp_item)
            return

        if self.current_tool == StudioTool.TEXT_OVERLAY:
            if self.on_text_overlay_placed:
                self.on_text_overlay_placed(pos)
            self.current_tool = StudioTool.SELECT
            return

        if self.current_tool == StudioTool.ANNOTATE_TEXT:
            item = AnnotationTextItem()
            item.setPos(pos)
            item.setZValue(300)
            self.addItem(item)
            if self.on_annotation_placed:
                self.on_annotation_placed(item)
            self.current_tool = StudioTool.SELECT
            return

        if self.current_tool in (StudioTool.ANNOTATE_LINE, StudioTool.ANNOTATE_BOX):
            self._draw_start = pos
            from doxyedit.themes import THEMES, DEFAULT_THEME
            _dt = THEMES[DEFAULT_THEME]
            pen = QPen(QColor(_dt.accent_bright), _dt.crop_border_width - 1)
            if self.current_tool == StudioTool.ANNOTATE_LINE:
                self._temp_item = QGraphicsLineItem(QLineF(pos, pos))
                self._temp_item.setPen(pen)
            else:
                self._temp_item = QGraphicsRectItem(QRectF(pos, pos))
                self._temp_item.setPen(pen)
                _abf = QColor(_dt.accent_bright)
                _abf.setAlpha(_dt.studio_guide_alpha)
                self._temp_item.setBrush(QBrush(_abf))
            self._temp_item.setZValue(300)
            self._temp_item.setFlags(
                QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
                | QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
            )
            self.addItem(self._temp_item)
            return

        super().mousePressEvent(event)

    def _compute_snap_guides(self, moving_item):
        """Return (dx, dy, guides) where dx/dy offset the moving_item to snap,
        and `guides` is a list of (x1,y1,x2,y2) to draw. Uses SNAP_THRESHOLD_PX.
        """
        if moving_item is None:
            return 0.0, 0.0, []
        mb = moving_item.sceneBoundingRect()
        m_edges_x = [mb.left(), mb.center().x(), mb.right()]
        m_edges_y = [mb.top(), mb.center().y(), mb.bottom()]

        candidates_x = []  # list of (target_x, y_range_lo, y_range_hi)
        candidates_y = []  # list of (target_y, x_range_lo, x_range_hi)

        # Canvas-center snaps (finds the pixmap item if present)
        for it in self.items():
            if isinstance(it, QGraphicsPixmapItem):
                pm = it.sceneBoundingRect()
                candidates_x.append((pm.center().x(), pm.top(), pm.bottom()))
                candidates_y.append((pm.center().y(), pm.left(), pm.right()))
                break

        # Every other item's edges + centers
        for it in self.items():
            if it is moving_item or it.parentItem() is not None:
                continue
            if not isinstance(it, (OverlayImageItem, OverlayTextItem,
                                   CensorRectItem, ResizableCropItem,
                                   NoteRectItem, QGraphicsPixmapItem)):
                continue
            if it is moving_item:
                continue
            ob = it.sceneBoundingRect()
            for x in (ob.left(), ob.center().x(), ob.right()):
                candidates_x.append((x, ob.top(), ob.bottom()))
            for y in (ob.top(), ob.center().y(), ob.bottom()):
                candidates_y.append((y, ob.left(), ob.right()))

        thr = self.SNAP_THRESHOLD_PX
        best_dx, best_dy = 0.0, 0.0
        best_dx_abs, best_dy_abs = thr + 1, thr + 1
        guides: list[tuple[float, float, float, float]] = []
        for me in m_edges_x:
            for target, y1, y2 in candidates_x:
                d = target - me
                if abs(d) <= thr and abs(d) < best_dx_abs:
                    best_dx, best_dx_abs = d, abs(d)
        for me in m_edges_y:
            for target, x1, x2 in candidates_y:
                d = target - me
                if abs(d) <= thr and abs(d) < best_dy_abs:
                    best_dy, best_dy_abs = d, abs(d)

        # After applying the winning deltas, collect guide lines that remain aligned
        final_left = mb.left() + best_dx
        final_right = mb.right() + best_dx
        final_centerx = mb.center().x() + best_dx
        final_top = mb.top() + best_dy
        final_bottom = mb.bottom() + best_dy
        final_centery = mb.center().y() + best_dy

        for target, y1, y2 in candidates_x:
            for edge in (final_left, final_centerx, final_right):
                if abs(edge - target) < 0.5:
                    y_lo = min(y1, final_top)
                    y_hi = max(y2, final_bottom)
                    guides.append((target, y_lo, target, y_hi))
                    break
        for target, x1, x2 in candidates_y:
            for edge in (final_top, final_centery, final_bottom):
                if abs(edge - target) < 0.5:
                    x_lo = min(x1, final_left)
                    x_hi = max(x2, final_right)
                    guides.append((x_lo, target, x_hi, target))
                    break
        return best_dx, best_dy, guides

    def mouseMoveEvent(self, event):
        # Snap-to-edge for the currently-dragged item (SELECT tool only).
        if (self.current_tool == StudioTool.SELECT
                and event.buttons() & Qt.MouseButton.LeftButton
                and self.mouseGrabberItem() is not None):
            grabber = self.mouseGrabberItem()
            if isinstance(grabber, (OverlayImageItem, OverlayTextItem,
                                    CensorRectItem, ResizableCropItem, NoteRectItem)):
                # Let Qt move it first, then snap
                super().mouseMoveEvent(event)
                dx, dy, guides = self._compute_snap_guides(grabber)
                if dx or dy:
                    grabber.moveBy(dx, dy)
                if guides != self._snap_guides:
                    self._snap_guides = guides
                    self.update()
                return
        if self._draw_start and self._temp_item:
            pos = event.scenePos()
            if isinstance(self._temp_item, QGraphicsLineItem):
                self._temp_item.setLine(QLineF(self._draw_start, pos))
            elif isinstance(self._temp_item, QGraphicsRectItem):
                r = QRectF(self._draw_start, pos).normalized()
                # Constrain crop to aspect ratio
                if self.current_tool == StudioTool.CROP and self.get_crop_aspect:
                    aspect = self.get_crop_aspect()
                    if aspect and r.width() > 2 and r.height() > 2:
                        cur = r.width() / r.height()
                        if cur > aspect:
                            r.setWidth(r.height() * aspect)
                        else:
                            r.setHeight(r.width() / aspect)
                self._temp_item.setRect(r)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # Clear snap guides at end of any drag
        if self._snap_guides:
            self._snap_guides = []
            self.update()

        if self._draw_start and self._temp_item:
            if self.current_tool == StudioTool.CENSOR:
                if self.on_censor_finished:
                    self.on_censor_finished(self._temp_item)
            elif self.current_tool == StudioTool.CROP:
                r = self._temp_item.rect()
                if r.width() > 10 and r.height() > 10 and self.on_crop_finished:
                    self.on_crop_finished(r)
                else:
                    self.removeItem(self._temp_item)
            elif self.current_tool == StudioTool.NOTE:
                r = self._temp_item.rect()
                if r.width() > 10 and r.height() > 10 and self.on_note_finished:
                    self.on_note_finished(self._temp_item, r)
                else:
                    self.removeItem(self._temp_item)
            self._draw_start = None
            self._temp_item = None
            self.current_tool = StudioTool.SELECT
            return
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class StudioView(QGraphicsView):
    """Zoomable (wheel) + pannable (middle-drag) view."""

    def __init__(self, scene: StudioScene, parent=None):
        super().__init__(scene, parent)
        self.setObjectName("studio_view")
        self._studio_editor = None  # set by StudioEditor after creation
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setAcceptDrops(True)
        self._panning = False
        self._pan_start = QPointF()
        self.on_file_dropped = None  # callback(path, scene_pos)

    def wheelEvent(self, event: QWheelEvent):
        _zoom = 1.15
        factor = _zoom if event.angleDelta().y() > 0 else 1 / _zoom
        self.setTransform(self.transform().scale(factor, factor))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        # Escape is handled by StudioScene.keyPressEvent (scene focus) or by
        # OverlayTextItem.sceneEvent (text-item focus). No view-level forward
        # needed; letting Qt route it normally now that the app-wide filter
        # is gone.
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if self.on_file_dropped:
                        pos = self.mapToScene(event.position().toPoint())
                        self.on_file_dropped(path, pos)
            event.acceptProposedAction()


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class StudioEditor(QWidget):
    """Unified censor + overlay + annotation workspace."""

    queue_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studio_editor")
        self._asset: Asset | None = None
        self._project: Project | None = None
        self._project_path: str = ""
        self._theme = None
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._censor_items: list[CensorRectItem] = []
        self._overlay_items: list[OverlayImageItem | OverlayTextItem] = []
        self._overlays_visible = True
        # Crop + note state
        self._crop_items: list[ResizableCropItem] = []
        self._crop_rect_item: QGraphicsRectItem | None = None
        self._crop_mask_item = None
        self._crop_start: QPointF | None = None
        self._notes: list[NoteRectItem] = []
        self._note_start: QPointF | None = None
        self._note_temp: NoteRectItem | None = None
        self._build()
        self._undo_stack = QUndoStack(self)
        self._undo_stack.setUndoLimit(50)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ---- keyboard shortcuts ----

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        # Ctrl combos
        if ctrl and key == Qt.Key.Key_Z:
            self._undo_stack.undo()
            return
        if ctrl and key == Qt.Key.Key_Y:
            self._undo_stack.redo()
            return
        if ctrl and key == Qt.Key.Key_D:
            self._duplicate_selected()
            return
        if ctrl and key == Qt.Key.Key_C:
            self._copy_selected_items()
            return
        if ctrl and key == Qt.Key.Key_V:
            self._paste_items_from_clipboard()
            return

        # Delete
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            # Only delete if no text item is in edit mode
            for item in self._scene.selectedItems():
                if isinstance(item, OverlayTextItem) and \
                   item.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction:
                    break
            else:
                self._delete_selected()
            return

        # Arrow nudge
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            delta = 10 if shift else 1
            dx, dy = 0, 0
            if key == Qt.Key.Key_Left:
                dx = -delta
            elif key == Qt.Key.Key_Right:
                dx = delta
            elif key == Qt.Key.Key_Up:
                dy = -delta
            elif key == Qt.Key.Key_Down:
                dy = delta
            moved = False
            moved_crop = False
            moved_note = False
            for item in self._scene.selectedItems():
                if isinstance(item, (CensorRectItem, OverlayImageItem, OverlayTextItem)):
                    item.moveBy(dx, dy)
                    if isinstance(item, (OverlayImageItem, OverlayTextItem)):
                        item.overlay.x = int(item.pos().x())
                        item.overlay.y = int(item.pos().y())
                    moved = True
                elif isinstance(item, ResizableCropItem):
                    item.moveBy(dx, dy)
                    moved_crop = True
                    if getattr(item, "on_changed", None):
                        item.on_changed(item)
                elif isinstance(item, NoteRectItem):
                    item.moveBy(dx, dy)
                    moved_note = True
            if moved:
                self._sync_censors_to_asset()
                self._sync_overlays_to_asset()
            if moved_note:
                self._save_notes_to_asset()
            return

        # Escape is handled by StudioScene.keyPressEvent (scene focus) or
        # OverlayTextItem.sceneEvent (text-item focus). Widget-level handler
        # is no longer needed; leaving it here would stomp on those paths.
        if key == Qt.Key.Key_Escape:
            super().keyPressEvent(event)
            return

        # Tool shortcuts (only when no modifier)
        if not ctrl and not shift:
            if key == Qt.Key.Key_Q:
                self._set_tool(StudioTool.SELECT)
                return
            if key == Qt.Key.Key_W:
                self._set_tool(StudioTool.CENSOR)
                return
            if key == Qt.Key.Key_E:
                self._set_tool(StudioTool.WATERMARK)
                return
            if key == Qt.Key.Key_R:
                self._set_tool(StudioTool.TEXT_OVERLAY)
                return
            if key == Qt.Key.Key_C:
                self._set_tool(StudioTool.CROP)
                return
            if key == Qt.Key.Key_N:
                self._set_tool(StudioTool.NOTE)
                return
            if key == Qt.Key.Key_F:
                if self._scene.sceneRect():
                    self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
                return
            if key == Qt.Key.Key_H:
                self._toggle_overlay_visibility()
                return
            elif key == Qt.Key.Key_L:
                # Toggle layer panel
                vis = self._layer_panel.isVisible()
                self._layer_panel.setVisible(not vis)
                return
            elif key == Qt.Key.Key_G:
                self._scene._grid_visible = not self._scene._grid_visible
                self._scene.update()
                return

        super().keyPressEvent(event)

    # ---- construction ----

    def _build(self):
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        # ── Layout ratios (change here to rescale all Studio widgets) ──
        SLIDER_WIDTH_RATIO = 7.0               # standard slider track
        SLIDER_NARROW_RATIO = 5.0              # narrow slider (kerning, outline)
        ICON_BUTTON_WIDTH_RATIO = 2.3          # icon buttons (B, I, ■, ◻)
        ZOOM_BUTTON_WIDTH_RATIO = 3.0          # zoom preset buttons (Fit, 50%, etc.)
        ZOOM_LABEL_WIDTH_RATIO = 3.3           # zoom percentage label
        LAYER_PANEL_MAX_WIDTH_RATIO = 16.7     # layer panel max width

        _pad = max(4, _dt.font_size // 3)
        _pad_lg = max(6, _dt.font_size // 2)
        _slider_w = int(_dt.font_size * SLIDER_WIDTH_RATIO)
        _slider_sm = int(_dt.font_size * SLIDER_NARROW_RATIO)
        _icon_btn_w = int(_dt.font_size * ICON_BUTTON_WIDTH_RATIO)

        root = QVBoxLayout(self)
        root.setContentsMargins(_pad_lg, _pad_lg, _pad_lg, _pad_lg)

        toolbar = QHBoxLayout()

        # Group 1: Selection
        self.btn_select = QPushButton("Select")
        self.btn_select.setObjectName("studio_btn_select")
        self.btn_select.clicked.connect(lambda: self._set_tool(StudioTool.SELECT))
        toolbar.addWidget(self.btn_select)

        toolbar.addWidget(QLabel("|"))

        # Group 2: Censor tools
        self.btn_censor = QPushButton("Censor")
        self.btn_censor.setObjectName("studio_btn_censor")
        self.btn_censor.clicked.connect(lambda: self._set_tool(StudioTool.CENSOR))
        toolbar.addWidget(self.btn_censor)

        self.combo_censor_style = QComboBox()
        self.combo_censor_style.setObjectName("studio_censor_style")
        self.combo_censor_style.addItems(["black", "blur", "pixelate"])
        self.combo_censor_style.currentTextChanged.connect(self._on_censor_style_changed)
        toolbar.addWidget(self.combo_censor_style)

        self.btn_crop = QPushButton("Crop")
        self.btn_crop.setObjectName("studio_btn_crop")
        self.btn_crop.clicked.connect(lambda: self._set_tool(StudioTool.CROP))
        toolbar.addWidget(self.btn_crop)

        self._crop_combo = QComboBox()
        self._crop_combo.setObjectName("studio_crop_combo")
        from doxyedit.themes import THEMES, DEFAULT_THEME as _DT
        _t = THEMES[_DT]
        self._crop_combo.setMinimumWidth(0)
        self._crop_combo.addItem("Free crop", None)
        for pid, platform in PLATFORMS.items():
            self._crop_combo.insertSeparator(self._crop_combo.count())
            self._crop_combo.addItem(f"\u2500\u2500 {platform.name} \u2500\u2500", None)
            idx = self._crop_combo.count() - 1
            self._crop_combo.model().item(idx).setEnabled(False)
            for slot in platform.slots:
                self._crop_combo.addItem(
                    f"  {slot.label} ({slot.width}x{slot.height})",
                    (pid, slot.name, slot.width, slot.height))
        toolbar.addWidget(self._crop_combo)

        self.btn_note = QPushButton("Note")
        self.btn_note.setObjectName("studio_btn_note")
        self.btn_note.clicked.connect(lambda: self._set_tool(StudioTool.NOTE))
        toolbar.addWidget(self.btn_note)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setObjectName("studio_btn_delete")
        self.btn_delete.clicked.connect(self._delete_selected)
        toolbar.addWidget(self.btn_delete)

        toolbar.addWidget(QLabel("|"))

        # Group 3: Overlay tools
        self.btn_watermark = QPushButton("Watermark")
        self.btn_watermark.setObjectName("studio_btn_watermark")
        self.btn_watermark.clicked.connect(lambda: self._set_tool(StudioTool.WATERMARK))
        toolbar.addWidget(self.btn_watermark)

        self.btn_text = QPushButton("Text")
        self.btn_text.setObjectName("studio_btn_text")
        self.btn_text.clicked.connect(lambda: self._set_tool(StudioTool.TEXT_OVERLAY))
        toolbar.addWidget(self.btn_text)

        self.combo_template = QComboBox()
        self.combo_template.setObjectName("studio_template_combo")
        self.combo_template.addItem("Apply Template...")
        self.combo_template.activated.connect(self._apply_template)
        toolbar.addWidget(self.combo_template)

        toolbar.addWidget(QLabel("|"))

        # Group 4: Sliders
        toolbar.addWidget(QLabel("Opacity:"))
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setObjectName("studio_opacity_slider")
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(30)
        self.slider_opacity.setFixedWidth(_slider_w)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        toolbar.addWidget(self.slider_opacity)

        toolbar.addWidget(QLabel("Scale:"))
        self.slider_scale = QSlider(Qt.Orientation.Horizontal)
        self.slider_scale.setObjectName("studio_scale_slider")
        self.slider_scale.setRange(5, 100)
        self.slider_scale.setValue(20)
        self.slider_scale.setFixedWidth(_slider_w)
        self.slider_scale.valueChanged.connect(self._on_scale_changed)
        toolbar.addWidget(self.slider_scale)

        toolbar.addWidget(QLabel("|"))

        # Group 4b: Alignment + distribute (menu dropdown)
        self.btn_align = QPushButton("Align ▾")
        self.btn_align.setObjectName("studio_btn_align")
        self.btn_align.setToolTip("Align or distribute 2+ selected items")
        self.btn_align.clicked.connect(self._show_align_menu)
        toolbar.addWidget(self.btn_align)

        toolbar.addWidget(QLabel("|"))

        # Group 5: Export
        self.btn_export = QPushButton("Export Preview")
        self.btn_export.setObjectName("studio_btn_export")
        self.btn_export.clicked.connect(self._export_preview)
        toolbar.addWidget(self.btn_export)

        self.btn_export_plat = QPushButton("Export Platform")
        self.btn_export_plat.setObjectName("studio_btn_export_plat")
        self.btn_export_plat.clicked.connect(self._export_current_platform)
        toolbar.addWidget(self.btn_export_plat)

        self.btn_export_all = QPushButton("Export All Platforms")
        self.btn_export_all.setObjectName("studio_btn_export_all")
        self.btn_export_all.clicked.connect(self._export_all_platforms)
        toolbar.addWidget(self.btn_export_all)

        btn_queue = QPushButton("Queue This")
        btn_queue.setObjectName("studio_queue_btn")
        btn_queue.clicked.connect(self._queue_current)
        toolbar.addWidget(btn_queue)

        toolbar.addStretch()

        root.addLayout(toolbar)

        # Row 2: Overlay properties (visible when text/watermark selected)
        self._props_row = QWidget()
        self._props_row.setObjectName("studio_props_row")
        props = QHBoxLayout(self._props_row)
        props.setContentsMargins(0, _pad // 2, 0, _pad // 2)

        props.addWidget(QLabel("Pos:"))
        self.combo_position = QComboBox()
        self.combo_position.setObjectName("studio_position_combo")
        self.combo_position.addItems([
            "bottom-right", "bottom-left", "top-right", "top-left", "center", "custom (drag)",
        ])
        self.combo_position.currentTextChanged.connect(self._on_position_changed)
        props.addWidget(self.combo_position)

        props.addWidget(QLabel("|"))

        props.addWidget(QLabel("Font:"))
        self.font_combo = QFontComboBox()
        self.font_combo.setObjectName("studio_font_combo")
        self.font_combo.currentFontChanged.connect(self._on_font_changed)
        props.addWidget(self.font_combo)

        props.addWidget(QLabel("Size:"))
        self.slider_font_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_font_size.setObjectName("studio_font_size")
        self.slider_font_size.setRange(8, 200)
        self.slider_font_size.setValue(24)
        self.slider_font_size.setFixedWidth(_slider_sm)
        self.slider_font_size.valueChanged.connect(self._on_font_size_changed)
        props.addWidget(self.slider_font_size)
        self._font_size_label = QLabel("24")
        props.addWidget(self._font_size_label)

        self.btn_bold = QPushButton("B")
        self.btn_bold.setObjectName("studio_bold_btn")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setFixedWidth(_icon_btn_w)
        self.btn_bold.clicked.connect(self._on_bold_changed)
        props.addWidget(self.btn_bold)

        self.btn_italic = QPushButton("I")
        self.btn_italic.setObjectName("studio_italic_btn")
        self.btn_italic.setCheckable(True)
        self.btn_italic.setFixedWidth(_icon_btn_w)
        self.btn_italic.clicked.connect(self._on_italic_changed)
        props.addWidget(self.btn_italic)

        self.btn_color = QPushButton("■")
        self.btn_color.setObjectName("studio_color_btn")
        self.btn_color.setFixedWidth(_icon_btn_w)
        self.btn_color.clicked.connect(self._on_color_pick)
        props.addWidget(self.btn_color)

        self.btn_outline_color = QPushButton("◻")
        self.btn_outline_color.setObjectName("studio_outline_btn")
        self.btn_outline_color.setFixedWidth(_icon_btn_w)
        self.btn_outline_color.setToolTip("Outline color")
        self.btn_outline_color.clicked.connect(self._on_outline_color_pick)
        props.addWidget(self.btn_outline_color)

        props.addWidget(QLabel("OL:"))
        self.slider_outline = QSlider(Qt.Orientation.Horizontal)
        self.slider_outline.setObjectName("studio_outline_slider")
        self.slider_outline.setRange(0, 10)
        self.slider_outline.setValue(0)
        self.slider_outline.setFixedWidth(_slider_sm)
        self.slider_outline.setToolTip("Outline width")
        self.slider_outline.valueChanged.connect(self._on_outline_changed)
        props.addWidget(self.slider_outline)

        props.addWidget(QLabel("|"))

        props.addWidget(QLabel("Kern:"))
        self.slider_kerning = QSlider(Qt.Orientation.Horizontal)
        self.slider_kerning.setObjectName("studio_kerning_slider")
        self.slider_kerning.setRange(-20, 20)
        self.slider_kerning.setValue(0)
        self.slider_kerning.setFixedWidth(_slider_sm)
        self.slider_kerning.valueChanged.connect(self._on_kerning_changed)
        props.addWidget(self.slider_kerning)

        props.addWidget(QLabel("LH:"))
        self.slider_line_height = QSlider(Qt.Orientation.Horizontal)
        self.slider_line_height.setObjectName("studio_line_height_slider")
        self.slider_line_height.setRange(50, 300)  # 0.5x to 3.0x (stored as int * 100)
        self.slider_line_height.setValue(120)       # default 1.2
        self.slider_line_height.setFixedWidth(_slider_sm)
        self.slider_line_height.setToolTip("Line height (1.0 = tight, 1.5 = loose, 2.0 = double)")
        self.slider_line_height.valueChanged.connect(self._on_line_height_changed)
        props.addWidget(self.slider_line_height)

        props.addWidget(QLabel("Rot:"))
        self.slider_rotation = QSlider(Qt.Orientation.Horizontal)
        self.slider_rotation.setObjectName("studio_rotation_slider")
        self.slider_rotation.setRange(-180, 180)
        self.slider_rotation.setValue(0)
        self.slider_rotation.setFixedWidth(_slider_sm)
        self.slider_rotation.valueChanged.connect(self._on_rotation_changed)
        props.addWidget(self.slider_rotation)

        props.addWidget(QLabel("W:"))
        self.slider_text_width = QSlider(Qt.Orientation.Horizontal)
        self.slider_text_width.setObjectName("studio_text_width")
        self.slider_text_width.setRange(0, 2000)
        self.slider_text_width.setValue(0)
        self.slider_text_width.setFixedWidth(_slider_sm)
        self.slider_text_width.valueChanged.connect(self._on_text_width_changed)
        props.addWidget(self.slider_text_width)

        props.addWidget(QLabel("|"))

        self.btn_save_template = QPushButton("Save Template")
        self.btn_save_template.setObjectName("studio_save_template_btn")
        self.btn_save_template.clicked.connect(self._save_as_template)
        props.addWidget(self.btn_save_template)

        props.addStretch()
        # Always visible but disabled when no overlay selected (prevents layout shift)
        self._props_row.setEnabled(False)
        root.addWidget(self._props_row)

        # Scene + View
        self._scene = StudioScene()
        self._scene.on_censor_finished = self._on_censor_drawn
        self._scene.on_crop_finished = self._on_crop_drawn
        self._scene.on_note_finished = self._on_note_drawn
        self._scene.on_text_overlay_placed = self._on_text_placed
        self._scene.get_crop_aspect = self._get_crop_aspect
        self._view = StudioView(self._scene)
        self._view._studio_editor = self
        self._view.on_file_dropped = self._on_file_dropped

        # F10 = cycling testbed
        from PySide6.QtGui import QShortcut, QKeySequence
        self._f10_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F10), self)
        self._f10_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._f10_shortcut.activated.connect(self._nuclear_clear)

        # Snap grid overlay — flag on the scene, drawn via foreground
        self._grid_visible = False
        self._grid_spacing = STUDIO_GRID_SPACING
        self._scene._grid_visible = False
        self._scene._grid_spacing = 50

        # Layer panel (right sidebar, collapsible)
        self._layer_panel = QListWidget()
        self._layer_panel.setObjectName("studio_layer_panel")
        self._layer_panel.setMaximumWidth(int(_dt.font_size * LAYER_PANEL_MAX_WIDTH_RATIO))
        self._layer_panel.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._layer_panel.itemClicked.connect(self._on_layer_clicked)
        # Drag-reorder wiring: when the user drags a row, the list widget
        # fires rowsMoved. We translate the new visual order back into
        # asset.overlays / asset.censors order (top of list = front).
        self._layer_panel.model().rowsMoved.connect(self._on_layer_reorder)

        # Layer properties panel (below the layer list) — shows opacity +
        # enabled toggle for the selected overlay. Disabled when the
        # selected layer is a censor (censors have no opacity / enabled
        # field — style is set via right-click menu).
        _layer_props = QWidget()
        _layer_props.setObjectName("studio_layer_props")
        _props_layout = QVBoxLayout(_layer_props)
        _props_layout.setContentsMargins(_pad_lg, _pad, _pad_lg, _pad)
        _props_layout.setSpacing(_pad)
        _op_row = QHBoxLayout()
        _op_row.addWidget(QLabel("Opacity"))
        self.slider_layer_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_layer_opacity.setObjectName("studio_layer_opacity_slider")
        self.slider_layer_opacity.setRange(0, 100)
        self.slider_layer_opacity.setValue(100)
        self.slider_layer_opacity.valueChanged.connect(self._on_layer_opacity_changed)
        _op_row.addWidget(self.slider_layer_opacity, 1)
        _props_layout.addLayout(_op_row)
        self.chk_layer_enabled = QCheckBox("Enabled")
        self.chk_layer_enabled.setObjectName("studio_layer_enabled_chk")
        self.chk_layer_enabled.toggled.connect(self._on_layer_enabled_toggled)
        _props_layout.addWidget(self.chk_layer_enabled)
        _layer_props.setEnabled(False)
        self._layer_props_widget = _layer_props

        # Vertical splitter so the layer list and props share the sidebar
        _layer_side = QSplitter(Qt.Orientation.Vertical)
        _layer_side.addWidget(self._layer_panel)
        _layer_side.addWidget(_layer_props)
        _layer_side.setStretchFactor(0, 1)
        _layer_side.setStretchFactor(1, 0)

        self._canvas_split = QSplitter(Qt.Orientation.Horizontal)
        self._canvas_split.addWidget(self._view)
        self._canvas_split.addWidget(_layer_side)
        self._canvas_split.setSizes([800, 200])
        self._canvas_split.setStretchFactor(0, 1)
        self._canvas_split.setStretchFactor(1, 0)
        root.addWidget(self._canvas_split, 1)

        # Platform preview strip (collapsible filmstrip)
        self._preview_thumb_h = max(_dt.filmstrip_thumb_min, int(_dt.font_size * _dt.filmstrip_height_ratio))
        strip_h = self._preview_thumb_h + int(_dt.font_size * _dt.filmstrip_label_ratio)
        self._preview_strip = QWidget()
        self._preview_strip.setObjectName("studio_preview_strip")
        self._preview_strip.setFixedHeight(strip_h)
        self._preview_strip_layout = QHBoxLayout(self._preview_strip)
        self._preview_strip_layout.setContentsMargins(_pad, _pad, _pad, _pad)
        self._preview_strip_layout.setSpacing(_pad_lg)
        self._preview_strip_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._preview_strip_scroll = QScrollArea()
        self._preview_strip_scroll.setObjectName("studio_preview_scroll")
        self._preview_strip_scroll.setWidgetResizable(True)
        self._preview_strip_scroll.setFixedHeight(strip_h)
        self._preview_strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._preview_strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_strip_scroll.setWidget(self._preview_strip)
        root.addWidget(self._preview_strip_scroll)
        self._preview_strip_scroll.setVisible(False)

        # Bottom status bar
        status_bar = QHBoxLayout()
        status_bar.setContentsMargins(_pad_lg, _pad, _pad_lg, _pad)
        status_bar.setSpacing(_pad_lg)

        # Zoom presets
        for label, factor in [("Fit", 0), ("50%", 0.5), ("100%", 1.0), ("200%", 2.0)]:
            btn = QPushButton(label)
            btn.setFixedWidth(int(_dt.font_size * ZOOM_BUTTON_WIDTH_RATIO))
            btn.setObjectName("studio_zoom_btn")
            if factor == 0:
                btn.clicked.connect(lambda: self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio))
            else:
                btn.clicked.connect(lambda _, f=factor: self._set_zoom(f))
            status_bar.addWidget(btn)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(int(_dt.font_size * ZOOM_LABEL_WIDTH_RATIO))
        status_bar.addWidget(self._zoom_label)

        status_bar.addWidget(QLabel("|"))

        self._asset_info = QLabel("")
        self._asset_info.setObjectName("studio_asset_info")
        status_bar.addWidget(self._asset_info)

        status_bar.addStretch()

        self.info_label = QLabel("No image loaded")
        self.info_label.setObjectName("studio_info")
        status_bar.addWidget(self.info_label)

        root.addLayout(status_bar)

        # Selection change -> update sliders + props row
        self._scene.selectionChanged.connect(self._on_selection_changed)

    # ---- public API ----

    def set_theme(self, theme):
        """Update scene background to match current theme."""
        self._theme = theme
        self._scene.set_theme(theme)

    def set_project(self, project: Project, project_path: str = ""):
        """Store project ref and populate template dropdown."""
        self._project = project
        self._project_path = project_path
        self.combo_template.clear()
        self.combo_template.addItem("Apply Template...")
        for i, tmpl in enumerate(project.default_overlays):
            label = tmpl.get("label", tmpl.get("type", f"Overlay {i + 1}"))
            self.combo_template.addItem(label)

    def load_asset(self, asset: Asset):
        """Load image, restore censors, overlays, crops, and notes."""
        self._asset = asset
        self._scene.clear()
        self._censor_items.clear()
        self._overlay_items.clear()
        self._crop_items.clear()
        self._notes.clear()
        self._crop_mask_item = None
        self._pixmap_item = None

        # Load base image
        src = Path(asset.source_path)
        ext = src.suffix.lower()
        if ext in (".psd", ".psb"):
            from doxyedit.imaging import load_psd
            pil_img, w, h = load_psd(str(src))
            import io
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            buf.seek(0)
            pm = QPixmap()
            pm.loadFromData(buf.read())
        else:
            pm = QPixmap(str(src))

        if pm.isNull():
            self.info_label.setText("Failed to load image")
            return

        self._pixmap_item = QGraphicsPixmapItem(pm)
        self._pixmap_item.setZValue(0)
        self._scene.addItem(self._pixmap_item)
        self._scene.setSceneRect(QRectF(pm.rect()))
        self._view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

        # Restore censors (Z 100-199)
        for i, cr in enumerate(asset.censors):
            item = CensorRectItem(QRectF(cr.x, cr.y, cr.w, cr.h), cr.style, cr.platforms)
            item._editor = self
            item.setZValue(100 + i)
            self._scene.addItem(item)
            self._censor_items.append(item)

        # Restore overlays (Z 200-299)
        for i, ov in enumerate(asset.overlays):
            item = self._create_overlay_item(ov)
            if item:
                item.setZValue(200 + i)
                self._overlay_items.append(item)

        # Restore crops + notes (Z 400+)
        self._load_existing_crops()
        self._load_saved_notes()

        self._update_info()

        # Update asset info
        if hasattr(self, '_asset_info'):
            size_mb = src.stat().st_size / (1024*1024) if src.exists() else 0
            self._asset_info.setText(f"{pm.width()}\u00d7{pm.height()} \u00b7 {src.suffix.upper().lstrip('.')} \u00b7 {size_mb:.1f}MB")

        if hasattr(self, '_layer_panel'):
            self._rebuild_layer_panel()

    def _set_zoom(self, factor: float):
        self._view.resetTransform()
        self._view.scale(factor, factor)
        self._zoom_label.setText(f"{int(factor * 100)}%")

    def _nuclear_clear(self):
        """F10 — clear text selection + crop mask. The two that work."""
        if not self.isVisible():
            return
        # Clear text selection
        for item in self._scene.items():
            if isinstance(item, OverlayTextItem):
                cursor = item.textCursor()
                cursor.clearSelection()
                item.setTextCursor(cursor)
                item.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                item.overlay.text = item.toPlainText()
                item.clearFocus()
        # Remove crop mask
        if self._crop_mask_item and self._crop_mask_item.scene():
            self._scene.removeItem(self._crop_mask_item)
            self._crop_mask_item = None
        self._scene.clearFocus()
        self._scene.clearSelection()
        self._set_tool(StudioTool.SELECT)
        self._view.setFocus()
        self.info_label.setText("F10 — cleared")

    def _clear_escape_state(self):
        """Shared cleanup for Escape — the two things that actually work."""
        if not self.isVisible():
            return
        print("[Studio] ESC — clearing")
        # Step 2: Clear text selection on ALL text items
        for item in self._scene.items():
            if isinstance(item, OverlayTextItem):
                cursor = item.textCursor()
                cursor.clearSelection()
                item.setTextCursor(cursor)
                item.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                item.overlay.text = item.toPlainText()
                item.clearFocus()
        # Step 5: Remove crop mask
        if self._crop_mask_item and self._crop_mask_item.scene():
            self._scene.removeItem(self._crop_mask_item)
            self._crop_mask_item = None
        # Also clear selection and reset tool
        self._scene.clearFocus()
        self._scene.clearSelection()
        self._set_tool(StudioTool.SELECT)
        self._view.setFocus()

    # ---- tool management ----

    def _set_tool(self, tool: StudioTool):
        self._scene.set_tool(tool)
        if tool in (StudioTool.CENSOR, StudioTool.CROP, StudioTool.NOTE):
            self._view.setCursor(Qt.CursorShape.CrossCursor)
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif tool == StudioTool.WATERMARK:
            self._add_watermark()
            self._scene.set_tool(StudioTool.SELECT)
        elif tool == StudioTool.TEXT_OVERLAY:
            self._view.setCursor(Qt.CursorShape.CrossCursor)
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        else:
            self._view.setCursor(Qt.CursorShape.ArrowCursor)
            self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def _get_crop_aspect(self) -> float | None:
        """Return target W/H aspect ratio from crop combo, or None for free crop."""
        data = self._crop_combo.currentData()
        if data is None:
            return None
        w, h = data[2], data[3]
        return w / h if h else None

    def _on_censor_style_changed(self, style: str):
        self._scene.set_censor_style(style)

    # ---- censor callbacks ----

    def _on_censor_drawn(self, item: CensorRectItem):
        """Called when a censor rect is finished drawing."""
        item._editor = self
        self._censor_items.append(item)
        item.setZValue(100 + len(self._censor_items))
        self._sync_censors_to_asset()
        self._view.setCursor(Qt.CursorShape.ArrowCursor)
        self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._update_info()

    # ---- crop / note callbacks ----

    def _on_crop_drawn(self, rect: QRectF):
        """Called when a crop rect is finished drawing."""
        if not self._asset:
            return
        # Remove the temp rect drawn by the scene
        if self._scene._temp_item and self._scene._temp_item.scene():
            self._scene.removeItem(self._scene._temp_item)
        # Determine label from crop combo — use slot_name for pipeline matching
        data = self._crop_combo.currentData()
        if data and len(data) >= 4:
            label = data[1]  # slot_name
            platform_id = data[0]  # platform_id
            slot_name = data[1]
        else:
            label = "free"
            platform_id = ""
            slot_name = ""
        # Save to asset (first-class platform_id; label kept for display)
        crop = CropRegion(x=int(rect.x()), y=int(rect.y()),
                          w=int(rect.width()), h=int(rect.height()),
                          label=label, platform_id=platform_id, slot_name=slot_name)
        self._asset.crops = [c for c in self._asset.crops if c.label != label]
        self._asset.crops.append(crop)
        # Create editable item
        aspect = data[2] / data[3] if data and len(data) >= 4 and data[3] else None
        crop_item = ResizableCropItem(rect, label=label, aspect=aspect, theme=self._theme)
        crop_item.on_changed = self._on_crop_edited
        self._scene.addItem(crop_item)
        self._crop_items.append(crop_item)
        # Update mask
        self._update_crop_mask(rect)
        self._view.setCursor(Qt.CursorShape.ArrowCursor)
        self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def _on_crop_edited(self, item: ResizableCropItem):
        """Sync a moved/resized crop back to the asset."""
        if not self._asset:
            return
        region = item.get_crop_region()
        # Preserve platform_id / slot_name from the crop being replaced so
        # editing doesn't silently downgrade a platform-scoped crop.
        for c in self._asset.crops:
            if c.label == region.label:
                region.platform_id = getattr(c, "platform_id", "") or region.platform_id
                region.slot_name = getattr(c, "slot_name", "") or region.slot_name
                break
        self._asset.crops = [c for c in self._asset.crops if c.label != region.label]
        self._asset.crops.append(region)
        r = item.rect().translated(item.pos())
        self._update_crop_mask(r)

    def _update_crop_mask(self, crop_rect: QRectF):
        """Draw dark overlay outside the crop region."""
        if self._crop_mask_item:
            if self._crop_mask_item.scene():
                self._scene.removeItem(self._crop_mask_item)
            self._crop_mask_item = None
        if not self._pixmap_item:
            return
        from PySide6.QtGui import QPainterPath
        from PySide6.QtWidgets import QGraphicsPathItem
        img_rect = self._pixmap_item.boundingRect()
        path = QPainterPath()
        path.addRect(img_rect)
        hole = QPainterPath()
        hole.addRect(crop_rect)
        path = path.subtracted(hole)
        self._crop_mask_item = QGraphicsPathItem(path)
        self._crop_mask_item.setPen(QPen(Qt.PenStyle.NoPen))
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _mask_bg = QColor(0, 0, 0); _mask_bg.setAlpha(THEMES[DEFAULT_THEME].preview_tooltip_bg_alpha)
        self._crop_mask_item.setBrush(QBrush(_mask_bg))
        self._crop_mask_item.setZValue(400)
        self._scene.addItem(self._crop_mask_item)

    def _load_existing_crops(self):
        """Show existing crop regions as editable overlays."""
        for item in self._crop_items:
            if item.scene():
                self._scene.removeItem(item)
        self._crop_items.clear()
        if self._crop_mask_item and self._crop_mask_item.scene():
            self._scene.removeItem(self._crop_mask_item)
            self._crop_mask_item = None
        if not self._asset or not self._asset.crops:
            return
        for crop in self._asset.crops:
            rect = QRectF(crop.x, crop.y, crop.w, crop.h)
            # Derive aspect from crop dimensions (preserves platform ratio)
            aspect = crop.w / crop.h if crop.w and crop.h else None
            item = ResizableCropItem(rect, label=crop.label, aspect=aspect, theme=self._theme)
            item.on_changed = self._on_crop_edited
            self._scene.addItem(item)
            self._crop_items.append(item)

    def _on_note_drawn(self, temp_item, rect: QRectF):
        """Called when a note rect is finished drawing."""
        if not self._asset:
            return
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Note")
        dlg.setLabelText("Enter note:")
        dlg.resize(500, 140)
        ok = dlg.exec()
        text = dlg.textValue() if ok else ""
        if ok and text.strip():
            temp_item.update_text(text.strip())
            self._notes.append(temp_item)
            self._save_notes_to_asset()
        else:
            if temp_item.scene():
                self._scene.removeItem(temp_item)
        self._view.setCursor(Qt.CursorShape.ArrowCursor)
        self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def _save_notes_to_asset(self):
        """Save all note annotations to the asset's notes field."""
        if not self._asset:
            return
        note_lines = []
        for n in self._notes:
            r = n.rect()
            note_lines.append(f"[{int(r.x())},{int(r.y())} {int(r.width())}x{int(r.height())}] {n.text}")
        existing = self._asset.notes
        existing_lines = [l for l in existing.split("\n") if l.strip() and not l.strip().startswith("[")]
        self._asset.notes = "\n".join(existing_lines + note_lines)

    def _load_saved_notes(self):
        """Parse annotation notes from asset.notes and display them."""
        for n in self._notes:
            if n.scene():
                self._scene.removeItem(n)
        self._notes.clear()
        if not self._asset or not self._asset.notes:
            return
        import re
        pattern = re.compile(r'\[(\d+),(\d+)\s+(\d+)x(\d+)\]\s*(.*)')
        for line in self._asset.notes.split("\n"):
            m = pattern.match(line.strip())
            if m:
                x, y, w, h = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                text = m.group(5)
                note = NoteRectItem(QRectF(x, y, w, h), text)
                note.setZValue(400)
                self._scene.addItem(note)
                self._notes.append(note)

    # ---- overlay creation ----

    def _create_overlay_item(self, ov: CanvasOverlay):
        """Create the appropriate graphics item for an overlay."""
        if ov.type in ("watermark", "logo") and ov.image_path:
            pm = QPixmap(ov.image_path)
            if pm.isNull():
                return None
            if self._pixmap_item:
                base_w = self._pixmap_item.pixmap().width()
                target_w = max(10, int(base_w * ov.scale))
                pm = pm.scaledToWidth(target_w, Qt.TransformationMode.SmoothTransformation)
            item = OverlayImageItem(pm, ov)
            item._editor = self
            self._scene.addItem(item)
            return item
        elif ov.type == "text":
            item = OverlayTextItem(ov)
            item._editor = self
            self._scene.addItem(item)
            return item
        return None

    def _add_watermark(self):
        """Open file dialog, add a watermark image overlay."""
        if not self._asset:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Watermark Image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if not path:
            return
        ov = CanvasOverlay(
            type="watermark",
            label=Path(path).stem,
            image_path=path,
            opacity=self.slider_opacity.value() / 100.0,
            scale=self.slider_scale.value() / 100.0,
            position="custom",
            x=50, y=50,
        )
        self._asset.overlays.append(ov)
        item = self._create_overlay_item(ov)
        if item:
            item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(item)
        self._update_info()

    def _on_text_placed(self, pos: QPointF):
        """Handle click-to-place text overlay from scene."""
        self._add_text_overlay(int(pos.x()), int(pos.y()))
        self._view.setCursor(Qt.CursorShape.ArrowCursor)
        self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def _add_text_overlay(self, x: int = 50, y: int = 50):
        """Add a text overlay at the given position."""
        if not self._asset:
            return
        ov = CanvasOverlay(
            type="text",
            label="Text",
            text="Your text",
            opacity=self.slider_opacity.value() / 100.0,
            position="custom",
            x=x, y=y,
        )
        self._asset.overlays.append(ov)
        item = self._create_overlay_item(ov)
        if item:
            item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(item)
        self._update_info()

    def _apply_template(self, index: int):
        """Load overlay preset from project.default_overlays.

        Recomputes position from the stored anchor + relative offset
        so the template adapts to the current image dimensions.
        """
        if index <= 0 or not self._project or not self._asset or not self._pixmap_item:
            return
        tmpl_index = index - 1
        if tmpl_index >= len(self._project.default_overlays):
            return
        tmpl = dict(self._project.default_overlays[tmpl_index])

        # Resolve position for this image
        anchor_key = tmpl.pop("_template_position", tmpl.get("position", "custom"))
        off_x = tmpl.pop("_template_offset_x", 0)
        off_y = tmpl.pop("_template_offset_y", 0)

        ov = CanvasOverlay.from_dict(tmpl)

        # Create item first so we know its rendered size
        item = self._create_overlay_item(ov)
        if not item:
            self.combo_template.setCurrentIndex(0)
            return

        base_w = self._pixmap_item.pixmap().width()
        base_h = self._pixmap_item.pixmap().height()
        iw = item.boundingRect().width()
        ih = item.boundingRect().height()
        margin = 20
        anchor_positions = {
            "bottom-right": (base_w - iw - margin, base_h - ih - margin),
            "bottom-left": (margin, base_h - ih - margin),
            "top-right": (base_w - iw - margin, margin),
            "top-left": (margin, margin),
            "center": ((base_w - iw) / 2, (base_h - ih) / 2),
        }
        if anchor_key in anchor_positions:
            ax, ay = anchor_positions[anchor_key]
            ov.x = int(ax + off_x * base_w)
            ov.y = int(ay + off_y * base_h)
            ov.position = anchor_key
            item.setPos(ov.x, ov.y)

        item.setZValue(200 + len(self._overlay_items))
        self._overlay_items.append(item)
        self._asset.overlays.append(ov)
        self._update_info()
        self.combo_template.setCurrentIndex(0)

    # ---- slider handlers ----

    def _push_overlay_attr(self, item, attr: str, new_value, apply_cb=None,
                           description: str = ""):
        """Push a SetAttrCmd that mutates item.overlay.<attr> = new_value.
        Consecutive ticks on the same (overlay, attr) fuse into one undo."""
        ov = item.overlay
        old = getattr(ov, attr, None)
        if old == new_value:
            return
        cmd = SetAttrCmd(ov, attr, old, new_value,
                         apply_cb=lambda t, v, _it=item, _cb=apply_cb:
                             _cb(_it, v) if _cb else None,
                         description=description or f"Change {attr}")
        self._undo_stack.push(cmd)

    def _on_opacity_changed(self, value: int):
        opacity = value / 100.0
        for item in self._scene.selectedItems():
            if isinstance(item, (OverlayImageItem, OverlayTextItem)):
                self._push_overlay_attr(
                    item, "opacity", opacity,
                    apply_cb=lambda it, v: it.setOpacity(v),
                    description="Change opacity",
                )

    def _on_scale_changed(self, value: int):
        scale = value / 100.0
        for item in self._scene.selectedItems():
            if isinstance(item, OverlayImageItem):
                def _apply_scale(it, v, _self=self):
                    if _self._pixmap_item:
                        base_w = _self._pixmap_item.pixmap().width()
                        target_w = max(10, int(base_w * v))
                        pm = QPixmap(it.overlay.image_path)
                        if not pm.isNull():
                            pm = pm.scaledToWidth(
                                target_w, Qt.TransformationMode.SmoothTransformation
                            )
                            it.setPixmap(pm)
                self._push_overlay_attr(
                    item, "scale", scale,
                    apply_cb=_apply_scale,
                    description="Change scale",
                )

    def _on_selection_changed(self):
        sel = [i for i in self._scene.selectedItems()
               if isinstance(i, (OverlayImageItem, OverlayTextItem))]
        if not sel:
            self._props_row.setEnabled(False)
            return

        item = sel[0]
        ov = item.overlay
        self._props_row.setEnabled(True)

        # Block signals during bulk update
        for w in (self.slider_opacity, self.slider_scale, self.combo_position,
                  self.font_combo, self.slider_font_size, self.btn_bold,
                  self.btn_italic, self.slider_kerning, self.slider_line_height,
                  self.slider_rotation, self.slider_text_width, self.slider_outline):
            w.blockSignals(True)

        self.slider_opacity.setValue(int(ov.opacity * 100))
        self.slider_scale.setValue(int(ov.scale * 100))
        pos_text = ov.position if ov.position != "custom" else "custom (drag)"
        idx = self.combo_position.findText(pos_text)
        if idx >= 0:
            self.combo_position.setCurrentIndex(idx)
        self.font_combo.setCurrentFont(QFont(ov.font_family))
        self.slider_font_size.setValue(ov.font_size)
        self.btn_bold.setChecked(ov.bold)
        self.btn_italic.setChecked(ov.italic)
        self.slider_kerning.setValue(int(ov.letter_spacing))
        self.slider_line_height.setValue(int(getattr(ov, 'line_height', 1.2) * 100))
        self.slider_rotation.setValue(int(ov.rotation))
        self.slider_text_width.setValue(ov.text_width)
        self.slider_outline.setValue(ov.stroke_width)

        for w in (self.slider_opacity, self.slider_scale, self.combo_position,
                  self.font_combo, self.slider_font_size, self.btn_bold,
                  self.btn_italic, self.slider_kerning, self.slider_line_height,
                  self.slider_rotation, self.slider_text_width, self.slider_outline):
            w.blockSignals(False)

    # ---- drag-drop from tray ----

    def _on_file_dropped(self, path: str, scene_pos):
        """Add dropped file as a watermark overlay at the drop position."""
        if not self._asset:
            return
        ext = Path(path).suffix.lower()
        if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
            return
        ov = CanvasOverlay(
            type="watermark", label=Path(path).stem, image_path=path,
            position="custom", x=int(scene_pos.x()), y=int(scene_pos.y()),
            opacity=self.slider_opacity.value() / 100.0,
            scale=self.slider_scale.value() / 100.0,
        )
        self._add_overlay_image(ov)
        self._sync_overlays_to_asset()

    def _add_overlay_image(self, ov: CanvasOverlay):
        """Add an overlay to the asset and scene."""
        self._asset.overlays.append(ov)
        item = self._create_overlay_item(ov)
        if item:
            item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(item)
        self._update_info()

    # ---- properties row handlers ----

    def _selected_overlay_items(self):
        return [i for i in self._scene.selectedItems()
                if isinstance(i, (OverlayImageItem, OverlayTextItem))]

    def _on_position_changed(self, text: str):
        if not self._pixmap_item:
            return
        base_w = self._pixmap_item.pixmap().width()
        base_h = self._pixmap_item.pixmap().height()
        for item in self._selected_overlay_items():
            ov = item.overlay
            pos_key = text.replace(" (drag)", "")
            ov.position = pos_key
            if pos_key == "custom":
                continue
            iw = item.boundingRect().width()
            ih = item.boundingRect().height()
            margin = 20
            positions = {
                "bottom-right": (base_w - iw - margin, base_h - ih - margin),
                "bottom-left": (margin, base_h - ih - margin),
                "top-right": (base_w - iw - margin, margin),
                "top-left": (margin, margin),
                "center": ((base_w - iw) / 2, (base_h - ih) / 2),
            }
            if pos_key in positions:
                nx, ny = positions[pos_key]
                ov.x, ov.y = int(nx), int(ny)
                item.setPos(nx, ny)
        self._sync_overlays_to_asset()

    def _on_font_changed(self, font: QFont):
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "font_family", font.family(),
                    apply_cb=lambda it, _v: it._apply_font(),
                    description="Change font",
                )
        self._sync_overlays_to_asset()

    def _on_font_size_changed(self, value: int):
        self._font_size_label.setText(str(value))
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "font_size", value,
                    apply_cb=lambda it, _v: it._apply_font(),
                    description="Change font size",
                )
        self._sync_overlays_to_asset()

    def _on_bold_changed(self):
        checked = self.btn_bold.isChecked()
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "bold", checked,
                    apply_cb=lambda it, _v: it._apply_font(),
                    description=("Bold on" if checked else "Bold off"),
                )
        self._sync_overlays_to_asset()

    def _on_italic_changed(self):
        checked = self.btn_italic.isChecked()
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "italic", checked,
                    apply_cb=lambda it, _v: it._apply_font(),
                    description=("Italic on" if checked else "Italic off"),
                )
        self._sync_overlays_to_asset()

    def _on_color_pick(self):
        items = self._selected_overlay_items()
        if not items:
            return
        current = QColor(items[0].overlay.color)
        color = QColorDialog.getColor(current, self, "Overlay Color")
        if color.isValid():
            for item in items:
                if isinstance(item, OverlayTextItem):
                    self._push_overlay_attr(
                        item, "color", color.name(),
                        apply_cb=lambda it, _v: it._apply_font(),
                        description="Change text color",
                    )
            self._sync_overlays_to_asset()

    def _on_outline_color_pick(self):
        items = self._selected_overlay_items()
        if not items:
            return
        current = QColor(items[0].overlay.stroke_color or "#000000")
        color = QColorDialog.getColor(current, self, "Outline Color")
        if color.isValid():
            for item in items:
                if isinstance(item, OverlayTextItem):
                    self._push_overlay_attr(
                        item, "stroke_color", color.name(),
                        apply_cb=lambda it, _v: it.update(),
                        description="Change outline color",
                    )
                    if item.overlay.stroke_width == 0:
                        # Also bump width to 2 so the color change is visible
                        self._push_overlay_attr(
                            item, "stroke_width", 2,
                            apply_cb=lambda it, _v: it.update(),
                            description="Set outline width",
                        )
                        self.slider_outline.blockSignals(True)
                        self.slider_outline.setValue(2)
                        self.slider_outline.blockSignals(False)
            self._sync_overlays_to_asset()

    def _on_outline_changed(self, value: int):
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "stroke_width", value,
                    apply_cb=lambda it, _v: it.update(),
                    description="Change outline",
                )
        self._sync_overlays_to_asset()

    def _on_kerning_changed(self, value: int):
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "letter_spacing", float(value),
                    apply_cb=lambda it, _v: it._apply_font(),
                    description="Change kerning",
                )
        self._sync_overlays_to_asset()

    def _on_rotation_changed(self, value: int):
        for item in self._selected_overlay_items():
            def _apply_rot(it, v):
                it.setTransformOriginPoint(it.boundingRect().center())
                it.setRotation(v)
            self._push_overlay_attr(
                item, "rotation", float(value),
                apply_cb=_apply_rot, description="Rotate",
            )
        self._sync_overlays_to_asset()

    def _on_line_height_changed(self, value: int):
        lh = value / 100.0
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "line_height", lh,
                    apply_cb=lambda it, _v: it._apply_font(),
                    description="Change line height",
                )
        self._sync_overlays_to_asset()

    def _on_text_width_changed(self, value: int):
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "text_width", value,
                    apply_cb=lambda it, _v: it._apply_font(),
                    description="Change text width",
                )
        self._sync_overlays_to_asset()

    def _save_as_template(self):
        """Save selected overlay as a reusable project template.

        Converts absolute x,y to relative offsets from the position anchor
        so the template works on images of any size.
        """
        items = self._selected_overlay_items()
        if not items or not self._project or not self._pixmap_item:
            return
        item = items[0]
        ov = item.overlay
        label, ok = QInputDialog.getText(self, "Save Template", "Template label:")
        if not ok or not label.strip():
            return
        d = ov.to_dict()
        d["label"] = label.strip()

        # Compute relative offset from anchor position
        base_w = self._pixmap_item.pixmap().width()
        base_h = self._pixmap_item.pixmap().height()
        iw = item.boundingRect().width()
        ih = item.boundingRect().height()
        margin = 20
        anchor_positions = {
            "bottom-right": (base_w - iw - margin, base_h - ih - margin),
            "bottom-left": (margin, base_h - ih - margin),
            "top-right": (base_w - iw - margin, margin),
            "top-left": (margin, margin),
            "center": ((base_w - iw) / 2, (base_h - ih) / 2),
        }
        anchor_key = ov.position if ov.position in anchor_positions else "bottom-right"
        ax, ay = anchor_positions[anchor_key]
        # Store offset as fraction of image dimensions (resolution-independent)
        d["_template_position"] = anchor_key
        d["_template_offset_x"] = (ov.x - ax) / base_w if base_w else 0
        d["_template_offset_y"] = (ov.y - ay) / base_h if base_h else 0
        # Remove absolute coords — they'll be recomputed on apply
        d.pop("x", None)
        d.pop("y", None)

        self._project.default_overlays.append(d)
        self.combo_template.addItem(label.strip())

    # ---- layer panel ----

    def _rebuild_layer_panel(self):
        """Rebuild the layer list from current scene items."""
        self._layer_panel.clear()
        if not self._asset:
            return

        def _scope_tag(platforms: list[str]) -> str:
            if not platforms:
                return ""
            abbrevs = [p[:2].upper() for p in platforms[:3]]
            suffix = "+" if len(platforms) > 3 else ""
            return f" [{','.join(abbrevs)}{suffix}]"

        # Overlays (top of list = front)
        for i, ov in enumerate(reversed(self._asset.overlays)):
            if ov.type == "text":
                label = f"T  {ov.text[:20]}" if ov.text else "T  (empty text)"
            elif ov.type == "watermark":
                label = f"W  {ov.label or Path(ov.image_path).stem}"
            else:
                label = f"O  {ov.label or ov.type}"
            label += _scope_tag(ov.platforms)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ("overlay", len(self._asset.overlays) - 1 - i))
            if not ov.enabled:
                item.setForeground(Qt.GlobalColor.gray)
            self._layer_panel.addItem(item)

        # Censors
        for i, cr in enumerate(self._asset.censors):
            label = f"C  {cr.style} ({cr.w}\u00d7{cr.h}){_scope_tag(cr.platforms)}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ("censor", i))
            self._layer_panel.addItem(item)

    _refresh_layer_panel = _rebuild_layer_panel

    def _on_layer_reorder(self, *_args):
        """Remap asset.overlays + asset.censors order from the layer panel row order.

        Rules:
        - Top of the list = front (higher z, drawn on top).
        - Layer panel contains overlays first, then censors. We keep that
          band separation: if a user drags a censor above overlays (or vice
          versa), we clamp the band back after the drag so censors stay in
          the censor band.
        """
        if not self._asset:
            return
        new_overlays = []
        new_censors = []
        misordered = False
        seen_first_censor = False
        for row in range(self._layer_panel.count()):
            it = self._layer_panel.item(row)
            data = it.data(Qt.ItemDataRole.UserRole)
            if not data:
                continue
            kind, idx = data
            if kind == "overlay":
                if seen_first_censor:
                    misordered = True
                if 0 <= idx < len(self._asset.overlays):
                    new_overlays.append(self._asset.overlays[idx])
            elif kind == "censor":
                seen_first_censor = True
                if 0 <= idx < len(self._asset.censors):
                    new_censors.append(self._asset.censors[idx])

        # Overlays in list order are top-to-bottom = front-to-back. Reverse
        # so asset.overlays goes back-to-front (matches rebuild order).
        new_overlays.reverse()
        self._asset.overlays = new_overlays
        self._asset.censors = new_censors

        # Re-apply z-values on scene items
        self._reassign_layer_z_values()
        # Rebuild the panel to re-bind UserRole indices to the new order
        self._rebuild_layer_panel()

        if misordered:
            # User dragged across the band. We kept the overlays-first /
            # censors-second order; inform via status bar.
            self.info_label.setText("Layer reorder: overlays stay in front of censors")

    def _reassign_layer_z_values(self):
        """Walk overlays + censors in their new list order and set Z on scene items."""
        if not self._asset:
            return
        # Censors: Z 100..199 — bottom of list first
        for i, cr in enumerate(self._asset.censors):
            for it in self._scene.items():
                if getattr(it, "_censor_region", None) is cr:
                    it.setZValue(100 + i)
                    break
        # Overlays: Z 200..299 — bottom of list first (last overlay = highest Z = front)
        for i, ov in enumerate(self._asset.overlays):
            for it in self._scene.items():
                if getattr(it, "overlay", None) is ov:
                    it.setZValue(200 + i)
                    break

    def _on_layer_clicked(self, item):
        """Select the corresponding scene item when layer is clicked."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, idx = data
        self._scene.clearSelection()
        # Find matching scene item
        for scene_item in self._scene.items():
            if kind == "censor" and hasattr(scene_item, '_censor_region'):
                if scene_item._censor_region is self._asset.censors[idx]:
                    scene_item.setSelected(True)
                    self._view.centerOn(scene_item)
                    break
            elif kind == "overlay" and hasattr(scene_item, 'overlay'):
                if scene_item.overlay is self._asset.overlays[idx]:
                    scene_item.setSelected(True)
                    self._view.centerOn(scene_item)
                    break
        # Sync the layer props panel to the clicked layer
        self._sync_layer_props_panel(kind, idx)

    def _sync_layer_props_panel(self, kind: str, idx: int):
        """Populate the opacity + enabled controls for the selected layer."""
        if not hasattr(self, "_layer_props_widget"):
            return
        if kind == "overlay" and 0 <= idx < len(self._asset.overlays):
            ov = self._asset.overlays[idx]
            self.slider_layer_opacity.blockSignals(True)
            self.slider_layer_opacity.setValue(int(ov.opacity * 100))
            self.slider_layer_opacity.blockSignals(False)
            self.chk_layer_enabled.blockSignals(True)
            self.chk_layer_enabled.setChecked(ov.enabled)
            self.chk_layer_enabled.blockSignals(False)
            self._layer_props_widget.setEnabled(True)
            self._layer_props_selection = ("overlay", idx)
        else:
            # Censors don't have opacity/enabled in CensorRegion
            self._layer_props_widget.setEnabled(False)
            self._layer_props_selection = None

    def _on_layer_opacity_changed(self, value: int):
        sel = getattr(self, "_layer_props_selection", None)
        if not sel or sel[0] != "overlay":
            return
        _, idx = sel
        if not (0 <= idx < len(self._asset.overlays)):
            return
        ov = self._asset.overlays[idx]
        new_op = value / 100.0
        # Find the scene item + apply via SetAttrCmd for undo
        for it in self._scene.items():
            if getattr(it, "overlay", None) is ov:
                self._push_overlay_attr(
                    it, "opacity", new_op,
                    apply_cb=lambda item, v: item.setOpacity(v),
                    description="Layer opacity",
                )
                break

    def _on_layer_enabled_toggled(self, checked: bool):
        sel = getattr(self, "_layer_props_selection", None)
        if not sel or sel[0] != "overlay":
            return
        _, idx = sel
        if not (0 <= idx < len(self._asset.overlays)):
            return
        ov = self._asset.overlays[idx]
        # Find the scene item + toggle visibility and enabled flag
        for it in self._scene.items():
            if getattr(it, "overlay", None) is ov:
                def _apply_enabled(item, v):
                    item.setVisible(bool(v))
                self._push_overlay_attr(
                    it, "enabled", checked,
                    apply_cb=_apply_enabled,
                    description=("Enable layer" if checked else "Disable layer"),
                )
                break
        # Refresh the layer panel so the row renders greyed-out when disabled
        self._rebuild_layer_panel()

    # ---- sync ----

    def _sync_censors_to_asset(self):
        """Write censor items back to asset.censors."""
        if not self._asset:
            return
        self._asset.censors.clear()
        for item in self._censor_items:
            r = item.rect()
            pos = item.pos()
            self._asset.censors.append(CensorRegion(
                x=int(pos.x() + r.x()), y=int(pos.y() + r.y()),
                w=int(r.width()), h=int(r.height()),
                style=item.style,
                platforms=list(item.platforms),
            ))
        if hasattr(self, '_layer_panel'):
            self._rebuild_layer_panel()

    def _sync_overlays_to_asset(self):
        """Write overlay items back to asset.overlays."""
        if not self._asset:
            return
        self._asset.overlays.clear()
        for item in self._overlay_items:
            self._asset.overlays.append(item.overlay)
        if hasattr(self, '_layer_panel'):
            self._rebuild_layer_panel()

    # ---- actions ----

    def _delete_selected(self):
        """Remove selected censors/overlays/crops/notes from scene and model."""
        cmd = DeleteItemCmd(self)
        has_undoable = False
        for item in self._scene.selectedItems():
            if isinstance(item, CensorRectItem):
                # Build CensorRegion from current item state for undo
                r = item.rect()
                pos = item.pos()
                region = CensorRegion(
                    x=int(pos.x() + r.x()), y=int(pos.y() + r.y()),
                    w=int(r.width()), h=int(r.height()),
                    style=item.style,
                )
                cmd._censors.append((region, item))
                if item in self._censor_items:
                    self._censor_items.remove(item)
                has_undoable = True
            elif isinstance(item, (OverlayImageItem, OverlayTextItem)):
                cmd._overlays.append((item.overlay, item))
                if item in self._overlay_items:
                    self._overlay_items.remove(item)
                has_undoable = True
            elif isinstance(item, ResizableCropItem):
                self._scene.removeItem(item)
                if item in self._crop_items:
                    self._crop_items.remove(item)
                if self._asset:
                    self._asset.crops = [c for c in self._asset.crops if c.label != item.label]
            elif isinstance(item, NoteRectItem):
                self._scene.removeItem(item)
                if item in self._notes:
                    self._notes.remove(item)
                self._save_notes_to_asset()
            elif isinstance(item, (AnnotationTextItem, QGraphicsRectItem, QGraphicsLineItem)):
                self._scene.removeItem(item)
        if has_undoable:
            self._undo_stack.push(cmd)
        self._sync_censors_to_asset()
        self._sync_overlays_to_asset()
        self._update_info()

    def _remove_censor_item(self, item: CensorRectItem):
        """Remove a single censor item from scene + model (for context menu)."""
        self._scene.removeItem(item)
        if item in self._censor_items:
            self._censor_items.remove(item)
        self._sync_censors_to_asset()
        self._update_info()

    def _remove_overlay_item(self, item):
        """Remove a single overlay item from scene + model (for context menu)."""
        self._scene.removeItem(item)
        if item in self._overlay_items:
            self._overlay_items.remove(item)
        self._sync_overlays_to_asset()
        self._update_info()

    def _duplicate_overlay_item(self, item):
        """Duplicate an overlay item with 20px offset (for context menu / Ctrl+D)."""
        if not self._asset:
            return
        ov_copy = copy.copy(item.overlay)
        ov_copy.x += 20
        ov_copy.y += 20
        self._asset.overlays.append(ov_copy)
        new_item = self._create_overlay_item(ov_copy)
        if new_item:
            new_item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(new_item)
        self._update_info()

    def _duplicate_selected(self):
        """Duplicate all selected overlay items."""
        for item in list(self._scene.selectedItems()):
            if isinstance(item, (OverlayImageItem, OverlayTextItem)):
                self._duplicate_overlay_item(item)

    # ---- alignment + distribute ----

    def _show_align_menu(self):
        """Dropdown from the Align toolbar button with 6 alignment actions."""
        from PySide6.QtWidgets import QMenu
        menu = _themed_menu(self)
        a_left = menu.addAction("Align Left")
        a_right = menu.addAction("Align Right")
        a_top = menu.addAction("Align Top")
        a_bottom = menu.addAction("Align Bottom")
        menu.addSeparator()
        a_ch = menu.addAction("Center Horizontal")
        a_cv = menu.addAction("Center Vertical")
        menu.addSeparator()
        a_dh = menu.addAction("Distribute Horizontal")
        a_dv = menu.addAction("Distribute Vertical")
        # Anchor below the button
        pos = self.btn_align.mapToGlobal(self.btn_align.rect().bottomLeft())
        chosen = menu.exec(pos)
        if chosen is a_left:
            self._align_selected("left")
        elif chosen is a_right:
            self._align_selected("right")
        elif chosen is a_top:
            self._align_selected("top")
        elif chosen is a_bottom:
            self._align_selected("bottom")
        elif chosen is a_ch:
            self._align_selected("center_h")
        elif chosen is a_cv:
            self._align_selected("center_v")
        elif chosen is a_dh:
            self._distribute_selected("h")
        elif chosen is a_dv:
            self._distribute_selected("v")

    def _alignable_items(self):
        """Return selected items we can align/distribute (overlays, censors, crops, notes)."""
        return [it for it in self._scene.selectedItems()
                if isinstance(it, (OverlayImageItem, OverlayTextItem,
                                   CensorRectItem, ResizableCropItem, NoteRectItem))]

    def _align_selected(self, edge: str):
        items = self._alignable_items()
        if len(items) < 2:
            self.info_label.setText("Select 2+ items to align")
            return
        rects = [it.sceneBoundingRect() for it in items]
        if edge == "left":
            target = min(r.left() for r in rects)
            for it, r in zip(items, rects):
                it.moveBy(target - r.left(), 0)
        elif edge == "right":
            target = max(r.right() for r in rects)
            for it, r in zip(items, rects):
                it.moveBy(target - r.right(), 0)
        elif edge == "top":
            target = min(r.top() for r in rects)
            for it, r in zip(items, rects):
                it.moveBy(0, target - r.top())
        elif edge == "bottom":
            target = max(r.bottom() for r in rects)
            for it, r in zip(items, rects):
                it.moveBy(0, target - r.bottom())
        elif edge == "center_h":
            target = sum(r.center().x() for r in rects) / len(rects)
            for it, r in zip(items, rects):
                it.moveBy(target - r.center().x(), 0)
        elif edge == "center_v":
            target = sum(r.center().y() for r in rects) / len(rects)
            for it, r in zip(items, rects):
                it.moveBy(0, target - r.center().y())
        self._sync_after_align(items)

    def _distribute_selected(self, axis: str):
        items = self._alignable_items()
        if len(items) < 3:
            self.info_label.setText("Select 3+ items to distribute")
            return
        pairs = [(it, it.sceneBoundingRect()) for it in items]
        if axis == "h":
            pairs.sort(key=lambda p: p[1].center().x())
            xs = [p[1].center().x() for p in pairs]
            span = xs[-1] - xs[0]
            if span <= 0:
                return
            step = span / (len(pairs) - 1)
            for i, (it, r) in enumerate(pairs[1:-1], start=1):
                target = xs[0] + step * i
                it.moveBy(target - r.center().x(), 0)
        else:  # v
            pairs.sort(key=lambda p: p[1].center().y())
            ys = [p[1].center().y() for p in pairs]
            span = ys[-1] - ys[0]
            if span <= 0:
                return
            step = span / (len(pairs) - 1)
            for i, (it, r) in enumerate(pairs[1:-1], start=1):
                target = ys[0] + step * i
                it.moveBy(0, target - r.center().y())
        self._sync_after_align(items)

    def _sync_after_align(self, items):
        """Write mutated positions back to asset data."""
        overlay_moved = False
        censor_moved = False
        crop_moved = False
        note_moved = False
        for it in items:
            if isinstance(it, (OverlayImageItem, OverlayTextItem)):
                it.overlay.x = int(it.pos().x())
                it.overlay.y = int(it.pos().y())
                overlay_moved = True
            elif isinstance(it, CensorRectItem):
                censor_moved = True
            elif isinstance(it, ResizableCropItem):
                crop_moved = True
                if getattr(it, "on_changed", None):
                    it.on_changed(it)
            elif isinstance(it, NoteRectItem):
                note_moved = True
        if overlay_moved:
            self._sync_overlays_to_asset()
        if censor_moved:
            self._sync_censors_to_asset()
        if note_moved:
            self._save_notes_to_asset()

    # ---- copy / paste ----

    _CLIPBOARD_MIME = "application/x-doxyedit-scene-items"
    _CLIPBOARD_SCHEMA = 1

    def _copy_selected_items(self):
        """Copy selected overlay and censor items to the system clipboard.

        Serialized as JSON under a custom MIME type. Uses a schema version
        so future format changes can bump and reject older payloads.
        """
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QMimeData
        from dataclasses import asdict
        overlays, censors = [], []
        for it in self._scene.selectedItems():
            if isinstance(it, (OverlayImageItem, OverlayTextItem)):
                overlays.append(it.overlay.to_dict())
            elif isinstance(it, CensorRectItem):
                cr = getattr(it, "_censor_region", None)
                if cr:
                    censors.append(asdict(cr))
        if not overlays and not censors:
            return
        payload = {
            "_schema": self._CLIPBOARD_SCHEMA,
            "overlays": overlays,
            "censors": censors,
        }
        mime = QMimeData()
        mime.setData(self._CLIPBOARD_MIME,
                     json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        QApplication.clipboard().setMimeData(mime)
        n = len(overlays) + len(censors)
        self.info_label.setText(f"Copied {n} item(s)")

    def _paste_items_from_clipboard(self):
        """Paste previously-copied overlays + censors, offset 20px from originals."""
        from PySide6.QtWidgets import QApplication
        mime = QApplication.clipboard().mimeData()
        if not mime.hasFormat(self._CLIPBOARD_MIME):
            return
        if not self._asset:
            return
        try:
            raw = bytes(mime.data(self._CLIPBOARD_MIME)).decode("utf-8")
            payload = json.loads(raw)
        except Exception:
            return
        if payload.get("_schema") != self._CLIPBOARD_SCHEMA:
            self.info_label.setText("Clipboard schema mismatch")
            return
        OFFSET = 20
        pasted = 0
        # Overlays
        for od in payload.get("overlays", []):
            try:
                ov = CanvasOverlay.from_dict(od)
                ov.x = int(ov.x) + OFFSET
                ov.y = int(ov.y) + OFFSET
                self._asset.overlays.append(ov)
                new_item = self._create_overlay_item(ov)
                if new_item:
                    new_item.setZValue(200 + len(self._overlay_items))
                    self._overlay_items.append(new_item)
                    pasted += 1
            except Exception:
                continue
        # Censors
        for cd in payload.get("censors", []):
            try:
                cr = CensorRegion(**cd)
                cr.x = int(cr.x) + OFFSET
                cr.y = int(cr.y) + OFFSET
                self._asset.censors.append(cr)
                item = CensorRectItem(
                    QRectF(cr.x, cr.y, cr.w, cr.h),
                    cr.style, theme=self._theme,
                )
                item._censor_region = cr
                item.setZValue(100 + len(self._censor_items))
                self._scene.addItem(item)
                self._censor_items.append(item)
                pasted += 1
            except Exception:
                continue
        if pasted:
            self._rebuild_layer_panel()
            self.info_label.setText(f"Pasted {pasted} item(s)")

    def _toggle_overlay_visibility(self):
        """Toggle visibility of all censor + overlay items."""
        self._overlays_visible = not self._overlays_visible
        for item in self._censor_items:
            item.setVisible(self._overlays_visible)
        for item in self._overlay_items:
            item.setVisible(self._overlays_visible)

    def _queue_current(self):
        if self._asset:
            self.queue_requested.emit(self._asset.id)

    def _export_preview(self):
        """Render censors + overlays via PIL and save."""
        if not self._asset:
            return
        self._sync_censors_to_asset()
        self._sync_overlays_to_asset()

        src_path = Path(self._asset.source_path)
        from doxyedit.imaging import load_image_for_export
        img = load_image_for_export(str(src_path))

        img = apply_censors(img, self._asset.censors)
        img = apply_overlays(img, self._asset.overlays)

        if self._project_path:
            from doxyedit.imaging import get_export_dir
            export_dir = get_export_dir(self._project_path)
            stem = src_path.stem
            if stem.isdigit() and src_path.parent.name:
                stem = f"{src_path.parent.name}_{stem}"
            out = export_dir / f"{stem}_studio_preview.png"
            img.save(str(out))
            self.info_label.setText(f"Exported: {stem}_studio_preview.png")
            self._open_export_folder(export_dir)
        else:
            default_name = f"{src_path.stem}_studio_preview.png"
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Studio Preview", default_name,
                "PNG (*.png);;JPEG (*.jpg);;All Files (*)",
            )
            if path:
                img.save(path)
                self.info_label.setText(f"Exported: {Path(path).name}")

    def _export_current_platform(self):
        """Export the currently selected crop combo platform slot."""
        if not self._asset or not self._project:
            self.info_label.setText("No asset or project loaded")
            return
        data = self._crop_combo.currentData()
        if not data or not isinstance(data, (list, tuple)) or len(data) < 4:
            self.info_label.setText("Select a platform slot in the crop dropdown first")
            return
        self._sync_censors_to_asset()
        self._sync_overlays_to_asset()

        platform_id, slot_name = data[0], data[1]

        from doxyedit.pipeline import prepare_for_platform
        from doxyedit.imaging import get_export_dir
        output_dir = str(get_export_dir(self._project_path)) if self._project_path else ""
        try:
            r = prepare_for_platform(
                self._asset, platform_id, self._project,
                slot_name=slot_name, output_dir=output_dir,
            )
        except Exception as e:
            self.info_label.setText(f"Export crashed: {e}")
            import traceback; traceback.print_exc()
            return
        if r.success:
            self._asset.variant_exports[f"{platform_id}_{slot_name}"] = r.output_path
            self.info_label.setText(f"Exported: {platform_id}/{slot_name} ({r.width}×{r.height})")
            self._populate_preview_strip([r])
            if self._project_path:
                self._open_export_folder(Path(r.output_path).parent)
        else:
            self.info_label.setText(f"Export failed: {r.error}")
            print(f"[Export Platform] FAILED: {r.error}")

    def _export_all_platforms(self):
        """Batch export all platform variants for the current asset."""
        if not self._asset or not self._project:
            return
        self._sync_censors_to_asset()
        self._sync_overlays_to_asset()

        from doxyedit.models import PLATFORMS
        from doxyedit.pipeline import prepare_for_platform
        from doxyedit.imaging import get_export_dir
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QCoreApplication

        output_dir = str(get_export_dir(self._project_path)) if self._project_path else ""

        if not self._asset.crops and not self._asset.censors and not self._asset.overlays:
            self.info_label.setText("Nothing to export — no crops, censors, or overlays")
            return

        from doxyedit.imaging import load_image_for_export
        from doxyedit.exporter import apply_censors, apply_overlays

        src_path = Path(self._asset.source_path)
        stem = src_path.stem
        if stem.isdigit() and src_path.parent.name:
            stem = f"{src_path.parent.name}_{stem}"
        out_base = Path(output_dir) if output_dir else Path("_exports")
        out_base.mkdir(parents=True, exist_ok=True)

        total = len(self._asset.crops) + 2  # +2 for full + censored
        progress = QProgressDialog("Exporting...", "Cancel", 0, total, self)
        progress.setWindowTitle("Export All")
        progress.setMinimumDuration(300)
        progress.setModal(True)
        step = 0

        # --- 1. Full image with ALL overlays (no crop) ---
        progress.setLabelText("Full image with overlays...")
        QCoreApplication.processEvents()
        try:
            img_full = load_image_for_export(str(src_path))
            all_overlays = [ov for ov in self._asset.overlays if not ov.platforms]
            if all_overlays:
                img_full = apply_overlays(img_full, all_overlays, str(src_path.parent))
            img_full.save(str(out_base / f"{stem}_full.png"), "PNG")
        except Exception as e:
            print(f"[Export All] full image failed: {e}")
        step += 1
        progress.setValue(step)

        # --- 2. Censored full image (all censors + overlays, no crop) ---
        if not progress.wasCanceled():
            progress.setLabelText("Censored full image...")
            QCoreApplication.processEvents()
            try:
                img_cens = load_image_for_export(str(src_path))
                if self._asset.censors:
                    img_cens = apply_censors(img_cens, self._asset.censors)
                all_overlays = [ov for ov in self._asset.overlays if not ov.platforms]
                if all_overlays:
                    img_cens = apply_overlays(img_cens, all_overlays, str(src_path.parent))
                img_cens.save(str(out_base / f"{stem}_censored.png"), "PNG")
            except Exception as e:
                print(f"[Export All] censored full failed: {e}")
        step += 1
        progress.setValue(step)

        # --- 3. One export per crop drawn on the asset ---
        crop_count = 0
        for ci, crop in enumerate(self._asset.crops):
            if progress.wasCanceled():
                break
            step += 1
            progress.setValue(step)
            crop_name = crop.label.strip() if crop.label.strip() and crop.label.strip() != "free" else f"crop_{ci+1}"
            progress.setLabelText(f"Cropping: {crop_name}...")
            QCoreApplication.processEvents()
            try:
                img_crop = load_image_for_export(str(src_path))
                # Resolve this crop's platform scope. Prefer the first-class
                # platform_id (H3.1). Fall back to label for legacy crops.
                crop_platform = getattr(crop, "platform_id", "") or ""
                crop_lbl = crop.label.strip().lower()

                def _crop_scope_matches(scope_list: list[str]) -> bool:
                    """True if the overlay/censor's platform scope includes this crop."""
                    if not scope_list:
                        return True  # no scope → applies to all
                    if crop_platform:
                        return crop_platform in scope_list
                    # Legacy crop: fall back to label-based match
                    for p in scope_list:
                        pl = p.lower()
                        if pl == crop_lbl or crop_lbl in pl or pl in crop_lbl:
                            return True
                    return False

                applicable_censors = [cr for cr in self._asset.censors
                                      if _crop_scope_matches(cr.platforms)]
                if applicable_censors:
                    img_crop = apply_censors(img_crop, applicable_censors)
                applicable_overlays = [ov for ov in self._asset.overlays
                                       if _crop_scope_matches(ov.platforms)]
                if applicable_overlays:
                    img_crop = apply_overlays(img_crop, applicable_overlays, str(src_path.parent))
                # Crop
                img_crop = img_crop.crop((crop.x, crop.y, crop.x + crop.w, crop.y + crop.h))
                out_path = out_base / f"{stem}_{crop_name}.png"
                img_crop.save(str(out_path), "PNG")
                crop_count += 1
            except Exception as e:
                print(f"[Export All] crop {crop_name} failed: {e}")
                import traceback; traceback.print_exc()

        progress.setValue(total)

        msg = f"Exported: full + censored + {crop_count} crop(s)"
        self.info_label.setText(msg)
        self._rebuild_layer_panel()
        self._show_filmstrip_from_files(out_base, stem)
        if self._project_path:
            self._open_export_folder(get_export_dir(self._project_path))

    @staticmethod
    def _open_export_folder(folder: Path):
        """Open the export folder in the system file manager."""
        import subprocess
        subprocess.Popen(
            ["explorer", str(folder)],
            creationflags=0x08000000, encoding="utf-8", errors="replace",
        )

    def _populate_preview_strip(self, results):
        """Fill the preview strip with thumbnails from export results."""
        # Clear old thumbnails
        while self._preview_strip_layout.count():
            item = self._preview_strip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        from doxyedit.models import PLATFORMS
        thumb_h = self._preview_thumb_h
        any_shown = False
        for r in results:
            if not r.success or not r.output_path:
                continue
            p = Path(r.output_path)
            if not p.exists():
                continue
            pm = QPixmap(str(p))
            if pm.isNull():
                continue
            pm = pm.scaledToHeight(thumb_h, Qt.TransformationMode.SmoothTransformation)
            frame = QWidget()
            frame.setObjectName("studio_preview_thumb")
            vl = QVBoxLayout(frame)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(2)
            img_label = QLabel()
            img_label.setPixmap(pm)
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vl.addWidget(img_label)
            plat = PLATFORMS.get(r.platform_id)
            name = plat.name if plat else r.platform_id
            txt = QLabel(f"{name}\n{r.width}×{r.height}")
            txt.setObjectName("studio_preview_thumb_label")
            txt.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vl.addWidget(txt)
            self._preview_strip_layout.addWidget(frame)
            any_shown = True

        self._preview_strip_layout.addStretch()
        self._preview_strip_scroll.setVisible(any_shown)

    def _show_filmstrip_from_files(self, folder: Path, stem: str):
        """Show filmstrip from exported files matching the stem."""
        while self._preview_strip_layout.count():
            item = self._preview_strip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        thumb_h = self._preview_thumb_h
        any_shown = False
        for f in sorted(folder.glob(f"{stem}*.png")):
            pm = QPixmap(str(f))
            if pm.isNull():
                continue
            pm = pm.scaledToHeight(thumb_h, Qt.TransformationMode.SmoothTransformation)
            frame = QWidget()
            frame.setObjectName("studio_preview_thumb")
            vl = QVBoxLayout(frame)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(2)
            img_label = QLabel()
            img_label.setPixmap(pm)
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vl.addWidget(img_label)
            txt = QLabel(f.stem.replace(f"{stem}_", ""))
            txt.setObjectName("studio_preview_thumb_label")
            txt.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vl.addWidget(txt)
            self._preview_strip_layout.addWidget(frame)
            any_shown = True
        self._preview_strip_layout.addStretch()
        self._preview_strip_scroll.setVisible(any_shown)

    # ---- helpers ----

    def _update_info(self):
        if not self._asset:
            self.info_label.setText("No image loaded")
            return
        name = Path(self._asset.source_path).name
        nc = len(self._censor_items)
        no = len(self._overlay_items)
        self.info_label.setText(f"{name} — {nc} censor, {no} overlay")
