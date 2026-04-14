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
)
from PySide6.QtCore import Qt, QRectF, QPointF, QLineF
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QBrush, QPen, QFont, QWheelEvent,
    QKeyEvent,
)
import copy
from PIL import Image

from doxyedit.models import Asset, Project, CensorRegion, CanvasOverlay
from doxyedit.exporter import apply_censors, apply_overlays


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
    """)
    return menu


# ---------------------------------------------------------------------------
# Tool state machine
# ---------------------------------------------------------------------------

class StudioTool(Enum):
    SELECT = auto()
    CENSOR = auto()
    WATERMARK = auto()
    TEXT_OVERLAY = auto()
    ANNOTATE_TEXT = auto()
    ANNOTATE_LINE = auto()
    ANNOTATE_BOX = auto()


# ---------------------------------------------------------------------------
# Graphics items
# ---------------------------------------------------------------------------

class CensorRectItem(QGraphicsRectItem):
    """Draggable censor rectangle — overlay exception: hardcoded colors OK."""

    def __init__(self, rect: QRectF, style: str = "black"):
        super().__init__(rect)
        self.style = style
        self._editor = None  # set by StudioEditor after creation
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
        )
        self._apply_style()

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

    def contextMenuEvent(self, event):
        menu = _themed_menu()
        styles = {"black": "Change to Black", "blur": "Change to Blur",
                   "pixelate": "Change to Pixelate"}
        for key, label in styles.items():
            if key != self.style:
                act = menu.addAction(label)
                act.setData(key)
        menu.addSeparator()
        delete_act = menu.addAction("Delete")

        chosen = menu.exec(event.screenPos())
        if not chosen:
            return
        if chosen is delete_act:
            if self._editor:
                self._editor._remove_censor_item(self)
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
        if overlay.rotation:
            self.setRotation(overlay.rotation)

    def itemChange(self, change, value):
        if change == QGraphicsPixmapItem.GraphicsItemChange.ItemPositionHasChanged:
            self.overlay.x = int(value.x())
            self.overlay.y = int(value.y())
            self.overlay.position = "custom"
        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        menu = _themed_menu()
        dup_act = menu.addAction("Duplicate")
        menu.addSeparator()
        fwd_act = menu.addAction("Bring Forward")
        bwd_act = menu.addAction("Send Backward")
        menu.addSeparator()
        del_act = menu.addAction("Delete")

        chosen = menu.exec(event.screenPos())
        if not chosen:
            return
        if chosen is dup_act and self._editor:
            self._editor._duplicate_overlay_item(self)
        elif chosen is fwd_act:
            self.setZValue(self.zValue() + 1)
        elif chosen is bwd_act:
            self.setZValue(max(200, self.zValue() - 1))
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

    def itemChange(self, change, value):
        if change == QGraphicsTextItem.GraphicsItemChange.ItemPositionHasChanged:
            self.overlay.x = int(value.x())
            self.overlay.y = int(value.y())
            self.overlay.position = "custom"
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.overlay.text = self.toPlainText()
        super().focusOutEvent(event)

    def contextMenuEvent(self, event):
        menu = _themed_menu()
        edit_act = menu.addAction("Edit Text")
        menu.addSeparator()
        dup_act = menu.addAction("Duplicate")
        menu.addSeparator()
        fwd_act = menu.addAction("Bring Forward")
        bwd_act = menu.addAction("Send Backward")
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
        elif chosen is fwd_act:
            self.setZValue(self.zValue() + 1)
        elif chosen is bwd_act:
            self.setZValue(max(200, self.zValue() - 1))
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
        self.setFont(QFont("Segoe UI", 11))
        self.setDefaultTextColor(QColor(_dt.text_primary))

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        super().focusOutEvent(event)


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------

class StudioScene(QGraphicsScene):
    """Scene with tool-aware mouse handling for censor/annotation drawing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        self.setBackgroundBrush(QBrush(QColor(_dt.bg_deep)))

        self.current_tool = StudioTool.SELECT
        self._draw_start: QPointF | None = None
        self._temp_item = None
        self._censor_style = "black"

        # Callbacks set by StudioEditor
        self.on_censor_finished = None   # callable(CensorRectItem)
        self.on_annotation_placed = None  # callable(item)

    def set_tool(self, tool: StudioTool):
        self.current_tool = tool

    def set_censor_style(self, style: str):
        self._censor_style = style

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        pos = event.scenePos()

        if self.current_tool == StudioTool.SELECT:
            return super().mousePressEvent(event)

        if self.current_tool == StudioTool.CENSOR:
            self._draw_start = pos
            self._temp_item = CensorRectItem(
                QRectF(pos, pos), self._censor_style
            )
            self._temp_item.setZValue(150)
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
            from doxyedit.themes import THEMES, DEFAULT_THEME
            _dt = THEMES[DEFAULT_THEME]
            pen = QPen(QColor(_dt.accent_bright), 2)
            if self.current_tool == StudioTool.ANNOTATE_LINE:
                self._temp_item = QGraphicsLineItem(QLineF(pos, pos))
                self._temp_item.setPen(pen)
            else:
                self._temp_item = QGraphicsRectItem(QRectF(pos, pos))
                self._temp_item.setPen(pen)
                self._temp_item.setBrush(QBrush(QColor(79, 195, 247, 30)))
            self._temp_item.setZValue(300)
            self._temp_item.setFlags(
                QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
                | QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
            )
            self.addItem(self._temp_item)
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._draw_start and self._temp_item:
            pos = event.scenePos()
            if isinstance(self._temp_item, QGraphicsLineItem):
                self._temp_item.setLine(QLineF(self._draw_start, pos))
            elif isinstance(self._temp_item, QGraphicsRectItem):
                r = QRectF(self._draw_start, pos).normalized()
                self._temp_item.setRect(r)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._draw_start and self._temp_item:
            if self.current_tool == StudioTool.CENSOR:
                if self.on_censor_finished:
                    self.on_censor_finished(self._temp_item)
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
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studio_editor")
        self._asset: Asset | None = None
        self._project: Project | None = None
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._censor_items: list[CensorRectItem] = []
        self._overlay_items: list[OverlayImageItem | OverlayTextItem] = []
        self._overlays_visible = True
        self._build()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ---- keyboard shortcuts ----

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        # Ctrl combos
        if ctrl and key == Qt.Key.Key_Z:
            print("[Studio] Undo not yet implemented")
            return
        if ctrl and key == Qt.Key.Key_Y:
            print("[Studio] Redo not yet implemented")
            return
        if ctrl and key == Qt.Key.Key_D:
            self._duplicate_selected()
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
            for item in self._scene.selectedItems():
                if isinstance(item, (CensorRectItem, OverlayImageItem, OverlayTextItem)):
                    item.moveBy(dx, dy)
                    if isinstance(item, (OverlayImageItem, OverlayTextItem)):
                        item.overlay.x = int(item.pos().x())
                        item.overlay.y = int(item.pos().y())
                    moved = True
            if moved:
                self._sync_censors_to_asset()
                self._sync_overlays_to_asset()
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
            if key == Qt.Key.Key_F:
                if self._scene.sceneRect():
                    self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
                return
            if key == Qt.Key.Key_H:
                self._toggle_overlay_visibility()
                return

        super().keyPressEvent(event)

    # ---- construction ----

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

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
        self.slider_opacity.setFixedWidth(100)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        toolbar.addWidget(self.slider_opacity)

        toolbar.addWidget(QLabel("Scale:"))
        self.slider_scale = QSlider(Qt.Orientation.Horizontal)
        self.slider_scale.setObjectName("studio_scale_slider")
        self.slider_scale.setRange(5, 100)
        self.slider_scale.setValue(20)
        self.slider_scale.setFixedWidth(100)
        self.slider_scale.valueChanged.connect(self._on_scale_changed)
        toolbar.addWidget(self.slider_scale)

        toolbar.addWidget(QLabel("|"))

        # Group 5: Export
        self.btn_export = QPushButton("Export Preview")
        self.btn_export.setObjectName("studio_btn_export")
        self.btn_export.clicked.connect(self._export_preview)
        toolbar.addWidget(self.btn_export)

        toolbar.addStretch()

        self.info_label = QLabel("No image loaded")
        self.info_label.setObjectName("studio_info")
        toolbar.addWidget(self.info_label)

        root.addLayout(toolbar)

        # Row 2: Overlay properties (visible when text/watermark selected)
        self._props_row = QWidget()
        self._props_row.setObjectName("studio_props_row")
        props = QHBoxLayout(self._props_row)
        props.setContentsMargins(0, 2, 0, 2)

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
        self.slider_font_size.setFixedWidth(80)
        self.slider_font_size.valueChanged.connect(self._on_font_size_changed)
        props.addWidget(self.slider_font_size)
        self._font_size_label = QLabel("24")
        props.addWidget(self._font_size_label)

        self.btn_bold = QPushButton("B")
        self.btn_bold.setObjectName("studio_bold_btn")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setFixedWidth(28)
        self.btn_bold.clicked.connect(self._on_bold_changed)
        props.addWidget(self.btn_bold)

        self.btn_italic = QPushButton("I")
        self.btn_italic.setObjectName("studio_italic_btn")
        self.btn_italic.setCheckable(True)
        self.btn_italic.setFixedWidth(28)
        self.btn_italic.clicked.connect(self._on_italic_changed)
        props.addWidget(self.btn_italic)

        self.btn_color = QPushButton("■")
        self.btn_color.setObjectName("studio_color_btn")
        self.btn_color.setFixedWidth(28)
        self.btn_color.clicked.connect(self._on_color_pick)
        props.addWidget(self.btn_color)

        props.addWidget(QLabel("|"))

        props.addWidget(QLabel("Kern:"))
        self.slider_kerning = QSlider(Qt.Orientation.Horizontal)
        self.slider_kerning.setObjectName("studio_kerning_slider")
        self.slider_kerning.setRange(-20, 20)
        self.slider_kerning.setValue(0)
        self.slider_kerning.setFixedWidth(80)
        self.slider_kerning.valueChanged.connect(self._on_kerning_changed)
        props.addWidget(self.slider_kerning)

        props.addWidget(QLabel("LH:"))
        self.slider_line_height = QSlider(Qt.Orientation.Horizontal)
        self.slider_line_height.setObjectName("studio_line_height_slider")
        self.slider_line_height.setRange(50, 300)  # 0.5x to 3.0x (stored as int * 100)
        self.slider_line_height.setValue(120)       # default 1.2
        self.slider_line_height.setFixedWidth(80)
        self.slider_line_height.setToolTip("Line height (1.0 = tight, 1.5 = loose, 2.0 = double)")
        self.slider_line_height.valueChanged.connect(self._on_line_height_changed)
        props.addWidget(self.slider_line_height)

        props.addWidget(QLabel("Rot:"))
        self.slider_rotation = QSlider(Qt.Orientation.Horizontal)
        self.slider_rotation.setObjectName("studio_rotation_slider")
        self.slider_rotation.setRange(-180, 180)
        self.slider_rotation.setValue(0)
        self.slider_rotation.setFixedWidth(80)
        self.slider_rotation.valueChanged.connect(self._on_rotation_changed)
        props.addWidget(self.slider_rotation)

        props.addWidget(QLabel("W:"))
        self.slider_text_width = QSlider(Qt.Orientation.Horizontal)
        self.slider_text_width.setObjectName("studio_text_width")
        self.slider_text_width.setRange(0, 2000)
        self.slider_text_width.setValue(0)
        self.slider_text_width.setFixedWidth(80)
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
        self._view = StudioView(self._scene)
        self._view.on_file_dropped = self._on_file_dropped
        root.addWidget(self._view)

        # Selection change -> update sliders + props row
        self._scene.selectionChanged.connect(self._on_selection_changed)

    # ---- public API ----

    def set_project(self, project: Project):
        """Store project ref and populate template dropdown."""
        self._project = project
        self.combo_template.clear()
        self.combo_template.addItem("Apply Template...")
        for i, tmpl in enumerate(project.default_overlays):
            label = tmpl.get("label", tmpl.get("type", f"Overlay {i + 1}"))
            self.combo_template.addItem(label)

    def load_asset(self, asset: Asset):
        """Load image, restore censors + overlays. Annotations are lost."""
        self._asset = asset
        self._scene.clear()
        self._censor_items.clear()
        self._overlay_items.clear()
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
            item = CensorRectItem(QRectF(cr.x, cr.y, cr.w, cr.h), cr.style)
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

        self._update_info()

    # ---- tool management ----

    def _set_tool(self, tool: StudioTool):
        self._scene.set_tool(tool)
        if tool == StudioTool.CENSOR:
            self._view.setCursor(Qt.CursorShape.CrossCursor)
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif tool == StudioTool.WATERMARK:
            self._add_watermark()
            self._scene.set_tool(StudioTool.SELECT)
        elif tool == StudioTool.TEXT_OVERLAY:
            self._add_text_overlay()
            self._scene.set_tool(StudioTool.SELECT)
        else:
            self._view.setCursor(Qt.CursorShape.ArrowCursor)
            self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

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

    def _add_text_overlay(self):
        """Add a text overlay at a default position."""
        if not self._asset:
            return
        ov = CanvasOverlay(
            type="text",
            label="Text",
            text="Your text",
            opacity=self.slider_opacity.value() / 100.0,
            position="custom",
            x=50, y=50,
        )
        self._asset.overlays.append(ov)
        item = self._create_overlay_item(ov)
        if item:
            item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(item)
        self._update_info()

    def _apply_template(self, index: int):
        """Load overlay preset from project.default_overlays."""
        if index <= 0 or not self._project or not self._asset:
            return
        tmpl_index = index - 1
        if tmpl_index >= len(self._project.default_overlays):
            return
        tmpl = self._project.default_overlays[tmpl_index]
        ov = CanvasOverlay.from_dict(tmpl)
        self._asset.overlays.append(ov)
        item = self._create_overlay_item(ov)
        if item:
            item.setZValue(200 + len(self._overlay_items))
            self._overlay_items.append(item)
        self._update_info()
        self.combo_template.setCurrentIndex(0)

    # ---- slider handlers ----

    def _on_opacity_changed(self, value: int):
        opacity = value / 100.0
        for item in self._scene.selectedItems():
            if isinstance(item, (OverlayImageItem, OverlayTextItem)):
                item.setOpacity(opacity)
                item.overlay.opacity = opacity

    def _on_scale_changed(self, value: int):
        scale = value / 100.0
        for item in self._scene.selectedItems():
            if isinstance(item, OverlayImageItem):
                item.overlay.scale = scale
                if self._pixmap_item:
                    base_w = self._pixmap_item.pixmap().width()
                    target_w = max(10, int(base_w * scale))
                    pm = QPixmap(item.overlay.image_path)
                    if not pm.isNull():
                        pm = pm.scaledToWidth(
                            target_w, Qt.TransformationMode.SmoothTransformation
                        )
                        item.setPixmap(pm)

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
                  self.slider_rotation, self.slider_text_width):
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

        for w in (self.slider_opacity, self.slider_scale, self.combo_position,
                  self.font_combo, self.slider_font_size, self.btn_bold,
                  self.btn_italic, self.slider_kerning, self.slider_line_height,
                  self.slider_rotation, self.slider_text_width):
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
                item.overlay.font_family = font.family()
                item._apply_font()
        self._sync_overlays_to_asset()

    def _on_font_size_changed(self, value: int):
        self._font_size_label.setText(str(value))
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                item.overlay.font_size = value
                item._apply_font()
        self._sync_overlays_to_asset()

    def _on_bold_changed(self):
        checked = self.btn_bold.isChecked()
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                item.overlay.bold = checked
                item._apply_font()
        self._sync_overlays_to_asset()

    def _on_italic_changed(self):
        checked = self.btn_italic.isChecked()
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                item.overlay.italic = checked
                item._apply_font()
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
                    item.overlay.color = color.name()
                    item._apply_font()
            self._sync_overlays_to_asset()

    def _on_kerning_changed(self, value: int):
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                item.overlay.letter_spacing = float(value)
                item._apply_font()
        self._sync_overlays_to_asset()

    def _on_rotation_changed(self, value: int):
        for item in self._selected_overlay_items():
            item.overlay.rotation = float(value)
            item.setTransformOriginPoint(item.boundingRect().center())
            item.setRotation(value)
        self._sync_overlays_to_asset()

    def _on_line_height_changed(self, value: int):
        lh = value / 100.0
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                item.overlay.line_height = lh
                item._apply_font()
        self._sync_overlays_to_asset()

    def _on_text_width_changed(self, value: int):
        for item in self._selected_overlay_items():
            if isinstance(item, OverlayTextItem):
                item.overlay.text_width = value
                item._apply_font()
        self._sync_overlays_to_asset()

    def _save_as_template(self):
        """Save selected overlay as a project template."""
        items = self._selected_overlay_items()
        if not items or not self._project:
            return
        ov = items[0].overlay
        label, ok = QInputDialog.getText(self, "Save Template", "Template label:")
        if not ok or not label.strip():
            return
        d = ov.to_dict()
        d["label"] = label.strip()
        self._project.default_overlays.append(d)
        self.combo_template.addItem(label.strip())

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
            ))

    def _sync_overlays_to_asset(self):
        """Write overlay items back to asset.overlays."""
        if not self._asset:
            return
        self._asset.overlays.clear()
        for item in self._overlay_items:
            self._asset.overlays.append(item.overlay)

    # ---- actions ----

    def _delete_selected(self):
        """Remove selected censors/overlays from scene and model."""
        for item in self._scene.selectedItems():
            if isinstance(item, CensorRectItem):
                self._scene.removeItem(item)
                if item in self._censor_items:
                    self._censor_items.remove(item)
            elif isinstance(item, (OverlayImageItem, OverlayTextItem)):
                self._scene.removeItem(item)
                if item in self._overlay_items:
                    self._overlay_items.remove(item)
            elif isinstance(item, (AnnotationTextItem, QGraphicsRectItem, QGraphicsLineItem)):
                self._scene.removeItem(item)
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

    def _toggle_overlay_visibility(self):
        """Toggle visibility of all censor + overlay items."""
        self._overlays_visible = not self._overlays_visible
        for item in self._censor_items:
            item.setVisible(self._overlays_visible)
        for item in self._overlay_items:
            item.setVisible(self._overlays_visible)

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

        default_name = f"{src_path.stem}_studio_preview.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Studio Preview", default_name,
            "PNG (*.png);;JPEG (*.jpg);;All Files (*)",
        )
        if path:
            img.save(path)
            self.info_label.setText(f"Exported: {Path(path).name}")

    # ---- helpers ----

    def _update_info(self):
        if not self._asset:
            self.info_label.setText("No image loaded")
            return
        name = Path(self._asset.source_path).name
        nc = len(self._censor_items)
        no = len(self._overlay_items)
        self.info_label.setText(f"{name} — {nc} censor, {no} overlay")
