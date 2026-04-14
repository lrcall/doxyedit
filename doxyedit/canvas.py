"""Graphics canvas — the main editing surface."""
from enum import Enum, auto
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsView, QGraphicsTextItem,
    QGraphicsRectItem, QGraphicsLineItem, QGraphicsPixmapItem,
)
from PySide6.QtCore import Qt, QPointF, QRectF, QLineF
from PySide6.QtGui import (
    QPen, QColor, QBrush, QFont, QPixmap, QPainter, QWheelEvent,
)


class Tool(Enum):
    SELECT = auto()
    TEXT = auto()
    LINE = auto()
    BOX = auto()
    TAG = auto()
    IMAGE = auto()


class EditableTextItem(QGraphicsTextItem):
    """Text box that can be moved and edited."""

    def __init__(self, text="Double-click to edit", parent=None):
        super().__init__(text, parent)
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        self.setFont(QFont(_dt.font_family, _dt.font_size))
        self.setFlags(
            QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsTextItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setDefaultTextColor(QColor(_dt.text_primary))
        self._editing = False

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self._editing = True
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._editing = False
        super().focusOutEvent(event)


class TagItem(QGraphicsRectItem):
    """A colored tag/label marker with text."""

    def __init__(self, x, y, label="tag", color="#ff6b6b"):
        super().__init__(0, 0, 80, 24)
        self.setBrush(QBrush(QColor(color)))
        self.setPen(QPen(QColor(color).darker(120), 1))
        self.setPos(x, y)
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
        )
        self._label = QGraphicsTextItem(label, self)
        self._label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        self._label.setDefaultTextColor(QColor(_dt.text_on_accent))
        self._label.setPos(4, 1)

    @property
    def label(self):
        return self._label.toPlainText()


class MovablePixmapItem(QGraphicsPixmapItem):
    """Image that can be moved and scaled."""

    def __init__(self, pixmap, parent=None):
        super().__init__(pixmap, parent)
        self.setFlags(
            QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsPixmapItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)


class CanvasScene(QGraphicsScene):
    """The scene holding all editable items."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(QRectF(-2000, -2000, 4000, 4000))
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        self.setBackgroundBrush(QBrush(QColor(_dt.bg_deep)))
        self.current_tool = Tool.SELECT
        self._draw_start = None
        self._temp_item = None

    def set_tool(self, tool: Tool):
        self.current_tool = tool

    def mousePressEvent(self, event):
        pos = event.scenePos()

        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        if self.current_tool == Tool.SELECT:
            return super().mousePressEvent(event)

        if self.current_tool == Tool.TEXT:
            item = EditableTextItem()
            item.setPos(pos)
            self.addItem(item)
            self.current_tool = Tool.SELECT
            return

        if self.current_tool == Tool.TAG:
            item = TagItem(pos.x(), pos.y())
            self.addItem(item)
            self.current_tool = Tool.SELECT
            return

        if self.current_tool in (Tool.LINE, Tool.BOX):
            self._draw_start = pos
            pen = QPen(QColor("#4fc3f7"), 2)
            if self.current_tool == Tool.LINE:
                self._temp_item = QGraphicsLineItem(QLineF(pos, pos))
                self._temp_item.setPen(pen)
            else:
                self._temp_item = QGraphicsRectItem(QRectF(pos, pos))
                self._temp_item.setPen(pen)
                self._temp_item.setBrush(QBrush(QColor(79, 195, 247, 30)))
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
            self._draw_start = None
            self._temp_item = None
            self.current_tool = Tool.SELECT
            return
        super().mouseReleaseEvent(event)

    def add_image(self, path: str, pos: QPointF = None):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return None
        if pixmap.width() > 800:
            pixmap = pixmap.scaledToWidth(800, Qt.TransformationMode.SmoothTransformation)
        item = MovablePixmapItem(pixmap)
        if pos:
            item.setPos(pos)
        self.addItem(item)
        return item


class CanvasView(QGraphicsView):
    """Zoomable, pannable view onto the canvas."""

    def __init__(self, scene: CanvasScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setStyleSheet("border: none;")
        self._panning = False
        self._pan_start = QPointF()

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
