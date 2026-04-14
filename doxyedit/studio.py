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
)
from PySide6.QtCore import Qt, QRectF, QPointF, QLineF
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QBrush, QPen, QFont, QWheelEvent,
)
from PIL import Image

from doxyedit.models import Asset, Project, CensorRegion, CanvasOverlay
from doxyedit.exporter import apply_censors, apply_overlays


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


class OverlayImageItem(QGraphicsPixmapItem):
    """Movable watermark/logo image — syncs position back to CanvasOverlay."""

    def __init__(self, pixmap: QPixmap, overlay: CanvasOverlay):
        super().__init__(pixmap)
        self.overlay = overlay
        self.setFlags(
            QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsPixmapItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setOpacity(overlay.opacity)
        self.setPos(overlay.x, overlay.y)

    def itemChange(self, change, value):
        if change == QGraphicsPixmapItem.GraphicsItemChange.ItemPositionHasChanged:
            self.overlay.x = int(value.x())
            self.overlay.y = int(value.y())
            self.overlay.position = "custom"
        return super().itemChange(change, value)


class OverlayTextItem(QGraphicsTextItem):
    """Movable, double-click editable text overlay — syncs to CanvasOverlay."""

    def __init__(self, overlay: CanvasOverlay):
        super().__init__(overlay.text or "Your text")
        self.overlay = overlay
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
        self.setFont(font)
        self.setDefaultTextColor(QColor(self.overlay.color))

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
        self._build()

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

        # Scene + View
        self._scene = StudioScene()
        self._scene.on_censor_finished = self._on_censor_drawn
        self._view = StudioView(self._scene)
        root.addWidget(self._view)

        # Selection change -> update sliders
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
            self._scene.addItem(item)
            return item
        elif ov.type == "text":
            item = OverlayTextItem(ov)
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
        for item in self._scene.selectedItems():
            if isinstance(item, (OverlayImageItem, OverlayTextItem)):
                self.slider_opacity.blockSignals(True)
                self.slider_opacity.setValue(int(item.overlay.opacity * 100))
                self.slider_opacity.blockSignals(False)
                if isinstance(item, OverlayImageItem):
                    self.slider_scale.blockSignals(True)
                    self.slider_scale.setValue(int(item.overlay.scale * 100))
                    self.slider_scale.blockSignals(False)
                break

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

    def _export_preview(self):
        """Render censors + overlays via PIL and save."""
        if not self._asset:
            return
        self._sync_censors_to_asset()
        self._sync_overlays_to_asset()

        src_path = Path(self._asset.source_path)
        ext = src_path.suffix.lower()
        if ext in (".psd", ".psb"):
            from doxyedit.imaging import load_psd
            img, _, _ = load_psd(str(src_path))
        else:
            img = Image.open(str(src_path)).convert("RGBA")

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
