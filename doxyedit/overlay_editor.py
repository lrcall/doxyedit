"""Asset-bound overlay editor — place watermarks, text, and logos on images."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsScene, QGraphicsView, QGraphicsPixmapItem, QGraphicsTextItem,
    QComboBox, QFileDialog, QSlider,
)
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QBrush, QPen, QFont, QImage,
)
from PIL import Image

from doxyedit.models import Asset, Project, CanvasOverlay
from doxyedit.exporter import apply_overlays


MIN_SLIDER_WIDTH = 80

# ---------------------------------------------------------------------------
# Graphics items
# ---------------------------------------------------------------------------

class _OverlayImageItem(QGraphicsPixmapItem):
    """A movable, selectable watermark/logo image item."""

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
            pos = value
            self.overlay.x = int(pos.x())
            self.overlay.y = int(pos.y())
            self.overlay.position = "custom"
        return super().itemChange(change, value)


class _OverlayTextItem(QGraphicsTextItem):
    """A movable, selectable, double-click-editable text overlay item."""

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
            pos = value
            self.overlay.x = int(pos.x())
            self.overlay.y = int(pos.y())
            self.overlay.position = "custom"
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        """Enter inline editing mode on double-click."""
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        """Commit text edits and leave editing mode."""
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.overlay.text = self.toPlainText()
        super().focusOutEvent(event)


# ---------------------------------------------------------------------------
# OverlayEditor widget
# ---------------------------------------------------------------------------

class OverlayEditor(QWidget):
    """Panel for placing watermarks, text, and logo overlays on an asset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("overlay_editor")
        self._asset: Asset | None = None
        self._project: Project | None = None
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._overlay_items: list[_OverlayImageItem | _OverlayTextItem] = []
        self._build()

    # ---- construction ----

    def _build(self):
        from PySide6.QtCore import QSettings
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)

        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)

        root = QVBoxLayout(self)
        root.setContentsMargins(_pad_lg + _pad, _pad_lg + _pad, _pad_lg + _pad, _pad_lg + _pad)

        # Toolbar
        toolbar = QHBoxLayout()

        btn_watermark = QPushButton("Add Watermark")
        btn_watermark.setObjectName("overlay_add_watermark_btn")
        btn_watermark.clicked.connect(self._add_watermark)
        toolbar.addWidget(btn_watermark)

        btn_text = QPushButton("Add Text")
        btn_text.setObjectName("overlay_add_text_btn")
        btn_text.clicked.connect(self._add_text)
        toolbar.addWidget(btn_text)

        self.template_combo = QComboBox()
        self.template_combo.setObjectName("overlay_template_combo")
        self.template_combo.addItem("Apply Template...")
        self.template_combo.activated.connect(self._apply_template)
        toolbar.addWidget(self.template_combo)

        # Separator
        sep1 = QLabel("|")
        sep1.setObjectName("overlay_sep")
        toolbar.addWidget(sep1)

        # Opacity slider
        toolbar.addWidget(QLabel("Opacity:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setObjectName("overlay_opacity_slider")
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(30)
        self.opacity_slider.setFixedWidth(max(MIN_SLIDER_WIDTH, int(_f * 8.3)))
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        toolbar.addWidget(self.opacity_slider)

        # Scale slider
        toolbar.addWidget(QLabel("Scale:"))
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setObjectName("overlay_scale_slider")
        self.scale_slider.setRange(5, 100)
        self.scale_slider.setValue(20)
        self.scale_slider.setFixedWidth(max(MIN_SLIDER_WIDTH, int(_f * 8.3)))
        self.scale_slider.valueChanged.connect(self._on_scale_changed)
        toolbar.addWidget(self.scale_slider)

        # Separator
        sep2 = QLabel("|")
        toolbar.addWidget(sep2)

        btn_delete = QPushButton("Delete")
        btn_delete.setObjectName("overlay_delete_btn")
        btn_delete.clicked.connect(self._delete_selected)
        toolbar.addWidget(btn_delete)

        btn_export = QPushButton("Export Preview")
        btn_export.setObjectName("overlay_export_btn")
        btn_export.clicked.connect(self._export_preview)
        toolbar.addWidget(btn_export)

        toolbar.addStretch()

        self.info_label = QLabel("No image loaded")
        self.info_label.setObjectName("overlay_info")
        toolbar.addWidget(self.info_label)

        root.addLayout(toolbar)

        # Canvas
        self.scene = QGraphicsScene()
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        self.scene.setBackgroundBrush(QBrush(QColor(_dt.bg_deep)))

        self.view = QGraphicsView(self.scene)
        self.view.setObjectName("overlay_view")
        self.view.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        root.addWidget(self.view)

        # Listen for selection changes to update sliders
        self.scene.selectionChanged.connect(self._on_selection_changed)

    # ---- public API ----

    def set_project(self, project: Project):
        """Store project reference and populate template dropdown."""
        self._project = project
        self.template_combo.clear()
        self.template_combo.addItem("Apply Template...")
        for i, tmpl in enumerate(project.default_overlays):
            label = tmpl.get("label", tmpl.get("type", f"Overlay {i + 1}"))
            self.template_combo.addItem(label)

    def load_asset(self, asset: Asset):
        """Load an asset's base image and recreate overlay items."""
        self._asset = asset
        self.scene.clear()
        self._overlay_items.clear()
        self._pixmap_item = None

        pm = QPixmap(asset.source_path)
        if pm.isNull():
            self.info_label.setText("Failed to load image")
            return

        self._pixmap_item = QGraphicsPixmapItem(pm)
        self._pixmap_item.setZValue(0)
        self.scene.addItem(self._pixmap_item)
        self.scene.setSceneRect(QRectF(pm.rect()))
        self.view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

        # Recreate items from existing overlays
        for ov in asset.overlays:
            self._create_item_for_overlay(ov)

        self._update_info()

    # ---- overlay creation ----

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
            opacity=self.opacity_slider.value() / 100.0,
            scale=self.scale_slider.value() / 100.0,
            position="custom",
            x=50, y=50,
        )
        self._asset.overlays.append(ov)
        self._create_item_for_overlay(ov)
        self._update_info()

    def _add_text(self):
        """Add a text overlay at a default position."""
        if not self._asset:
            return

        ov = CanvasOverlay(
            type="text",
            label="Text",
            text="Your text",
            opacity=self.opacity_slider.value() / 100.0,
            position="custom",
            x=50, y=50,
        )
        self._asset.overlays.append(ov)
        self._create_item_for_overlay(ov)
        self._update_info()

    def _apply_template(self, index: int):
        """Load an overlay preset from project.default_overlays."""
        if index <= 0 or not self._project or not self._asset:
            return
        tmpl_index = index - 1  # offset for placeholder item
        if tmpl_index >= len(self._project.default_overlays):
            return

        tmpl = self._project.default_overlays[tmpl_index]
        ov = CanvasOverlay.from_dict(tmpl)
        self._asset.overlays.append(ov)
        self._create_item_for_overlay(ov)
        self._update_info()
        # Reset combo to placeholder
        self.template_combo.setCurrentIndex(0)

    # ---- item factory ----

    def _create_item_for_overlay(self, ov: CanvasOverlay):
        """Create the appropriate graphics item for an overlay and add to scene."""
        if ov.type in ("watermark", "logo") and ov.image_path:
            pm = QPixmap(ov.image_path)
            if pm.isNull():
                return
            # Scale pixmap to overlay.scale fraction of base image width
            if self._pixmap_item:
                base_w = self._pixmap_item.pixmap().width()
                target_w = max(10, int(base_w * ov.scale))
                pm = pm.scaledToWidth(target_w, Qt.TransformationMode.SmoothTransformation)
            item = _OverlayImageItem(pm, ov)
            item.setZValue(len(self._overlay_items) + 1)
            self.scene.addItem(item)
            self._overlay_items.append(item)

        elif ov.type == "text":
            item = _OverlayTextItem(ov)
            item.setZValue(len(self._overlay_items) + 1)
            self.scene.addItem(item)
            self._overlay_items.append(item)

    # ---- slider handlers ----

    def _on_opacity_changed(self, value: int):
        """Apply opacity slider to all selected overlay items."""
        opacity = value / 100.0
        for item in self.scene.selectedItems():
            if isinstance(item, (_OverlayImageItem, _OverlayTextItem)):
                item.setOpacity(opacity)
                item.overlay.opacity = opacity

    def _on_scale_changed(self, value: int):
        """Apply scale slider to selected image overlays (rescale pixmap)."""
        scale = value / 100.0
        for item in self.scene.selectedItems():
            if isinstance(item, _OverlayImageItem):
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
        """Update sliders to reflect the first selected item's values."""
        sel = self.scene.selectedItems()
        for item in sel:
            if isinstance(item, (_OverlayImageItem, _OverlayTextItem)):
                self.opacity_slider.blockSignals(True)
                self.opacity_slider.setValue(int(item.overlay.opacity * 100))
                self.opacity_slider.blockSignals(False)
                if isinstance(item, _OverlayImageItem):
                    self.scale_slider.blockSignals(True)
                    self.scale_slider.setValue(int(item.overlay.scale * 100))
                    self.scale_slider.blockSignals(False)
                break

    # ---- sync & actions ----

    def _sync_to_asset(self):
        """Write overlay items back to asset.overlays."""
        if not self._asset:
            return
        self._asset.overlays.clear()
        for item in self._overlay_items:
            self._asset.overlays.append(item.overlay)
        self._update_info()

    def _delete_selected(self):
        """Remove selected overlays from scene and model."""
        for item in self.scene.selectedItems():
            if isinstance(item, (_OverlayImageItem, _OverlayTextItem)):
                self.scene.removeItem(item)
                if item in self._overlay_items:
                    self._overlay_items.remove(item)
        self._sync_to_asset()

    def _export_preview(self):
        """Render overlays via exporter and save to file."""
        if not self._asset:
            return
        self._sync_to_asset()

        src_path = Path(self._asset.source_path)
        from doxyedit.imaging import load_image_for_export
        img = load_image_for_export(str(src_path))
        img = apply_overlays(img, self._asset.overlays)

        src = Path(self._asset.source_path)
        default_name = f"{src.stem}_overlay_preview{src.suffix}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Overlay Preview", default_name,
            "PNG (*.png);;JPEG (*.jpg);;All Files (*)",
        )
        if path:
            img.save(path)
            self.info_label.setText(f"Exported: {Path(path).name}")

    # ---- helpers ----

    def _update_info(self):
        """Refresh the info label with overlay count."""
        if not self._asset:
            self.info_label.setText("No image loaded")
            return
        n = len(self._asset.overlays)
        name = Path(self._asset.source_path).name
        self.info_label.setText(f"{name} — {n} overlay{'s' if n != 1 else ''}")
