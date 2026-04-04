"""Non-destructive censor editor — draw censor regions over an image."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsScene, QGraphicsView, QGraphicsRectItem, QGraphicsPixmapItem,
    QComboBox, QFileDialog,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QBrush, QPen, QFont, QImage,
)
from PIL import Image
import io

from doxyedit.models import Asset, CensorRegion
from doxyedit.exporter import apply_censors


class CensorRectItem(QGraphicsRectItem):
    """A draggable, resizable censor rectangle."""

    def __init__(self, rect: QRectF, style="black"):
        super().__init__(rect)
        self.style = style
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


class CensorEditor(QWidget):
    """Panel for adding censor regions to an image non-destructively."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._asset = None
        self._pixmap_item = None
        self._drawing = False
        self._draw_start = None
        self._temp_rect = None
        self._censor_items: list[CensorRectItem] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()

        self.style_combo = QComboBox()
        self.style_combo.addItems(["black", "blur", "pixelate"])
        # Inherits from theme
        toolbar.addWidget(QLabel("Style:"))
        toolbar.addWidget(self.style_combo)

        btn_draw = QPushButton("Draw Censor Region")
        btn_draw.setStyleSheet(self._btn_style())
        btn_draw.clicked.connect(self._start_drawing)
        toolbar.addWidget(btn_draw)

        btn_del = QPushButton("Delete Selected")
        btn_del.setStyleSheet(self._btn_style())
        btn_del.clicked.connect(self._delete_selected)
        toolbar.addWidget(btn_del)

        btn_export = QPushButton("Export Censored")
        btn_export.setStyleSheet(self._btn_style())
        btn_export.clicked.connect(self._export_censored)
        toolbar.addWidget(btn_export)

        toolbar.addStretch()

        self.info_label = QLabel("No image loaded")
        # Inherits from theme
        toolbar.addWidget(self.info_label)

        root.addLayout(toolbar)

        # Canvas
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QBrush(QColor(40, 40, 40)))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.view.setStyleSheet("border: none;")
        root.addWidget(self.view)

        # Override mouse events on the view
        self.view.mousePressEvent = self._view_mouse_press
        self.view.mouseMoveEvent = self._view_mouse_move
        self.view.mouseReleaseEvent = self._view_mouse_release

    def _btn_style(self):
        return "QPushButton { padding: 6px 14px; }"

    def load_asset(self, asset: Asset):
        """Load an asset image into the censor editor."""
        self._asset = asset
        self.scene.clear()
        self._censor_items.clear()

        pm = QPixmap(asset.source_path)
        if pm.isNull():
            self.info_label.setText("Failed to load image")
            return

        self._pixmap_item = QGraphicsPixmapItem(pm)
        self.scene.addItem(self._pixmap_item)
        self.scene.setSceneRect(QRectF(pm.rect()))
        self.view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

        # Restore existing censor regions
        for cr in asset.censors:
            rect_item = CensorRectItem(QRectF(cr.x, cr.y, cr.w, cr.h), cr.style)
            self.scene.addItem(rect_item)
            self._censor_items.append(rect_item)

        n = len(asset.censors)
        self.info_label.setText(f"{Path(asset.source_path).name} — {n} censor region{'s' if n != 1 else ''}")

    def _start_drawing(self):
        self._drawing = True
        self.view.setCursor(Qt.CursorShape.CrossCursor)

    def _view_mouse_press(self, event):
        if self._drawing and event.button() == Qt.MouseButton.LeftButton:
            self._draw_start = self.view.mapToScene(event.position().toPoint())
            style = self.style_combo.currentText()
            self._temp_rect = CensorRectItem(QRectF(self._draw_start, self._draw_start), style)
            self.scene.addItem(self._temp_rect)
            return
        QGraphicsView.mousePressEvent(self.view, event)

    def _view_mouse_move(self, event):
        if self._drawing and self._draw_start and self._temp_rect:
            pos = self.view.mapToScene(event.position().toPoint())
            r = QRectF(self._draw_start, pos).normalized()
            self._temp_rect.setRect(r)
            return
        QGraphicsView.mouseMoveEvent(self.view, event)

    def _view_mouse_release(self, event):
        if self._drawing and self._temp_rect:
            self._censor_items.append(self._temp_rect)
            self._sync_to_asset()
            self._temp_rect = None
            self._draw_start = None
            self._drawing = False
            self.view.setCursor(Qt.CursorShape.ArrowCursor)
            return
        QGraphicsView.mouseReleaseEvent(self.view, event)

    def _delete_selected(self):
        for item in self.scene.selectedItems():
            if isinstance(item, CensorRectItem):
                self.scene.removeItem(item)
                if item in self._censor_items:
                    self._censor_items.remove(item)
        self._sync_to_asset()

    def _sync_to_asset(self):
        """Write censor rects back to the asset model."""
        if not self._asset:
            return
        self._asset.censors.clear()
        for item in self._censor_items:
            r = item.rect()
            self._asset.censors.append(CensorRegion(
                x=int(r.x()), y=int(r.y()),
                w=int(r.width()), h=int(r.height()),
                style=item.style,
            ))
        n = len(self._asset.censors)
        self.info_label.setText(
            f"{Path(self._asset.source_path).name} — {n} censor region{'s' if n != 1 else ''}"
        )

    def _export_censored(self):
        if not self._asset:
            return
        self._sync_to_asset()

        img = Image.open(self._asset.source_path).convert("RGBA")
        img = apply_censors(img, self._asset.censors)

        # Ask where to save
        src = Path(self._asset.source_path)
        default_name = f"{src.stem}_censored{src.suffix}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Censored Image", default_name,
            "PNG (*.png);;JPEG (*.jpg);;All Files (*)"
        )
        if path:
            img.save(path)
            self.info_label.setText(f"Exported: {Path(path).name}")
