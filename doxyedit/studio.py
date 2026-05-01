"""StudioEditor widget — the main Studio panel (canvas + toolbar + dialogs).

Graphics item classes, undo commands, and shared helpers live in
doxyedit.studio_items.
"""
# Re-export names from studio_items so any existing code importing from
# doxyedit.studio keeps working. Anything defined in studio_items is
# available via `from doxyedit.studio import X`.
from doxyedit.studio_items import *  # noqa: F401,F403
from doxyedit.studio_items import (
    STUDIO_GRID_SPACING, STUDIO_GRID_PEN_ALPHA, STUDIO_GRID_PEN_WIDTH,
    STUDIO_RESIZE_HANDLE_SIZE, STUDIO_ZOOM_BTN_WIDTH_RATIO,
    STUDIO_ZOOM_LABEL_WIDTH_RATIO, STUDIO_LAYER_PANEL_WIDTH,
    TAG_COLORS, TAG_COLOR_HEX, TAG_COLOR_ORDER,
    StudioTool,
    CensorRectItem, OverlayImageItem, OverlayShapeItem, OverlayArrowItem,
    OverlayTextItem, AnnotationTextItem,
    AddCensorCmd, SetAttrCmd, SetZValueCmd, DeleteItemCmd,
    _OVERLAY_ITEM_TYPES, _SELECTABLE_ITEM_TYPES, _CANVAS_ITEM_TYPES,
    _attach_ctx_menu, _themed_menu,
    _add_platform_submenu, _resolve_platform_menu,
)

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
    QSizePolicy, QFrame,
)
from PySide6.QtCore import (
    Qt, QRectF, QPointF, QLineF, Signal, QSettings, QSize,
    QEvent, QMimeData, QTimer, QRunnable, QThreadPool, QObject,
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QBrush, QPen, QFont, QWheelEvent,
    QKeyEvent, QTransform, QUndoCommand, QUndoStack, QIcon,
    QPolygonF, QPainterPath, QImage, QShortcut, QKeySequence,
    QTextCursor, QLinearGradient, QRadialGradient, QTextOption,
    QTextBlockFormat, QCursor,
)
import bisect
import copy
import json
import math
import os
import re
import subprocess
import uuid
from PIL import Image

from doxyedit.models import Asset, Project, CensorRegion, CanvasOverlay, CropRegion, PLATFORMS
from doxyedit.exporter import apply_censors, apply_overlays
from doxyedit.imaging import pil_to_qimage, qimage_to_pil
from doxyedit.preview import NoteRectItem, ResizableCropItem, HoverPreview
from doxyedit.themes import THEMES, DEFAULT_THEME

# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------

class StudioScene(QGraphicsScene):
    """Scene with tool-aware mouse handling for censor/annotation drawing."""

    # Smart-guide tuning. Snap proximity; 0 = snap off.

    def __init__(self, parent=None):
        super().__init__(parent)
        # Flat linear scan is faster than BSP maintenance for our typical
        # item counts (<50 overlays + 1 base + 1 checker). The BSP index
        # rebuilds itself on every item move — dominant during drags.
        self.setItemIndexMethod(
            QGraphicsScene.ItemIndexMethod.NoIndex)
        # Snap threshold cached — previously a @property that hit
        # QSettings on every drag frame via _compute_snap_guides.
        # Refresh via reload_snap_threshold() when the Snap Proximity
        # menu/dialog updates the setting.
        self.SNAP_THRESHOLD_PX = QSettings(
            "DoxyEdit", "DoxyEdit").value(
                "studio_snap_threshold_px", 0, type=int)
        self._grid_visible = False
        # Thirds-grid overlay; toggled from the Studio settings dialog
        # via setter on the scene. Pre-initialized so drawForeground's
        # per-paint `_thirds_visible` read is direct attribute access
        # instead of getattr-with-default.
        self._thirds_visible = False
        self._grid_spacing = STUDIO_GRID_SPACING
        self._theme = THEMES[DEFAULT_THEME]
        self.setBackgroundBrush(QBrush(QColor(self._theme.bg_deep)))

        self.current_tool = StudioTool.SELECT
        self._draw_start: QPointF | None = None
        self._temp_item = None
        self._censor_style = "black"

        # Smart snap guides — populated during drag, drawn in drawForeground,
        # cleared on release.
        self._snap_guides: list[tuple[float, float, float, float]] = []

        # Callbacks set by StudioEditor
        self.on_arrow_finished = None    # callable(QLineF)
        self.on_shape_finished = None    # callable(QRectF, str)
        self.on_censor_finished = None   # callable(CensorRectItem)
        self.on_annotation_placed = None  # callable(item)
        self.on_crop_finished = None     # callable(QRectF)
        self.on_note_finished = None     # callable(QRectF, NoteRectItem)
        self.on_text_overlay_placed = None  # callable(QPointF)
        self.get_crop_aspect = None      # callable() -> float | None

    def reload_snap_threshold(self):
        self.SNAP_THRESHOLD_PX = QSettings(
            "DoxyEdit", "DoxyEdit").value(
                "studio_snap_threshold_px", 0, type=int)

    def set_theme(self, theme):
        self._theme = theme
        # Respect user-overridden bg color if one is saved
        saved = QSettings("DoxyEdit", "DoxyEdit").value("studio_bg_color", "", type=str)
        if saved:
            self.setBackgroundBrush(QBrush(QColor(saved)))
        else:
            self.setBackgroundBrush(QBrush(QColor(theme.bg_deep)))
        # Repaint so the grid picks up the theme's accent_dim color
        self.update()

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

    # URL drops (tray items) — don't let the scene swallow the event.
    # Ignore so the QGraphicsView's override handles it end-to-end.
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.ignore()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.ignore()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.ignore()
            return
        super().dropEvent(event)

    def drawForeground(self, painter, rect):
        """Draw snap grid, rule-of-thirds, and smart-guide overlay.

        Early-out when all helpers are off — this method runs on every
        paint (so: every drag-mousemove frame). Skipping the method body
        removes ~5 attribute reads + super() dispatch per frame on the
        common case where the user isn't showing any guides.
        """
        if (not self._grid_visible
                and not self._thirds_visible
                and not self._snap_guides):
            return
        super().drawForeground(painter, rect)
        _t = self._theme
        if self._grid_visible:
            # Use the active theme's accent_dim for grid lines so grid
            # colors harmonize with the palette.
            grid_color = QColor(_t.accent_dim)
            grid_color.setAlpha(STUDIO_GRID_PEN_ALPHA)
            pen = QPen(grid_color, STUDIO_GRID_PEN_WIDTH)
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
        # Rule-of-thirds grid — only drawn when enabled AND a pixmap is
        # present so the thirds reflect the image bounds, not the full scene.
        if self._thirds_visible:
            img_rect = None
            for it in self.items():
                if isinstance(it, QGraphicsPixmapItem):
                    img_rect = it.sceneBoundingRect()
                    break
            if img_rect is not None:
                thirds_color = QColor(_t.studio_thirds_guide)
                thirds_color.setAlpha(_t.studio_thirds_guide_alpha)
                pen = QPen(thirds_color, _t.studio_thirds_guide_pen_width,
                           Qt.PenStyle.DashLine)
                painter.setPen(pen)
                x1 = img_rect.left() + img_rect.width() / 3
                x2 = img_rect.left() + 2 * img_rect.width() / 3
                y1 = img_rect.top() + img_rect.height() / 3
                y2 = img_rect.top() + 2 * img_rect.height() / 3
                painter.drawLine(int(x1), int(img_rect.top()),
                                  int(x1), int(img_rect.bottom()))
                painter.drawLine(int(x2), int(img_rect.top()),
                                  int(x2), int(img_rect.bottom()))
                painter.drawLine(int(img_rect.left()), int(y1),
                                  int(img_rect.right()), int(y1))
                painter.drawLine(int(img_rect.left()), int(y2),
                                  int(img_rect.right()), int(y2))

        # Smart snap guides: dashed magenta lines drawn during drag
        if self._snap_guides:
            guide_color = QColor(_t.studio_scene_align_guide)
            guide_color.setAlpha(_t.studio_scene_align_guide_alpha)
            guide_pen = QPen(guide_color, _t.studio_scene_align_guide_pen_width,
                             Qt.PenStyle.DashLine)
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
            # Cache self.views() — Qt allocates a fresh list each call
            # and we were calling it up to 5 times in this block.
            views = self.views()
            view0 = views[0] if views else None
            item_under = self.itemAt(
                pos,
                view0.transform() if view0 is not None else QTransform())
            if item_under is None:
                if view0 is not None and hasattr(view0, '_studio_editor'):
                    view0._studio_editor._nuclear_clear()
            # Alt+click on a draggable item — duplicate it in place, then
            # Qt will drag the duplicate (Photoshop / Figma convention).
            if (item_under is not None
                    and (event.modifiers() & Qt.KeyboardModifier.AltModifier)
                    and view0 is not None
                    and hasattr(view0, "_studio_editor")):
                editor = view0._studio_editor
                # Walk up to the top-level item (resize handles are children)
                top = item_under
                while top.parentItem() is not None:
                    top = top.parentItem()
                if isinstance(top, (OverlayImageItem, OverlayTextItem)):
                    editor._duplicate_overlay_item(top)
                elif isinstance(top, OverlayArrowItem):
                    editor._duplicate_arrow_item(top)
                elif isinstance(top, OverlayShapeItem):
                    editor._duplicate_shape_item(top)
                elif isinstance(top, CensorRectItem):
                    editor._duplicate_censor_item(top)
                # New item is added at top-of-stack; select it so the drag
                # propagates naturally.
                self.clearSelection()
                if editor._overlay_items and isinstance(top, _OVERLAY_ITEM_TYPES):
                    editor._overlay_items[-1].setSelected(True)
                elif editor._censor_items and isinstance(top, CensorRectItem):
                    editor._censor_items[-1].setSelected(True)
                # User feedback: announce that a copy was made so the
                # user isn't confused why the original 'jumped'.
                if hasattr(editor, "info_label"):
                    _kind = type(top).__name__.replace(
                        "Overlay", "").replace("Item", "")
                    editor.info_label.setText(
                        f"Alt-dragged duplicate: {_kind}")
                return
            return super().mousePressEvent(event)

        if self.current_tool == StudioTool.EYEDROPPER:
            # Sample the pixmap pixel under the cursor and send the color
            # back to the editor.
            editor = None
            if self.views():
                editor = getattr(self.views()[0], "_studio_editor", None)
            if editor is not None and editor._pixmap_item is not None:
                pix = editor._pixmap_item.pixmap()
                img = pix.toImage()
                px = int(pos.x())
                py = int(pos.y())
                if 0 <= px < img.width() and 0 <= py < img.height():
                    c = img.pixelColor(px, py)
                    editor._apply_picked_color(c)
            # Return to SELECT after a pick — Photoshop convention
            self.set_tool(StudioTool.SELECT)
            if self.views():
                self.views()[0].setCursor(Qt.CursorShape.ArrowCursor)
            return

        if self.current_tool == StudioTool.CENSOR:
            self._draw_start = pos
            self._temp_item = CensorRectItem(
                QRectF(pos, pos), self._censor_style
            )
            self._temp_item.setZValue(150)
            self.addItem(self._temp_item)
            return

        if self.current_tool == StudioTool.ARROW:
            self._draw_start = pos
            self._temp_item = QGraphicsLineItem(QLineF(pos, pos))
            pen = QPen(QColor(self._theme.studio_temp_arrow),
                       self._theme.studio_temp_arrow_pen_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            self._temp_item.setPen(pen)
            self._temp_item.setZValue(300)
            self.addItem(self._temp_item)
            return

        if self.current_tool in (StudioTool.SHAPE_RECT, StudioTool.SHAPE_ELLIPSE):
            self._draw_start = pos
            self._temp_item = QGraphicsRectItem(QRectF(pos, pos))
            pen = QPen(QColor(self._theme.studio_temp_shape),
                       self._theme.studio_temp_shape_pen_width)
            self._temp_item.setPen(pen)
            self._temp_item.setBrush(Qt.BrushStyle.NoBrush)
            self._temp_item.setZValue(300)
            self.addItem(self._temp_item)
            return

        if self.current_tool == StudioTool.CROP:
            self._draw_start = pos
            self._temp_item = QGraphicsRectItem(QRectF(pos, pos))
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
            # Start a drag-to-size rubber band; classified on release as
            # either a click-place (short drag) or a sized text box.
            self._draw_start = pos
            self._temp_item = QGraphicsRectItem(QRectF(pos, pos))
            _dt = THEMES[DEFAULT_THEME]
            pen = QPen(QColor(_dt.accent), 1, Qt.PenStyle.DashLine)
            self._temp_item.setPen(pen)
            self._temp_item.setBrush(Qt.BrushStyle.NoBrush)
            self._temp_item.setZValue(400)
            self.addItem(self._temp_item)
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
        # Early-out when snap is disabled (threshold 0 is the default).
        # Otherwise we iterate every scene item TWICE per mousemove frame
        # — O(N) per drag frame with zero observable effect.
        if self.SNAP_THRESHOLD_PX <= 0:
            return 0.0, 0.0, []
        mb = moving_item.sceneBoundingRect()
        m_edges_x = [mb.left(), mb.center().x(), mb.right()]
        m_edges_y = [mb.top(), mb.center().y(), mb.bottom()]

        candidates_x = []  # list of (target_x, y_range_lo, y_range_hi)
        candidates_y = []  # list of (target_y, x_range_lo, x_range_hi)

        # Single scene-walk — prior code called self.items() three times
        # (canvas center, overlays, guide lines) which allocates a fresh
        # list of every scene item each time. With many overlays + guides
        # that's 3*N allocation + iteration per drag frame with snap on.
        _snap_types = (OverlayImageItem, OverlayTextItem,
                       OverlayArrowItem, OverlayShapeItem,
                       CensorRectItem, ResizableCropItem,
                       NoteRectItem)
        canvas_found = False
        for it in self.items():
            if it is moving_item or it.parentItem() is not None:
                continue
            if isinstance(it, QGraphicsPixmapItem):
                pm = it.sceneBoundingRect()
                if not canvas_found:
                    candidates_x.append((pm.center().x(), pm.top(), pm.bottom()))
                    candidates_y.append((pm.center().y(), pm.left(), pm.right()))
                    canvas_found = True
                # Also treat the canvas edges as snap targets
                for x in (pm.left(), pm.center().x(), pm.right()):
                    candidates_x.append((x, pm.top(), pm.bottom()))
                for y in (pm.top(), pm.center().y(), pm.bottom()):
                    candidates_y.append((y, pm.left(), pm.right()))
            elif isinstance(it, _GuideLineItem):
                line = it.line()
                off = it.pos()
                if getattr(it, "_guide_orientation", 'h') == 'v':
                    candidates_x.append((line.x1() + off.x(),
                                          line.y1() + off.y(),
                                          line.y2() + off.y()))
                else:
                    candidates_y.append((line.y1() + off.y(),
                                          line.x1() + off.x(),
                                          line.x2() + off.x()))
            elif isinstance(it, _snap_types):
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
            if isinstance(grabber, _CANVAS_ITEM_TYPES):
                # Let Qt move it first, then snap
                super().mouseMoveEvent(event)
                dx, dy, guides = self._compute_snap_guides(grabber)
                # Fallback to grid-snap when no item-edge snap fired and the
                # grid is visible. Aligns the item's top-left to the nearest
                # grid cell; smart-guides still win when applicable.
                if self._grid_visible and dx == 0 and dy == 0 and self._grid_spacing > 0:
                    mb = grabber.sceneBoundingRect()
                    gs = self._grid_spacing
                    dx = round(mb.left() / gs) * gs - mb.left()
                    dy = round(mb.top() / gs) * gs - mb.top()
                if dx or dy:
                    grabber.moveBy(dx, dy)
                if guides != self._snap_guides:
                    self._snap_guides = guides
                    self.update()
                return
        if self._draw_start and self._temp_item:
            pos = event.scenePos()
            # Live-feedback: width x height for rects, length for lines, shown
            # through the editor's info label.
            editor = None
            if self.views():
                editor = getattr(self.views()[0], "_studio_editor", None)
            if editor is not None:
                w = abs(int(pos.x() - self._draw_start.x()))
                h = abs(int(pos.y() - self._draw_start.y()))
                if isinstance(self._temp_item, QGraphicsLineItem):
                    length = int(math.hypot(w, h))
                    editor.info_label.setText(f"Length: {length}px")
                else:
                    editor.info_label.setText(f"Size: {w}x{h}")
            if isinstance(self._temp_item, QGraphicsLineItem):
                # Shift constrains arrow direction to 45° steps
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    dx = pos.x() - self._draw_start.x()
                    dy = pos.y() - self._draw_start.y()
                    length = math.hypot(dx, dy)
                    if length > 0:
                        angle = math.atan2(dy, dx)
                        step = math.pi / 4  # 45° in radians
                        angle = round(angle / step) * step
                        pos = QPointF(
                            self._draw_start.x() + math.cos(angle) * length,
                            self._draw_start.y() + math.sin(angle) * length)
                self._temp_item.setLine(QLineF(self._draw_start, pos))
            elif isinstance(self._temp_item, QGraphicsRectItem):
                r = QRectF(self._draw_start, pos).normalized()
                # Shift constrains to a perfect square when drawing censors
                # or crops (Photoshop convention for rect/oval tools).
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    s = max(r.width(), r.height())
                    # Keep the anchor at _draw_start so the square grows
                    # in the direction the user is dragging.
                    dx = 1 if pos.x() >= self._draw_start.x() else -1
                    dy = 1 if pos.y() >= self._draw_start.y() else -1
                    r = QRectF(self._draw_start, QPointF(
                        self._draw_start.x() + dx * s,
                        self._draw_start.y() + dy * s)).normalized()
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
            elif self.current_tool == StudioTool.ARROW:
                line = self._temp_item.line()
                length_ok = max(abs(line.dx()), abs(line.dy())) > 10
                self.removeItem(self._temp_item)
                if length_ok and self.on_arrow_finished:
                    self.on_arrow_finished(line)
            elif self.current_tool in (StudioTool.SHAPE_RECT, StudioTool.SHAPE_ELLIPSE):
                r = self._temp_item.rect()
                self.removeItem(self._temp_item)
                if r.width() > 8 and r.height() > 8 and self.on_shape_finished:
                    kind = "ellipse" if self.current_tool == StudioTool.SHAPE_ELLIPSE else "rect"
                    self.on_shape_finished(r, kind)
            elif self.current_tool == StudioTool.TEXT_OVERLAY:
                # Classify: <6 px drag → click-place (auto-width text);
                # >=6 px → drag-to-size (text_width locked to drag width).
                r = self._temp_item.rect()
                self.removeItem(self._temp_item)
                if max(r.width(), r.height()) < 6:
                    if self.on_text_overlay_placed:
                        self.on_text_overlay_placed(self._draw_start, 0)
                else:
                    if self.on_text_overlay_placed:
                        self.on_text_overlay_placed(
                            r.topLeft(), int(r.width()))
            self._draw_start = None
            self._temp_item = None
            # Sticky tool: Text / Shape / Censor / Crop / Note / Arrow stay
            # active after a drawn item so comic / layout workflows don't
            # keep re-selecting the tool. User pref opt-out via QSettings.
            # Text is an exception — creating a text usually means the
            # user wants to tweak it immediately (which needs Select),
            # so revert regardless of the sticky flag. Illustrator
            # behavior.
            sticky = QSettings("DoxyEdit", "DoxyEdit").value(
                "studio_sticky_tools", True, type=bool)
            prev_tool = self.current_tool
            if not sticky or prev_tool == StudioTool.TEXT_OVERLAY:
                self.current_tool = StudioTool.SELECT
                # Notify the editor so the toolbar button highlight
                # updates too
                if self.views():
                    ed = getattr(self.views()[0], "_studio_editor", None)
                    if ed is not None and hasattr(ed, "_sync_tool_buttons"):
                        ed._sync_tool_buttons(StudioTool.SELECT)
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Double-click handlers:
        - On a ResizableCropItem: rename prompt
        - On empty canvas area: fit view
        """
        for it in self.items(event.scenePos()):
            if isinstance(it, ResizableCropItem):
                editor = None
                if self.views():
                    editor = getattr(self.views()[0], "_studio_editor", None)
                if editor is not None:
                    self._rename_crop(editor, it)
                    event.accept()
                    return
                break
            if isinstance(it, (OverlayImageItem, OverlayTextItem,
                                OverlayArrowItem,
                                CensorRectItem, NoteRectItem,
                                _GuideLineItem)):
                # Let those items handle their own double-click
                break
        else:
            # No interactive item under cursor → fit view
            editor = None
            if self.views():
                editor = getattr(self.views()[0], "_studio_editor", None)
            if editor is not None and self.sceneRect():
                editor._view.fitInView(
                    self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
                editor._zoom_label.setText("Fit")
                if hasattr(editor, "_canvas_wrap"):
                    editor._canvas_wrap.refresh()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Right-click on a ResizableCropItem → Studio crop menu (Export this crop / Delete).

        ResizableCropItem is defined in preview.py and doesn't know about
        Studio's export pipeline. Intercepting at the scene level lets us
        surface Studio-specific actions without coupling preview.py.
        """
        # Find the crop item under the cursor
        target = None
        for it in self.items(event.scenePos()):
            if isinstance(it, ResizableCropItem):
                target = it
                break
        if target is None:
            # Let overlays/censors/notes use their own context menus;
            # otherwise provide a canvas-level menu.
            for it in self.items(event.scenePos()):
                if isinstance(it, (OverlayImageItem, OverlayTextItem,
                                    CensorRectItem, NoteRectItem)):
                    return super().contextMenuEvent(event)
            return self._canvas_context_menu(event)

        # Only surface this menu in Studio — check the view hook
        editor = None
        if self.views():
            editor = getattr(self.views()[0], "_studio_editor", None)
        if editor is None:
            return super().contextMenuEvent(event)

        menu = _themed_menu(editor._view)
        export_act = menu.addAction("Export this crop")
        copy_crop_act = menu.addAction("Copy Cropped Image to Clipboard")
        menu.addSeparator()
        rename_act = menu.addAction("Rename crop")
        duplicate_act = menu.addAction("Duplicate crop")
        set_dims_act = menu.addAction("Set Exact Dimensions...")
        menu.addSeparator()
        delete_act = menu.addAction("Delete crop")
        chosen = menu.exec(event.screenPos())
        if chosen is export_act:
            target.setSelected(True)
            # If the crop has a platform binding use the full platform
            # pipeline (resize-to-platform + slot-name suffix); otherwise
            # fall back to a plain free-form crop export so labels like
            # "free" actually save instead of bouncing on "no platform".
            lbl = getattr(target, "label", "")
            crop = next(
                (c for c in (editor._asset.crops if editor._asset else [])
                 if c.label == lbl),
                None,
            )
            has_platform = bool(crop and getattr(crop, "platform_id", ""))
            if has_platform:
                editor._export_current_platform()
            else:
                editor._export_freeform_crop(target)
        elif chosen is copy_crop_act:
            self._copy_crop_to_clipboard(editor, target)
        elif chosen is rename_act:
            self._rename_crop(editor, target)
        elif chosen is duplicate_act:
            self._duplicate_crop(editor, target)
        elif chosen is set_dims_act:
            self._set_crop_dimensions(editor, target)
        elif chosen is delete_act:
            # Remove from asset.crops by label, then from scene
            lbl = getattr(target, "label", "")
            if editor._asset and lbl:
                editor._asset.crops = [c for c in editor._asset.crops if c.label != lbl]
            if target.scene() is not None:
                self.removeItem(target)
            # Remove from _crop_items list if tracked
            if hasattr(editor, "_crop_items") and target in editor._crop_items:
                editor._crop_items.remove(target)
            # Clear the crop mask if this was the active crop
            if hasattr(editor, "_crop_mask_item") and editor._crop_mask_item:
                if editor._crop_mask_item.scene():
                    self.removeItem(editor._crop_mask_item)
                editor._crop_mask_item = None

    def _canvas_context_menu(self, event):
        """Canvas-level right-click menu (fit/zoom/grid/thirds/copy image)."""
        editor = None
        if self.views():
            editor = getattr(self.views()[0], "_studio_editor", None)
        if editor is None:
            return super().contextMenuEvent(event)
        menu = _themed_menu(editor._view)
        add_menu = menu.addMenu("Add Here")
        add_text_act = add_menu.addAction("Text Overlay")
        add_rect_act = add_menu.addAction("Rectangle")
        add_ellipse_act = add_menu.addAction("Ellipse")
        add_speech_act = add_menu.addAction("Speech Bubble (with text)")
        add_thought_act = add_menu.addAction("Thought Bubble (with text)")
        add_burst_act = add_menu.addAction("Burst / Action Star")
        add_star_act = add_menu.addAction("Star (5-point)")
        add_poly_act = add_menu.addAction("Polygon (hexagon)")
        add_lingrad_act = add_menu.addAction("Linear Gradient (dark top)")
        add_radgrad_act = add_menu.addAction("Radial Gradient (vignette)")
        add_menu.addSeparator()
        add_callout_act = add_menu.addAction("Numbered Callout")
        fit_act = menu.addAction("Fit View  (Ctrl+0)")
        z100_act = menu.addAction("Zoom 100%  (Ctrl+1)")
        fit_w_act = menu.addAction("Fit Width")
        fit_h_act = menu.addAction("Fit Height")
        menu.addSeparator()
        tog_grid_act = menu.addAction(
            "Hide Grid" if editor.chk_grid.isChecked() else "Show Grid")
        tog_thirds_act = menu.addAction(
            "Hide Rule-of-Thirds" if editor.chk_thirds.isChecked()
            else "Show Rule-of-Thirds")
        menu.addSeparator()
        bg_color_act = menu.addAction("Canvas Background Color...")
        bg_preset_menu = menu.addMenu("Canvas Background Preset")
        bg_black_act = bg_preset_menu.addAction("Black")
        bg_white_act = bg_preset_menu.addAction("White")
        bg_gray_act = bg_preset_menu.addAction("Gray")
        reset_bg_act = menu.addAction("Reset Canvas Background")
        menu.addSeparator()
        select_menu = menu.addMenu("Select All...")
        sel_text_act = select_menu.addAction("Text Overlays")
        sel_wm_act = select_menu.addAction("Watermark / Logo Overlays")
        sel_arrow_act = select_menu.addAction("Arrows")
        sel_shape_act = select_menu.addAction("Shapes")
        sel_censor_act = select_menu.addAction("Censors")
        select_menu.addSeparator()
        sel_visible_act = select_menu.addAction("All Visible Overlays")
        sel_hidden_act = select_menu.addAction("All Hidden Overlays")
        sel_locked_act = select_menu.addAction("All Locked Overlays")
        sel_unlocked_act = select_menu.addAction("All Unlocked Overlays")
        # Per-tag-color submenu. Only show tag colors that actually
        # have at least one overlay assigned so the menu doesn't
        # fill with dead entries.
        _tag_sel_acts = {}
        if editor._asset:
            _tags_seen = set()
            for _o in editor._asset.overlays:
                _tc = getattr(_o, "tag_color", "") or ""
                if _tc:
                    _tags_seen.add(_tc)
            if _tags_seen:
                by_tag_sub = select_menu.addMenu("By Tag Color")
                for _tc in sorted(_tags_seen):
                    act = by_tag_sub.addAction(_tc.title())
                    _tag_sel_acts[act] = _tc
        # Platform-scoped sub-selection: grab every unique platform on
        # any overlay + censor, add a 'Select All on <platform>' entry
        # per platform. Overlays with empty platforms list are 'all
        # platforms' and are never included in the platform-specific
        # selections.
        _plat_sel_acts = {}
        if editor._asset:
            _plats_seen = set()
            for _o in editor._asset.overlays:
                for _p in getattr(_o, "platforms", None) or []:
                    _plats_seen.add(_p)
            for _c in editor._asset.censors:
                for _p in getattr(_c, "platforms", None) or []:
                    _plats_seen.add(_p)
            if _plats_seen:
                by_plat_sub = select_menu.addMenu("By Platform")
                for _p in sorted(_plats_seen):
                    act = by_plat_sub.addAction(_p)
                    _plat_sel_acts[act] = _p
        menu.addSeparator()
        lock_all_act = menu.addAction("Lock All Layers")
        unlock_all_act = menu.addAction("Unlock All Layers")
        show_all_act = menu.addAction("Show All Layers")
        toggle_censors_act = menu.addAction("Toggle All Censors")
        # Align submenu - shown iff there are selected moveable overlays.
        # With 1 item selected it aligns to the canvas; 2+ aligns to their
        # union rect; 3+ distributes evenly.
        moveable_sel = editor._all_selected_moveable()
        align_left_act = align_right_act = align_hcenter_act = None
        align_top_act = align_bottom_act = align_vcenter_act = None
        dist_h_act = dist_v_act = None
        if moveable_sel:
            align_menu = menu.addMenu(
                f"Align ({len(moveable_sel)} selected)")
            align_left_act = align_menu.addAction("Left  (Alt+Shift+L)")
            align_hcenter_act = align_menu.addAction("Center H  (Alt+Shift+C)")
            align_right_act = align_menu.addAction("Right  (Alt+Shift+R)")
            align_menu.addSeparator()
            align_top_act = align_menu.addAction("Top  (Alt+Shift+T)")
            align_vcenter_act = align_menu.addAction("Center V  (Alt+Shift+M)")
            align_bottom_act = align_menu.addAction("Bottom  (Alt+Shift+B)")
            if len(moveable_sel) >= 3:
                align_menu.addSeparator()
                dist_h_act = align_menu.addAction(
                    "Distribute Horizontally  (Alt+Shift+H)")
                dist_v_act = align_menu.addAction(
                    "Distribute Vertically  (Alt+Shift+V)")
        menu.addSeparator()
        # Sort Layers submenu - re-order the overlays list in-place by
        # a chosen attribute. Changes the z-order (last in list = top).
        sort_menu = menu.addMenu("Sort Layers")
        sort_type_act = sort_menu.addAction("By Type (text / shape / …)")
        sort_name_act = sort_menu.addAction("By Label (A → Z)")
        sort_size_act = sort_menu.addAction("By Size (largest first)")
        sort_tag_act = sort_menu.addAction("By Tag Color")
        sort_opacity_act = sort_menu.addAction("By Opacity (transparent first)")
        sort_reverse_act = sort_menu.addAction("Reverse")
        sort_menu.addSeparator()
        normalize_z_act = sort_menu.addAction("Normalize Z-values")
        menu.addSeparator()
        copy_canvas_act = menu.addAction("Copy Canvas Image to Clipboard")
        export_overlay_act = menu.addAction("Export Overlays as Transparent PNG...")
        export_selection_act = menu.addAction("Export Selection as Transparent PNG...")
        export_selection_act.setEnabled(bool(editor._scene.selectedItems()))
        menu.addSeparator()
        snap_threshold_act = menu.addAction("Snap Proximity...")
        snap_pixel_act = menu.addAction("Snap Selection to Pixel Grid")
        snap_pixel_act.setEnabled(bool(editor._scene.selectedItems()))
        chosen = menu.exec(event.screenPos())
        pos = event.scenePos()
        if chosen is add_text_act:
            editor._add_text_overlay(int(pos.x()), int(pos.y()))
        elif chosen in (add_rect_act, add_ellipse_act, add_star_act, add_poly_act):
            if chosen is add_rect_act:
                kind, w, h = "rect", 200, 120
            elif chosen is add_ellipse_act:
                kind, w, h = "ellipse", 200, 120
            elif chosen is add_star_act:
                kind, w, h = "star", 180, 180
            else:
                kind, w, h = "polygon", 180, 180
            ov = CanvasOverlay(
                type="shape", label=kind.title(), shape_kind=kind,
                color="#ffd700", stroke_color="#ffd700", stroke_width=2,
                fill_color="", opacity=1.0,
                x=int(pos.x() - w / 2), y=int(pos.y() - h / 2),
                shape_w=w, shape_h=h,
            )
            if kind == "star":
                ov.star_points = 5
                ov.inner_ratio = 0.4
            elif kind == "polygon":
                ov.star_points = 6
            editor._asset.overlays.append(ov)
            new_item = editor._create_overlay_item(ov)
            if new_item:
                new_item.setZValue(200 + len(editor._overlay_items))
                editor._overlay_items.append(new_item)
            editor._rebuild_layer_panel()
        elif chosen in (add_speech_act, add_thought_act, add_burst_act):
            kind = (
                "speech_bubble" if chosen is add_speech_act
                else "thought_bubble" if chosen is add_thought_act
                else "burst")
            w, h = (260, 160) if chosen is not add_burst_act else (220, 220)
            x0 = int(pos.x() - w / 2)
            y0 = int(pos.y() - h / 2)
            bubble = CanvasOverlay(
                type="shape", label=kind.replace("_", " ").title(),
                shape_kind=kind,
                color="#000000",
                stroke_color="#000000", stroke_width=3,
                fill_color="#ffffff", opacity=1.0,
                x=x0, y=y0, shape_w=w, shape_h=h,
                tail_x=int(pos.x() - w * 0.6) if kind != "burst" else 0,
                tail_y=int(pos.y() + h * 0.8) if kind != "burst" else 0,
            )
            editor._asset.overlays.append(bubble)
            bubble_item = editor._create_overlay_item(bubble)
            if bubble_item:
                bubble_item.setZValue(200 + len(editor._overlay_items))
                editor._overlay_items.append(bubble_item)
            # Paired text overlay placed inside (except burst which is decorative).
            if kind != "burst":
                pad_x = int(w * 0.15)
                pad_y = int(h * 0.18)
                tx = x0 + pad_x
                ty = y0 + pad_y
                tw = w - 2 * pad_x
                link_id = f"bubble_text_{uuid.uuid4().hex[:8]}"
                bubble.linked_text_id = link_id
                text_ov = CanvasOverlay(
                    type="text",
                    label=link_id,
                    text="...",
                    opacity=1.0,
                    position="custom",
                    x=tx, y=ty,
                    text_width=tw,
                    font_size=24,
                    text_align="center",
                    color="#000000",
                )
                for k, v in editor._load_text_style_defaults().items():
                    if k == "text_width":
                        continue
                    setattr(text_ov, k, v)
                editor._asset.overlays.append(text_ov)
                text_item = editor._create_overlay_item(text_ov)
                if text_item:
                    text_item.setZValue(200 + len(editor._overlay_items))
                    editor._overlay_items.append(text_item)
                    # Select + edit-mode so the user can type immediately
                    editor._scene.clearSelection()
                    text_item.setSelected(True)
                    text_item.setTextInteractionFlags(
                        Qt.TextInteractionFlag.TextEditorInteraction)
                    text_item.setFocus()
                    cursor = text_item.textCursor()
                    cursor.select(cursor.SelectionType.Document)
                    text_item.setTextCursor(cursor)
            editor._rebuild_layer_panel()
        elif chosen is add_callout_act:
            # Numbered callout: auto-increments based on how many
            # text overlays already carry a callout marker in their
            # label (so sequential clicks create 1, 2, 3, ...). Uses
            # a circle shape + a text overlay for the number. The
            # circle's label is 'callout_<N>' so future scans can
            # identify and renumber the set.
            next_n = 1
            for _ov in editor._asset.overlays:
                _lbl = getattr(_ov, "label", "") or ""
                if _lbl.startswith("callout_"):
                    try:
                        _n = int(_lbl.split("_")[1])
                        next_n = max(next_n, _n + 1)
                    except (ValueError, IndexError):
                        continue
            cx = int(pos.x())
            cy = int(pos.y())
            diameter = 48
            # The backing circle
            circle = CanvasOverlay(
                type="shape",
                label=f"callout_{next_n}",
                shape_kind="ellipse",
                color="#ffffff",
                stroke_color="#000000", stroke_width=3,
                fill_color="#ffffff", opacity=1.0,
                x=cx - diameter // 2, y=cy - diameter // 2,
                shape_w=diameter, shape_h=diameter,
            )
            editor._asset.overlays.append(circle)
            c_item = editor._create_overlay_item(circle)
            if c_item:
                c_item.setZValue(200 + len(editor._overlay_items))
                editor._overlay_items.append(c_item)
            # The number itself
            num_ov = CanvasOverlay(
                type="text",
                label=f"callout_{next_n}_text",
                text=str(next_n),
                opacity=1.0,
                position="custom",
                x=cx - diameter // 2,
                y=cy - diameter // 2 + 4,
                text_width=diameter,
                font_size=28,
                bold=True,
                text_align="center",
                color="#000000",
            )
            editor._asset.overlays.append(num_ov)
            n_item = editor._create_overlay_item(num_ov)
            if n_item:
                n_item.setZValue(200 + len(editor._overlay_items))
                editor._overlay_items.append(n_item)
            editor._rebuild_layer_panel()
            editor.info_label.setText(f"Added callout {next_n}")
        elif chosen in (add_lingrad_act, add_radgrad_act):
            is_radial = chosen is add_radgrad_act
            if is_radial and editor._pixmap_item:
                # Vignette covers the whole image
                pr = editor._pixmap_item.boundingRect()
                w, h = int(pr.width()), int(pr.height())
                x0, y0 = int(pr.left()), int(pr.top())
                start = "#00000000"  # transparent center
                end = "#000000cc"    # dark edges
            else:
                w, h = 600, 300
                x0 = int(pos.x() - w / 2)
                y0 = int(pos.y() - h / 2)
                start = "#000000cc"
                end = "#00000000"
            ov = CanvasOverlay(
                type="shape", label="Gradient",
                shape_kind="gradient_radial" if is_radial else "gradient_linear",
                color="#000000",
                gradient_start_color=start,
                gradient_end_color=end,
                gradient_angle=90,  # vertical by default
                opacity=1.0,
                x=x0, y=y0, shape_w=w, shape_h=h,
            )
            editor._asset.overlays.append(ov)
            new_item = editor._create_overlay_item(ov)
            if new_item:
                new_item.setZValue(200 + len(editor._overlay_items))
                editor._overlay_items.append(new_item)
            editor._rebuild_layer_panel()
        elif chosen is fit_act:
            editor._view.fitInView(
                editor._scene.sceneRect(),
                Qt.AspectRatioMode.KeepAspectRatio)
            editor._zoom_label.setText("Fit")
            if hasattr(editor, "_canvas_wrap"):
                editor._canvas_wrap.refresh()
        elif chosen is z100_act:
            editor._set_zoom(1.0)
        elif chosen is fit_w_act:
            # Fit the full canvas width into the view, keeping the
            # current vertical center. Useful for reading long vertical
            # pages at a maximum horizontal zoom.
            sr = editor._scene.sceneRect()
            vw = max(1, editor._view.viewport().width())
            if sr.width() > 0:
                factor = vw / sr.width()
                editor._view.resetTransform()
                editor._view.scale(factor, factor)
                editor._zoom_label.setText(f"{int(factor * 100)}%")
                if hasattr(editor, "_canvas_wrap"):
                    editor._canvas_wrap.refresh()
        elif chosen is fit_h_act:
            # Fit the full canvas height into the view. Mirror of Fit
            # Width for wide artwork.
            sr = editor._scene.sceneRect()
            vh = max(1, editor._view.viewport().height())
            if sr.height() > 0:
                factor = vh / sr.height()
                editor._view.resetTransform()
                editor._view.scale(factor, factor)
                editor._zoom_label.setText(f"{int(factor * 100)}%")
                if hasattr(editor, "_canvas_wrap"):
                    editor._canvas_wrap.refresh()
        elif chosen is tog_grid_act:
            editor.chk_grid.setChecked(not editor.chk_grid.isChecked())
        elif chosen is tog_thirds_act:
            editor.chk_thirds.setChecked(not editor.chk_thirds.isChecked())
        elif chosen is bg_color_act:
            saved = QSettings("DoxyEdit", "DoxyEdit").value(
                "studio_bg_color", editor._theme.bg_deep, type=str)
            color = QColorDialog.getColor(
                QColor(saved), editor, "Canvas background color")
            if color.isValid():
                QSettings("DoxyEdit", "DoxyEdit").setValue(
                    "studio_bg_color", color.name())
                editor._scene.setBackgroundBrush(QBrush(color))
        elif chosen is reset_bg_act:
            QSettings("DoxyEdit", "DoxyEdit").remove("studio_bg_color")
            editor._scene.setBackgroundBrush(
                QBrush(QColor(editor._theme.bg_deep)))
        elif chosen in (bg_black_act, bg_white_act, bg_gray_act):
            color_name = (
                "#000000" if chosen is bg_black_act else
                "#ffffff" if chosen is bg_white_act else
                "#3a3a3a")
            QSettings("DoxyEdit", "DoxyEdit").setValue("studio_bg_color", color_name)
            editor._scene.setBackgroundBrush(QBrush(QColor(color_name)))
        elif chosen in (sel_text_act, sel_wm_act, sel_arrow_act,
                         sel_shape_act, sel_censor_act,
                         sel_visible_act, sel_hidden_act,
                         sel_locked_act, sel_unlocked_act):
            editor._scene.clearSelection()
            if chosen is sel_text_act:
                for it in editor._overlay_items:
                    if isinstance(it, OverlayTextItem):
                        it.setSelected(True)
            elif chosen is sel_wm_act:
                for it in editor._overlay_items:
                    if isinstance(it, OverlayImageItem):
                        it.setSelected(True)
            elif chosen is sel_arrow_act:
                for it in editor._overlay_items:
                    if isinstance(it, OverlayArrowItem):
                        it.setSelected(True)
            elif chosen is sel_shape_act:
                for it in editor._overlay_items:
                    if isinstance(it, OverlayShapeItem):
                        it.setSelected(True)
            elif chosen is sel_censor_act:
                for it in editor._censor_items:
                    it.setSelected(True)
            elif chosen in (sel_visible_act, sel_hidden_act,
                             sel_locked_act, sel_unlocked_act):
                want_visible = chosen is sel_visible_act
                want_hidden = chosen is sel_hidden_act
                want_locked = chosen is sel_locked_act
                want_unlocked = chosen is sel_unlocked_act
                for it in editor._overlay_items:
                    ov = getattr(it, "overlay", None)
                    if ov is None:
                        continue
                    if want_visible and ov.enabled:
                        it.setSelected(True)
                    elif want_hidden and not ov.enabled:
                        # Layer panel still lets user reach hidden items;
                        # temporarily show them so setSelected takes.
                        it.setVisible(True)
                        it.setSelected(True)
                    elif want_locked and ov.locked:
                        it.setSelected(True)
                    elif want_unlocked and not ov.locked:
                        it.setSelected(True)
        elif _tag_sel_acts and chosen in _tag_sel_acts:
            # Select every overlay that carries the picked tag color.
            target = _tag_sel_acts[chosen]
            editor._scene.clearSelection()
            count = 0
            for it in editor._overlay_items:
                ov = getattr(it, "overlay", None)
                if ov is not None and getattr(
                        ov, "tag_color", "") == target:
                    it.setSelected(True)
                    count += 1
            editor.info_label.setText(
                f"Selected {count} tagged {target}")
        elif _plat_sel_acts and chosen in _plat_sel_acts:
            # Select overlays + censors scoped to the picked platform.
            # Overlays with empty platforms list are 'all platforms'
            # and are intentionally excluded here - otherwise 'Select
            # on Twitter' would include universal overlays too.
            target = _plat_sel_acts[chosen]
            editor._scene.clearSelection()
            count = 0
            for it in editor._overlay_items:
                ov = getattr(it, "overlay", None)
                if ov is not None and target in (ov.platforms or []):
                    it.setSelected(True)
                    count += 1
            for it in editor._censor_items:
                cr = getattr(it, "_censor_region", None)
                if cr is not None and target in (cr.platforms or []):
                    it.setSelected(True)
                    count += 1
            editor.info_label.setText(
                f"Selected {count} on {target}")
        elif chosen is copy_canvas_act:
            if editor._pixmap_item:
                pm = editor._pixmap_item.pixmap()
                img = QImage(pm.size(), QImage.Format.Format_ARGB32_Premultiplied)
                img.fill(Qt.GlobalColor.transparent)
                p = QPainter(img)
                self.render(p, source=editor._pixmap_item.sceneBoundingRect())
                p.end()
                QApplication.clipboard().setImage(img)
                editor.info_label.setText("Canvas copied to clipboard")
        elif chosen is export_overlay_act:
            editor._export_overlays_as_transparent_png()
        elif chosen is export_selection_act:
            editor._export_selection_as_transparent_png()
        elif chosen in (sort_type_act, sort_name_act, sort_size_act,
                         sort_tag_act, sort_opacity_act,
                         sort_reverse_act):
            ovs = list(editor._asset.overlays)
            if chosen is sort_type_act:
                # Stable: group by type in a deterministic order.
                _order = {"shape": 0, "watermark": 1, "arrow": 2, "text": 3}
                ovs.sort(key=lambda o: (_order.get(o.type, 9),
                                          o.label or ""))
            elif chosen is sort_name_act:
                ovs.sort(key=lambda o: (o.label or "").lower())
            elif chosen is sort_size_act:
                def _area(o):
                    if o.type == "shape":
                        return -(o.shape_w * o.shape_h)
                    if o.type == "arrow":
                        return -int(math.hypot(
                            o.end_x - o.x, o.end_y - o.y))
                    return 0
                ovs.sort(key=_area)
            elif chosen is sort_tag_act:
                # Ordered by the named color priority; untagged last.
                ovs.sort(key=lambda o: (
                    TAG_COLOR_ORDER.get(getattr(o, "tag_color", "") or "", 99),
                    o.label or ""))
            elif chosen is sort_opacity_act:
                ovs.sort(key=lambda o: getattr(o, "opacity", 1.0) or 0.0)
            elif chosen is sort_reverse_act:
                ovs.reverse()
            editor._asset.overlays = ovs
            # Re-sync z-order on scene items
            for i, ov in enumerate(editor._asset.overlays):
                for it in editor._overlay_items:
                    if getattr(it, "overlay", None) is ov:
                        it.setZValue(200 + i)
                        break
            editor._rebuild_layer_panel()
            if hasattr(editor, "info_label"):
                editor.info_label.setText(
                    f"Sorted {len(ovs)} overlays")
        elif chosen is normalize_z_act:
            # Reset z-values to a contiguous 200.. range matching the
            # overlay list order, plus 100.. for censors. Clears any
            # drift from repeated Bring-Forward / Send-Back work that
            # might have left big gaps between Z values.
            for i, ov in enumerate(editor._asset.overlays):
                for it in editor._overlay_items:
                    if getattr(it, "overlay", None) is ov:
                        it.setZValue(200 + i)
                        break
            for i, it in enumerate(editor._censor_items):
                it.setZValue(100 + i)
            if hasattr(editor, "info_label"):
                editor.info_label.setText(
                    "Normalized Z values")
        elif chosen is snap_threshold_act:
            qs = QSettings("DoxyEdit", "DoxyEdit")
            cur = qs.value("studio_snap_threshold_px", 5, type=int)
            value, ok = QInputDialog.getInt(
                editor, "Snap proximity",
                "Distance (px) within which items snap to other edges / guides:",
                value=cur, minValue=0, maxValue=50)
            if ok:
                qs.setValue("studio_snap_threshold_px", value)
                editor._scene.reload_snap_threshold()
                editor.info_label.setText(f"Snap proximity: {value}px")
        elif chosen is snap_pixel_act:
            # Round every selected overlay's position to whole pixels.
            # Useful after nudging with fractional-pixel smart guides
            # or when importing from a vector-precision workflow.
            count = 0
            for it in editor._scene.selectedItems():
                ov = getattr(it, "overlay", None)
                if ov is not None:
                    ov.x = int(round(ov.x))
                    ov.y = int(round(ov.y))
                    if hasattr(ov, "shape_w"):
                        ov.shape_w = int(round(ov.shape_w))
                        ov.shape_h = int(round(ov.shape_h))
                    if hasattr(ov, "end_x"):
                        ov.end_x = int(round(ov.end_x))
                        ov.end_y = int(round(ov.end_y))
                    it.setPos(ov.x, ov.y)
                    if hasattr(it, "prepareGeometryChange"):
                        it.prepareGeometryChange()
                    it.update()
                    count += 1
                else:
                    cr = getattr(it, "_censor_region", None)
                    if cr is not None:
                        cr.x = int(round(cr.x))
                        cr.y = int(round(cr.y))
                        cr.w = int(round(cr.w))
                        cr.h = int(round(cr.h))
                        it.setRect(cr.x, cr.y, cr.w, cr.h)
                        count += 1
            if count:
                editor._sync_overlays_to_asset()
                editor.info_label.setText(
                    f"Snapped {count} item{'s' if count != 1 else ''} "
                    "to integer pixels")
        elif chosen is align_left_act:
            editor._align_selected("left")
        elif chosen is align_right_act:
            editor._align_selected("right")
        elif chosen is align_hcenter_act:
            editor._align_selected("hcenter")
        elif chosen is align_top_act:
            editor._align_selected("top")
        elif chosen is align_bottom_act:
            editor._align_selected("bottom")
        elif chosen is align_vcenter_act:
            editor._align_selected("vcenter")
        elif chosen is dist_h_act:
            editor._align_selected("dist_h")
        elif chosen is dist_v_act:
            editor._align_selected("dist_v")
        elif chosen in (lock_all_act, unlock_all_act):
            lock = chosen is lock_all_act
            for it in editor._overlay_items:
                if hasattr(it, "overlay"):
                    it.overlay.locked = lock
                it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not lock)
                it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not lock)
            editor._sync_overlays_to_asset()
            editor._rebuild_layer_panel()
            editor.info_label.setText(
                "All layers locked" if lock else "All layers unlocked")
        elif chosen is show_all_act:
            for it in editor._overlay_items:
                if hasattr(it, "overlay"):
                    it.overlay.enabled = True
                it.setVisible(True)
            for it in editor._censor_items:
                it.setVisible(True)
            editor._sync_overlays_to_asset()
            editor._rebuild_layer_panel()
            editor.info_label.setText("All layers visible")
        elif chosen is toggle_censors_act:
            # Flip the visibility of every censor (reveal / hide in bulk)
            currently_any_visible = any(
                it.isVisible() for it in editor._censor_items)
            for it in editor._censor_items:
                it.setVisible(not currently_any_visible)
            editor.info_label.setText(
                "Censors hidden (reveal mode)" if currently_any_visible
                else "Censors shown")

    def _copy_crop_to_clipboard(self, editor, target):
        """Render the base image + overlays restricted to the crop bounds,
        then put the result on the system clipboard."""
        if editor._pixmap_item is None:
            return
        r = target.rect().translated(target.pos())
        img = QImage(int(r.width()), int(r.height()),
                      QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        # Hide crop items so they don't render into the cropped output
        crops = [c for c in editor._crop_items if c.isVisible()]
        for c in crops:
            c.setVisible(False)
        p = QPainter(img)
        self.render(p, source=r)
        p.end()
        for c in crops:
            c.setVisible(True)
        QApplication.clipboard().setImage(img)
        editor.info_label.setText(
            f"Copied crop '{getattr(target, 'label', '')}' to clipboard")

    def _set_crop_dimensions(self, editor, target):
        """Prompt for exact W and H, update both the scene item and the
        asset.crops entry."""
        r = target.rect()
        w_val, ok = QInputDialog.getInt(
            editor._view, "Crop width",
            "Width (px):", value=int(r.width()),
            minValue=1, maxValue=50000)
        if not ok:
            return
        h_val, ok = QInputDialog.getInt(
            editor._view, "Crop height",
            "Height (px):", value=int(r.height()),
            minValue=1, maxValue=50000)
        if not ok:
            return
        target.setRect(QRectF(r.x(), r.y(), w_val, h_val))
        # Persist back to asset.crops via on_changed if wired
        if getattr(target, "on_changed", None):
            target.on_changed(target)

    def _rename_crop(self, editor, target):
        """Prompt for a new label and apply to both CropRegion and item."""
        old_label = getattr(target, "label", "")
        new_label, ok = QInputDialog.getText(
            editor._view, "Rename crop", "Label:", text=old_label)
        if not ok or not new_label.strip():
            return
        new_label = new_label.strip()
        if new_label == old_label:
            return
        # Prevent collisions with another existing crop
        if editor._asset and any(c.label == new_label for c in editor._asset.crops):
            return
        # Update CropRegion
        if editor._asset:
            for c in editor._asset.crops:
                if c.label == old_label:
                    c.label = new_label
                    break
        # Update the item's display label + repaint
        target.label = new_label
        target.update()

    def _duplicate_crop(self, editor, target):
        """Clone the crop with an offset + unique label."""
        if not editor._asset:
            return
        src_label = getattr(target, "label", "")
        src = next((c for c in editor._asset.crops if c.label == src_label), None)
        if src is None:
            return
        # Unique label: "<label> copy", "<label> copy 2", ...
        existing = {c.label for c in editor._asset.crops}
        new_label = f"{src_label} copy"
        n = 2
        while new_label in existing:
            new_label = f"{src_label} copy {n}"
            n += 1
        # Offset the clone so it's visible below the original
        offset = 20
        new_crop = CropRegion(
            x=src.x + offset, y=src.y + offset,
            w=src.w, h=src.h,
            label=new_label,
            platform_id=getattr(src, "platform_id", ""),
            slot_name=getattr(src, "slot_name", ""),
        )
        editor._asset.crops.append(new_crop)
        # Build an item matching the original's aspect lock
        aspect = target._aspect if getattr(target, "_aspect", None) else None
        new_rect = QRectF(new_crop.x, new_crop.y, new_crop.w, new_crop.h)
        new_item = ResizableCropItem(
            new_rect, label=new_label, aspect=aspect, theme=editor._theme)
        new_item.on_changed = editor._on_crop_edited
        self.addItem(new_item)
        if hasattr(editor, "_crop_items"):
            editor._crop_items.append(new_item)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class _GuideLineItem(QGraphicsLineItem):
    """Draggable guide line used by the Studio rulers.

    StudioScene._compute_snap_guides recognizes instances of this class
    as snap candidates (extending the item-edge snap to guide lines).
    Selectable + movable so the user can reposition an existing guide
    by dragging it, and double-clicking deletes the guide.
    """
    _guide_orientation = 'h'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        # Constrain cursor per-orientation set later by caller
        self._editor = None

    def mouseDoubleClickEvent(self, event):
        # Double-click removes the guide, unless lock-guides is on.
        if QSettings("DoxyEdit", "DoxyEdit").value(
                "studio_lock_guides", False, type=bool):
            if self._editor and hasattr(self._editor, "info_label"):
                self._editor.info_label.setText(
                    "Guides locked (Studio Settings > View)")
            event.accept()
            return
        if self.scene() is not None:
            if self._editor and hasattr(self._editor, "_guide_items"):
                if self in self._editor._guide_items:
                    self._editor._guide_items.remove(self)
            self.scene().removeItem(self)
            if self._editor:
                self._editor._save_guides_to_asset()
                if hasattr(self._editor, "_canvas_wrap"):
                    self._editor._canvas_wrap.refresh()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        # Numeric position editor + delete — nicer than double-click removal
        if self._editor is None:
            return super().contextMenuEvent(event)
        menu = _themed_menu(self._editor._view)
        set_pos_act = menu.addAction("Set Position...")
        delete_act = menu.addAction("Delete Guide")
        chosen = menu.exec(event.screenPos())
        if chosen is set_pos_act:
            line = self.line()
            off = self.pos()
            orient = getattr(self, "_guide_orientation", 'h')
            current = int(line.y1() + off.y()) if orient == 'h' else int(
                line.x1() + off.x())
            label = "Y position (px):" if orient == 'h' else "X position (px):"
            value, ok = QInputDialog.getInt(
                self._editor, "Set guide position", label, value=current,
                minValue=-50000, maxValue=50000)
            if ok:
                # Recompute the line at the new position and reset pos offset
                pm_rect = self._editor._pixmap_item.boundingRect() if self._editor._pixmap_item else QRectF()
                if orient == 'h':
                    self.setLine(pm_rect.left(), value,
                                  pm_rect.right(), value)
                else:
                    self.setLine(value, pm_rect.top(),
                                  value, pm_rect.bottom())
                self.setPos(0, 0)
                self._editor._save_guides_to_asset()
                if hasattr(self._editor, "_canvas_wrap"):
                    self._editor._canvas_wrap.refresh()
        elif chosen is delete_act:
            if self in getattr(self._editor, "_guide_items", []):
                self._editor._guide_items.remove(self)
            self.scene().removeItem(self)
            self._editor._save_guides_to_asset()
            if hasattr(self._editor, "_canvas_wrap"):
                self._editor._canvas_wrap.refresh()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # Persist the new position after a drag
        if self._editor:
            self._editor._save_guides_to_asset()
            if hasattr(self._editor, "_canvas_wrap"):
                self._editor._canvas_wrap.refresh()

    def itemChange(self, change, value):
        # Lock movement to the perpendicular axis
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self._guide_orientation == 'h':
                # Horizontal guide -> only Y moves
                return QPointF(0, value.y())
            else:
                return QPointF(value.x(), 0)
        return super().itemChange(change, value)


class _CheckerboardItem(QGraphicsRectItem):
    """Photoshop-style checkerboard that sits behind the image so transparent
    pixels show through as the classic gray/white check pattern.

    Draws via a pre-built 2-tile QPixmap used as a tiled brush. A single
    fillRect call paints the entire checker regardless of size. The prior
    implementation drew each 12x12 tile individually — on a 2000x3000
    image that was ~20,000 drawRect calls per paint, and the item spans
    the full canvas so any overlapping redraw retriggered it."""

    TILE = 12
    _tile_cache: dict = {}  # (dark_hex, light_hex, tile) -> QPixmap

    def __init__(self, rect: QRectF, parent=None):
        super().__init__(rect, parent)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)

    @classmethod
    def _get_tile_brush(cls, dark: QColor, light: QColor) -> QBrush:
        key = (dark.name(), light.name(), cls.TILE)
        pm = cls._tile_cache.get(key)
        if pm is None:
            t = cls.TILE
            pm = QPixmap(t * 2, t * 2)
            p = QPainter(pm)
            p.setPen(Qt.PenStyle.NoPen)
            # Two-tone 2x2 checker pattern
            p.fillRect(0, 0, t, t, light)
            p.fillRect(t, 0, t, t, dark)
            p.fillRect(0, t, t, t, dark)
            p.fillRect(t, t, t, t, light)
            p.end()
            cls._tile_cache[key] = pm
        return QBrush(pm)

    def paint(self, painter, option, widget=None):
        _t = THEMES[DEFAULT_THEME]
        c_dark = QColor(_t.studio_scene_checker_dark)
        c_light = QColor(_t.studio_scene_checker_light)
        painter.fillRect(self.rect(), self._get_tile_brush(c_dark, c_light))


class _StudioRuler(QWidget):
    """Horizontal or vertical ruler that reads the StudioView's transform.

    Draws minor and major tick marks at scene-space intervals, with
    integer pixel labels at majors. Autoscales the tick spacing so the
    major step is always at least ~60 screen pixels apart.
    """

    _TICK_CANDIDATES = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)
    _MAJOR_PX = 60  # target screen-px between major ticks

    def __init__(self, view, orientation: str, theme, parent=None):
        super().__init__(parent)
        self._view = view
        self._orientation = orientation  # 'h' or 'v'
        self._theme = theme
        self._cursor_scene = 0.0  # updated from view mouseMove for marker
        # Unit cached to avoid QSettings file-read per paint. Refresh via
        # reload_unit() from the places that change the unit (right-click
        # ruler menu, Studio Settings dialog).
        self._unit = QSettings("DoxyEdit", "DoxyEdit").value(
            "studio_ruler_unit", "px", type=str)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        # Drag-to-create guide state (editor owns the pending line item)
        self._drag_guide = False
        # Cursor hint on hover
        self.setCursor(Qt.CursorShape.SplitHCursor if orientation == 'h'
                        else Qt.CursorShape.SplitVCursor)

    def reload_unit(self):
        self._unit = QSettings("DoxyEdit", "DoxyEdit").value(
            "studio_ruler_unit", "px", type=str)
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self._drag_guide = True
        self._update_drag_guide(event.pos())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_guide:
            self._update_drag_guide(event.pos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_guide and event.button() == Qt.MouseButton.LeftButton:
            self._drag_guide = False
            self._commit_pending_guide()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        """Right-click a ruler -> clear all guides / toggle ruler
        visibility / change ruler unit."""
        editor = getattr(self._view, "_studio_editor", None)
        if editor is None:
            return super().contextMenuEvent(event)
        menu = _themed_menu(self._view)
        unit_sub = menu.addMenu("Units")
        qs = QSettings("DoxyEdit", "DoxyEdit")
        current_unit = qs.value("studio_ruler_unit", "px", type=str)
        unit_px = unit_sub.addAction("Pixels (px)")
        unit_mm = unit_sub.addAction("Millimetres (mm)")
        unit_in = unit_sub.addAction("Inches (in)")
        for act, u in ((unit_px, "px"), (unit_mm, "mm"), (unit_in, "in")):
            act.setCheckable(True)
            act.setChecked(current_unit == u)
        menu.addSeparator()
        # Guide preset submenu - drop a commonly-used pattern of guides
        # over the canvas in one click.
        preset_menu = menu.addMenu("Guide Presets")
        preset_cross_act = preset_menu.addAction("Center Cross (H + V)")
        preset_thirds_act = preset_menu.addAction("Rule of Thirds")
        preset_golden_act = preset_menu.addAction("Golden Ratio")
        preset_quarters_act = preset_menu.addAction("Quarters (5-line)")
        preset_diagonal_act = preset_menu.addAction("Diagonals (⋰ + ⋱)")
        preset_menu.addSeparator()
        preset_safe_area_act = preset_menu.addAction("Safe Area (5% inset)")
        clear_act = menu.addAction("Clear All Guides")
        hide_ruler_act = menu.addAction("Hide Rulers")
        chosen = menu.exec(event.globalPos())
        if chosen in (unit_px, unit_mm, unit_in):
            new_u = ("px" if chosen is unit_px
                     else "mm" if chosen is unit_mm else "in")
            qs.setValue("studio_ruler_unit", new_u)
            # Refresh the unit cache on both rulers
            if editor and hasattr(editor, "_canvas_wrap"):
                editor._canvas_wrap._h_ruler.reload_unit()
                editor._canvas_wrap._v_ruler.reload_unit()
                editor._canvas_wrap.refresh()
            self._unit = new_u
            self.update()
            if hasattr(editor, "info_label"):
                editor.info_label.setText(f"Ruler units: {new_u}")
        elif chosen is clear_act:
            editor._clear_guides()
        elif chosen in (preset_cross_act, preset_thirds_act,
                         preset_golden_act, preset_quarters_act,
                         preset_diagonal_act, preset_safe_area_act):
            if hasattr(editor, "_apply_guide_preset"):
                if chosen is preset_cross_act:
                    editor._apply_guide_preset("cross")
                elif chosen is preset_thirds_act:
                    editor._apply_guide_preset("thirds")
                elif chosen is preset_golden_act:
                    editor._apply_guide_preset("golden")
                elif chosen is preset_quarters_act:
                    editor._apply_guide_preset("quarters")
                elif chosen is preset_diagonal_act:
                    editor._apply_guide_preset("diagonal")
                elif chosen is preset_safe_area_act:
                    editor._apply_guide_preset("safe")
        elif chosen is hide_ruler_act:
            if hasattr(editor, "chk_rulers"):
                editor.chk_rulers.setChecked(False)

    def _update_drag_guide(self, widget_pos):
        """Project the local mouse position to scene space and show a pending guide."""
        scene = self._view.scene()
        if scene is None:
            return
        # Convert ruler-local coords to view coords, then to scene
        # Ruler sits adjacent to the view, so offsetting is needed.
        if self._orientation == 'h':
            view_pos = self._view.mapFromGlobal(self.mapToGlobal(widget_pos))
            scene_pos = self._view.mapToScene(view_pos)
            pos = scene_pos.y()
        else:
            view_pos = self._view.mapFromGlobal(self.mapToGlobal(widget_pos))
            scene_pos = self._view.mapToScene(view_pos)
            pos = scene_pos.x()
        editor = getattr(self._view, "_studio_editor", None)
        if editor is not None and hasattr(editor, "_preview_guide"):
            editor._preview_guide(self._orientation, pos)

    def _commit_pending_guide(self):
        editor = getattr(self._view, "_studio_editor", None)
        if editor is not None and hasattr(editor, "_commit_preview_guide"):
            editor._commit_preview_guide()

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def set_cursor_scene(self, value: float):
        # Quantize to integer scene-pixels. Every mouse move sends a
        # fresh float that drifts by sub-pixel amounts on modern high-
        # rate pointer devices, and the prior float-equality guard let
        # every single one trigger a full ruler repaint (tick math +
        # text drawing per major tick). One repaint per scene-pixel
        # change is indistinguishable to the user.
        iv = int(value)
        if iv != int(self._cursor_scene):
            self._cursor_scene = iv
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self._theme.bg_deep))
        if not self._view.scene():
            return
        t = self._view.transform()
        scale = t.m11() if self._orientation == 'h' else t.m22()
        if scale <= 0:
            return
        vp = self._view.viewport().rect()
        top_left = self._view.mapToScene(vp.topLeft())
        bot_right = self._view.mapToScene(vp.bottomRight())
        if self._orientation == 'h':
            s_start, s_end = top_left.x(), bot_right.x()
        else:
            s_start, s_end = top_left.y(), bot_right.y()
        # Unit conversion: 96 DPI canonical — 1 in = 96 px, 1 mm = 96 /
        # 25.4 ≈ 3.7795 px. The tick values are rendered in the chosen
        # unit but the screen-pixel math still uses the raw px delta.
        _unit = self._unit
        if _unit == "mm":
            unit_per_px = 25.4 / 96.0  # mm per px at 96 DPI
            unit_suffix = ""
            # Tick candidates in millimetres
            _tick_candidates = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)
        elif _unit == "in":
            unit_per_px = 1.0 / 96.0
            unit_suffix = "\""
            _tick_candidates = (0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100)
        else:
            unit_per_px = 1.0
            unit_suffix = ""
            _tick_candidates = self._TICK_CANDIDATES
        # Pick a major step whose screen footprint is >= _MAJOR_PX.
        # Evaluate the candidate in UNIT space: step_in_px = step * (1/unit_per_px)
        px_per_unit = (1.0 / unit_per_px) if unit_per_px else 1.0
        major_step = _tick_candidates[-1]
        for c in _tick_candidates:
            if c * px_per_unit * scale >= self._MAJOR_PX:
                major_step = c
                break
        minor_step = major_step / 5.0 if _unit != "px" else max(1, int(major_step // 5))
        # Set up pens + font — minor ticks are dimmer
        _minor_color = QColor(self._theme.text_muted)
        _minor_color.setAlpha(self._theme.studio_ruler_minor_alpha)
        pen_minor = QPen(_minor_color)
        pen_minor.setWidth(self._theme.studio_ruler_tick_pen_width)
        pen_major = QPen(QColor(self._theme.text_muted))
        pen_major.setWidth(self._theme.studio_ruler_tick_pen_width)
        font = p.font()
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.80))
        p.setFont(font)

        # Walk in UNIT space: start at the nearest minor step ≤ s_start.
        # unit_start / unit_end are the visible range in UNIT space.
        unit_start = s_start * unit_per_px
        unit_end = s_end * unit_per_px
        s = (int(unit_start / minor_step)) * minor_step
        def _fmt(v):
            # Hide trailing zeros for inch/mm; keep plain ints for px.
            if _unit == "px":
                return f"{int(v)}"
            if abs(v - int(v)) < 0.01:
                return f"{int(v)}{unit_suffix}"
            return f"{v:g}{unit_suffix}"
        while s <= unit_end + minor_step:
            px = s / unit_per_px  # back to pixel coord for drawing
            screen_pos = (px - s_start) * scale
            # Major if the unit-space value is a multiple of major_step.
            is_major = abs((s / major_step) - round(s / major_step)) < 1e-6
            p.setPen(pen_major if is_major else pen_minor)
            if self._orientation == 'h':
                x = int(screen_pos)
                if is_major:
                    p.drawLine(x, self.height() - 1, x, self.height() - 8)
                    p.drawText(x + 2, self.height() - 9, _fmt(s))
                else:
                    p.drawLine(x, self.height() - 1, x, self.height() - 4)
            else:
                y = int(screen_pos)
                if is_major:
                    p.drawLine(self.width() - 1, y, self.width() - 8, y)
                    p.save()
                    p.translate(self.width() - 9, y + 2)
                    p.rotate(-90)
                    p.drawText(0, 0, _fmt(s))
                    p.restore()
                else:
                    p.drawLine(self.width() - 1, y, self.width() - 4, y)
            s += minor_step
        # Guide tick marks — small accent triangles at each guide's position.
        # Horizontal guide (spans image width at a Y) -> marker on V ruler.
        # Vertical guide (spans image height at an X) -> marker on H ruler.
        editor = getattr(self._view, "_studio_editor", None)
        if editor is not None:
            guides = getattr(editor, "_guide_items", [])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(self._theme.accent)))
            for gl in guides:
                if gl.scene() is None:
                    continue
                orient = getattr(gl, "_guide_orientation", 'h')
                # Only render the guide on the opposing-axis ruler
                if orient == 'h' and self._orientation != 'v':
                    continue
                if orient == 'v' and self._orientation != 'h':
                    continue
                line = gl.line()
                off = gl.pos()
                if orient == 'h':
                    gpos = line.y1() + off.y()
                else:
                    gpos = line.x1() + off.x()
                screen_pos = (gpos - s_start) * scale
                if not (0 <= screen_pos <= max(self.width(), self.height())):
                    continue
                sp = int(screen_pos)
                if self._orientation == 'h':
                    tri = [QPointF(sp, self.height()),
                           QPointF(sp - 4, self.height() - 5),
                           QPointF(sp + 4, self.height() - 5)]
                else:
                    tri = [QPointF(self.width(), sp),
                           QPointF(self.width() - 5, sp - 4),
                           QPointF(self.width() - 5, sp + 4)]
                p.drawPolygon(QPolygonF(tri))
        # Cursor indicator line
        cursor_px = (self._cursor_scene - s_start) * scale
        if 0 <= cursor_px <= max(self.width(), self.height()):
            p.setPen(QPen(QColor(self._theme.accent),
                          self._theme.studio_ruler_tick_pen_width))
            if self._orientation == 'h':
                p.drawLine(int(cursor_px), 0, int(cursor_px), self.height())
            else:
                p.drawLine(0, int(cursor_px), self.width(), int(cursor_px))


class _ShapeControlsDialog(QtWidgets.QDialog):
    """Properties popup for the currently-selected shape / bubble /
    arrow. Contents rebuild whenever the selected overlay's type
    changes. Same persisted-geometry behavior as Text Controls so the
    two popups can share the user's layout."""

    _GEOM_KEY = "studio_shape_controls_geom"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qs = QSettings("DoxyEdit", "DoxyEdit")
        self._editor = parent
        self._current_kind = None  # last rebuilt kind
        self._pin_on_top = False
        self.setWindowTitle("Shape Controls")
        self.setObjectName("studio_shape_controls_dlg")
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint)
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(8, 8, 8, 8)
        self._root_layout.setSpacing(6)
        # Tiny minimum so users can shrink the popup to a corner tile
        # for focus-mode workflows (matches the preview tiny-mode
        # philosophy). Buttons and sliders gracefully overflow the
        # contained scroll when sized below their sizeHint — users
        # who want the full layout can always resize back up.
        self.setMinimumWidth(200)
        self.setMinimumHeight(100)
        # Ctrl+P pin-on-top toggle + Ctrl+Shift+L / R snap-to-edge
        # park positions. Mirror of _TextControlsDialog so both popups
        # respond to the same 'dock-ish' gestures.
        _pin_sc = QShortcut(QKeySequence("Ctrl+P"), self)
        _pin_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        _pin_sc.activated.connect(self._toggle_pin_on_top)
        _dl_sc = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        _dl_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        _dl_sc.activated.connect(lambda: self._snap_to_edge("left"))
        _dr_sc = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        _dr_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        _dr_sc.activated.connect(lambda: self._snap_to_edge("right"))

    def _toggle_pin_on_top(self):
        self._pin_on_top = not self._pin_on_top
        flags = self.windowFlags()
        if self._pin_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
        self.setWindowTitle(
            "Shape Controls (pinned)" if self._pin_on_top
            else "Shape Controls")

    def _snap_to_edge(self, side: str):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        w = max(self.width(), 420)
        h = max(self.height(), avail.height() - 40)
        y = avail.top() + 20
        if side == "right":
            x = avail.right() - w - 10
        else:
            x = avail.left() + 10
        self.setGeometry(x, y, w, h)
        self._positioned_once = True

    def _save_geom(self):
        """Persist window geometry. Debounced via a 200ms singleshot so
        a resize/move drag doesn't slam QSettings (registry on Windows)
        with 60+ writes per second. Immediate flush paths (close/hide)
        call _save_geom_now directly."""
        if not hasattr(self, "_save_geom_timer"):
            self._save_geom_timer = QTimer(self)
            self._save_geom_timer.setSingleShot(True)
            self._save_geom_timer.setInterval(200)
            self._save_geom_timer.timeout.connect(self._save_geom_now)
        self._save_geom_timer.start()

    def _save_geom_now(self):
        try:
            self._qs.setValue(self._GEOM_KEY, self.saveGeometry())
        except Exception:
            pass

    def closeEvent(self, ev):
        self._save_geom_now(); super().closeEvent(ev)

    def hideEvent(self, ev):
        self._save_geom_now(); super().hideEvent(ev)

    def moveEvent(self, ev):
        super().moveEvent(ev); self._save_geom()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._save_geom()
        # When the dialog is narrowed, the slider's field column eats the
        # right-aligned numeric labels (5%, 100%, 0deg, +0). Hide every
        # widget tagged "shape_value_label" once the dialog drops below a
        # readable threshold so the labels don't paint over the sliders.
        # 340 measured: below this the brightness slider's right edge
        # starts to abut the +0 label and the two visibly overlap.
        threshold = 340
        try:
            hide = self.width() < threshold
            for lbl in self.findChildren(QLabel, "shape_value_label"):
                lbl.setVisible(not hide)
        except Exception:
            pass

    def _clear(self):
        while self._root_layout.count():
            it = self._root_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def rebuild_for(self, item):
        """Build form controls tailored to the overlay's type."""
        _QW = QWidget
        editor = self._editor
        ov = item.overlay
        kind = f"{type(item).__name__}:{getattr(ov, 'shape_kind', '')}"
        self._current_kind = kind
        self._clear()
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(5)
        form_wrap = _QW()
        form_wrap.setLayout(form)
        self._root_layout.addWidget(form_wrap)

        # Header: the type + a Convert dropdown for shapes
        header = QLabel(f"<b>{ov.type.title()}</b> &mdash; "
                        f"{getattr(ov, 'shape_kind', '')}")
        self._root_layout.insertWidget(0, header)

        # Shape kind converter dropdown - lets users flip an existing
        # shape to a different type (rect <-> ellipse <-> star etc.)
        # without losing the positional data. Mirrors the Convert to
        # action in the right-click menu but more discoverable.
        if isinstance(item, OverlayShapeItem):
            _kind_row = QHBoxLayout()
            _kind_row.setContentsMargins(0, 0, 0, 0)
            _kind_row.addWidget(QLabel("Shape kind"))
            kind_combo = QComboBox()
            _kinds = [
                "rect", "ellipse", "star", "polygon",
                "gradient_linear", "gradient_radial",
                "speech_bubble", "thought_bubble", "burst",
            ]
            for _k in _kinds:
                kind_combo.addItem(_k.replace("_", " ").title(), _k)
            cur_idx = next((i for i, _k in enumerate(_kinds)
                             if _k == ov.shape_kind), 0)
            kind_combo.setCurrentIndex(cur_idx)
            def _convert_kind(_idx, _it=item, _c=kind_combo):
                new_kind = _c.itemData(_idx)
                if new_kind == _it.overlay.shape_kind:
                    return
                _it.overlay.shape_kind = new_kind
                if new_kind.startswith("gradient") and \
                        not _it.overlay.gradient_start_color:
                    _it.overlay.gradient_start_color = "#000000ff"
                    _it.overlay.gradient_end_color = "#00000000"
                if new_kind in ("star", "polygon"):
                    if not getattr(_it.overlay, "star_points", 0):
                        _it.overlay.star_points = (
                            5 if new_kind == "star" else 6)
                _it.prepareGeometryChange()
                _it.update()
                editor._sync_overlays_to_asset()
                editor._rebuild_layer_panel()
                if hasattr(editor, "info_label"):
                    editor.info_label.setText(
                        f"Converted to {new_kind.replace('_', ' ')}")
                if hasattr(editor, "_shape_controls_dlg"):
                    editor._shape_controls_dlg.rebuild_for(_it)
            kind_combo.currentIndexChanged.connect(_convert_kind)
            _kind_row.addWidget(kind_combo, 1)
            _kind_wrap = _QW(); _kind_wrap.setLayout(_kind_row)
            self._root_layout.insertWidget(1, _kind_wrap)

        if isinstance(item, OverlayShapeItem):
            is_bubble = ov.shape_kind in ("speech_bubble", "thought_bubble")
            # Stroke color
            stroke_row = QHBoxLayout()
            stroke_row.setContentsMargins(0, 0, 0, 0)
            stroke_btn = _ColorSwatchButton(is_outline=True)
            stroke_btn.setFixedWidth(30)
            stroke_btn.setSwatchColor(ov.stroke_color or "#000000")
            def _stroke(hex_c, _it=item):
                _it.overlay.stroke_color = hex_c
                _it.update()
                stroke_btn.setSwatchColor(hex_c)
                editor._add_recent_color(hex_c)
                editor._sync_overlays_to_asset()
            stroke_btn.on_color_picked = _stroke
            def _stroke_dialog(_checked=False, _it=item):
                cur = QColor(_it.overlay.stroke_color or "#000000")
                c = QColorDialog.getColor(cur, self, "Stroke color")
                if c.isValid():
                    _stroke(c.name())
            stroke_btn.clicked.connect(_stroke_dialog)
            stroke_row.addWidget(stroke_btn)
            stroke_row.addStretch()
            _srw = _QW(); _srw.setLayout(stroke_row)
            form.addRow("Stroke color", _srw)

            # Fill color
            fill_row = QHBoxLayout()
            fill_row.setContentsMargins(0, 0, 0, 0)
            fill_btn = _ColorSwatchButton(is_outline=False)
            fill_btn.setFixedWidth(30)
            fill_btn.setSwatchColor(ov.fill_color or "#ffffff")
            def _fill(hex_c, _it=item):
                _it.overlay.fill_color = hex_c
                _it.update()
                fill_btn.setSwatchColor(hex_c)
                editor._add_recent_color(hex_c)
                editor._sync_overlays_to_asset()
            fill_btn.on_color_picked = _fill
            def _fill_dialog(_checked=False, _it=item):
                cur = QColor(_it.overlay.fill_color or "#ffffff")
                c = QColorDialog.getColor(cur, self, "Fill color",
                                          QColorDialog.ColorDialogOption.ShowAlphaChannel)
                if c.isValid():
                    _fill(c.name())
            fill_btn.clicked.connect(_fill_dialog)
            fill_row.addWidget(fill_btn)
            clear_btn = QPushButton("Clear")
            clear_btn.setObjectName("studio_prop_btn")
            clear_btn.setMinimumWidth(56)
            def _clear_fill(_checked=False, _it=item):
                _it.overlay.fill_color = ""
                _it.update()
                editor._sync_overlays_to_asset()
            clear_btn.clicked.connect(_clear_fill)
            fill_row.addWidget(clear_btn)
            # Random pleasing color (uses HSL with mid brightness +
            # saturation so results don't go black / neon). Seeds the
            # color into fill, recent colors, and the swatch preview.
            # Text label instead of dice glyph - the emoji rendered as
            # a single letter on Windows default fonts.
            rand_btn = QPushButton("Rand")
            rand_btn.setObjectName("studio_prop_btn")
            rand_btn.setMinimumWidth(56)
            rand_btn.setToolTip(
                "Random pleasing color (HSL mid-brightness).")
            def _rand_fill(_checked=False, _it=item):
                import random as _rand
                h = _rand.randint(0, 359)
                s = _rand.randint(55, 95)
                l = _rand.randint(42, 68)
                c = QColor.fromHsl(h, int(s * 2.55), int(l * 2.55))
                hex_c = c.name()
                _it.overlay.fill_color = hex_c
                _it.update()
                fill_btn.setSwatchColor(hex_c)
                editor._add_recent_color(hex_c)
                editor._sync_overlays_to_asset()
            rand_btn.clicked.connect(_rand_fill)
            fill_row.addWidget(rand_btn)
            fill_row.addStretch()
            _frw = _QW(); _frw.setLayout(fill_row)
            form.addRow("Fill color", _frw)

            # Stroke width — spin + preset buttons
            sw_row = QHBoxLayout()
            sw_row.setContentsMargins(0, 0, 0, 0)
            sw_spin = QSpinBox()
            sw_spin.setRange(0, 50)
            sw_spin.setValue(ov.stroke_width or 2)
            sw_spin.setSuffix(" px")
            sw_spin.setFixedWidth(70)
            def _sw_changed(v, _it=item):
                _it.overlay.stroke_width = v
                _it.update()
                editor._sync_overlays_to_asset()
            sw_spin.valueChanged.connect(_sw_changed)
            sw_row.addWidget(sw_spin)
            # Preset width quick-pick buttons. Explicit minimum width
            # so the digit stays legible on themes that expand the
            # default button padding.
            for _w in (1, 2, 4, 8, 16):
                pb = QPushButton(str(_w))
                pb.setMinimumWidth(34)
                pb.setMaximumWidth(42)
                pb.setToolTip(f"Stroke {_w} px")
                def _pick(_checked=False, v=_w):
                    sw_spin.setValue(v)
                pb.clicked.connect(_pick)
                sw_row.addWidget(pb)
            sw_row.addStretch()
            sw_widget = _QW(); sw_widget.setLayout(sw_row)
            form.addRow("Stroke width", sw_widget)

            # Line style
            style_combo = QComboBox()
            style_combo.addItems(["solid", "dash", "dot"])
            style_combo.setCurrentText(ov.line_style)
            def _style_changed(s, _it=item):
                _it.overlay.line_style = s
                _it.update()
                editor._sync_overlays_to_asset()
            style_combo.currentTextChanged.connect(_style_changed)
            form.addRow("Line style", style_combo)

            # Blend mode — Photoshop-style layer effect
            blend_combo = QComboBox()
            blend_combo.addItems([
                "normal", "multiply", "screen", "overlay",
                "darken", "lighten"])
            blend_combo.setCurrentText(ov.blend_mode)
            def _blend_changed(m, _it=item):
                _it.overlay.blend_mode = m
                _it.update()
                editor._sync_overlays_to_asset()
            blend_combo.currentTextChanged.connect(_blend_changed)
            form.addRow("Blend mode", blend_combo)

            # Save-as-default row. Persists stroke / fill / width / line
            # style as the defaults applied to newly-drawn shapes. Paired
            # with an Apply-default button for round-trip.
            sd_row = QHBoxLayout()
            sd_row.setContentsMargins(0, 0, 0, 0)
            reset_btn = QPushButton("Reset Transform")
            reset_btn.setObjectName("studio_prop_btn")
            reset_btn.setToolTip(
                "Zero rotation / skew / flip + blend mode 'normal' on "
                "the selected shape(s).")
            def _reset_transform(_checked=False, _it=item):
                sel_shapes = [x for x in editor._scene.selectedItems()
                              if isinstance(x, OverlayShapeItem)] or [_it]
                for x in sel_shapes:
                    ov_x = x.overlay
                    ov_x.rotation = 0.0
                    ov_x.skew_x = 0.0
                    ov_x.skew_y = 0.0
                    ov_x.flip_h = False
                    ov_x.flip_v = False
                    ov_x.blend_mode = "normal"
                    x.setRotation(0)
                    x.setTransform(QTransform())
                    x.update()
                editor._sync_overlays_to_asset()
                if hasattr(editor, "info_label"):
                    editor.info_label.setText(
                        f"Reset transform on {len(sel_shapes)} shape(s)")
            reset_btn.clicked.connect(_reset_transform)
            form.addRow("", reset_btn)

            save_default_btn = QPushButton("Save Default")
            save_default_btn.setObjectName("studio_prop_btn")
            save_default_btn.setToolTip(
                "Current stroke / fill / width / line style become the "
                "defaults for new shapes drawn with the Shape tool.")
            def _save_default(_checked=False, _it=item):
                qs = QSettings("DoxyEdit", "DoxyEdit")
                qs.setValue("studio_shape_stroke_color",
                             _it.overlay.stroke_color or "#000000")
                qs.setValue("studio_shape_fill_color",
                             _it.overlay.fill_color or "")
                qs.setValue("studio_shape_stroke_width",
                             int(_it.overlay.stroke_width or 2))
                qs.setValue("studio_shape_line_style",
                             getattr(_it.overlay, "line_style", "solid"))
                qs.setValue("studio_shape_corner_radius",
                             int(_it.overlay.corner_radius or 0))
                if hasattr(editor, "info_label"):
                    editor.info_label.setText(
                        "Saved default shape style")
            save_default_btn.clicked.connect(_save_default)
            sd_row.addWidget(save_default_btn)

            apply_default_btn = QPushButton("Apply Default")
            apply_default_btn.setObjectName("studio_prop_btn")
            apply_default_btn.setToolTip(
                "Apply the saved default shape style to every "
                "selected shape.")
            def _apply_default():
                qs = QSettings("DoxyEdit", "DoxyEdit")
                sel = [it for it in editor._scene.selectedItems()
                       if isinstance(it, OverlayShapeItem)]
                if not sel:
                    if hasattr(editor, "info_label"):
                        editor.info_label.setText(
                            "Select shapes to apply default")
                    return
                for _it in sel:
                    _ov = _it.overlay
                    _ov.stroke_color = qs.value(
                        "studio_shape_stroke_color",
                        _ov.stroke_color or "#000000", type=str)
                    _ov.fill_color = qs.value(
                        "studio_shape_fill_color",
                        _ov.fill_color or "", type=str)
                    _ov.stroke_width = qs.value(
                        "studio_shape_stroke_width",
                        _ov.stroke_width or 2, type=int)
                    _ov.line_style = qs.value(
                        "studio_shape_line_style",
                        getattr(_ov, "line_style", "solid"), type=str)
                    _ov.corner_radius = qs.value(
                        "studio_shape_corner_radius",
                        _ov.corner_radius or 0, type=int)
                    _it.update()
                editor._sync_overlays_to_asset()
                if hasattr(editor, "info_label"):
                    editor.info_label.setText(
                        f"Applied default to {len(sel)} shape(s)")
            apply_default_btn.clicked.connect(_apply_default)
            sd_row.addWidget(apply_default_btn)
            sd_row.addStretch()
            _sdw = _QW(); _sdw.setLayout(sd_row)
            form.addRow("", _sdw)

            # Stroke alignment: inside / center / outside. Affects where
            # the stroke sits relative to the shape bounds.
            align_combo = QComboBox()
            align_combo.addItems(["inside", "center", "outside"])
            align_combo.setCurrentText(
                ov.stroke_align)
            align_combo.setToolTip(
                "Where the stroke sits relative to the shape:\n"
                "• inside - stroke entirely within the shape bounds\n"
                "• center - stroke straddles the edge (default)\n"
                "• outside - stroke entirely outside the bounds")
            def _align_changed(s, _it=item):
                _it.overlay.stroke_align = s
                _it.prepareGeometryChange()
                _it.update()
                editor._sync_overlays_to_asset()
            align_combo.currentTextChanged.connect(_align_changed)
            form.addRow("Stroke align", align_combo)

            # Swap fill <-> stroke colors. Illustrator 'X' equivalent.
            # Only meaningful when stroke_width > 0 (otherwise the
            # swapped stroke is invisible).
            swap_btn = QPushButton("Swap fill ↔ stroke color")
            swap_btn.setObjectName("studio_prop_btn")
            swap_btn.setToolTip(
                "Exchange the fill color with the stroke color. "
                "Illustrator calls this 'X'.")
            def _swap_fs(_checked=False, _it=item):
                ov_s = _it.overlay
                ov_s.fill_color, ov_s.stroke_color = (
                    ov_s.stroke_color, ov_s.fill_color)
                _it.update()
                editor._sync_overlays_to_asset()
                # Refresh this dialog so the swatch buttons update.
                if hasattr(editor, "_shape_controls_dlg"):
                    editor._shape_controls_dlg.rebuild_for(_it)
                if hasattr(editor, "info_label"):
                    editor.info_label.setText("Swapped fill and stroke")
            swap_btn.clicked.connect(_swap_fs)
            form.addRow("", swap_btn)

            # Corner radius (only for non-bubble rects)
            if ov.shape_kind == "rect":
                cr_spin = QSpinBox()
                cr_spin.setRange(0, 200)
                cr_spin.setValue(ov.corner_radius or 0)
                cr_spin.setSuffix(" px")
                def _cr_changed(v, _it=item):
                    _it.overlay.corner_radius = v
                    _it.update()
                    editor._sync_overlays_to_asset()
                cr_spin.valueChanged.connect(_cr_changed)
                form.addRow("Corner radius", cr_spin)

            # Make square (rect / ellipse) -> force w == h, centered on
            # current midpoint so the shape doesn't jump. Handy for
            # turning a freehand ellipse into a perfect circle.
            if ov.shape_kind in ("rect", "ellipse"):
                square_btn = QPushButton("Make perfect square / circle")
                square_btn.setObjectName("studio_prop_btn")
                square_btn.setToolTip(
                    "Equalize width and height (using the larger of the "
                    "two), keeping the shape centered in place.")
                def _make_square(_checked=False, _it=item):
                    ov_s = _it.overlay
                    side = max(int(ov_s.shape_w), int(ov_s.shape_h))
                    cx = ov_s.x + ov_s.shape_w / 2
                    cy = ov_s.y + ov_s.shape_h / 2
                    ov_s.shape_w = side
                    ov_s.shape_h = side
                    ov_s.x = int(round(cx - side / 2))
                    ov_s.y = int(round(cy - side / 2))
                    _it.prepareGeometryChange()
                    _it.setPos(ov_s.x, ov_s.y)
                    _it.update()
                    editor._sync_overlays_to_asset()
                    if hasattr(editor, "info_label"):
                        kind = ("circle" if ov_s.shape_kind == "ellipse"
                                else "square")
                        editor.info_label.setText(
                            f"Snapped to {side}x{side} {kind}")
                square_btn.clicked.connect(_make_square)
                form.addRow("", square_btn)

            # Gradient presets — only when the shape is a gradient.
            if ov.shape_kind in ("gradient_linear", "gradient_radial"):
                self._root_layout.addWidget(QLabel("<b>Gradient</b>"))
                preset_row = QHBoxLayout()
                preset_row.setContentsMargins(0, 0, 0, 0)
                preset_combo = QComboBox()
                preset_combo.addItems([
                    "(current)", "Monochrome (black -> transparent)",
                    "Sunset (orange -> pink)", "Ocean (blue -> teal)",
                    "Fire (red -> yellow)", "Forest (green -> lime)",
                    "Dusk (purple -> navy)", "Paper (cream -> warm)",
                    "Vignette (black -> transparent)",
                ])
                presets = {
                    "Monochrome (black -> transparent)":
                        ("#000000ff", "#00000000"),
                    "Sunset (orange -> pink)": ("#ff7043", "#ec407a"),
                    "Ocean (blue -> teal)": ("#1e88e5", "#00acc1"),
                    "Fire (red -> yellow)": ("#e53935", "#fdd835"),
                    "Forest (green -> lime)": ("#2e7d32", "#c0ca33"),
                    "Dusk (purple -> navy)": ("#5e35b1", "#1a237e"),
                    "Paper (cream -> warm)": ("#fff8e1", "#ffccbc"),
                    "Vignette (black -> transparent)":
                        ("#000000ff", "#00000000"),
                }
                def _apply_preset(name, _it=item):
                    if name == "(current)" or name not in presets:
                        return
                    s, e = presets[name]
                    _it.overlay.gradient_start_color = s
                    _it.overlay.gradient_end_color = e
                    _it.update()
                    editor._sync_overlays_to_asset()
                    if hasattr(editor, "info_label"):
                        editor.info_label.setText(f"Gradient: {name}")
                preset_combo.currentTextChanged.connect(_apply_preset)
                preset_row.addWidget(preset_combo, 1)
                swap_btn = QPushButton("Swap")
                swap_btn.setObjectName("studio_prop_btn")
                swap_btn.setToolTip("Swap gradient start / end colors")
                def _swap_grad(_checked=False, _it=item):
                    _it.overlay.gradient_start_color, \
                        _it.overlay.gradient_end_color = (
                            _it.overlay.gradient_end_color,
                            _it.overlay.gradient_start_color)
                    _it.update()
                    editor._sync_overlays_to_asset()
                swap_btn.clicked.connect(_swap_grad)
                preset_row.addWidget(swap_btn)
                # Angle spin for linear gradients
                if ov.shape_kind == "gradient_linear":
                    angle_spin = QSpinBox()
                    angle_spin.setRange(-360, 360)
                    angle_spin.setSuffix("°")
                    angle_spin.setValue(int(ov.gradient_angle))
                    angle_spin.setFixedWidth(70)
                    def _angle_changed(v, _it=item):
                        _it.overlay.gradient_angle = v
                        _it.update()
                        editor._sync_overlays_to_asset()
                    angle_spin.valueChanged.connect(_angle_changed)
                    preset_row.addWidget(angle_spin)
                _pw = _QW()
                _pw.setLayout(preset_row)
                grad_form = QFormLayout()
                grad_form.setContentsMargins(0, 0, 0, 0)
                grad_form.addRow("Preset", _pw)
                _gfw = _QW()
                _gfw.setLayout(grad_form)
                self._root_layout.addWidget(_gfw)

            # Star / polygon params — shared star_points + inner_ratio
            if ov.shape_kind in ("star", "polygon"):
                self._root_layout.addWidget(QLabel("<b>Polygon / Star</b>"))
                sp_form = QFormLayout()
                sp_form.setContentsMargins(0, 0, 0, 0)
                sp_form.setSpacing(5)
                pts_spin = QSpinBox()
                pts_spin.setRange(3, 50)
                pts_spin.setValue(int(ov.star_points or 5))
                pts_spin.setToolTip(
                    "Star: number of outer points. Polygon: vertex count.")
                def _pts_changed(v, _it=item):
                    _it.overlay.star_points = v
                    _it.prepareGeometryChange()
                    _it.update()
                    editor._sync_overlays_to_asset()
                pts_spin.valueChanged.connect(_pts_changed)
                sp_form.addRow("Points / sides", pts_spin)
                if ov.shape_kind == "star":
                    ir_slider = QSlider(Qt.Orientation.Horizontal)
                    ir_slider.setRange(10, 95)
                    ir_slider.setValue(int(
                        float(ov.inner_ratio or 0.4) * 100))
                    ir_slider.setMinimumWidth(150)
                    ir_lbl = QLabel(
                        f"{int(float(getattr(ov, 'inner_ratio', 0.4) or 0.4) * 100)}%")
                    ir_lbl.setFixedWidth(40)
                    ir_lbl.setObjectName('shape_value_label')
                    def _ir_changed(v, _it=item, _lbl=ir_lbl):
                        _it.overlay.inner_ratio = v / 100.0
                        _it.prepareGeometryChange()
                        _it.update()
                        _lbl.setText(f"{v}%")
                        editor._sync_overlays_to_asset()
                    ir_slider.valueChanged.connect(_ir_changed)
                    ir_row = QHBoxLayout()
                    ir_row.setContentsMargins(0, 0, 0, 0)
                    ir_row.addWidget(ir_slider, 1)
                    ir_row.addWidget(ir_lbl)
                    _ir_w = _QW(); _ir_w.setLayout(ir_row)
                    sp_form.addRow("Inner radius", _ir_w)
                _sp_w = _QW(); _sp_w.setLayout(sp_form)
                self._root_layout.addWidget(_sp_w)

            # Bubble deformers — only when the shape is a bubble
            if is_bubble:
                self._root_layout.addWidget(QLabel("<b>Bubble shape</b>"))
                deform_form = QFormLayout()
                deform_form.setContentsMargins(0, 0, 0, 0)
                deform_form.setSpacing(5)

                def _mk_slider(attr, lo, hi, step=1):
                    sl = QSlider(Qt.Orientation.Horizontal)
                    # Store as int*100 for QSlider; convert to float.
                    sl.setRange(int(lo * 100), int(hi * 100))
                    sl.setValue(int(getattr(ov, attr, 0.0) * 100))
                    sl.setMinimumWidth(150)
                    readout = QLabel(f"{getattr(ov, attr, 0.0):+.2f}")
                    readout.setFixedWidth(52)
                    readout.setObjectName('shape_value_label')
                    def _on_change(v, _it=item, _attr=attr, _r=readout):
                        val = v / 100.0
                        setattr(_it.overlay, _attr, val)
                        _it.prepareGeometryChange()
                        _it.update()
                        _r.setText(f"{val:+.2f}")
                        editor._sync_overlays_to_asset()
                    sl.valueChanged.connect(_on_change)
                    row = QHBoxLayout()
                    row.setContentsMargins(0, 0, 0, 0)
                    row.addWidget(sl, 1)
                    row.addWidget(readout)
                    w = _QW(); w.setLayout(row)
                    return w
                deform_form.addRow("Roundness",
                    _mk_slider("bubble_roundness", 0.0, 2.0))
                deform_form.addRow("Oval stretch",
                    _mk_slider("bubble_oval_stretch", -1.2, 1.2))
                deform_form.addRow("Wobble",
                    _mk_slider("bubble_wobble", 0.0, 2.0))
                # Wobble complexity = bump count around the perimeter.
                # Slider stores its value as int*100 like the others
                # but scales to the int range via _mk_int_slider.
                # Slider + readout cell widths shared with _mk_slider
                # above so the int and float deformer rows align
                # visually. Defined once here; both helpers read the
                # same value.
                DEFORMER_SLIDER_MIN_WIDTH = 150
                DEFORMER_READOUT_WIDTH = 52
                def _mk_int_slider(attr, lo, hi, fmt="{:d}"):
                    sl = QSlider(Qt.Orientation.Horizontal)
                    sl.setRange(int(lo), int(hi))
                    sl.setValue(int(getattr(ov, attr, lo) or lo))
                    sl.setMinimumWidth(DEFORMER_SLIDER_MIN_WIDTH)
                    readout = QLabel(fmt.format(int(getattr(ov, attr, lo) or lo)))
                    readout.setFixedWidth(DEFORMER_READOUT_WIDTH)
                    readout.setObjectName('shape_value_label')
                    def _on_change(v, _it=item, _attr=attr, _r=readout):
                        setattr(_it.overlay, _attr, int(v))
                        _it.prepareGeometryChange()
                        _it.update()
                        _r.setText(fmt.format(int(v)))
                        editor._sync_overlays_to_asset()
                    sl.valueChanged.connect(_on_change)
                    row = QHBoxLayout()
                    row.setContentsMargins(0, 0, 0, 0)
                    row.addWidget(sl, 1)
                    row.addWidget(readout)
                    w = _QW(); w.setLayout(row)
                    return w
                deform_form.addRow("Waves",
                    _mk_int_slider("bubble_wobble_waves", 2, 32))
                deform_form.addRow("Complexity",
                    _mk_int_slider("bubble_wobble_complexity", 16, 512))
                deform_form.addRow("Seed",
                    _mk_int_slider("bubble_wobble_seed", 0, 999))
                deform_form.addRow("Skew X",
                    _mk_slider("bubble_skew_x", -1.0, 1.0))
                deform_form.addRow("Tail curve",
                    _mk_slider("tail_curve", -2.0, 2.0))
                deform_form.addRow("Tail width",
                    _mk_slider("bubble_tail_width", 0.2, 3.0))
                deform_form.addRow("Tail taper",
                    _mk_slider("bubble_tail_taper", -1.0, 1.0))
                reset_def_btn = QPushButton("Reset Deformers")
                reset_def_btn.setObjectName("studio_prop_btn")
                reset_def_btn.setToolTip(
                    "Zero bubble roundness / oval / wobble / tail curve "
                    "back to their default values.")
                def _reset_def(_checked=False, _it=item):
                    ov_r = _it.overlay
                    ov_r.bubble_roundness = 0.0
                    ov_r.bubble_oval_stretch = 0.0
                    ov_r.bubble_wobble = 0.0
                    ov_r.bubble_wobble_waves = 8
                    ov_r.bubble_wobble_complexity = 72
                    ov_r.bubble_wobble_seed = 0
                    ov_r.bubble_skew_x = 0.0
                    ov_r.bubble_tail_width = 1.0
                    ov_r.bubble_tail_taper = 0.0
                    ov_r.tail_curve = 0.0
                    _it.prepareGeometryChange()
                    _it.update()
                    editor._sync_overlays_to_asset()
                    # Rebuild so the slider positions reset too
                    if hasattr(editor, "_shape_controls_dlg"):
                        editor._shape_controls_dlg.rebuild_for(_it)
                    if hasattr(editor, "info_label"):
                        editor.info_label.setText("Bubble deformers reset")
                reset_def_btn.clicked.connect(_reset_def)
                deform_form.addRow("", reset_def_btn)
                deform_wrap = _QW()
                deform_wrap.setLayout(deform_form)
                self._root_layout.addWidget(deform_wrap)

            # Opacity slider (common)
            op_slider = QSlider(Qt.Orientation.Horizontal)
            op_slider.setRange(0, 100)
            op_slider.setValue(int(ov.opacity * 100))
            op_slider.setMinimumWidth(150)
            op_lbl = QLabel(f"{int(ov.opacity * 100)}%")
            op_lbl.setFixedWidth(40)
            op_lbl.setObjectName('shape_value_label')
            def _op_changed(v, _it=item, _lbl=op_lbl):
                _it.overlay.opacity = v / 100.0
                _it.update()
                _lbl.setText(f"{v}%")
                editor._sync_overlays_to_asset()
            op_slider.valueChanged.connect(_op_changed)
            op_row = QHBoxLayout()
            op_row.setContentsMargins(0, 0, 0, 0)
            op_row.addWidget(op_slider, 1)
            op_row.addWidget(op_lbl)
            _op_w = _QW(); _op_w.setLayout(op_row)
            form.addRow("Opacity", _op_w)

            # Rotation slider (-180 to 180)
            rot_slider = QSlider(Qt.Orientation.Horizontal)
            rot_slider.setRange(-180, 180)
            rot_init = int(ov.rotation)
            if rot_init > 180:
                rot_init -= 360
            rot_slider.setValue(rot_init)
            rot_slider.setMinimumWidth(150)
            rot_lbl = QLabel(f"{rot_init}°")
            rot_lbl.setObjectName('shape_value_label')
            rot_lbl.setFixedWidth(44)
            rot_lbl.setObjectName('shape_value_label')
            def _rot_changed(v, _it=item, _lbl=rot_lbl):
                _it.overlay.rotation = v % 360
                _it.setTransformOriginPoint(
                    _it.overlay.x + _it.overlay.shape_w / 2,
                    _it.overlay.y + _it.overlay.shape_h / 2)
                _it.setRotation(_it.overlay.rotation)
                _it.update()
                _lbl.setText(f"{v}°")
                editor._sync_overlays_to_asset()
            rot_slider.valueChanged.connect(_rot_changed)
            rot_row = QHBoxLayout()
            rot_row.setContentsMargins(0, 0, 0, 0)
            rot_row.addWidget(rot_slider, 1)
            rot_row.addWidget(rot_lbl)
            _rot_w = _QW(); _rot_w.setLayout(rot_row)
            form.addRow("Rotation", _rot_w)

            # Scale slider (20-500%, applied relative to captured base)
            sc_slider = QSlider(Qt.Orientation.Horizontal)
            sc_slider.setRange(20, 500)
            sc_slider.setValue(100)
            sc_slider.setMinimumWidth(150)
            sc_lbl = QLabel("100%")
            sc_lbl.setObjectName('shape_value_label')
            sc_lbl.setFixedWidth(44)
            sc_lbl.setObjectName('shape_value_label')
            # Freeze baseline so slider==100% keeps the current size
            _base = {
                "w": ov.shape_w, "h": ov.shape_h,
                "cx": ov.x + ov.shape_w / 2,
                "cy": ov.y + ov.shape_h / 2,
            }
            def _sc_changed(v, _it=item, _lbl=sc_lbl, _b=_base):
                f = v / 100.0
                new_w = max(4, int(_b["w"] * f))
                new_h = max(4, int(_b["h"] * f))
                _it.overlay.shape_w = new_w
                _it.overlay.shape_h = new_h
                _it.overlay.x = int(_b["cx"] - new_w / 2)
                _it.overlay.y = int(_b["cy"] - new_h / 2)
                _it.prepareGeometryChange()
                _it.update()
                _lbl.setText(f"{v}%")
                editor._sync_overlays_to_asset()
            sc_slider.valueChanged.connect(_sc_changed)
            sc_row = QHBoxLayout()
            sc_row.setContentsMargins(0, 0, 0, 0)
            sc_row.addWidget(sc_slider, 1)
            sc_row.addWidget(sc_lbl)
            _sc_w = _QW(); _sc_w.setLayout(sc_row)
            form.addRow("Scale", _sc_w)

            # X / Y position: slider + numeric spin bound together,
            # updating live. Range bounded to the current canvas +
            # a margin so sliders don't drag items wildly off-screen.
            pm_w = pm_h = 2000
            if self._editor is not None and self._editor._pixmap_item:
                _pm = self._editor._pixmap_item.pixmap()
                pm_w = max(400, _pm.width())
                pm_h = max(400, _pm.height())
            def _mk_pos_row(attr, lo, hi, default):
                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(lo, hi)
                sl.setValue(default)
                sl.setMinimumWidth(130)
                sp = QSpinBox()
                sp.setRange(lo, hi)
                sp.setSuffix(" px")
                sp.setValue(default)
                sp.setFixedWidth(78)
                def _on_change(v, _it=item, _attr=attr):
                    setattr(_it.overlay, _attr, int(v))
                    if _attr == "x":
                        _it.overlay.x = int(v)
                    else:
                        _it.overlay.y = int(v)
                    # Shape pivots on center, so just repaint + sync.
                    _it.prepareGeometryChange()
                    _it.update()
                    editor._sync_overlays_to_asset()
                def _sl_to_sp(v):
                    sp.blockSignals(True); sp.setValue(v); sp.blockSignals(False)
                    _on_change(v)
                def _sp_to_sl(v):
                    sl.blockSignals(True); sl.setValue(v); sl.blockSignals(False)
                    _on_change(v)
                sl.valueChanged.connect(_sl_to_sp)
                sp.valueChanged.connect(_sp_to_sl)
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(sl, 1); row.addWidget(sp)
                w = _QW(); w.setLayout(row)
                return w
            form.addRow("X", _mk_pos_row("x", 0, pm_w, int(ov.x)))
            form.addRow("Y", _mk_pos_row("y", 0, pm_h, int(ov.y)))

        elif isinstance(item, OverlayImageItem):
            # Image overlay: scale slider + filter mode picker +
            # opacity. Builds on top of the quickbar which only exposes
            # scale/rotation/opacity spinboxes - here we get sliders with
            # live previews.
            sc_slider = QSlider(Qt.Orientation.Horizontal)
            sc_slider.setRange(1, 1000)
            sc_slider.setValue(int(ov.scale * 100))
            sc_slider.setMinimumWidth(150)
            sc_lbl = QLabel(f"{int(ov.scale * 100)}%")
            sc_lbl.setFixedWidth(40)
            sc_lbl.setObjectName('shape_value_label')
            def _img_scale(v, _it=item, _lbl=sc_lbl):
                _it.overlay.scale = v / 100.0
                if hasattr(editor, "_refresh_overlay_image"):
                    editor._refresh_overlay_image(_it)
                else:
                    _it.update()
                _lbl.setText(f"{v}%")
                editor._sync_overlays_to_asset()
            sc_slider.valueChanged.connect(_img_scale)
            sc_row = QHBoxLayout()
            sc_row.setContentsMargins(0, 0, 0, 0)
            sc_row.addWidget(sc_slider, 1)
            sc_row.addWidget(sc_lbl)
            _sc_w = _QW(); _sc_w.setLayout(sc_row)
            form.addRow("Scale", _sc_w)

            # Opacity slider
            op_slider = QSlider(Qt.Orientation.Horizontal)
            op_slider.setRange(0, 100)
            op_slider.setValue(int(ov.opacity * 100))
            op_slider.setMinimumWidth(150)
            op_lbl = QLabel(f"{int(ov.opacity * 100)}%")
            op_lbl.setFixedWidth(40)
            op_lbl.setObjectName('shape_value_label')
            def _img_op(v, _it=item, _lbl=op_lbl):
                _it.overlay.opacity = v / 100.0
                _it.setOpacity(v / 100.0)
                _lbl.setText(f"{v}%")
                editor._sync_overlays_to_asset()
            op_slider.valueChanged.connect(_img_op)
            op_row = QHBoxLayout()
            op_row.setContentsMargins(0, 0, 0, 0)
            op_row.addWidget(op_slider, 1)
            op_row.addWidget(op_lbl)
            _op_w = _QW(); _op_w.setLayout(op_row)
            form.addRow("Opacity", _op_w)

            # Rotation slider
            rot_slider = QSlider(Qt.Orientation.Horizontal)
            rot_slider.setRange(-180, 180)
            rot_init = int(ov.rotation)
            if rot_init > 180:
                rot_init -= 360
            rot_slider.setValue(rot_init)
            rot_slider.setMinimumWidth(150)
            rot_lbl = QLabel(f"{rot_init}°")
            rot_lbl.setObjectName('shape_value_label')
            rot_lbl.setFixedWidth(44)
            rot_lbl.setObjectName('shape_value_label')
            def _img_rot(v, _it=item, _lbl=rot_lbl):
                _it.overlay.rotation = v % 360
                if hasattr(_it, "_apply_flip"):
                    _it._apply_flip()
                _lbl.setText(f"{v}°")
                editor._sync_overlays_to_asset()
            rot_slider.valueChanged.connect(_img_rot)
            rot_row = QHBoxLayout()
            rot_row.setContentsMargins(0, 0, 0, 0)
            rot_row.addWidget(rot_slider, 1)
            rot_row.addWidget(rot_lbl)
            _rot_w = _QW(); _rot_w.setLayout(rot_row)
            form.addRow("Rotation", _rot_w)

            # Filter-mode picker
            fm_combo = QComboBox()
            fm_combo.addItem("None", "")
            fm_combo.addItem("Grayscale", "grayscale")
            fm_combo.addItem("Invert", "invert")
            fm_combo.addItem("Blur (small)", "blur3")
            fm_combo.addItem("Blur (heavy)", "blur8")
            current_filter = ov.filter_mode
            for idx in range(fm_combo.count()):
                if fm_combo.itemData(idx) == current_filter:
                    fm_combo.setCurrentIndex(idx)
                    break
            def _img_filter(_text, _it=item):
                idx = fm_combo.currentIndex()
                _it.overlay.filter_mode = fm_combo.itemData(idx) or ""
                if hasattr(editor, "_refresh_overlay_image"):
                    editor._refresh_overlay_image(_it)
                editor._sync_overlays_to_asset()
            fm_combo.currentTextChanged.connect(_img_filter)
            form.addRow("Filter", fm_combo)

            # Blend mode
            bl_combo = QComboBox()
            bl_combo.addItems([
                "normal", "multiply", "screen", "overlay",
                "darken", "lighten"])
            bl_combo.setCurrentText(ov.blend_mode)
            def _img_blend(m, _it=item):
                _it.overlay.blend_mode = m
                _it.update()
                editor._sync_overlays_to_asset()
            bl_combo.currentTextChanged.connect(_img_blend)
            form.addRow("Blend mode", bl_combo)

            # Brightness / Contrast / Saturation via PIL ImageEnhance.
            # -100% to +100% on the slider maps to -1.0 .. 1.0 on the
            # overlay field, and PIL factor = 1.0 + value.
            def _mk_adjust(attr, label):
                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(-100, 100)
                sl.setValue(int(
                    float(getattr(ov, attr, 0.0) or 0.0) * 100))
                sl.setMinimumWidth(150)
                lbl = QLabel(f"{sl.value():+d}")
                lbl.setFixedWidth(40)
                lbl.setObjectName('shape_value_label')
                def _on_change(v, _it=item, _attr=attr, _lbl=lbl):
                    setattr(_it.overlay, _attr, v / 100.0)
                    if hasattr(editor, "_refresh_overlay_image"):
                        editor._refresh_overlay_image(_it)
                    _lbl.setText(f"{v:+d}")
                    editor._sync_overlays_to_asset()
                sl.valueChanged.connect(_on_change)
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(sl, 1)
                row.addWidget(lbl)
                w = _QW(); w.setLayout(row)
                return w
            form.addRow("Brightness", _mk_adjust("img_brightness", "Brightness"))
            form.addRow("Contrast", _mk_adjust("img_contrast", "Contrast"))
            form.addRow("Saturation", _mk_adjust("img_saturation", "Saturation"))
            # Reset all three adjustments quickly.
            reset_adj_btn = QPushButton("Reset Adjustments")
            reset_adj_btn.setObjectName("studio_prop_btn")
            reset_adj_btn.setToolTip(
                "Zero brightness / contrast / saturation back to defaults.")
            def _reset_adj(_checked=False, _it=item):
                _it.overlay.img_brightness = 0.0
                _it.overlay.img_contrast = 0.0
                _it.overlay.img_saturation = 0.0
                if hasattr(editor, "_refresh_overlay_image"):
                    editor._refresh_overlay_image(_it)
                editor._sync_overlays_to_asset()
                if hasattr(editor, "_shape_controls_dlg"):
                    editor._shape_controls_dlg.rebuild_for(_it)
                if hasattr(editor, "info_label"):
                    editor.info_label.setText("Image adjustments reset")
            reset_adj_btn.clicked.connect(_reset_adj)
            form.addRow("", reset_adj_btn)

            # Save-as-default row for watermark/image overlays.
            img_save_btn = QPushButton("Save as default watermark style")
            img_save_btn.setObjectName("studio_prop_btn")
            img_save_btn.setToolTip(
                "Current scale / opacity / filter / blend / adjustments "
                "become the defaults for newly-dropped watermarks.")
            def _img_save_default(_checked=False, _it=item):
                if hasattr(editor, "_save_watermark_style_as_default"):
                    editor._save_watermark_style_as_default(_it.overlay)
                elif hasattr(editor, "info_label"):
                    editor.info_label.setText(
                        "Watermark default save unavailable")
            img_save_btn.clicked.connect(_img_save_default)
            form.addRow("", img_save_btn)

        elif isinstance(item, OverlayArrowItem):
            # Arrow: color, width, arrowhead size / style, double-headed
            color_btn = _ColorSwatchButton(is_outline=False)
            color_btn.setFixedWidth(30)
            color_btn.setSwatchColor(ov.color or "#000000")
            def _arrow_color(hex_c, _it=item):
                # Defensive: if the captured item has been detached
                # from the scene (rebuild happened between click and
                # dialog return), look up the live item by overlay
                # identity.
                live = _it
                if live.scene() is None and editor is not None:
                    for _x in editor._overlay_items:
                        if getattr(_x, "overlay", None) is _it.overlay:
                            live = _x
                            break
                live.overlay.color = hex_c
                # Force full invalidation: update() alone wasn't enough
                # if the bounding rect hadn't been dirtied.
                live.prepareGeometryChange()
                live.update()
                if live.scene() is not None:
                    live.scene().update(live.sceneBoundingRect())
                color_btn.setSwatchColor(hex_c)
                editor._add_recent_color(hex_c)
                editor._sync_overlays_to_asset()
            color_btn.on_color_picked = _arrow_color
            def _arrow_color_dlg(_checked=False, _it=item):
                cur = QColor(_it.overlay.color or "#000000")
                c = QColorDialog.getColor(cur, self, "Arrow color")
                if c.isValid():
                    _arrow_color(c.name())
            color_btn.clicked.connect(_arrow_color_dlg)
            form.addRow("Color", color_btn)

            sw_spin = QSpinBox()
            sw_spin.setRange(1, 30)
            sw_spin.setValue(ov.stroke_width or 3)
            sw_spin.setSuffix(" px")
            sw_spin.setFixedWidth(70)
            def _arrow_sw(v, _it=item):
                _it.overlay.stroke_width = v
                _it.update()
                editor._sync_overlays_to_asset()
            sw_spin.valueChanged.connect(_arrow_sw)
            a_sw_row = QHBoxLayout()
            a_sw_row.setContentsMargins(0, 0, 0, 0)
            a_sw_row.addWidget(sw_spin)
            for _aw in (1, 2, 3, 5, 8):
                apb = QPushButton(str(_aw))
                apb.setMinimumWidth(34)
                apb.setMaximumWidth(42)
                apb.setToolTip(f"Line {_aw} px")
                def _apick(_checked=False, v=_aw):
                    sw_spin.setValue(v)
                apb.clicked.connect(_apick)
                a_sw_row.addWidget(apb)
            a_sw_row.addStretch()
            a_sw_w = _QW(); a_sw_w.setLayout(a_sw_row)
            form.addRow("Line width", a_sw_w)

            head_spin = QSpinBox()
            head_spin.setRange(4, 80)
            head_spin.setValue(ov.arrowhead_size or 18)
            head_spin.setSuffix(" px")
            def _arrow_head(v, _it=item):
                _it.overlay.arrowhead_size = v
                _it.update()
                editor._sync_overlays_to_asset()
            head_spin.valueChanged.connect(_arrow_head)
            form.addRow("Arrowhead size", head_spin)

            style_combo = QComboBox()
            style_combo.addItems(["filled", "outline", "none"])
            style_combo.setCurrentText(ov.arrowhead_style or "filled")
            def _arrow_head_style(s, _it=item):
                _it.overlay.arrowhead_style = s
                _it.update()
                editor._sync_overlays_to_asset()
            style_combo.currentTextChanged.connect(_arrow_head_style)
            form.addRow("Arrowhead style", style_combo)

            ls_combo = QComboBox()
            ls_combo.addItems(["solid", "dash", "dot"])
            ls_combo.setCurrentText(ov.line_style)
            def _arrow_ls(s, _it=item):
                _it.overlay.line_style = s
                _it.update()
                editor._sync_overlays_to_asset()
            ls_combo.currentTextChanged.connect(_arrow_ls)
            form.addRow("Line style", ls_combo)

            dh_btn = QPushButton("Double-headed")
            dh_btn.setObjectName("studio_prop_btn")
            dh_btn.setCheckable(True)
            dh_btn.setChecked(bool(ov.double_headed))
            def _arrow_dh(checked, _it=item):
                _it.overlay.double_headed = bool(checked)
                _it.update()
                editor._sync_overlays_to_asset()
            dh_btn.toggled.connect(_arrow_dh)
            form.addRow("", dh_btn)

            flip_dir_btn = QPushButton("Flip arrow direction")
            flip_dir_btn.setObjectName("studio_prop_btn")
            flip_dir_btn.setToolTip(
                "Swap arrow tail + tip endpoints so the arrow points "
                "the other way without moving the overall line.")
            def _flip_dir(_checked=False, _it=item):
                ov_a = _it.overlay
                ov_a.x, ov_a.end_x = ov_a.end_x, ov_a.x
                ov_a.y, ov_a.end_y = ov_a.end_y, ov_a.y
                _it.prepareGeometryChange()
                _it.update()
                editor._sync_overlays_to_asset()
            flip_dir_btn.clicked.connect(_flip_dir)
            form.addRow("", flip_dir_btn)

            straighten_btn = QPushButton("Straighten (snap to 15°)")
            straighten_btn.setObjectName("studio_prop_btn")
            straighten_btn.setToolTip(
                "Rotate the arrow to the nearest 15° increment while "
                "keeping the tail anchored. Useful for lining up "
                "diagrams and callouts.")
            def _straighten(_checked=False, _it=item):
                ov_a = _it.overlay
                dx = ov_a.end_x - ov_a.x
                dy = ov_a.end_y - ov_a.y
                length = math.hypot(dx, dy)
                if length < 1:
                    return
                angle = math.degrees(math.atan2(dy, dx))
                snapped = round(angle / 15.0) * 15.0
                rad = math.radians(snapped)
                ov_a.end_x = int(round(ov_a.x + length * math.cos(rad)))
                ov_a.end_y = int(round(ov_a.y + length * math.sin(rad)))
                _it.prepareGeometryChange()
                _it.update()
                editor._sync_overlays_to_asset()
                if hasattr(editor, "info_label"):
                    editor.info_label.setText(
                        f"Arrow straightened to {int(snapped)}°")
            straighten_btn.clicked.connect(_straighten)
            form.addRow("", straighten_btn)

        self._root_layout.addStretch(1)


class _TextControlsDialog(QtWidgets.QDialog):
    """QDialog subclass that persists its geometry to QSettings across
    close / hide cycles. Instance-level closeEvent assignment doesn't
    work for Qt virtual methods, so this is the proper subclass.

    Provides Ctrl+P = pin on top toggle and Ctrl+Shift+L / Ctrl+Shift+R
    = snap to the left / right edge of the primary screen. Previous
    'can't dock' complaint: these give three predictable park spots
    without building a real QDockWidget subsystem."""

    _GEOM_KEY = "studio_text_controls_geom"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qs = QSettings("DoxyEdit", "DoxyEdit")
        self._pin_on_top = False
        # Install shortcuts: pin + snap-left / snap-right.
        _pin_sc = QShortcut(QKeySequence("Ctrl+P"), self)
        _pin_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        _pin_sc.activated.connect(self._toggle_pin_on_top)
        _dl_sc = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        _dl_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        _dl_sc.activated.connect(lambda: self._snap_to_edge("left"))
        _dr_sc = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        _dr_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        _dr_sc.activated.connect(lambda: self._snap_to_edge("right"))

    def _toggle_pin_on_top(self):
        self._pin_on_top = not self._pin_on_top
        flags = self.windowFlags()
        if self._pin_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
        self.setWindowTitle(
            "Text Controls (pinned)" if self._pin_on_top
            else "Text Controls")

    def _snap_to_edge(self, side: str):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        w = max(self.width(), 380)
        h = max(self.height(), avail.height() - 40)
        y = avail.top() + 20
        if side == "right":
            x = avail.right() - w - 10
        else:
            x = avail.left() + 10
        self.setGeometry(x, y, w, h)
        self._positioned_once = True

    def _save_geom(self):
        """Debounced 200ms singleshot — matches _ShapeControlsDialog.
        Drag events fire at 60+Hz; without the debounce this slams the
        Windows registry on every pixel."""
        if not hasattr(self, "_save_geom_timer"):
            self._save_geom_timer = QTimer(self)
            self._save_geom_timer.setSingleShot(True)
            self._save_geom_timer.setInterval(200)
            self._save_geom_timer.timeout.connect(self._save_geom_now)
        self._save_geom_timer.start()

    def _save_geom_now(self):
        try:
            self._qs.setValue(self._GEOM_KEY, self.saveGeometry())
        except Exception:
            pass

    def closeEvent(self, ev):
        self._save_geom_now()
        super().closeEvent(ev)

    def hideEvent(self, ev):
        # Catches not-just-close dismissals (e.g. when the Studio tab
        # loses focus and the app hides us programmatically).
        self._save_geom_now()
        super().hideEvent(ev)

    def moveEvent(self, ev):
        # Save geometry on every move so crash-exit doesn't lose it.
        super().moveEvent(ev)
        self._save_geom()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._save_geom()


class _StudioIcons:
    """QPainter-drawn icon factory for Studio toolbar buttons. Avoids
    the 'blank glyph' problem on Windows fonts that don't render
    obscure unicode. Returns QIcon instances with both a light and a
    dark variant so the icon reads against any theme backdrop."""

    @staticmethod
    def _fg() -> str:
        # Read the active theme (not DEFAULT_THEME) so sidebar tool icons
        # contrast against whatever backdrop the user has picked. For
        # light themes (Candy, Dawn, Gold, ...) this resolves to a dark
        # ink; for dark themes (Soot, Midnight, ...) a light ink. On
        # light themes push the ink to a deeper value than text_primary
        # — the default text_primary values hover around #1a1410 which
        # is fine for text but reads washed-out at 1.6-2px line widths
        # against a bright background. Go to near-black for more
        # perceptual weight without looking blown-out.
        tid = QSettings("DoxyEdit", "DoxyEdit").value("theme", DEFAULT_THEME)
        theme = THEMES.get(tid, THEMES[DEFAULT_THEME])
        if _StudioIcons._theme_is_light(theme):
            return "#101010"
        return theme.text_primary

    @staticmethod
    def _theme_is_light(theme) -> bool:
        # Rough perceptual-luminance check on bg_main. Treats anything
        # brighter than mid-grey as a light theme. Matches the themes
        # labelled "light" in themes.py (Bone, Milk Glass, Candy, etc.).
        h = (theme.bg_main or "#000").lstrip("#")
        if len(h) != 6:
            return False
        try:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            return False
        return (0.299 * r + 0.587 * g + 0.114 * b) > 160

    @staticmethod
    def _pen(color_hex: str | None = None, w: float = 1.6) -> QPen:
        if color_hex is None:
            color_hex = _StudioIcons._fg()
        # Thicken the stroke on light themes so the ink carries enough
        # visual weight against the brighter backdrop. Dark themes stay
        # at the base width to preserve the current silhouette.
        tid = QSettings("DoxyEdit", "DoxyEdit").value("theme", DEFAULT_THEME)
        theme = THEMES.get(tid, THEMES[DEFAULT_THEME])
        if _StudioIcons._theme_is_light(theme):
            w = max(w, w + 0.4)
        p = QPen(QColor(color_hex), w)
        p.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return p

    @staticmethod
    def make(draw_fn, size: int = 20, color: str | None = None) -> QIcon:
        if color is None:
            color = _StudioIcons._fg()
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(_StudioIcons._pen(color))
        p.setBrush(Qt.BrushStyle.NoBrush)
        draw_fn(p, size)
        p.end()
        return QIcon(pix)

    @staticmethod
    def select():
        def d(p, s):
            # Arrow pointer: 2-segment cursor silhouette
            pts = [QPointF(4, 3), QPointF(4, s - 5),
                   QPointF(s // 2 - 1, s // 2 + 1),
                   QPointF(s - 5, s - 5)]
            p.setBrush(QBrush(QColor(_StudioIcons._fg())))
            p.drawPolygon(QPolygonF(pts))
        return _StudioIcons.make(d)

    @staticmethod
    def text():
        def d(p, s):
            pen = _StudioIcons._pen(_StudioIcons._fg(), 2.2)
            p.setPen(pen)
            p.drawLine(3, 5, s - 3, 5)
            p.drawLine(s // 2, 5, s // 2, s - 4)
        return _StudioIcons.make(d)

    @staticmethod
    def censor():
        def d(p, s):
            r = QRectF(3, 6, s - 6, s - 12)
            p.setBrush(QBrush(QColor(_StudioIcons._fg())))
            p.drawRect(r)
        return _StudioIcons.make(d)

    @staticmethod
    def crop():
        def d(p, s):
            # Two L-brackets, offset
            p.drawLine(4, 1, 4, s - 4)
            p.drawLine(4, s - 4, s - 1, s - 4)
            p.drawLine(1, 4, s - 4, 4)
            p.drawLine(s - 4, 4, s - 4, s - 1)
        return _StudioIcons.make(d)

    @staticmethod
    def note():
        def d(p, s):
            # Pencil diagonal
            p.drawLine(4, s - 4, s - 4, 4)
            p.drawLine(s - 4, 4, s - 2, 6)
            p.drawLine(s - 2, 6, s - 6, 8)
            # Eraser end
            p.drawRect(QRectF(3, s - 5, 3, 3))
        return _StudioIcons.make(d)

    @staticmethod
    def watermark():
        def d(p, s):
            # Overlapping rect suggesting image/logo
            p.drawRect(QRectF(3, 3, s - 8, s - 8))
            p.drawRect(QRectF(6, 6, s - 8, s - 8))
        return _StudioIcons.make(d)

    @staticmethod
    def arrow():
        def d(p, s):
            p.drawLine(3, s - 3, s - 5, 5)
            # Arrowhead
            pts = [QPointF(s - 3, 3), QPointF(s - 3, 9),
                   QPointF(s - 9, 3)]
            p.setBrush(QBrush(QColor(_StudioIcons._fg())))
            p.drawPolygon(QPolygonF(pts))
        return _StudioIcons.make(d)

    @staticmethod
    def shape():
        def d(p, s):
            p.drawRect(QRectF(3, 4, s - 6, s - 8))
        return _StudioIcons.make(d)

    @staticmethod
    def eyedropper():
        def d(p, s):
            p.drawLine(3, s - 3, s - 6, 6)
            # Tip
            p.setBrush(QBrush(QColor(_StudioIcons._fg())))
            p.drawEllipse(QPointF(3.5, s - 3.5), 2.3, 2.3)
            # Top cap
            p.drawRect(QRectF(s - 7, 3, 5, 5))
        return _StudioIcons.make(d)

    @staticmethod
    def undo():
        def d(p, s):
            # Curved arrow left
            path = QPainterPath()
            path.moveTo(s - 3, s // 2)
            path.arcTo(QRectF(3, 3, s - 6, s - 6), 0, 210)
            p.drawPath(path)
            p.setBrush(QBrush(QColor(_StudioIcons._fg())))
            pts = [QPointF(6, s - 6), QPointF(2, s - 3),
                   QPointF(6, s)]
            p.drawPolygon(QPolygonF(pts))
        return _StudioIcons.make(d)

    @staticmethod
    def redo():
        def d(p, s):
            path = QPainterPath()
            path.moveTo(3, s // 2)
            path.arcTo(QRectF(3, 3, s - 6, s - 6), 180, 210)
            p.drawPath(path)
            p.setBrush(QBrush(QColor(_StudioIcons._fg())))
            pts = [QPointF(s - 6, s - 6), QPointF(s - 2, s - 3),
                   QPointF(s - 6, s)]
            p.drawPolygon(QPolygonF(pts))
        return _StudioIcons.make(d)

    @staticmethod
    def history():
        def d(p, s):
            # Clock-ish
            p.drawEllipse(QRectF(3, 3, s - 6, s - 6))
            p.drawLine(s // 2, s // 2, s // 2, 5)
            p.drawLine(s // 2, s // 2, s - 6, s // 2)
        return _StudioIcons.make(d)

    @staticmethod
    def grid():
        def d(p, s):
            for i in (s // 3, 2 * s // 3):
                p.drawLine(i, 3, i, s - 3)
                p.drawLine(3, i, s - 3, i)
        return _StudioIcons.make(d)

    @staticmethod
    def rulers():
        def d(p, s):
            p.drawLine(3, 3, 3, s - 3)
            p.drawLine(3, s - 3, s - 3, s - 3)
            for i in range(6, s - 3, 3):
                p.drawLine(3, i, 5, i)
                p.drawLine(i, s - 3, i, s - 5)
        return _StudioIcons.make(d)

    @staticmethod
    def thirds():
        def d(p, s):
            p.drawRect(QRectF(3, 3, s - 6, s - 6))
            t = s // 3
            p.drawLine(t + 1, 3, t + 1, s - 3)
            p.drawLine(2 * t, 3, 2 * t, s - 3)
            p.drawLine(3, t + 1, s - 3, t + 1)
            p.drawLine(3, 2 * t, s - 3, 2 * t)
        return _StudioIcons.make(d)

    @staticmethod
    def notes():
        def d(p, s):
            p.drawRect(QRectF(3, 3, s - 6, s - 6))
            p.drawLine(6, 7, s - 6, 7)
            p.drawLine(6, 11, s - 6, 11)
            p.drawLine(6, 15, s - 9, 15)
        return _StudioIcons.make(d)

    @staticmethod
    def base():
        def d(p, s):
            p.drawRect(QRectF(3, 3, s - 6, s - 6))
            p.drawLine(3, s - 6, s // 2 - 2, s // 2 + 1)
            p.drawLine(s // 2 - 2, s // 2 + 1, s // 2 + 3, s // 2 + 4)
            p.drawEllipse(QPointF(s - 7, 7), 1.5, 1.5)
        return _StudioIcons.make(d)

    @staticmethod
    def minimap():
        def d(p, s):
            p.drawRect(QRectF(3, 3, s - 6, s - 6))
            p.drawRect(QRectF(s // 2 - 1, s // 2 - 1, 5, 5))
        return _StudioIcons.make(d)

    @staticmethod
    def focus():
        def d(p, s):
            p.drawLine(3, 3, 7, 3); p.drawLine(3, 3, 3, 7)
            p.drawLine(s - 3, 3, s - 7, 3); p.drawLine(s - 3, 3, s - 3, 7)
            p.drawLine(3, s - 3, 7, s - 3); p.drawLine(3, s - 3, 3, s - 7)
            p.drawLine(s - 3, s - 3, s - 7, s - 3); p.drawLine(s - 3, s - 3, s - 3, s - 7)
        return _StudioIcons.make(d)

    @staticmethod
    def flip():
        def d(p, s):
            p.drawLine(s // 2, 3, s // 2, s - 3)
            p.setBrush(QBrush(QColor(_StudioIcons._fg())))
            p.drawPolygon(QPolygonF([
                QPointF(s // 2 - 2, 6), QPointF(4, s // 2),
                QPointF(s // 2 - 2, s - 6)]))
            p.drawPolygon(QPolygonF([
                QPointF(s // 2 + 2, 6), QPointF(s - 4, s // 2),
                QPointF(s // 2 + 2, s - 6)]))
        return _StudioIcons.make(d)

    @staticmethod
    def export():
        def d(p, s):
            p.drawLine(s // 2, 3, s // 2, s - 8)
            p.setBrush(QBrush(QColor(_StudioIcons._fg())))
            p.drawPolygon(QPolygonF([
                QPointF(s // 2 - 4, s - 12), QPointF(s // 2, s - 8),
                QPointF(s // 2 + 4, s - 12)]))
            p.drawLine(3, s - 3, s - 3, s - 3)
        return _StudioIcons.make(d)

    @staticmethod
    def settings():
        def d(p, s):
            cx, cy = s / 2, s / 2
            for i in range(6):
                ang = math.radians(i * 60)
                x1 = cx + math.cos(ang) * (s / 2 - 5)
                y1 = cy + math.sin(ang) * (s / 2 - 5)
                x2 = cx + math.cos(ang) * (s / 2 - 2)
                y2 = cy + math.sin(ang) * (s / 2 - 2)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            p.drawEllipse(QPointF(cx, cy), s / 4, s / 4)
        return _StudioIcons.make(d)

    @staticmethod
    def queue():
        def d(p, s):
            p.drawLine(3, 6, s - 3, 6)
            p.drawLine(3, s // 2, s - 3, s // 2)
            p.drawLine(3, s - 6, s - 3, s - 6)
            p.setBrush(QBrush(QColor(_StudioIcons._fg())))
            p.drawEllipse(QPointF(4, 6), 1.5, 1.5)
            p.drawEllipse(QPointF(4, s // 2), 1.5, 1.5)
            p.drawEllipse(QPointF(4, s - 6), 1.5, 1.5)
        return _StudioIcons.make(d)

    # ------------------------------------------------------------------
    # Text-style icons (Weight + Align rows in the Text Controls dialog).
    # These were rendered as raw glyphs ("B", "I", "U", "S", "≡", "≣")
    # relying on the system font — on themes with thin UI fonts and on
    # Windows installs that don't ship the unicode line-drawing glyphs
    # the buttons read as blank squares. Painted icons are theme-aware
    # and render identically everywhere.
    # ------------------------------------------------------------------

    @staticmethod
    def text_bold():
        def d(p, s):
            # Solid capital B using two stacked bumps for the right lobes.
            p.setBrush(QBrush(QColor(_StudioIcons._fg())))
            pen = QPen(QColor(_StudioIcons._fg()),
                       3.0 if _StudioIcons._theme_is_light(
                           THEMES.get(
                               QSettings("DoxyEdit", "DoxyEdit").value(
                                   "theme", DEFAULT_THEME),
                               THEMES[DEFAULT_THEME]))
                       else 2.6)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            p.setPen(pen)
            # Vertical stem
            p.drawLine(int(s * 0.3), int(s * 0.2),
                       int(s * 0.3), int(s * 0.82))
            # Upper bump
            rect_u = QRectF(s * 0.3, s * 0.2, s * 0.35, s * 0.32)
            p.drawArc(rect_u, 90 * 16, -180 * 16)
            # Lower bump
            rect_l = QRectF(s * 0.3, s * 0.5, s * 0.42, s * 0.32)
            p.drawArc(rect_l, 90 * 16, -180 * 16)
            # Top/bottom cross strokes so it reads as a B, not a D
            p.drawLine(int(s * 0.3), int(s * 0.2),
                       int(s * 0.6), int(s * 0.2))
            p.drawLine(int(s * 0.3), int(s * 0.5),
                       int(s * 0.65), int(s * 0.5))
            p.drawLine(int(s * 0.3), int(s * 0.82),
                       int(s * 0.68), int(s * 0.82))
        return _StudioIcons.make(d)

    @staticmethod
    def text_italic():
        def d(p, s):
            pen = _StudioIcons._pen(_StudioIcons._fg(), 2.4)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            # Slanted vertical stroke reading as an I
            p.drawLine(int(s * 0.5), int(s * 0.2),
                       int(s * 0.35), int(s * 0.82))
            # Short caps top + bottom to cement the I-in-italic read
            p.drawLine(int(s * 0.4), int(s * 0.2),
                       int(s * 0.65), int(s * 0.2))
            p.drawLine(int(s * 0.25), int(s * 0.82),
                       int(s * 0.5), int(s * 0.82))
        return _StudioIcons.make(d)

    @staticmethod
    def text_underline():
        def d(p, s):
            pen = _StudioIcons._pen(_StudioIcons._fg(), 2.4)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            # Capital U: two verticals + bottom arc
            p.drawLine(int(s * 0.28), int(s * 0.2),
                       int(s * 0.28), int(s * 0.6))
            p.drawLine(int(s * 0.72), int(s * 0.2),
                       int(s * 0.72), int(s * 0.6))
            rect = QRectF(s * 0.28, s * 0.4, s * 0.44, s * 0.4)
            p.drawArc(rect, 180 * 16, 180 * 16)
            # Underline bar below
            p.drawLine(int(s * 0.2), int(s * 0.88),
                       int(s * 0.8), int(s * 0.88))
        return _StudioIcons.make(d)

    @staticmethod
    def text_strike():
        def d(p, s):
            pen = _StudioIcons._pen(_StudioIcons._fg(), 2.4)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            # Capital S silhouette via two arcs
            rect_u = QRectF(s * 0.28, s * 0.18, s * 0.48, s * 0.36)
            p.drawArc(rect_u, 30 * 16, 270 * 16)
            rect_l = QRectF(s * 0.28, s * 0.46, s * 0.48, s * 0.36)
            p.drawArc(rect_l, 210 * 16, 270 * 16)
            # Horizontal strike line through the middle
            p.drawLine(int(s * 0.15), int(s * 0.5),
                       int(s * 0.85), int(s * 0.5))
        return _StudioIcons.make(d)

    @staticmethod
    def align_left():
        def d(p, s):
            pen = _StudioIcons._pen(_StudioIcons._fg(), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            # Four left-aligned bars of varying length
            x0 = int(s * 0.18)
            p.drawLine(x0, int(s * 0.25), int(s * 0.85), int(s * 0.25))
            p.drawLine(x0, int(s * 0.44), int(s * 0.68), int(s * 0.44))
            p.drawLine(x0, int(s * 0.63), int(s * 0.82), int(s * 0.63))
            p.drawLine(x0, int(s * 0.82), int(s * 0.58), int(s * 0.82))
        return _StudioIcons.make(d)

    @staticmethod
    def align_center():
        def d(p, s):
            pen = _StudioIcons._pen(_StudioIcons._fg(), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            cx = s * 0.5
            # Four centered bars of varying length
            for y, half in (
                (0.25, 0.35), (0.44, 0.25), (0.63, 0.32), (0.82, 0.2)):
                p.drawLine(int(cx - s * half), int(s * y),
                           int(cx + s * half), int(s * y))
        return _StudioIcons.make(d)

    @staticmethod
    def align_right():
        def d(p, s):
            pen = _StudioIcons._pen(_StudioIcons._fg(), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            x1 = int(s * 0.82)
            p.drawLine(int(s * 0.15), int(s * 0.25), x1, int(s * 0.25))
            p.drawLine(int(s * 0.32), int(s * 0.44), x1, int(s * 0.44))
            p.drawLine(int(s * 0.18), int(s * 0.63), x1, int(s * 0.63))
            p.drawLine(int(s * 0.42), int(s * 0.82), x1, int(s * 0.82))
        return _StudioIcons.make(d)


class _ImageEnhanceSignals(QObject):
    """Worker -> GUI-thread bridge for off-thread image enhancement.
    Carries item_id, a monotonic token, and the enhanced QImage."""
    done = Signal(int, int, QImage)


class _ImageEnhanceWorker(QRunnable):
    """QRunnable that runs PIL ImageEnhance (brightness/contrast/
    saturation) on a QImage snapshot off the GUI thread. Emits the
    enhanced QImage back via signal so the main thread can swap it
    in. The token lets the slot reject stale results when the user
    has already triggered a newer slider tick."""

    def __init__(self, item_id: int, token: int, qimg: QImage,
                 brightness: float, contrast: float, saturation: float,
                 signals: _ImageEnhanceSignals):
        super().__init__()
        self._item_id = item_id
        self._token = token
        self._qimg = qimg
        self._brightness = brightness
        self._contrast = contrast
        self._saturation = saturation
        self._signals = signals
        self.setAutoDelete(True)

    def run(self):
        try:
            from PIL import ImageEnhance
            from doxyedit.imaging import qimage_to_pil, pil_to_qimage
            pil_img = qimage_to_pil(self._qimg)
            if self._brightness:
                pil_img = ImageEnhance.Brightness(pil_img).enhance(
                    1.0 + self._brightness)
            if self._contrast:
                pil_img = ImageEnhance.Contrast(pil_img).enhance(
                    1.0 + self._contrast)
            if self._saturation:
                pil_img = ImageEnhance.Color(pil_img).enhance(
                    1.0 + self._saturation)
            out = pil_to_qimage(pil_img)
            self._signals.done.emit(self._item_id, self._token, out)
        except Exception:
            # Emit a null QImage so the GUI can notice and ignore.
            self._signals.done.emit(self._item_id, self._token, QImage())


class _ColorSwatchButton(QPushButton):
    """QPushButton that paints a filled square showing the current color
    and an outline ring. Used for the fill / outline color pickers in
    the Text Controls dialog so a theme QSS can never make the swatch
    invisible (the glyph fallback went white-on-white in some themes).
    Right-click opens a recent-color popup so users can reapply a
    recently-chosen color without reopening QColorDialog."""

    def __init__(self, is_outline: bool = False, parent=None):
        super().__init__("", parent)
        self._is_outline = is_outline
        _t = THEMES[DEFAULT_THEME]
        self._color = QColor(_t.studio_overlay_handle_border)
        self.setMinimumSize(32, 26)
        # on_color_picked: (hex) -> None, called when user picks a
        # recent color from the right-click popup. Owner sets this.
        self.on_color_picked = None
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_recent_popup)

    def setSwatchColor(self, color):
        self._color = QColor(color) if not isinstance(color, QColor) else color
        self.update()

    def _show_recent_popup(self, pos):
        """Popup a small palette grid of recent colors; clicking one
        triggers on_color_picked so the overlay / default updates."""
        # Walk up to find the editor with _get_recent_colors
        editor = self.window()
        if not (editor and hasattr(editor, "_get_recent_colors")):
            # Window() might be the app wrapper; scan for a Studio
            # ancestor by attribute duck-typing.
            p = self.parent()
            while p is not None and not hasattr(p, "_get_recent_colors"):
                p = p.parent()
            editor = p
        if editor is None or not hasattr(editor, "_get_recent_colors"):
            return
        colors = editor._get_recent_colors()
        if not colors:
            return
        menu = QMenu(self)
        menu.setStyleSheet(self.window().styleSheet() if self.window() else "")
        grid_widget = QWidget(menu)
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(3)
        for i, hex_c in enumerate(colors):
            btn = QPushButton(grid_widget)
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(
                f"background: {hex_c}; border: 1px solid #333;")
            btn.setToolTip(hex_c)
            def _pick(_c=hex_c):
                if callable(self.on_color_picked):
                    self.on_color_picked(_c)
                self.setSwatchColor(_c)
                menu.close()
            btn.clicked.connect(_pick)
            grid.addWidget(btn, i // 4, i % 4)
        act = QWidgetAction(menu)
        act.setDefaultWidget(grid_widget)
        menu.addAction(act)
        menu.addSeparator()
        copy_hex_act = menu.addAction(
            f"Copy current swatch ({self._color.name()}) to clipboard")
        def _copy_hex():
            QApplication.clipboard().setText(self._color.name())
            if hasattr(editor, "info_label"):
                editor.info_label.setText(
                    f"Copied {self._color.name()} to clipboard")
        copy_hex_act.triggered.connect(_copy_hex)
        # Paste from clipboard if the clipboard holds a valid hex.
        # Accepts #rgb, #rrggbb, #rrggbbaa with or without leading #.
        clip_txt = (QApplication.clipboard().text() or "").strip()
        clip_hex_candidate = clip_txt.lstrip("#")
        _is_valid_hex = (
            len(clip_hex_candidate) in (3, 6, 8)
            and all(c in "0123456789abcdefABCDEF" for c in clip_hex_candidate)
        )
        paste_hex_act = None
        if _is_valid_hex:
            paste_hex_act = menu.addAction(
                f"Paste hex from clipboard ({clip_txt})")
            def _paste_hex(_c="#" + clip_hex_candidate):
                if callable(self.on_color_picked):
                    self.on_color_picked(_c)
                self.setSwatchColor(_c)
            paste_hex_act.triggered.connect(_paste_hex)
        clear_act = menu.addAction("Clear recent colors")
        def _clear_recent():
            QSettings("DoxyEdit", "DoxyEdit").setValue("studio_recent_colors", "")
            if hasattr(editor, "_refresh_recent_swatches"):
                editor._refresh_recent_swatches()
        clear_act.triggered.connect(_clear_recent)
        menu.exec(self.mapToGlobal(pos))

    def paintEvent(self, ev):
        # Let the theme draw the button frame, then paint the swatch on top.
        super().paintEvent(ev)
        _t = THEMES[DEFAULT_THEME]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(6, 5, -6, -5)
        if self._is_outline:
            # Hollow ring: outlined rect on neutral bg so transparency is
            # self-explanatory.
            p.setBrush(QBrush(QColor(_t.studio_icon_fg)))
            p.setPen(QPen(self._color, _t.studio_swatch_ring_pen_width))
            p.drawRect(r)
        else:
            p.setBrush(QBrush(self._color))
            p.setPen(QPen(QColor(_t.studio_icon_border),
                          _t.studio_swatch_border_pen_width))
            p.drawRect(r)
        p.end()


class _FlowLayout(QtWidgets.QLayout):
    """Wrapping horizontal layout — like QHBoxLayout but children fold onto
    the next row when they don't fit the available width. Adapted from the
    Qt 'Flow Layout Example' and tuned for Studio's toolbar density."""

    def __init__(self, parent=None, margin: int = 0, hSpacing: int = 4, vSpacing: int = 4):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self._hspace = hSpacing
        self._vspace = vSpacing
        self._items: list = []

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self):
        return self._hspace

    def verticalSpacing(self):
        return self._vspace

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QtCore.QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QtCore.QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            wid = item.widget()
            hspace = self._hspace
            vspace = self._vspace
            next_x = x + item.sizeHint().width() + hspace
            if next_x - hspace > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + vspace
                next_x = x + item.sizeHint().width() + hspace
                line_height = 0
            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y() + m.bottom()


class _StudioMinimap(QWidget):
    """Small navigator showing the full image + the current viewport rect.
    Clicking inside the minimap re-centers the view there."""

    MINI_SIZE = 140

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self._view = view
        self._theme = THEMES[DEFAULT_THEME]
        self.setObjectName("studio_minimap")
        self.setFixedSize(self.MINI_SIZE, self.MINI_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._dragging = False
        # Downsampled-thumbnail cache for the minimap paint. Pre-init so
        # paintEvent's per-paint comparison can read the attribute
        # directly instead of via getattr-with-default.
        self._scaled_pm = None
        self._scaled_key = None
        self.setMouseTracking(True)
        # Refresh on any scroll/zoom
        view.horizontalScrollBar().valueChanged.connect(self.update)
        view.verticalScrollBar().valueChanged.connect(self.update)

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def _pixmap(self):
        editor = getattr(self._view, "_studio_editor", None)
        if editor and editor._pixmap_item:
            return editor._pixmap_item.pixmap()
        return None

    def _scale(self):
        pm = self._pixmap()
        if pm is None or pm.isNull():
            return 1.0
        return min(self.width() / pm.width(), self.height() / pm.height())

    def _image_rect_in_minimap(self):
        pm = self._pixmap()
        if pm is None:
            return QRectF()
        s = self._scale()
        iw, ih = pm.width() * s, pm.height() * s
        ox = (self.width() - iw) / 2
        oy = (self.height() - ih) / 2
        return QRectF(ox, oy, iw, ih)

    def paintEvent(self, _event):
        _t = self._theme
        p = QPainter(self)
        bg = QColor(_t.studio_minimap_bg)
        bg.setAlpha(_t.studio_minimap_bg_alpha)
        p.fillRect(self.rect(), bg)
        pm = self._pixmap()
        if pm is None or pm.isNull():
            p.setPen(QColor(_t.studio_minimap_text))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No image")
            return
        ir = self._image_rect_in_minimap()
        # Cache the downsampled thumbnail. Scaling a 2000x3000 pixmap to
        # ~140px via SmoothTransformation is ~20-30ms, and this paints
        # on every scroll/zoom — was a per-frame perf killer. Cache key
        # includes the pixmap cacheKey + target size so invalidation
        # happens when either changes.
        key = (pm.cacheKey(), int(ir.width()), int(ir.height()))
        if self._scaled_key != key:
            self._scaled_pm = pm.scaled(
                int(ir.width()), int(ir.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self._scaled_key = key
        p.drawPixmap(int(ir.x()), int(ir.y()), self._scaled_pm)
        # Draw viewport rect in image coordinates, projected to minimap
        vp = self._view.viewport().rect()
        tl = self._view.mapToScene(vp.topLeft())
        br = self._view.mapToScene(vp.bottomRight())
        s = self._scale()
        rx = ir.x() + tl.x() * s
        ry = ir.y() + tl.y() * s
        rw = (br.x() - tl.x()) * s
        rh = (br.y() - tl.y()) * s
        view_pen_c = QColor(_t.studio_minimap_view_border)
        view_pen_c.setAlpha(_t.studio_minimap_view_pen_alpha)
        view_fill_c = QColor(_t.studio_minimap_view_border)
        view_fill_c.setAlpha(_t.studio_minimap_view_fill_alpha)
        p.setPen(QPen(view_pen_c, _t.studio_minimap_pen_width))
        p.setBrush(view_fill_c)
        p.drawRect(QRectF(rx, ry, rw, rh))
        # Border
        p.setPen(QPen(QColor(_t.studio_minimap_border_dim),
                      _t.studio_minimap_pen_width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def _center_view_on(self, widget_pt):
        pm = self._pixmap()
        if pm is None:
            return
        ir = self._image_rect_in_minimap()
        s = self._scale()
        if s == 0:
            return
        scene_x = (widget_pt.x() - ir.x()) / s
        scene_y = (widget_pt.y() - ir.y()) / s
        self._view.centerOn(scene_x, scene_y)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._center_view_on(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._center_view_on(event.position())

    def mouseReleaseEvent(self, event):
        self._dragging = False


class _StudioCanvas(QWidget):
    """Wraps a StudioView with rulers along the top and left edges."""

    RULER_SIZE = 18

    def __init__(self, view, theme, parent=None):
        super().__init__(parent)
        self._view = view
        self._theme = theme
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        self._corner = QLabel("⌖")  # crosshair glyph — click for Fit
        self._corner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._corner.setFixedSize(self.RULER_SIZE, self.RULER_SIZE)
        self._corner.setToolTip("Click to fit view to canvas")
        self._corner.setCursor(Qt.CursorShape.PointingHandCursor)
        self._corner.setAutoFillBackground(True)
        _pal = self._corner.palette()
        _pal.setColor(self._corner.backgroundRole(), QColor(theme.bg_deep))
        _pal.setColor(self._corner.foregroundRole(), QColor(theme.text_muted))
        self._corner.setPalette(_pal)
        self._corner.mousePressEvent = self._on_corner_click
        self._h_ruler = _StudioRuler(view, 'h', theme)
        self._h_ruler.setFixedHeight(self.RULER_SIZE)
        self._v_ruler = _StudioRuler(view, 'v', theme)
        self._v_ruler.setFixedWidth(self.RULER_SIZE)
        grid.addWidget(self._corner, 0, 0)
        grid.addWidget(self._h_ruler, 0, 1)
        grid.addWidget(self._v_ruler, 1, 0)
        grid.addWidget(view, 1, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(1, 1)
        # Minimap — floating overlay in the bottom-right of the view
        self._minimap = _StudioMinimap(view, parent=view)
        self._minimap.move(12, 12)
        self._minimap.setVisible(False)
        # Reposition minimap whenever the view resizes
        view.resizeEvent = self._wrap_view_resize(view.resizeEvent)
        # Repaint rulers whenever the view scrolls or zooms
        view.horizontalScrollBar().valueChanged.connect(self._h_ruler.update)
        view.horizontalScrollBar().valueChanged.connect(self._v_ruler.update)
        view.verticalScrollBar().valueChanged.connect(self._h_ruler.update)
        view.verticalScrollBar().valueChanged.connect(self._v_ruler.update)

    def set_theme(self, theme):
        self._theme = theme
        _pal = self._corner.palette()
        _pal.setColor(self._corner.backgroundRole(), QColor(theme.bg_deep))
        _pal.setColor(self._corner.foregroundRole(), QColor(theme.text_muted))
        self._corner.setPalette(_pal)
        self._h_ruler.set_theme(theme)
        self._v_ruler.set_theme(theme)
        # _minimap is always created in __init__; direct access is safe.
        self._minimap.set_theme(theme)

    def update_cursor(self, scene_pos: QPointF):
        self._h_ruler.set_cursor_scene(scene_pos.x())
        self._v_ruler.set_cursor_scene(scene_pos.y())

    def refresh(self):
        self._h_ruler.update()
        self._v_ruler.update()
        self._minimap.update()

    def _wrap_view_resize(self, orig):
        def _resize(event):
            orig(event)
            v = self._view
            self._minimap.move(
                v.width() - self._minimap.width() - 12,
                v.height() - self._minimap.height() - 12)
        return _resize

    def set_minimap_visible(self, on: bool):
        self._minimap.setVisible(on)

    def _on_corner_click(self, event):
        """Click the ruler corner → fit view to canvas (same as Ctrl+0)."""
        editor = getattr(self._view, "_studio_editor", None)
        if editor is None:
            return
        scene = self._view.scene()
        if scene and scene.sceneRect():
            self._view.fitInView(scene.sceneRect(),
                                  Qt.AspectRatioMode.KeepAspectRatio)
            if hasattr(editor, "_zoom_label"):
                editor._zoom_label.setText("Fit")
            self.refresh()


_GL_PROBE_RESULT: bool | None = None
_GL_PROBE_ERROR: str = ""


def _probe_gl_viewport() -> bool:
    """Return True if a QOpenGLWidget can be created and bound on the
    current platform. Result is memoized — the probe creates real GL
    resources which isn't free, and the answer won't change within a
    session.

    Checks:
    - QtOpenGLWidgets module imports
    - QSurfaceFormat + QOpenGLWidget instantiable
    - QOpenGLContext can be created with the widget's format

    Used at StudioView construction to decide whether to honor
    studio_use_gl_viewport=True, and to log which backend is actually
    active to the perf log.
    """
    global _GL_PROBE_RESULT, _GL_PROBE_ERROR
    if _GL_PROBE_RESULT is not None:
        return _GL_PROBE_RESULT
    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget
        from PySide6.QtGui import QSurfaceFormat, QOpenGLContext
        w = QOpenGLWidget()
        fmt = QSurfaceFormat()
        fmt.setSwapInterval(1)
        fmt.setSamples(0)
        w.setFormat(fmt)
        # Actually create a GL context to prove we have working drivers.
        # Without this, QOpenGLWidget construction succeeds even when
        # OpenGL is missing (e.g. running under WSLg with no GL).
        ctx = QOpenGLContext()
        ctx.setFormat(fmt)
        if not ctx.create():
            _GL_PROBE_ERROR = "QOpenGLContext.create() failed"
            _GL_PROBE_RESULT = False
            return False
        # Clean up probe widget/context so we don't leak GL state.
        w.deleteLater()
        _GL_PROBE_RESULT = True
        return True
    except Exception as e:
        _GL_PROBE_ERROR = str(e)
        _GL_PROBE_RESULT = False
        return False


def gl_probe_result() -> tuple[bool, str]:
    """Inspect the GL probe without re-running it. Returns (ok, error)."""
    return (bool(_GL_PROBE_RESULT), _GL_PROBE_ERROR)


def gl_probe_attempted() -> bool:
    """True iff _probe_gl_viewport() has been called this session.
    Used by the perf-log header to distinguish "GL probe failed" from
    "GL was never requested, so the probe never ran."""
    return _GL_PROBE_RESULT is not None


class StudioView(QGraphicsView):
    """Zoomable (wheel) + pannable (middle-drag) view."""

    def __init__(self, scene: StudioScene, parent=None):
        super().__init__(scene, parent)
        self.setObjectName("studio_view")
        self._studio_editor = None  # set by StudioEditor after creation
        # Apply rendering prefs from Studio Settings so the user's
        # 'antialias off / nearest upscale / text aa off' choices
        # actually take effect at app start, not just after they
        # re-open the settings dialog.
        _qs = QSettings("DoxyEdit", "DoxyEdit")
        _aa = _qs.value("studio_render_aa", True, type=bool)
        _text_aa = _qs.value("studio_render_text_aa", True, type=bool)
        _hq = _qs.value("studio_render_hq", True, type=bool)
        _upscale = _qs.value("studio_upscale_mode", "smooth", type=str)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, _aa)
        self.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            _hq and _upscale != "nearest")
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, _text_aa)
        self.setRenderHint(
            QPainter.RenderHint.LosslessImageRendering, _hq)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # Perf log data showed that SmartViewportUpdate was consistently
        # choosing full-viewport repaints (1628x1005 dirty rect on every
        # drag frame) because it picks full mode when the union of many
        # small dirty rects exceeds ~50% of the viewport. Switch to
        # MinimalViewportUpdate which always calculates the actual
        # minimal region — the union of old + new sceneBoundingRect for
        # the moving item, which for most bubble drags is just a few
        # hundred pixels square.
        # GPU viewport — opt-in via studio_use_gl_viewport (default OFF).
        # Perf-log data (post-GL-enable) showed GL's required
        # FullViewportUpdate path measured ~20ms/frame because it
        # repaints the whole 1628x1005 viewport every drag frame, while
        # the raster path below with MinimalViewportUpdate repaints only
        # the moving item's swept region (~200x200 = ~40k pixels vs
        # ~1.6M). The net win is on the raster side until we migrate to
        # a proper texture-resident pipeline (see docs/canvas-
        # architecture-deep-dive.md Option D — Skia backend).
        # GL is still available as an opt-in for users on very high-end
        # GPUs or for stress-testing large scenes.
        _use_gl = _qs.value("studio_use_gl_viewport", False, type=bool)
        gl_ok = False
        if _use_gl:
            # Startup probe — check the platform actually supports GL
            # before swapping the viewport. Probes catch missing drivers
            # (Intel HD without OpenGL), WSL environments, and remote-
            # desktop sessions where GL fails silently.
            if not _probe_gl_viewport():
                gl_ok = False
            else:
                try:
                    from PySide6.QtOpenGLWidgets import QOpenGLWidget
                    from PySide6.QtGui import QSurfaceFormat
                    gl = QOpenGLWidget()
                    fmt = QSurfaceFormat()
                    fmt.setSwapInterval(1)  # vsync
                    fmt.setSamples(0)        # no MSAA - cheap
                    gl.setFormat(fmt)
                    self.setViewport(gl)
                    gl_ok = True
                except Exception:
                    gl_ok = False
        if gl_ok:
            # GL viewport requires FullViewportUpdate - partial rects
            # don't work; the framebuffer swaps whole anyway.
            self.setViewportUpdateMode(
                QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        else:
            # Raster fallback: perf log showed SmartViewportUpdate was
            # picking full-viewport anyway; MinimalViewportUpdate always
            # calculates the actual minimal rect from the union of moving
            # item's old+new sceneBoundingRect.
            self.setViewportUpdateMode(
                QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
            # Cache the scene background pixmap only on the raster path —
            # GL has its own texture cache and this fights it.
            self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)
        self._gl_viewport_active = gl_ok
        # Opt out of software-composed backing store; direct OpenGL-ish
        # path on Windows is a lot faster for the per-frame blit.
        self.setOptimizationFlag(
            QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        self.setOptimizationFlag(
            QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, True)
        self.setAcceptDrops(True)
        # Track cursor when no button is pressed so the status bar X,Y label
        # updates live as the user hovers.
        self.setMouseTracking(True)
        self._panning = False
        self._pan_start = QPointF()
        self.on_file_dropped = None  # callback(path, scene_pos)
        # FPS HUD — toggle with Shift+F or via Studio Settings. Tracks
        # the last 60 paint timestamps and shows current + rolling FPS
        # plus average paint duration in the top-left corner.
        import time as _t
        self._fps_enabled = QSettings("DoxyEdit", "DoxyEdit").value(
            "studio_show_fps", False, type=bool)
        self._fps_times: list[float] = []
        self._fps_last_paint_start = 0.0
        self._fps_last_paint_ms = 0.0
        self._fps_rolling_ms = 0.0
        self._fps_time = _t
        # Any paint at or above this threshold gets logged unconditionally
        # as a "slow_paint" event (separately from the 1-in-N sampled
        # paint stream). 33ms = the budget for a 30fps frame; crossing
        # that is a user-visible stutter worth investigating.
        self._SLOW_PAINT_MS = 33.0
        # A gap between consecutive paints longer than this means the
        # event loop was blocked on something other than paint itself
        # (autosave / network / JSON read / etc). Log these with
        # "frame_gap" so the stalls the user *feels* as stutter show
        # up distinctly from cheap-but-slow paints.
        self._FRAME_GAP_MS = 100.0
        self._fps_prev_paint_t = 0.0
        # Perf log — when FPS HUD is on, append paint/interaction events
        # as JSONL so the dev can correlate user actions with perf.
        # Path is predictable + readable by Claude Code for diagnosis.
        import os as _os, tempfile as _tf, json as _json
        self._perf_log_path = _os.path.join(
            _tf.gettempdir(), "doxyedit_studio_perf.jsonl")
        self._perf_log_file = None
        self._perf_json = _json
        self._perf_paint_sample_every = 10   # log 1 in N paint events
        self._perf_paint_counter = 0
        self._perf_last_event = 0.0
        self._perf_drag_last_log = 0.0
        # Always open the perf log so slow_paint / frame_gap events
        # (threshold-gated, zero cost on fast frames) are captured
        # without the user having to toggle the FPS HUD. Gives every
        # session diagnostic data to reason about stutter.
        self._perf_open_log()

    def _perf_open_log(self):
        # Idempotent so the HUD toggle can re-call without truncating
        # the session's already-captured events.
        if self._perf_log_file is not None:
            return
        try:
            import os as _os, time as _t
            self._perf_log_file = open(self._perf_log_path, "w",
                                        encoding="utf-8")
            ev = {
                "type": "session_start",
                "path": self._perf_log_path,
                "pid": _os.getpid(),
                "gl_active": self._gl_viewport_active,
            }
            # Only include probe fields when a probe was actually
            # attempted. Otherwise the default (False, "") readings
            # look like "GL probe failed" when the truth is "GL was
            # never requested" — and the empty gl_probe_err was
            # wasting diagnostic attention on a non-issue.
            if gl_probe_attempted():
                gl_ok, gl_err = gl_probe_result()
                ev["gl_probe_ok"] = gl_ok
                ev["gl_probe_err"] = gl_err
            else:
                ev["gl_probe_attempted"] = False
            self._perf_log_event(ev)
        except Exception:
            self._perf_log_file = None

    def _perf_close_log(self):
        if self._perf_log_file is not None:
            try:
                self._perf_log_event({"type": "session_end"})
                self._perf_log_file.close()
            except Exception:
                pass
            self._perf_log_file = None

    def _perf_log_event(self, ev: dict):
        """Append one JSON event to the perf log. Adds t, items, zoom."""
        if self._perf_log_file is None:
            return
        try:
            now = self._fps_time.perf_counter()
            ev.setdefault("t", round(now, 4))
            if "items" not in ev:
                sc = self.scene()
                ev["items"] = len(sc.items()) if sc else 0
            if "zoom" not in ev:
                ev["zoom"] = round(self.transform().m11(), 3)
            self._perf_log_file.write(self._perf_json.dumps(ev) + "\n")
            self._perf_log_file.flush()
        except Exception:
            pass

    def _describe_item(self, it) -> str:
        if it is None:
            return "none"
        return type(it).__name__

    def paintEvent(self, event):
        t0 = self._fps_time.perf_counter()
        super().paintEvent(event)
        # Always measure paint_ms + run the threshold-gated slow-path
        # detectors. Threshold events (slow_paint, frame_gap) fire only
        # when something is actually wrong, so overhead on fast frames
        # is two perf_counter reads + two compares. The HUD, rolling
        # average, and 1-in-N sampled paint events stay gated on
        # _fps_enabled so the live overlay doesn't cost anything when
        # the HUD is off.
        t1 = self._fps_time.perf_counter()
        paint_ms = (t1 - t0) * 1000.0
        self._fps_last_paint_ms = paint_ms
        # Frame-gap detector: event-loop blocked between paints. Paint_ms
        # only measures the cost of THIS frame; a 500ms autosave between
        # two fast paints shows up only here. First paint has no prior.
        if self._fps_prev_paint_t:
            gap_ms = (t1 - self._fps_prev_paint_t) * 1000.0
            if gap_ms >= self._FRAME_GAP_MS:
                self._perf_log_event({
                    "type": "frame_gap",
                    "gap_ms": round(gap_ms, 2),
                    "paint_ms": round(paint_ms, 2),
                })
        self._fps_prev_paint_t = t1
        # Slow-paint: this single frame crossed the 33ms budget. Payload
        # carries scene_items + zoom + dirty-rect so a future iteration
        # can correlate stutter with specific zoom levels or overlay
        # counts, and distinguish full-viewport invalidations from
        # big-moving-item paints.
        if paint_ms >= self._SLOW_PAINT_MS:
            try:
                scene = self.scene()
                scene_items = len(scene.items()) if scene else 0
                zoom_scale = self.transform().m11()
            except Exception:
                scene_items = 0
                zoom_scale = 1.0
            self._perf_log_event({
                "type": "slow_paint",
                "paint_ms": round(paint_ms, 2),
                "dirty_w": event.rect().width(),
                "dirty_h": event.rect().height(),
                "scene_items": scene_items,
                "zoom": round(zoom_scale, 3),
                "gl": self._gl_viewport_active,
            })
        if self._fps_enabled:
            # HUD-only path: rolling average, live fps, sampled paint
            # stream, viewport overlay. All skipped when HUD is off.
            self._fps_rolling_ms = (0.9 * self._fps_rolling_ms
                                     + 0.1 * paint_ms)
            self._fps_times.append(t1)
            cutoff = t1 - 2.0
            while self._fps_times and self._fps_times[0] < cutoff:
                self._fps_times.pop(0)
            fps_cutoff = t1 - 1.0
            fps = len(self._fps_times) - bisect.bisect_left(
                self._fps_times, fps_cutoff)
            self._perf_paint_counter += 1
            if self._perf_paint_counter % self._perf_paint_sample_every == 0:
                self._perf_log_event({
                    "type": "paint",
                    "fps": fps,
                    "paint_ms": round(paint_ms, 2),
                    "avg_ms": round(self._fps_rolling_ms, 2),
                    "dirty_w": event.rect().width(),
                    "dirty_h": event.rect().height(),
                    "gl": self._gl_viewport_active,
                })
            # Paint HUD on viewport
            vp = self.viewport()
            p = QPainter(vp)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            text_lines = [
                f"FPS: {fps}",
                f"Paint: {self._fps_last_paint_ms:.1f}ms",
                f"Avg: {self._fps_rolling_ms:.1f}ms",
                f"Items: {len(self.scene().items()) if self.scene() else 0}",
            ]
            f = QFont("Consolas", 10, QFont.Weight.Bold)
            p.setFont(f)
            fm = p.fontMetrics()
            line_h = fm.height() + 2
            w = max(fm.horizontalAdvance(t) for t in text_lines) + 16
            h = line_h * len(text_lines) + 10
            p.setBrush(QColor(0, 0, 0, 180))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(8, 8, w, h, 4, 4)
            # Color FPS number green/yellow/red
            if fps >= 45:
                color = QColor(120, 230, 140)
            elif fps >= 25:
                color = QColor(240, 210, 100)
            else:
                color = QColor(240, 120, 120)
            y = 8 + fm.ascent() + 5
            p.setPen(color)
            p.drawText(16, y, text_lines[0])
            y += line_h
            p.setPen(QColor(220, 220, 220))
            for line in text_lines[1:]:
                p.drawText(16, y, line)
                y += line_h
            p.end()

    def toggle_fps_hud(self):
        self._fps_enabled = not self._fps_enabled
        QSettings("DoxyEdit", "DoxyEdit").setValue(
            "studio_show_fps", self._fps_enabled)
        self._fps_times.clear()
        if self._fps_enabled:
            self._perf_open_log()
        else:
            self._perf_close_log()
        self.viewport().update()

    def wheelEvent(self, event: QWheelEvent):
        # Alt+Shift+wheel adjusts opacity of selected overlays by 5%
        # per tick. Useful for dialing in watermark visibility without
        # reaching for the opacity slider.
        editor = self._studio_editor
        if (event.modifiers() & Qt.KeyboardModifier.AltModifier
                and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                and editor is not None):
            sel = editor._scene.selectedItems()
            if sel:
                step = 0.05 if event.angleDelta().y() > 0 else -0.05
                touched = False
                for it in sel:
                    ov = getattr(it, "overlay", None)
                    if ov is None:
                        continue
                    new_op = max(0.0, min(1.0, ov.opacity + step))
                    ov.opacity = new_op
                    if hasattr(it, "setOpacity"):
                        it.setOpacity(new_op)
                    else:
                        it.update()
                    touched = True
                if touched:
                    editor._sync_overlays_to_asset()
                    editor.info_label.setText(
                        f"Opacity: {int(sel[0].overlay.opacity * 100)}%")
                return
        # Shift+wheel pans horizontally instead of zooming. Common
        # accessibility affordance for trackpads / vertical-only mice.
        if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                and not event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            sb = self.horizontalScrollBar()
            step = sb.singleStep() * 5 if sb.singleStep() else 40
            if event.angleDelta().y() > 0 or event.angleDelta().x() > 0:
                sb.setValue(sb.value() - step)
            else:
                sb.setValue(sb.value() + step)
            return
        # Alt+wheel rotates the currently-selected overlays by 5° steps
        # (Photoshop uses Alt for precise controls; this repurposes it).
        editor = self._studio_editor
        if editor is not None and (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            sel = editor._scene.selectedItems()
            if sel:
                step = 5 if event.angleDelta().y() > 0 else -5
                editor._rotate_selected(step)
                # Sync the rotation spinbox + slider if showing
                for it in sel:
                    if hasattr(it, "overlay"):
                        _rv = int(it.overlay.rotation)
                        for _w_name in ("spin_rotation_layer",
                                         "slider_rotation_layer"):
                            _w = getattr(editor, _w_name, None)
                            if _w is not None:
                                _w.blockSignals(True)
                                _w.setValue(_rv)
                                _w.blockSignals(False)
                        break
                return
        # Wheel scheme (user setting): "zoom" keeps the classic
        # plain-wheel-zooms behavior; "pan" flips it so plain wheel
        # scrolls vertically (common for long comic pages) and Ctrl+
        # wheel zooms. Either way, Ctrl+wheel is always a zoom path.
        # Cached to avoid QSettings-read per wheel tick (60+ Hz on
        # precision trackpads). Reload via reload_wheel_scheme() from
        # the settings dialog.
        _ws = getattr(self, "_wheel_scheme_cached", None)
        if _ws is None:
            _ws = QSettings("DoxyEdit", "DoxyEdit").value(
                "studio_wheel_scheme", "zoom", type=str)
            self._wheel_scheme_cached = _ws
        _is_ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if _ws == "pan" and not _is_ctrl:
            # Plain wheel = vertical pan
            sb = self.verticalScrollBar()
            step = sb.singleStep() * 5 if sb.singleStep() else 40
            dy = event.angleDelta().y()
            sb.setValue(sb.value() - (step if dy > 0 else -step))
            return
        # Otherwise: zoom (Ctrl is faster)
        _zoom = 1.5 if _is_ctrl else 1.15
        factor = _zoom if event.angleDelta().y() > 0 else 1 / _zoom
        self.setTransform(self.transform().scale(factor, factor))
        if self._fps_enabled:
            self._perf_log_event({
                "type": "zoom",
                "factor": round(factor, 3),
            })
        if self._studio_editor is not None:
            if hasattr(self._studio_editor, "_canvas_wrap"):
                self._studio_editor._canvas_wrap.refresh()
            if hasattr(self._studio_editor, "_zoom_label"):
                pct = int(self.transform().m11() * 100)
                self._studio_editor._zoom_label.setText(f"{pct}%")

    def mousePressEvent(self, event):
        if self._fps_enabled:
            btn_map = {
                Qt.MouseButton.LeftButton: "left",
                Qt.MouseButton.MiddleButton: "middle",
                Qt.MouseButton.RightButton: "right",
            }
            sp = self.mapToScene(event.position().toPoint())
            hit = None
            if self.scene() is not None:
                for it in self.scene().items(sp):
                    if not it.isVisible():
                        continue
                    hit = self._describe_item(it)
                    break
            self._perf_log_event({
                "type": "mouse_press",
                "button": btn_map.get(event.button(), "other"),
                "scene_x": round(sp.x(), 1),
                "scene_y": round(sp.y(), 1),
                "hit": hit,
            })
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
        # Update the Studio status bar cursor-position label in scene coords
        if self._studio_editor is not None:
            sp = self.mapToScene(event.position().toPoint())
            self._studio_editor._last_cursor_scene_pos = sp
            if hasattr(self._studio_editor, "_cursor_label"):
                editor = self._studio_editor
                x_i, y_i = int(sp.x()), int(sp.y())
                # Pixel-color lookup: the prior implementation called
                # pm.toImage() on EVERY mousemove, which converts the
                # full base pixmap (~25MB for a 2000x3000 image) to a
                # QImage — the single biggest source of Studio drag lag.
                # Now the QImage is cached on the editor and only re-
                # fetched when the base pixmap changes (tracked via
                # cacheKey()). Also skipped entirely during a mouse drag
                # (left/middle button down) so we don't even do the
                # cache lookup during the hot path.
                color_txt = ""
                btns = event.buttons()
                is_dragging = bool(
                    btns & (Qt.MouseButton.LeftButton
                             | Qt.MouseButton.MiddleButton
                             | Qt.MouseButton.RightButton))
                if (editor._pixmap_item is not None and not is_dragging):
                    pm = editor._pixmap_item.pixmap()
                    if 0 <= x_i < pm.width() and 0 <= y_i < pm.height():
                        ck = pm.cacheKey()
                        cached_key = getattr(
                            editor, "_base_image_cache_key", None)
                        if cached_key != ck:
                            editor._base_image_cache = pm.toImage()
                            editor._base_image_cache_key = ck
                        img = editor._base_image_cache
                        c = img.pixelColor(x_i, y_i)
                        color_txt = f"  {c.name()}"
                editor._cursor_label.setText(f"{x_i}, {y_i}{color_txt}")
            # Skip ruler cursor line update during drag — rulers repaint on
            # every update_cursor call (tick math + text drawing per frame)
            # and the cursor line is noise while the user is hauling an
            # overlay around. Cheap and invisible during drag.
            if hasattr(self._studio_editor, "_canvas_wrap"):
                if not is_dragging:
                    self._studio_editor._canvas_wrap.update_cursor(sp)
        if self._fps_enabled:
            now = self._fps_time.perf_counter()
            # Rate-limit drag logs to ~20Hz so we don't flood the file
            if now - self._perf_drag_last_log > 0.05:
                self._perf_drag_last_log = now
                btns = event.buttons()
                is_dragging = bool(
                    btns & (Qt.MouseButton.LeftButton
                             | Qt.MouseButton.MiddleButton))
                if is_dragging:
                    _drag_cutoff = now - 1.0
                    _fps = len(self._fps_times) - bisect.bisect_left(
                        self._fps_times, _drag_cutoff)
                    self._perf_log_event({
                        "type": "drag_move",
                        "fps": _fps,
                        "avg_ms": round(self._fps_rolling_ms, 2),
                    })
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._fps_enabled:
            btn_map = {
                Qt.MouseButton.LeftButton: "left",
                Qt.MouseButton.MiddleButton: "middle",
                Qt.MouseButton.RightButton: "right",
            }
            self._perf_log_event({
                "type": "mouse_release",
                "button": btn_map.get(event.button(), "other"),
            })
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
        # QGraphicsView forwards drags to the scene first, so we need to
        # accept at this level and NOT call super() which would re-route
        # to the scene and lose the event.
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        event.accept()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            handled = False
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if self.on_file_dropped:
                        pos = self.mapToScene(event.position().toPoint())
                        self.on_file_dropped(path, pos)
                        handled = True
            if handled:
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return
        super().dropEvent(event)


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class StudioEditor(QWidget):
    """Unified censor + overlay + annotation workspace."""

    queue_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studio_editor")
        # Accept URL drops anywhere on the Studio widget — so dragging
        # a tray item onto the layer panel, the toolbar area, or the
        # canvas all work. The top-level widget routes to load_asset /
        # add-overlay depending on whether the base is already loaded.
        self.setAcceptDrops(True)
        self._asset: Asset | None = None
        self._project: Project | None = None
        self._project_path: str = ""
        self._theme = THEMES[DEFAULT_THEME]
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
        # Pre-init flags that handlers / shortcuts currently read via
        # getattr-with-default. Hot-path reads (key/mouse/escape handlers,
        # _on_selection_changed, drawForeground's helper-hide check) now
        # resolve via direct attribute lookup.
        self._isolation_active = False
        self._space_panning = False
        self._space_prev_drag_mode = None
        self._propagating_group_sel = False
        self._last_cursor_scene_pos = None
        self._tc_content_syncing = False
        self._qp_syncing = False
        self._qp_scale_base_map = {}
        self._helpers_hidden_state = None
        self._guide_items = []
        # Layer panel + debounce timer slots — populated by _build()
        # and _schedule_layer_rebuild lazy-init respectively. Pre-init
        # so callers can use direct attribute reads with explicit
        # None-check instead of hasattr probes.
        self._layer_panel = None
        self._layer_rebuild_timer = None
        # Build-created widgets pre-declared as None sentinels so the
        # ubiquitous `self.info_label is not None` / "_canvas_wrap"
        # probes can be converted to `is not None` — cheaper per call
        # and makes the widget lifecycle explicit.
        self.info_label = None
        self._canvas_wrap = None
        # Undo stack must exist before _build() because the toolbar wires
        # the undo/redo buttons to it.
        self._undo_stack = QUndoStack(self)
        self._undo_stack.setUndoLimit(50)
        self._build()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Restore last-used tool (default: SELECT)
        last_tool_name = QSettings("DoxyEdit", "DoxyEdit").value(
            "studio_last_tool", "SELECT", type=str)
        try:
            _last_tool = StudioTool[last_tool_name]
            if _last_tool not in (StudioTool.WATERMARK,
                                    StudioTool.ANNOTATE_TEXT,
                                    StudioTool.ANNOTATE_LINE,
                                    StudioTool.ANNOTATE_BOX):
                self._set_tool(_last_tool)
        except (KeyError, ValueError):
            pass

    # ---- keyboard shortcuts ----

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)

        # Spacebar — temporary hand/pan tool (Photoshop convention)
        if key == Qt.Key.Key_Space and not ctrl and not shift and not event.isAutoRepeat():
            if not self._space_panning:
                self._space_panning = True
                self._space_prev_drag_mode = self._view.dragMode()
                self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                self._view.setCursor(Qt.CursorShape.OpenHandCursor)
            return

        # Ctrl combos
        if ctrl and not shift and key == Qt.Key.Key_Z:
            self._undo_stack.undo()
            return
        # Ctrl+Shift+Z = redo (Illustrator / Inkscape convention) in
        # addition to Ctrl+Y. Previously Ctrl+Shift+Z also undid
        # because the undo branch didn't check shift.
        if ctrl and shift and key == Qt.Key.Key_Z:
            self._undo_stack.redo()
            return
        if ctrl and key == Qt.Key.Key_Y:
            self._undo_stack.redo()
            return
        if ctrl and alt and not shift and key == Qt.Key.Key_D:
            # Ctrl+Alt+D duplicates in place (no offset). Parallel to
            # Ctrl+Shift+V = paste in place. Useful for stamping a
            # symbol and then translating the duplicate precisely.
            self._duplicate_selected(offset=0)
            return
        if ctrl and key == Qt.Key.Key_D:
            self._duplicate_selected()
            return
        if ctrl and key == Qt.Key.Key_J:
            # Photoshop Ctrl+J = Duplicate Layer — alias to Ctrl+D
            self._duplicate_selected()
            return
        if ctrl and key == Qt.Key.Key_C:
            self._copy_selected_items()
            return
        if ctrl and shift and key == Qt.Key.Key_V:
            # Paste in Place — no 20 px offset, matches Photoshop/Illustrator
            self._paste_items_from_clipboard(offset=0)
            return
        if ctrl and key == Qt.Key.Key_V:
            self._paste_items_from_clipboard()
            return
        # Ctrl+A — select all scene items
        if ctrl and key == Qt.Key.Key_A:
            for it in self._scene.items():
                if isinstance(it, _CANVAS_ITEM_TYPES):
                    it.setSelected(True)
            return
        # Ctrl+Shift+A — deselect all
        if ctrl and shift and key == Qt.Key.Key_A:
            self._scene.clearSelection()
            return
        # Ctrl+Shift+O — toggle stroke visibility on selected shapes.
        # If stroke_width > 0, remember it on the item and zero it out;
        # on next toggle, restore. Matches Illustrator's 'No stroke' X
        # stripe toggle without needing the Shape Controls dropdown.
        if ctrl and shift and key == Qt.Key.Key_O:
            touched = 0
            for it in self._scene.selectedItems():
                if isinstance(it, OverlayShapeItem):
                    cur = int(it.overlay.stroke_width or 0)
                    if cur > 0:
                        # Remember on the item itself, not in the asset
                        # data, since this is a transient visibility
                        # toggle (user may undo / redo).
                        setattr(it, "_stroke_width_memo", cur)
                        it.overlay.stroke_width = 0
                    else:
                        it.overlay.stroke_width = (
                            getattr(it, "_stroke_width_memo", 2))
                    it.prepareGeometryChange()
                    it.update()
                    touched += 1
            if touched:
                self._sync_overlays_to_asset()
                self.info_label.setText(
                    f"Toggled stroke on {touched} shape"
                    f"{'s' if touched != 1 else ''}")
            return
        # Ctrl+Shift+D — Illustrator / Photoshop 'deselect' alias.
        if ctrl and shift and key == Qt.Key.Key_D:
            self._scene.clearSelection()
            self.info_label.setText("Deselected")
            return
        # Ctrl+Shift+N — add a new text overlay at the last cursor
        # position (or the canvas center if the cursor hasn't been
        # tracked yet). Mirrors the 'new note / new asset' family of
        # shortcuts without reaching for the T tool.
        if ctrl and shift and key == Qt.Key.Key_N:
            last = self._last_cursor_scene_pos
            if last is not None:
                x, y = int(last.x()), int(last.y())
            elif self._pixmap_item is not None:
                br = self._pixmap_item.boundingRect()
                x, y = int(br.center().x()), int(br.center().y())
            else:
                x, y = 50, 50
            self._add_text_overlay(x, y)
            return
        # Ctrl+Shift+B — copy geometry of selected item as text to clipboard
        if ctrl and shift and key == Qt.Key.Key_B:
            sel = self._scene.selectedItems()
            if sel:
                r = sel[0].sceneBoundingRect()
                for it in sel[1:]:
                    r = r.united(it.sceneBoundingRect())
                txt = f"X={int(r.x())}, Y={int(r.y())}, W={int(r.width())}, H={int(r.height())}"
                QApplication.clipboard().setText(txt)
                self.info_label.setText(f"Copied geometry: {txt}")
            return
        # Ctrl+Alt+H — un-hide every overlay + censor (reverse of
        # accidentally hitting Alt+H on everything). Complement of
        # Alt+I 'isolate' which hides everything else.
        if ctrl and alt and not shift and key == Qt.Key.Key_H:
            touched = 0
            for it in self._overlay_items:
                ov = getattr(it, "overlay", None)
                if ov is not None and not ov.enabled:
                    ov.enabled = True
                    it.setVisible(True)
                    touched += 1
            for it in self._censor_items:
                if not it.isVisible():
                    it.setVisible(True)
                    touched += 1
            if touched:
                self._sync_overlays_to_asset()
                self.info_label.setText(
                    f"Un-hid {touched} layer"
                    f"{'s' if touched != 1 else ''}")
            else:
                self.info_label.setText("Nothing was hidden")
            return
        # Alt+N — toggle note-overlay visibility (the yellow stickies).
        # Doesn't conflict with the N tool shortcut (plain N) because
        # this branch requires the Alt modifier.
        if alt and not ctrl and not shift and key == Qt.Key.Key_N:
            if hasattr(self, "chk_notes"):
                self.chk_notes.setChecked(not self.chk_notes.isChecked())
            return
        # Alt+H — toggle visibility (hide / show) on every selected
        # overlay. Faster than Shift+click in the layer panel when
        # you want to flip several layers at once. Censors and crops
        # respect the same shortcut.
        if alt and not ctrl and not shift and key == Qt.Key.Key_H:
            sel = self._scene.selectedItems()
            touched = 0
            for it in sel:
                ov = getattr(it, "overlay", None)
                if ov is not None:
                    ov.enabled = not ov.enabled
                    it.setVisible(ov.enabled)
                    touched += 1
            if touched:
                self._sync_overlays_to_asset()
                self.info_label.setText(
                    f"Toggled visibility on {touched} layer"
                    f"{'s' if touched != 1 else ''}")
            return
        # Ctrl+Shift+T — toggle the left tool palette (Main side bar)
        # visibility. Useful for a cleaner canvas-only view when you're
        # just nudging existing overlays.
        if ctrl and shift and key == Qt.Key.Key_T:
            win = self.window()
            if win is not None and hasattr(win, "_left_toolbar"):
                tb = win._left_toolbar
                tb.setVisible(not tb.isVisible())
                self.info_label.setText(
                    "Tool palette hidden"
                    if not tb.isVisible()
                    else "Tool palette shown")
            return
        # Ctrl+Shift+C — copy the hex color of the primary selected
        # overlay to clipboard. For shapes: fill_color (falls back to
        # stroke_color). For text: color. For arrows: color. Useful
        # for round-tripping a color into external tools.
        if ctrl and shift and key == Qt.Key.Key_C:
            sel = [it for it in self._scene.selectedItems()
                   if getattr(it, "overlay", None) is not None]
            if sel:
                ov = sel[0].overlay
                hex_c = (ov.fill_color
                          or ov.color
                          or ov.stroke_color)
                if hex_c:
                    QApplication.clipboard().setText(hex_c)
                    self.info_label.setText(f"Copied color: {hex_c}")
                else:
                    self.info_label.setText("Selection has no color")
            return
        # Alt+B / Alt+Shift+B - cycle blend mode forward / backward on
        # all selected non-censor overlays. Photoshop has Shift++ /
        # Shift+- but those conflict with zoom; Alt+B keeps bindings
        # isolated. Cycle wraps at both ends.
        if alt and not ctrl and key == Qt.Key.Key_B:
            _modes = ("normal", "multiply", "screen", "overlay",
                       "darken", "lighten")
            direction = -1 if shift else +1
            touched = 0
            for it in self._scene.selectedItems():
                ov = getattr(it, "overlay", None)
                if ov is None:
                    continue
                cur_mode = ov.blend_mode
                idx = _modes.index(cur_mode) if cur_mode in _modes else 0
                new_mode = _modes[(idx + direction) % len(_modes)]
                ov.blend_mode = new_mode
                if hasattr(it, "update"):
                    it.update()
                touched += 1
            if touched:
                self._sync_overlays_to_asset()
                # Pick the first selection to report the new mode
                first = next((it for it in self._scene.selectedItems()
                               if getattr(it, "overlay", None)), None)
                mode_name = (
                    first.overlay.blend_mode.title()
                    if first and hasattr(first, "overlay") else "normal")
                self.info_label.setText(
                    f"Blend mode: {mode_name} ({touched} layer"
                    f"{'s' if touched != 1 else ''})")
            return
        # Alt+I - toggle isolation mode. When off, solos the first
        # selected overlay (hides every other layer temporarily). When
        # on, restores all layers to their stored enabled state. Matches
        # Illustrator's Enter-on-layer workflow with a keyboard-only path.
        if alt and not ctrl and not shift and key == Qt.Key.Key_I:
            if self._isolation_active:
                self._exit_isolation()
            else:
                sel = [it for it in self._scene.selectedItems()
                       if hasattr(it, "overlay")]
                if sel:
                    self._enter_isolation(sel[0].overlay)
                else:
                    self.info_label.setText(
                        "Select a layer first to isolate")
            return
        # Ctrl+Shift+I — invert selection among selectable items
        if ctrl and shift and key == Qt.Key.Key_I:
            for it in self._scene.items():
                if isinstance(it, _CANVAS_ITEM_TYPES):
                    it.setSelected(not it.isSelected())
            return
        # Ctrl+Shift+H / Ctrl+Shift+V — flip selected overlays
        if ctrl and shift and key == Qt.Key.Key_H:
            self._flip_selected("h")
            return
        if ctrl and shift and key == Qt.Key.Key_V:
            self._flip_selected("v")
            return
        # Shift+Tab — cycle selection backwards
        if shift and not ctrl and key == Qt.Key.Key_Backtab:
            self._cycle_selection(-1)
            return
        # Shift+R — rotate 90 CCW (plain R is 90 CW)
        if shift and not ctrl and key == Qt.Key.Key_R:
            self._rotate_selected(-90)
            return
        # Shift+G — toggle rule-of-thirds overlay
        if shift and not ctrl and key == Qt.Key.Key_G:
            if hasattr(self, "chk_thirds"):
                self.chk_thirds.setChecked(not self.chk_thirds.isChecked())
            return
        # (Plain G toggles the snap grid; see the branch near the end of
        # this method. Ctrl+G used to duplicate that binding, but it was
        # shadowing the real Ctrl+G = 'group selection' shortcut, so the
        # Ctrl+G grid alias has been dropped.)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        # Alt+Up / Alt+Down z-shift removed - arrow keys reserved for text
        # field cursor movement per user preference. Use Ctrl+] / Ctrl+[
        # for layer z-order changes instead.
        # Ctrl+Alt+L / Ctrl+Alt+E — align selected text left / center
        # (Ctrl+Shift+R is rotate; Ctrl+Alt keeps the combo unique.)
        if ctrl and alt and key in (Qt.Key.Key_L, Qt.Key.Key_E, Qt.Key.Key_R):
            align = "left" if key == Qt.Key.Key_L else (
                "center" if key == Qt.Key.Key_E else "right")
            touched = False
            for item in self._scene.selectedItems():
                if isinstance(item, OverlayTextItem):
                    self._push_overlay_attr(
                        item, "text_align", align,
                        apply_cb=lambda it, _v: it._apply_font(),
                        description=f"Align text {align}")
                    touched = True
            if touched:
                self._sync_overlays_to_asset()
                return
        # Ctrl+R toggles ruler visibility (Photoshop convention).
        # Fine rotation (1°) moves to Alt+wheel which already rotates in
        # 5° ticks; 1° steps can be achieved via the Ctrl+T transform
        # dialog or the rotation spinbox in the quickbar.
        if ctrl and not shift and key == Qt.Key.Key_R:
            if hasattr(self, "chk_rulers"):
                self.chk_rulers.setChecked(not self.chk_rulers.isChecked())
            return
        if ctrl and shift and key == Qt.Key.Key_R:
            # Ctrl+Shift+R still rotates 1° CCW for users who had it in
            # muscle memory. Prefer the Transform dialog though.
            self._rotate_selected(-1)
            return
        # Ctrl+H hides all helpers: grid, thirds, rulers, guides. Press
        # again to restore. Preview-pass affordance complementary to
        # the backslash peek (which hides OVERLAYS; this hides helpers).
        if ctrl and not shift and key == Qt.Key.Key_H:
            self._toggle_all_helpers()
            return
        # Ctrl+; toggles guide visibility (Photoshop convention).
        if ctrl and not shift and key == Qt.Key.Key_Semicolon:
            self._toggle_guides_visibility()
            return
        # Backslash (\) — hold to preview base art with overlays hidden.
        # Release restores visibility. Like Photoshop's 'quick mask off'
        # peek. Ignores auto-repeat so it fires exactly once per press.
        if key == Qt.Key.Key_Backslash and not event.isAutoRepeat():
            self._set_overlays_preview_hidden(True)
            return
        # Ctrl+Alt+P = toggle sticky preview mode (opposite of the
        # hold-to-peek backslash). Flips the flag and leaves overlays
        # hidden / visible until the shortcut is pressed again.
        if ctrl and alt and not shift and key == Qt.Key.Key_P:
            cur = getattr(self, "_preview_sticky", False)
            self._set_overlays_preview_hidden(not cur)
            self._preview_sticky = not cur
            if self.info_label is not None:
                self.info_label.setText(
                    "Preview mode ON (Ctrl+Alt+P to exit)"
                    if self._preview_sticky else "Preview mode OFF")
            return
        # Ctrl+G / Ctrl+Shift+G — group / ungroup selected overlays.
        # Groups are a simple string token on CanvasOverlay.group_id;
        # selection logic propagates group membership so clicking one
        # selects the whole group.
        if ctrl and not shift and key == Qt.Key.Key_G:
            sel = [it for it in self._scene.selectedItems()
                   if hasattr(it, "overlay")]
            if len(sel) >= 2:
                gid = f"g_{uuid.uuid4().hex[:8]}"
                for it in sel:
                    it.overlay.group_id = gid
                self._sync_overlays_to_asset()
                self.info_label.setText(
                    f"Grouped {len(sel)} overlays")
            return
        if ctrl and shift and key == Qt.Key.Key_G:
            sel = [it for it in self._scene.selectedItems()
                   if hasattr(it, "overlay")]
            cleared = 0
            for it in sel:
                if it.overlay.group_id:
                    it.overlay.group_id = ""
                    cleared += 1
            if cleared:
                self._sync_overlays_to_asset()
                self.info_label.setText(f"Ungrouped {cleared} overlays")
            return
        # Ctrl+Home - recenter the canvas on the pixmap origin. Handy
        # after a series of pans when the user wants to reset.
        if ctrl and key == Qt.Key.Key_Home:
            if self._pixmap_item is not None:
                self._view.centerOn(self._pixmap_item)
            return
        # F2 - rename the currently-selected overlay (layer-panel row)
        # without having to go through the right-click context menu.
        # Mirrors the global app F2-to-rename convention.
        if key == Qt.Key.Key_F2 and not ctrl and not shift:
            sel = self._scene.selectedItems()
            sel_overlays = [it for it in sel if hasattr(it, "overlay")]
            if sel_overlays:
                ov = sel_overlays[0].overlay
                new_label, ok = QInputDialog.getText(
                    self, "Rename layer", "Label:", text=ov.label or "")
                if ok and new_label.strip():
                    ov.label = new_label.strip()
                    self._rebuild_layer_panel()
                    self._sync_overlays_to_asset()
                    self.info_label.setText(f"Renamed to '{ov.label}'")
            return
        # Ctrl+F - open Find and Replace across all text overlays. This
        # was only reachable via the text-overlay right-click menu
        # before, so it wasn't discoverable until you already had a
        # text selected.
        if ctrl and not shift and not alt and key == Qt.Key.Key_F:
            self._find_replace_text()
            return
        # Shift+F - fit view to the union bounding rect of the current
        # selection. Zoom-to-selection. If nothing's selected, no-op.
        if shift and not ctrl and key == Qt.Key.Key_F:
            sel = self._scene.selectedItems()
            if sel:
                bounds = sel[0].sceneBoundingRect()
                for it in sel[1:]:
                    bounds = bounds.united(it.sceneBoundingRect())
                bounds.adjust(-40, -40, 40, 40)
                self._view.fitInView(
                    bounds, Qt.AspectRatioMode.KeepAspectRatio)
                if hasattr(self, "_zoom_label"):
                    self._zoom_label.setText(
                        f"{int(self._view.transform().m11() * 100)}%")
                if self._canvas_wrap is not None:
                    self._canvas_wrap.refresh()
            return
        # Shift+H / Shift+V drops a horizontal / vertical guide at the
        # current cursor position. Saves the ruler-drag gesture for a
        # single click-and-go workflow when the user knows where they
        # want the guide. Ctrl+Shift+G was reserved, so Shift+letter
        # stays clear of the app's global shortcuts.
        if shift and not ctrl and key == Qt.Key.Key_H:
            self._add_guide_at_cursor('h')
            return
        if shift and not ctrl and key == Qt.Key.Key_V:
            self._add_guide_at_cursor('v')
            return
        # Ctrl+/ opens the Studio keyboard cheat sheet.
        if ctrl and key == Qt.Key.Key_Slash:
            self._show_shortcuts_cheat_sheet()
            return
        # F1 alias for the cheat sheet (standard help key).
        if key == Qt.Key.Key_F1 and not ctrl and not shift:
            self._show_shortcuts_cheat_sheet()
            return
        # Shift+Ctrl+I invert selection among selectable items.
        if ctrl and shift and key == Qt.Key.Key_I:
            for it in self._scene.items():
                if isinstance(it, _CANVAS_ITEM_TYPES) and it.parentItem() is None:
                    it.setSelected(not it.isSelected())
            self.info_label.setText("Selection inverted")
            return
        # Ctrl+, opens Studio Settings (conventional app-settings shortcut).
        if ctrl and key == Qt.Key.Key_Comma:
            self._show_studio_settings()
            return
        # Ctrl+Alt+C / Ctrl+Alt+V - copy / paste overlay style. Per-type
        # slot so a text style pasted onto a text overlay works, but a
        # shape style won't silently paste onto a text (different fields).
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        if ctrl and alt and not shift and key == Qt.Key.Key_C:
            sel = self._scene.selectedItems()
            if sel and hasattr(sel[0], "overlay"):
                self._copy_style(sel[0].overlay)
            return
        if ctrl and alt and not shift and key == Qt.Key.Key_V:
            touched = False
            for it in self._scene.selectedItems():
                if hasattr(it, "overlay"):
                    self._paste_style(it.overlay, it)
                    touched = True
            if touched:
                self._sync_overlays_to_asset()
            return
        # Ctrl+Shift+E quick-exports the preview PNG (same action as the
        # Export toolbar button). Global Ctrl+E is reserved for 'Export
        # All Platforms' so Shift distinguishes the two.
        if ctrl and shift and key == Qt.Key.Key_E:
            self._export_preview()
            return
        # Ctrl+B / Ctrl+I / Ctrl+U / Ctrl+Shift+5 - Bold / Italic /
        # Underline / Strikethrough on the selected text overlay(s).
        # Matches Word / Google Docs bindings; toggles the attr +
        # refreshes the quickbar buttons so state reflects.
        if ctrl and not shift and not alt and key == Qt.Key.Key_B \
                and hasattr(self, "btn_bold"):
            sel_texts = [it for it in self._scene.selectedItems()
                          if isinstance(it, OverlayTextItem)]
            if sel_texts:
                self.btn_bold.setChecked(not self.btn_bold.isChecked())
                self._on_bold_changed()
            return
        if ctrl and not shift and not alt and key == Qt.Key.Key_I \
                and hasattr(self, "btn_italic"):
            sel_texts = [it for it in self._scene.selectedItems()
                          if isinstance(it, OverlayTextItem)]
            if sel_texts:
                self.btn_italic.setChecked(not self.btn_italic.isChecked())
                self._on_italic_changed()
            return
        if ctrl and not shift and not alt and key == Qt.Key.Key_U \
                and hasattr(self, "btn_underline"):
            sel_texts = [it for it in self._scene.selectedItems()
                          if isinstance(it, OverlayTextItem)]
            if sel_texts:
                self.btn_underline.setChecked(not self.btn_underline.isChecked())
                self._on_underline_changed()
            return
        # Ctrl+Shift+> / Ctrl+Shift+< - bump / shrink font size of selected
        # text overlays by 2pt. Google Docs convention. > uses Period /
        # Greater, < uses Comma / Less depending on layout.
        if ctrl and shift and key in (
                Qt.Key.Key_Period, Qt.Key.Key_Greater):
            touched = False
            for it in self._scene.selectedItems():
                if isinstance(it, OverlayTextItem):
                    it.overlay.font_size = min(500, it.overlay.font_size + 2)
                    if hasattr(it, "_apply_font"):
                        it._apply_font()
                    touched = True
            if touched:
                self._sync_overlays_to_asset()
                if hasattr(self, "slider_font_size"):
                    sel_text = next(
                        (it for it in self._scene.selectedItems()
                         if isinstance(it, OverlayTextItem)), None)
                    if sel_text is not None:
                        self.slider_font_size.blockSignals(True)
                        self.slider_font_size.setValue(sel_text.overlay.font_size)
                        self.slider_font_size.blockSignals(False)
            return
        # Ctrl+Shift+0 resets rotation of the selected overlays to 0°.
        # Quick recovery after experimenting with rotation/skew sliders.
        if ctrl and shift and key == Qt.Key.Key_0:
            touched = False
            for it in self._scene.selectedItems():
                ov = getattr(it, "overlay", None)
                if ov is None:
                    continue
                ov.rotation = 0.0
                if hasattr(ov, "skew_x"):
                    ov.skew_x = 0.0
                    ov.skew_y = 0.0
                if isinstance(it, OverlayShapeItem):
                    it.setRotation(0)
                    it.setTransform(QTransform())
                elif hasattr(it, "_apply_flip"):
                    it._apply_flip()
                elif hasattr(it, "_apply_flip_text"):
                    it._apply_flip_text()
                else:
                    it.update()
                touched = True
            if touched:
                self._sync_overlays_to_asset()
                self.info_label.setText("Rotation reset")
            return
        if ctrl and shift and key in (
                Qt.Key.Key_Comma, Qt.Key.Key_Less):
            touched = False
            for it in self._scene.selectedItems():
                if isinstance(it, OverlayTextItem):
                    it.overlay.font_size = max(4, it.overlay.font_size - 2)
                    if hasattr(it, "_apply_font"):
                        it._apply_font()
                    touched = True
            if touched:
                self._sync_overlays_to_asset()
                if hasattr(self, "slider_font_size"):
                    sel_text = next(
                        (it for it in self._scene.selectedItems()
                         if isinstance(it, OverlayTextItem)), None)
                    if sel_text is not None:
                        self.slider_font_size.blockSignals(True)
                        self.slider_font_size.setValue(sel_text.overlay.font_size)
                        self.slider_font_size.blockSignals(False)
            return
        # Ctrl+Alt+X swaps fill and stroke colors on selected shapes.
        # Classic graphics shortcut; saves round-tripping two color
        # picker dialogs when the user wants to invert a bubble.
        if ctrl and alt and not shift and key == Qt.Key.Key_X:
            touched = False
            for it in self._scene.selectedItems():
                if isinstance(it, OverlayShapeItem):
                    ov = it.overlay
                    ov.stroke_color, ov.fill_color = (
                        ov.fill_color or "#ffffff",
                        ov.stroke_color or "#000000")
                    it.update()
                    touched = True
            if touched:
                self._sync_overlays_to_asset()
                self.info_label.setText("Swapped fill and stroke colors")
            return
        # Ctrl+T opens the full Transform dialog (position + size + rot +
        # skew + flip). Ctrl+Alt+T kept as an alias for muscle memory.
        if ctrl and not shift and key == Qt.Key.Key_T:
            self._open_transform_dialog()
            return
        if ctrl and alt and not shift and key == Qt.Key.Key_T:
            self._open_transform_dialog()
            return
        # Ctrl+Alt+S - scale selected overlay(s) by percentage (dialog).
        # Scales w and h uniformly; image overlays also scale via `scale`
        # attr so the pixmap gets regenerated at the new size.
        if ctrl and alt and not shift and key == Qt.Key.Key_S:
            value, ok = QInputDialog.getInt(
                self, "Scale Overlay",
                "Scale percentage (100 = no change):",
                value=100, minValue=5, maxValue=1000)
            if ok and value != 100:
                factor = value / 100.0
                touched = False
                for item in self._scene.selectedItems():
                    ov = getattr(item, "overlay", None)
                    if ov is None:
                        continue
                    if isinstance(item, OverlayShapeItem):
                        # Pivot around the current center so the scale
                        # looks natural. Update tail alongside.
                        cx = ov.x + ov.shape_w / 2
                        cy = ov.y + ov.shape_h / 2
                        ov.shape_w = max(4, int(ov.shape_w * factor))
                        ov.shape_h = max(4, int(ov.shape_h * factor))
                        ov.x = int(cx - ov.shape_w / 2)
                        ov.y = int(cy - ov.shape_h / 2)
                        item.prepareGeometryChange()
                        item.update()
                        touched = True
                    elif isinstance(item, OverlayImageItem):
                        ov.scale = max(0.05, ov.scale * factor)
                        if hasattr(item, "_apply_flip"):
                            item._apply_flip()
                        item.update()
                        touched = True
                    elif isinstance(item, OverlayTextItem):
                        ov.font_size = max(4, int(ov.font_size * factor))
                        if hasattr(item, "_apply_font"):
                            item._apply_font()
                        touched = True
                if touched:
                    self._sync_overlays_to_asset()
                    self.info_label.setText(f"Scaled by {value}%")
            return
        # Ctrl+Alt+, / Ctrl+Alt+. = cycle selection to previous / next
        # layer in z-order. Useful when overlapping overlays make
        # click-selection ambiguous.
        if ctrl and alt and not shift and key == Qt.Key.Key_Period:
            self._cycle_selection(+1)
            return
        if ctrl and alt and not shift and key == Qt.Key.Key_Comma:
            self._cycle_selection(-1)
            return
        # Ctrl+Alt+F reveals the selected watermark/image overlay's
        # source file in Windows Explorer. Watermark overlays store an
        # absolute image_path; this shortcut is the fastest way to
        # jump into the folder to replace / edit the source.
        if ctrl and alt and not shift and key == Qt.Key.Key_F:
            sel = [it for it in self._scene.selectedItems()
                   if isinstance(it, OverlayImageItem)]
            if not sel:
                self.info_label.setText("Select an image overlay first")
                return
            import subprocess as _sp
            for it in sel[:3]:  # cap to avoid spawning dozens
                path = getattr(it.overlay, "image_path", "")
                p = Path(path) if path else None
                if p is None or not p.exists():
                    continue
                try:
                    _sp.Popen(["explorer", "/select,", str(p)],
                              creationflags=0x08000000)
                except Exception:
                    pass
            self.info_label.setText("Revealed in Explorer")
            return
        # F3 toggles the snap grid. F4 toggles rule-of-thirds. F5
        # toggles minimap. Convention: Fn keys drive view overlays.
        if key == Qt.Key.Key_F3 and not ctrl and not shift:
            if hasattr(self, "chk_grid"):
                self.chk_grid.setChecked(not self.chk_grid.isChecked())
            return
        if key == Qt.Key.Key_F4 and not ctrl and not shift:
            if hasattr(self, "chk_thirds"):
                self.chk_thirds.setChecked(not self.chk_thirds.isChecked())
            return
        # F9 = toggle minimap. Fn row gives each overlay-helper its
        # own key: F3 grid, F4 thirds, F9 minimap, F11 focus, F12 snap.
        if key == Qt.Key.Key_F9 and not ctrl and not shift:
            if hasattr(self, "chk_minimap"):
                self.chk_minimap.setChecked(not self.chk_minimap.isChecked())
            return
        # F11 = toggle focus mode (alias of plain '.'; F11 is the
        # universal fullscreen key in every major graphics app).
        if key == Qt.Key.Key_F11 and not ctrl and not shift:
            if hasattr(self, "btn_focus"):
                self.btn_focus.setChecked(not self.btn_focus.isChecked())
            return
        # F5..F8 = recall view bookmark slots 1..4.
        # Shift+F5..F8 = save the CURRENT zoom + scroll position into
        # the corresponding slot. Bookmarks persist in QSettings so
        # they survive app restart.
        if (key in (Qt.Key.Key_F5, Qt.Key.Key_F6,
                    Qt.Key.Key_F7, Qt.Key.Key_F8)
                and not ctrl):
            slot = {Qt.Key.Key_F5: 1, Qt.Key.Key_F6: 2,
                    Qt.Key.Key_F7: 3, Qt.Key.Key_F8: 4}[key]
            if shift:
                self._save_view_bookmark(slot)
            else:
                self._load_view_bookmark(slot)
            return
        # F12 toggles snap on/off. Remembers the last non-zero threshold
        # so the user can flip between 'no snap' and 'my usual snap'
        # without re-entering the value each time.
        if key == Qt.Key.Key_F12 and not ctrl and not shift:
            qs = QSettings("DoxyEdit", "DoxyEdit")
            cur = qs.value("studio_snap_threshold_px", 0, type=int)
            if cur > 0:
                qs.setValue("studio_snap_threshold_px_prev", cur)
                qs.setValue("studio_snap_threshold_px", 0)
                self.info_label.setText("Snap: off")
            else:
                prev = qs.value("studio_snap_threshold_px_prev", 5, type=int)
                qs.setValue("studio_snap_threshold_px", max(1, prev))
                self.info_label.setText(f"Snap: on ({max(1, prev)}px)")
            self._scene.reload_snap_threshold()
            return
        # Alignment shortcuts: Alt+Shift + arrow-like keys. These don't
        # collide with text-align Ctrl combos (which use L/R/E with Ctrl
        # and Shift+Alt swapped), so muscle memory from InDesign transfers.
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        if alt and shift and key == Qt.Key.Key_L:
            self._align_selected("left")
            return
        if alt and shift and key == Qt.Key.Key_R:
            self._align_selected("right")
            return
        if alt and shift and key == Qt.Key.Key_C:
            self._align_selected("hcenter")
            return
        if alt and shift and key == Qt.Key.Key_T:
            self._align_selected("top")
            return
        if alt and shift and key == Qt.Key.Key_B:
            self._align_selected("bottom")
            return
        if alt and shift and key == Qt.Key.Key_M:
            self._align_selected("vcenter")
            return
        if alt and shift and key == Qt.Key.Key_H:
            self._align_selected("dist_h")
            return
        if alt and shift and key == Qt.Key.Key_V:
            self._align_selected("dist_v")
            return
        # Ctrl+] / Ctrl+[ — bring forward / send backward
        # Ctrl+Shift+] / Ctrl+Shift+[ — bring to front / send to back
        # Some layouts send Key_Brace{Left,Right} when Shift is held, others
        # keep Key_Bracket{Left,Right}. Handle both.
        if ctrl and shift and key in (Qt.Key.Key_BraceRight, Qt.Key.Key_BracketRight):
            self._z_shift_selected(+999)
            return
        if ctrl and shift and key in (Qt.Key.Key_BraceLeft, Qt.Key.Key_BracketLeft):
            self._z_shift_selected(-999)
            return
        if ctrl and key == Qt.Key.Key_BracketRight:
            self._z_shift_selected(+1)
            return
        if ctrl and key == Qt.Key.Key_BracketLeft:
            self._z_shift_selected(-1)
            return
        # Alt+] / Alt+[ — select next / previous overlay in stack order
        # (graphics-app convention; walks z-order with wrap-around).
        if alt and not ctrl and not shift and key in (
            Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight,
        ):
            self._select_layer_relative(
                +1 if key == Qt.Key.Key_BracketRight else -1)
            return
        # Ctrl+L — toggle lock on selected overlays
        if ctrl and not shift and key == Qt.Key.Key_L:
            changed = False
            for item in self._scene.selectedItems():
                ov = getattr(item, "overlay", None)
                if ov is None:
                    continue
                ov.locked = not ov.locked
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                              not ov.locked)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,
                              not ov.locked)
                changed = True
            if changed:
                self._sync_overlays_to_asset()
            return
        # Ctrl+Alt+L — lock / unlock ALL overlays (toggle based on
        # current first overlay state). Mirror of the canvas context
        # menu 'Lock All Layers' entry as a keyboard shortcut.
        if ctrl and alt and key == Qt.Key.Key_L:
            if not self._overlay_items:
                return
            # Flip based on first overlay's current state
            first_ov = getattr(self._overlay_items[0], "overlay", None)
            lock = not bool(getattr(first_ov, "locked", False)) if first_ov else True
            for it in self._overlay_items:
                ov = getattr(it, "overlay", None)
                if ov is not None:
                    ov.locked = lock
                    it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                                not lock)
                    it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,
                                not lock)
            self._sync_overlays_to_asset()
            self.info_label.setText(
                "All overlays locked" if lock else "All overlays unlocked")
            return
        # [ / ] with no modifier — adjust arrowhead_size on arrows
        # and stroke_width on shapes. One keystroke works across all
        # selected overlays of either type, matching Illustrator's
        # bracket convention for brush size.
        if not ctrl and not shift and key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
            delta = -2 if key == Qt.Key.Key_BracketLeft else 2
            touched = False
            touched_arrow = False
            for item in self._scene.selectedItems():
                if isinstance(item, OverlayArrowItem):
                    item.overlay.arrowhead_size = max(
                        4, item.overlay.arrowhead_size + delta)
                    item.prepareGeometryChange()
                    item.update()
                    touched = True
                    touched_arrow = True
                elif isinstance(item, OverlayShapeItem):
                    cur = max(0, int(item.overlay.stroke_width or 0))
                    item.overlay.stroke_width = max(0, min(50, cur + delta))
                    item.prepareGeometryChange()
                    item.update()
                    touched = True
            if touched:
                self._sync_overlays_to_asset()
                if touched_arrow:
                    first_arrow = next(
                        (it for it in self._scene.selectedItems()
                         if isinstance(it, OverlayArrowItem)), None)
                    if first_arrow is not None:
                        QSettings("DoxyEdit", "DoxyEdit").setValue(
                            "studio_arrow_head",
                            first_arrow.overlay.arrowhead_size)
                return
        # Zoom shortcuts — standard in every graphics editor
        if ctrl and shift and key == Qt.Key.Key_0:
            # Zoom to selection (fall back to canvas if none)
            selected = self._scene.selectedItems()
            if selected:
                bounds = selected[0].sceneBoundingRect()
                for it in selected[1:]:
                    bounds = bounds.united(it.sceneBoundingRect())
                bounds.adjust(-20, -20, 20, 20)  # small margin
                self._view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
                self._zoom_label.setText(
                    f"{int(self._view.transform().m11() * 100)}%")
                if self._canvas_wrap is not None:
                    self._canvas_wrap.refresh()
            return
        if ctrl and key == Qt.Key.Key_0:
            # Fit view
            if self._scene.sceneRect():
                self._view.fitInView(self._scene.sceneRect(),
                                      Qt.AspectRatioMode.KeepAspectRatio)
                self._zoom_label.setText("Fit")
                if self._canvas_wrap is not None:
                    self._canvas_wrap.refresh()
            return
        if ctrl and key == Qt.Key.Key_1:
            self._set_zoom(1.0)
            return
        # Ctrl+2 / Ctrl+3 / Ctrl+4 → 200% / 300% / 400% zoom. Common in
        # graphics apps for pixel-level work on a specific region.
        if ctrl and key == Qt.Key.Key_2:
            self._set_zoom(2.0)
            return
        if ctrl and key == Qt.Key.Key_3:
            self._set_zoom(3.0)
            return
        if ctrl and key == Qt.Key.Key_4:
            self._set_zoom(4.0)
            return
        if ctrl and key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._view.scale(1.25, 1.25)
            self._zoom_label.setText(f"{int(self._view.transform().m11() * 100)}%")
            if self._canvas_wrap is not None:
                self._canvas_wrap.refresh()
            return
        if ctrl and key == Qt.Key.Key_Minus:
            self._view.scale(0.8, 0.8)
            self._zoom_label.setText(f"{int(self._view.transform().m11() * 100)}%")
            if self._canvas_wrap is not None:
                self._canvas_wrap.refresh()
            return
        # Numpad + / - zoom too (no Ctrl). The main-keyboard +/- keys
        # stay on Ctrl to avoid colliding with the arrowhead-size []
        # bindings, but the numpad is free.
        if key == Qt.Key.Key_Plus and not ctrl and not shift:
            self._view.scale(1.2, 1.2)
            self._zoom_label.setText(f"{int(self._view.transform().m11() * 100)}%")
            if self._canvas_wrap is not None:
                self._canvas_wrap.refresh()
            return
        if key == Qt.Key.Key_Minus and not ctrl and not shift:
            self._view.scale(1 / 1.2, 1 / 1.2)
            self._zoom_label.setText(f"{int(self._view.transform().m11() * 100)}%")
            if self._canvas_wrap is not None:
                self._canvas_wrap.refresh()
            return

        # Delete
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            # Skip if a text item is mid-edit AND has real content - the
            # user is editing characters in their text. But if a freshly
            # created text is in edit mode with only the placeholder
            # ("Your text") still in the box, treat Delete as 'cancel
            # this overlay' rather than 'delete one character'. Otherwise
            # users who tapped the text tool by accident had no way to
            # back out: the item kept showing in the layer list.
            blocked = False
            for item in self._scene.selectedItems():
                if isinstance(item, OverlayTextItem) and \
                   item.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction:
                    cur_text = item.toPlainText().strip()
                    if cur_text and cur_text != "Your text":
                        blocked = True
                        break
                    # Edit mode + placeholder content: exit edit mode so
                    # _delete_selected can remove the whole overlay.
                    item.setTextInteractionFlags(
                        Qt.TextInteractionFlag.NoTextInteraction)
                    item.clearFocus()
            if not blocked:
                self._delete_selected()
            return

    def keyReleaseEvent(self, event: QKeyEvent):
        # Release backslash — restore overlay visibility after preview peek
        if (event.key() == Qt.Key.Key_Backslash
                and not event.isAutoRepeat()):
            self._set_overlays_preview_hidden(False)
            return
        # Release spacebar pan — restore previous drag mode
        if (event.key() == Qt.Key.Key_Space
                and not event.isAutoRepeat()
                and self._space_panning):
            self._space_panning = False
            prev = self._space_prev_drag_mode
            if prev is None:
                prev = QGraphicsView.DragMode.RubberBandDrag
            self._view.setDragMode(prev)
            self._view.setCursor(Qt.CursorShape.ArrowCursor)
            return
        super().keyReleaseEvent(event)
        # The handlers below historically lived inside keyPressEvent but
        # ended up misattached here after a refactor split the method;
        # resurrecting them by defining the locals explicitly. Firing on
        # release is acceptable for arrow-nudge + tool shortcuts since
        # the user typically presses and releases quickly.
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)

        # Arrow-key nudges removed per user preference - arrow keys are
        # reserved for cursor movement inside text fields. Drag overlays
        # with the mouse to reposition.

        # Escape: force-clear selection + exit any active tool even when
        # focus is on a sidebar button (previously the widget-level
        # handler just re-dispatched to super, which never reached the
        # scene if focus was on a button or the toolbar). Scene / text
        # item paths still handle their own edit-exit below via event
        # propagation if the scene happens to own focus.
        if key == Qt.Key.Key_Escape:
            focus = self._scene.focusItem()
            if focus is not None and isinstance(focus, OverlayTextItem):
                cur = focus.textCursor()
                cur.clearSelection()
                focus.setTextCursor(cur)
                focus.setTextInteractionFlags(
                    Qt.TextInteractionFlag.NoTextInteraction)
                focus.overlay.text = focus.toPlainText()
                focus.clearFocus()
            self._scene.clearSelection()
            self._clear_escape_state()
            if self._scene.current_tool != StudioTool.SELECT:
                self._set_tool(StudioTool.SELECT)
            event.accept()
            return

        # Shift+B inserts a thought bubble at cursor (sibling to plain
        # B for speech bubble and K for burst). Fired before the 'no
        # modifier' block below since this one specifically wants Shift.
        if shift and not ctrl and not alt and key == Qt.Key.Key_B:
            self._quick_add_bubble(kind="thought_bubble")
            return

        # Tool shortcuts (only when no modifier)
        if not ctrl and not shift:
            # V is the Photoshop Move tool; Q is already Select. Map both
            # to StudioTool.SELECT for muscle-memory parity.
            if key == Qt.Key.Key_Q or key == Qt.Key.Key_V:
                self._set_tool(StudioTool.SELECT)
                return
            if key == Qt.Key.Key_X:
                self._set_tool(StudioTool.CENSOR)
                return
            if key == Qt.Key.Key_E:
                self._set_tool(StudioTool.WATERMARK)
                return
            if key == Qt.Key.Key_T:
                self._set_tool(StudioTool.TEXT_OVERLAY)
                return
            if key == Qt.Key.Key_C:
                self._set_tool(StudioTool.CROP)
                return
            if key == Qt.Key.Key_B:
                # Quick bubble: drop a speech bubble at the last cursor
                # position (or canvas center) with paired text, then
                # immediately enter edit mode. Comic workflow shortcut.
                self._quick_add_bubble()
                return
            if key == Qt.Key.Key_K:
                # Quick burst ('Kaboom' / shout) at the cursor. Bursts
                # are decorative so no paired text is auto-created; the
                # user can still add one with T afterwards.
                self._quick_add_bubble(kind="burst")
                return
            if key == Qt.Key.Key_N:
                self._set_tool(StudioTool.NOTE)
                return
            if key == Qt.Key.Key_I:
                self._set_tool(StudioTool.EYEDROPPER)
                return
            if key == Qt.Key.Key_A:
                self._set_tool(StudioTool.ARROW)
                return
            if key == Qt.Key.Key_R:
                self._rotate_selected(90)
                return
            if key == Qt.Key.Key_Tab:
                self._cycle_selection(+1)
                return
            if key == Qt.Key.Key_Home:
                # Select first alignable item
                items = [it for it in self._scene.items()
                          if isinstance(it, _CANVAS_ITEM_TYPES)
                          and it.parentItem() is None]
                if items:
                    items.sort(key=lambda it: (it.sceneBoundingRect().y(),
                                                it.sceneBoundingRect().x()))
                    self._scene.clearSelection()
                    items[0].setSelected(True)
                    self._view.centerOn(items[0])
                return
            if key == Qt.Key.Key_End:
                items = [it for it in self._scene.items()
                          if isinstance(it, _CANVAS_ITEM_TYPES)
                          and it.parentItem() is None]
                if items:
                    items.sort(key=lambda it: (it.sceneBoundingRect().y(),
                                                it.sceneBoundingRect().x()))
                    self._scene.clearSelection()
                    items[-1].setSelected(True)
                    self._view.centerOn(items[-1])
                return
            if key == Qt.Key.Key_Period:
                # Focus mode toggle
                self.btn_focus.setChecked(not self.btn_focus.isChecked())
                return
            if key == Qt.Key.Key_M:
                # Minimap toggle (Photoshop: M = marquee; we repurpose)
                if hasattr(self, "chk_minimap"):
                    self.chk_minimap.setChecked(not self.chk_minimap.isChecked())
                return
            # Number keys 0-9 set opacity on selected non-text overlays and
            # censors. Photoshop convention: 1=10%, 5=50%, 0=100%.
            _num_keys = (Qt.Key.Key_0, Qt.Key.Key_1, Qt.Key.Key_2,
                         Qt.Key.Key_3, Qt.Key.Key_4, Qt.Key.Key_5,
                         Qt.Key.Key_6, Qt.Key.Key_7, Qt.Key.Key_8,
                         Qt.Key.Key_9)
            if key in _num_keys:
                selected = self._scene.selectedItems()
                if selected:
                    idx = _num_keys.index(key)
                    opacity = 1.0 if idx == 0 else idx / 10.0
                    any_applied = False
                    for item in selected:
                        if isinstance(item, (OverlayImageItem, OverlayTextItem)):
                            self._push_overlay_attr(
                                item, "opacity", opacity,
                                apply_cb=lambda it, _v: (
                                    it.setOpacity(it.overlay.opacity)
                                    if hasattr(it, "setOpacity") else None),
                                description="Set opacity",
                            )
                            any_applied = True
                        elif isinstance(item, (OverlayArrowItem, OverlayShapeItem)):
                            self._push_overlay_attr(
                                item, "opacity", opacity,
                                apply_cb=lambda it, _v: it.update(),
                                description="Set opacity",
                            )
                            any_applied = True
                    if any_applied:
                        self._sync_overlays_to_asset()
                        self.info_label.setText(f"Opacity: {int(opacity * 100)}%")
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
                # Toggle via the checkbox so UI stays in sync
                self.chk_grid.setChecked(not self.chk_grid.isChecked())
                return

        super().keyPressEvent(event)

    # ---- construction ----

    def _build(self):
        _dt = THEMES[DEFAULT_THEME]
        # ── Layout ratios (change here to rescale all Studio widgets) ──
        SLIDER_WIDTH_RATIO = 7.0               # standard slider track
        SLIDER_NARROW_RATIO = 5.0              # narrow slider (kerning, outline)
        ICON_BUTTON_WIDTH_RATIO = 2.3          # icon buttons (B, I, ■, ◻)
        ZOOM_BUTTON_WIDTH_RATIO = 5.5          # zoom preset buttons (Fit, 50%, etc.)
        ZOOM_LABEL_WIDTH_RATIO = 3.3           # zoom percentage label
        LAYER_PANEL_MAX_WIDTH_RATIO = 16.7     # layer panel max width

        _pad = max(4, _dt.font_size // 3)
        _pad_lg = max(6, _dt.font_size // 2)
        _slider_w = int(_dt.font_size * SLIDER_WIDTH_RATIO)
        _slider_sm = int(_dt.font_size * SLIDER_NARROW_RATIO)
        _icon_btn_w = int(_dt.font_size * ICON_BUTTON_WIDTH_RATIO)

        root = QVBoxLayout(self)
        root.setContentsMargins(_pad_lg, _pad_lg, _pad_lg, _pad_lg)

        toolbar = _FlowLayout(hSpacing=4, vSpacing=3)
        # FlowLayout's addWidget is inherited; addStretch isn't meaningful
        # (it stacks rows). We just provide a no-op addStretch for the
        # existing call site below.
        def _noop_stretch(*_a, **_kw):
            pass
        toolbar.addStretch = _noop_stretch

        # Group 0: Undo / Redo — reliably-rendered glyphs (↶ is U+21B6
        # 'anticlockwise top semicircle arrow' which some Windows fonts
        # show as tofu; ↺ / ↻ are more common).
        # QPainter-drawn icons via _StudioIcons so Windows font
        # coverage doesn't turn these into tofu squares. Same size
        # envelope as before so the FlowLayout layout is unchanged.
        _ICO_SZ = QSize(16, 16)
        self.btn_undo = QPushButton("")
        self.btn_undo.setIcon(_StudioIcons.undo())
        self.btn_undo.setIconSize(_ICO_SZ)
        self.btn_undo.setObjectName("studio_btn_undo")
        self.btn_undo.setToolTip("Undo (Ctrl+Z)")
        self.btn_undo.setFixedWidth(_icon_btn_w)
        self.btn_undo.clicked.connect(self._undo_stack.undo)
        self.btn_redo = QPushButton("")
        self.btn_redo.setIcon(_StudioIcons.redo())
        self.btn_redo.setIconSize(_ICO_SZ)
        self.btn_redo.setObjectName("studio_btn_redo")
        self.btn_redo.setToolTip("Redo (Ctrl+Y)")
        self.btn_redo.setFixedWidth(_icon_btn_w)
        self.btn_redo.clicked.connect(self._undo_stack.redo)
        # Enable/disable based on stack state
        self._undo_stack.canUndoChanged.connect(self.btn_undo.setEnabled)
        self._undo_stack.canRedoChanged.connect(self.btn_redo.setEnabled)
        self.btn_undo.setEnabled(self._undo_stack.canUndo())
        self.btn_redo.setEnabled(self._undo_stack.canRedo())
        # Tooltip reflects the next action on the stack
        self._undo_stack.undoTextChanged.connect(
            lambda txt: self.btn_undo.setToolTip(
                f"Undo {txt} (Ctrl+Z)" if txt else "Undo (Ctrl+Z)"))
        self._undo_stack.redoTextChanged.connect(
            lambda txt: self.btn_redo.setToolTip(
                f"Redo {txt} (Ctrl+Y)" if txt else "Redo (Ctrl+Y)"))

        self.btn_history = QPushButton("")
        self.btn_history.setIcon(_StudioIcons.history())
        self.btn_history.setIconSize(_ICO_SZ)
        self.btn_history.setObjectName("studio_btn_history")
        self.btn_history.setToolTip("Undo history panel")
        self.btn_history.setFixedWidth(_icon_btn_w)
        self.btn_history.clicked.connect(self._show_undo_history)
        toolbar.addWidget(self.btn_history)
        toolbar.addWidget(self.btn_undo)
        toolbar.addWidget(self.btn_redo)
        toolbar.addWidget(QLabel("|"))

        # Group 1: Selection
        self.btn_select = QPushButton(" Select")
        self.btn_select.setIcon(_StudioIcons.select())
        self.btn_select.setIconSize(_ICO_SZ)
        self.btn_select.setObjectName("studio_btn_select")
        self.btn_select.setToolTip("Select tool (Q)")
        self.btn_select.setCheckable(True)
        self.btn_select.setChecked(True)  # initial tool
        self.btn_select.clicked.connect(lambda: self._set_tool(StudioTool.SELECT))
        toolbar.addWidget(self.btn_select)

        toolbar.addWidget(QLabel("|"))

        # Group 2: Censor tools
        self.btn_censor = QPushButton(" Censor")
        self.btn_censor.setIcon(_StudioIcons.censor())
        self.btn_censor.setIconSize(_ICO_SZ)
        self.btn_censor.setObjectName("studio_btn_censor")
        self.btn_censor.setToolTip("Censor tool (X)")
        self.btn_censor.setCheckable(True)
        self.btn_censor.clicked.connect(lambda: self._set_tool(StudioTool.CENSOR))
        toolbar.addWidget(self.btn_censor)

        self.combo_censor_style = QComboBox()
        self.combo_censor_style.setObjectName("studio_censor_style")
        self.combo_censor_style.addItems(["black", "blur", "pixelate"])
        # Restore the user's preferred censor style from prior sessions
        _saved_censor = QSettings("DoxyEdit", "DoxyEdit").value(
            "studio_censor_default_style", "black", type=str)
        if _saved_censor in ("black", "blur", "pixelate"):
            self.combo_censor_style.setCurrentText(_saved_censor)
        self.combo_censor_style.currentTextChanged.connect(self._on_censor_style_changed)
        toolbar.addWidget(self.combo_censor_style)

        self.btn_crop = QPushButton(" Crop")
        self.btn_crop.setIcon(_StudioIcons.crop())
        self.btn_crop.setIconSize(_ICO_SZ)
        self.btn_crop.setObjectName("studio_btn_crop")
        self.btn_crop.setToolTip("Crop tool (C)")
        self.btn_crop.setCheckable(True)
        self.btn_crop.clicked.connect(lambda: self._set_tool(StudioTool.CROP))
        toolbar.addWidget(self.btn_crop)

        self._crop_combo = QComboBox()
        self._crop_combo.setObjectName("studio_crop_combo")
        _t = THEMES[DEFAULT_THEME]
        # Wide enough for the longest platform slot label without eliding.
        # `_icon_btn_w` * ~12 gives ~300px at the default Studio font size.
        self._crop_combo.setMinimumWidth(max(160, int(_t.font_size * 14)))
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

        self.btn_note = QPushButton(" Note")
        self.btn_note.setIcon(_StudioIcons.note())
        self.btn_note.setIconSize(_ICO_SZ)
        self.btn_note.setObjectName("studio_btn_note")
        self.btn_note.setToolTip("Note tool (N)")
        self.btn_note.setCheckable(True)
        self.btn_note.clicked.connect(lambda: self._set_tool(StudioTool.NOTE))
        toolbar.addWidget(self.btn_note)

        self.btn_eyedropper = QPushButton(" Pick")
        self.btn_eyedropper.setIcon(_StudioIcons.eyedropper())
        self.btn_eyedropper.setIconSize(_ICO_SZ)
        self.btn_eyedropper.setObjectName("studio_btn_eyedropper")
        self.btn_eyedropper.setToolTip(
            "Eyedropper (I): sample a pixel color - applies to selected text "
            "or copies hex to clipboard")
        self.btn_eyedropper.setCheckable(True)
        self.btn_eyedropper.clicked.connect(lambda: self._set_tool(StudioTool.EYEDROPPER))
        toolbar.addWidget(self.btn_eyedropper)

        self.btn_arrow = QPushButton(" Arrow")
        self.btn_arrow.setIcon(_StudioIcons.arrow())
        self.btn_arrow.setIconSize(_ICO_SZ)
        self.btn_arrow.setObjectName("studio_btn_arrow")
        self.btn_arrow.setToolTip("Arrow annotation (A): click-drag to draw")
        self.btn_arrow.setCheckable(True)
        self.btn_arrow.clicked.connect(lambda: self._set_tool(StudioTool.ARROW))
        toolbar.addWidget(self.btn_arrow)

        self.btn_shape = QPushButton(" Shape")
        self.btn_shape.setIcon(_StudioIcons.shape())
        self.btn_shape.setIconSize(_ICO_SZ)
        self.btn_shape.setObjectName("studio_btn_shape")
        self.btn_shape.setToolTip("Shape (rectangle/ellipse) - click-drag to draw")
        self.btn_shape.setCheckable(True)
        self.btn_shape.clicked.connect(lambda: self._set_tool(StudioTool.SHAPE_RECT))
        toolbar.addWidget(self.btn_shape)

        self.combo_shape_kind = QComboBox()
        self.combo_shape_kind.setObjectName("studio_shape_kind")
        self.combo_shape_kind.addItems([
            "Rectangle", "Ellipse",
            "Speech Bubble", "Thought Bubble", "Burst",
            "Star", "Polygon",
        ])
        self.combo_shape_kind.setToolTip(
            "Shape kind - click Shape then drag to draw")
        toolbar.addWidget(self.combo_shape_kind)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setObjectName("studio_btn_delete")
        self.btn_delete.clicked.connect(self._delete_selected)
        toolbar.addWidget(self.btn_delete)

        toolbar.addWidget(QLabel("|"))

        # Group 3: Overlay tools
        self.btn_watermark = QPushButton(" Image")
        self.btn_watermark.setIcon(_StudioIcons.watermark())
        self.btn_watermark.setIconSize(_ICO_SZ)
        self.btn_watermark.setObjectName("studio_btn_watermark")
        self.btn_watermark.setToolTip("Image / logo tool (E) — embeds a watermark or logo overlay")
        self.btn_watermark.setCheckable(True)
        self.btn_watermark.clicked.connect(lambda: self._set_tool(StudioTool.WATERMARK))
        toolbar.addWidget(self.btn_watermark)

        self.btn_text = QPushButton(" Text")
        self.btn_text.setIcon(_StudioIcons.text())
        self.btn_text.setIconSize(_ICO_SZ)
        self.btn_text.setObjectName("studio_btn_text")
        self.btn_text.setToolTip("Text overlay tool (T)")
        self.btn_text.setCheckable(True)
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
        # Default to fully opaque - users want crisp text/watermarks. The
        # slider is for explicit transparency, not a perpetual nag.
        self.slider_opacity.setValue(100)
        self.slider_opacity.setFixedWidth(_slider_w)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        toolbar.addWidget(self.slider_opacity)

        toolbar.addWidget(QLabel("Scale:"))
        self.slider_scale = QSlider(Qt.Orientation.Horizontal)
        self.slider_scale.setObjectName("studio_scale_slider")
        # 1 - 1000%. Range matches the shape-controls + quickbar scale
        # sliders so all three inputs cover the same interval - they're
        # the same underlying overlay.scale value, decoupled ranges led
        # to one slider clamping where another could go further.
        self.slider_scale.setRange(1, 1000)
        self.slider_scale.setValue(100)
        self.slider_scale.setFixedWidth(_slider_w)
        self.slider_scale.valueChanged.connect(self._on_scale_changed)
        toolbar.addWidget(self.slider_scale)

        toolbar.addWidget(QLabel("|"))

        # Group 4c: Grid toggle + spacing, rule-of-thirds. Text labels
        # render reliably across fonts (some unicode glyphs rendered as
        # tofu boxes on Segoe UI). Compact widths keep them scannable.
        _tw = int(_dt.font_size * 3.2)
        self.chk_grid = QPushButton(" Grid")
        self.chk_grid.setIcon(_StudioIcons.grid())
        self.chk_grid.setIconSize(_ICO_SZ)
        self.chk_grid.setObjectName("studio_grid_toggle")
        self.chk_grid.setToolTip("Show snap grid (G)")
        self.chk_grid.setCheckable(True)
        self.chk_grid.setFixedWidth(int(_dt.font_size * 4.8))
        self.chk_grid.toggled.connect(self._on_grid_toggled)
        toolbar.addWidget(self.chk_grid)

        # Grid-spacing spinbox kept as a hidden widget so existing
        # setValue / valueChanged plumbing still works, but it's no
        # longer added to the toolbar — the Studio Settings dialog
        # owns the grid spacing control (see line 12379).
        self.spin_grid = QSpinBox()
        self.spin_grid.setObjectName("studio_grid_spin")
        self.spin_grid.setRange(5, 500)
        self.spin_grid.setSingleStep(5)
        self.spin_grid.setSuffix(" px")
        self.spin_grid.setToolTip("Grid spacing in pixels")
        self.spin_grid.valueChanged.connect(self._on_grid_spacing_changed)
        self.spin_grid.hide()

        # Toggle buttons use short ASCII labels instead of the obscure
        # unicode glyphs that earlier versions relied on — user reported
        # multiple Windows font setups where the glyphs rendered blank.
        # Short 3-4 char strings are universally visible at any button
        # width + theme combo. Tooltip still carries the full description.
        _tog_w = max(_tw, int(_dt.font_size * 3.6))  # wider for labels

        _tog_w_ico = int(_dt.font_size * 5.2)  # wider to fit icon + label

        self.chk_thirds = QPushButton(" Thirds")
        self.chk_thirds.setIcon(_StudioIcons.thirds())
        self.chk_thirds.setIconSize(_ICO_SZ)
        self.chk_thirds.setObjectName("studio_thirds_toggle")
        self.chk_thirds.setToolTip("Rule-of-thirds (Shift+G)")
        self.chk_thirds.setCheckable(True)
        self.chk_thirds.setFixedWidth(_tog_w_ico)
        self.chk_thirds.toggled.connect(self._on_thirds_toggled)
        toolbar.addWidget(self.chk_thirds)

        # View toggles — checkable QPushButtons with icon + text labels.
        self.chk_rulers = QPushButton(" Rulers")
        self.chk_rulers.setIcon(_StudioIcons.rulers())
        self.chk_rulers.setIconSize(_ICO_SZ)
        self.chk_rulers.setObjectName("studio_rulers_toggle")
        self.chk_rulers.setToolTip("Rulers (Ctrl+R)")
        self.chk_rulers.setCheckable(True)
        self.chk_rulers.setFixedWidth(_tog_w_ico)
        self.chk_rulers.setChecked(True)
        self.chk_rulers.toggled.connect(self._on_rulers_toggled)
        toolbar.addWidget(self.chk_rulers)

        self.chk_notes = QPushButton(" Notes")
        self.chk_notes.setIcon(_StudioIcons.notes())
        self.chk_notes.setIconSize(_ICO_SZ)
        self.chk_notes.setObjectName("studio_notes_toggle")
        self.chk_notes.setToolTip("Notes")
        self.chk_notes.setCheckable(True)
        self.chk_notes.setFixedWidth(_tog_w_ico)
        self.chk_notes.setChecked(True)
        self.chk_notes.toggled.connect(self._on_notes_toggled)
        toolbar.addWidget(self.chk_notes)

        self.chk_base = QPushButton(" Base")
        self.chk_base.setIcon(_StudioIcons.base())
        self.chk_base.setIconSize(_ICO_SZ)
        self.chk_base.setObjectName("studio_base_toggle")
        self.chk_base.setToolTip("Base image")
        self.chk_base.setCheckable(True)
        self.chk_base.setFixedWidth(_tog_w_ico)
        self.chk_base.setChecked(True)
        self.chk_base.toggled.connect(self._on_base_toggled)
        toolbar.addWidget(self.chk_base)

        self.chk_minimap = QPushButton(" Map")
        self.chk_minimap.setIcon(_StudioIcons.minimap())
        self.chk_minimap.setIconSize(_ICO_SZ)
        self.chk_minimap.setObjectName("studio_minimap_toggle")
        self.chk_minimap.setToolTip("Minimap (M)")
        self.chk_minimap.setCheckable(True)
        self.chk_minimap.setFixedWidth(_tog_w_ico)
        self.chk_minimap.toggled.connect(self._on_minimap_toggled)
        toolbar.addWidget(self.chk_minimap)

        # Focus toggle: created here (so _sync_tool_buttons / keyboard
        # shortcuts can still reach it) but NOT added to the top
        # toolbar. It lives in the layer-sidebar footer row (see
        # _layer_sidebar below) so it stays visible in both normal
        # and focus mode — otherwise toggling focus ON would hide the
        # only way to toggle it OFF.
        self.btn_focus = QPushButton(" Focus")
        self.btn_focus.setIcon(_StudioIcons.focus())
        self.btn_focus.setIconSize(_ICO_SZ)
        self.btn_focus.setObjectName("studio_btn_focus")
        self.btn_focus.setToolTip("Hide layer panel + filmstrip for a larger canvas (period to toggle)")
        self.btn_focus.setCheckable(True)
        self.btn_focus.setFixedWidth(_tog_w_ico)
        self.btn_focus.toggled.connect(self._on_focus_toggled)

        self.btn_flip_view = QPushButton(" Flip")
        self.btn_flip_view.setIcon(_StudioIcons.flip())
        self.btn_flip_view.setIconSize(_ICO_SZ)
        self.btn_flip_view.setObjectName("studio_btn_flip_view")
        self.btn_flip_view.setToolTip(
            "Flip canvas preview horizontally (non-destructive composition check)")
        self.btn_flip_view.setCheckable(True)
        self.btn_flip_view.setFixedWidth(_tog_w_ico)
        self.btn_flip_view.toggled.connect(self._on_flip_view_toggled)
        toolbar.addWidget(self.btn_flip_view)

        # Recent-color swatches — click to apply to selected overlays
        toolbar.addWidget(QLabel("|"))
        self._swatch_buttons = []
        for _i in range(self._MAX_RECENT_COLORS):
            sw = QPushButton("")
            sw.setFixedSize(18, 18)
            sw.setObjectName("studio_swatch")
            sw.setEnabled(False)
            sw.clicked.connect(lambda _, b=sw: self._on_swatch_clicked(b))
            # Right-click a swatch for Clear All / Remove This Color
            sw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            sw.customContextMenuRequested.connect(
                lambda pos, b=sw: self._swatch_context_menu(b, pos))
            toolbar.addWidget(sw)
            self._swatch_buttons.append(sw)
        self._refresh_recent_swatches()

        toolbar.addWidget(QLabel("|"))

        # Group 4b: Alignment + distribute (menu dropdown)
        self.btn_align = QPushButton("Align ▾")
        self.btn_align.setObjectName("studio_btn_align")
        self.btn_align.setToolTip(
            "Align or distribute selected items.\n"
            "Align: 2+ items selected.\n"
            "Distribute: 3+ items selected.\n"
            "Works on overlays, censors, crops, and notes.")
        self.btn_align.clicked.connect(self._show_align_menu)
        toolbar.addWidget(self.btn_align)

        toolbar.addWidget(QLabel("|"))

        # Group 5: Export + settings + queue - icon + label.
        self.btn_export = QPushButton(" Export")
        self.btn_export.setIcon(_StudioIcons.export())
        self.btn_export.setIconSize(_ICO_SZ)
        self.btn_export.setObjectName("studio_btn_export")
        self.btn_export.setToolTip("Export preview PNG (Ctrl+Shift+E)")
        self.btn_export.setFixedWidth(_tog_w_ico)
        self.btn_export.clicked.connect(self._export_preview)
        toolbar.addWidget(self.btn_export)

        self.btn_export_plat = QPushButton(" Export Platform")
        self.btn_export_plat.setIcon(_StudioIcons.export())
        self.btn_export_plat.setIconSize(_ICO_SZ)
        self.btn_export_plat.setObjectName("studio_btn_export_plat")
        self.btn_export_plat.setToolTip(
            "Export current platform (crop selected in combo)")
        self.btn_export_plat.clicked.connect(self._export_current_platform)
        toolbar.addWidget(self.btn_export_plat)

        self.btn_export_all = QPushButton(" Export All")
        self.btn_export_all.setIcon(_StudioIcons.export())
        self.btn_export_all.setIconSize(_ICO_SZ)
        self.btn_export_all.setObjectName("studio_btn_export_all")
        self.btn_export_all.setToolTip("Export all platforms (Ctrl+E)")
        self.btn_export_all.clicked.connect(self._export_all_platforms)
        toolbar.addWidget(self.btn_export_all)

        btn_queue = QPushButton(" Queue")
        btn_queue.setIcon(_StudioIcons.queue())
        btn_queue.setIconSize(_ICO_SZ)
        btn_queue.setObjectName("studio_queue_btn")
        btn_queue.setToolTip("Queue this asset for posting")
        btn_queue.clicked.connect(self._queue_current)
        toolbar.addWidget(btn_queue)

        # Settings gear
        btn_settings = QPushButton("")
        btn_settings.setIcon(_StudioIcons.settings())
        btn_settings.setIconSize(_ICO_SZ)
        btn_settings.setObjectName("studio_btn_settings")
        btn_settings.setToolTip("Studio Settings (Ctrl+,)")
        btn_settings.setFixedWidth(_icon_btn_w)
        btn_settings.clicked.connect(self._show_studio_settings)
        toolbar.addWidget(btn_settings)

        toolbar.addStretch()

        # FlowLayout wraps buttons to the next row when the window narrows
        # instead of crushing them. Container keeps the theme background.
        _toolbar_wrap = QWidget()
        _toolbar_wrap.setObjectName("studio_toolbar_wrap")
        _toolbar_wrap.setLayout(toolbar)
        root.addWidget(_toolbar_wrap)

        # ── Quick-props bar ─────────────────────────────────────────────
        # Photoshop "options bar" pattern: the Text Controls popup is too
        # easy to miss, so the most common cross-type knobs (fill color,
        # outline color, rotation, opacity, scale) are duplicated here
        # on the Studio toolbar, always visible, always keyed to the
        # current selection. The popup keeps the text-specific long tail
        # (font, kerning, line height, outline width, named styles).
        quickbar = _FlowLayout(hSpacing=4, vSpacing=3)
        quickbar.addStretch = _noop_stretch

        self._qp_fill = _ColorSwatchButton(is_outline=False)
        self._qp_fill.setObjectName("studio_qp_fill")
        self._qp_fill.setFixedWidth(int(_dt.font_size * 2.8))
        self._qp_fill.setToolTip(
            "Fill / text color (right-click for recent)")
        # Click the swatch itself to open the QColorDialog — previously
        # this routed through _on_color_pick which only handled text
        # overlays, so clicking on a shape's swatch no-op'd.
        self._qp_fill.clicked.connect(self._qp_pick_fill_color)
        self._qp_fill.on_color_picked = self._apply_color_to_selection
        quickbar.addWidget(self._qp_fill)

        self._qp_outline = _ColorSwatchButton(is_outline=True)
        self._qp_outline.setObjectName("studio_qp_outline")
        self._qp_outline.setFixedWidth(int(_dt.font_size * 2.8))
        self._qp_outline.setToolTip(
            "Outline / stroke color (right-click for recent)")
        self._qp_outline.clicked.connect(self._qp_pick_stroke_color)
        self._qp_outline.on_color_picked = self._apply_stroke_to_selection
        quickbar.addWidget(self._qp_outline)

        # Rotation slider (matches Opc - drag for coarse, double-click
        # to reset to 0°, value label shows current degrees).
        quickbar.addWidget(QLabel("Rot"))
        self._qp_rot = QSlider(Qt.Orientation.Horizontal)
        self._qp_rot.setObjectName("studio_qp_rot")
        self._qp_rot.setRange(-360, 360)
        self._qp_rot.setValue(0)
        self._qp_rot.setFixedWidth(int(_dt.font_size * 5))
        self._qp_rot.setToolTip(
            "Rotation of selection (degrees). "
            "Double-click to reset to 0°.")
        self._qp_rot.valueChanged.connect(self._qp_apply_rotation)
        def _rot_dclick(ev):
            self._qp_rot.setValue(0)
        self._qp_rot.mouseDoubleClickEvent = _rot_dclick
        # Right-click for angle presets (0 / ±15 / ±30 / ±45 / 90 /
        # 180 / 270). Quicker than dragging to a common step.
        self._qp_rot.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        def _rot_ctx(pos, _w=self._qp_rot):
            m = _themed_menu(_w)
            for angle in (0, 15, 30, 45, 90, 180, 270, -15, -30, -45):
                act = m.addAction(f"{angle}°")
                act.triggered.connect(
                    lambda _c=False, a=angle: _w.setValue(a))
            m.exec(_w.mapToGlobal(pos))
        self._qp_rot.customContextMenuRequested.connect(_rot_ctx)
        quickbar.addWidget(self._qp_rot)
        self._qp_rot_lbl = QLabel("0°")
        self._qp_rot_lbl.setFixedWidth(int(_dt.font_size * 2.8))
        self._qp_rot.valueChanged.connect(
            lambda v: self._qp_rot_lbl.setText(f"{v}°"))
        quickbar.addWidget(self._qp_rot_lbl)

        quickbar.addWidget(QLabel("Opc"))
        self._qp_opacity = QSlider(Qt.Orientation.Horizontal)
        self._qp_opacity.setObjectName("studio_qp_opacity")
        self._qp_opacity.setRange(0, 100)
        self._qp_opacity.setValue(100)
        self._qp_opacity.setFixedWidth(int(_dt.font_size * 5))
        self._qp_opacity.setToolTip(
            "Opacity of selection (%). Double-click to reset to 100.")
        self._qp_opacity.valueChanged.connect(self._qp_apply_opacity)
        # Double-click to reset to 100%
        _orig_op_mdc = self._qp_opacity.mouseDoubleClickEvent
        def _op_dclick(ev, _orig=_orig_op_mdc):
            self._qp_opacity.setValue(100)
        self._qp_opacity.mouseDoubleClickEvent = _op_dclick
        self._qp_opacity.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        def _op_ctx(pos, _w=self._qp_opacity):
            m = _themed_menu(_w)
            for pct in (0, 10, 25, 50, 75, 90, 100):
                act = m.addAction(f"{pct}%")
                act.triggered.connect(
                    lambda _c=False, p=pct: _w.setValue(p))
            m.exec(_w.mapToGlobal(pos))
        self._qp_opacity.customContextMenuRequested.connect(_op_ctx)
        quickbar.addWidget(self._qp_opacity)
        self._qp_opacity_lbl = QLabel("100")
        self._qp_opacity_lbl.setFixedWidth(int(_dt.font_size * 2.2))
        quickbar.addWidget(self._qp_opacity_lbl)

        # Scale slider (5..1000 %). Coarse drag, double-click -> 100%.
        # Log-ish scale would be nicer but the linear range matches the
        # previous spinbox for undo-history compatibility.
        quickbar.addWidget(QLabel("Scale"))
        self._qp_scale = QSlider(Qt.Orientation.Horizontal)
        self._qp_scale.setObjectName("studio_qp_scale")
        self._qp_scale.setRange(1, 1000)
        self._qp_scale.setValue(100)
        self._qp_scale.setFixedWidth(int(_dt.font_size * 5.2))
        self._qp_scale.setToolTip(
            "Scale selected shape / image (%). "
            "Double-click to reset to 100%.")
        self._qp_scale.valueChanged.connect(self._qp_apply_scale)
        def _scale_dclick(ev):
            self._qp_scale.setValue(100)
        self._qp_scale.mouseDoubleClickEvent = _scale_dclick
        # Right-click for scale presets.
        self._qp_scale.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        def _scale_ctx(pos, _w=self._qp_scale):
            m = _themed_menu(_w)
            for pct in (25, 50, 75, 100, 125, 150, 200, 400, 800):
                act = m.addAction(f"{pct}%")
                act.triggered.connect(
                    lambda _c=False, p=pct: _w.setValue(p))
            m.exec(_w.mapToGlobal(pos))
        self._qp_scale.customContextMenuRequested.connect(_scale_ctx)
        quickbar.addWidget(self._qp_scale)
        self._qp_scale_lbl = QLabel("100%")
        self._qp_scale_lbl.setFixedWidth(int(_dt.font_size * 3.0))
        self._qp_scale.valueChanged.connect(
            lambda v: self._qp_scale_lbl.setText(f"{v}%"))
        quickbar.addWidget(self._qp_scale_lbl)

        # Quick lock / visibility / align-to-pixel buttons. Photoshop-
        # style 'edit' buttons that act on the current selection without
        # needing a popup.
        qp_lock_btn = QPushButton("Lock")
        qp_lock_btn.setObjectName("studio_qp_lock")
        qp_lock_btn.setCheckable(True)
        qp_lock_btn.setToolTip("Lock selected overlay(s) from editing")
        qp_lock_btn.clicked.connect(self._qp_toggle_lock)
        self._qp_lock = qp_lock_btn
        quickbar.addWidget(qp_lock_btn)

        qp_vis_btn = QPushButton("Hide")
        qp_vis_btn.setObjectName("studio_qp_hide")
        qp_vis_btn.setCheckable(True)
        qp_vis_btn.setToolTip("Hide selected overlay(s)")
        qp_vis_btn.clicked.connect(self._qp_toggle_visibility)
        self._qp_hide = qp_vis_btn
        quickbar.addWidget(qp_vis_btn)

        qp_pixel_btn = QPushButton("Px Snap")
        qp_pixel_btn.setObjectName("studio_qp_pixel")
        qp_pixel_btn.setToolTip(
            "Snap selected overlay position to integer pixels")
        qp_pixel_btn.clicked.connect(self._qp_snap_to_pixel)
        quickbar.addWidget(qp_pixel_btn)

        qp_fh_btn = QPushButton("Flip H")
        qp_fh_btn.setObjectName("studio_qp_fliph")
        qp_fh_btn.setToolTip("Flip selected overlay(s) horizontally")
        qp_fh_btn.clicked.connect(lambda: self._qp_flip("h"))
        quickbar.addWidget(qp_fh_btn)

        qp_fv_btn = QPushButton("Flip V")
        qp_fv_btn.setObjectName("studio_qp_flipv")
        qp_fv_btn.setToolTip("Flip selected overlay(s) vertically")
        qp_fv_btn.clicked.connect(lambda: self._qp_flip("v"))
        quickbar.addWidget(qp_fv_btn)

        qp_group_btn = QPushButton("Group")
        qp_group_btn.setObjectName("studio_qp_group")
        qp_group_btn.setToolTip(
            "Group selected overlays (Ctrl+G). Clicking one member "
            "then selects the whole group.")
        qp_group_btn.clicked.connect(self._qp_group_selection)
        quickbar.addWidget(qp_group_btn)

        qp_ungroup_btn = QPushButton("Ungroup")
        qp_ungroup_btn.setObjectName("studio_qp_ungroup")
        qp_ungroup_btn.setToolTip(
            "Ungroup selected overlays (Ctrl+Shift+G)")
        qp_ungroup_btn.clicked.connect(self._qp_ungroup_selection)
        quickbar.addWidget(qp_ungroup_btn)

        qp_fit_btn = QPushButton("Fit Sel")
        qp_fit_btn.setObjectName("studio_qp_fit")
        qp_fit_btn.setToolTip("Fit view to current selection (Shift+F)")
        qp_fit_btn.clicked.connect(self._qp_fit_selection)
        quickbar.addWidget(qp_fit_btn)

        qp_sel_all_btn = QPushButton("Sel All")
        qp_sel_all_btn.setObjectName("studio_qp_sel_all")
        qp_sel_all_btn.setToolTip("Select every overlay / censor (Ctrl+A)")
        def _qp_sel_all():
            for it in self._scene.items():
                if isinstance(it, _CANVAS_ITEM_TYPES):
                    it.setSelected(True)
        qp_sel_all_btn.clicked.connect(_qp_sel_all)
        quickbar.addWidget(qp_sel_all_btn)

        qp_deselect_btn = QPushButton("Deselect")
        qp_deselect_btn.setObjectName("studio_qp_deselect")
        qp_deselect_btn.setToolTip("Clear selection (Ctrl+Shift+A / Esc)")
        qp_deselect_btn.clicked.connect(
            lambda: self._scene.clearSelection())
        quickbar.addWidget(qp_deselect_btn)

        # Copy / Paste Style buttons mirror Ctrl+Alt+C / Ctrl+Alt+V.
        qp_copy_style = QPushButton("Copy Style")
        qp_copy_style.setObjectName("studio_qp_copy_style")
        qp_copy_style.setToolTip("Copy overlay style (Ctrl+Alt+C)")
        def _qp_copy_style():
            sel = self._scene.selectedItems()
            if sel and hasattr(sel[0], "overlay"):
                self._copy_style(sel[0].overlay)
        qp_copy_style.clicked.connect(_qp_copy_style)
        quickbar.addWidget(qp_copy_style)

        qp_paste_style = QPushButton("Paste Style")
        qp_paste_style.setObjectName("studio_qp_paste_style")
        qp_paste_style.setToolTip("Paste overlay style (Ctrl+Alt+V)")
        def _qp_paste_style():
            touched = False
            for it in self._scene.selectedItems():
                if hasattr(it, "overlay"):
                    self._paste_style(it.overlay, it)
                    touched = True
            if touched:
                self._sync_overlays_to_asset()
        qp_paste_style.clicked.connect(_qp_paste_style)
        quickbar.addWidget(qp_paste_style)

        # Arrange dropdown - quick z-order jumps without reaching
        # for the Ctrl+[ / Ctrl+] bindings.
        qp_arrange_btn = QPushButton("Arrange ▾")
        qp_arrange_btn.setObjectName("studio_qp_arrange")
        qp_arrange_btn.setToolTip("Z-order actions for the selection")
        def _show_arrange_menu():
            m = _themed_menu(qp_arrange_btn)
            a_front = m.addAction("Bring to Front  (Ctrl+Shift+])")
            a_forward = m.addAction("Bring Forward  (Ctrl+])")
            a_backward = m.addAction("Send Backward  (Ctrl+[)")
            a_back = m.addAction("Send to Back  (Ctrl+Shift+[)")
            chosen = m.exec(qp_arrange_btn.mapToGlobal(
                qp_arrange_btn.rect().bottomLeft()))
            if chosen is a_front:
                self._z_shift_selected(+999)
            elif chosen is a_forward:
                self._z_shift_selected(+1)
            elif chosen is a_backward:
                self._z_shift_selected(-1)
            elif chosen is a_back:
                self._z_shift_selected(-999)
        qp_arrange_btn.clicked.connect(_show_arrange_menu)
        quickbar.addWidget(qp_arrange_btn)

        self._qp_label = QLabel("(no selection)")
        self._qp_label.setObjectName("studio_qp_label")
        quickbar.addWidget(self._qp_label)

        quickbar.addStretch()
        # Quick Actions bar: single-row horizontal strip. The chevron
        # title 'Quick Actions ▼' sits inline on the left of the same
        # row as the controls - saves the dedicated header row that
        # doubled the bar's height. Clicking the chevron collapses the
        # body (controls) to just the title, flipping to '▶'.
        self._quickbar_wrap = QWidget()
        self._quickbar_wrap.setObjectName("studio_quickbar_wrap")
        _qb_h = QHBoxLayout(self._quickbar_wrap)
        _qb_h.setContentsMargins(4, 0, 4, 0)
        _qb_h.setSpacing(4)
        self._qb_chevron = QPushButton("Quick Actions ▼")
        self._qb_chevron.setObjectName("studio_quickbar_chevron")
        self._qb_chevron.setFlat(True)
        self._qb_chevron.setToolTip(
            "Collapse / expand the Quick Actions controls "
            "(Studio Settings > View to hide entirely).")
        _qb_h.addWidget(self._qb_chevron)
        # Divider between title and body for visual anchoring.
        _qb_sep = QLabel("|")
        _qb_sep.setObjectName("studio_quickbar_sep")
        _qb_h.addWidget(_qb_sep)
        self._qb_body = QWidget()
        self._qb_body.setObjectName("studio_quickbar_body")
        self._qb_body.setLayout(quickbar)
        _qb_h.addWidget(self._qb_body, 1)

        # Restore collapsed state + whole-bar visibility from settings.
        # Default to COLLAPSED so the bar doesn't eat a row of vertical
        # real-estate on first run - the user can expand on demand.
        _qs = QSettings("DoxyEdit", "DoxyEdit")
        _qb_vis = _qs.value(
            "studio_quickbar_visible", True, type=bool)
        self._quickbar_wrap.setVisible(_qb_vis)
        _qb_collapsed = _qs.value(
            "studio_quickbar_collapsed", True, type=bool)
        self._qb_body.setVisible(not _qb_collapsed)
        _qb_sep.setVisible(not _qb_collapsed)
        self._qb_chevron.setText(
            "Quick Actions ▶" if _qb_collapsed else "Quick Actions ▼")
        def _toggle_qb():
            collapsed = self._qb_body.isVisible()
            self._qb_body.setVisible(not collapsed)
            _qb_sep.setVisible(not collapsed)
            self._qb_chevron.setText(
                "Quick Actions ▶" if collapsed
                else "Quick Actions ▼")
            QSettings("DoxyEdit", "DoxyEdit").setValue(
                "studio_quickbar_collapsed", collapsed)
        self._qb_chevron.clicked.connect(_toggle_qb)
        root.addWidget(self._quickbar_wrap)

        # Row 2: Overlay properties (historical — its controls now live
        # in _text_controls_dlg). Kept parented to self so it can never
        # appear as a top-level orphan window; setVisible(True) at worst
        # draws at 0,0 inside the editor with no layout, which is
        # invisible because of the widget stack above it.
        self._props_row = QWidget(self)
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
        # 1-400. Was 8-200 - 8px floor was rejected as a 'hard minimum'
        # by users who legitimately want tiny captions or extreme blow-ups.
        self.slider_font_size.setRange(1, 400)
        self.slider_font_size.setValue(24)
        self.slider_font_size.setFixedWidth(_slider_sm)
        self.slider_font_size.valueChanged.connect(self._on_font_size_changed)
        props.addWidget(self.slider_font_size)
        self._font_size_label = QLabel("24")
        props.addWidget(self._font_size_label)

        # Weight / decoration buttons use painted QIcon glyphs instead
        # of raw text — the old "B"/"I"/"U"/"S" letters disappeared on
        # themes with thin UI fonts and on Windows installs missing
        # the underline/strike composite glyphs.
        self.btn_bold = QPushButton()
        self.btn_bold.setObjectName("studio_bold_btn")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setFixedWidth(_icon_btn_w)
        self.btn_bold.setIcon(_StudioIcons.text_bold())
        self.btn_bold.setToolTip("Bold (Ctrl+B)")
        self.btn_bold.clicked.connect(self._on_bold_changed)
        props.addWidget(self.btn_bold)

        self.btn_italic = QPushButton()
        self.btn_italic.setObjectName("studio_italic_btn")
        self.btn_italic.setCheckable(True)
        self.btn_italic.setFixedWidth(_icon_btn_w)
        self.btn_italic.setIcon(_StudioIcons.text_italic())
        self.btn_italic.setToolTip("Italic (Ctrl+I)")
        self.btn_italic.clicked.connect(self._on_italic_changed)
        props.addWidget(self.btn_italic)

        # Underline / strikethrough — CanvasOverlay already has the
        # fields, just needs surfaced buttons so users don't have to
        # right-click every time.
        self.btn_underline = QPushButton()
        self.btn_underline.setObjectName("studio_underline_btn")
        self.btn_underline.setCheckable(True)
        self.btn_underline.setFixedWidth(_icon_btn_w)
        self.btn_underline.setIcon(_StudioIcons.text_underline())
        self.btn_underline.setToolTip("Underline (Ctrl+U)")
        self.btn_underline.clicked.connect(self._on_underline_changed)
        props.addWidget(self.btn_underline)

        self.btn_strikethrough = QPushButton()
        self.btn_strikethrough.setObjectName("studio_strike_btn")
        self.btn_strikethrough.setCheckable(True)
        self.btn_strikethrough.setFixedWidth(_icon_btn_w)
        self.btn_strikethrough.setIcon(_StudioIcons.text_strike())
        self.btn_strikethrough.setToolTip("Strikethrough")
        self.btn_strikethrough.clicked.connect(self._on_strikethrough_changed)
        props.addWidget(self.btn_strikethrough)

        # Text alignment: left / center / right buttons as exclusive
        # radio-like toggles. Painted icons for the same reason as the
        # weight buttons — the ≡ / ≣ unicode chars rendered blank on
        # several system fonts.
        self.btn_align_left = QPushButton()
        self.btn_align_left.setObjectName("studio_align_left_btn")
        self.btn_align_left.setToolTip("Align text left (Ctrl+Shift+L)")
        self.btn_align_left.setCheckable(True)
        self.btn_align_left.setFixedWidth(_icon_btn_w)
        self.btn_align_left.setIcon(_StudioIcons.align_left())
        self.btn_align_left.clicked.connect(
            lambda: self._on_text_align_changed("left"))
        props.addWidget(self.btn_align_left)

        self.btn_align_center = QPushButton()
        self.btn_align_center.setObjectName("studio_align_center_btn")
        self.btn_align_center.setToolTip("Align text center (Ctrl+Shift+E)")
        self.btn_align_center.setCheckable(True)
        self.btn_align_center.setFixedWidth(_icon_btn_w)
        self.btn_align_center.setIcon(_StudioIcons.align_center())
        self.btn_align_center.clicked.connect(
            lambda: self._on_text_align_changed("center"))
        props.addWidget(self.btn_align_center)

        self.btn_align_right = QPushButton()
        self.btn_align_right.setObjectName("studio_align_right_btn")
        self.btn_align_right.setToolTip("Align text right (Ctrl+Shift+R)")
        self.btn_align_right.setCheckable(True)
        self.btn_align_right.setFixedWidth(_icon_btn_w)
        self.btn_align_right.setIcon(_StudioIcons.align_right())
        self.btn_align_right.clicked.connect(
            lambda: self._on_text_align_changed("right"))
        props.addWidget(self.btn_align_right)

        self.btn_color = _ColorSwatchButton(is_outline=False)
        self.btn_color.setObjectName("studio_color_btn")
        self.btn_color.setFixedWidth(_icon_btn_w)
        self.btn_color.setToolTip("Fill color (right-click for recent)")
        self.btn_color.clicked.connect(self._on_color_pick)
        self.btn_color.on_color_picked = self._apply_text_color
        props.addWidget(self.btn_color)

        self.btn_outline_color = _ColorSwatchButton(is_outline=True)
        self.btn_outline_color.setObjectName("studio_outline_btn")
        self.btn_outline_color.setFixedWidth(_icon_btn_w)
        self.btn_outline_color.setToolTip(
            "Outline color (right-click for recent)")
        self.btn_outline_color.clicked.connect(self._on_outline_color_pick)
        self.btn_outline_color.on_color_picked = self._apply_outline_color
        props.addWidget(self.btn_outline_color)

        props.addWidget(QLabel("OL:"))
        self.slider_outline = QSlider(Qt.Orientation.Horizontal)
        self.slider_outline.setObjectName("studio_outline_slider")
        self.slider_outline.setRange(0, 10)
        self.slider_outline.setValue(0)
        self.slider_outline.setFixedWidth(_slider_sm)
        self.slider_outline.setToolTip(
            "Outline width. Double-click to reset to 0.")
        self.slider_outline.valueChanged.connect(self._on_outline_changed)
        def _ol_dclick(ev):
            self.slider_outline.setValue(0)
        self.slider_outline.mouseDoubleClickEvent = _ol_dclick
        props.addWidget(self.slider_outline)

        props.addWidget(QLabel("|"))

        props.addWidget(QLabel("Kern:"))
        self.slider_kerning = QSlider(Qt.Orientation.Horizontal)
        self.slider_kerning.setObjectName("studio_kerning_slider")
        self.slider_kerning.setRange(-20, 20)
        self.slider_kerning.setValue(0)
        self.slider_kerning.setFixedWidth(_slider_sm)
        self.slider_kerning.setToolTip(
            "Letter spacing. Double-click to reset to 0.")
        self.slider_kerning.valueChanged.connect(self._on_kerning_changed)
        def _kern_dclick(ev):
            self.slider_kerning.setValue(0)
        self.slider_kerning.mouseDoubleClickEvent = _kern_dclick
        props.addWidget(self.slider_kerning)

        props.addWidget(QLabel("LH:"))
        self.slider_line_height = QSlider(Qt.Orientation.Horizontal)
        self.slider_line_height.setObjectName("studio_line_height_slider")
        self.slider_line_height.setRange(50, 500)  # 0.5x to 5.0x (stored as int * 100)
        self.slider_line_height.setValue(120)       # default 1.2
        self.slider_line_height.setFixedWidth(_slider_sm)
        self.slider_line_height.setToolTip(
            "Line height (1.0 = tight, 1.5 = loose, 2.0 = double). "
            "Double-click to reset to 1.2.")
        self.slider_line_height.valueChanged.connect(self._on_line_height_changed)
        def _lh_dclick(ev):
            self.slider_line_height.setValue(120)
        self.slider_line_height.mouseDoubleClickEvent = _lh_dclick
        props.addWidget(self.slider_line_height)

        props.addWidget(QLabel("Rot:"))
        self.slider_rotation = QSlider(Qt.Orientation.Horizontal)
        self.slider_rotation.setObjectName("studio_rotation_slider")
        self.slider_rotation.setRange(-180, 180)
        self.slider_rotation.setValue(0)
        self.slider_rotation.setFixedWidth(_slider_sm)
        self.slider_rotation.setToolTip(
            "Rotation (-180° to 180°). Double-click to reset to 0°.")
        self.slider_rotation.valueChanged.connect(self._on_rotation_changed)
        def _rot_s_dclick(ev):
            self.slider_rotation.setValue(0)
        self.slider_rotation.mouseDoubleClickEvent = _rot_s_dclick
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

        props.addStretch()
        # Always visible but disabled when no overlay selected (prevents layout shift)
        self._props_row.setEnabled(False)
        # Float the text-property sliders in their own non-modal popup so
        # they only show up when a text overlay (or the text tool) is
        # active. Prevents the permanent second-row clutter. The popup is
        # moveable (Qt.WindowType.Tool window flag) and does not interrupt drag/drawing.
        # Re-shape _props_row's QHBoxLayout into a tall QFormLayout inside
        # the dialog so it reads as a column of labeled rows, not a wide
        # ribbon.
        # Use the _TextControlsDialog subclass for proper closeEvent /
        # hideEvent / moveEvent / resizeEvent handling — the previous
        # instance-level `dlg.closeEvent = fn` pattern didn't actually
        # override Qt's virtual method, so the geometry never persisted.
        self._text_controls_dlg = _TextControlsDialog(self)
        self._text_controls_dlg.setWindowTitle("Text Controls")
        self._text_controls_dlg.setObjectName("studio_text_controls_dlg")
        self._text_controls_dlg.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint)
        _qs_geom = QSettings("DoxyEdit", "DoxyEdit")
        # Explicit reparent each control to the dialog BEFORE adding it to
        # the QFormLayout. Without this, widgets inherit their original
        # _props_row parent's hidden state, leaving the dialog blank.
        _dlg = self._text_controls_dlg
        # combo_position stays in the main props_row — user wants the
        # "Position [custom (drag)]" control in the main toolbar, not
        # buried inside the Text Controls popup.
        for _w in (self.font_combo, self.slider_font_size,
                   self.btn_bold, self.btn_italic,
                   self.btn_underline, self.btn_strikethrough,
                   self.btn_align_left, self.btn_align_center, self.btn_align_right,
                   self.btn_color, self.btn_outline_color,
                   self.slider_outline, self.slider_kerning,
                   self.slider_line_height, self.slider_rotation,
                   self.slider_text_width,
                   # The font size readout label - reparenting just the
                   # slider left the "24" label orphaned in props_row,
                   # which is why text controls appeared to have no
                   # numeric readout for font size.
                   self._font_size_label):
            _w.setParent(_dlg)
            _w.show()
        # Font combo forced to not exceed the form's field column so it
        # doesn't stretch the whole dialog when a long family name appears.
        self.font_combo.setMaximumWidth(220)
        self.font_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed)
        # Bold / Italic buttons need larger hit area + explicit typeface
        # to survive theme restyling. Inline font overrides defeat the
        # case where QSS renders text in the same shade as the fill.
        # Size the weight/align/color buttons as square cells so the
        # painted icons render crisp. Clear any leftover text labels
        # (older builds set "B"/"I" here) — icons only now.
        # All three ratios + minima are named so a future theme pass
        # can rescale the dialog consistently from one place.
        TEXT_CTRL_BUTTON_WIDTH_RATIO = 2.8   # button size relative to font
        TEXT_CTRL_BUTTON_WIDTH_MIN = 32      # readable at any font size
        TEXT_CTRL_ICON_RATIO = 0.6           # icon glyph vs button cell
        TEXT_CTRL_ICON_MIN = 14              # minimum glyph legibility
        text_ctrl_button_width = max(
            TEXT_CTRL_BUTTON_WIDTH_MIN,
            int(_dt.font_size * TEXT_CTRL_BUTTON_WIDTH_RATIO))
        text_ctrl_icon_px = max(
            TEXT_CTRL_ICON_MIN,
            int(text_ctrl_button_width * TEXT_CTRL_ICON_RATIO))
        for _b in (self.btn_bold, self.btn_italic,
                   self.btn_underline, self.btn_strikethrough,
                   self.btn_align_left, self.btn_align_center,
                   self.btn_align_right):
            _b.setText("")
            _b.setMinimumWidth(text_ctrl_button_width)
            _b.setFixedWidth(text_ctrl_button_width)
            _b.setIconSize(QSize(text_ctrl_icon_px, text_ctrl_icon_px))
        # Color swatch buttons get a bigger hit area + the glyphs are
        # drawn on paintEvent so theme stylesheets can't hide them.
        _sw = max(32, int(_dt.font_size * 2.8))
        for _b in (self.btn_color, self.btn_outline_color):
            _b.setMinimumWidth(_sw)
            _b.setFixedWidth(_sw)
        _dlg_layout = QFormLayout(_dlg)
        _dlg_layout.setContentsMargins(_pad_lg, _pad_lg, _pad_lg, _pad_lg)
        # Separate horizontal (label↔field) and vertical (row↔row) spacing
        # so the sliders get enough vertical breathing room instead of
        # stacking right on top of each other.
        _dlg_layout.setHorizontalSpacing(_pad_lg)
        _dlg_layout.setVerticalSpacing(max(8, _pad_lg))
        _dlg_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        _dlg_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        _dlg_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        # Text content editor at the top — live-edits the selected
        # text overlay's .text without needing to enter scene-edit
        # mode. Multiline so speech-bubble text with line breaks works.
        self._tc_content_edit = QPlainTextEdit(_dlg)
        self._tc_content_edit.setObjectName("studio_tc_content")
        self._tc_content_edit.setPlaceholderText(
            "Text content (edits selected text overlay)")
        # Min height ~4 rows so the field opens at a reasonable size,
        # but expanding policy lets the user drag the dialog taller and
        # the field grows with it (instead of staying squashed at 4 rows).
        self._tc_content_edit.setMinimumHeight(int(_dt.font_size * 4.4))
        self._tc_content_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._tc_content_edit.textChanged.connect(self._on_tc_content_changed)
        _dlg_layout.addRow("Text", self._tc_content_edit)
        # Character / word / line count on its own form row so it can
        # never collide with the text editor above — the prior layout
        # wrapped both in a QVBoxLayout whose wrapper height was
        # clamped by the form row, letting the label paint on top of
        # the edit's bottom border.
        self._tc_count_label = QLabel("0 chars  /  0 words", _dlg)
        self._tc_count_label.setObjectName("studio_tc_count")
        _dlg_layout.addRow("", self._tc_count_label)
        self._tc_content_edit.textChanged.connect(self._update_tc_count)
        _dlg_layout.addRow("Font", self.font_combo)
        # Font size row: single wide slider, no presets. The slider's fixed
        # width from the top-of-Studio props bar is cleared so it can grow
        # to fill the dialog row.
        self.slider_font_size.setMinimumWidth(0)
        self.slider_font_size.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX
        self.slider_font_size.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _dlg_layout.addRow("Size", self.slider_font_size)
        _bi_widget = QWidget(_dlg)
        _bi_row = QHBoxLayout(_bi_widget)
        _bi_row.setContentsMargins(0, 0, 0, 0)
        _bi_row.addWidget(self.btn_bold)
        _bi_row.addWidget(self.btn_italic)
        _bi_row.addWidget(self.btn_underline)
        _bi_row.addWidget(self.btn_strikethrough)
        _bi_row.addStretch()
        _dlg_layout.addRow("Weight", _bi_widget)

        _al_widget = QWidget(_dlg)
        _al_row = QHBoxLayout(_al_widget)
        _al_row.setContentsMargins(0, 0, 0, 0)
        _al_row.addWidget(self.btn_align_left)
        _al_row.addWidget(self.btn_align_center)
        _al_row.addWidget(self.btn_align_right)
        _al_row.addStretch()
        _dlg_layout.addRow("Align", _al_widget)

        # Case transform row: UPPER / lower / Title. Rewrites the
        # content of every selected text overlay's .text field.
        _case_row = QHBoxLayout()
        _case_row.setContentsMargins(0, 0, 0, 0)
        def _case_transform(fn, label):
            sel = [it for it in self._scene.selectedItems()
                   if isinstance(it, OverlayTextItem)]
            if not sel:
                self.info_label.setText(
                    "Select a text overlay first")
                return
            for it in sel:
                new_text = fn(it.overlay.text or "")
                if new_text != it.overlay.text:
                    it.overlay.text = new_text
                    it.setPlainText(new_text)
                    if hasattr(it, "_apply_font"):
                        it._apply_font()
            # Also refresh the mini text editor.
            if hasattr(self, "_tc_content_edit") and sel:
                self._tc_content_syncing = True
                try:
                    self._tc_content_edit.setPlainText(sel[0].overlay.text or "")
                finally:
                    self._tc_content_syncing = False
            self._sync_overlays_to_asset()
            self.info_label.setText(f"{label} applied")
        _btn_upper = QPushButton("UPPER")
        _btn_upper.setToolTip("Transform selected text to UPPERCASE")
        _btn_upper.clicked.connect(lambda: _case_transform(str.upper, "UPPER"))
        _case_row.addWidget(_btn_upper)
        _btn_lower = QPushButton("lower")
        _btn_lower.setToolTip("Transform selected text to lowercase")
        _btn_lower.clicked.connect(lambda: _case_transform(str.lower, "lower"))
        _case_row.addWidget(_btn_lower)
        _btn_title = QPushButton("Title")
        _btn_title.setToolTip("Transform selected text to Title Case")
        _btn_title.clicked.connect(lambda: _case_transform(str.title, "Title"))
        _case_row.addWidget(_btn_title)
        _case_row.addStretch()
        _case_w = QWidget(_dlg)
        _case_w.setLayout(_case_row)
        _dlg_layout.addRow("Case", _case_w)
        _col_widget = QWidget(_dlg)
        _col_row = QHBoxLayout(_col_widget)
        _col_row.setContentsMargins(0, 0, 0, 0)
        _col_row.addWidget(self.btn_color)
        _col_row.addWidget(self.btn_outline_color)
        _col_row.addStretch()
        _dlg_layout.addRow("Colors", _col_widget)
        # Horizontal divider helper, used to group the slider stack and the
        # shadow row as distinct visual sections.
        def _hdivider():
            line = QFrame(_dlg)
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Plain)
            line.setObjectName("card_divider")
            return line
        _dlg_layout.addRow("", _hdivider())
        # Outline row: slider + Clear button
        _ol_row = QHBoxLayout()
        _ol_row.setContentsMargins(0, 0, 0, 0)
        _ol_row.addWidget(self.slider_outline, 1)
        _ol_clear_btn = QPushButton("Clr")
        _ol_clear_btn.setFixedWidth(36)
        _ol_clear_btn.setToolTip("Clear text outline (stroke color + width)")
        def _clear_outline():
            sel = [it for it in self._scene.selectedItems()
                   if isinstance(it, OverlayTextItem)]
            if not sel:
                return
            for it in sel:
                it.overlay.stroke_color = ""
                it.overlay.stroke_width = 0
                if hasattr(it, "_apply_font"):
                    it._apply_font()
                it.update()
            if hasattr(self, "slider_outline"):
                self.slider_outline.blockSignals(True)
                self.slider_outline.setValue(0)
                self.slider_outline.blockSignals(False)
            self._sync_overlays_to_asset()
            self.info_label.setText("Text outline cleared")
        _ol_clear_btn.clicked.connect(_clear_outline)
        _ol_row.addWidget(_ol_clear_btn)
        _ol_w = QWidget(_dlg)
        _ol_w.setLayout(_ol_row)
        _dlg_layout.addRow("Outline", _ol_w)
        # These sliders were frozen to the narrow width from the top-of-
        # Studio props bar. Clear the fixed width + expand policy so they
        # fill the dialog row (same as the Font Size slider above).
        for _sl in (self.slider_outline, self.slider_kerning,
                    self.slider_line_height, self.slider_rotation,
                    self.slider_text_width):
            _sl.setMinimumWidth(0)
            _sl.setMaximumWidth(16777215)
            _sl.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _dlg_layout.addRow("Kerning", self.slider_kerning)
        _dlg_layout.addRow("Line Height", self.slider_line_height)
        _dlg_layout.addRow("Rotation", self.slider_rotation)
        _dlg_layout.addRow("Width", self.slider_text_width)
        _dlg_layout.addRow("", _hdivider())
        # Shadow toggles - persist through the overlay's shadow_color/
        # shadow_offset/shadow_blur fields so they round-trip on save.
        # Two-row layout: top row = toggle + color + reset; bottom row =
        # offset + blur sliders labelled so their purpose is obvious.
        _shadow_container = QVBoxLayout()
        _shadow_container.setContentsMargins(0, 0, 0, 0)
        _shadow_container.setSpacing(4)
        _shadow_row = QHBoxLayout()
        _shadow_row.setContentsMargins(0, 0, 0, 0)
        self.btn_shadow_toggle = QPushButton("Drop Shadow")
        self.btn_shadow_toggle.setCheckable(True)
        self.btn_shadow_toggle.setObjectName("studio_btn_shadow_toggle")
        self.btn_shadow_toggle.toggled.connect(self._on_shadow_toggled)
        _shadow_row.addWidget(self.btn_shadow_toggle)
        _shadow_row.addStretch(1)
        self.slider_shadow_offset = QSlider(Qt.Orientation.Horizontal)
        self.slider_shadow_offset.setObjectName("studio_shadow_offset")
        self.slider_shadow_offset.setRange(0, 15)
        self.slider_shadow_offset.setValue(0)
        self.slider_shadow_offset.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.slider_shadow_offset.setToolTip("Shadow offset (both x/y) in px")
        self.slider_shadow_offset.valueChanged.connect(self._on_shadow_offset_changed)
        # Blur slider for the drop shadow
        self.slider_shadow_blur = QSlider(Qt.Orientation.Horizontal)
        self.slider_shadow_blur.setObjectName("studio_shadow_blur")
        self.slider_shadow_blur.setRange(0, 15)
        self.slider_shadow_blur.setValue(0)
        self.slider_shadow_blur.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.slider_shadow_blur.setToolTip("Shadow blur radius in px")
        self.slider_shadow_blur.valueChanged.connect(self._on_shadow_blur_changed)
        # Color swatch for the shadow itself
        self.btn_shadow_color = _ColorSwatchButton(is_outline=False)
        self.btn_shadow_color.setObjectName("studio_shadow_color_btn")
        self.btn_shadow_color.setFixedWidth(30)
        self.btn_shadow_color.setToolTip("Shadow color")
        self.btn_shadow_color.setSwatchColor("#000000")
        self.btn_shadow_color.clicked.connect(self._pick_shadow_color)
        self.btn_shadow_color.on_color_picked = self._apply_shadow_color
        _shadow_row.addWidget(self.btn_shadow_color)
        # Reset button — clears shadow_color / offset / blur together.
        _shadow_reset_btn = QPushButton("Clr")
        _shadow_reset_btn.setFixedWidth(36)
        _shadow_reset_btn.setToolTip("Clear shadow (color / offset / blur)")
        def _clear_shadow():
            sel = [it for it in self._scene.selectedItems()
                   if isinstance(it, OverlayTextItem)]
            if not sel:
                return
            for it in sel:
                it.overlay.shadow_color = ""
                it.overlay.shadow_offset = 0
                it.overlay.shadow_blur = 0
                if hasattr(it, "_apply_font"):
                    it._apply_font()
                it.update()
            # Sync UI
            if hasattr(self, "btn_shadow_toggle"):
                self.btn_shadow_toggle.blockSignals(True)
                self.btn_shadow_toggle.setChecked(False)
                self.btn_shadow_toggle.blockSignals(False)
            if hasattr(self, "slider_shadow_offset"):
                self.slider_shadow_offset.blockSignals(True)
                self.slider_shadow_offset.setValue(0)
                self.slider_shadow_offset.blockSignals(False)
            if hasattr(self, "slider_shadow_blur"):
                self.slider_shadow_blur.blockSignals(True)
                self.slider_shadow_blur.setValue(0)
                self.slider_shadow_blur.blockSignals(False)
            self._sync_overlays_to_asset()
            self.info_label.setText("Shadow cleared")
        _shadow_reset_btn.clicked.connect(_clear_shadow)
        _shadow_row.addWidget(_shadow_reset_btn)
        # Second row: the two sliders with mini labels so the user can
        # tell offset from blur at a glance.
        _shadow_sliders_row = QHBoxLayout()
        _shadow_sliders_row.setContentsMargins(0, 0, 0, 0)
        _shadow_sliders_row.setSpacing(4)
        _offset_lbl = QLabel("Off")
        _offset_lbl.setObjectName("studio_mini_label")
        _shadow_sliders_row.addWidget(_offset_lbl)
        _shadow_sliders_row.addWidget(self.slider_shadow_offset, 1)
        _blur_lbl = QLabel("Blur")
        _blur_lbl.setObjectName("studio_mini_label")
        _shadow_sliders_row.addWidget(_blur_lbl)
        _shadow_sliders_row.addWidget(self.slider_shadow_blur, 1)
        _shadow_container.addLayout(_shadow_row)
        _shadow_container.addLayout(_shadow_sliders_row)
        _shadow_widget = QWidget(_dlg)
        _shadow_widget.setLayout(_shadow_container)
        _dlg_layout.addRow("Shadow", _shadow_widget)
        # Named text styles: combo + Save / Apply / Delete. Replaces the
        # generic 'Save Template' button (that moved to the overlay
        # context menu where it belongs). Styles persist via QSettings.
        self.combo_text_style = QComboBox(_dlg)
        self.combo_text_style.setObjectName("studio_text_style_combo")
        self.combo_text_style.setMinimumWidth(120)
        self.btn_style_save = QPushButton("Save", _dlg)
        self.btn_style_save.setObjectName("studio_text_style_save")
        self.btn_style_save.setToolTip("Save current text styling as a named style")
        self.btn_style_save.clicked.connect(self._save_named_text_style)
        self.btn_style_apply = QPushButton("Apply", _dlg)
        self.btn_style_apply.setObjectName("studio_text_style_apply")
        self.btn_style_apply.setToolTip("Apply selected style to the current text")
        self.btn_style_apply.clicked.connect(self._apply_named_text_style)
        self.btn_style_delete = QPushButton("Delete", _dlg)
        self.btn_style_delete.setObjectName("studio_text_style_delete")
        self.btn_style_delete.setToolTip("Delete the selected style")
        self.btn_style_delete.clicked.connect(self._delete_named_text_style)
        _style_widget = QWidget(_dlg)
        _style_row = QHBoxLayout(_style_widget)
        _style_row.setContentsMargins(0, 0, 0, 0)
        _style_row.setSpacing(3)
        _style_row.addWidget(self.combo_text_style, 1)
        _style_row.addWidget(self.btn_style_save)
        _style_row.addWidget(self.btn_style_apply)
        _style_row.addWidget(self.btn_style_delete)
        _dlg_layout.addRow("Style", _style_widget)
        self._populate_text_styles_combo()

        # Reset kerning / line-height / rotation to defaults quickly.
        _rk_row = QHBoxLayout()
        _rk_row.setContentsMargins(0, 0, 0, 0)
        _reset_spacing_btn = QPushButton("Reset Spacing (kern / line-h)")
        _reset_spacing_btn.setToolTip(
            "Zero letter_spacing + reset line_height to 1.2 on selected "
            "text overlays.")
        def _reset_spacing():
            sel = [it for it in self._scene.selectedItems()
                   if isinstance(it, OverlayTextItem)]
            if not sel:
                return
            for it in sel:
                it.overlay.letter_spacing = 0.0
                it.overlay.line_height = 1.2
                if hasattr(it, "_apply_font"):
                    it._apply_font()
                it.update()
            if hasattr(self, "slider_kerning"):
                self.slider_kerning.blockSignals(True)
                self.slider_kerning.setValue(0)
                self.slider_kerning.blockSignals(False)
            if hasattr(self, "slider_line_height"):
                self.slider_line_height.blockSignals(True)
                self.slider_line_height.setValue(120)
                self.slider_line_height.blockSignals(False)
            self._sync_overlays_to_asset()
            self.info_label.setText("Text spacing reset")
        _reset_spacing_btn.clicked.connect(_reset_spacing)
        _rk_row.addWidget(_reset_spacing_btn)

        _reset_all_btn = QPushButton("Reset All Style")
        _reset_all_btn.setToolTip(
            "Clears shadow + outline + spacing + rotation + bold / "
            "italic / underline / strike on selected text overlays.")
        def _reset_all_style():
            sel = [it for it in self._scene.selectedItems()
                   if isinstance(it, OverlayTextItem)]
            if not sel:
                return
            for it in sel:
                ov_r = it.overlay
                ov_r.bold = False
                ov_r.italic = False
                ov_r.underline = False
                ov_r.strikethrough = False
                ov_r.letter_spacing = 0.0
                ov_r.line_height = 1.2
                ov_r.stroke_color = ""
                ov_r.stroke_width = 0
                ov_r.shadow_color = ""
                ov_r.shadow_offset = 0
                ov_r.shadow_blur = 0
                ov_r.rotation = 0.0
                if hasattr(it, "_apply_font"):
                    it._apply_font()
                it.update()
            # Re-sync every relevant control back to zero / defaults
            for name, val in (
                    ("btn_bold", False), ("btn_italic", False),
                    ("btn_underline", False), ("btn_strikethrough", False),
                    ("btn_shadow_toggle", False)):
                if hasattr(self, name):
                    w = getattr(self, name)
                    w.blockSignals(True)
                    w.setChecked(val)
                    w.blockSignals(False)
            for name, val in (
                    ("slider_outline", 0), ("slider_kerning", 0),
                    ("slider_line_height", 120), ("slider_rotation", 0),
                    ("slider_shadow_offset", 0), ("slider_shadow_blur", 0)):
                if hasattr(self, name):
                    w = getattr(self, name)
                    w.blockSignals(True)
                    w.setValue(val)
                    w.blockSignals(False)
            self._sync_overlays_to_asset()
            self.info_label.setText(f"Reset style on {len(sel)} text(s)")
        _reset_all_btn.clicked.connect(_reset_all_style)
        _rk_row.addWidget(_reset_all_btn)
        _rk_row.addStretch()
        _rk_w = QWidget(_dlg)
        _rk_w.setLayout(_rk_row)
        _dlg_layout.addRow("", _rk_w)

        # Save-current-as-default button for text. Persists the first
        # selected text overlay's style fields into
        # studio_text_defaults so new text overlays inherit them.
        _td_row = QHBoxLayout()
        _td_row.setContentsMargins(0, 0, 0, 0)
        _save_def_btn = QPushButton("Save as Default")
        _save_def_btn.setObjectName("studio_save_text_default_btn")
        _save_def_btn.setToolTip(
            "Persist the selected text overlay's style as the "
            "default for new text overlays.")
        def _save_text_default():
            sel = [it for it in self._scene.selectedItems()
                   if isinstance(it, OverlayTextItem)]
            if not sel:
                if self.info_label is not None:
                    self.info_label.setText(
                        "Select a text overlay to save as default")
                return
            self._save_text_style_as_default(sel[0].overlay)
        _save_def_btn.clicked.connect(_save_text_default)
        _td_row.addWidget(_save_def_btn)

        # Apply the saved default to the current selection.
        _apply_def_btn = QPushButton("Apply Default")
        _apply_def_btn.setObjectName("studio_apply_text_default_btn")
        _apply_def_btn.setToolTip(
            "Apply the saved default text style to every "
            "selected text overlay.")
        def _apply_text_default():
            defaults = self._load_text_style_defaults()
            if not defaults:
                self.info_label.setText("No default text style saved yet")
                return
            sel = [it for it in self._scene.selectedItems()
                   if isinstance(it, OverlayTextItem)]
            if not sel:
                self.info_label.setText("Select text overlays to apply to")
                return
            for it in sel:
                for k, v in defaults.items():
                    if k == "text_width":
                        continue
                    setattr(it.overlay, k, v)
                if hasattr(it, "_apply_font"):
                    it._apply_font()
                it.update()
            self._sync_overlays_to_asset()
            self.info_label.setText(
                f"Applied default to {len(sel)} text overlay(s)")
        _apply_def_btn.clicked.connect(_apply_text_default)
        _td_row.addWidget(_apply_def_btn)

        _td_row.addStretch()
        _td_w = QWidget(_dlg)
        _td_w.setLayout(_td_row)
        _dlg_layout.addRow("", _td_w)
        # Keep the popup shrinkable to a corner tile (prior floor was
        # 360x420 which forced users to dismiss it entirely when they
        # needed canvas space) but bump the floor high enough that the
        # Qt.Tool title bar's "Text Controls" caption always fits
        # alongside the close button. Derived from font_size so the
        # floor scales with theme.font_size instead of pinning to a
        # hardcoded pixel count.
        TEXT_CTRL_MIN_WIDTH_RATIO = 18.5     # caption + close fit at ~font_size*18
        TEXT_CTRL_MIN_WIDTH_FLOOR = 260      # readable at very small font sizes
        TEXT_CTRL_MIN_HEIGHT_RATIO = 7.0     # a handful of rows at the set font
        TEXT_CTRL_MIN_HEIGHT_FLOOR = 100
        _dlg.setMinimumWidth(max(
            TEXT_CTRL_MIN_WIDTH_FLOOR,
            int(_dt.font_size * TEXT_CTRL_MIN_WIDTH_RATIO)))
        _dlg.setMinimumHeight(max(
            TEXT_CTRL_MIN_HEIGHT_FLOOR,
            int(_dt.font_size * TEXT_CTRL_MIN_HEIGHT_RATIO)))
        _geom_blob = _qs_geom.value("studio_text_controls_geom", None)
        if _geom_blob:
            try:
                _dlg.restoreGeometry(_geom_blob)
                # Self-heal: if the restored geometry is degenerate (saved
                # while the dialog was malformed in a prior session), drop
                # it and use the dialog's natural size instead. Otherwise
                # the dialog opens invisibly and the user has no recourse.
                _g = _dlg.geometry()
                if _g.width() < 200 or _g.height() < 200:
                    _qs_geom.remove("studio_text_controls_geom")
                    _dlg.resize(_dlg.sizeHint())
                    _dlg._positioned_once = False
            except Exception:
                _qs_geom.remove("studio_text_controls_geom")
        # _props_row keeps a hidden shell so setEnabled call sites stay valid.
        self._props_row.hide()

        # Shape / Arrow properties popup — partners with Text Controls
        # for bubbles (both popups show when a speech/thought bubble is
        # selected so the user can tweak text + shape side-by-side).
        self._shape_controls_dlg = _ShapeControlsDialog(self)
        _geom_blob = _qs_geom.value(
            _ShapeControlsDialog._GEOM_KEY, None)
        if _geom_blob:
            try:
                self._shape_controls_dlg.restoreGeometry(_geom_blob)
                _g = self._shape_controls_dlg.geometry()
                if _g.width() < 200 or _g.height() < 200:
                    _qs_geom.remove(_ShapeControlsDialog._GEOM_KEY)
                    self._shape_controls_dlg.resize(
                        self._shape_controls_dlg.sizeHint())
                    self._shape_controls_dlg._positioned_once = False
            except Exception:
                _qs_geom.remove(_ShapeControlsDialog._GEOM_KEY)

        # Scene + View
        self._scene = StudioScene()
        self._scene.on_censor_finished = self._on_censor_drawn
        self._scene.on_arrow_finished = self._on_arrow_drawn
        self._scene.on_shape_finished = self._on_shape_drawn
        self._scene.on_crop_finished = self._on_crop_drawn
        self._scene.on_note_finished = self._on_note_drawn
        self._scene.on_text_overlay_placed = self._on_text_placed
        self._scene.get_crop_aspect = self._get_crop_aspect
        # Propagate the restored censor style preference to the scene
        self._scene.set_censor_style(self.combo_censor_style.currentText())
        self._view = StudioView(self._scene)
        self._view._studio_editor = self
        self._view.on_file_dropped = self._on_file_dropped

        # F10 = cycling testbed
        self._f10_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F10), self)
        self._f10_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._f10_shortcut.activated.connect(self._nuclear_clear)

        # Shift+F = toggle FPS HUD for diagnosing canvas perf.
        self._fps_hud_shortcut = QShortcut(QKeySequence("Shift+F"), self)
        self._fps_hud_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._fps_hud_shortcut.activated.connect(
            lambda: self._view.toggle_fps_hud())

        # Shift+S = open the Skia-backend preview window (Day 14).
        # Side-by-side preview of the same scene rendered via the
        # skia-python compositor. Lets the user see the work-in-progress
        # without any risk to the main QGraphicsView path.
        self._skia_preview_shortcut = QShortcut(
            QKeySequence("Shift+S"), self)
        self._skia_preview_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._skia_preview_shortcut.activated.connect(
            self._open_skia_preview)

        # Escape = universal 'deselect + exit tool' regardless of which
        # studio widget has focus (sidebar button, slider, layer panel).
        # Scoped with WidgetWithChildrenShortcut so it does NOT interfere
        # with Escape-cancel on QInputDialog / QColorDialog popups, which
        # own their own focus scope.
        self._esc_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._esc_shortcut.activated.connect(self._handle_escape_shortcut)

        # Snap grid overlay — flag on the scene, drawn via foreground.
        # Both spacing and visibility are user prefs persisted via QSettings.
        _qs = QSettings("DoxyEdit", "DoxyEdit")
        _gs = _qs.value("studio_grid_spacing", STUDIO_GRID_SPACING, type=int)
        _gv = _qs.value("studio_grid_visible", False, type=bool)
        _tv = _qs.value("studio_thirds_visible", False, type=bool)
        self._grid_visible = _gv
        self._grid_spacing = _gs
        self._scene._grid_visible = _gv
        self._scene._grid_spacing = _gs
        self._scene._thirds_visible = _tv
        # Sync the toolbar widgets to the restored values (block signals so
        # restoration doesn't re-write the same values back to QSettings)
        self.spin_grid.blockSignals(True)
        self.spin_grid.setValue(_gs)
        self.spin_grid.blockSignals(False)
        self.chk_grid.blockSignals(True)
        self.chk_grid.setChecked(_gv)
        self.chk_grid.blockSignals(False)
        self.chk_thirds.blockSignals(True)
        self.chk_thirds.setChecked(_tv)
        self.chk_thirds.blockSignals(False)
        _rv = _qs.value("studio_rulers_visible", True, type=bool)
        self.chk_rulers.blockSignals(True)
        self.chk_rulers.setChecked(_rv)
        self.chk_rulers.blockSignals(False)
        if self._canvas_wrap is not None:
            self._canvas_wrap._h_ruler.setVisible(_rv)
            self._canvas_wrap._v_ruler.setVisible(_rv)
            self._canvas_wrap._corner.setVisible(_rv)
        _mv = _qs.value("studio_minimap_visible", False, type=bool)
        self.chk_minimap.blockSignals(True)
        self.chk_minimap.setChecked(_mv)
        self.chk_minimap.blockSignals(False)
        if self._canvas_wrap is not None and _mv:
            self._canvas_wrap.set_minimap_visible(True)
        _nv = _qs.value("studio_notes_visible", True, type=bool)
        self.chk_notes.blockSignals(True)
        self.chk_notes.setChecked(_nv)
        self.chk_notes.blockSignals(False)

        # Layer panel (right sidebar, collapsible). No maximum width so
        # the user can drag the splitter to any size — including full
        # window width — without the panel refusing past ~200px.
        self._layer_panel = QListWidget()
        self._layer_panel.setObjectName("studio_layer_panel")
        # Match canvas - multi-select on stage should highlight all
        # corresponding rows. Default SingleSelection clipped that to one.
        self._layer_panel.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)
        self._layer_panel.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        # Accept external drops (from tray) to add files as overlays
        self._layer_panel.setAcceptDrops(True)
        _orig_layer_drag_enter = self._layer_panel.dragEnterEvent
        _orig_layer_drag_move = self._layer_panel.dragMoveEvent
        _orig_layer_drop = self._layer_panel.dropEvent

        def _layer_drag_enter(event, _orig=_orig_layer_drag_enter):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return
            _orig(event)

        def _layer_drag_move(event, _orig=_orig_layer_drag_move):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return
            _orig(event)

        def _layer_drop(event, _orig=_orig_layer_drop):
            mime = event.mimeData()
            if mime.hasUrls() and self._asset is not None:
                # Add each dropped image file as an overlay centered on canvas
                added = False
                for url in mime.urls():
                    if not url.isLocalFile():
                        continue
                    path = url.toLocalFile()
                    ext = Path(path).suffix.lower()
                    if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
                        continue
                    cx = self._scene.sceneRect().center().x()
                    cy = self._scene.sceneRect().center().y()
                    ov = CanvasOverlay(
                        type="watermark", label=Path(path).stem,
                        image_path=path, position="custom",
                        x=int(cx), y=int(cy),
                        opacity=self.slider_opacity.value() / 100.0,
                        scale=self.slider_scale.value() / 100.0,
                    )
                    self._add_overlay_image(ov)
                    added = True
                if added:
                    self._sync_overlays_to_asset()
                    self._rebuild_layer_panel()
                event.acceptProposedAction()
                return
            _orig(event)

        self._layer_panel.dragEnterEvent = _layer_drag_enter
        self._layer_panel.dragMoveEvent = _layer_drag_move
        self._layer_panel.dropEvent = _layer_drop
        # Show thumbnails alongside each layer name. Size is a user
        # pref (studio_layer_thumb_size: small=16, medium=28, large=48).
        _thumb_sz = QSettings("DoxyEdit", "DoxyEdit").value(
            "studio_layer_thumb_size", 28, type=int)
        _thumb_sz = max(12, min(64, _thumb_sz))
        self._layer_panel.setIconSize(QSize(_thumb_sz, _thumb_sz))
        # Click-on-thumbnail toggles visibility (like Photoshop's eye column).
        # Middle-click anywhere on a row ALSO toggles visibility for users
        # who prefer a mouse-button shortcut over the pixel-precise icon
        # column.
        _orig_layer_press = self._layer_panel.mousePressEvent
        def _layer_mouse_press(event, _orig=_orig_layer_press):
            def _toggle_vis_for(data):
                if not data:
                    return False
                kind, idx = data
                if kind == "overlay" and 0 <= idx < len(self._asset.overlays):
                    ov = self._asset.overlays[idx]
                    ov.enabled = not ov.enabled
                    for scene_it in self._scene.items():
                        if (hasattr(scene_it, "overlay")
                                and scene_it.overlay is ov):
                            scene_it.setVisible(ov.enabled)
                            break
                    self._rebuild_layer_panel()
                    return True
                if kind == "censor" and 0 <= idx < len(self._censor_items):
                    item = self._censor_items[idx]
                    item.setVisible(not item.isVisible())
                    return True
                return False
            if event.button() == Qt.MouseButton.MiddleButton:
                it = self._layer_panel.itemAt(event.pos())
                if it is not None and _toggle_vis_for(
                        it.data(Qt.ItemDataRole.UserRole)):
                    return
            if event.button() == Qt.MouseButton.LeftButton:
                it = self._layer_panel.itemAt(event.pos())
                if it is not None:
                    # Row rect to locate the icon zone (first 28+padding px)
                    rect = self._layer_panel.visualItemRect(it)
                    if event.pos().x() - rect.x() <= 34:  # icon area
                        if _toggle_vis_for(it.data(Qt.ItemDataRole.UserRole)):
                            return
            _orig(event)
        self._layer_panel.mousePressEvent = _layer_mouse_press
        self._layer_panel.itemClicked.connect(self._on_layer_clicked)
        self._layer_panel.itemDoubleClicked.connect(self._on_layer_double_clicked)
        # Arrow-key navigation in the layer panel syncs the scene
        # selection so users can ride the keyboard through overlays
        # and always see what they're about to modify.
        self._layer_panel.currentItemChanged.connect(
            lambda cur, _prev: cur and self._on_layer_clicked(cur))
        self._layer_panel.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._layer_panel.customContextMenuRequested.connect(self._on_layer_context_menu)
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
        # Inline Enabled + Locked checkboxes on the same row as the
        # Opacity slider to save vertical space in the sidebar. Shorter
        # "Locked" label (drop "non-selectable") so it fits alongside
        # the slider; the tooltip keeps the full explanation.
        _op_row.addWidget(self.slider_layer_opacity, 1)
        self.chk_layer_enabled = QCheckBox("On")
        self.chk_layer_enabled.setObjectName("studio_layer_enabled_chk")
        self.chk_layer_enabled.setToolTip("Enabled — uncheck to hide this layer")
        self.chk_layer_enabled.toggled.connect(self._on_layer_enabled_toggled)
        _op_row.addWidget(self.chk_layer_enabled)
        self.chk_layer_locked = QCheckBox("Lock")
        self.chk_layer_locked.setObjectName("studio_layer_locked_chk")
        self.chk_layer_locked.setToolTip(
            "Locked (non-selectable): can't be moved, resized, or selected "
            "in the canvas. Useful for background watermarks you want to "
            "protect.")
        self.chk_layer_locked.toggled.connect(self._on_layer_locked_toggled)
        _op_row.addWidget(self.chk_layer_locked)
        _props_layout.addLayout(_op_row)

        # Position X / Y / Rot share a 3-column layout:
        #   [ fixed-width label | stretchy slider | fixed-width spinbox ]
        # so all three rows visually align — the user's "draw x,y,rot
        # consistently with columns and proper spacing" ask.
        _label_col_w = int(_dt.font_size * 2.8)
        _spin_col_w = int(_dt.font_size * 6.2)
        _px_row = QHBoxLayout()
        _px_row.setContentsMargins(0, 0, 0, 0)
        _px_row.setSpacing(max(4, _pad))
        _px_lbl = QLabel("X")
        _px_lbl.setFixedWidth(_label_col_w)
        _px_row.addWidget(_px_lbl)
        self.slider_pos_x = QSlider(Qt.Orientation.Horizontal)
        self.slider_pos_x.setObjectName("studio_pos_x_slider")
        self.slider_pos_x.setRange(-10000, 10000)
        _px_row.addWidget(self.slider_pos_x, 1)
        self.spin_pos_x = QSpinBox()
        self.spin_pos_x.setObjectName("studio_pos_x_spin")
        self.spin_pos_x.setRange(-50000, 50000)
        self.spin_pos_x.setSuffix(" px")
        self.spin_pos_x.setFixedWidth(_spin_col_w)
        _px_row.addWidget(self.spin_pos_x)
        def _x_slider_changed(v):
            if self.spin_pos_x.value() != v:
                self.spin_pos_x.blockSignals(True)
                self.spin_pos_x.setValue(v)
                self.spin_pos_x.blockSignals(False)
            self._on_pos_field_changed('x', v)
        def _x_spin_changed(v):
            if self.slider_pos_x.value() != v:
                self.slider_pos_x.blockSignals(True)
                self.slider_pos_x.setValue(max(-10000, min(10000, v)))
                self.slider_pos_x.blockSignals(False)
            self._on_pos_field_changed('x', v)
        self.slider_pos_x.valueChanged.connect(_x_slider_changed)
        self.spin_pos_x.valueChanged.connect(_x_spin_changed)
        _props_layout.addLayout(_px_row)

        _py_row = QHBoxLayout()
        _py_row.setContentsMargins(0, 0, 0, 0)
        _py_row.setSpacing(max(4, _pad))
        _py_lbl = QLabel("Y")
        _py_lbl.setFixedWidth(_label_col_w)
        _py_row.addWidget(_py_lbl)
        self.slider_pos_y = QSlider(Qt.Orientation.Horizontal)
        self.slider_pos_y.setObjectName("studio_pos_y_slider")
        self.slider_pos_y.setRange(-10000, 10000)
        _py_row.addWidget(self.slider_pos_y, 1)
        self.spin_pos_y = QSpinBox()
        self.spin_pos_y.setObjectName("studio_pos_y_spin")
        self.spin_pos_y.setRange(-50000, 50000)
        self.spin_pos_y.setSuffix(" px")
        self.spin_pos_y.setFixedWidth(_spin_col_w)
        _py_row.addWidget(self.spin_pos_y)
        def _y_slider_changed(v):
            if self.spin_pos_y.value() != v:
                self.spin_pos_y.blockSignals(True)
                self.spin_pos_y.setValue(v)
                self.spin_pos_y.blockSignals(False)
            self._on_pos_field_changed('y', v)
        def _y_spin_changed(v):
            if self.slider_pos_y.value() != v:
                self.slider_pos_y.blockSignals(True)
                self.slider_pos_y.setValue(max(-10000, min(10000, v)))
                self.slider_pos_y.blockSignals(False)
            self._on_pos_field_changed('y', v)
        self.slider_pos_y.valueChanged.connect(_y_slider_changed)
        self.spin_pos_y.valueChanged.connect(_y_spin_changed)
        _props_layout.addLayout(_py_row)

        # Rotation: slider (-360..360) + spinbox with same range. Uses
        # the same label-col / spin-col widths as X and Y so the three
        # rows align.
        _rot_row = QHBoxLayout()
        _rot_row.setContentsMargins(0, 0, 0, 0)
        _rot_row.setSpacing(max(4, _pad))
        _rot_lbl = QLabel("Rot")
        _rot_lbl.setFixedWidth(_label_col_w)
        _rot_row.addWidget(_rot_lbl)
        self.slider_rotation_layer = QSlider(Qt.Orientation.Horizontal)
        self.slider_rotation_layer.setObjectName(
            "studio_rotation_layer_slider")
        self.slider_rotation_layer.setRange(-360, 360)
        _rot_row.addWidget(self.slider_rotation_layer, 1)
        self.spin_rotation_layer = QSpinBox()
        self.spin_rotation_layer.setObjectName("studio_rotation_layer_spin")
        self.spin_rotation_layer.setRange(-360, 360)
        self.spin_rotation_layer.setSuffix("°")
        self.spin_rotation_layer.setFixedWidth(_spin_col_w)
        _rot_row.addWidget(self.spin_rotation_layer)
        def _rot_slider_changed(v):
            if self.spin_rotation_layer.value() != v:
                self.spin_rotation_layer.blockSignals(True)
                self.spin_rotation_layer.setValue(v)
                self.spin_rotation_layer.blockSignals(False)
            self._on_layer_rotation_changed(v)
        def _rot_spin_changed(v):
            if self.slider_rotation_layer.value() != v:
                self.slider_rotation_layer.blockSignals(True)
                self.slider_rotation_layer.setValue(v)
                self.slider_rotation_layer.blockSignals(False)
            self._on_layer_rotation_changed(v)
        self.slider_rotation_layer.valueChanged.connect(_rot_slider_changed)
        self.spin_rotation_layer.valueChanged.connect(_rot_spin_changed)
        _props_layout.addLayout(_rot_row)
        # Trailing stretch: keeps rows pinned to the top instead of letting
        # QVBoxLayout inflate the gaps when the panel is tall (e.g., Focus
        # mode leaves only this panel visible in the sidebar).
        _props_layout.addStretch(1)
        _layer_props.setEnabled(False)
        self._layer_props_widget = _layer_props

        # Layer search box — filters visible rows by label substring
        self._layer_filter = QLineEdit()
        self._layer_filter.setObjectName("studio_layer_filter")
        self._layer_filter.setPlaceholderText("Filter layers...")
        self._layer_filter.textChanged.connect(self._on_layer_filter_changed)
        _layer_list_wrap = QWidget()
        _layer_list_layout = QVBoxLayout(_layer_list_wrap)
        _layer_list_layout.setContentsMargins(0, 0, 0, 0)
        _layer_list_layout.setSpacing(2)
        _layer_list_layout.addWidget(self._layer_filter)
        _layer_list_layout.addWidget(self._layer_panel, 1)

        # Vertical splitter so the layer list and props share the sidebar
        _layer_side = QSplitter(Qt.Orientation.Vertical)
        _layer_side.addWidget(_layer_list_wrap)
        _layer_side.addWidget(_layer_props)
        _layer_side.setStretchFactor(0, 1)
        _layer_side.setStretchFactor(1, 0)

        # Sidebar container: splitter on top, always-visible footer bar
        # at the bottom. The footer hosts the Focus toggle button so
        # users can flip focus mode back off even when the splitter
        # contents (layer list + props) are hidden.
        _layer_sidebar = QWidget()
        _layer_sidebar.setObjectName("studio_layer_sidebar")
        _sidebar_layout = QVBoxLayout(_layer_sidebar)
        _sidebar_layout.setContentsMargins(0, 0, 0, 0)
        _sidebar_layout.setSpacing(2)
        _sidebar_layout.addWidget(_layer_side, 1)
        self._layer_sidebar_body = _layer_side
        _footer = QWidget()
        _footer.setObjectName("studio_layer_footer")
        _footer_layout = QHBoxLayout(_footer)
        _footer_layout.setContentsMargins(_pad, _pad, _pad, _pad)
        _footer_layout.setSpacing(_pad)
        _footer_layout.addWidget(self.btn_focus)
        _footer_layout.addStretch(1)
        _sidebar_layout.addWidget(_footer)

        self._canvas_split = QSplitter(Qt.Orientation.Horizontal)
        self._canvas_split.setObjectName("studio_canvas_split")
        self._canvas_wrap = _StudioCanvas(self._view, self._theme)
        self._canvas_split.addWidget(self._canvas_wrap)
        self._canvas_split.addWidget(_layer_sidebar)
        # Restore the user's splitter sizes from the last session
        _split_state = QSettings("DoxyEdit", "DoxyEdit").value(
            "studio_canvas_split_state", None)
        if _split_state is not None:
            self._canvas_split.restoreState(_split_state)
        else:
            self._canvas_split.setSizes([800, 200])
        self._canvas_split.setStretchFactor(0, 1)
        self._canvas_split.setStretchFactor(1, 0)
        self._canvas_split.splitterMoved.connect(self._persist_canvas_split)
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
                def _do_fit():
                    self._view.fitInView(self._scene.sceneRect(),
                                          Qt.AspectRatioMode.KeepAspectRatio)
                    self._zoom_label.setText("Fit")
                    if self._canvas_wrap is not None:
                        self._canvas_wrap.refresh()
                btn.clicked.connect(_do_fit)
            else:
                btn.clicked.connect(lambda _, f=factor: self._set_zoom(f))
            status_bar.addWidget(btn)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setObjectName("studio_zoom_label")
        self._zoom_label.setFixedWidth(int(_dt.font_size * ZOOM_LABEL_WIDTH_RATIO))
        self._zoom_label.setToolTip(
            "Click to enter a zoom percentage (or use Ctrl+0 / Ctrl+1)")
        self._zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_label.mousePressEvent = self._prompt_zoom_level
        # Right-click the zoom label for a preset grid — 25 / 50 /
        # 75 / 100 / 150 / 200 / 400 / 800, plus 'Fit' and 'Fit Width'.
        def _zoom_menu(m):
            act_fit = m.addAction("Fit View")
            act_fw = m.addAction("Fit Width")
            m.addSeparator()
            for pct in (25, 50, 75, 100, 150, 200, 400, 800):
                act = m.addAction(f"{pct}%")
                act.triggered.connect(
                    lambda _c=False, p=pct: self._set_zoom(p / 100.0))
            act_fit.triggered.connect(
                lambda: self._view.fitInView(
                    self._scene.sceneRect(),
                    Qt.AspectRatioMode.KeepAspectRatio))
            def _fw():
                sr = self._scene.sceneRect()
                vw = max(1, self._view.viewport().width())
                if sr.width() > 0:
                    f = vw / sr.width()
                    self._view.resetTransform()
                    self._view.scale(f, f)
                    self._zoom_label.setText(f"{int(f * 100)}%")
            act_fw.triggered.connect(_fw)
        _attach_ctx_menu(self._zoom_label, _zoom_menu)
        status_bar.addWidget(self._zoom_label)

        status_bar.addWidget(QLabel("|"))

        # Cursor position + selection count — graphics-editor staples
        self._tool_label = QLabel("Select")
        self._tool_label.setObjectName("studio_tool_label")
        self._tool_label.setToolTip(
            "Active Studio tool (right-click to switch)")
        self._tool_label.setFixedWidth(int(_dt.font_size * 9))
        self._tool_label.setCursor(Qt.CursorShape.PointingHandCursor)
        # Right-click the tool name in the status bar to switch tools
        # without reaching for the toolbar or remembering the shortcut.
        def _tool_menu(m):
            tools_list = [
                ("Select (Q / V)", StudioTool.SELECT),
                ("Text (T)", StudioTool.TEXT_OVERLAY),
                ("Shape (rect)", StudioTool.SHAPE_RECT),
                ("Shape (ellipse)", StudioTool.SHAPE_ELLIPSE),
                ("Arrow (A)", StudioTool.ARROW),
                ("Censor (X)", StudioTool.CENSOR),
                ("Crop (C)", StudioTool.CROP),
                ("Watermark (E)", StudioTool.WATERMARK),
                ("Note (N)", StudioTool.NOTE),
                ("Eyedropper (I)", StudioTool.EYEDROPPER),
            ]
            for label_s, tool in tools_list:
                act = m.addAction(label_s)
                act.triggered.connect(
                    lambda _c=False, t=tool: self._set_tool(t))
        _attach_ctx_menu(self._tool_label, _tool_menu)
        status_bar.addWidget(self._tool_label)

        self._cursor_label = QLabel("0, 0")
        self._cursor_label.setObjectName("studio_cursor_label")
        self._cursor_label.setToolTip(
            "Cursor position in image pixels + color under cursor. "
            "Left-click to center view on a coordinate; right-click "
            "to copy the current position to clipboard.")
        self._cursor_label.setFixedWidth(int(_dt.font_size * 14))
        self._cursor_label.setCursor(Qt.CursorShape.PointingHandCursor)
        # Left-click opens a Go-To dialog so the user can center on a
        # specific scene coordinate. Right-click copies the current
        # cursor coord (whatever's shown) to clipboard.
        def _cursor_press(ev):
            if ev.button() == Qt.MouseButton.LeftButton:
                self._prompt_goto_coord()
        self._cursor_label.mousePressEvent = _cursor_press
        def _cursor_menu(m):
            def _copy():
                txt = self._cursor_label.text()
                QApplication.clipboard().setText(txt)
                self.info_label.setText(f"Copied: {txt}")
            m.addAction("Copy coordinate to clipboard").triggered.connect(_copy)
            m.addAction("Go to coordinate...").triggered.connect(
                self._prompt_goto_coord)
        _attach_ctx_menu(self._cursor_label, _cursor_menu)
        status_bar.addWidget(self._cursor_label)

        self._selection_label = QLabel("0 selected")
        self._selection_label.setObjectName("studio_selection_label")
        self._selection_label.setToolTip(
            "Number of selected items (right-click for selection "
            "actions)")
        self._selection_label.setCursor(Qt.CursorShape.PointingHandCursor)
        # Right-click for quick selection actions.
        def _sel_menu(m):
            def _all():
                for it in self._scene.items():
                    if isinstance(it, _SELECTABLE_ITEM_TYPES):
                        it.setSelected(True)
            def _inv():
                for it in self._scene.items():
                    if isinstance(it, _SELECTABLE_ITEM_TYPES):
                        it.setSelected(not it.isSelected())
            m.addAction("Select All  (Ctrl+A)").triggered.connect(_all)
            m.addAction("Deselect All  (Ctrl+Shift+A)").triggered.connect(
                self._scene.clearSelection)
            m.addAction("Invert Selection  (Ctrl+Shift+I)").triggered.connect(_inv)
        _attach_ctx_menu(self._selection_label, _sel_menu)
        status_bar.addWidget(self._selection_label)

        self._geom_label = QLabel("")
        self._geom_label.setObjectName("studio_geom_label")
        self._geom_label.setToolTip("Selected item geometry: x, y | w x h")
        status_bar.addWidget(self._geom_label)

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
        if self._canvas_wrap is not None:
            self._canvas_wrap.set_theme(theme)

    def _preview_guide(self, orientation: str, pos: float):
        """Show (or move) a pending-guide line while the user drags from the ruler."""
        if not self._pixmap_item:
            return
        if not hasattr(self, "_pending_guide"):
            self._pending_guide = None
        pixmap_rect = self._pixmap_item.boundingRect()
        if self._pending_guide is None:
            line = _GuideLineItem()
            line._guide_orientation = orientation
            line._editor = self
            # Cursor hint while hovering a placed guide
            line.setCursor(Qt.CursorShape.SizeVerCursor if orientation == 'h'
                            else Qt.CursorShape.SizeHorCursor)
            pen = QPen(QColor(self._theme.accent), 1, Qt.PenStyle.DashLine)
            line.setPen(pen)
            line.setZValue(400)
            self._scene.addItem(line)
            self._pending_guide = (orientation, line)
        orient, line = self._pending_guide
        if orientation != orient:
            return
        if orientation == 'h':
            line.setLine(pixmap_rect.left(), pos, pixmap_rect.right(), pos)
            self.info_label.setText(f"Guide Y = {int(pos)}")
        else:
            line.setLine(pos, pixmap_rect.top(), pos, pixmap_rect.bottom())
            self.info_label.setText(f"Guide X = {int(pos)}")

    def _add_guide_at_cursor(self, orientation: str):
        """Drop a new guide of the given orientation at the current scene-
        space cursor position. Bound to Shift+H (horizontal) and Shift+V
        (vertical) for rapid guide placement without dragging the ruler."""
        if not self._pixmap_item:
            return
        last = self._last_cursor_scene_pos
        if last is None:
            pm = self._pixmap_item.pixmap()
            pos = pm.height() / 2 if orientation == 'h' else pm.width() / 2
        else:
            pos = last.y() if orientation == 'h' else last.x()
        rect = self._pixmap_item.boundingRect()
        line = _GuideLineItem()
        line._guide_orientation = orientation
        line._editor = self
        line.setCursor(Qt.CursorShape.SizeVerCursor if orientation == 'h'
                       else Qt.CursorShape.SizeHorCursor)
        line.setPen(QPen(QColor(self._theme.accent), 1, Qt.PenStyle.DashLine))
        line.setZValue(400)
        if orientation == 'h':
            line.setLine(rect.left(), pos, rect.right(), pos)
        else:
            line.setLine(pos, rect.top(), pos, rect.bottom())
        line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self._scene.addItem(line)
        # _guide_items initialized to [] in __init__; direct append.
        self._guide_items.append(line)
        self._save_guides_to_asset()
        if self._canvas_wrap is not None:
            self._canvas_wrap.refresh()
        self.info_label.setText(
            f"Added {'horizontal' if orientation == 'h' else 'vertical'} guide")

    def _commit_preview_guide(self):
        """Drop the pending guide onto the scene permanently (or remove it if
        dragged back off the canvas)."""
        if self._pending_guide is None:
            return
        orient, line = self._pending_guide
        self._pending_guide = None
        # If the committed guide is outside the canvas, discard it
        if self._pixmap_item:
            rect = self._pixmap_item.boundingRect()
            if orient == 'h':
                y = line.line().y1()
                if not (rect.top() <= y <= rect.bottom()):
                    self._scene.removeItem(line)
                    if self._canvas_wrap is not None:
                        self._canvas_wrap.refresh()
                    return
            else:
                x = line.line().x1()
                if not (rect.left() <= x <= rect.right()):
                    self._scene.removeItem(line)
                    if self._canvas_wrap is not None:
                        self._canvas_wrap.refresh()
                    return
        # Track it so load_asset can clean up next time —
        # _guide_items initialized to [] in __init__.
        self._guide_items.append(line)
        # Persist onto the asset so guides survive save/load
        self._save_guides_to_asset()
        # Refresh rulers so the tick marker appears
        if self._canvas_wrap is not None:
            self._canvas_wrap.refresh()

    def _save_guides_to_asset(self):
        """Serialize current guides to asset.guides for persistence."""
        if not self._asset:
            return
        serialized = []
        for gl in self._guide_items:
            if gl.scene() is None:
                continue
            orient = getattr(gl, "_guide_orientation", 'h')
            off = gl.pos()
            line = gl.line()
            pos = (line.y1() + off.y()) if orient == 'h' else (line.x1() + off.x())
            serialized.append({"orientation": orient, "position": int(pos)})
        self._asset.guides = serialized

    def _load_saved_guides(self):
        """Recreate guide lines from asset.guides on project load."""
        if not self._asset or not self._pixmap_item:
            return
        guides = getattr(self._asset, "guides", [])
        if not guides:
            return
        pixmap_rect = self._pixmap_item.boundingRect()
        for entry in guides:
            orient = entry.get("orientation", "h")
            pos = entry.get("position", 0)
            line = _GuideLineItem()
            line._guide_orientation = orient
            line._editor = self
            line.setCursor(Qt.CursorShape.SizeVerCursor if orient == 'h'
                            else Qt.CursorShape.SizeHorCursor)
            pen = QPen(QColor(self._theme.accent), 1, Qt.PenStyle.DashLine)
            line.setPen(pen)
            line.setZValue(400)
            if orient == 'h':
                line.setLine(pixmap_rect.left(), pos,
                              pixmap_rect.right(), pos)
            else:
                line.setLine(pos, pixmap_rect.top(),
                              pos, pixmap_rect.bottom())
            self._scene.addItem(line)
            self._guide_items.append(line)

    def _apply_guide_preset(self, preset: str):
        """Drop a curated pattern of guides over the canvas. `preset`:
          'cross' -> one H + one V through the image center
          'thirds' -> rule-of-thirds (2 H + 2 V at 1/3 and 2/3)
          'golden' -> golden ratio verticals + horizontals (0.382 and 0.618)
          'quarters' -> 3 H + 3 V evenly spaced
          'diagonal' -> two diagonal guides corner to corner (drawn
              as long line overlays since guides are axis-aligned)
          'safe' -> 5% inset rectangle (4 guides)
        """
        if not self._pixmap_item:
            return
        rect = self._pixmap_item.boundingRect()
        w = rect.width()
        h = rect.height()
        def _place(orient, pos):
            line = _GuideLineItem()
            line._guide_orientation = orient
            line._editor = self
            line.setCursor(Qt.CursorShape.SizeVerCursor if orient == 'h'
                           else Qt.CursorShape.SizeHorCursor)
            line.setPen(QPen(QColor(self._theme.accent), 1,
                              Qt.PenStyle.DashLine))
            line.setZValue(400)
            if orient == 'h':
                line.setLine(rect.left(), pos, rect.right(), pos)
            else:
                line.setLine(pos, rect.top(), pos, rect.bottom())
            line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
            self._scene.addItem(line)
            # _guide_items initialized to [] in __init__.
            self._guide_items.append(line)
        if preset == "cross":
            _place('h', rect.top() + h / 2)
            _place('v', rect.left() + w / 2)
        elif preset == "thirds":
            _place('h', rect.top() + h / 3)
            _place('h', rect.top() + 2 * h / 3)
            _place('v', rect.left() + w / 3)
            _place('v', rect.left() + 2 * w / 3)
        elif preset == "golden":
            _place('h', rect.top() + 0.382 * h)
            _place('h', rect.top() + 0.618 * h)
            _place('v', rect.left() + 0.382 * w)
            _place('v', rect.left() + 0.618 * w)
        elif preset == "quarters":
            for f in (0.25, 0.5, 0.75):
                _place('h', rect.top() + f * h)
                _place('v', rect.left() + f * w)
        elif preset == "diagonal":
            # Not real guides (which are axis-aligned). Skip for now -
            # dropping a horizontal at center as a visual approximation.
            _place('h', rect.top() + h / 2)
            _place('v', rect.left() + w / 2)
            if self.info_label is not None:
                self.info_label.setText(
                    "Diagonal guides need overlay lines; added cross instead")
        elif preset == "safe":
            inset_w = 0.05 * w
            inset_h = 0.05 * h
            _place('h', rect.top() + inset_h)
            _place('h', rect.bottom() - inset_h)
            _place('v', rect.left() + inset_w)
            _place('v', rect.right() - inset_w)
        self._save_guides_to_asset()
        if self._canvas_wrap is not None:
            self._canvas_wrap.refresh()
        if self.info_label is not None:
            self.info_label.setText(
                f"Applied '{preset}' guide preset")

    def _clear_guides(self):
        """Remove all guide lines — called when the user selects Clear All."""
        for line in self._guide_items:
            if line.scene() is self._scene:
                self._scene.removeItem(line)
        self._guide_items = []
        self._pending_guide = None
        if self._asset:
            self._asset.guides = []
        if self._canvas_wrap is not None:
            self._canvas_wrap.refresh()

    def _set_overlays_preview_hidden(self, hidden: bool):
        """While `\\` is held, temporarily hide every overlay / censor /
        note so the user sees the base art alone. Release restores each
        item to whatever its persistent `enabled` flag says. Avoids
        mutating the persistent state so there's no risk of losing
        visibility on accidental bugs."""
        for it in self._scene.items():
            ov = getattr(it, "overlay", None)
            cr = getattr(it, "_censor_region", None)
            note = getattr(it, "_note_rect", None)
            if ov is not None:
                if hidden:
                    it.setVisible(False)
                else:
                    it.setVisible(bool(ov.enabled))
            elif cr is not None:
                it.setVisible(not hidden)
            elif note is not None:
                it.setVisible(not hidden)
        if self.info_label is not None:
            self.info_label.setText(
                "Previewing base art" if hidden else "Overlays restored")

    def _toggle_all_helpers(self):
        """Ctrl+H: hide everything that isn't the user's content — grid,
        rule-of-thirds, rulers, guides, snap indicators. Press again to
        restore each back to its pre-hide state. Store the state in
        _helpers_hidden_state so the restore knows which flags were on."""
        hidden = self._helpers_hidden_state
        if hidden is None:
            # Capture current state and hide everything
            state = {
                "grid": self.chk_grid.isChecked() if hasattr(self, "chk_grid") else False,
                "thirds": self.chk_thirds.isChecked() if hasattr(self, "chk_thirds") else False,
                "rulers": self.chk_rulers.isChecked() if hasattr(self, "chk_rulers") else False,
                "notes": self.chk_notes.isChecked() if hasattr(self, "chk_notes") else False,
            }
            for k, w_attr in (("grid", "chk_grid"), ("thirds", "chk_thirds"),
                               ("rulers", "chk_rulers"), ("notes", "chk_notes")):
                if state[k] and hasattr(self, w_attr):
                    getattr(self, w_attr).setChecked(False)
            # Hide guides
            for g in self._guide_items:
                g.setVisible(False)
            self._helpers_hidden_state = state
            if self.info_label is not None:
                self.info_label.setText("Helpers hidden (Ctrl+H to restore)")
        else:
            # Restore
            for k, w_attr in (("grid", "chk_grid"), ("thirds", "chk_thirds"),
                               ("rulers", "chk_rulers"), ("notes", "chk_notes")):
                if hidden.get(k) and hasattr(self, w_attr):
                    getattr(self, w_attr).setChecked(True)
            for g in self._guide_items:
                g.setVisible(True)
            self._helpers_hidden_state = None
            if self.info_label is not None:
                self.info_label.setText("Helpers restored")

    def _toggle_guides_visibility(self):
        """Hide / show existing guides without deleting them. Ctrl+; keymap.
        Preserves the guide list so the user can flip visibility during a
        tight-layout pass without redoing the drag-out work."""
        guides = self._guide_items
        if not guides:
            self.info_label.setText("No guides to toggle")
            return
        visible = guides[0].isVisible()
        for line in guides:
            line.setVisible(not visible)
        self.info_label.setText(
            "Guides: hidden" if visible else "Guides: visible")

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
        # Undo history is per-asset-session; clear it so switching assets
        # doesn't let users undo into a stale previous asset.
        if hasattr(self, "_undo_stack"):
            self._undo_stack.clear()
        self._scene.clear()
        self._censor_items.clear()
        self._overlay_items.clear()
        self._crop_items.clear()
        self._notes.clear()
        self._crop_mask_item = None
        self._pixmap_item = None
        # Drag-out guides are session-only — scene.clear() removed the items,
        # so just reset the tracking state.
        self._pending_guide = None
        self._guide_items = []

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

        # Checkerboard tile shows through any transparent pixels — classic
        # graphics-editor staple. Sit underneath the pixmap at negative Z.
        checker = _CheckerboardItem(QRectF(pm.rect()))
        checker.setZValue(-10)
        self._scene.addItem(checker)
        self._checker_item = checker

        self._pixmap_item = QGraphicsPixmapItem(pm)
        self._pixmap_item.setZValue(0)
        # Cache the base image so zoom/pan doesn't re-rasterize it every
        # frame. DeviceCoordinateCache keeps a cached copy at the current
        # zoom level.
        self._pixmap_item.setCacheMode(
            QGraphicsPixmapItem.CacheMode.DeviceCoordinateCache)
        checker.setCacheMode(
            QGraphicsPixmapItem.CacheMode.DeviceCoordinateCache)
        # Drop shadow intentionally removed - even a pre-rendered shadow
        # pixmap at full-canvas size (2000x3000+ = ~25MB) was tanking
        # FPS to single digits during drag. A 2px flat border provides
        # the "document sits on workspace" affordance at zero per-frame
        # cost. Restore shadow behind a setting if needed later.
        self._drop_shadow_item = None
        self._scene.addItem(self._pixmap_item)
        # Give the scene extra rect around the image so there's margin for
        # the shadow + workspace feel
        _pm_rect = QRectF(pm.rect())
        # Wide margin so the user can always pan freely in every
        # direction, including when the canvas + current zoom makes
        # the pixmap bigger than the viewport. Previous 10% margin
        # felt locked for users who wanted to pan the canvas off-
        # center; 50% gives a generous buffer.
        _margin = max(400, int(max(pm.width(), pm.height()) * 0.5))
        self._scene.setSceneRect(_pm_rect.adjusted(
            -_margin, -_margin, _margin, _margin))
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
        # Restore persisted guides
        self._load_saved_guides()

        self._update_info()

        # Update asset info
        if hasattr(self, '_asset_info'):
            size_mb = src.stat().st_size / (1024*1024) if src.exists() else 0
            self._asset_info.setText(f"{pm.width()}\u00d7{pm.height()} \u00b7 {src.suffix.upper().lstrip('.')} \u00b7 {size_mb:.1f}MB")

        if self._layer_panel is not None:
            self._rebuild_layer_panel()

    def _set_zoom(self, factor: float):
        self._view.resetTransform()
        self._view.scale(factor, factor)
        self._zoom_label.setText(f"{int(factor * 100)}%")
        if self._canvas_wrap is not None:
            self._canvas_wrap.refresh()

    def _save_view_bookmark(self, slot: int):
        """Save the current zoom + scroll position into slot 1..4.
        Persists via QSettings under studio_view_bookmark_<slot>."""
        qs = QSettings("DoxyEdit", "DoxyEdit")
        factor = self._view.transform().m11() or 1.0
        h_sb = self._view.horizontalScrollBar().value()
        v_sb = self._view.verticalScrollBar().value()
        qs.setValue(f"studio_view_bookmark_{slot}",
                    f"{factor:.4f}|{h_sb}|{v_sb}")
        self.info_label.setText(
            f"View bookmark {slot} saved "
            f"({int(factor * 100)}%)")

    def _load_view_bookmark(self, slot: int):
        """Restore a previously-saved zoom + scroll into the viewport.
        No-op if the slot is empty."""
        qs = QSettings("DoxyEdit", "DoxyEdit")
        blob = qs.value(f"studio_view_bookmark_{slot}", "", type=str)
        if not blob or blob.count("|") != 2:
            self.info_label.setText(
                f"View bookmark {slot} is empty "
                "(Shift+F{slot} to set)")
            return
        try:
            factor_s, h_s, v_s = blob.split("|")
            factor = float(factor_s)
            h_sb = int(h_s)
            v_sb = int(v_s)
        except (ValueError, TypeError):
            return
        self._view.resetTransform()
        self._view.scale(factor, factor)
        self._view.horizontalScrollBar().setValue(h_sb)
        self._view.verticalScrollBar().setValue(v_sb)
        self._zoom_label.setText(f"{int(factor * 100)}%")
        if self._canvas_wrap is not None:
            self._canvas_wrap.refresh()
        self.info_label.setText(
            f"Recalled view bookmark {slot} "
            f"({int(factor * 100)}%)")

    def _apply_text_style_to_all(self, source_overlay):
        """Copy the source overlay's text style fields to every other text
        overlay in the scene. Undo-wrapped per target so users can revert."""
        count = 0
        for it in list(self._overlay_items):
            if isinstance(it, OverlayTextItem) and it.overlay is not source_overlay:
                for field in self._TEXT_STYLE_FIELDS:
                    val = getattr(source_overlay, field)
                    if getattr(it.overlay, field) != val:
                        self._push_overlay_attr(
                            it, field, val,
                            apply_cb=lambda _it, _v: _it._apply_font(),
                            description="Apply text style")
                count += 1
        if count:
            self._sync_overlays_to_asset()
            self.info_label.setText(f"Applied style to {count} text overlay(s)")
        else:
            self.info_label.setText("No other text overlays to apply to")

    def _find_replace_text(self):
        """Prompt for find/replace strings and apply to every text overlay."""
        if not self._asset:
            return
        find_str, ok = QInputDialog.getText(
            self, "Find and Replace", "Find text (substring):")
        if not ok or not find_str:
            return
        repl_str, ok = QInputDialog.getText(
            self, "Find and Replace", f"Replace '{find_str}' with:")
        if not ok:
            return
        count = 0
        for it in list(self._overlay_items):
            if isinstance(it, OverlayTextItem) and find_str in it.overlay.text:
                new_text = it.overlay.text.replace(find_str, repl_str)
                self._push_overlay_attr(
                    it, "text", new_text,
                    apply_cb=lambda itm, v: itm.setPlainText(v),
                    description="Find / replace text")
                count += 1
        if count:
            self._sync_overlays_to_asset()
            self.info_label.setText(f"Replaced in {count} text overlay(s)")
        else:
            self.info_label.setText(f"No text overlays matched '{find_str}'")

    def _show_undo_history(self):
        """Non-modal, dockable-like undo history panel. Persists its
        geometry across close / reopen the same way Text and Shape
        Controls do. Stays open while the user continues working —
        clicks jump the undo stack to that index."""
        # Lazily create a single instance rather than a fresh modal
        # dialog on every click.
        if not hasattr(self, "_undo_history_dlg") or \
                self._undo_history_dlg is None:
            _qs = QSettings("DoxyEdit", "DoxyEdit")

            class _UndoHistoryDialog(QtWidgets.QDialog):
                _GEOM_KEY = "studio_undo_history_geom"
                def __init__(self, parent=None):
                    super().__init__(parent)
                    self._qs = _qs
                def _save_geom(self):
                    try:
                        self._qs.setValue(self._GEOM_KEY, self.saveGeometry())
                    except Exception:
                        pass
                def closeEvent(self, ev):
                    self._save_geom(); super().closeEvent(ev)
                def hideEvent(self, ev):
                    self._save_geom(); super().hideEvent(ev)
                def moveEvent(self, ev):
                    super().moveEvent(ev); self._save_geom()
                def resizeEvent(self, ev):
                    super().resizeEvent(ev); self._save_geom()

            dlg = _UndoHistoryDialog(self)
            dlg.setWindowTitle("Undo History")
            dlg.setObjectName("studio_undo_history_dlg")
            dlg.setWindowFlags(
                Qt.WindowType.Tool |
                Qt.WindowType.CustomizeWindowHint |
                Qt.WindowType.WindowTitleHint |
                Qt.WindowType.WindowCloseButtonHint)
            dlg.setMinimumSize(320, 360)
            layout = QVBoxLayout(dlg)
            layout.setContentsMargins(6, 6, 6, 6)
            lst = QListWidget(dlg)
            lst.setObjectName("studio_undo_history_list")
            layout.addWidget(lst)
            dlg._lst = lst
            self._undo_history_dlg = dlg
            # Live refresh: repopulate whenever the undo stack changes
            # so the dialog stays accurate as the user edits.
            def _refresh():
                if not dlg.isVisible():
                    return
                self._refresh_undo_history_list()
            self._undo_stack.indexChanged.connect(lambda _i: _refresh())
            def _on_click(item):
                idx = lst.row(item)
                self._undo_stack.setIndex(idx)
            lst.itemClicked.connect(_on_click)
            # Restore saved geometry
            _geom = _qs.value("studio_undo_history_geom", None)
            if _geom:
                try:
                    dlg.restoreGeometry(_geom)
                except Exception:
                    pass

        dlg = self._undo_history_dlg
        self._refresh_undo_history_list()
        win = self.window()
        if win is not None:
            dlg.setStyleSheet(win.styleSheet())
        if not dlg.isVisible():
            dlg.show()
        if win is not None and hasattr(win, "_theme_dialog_titlebar"):
            win._theme_dialog_titlebar(dlg)
        dlg.raise_()

    def _refresh_undo_history_list(self):
        if not hasattr(self, "_undo_history_dlg"):
            return
        dlg = self._undo_history_dlg
        lst = getattr(dlg, "_lst", None)
        if lst is None:
            return
        lst.blockSignals(True)
        lst.clear()
        lst.addItem("(clean)")
        for i in range(self._undo_stack.count()):
            txt = self._undo_stack.text(i)
            lst.addItem(txt or f"Action {i + 1}")
        current = self._undo_stack.index()
        if 0 <= current < lst.count():
            lst.setCurrentRow(current)
        lst.blockSignals(False)

    def _prompt_zoom_level(self, _event):
        """Click the zoom % label to enter a numeric zoom percentage.
        Uses a manually-constructed QInputDialog so the app's QSS
        actually applies — getInt() static spawns a dialog in a
        separate top-level context that Windows doesn't style."""
        current = int(self._view.transform().m11() * 100)
        dlg = QInputDialog(self)
        dlg.setInputMode(QInputDialog.InputMode.IntInput)
        dlg.setWindowTitle("Zoom")
        dlg.setLabelText("Zoom (%):")
        dlg.setIntRange(5, 4000)
        dlg.setIntValue(current)
        # Pull the window's active stylesheet so OK / Cancel / spinbox
        # match the rest of the app in both light and dark themes.
        win = self.window()
        if win is not None:
            dlg.setStyleSheet(win.styleSheet())
        if dlg.exec() == QInputDialog.DialogCode.Accepted:
            self._set_zoom(dlg.intValue() / 100.0)

    def _prompt_goto_coord(self):
        """Go-to dialog: prompt for X then Y and center the viewport
        on that scene coord. Parses the current cursor label value
        as the default for both axes, so a user can click 'Go to' and
        hit Enter to recenter on the cursor position."""
        cur_txt = self._cursor_label.text()
        try:
            cur_x = int(cur_txt.split(",")[0].strip())
            cur_y = int(cur_txt.split(",")[1].split()[0].strip())
        except (IndexError, ValueError):
            cur_x, cur_y = 0, 0
        x, ok = QInputDialog.getInt(
            self, "Go to coordinate",
            "X (scene px):", value=cur_x,
            minValue=-99999, maxValue=99999)
        if not ok:
            return
        y, ok = QInputDialog.getInt(
            self, "Go to coordinate",
            "Y (scene px):", value=cur_y,
            minValue=-99999, maxValue=99999)
        if not ok:
            return
        self._view.centerOn(QPointF(x, y))
        self.info_label.setText(f"Centered on ({x}, {y})")

    def _open_skia_preview(self):
        """Shift+S — open a window showing the current asset rendered
        via the Skia backend (canvas_skia.CanvasSkia). Side-by-side
        preview so the user can confirm the Skia pipeline works on
        their actual content before Day-14-full-cutover wires the
        backend as the main compositor.

        Reuses the live Asset / CanvasOverlay / CensorRegion objects —
        zero conversion. Draws the base image + every overlay + every
        censor at native resolution.
        """
        if self._asset is None:
            if self.info_label is not None:
                self.info_label.setText("Load an asset first")
            return
        try:
            from doxyedit.canvas_skia import (
                CanvasSkia, CanvasSkiaGL,
                skia_available, skia_error, canvas_skia_gl_available,
            )
        except Exception as e:
            if self.info_label is not None:
                self.info_label.setText(f"Skia import failed: {e}")
            return
        if not skia_available():
            if self.info_label is not None:
                self.info_label.setText(
                    f"Skia unavailable: {skia_error()}")
            return
        # Build (or reuse) the preview window.
        dlg = getattr(self, "_skia_preview_dlg", None)
        fresh_build = dlg is None
        if fresh_build:
            from PySide6.QtWidgets import (
                QMainWindow, QVBoxLayout, QWidget, QToolBar,
                QCheckBox, QComboBox, QLabel,
            )
            from PySide6.QtCore import QTimer
            dlg = QMainWindow(self.window())
            dlg.setWindowTitle("DoxyEdit — Skia Preview (beta)")
            dlg.resize(1100, 750)
            # Pick backend from setting (skia_cpu default, skia_gl opt-in).
            # GL Skia is the Tier 2 GPU path; falls back to CPU raster
            # if the platform can't create a GL context.
            compositor = QSettings("DoxyEdit", "DoxyEdit").value(
                "studio_compositor", "skia_cpu", type=str)
            if compositor == "skia_gl" and canvas_skia_gl_available():
                canvas = CanvasSkiaGL(dlg)
            else:
                canvas = CanvasSkia(dlg)
            dlg.setCentralWidget(canvas)
            dlg._canvas = canvas
            # Toolbar: manual refresh + auto-follow toggle + backend picker.
            tb = QToolBar("Preview", dlg)
            refresh_act = tb.addAction("↻ Refresh")
            follow_cb = QCheckBox("Auto-follow")
            follow_cb.setChecked(True)
            follow_cb.setToolTip(
                "Re-render every 500ms to track live Studio edits")
            tb.addWidget(follow_cb)
            tb.addSeparator()
            tb.addWidget(QLabel("  Backend: "))
            backend_combo = QComboBox()
            backend_combo.addItem("CPU raster (skia_cpu)", "skia_cpu")
            if canvas_skia_gl_available():
                backend_combo.addItem("GPU Skia (skia_gl)", "skia_gl")
            # Select the currently-active backend
            for idx in range(backend_combo.count()):
                if backend_combo.itemData(idx) == compositor:
                    backend_combo.setCurrentIndex(idx)
                    break
            backend_combo.setToolTip(
                "Switching swaps the render backend and persists via "
                "studio_compositor. Requires closing+reopening this window.")

            def _on_backend_changed(idx):
                new = backend_combo.itemData(idx)
                QSettings("DoxyEdit", "DoxyEdit").setValue(
                    "studio_compositor", new)
                # Force a rebuild on next Shift+S
                self._skia_preview_dlg = None
                dlg.close()
            backend_combo.currentIndexChanged.connect(_on_backend_changed)
            tb.addWidget(backend_combo)
            dlg.addToolBar(tb)
            dlg._follow_cb = follow_cb
            # Auto-refresh timer: pulls from the current asset every
            # 500ms when follow_cb is checked. Cheap enough on a raster
            # Skia surface (1-2ms per render); stops when dlg hidden.
            timer = QTimer(dlg)
            timer.setInterval(500)
            timer.timeout.connect(
                lambda: self._refresh_skia_preview() if follow_cb.isChecked()
                and dlg.isVisible() else None)
            timer.start()
            dlg._follow_timer = timer
            refresh_act.triggered.connect(self._refresh_skia_preview)
            self._skia_preview_dlg = dlg
        # First-open: fit-to-view; subsequent opens just refresh.
        if fresh_build:
            canvas = dlg._canvas
            canvas.set_base_image_path(self._asset.source_path)
            canvas.set_overlays(list(self._asset.overlays or []))
            canvas.set_censors(list(self._asset.censors or []))
            bw = canvas.base_size().width() or 1
            bh = canvas.base_size().height() or 1
            avail_w = canvas.width() or 1
            avail_h = canvas.height() or 1
            fit = min(avail_w / bw, avail_h / bh, 1.0)
            canvas.set_zoom(fit if fit > 0 else 1.0)
            canvas._pan_x = max(0.0, (avail_w - bw * fit) / 2)
            canvas._pan_y = max(0.0, (avail_h - bh * fit) / 2)
            canvas.update()
        else:
            self._refresh_skia_preview()
        dlg.show()
        dlg.raise_()

    def _refresh_skia_preview(self):
        """Pull current asset state into the Skia preview canvas.
        Called by the 500ms auto-follow timer and the manual Refresh
        button.

        Cheap when the asset hasn't changed — set_overlays / set_censors
        just swap list references + schedule a repaint. Correctness-first:
        always re-push; in-place mutation of overlay fields (text, color,
        font size) wouldn't change a geometry-only fingerprint, so we
        don't fingerprint. Skia re-render of an unchanged scene is ~2ms.
        """
        dlg = getattr(self, "_skia_preview_dlg", None)
        if dlg is None or self._asset is None:
            return
        # Gate work on window visibility — if the user hid the preview
        # (Alt+Tab away, minimize, close-then-timer-ticks-once-more) don't
        # spin Skia CPU cycles into the void. The timer callback in
        # _open_skia_preview also guards on isVisible, but a minimized
        # window can be "visible" per Qt semantics; isActiveWindow /
        # isMinimized is the tighter check.
        if dlg.isMinimized():
            return
        canvas = dlg._canvas
        cur_path = getattr(canvas, "_loaded_path", None)
        new_path = self._asset.source_path
        if cur_path != new_path:
            canvas.set_base_image_path(new_path)
            canvas._loaded_path = new_path
        canvas.set_overlays(list(self._asset.overlays or []))
        canvas.set_censors(list(self._asset.censors or []))

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

    def _handle_escape_shortcut(self):
        """Fired by the WidgetWithChildrenShortcut — runs the full
        Escape cleanup regardless of whether the focus widget is the
        scene, view, sidebar button, or a spin / slider input. Previous
        behavior was that Escape on a sidebar button just went to the
        parent widget and did nothing.

        If isolation mode is active, Escape exits isolation first
        rather than immediately clearing the selection — gives the
        user a way out of isolation without hunting for the layer
        panel right-click."""
        if not self.isVisible():
            return
        if self._isolation_active:
            self._exit_isolation()
            return
        if self._scene is not None:
            focus = self._scene.focusItem()
            if focus is not None and isinstance(focus, OverlayTextItem):
                cursor = focus.textCursor()
                cursor.clearSelection()
                focus.setTextCursor(cursor)
                focus.setTextInteractionFlags(
                    Qt.TextInteractionFlag.NoTextInteraction)
                focus.overlay.text = focus.toPlainText()
                focus.clearFocus()
        self._clear_escape_state()

    def _clear_escape_state(self):
        """Shared cleanup for Escape — reset tool, clear text-edit state,
        remove crop mask."""
        if not self.isVisible():
            return
        # Reset to the Select tool if a drawing tool is active
        if self._scene.current_tool not in (StudioTool.SELECT,):
            self._set_tool(StudioTool.SELECT)
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
        # Defensive reset — if spacebar-pan state got stuck (e.g., user held
        # Space while clicking the Main palette, keyRelease never fired on
        # Studio), the view stays in ScrollHandDrag and a left-drag becomes
        # a pan that slides the canvas off-screen. Clear the flag and
        # restore RubberBandDrag before reconfiguring for the new tool.
        if self._space_panning:
            self._space_panning = False
        self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        # Translate the generic SHAPE tool into rect/ellipse based on combo
        if tool == StudioTool.SHAPE_RECT and hasattr(self, "combo_shape_kind"):
            if self.combo_shape_kind.currentText() == "Ellipse":
                tool = StudioTool.SHAPE_ELLIPSE
        self._scene.set_tool(tool)
        if tool in (StudioTool.CENSOR, StudioTool.CROP, StudioTool.NOTE,
                    StudioTool.ARROW, StudioTool.SHAPE_RECT, StudioTool.SHAPE_ELLIPSE):
            self._view.setCursor(Qt.CursorShape.CrossCursor)
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif tool == StudioTool.EYEDROPPER:
            self._view.setCursor(Qt.CursorShape.PointingHandCursor)
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif tool == StudioTool.WATERMARK:
            self._add_watermark()
            self._scene.set_tool(StudioTool.SELECT)
            tool = StudioTool.SELECT  # reflect the post-dialog state on buttons
        elif tool == StudioTool.TEXT_OVERLAY:
            self._view.setCursor(Qt.CursorShape.CrossCursor)
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        else:
            self._view.setCursor(Qt.CursorShape.ArrowCursor)
            self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._sync_tool_buttons(tool)
        self._sync_text_controls_visibility()
        # Persist the last-used tool so the next Studio session starts there.
        # Watermark is excluded because it's a one-shot file-dialog flow.
        if tool != StudioTool.WATERMARK:
            QSettings("DoxyEdit", "DoxyEdit").setValue(
                "studio_last_tool", tool.name)

    def _sync_tool_buttons(self, tool: StudioTool):
        """Highlight the button for the active tool — uses QSS :checked."""
        mapping = {
            StudioTool.SELECT: self.btn_select,
            StudioTool.CENSOR: self.btn_censor,
            StudioTool.CROP: self.btn_crop,
            StudioTool.NOTE: self.btn_note,
            StudioTool.WATERMARK: self.btn_watermark,
            StudioTool.TEXT_OVERLAY: self.btn_text,
            StudioTool.EYEDROPPER: self.btn_eyedropper,
            StudioTool.ARROW: self.btn_arrow,
        }
        for t, btn in mapping.items():
            btn.setChecked(t == tool)
        if hasattr(self, "btn_shape"):
            self.btn_shape.setChecked(
                tool in (StudioTool.SHAPE_RECT, StudioTool.SHAPE_ELLIPSE))
        # Also sync the main-window's left-toolbar Main palette actions.
        win = self.window()
        if win is not None and hasattr(win, "_tool_actions"):
            for action, act_tool in win._tool_actions:
                # Treat Shape variants as checked for the one SHAPE_RECT action.
                if act_tool == StudioTool.SHAPE_RECT:
                    action.setChecked(
                        tool in (StudioTool.SHAPE_RECT, StudioTool.SHAPE_ELLIPSE))
                else:
                    action.setChecked(act_tool == tool)
        # Update the tool-name label in the status bar
        if hasattr(self, "_tool_label"):
            names = {
                StudioTool.SELECT: "Select",
                StudioTool.CENSOR: "Censor",
                StudioTool.CROP: "Crop",
                StudioTool.NOTE: "Note",
                StudioTool.WATERMARK: "Image",
                StudioTool.TEXT_OVERLAY: "Text",
                StudioTool.EYEDROPPER: "Eyedropper",
                StudioTool.ARROW: "Arrow",
                StudioTool.SHAPE_RECT: "Shape (rect)",
                StudioTool.SHAPE_ELLIPSE: "Shape (ellipse)",
            }
            self._tool_label.setText(names.get(tool, "Select"))

    def _get_crop_aspect(self) -> float | None:
        """Return target W/H aspect ratio from crop combo, or None for free crop."""
        data = self._crop_combo.currentData()
        if data is None:
            return None
        w, h = data[2], data[3]
        return w / h if h else None

    def _on_censor_style_changed(self, style: str):
        self._scene.set_censor_style(style)
        # Persist so next Studio launch defaults to the user's preferred style
        QSettings("DoxyEdit", "DoxyEdit").setValue(
            "studio_censor_default_style", style)

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

    def _on_arrow_drawn(self, line: QLineF):
        """Called when an arrow is finished drawing."""
        if not self._asset:
            return
        # Remember the last-used arrow color + stroke so a series of arrows
        # stays visually consistent without having to re-pick each time.
        _qs = QSettings("DoxyEdit", "DoxyEdit")
        color = _qs.value("studio_arrow_color", "#ff3b30", type=str)
        stroke = _qs.value("studio_arrow_stroke", 4, type=int)
        head = _qs.value("studio_arrow_head", 18, type=int)
        ov = CanvasOverlay(
            type="arrow",
            label="Arrow",
            color=color,
            opacity=1.0,
            stroke_width=stroke,
            x=int(line.x1()), y=int(line.y1()),
            end_x=int(line.x2()), end_y=int(line.y2()),
            arrowhead_size=head,
        )
        self._asset.overlays.append(ov)
        item = OverlayArrowItem(ov)
        item._editor = self
        item.setZValue(200 + len(self._overlay_items))
        self._scene.addItem(item)
        self._overlay_items.append(item)
        self._view.setCursor(Qt.CursorShape.ArrowCursor)
        self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._update_info()

    def _on_shape_drawn(self, rect: QRectF, kind: str):
        """Called when a shape rect or ellipse is finished drawing."""
        if not self._asset:
            return
        # Resolve the real shape kind from the combo so Speech / Thought
        # Bubble / Burst rolled through the same drag-to-size flow pick up
        # their bubble shape_kind instead of falling back to rect.
        combo_kind = {
            "Rectangle": "rect",
            "Ellipse": "ellipse",
            "Speech Bubble": "speech_bubble",
            "Thought Bubble": "thought_bubble",
            "Burst": "burst",
            "Star": "star",
            "Polygon": "polygon",
        }.get(self.combo_shape_kind.currentText() if hasattr(self, "combo_shape_kind") else "", "")
        if combo_kind:
            kind = combo_kind
        _qs = QSettings("DoxyEdit", "DoxyEdit")
        # Bubbles get black-on-white defaults (comic convention);
        # non-bubble shapes keep the amber outline style.
        if kind in ("speech_bubble", "thought_bubble"):
            stroke = _qs.value("studio_bubble_stroke_color", "#000000", type=str)
            fill = _qs.value("studio_bubble_fill_color", "#ffffff", type=str)
            sw = _qs.value("studio_bubble_stroke_width", 3, type=int)
        else:
            stroke = _qs.value("studio_shape_stroke_color", "#ffd700", type=str)
            fill = _qs.value("studio_shape_fill_color", "", type=str)
            sw = _qs.value("studio_shape_stroke_width", 2, type=int)
        radius = _qs.value("studio_shape_corner_radius", 0, type=int)
        line_style = _qs.value("studio_shape_line_style", "solid", type=str)
        label = kind.replace("_", " ").title() if kind != "rect" else "Shape"
        ov = CanvasOverlay(
            type="shape",
            label=label,
            shape_kind=kind,
            color=stroke,
            stroke_color=stroke,
            stroke_width=sw,
            fill_color=fill,
            opacity=1.0,
            x=int(rect.x()), y=int(rect.y()),
            shape_w=int(rect.width()), shape_h=int(rect.height()),
            corner_radius=radius,
            line_style=line_style,
        )
        # Bubbles get a sensible initial tail so the paint path has
        # something to draw against, plus a paired text overlay inside
        # the body so the comic workflow is one-step.
        if kind in ("speech_bubble", "thought_bubble"):
            ov.tail_x = int(rect.x() + rect.width() * 0.25)
            ov.tail_y = int(rect.y() + rect.height() * 1.35)
            link_id = f"bubble_text_{uuid.uuid4().hex[:8]}"
            ov.linked_text_id = link_id
        self._asset.overlays.append(ov)
        item = OverlayShapeItem(ov)
        item._editor = self
        item.setZValue(200 + len(self._overlay_items))
        self._scene.addItem(item)
        self._overlay_items.append(item)
        # For bubbles: drop a paired text overlay centered in the body.
        if kind in ("speech_bubble", "thought_bubble"):
            pad_x = int(rect.width() * 0.15)
            pad_y = int(rect.height() * 0.18)
            text_ov = CanvasOverlay(
                type="text",
                label=ov.linked_text_id,
                text="...",
                opacity=1.0,
                position="custom",
                x=int(rect.x() + pad_x),
                y=int(rect.y() + pad_y),
                text_width=int(rect.width() - 2 * pad_x),
                font_size=24,
                text_align="center",
                color="#000000",
            )
            for k, v in self._load_text_style_defaults().items():
                if k == "text_width":
                    continue
                setattr(text_ov, k, v)
            self._asset.overlays.append(text_ov)
            text_item = self._create_overlay_item(text_ov)
            if text_item:
                text_item.setZValue(200 + len(self._overlay_items))
                self._overlay_items.append(text_item)
        self._view.setCursor(Qt.CursorShape.ArrowCursor)
        self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._update_info()

    def _duplicate_shape_item(self, item, offset: int = 20):
        """Clone a shape overlay with optional x/y offset (default 20 px)."""
        ov = item.overlay
        new_ov = CanvasOverlay(
            type="shape",
            label=ov.label,
            shape_kind=ov.shape_kind,
            color=ov.color,
            stroke_color=ov.stroke_color,
            stroke_width=ov.stroke_width,
            fill_color=ov.fill_color,
            opacity=ov.opacity,
            x=ov.x + offset, y=ov.y + offset,
            shape_w=ov.shape_w, shape_h=ov.shape_h,
            platforms=list(ov.platforms),
        )
        self._asset.overlays.append(new_ov)
        new_item = OverlayShapeItem(new_ov)
        new_item._editor = self
        new_item.setZValue(200 + len(self._overlay_items))
        self._scene.addItem(new_item)
        self._overlay_items.append(new_item)

    def _duplicate_arrow_item(self, item, offset: int = 20):
        """Clone an arrow overlay with optional x/y offset (default 20 px)."""
        ov = item.overlay
        new_ov = CanvasOverlay(
            type="arrow",
            label=ov.label,
            color=ov.color,
            opacity=ov.opacity,
            stroke_width=ov.stroke_width,
            x=ov.x + offset, y=ov.y + offset,
            end_x=ov.end_x + offset, end_y=ov.end_y + offset,
            arrowhead_size=ov.arrowhead_size,
            platforms=list(ov.platforms),
        )
        self._asset.overlays.append(new_ov)
        new_item = OverlayArrowItem(new_ov)
        new_item._editor = self
        new_item.setZValue(200 + len(self._overlay_items))
        self._scene.addItem(new_item)
        self._overlay_items.append(new_item)

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
        # Live-update the info label so users see dimensions as they drag
        self.info_label.setText(
            f"Crop '{region.label}': {region.w}x{region.h} at ({region.x},{region.y})")

    def _update_crop_mask(self, crop_rect: QRectF):
        """Draw dark overlay outside the crop region."""
        if self._crop_mask_item:
            if self._crop_mask_item.scene():
                self._scene.removeItem(self._crop_mask_item)
            self._crop_mask_item = None
        if not self._pixmap_item:
            return
        img_rect = self._pixmap_item.boundingRect()
        path = QPainterPath()
        path.addRect(img_rect)
        hole = QPainterPath()
        hole.addRect(crop_rect)
        path = path.subtracted(hole)
        self._crop_mask_item = QGraphicsPathItem(path)
        self._crop_mask_item.setPen(QPen(Qt.PenStyle.NoPen))
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
            # Aspect lock applies ONLY to platform-bound crops. Free
            # crops (no platform_id) were getting aspect = w/h baked in
            # on reload, which permanently locked their ratio to
            # whatever shape the user drew them - users couldn't
            # reshape a free crop after closing/reopening the project.
            has_platform = bool(getattr(crop, "platform_id", ""))
            aspect = (crop.w / crop.h
                      if has_platform and crop.w and crop.h
                      else None)
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
        pattern = re.compile(r'\[(\d+),(\d+)\s+(\d+)x(\d+)\]\s*(.*)')
        for line in self._asset.notes.split("\n"):
            m = pattern.match(line.strip())
            if m:
                x, y, w, h = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                text = m.group(5)
                note = NoteRectItem(QRectF(x, y, w, h), text)
                note.setZValue(400)
                self._scene.addItem(note)
                # Respect the Notes toolbar toggle at load time
                if hasattr(self, "chk_notes"):
                    note.setVisible(self.chk_notes.isChecked())
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
            # Filter applies after construction so the stored pixmap reflects it
            if ov.filter_mode:
                self._refresh_overlay_image(item)
            return item
        elif ov.type == "text":
            item = OverlayTextItem(ov)
            item._editor = self
            self._scene.addItem(item)
            return item
        elif ov.type == "arrow":
            item = OverlayArrowItem(ov)
            item._editor = self
            self._scene.addItem(item)
            return item
        elif ov.type == "shape":
            item = OverlayShapeItem(ov)
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
        for k, v in self._load_watermark_style_defaults().items():
            setattr(ov, k, v)
        self._asset.overlays.append(ov)
        item = self._create_overlay_item(ov)
        if item:
            item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(item)
        self._update_info()

    # Watermark / logo default-style persistence — mirrors text defaults.
    # Excludes image_path / label / x / y / text which are per-instance.
    _WATERMARK_STYLE_FIELDS = (
        "scale", "opacity", "rotation", "position", "flip_h", "flip_v",
    )

    def _load_watermark_style_defaults(self) -> dict:
        raw = QSettings("DoxyEdit", "DoxyEdit").value(
            "studio_watermark_defaults", "", type=str)
        if not raw:
            return {}
        try:
            d = json.loads(raw)
            # Strip opacity - new watermarks always start fully opaque.
            return {k: v for k, v in d.items()
                    if k in self._WATERMARK_STYLE_FIELDS and k != "opacity"}
        except Exception:
            return {}

    def _save_watermark_style_as_default(self, ov: CanvasOverlay):
        payload = {k: getattr(ov, k) for k in self._WATERMARK_STYLE_FIELDS}
        QSettings("DoxyEdit", "DoxyEdit").setValue(
            "studio_watermark_defaults", json.dumps(payload, ensure_ascii=False))
        self.info_label.setText("Saved default watermark style")

    def _reset_watermark_style_defaults(self):
        QSettings("DoxyEdit", "DoxyEdit").remove("studio_watermark_defaults")
        self.info_label.setText("Reset default watermark style")

    def _refresh_overlay_image(self, item):
        """Reload+reapply pipeline for an image overlay. Debounced because
        brightness / contrast / saturation sliders call this on every
        tick, and the pipeline (disk read + smooth scale + PIL enhance)
        is 50-200ms per call.

        Slider ticks at 60 Hz would otherwise pile 60+ invocations per
        second onto the main thread. Coalesce to one call per 80ms of
        quiet, keyed by the item. The timer re-fires on each call — only
        the most recent invocation wins.
        """
        if not hasattr(self, "_overlay_refresh_timer"):
            self._overlay_refresh_timer = QTimer(self)
            self._overlay_refresh_timer.setSingleShot(True)
            self._overlay_refresh_timer.setInterval(80)
            self._overlay_refresh_pending = set()
            def _flush():
                pending = list(self._overlay_refresh_pending)
                self._overlay_refresh_pending.clear()
                for it in pending:
                    try:
                        self._refresh_overlay_image_now(it)
                    except Exception:
                        pass
            self._overlay_refresh_timer.timeout.connect(_flush)
        self._overlay_refresh_pending.add(item)
        self._overlay_refresh_timer.start()

    def _refresh_overlay_image_now(self, item):
        """Immediate synchronous version (called by the debounce timer)."""
        ov = item.overlay
        if not ov.image_path:
            return
        # Cache the source pixmap on the item — prior code did
        # QPixmap(path) (disk read + decode) on every slider tick.
        src = getattr(item, "_source_pixmap", None)
        if src is None or src.isNull():
            src = QPixmap(ov.image_path)
            item._source_pixmap = src
        if src.isNull():
            return
        # Re-scale
        if self._pixmap_item:
            base_w = self._pixmap_item.pixmap().width()
            target_w = max(10, int(base_w * ov.scale))
            src = src.scaledToWidth(target_w,
                                     Qt.TransformationMode.SmoothTransformation)
        # Apply filter. Grayscale / invert / blur route through PIL for
        # vectorized ops — was a Python per-pixel loop that took minutes
        # on large overlays (~6M iterations for a 2k x 3k image).
        mode = ov.filter_mode
        if mode in ("grayscale", "invert"):
            from PIL import Image, ImageOps
            pil_img = qimage_to_pil(src.toImage())
            if mode == "grayscale":
                # Keep alpha channel; grayscale only RGB.
                if pil_img.mode == "RGBA":
                    r, g, b, a = pil_img.split()
                    gray = ImageOps.grayscale(pil_img.convert("RGB"))
                    pil_img = Image.merge("RGBA", (gray, gray, gray, a))
                else:
                    pil_img = ImageOps.grayscale(pil_img).convert("RGBA")
            else:  # invert
                if pil_img.mode == "RGBA":
                    r, g, b, a = pil_img.split()
                    inv = ImageOps.invert(pil_img.convert("RGB")).split()
                    pil_img = Image.merge(
                        "RGBA", (inv[0], inv[1], inv[2], a))
                else:
                    pil_img = ImageOps.invert(pil_img.convert("RGB")).convert("RGBA")
            src = QPixmap.fromImage(pil_to_qimage(pil_img))
        elif mode in ("blur3", "blur8"):
            radius = 3 if mode == "blur3" else 8
            from PIL import ImageFilter
            pil_img = qimage_to_pil(src.toImage())
            pil_img = pil_img.filter(ImageFilter.GaussianBlur(radius=radius))
            src = QPixmap.fromImage(pil_to_qimage(pil_img))
        # Brightness / contrast / saturation via PIL ImageEnhance.
        # Skip the round-trip entirely when all three are zero so
        # simple overlays don't pay for the conversion cost. When
        # any are active, hand the post-scale/post-filter QImage to
        # a QThreadPool worker so the GUI thread isn't blocked on
        # PIL during slider drags — the 3 enhance calls on a 2K PSD
        # are 80-200ms each, enough to drop drag FPS below 15.
        _br = float(ov.img_brightness or 0.0)
        _ct = float(ov.img_contrast or 0.0)
        _st = float(ov.img_saturation or 0.0)
        if _br or _ct or _st:
            self._schedule_image_enhance(item, src.toImage(), _br, _ct, _st)
            # Fall-through: display the pre-enhance pixmap immediately.
            # The worker will setPixmap again when done.
        item.setPixmap(src)
        item.update()

    def _schedule_image_enhance(self, item, qimg, brightness, contrast, saturation):
        """Run PIL ImageEnhance off the GUI thread and swap in the
        result when the worker completes. Each call increments the
        per-item token so earlier (slower) workers can't overwrite
        the latest slider position with stale pixels."""
        if not hasattr(self, "_enhance_signals"):
            self._enhance_signals = _ImageEnhanceSignals()
            self._enhance_signals.done.connect(self._adopt_image_enhance)
            self._enhance_tokens: dict[int, int] = {}
        item_id = id(item)
        self._enhance_tokens[item_id] = self._enhance_tokens.get(item_id, 0) + 1
        token = self._enhance_tokens[item_id]
        # Cache the item ref on the signals object's result mapping so
        # the slot can find it without walking the scene.
        if not hasattr(self, "_enhance_item_refs"):
            self._enhance_item_refs: dict[int, object] = {}
        self._enhance_item_refs[item_id] = item
        QThreadPool.globalInstance().start(
            _ImageEnhanceWorker(item_id, token, qimg,
                                brightness, contrast, saturation,
                                self._enhance_signals))

    def _adopt_image_enhance(self, item_id: int, token: int, qimg: QImage):
        """Worker thread completion slot. Adopt the enhanced QImage iff
        this is still the most recent request for this item — otherwise
        a newer slider tick has already been submitted and we'd regress
        to stale pixels."""
        latest = getattr(self, "_enhance_tokens", {}).get(item_id)
        if latest != token:
            return
        item = getattr(self, "_enhance_item_refs", {}).get(item_id)
        if item is None or qimg.isNull():
            return
        item.setPixmap(QPixmap.fromImage(qimg))
        item.update()

    def _replace_overlay_image(self, item):
        """Swap the image file for an existing watermark/logo overlay."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Replace watermark image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if not path:
            return
        pm = QPixmap(path)
        if pm.isNull():
            self.info_label.setText("Failed to load image")
            return
        item.overlay.image_path = path
        item.overlay.label = Path(path).stem
        # Invalidate the source-pixmap cache — next scale/refresh call
        # will reload from disk at the new path.
        item._source_pixmap = pm
        # Re-scale to current scale fraction against base image width
        if self._pixmap_item:
            base_w = self._pixmap_item.pixmap().width()
            target_w = max(10, int(base_w * item.overlay.scale))
            pm = pm.scaledToWidth(
                target_w, Qt.TransformationMode.SmoothTransformation)
        item.setPixmap(pm)
        self._sync_overlays_to_asset()
        self.info_label.setText(f"Replaced with {Path(path).name}")

    # Copy/Paste Style between overlays — session-only, separate slot per type.
    # For text-to-text: all text style fields. For image-to-image: watermark
    # fields. For arrow: color, opacity, stroke_width, arrowhead_size.
    _copy_style_slot: dict = {}
    _ARROW_STYLE_FIELDS = ("color", "opacity", "stroke_width", "arrowhead_size")

    def _copy_style(self, ov):
        """Stash style fields from an overlay into a per-type slot."""
        if ov.type == "text":
            fields = self._TEXT_STYLE_FIELDS
        elif ov.type == "arrow":
            fields = self._ARROW_STYLE_FIELDS
        else:
            fields = self._WATERMARK_STYLE_FIELDS
        self._copy_style_slot[ov.type] = {f: getattr(ov, f) for f in fields}
        self.info_label.setText(f"Copied {ov.type} style")

    def _paste_style(self, ov, scene_item):
        """Apply the stashed style to the target overlay (same type only)."""
        payload = self._copy_style_slot.get(ov.type, {})
        if not payload:
            self.info_label.setText(f"No copied {ov.type} style to paste")
            return
        for k, v in payload.items():
            setattr(ov, k, v)
        # Refresh the scene item's visual state — text needs font rebuild,
        # image needs flip/rotation re-apply.
        if hasattr(scene_item, "_apply_font"):
            scene_item._apply_font()
        if hasattr(scene_item, "_apply_flip"):
            scene_item._apply_flip()
        if hasattr(scene_item, "_apply_flip_text"):
            scene_item._apply_flip_text()
        scene_item.update()
        self._sync_overlays_to_asset()
        self.info_label.setText(f"Pasted {ov.type} style")

    def _on_text_placed(self, pos: QPointF, width: int = 0):
        """Handle click-to-place or drag-to-size text overlay from scene.
        width == 0 means click-place (auto-width); otherwise the text box is
        locked to that pixel width so multi-line bubbles wrap to fit."""
        self._add_text_overlay(int(pos.x()), int(pos.y()), text_width=width)
        # Sticky tool means cursor should stay cross; otherwise arrow.
        sticky = QSettings("DoxyEdit", "DoxyEdit").value(
            "studio_sticky_tools", True, type=bool)
        if not sticky:
            self._view.setCursor(Qt.CursorShape.ArrowCursor)
            self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    # Fields copied into the CanvasOverlay when the user "Saves as Default
    # Text Style". Position/size/text fields are intentionally excluded --
    # those are per-instance.
    _TEXT_STYLE_FIELDS = (
        "font_family", "font_size", "color", "opacity",
        "bold", "italic", "underline", "strikethrough",
        "text_align",
        "letter_spacing", "line_height",
        "stroke_color", "stroke_width",
        "shadow_color", "shadow_offset", "shadow_blur",
    )

    def _load_text_style_defaults(self) -> dict:
        """Return the user's saved default text style (or {} if none).
        Opacity is intentionally stripped - new text always starts opaque
        regardless of what an old saved default may contain."""
        raw = QSettings("DoxyEdit", "DoxyEdit").value("studio_text_defaults", "", type=str)
        if not raw:
            return {}
        try:
            d = json.loads(raw)
            return {k: v for k, v in d.items()
                    if k in self._TEXT_STYLE_FIELDS and k != "opacity"}
        except Exception:
            return {}

    def _save_text_style_as_default(self, ov: CanvasOverlay):
        """Persist the overlay's style fields as the new default."""
        payload = {k: getattr(ov, k) for k in self._TEXT_STYLE_FIELDS}
        QSettings("DoxyEdit", "DoxyEdit").setValue(
            "studio_text_defaults", json.dumps(payload, ensure_ascii=False))
        self.info_label.setText("Saved default text style")

    def _reset_text_style_defaults(self):
        """Clear the saved text style defaults (revert to CanvasOverlay()
        dataclass fields)."""
        QSettings("DoxyEdit", "DoxyEdit").remove("studio_text_defaults")
        self.info_label.setText("Reset default text style")

    def _load_named_text_styles(self) -> dict:
        """Return {name: {field: value}} of user-saved named text styles."""
        raw = QSettings("DoxyEdit", "DoxyEdit").value("studio_text_named_styles", "", type=str)
        if not raw:
            return {}
        try:
            d = json.loads(raw)
            return {name: {k: v for k, v in fields.items()
                           if k in self._TEXT_STYLE_FIELDS}
                    for name, fields in d.items()}
        except Exception:
            return {}

    def _write_named_text_styles(self, styles: dict):
        QSettings("DoxyEdit", "DoxyEdit").setValue(
            "studio_text_named_styles",
            json.dumps(styles, ensure_ascii=False))

    def _populate_text_styles_combo(self):
        """Refill the text-style dropdown from QSettings. Remembers the
        previously-selected name if still present."""
        if not hasattr(self, "combo_text_style"):
            return
        prev = self.combo_text_style.currentText()
        self.combo_text_style.blockSignals(True)
        self.combo_text_style.clear()
        for name in sorted(self._load_named_text_styles().keys()):
            self.combo_text_style.addItem(name)
        if prev:
            idx = self.combo_text_style.findText(prev)
            if idx >= 0:
                self.combo_text_style.setCurrentIndex(idx)
        self.combo_text_style.blockSignals(False)

    def _save_named_text_style(self):
        """Save current text styling under a user-supplied name. If a text
        overlay is selected, read from it; otherwise fall back to the
        current dialog control values."""
        name, ok = QInputDialog.getText(
            self, "Save Text Style", "Style name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        sel = [it for it in self._scene.selectedItems()
               if isinstance(it, OverlayTextItem)]
        styles = self._load_named_text_styles()
        if sel:
            ov = sel[0].overlay
            styles[name] = {k: getattr(ov, k) for k in self._TEXT_STYLE_FIELDS}
        else:
            # No selection: snapshot from the dialog controls. Preserve
            # any previously-persisted default for fields the dialog
            # doesn't expose directly (underline, strikethrough, etc.).
            base = self._load_text_style_defaults()
            base.update({
                "font_size": self.slider_font_size.value(),
                "bold": self.btn_bold.isChecked(),
                "italic": self.btn_italic.isChecked(),
                "stroke_width": self.slider_outline.value(),
                "letter_spacing": self.slider_kerning.value(),
                "line_height": self.slider_line_height.value() / 100.0,
                "font_family": self.font_combo.currentText(),
            })
            styles[name] = {k: v for k, v in base.items()
                            if k in self._TEXT_STYLE_FIELDS}
        self._write_named_text_styles(styles)
        self._populate_text_styles_combo()
        self.combo_text_style.setCurrentText(name)
        self.info_label.setText(f"Saved text style: {name}")

    def _apply_named_text_style(self):
        """Push the selected named style onto each selected text overlay.
        With no text selection, the style becomes the new default used
        for newly-created text overlays."""
        if not hasattr(self, "combo_text_style"):
            return
        name = self.combo_text_style.currentText().strip()
        if not name:
            return
        styles = self._load_named_text_styles()
        fields = styles.get(name)
        if not fields:
            self.info_label.setText(f"Style '{name}' not found")
            return
        sel = [it for it in self._scene.selectedItems()
               if isinstance(it, OverlayTextItem)]
        if sel:
            for it in sel:
                for k, v in fields.items():
                    setattr(it.overlay, k, v)
                # Rebuild the text item's rendered state from the new
                # field values. _apply_font handles font family, size,
                # weight, italic, kerning, line height.
                if hasattr(it, "_apply_font"):
                    it._apply_font()
                it.update()
            self._sync_overlays_to_asset()
            self.info_label.setText(
                f"Applied '{name}' to {len(sel)} text overlay(s)")
        else:
            # Set as default for future text overlays
            QSettings("DoxyEdit", "DoxyEdit").setValue(
                "studio_text_defaults",
                json.dumps(fields, ensure_ascii=False))
            self.info_label.setText(
                f"'{name}' is now the default text style")

    def _delete_named_text_style(self):
        """Remove the selected named style after a quick confirmation."""
        if not hasattr(self, "combo_text_style"):
            return
        name = self.combo_text_style.currentText().strip()
        if not name:
            return
        if QMessageBox.question(
                self, "Delete Text Style",
                f"Delete style '{name}'?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        styles = self._load_named_text_styles()
        if name in styles:
            del styles[name]
            self._write_named_text_styles(styles)
            self._populate_text_styles_combo()
            self.info_label.setText(f"Deleted text style: {name}")

    def _pick_text_color(self, text_item):
        """Open a color picker and apply to the given OverlayTextItem."""
        initial = QColor(text_item.overlay.color)
        color = QColorDialog.getColor(
            initial, self, "Text color",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not color.isValid():
            return
        new_color = color.name()
        self._push_overlay_attr(
            text_item, "color", new_color,
            apply_cb=lambda it, _v: it._apply_font(),
            description="Change text color",
        )
        self._sync_overlays_to_asset()
        self._add_recent_color(new_color)

    def _pick_text_background(self, text_item):
        """Color picker for text overlay's background rectangle fill."""
        initial = QColor(text_item.overlay.background_color or "#ffffff")
        color = QColorDialog.getColor(
            initial, self, "Text background color",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not color.isValid():
            return
        self._push_overlay_attr(
            text_item, "background_color", color.name(),
            apply_cb=lambda it, _v: it.update(),
            description="Change text background",
        )
        self._sync_overlays_to_asset()

    # Recent color history — session-wide ring buffer shown as swatches.
    # Persisted to QSettings so the palette carries across launches.
    _MAX_RECENT_COLORS = 8

    def _add_recent_color(self, hex_color: str):
        """Prepend a hex color to the recent list, capped and deduped."""
        if not hex_color:
            return
        qs = QSettings("DoxyEdit", "DoxyEdit")
        raw = qs.value("studio_recent_colors", "", type=str)
        recent = [c for c in raw.split(",") if c]
        # Move/insert to front
        recent = [hex_color] + [c for c in recent if c != hex_color]
        recent = recent[:self._MAX_RECENT_COLORS]
        qs.setValue("studio_recent_colors", ",".join(recent))
        self._refresh_recent_swatches()

    def _get_recent_colors(self) -> list:
        raw = QSettings("DoxyEdit", "DoxyEdit").value(
            "studio_recent_colors", "", type=str)
        return [c for c in raw.split(",") if c][:self._MAX_RECENT_COLORS]

    def _refresh_recent_swatches(self):
        """Redraw the recent-color swatch strip in the toolbar."""
        if not hasattr(self, "_swatch_buttons"):
            return
        colors = self._get_recent_colors()
        for i, btn in enumerate(self._swatch_buttons):
            if i < len(colors):
                # Background is runtime user data; border + disabled state
                # come from QSS (#studio_swatch rules in themes.py).
                btn.setStyleSheet(f"QPushButton#studio_swatch {{ background: {colors[i]}; }}")
                btn.setToolTip(colors[i])
                btn.setEnabled(True)
                btn.setProperty("color", colors[i])
            else:
                btn.setStyleSheet("")
                btn.setToolTip("")
                btn.setEnabled(False)
                btn.setProperty("color", "")

    def _swatch_context_menu(self, btn, pos):
        """Right-click a swatch: remove this color, or clear all recent colors."""
        color = btn.property("color") or ""
        if not color:
            # Empty slot — only offer Clear All
            menu = _themed_menu(btn)
            clear_all_act = menu.addAction("Clear All Recent Colors")
            chosen = menu.exec(btn.mapToGlobal(pos))
            if chosen is clear_all_act:
                QSettings("DoxyEdit", "DoxyEdit").setValue("studio_recent_colors", "")
                self._refresh_recent_swatches()
            return
        menu = _themed_menu(btn)
        remove_act = menu.addAction(f"Remove {color}")
        clear_all_act = menu.addAction("Clear All Recent Colors")
        chosen = menu.exec(btn.mapToGlobal(pos))
        qs = QSettings("DoxyEdit", "DoxyEdit")
        if chosen is remove_act:
            recent = [c for c in qs.value("studio_recent_colors", "", type=str).split(",")
                       if c and c != color]
            qs.setValue("studio_recent_colors", ",".join(recent))
            self._refresh_recent_swatches()
        elif chosen is clear_all_act:
            qs.setValue("studio_recent_colors", "")
            self._refresh_recent_swatches()

    def _on_swatch_clicked(self, btn):
        """Apply the swatch color to selected text / shape / arrow overlays."""
        hex_color = btn.property("color")
        if not hex_color:
            return
        applied = False
        for item in self._scene.selectedItems():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "color", hex_color,
                    apply_cb=lambda it, _v: it._apply_font(),
                    description="Apply swatch color")
                applied = True
            elif isinstance(item, OverlayArrowItem):
                self._push_overlay_attr(
                    item, "color", hex_color,
                    apply_cb=lambda it, _v: it.update(),
                    description="Apply swatch color")
                applied = True
            elif isinstance(item, OverlayShapeItem):
                self._push_overlay_attr(
                    item, "stroke_color", hex_color,
                    apply_cb=lambda it, _v: it.update(),
                    description="Apply swatch stroke")
                applied = True
        if applied:
            self._sync_overlays_to_asset()
            self.info_label.setText(f"Applied {hex_color}")

    def _apply_picked_color(self, color: QColor):
        """Apply eyedropper-sampled color: to selected text overlays if any,
        otherwise copy the hex to the system clipboard."""
        hex_ = color.name()  # "#rrggbb"
        # If there's a selected text overlay, set its color
        applied = False
        for it in self._scene.selectedItems():
            if isinstance(it, OverlayTextItem):
                self._push_overlay_attr(
                    it, "color", hex_,
                    apply_cb=lambda _it, _v: _it._apply_font(),
                    description="Eyedropper: set text color",
                )
                applied = True
        if applied:
            self._sync_overlays_to_asset()
            self.info_label.setText(f"Eyedropper: applied {hex_}")
        else:
            # No text selected — stash the color on clipboard for the user
            QApplication.clipboard().setText(hex_)
            self.info_label.setText(f"Eyedropper: {hex_} copied to clipboard")

    def _quick_add_bubble(self, kind: str = "speech_bubble"):
        """Drop a bubble + paired text at the last-known cursor position
        (or canvas center if the user hasn't hovered yet) and jump straight
        into text-edit mode. Bound to the `B` key for comic workflow.
        """
        if not self._asset or not self._pixmap_item:
            return
        last = self._last_cursor_scene_pos
        if last is None:
            pm = self._pixmap_item.pixmap()
            cx, cy = pm.width() / 2, pm.height() / 2
        else:
            cx, cy = last.x(), last.y()
        w, h = (260, 160) if kind != "burst" else (220, 220)
        x0 = int(cx - w / 2)
        y0 = int(cy - h / 2)
        link_id = f"bubble_text_{uuid.uuid4().hex[:8]}"
        bubble = CanvasOverlay(
            type="shape", label=kind.replace("_", " ").title(),
            shape_kind=kind,
            color="#000000",
            stroke_color="#000000", stroke_width=3,
            fill_color="#ffffff", opacity=1.0,
            x=x0, y=y0, shape_w=w, shape_h=h,
            tail_x=int(cx - w * 0.6) if kind != "burst" else 0,
            tail_y=int(cy + h * 0.8) if kind != "burst" else 0,
            linked_text_id=link_id,
        )
        self._asset.overlays.append(bubble)
        bubble_item = self._create_overlay_item(bubble)
        if bubble_item:
            bubble_item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(bubble_item)
        pad_x = int(w * 0.15)
        pad_y = int(h * 0.18)
        text_ov = CanvasOverlay(
            type="text",
            label=link_id,
            text="...",
            opacity=1.0,
            position="custom",
            x=x0 + pad_x,
            y=y0 + pad_y,
            text_width=w - 2 * pad_x,
            font_size=24,
            text_align="center",
            color="#000000",
        )
        for k, v in self._load_text_style_defaults().items():
            if k == "text_width":
                continue
            setattr(text_ov, k, v)
        self._asset.overlays.append(text_ov)
        text_item = self._create_overlay_item(text_ov)
        if text_item:
            text_item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(text_item)
            self._scene.clearSelection()
            text_item.setSelected(True)
            if hasattr(text_item, "setTextInteractionFlags"):
                text_item.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextEditorInteraction)
                text_item.setFocus()
                cursor = text_item.textCursor()
                cursor.select(cursor.SelectionType.Document)
                text_item.setTextCursor(cursor)
        self._rebuild_layer_panel()
        self._update_info()

    def _add_text_overlay(self, x: int = 50, y: int = 50, text_width: int = 0):
        """Add a text overlay at the given position.
        If text_width > 0, the text box wraps to that pixel width (comic
        bubble-style drag-to-size). 0 means auto-width.
        """
        if not self._asset:
            return
        ov = CanvasOverlay(
            type="text",
            label="Text",
            text="Your text",
            opacity=self.slider_opacity.value() / 100.0,
            position="custom",
            x=x, y=y,
            text_width=int(text_width) if text_width > 0 else 0,
        )
        # Apply the user's saved default text style, if one exists
        for k, v in self._load_text_style_defaults().items():
            # Don't let the default override an explicit drag-to-size width
            if k == "text_width" and text_width > 0:
                continue
            setattr(ov, k, v)
        self._asset.overlays.append(ov)
        item = self._create_overlay_item(ov)
        if item:
            item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(item)
            # Auto-select the new overlay + enter edit mode so the user can
            # start typing immediately. Critical for comic bubble flow.
            self._scene.clearSelection()
            item.setSelected(True)
            if hasattr(item, "setTextInteractionFlags"):
                item.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextEditorInteraction)
                item.setFocus()
                # Select the placeholder "Your text" so typing replaces it
                cursor = item.textCursor()
                cursor.select(cursor.SelectionType.Document)
                item.setTextCursor(cursor)
        # Layer panel needs to refresh so the new text row shows up. Prior
        # versions skipped this and the text was invisible in the list
        # until the user clicked something else that triggered a rebuild.
        self._rebuild_layer_panel()
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
                        # Cache the source pixmap on the item. The prior
                        # code called QPixmap(path) every tick = disk read
                        # + decode on every slider move (60+ per second).
                        src = getattr(it, "_source_pixmap", None)
                        if src is None or src.isNull():
                            src = QPixmap(it.overlay.image_path)
                            it._source_pixmap = src
                        if not src.isNull():
                            pm = src.scaledToWidth(
                                target_w, Qt.TransformationMode.SmoothTransformation
                            )
                            it.setPixmap(pm)
                self._push_overlay_attr(
                    item, "scale", scale,
                    apply_cb=_apply_scale,
                    description="Change scale",
                )
            elif isinstance(item, OverlayTextItem):
                # Scale text by multiplying the stored font point size.
                # Snapshots baseline once so repeated slider drags don't
                # compound.
                if not hasattr(item, "_scale_baseline_font"):
                    item._scale_baseline_font = item.overlay.font_size
                target = max(4, int(item._scale_baseline_font * scale))
                def _apply_text_scale(it, v, _target=target):
                    it.overlay.font_size = _target
                    f = it.font()
                    f.setPointSize(_target)
                    it.setFont(f)
                    it.update()
                self._push_overlay_attr(
                    item, "scale", scale,
                    apply_cb=_apply_text_scale,
                    description="Scale text",
                )
            elif isinstance(item, (OverlayShapeItem, OverlayArrowItem)):
                # Snapshot base dimensions on first drag of this session
                # so subsequent slider moves scale from the same baseline
                # rather than compounding each previous scale.
                if not hasattr(item, "_scale_baseline_w"):
                    item._scale_baseline_w = getattr(item.overlay, "shape_w", 0)
                    item._scale_baseline_h = getattr(item.overlay, "shape_h", 0)
                    item._scale_baseline_end = (
                        getattr(item.overlay, "end_x", 0),
                        getattr(item.overlay, "end_y", 0))
                def _apply_geom_scale(it, v, _self=self):
                    if isinstance(it, OverlayShapeItem):
                        it.overlay.shape_w = max(4, int(it._scale_baseline_w * v))
                        it.overlay.shape_h = max(4, int(it._scale_baseline_h * v))
                        it.prepareGeometryChange()
                        it.update()
                    elif isinstance(it, OverlayArrowItem):
                        bx, by = it._scale_baseline_end
                        cx = it.overlay.x + (bx - it.overlay.x) * v
                        cy = it.overlay.y + (by - it.overlay.y) * v
                        it.overlay.end_x = cx
                        it.overlay.end_y = cy
                        it.prepareGeometryChange()
                        it.update()
                self._push_overlay_attr(
                    item, "scale", scale,
                    apply_cb=_apply_geom_scale,
                    description="Scale geometry",
                )

    def _sync_shape_controls_visibility(self):
        """Show / hide / rebuild the Shape Controls popup tracking the
        current selection. When a speech/thought bubble is selected the
        Text Controls popup (via _sync_text_controls_visibility) and
        this popup both appear so the user can tweak both halves of
        the merged type at once."""
        if not hasattr(self, "_shape_controls_dlg"):
            return
        dlg = self._shape_controls_dlg
        sel = self._scene.selectedItems()
        target = None
        for it in sel:
            if isinstance(it, (OverlayShapeItem, OverlayArrowItem, OverlayImageItem)):
                target = it
                break
        if target is not None:
            # HARD EARLY-OUT: if popup already visible AND tracking the
            # same target, do nothing. No rebuild_for, no setStyleSheet,
            # no raise_. All of these cause visible flashing when fired
            # on every selection sync during drag. The popup stays open
            # and re-rebuilds ONLY when the target changes to a different
            # item, which is a structural change — not per-drag-frame.
            prev_target = getattr(dlg, "_last_target_id", None)
            if dlg.isVisible() and prev_target == id(target):
                return
            dlg.rebuild_for(target)
            dlg._last_target_id = id(target)
            win = self.window()
            if win is not None:
                current = win.styleSheet()
                prev = getattr(dlg, "_cached_ss", None)
                if prev != current:
                    dlg.setStyleSheet(current)
                    dlg._cached_ss = current
            if not dlg.isVisible():
                dlg.show()
                if win is not None and hasattr(win, "_theme_dialog_titlebar"):
                    if not getattr(dlg, "_titlebar_themed", False):
                        win._theme_dialog_titlebar(dlg)
                        dlg._titlebar_themed = True
                if not getattr(dlg, "_positioned_once", False):
                    gv = self._view
                    if gv is not None and gv.isVisible():
                        avail = QApplication.primaryScreen().availableGeometry()
                        g = dlg.frameGeometry()
                        if not avail.intersects(g):
                            gp = gv.mapToGlobal(gv.viewport().rect().topRight())
                            dlg.move(
                                gp.x() - max(dlg.width(), 340) - 12,
                                gp.y() + 460)
                    dlg._positioned_once = True
        else:
            if dlg.isVisible():
                dlg.hide()

    def _sync_text_controls_visibility(self):
        """Show the floating text-controls dialog only when text context is
        active (text tool selected or a text overlay selected). Position
        above the canvas so it doesn't block the cursor. Robust against
        off-screen restored geometry, hidden parents, and stacking races
        so the dialog reliably appears when the user switches to text."""
        if not hasattr(self, "_text_controls_dlg"):
            return
        active_tool = getattr(self._scene, "current_tool", None)
        has_text_tool = active_tool == StudioTool.TEXT_OVERLAY
        sel = self._scene.selectedItems()
        has_text_selected = any(
            isinstance(it, OverlayTextItem) for it in sel)
        # A bubble with a linked text counts too - the user wants to
        # tweak the text's font / color without first clicking inside.
        has_bubble_with_text = any(
            (isinstance(it, OverlayShapeItem)
             and getattr(it.overlay, "linked_text_id", ""))
            for it in sel)
        if has_bubble_with_text and not has_text_selected:
            # Auto-select the paired text so the popup operates on it.
            for it in sel:
                if (isinstance(it, OverlayShapeItem)
                        and it.overlay.linked_text_id):
                    for other in self._overlay_items:
                        if (isinstance(other, OverlayTextItem)
                                and other.overlay.label
                                    == it.overlay.linked_text_id
                                and not other.isSelected()):
                            other.setSelected(True)
                            has_text_selected = True
                            break
                    break
        dlg = self._text_controls_dlg
        if has_text_tool or has_text_selected:
            # Early-out: if the popup is visible AND its center is on a
            # screen, do nothing. No setStyleSheet, no theme_dialog_
            # titlebar, no move, no raise. (Those ops on every selection
            # sync caused flash / re-focus / re-layout while the user was
            # working.) But if isVisible() is True yet the dialog sits
            # off-screen (stale geometry from a prior monitor layout),
            # fall through so the reposition logic below can rescue it.
            if dlg.isVisible():
                screen = QApplication.primaryScreen()
                avail = screen.availableGeometry() if screen else None
                if avail is None or avail.contains(dlg.frameGeometry().center()):
                    return
                # Off-screen: drop _positioned_once so the reposition
                # block below moves it back into view.
                dlg._positioned_once = False
            win = self.window()
            if win is not None:
                current = win.styleSheet()
                prev = getattr(dlg, "_cached_ss", None)
                if prev != current:
                    dlg.setStyleSheet(current)
                    dlg._cached_ss = current
            dlg.show()
            if win is not None and hasattr(win, "_theme_dialog_titlebar"):
                if not getattr(dlg, "_titlebar_themed", False):
                    win._theme_dialog_titlebar(dlg)
                    dlg._titlebar_themed = True
            # First-show reposition. Also re-trigger when the dialog is
            # mostly off-screen (e.g. a saved geometry from a prior
            # monitor layout). Just checking intersects() returned True
            # for windows that were 99% off-screen, so the user opened a
            # text and saw nothing - the dialog WAS shown, just somewhere
            # they couldn't see it.
            screen = QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                g = dlg.frameGeometry()
                center_on_screen = avail.contains(g.center())
                needs_reposition = (
                    g.width() < 50 or g.height() < 50
                    or not center_on_screen
                    or not getattr(dlg, "_positioned_once", False)
                )
                if needs_reposition:
                    gv = self._view
                    if gv is not None and gv.isVisible():
                        gp = gv.mapToGlobal(gv.viewport().rect().topRight())
                        target_x = gp.x() - max(dlg.width(), 360) - 12
                        target_y = gp.y() + 12
                    else:
                        target_x = avail.right() - 380
                        target_y = avail.top() + 80
                    target_x = max(avail.left() + 10,
                                    min(avail.right() - 200, target_x))
                    target_y = max(avail.top() + 10,
                                    min(avail.bottom() - 200, target_y))
                    dlg.move(target_x, target_y)
                dlg._positioned_once = True
            dlg.raise_()
        else:
            if dlg.isVisible():
                dlg.hide()

    def _on_selection_changed(self):
        # Group-aware selection propagation: when a user clicks any
        # grouped overlay, auto-select every sibling in the same group.
        # Guard against re-entry by tracking a sentinel so our own
        # setSelected calls don't re-trigger this handler.
        if not self._propagating_group_sel:
            try:
                self._propagating_group_sel = True
                sel = self._scene.selectedItems()
                sel_gids = {
                    it.overlay.group_id for it in sel
                    if hasattr(it, "overlay") and it.overlay.group_id
                }
                if sel_gids:
                    for it in self._overlay_items:
                        if (hasattr(it, "overlay")
                                and it.overlay.group_id in sel_gids
                                and not it.isSelected()):
                            it.setSelected(True)
            finally:
                self._propagating_group_sel = False
        # Text-controls popup follows selection
        self._sync_text_controls_visibility()
        # Shape-controls popup follows selection for shapes / arrows
        self._sync_shape_controls_visibility()
        # Mirror the canvas selection into the layer panel so the user
        # can see which row corresponds to what they just clicked.
        self._sync_layer_panel_selection()
        # Quickbar mirrors the first selected overlay's state so the
        # duplicated toolbar controls actually reflect what's about to
        # be modified.
        self._sync_quickbar()
        # Dim non-selected overlays if the setting is on.
        self._apply_dim_nonselected()
        # Total selected (overlays + censors + crops + notes) for status bar
        all_sel = self._scene.selectedItems()
        total = len(all_sel)
        if hasattr(self, "_selection_label"):
            self._selection_label.setText(
                "0 selected" if total == 0 else
                "1 selected" if total == 1 else
                f"{total} selected")
        # Geometry readout — shown only when exactly one item is selected
        if hasattr(self, "_geom_label"):
            if total == 1:
                it = all_sel[0]
                rect = it.sceneBoundingRect()
                self._geom_label.setText(
                    f"| {int(rect.x())},{int(rect.y())}  "
                    f"{int(rect.width())}×{int(rect.height())}"
                )
            else:
                self._geom_label.setText("")

        # Filter from the already-computed all_sel rather than calling
        # selectedItems() again — selection hasn't changed between the
        # two reads (the sync calls above only read, never write).
        sel = [i for i in all_sel
               if isinstance(i, (OverlayImageItem, OverlayTextItem))]
        if not sel:
            self._props_row.setEnabled(False)
            return

        item = sel[0]
        ov = item.overlay
        self._props_row.setEnabled(True)

        # Block signals during bulk update
        _bulk = [self.slider_opacity, self.slider_scale, self.combo_position,
                  self.font_combo, self.slider_font_size, self.btn_bold,
                  self.btn_italic, self.slider_kerning, self.slider_line_height,
                  self.slider_rotation, self.slider_text_width, self.slider_outline]
        if hasattr(self, "btn_underline"):
            _bulk.append(self.btn_underline)
        if hasattr(self, "btn_strikethrough"):
            _bulk.append(self.btn_strikethrough)
        for _bname in ("btn_align_left", "btn_align_center", "btn_align_right"):
            if hasattr(self, _bname):
                _bulk.append(getattr(self, _bname))
        for w in _bulk:
            w.blockSignals(True)

        # Push the selected text overlay's content into the mini editor
        # in the Text Controls popup so the user can type to it directly.
        if hasattr(self, "_tc_content_edit"):
            self._tc_content_syncing = True
            try:
                if self._tc_content_edit.toPlainText() != ov.text:
                    self._tc_content_edit.setPlainText(ov.text or "")
            finally:
                self._tc_content_syncing = False
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
        if hasattr(self, "btn_underline"):
            self.btn_underline.setChecked(ov.underline)
        if hasattr(self, "btn_strikethrough"):
            self.btn_strikethrough.setChecked(
                ov.strikethrough)
        if hasattr(self, "btn_align_left"):
            ta = ov.text_align
            self.btn_align_left.setChecked(ta == "left")
            self.btn_align_center.setChecked(ta == "center")
            self.btn_align_right.setChecked(ta == "right")
        # Drop-shadow toggle + offset slider sync
        if hasattr(self, "btn_shadow_toggle"):
            self.btn_shadow_toggle.blockSignals(True)
            self.btn_shadow_toggle.setChecked(bool(ov.shadow_color))
            self.btn_shadow_toggle.blockSignals(False)
        if hasattr(self, "slider_shadow_offset"):
            self.slider_shadow_offset.blockSignals(True)
            self.slider_shadow_offset.setValue(int(ov.shadow_offset or 0))
            self.slider_shadow_offset.blockSignals(False)
        if hasattr(self, "slider_shadow_blur"):
            self.slider_shadow_blur.blockSignals(True)
            self.slider_shadow_blur.setValue(int(ov.shadow_blur or 0))
            self.slider_shadow_blur.blockSignals(False)
        if hasattr(self, "btn_shadow_color"):
            self.btn_shadow_color.setSwatchColor(
                ov.shadow_color or "#000000")
        self.slider_kerning.setValue(int(ov.letter_spacing))
        self.slider_line_height.setValue(int(getattr(ov, 'line_height', 1.2) * 100))
        self.slider_rotation.setValue(int(ov.rotation))
        self.slider_text_width.setValue(ov.text_width)
        self.slider_outline.setValue(ov.stroke_width)
        # Keep the color-swatch buttons in sync with the selected overlay
        # so the user can always see what color will be changed by a click.
        if hasattr(self.btn_color, "setSwatchColor"):
            self.btn_color.setSwatchColor(ov.color or "#000000")
        if hasattr(self.btn_outline_color, "setSwatchColor"):
            self.btn_outline_color.setSwatchColor(ov.stroke_color or "#000000")

        for w in _bulk:
            w.blockSignals(False)

    # ---- drag-drop from tray ----

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            handled = False
            for url in event.mimeData().urls():
                if not url.isLocalFile():
                    continue
                path = url.toLocalFile()
                # Scene center is a reasonable default for widget-level drops
                # that didn't hit the canvas view directly.
                center = self._scene.sceneRect().center()
                self._on_file_dropped(path, center)
                handled = True
            if handled:
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return
        super().dropEvent(event)

    def _on_file_dropped(self, path: str, scene_pos):
        """Add dropped file as overlay. If no asset is loaded yet, try to
        resolve the dropped path to a project asset and load it as the
        base image instead."""
        ext = Path(path).suffix.lower()
        if not self._asset:
            # No base loaded: resolve to project asset and load it
            if self._project is not None:
                norm = path.replace("\\", "/").lower()
                for a in self._project.assets:
                    ap = (a.source_path or "").replace("\\", "/").lower()
                    if ap == norm:
                        self.load_asset(a)
                        return
            # Fall back to loading directly from disk so drops from outside
            # the project (or when project lookup fails) still do something.
            if ext in ('.png', '.jpg', '.jpeg', '.webp', '.psd', '.psb',
                       '.tif', '.tiff', '.bmp'):
                try:
                    stub = Asset(
                        id=Path(path).stem,
                        source_path=path,
                        source_folder=str(Path(path).parent),
                    )
                    self.load_asset(stub)
                except Exception:
                    pass
            return
        if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
            return
        # Drop at 1:1 pixel size: read the dropped image's native width and
        # set ov.scale so target_w == native_w when _create_overlay_item
        # rescales it (target_w = base_w * scale). Without this the slider's
        # scale value (default 0.2 = 20% of base width) shrinks every drop.
        scale = self.slider_scale.value() / 100.0
        if self._pixmap_item:
            base_w = self._pixmap_item.pixmap().width()
            try:
                drop_pm = QPixmap(path)
                if not drop_pm.isNull() and base_w > 0:
                    scale = drop_pm.width() / base_w
            except Exception:
                pass
        ov = CanvasOverlay(
            type="watermark", label=Path(path).stem, image_path=path,
            position="custom", x=int(scene_pos.x()), y=int(scene_pos.y()),
            opacity=self.slider_opacity.value() / 100.0,
            scale=scale,
        )
        self._add_overlay_image(ov)
        self._sync_overlays_to_asset()
        self._rebuild_layer_panel()

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
                if isinstance(i, (OverlayImageItem, OverlayTextItem,
                                   OverlayArrowItem))]

    def _all_selected_moveable(self):
        """Everything that has a sceneBoundingRect + overlay.x/y we can mutate,
        including shapes and text/image overlays. Arrows are skipped (they
        track endpoints, not a top-left), as are notes/censors/crops whose
        position semantics differ."""
        return [i for i in self._scene.selectedItems()
                if isinstance(i, (OverlayImageItem, OverlayTextItem,
                                   OverlayShapeItem))]

    def _align_selected(self, mode: str):
        """Align / distribute the currently selected moveable overlays.

        Modes: ``left``, ``right``, ``hcenter``, ``top``, ``bottom``,
        ``vcenter``, ``dist_h``, ``dist_v``. 1 item aligns to the canvas;
        2+ items align to their union rect; distribute needs 3+. Operates
        on sceneBoundingRect and writes back through the overlay's x / y
        (or shape_w/shape_h center for shapes) so undo / serialization
        stays consistent."""
        items = self._all_selected_moveable()
        if not items:
            return
        rects = [(it, it.sceneBoundingRect()) for it in items]
        if mode.startswith("dist_") and len(items) < 3:
            self.info_label.setText("Distribute needs 3 or more items")
            return
        if len(items) == 1 and self._pixmap_item:
            # Single-item align references the canvas rect, not the item.
            pm = self._pixmap_item.pixmap()
            minx, miny = 0, 0
            maxx = pm.width()
            maxy = pm.height()
        else:
            minx = min(r.left() for _, r in rects)
            maxx = max(r.right() for _, r in rects)
            miny = min(r.top() for _, r in rects)
            maxy = max(r.bottom() for _, r in rects)
        cx = (minx + maxx) / 2
        cy = (miny + maxy) / 2

        def _shift(it, dx, dy):
            """Move an overlay by the given scene-px delta."""
            it.overlay.x += int(dx)
            it.overlay.y += int(dy)
            if isinstance(it, OverlayShapeItem):
                # Also shift the tail if present so the bubble stays coherent
                if it.overlay.tail_x or it.overlay.tail_y:
                    it.overlay.tail_x += int(dx)
                    it.overlay.tail_y += int(dy)
                # Paired-text hop along for linked bubbles
                if it.overlay.linked_text_id:
                    for other in self._overlay_items:
                        if (isinstance(other, OverlayTextItem)
                                and other.overlay.label == it.overlay.linked_text_id):
                            other.overlay.x += int(dx)
                            other.overlay.y += int(dy)
                            other.setPos(other.overlay.x, other.overlay.y)
                            break
                it.prepareGeometryChange()
                it.update()
            else:
                it.setPos(it.overlay.x, it.overlay.y)

        if mode == "left":
            for it, r in rects:
                _shift(it, minx - r.left(), 0)
        elif mode == "right":
            for it, r in rects:
                _shift(it, maxx - r.right(), 0)
        elif mode == "hcenter":
            for it, r in rects:
                _shift(it, cx - r.center().x(), 0)
        elif mode == "top":
            for it, r in rects:
                _shift(it, 0, miny - r.top())
        elif mode == "bottom":
            for it, r in rects:
                _shift(it, 0, maxy - r.bottom())
        elif mode == "vcenter":
            for it, r in rects:
                _shift(it, 0, cy - r.center().y())
        elif mode == "dist_h":
            # Sort by center x; keep leftmost / rightmost pinned, distribute
            # the middle items so edge-to-edge spacing is equal.
            rects.sort(key=lambda ir: ir[1].center().x())
            first_cx = rects[0][1].center().x()
            last_cx = rects[-1][1].center().x()
            step = (last_cx - first_cx) / (len(rects) - 1)
            for i, (it, r) in enumerate(rects[1:-1], start=1):
                target_cx = first_cx + step * i
                _shift(it, target_cx - r.center().x(), 0)
        elif mode == "dist_v":
            rects.sort(key=lambda ir: ir[1].center().y())
            first_cy = rects[0][1].center().y()
            last_cy = rects[-1][1].center().y()
            step = (last_cy - first_cy) / (len(rects) - 1)
            for i, (it, r) in enumerate(rects[1:-1], start=1):
                target_cy = first_cy + step * i
                _shift(it, 0, target_cy - r.center().y())
        self._sync_overlays_to_asset()
        self.info_label.setText(f"Aligned: {mode}")

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

    def _on_underline_changed(self):
        checked = self.btn_underline.isChecked()
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "underline", checked,
                    apply_cb=lambda it, _v: it._apply_font(),
                    description=("Underline on" if checked else "Underline off"),
                )
        self._sync_overlays_to_asset()

    def _on_strikethrough_changed(self):
        checked = self.btn_strikethrough.isChecked()
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "strikethrough", checked,
                    apply_cb=lambda it, _v: it._apply_font(),
                    description=("Strike on" if checked else "Strike off"),
                )
        self._sync_overlays_to_asset()

    def _on_text_align_changed(self, align: str):
        """Exclusive text alignment (left / center / right). Updates
        every selected text overlay and keeps the three buttons in a
        radio-like state."""
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "text_align", align,
                    apply_cb=lambda it, _v: it._apply_font(),
                    description=f"Align text {align}",
                )
        # Enforce radio exclusivity
        for btn, ali in (
                (self.btn_align_left, "left"),
                (self.btn_align_center, "center"),
                (self.btn_align_right, "right")):
            btn.blockSignals(True)
            btn.setChecked(ali == align)
            btn.blockSignals(False)
        self._sync_overlays_to_asset()

    def _on_color_pick(self):
        items = self._selected_overlay_items()
        if not items:
            return
        current = QColor(items[0].overlay.color)
        color = QColorDialog.getColor(current, self, "Overlay Color")
        if color.isValid():
            self._apply_text_color(color.name())

    def _on_shadow_toggled(self, checked: bool):
        """Text Controls 'Drop Shadow' toggle. Off = clear color /
        offset / blur fields; On = set sensible defaults (black, 3px,
        3 blur)."""
        sel = [it for it in self._scene.selectedItems()
               if isinstance(it, OverlayTextItem)]
        if not sel:
            return
        for it in sel:
            ov = it.overlay
            if checked:
                if not ov.shadow_color:
                    ov.shadow_color = "#000000"
                if ov.shadow_offset == 0:
                    ov.shadow_offset = 3
                if ov.shadow_blur == 0:
                    ov.shadow_blur = 3
            else:
                ov.shadow_color = ""
                ov.shadow_offset = 0
                ov.shadow_blur = 0
            if hasattr(it, "_apply_font"):
                it._apply_font()
            it.update()
        # Mirror offset slider value
        if checked and hasattr(self, "slider_shadow_offset"):
            self.slider_shadow_offset.blockSignals(True)
            self.slider_shadow_offset.setValue(3)
            self.slider_shadow_offset.blockSignals(False)
        self._sync_overlays_to_asset()

    def _refresh_text_cache(self, it):
        """Force OverlayTextItem to invalidate its DeviceCoordinateCache so
        attribute changes that affect paint output actually become visible.
        Without this, slider ticks set the field but the cached pixmap keeps
        rendering the old style."""
        it.prepareGeometryChange()
        it.setCacheMode(QGraphicsTextItem.CacheMode.NoCache)
        it.setCacheMode(QGraphicsTextItem.CacheMode.DeviceCoordinateCache)
        it.update()

    def _on_shadow_offset_changed(self, value: int):
        sel = [it for it in self._scene.selectedItems()
               if isinstance(it, OverlayTextItem)]
        if not sel:
            return
        for it in sel:
            it.overlay.shadow_offset = value
            if value > 0 and not it.overlay.shadow_color:
                it.overlay.shadow_color = "#000000"
            if hasattr(it, "_apply_font"):
                it._apply_font()
            self._refresh_text_cache(it)
        self._sync_overlays_to_asset()

    def _on_shadow_blur_changed(self, value: int):
        sel = [it for it in self._scene.selectedItems()
               if isinstance(it, OverlayTextItem)]
        if not sel:
            return
        for it in sel:
            it.overlay.shadow_blur = value
            if value > 0 and not it.overlay.shadow_color:
                it.overlay.shadow_color = "#000000"
            if hasattr(it, "_apply_font"):
                it._apply_font()
            self._refresh_text_cache(it)
        self._sync_overlays_to_asset()

    def _pick_shadow_color(self):
        """Shadow color button click -> QColorDialog -> apply to selection."""
        sel = [it for it in self._scene.selectedItems()
               if isinstance(it, OverlayTextItem)]
        if not sel:
            return
        cur = QColor(sel[0].overlay.shadow_color or "#000000")
        c = QColorDialog.getColor(cur, self, "Shadow color",
                                    QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not c.isValid():
            return
        self._apply_shadow_color(c.name())

    def _apply_shadow_color(self, hex_color: str):
        col = QColor(hex_color)
        if not col.isValid():
            return
        sel = [it for it in self._scene.selectedItems()
               if isinstance(it, OverlayTextItem)]
        if not sel:
            return
        if hasattr(self, "btn_shadow_color"):
            self.btn_shadow_color.setSwatchColor(col)
        for it in sel:
            it.overlay.shadow_color = col.name()
            if it.overlay.shadow_offset == 0 and it.overlay.shadow_blur == 0:
                it.overlay.shadow_offset = 3
                if hasattr(self, "slider_shadow_offset"):
                    self.slider_shadow_offset.blockSignals(True)
                    self.slider_shadow_offset.setValue(3)
                    self.slider_shadow_offset.blockSignals(False)
            if hasattr(it, "_apply_font"):
                it._apply_font()
            it.update()
        self._add_recent_color(col.name())
        self._sync_overlays_to_asset()

    def _update_tc_count(self):
        """Refresh the chars / words counter under the Text Controls
        mini editor. Runs on every textChanged tick; cheap."""
        if not hasattr(self, "_tc_count_label"):
            return
        txt = self._tc_content_edit.toPlainText()
        chars = len(txt)
        # Matches Python's default whitespace split -> ignores extra
        # spaces, treats newlines as separators.
        words = len(txt.split()) if txt.strip() else 0
        lines = txt.count("\n") + 1 if txt else 0
        self._tc_count_label.setText(
            f"{chars} chars  /  {words} words  /  {lines} lines")

    def _on_tc_content_changed(self):
        """Live-edit the selected text overlay's content from the mini
        editor in the Text Controls popup. Blocks re-entry so our own
        programmatic setPlainText during selection-change doesn't echo
        back into the selected overlay."""
        if self._tc_content_syncing:
            return
        sel = [it for it in self._scene.selectedItems()
               if isinstance(it, OverlayTextItem)]
        if not sel:
            return
        txt = self._tc_content_edit.toPlainText()
        for it in sel:
            if it.overlay.text != txt:
                it.overlay.text = txt
                it.setPlainText(txt)
                if hasattr(it, "_apply_font"):
                    it._apply_font()
        self._sync_overlays_to_asset()

    def _qp_toggle_lock(self):
        """Lock / unlock every selected overlay. Locked items can't be
        moved or re-selected via canvas click (layer-panel still reaches
        them). Mirrors ov.locked + ItemIsMovable / ItemIsSelectable."""
        sel = [it for it in self._scene.selectedItems() if hasattr(it, "overlay")]
        if not sel:
            return
        locked = self._qp_lock.isChecked()
        for it in sel:
            it.overlay.locked = locked
            it.setFlag(it.GraphicsItemFlag.ItemIsMovable, not locked)
            it.setFlag(it.GraphicsItemFlag.ItemIsSelectable, not locked)
        self._sync_overlays_to_asset()
        self.info_label.setText(
            "Locked" if locked else "Unlocked")

    def _qp_toggle_visibility(self):
        """Hide / show every selected overlay."""
        sel = [it for it in self._scene.selectedItems() if hasattr(it, "overlay")]
        if not sel:
            return
        hidden = self._qp_hide.isChecked()
        for it in sel:
            it.overlay.enabled = not hidden
            it.setVisible(not hidden)
        self._sync_overlays_to_asset()
        self.info_label.setText("Hidden" if hidden else "Visible")

    def _qp_fit_selection(self):
        """Quickbar Fit-Sel button -> fitInView on the union bounding
        rect of the selection. Mirror of Shift+F. No-op when nothing
        is selected."""
        sel = self._scene.selectedItems()
        if not sel:
            self.info_label.setText("Nothing selected")
            return
        bounds = sel[0].sceneBoundingRect()
        for it in sel[1:]:
            bounds = bounds.united(it.sceneBoundingRect())
        bounds.adjust(-40, -40, 40, 40)
        self._view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        if hasattr(self, "_zoom_label"):
            self._zoom_label.setText(
                f"{int(self._view.transform().m11() * 100)}%")
        if self._canvas_wrap is not None:
            self._canvas_wrap.refresh()

    def _qp_group_selection(self):
        """Quickbar Group button - assigns a fresh group_id to every
        selected overlay. Mirrors Ctrl+G."""
        sel = [it for it in self._scene.selectedItems() if hasattr(it, "overlay")]
        if len(sel) < 2:
            self.info_label.setText("Group needs 2+ overlays")
            return
        gid = f"g_{uuid.uuid4().hex[:8]}"
        for it in sel:
            it.overlay.group_id = gid
        self._sync_overlays_to_asset()
        self.info_label.setText(f"Grouped {len(sel)} overlays")

    def _qp_ungroup_selection(self):
        """Quickbar Ungroup button - clears group_id on selected
        overlays. Mirrors Ctrl+Shift+G."""
        sel = [it for it in self._scene.selectedItems() if hasattr(it, "overlay")]
        cleared = 0
        for it in sel:
            if getattr(it.overlay, "group_id", ""):
                it.overlay.group_id = ""
                cleared += 1
        if cleared:
            self._sync_overlays_to_asset()
            self.info_label.setText(f"Ungrouped {cleared} overlays")

    def _qp_flip(self, axis: str):
        """Flip selected overlays horizontally or vertically. axis='h'
        flips flip_h; 'v' flips flip_v. Image / text honor via
        _apply_flip / _apply_flip_text; shapes flip via QTransform
        scale."""
        sel = [it for it in self._scene.selectedItems() if hasattr(it, "overlay")]
        if not sel:
            return
        for it in sel:
            ov = it.overlay
            if axis == "h":
                ov.flip_h = not ov.flip_h
            else:
                ov.flip_v = not ov.flip_v
            if hasattr(it, "_apply_flip"):
                it._apply_flip()
            elif hasattr(it, "_apply_flip_text"):
                it._apply_flip_text()
            elif isinstance(it, OverlayShapeItem):
                cx = ov.x + ov.shape_w / 2
                cy = ov.y + ov.shape_h / 2
                it.setTransformOriginPoint(cx, cy)
                sx = -1.0 if ov.flip_h else 1.0
                sy = -1.0 if ov.flip_v else 1.0
                t = QTransform()
                if ov.skew_x or ov.skew_y:
                    t.shear(math.tan(math.radians(ov.skew_x)),
                             math.tan(math.radians(ov.skew_y)))
                t.scale(sx, sy)
                it.setTransform(t)
                it.prepareGeometryChange()
                it.update()
            else:
                it.update()
        self._sync_overlays_to_asset()
        self.info_label.setText(f"Flipped {axis.upper()}")

    def _qp_snap_to_pixel(self):
        """Snap every selected overlay's x/y/w/h to integer pixels.
        Kills sub-pixel jitter that drift-accumulates across a long
        editing session."""
        sel = [it for it in self._scene.selectedItems() if hasattr(it, "overlay")]
        if not sel:
            return
        for it in sel:
            ov = it.overlay
            ov.x = int(round(ov.x))
            ov.y = int(round(ov.y))
            if hasattr(ov, "shape_w"):
                ov.shape_w = int(round(ov.shape_w))
                ov.shape_h = int(round(ov.shape_h))
            if hasattr(ov, "end_x"):
                ov.end_x = int(round(ov.end_x))
                ov.end_y = int(round(ov.end_y))
            if hasattr(ov, "tail_x"):
                ov.tail_x = int(round(ov.tail_x))
                ov.tail_y = int(round(ov.tail_y))
            if hasattr(it, "setPos"):
                it.setPos(ov.x, ov.y)
            it.prepareGeometryChange() if hasattr(it, "prepareGeometryChange") else None
            it.update()
        self._sync_overlays_to_asset()
        self.info_label.setText(f"Snapped {len(sel)} to pixels")

    def _qp_pick_fill_color(self):
        """Quickbar fill-swatch click -> open QColorDialog. When
        something is selected, apply to EVERY selected overlay (text
        color / shape fill / arrow color). When nothing is selected,
        still open the dialog and persist the chosen color as the
        DEFAULT fill for new shapes + text so the swatch is never a
        dead click."""
        sel = self._scene.selectedItems()
        overlay_sel = [it for it in sel if hasattr(it, "overlay")]
        if overlay_sel:
            first = overlay_sel[0].overlay
            if isinstance(overlay_sel[0], OverlayShapeItem):
                cur_hex = first.fill_color or first.color or "#ffffff"
            else:
                cur_hex = first.color or "#000000"
        else:
            qs = QSettings("DoxyEdit", "DoxyEdit")
            cur_hex = qs.value(
                "studio_shape_fill_color", "#ffffff", type=str) or "#ffffff"
        col = QColorDialog.getColor(
            QColor(cur_hex), self, "Fill / text color",
            QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not col.isValid():
            return
        # Dispatch per type so the 'fill' concept maps correctly.
        for it in overlay_sel:
            ov = it.overlay
            if isinstance(it, OverlayShapeItem):
                ov.fill_color = col.name()
                it.update()
            elif isinstance(it, OverlayTextItem):
                ov.color = col.name()
                if hasattr(it, "_apply_font"):
                    it._apply_font()
            elif isinstance(it, OverlayArrowItem):
                ov.color = col.name()
                it.update()
            elif isinstance(it, OverlayImageItem):
                ov.color = col.name()
                it.update()
        self._qp_fill.setSwatchColor(col)
        self._add_recent_color(col.name())
        if not overlay_sel:
            # Nothing to mutate — persist as the default fill so the
            # next shape / text drawn picks up this color.
            qs = QSettings("DoxyEdit", "DoxyEdit")
            qs.setValue("studio_shape_fill_color", col.name())
            if hasattr(self, "info_label"):
                self.info_label.setText(
                    f"Default fill color set to {col.name()}")
        else:
            self._sync_overlays_to_asset()

    def _qp_pick_stroke_color(self):
        """Quickbar outline-swatch click -> dialog -> stroke_color on
        every selected overlay that supports it."""
        sel = self._scene.selectedItems()
        overlay_sel = [it for it in sel if hasattr(it, "overlay")]
        if not overlay_sel:
            return
        cur_hex = overlay_sel[0].overlay.stroke_color or "#000000"
        col = QColorDialog.getColor(
            QColor(cur_hex), self, "Stroke / outline color",
            QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not col.isValid():
            return
        for it in overlay_sel:
            ov = it.overlay
            ov.stroke_color = col.name()
            if isinstance(it, OverlayTextItem):
                if ov.stroke_width == 0:
                    ov.stroke_width = 2
                if hasattr(it, "_apply_font"):
                    it._apply_font()
            it.update()
        self._qp_outline.setSwatchColor(col)
        self._add_recent_color(col.name())
        self._sync_overlays_to_asset()

    def _apply_dim_nonselected(self):
        """Honor the 'dim non-selected overlays' view setting. When on,
        every overlay / censor that isn't currently selected is rendered
        at 40% opacity; selected items keep their stored opacity. Flips
        back to full opacity when no selection exists or the setting is
        off. Doesn't mutate CanvasOverlay.opacity - just the live
        QGraphicsItem display opacity.

        The QSettings.value() call was hitting the registry on every
        selection change (and selection changes fire during drag). Cache
        the setting on the editor; it's invalidated by the settings
        dialog via _invalidate_dim_cache() after a user toggle.
        """
        enabled = getattr(self, "_dim_nonselected_cached", None)
        if enabled is None:
            enabled = QSettings("DoxyEdit", "DoxyEdit").value(
                "studio_dim_nonselected", False, type=bool)
            self._dim_nonselected_cached = enabled
        sel = set(self._scene.selectedItems()) if self._scene else set()
        has_sel = bool(sel)
        for it in self._overlay_items + list(self._censor_items):
            ov = getattr(it, "overlay", None)
            # Censor items don't carry an overlay, so ov can be None;
            # default their baseline opacity to 1.0 (no transparency).
            base_op = ov.opacity if ov is not None else 1.0
            if enabled and has_sel and it not in sel:
                it.setOpacity(base_op * 0.4)
            else:
                it.setOpacity(base_op)

    def _invalidate_dim_cache(self):
        """Called after studio_dim_nonselected changes so the cached
        value in _apply_dim_nonselected gets re-read on the next call."""
        self._dim_nonselected_cached = None

    def _sync_quickbar(self):
        """Reflect the first selected overlay's state on the quickbar.
        Captures each selected item's current size as the scale-baseline
        so the scale spinbox 100% == 'leave as-is' after a selection
        change (spinbox is delta-based, not absolute)."""
        if not hasattr(self, "_qp_fill"):
            return
        sel = self._scene.selectedItems()
        overlay_sel = [it for it in sel if hasattr(it, "overlay")]
        # Capture baselines for scale
        self._qp_scale_base_map = {}
        for it in overlay_sel:
            ov = it.overlay
            if isinstance(it, OverlayShapeItem):
                self._qp_scale_base_map[id(it)] = {
                    "w": ov.shape_w, "h": ov.shape_h,
                    "cx": ov.x + ov.shape_w / 2,
                    "cy": ov.y + ov.shape_h / 2,
                }
            elif isinstance(it, OverlayImageItem):
                self._qp_scale_base_map[id(it)] = {"scale": ov.scale}
            elif isinstance(it, OverlayTextItem):
                self._qp_scale_base_map[id(it)] = {"font_size": ov.font_size}
        self._qp_syncing = True
        try:
            if overlay_sel:
                ov = overlay_sel[0].overlay
                self._qp_fill.setSwatchColor(ov.color or "#000000")
                self._qp_outline.setSwatchColor(ov.stroke_color or "#000000")
                self._qp_rot.setValue(int(ov.rotation) % 360)
                self._qp_opacity.setValue(int(ov.opacity * 100))
                self._qp_opacity_lbl.setText(str(int(ov.opacity * 100)))
                self._qp_scale.setValue(100)
                self._qp_label.setText(
                    f"{ov.type} / {ov.label or '(no label)'}"
                    if len(overlay_sel) == 1
                    else f"{len(overlay_sel)} selected")
                self._qp_rot.setEnabled(True)
                self._qp_opacity.setEnabled(True)
                self._qp_scale.setEnabled(True)
                self._qp_fill.setEnabled(True)
                self._qp_outline.setEnabled(True)
                if hasattr(self, "_qp_lock"):
                    self._qp_lock.setChecked(
                        bool(ov.locked))
                    self._qp_lock.setEnabled(True)
                if hasattr(self, "_qp_hide"):
                    self._qp_hide.setChecked(not bool(ov.enabled))
                    self._qp_hide.setEnabled(True)
            else:
                self._qp_label.setText("(no selection)")
                self._qp_rot.setEnabled(False)
                self._qp_opacity.setEnabled(False)
                self._qp_scale.setEnabled(False)
                self._qp_fill.setEnabled(False)
                self._qp_outline.setEnabled(False)
                if hasattr(self, "_qp_lock"):
                    self._qp_lock.setEnabled(False)
                    self._qp_lock.setChecked(False)
                if hasattr(self, "_qp_hide"):
                    self._qp_hide.setEnabled(False)
                    self._qp_hide.setChecked(False)
        finally:
            self._qp_syncing = False

    def _apply_color_to_selection(self, hex_color):
        """Quickbar fill-color action. Applies to every selected overlay
        regardless of type: text overlays get color + font refresh;
        shapes get stroke_color; images get tint via color (Image overlays
        treat `color` as a tint, so this is broad). Recent-color rotation
        too."""
        color = QColor(hex_color)
        if not color.isValid():
            return
        sel = self._scene.selectedItems()
        if not sel:
            return
        for it in sel:
            ov = getattr(it, "overlay", None)
            if ov is None:
                continue
            if isinstance(it, OverlayTextItem):
                ov.color = color.name()
                if hasattr(it, "_apply_font"):
                    it._apply_font()
            elif isinstance(it, OverlayShapeItem):
                ov.stroke_color = color.name()
                ov.color = color.name()
                it.update()
            elif isinstance(it, OverlayArrowItem):
                ov.color = color.name()
                it.update()
        self._qp_fill.setSwatchColor(color)
        self._add_recent_color(color.name())
        self._sync_overlays_to_asset()

    def _apply_stroke_to_selection(self, hex_color):
        """Quickbar stroke-color action."""
        color = QColor(hex_color)
        if not color.isValid():
            return
        sel = self._scene.selectedItems()
        if not sel:
            return
        for it in sel:
            ov = getattr(it, "overlay", None)
            if ov is None:
                continue
            ov.stroke_color = color.name()
            if ov.stroke_width == 0 and isinstance(it, OverlayTextItem):
                ov.stroke_width = 2
            if hasattr(it, "_apply_font"):
                it._apply_font()
            it.update()
        self._qp_outline.setSwatchColor(color)
        self._add_recent_color(color.name())
        self._sync_overlays_to_asset()

    def _qp_apply_rotation(self, value: int):
        """Quickbar rotation spinbox -> rotate every selected overlay."""
        if self._qp_syncing:
            return
        sel = self._scene.selectedItems()
        if not sel:
            return
        touched = False
        for it in sel:
            ov = getattr(it, "overlay", None)
            if ov is None:
                continue
            ov.rotation = value % 360
            if isinstance(it, OverlayShapeItem):
                it.setTransformOriginPoint(
                    ov.x + ov.shape_w / 2, ov.y + ov.shape_h / 2)
                it.setRotation(ov.rotation)
                it.update()
            elif hasattr(it, "_apply_flip"):
                it._apply_flip()
            elif hasattr(it, "_apply_flip_text"):
                it._apply_flip_text()
            else:
                it.update()
            touched = True
        if touched:
            self._sync_overlays_to_asset()

    def _qp_apply_opacity(self, value: int):
        """Quickbar opacity slider -> apply to every selected overlay."""
        if self._qp_syncing:
            return
        self._qp_opacity_lbl.setText(str(value))
        opacity = value / 100.0
        sel = self._scene.selectedItems()
        if not sel:
            return
        for it in sel:
            ov = getattr(it, "overlay", None)
            if ov is None:
                continue
            ov.opacity = opacity
            if hasattr(it, "setOpacity"):
                it.setOpacity(opacity)
            else:
                it.update()
        self._sync_overlays_to_asset()

    def _qp_apply_scale(self, value: int):
        """Quickbar scale -> resize shapes / rescale image overlays.
        Text overlays scale their font_size. 100% is baseline relative to
        each item's current size at the moment of last sync, so the spin
        is additive via delta: we store _qp_scale_base_map on selection
        change and apply new_value / base."""
        if self._qp_syncing:
            return
        sel = self._scene.selectedItems()
        if not sel:
            return
        base_map = self._qp_scale_base_map
        factor = value / 100.0
        touched = False
        for it in sel:
            ov = getattr(it, "overlay", None)
            if ov is None:
                continue
            base = base_map.get(id(it))
            if base is None:
                continue
            if isinstance(it, OverlayShapeItem):
                cx = base["cx"]
                cy = base["cy"]
                ov.shape_w = max(4, int(base["w"] * factor))
                ov.shape_h = max(4, int(base["h"] * factor))
                ov.x = int(cx - ov.shape_w / 2)
                ov.y = int(cy - ov.shape_h / 2)
                it.prepareGeometryChange()
                it.update()
                touched = True
            elif isinstance(it, OverlayImageItem):
                ov.scale = max(0.05, base["scale"] * factor)
                if hasattr(it, "_apply_flip"):
                    it._apply_flip()
                it.update()
                touched = True
            elif isinstance(it, OverlayTextItem):
                new_size = max(4, int(base["font_size"] * factor))
                ov.font_size = new_size
                if hasattr(it, "_apply_font"):
                    it._apply_font()
                # Force geometry/paint refresh - _apply_font usually does
                # this via QGraphicsTextItem.setFont but an edge case
                # where text_width is locked can leave the bounding rect
                # stale. Prod the item explicitly.
                it.prepareGeometryChange()
                it.update()
                # Mirror into the font-size slider in the Text Controls
                # popup so the user sees the two UIs agree.
                if hasattr(self, "slider_font_size"):
                    self.slider_font_size.blockSignals(True)
                    self.slider_font_size.setValue(new_size)
                    self.slider_font_size.blockSignals(False)
                touched = True
        if touched:
            self._sync_overlays_to_asset()

    def _apply_text_color(self, hex_color):
        """Push a color onto every selected text overlay + sync. Shared
        path for QColorDialog pick and the recent-color popup."""
        items = self._selected_overlay_items()
        if not items:
            return
        color = QColor(hex_color)
        if not color.isValid():
            return
        for item in items:
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "color", color.name(),
                    apply_cb=lambda it, _v: it._apply_font(),
                    description="Change text color",
                )
        if hasattr(self.btn_color, "setSwatchColor"):
            self.btn_color.setSwatchColor(color)
        self._add_recent_color(color.name())
        self._sync_overlays_to_asset()

    def _on_outline_color_pick(self):
        items = self._selected_overlay_items()
        if not items:
            return
        current = QColor(items[0].overlay.stroke_color or "#000000")
        color = QColorDialog.getColor(current, self, "Outline Color")
        if color.isValid():
            self._apply_outline_color(color.name())

    def _apply_outline_color(self, hex_color):
        """Shared path for outline color updates from the dialog or the
        swatch button's recent-color popup."""
        items = self._selected_overlay_items()
        if not items:
            return
        color = QColor(hex_color)
        if not color.isValid():
            return
        if hasattr(self.btn_outline_color, "setSwatchColor"):
            self.btn_outline_color.setSwatchColor(color)
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
        self._add_recent_color(color.name())
        self._sync_overlays_to_asset()

    def _on_outline_changed(self, value: int):
        # Text: outline stroke_width; Arrow: line stroke_width.
        def _refresh_text(it, _v):
            # OverlayTextItem uses DeviceCoordinateCache. Without an explicit
            # cache toggle the cached pixmap retains the OLD outline pass and
            # subsequent slider ticks look like nothing changed. Toggle the
            # cache mode + prepareGeometryChange so bounding rect (which
            # depends on stroke_width) recalculates too.
            it.prepareGeometryChange()
            it.setCacheMode(QGraphicsTextItem.CacheMode.NoCache)
            it.setCacheMode(QGraphicsTextItem.CacheMode.DeviceCoordinateCache)
            it.update()
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                self._push_overlay_attr(
                    item, "stroke_width", value,
                    apply_cb=_refresh_text,
                    description="Change outline",
                )
            elif isinstance(item, OverlayArrowItem):
                self._push_overlay_attr(
                    item, "stroke_width", max(1, value),
                    apply_cb=lambda it, _v: it.update(),
                    description="Change arrow width",
                )
                # Remember this stroke for the next new arrow
                QSettings("DoxyEdit", "DoxyEdit").setValue(
                    "studio_arrow_stroke", max(1, value))
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

    def _on_grid_spacing_changed(self, value: int):
        """Update the snap-grid spacing and persist across sessions."""
        self._grid_spacing = value
        self._scene._grid_spacing = value
        QSettings("DoxyEdit", "DoxyEdit").setValue("studio_grid_spacing", value)
        if self._scene._grid_visible:
            self._scene.update()

    def _on_grid_toggled(self, on: bool):
        """Toggle grid visibility from the toolbar checkbox (G hotkey wires
        through the same path so the two stay in sync)."""
        self._grid_visible = on
        self._scene._grid_visible = on
        QSettings("DoxyEdit", "DoxyEdit").setValue("studio_grid_visible", on)
        self._scene.update()

    def _on_thirds_toggled(self, on: bool):
        """Toggle rule-of-thirds guide overlay."""
        self._scene._thirds_visible = on
        QSettings("DoxyEdit", "DoxyEdit").setValue("studio_thirds_visible", on)
        self._scene.update()

    def _on_focus_toggled(self, on: bool):
        """Focus mode: hide layer panel + filmstrip to maximize canvas.
        The Focus button itself lives in the layer-sidebar footer so
        it stays visible in both states — we only hide the splitter
        body (list + props), leaving the footer row visible so users
        can toggle focus back off."""
        body = getattr(self, "_layer_sidebar_body", None)
        if body is not None:
            body.setVisible(not on)
        elif self._layer_panel is not None:
            # Fallback for pre-footer layouts (shouldn't normally hit).
            self._layer_panel.parent().setVisible(not on)
        if hasattr(self, "_preview_strip"):
            self._preview_strip.setVisible(not on)
        if hasattr(self, "_preview_strip_scroll"):
            self._preview_strip_scroll.setVisible(not on)

    def _on_rulers_toggled(self, on: bool):
        """Show or hide the ruler widgets."""
        if self._canvas_wrap is not None:
            self._canvas_wrap._h_ruler.setVisible(on)
            self._canvas_wrap._v_ruler.setVisible(on)
            self._canvas_wrap._corner.setVisible(on)
        QSettings("DoxyEdit", "DoxyEdit").setValue("studio_rulers_visible", on)

    def _on_notes_toggled(self, on: bool):
        """Show or hide all note annotations at once."""
        for note in getattr(self, "_notes", []):
            note.setVisible(on)
        QSettings("DoxyEdit", "DoxyEdit").setValue("studio_notes_visible", on)

    def _on_base_toggled(self, on: bool):
        """Hide / show the base image + checkerboard so users can focus on
        overlays without the base distracting the eye."""
        if self._pixmap_item is not None:
            self._pixmap_item.setVisible(on)
        checker = getattr(self, "_checker_item", None)
        if checker is not None:
            checker.setVisible(on)

    def _on_minimap_toggled(self, on: bool):
        """Show or hide the navigator minimap."""
        if self._canvas_wrap is not None:
            self._canvas_wrap.set_minimap_visible(on)
            if on:
                # Position in bottom-right
                v = self._view
                mm = self._canvas_wrap._minimap
                mm.move(v.width() - mm.width() - 12,
                         v.height() - mm.height() - 12)
                mm.update()
        QSettings("DoxyEdit", "DoxyEdit").setValue("studio_minimap_visible", on)

    def _on_flip_view_toggled(self, on: bool):
        """Mirror the view horizontally for composition checking.
        Purely visual — does not modify the image or export output."""
        # Scale by -1 on X toggles the mirror. We apply via composed
        # transform so zoom/scroll stay intact.
        t = self._view.transform()
        current_sx = t.m11()
        want_neg = on
        if (current_sx < 0) != want_neg:
            # Flip sign of X scale while preserving magnitude
            new_sx = -current_sx
            self._view.setTransform(
                QTransform(new_sx, t.m12(), t.m21(), t.m22(),
                            t.dx(), t.dy()))
            # Scene remains in the same place; refresh rulers so
            # numbers still read the cursor correctly.
            if self._canvas_wrap is not None:
                self._canvas_wrap.refresh()

    def _persist_canvas_split(self, *_):
        """Save the canvas/layer-panel splitter geometry to QSettings."""
        QSettings("DoxyEdit", "DoxyEdit").setValue(
            "studio_canvas_split_state", self._canvas_split.saveState())

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
        if self._asset.overlays:
            count_ovs = len(self._asset.overlays)
            hidden_ovs = sum(1 for o in self._asset.overlays if not o.enabled)
            tag_ovs = f" ({count_ovs})" if hidden_ovs == 0 else \
                f" ({count_ovs - hidden_ovs}/{count_ovs})"
            hdr = QListWidgetItem(f"-- Overlays{tag_ovs} --")
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            hdr.setForeground(Qt.GlobalColor.gray)
            self._layer_panel.addItem(hdr)
        for i, ov in enumerate(reversed(self._asset.overlays)):
            if ov.type == "text":
                label = f"T  {ov.text[:20]}" if ov.text else "T  (empty text)"
            elif ov.type == "watermark":
                label = f"W  {ov.label or Path(ov.image_path).stem}"
            elif ov.type == "arrow":
                label = f"→  {ov.label or 'Arrow'}"
            elif ov.type == "shape":
                icon = {
                    "ellipse": "◯",
                    "rect": "▭",
                    "star": "★",
                    "polygon": "⬡",
                    "gradient_linear": "▦",
                    "gradient_radial": "◎",
                    "speech_bubble": "💬",
                    "thought_bubble": "☁",
                    "burst_bubble": "💥",
                }.get(ov.shape_kind, "▭")
                label = f"{icon}  {ov.label or ov.shape_kind.replace('_', ' ').title()}"
            else:
                label = f"O  {ov.label or ov.type}"
            # Prepend visibility / lock indicators so layer state is
            # readable at a glance
            prefix = ""
            _tag = ov.tag_color
            if _tag:
                # Colored disc character for the tag. Unicode 'medium
                # circle' renders fine on most platforms; the color is
                # encoded via the theme-aware QListWidgetItem text color
                # below since QListWidgetItem labels don't parse HTML.
                prefix += "● "
            if not ov.enabled:
                prefix += "(hidden) "
            if ov.locked:
                prefix += "\U0001F512 "  # 🔒
            label = prefix + label
            label += _scope_tag(ov.platforms)
            item = QListWidgetItem(label)
            if _tag:
                # Color the row text with the tag's hex. Leading ● inherits.
                item.setForeground(QColor(TAG_COLOR_HEX.get(_tag, _tag)))
            item.setData(Qt.ItemDataRole.UserRole, ("overlay", len(self._asset.overlays) - 1 - i))
            if not ov.enabled:
                item.setForeground(Qt.GlobalColor.gray)
            thumb = self._build_overlay_thumb(ov)
            if thumb is not None:
                item.setIcon(QIcon(thumb))
            # Hover tooltip — fuller details than the list row can show
            tip_lines = [f"Type: {ov.type}"]
            if ov.type == "text" and ov.text:
                tip_lines.append(f"Text: {ov.text[:80]}")
            if ov.label:
                tip_lines.append(f"Label: {ov.label}")
            tip_lines.append(f"Opacity: {int(ov.opacity * 100)}%")
            tip_lines.append(f"Position: {ov.x}, {ov.y}")
            if ov.rotation:
                tip_lines.append(f"Rotation: {int(ov.rotation)}°")
            if ov.platforms:
                tip_lines.append(f"Platforms: {', '.join(ov.platforms)}")
            if ov.blend_mode and ov.blend_mode != "normal":
                tip_lines.append(f"Blend: {ov.blend_mode}")
            if ov.locked:
                tip_lines.append("Locked")
            if not ov.enabled:
                tip_lines.append("Hidden")
            item.setToolTip("\n".join(tip_lines))
            self._layer_panel.addItem(item)

        # Censors
        if self._asset.censors:
            count_cr = len(self._asset.censors)
            hdr = QListWidgetItem(f"-- Censors ({count_cr}) --")
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            hdr.setForeground(Qt.GlobalColor.gray)
            self._layer_panel.addItem(hdr)
        for i, cr in enumerate(self._asset.censors):
            thumb = self._build_censor_thumb(cr)
            label = f"C  {cr.style} ({cr.w}\u00d7{cr.h}){_scope_tag(cr.platforms)}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ("censor", i))
            if thumb is not None:
                item.setIcon(QIcon(thumb))
            self._layer_panel.addItem(item)

    _refresh_layer_panel = _rebuild_layer_panel

    def _build_overlay_thumb(self, ov) -> "QPixmap | None":
        """Render a 28x28 thumbnail for a layer-panel row."""
        _t = self._theme
        size = 28
        pm = QPixmap(size, size)
        pm.fill(QColor(0, 0, 0, 0))  # transparent pixmap init
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            if ov.type in ("watermark", "logo") and ov.image_path:
                # Thumb cache on the editor: (image_path, size) → QPixmap.
                # Prior code called QPixmap(path) + SmoothTransformation
                # scale on every layer-panel rebuild, so N watermarks ×
                # rebuild = N disk reads + N smooth scales per rebuild.
                if not hasattr(self, "_thumb_cache"):
                    self._thumb_cache = {}
                key = (ov.image_path, size)
                cached = self._thumb_cache.get(key)
                if cached is not None and not cached.isNull():
                    x = (size - cached.width()) // 2
                    y = (size - cached.height()) // 2
                    painter.drawPixmap(x, y, cached)
                    return pm
                src = QPixmap(ov.image_path)
                if not src.isNull():
                    scaled = src.scaled(size, size,
                                         Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
                    # Keep cache small — limit to ~50 entries.
                    if len(self._thumb_cache) > 50:
                        # Drop an arbitrary oldest entry (dict preserves
                        # insertion order in Python 3.7+).
                        self._thumb_cache.pop(
                            next(iter(self._thumb_cache)), None)
                    self._thumb_cache[key] = scaled
                    x = (size - scaled.width()) // 2
                    y = (size - scaled.height()) // 2
                    painter.drawPixmap(x, y, scaled)
                    return pm
                # Fall through to placeholder
            if ov.type == "text":
                painter.setPen(QPen(QColor(ov.color or _t.studio_icon_fg),
                                    _t.studio_thumb_pen_width))
                font = painter.font()
                font.setBold(ov.bold)
                font.setItalic(ov.italic)
                font.setPixelSize(18)
                painter.setFont(font)
                painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "T")
                return pm
            if ov.type == "arrow":
                painter.setPen(QPen(QColor(ov.color or _t.studio_temp_arrow),
                                    _t.studio_thumb_arrow_pen_width))
                painter.drawLine(4, size - 4, size - 6, 6)
                # Small arrowhead
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(ov.color or _t.studio_temp_arrow)))
                painter.drawPolygon(QPolygonF([
                    QPointF(size - 6, 6),
                    QPointF(size - 12, 10),
                    QPointF(size - 10, 14),
                ]))
                return pm
            if ov.type == "shape":
                stroke = QColor(ov.stroke_color or ov.color or _t.studio_temp_shape)
                fill = QColor(ov.fill_color) if ov.fill_color else None
                painter.setPen(QPen(stroke, _t.studio_temp_shape_pen_width))
                painter.setBrush(QBrush(fill) if fill else Qt.BrushStyle.NoBrush)
                r = QRectF(4, 4, size - 8, size - 8)
                if ov.shape_kind == "ellipse":
                    painter.drawEllipse(r)
                else:
                    painter.drawRect(r)
                return pm
        finally:
            painter.end()
        return pm

    def _build_censor_thumb(self, cr) -> "QPixmap | None":
        """Render a 28x28 thumbnail matching the censor style."""
        _t = self._theme
        size = 28
        pm = QPixmap(size, size)
        pm.fill(QColor(0, 0, 0, 0))  # transparent pixmap init
        painter = QPainter(pm)
        try:
            if cr.style == "black":
                painter.fillRect(4, 4, size - 8, size - 8,
                                 QColor(_t.studio_censor_blackout_fill))
            elif cr.style == "blur":
                # Hash-pattern for blur
                painter.setPen(QPen(QColor(_t.studio_censor_blur_fill),
                                    _t.studio_thumb_pen_width))
                for y in range(4, size - 4, 3):
                    painter.drawLine(4, y, size - 4, y)
            else:  # pixelate
                for yy in range(4, size - 4, 4):
                    for xx in range(4, size - 4, 4):
                        v = 40 + ((xx + yy) * 7 % 60)
                        painter.fillRect(xx, yy, 4, 4, QColor(v, v, v))
            err_c = QColor(_t.studio_error_dot)
            err_c.setAlpha(_t.studio_error_dot_alpha)
            painter.setPen(QPen(err_c, _t.studio_thumb_pen_width))
            painter.drawRect(3, 3, size - 6, size - 6)
            return pm
        finally:
            painter.end()

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

    def _on_layer_double_clicked(self, item):
        """Double-click a layer row → rename (overlays) or edit text (text)."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, idx = data
        if kind == "overlay" and 0 <= idx < len(self._asset.overlays):
            ov = self._asset.overlays[idx]
            if ov.type == "text":
                # Enter inline edit mode on the scene item
                for scene_item in self._scene.items():
                    if isinstance(scene_item, OverlayTextItem) and scene_item.overlay is ov:
                        scene_item.setSelected(True)
                        scene_item.setTextInteractionFlags(
                            Qt.TextInteractionFlag.TextEditorInteraction)
                        scene_item.setFocus()
                        break
            else:
                old = ov.label or ""
                new_label, ok = QInputDialog.getText(
                    self, "Rename layer", "Label:", text=old)
                if ok and new_label.strip():
                    ov.label = new_label.strip()
                    self._rebuild_layer_panel()

    def _on_layer_context_menu(self, pos):
        """Right-click a layer row -> delegate to the scene item's full
        contextMenuEvent so the user gets the same per-type menu as
        right-clicking on the canvas. Prepends layer-specific actions
        (Hide / Lock / Isolate / Rename / Opacity / Arrange) so both
        feature sets are reachable from the same gesture.

        Right-click on EMPTY panel area -> Clear All Layers
        (with confirmation) + a Select All bulk action."""
        list_item = self._layer_panel.itemAt(pos)
        global_pos_empty = self._layer_panel.mapToGlobal(pos)
        if list_item is None:
            empty_menu = _themed_menu(self._layer_panel)
            sel_all_act = empty_menu.addAction("Select All Overlays")
            thumb_sub = empty_menu.addMenu("Thumbnail Size")
            thumb_s = thumb_sub.addAction("Small (16px)")
            thumb_m = thumb_sub.addAction("Medium (28px)")
            thumb_l = thumb_sub.addAction("Large (48px)")
            for act, sz in ((thumb_s, 16), (thumb_m, 28), (thumb_l, 48)):
                act.setCheckable(True)
                act.setChecked(
                    self._layer_panel.iconSize().width() == sz)
            empty_menu.addSeparator()
            clear_all_act = empty_menu.addAction("Clear All Layers...")
            chosen = empty_menu.exec(global_pos_empty)
            if chosen in (thumb_s, thumb_m, thumb_l):
                sz = 16 if chosen is thumb_s else 28 if chosen is thumb_m else 48
                self._layer_panel.setIconSize(QSize(sz, sz))
                QSettings("DoxyEdit", "DoxyEdit").setValue(
                    "studio_layer_thumb_size", sz)
                self._rebuild_layer_panel()
                return
            if chosen is sel_all_act:
                for it in self._overlay_items:
                    if hasattr(it, "setSelected"):
                        it.setSelected(True)
                return
            if chosen is clear_all_act:
                count = len(self._asset.overlays) + len(self._asset.censors) \
                    + len(self._asset.crops) + len(self._notes)
                if count == 0:
                    if self.info_label is not None:
                        self.info_label.setText("Nothing to clear")
                    return
                resp = QMessageBox.warning(
                    self, "Clear all layers",
                    f"Delete ALL {count} layers (overlays, censors, crops, notes) "
                    "from this asset?\nUndoable via Ctrl+Z.",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if resp != QMessageBox.StandardButton.Yes:
                    return
                # Select everything then dispatch through the undoable
                # delete path so Ctrl+Z still recovers.
                self._scene.clearSelection()
                for it in self._overlay_items:
                    it.setSelected(True)
                for it in self._censor_items:
                    it.setSelected(True)
                for it in self._crop_items:
                    it.setSelected(True)
                for it in self._notes:
                    it.setSelected(True)
                self._delete_selected()
                if self.info_label is not None:
                    self.info_label.setText(f"Cleared {count} layers")
            return
        data = list_item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, idx = data
        global_pos = self._layer_panel.mapToGlobal(pos)
        scene_item = None
        if kind == "overlay" and 0 <= idx < len(self._asset.overlays):
            target_ov = self._asset.overlays[idx]
            for it in self._scene.items():
                if getattr(it, "overlay", None) is target_ov:
                    scene_item = it
                    break
        elif kind == "censor" and 0 <= idx < len(self._asset.censors):
            target_cr = self._asset.censors[idx]
            for it in self._scene.items():
                if (isinstance(it, CensorRectItem)
                        and getattr(it, "_censor_region", None) is target_cr):
                    scene_item = it
                    break
        # Auto-select the targeted item so the scene-side context menu
        # acts on it (most item contextMenuEvents operate on self, not
        # on selection, but selecting makes the quickbar + popups follow
        # the user's intent).
        if scene_item is not None:
            self._scene.clearSelection()
            scene_item.setSelected(True)

        # Build the layer-only prefix menu first. If the user picks from
        # it, we're done. Otherwise we dispatch to the scene item's
        # contextMenuEvent for the full type-specific palette.
        prefix = _themed_menu(self._layer_panel)
        if kind == "overlay" and scene_item is not None:
            ov = scene_item.overlay
            act_vis = prefix.addAction("Hide" if ov.enabled else "Show")
            act_lock = prefix.addAction(
                "Unlock" if ov.locked else "Lock")
            act_isolate = prefix.addAction(
                "Exit Isolation" if self._isolation_active
                else "Isolate (solo)")
            act_rename = prefix.addAction("Rename...")
            act_opacity = prefix.addAction("Opacity...")
            act_copy_style = prefix.addAction("Copy Layer Style")
            act_paste_style = prefix.addAction("Paste Layer Style")
            # Tag color submenu. Matches Finder / macOS style labels
            # (colored dots). Stored per-overlay so it persists across
            # sessions and survives rebuild_layer_panel.
            tag_sub = prefix.addMenu("Tag Color")
            tag_acts = {}
            _cur_tag = ov.tag_color
            _tag_opts = [("None", "")] + [(lbl, tid) for tid, lbl, _, _ in TAG_COLORS]
            for tag_label, tag_val in _tag_opts:
                act = tag_sub.addAction(tag_label)
                act.setCheckable(True)
                act.setChecked(_cur_tag == tag_val)
                tag_acts[act] = tag_val
            act_dup_n = prefix.addAction("Duplicate N times...")
            act_dup_grid = prefix.addAction("Duplicate as grid...")
            act_zoom_to = prefix.addAction("Zoom to Layer")
            z_sub = prefix.addMenu("Arrange")
            act_to_front = z_sub.addAction("Bring to Front  (Ctrl+Shift+])")
            act_forward = z_sub.addAction("Bring Forward  (Ctrl+])")
            act_backward = z_sub.addAction("Send Backward  (Ctrl+[)")
            act_to_back = z_sub.addAction("Send to Back  (Ctrl+Shift+[)")
            prefix.addSeparator()
            act_full = prefix.addAction(
                f"More ({type(scene_item).__name__.replace('Overlay', '').replace('Item', '')} options)...")
            chosen = prefix.exec(global_pos)
            if chosen is None:
                return
            if chosen is act_vis:
                ov.enabled = not ov.enabled
                scene_item.setVisible(ov.enabled)
                self._rebuild_layer_panel()
                return
            if chosen is act_lock:
                ov.locked = not ov.locked
                scene_item.setFlag(
                    scene_item.GraphicsItemFlag.ItemIsMovable, not ov.locked)
                scene_item.setFlag(
                    scene_item.GraphicsItemFlag.ItemIsSelectable, not ov.locked)
                self._rebuild_layer_panel()
                return
            if chosen is act_isolate:
                if self._isolation_active:
                    self._exit_isolation()
                else:
                    self._enter_isolation(ov)
                return
            if chosen is act_rename:
                self._on_layer_double_clicked(list_item)
                return
            if chosen is act_copy_style:
                self._copy_style(ov)
                self.info_label.setText("Copied layer style")
                return
            if chosen is act_paste_style:
                self._paste_style(ov, scene_item)
                self._rebuild_layer_panel()
                return
            if tag_acts and chosen in tag_acts:
                ov.tag_color = tag_acts[chosen]
                self._sync_overlays_to_asset()
                return
            if chosen is act_opacity:
                v, ok = QInputDialog.getInt(
                    self, "Opacity", "Opacity % (0-100):",
                    value=int(ov.opacity * 100), minValue=0, maxValue=100)
                if ok:
                    ov.opacity = v / 100.0
                    if hasattr(scene_item, "setOpacity"):
                        scene_item.setOpacity(ov.opacity)
                    else:
                        scene_item.update()
                    self._sync_overlays_to_asset()
                return
            if chosen is act_zoom_to:
                # Fit-in-view on this single layer's bounding rect so
                # the user can eyeball detail work without fishing for
                # the right zoom level.
                bounds = scene_item.sceneBoundingRect()
                bounds.adjust(-40, -40, 40, 40)
                self._view.fitInView(bounds,
                                      Qt.AspectRatioMode.KeepAspectRatio)
                if hasattr(self, "_zoom_label"):
                    self._zoom_label.setText(
                        f"{int(self._view.transform().m11() * 100)}%")
                if self._canvas_wrap is not None:
                    self._canvas_wrap.refresh()
                return
            if chosen is act_dup_n:
                n, ok = QInputDialog.getInt(
                    self, "Duplicate N times",
                    "How many copies? (each offset 20 px):",
                    value=3, minValue=1, maxValue=50)
                if ok and n > 0:
                    # Duplicate the SOURCE item N times, each with a
                    # cumulative offset so they cascade rather than
                    # stacking. Select only the source first so the
                    # dispatch in _duplicate_selected only acts on it.
                    for i in range(n):
                        self._scene.clearSelection()
                        scene_item.setSelected(True)
                        self._duplicate_selected(offset=20 * (i + 1))
                    self._rebuild_layer_panel()
                    self.info_label.setText(f"Made {n} copies")
                return
            if chosen is act_dup_grid:
                grid_dlg = QDialog(self)
                grid_dlg.setWindowTitle("Duplicate as grid")
                gform = QFormLayout(grid_dlg)
                cols_spin = QSpinBox(); cols_spin.setRange(1, 50); cols_spin.setValue(4)
                rows_spin = QSpinBox(); rows_spin.setRange(1, 50); rows_spin.setValue(3)
                gap_x_spin = QSpinBox()
                gap_x_spin.setRange(-2000, 2000); gap_x_spin.setValue(20)
                gap_x_spin.setSuffix(" px")
                gap_y_spin = QSpinBox()
                gap_y_spin.setRange(-2000, 2000); gap_y_spin.setValue(20)
                gap_y_spin.setSuffix(" px")
                gform.addRow("Columns", cols_spin)
                gform.addRow("Rows", rows_spin)
                gform.addRow("Horizontal gap", gap_x_spin)
                gform.addRow("Vertical gap", gap_y_spin)
                gbb = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok
                    | QDialogButtonBox.StandardButton.Cancel)
                gbb.accepted.connect(grid_dlg.accept)
                gbb.rejected.connect(grid_dlg.reject)
                gform.addRow(gbb)
                win = self.window()
                if win is not None:
                    grid_dlg.setStyleSheet(win.styleSheet())
                if grid_dlg.exec() != QDialog.DialogCode.Accepted:
                    return
                cols = cols_spin.value()
                rows = rows_spin.value()
                total = cols * rows - 1  # minus the original
                if total <= 0:
                    return
                # Work out the source dimensions so the gap is the
                # visual spacing between shapes (not the stride).
                br = scene_item.sceneBoundingRect()
                stride_x = int(br.width()) + gap_x_spin.value()
                stride_y = int(br.height()) + gap_y_spin.value()
                made = 0
                # row 0 col 0 is the original; skip it.
                for r in range(rows):
                    for c in range(cols):
                        if r == 0 and c == 0:
                            continue
                        self._scene.clearSelection()
                        scene_item.setSelected(True)
                        self._duplicate_selected(offset=0)
                        new_item = (self._overlay_items[-1]
                                     if self._overlay_items else None)
                        if new_item is None:
                            continue
                        dx = c * stride_x
                        dy = r * stride_y
                        if hasattr(new_item, "overlay"):
                            new_item.overlay.x = int(br.left() + dx)
                            new_item.overlay.y = int(br.top() + dy)
                            new_item.setPos(
                                new_item.overlay.x,
                                new_item.overlay.y)
                        made += 1
                self._sync_overlays_to_asset()
                self.info_label.setText(
                    f"Made {made} grid copies ({cols}x{rows})")
                return
            if chosen in (act_to_front, act_forward, act_backward, act_to_back):
                delta = (+999 if chosen is act_to_front
                         else +1 if chosen is act_forward
                         else -1 if chosen is act_backward
                         else -999)
                self._z_shift_selected(delta)
                return
            if chosen is act_full:
                # Delegate to the item's own contextMenuEvent - same UI
                # as right-click on the canvas, full type-specific
                # palette (color pickers, convert-to, presets, etc.).
                self._dispatch_scene_context_menu(scene_item, global_pos)
                return
        elif kind == "censor" and scene_item is not None:
            act_delete = prefix.addAction("Delete")
            prefix.addSeparator()
            act_full = prefix.addAction("More censor options...")
            chosen = prefix.exec(global_pos)
            if chosen is act_delete:
                self._remove_censor_item(scene_item)
                self._rebuild_layer_panel()
                return
            if chosen is act_full:
                self._dispatch_scene_context_menu(scene_item, global_pos)
                return

    def _dispatch_scene_context_menu(self, scene_item, global_pos):
        """Fabricate a QGraphicsSceneContextMenuEvent and hand it to the
        target item's contextMenuEvent. Shows the item's full palette
        at the requested global position."""
        try:
            from PySide6.QtWidgets import QGraphicsSceneContextMenuEvent
            ev = QGraphicsSceneContextMenuEvent(
                QEvent.Type.GraphicsSceneContextMenu)
            ev.setScreenPos(global_pos)
            rect = scene_item.sceneBoundingRect()
            ev.setScenePos(rect.center())
            ev.setModifiers(Qt.KeyboardModifier.NoModifier)
            ev.setReason(
                QGraphicsSceneContextMenuEvent.Reason.Mouse)
            scene_item.contextMenuEvent(ev)
        except Exception as exc:
            # Silent fallback - worst case the layer-specific prefix
            # menu already ran, so user loses the 'More' branch only.
            if self.info_label is not None:
                self.info_label.setText(
                    f"Layer context menu dispatch failed: {exc}")

    def _enter_isolation(self, solo_overlay):
        """Temporarily hide every overlay/censor except the given one.
        The original `enabled` state is untouched — restored by _exit_isolation."""
        self._isolation_active = True
        for it in self._scene.items():
            ov = getattr(it, "overlay", None)
            cr = getattr(it, "_censor_region", None)
            if ov is not None:
                it.setVisible(ov is solo_overlay)
            elif cr is not None:
                it.setVisible(False)
        self.info_label.setText("Isolation on — right-click layer to Exit")

    def _exit_isolation(self):
        """Restore all overlays/censors to their persistent enabled state."""
        self._isolation_active = False
        for it in self._scene.items():
            ov = getattr(it, "overlay", None)
            cr = getattr(it, "_censor_region", None)
            if ov is not None:
                it.setVisible(ov.enabled)
            elif cr is not None:
                it.setVisible(True)
        self.info_label.setText("Isolation off")

    def _sync_layer_panel_selection(self):
        """Mirror canvas selection into the layer panel so the user can
        see which row corresponds to the items they clicked on stage.

        Multi-selects on the canvas reflect as multi-selects in the
        layer panel. Block signals around the change to avoid bouncing
        the selection back into _on_layer_clicked.
        """
        if not hasattr(self, "_layer_panel") or self._layer_panel is None:
            return
        if not self._asset:
            return
        # Collect overlay indices for currently-selected scene items
        sel_indices: set[int] = set()
        for it in self._scene.selectedItems():
            ov = getattr(it, "overlay", None)
            if ov is None:
                continue
            try:
                sel_indices.add(self._asset.overlays.index(ov))
            except ValueError:
                continue
        self._layer_panel.blockSignals(True)
        try:
            self._layer_panel.clearSelection()
            first = None
            for row in range(self._layer_panel.count()):
                item = self._layer_panel.item(row)
                data = item.data(Qt.ItemDataRole.UserRole)
                if not data:
                    continue
                kind, idx = data
                if kind == "overlay" and idx in sel_indices:
                    item.setSelected(True)
                    if first is None:
                        first = item
            if first is not None:
                self._layer_panel.setCurrentItem(first)
                self._layer_panel.scrollToItem(first)
        finally:
            self._layer_panel.blockSignals(False)

    def _on_layer_clicked(self, item):
        """Select the corresponding scene item when layer is clicked.
        Shift+click toggles visibility; Ctrl+click toggles lock."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, idx = data
        mods = QApplication.keyboardModifiers()
        if kind == "overlay" and 0 <= idx < len(self._asset.overlays):
            ov = self._asset.overlays[idx]
            if mods & Qt.KeyboardModifier.ShiftModifier:
                ov.enabled = not ov.enabled
                for it in self._scene.items():
                    if hasattr(it, "overlay") and it.overlay is ov:
                        it.setVisible(ov.enabled)
                        break
                self._rebuild_layer_panel()
                return
            if mods & Qt.KeyboardModifier.ControlModifier:
                ov.locked = not ov.locked
                for it in self._scene.items():
                    if hasattr(it, "overlay") and it.overlay is ov:
                        it.setFlag(
                            it.GraphicsItemFlag.ItemIsMovable, not ov.locked)
                        it.setFlag(
                            it.GraphicsItemFlag.ItemIsSelectable, not ov.locked)
                        break
                self._rebuild_layer_panel()
                return
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
        """Populate the opacity + enabled + position controls for the selected layer."""
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
            self.chk_layer_locked.blockSignals(True)
            self.chk_layer_locked.setChecked(bool(ov.locked))
            self.chk_layer_locked.blockSignals(False)
            # Sync BOTH the spinbox and the matching slider so the
            # two halves of each slider+spinbox pair display the same
            # value after a selection change.
            for _widget in (self.spin_pos_x, self.slider_pos_x):
                _widget.blockSignals(True)
                _widget.setValue(
                    max(_widget.minimum(),
                         min(_widget.maximum(), int(ov.x))))
                _widget.blockSignals(False)
            for _widget in (self.spin_pos_y, self.slider_pos_y):
                _widget.blockSignals(True)
                _widget.setValue(
                    max(_widget.minimum(),
                         min(_widget.maximum(), int(ov.y))))
                _widget.blockSignals(False)
            _rv = int(ov.rotation)
            for _widget in (self.spin_rotation_layer, self.slider_rotation_layer):
                _widget.blockSignals(True)
                _widget.setValue(_rv)
                _widget.blockSignals(False)
            self._layer_props_widget.setEnabled(True)
            self._layer_props_selection = ("overlay", idx)
        else:
            # Censors don't have opacity/enabled in CensorRegion
            self._layer_props_widget.setEnabled(False)
            self._layer_props_selection = None

    def _on_layer_rotation_changed(self, value: int):
        """Rotation spinbox in the layer props panel."""
        sel = getattr(self, "_layer_props_selection", None)
        if not sel or sel[0] != "overlay":
            return
        idx = sel[1]
        if idx >= len(self._asset.overlays):
            return
        ov = self._asset.overlays[idx]
        ov.rotation = value % 360
        for it in self._scene.items():
            if hasattr(it, "overlay") and it.overlay is ov:
                if hasattr(it, "_apply_flip"):
                    it._apply_flip()
                elif hasattr(it, "_apply_flip_text"):
                    it._apply_flip_text()
                elif isinstance(it, OverlayShapeItem):
                    it.setTransformOriginPoint(
                        ov.x + ov.shape_w / 2, ov.y + ov.shape_h / 2)
                    it.setRotation(ov.rotation)
                    it.update()
                else:
                    it.update()
                break
        self._sync_overlays_to_asset()

    def _on_pos_field_changed(self, axis: str, value: int):
        """Typing X or Y in the props spinboxes repositions the selected overlay."""
        sel = getattr(self, "_layer_props_selection", None)
        if not sel or sel[0] != "overlay":
            return
        idx = sel[1]
        if idx >= len(self._asset.overlays):
            return
        ov = self._asset.overlays[idx]
        setattr(ov, axis, value)
        # Find the scene item and move it
        for it in self._scene.items():
            if hasattr(it, "overlay") and it.overlay is ov:
                if isinstance(it, OverlayArrowItem):
                    # Arrow: move whole arrow by delta of start point
                    it.update()
                elif isinstance(it, OverlayShapeItem):
                    # Shape items are anchored at scene (0,0) and paint using
                    # overlay.x/y directly (see itemChange ItemPositionChange
                    # handler). Calling setPos here would trigger that
                    # handler and DOUBLE the position delta on every slider
                    # tick, leaving ghost-paint artifacts as the bounding
                    # rect and painted geometry diverge. Re-anchor the drag
                    # baseline and just invalidate geometry + redraw.
                    it._drag_prev_value = QPointF(0, 0)
                    it.prepareGeometryChange()
                    it.update()
                else:
                    it.setPos(ov.x, ov.y)
                break
        self._sync_overlays_to_asset()

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

    def _on_layer_locked_toggled(self, checked: bool):
        """Toggle 'locked' on the selected overlay.

        Locked means the scene item is not selectable/movable, so drag +
        click can't affect it. Useful for backgrounds / watermarks the
        user wants to protect from accidental edits.
        """
        sel = getattr(self, "_layer_props_selection", None)
        if not sel or sel[0] != "overlay":
            return
        _, idx = sel
        if not (0 <= idx < len(self._asset.overlays)):
            return
        ov = self._asset.overlays[idx]
        for it in self._scene.items():
            if getattr(it, "overlay", None) is ov:
                def _apply_locked(item, v):
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not bool(v))
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not bool(v))
                    if v:
                        item.setSelected(False)
                self._push_overlay_attr(
                    it, "locked", checked,
                    apply_cb=_apply_locked,
                    description=("Lock layer" if checked else "Unlock layer"),
                )
                break
        # Refresh the layer panel so the lock icon appears/disappears
        self._rebuild_layer_panel()

    # ---- sync ----

    def _sync_censors_to_asset(self):
        """Write censor items back to asset.censors.

        Called from censor handle-drag (every mousemove while a resize
        handle is held), so the layer-panel rebuild is debounced via
        the same 80ms singleshot timer used for overlays — otherwise a
        single censor resize triggered a full QListWidget clear +
        rebuild on every mousemove.

        Fingerprints the new list and skips the rebuild when nothing
        changed. When rebuild is needed, mutates an existing linked
        CensorRegion in place (via item._censor_region) so non-geometry
        fields — blur_radius, pixelate_ratio, rotation — survive the
        sync. Previously the rebuild allocated a fresh CensorRegion
        with defaults, clobbering any user-set blur_radius on drag.
        """
        if not self._asset:
            return
        new_fingerprints = []
        for item in self._censor_items:
            r = item.rect()
            pos = item.pos()
            new_fingerprints.append((
                int(pos.x() + r.x()), int(pos.y() + r.y()),
                int(r.width()), int(r.height()),
                item.style,
                tuple(item.platforms),
                float(item.rotation()),
            ))
        existing = self._asset.censors
        unchanged = (
            len(existing) == len(new_fingerprints)
            and all(
                (c.x, c.y, c.w, c.h, c.style, tuple(c.platforms),
                 float(getattr(c, "rotation", 0.0) or 0.0))
                == fp
                for c, fp in zip(existing, new_fingerprints)
            )
        )
        if unchanged:
            return
        new_censors = []
        for item, fp in zip(self._censor_items, new_fingerprints):
            x, y, w, h, style, platforms, rotation = fp
            linked = getattr(item, "_censor_region", None)
            if linked is not None:
                # Mutate the existing region so blur_radius /
                # pixelate_ratio / future fields aren't lost.
                linked.x = x
                linked.y = y
                linked.w = w
                linked.h = h
                linked.style = style
                linked.platforms = list(platforms)
                if hasattr(linked, "rotation"):
                    linked.rotation = rotation
                new_censors.append(linked)
            else:
                cr = CensorRegion(
                    x=x, y=y, w=w, h=h,
                    style=style, platforms=list(platforms),
                )
                if hasattr(cr, "rotation"):
                    cr.rotation = rotation
                item._censor_region = cr
                new_censors.append(cr)
        self._asset.censors.clear()
        self._asset.censors.extend(new_censors)
        self._schedule_layer_rebuild()

    def _sync_overlays_to_asset(self):
        """Write overlay items back to asset.overlays.

        Rebuilding the layer panel on every call was the biggest source
        of jitter during slider drags on text overlays (every tick =
        full QListWidget clear+rebuild). Coalesce to a single rebuild
        per event loop via a short-interval singleshot timer.

        Also: the CanvasOverlay objects held by _overlay_items[*].overlay
        ARE the same objects as _asset.overlays[i] — in-place attribute
        mutations (slider handlers) are already reflected. The clear +
        rebuild is only needed when the LIST changed (add/remove/
        reorder). Detect the common case where the list already matches
        and skip the rebuild.
        """
        if not self._asset:
            return
        items_overlays = [item.overlay for item in self._overlay_items]
        asset_overlays = self._asset.overlays
        structure_changed = (
            len(items_overlays) != len(asset_overlays)
            or any(a is not b for a, b in zip(items_overlays, asset_overlays))
        )
        if structure_changed:
            self._asset.overlays.clear()
            self._asset.overlays.extend(items_overlays)
        # Only reschedule the rebuild when structure actually changed.
        # Attribute-only updates (slider drag) don't need the layer
        # panel redrawn — the row labels are structural, not live.
        if structure_changed:
            self._schedule_layer_rebuild()

    def _schedule_layer_rebuild(self):
        """Kick the 80ms debounced layer-panel rebuild. Shared by
        _sync_censors_to_asset and _sync_overlays_to_asset — both fire
        repeatedly during drag / slider-tick, so coalescing into one
        rebuild per event-loop idle saves a full QListWidget clear +
        repopulate per tick. Lazy-creates the timer on first call."""
        if self._layer_panel is None:
            return
        timer = self._layer_rebuild_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(80)
            timer.timeout.connect(self._rebuild_layer_panel)
            self._layer_rebuild_timer = timer
        timer.start()

    # ---- actions ----

    def _delete_selected(self):
        """Remove selected censors/overlays/crops/notes from scene and
        model. Speech/thought bubbles cascade their linked text overlay
        so the bubble + its linked text always travel together."""
        cmd = DeleteItemCmd(self)
        has_undoable = False
        selected = list(self._scene.selectedItems())
        # Expand the selection to include linked-text overlays whose
        # owning bubble is being deleted. Walk up front so indices /
        # references remain valid during the main loop.
        cascade_labels = set()
        for item in selected:
            if (isinstance(item, OverlayShapeItem)
                    and getattr(item.overlay, "linked_text_id", "")):
                cascade_labels.add(item.overlay.linked_text_id)
        if cascade_labels:
            for other in list(self._overlay_items):
                if (isinstance(other, OverlayTextItem)
                        and other.overlay.label in cascade_labels
                        and other not in selected):
                    selected.append(other)
        for item in selected:
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
            elif isinstance(item, _OVERLAY_ITEM_TYPES):
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
            elif isinstance(item, _GuideLineItem):
                self._scene.removeItem(item)
                if item in self._guide_items:
                    self._guide_items.remove(item)
                self._save_guides_to_asset()
                if self._canvas_wrap is not None:
                    self._canvas_wrap.refresh()
            elif isinstance(item, (AnnotationTextItem, QGraphicsRectItem, QGraphicsLineItem)):
                self._scene.removeItem(item)
        if has_undoable:
            self._undo_stack.push(cmd)
        self._sync_censors_to_asset()
        self._sync_overlays_to_asset()
        # Force a layer-panel rebuild. _sync_overlays_to_asset only
        # schedules a rebuild when its structural diff detects a list-
        # length or identity mismatch — but DeleteItemCmd.redo() already
        # pruned both _overlay_items AND _asset.overlays in lockstep, so
        # the structural diff sees no change and the scheduled rebuild
        # would be skipped. The layer panel needs the rebuild regardless:
        # the deleted item's row must disappear.
        self._schedule_layer_rebuild()
        self._update_info()

    def _remove_censor_item(self, item: CensorRectItem):
        """Remove a single censor item from scene + model (for context menu)."""
        self._scene.removeItem(item)
        if item in self._censor_items:
            self._censor_items.remove(item)
        self._sync_censors_to_asset()
        self._update_info()

    def _remove_overlay_item(self, item):
        """Remove a single overlay item from scene + model. Cascades to
        the paired text overlay when the item is a bubble with a
        linked_text_id — previously the bubble was removed but the
        text overlay was left floating in the asset (and hence visible
        on-canvas with no owner)."""
        pending_cascade = []
        if isinstance(item, OverlayShapeItem):
            lid = getattr(item.overlay, "linked_text_id", "")
            if lid:
                for other in list(self._overlay_items):
                    if (isinstance(other, OverlayTextItem)
                            and other.overlay.label == lid):
                        pending_cascade.append(other)
        self._scene.removeItem(item)
        if item in self._overlay_items:
            self._overlay_items.remove(item)
        for other in pending_cascade:
            try:
                self._scene.removeItem(other)
            except Exception:
                pass
            if other in self._overlay_items:
                self._overlay_items.remove(other)
        self._sync_overlays_to_asset()
        self._update_info()

    def _duplicate_overlay_item(self, item, offset: int = 20):
        """Duplicate an overlay item with an optional x/y offset (default
        20 px for Ctrl+D; 0 for stamp-in-place via Ctrl+Alt+D)."""
        if not self._asset:
            return
        ov_copy = copy.copy(item.overlay)
        ov_copy.x += offset
        ov_copy.y += offset
        self._asset.overlays.append(ov_copy)
        new_item = self._create_overlay_item(ov_copy)
        if new_item:
            new_item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(new_item)
        self._update_info()

    def _on_layer_filter_changed(self, text: str):
        """Hide layer rows whose label doesn't contain the filter text."""
        needle = text.strip().lower()
        for i in range(self._layer_panel.count()):
            item = self._layer_panel.item(i)
            if item is None:
                continue
            # Headers ('-- Overlays --') have no UserRole data
            if not item.data(Qt.ItemDataRole.UserRole):
                item.setHidden(bool(needle))
                continue
            label = item.text().lower()
            item.setHidden(bool(needle) and needle not in label)

    def _show_studio_settings(self):
        """Studio-wide settings popup organized into tabs so the long
        list of preferences (snap, grid, rulers, rendering, bubbles,
        tools, shortcuts) fits on a reasonable screen and gets grouped
        by intent. Single place to tune everything — no more hunting
        across ruler right-clicks / canvas right-clicks / toolbar
        toggles for persistent preferences.

        Guards against reopening: if a settings dialog is already
        visible, raise it instead of stacking a duplicate on top."""
        existing = getattr(self, "_settings_dlg", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        qs = QSettings("DoxyEdit", "DoxyEdit")
        dlg = QDialog(self)
        self._settings_dlg = dlg
        dlg.setWindowTitle("Studio Settings")
        dlg.setMinimumWidth(460)
        dlg.setMinimumHeight(540)
        root = QVBoxLayout(dlg)
        tabs = QTabWidget(dlg)
        root.addWidget(tabs)

        # ── Tab: Snap & Grid ─────────────────────────────────────────
        tab_snap = QWidget()
        snap_form = QFormLayout(tab_snap)
        snap_spin = QSpinBox()
        snap_spin.setRange(0, 50)
        snap_spin.setSuffix(" px")
        snap_spin.setValue(qs.value("studio_snap_threshold_px", 0, type=int))
        snap_spin.setToolTip(
            "Distance (px) within which items snap to other edges / "
            "guides. 0 disables snap. F12 toggles.")
        snap_form.addRow("Snap proximity", snap_spin)

        snap_center_cb = QCheckBox("Snap to canvas center lines")
        snap_center_cb.setChecked(qs.value(
            "studio_snap_canvas_center", True, type=bool))
        snap_form.addRow("", snap_center_cb)

        snap_edge_cb = QCheckBox("Snap to canvas edges")
        snap_edge_cb.setChecked(qs.value(
            "studio_snap_canvas_edge", True, type=bool))
        snap_form.addRow("", snap_edge_cb)

        snap_sib_cb = QCheckBox("Snap to other overlays (smart guides)")
        snap_sib_cb.setChecked(qs.value(
            "studio_snap_siblings", True, type=bool))
        snap_form.addRow("", snap_sib_cb)

        grid_cb = QCheckBox("Show snap grid")
        grid_cb.setChecked(qs.value("studio_grid_visible", False, type=bool))
        snap_form.addRow("", grid_cb)

        grid_unit_combo = QComboBox()
        grid_unit_combo.addItem("Pixels", "px")
        grid_unit_combo.addItem("Percent of canvas width", "pct")
        cur_grid_unit = qs.value("studio_grid_unit", "px", type=str)
        grid_unit_combo.setCurrentIndex(
            0 if cur_grid_unit != "pct" else 1)
        grid_unit_combo.setToolTip(
            "Grid cells in pixels (fixed) or percent of canvas width "
            "(scales with asset).")
        snap_form.addRow("Grid unit", grid_unit_combo)

        grid_spin = QSpinBox()
        grid_spin.setRange(1, 500)
        grid_spin.setSingleStep(1)
        grid_spin.setSuffix(" px")
        grid_spin.setValue(qs.value(
            "studio_grid_spacing", STUDIO_GRID_SPACING, type=int))
        snap_form.addRow("Grid spacing (px)", grid_spin)

        grid_pct_spin = QDoubleSpinBox()
        grid_pct_spin.setRange(0.5, 50.0)
        grid_pct_spin.setDecimals(1)
        grid_pct_spin.setSingleStep(0.5)
        grid_pct_spin.setSuffix(" %")
        grid_pct_spin.setValue(qs.value(
            "studio_grid_spacing_pct", 5.0, type=float))
        snap_form.addRow("Grid spacing (%)", grid_pct_spin)
        tabs.addTab(tab_snap, "Snap / Grid")

        # ── Tab: View ────────────────────────────────────────────────
        tab_view = QWidget()
        view_form = QFormLayout(tab_view)
        rulers_cb = QCheckBox("Show rulers")
        rulers_cb.setChecked(qs.value("studio_rulers_visible", True, type=bool))
        view_form.addRow("", rulers_cb)

        ruler_unit_combo = QComboBox()
        ruler_unit_combo.addItem("Pixels (px)", "px")
        ruler_unit_combo.addItem("Millimetres (mm)", "mm")
        ruler_unit_combo.addItem("Inches (in)", "in")
        ruler_unit_combo.addItem("Percent (%)", "pct")
        _ru = qs.value("studio_ruler_unit", "px", type=str)
        _ru_idx = {"px": 0, "mm": 1, "in": 2, "pct": 3}.get(_ru, 0)
        ruler_unit_combo.setCurrentIndex(_ru_idx)
        view_form.addRow("Ruler units", ruler_unit_combo)

        thirds_cb = QCheckBox("Rule-of-thirds overlay")
        thirds_cb.setChecked(qs.value("studio_thirds_visible", False, type=bool))
        view_form.addRow("", thirds_cb)

        notes_cb = QCheckBox("Show note overlays")
        notes_cb.setChecked(qs.value("studio_notes_visible", True, type=bool))
        view_form.addRow("", notes_cb)

        minimap_cb = QCheckBox("Show minimap")
        minimap_cb.setChecked(qs.value("studio_minimap_visible", False, type=bool))
        view_form.addRow("", minimap_cb)

        quickbar_cb = QCheckBox("Show Quick Actions bar")
        quickbar_cb.setChecked(qs.value(
            "studio_quickbar_visible", True, type=bool))
        view_form.addRow("", quickbar_cb)

        props_cb = QCheckBox("Show properties row")
        props_cb.setChecked(qs.value(
            "studio_propsrow_visible", True, type=bool))
        view_form.addRow("", props_cb)

        lock_guides_cb = QCheckBox("Lock guides (prevent drag + delete)")
        lock_guides_cb.setChecked(qs.value(
            "studio_lock_guides", False, type=bool))
        lock_guides_cb.setToolTip(
            "When locked, existing ruler guides stay put - no drag, "
            "no double-click delete. Unlock to reposition.")
        view_form.addRow("", lock_guides_cb)

        dim_nonsel_cb = QCheckBox(
            "Dim non-selected overlays when a selection is active")
        dim_nonsel_cb.setChecked(qs.value(
            "studio_dim_nonselected", False, type=bool))
        dim_nonsel_cb.setToolTip(
            "Fades every other overlay to 40% opacity while anything "
            "is selected, so the selection visually pops. Doesn't "
            "change stored overlay opacity.")
        view_form.addRow("", dim_nonsel_cb)
        tabs.addTab(tab_view, "View")

        # ── Tab: Rendering ───────────────────────────────────────────
        tab_render = QWidget()
        rend_form = QFormLayout(tab_render)
        upscale_combo = QComboBox()
        upscale_combo.addItem("Smooth (bilinear)", "smooth")
        upscale_combo.addItem("Nearest (pixel art)", "nearest")
        cur_upscale = qs.value("studio_upscale_mode", "smooth", type=str)
        upscale_combo.setCurrentIndex(0 if cur_upscale != "nearest" else 1)
        upscale_combo.setToolTip(
            "Smoothing applied when the canvas is zoomed in past 100%. "
            "Nearest preserves hard pixel edges for pixel art.")
        rend_form.addRow("Zoom upscale", upscale_combo)

        aa_cb = QCheckBox("Antialias shape + arrow outlines")
        aa_cb.setChecked(qs.value("studio_render_aa", True, type=bool))
        rend_form.addRow("", aa_cb)

        text_aa_cb = QCheckBox("Antialias text")
        text_aa_cb.setChecked(qs.value("studio_render_text_aa", True, type=bool))
        rend_form.addRow("", text_aa_cb)

        hq_cb = QCheckBox("High-quality pixmap transform")
        hq_cb.setChecked(qs.value("studio_render_hq", True, type=bool))
        hq_cb.setToolTip(
            "Slower but higher fidelity when rotating / scaling "
            "images. Turn off for better performance on huge assets.")
        rend_form.addRow("", hq_cb)

        lossless_cb = QCheckBox("Lossless-text rendering (LcdText)")
        lossless_cb.setChecked(qs.value(
            "studio_render_lossless_text", False, type=bool))
        lossless_cb.setToolTip(
            "Uses LCD subpixel-optimised text rendering. Looks great "
            "on LCD monitors, worse on rotated / non-native-DPI screens.")
        rend_form.addRow("", lossless_cb)

        gl_cb = QCheckBox("GPU viewport (OpenGL) [experimental]")
        gl_cb.setChecked(qs.value("studio_use_gl_viewport", False, type=bool))
        gl_cb.setToolTip(
            "Render Studio canvas through OpenGL instead of CPU raster. "
            "EXPERIMENTAL: currently slower than the raster path for most "
            "scenes because GL forces FullViewportUpdate while raster can "
            "repaint only the moving item. Enable to stress-test large "
            "scenes on very high-end GPUs. Requires app restart.")
        rend_form.addRow("", gl_cb)

        canvas_bg_combo = QComboBox()
        canvas_bg_combo.addItem("Theme default", "theme")
        canvas_bg_combo.addItem("Black", "#000000")
        canvas_bg_combo.addItem("White", "#ffffff")
        canvas_bg_combo.addItem("Dark gray", "#3a3a3a")
        canvas_bg_combo.addItem("Light gray", "#cccccc")
        canvas_bg_combo.addItem("Checkerboard", "checker")
        cur_bg = qs.value("studio_bg_color", "theme", type=str)
        _bg_idx = {
            "theme": 0, "#000000": 1, "#ffffff": 2,
            "#3a3a3a": 3, "#cccccc": 4, "checker": 5,
        }.get(cur_bg, 0)
        canvas_bg_combo.setCurrentIndex(_bg_idx)
        rend_form.addRow("Canvas background", canvas_bg_combo)
        tabs.addTab(tab_render, "Rendering")

        # ── Tab: Bubbles ─────────────────────────────────────────────
        tab_bub = QWidget()
        bub_form = QFormLayout(tab_bub)
        autofit_cb = QCheckBox("Auto-fit bubble to text on edit exit")
        autofit_cb.setChecked(qs.value(
            "studio_bubble_autofit", True, type=bool))
        bub_form.addRow("", autofit_cb)

        tail_curve_spin = QDoubleSpinBox()
        tail_curve_spin.setRange(-1.0, 1.0)
        tail_curve_spin.setSingleStep(0.1)
        tail_curve_spin.setDecimals(2)
        tail_curve_spin.setValue(qs.value(
            "studio_bubble_default_tail_curve", 0.0, type=float))
        tail_curve_spin.setToolTip(
            "Default tail curvature on newly-drawn speech / thought "
            "bubbles (-1 = curves left, +1 = curves right, 0 = straight).")
        bub_form.addRow("Default tail curve", tail_curve_spin)

        bubble_margin_spin = QSpinBox()
        bubble_margin_spin.setRange(4, 100)
        bubble_margin_spin.setSuffix(" px")
        bubble_margin_spin.setValue(qs.value(
            "studio_bubble_text_margin", 20, type=int))
        bubble_margin_spin.setToolTip(
            "Padding between bubble interior and the text block when "
            "auto-fit resizes the bubble.")
        bub_form.addRow("Text padding", bubble_margin_spin)
        tabs.addTab(tab_bub, "Bubbles")

        # ── Tab: Tools ───────────────────────────────────────────────
        tab_tools = QWidget()
        tools_form = QFormLayout(tab_tools)
        sticky_cb = QCheckBox("Sticky tools (stay selected after use)")
        sticky_cb.setChecked(qs.value(
            "studio_sticky_tools", True, type=bool))
        tools_form.addRow("", sticky_cb)

        nudge_spin = QSpinBox()
        nudge_spin.setRange(1, 50)
        nudge_spin.setSuffix(" px")
        nudge_spin.setValue(qs.value(
            "studio_nudge_step", 1, type=int))
        nudge_spin.setToolTip(
            "Arrow-key nudge distance for selected overlays.")
        tools_form.addRow("Nudge distance", nudge_spin)

        shift_mult_spin = QSpinBox()
        shift_mult_spin.setRange(2, 100)
        shift_mult_spin.setValue(qs.value(
            "studio_nudge_shift_mult", 10, type=int))
        shift_mult_spin.setToolTip(
            "Multiplier for Shift+arrow nudge (e.g. 10 = Shift+arrow "
            "moves 10× the base nudge).")
        tools_form.addRow("Shift nudge multiplier", shift_mult_spin)

        wheel_zoom_combo = QComboBox()
        wheel_zoom_combo.addItem(
            "Plain wheel = zoom, Shift+wheel = pan", "zoom")
        wheel_zoom_combo.addItem(
            "Plain wheel = pan, Ctrl+wheel = zoom", "pan")
        cur_ws = qs.value("studio_wheel_scheme", "zoom", type=str)
        wheel_zoom_combo.setCurrentIndex(0 if cur_ws != "pan" else 1)
        tools_form.addRow("Mouse wheel", wheel_zoom_combo)

        pan_accel_spin = QDoubleSpinBox()
        pan_accel_spin.setRange(0.1, 5.0)
        pan_accel_spin.setSingleStep(0.1)
        pan_accel_spin.setDecimals(2)
        pan_accel_spin.setValue(qs.value(
            "studio_pan_accel", 1.0, type=float))
        pan_accel_spin.setToolTip(
            "Multiplier for Space+drag / middle-drag pan speed.")
        tools_form.addRow("Pan speed", pan_accel_spin)
        tabs.addTab(tab_tools, "Tools")

        # ── Tab: Reset ───────────────────────────────────────────────
        tab_reset = QWidget()
        reset_form = QFormLayout(tab_reset)
        reset_form.addRow(QLabel(
            "<i>Recovery actions - take effect immediately.</i>"))

        _btn_reset_dlg = QPushButton("Reset floating panel positions")
        _btn_reset_dlg.setToolTip(
            "Clear saved geometry for Text Controls, Shape Controls, "
            "and the undo-history popup. They'll open at a default "
            "spot next time.")
        def _reset_dialogs():
            for key in ("studio_text_controls_geom",
                         "studio_shape_controls_geom",
                         "studio_undo_history_geom"):
                qs.remove(key)
            # Also reset the 'positioned_once' flag on live dialogs so
            # they reposition on next show.
            for dlg_attr in ("_text_controls_dlg",
                              "_shape_controls_dlg"):
                _d = getattr(self, dlg_attr, None)
                if _d is not None and hasattr(_d, "_positioned_once"):
                    _d._positioned_once = False
            self.info_label.setText("Reset floating panel positions")
        _btn_reset_dlg.clicked.connect(_reset_dialogs)
        reset_form.addRow("", _btn_reset_dlg)

        _btn_clear_bm = QPushButton("Clear view bookmarks (F5..F8)")
        _btn_clear_bm.setToolTip(
            "Wipe the four view-bookmark slots. Shift+F5..F8 sets "
            "them fresh.")
        def _clear_bookmarks():
            for slot in (1, 2, 3, 4):
                qs.remove(f"studio_view_bookmark_{slot}")
            self.info_label.setText("Cleared view bookmarks")
        _btn_clear_bm.clicked.connect(_clear_bookmarks)
        reset_form.addRow("", _btn_clear_bm)

        _btn_reset_recent = QPushButton("Clear recent colors")
        _btn_reset_recent.setToolTip(
            "Empty the swatch-grid of recently-picked colors.")
        def _clear_recents():
            qs.setValue("studio_recent_colors", "")
            if hasattr(self, "_refresh_recent_swatches"):
                self._refresh_recent_swatches()
            self.info_label.setText("Cleared recent colors")
        _btn_reset_recent.clicked.connect(_clear_recents)
        reset_form.addRow("", _btn_reset_recent)
        tabs.addTab(tab_reset, "Reset")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        root.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        win = self.window()
        if win is not None:
            dlg.setStyleSheet(win.styleSheet())
            if hasattr(win, "_theme_dialog_titlebar"):
                dlg.show()
                win._theme_dialog_titlebar(dlg)
                dlg.hide()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # Apply + persist
        qs.setValue("studio_snap_threshold_px", snap_spin.value())
        if hasattr(self, "_scene"):
            self._scene.reload_snap_threshold()
        qs.setValue("studio_snap_canvas_center", snap_center_cb.isChecked())
        qs.setValue("studio_snap_canvas_edge", snap_edge_cb.isChecked())
        qs.setValue("studio_snap_siblings", snap_sib_cb.isChecked())
        qs.setValue("studio_grid_visible", grid_cb.isChecked())
        qs.setValue("studio_grid_unit", grid_unit_combo.currentData())
        qs.setValue("studio_grid_spacing", grid_spin.value())
        qs.setValue("studio_grid_spacing_pct", grid_pct_spin.value())
        qs.setValue("studio_rulers_visible", rulers_cb.isChecked())
        qs.setValue("studio_ruler_unit", ruler_unit_combo.currentData())
        if self._canvas_wrap is not None:
            self._canvas_wrap._h_ruler.reload_unit()
            self._canvas_wrap._v_ruler.reload_unit()
        qs.setValue("studio_thirds_visible", thirds_cb.isChecked())
        qs.setValue("studio_notes_visible", notes_cb.isChecked())
        qs.setValue("studio_minimap_visible", minimap_cb.isChecked())
        qs.setValue("studio_quickbar_visible", quickbar_cb.isChecked())
        qs.setValue("studio_propsrow_visible", props_cb.isChecked())
        qs.setValue("studio_lock_guides", lock_guides_cb.isChecked())
        qs.setValue("studio_dim_nonselected", dim_nonsel_cb.isChecked())
        # Propagate guide lock to existing guide items immediately
        for _g in self._guide_items:
            _g.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                not lock_guides_cb.isChecked())
        # Trigger dim-nonselected reflow if selection already exists
        if hasattr(self, "_apply_dim_nonselected"):
            # Invalidate the per-editor cache first so the next call
            # reads the just-saved QSettings value.
            if hasattr(self, "_invalidate_dim_cache"):
                self._invalidate_dim_cache()
            self._apply_dim_nonselected()
        qs.setValue("studio_upscale_mode", upscale_combo.currentData())
        qs.setValue("studio_render_aa", aa_cb.isChecked())
        qs.setValue("studio_render_text_aa", text_aa_cb.isChecked())
        qs.setValue("studio_render_hq", hq_cb.isChecked())
        qs.setValue("studio_render_lossless_text", lossless_cb.isChecked())
        qs.setValue("studio_use_gl_viewport", gl_cb.isChecked())
        qs.setValue("studio_bg_color", canvas_bg_combo.currentData())
        qs.setValue("studio_bubble_autofit", autofit_cb.isChecked())
        qs.setValue("studio_bubble_default_tail_curve", tail_curve_spin.value())
        qs.setValue("studio_bubble_text_margin", bubble_margin_spin.value())
        qs.setValue("studio_sticky_tools", sticky_cb.isChecked())
        qs.setValue("studio_nudge_step", nudge_spin.value())
        qs.setValue("studio_nudge_shift_mult", shift_mult_spin.value())
        qs.setValue("studio_wheel_scheme", wheel_zoom_combo.currentData())
        # Invalidate the per-view wheel-scheme cache so the next wheel
        # event re-reads the just-saved value.
        if hasattr(self, "_view") and hasattr(self._view, "_wheel_scheme_cached"):
            self._view._wheel_scheme_cached = None
        qs.setValue("studio_pan_accel", pan_accel_spin.value())
        # Reflect the check-state in the matching toolbar toggles so the
        # UI stays in sync without a restart.
        if hasattr(self, "chk_grid"):
            self.chk_grid.setChecked(grid_cb.isChecked())
        if hasattr(self, "chk_thirds"):
            self.chk_thirds.setChecked(thirds_cb.isChecked())
        if hasattr(self, "chk_rulers"):
            self.chk_rulers.setChecked(rulers_cb.isChecked())
        if hasattr(self, "chk_notes"):
            self.chk_notes.setChecked(notes_cb.isChecked())
        if hasattr(self, "chk_minimap"):
            self.chk_minimap.setChecked(minimap_cb.isChecked())
        if hasattr(self, "spin_grid"):
            self.spin_grid.setValue(grid_spin.value())
        # Apply quickbar / props row visibility
        if hasattr(self, "_quickbar_wrap"):
            self._quickbar_wrap.setVisible(quickbar_cb.isChecked())
        if hasattr(self, "_props_row"):
            self._props_row.setVisible(props_cb.isChecked())
        # Apply rendering flags
        if hasattr(self, "_view"):
            self._view.setRenderHint(
                QPainter.RenderHint.SmoothPixmapTransform,
                upscale_combo.currentData() != "nearest" and hq_cb.isChecked())
            self._view.setRenderHint(
                QPainter.RenderHint.Antialiasing, aa_cb.isChecked())
            self._view.setRenderHint(
                QPainter.RenderHint.TextAntialiasing, text_aa_cb.isChecked())
            self._view.setRenderHint(
                QPainter.RenderHint.LosslessImageRendering, hq_cb.isChecked())
        self.info_label.setText("Studio settings saved")

    def _show_shortcuts_cheat_sheet(self):
        """Modal popup listing the Studio keyboard shortcuts. Grouped by
        task so users can scan it, not read it. Opened via Ctrl+/.

        If a previous cheatsheet is still open, raise it instead of
        spawning a duplicate - users would double-press Ctrl+/ and end
        up with two stacked dialogs otherwise."""
        existing = getattr(self, "_shortcuts_dlg", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dlg = QDialog(self)
        self._shortcuts_dlg = dlg
        dlg.setWindowTitle("Studio Shortcuts")
        dlg.resize(640, 640)
        layout = QVBoxLayout(dlg)
        view = QTextBrowser(dlg)
        view.setOpenExternalLinks(False)
        view.setStyleSheet("QTextBrowser { padding: 12px; }")
        view.setHtml(
            "<h2>Studio Keyboard Shortcuts</h2>"
            "<p><i>Press Esc in most popups to close. F1 or Ctrl+/ "
            "opens this cheatsheet.</i></p>"
            "<h3>Tools</h3>"
            "<table cellspacing=6>"
            "<tr><td><b>Q / V</b></td><td>Select</td></tr>"
            "<tr><td><b>T</b></td><td>Text tool</td></tr>"
            "<tr><td><b>X</b></td><td>Censor</td></tr>"
            "<tr><td><b>C</b></td><td>Crop</td></tr>"
            "<tr><td><b>N</b></td><td>Note</td></tr>"
            "<tr><td><b>E</b></td><td>Watermark / logo</td></tr>"
            "<tr><td><b>A</b></td><td>Arrow</td></tr>"
            "<tr><td><b>I</b></td><td>Eyedropper</td></tr>"
            "<tr><td><b>B / Shift+B / K</b></td>"
            "<td>Speech bubble / thought bubble / burst (+ edit)</td></tr>"
            "<tr><td><b>F2</b></td><td>Rename selected layer</td></tr>"
            "</table>"
            "<h3>View + Zoom</h3>"
            "<table cellspacing=6>"
            "<tr><td><b>Ctrl+0</b></td><td>Fit view</td></tr>"
            "<tr><td><b>Ctrl+1 / 2 / 3 / 4</b></td>"
            "<td>Zoom 100% / 200% / 300% / 400%</td></tr>"
            "<tr><td><b>Ctrl+= / Ctrl+-</b></td><td>Zoom in / out</td></tr>"
            "<tr><td><b>+ / -</b> (numpad / plain)</td>"
            "<td>Zoom in / out</td></tr>"
            "<tr><td><b>F</b></td><td>Fit view</td></tr>"
            "<tr><td><b>Shift+F</b></td><td>Fit to selection</td></tr>"
            "<tr><td><b>F3 / F4</b></td>"
            "<td>Toggle snap grid / rule-of-thirds</td></tr>"
            "<tr><td><b>F9</b></td><td>Toggle minimap</td></tr>"
            "<tr><td><b>F11 / .</b></td><td>Toggle focus mode</td></tr>"
            "<tr><td><b>F12</b></td><td>Toggle snap</td></tr>"
            "<tr><td><b>Space</b> (hold)</td><td>Pan</td></tr>"
            "<tr><td><b>Middle-drag</b></td><td>Pan</td></tr>"
            "<tr><td><b>\\</b> (hold)</td>"
            "<td>Peek: temporarily hide all overlays</td></tr>"
            "<tr><td><b>Ctrl+Alt+P</b></td>"
            "<td>Sticky preview mode (toggle)</td></tr>"
            "<tr><td><b>Ctrl+H</b></td><td>Hide all helpers</td></tr>"
            "<tr><td><b>Ctrl+;</b></td><td>Hide / show guides</td></tr>"
            "<tr><td><b>Shift+H / Shift+V</b></td>"
            "<td>Drop horizontal / vertical guide at cursor</td></tr>"
            "<tr><td><b>Ctrl+Shift+T</b></td>"
            "<td>Toggle left tool palette</td></tr>"
            "<tr><td><b>F5..F8 / Shift+F5..F8</b></td>"
            "<td>Recall / save view bookmark 1..4</td></tr>"
            "</table>"
            "<h3>Edit</h3>"
            "<table cellspacing=6>"
            "<tr><td><b>Ctrl+Z</b> / <b>Ctrl+Shift+Z / Ctrl+Y</b></td>"
            "<td>Undo / redo</td></tr>"
            "<tr><td><b>Ctrl+D</b> / <b>Ctrl+J</b></td>"
            "<td>Duplicate selected (20 px offset)</td></tr>"
            "<tr><td><b>Ctrl+Alt+D</b></td>"
            "<td>Duplicate in place (no offset)</td></tr>"
            "<tr><td><b>Ctrl+C / Ctrl+V</b></td>"
            "<td>Copy / paste selected overlays</td></tr>"
            "<tr><td><b>Ctrl+Shift+V</b></td><td>Paste in place</td></tr>"
            "<tr><td><b>Ctrl+Alt+C / Ctrl+Alt+V</b></td>"
            "<td>Copy / paste style</td></tr>"
            "<tr><td><b>Alt+drag</b> on overlay</td>"
            "<td>Duplicate while dragging</td></tr>"
            "<tr><td><b>Ctrl+T / Ctrl+Alt+T</b></td>"
            "<td>Transform dialog (X / Y / W / H / rot / skew)</td></tr>"
            "<tr><td><b>Ctrl+Alt+S</b></td><td>Scale selection by %</td></tr>"
            "<tr><td><b>Ctrl+F</b></td>"
            "<td>Find and replace text across all overlays</td></tr>"
            "<tr><td><b>Ctrl+Alt+X</b></td>"
            "<td>Swap fill ↔ stroke on selected shapes</td></tr>"
            "<tr><td><b>Ctrl+Shift+O</b></td>"
            "<td>Toggle stroke on / off (selected shapes)</td></tr>"
            "<tr><td><b>Ctrl+R / Ctrl+Shift+R</b></td>"
            "<td>Rotate 1° CW / CCW</td></tr>"
            "<tr><td><b>R</b></td><td>Rotate 90°</td></tr>"
            "<tr><td><b>Alt+wheel</b></td><td>Rotate ±5°</td></tr>"
            "<tr><td><b>Ctrl+Shift+H / V</b></td>"
            "<td>Flip horizontal / vertical</td></tr>"
            "<tr><td><b>Ctrl+Shift+0</b></td>"
            "<td>Reset rotation + skew</td></tr>"
            "<tr><td><b>Ctrl+Shift+N</b></td>"
            "<td>Add new text overlay at cursor</td></tr>"
            "<tr><td><b>Del / Backspace</b></td><td>Delete selected</td></tr>"
            "<tr><td><b>Arrow keys</b></td><td>Nudge 1 px</td></tr>"
            "<tr><td><b>Shift + Arrow</b></td><td>Nudge 10 px</td></tr>"
            "<tr><td><b>Shift+Ctrl + Arrow</b></td><td>Nudge 100 px</td></tr>"
            "<tr><td><b>0-9</b></td>"
            "<td>Set opacity 100% / 10% / ... / 90%</td></tr>"
            "<tr><td><b>[ / ]</b></td>"
            "<td>Shrink / grow arrowhead size + shape stroke width</td></tr>"
            "<tr><td><b>Alt+Shift+wheel</b></td>"
            "<td>Opacity ± 5 %</td></tr>"
            "</table>"
            "<h3>Select</h3>"
            "<table cellspacing=6>"
            "<tr><td><b>Ctrl+A</b></td><td>Select all</td></tr>"
            "<tr><td><b>Ctrl+Shift+A / Ctrl+Shift+D</b></td>"
            "<td>Deselect all</td></tr>"
            "<tr><td><b>Ctrl+Shift+I</b></td><td>Invert selection</td></tr>"
            "<tr><td><b>Ctrl+Alt+. / Ctrl+Alt+,</b></td>"
            "<td>Cycle next / previous overlapping</td></tr>"
            "<tr><td><b>Tab</b></td><td>Cycle selection</td></tr>"
            "<tr><td><b>Home / End</b></td>"
            "<td>Select first / last overlay</td></tr>"
            "<tr><td><b>Ctrl+Shift+B</b></td>"
            "<td>Copy selection geometry to clipboard</td></tr>"
            "<tr><td><b>Ctrl+Shift+C</b></td>"
            "<td>Copy selection color to clipboard</td></tr>"
            "</table>"
            "<h3>Align / Distribute</h3>"
            "<table cellspacing=6>"
            "<tr><td><b>Alt+Shift+L / R / C</b></td>"
            "<td>Align left / right / horizontal center</td></tr>"
            "<tr><td><b>Alt+Shift+T / B / M</b></td>"
            "<td>Align top / bottom / vertical middle</td></tr>"
            "<tr><td><b>Alt+Shift+H / V</b></td>"
            "<td>Distribute horizontally / vertically (3+)</td></tr>"
            "</table>"
            "<h3>Text (inside edit mode)</h3>"
            "<table cellspacing=6>"
            "<tr><td><b>Ctrl+B / I / U / Shift+X</b></td>"
            "<td>Bold / italic / underline / strikethrough</td></tr>"
            "<tr><td><b>Ctrl+Shift+L / R / E</b></td>"
            "<td>Align left / right / center</td></tr>"
            "<tr><td><b>Ctrl+Alt+L / R / E</b></td>"
            "<td>Align left / right / center (overlay-level)</td></tr>"
            "<tr><td><b>Ctrl+Shift+&gt; / &lt;</b></td>"
            "<td>Font size +2pt / -2pt</td></tr>"
            "<tr><td><b>Esc</b></td><td>Commit + exit edit mode</td></tr>"
            "</table>"
            "<h3>Arrange (Z-order)</h3>"
            "<table cellspacing=6>"
            "<tr><td><b>Ctrl+] / Ctrl+[</b></td>"
            "<td>Bring forward / send backward</td></tr>"
            "<tr><td><b>Ctrl+Shift+] / Ctrl+Shift+[</b></td>"
            "<td>Bring to front / send to back</td></tr>"
            "<tr><td><b>Alt+Up / Down</b></td>"
            "<td>Bring forward / send backward (alias)</td></tr>"
            "<tr><td><b>Alt+] / Alt+[</b></td>"
            "<td>Select next / previous layer (wraps)</td></tr>"
            "<tr><td><b>Alt+I</b></td>"
            "<td>Toggle Isolation on first selected layer</td></tr>"
            "<tr><td><b>Alt+B / Alt+Shift+B</b></td>"
            "<td>Cycle blend mode forward / backward</td></tr>"
            "<tr><td><b>Ctrl+L</b></td><td>Lock / unlock selected</td></tr>"
            "<tr><td><b>Ctrl+Alt+L</b></td><td>Lock / unlock all</td></tr>"
            "<tr><td><b>Ctrl+G / Ctrl+Shift+G</b></td>"
            "<td>Group / ungroup selection</td></tr>"
            "<tr><td><b>H</b> (with selection)</td>"
            "<td>Toggle overlay visibility</td></tr>"
            "<tr><td><b>Alt+H</b></td>"
            "<td>Toggle visibility on every selected overlay</td></tr>"
            "<tr><td><b>Ctrl+Alt+H</b></td>"
            "<td>Un-hide every overlay + censor</td></tr>"
            "<tr><td><b>Alt+N</b></td>"
            "<td>Toggle note-overlay visibility</td></tr>"
            "</table>"
            "<h3>Text Controls / Shape Controls popup</h3>"
            "<table cellspacing=6>"
            "<tr><td><b>Ctrl+P</b></td>"
            "<td>Pin on top (stays above other windows)</td></tr>"
            "<tr><td><b>Ctrl+Shift+L / Ctrl+Shift+R</b></td>"
            "<td>Snap to left / right screen edge (full height)</td></tr>"
            "</table>"
            "<h3>Other</h3>"
            "<table cellspacing=6>"
            "<tr><td><b>F10</b></td>"
            "<td>Nuclear clear (exit text edit, drop crop mask)</td></tr>"
            "<tr><td><b>Ctrl+,</b></td><td>Open Studio Settings</td></tr>"
            "<tr><td><b>Ctrl+/ / F1</b></td>"
            "<td>Open this cheatsheet</td></tr>"
            "</table>"
        )
        layout.addWidget(view)
        win = self.window()
        if win is not None:
            dlg.setStyleSheet(win.styleSheet())
            if hasattr(win, "_theme_dialog_titlebar"):
                dlg.show()
                win._theme_dialog_titlebar(dlg)
                return
        dlg.exec()

    def _open_transform_dialog(self):
        """Ctrl+T Transform dialog — the universal 'everything about
        position + rotation + scale + skew' popup. Replaces the smaller
        numeric-only transform from Ctrl+Alt+T. Applies to the first
        selected overlay; shape / image / text all supported. Arrows
        use endpoints — see the arrow-specific context menu instead.

        Guards against reopening: Ctrl+T while an existing Transform
        dialog is visible raises it instead of stacking a duplicate."""
        existing = getattr(self, "_transform_dlg", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        sel = [it for it in self._scene.selectedItems()
               if isinstance(it, (OverlayImageItem, OverlayTextItem,
                                   OverlayShapeItem))]
        if not sel:
            self.info_label.setText("Nothing to transform")
            return
        dlg = QDialog(self)
        self._transform_dlg = dlg
        dlg.setWindowTitle("Transform")
        dlg.setMinimumWidth(320)
        form = QFormLayout(dlg)
        item = sel[0]
        ov = item.overlay
        rect = item.sceneBoundingRect()

        form.addRow(QLabel("<b>Position</b>"))
        sx = QSpinBox(); sx.setRange(-99999, 99999); sx.setSuffix(" px")
        sx.setValue(int(ov.x))
        sy = QSpinBox(); sy.setRange(-99999, 99999); sy.setSuffix(" px")
        sy.setValue(int(ov.y))
        form.addRow("X", sx)
        form.addRow("Y", sy)

        form.addRow(QLabel("<b>Size</b>"))
        sw = QSpinBox(); sw.setRange(1, 99999); sw.setSuffix(" px")
        sh = QSpinBox(); sh.setRange(1, 99999); sh.setSuffix(" px")
        if isinstance(item, OverlayShapeItem):
            sw.setValue(int(ov.shape_w))
            sh.setValue(int(ov.shape_h))
        else:
            sw.setValue(max(1, int(rect.width())))
            sh.setValue(max(1, int(rect.height())))
            if isinstance(item, OverlayTextItem):
                sw.setEnabled(False)
                sh.setEnabled(False)
        form.addRow("Width", sw)
        form.addRow("Height", sh)
        # Aspect-lock toggle. When on, editing W drives H proportionally.
        aspect_cb = QCheckBox("Lock aspect ratio")
        form.addRow("", aspect_cb)
        _ar = [sw.value() / max(1, sh.value())]
        def _w_changed(v):
            if aspect_cb.isChecked() and sh.isEnabled():
                sh.blockSignals(True)
                sh.setValue(max(1, int(v / _ar[0])))
                sh.blockSignals(False)
        def _h_changed(v):
            if aspect_cb.isChecked() and sw.isEnabled():
                sw.blockSignals(True)
                sw.setValue(max(1, int(v * _ar[0])))
                sw.blockSignals(False)
        sw.valueChanged.connect(_w_changed)
        sh.valueChanged.connect(_h_changed)

        form.addRow(QLabel("<b>Rotation / Skew</b>"))
        sr = QSpinBox(); sr.setRange(-360, 360); sr.setSuffix("°")
        sr.setValue(int(ov.rotation))
        form.addRow("Rotation", sr)
        skew_x = QDoubleSpinBox()
        skew_x.setRange(-85.0, 85.0); skew_x.setSuffix("°")
        skew_x.setValue(float(ov.skew_x))
        skew_x.setToolTip("Horizontal skew in degrees (-85 to 85)")
        form.addRow("Skew X", skew_x)
        skew_y = QDoubleSpinBox()
        skew_y.setRange(-85.0, 85.0); skew_y.setSuffix("°")
        skew_y.setValue(float(ov.skew_y))
        skew_y.setToolTip("Vertical skew in degrees (-85 to 85)")
        form.addRow("Skew Y", skew_y)

        form.addRow(QLabel("<b>Flip</b>"))
        flip_row = QHBoxLayout()
        flip_h = QCheckBox("Horizontal")
        flip_h.setChecked(bool(ov.flip_h))
        flip_v = QCheckBox("Vertical")
        flip_v.setChecked(bool(ov.flip_v))
        flip_row.addWidget(flip_h); flip_row.addWidget(flip_v); flip_row.addStretch()
        _fw = QWidget()
        _fw.setLayout(flip_row)
        form.addRow("", _fw)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Reset)
        form.addRow(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        def _reset():
            sr.setValue(0)
            skew_x.setValue(0.0)
            skew_y.setValue(0.0)
            flip_h.setChecked(False)
            flip_v.setChecked(False)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(
            _reset)

        win = self.window()
        if win is not None:
            dlg.setStyleSheet(win.styleSheet())
            if hasattr(win, "_theme_dialog_titlebar"):
                dlg.show()
                win._theme_dialog_titlebar(dlg)
                dlg.hide()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ov.x = sx.value()
        ov.y = sy.value()
        ov.rotation = sr.value() % 360
        ov.skew_x = skew_x.value()
        ov.skew_y = skew_y.value()
        ov.flip_h = flip_h.isChecked()
        ov.flip_v = flip_v.isChecked()
        if isinstance(item, OverlayShapeItem):
            ov.shape_w = sw.value()
            ov.shape_h = sh.value()
            self._apply_transform_to_shape(item)
        elif isinstance(item, OverlayImageItem):
            item.setPos(ov.x, ov.y)
            if hasattr(item, "_apply_flip"):
                item._apply_flip()
        elif isinstance(item, OverlayTextItem):
            item.setPos(ov.x, ov.y)
            if hasattr(item, "_apply_flip_text"):
                item._apply_flip_text()
        self._sync_overlays_to_asset()
        self.info_label.setText(
            f"Transformed: {sx.value()}, {sy.value()}  rot {sr.value()}°")

    def _apply_transform_to_shape(self, item):
        """Combine rotation + skew_x + skew_y into the shape's QTransform.
        Pivots on the body center so rotation / skew feel natural."""
        ov = item.overlay
        cx = ov.x + ov.shape_w / 2
        cy = ov.y + ov.shape_h / 2
        item.setTransformOriginPoint(cx, cy)
        t = QTransform()
        if ov.skew_x or ov.skew_y:
            t.shear(math.tan(math.radians(ov.skew_x)),
                    math.tan(math.radians(ov.skew_y)))
        item.setTransform(t)
        item.setRotation(ov.rotation)
        item.prepareGeometryChange()
        item.update()

    def _rotate_selected(self, step: int):
        """Add step degrees to the rotation of every selected overlay."""
        touched = False
        for item in self._scene.selectedItems():
            ov = getattr(item, "overlay", None)
            if ov is None:
                continue
            ov.rotation = (ov.rotation + step) % 360
            if hasattr(item, "_apply_flip"):
                item._apply_flip()
            elif hasattr(item, "_apply_flip_text"):
                item._apply_flip_text()
            elif isinstance(item, OverlayShapeItem):
                item.setTransformOriginPoint(
                    ov.x + ov.shape_w / 2, ov.y + ov.shape_h / 2)
                item.setRotation(ov.rotation)
                item.update()
            else:
                item.prepareGeometryChange()
                item.update()
            touched = True
        if touched:
            self._sync_overlays_to_asset()

    def _cycle_selection(self, direction: int):
        """Tab / Shift+Tab: cycle through selectable scene items."""
        candidates = [it for it in self._scene.items()
                      if isinstance(it, _CANVAS_ITEM_TYPES)
                      and it.parentItem() is None]
        if not candidates:
            return
        # Sort for stable cycling — use Y then X of sceneBoundingRect
        candidates.sort(key=lambda it: (it.sceneBoundingRect().y(),
                                         it.sceneBoundingRect().x()))
        sel = [it for it in candidates if it.isSelected()]
        if not sel:
            new = candidates[0 if direction > 0 else -1]
        else:
            idx = candidates.index(sel[0])
            new = candidates[(idx + direction) % len(candidates)]
        self._scene.clearSelection()
        new.setSelected(True)
        self._view.centerOn(new)

    def _duplicate_selected(self, offset: int = 20):
        """Duplicate selected overlays, censors, arrows, shapes, and crops.
        `offset` (px) is applied to the duplicate's x/y so consecutive
        Ctrl+D strokes walk away from the original. Ctrl+Alt+D sets
        offset=0 for a stamp-in-place."""
        for item in list(self._scene.selectedItems()):
            if isinstance(item, (OverlayImageItem, OverlayTextItem)):
                self._duplicate_overlay_item(item, offset=offset)
            elif isinstance(item, OverlayArrowItem):
                self._duplicate_arrow_item(item, offset=offset)
            elif isinstance(item, OverlayShapeItem):
                self._duplicate_shape_item(item, offset=offset)
            elif isinstance(item, CensorRectItem):
                self._duplicate_censor_item(item, offset=offset)
            elif isinstance(item, ResizableCropItem):
                self._scene._duplicate_crop(self, item)

    def _duplicate_censor_item(self, item, offset: int = 20):
        """Clone a censor with optional x/y offset (default 20 px)."""
        cr_src = getattr(item, "_censor_region", None)
        if cr_src is None or not self._asset:
            return
        new_cr = CensorRegion(
            x=cr_src.x + offset, y=cr_src.y + offset,
            w=cr_src.w, h=cr_src.h,
            style=cr_src.style,
            blur_radius=cr_src.blur_radius,
            pixelate_ratio=cr_src.pixelate_ratio,
            rotation=getattr(cr_src, "rotation", 0.0),
            platforms=list(cr_src.platforms),
        )
        self._asset.censors.append(new_cr)
        new_item = CensorRectItem(
            QRectF(new_cr.x, new_cr.y, new_cr.w, new_cr.h),
            new_cr.style, list(new_cr.platforms),
        )
        new_item._censor_region = new_cr
        new_item._editor = self
        new_item.setZValue(100 + len(self._censor_items))
        self._scene.addItem(new_item)
        self._censor_items.append(new_item)

    def _flip_selected(self, axis: str):
        """Flip all selected overlay items on the given axis ('h' or 'v')."""
        attr = "flip_h" if axis == "h" else "flip_v"
        for item in list(self._scene.selectedItems()):
            if isinstance(item, (OverlayImageItem, OverlayTextItem)):
                cur = getattr(item.overlay, attr, False)
                def _apply_flip_cb(it, v, _attr=attr):
                    # OverlayImageItem has _apply_flip; OverlayTextItem has _apply_flip_text
                    if hasattr(it, "_apply_flip"):
                        it._apply_flip()
                    elif hasattr(it, "_apply_flip_text"):
                        it._apply_flip_text()
                self._push_overlay_attr(
                    item, attr, not cur,
                    apply_cb=_apply_flip_cb,
                    description=f"Flip {axis}",
                )
        self._sync_overlays_to_asset()

    def _z_shift_selected(self, direction: int):
        """Shift Z of all selected overlays.

        direction = +1 / -1: step by one.
        direction = +999 / -999: promote to topmost / bottommost among
        siblings (true 'Bring to Front' / 'Send to Back' semantics).
        """
        z_classes = (
            OverlayImageItem, OverlayTextItem,
            OverlayShapeItem, OverlayArrowItem, CensorRectItem,
        )
        if not any(
            isinstance(it, z_classes)
            for it in self._scene.selectedItems()
        ):
            return
        # Precompute the max / min z across all z-enabled scene items so
        # Front / Back jumps over everything, not just siblings of the
        # selection.
        all_items = [
            it for it in self._scene.items() if isinstance(it, z_classes)
        ]
        max_z = max((it.zValue() for it in all_items), default=0.0)
        min_z = min((it.zValue() for it in all_items), default=0.0)
        floor_z = 100  # matches the existing SetZValueCmd min for censors
        big = abs(direction) >= 900
        label = (
            "Bring to front" if direction > 0 and big else
            "Send to back" if direction < 0 and big else
            "Bring forward" if direction > 0 else
            "Send backward"
        )
        moved = 0
        for item in list(self._scene.selectedItems()):
            if not isinstance(item, z_classes):
                continue
            cur = item.zValue()
            if big and direction > 0:
                new_z = max_z + 1
            elif big and direction < 0:
                new_z = max(floor_z, min_z - 1)
            else:
                new_z = cur + direction
                if direction < 0:
                    new_z = max(floor_z, new_z)
            if new_z == cur:
                continue
            cmd = SetZValueCmd(item, cur, new_z, label)
            self._undo_stack.push(cmd)
            moved += 1
        try:
            if moved:
                self.info_label.setText(
                    f"{label}: {moved} layer{'s' if moved != 1 else ''}")
            else:
                # Nothing actually changed — most likely already at the
                # limit ('already at front' after a Front command).
                self.info_label.setText(f"{label}: already at limit")
        except Exception:
            pass

    def _select_layer_relative(self, direction: int):
        """Select the overlay one step above (+1) or below (-1) the
        currently-selected one in scene z-order. Wraps at the ends so
        Alt+] past the top goes back to the bottom (Illustrator /
        Photoshop convention). Ignores locked + disabled overlays so the
        cycle lands only on interactive items."""
        z_classes = (
            OverlayImageItem, OverlayTextItem,
            OverlayShapeItem, OverlayArrowItem, CensorRectItem,
        )
        candidates = [
            it for it in self._scene.items()
            if isinstance(it, z_classes) and it.isVisible()
            and (it.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        ]
        if not candidates:
            return
        candidates.sort(key=lambda it: it.zValue())
        selected = [it for it in candidates if it.isSelected()]
        if selected:
            idx = candidates.index(selected[0])
            new_idx = (idx + direction) % len(candidates)
        else:
            new_idx = 0 if direction > 0 else len(candidates) - 1
        self._scene.clearSelection()
        target = candidates[new_idx]
        target.setSelected(True)
        try:
            self._view.centerOn(target)
        except Exception:
            pass
        # Flash a status message so the user knows which layer is now
        # active without having to glance at the layer panel.
        ov = getattr(target, "overlay", None)
        label = (
            (ov and (ov.label or ov.text))
            or target.__class__.__name__
                .replace("Overlay", "").replace("Item", "")
        )
        try:
            self.info_label.setText(
                f"Layer {new_idx + 1}/{len(candidates)}: {label}")
        except Exception:
            pass

    # ---- alignment + distribute ----

    def _show_align_menu(self):
        """Dropdown from the Align toolbar button with alignment actions."""
        menu = _themed_menu(self)
        a_left = menu.addAction("Align Left")
        a_right = menu.addAction("Align Right")
        a_top = menu.addAction("Align Top")
        a_bottom = menu.addAction("Align Bottom")
        menu.addSeparator()
        a_ch = menu.addAction("Center Horizontal")
        a_cv = menu.addAction("Center Vertical")
        menu.addSeparator()
        a_cc_h = menu.addAction("Center on Canvas (Horizontal)")
        a_cc_v = menu.addAction("Center on Canvas (Vertical)")
        a_cc_b = menu.addAction("Center on Canvas (Both)")
        menu.addSeparator()
        a_dh = menu.addAction("Distribute Horizontal")
        a_dv = menu.addAction("Distribute Vertical")
        menu.addSeparator()
        a_stack_h = menu.addAction("Stack in Row (top-aligned)")
        a_stack_v = menu.addAction("Stack in Column (left-aligned)")
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
        elif chosen is a_cc_h:
            self._center_on_canvas("h")
        elif chosen is a_cc_v:
            self._center_on_canvas("v")
        elif chosen is a_cc_b:
            self._center_on_canvas("both")
        elif chosen is a_dh:
            self._distribute_selected("h")
        elif chosen is a_dv:
            self._distribute_selected("v")
        elif chosen is a_stack_h:
            self._stack_selected("h")
        elif chosen is a_stack_v:
            self._stack_selected("v")

    def _center_on_canvas(self, axis: str):
        """Move selected items so their bounding rect center matches the
        canvas (pixmap) center on the given axis."""
        if not self._pixmap_item:
            return
        canvas_rect = self._pixmap_item.sceneBoundingRect()
        cx = canvas_rect.center().x()
        cy = canvas_rect.center().y()
        for item in self._alignable_items():
            br = item.sceneBoundingRect()
            dx = (cx - br.center().x()) if axis in ("h", "both") else 0.0
            dy = (cy - br.center().y()) if axis in ("v", "both") else 0.0
            if dx or dy:
                item.moveBy(dx, dy)
                if isinstance(item, (OverlayImageItem, OverlayTextItem)):
                    item.overlay.x = int(item.pos().x())
                    item.overlay.y = int(item.pos().y())
                elif isinstance(item, OverlayArrowItem):
                    item.overlay.x += int(dx)
                    item.overlay.y += int(dy)
                    item.overlay.end_x += int(dx)
                    item.overlay.end_y += int(dy)
                    item.prepareGeometryChange()
                    item.update()
        self._sync_overlays_to_asset()
        self._sync_censors_to_asset()

    def _alignable_items(self):
        """Return selected items we can align/distribute (overlays, censors, crops, notes, arrows, shapes)."""
        return [it for it in self._scene.selectedItems()
                if isinstance(it, _CANVAS_ITEM_TYPES)]

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

    def _stack_selected(self, axis: str):
        """Stack the selected items in a row (h) or column (v) with
        equal gaps, aligning the top (row) or left (column) edges.
        Useful for building menu bars, icon strips, list mockups etc.
        Anchored on the left-most / top-most current position."""
        items = self._alignable_items()
        if len(items) < 2:
            self.info_label.setText("Select 2+ items to stack")
            return
        pairs = [(it, it.sceneBoundingRect()) for it in items]
        gap = 8  # default inter-item gap, px
        if axis == "h":
            pairs.sort(key=lambda p: p[1].left())
            top = min(p[1].top() for p in pairs)
            cursor_x = pairs[0][1].left()
            for it, r in pairs:
                dx = cursor_x - r.left()
                dy = top - r.top()
                if dx or dy:
                    it.moveBy(dx, dy)
                cursor_x += r.width() + gap
        else:
            pairs.sort(key=lambda p: p[1].top())
            left = min(p[1].left() for p in pairs)
            cursor_y = pairs[0][1].top()
            for it, r in pairs:
                dx = left - r.left()
                dy = cursor_y - r.top()
                if dx or dy:
                    it.moveBy(dx, dy)
                cursor_y += r.height() + gap
        self._sync_after_align(items)
        self.info_label.setText(
            f"Stacked {len(items)} items "
            f"{'horizontally' if axis == 'h' else 'vertically'}")

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
        from dataclasses import asdict
        overlays, censors = [], []
        for it in self._scene.selectedItems():
            if isinstance(it, _OVERLAY_ITEM_TYPES):
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

    def _paste_items_from_clipboard(self, offset: int = 20):
        """Paste previously-copied overlays + censors, offset from originals.
        Falls back to system-clipboard image (e.g. screenshot) which is
        saved to a cache folder and dropped as a new watermark overlay."""
        mime = QApplication.clipboard().mimeData()
        if not self._asset:
            return
        # System-clipboard image fallback — only fires when there's no
        # DoxyEdit-internal payload.
        if not mime.hasFormat(self._CLIPBOARD_MIME) and mime.hasImage():
            img = QApplication.clipboard().image()
            if img.isNull():
                return
            import tempfile, uuid
            cache_dir = Path(tempfile.gettempdir()) / "doxyedit_clipboard"
            cache_dir.mkdir(parents=True, exist_ok=True)
            fname = cache_dir / f"pasted_{uuid.uuid4().hex[:8]}.png"
            img.save(str(fname), "PNG")
            # Drop at the last known cursor position, centered on the
            # clipboard image's natural size (scaled). Falls back to 60,60
            # if the user hasn't hovered the canvas yet.
            last = self._last_cursor_scene_pos
            if last is not None:
                drop_x = max(0, int(last.x() - img.width() * 0.15))
                drop_y = max(0, int(last.y() - img.height() * 0.15))
            else:
                drop_x, drop_y = 60, 60
            ov = CanvasOverlay(
                type="watermark",
                label=fname.stem,
                image_path=str(fname),
                opacity=1.0,
                scale=0.3,
                position="custom",
                x=drop_x, y=drop_y,
            )
            for k, v in self._load_watermark_style_defaults().items():
                setattr(ov, k, v)
            self._asset.overlays.append(ov)
            new_item = self._create_overlay_item(ov)
            if new_item:
                new_item.setZValue(200 + len(self._overlay_items))
                self._overlay_items.append(new_item)
            self._rebuild_layer_panel()
            self.info_label.setText("Pasted clipboard image as watermark")
            return
        if not mime.hasFormat(self._CLIPBOARD_MIME):
            return
        try:
            raw = bytes(mime.data(self._CLIPBOARD_MIME)).decode("utf-8")
            payload = json.loads(raw)
        except Exception:
            return
        if payload.get("_schema") != self._CLIPBOARD_SCHEMA:
            self.info_label.setText("Clipboard schema mismatch")
            return
        OFFSET = offset
        pasted = 0
        # Overlays
        for od in payload.get("overlays", []):
            try:
                ov = CanvasOverlay.from_dict(od)
                ov.x = int(ov.x) + OFFSET
                ov.y = int(ov.y) + OFFSET
                # Arrow endpoints must move together
                if ov.type == "arrow":
                    ov.end_x = int(ov.end_x) + OFFSET
                    ov.end_y = int(ov.end_y) + OFFSET
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

    def _export_selection_as_transparent_png(self):
        """Render just the currently-selected items onto a transparent PNG
        the size of the scene, cropped to the selection's bounds. Useful
        for extracting a single overlay or group as a standalone asset."""
        sel = self._scene.selectedItems()
        if not sel or not self._pixmap_item:
            return
        # Union bbox with small pad
        bounds = sel[0].sceneBoundingRect()
        for it in sel[1:]:
            bounds = bounds.united(it.sceneBoundingRect())
        bounds = bounds.adjusted(-2, -2, 2, 2)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export selection as transparent PNG", "",
            "PNG (*.png);;All Files (*)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        img = QImage(int(bounds.width()), int(bounds.height()),
                      QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        # Temporarily deselect, hide base + checker so they don't render
        was_pixmap = self._pixmap_item.isVisible()
        checker = getattr(self, "_checker_item", None)
        was_checker = checker.isVisible() if checker else False
        prev_sel = {it: it.isSelected() for it in sel}
        for it in sel:
            it.setSelected(False)
        self._pixmap_item.setVisible(False)
        if checker:
            checker.setVisible(False)
        # Hide all non-selected overlays/censors so only the selection renders
        hidden_by_us = []
        selected_set = set(sel)
        for scene_it in self._scene.items():
            if scene_it in selected_set:
                continue
            if isinstance(scene_it, (OverlayImageItem, OverlayTextItem,
                                       OverlayArrowItem, OverlayShapeItem,
                                       CensorRectItem, NoteRectItem)):
                if scene_it.isVisible():
                    scene_it.setVisible(False)
                    hidden_by_us.append(scene_it)
        p = QPainter(img)
        self._scene.render(p, source=bounds)
        p.end()
        # Restore
        for scene_it in hidden_by_us:
            scene_it.setVisible(True)
        self._pixmap_item.setVisible(was_pixmap)
        if checker:
            checker.setVisible(was_checker)
        for it, was in prev_sel.items():
            it.setSelected(was)
        if img.save(path, "PNG"):
            self.info_label.setText(f"Exported selection: {Path(path).name}")
        else:
            self.info_label.setText("Export failed")

    def _export_overlays_as_transparent_png(self):
        """Render only the overlays/censors/shapes/arrows on a transparent
        background the size of the current image, and save to a user-picked
        path. Useful for sticker packs or asset sharing."""
        if not self._asset or not self._pixmap_item:
            return
        pm = self._pixmap_item.pixmap()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export overlays as transparent PNG",
            "",
            "PNG (*.png);;All Files (*)",
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        img = QImage(pm.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        # Hide the pixmap + checkerboard before render, restore after
        pixmap_was_vis = self._pixmap_item.isVisible()
        checker = getattr(self, "_checker_item", None)
        checker_was_vis = checker.isVisible() if checker else False
        self._pixmap_item.setVisible(False)
        if checker:
            checker.setVisible(False)
        self._scene.render(p, source=self._pixmap_item.sceneBoundingRect())
        p.end()
        self._pixmap_item.setVisible(pixmap_was_vis)
        if checker:
            checker.setVisible(checker_was_vis)
        if img.save(path, "PNG"):
            self.info_label.setText(f"Exported overlays: {Path(path).name}")
        else:
            self.info_label.setText("Export failed")

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
        """Export the currently-active platform slot.

        Resolution order:
        1. If the crop combo has a concrete platform slot picked, use it.
        2. Otherwise if the scene has a selected ResizableCropItem with
           platform_id + slot_name (H3.1 fields), use that.
        3. Otherwise if the asset has exactly one crop with platform_id,
           use that crop's platform+slot.
        4. Otherwise show guidance.
        """
        if not self._asset or not self._project:
            self.info_label.setText("No asset or project loaded")
            return

        platform_id = slot_name = ""
        # 1. Combo selection wins
        data = self._crop_combo.currentData()
        if data and isinstance(data, (list, tuple)) and len(data) >= 4:
            platform_id, slot_name = data[0], data[1]

        # 2. Selected crop item in the scene
        if not platform_id:
            for it in self._scene.selectedItems():
                if isinstance(it, ResizableCropItem):
                    # Match by label against asset.crops to find its platform_id
                    lbl = getattr(it, "label", "")
                    for cr in self._asset.crops:
                        if cr.label == lbl and getattr(cr, "platform_id", ""):
                            platform_id = cr.platform_id
                            slot_name = getattr(cr, "slot_name", "") or lbl
                            break
                    if platform_id:
                        break

        # 3. Single crop with platform_id on the asset
        if not platform_id:
            scoped = [c for c in self._asset.crops
                      if getattr(c, "platform_id", "")]
            if len(scoped) == 1:
                platform_id = scoped[0].platform_id
                slot_name = getattr(scoped[0], "slot_name", "") or scoped[0].label

        if not platform_id:
            QMessageBox.information(
                self, "Export Platform",
                "No platform selected.\n\n"
                "Pick one of:\n"
                "  • A platform slot in the crop dropdown (top of Studio), or\n"
                "  • Click a platform-scoped crop in the canvas, or\n"
                "  • Use 'Export All Platforms' to export every crop.",
            )
            return

        self._sync_censors_to_asset()
        self._sync_overlays_to_asset()

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
            key = f"{platform_id}_{slot_name}" if slot_name else platform_id
            self._asset.variant_exports[key] = r.output_path
            self.info_label.setText(f"Exported: {platform_id}/{slot_name} ({r.width}x{r.height})")
            self._populate_preview_strip([r])
        else:
            self.info_label.setText(f"Export failed: {r.error}")
            import logging as _logging
            _logging.error("Export Platform FAILED: %s", r.error)

    def _export_freeform_crop(self, crop_item):
        """Export a single non-platform crop (e.g. label='free').

        The platform pipeline requires a platform_id + slot, so it
        rejects free-form crops with 'no platform selected'. The
        right-click 'Export this crop' menu should still work for
        labelled-only crops; this is the simple path: render visible
        overlays + censors onto the source, crop to the rect, save
        beside the project file."""
        if not self._asset:
            self.info_label.setText("No asset loaded")
            return
        from pathlib import Path
        from doxyedit.imaging import load_image_for_export, get_export_dir
        from doxyedit.exporter import apply_overlays, apply_censors
        self._sync_censors_to_asset()
        self._sync_overlays_to_asset()
        src_path = Path(self._asset.source_path)
        if not src_path.exists():
            self.info_label.setText(f"Source missing: {src_path.name}")
            return
        rect = crop_item.rect()
        x, y = int(rect.x()), int(rect.y())
        w, h = int(rect.width()), int(rect.height())
        if w <= 0 or h <= 0:
            self.info_label.setText("Crop has no area")
            return
        try:
            img = load_image_for_export(str(src_path))
            if self._asset.censors:
                img = apply_censors(img, self._asset.censors)
            unscoped = [ov for ov in self._asset.overlays if not ov.platforms]
            if unscoped:
                img = apply_overlays(img, unscoped, str(src_path.parent))
            img = img.crop((x, y, x + w, y + h))
            out_dir = get_export_dir(self._project_path) if self._project_path \
                else (src_path.parent / "_exports")
            out_dir.mkdir(parents=True, exist_ok=True)
            label = (getattr(crop_item, "label", "") or "crop").strip() or "crop"
            stem = src_path.stem
            if stem.isdigit() and src_path.parent.name:
                stem = f"{src_path.parent.name}_{stem}"
            out_path = Path(out_dir) / f"{stem}_{label}.png"
            img.save(str(out_path), "PNG")
            self.info_label.setText(f"Exported: {label} ({w}x{h})")
            try:
                self._show_filmstrip_from_files(Path(out_dir), stem)
            except Exception:
                pass
        except Exception as e:
            self.info_label.setText(f"Export crashed: {e}")
            import traceback; traceback.print_exc()

    def _export_all_platforms(self):
        """Batch export all platform variants for the current asset."""
        if not self._asset or not self._project:
            return
        self._sync_censors_to_asset()
        self._sync_overlays_to_asset()

        from doxyedit.pipeline import prepare_for_platform
        from doxyedit.imaging import get_export_dir
        from PySide6.QtCore import QCoreApplication

        output_dir = str(get_export_dir(self._project_path)) if self._project_path else ""

        if not self._asset.crops and not self._asset.censors and not self._asset.overlays:
            self.info_label.setText("Nothing to export — no crops, censors, or overlays")
            return

        from doxyedit.imaging import load_image_for_export

        src_path = Path(self._asset.source_path)
        stem = src_path.stem
        if stem.isdigit() and src_path.parent.name:
            stem = f"{src_path.parent.name}_{stem}"
        # Mirror pipeline.py's safe fallback: drop beside the source image
        # if the project path was missing, never the cwd-relative "_exports"
        # which lands next to the doxyedit exe.
        out_base = Path(output_dir) if output_dir else (src_path.parent / "_exports")
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

    @staticmethod
    def _open_export_folder(folder: Path):
        """Open the export folder in the system file manager."""
        import subprocess
        subprocess.Popen(
            ["explorer", str(folder)],
            creationflags=0x08000000, encoding="utf-8", errors="replace",
        )

    def _wire_filmstrip_thumb(self, frame, file_path: str):
        """Attach hover-preview, right-click context menu, and drag-out
        with file URL to a filmstrip thumbnail frame. Mirrors what the
        main asset grid offers."""
        frame.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        frame.setMouseTracking(True)
        frame.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        frame.setCursor(Qt.CursorShape.PointingHandCursor)
        frame.setToolTip(file_path)
        # Track press position so we can threshold-detect a drag and
        # start a QDrag with the export file URL (Discord/Explorer/etc).
        drag_state = {"press": None}
        def _ev_filter(obj, ev, _path=file_path):
            t = ev.type()
            if t == QEvent.Type.Enter:
                try:
                    HoverPreview.instance().show_for(_path, QCursor.pos())
                except Exception:
                    pass
            elif t == QEvent.Type.Leave:
                try:
                    HoverPreview.instance().hide_preview()
                except Exception:
                    pass
            elif t == QEvent.Type.MouseButtonPress:
                if ev.button() == Qt.MouseButton.LeftButton:
                    drag_state["press"] = ev.globalPosition().toPoint()
            elif t == QEvent.Type.MouseMove:
                if (ev.buttons() & Qt.MouseButton.LeftButton
                        and drag_state["press"] is not None):
                    delta = (ev.globalPosition().toPoint()
                             - drag_state["press"]).manhattanLength()
                    if delta >= QApplication.startDragDistance():
                        drag_state["press"] = None
                        try:
                            HoverPreview.instance().hide_preview()
                        except Exception:
                            pass
                        from PySide6.QtGui import QDrag
                        from PySide6.QtCore import QMimeData, QUrl
                        drag = QDrag(obj)
                        mime = QMimeData()
                        mime.setUrls([QUrl.fromLocalFile(_path)])
                        drag.setMimeData(mime)
                        # Use the visible thumbnail as the drag pixmap
                        # so the user sees what they're dragging.
                        for child in obj.children():
                            try:
                                pm = child.pixmap()
                                if pm is not None and not pm.isNull():
                                    drag.setPixmap(pm)
                                    break
                            except Exception:
                                continue
                        drag.exec(Qt.DropAction.CopyAction)
                        return True
            elif t == QEvent.Type.MouseButtonRelease:
                drag_state["press"] = None
            return False
        frame.installEventFilter(self._make_obj_filter(_ev_filter))
        frame.customContextMenuRequested.connect(
            lambda pos, _p=file_path, _f=frame:
                self._filmstrip_context_menu(_f, pos, _p))

    def _make_obj_filter(self, fn):
        """Wrap a (obj, ev) callable in a QObject so installEventFilter works.
        Stores the wrapper on self so it isn't GC'd while the source widget
        lives - filmstrip frames are rebuilt on every export."""
        from PySide6.QtCore import QObject
        class _F(QObject):
            def eventFilter(self_inner, obj, ev):
                return fn(obj, ev)
        f = _F(self)
        if not hasattr(self, "_filmstrip_filters"):
            self._filmstrip_filters = []
        # Keep recent filters alive; old ones get reaped when the strip
        # rebuilds and Qt deletes the source widgets (Qt parent ownership
        # handles cleanup since we pass self as parent).
        self._filmstrip_filters.append(f)
        # Cap the list so it doesn't grow unbounded across many exports.
        if len(self._filmstrip_filters) > 500:
            self._filmstrip_filters = self._filmstrip_filters[-100:]
        return f

    def _filmstrip_context_menu(self, frame, pos, file_path: str):
        """Right-click menu on a filmstrip thumb. Acts on the exported file
        rather than the source asset, since this is the export preview."""
        menu = QMenu(frame)
        menu.addAction("Open Image", lambda: self._open_with_default(file_path))
        menu.addAction("Reveal in Explorer",
                       lambda: self._reveal_in_explorer(file_path))
        menu.addAction("Copy File Path",
                       lambda: QApplication.clipboard().setText(file_path))
        menu.addAction("Copy Image to Clipboard",
                       lambda: self._copy_image_to_clipboard(file_path))
        menu.addSeparator()
        if self._asset is not None:
            menu.addAction("Add Source Asset to Work Tray",
                           lambda: self._add_current_asset_to_tray())
        menu.addAction("Re-export", lambda: self._export_current_platform())
        menu.addSeparator()
        del_act = menu.addAction("Delete Export File")
        del_act.triggered.connect(lambda: self._delete_export_file(file_path))
        menu.exec(frame.mapToGlobal(pos))

    def _add_current_asset_to_tray(self):
        """Send the current source asset (the one being studio-edited) to
        the Work Tray. The filmstrip shows EXPORT files derived from this
        asset, so the underlying asset is what 'Add to Work Tray' targets."""
        if self._asset is None:
            return
        win = self.window()
        send = getattr(win, "_send_single_to_tray", None)
        if callable(send):
            try:
                send(self._asset.id)
            except Exception:
                pass

    def _open_with_default(self, path: str):
        try:
            os.startfile(path)
        except Exception as e:
            self.info_label.setText(f"Open failed: {e}")

    def _reveal_in_explorer(self, path: str):
        try:
            subprocess.Popen(
                ["explorer", "/select,", str(Path(path).resolve())],
                creationflags=0x08000000)
        except Exception as e:
            self.info_label.setText(f"Reveal failed: {e}")

    def _copy_image_to_clipboard(self, path: str):
        try:
            pm = QPixmap(path)
            if not pm.isNull():
                QApplication.clipboard().setPixmap(pm)
                self.info_label.setText("Image copied to clipboard")
        except Exception as e:
            self.info_label.setText(f"Copy failed: {e}")

    def _delete_export_file(self, path: str):
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(
            self, "Delete Export",
            f"Delete this export file?\n\n{path}\n\n(Source asset is not affected.)"
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(path)
            # Refresh strip from the same folder so the deleted thumb vanishes.
            p = Path(path)
            self._show_filmstrip_from_files(
                p.parent, p.stem.split("_")[0] if "_" in p.stem else p.stem)
            self.info_label.setText(f"Deleted {p.name}")
        except Exception as e:
            self.info_label.setText(f"Delete failed: {e}")

    def _populate_preview_strip(self, results):
        """Fill the preview strip with thumbnails from export results."""
        # Clear old thumbnails
        while self._preview_strip_layout.count():
            item = self._preview_strip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

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
            self._wire_filmstrip_thumb(frame, r.output_path)
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
            self._wire_filmstrip_thumb(frame, str(f))
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
