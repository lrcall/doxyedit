"""Image preview — hover tooltip, full preview with annotation notes, crop tool."""
import re
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsScene, QGraphicsView,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsPathItem, QGraphicsItem,
    QApplication, QPushButton, QInputDialog, QWidget, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Qt, QPoint, QRectF, QSettings, QPointF, Signal, QEvent, QTimer, QSize
from PySide6.QtGui import (
    QPainter, QFont, QColor, QKeySequence, QShortcut,
    QTransform, QPen, QBrush, QPainterPath, QPixmap, QIcon,
)

from doxyedit.imaging import load_pixmap
from doxyedit.models import CropRegion, PLATFORMS
from doxyedit.themes import THEMES, DEFAULT_THEME, ui_font_size


def fit_view_to_items(view, scene) -> None:
    """Fit the last item in `scene` into `view`, preserving aspect ratio.
    Centralized so PreviewPane / ImagePreviewDialog / future preview
    widgets share one Fit-to-View implementation."""
    items = scene.items()
    if items:
        view.fitInView(items[-1], Qt.AspectRatioMode.KeepAspectRatio)


def wheel_zoom_view(view, event, factor: float = 1.2) -> None:
    """Scale `view` in/out by `factor` based on the wheel direction.
    Centralized so all preview widgets share the same zoom feel."""
    f = factor if event.angleDelta().y() > 0 else 1 / factor
    view.scale(f, f)


def _preview_xform_mode():
    """Return the QGraphicsPixmapItem.TransformationMode the user last chose.
    Used at every point we (re)build a pixmap item so the saved 'preview_bilinear'
    setting isn't clobbered when navigating between images / reopening preview."""
    bilinear = QSettings("DoxyEdit", "DoxyEdit").value(
        "preview_bilinear", True, type=bool)
    return (Qt.TransformationMode.SmoothTransformation if bilinear
            else Qt.TransformationMode.FastTransformation)


class HoverPreview(QWidget):
    """Floating preview that appears near the cursor on hover."""

    _instance = None
    PREVIEW_SIZE = 500

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("hover_preview")
        _f = ui_font_size()
        _pad = max(4, _f // 3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_pad, _pad, _pad, _pad)
        layout.setSpacing(max(2, _pad // 2))
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._img_label)
        self._info_label = QLabel()
        self._info_label.setObjectName("hover_preview_info")
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)
        self.hide()
        self._path = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def show_for(self, image_path: str, global_pos: QPoint):
        if self._path == image_path and self.isVisible():
            return
        self._path = image_path
        pm, w, h = load_pixmap(image_path)
        if pm.isNull():
            self.hide()
            return
        orig_w, orig_h = pm.width(), pm.height()
        pm = pm.scaled(
            self.PREVIEW_SIZE, self.PREVIEW_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._img_label.setPixmap(pm)
        self._info_label.setText(f"{orig_w} x {orig_h}px\n{image_path}")
        self.adjustSize()

        screen = QApplication.screenAt(global_pos)
        if screen:
            screen_rect = screen.availableGeometry()
            x = global_pos.x() + 20
            y = global_pos.y() - self.height() // 2
            if x + self.width() > screen_rect.right():
                x = global_pos.x() - self.width() - 20
            y = max(screen_rect.top(), min(y, screen_rect.bottom() - self.height()))
            self.move(x, y)

        self.show()

    def hide_preview(self):
        self._path = None
        self.hide()


class NoteRectItem(QGraphicsRectItem):
    """A draggable note box with text label — text stays fixed screen size at any zoom."""

    _FONT = QFont(); _FONT.setBold(True)

    def __init__(self, rect: QRectF, text: str = ""):
        super().__init__(rect)
        _dt = THEMES[DEFAULT_THEME]
        _nc = QColor(_dt.note_border)
        _nc.setAlpha(_dt.preview_overlay_alpha)
        self.setPen(QPen(_nc, _dt.crop_border_width))
        _nf = QColor(_dt.note_border)
        _nf.setAlpha(_dt.preview_hint_bg_alpha)
        self.setBrush(QBrush(_nf))
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.text = text

    def update_text(self, text: str):
        self.text = text
        self.update()

    def paint(self, painter, option, widget=None):
        # Draw the rect border/fill normally (scales with zoom)
        super().paint(painter, option, widget)
        if not self.text:
            return

        # Map the rect's top-left corner from scene → screen pixels
        scene_tl = self.mapToScene(self.rect().topLeft())
        screen_tl = painter.transform().map(scene_tl)

        # Switch to screen-space drawing so font size is independent of zoom
        painter.save()
        painter.resetTransform()

        fm = painter.fontMetrics()  # use whatever font is current
        painter.setFont(self._FONT)
        fm = painter.fontMetrics()
        pad_x, pad_y = 8, 5
        text_w = fm.horizontalAdvance(self.text) + pad_x * 2
        text_h = fm.height() + pad_y * 2

        bg = QRectF(screen_tl.x() + 4, screen_tl.y() + 4, text_w, text_h)
        _dt = THEMES[DEFAULT_THEME]
        _label_bg = QColor(0, 0, 0); _label_bg.setAlpha(_dt.preview_label_bg_alpha)
        painter.fillRect(bg, _label_bg)
        _label_fg = QColor(255, 240, 210); _label_fg.setAlpha(_dt.preview_label_text_alpha)
        painter.setPen(_label_fg)
        painter.drawText(bg.adjusted(pad_x, pad_y, -pad_x, -pad_y), self.text)

        painter.restore()


class ResizableCropItem(QGraphicsRectItem):
    """Crop rectangle with 8 resize handles, a rotate handle, and
    drag-to-move."""

    HANDLE_SIZE = 14
    ROTATE_HANDLE_OFFSET = 24   # px above top edge for the rotate handle
    ROTATE_HANDLE_DIAM = 14     # circle diameter

    def __init__(self, rect: QRectF, label: str = "", aspect: float | None = None, theme=None, parent=None):
        super().__init__(rect, parent)
        self.label = label
        self._aspect = aspect
        self._handle_dragging = -1  # which handle is being dragged (-1 = none)
        self._drag_start_rect = QRectF()
        # Cosmetic: when set, paint() draws a dashed outline of the rotated
        # crop region around the rect's center so the user sees how the
        # exporter will rotate-before-crop. Axis-aligned rect itself stays
        # the source of truth for x/y/w/h.
        self.rotation_deg: float = 0.0
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        if theme is None:
            theme = THEMES[DEFAULT_THEME]
        self._theme = theme
        _cc = QColor(theme.crop_border)
        _cc.setAlpha(theme.preview_overlay_alpha)
        self.setPen(QPen(_cc, theme.crop_border_width))
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setZValue(101)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.on_changed = None  # callback when rect changes

    def paint(self, painter, option, widget=None):
        # Draw main rect
        painter.setPen(self.pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect())
        # Draw rotated outline (dashed) when rotation is non-zero so the
        # user sees what the exporter will produce. Drawn around the
        # rect's center to match exporter.apply_crop_rect.
        if self.rotation_deg:
            painter.save()
            r = self.rect()
            cx, cy = r.center().x(), r.center().y()
            painter.translate(cx, cy)
            painter.rotate(self.rotation_deg)
            painter.translate(-cx, -cy)
            dash_pen = QPen(self.pen())
            dash_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(dash_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(r)
            painter.restore()
        # Draw label (screen-space sized so it stays readable at any zoom)
        if self.label:
            _dt = THEMES[DEFAULT_THEME]
            font = painter.font()
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            scale = view.transform().m11() if view else 1.0
            _t = self._theme
            # Clamp to a positive minimum — Qt logs "Pixel size <= 0" if
            # this ever becomes 0, which happened during zoom-wheel spam.
            _px = max(_t.crop_label_min_font or 12,
                       int((_t.font_size or 12) * _t.crop_label_scale_ratio
                           / max(abs(scale), 0.01)))
            font.setPixelSize(max(1, _px))
            font.setBold(True)
            painter.setFont(font)
            inv = 1.0 / max(scale, 0.01)
            pad = 6 * inv
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(self.label)
            th = fm.height()
            tx = self.rect().x() + pad
            ty = self.rect().y() + pad
            bg_rect = QRectF(tx - 3 * inv, ty - 2 * inv, tw + 6 * inv, th + 4 * inv)
            painter.setPen(Qt.PenStyle.NoPen)
            _bg = QColor(0, 0, 0)
            _bg.setAlpha(_t.crop_label_bg_alpha)
            painter.setBrush(_bg)
            painter.drawRoundedRect(bg_rect, 3 * inv, 3 * inv)
            painter.setPen(QColor(_t.crop_label_text))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(QRectF(tx, ty, tw, th), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.label)
        # Draw handles if selected
        if self.isSelected():
            handles = self._handle_rects()
            # Resize handles 0..7 as small filled rects
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._theme.crop_border))
            for hr in handles[:8]:
                painter.drawRect(hr)
            # Rotate handle (index 8) drawn as an outlined circle so
            # users can tell it apart from the resize handles, with a
            # thin connector line down to the top edge.
            r = self.rect()
            cx = r.center().x()
            top_y = r.top()
            rot_handle = handles[8]
            connector_pen = QPen(QColor(self._theme.crop_border),
                                 max(1, self.HANDLE_SIZE // 7))
            painter.setPen(connector_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(
                QPointF(cx, top_y),
                QPointF(rot_handle.center().x(), rot_handle.center().y()))
            painter.setBrush(QColor(self._theme.crop_border))
            painter.drawEllipse(rot_handle)

    def _handle_rects(self) -> list[QRectF]:
        """Return 9 handle rects in order:
        0:TL 1:TC 2:TR 3:ML 4:MR 5:BL 6:BC 7:BR 8:rotate."""
        r = self.rect()
        s = self.HANDLE_SIZE
        hs = s / 2
        cx, cy = r.center().x(), r.center().y()
        rd = self.ROTATE_HANDLE_DIAM
        rh = rd / 2
        return [
            QRectF(r.left() - hs, r.top() - hs, s, s),          # 0: TL
            QRectF(cx - hs, r.top() - hs, s, s),                 # 1: TC
            QRectF(r.right() - hs, r.top() - hs, s, s),          # 2: TR
            QRectF(r.left() - hs, cy - hs, s, s),                # 3: ML
            QRectF(r.right() - hs, cy - hs, s, s),               # 4: MR
            QRectF(r.left() - hs, r.bottom() - hs, s, s),        # 5: BL
            QRectF(cx - hs, r.bottom() - hs, s, s),              # 6: BC
            QRectF(r.right() - hs, r.bottom() - hs, s, s),       # 7: BR
            QRectF(cx - rh,
                   r.top() - self.ROTATE_HANDLE_OFFSET - rh,
                   rd, rd),                                       # 8: rotate
        ]

    def boundingRect(self):
        """Expand the bounding rect upward so the rotate handle and
        its connector line are inside the paint dispatch area."""
        r = self.rect()
        margin_top = self.ROTATE_HANDLE_OFFSET + self.ROTATE_HANDLE_DIAM
        return r.adjusted(0, -margin_top, 0, 0)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            for i, hr in enumerate(self._handle_rects()):
                if hr.contains(pos):
                    self._handle_dragging = i
                    self._drag_start_rect = QRectF(self.rect())
                    event.accept()
                    return
        self._handle_dragging = -1
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._handle_dragging == 8:
            # Rotate handle: angle from rect center to cursor, where
            # 0 deg = handle straight up. atan2(dx, -dy) gives clockwise
            # angle from "12 o'clock". Snap to 15deg with Shift held.
            import math
            r = self.rect()
            cx, cy = r.center().x(), r.center().y()
            dx = event.pos().x() - cx
            dy = event.pos().y() - cy
            angle = math.degrees(math.atan2(dx, -dy))
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                angle = round(angle / 15.0) * 15.0
            # Wrap to [-180, 180]
            while angle > 180:
                angle -= 360
            while angle < -180:
                angle += 360
            self.rotation_deg = float(angle)
            self.update()
            event.accept()
            return
        if self._handle_dragging >= 0:
            pos = event.pos()
            r = QRectF(self._drag_start_rect)
            h = self._handle_dragging
            if h in (0, 3, 5):  # left handles
                r.setLeft(pos.x())
            if h in (2, 4, 7):  # right handles
                r.setRight(pos.x())
            if h in (0, 1, 2):  # top handles
                r.setTop(pos.y())
            if h in (5, 6, 7):  # bottom handles
                r.setBottom(pos.y())
            r = r.normalized()
            if self._aspect and self._aspect > 0:
                if h in (3, 4):
                    r.setHeight(r.width() / self._aspect)
                elif h in (1, 6):
                    r.setWidth(r.height() * self._aspect)
                else:
                    r.setHeight(r.width() / self._aspect)
            if r.width() >= 10 and r.height() >= 10:
                self.prepareGeometryChange()
                self.setRect(r)
                self._drag_start_rect = QRectF(r)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._handle_dragging >= 0:
            self._handle_dragging = -1
            if self.on_changed:
                self.on_changed(self)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self.on_changed:
            self.on_changed(self)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and self.on_changed:
            self.on_changed(self)
        return super().itemChange(change, value)

    def get_crop_region(self):
        """Return current bounds as a CropRegion. Carries the cosmetic
        rotation_deg through so dragging/resizing the rect doesn't
        silently zero out a previously-set rotation."""
        r = self.rect().translated(self.pos())
        return CropRegion(
            x=int(r.x()), y=int(r.y()),
            w=int(r.width()), h=int(r.height()),
            label=self.label,
            rotation=float(getattr(self, "rotation_deg", 0.0) or 0.0),
        )


class ImagePreviewDialog(QDialog):
    """Full image preview — zoomable, with annotation notes and prev/next navigation."""

    navigated = Signal(str)   # emitted with asset_id when user navigates to a different asset
    dock_requested = Signal()  # emitted when user clicks the Dock button
    studio_requested = Signal()  # emitted when user clicks the Studio button

    DIALOG_MIN_WIDTH_RATIO = 66.7      # preview dialog minimum width
    DIALOG_MIN_HEIGHT_RATIO = 50.0     # preview dialog minimum height
    # Tiny mode lower-bound: ~3x3 cm on a typical 96 DPI display. Small
    # enough to tuck into a corner as a passive reference image.
    DIALOG_MIN_WIDTH_TINY = 120
    DIALOG_MIN_HEIGHT_TINY = 80

    def __init__(self, image_path: str, asset=None, parent=None,
                 assets: list = None, current_index: int = 0):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint)
        self._asset = asset
        self._assets = assets or []   # ordered list of Asset objects for navigation
        self._nav_index = current_index
        self._is_fullscreen = False
        self.setWindowTitle(f"Preview — {Path(image_path).name}")
        settings = QSettings("DoxyEdit", "DoxyEdit")
        _f = settings.value("font_size", 12, type=int)
        # "Tiny mode" preference — when on, the dialog can shrink to a
        # thumbnail-sized reference tile. Persisted so the user's choice
        # survives sessions. Right-click anywhere inside the dialog to
        # flip the toggle.
        self._preview_tiny_mode = settings.value(
            "preview_tiny_mode", False, type=bool)
        self._apply_preview_min_size(_f)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            self._on_preview_context_menu)
        _cb = max(14, _f + 2)
        w_size = settings.value("preview_width", 1100, type=int)
        h_size = settings.value("preview_height", 800, type=int)
        self.resize(w_size, h_size)
        px = settings.value("preview_x", -1, type=int)
        py = settings.value("preview_y", -1, type=int)
        if px >= 0 and py >= 0:
            # Validate position is on a connected screen
            target = QPoint(px + self.width() // 2, py + 30)
            screen = QApplication.screenAt(target)
            if screen:
                # Clamp to screen bounds
                geom = screen.availableGeometry()
                px = max(geom.left(), min(px, geom.right() - self.width()))
                py = max(geom.top(), min(py, geom.bottom() - self.height()))
                self.move(px, py)
            else:
                # Saved position is off-screen — center on primary screen
                primary = QApplication.primaryScreen()
                if primary:
                    geom = primary.availableGeometry()
                    self.move(
                        geom.left() + (geom.width() - self.width()) // 2,
                        geom.top() + (geom.height() - self.height()) // 2)
        # Stylesheet applied externally by caller (so theme is inherited)
        # Fall back to a dark background if none is provided
        self.setObjectName("preview_dialog")

        self._annotating = False
        self._draw_start = None
        self._temp_rect = None
        self._notes: list[NoteRectItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Info bar
        info_bar = QHBoxLayout()
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)
        info_bar.setContentsMargins(_pad * 3, _pad_lg, _pad * 3, _pad)

        pm, w, h = load_pixmap(image_path)
        name = Path(image_path).name
        ratio = f"{w/h:.2f}" if h else "?"

        info = QLabel(f"{name}  |  {w} x {h}  |  ratio {ratio}")
        info.setObjectName("preview_info")
        info_bar.addWidget(info)
        info_bar.addStretch()

        # Studio button — jump this asset into Studio
        self._studio_btn = QPushButton("Studio")
        self._studio_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._studio_btn.setToolTip("Open this asset in Studio")
        self._studio_btn.clicked.connect(
            lambda: self.studio_requested.emit() if self._asset else None)
        info_bar.addWidget(self._studio_btn)

        # Note button — NoFocus so Space/Tab never get captured by button
        self._note_btn = QPushButton("Add Note")
        self._note_btn.setCheckable(True)
        self._note_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._note_btn.toggled.connect(self._toggle_note_mode)
        info_bar.addWidget(self._note_btn)

        self._view_notes_btn = QPushButton("View Notes")
        self._view_notes_btn.setCheckable(True)
        self._view_notes_btn.setChecked(False)
        self._view_notes_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._view_notes_btn.toggled.connect(self._toggle_view_notes)
        info_bar.addWidget(self._view_notes_btn)

        # Crop tool
        self._crop_btn = QPushButton("Crop")
        self._crop_btn.setCheckable(True)
        self._crop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._crop_btn.setToolTip("Draw a crop region (C key)")
        self._crop_btn.toggled.connect(self._toggle_crop_mode)
        info_bar.addWidget(self._crop_btn)

        self._crop_combo = QComboBox()
        self._crop_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._crop_combo.setFixedWidth(max(160, int(_f * 16.7)))
        self._crop_combo.addItem("Free crop", None)
        for pid, platform in PLATFORMS.items():
            self._crop_combo.insertSeparator(self._crop_combo.count())
            # Platform header (disabled)
            self._crop_combo.addItem(f"\u2500\u2500 {platform.name} \u2500\u2500", None)
            idx = self._crop_combo.count() - 1
            self._crop_combo.model().item(idx).setEnabled(False)
            for slot in platform.slots:
                ratio = f"{slot.width}x{slot.height}"
                self._crop_combo.addItem(
                    f"  {slot.label} ({ratio})",
                    (slot.width, slot.height))
        self._crop_combo.setVisible(False)
        info_bar.addWidget(self._crop_combo)

        self._cropping = False
        self._crop_start: QPointF | None = None
        self._crop_rect_item: QGraphicsRectItem | None = None
        self._crop_mask_item: QGraphicsPathItem | None = None
        self._crop_items: list[ResizableCropItem] = []

        self._on_top_btn = QPushButton("On Top")
        self._on_top_btn.setCheckable(True)
        self._on_top_btn.setChecked(True)
        self._on_top_btn.setToolTip("Stay above DoxyEdit window")
        self._on_top_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._on_top_btn.toggled.connect(self._toggle_on_top)
        info_bar.addWidget(self._on_top_btn)
        # setChecked(True) ran BEFORE the connect above, so the initial
        # on-top state was never actually installed — the button showed
        # checked but nothing was wired to raise us when the parent
        # gained focus. Fire the handler once post-connect to install
        # the event filter so "On Top" actually works on first open.
        self._toggle_on_top(True)

        self._pin_btn = QPushButton("Pin")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setToolTip("Always on top (system-wide)")
        self._pin_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pin_btn.toggled.connect(self._toggle_always_on_top)
        info_bar.addWidget(self._pin_btn)

        self._dock_btn = QPushButton("Dock")
        self._dock_btn.setToolTip("Dock preview into main window (Ctrl+D)")
        self._dock_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._dock_btn.clicked.connect(self._on_dock)
        info_bar.addWidget(self._dock_btn)

        # Fullscreen toggle — painted icon (four corner brackets,
        # matching Studio's _StudioIcons.focus() style). The unicode
        # "⛶" fallback rendered as a blank tofu on several Windows
        # font setups.
        def _fs_icon(size=_cb):
            pm = QPixmap(size, size)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            _t = THEMES[DEFAULT_THEME]
            pen = QPen(QColor(_t.text_secondary))
            pen.setWidth(max(1, size // 10))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            m = max(2, size // 6)            # inset margin
            arm = max(2, size // 4)          # bracket arm length
            # Top-left corner
            p.drawLine(m, m, m + arm, m)
            p.drawLine(m, m, m, m + arm)
            # Top-right
            p.drawLine(size - m, m, size - m - arm, m)
            p.drawLine(size - m, m, size - m, m + arm)
            # Bottom-left
            p.drawLine(m, size - m, m + arm, size - m)
            p.drawLine(m, size - m, m, size - m - arm)
            # Bottom-right
            p.drawLine(size - m, size - m, size - m - arm, size - m)
            p.drawLine(size - m, size - m, size - m, size - m - arm)
            p.end()
            return QIcon(pm)

        self._fs_btn = QPushButton()
        self._fs_btn.setIcon(_fs_icon())
        self._fs_btn.setIconSize(QSize(int(_cb * 0.9), int(_cb * 0.9)))
        self._fs_btn.setFixedWidth(_cb * 2)
        self._fs_btn.setToolTip("Toggle fullscreen (F11)")
        self._fs_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fs_btn.clicked.connect(self._toggle_fullscreen)
        info_bar.addWidget(self._fs_btn)

        nav_hint = " |  ← → Space" if self._assets else ""
        hint_text = f"Scroll=zoom  Drag=pan  N=note  V=toggle  F11=full  Esc=close{nav_hint}"
        self._hint_lbl = QLabel(hint_text)
        self._hint_lbl.setObjectName("preview_hint")
        self._hint_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info_bar.addWidget(self._hint_lbl)

        # Info bar widget — double-click toggles fullscreen
        info_bar_widget = QWidget()
        info_bar_widget.setLayout(info_bar)
        info_bar_widget.mouseDoubleClickEvent = lambda e: self._toggle_fullscreen()
        layout.addWidget(info_bar_widget)
        # Held so Tiny mode can hide this whole row — the toggle is
        # about reclaiming space, not just shrinking the frame.
        self._info_bar_widget = info_bar_widget
        # Apply whatever tiny-mode persisted state we read at init.
        if self._preview_tiny_mode:
            info_bar_widget.setVisible(False)

        # Zoomable view
        _dt = THEMES[DEFAULT_THEME]
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QColor(_dt.bg_deep))
        self.view = QGraphicsView(self.scene)
        # Apply persisted bilinear / nearest preference. Default on
        # (smooth upscale); users who want true pixel ratio flip via
        # right-click context menu.
        _bilinear = QSettings("DoxyEdit", "DoxyEdit").value(
            "preview_bilinear", True, type=bool)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform, _bilinear)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # Allow panning beyond the image edges
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.view)

        self._pixmap_item = None
        if not pm.isNull():
            self._pixmap_item = QGraphicsPixmapItem(pm)
            self._pixmap_item.setTransformationMode(self._preview_xform_mode())
            self.scene.addItem(self._pixmap_item)
            self._expand_scene_rect(pm.width(), pm.height())

            saved_zoom = settings.value("preview_zoom", 0.0, type=float)
            if saved_zoom > 0:
                self.view.setTransform(QTransform.fromScale(saved_zoom, saved_zoom))
                self.view.centerOn(self._pixmap_item)
            else:
                self.view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
                self.view.centerOn(self._pixmap_item)

        # Override mouse events for annotation
        self.view.mousePressEvent = self._view_mouse_press
        self.view.mouseMoveEvent = self._view_mouse_move
        self.view.mouseReleaseEvent = self._view_mouse_release
        self.view.wheelEvent = self._wheel_zoom

        QShortcut(QKeySequence("Escape"), self, self.close)
        QShortcut(QKeySequence("Ctrl+0"), self, self._fit_to_view)
        QShortcut(QKeySequence("N"), self, lambda: self._note_btn.toggle())
        QShortcut(QKeySequence("C"), self, lambda: self._crop_btn.toggle())
        QShortcut(QKeySequence("V"), self, lambda: self._view_notes_btn.toggle())
        QShortcut(QKeySequence("S"), self,
                   lambda: self.studio_requested.emit() if self._asset else None)
        QShortcut(QKeySequence("Delete"), self, self._delete_selected_note)
        QShortcut(QKeySequence("F11"), self, self._toggle_fullscreen)
        # Navigation keys are intercepted at dialog level so they always fire
        # regardless of which child widget has focus.
        self.installEventFilter(self)
        self.view.viewport().installEventFilter(self)
        self.view.installEventFilter(self)

        # Load existing annotations from asset notes
        self._load_saved_notes()
        self._load_existing_crops()

    def update_theme(self, theme):
        """Update QGraphicsScene background from theme (can't use QSS for scenes)."""
        self.scene.setBackgroundBrush(QColor(theme.bg_deep))

    def eventFilter(self, obj, event):
        # Parent window activated — raise preview above it (On Top mode)
        # Deferred so it fires after Qt finishes processing the activation
        if obj is self.parent() and event.type() == QEvent.Type.WindowActivate:
            if self.isVisible():
                QTimer.singleShot(0, self.raise_)
            return False  # don't consume

        # Ctrl+C — copy image to clipboard
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if self._pixmap_item and not self._pixmap_item.pixmap().isNull():
                    QApplication.clipboard().setPixmap(self._pixmap_item.pixmap())
                    self._hint_lbl.setText("Copied to clipboard")
                return True

        # Navigation keys — intercept before any child widget. Arrow keys
        # are reserved for text-field cursor movement per user preference;
        # only Space / Tab / Backspace navigate between previewed assets.
        if event.type() == QEvent.Type.KeyPress and self._assets:
            key = event.key()
            if key in (Qt.Key.Key_Space, Qt.Key.Key_Tab):
                self._navigate(1)
                return True
            if key == Qt.Key.Key_Backspace:
                self._navigate(-1)
                return True
        return super().eventFilter(obj, event)

    def _load_saved_notes(self):
        """Parse annotation notes from asset.notes and display them."""
        if not self._asset or not self._asset.notes:
            return
        pattern = re.compile(r'\[(\d+),(\d+)\s+(\d+)x(\d+)\]\s*(.*)')
        for line in self._asset.notes.split("\n"):
            m = pattern.match(line.strip())
            if m:
                x, y, w, h = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                text = m.group(5)
                note = NoteRectItem(QRectF(x, y, w, h), text)
                self.scene.addItem(note)
                self._notes.append(note)

    def _toggle_view_notes(self, checked):
        """Show/hide all annotation notes."""
        for note in self._notes:
            note.setVisible(checked)

    def _toggle_note_mode(self, checked):
        self._annotating = checked
        if checked:
            self._crop_btn.setChecked(False)  # turn off crop if note on
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.setCursor(Qt.CursorShape.CrossCursor)
        else:
            if not self._cropping:
                self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                self.view.setCursor(Qt.CursorShape.ArrowCursor)

    def _toggle_crop_mode(self, checked):
        self._cropping = checked
        self._crop_combo.setVisible(checked)
        if checked:
            self._note_btn.setChecked(False)  # turn off notes if crop on
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.view.setCursor(Qt.CursorShape.ArrowCursor)
            self._clear_crop_visuals()

    def _clear_crop_visuals(self):
        if self._crop_rect_item:
            self.scene.removeItem(self._crop_rect_item)
            self._crop_rect_item = None
        if self._crop_mask_item:
            self.scene.removeItem(self._crop_mask_item)
            self._crop_mask_item = None

    def _get_crop_aspect(self) -> float | None:
        """Return target W/H aspect ratio from combo, or None for free crop."""
        data = self._crop_combo.currentData()
        if data is None:
            return None
        w, h = data
        return w / h if h else None

    def _constrain_rect(self, start: QPointF, end: QPointF, aspect: float | None) -> QRectF:
        """Build a QRectF from two points, optionally constrained to aspect ratio."""
        r = QRectF(start, end).normalized()
        if aspect is None or r.width() < 2 or r.height() < 2:
            return r
        # Constrain to aspect ratio — expand to fill the drag extent
        cur_aspect = r.width() / r.height()
        if cur_aspect > aspect:
            # Too wide — shrink width
            new_w = r.height() * aspect
            r.setWidth(new_w)
        else:
            # Too tall — shrink height
            new_h = r.width() / aspect
            r.setHeight(new_h)
        return r

    def _update_crop_mask(self, crop_rect: QRectF):
        """Draw dark overlay outside the crop region."""
        if self._crop_mask_item:
            self.scene.removeItem(self._crop_mask_item)
        # Get image bounds from cached reference
        img_item = getattr(self, '_pixmap_item', None)
        if not img_item:
            # Fallback: scan scene
            items = [i for i in self.scene.items() if isinstance(i, QGraphicsPixmapItem)]
            if not items:
                return
            img_item = items[-1]
        img_rect = img_item.boundingRect()
        # Build mask path: full image minus crop hole
        path = QPainterPath()
        path.addRect(img_rect)
        hole = QPainterPath()
        hole.addRect(crop_rect)
        path = path.subtracted(hole)
        self._crop_mask_item = QGraphicsPathItem(path)
        self._crop_mask_item.setPen(QPen(Qt.PenStyle.NoPen))
        _mask_bg = QColor(0, 0, 0); _mask_bg.setAlpha(THEMES[DEFAULT_THEME].preview_tooltip_bg_alpha)
        self._crop_mask_item.setBrush(QBrush(_mask_bg))
        self._crop_mask_item.setZValue(100)
        self.scene.addItem(self._crop_mask_item)

    def _save_crop_to_asset(self, rect: QRectF):
        """Store the crop region on the current asset."""
        if not self._asset:
            return
        data = self._crop_combo.currentData()
        label = self._crop_combo.currentText() if data else "free"
        crop = CropRegion(
            x=int(rect.x()), y=int(rect.y()),
            w=int(rect.width()), h=int(rect.height()),
            label=label)
        # Replace existing crop with same label, or append
        self._asset.crops = [c for c in self._asset.crops if c.label != label]
        self._asset.crops.append(crop)

    def _replace_with_editable_crop(self, rect: QRectF, label: str):
        """Replace temp crop rect with a persistent, editable one."""
        # Remove temp visuals
        if self._crop_rect_item and self._crop_rect_item.scene():
            self.scene.removeItem(self._crop_rect_item)
        self._crop_rect_item = None
        # Create editable crop
        crop_item = ResizableCropItem(rect, label=label)
        crop_item.on_changed = self._on_crop_edited
        self.scene.addItem(crop_item)
        self._crop_items.append(crop_item)
        self._update_crop_mask(rect)

    def _load_existing_crops(self):
        """Show existing crop regions as editable overlays."""
        # Clear old crop items
        for item in self._crop_items:
            if item.scene():
                self.scene.removeItem(item)
        self._crop_items.clear()
        if not self._asset or not self._asset.crops:
            return
        for crop in self._asset.crops:
            rect = QRectF(crop.x, crop.y, crop.w, crop.h)
            item = ResizableCropItem(rect, label=crop.label)
            item.on_changed = self._on_crop_edited
            self.scene.addItem(item)
            self._crop_items.append(item)

    def _on_crop_edited(self, item: ResizableCropItem):
        """Sync a moved/resized crop back to the asset."""
        if not self._asset:
            return
        region = item.get_crop_region()
        # Replace existing crop with same label
        self._asset.crops = [c for c in self._asset.crops if c.label != region.label]
        self._asset.crops.append(region)
        # Update mask to match edited crop
        r = item.rect().translated(item.pos())
        self._update_crop_mask(r)

    def _view_mouse_press(self, event):
        if self._cropping and event.button() == Qt.MouseButton.LeftButton:
            self._crop_start = self.view.mapToScene(event.position().toPoint())
            self._clear_crop_visuals()
            self._crop_rect_item = QGraphicsRectItem()
            _dt = THEMES[DEFAULT_THEME]
            _cc = QColor(_dt.crop_border); _cc.setAlpha(_dt.preview_overlay_alpha)
            self._crop_rect_item.setPen(QPen(_cc, _dt.crop_border_width))
            self._crop_rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            self._crop_rect_item.setZValue(101)
            self.scene.addItem(self._crop_rect_item)
            return
        if self._annotating and event.button() == Qt.MouseButton.LeftButton:
            self._draw_start = self.view.mapToScene(event.position().toPoint())
            self._temp_rect = NoteRectItem(QRectF(self._draw_start, self._draw_start), "")
            self.scene.addItem(self._temp_rect)
            return
        QGraphicsView.mousePressEvent(self.view, event)

    def _view_mouse_move(self, event):
        if self._cropping and self._crop_start and self._crop_rect_item:
            pos = self.view.mapToScene(event.position().toPoint())
            aspect = self._get_crop_aspect()
            r = self._constrain_rect(self._crop_start, pos, aspect)
            self._crop_rect_item.setRect(r)
            self._update_crop_mask(r)
            return
        if self._annotating and self._draw_start and self._temp_rect:
            pos = self.view.mapToScene(event.position().toPoint())
            r = QRectF(self._draw_start, pos).normalized()
            self._temp_rect.setRect(r)
            return
        QGraphicsView.mouseMoveEvent(self.view, event)

    def _view_mouse_release(self, event):
        if self._cropping and self._crop_rect_item and self._crop_start:
            r = self._crop_rect_item.rect()
            if r.width() > 10 and r.height() > 10:
                self._save_crop_to_asset(r)
                # Replace temp rect with editable crop item
                data = self._crop_combo.currentData()
                label = self._crop_combo.currentText().strip() if data else "free"
                self._replace_with_editable_crop(r, label)
            else:
                self._clear_crop_visuals()
            self._crop_start = None
            self._crop_btn.setChecked(False)
            return
        if self._annotating and self._temp_rect:
            r = self._temp_rect.rect()
            if r.width() > 10 and r.height() > 10:
                # Ask for note text
                dlg = QInputDialog(self)
                dlg.setWindowTitle("Note")
                dlg.setLabelText("Enter note:")
                from doxyedit.themes import themed_dialog_size
                dlg.resize(*themed_dialog_size(41.67, 11.67))
                ok = dlg.exec()
                text = dlg.textValue() if ok else ""
                if ok and text.strip():
                    self._temp_rect.update_text(text.strip())
                    self._notes.append(self._temp_rect)
                    self._save_notes_to_asset()
                else:
                    self.scene.removeItem(self._temp_rect)
            else:
                self.scene.removeItem(self._temp_rect)
            self._temp_rect = None
            self._draw_start = None
            self._note_btn.setChecked(False)
            return
        QGraphicsView.mouseReleaseEvent(self.view, event)

    def _delete_selected_note(self):
        for item in self.scene.selectedItems():
            if isinstance(item, ResizableCropItem):
                if item.scene():
                    self.scene.removeItem(item)
                if item in self._crop_items:
                    self._crop_items.remove(item)
                if self._asset:
                    self._asset.crops = [c for c in self._asset.crops if c.label != item.label]
            elif isinstance(item, NoteRectItem):
                self.scene.removeItem(item)
                if item in self._notes:
                    self._notes.remove(item)
        self._save_notes_to_asset()

    def _save_notes_to_asset(self):
        """Save all note annotations to the asset's notes field."""
        if not self._asset:
            return
        note_lines = []
        for n in self._notes:
            r = n.rect()
            note_lines.append(f"[{int(r.x())},{int(r.y())} {int(r.width())}x{int(r.height())}] {n.text}")
        # Preserve any existing non-annotation notes
        existing = self._asset.notes
        existing_lines = [l for l in existing.split("\n") if l.strip() and not l.strip().startswith("[")]
        all_lines = existing_lines + note_lines
        self._asset.notes = "\n".join(all_lines)

    def jump_to(self, asset, assets: list, index: int):
        """Switch to a different asset (called externally when reusing the dialog).
        Does NOT emit navigated — the browser already knows the selection."""
        self._assets = assets
        self._nav_index = index
        self._load_asset(asset)
        self.raise_()
        self.activateWindow()

    def _navigate(self, direction: int):
        """Move to the next (+1) or previous (-1) asset."""
        if not self._assets:
            return
        self._nav_index = (self._nav_index + direction) % len(self._assets)
        asset = self._assets[self._nav_index]
        self._load_asset(asset)
        self.navigated.emit(asset.id)

    def _expand_scene_rect(self, img_w: int, img_h: int):
        """Set scene rect to image + large overpan margin so panning isn't clamped."""
        margin = max(img_w, img_h, 4000)
        self.scene.setSceneRect(QRectF(-margin, -margin, img_w + margin * 2, img_h + margin * 2))

    def _load_asset(self, asset):
        """Swap the displayed image for a new asset without recreating the dialog."""
        self._save_notes_to_asset()
        self._asset = asset
        self._crop_rect_item = None
        self._crop_mask_item = None
        self._crop_start = None
        self._crop_items = []
        pm, w, h = load_pixmap(asset.source_path)
        self.setWindowTitle(f"Preview — {Path(asset.source_path).name}")
        self.scene.clear()
        self._notes = []
        self._pixmap_item = None
        if not pm.isNull():
            self._pixmap_item = QGraphicsPixmapItem(pm)
            self._pixmap_item.setTransformationMode(self._preview_xform_mode())
            self.scene.addItem(self._pixmap_item)
            self._expand_scene_rect(pm.width(), pm.height())
            self.view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            self.view.centerOn(self._pixmap_item)
        self._load_saved_notes()
        self._load_existing_crops()

    def _on_dock(self):
        """Request docking into main window and close this dialog."""
        self.dock_requested.emit()
        self.close()

    def _toggle_on_top(self, on: bool):
        """Stay above the DoxyEdit parent window but not other apps."""
        if on:
            if self.parent():
                self.parent().installEventFilter(self)
            self.raise_()
        else:
            if self.parent():
                self.parent().removeEventFilter(self)

    def _toggle_always_on_top(self, on: bool):
        """System-wide always-on-top via Qt window flag."""
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_hint_lbl'):
            self._hint_lbl.setVisible(self.width() >= 820)

    def _apply_preview_min_size(self, font_size: int | None = None):
        """Set minimum window size based on the tiny-mode preference.

        Normal mode: width = font_size * DIALOG_MIN_WIDTH_RATIO, similar
        for height — roughly 800x600 at 12pt.
        Tiny mode: 120x80 absolute — small enough to tuck into a corner
        as a passive reference image while working elsewhere.
        """
        if font_size is None:
            font_size = QSettings("DoxyEdit", "DoxyEdit").value(
                "font_size", 12, type=int)
        if getattr(self, "_preview_tiny_mode", False):
            self.setMinimumSize(self.DIALOG_MIN_WIDTH_TINY,
                                self.DIALOG_MIN_HEIGHT_TINY)
        else:
            self.setMinimumSize(
                int(font_size * self.DIALOG_MIN_WIDTH_RATIO),
                int(font_size * self.DIALOG_MIN_HEIGHT_RATIO))

    def _on_preview_context_menu(self, pos):
        """Right-click anywhere in the preview dialog — offer Tiny mode
        + bilinear-filtering toggles. Both persist via QSettings so the
        choice survives restarts."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        tiny_act = menu.addAction("Tiny mode")
        tiny_act.setCheckable(True)
        tiny_act.setChecked(bool(getattr(self, "_preview_tiny_mode", False)))
        menu.addSeparator()
        bil_act = menu.addAction("Bilinear filter (smooth upscale)")
        bil_act.setCheckable(True)
        cur_bilinear = QSettings("DoxyEdit", "DoxyEdit").value(
            "preview_bilinear", True, type=bool)
        bil_act.setChecked(cur_bilinear)
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is tiny_act:
            self._preview_tiny_mode = not self._preview_tiny_mode
            QSettings("DoxyEdit", "DoxyEdit").setValue(
                "preview_tiny_mode", self._preview_tiny_mode)
            # Also hide / show the top info bar — tiny-mode reclaims
            # that whole strip instead of just letting the window
            # shrink behind it.
            if hasattr(self, "_info_bar_widget"):
                self._info_bar_widget.setVisible(not self._preview_tiny_mode)
            self._apply_preview_min_size()
        elif chosen is bil_act:
            new_val = not cur_bilinear
            QSettings("DoxyEdit", "DoxyEdit").setValue(
                "preview_bilinear", new_val)
            self._apply_preview_smoothing(new_val)

    def _preview_xform_mode(self):
        return _preview_xform_mode()

    def _apply_preview_smoothing(self, bilinear: bool):
        """Swap the QGraphicsView's render hints between smooth bilinear
        upscale and nearest-neighbor. Nearest gives true pixel ratio
        with no interpolation — the "pixel-art / exact-pixel inspect"
        mode the user asked for."""
        view = getattr(self, "view", None)
        if view is None:
            return
        view.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform, bilinear)
        for item in view.items():
            if hasattr(item, "setTransformationMode"):
                item.setTransformationMode(
                    Qt.TransformationMode.SmoothTransformation if bilinear
                    else Qt.TransformationMode.FastTransformation)
        view.viewport().update()

    def _toggle_fullscreen(self):
        if self._is_fullscreen:
            self.showNormal()
            self._is_fullscreen = False
        else:
            self.showFullScreen()
            self._is_fullscreen = True

    def _fit_to_view(self):
        fit_view_to_items(self.view, self.scene)

    def _wheel_zoom(self, event):
        wheel_zoom_view(self.view, event)

    def closeEvent(self, event):
        if self.parent():
            self.parent().removeEventFilter(self)
        settings = QSettings("DoxyEdit", "DoxyEdit")
        settings.setValue("preview_width", self.width())
        settings.setValue("preview_height", self.height())
        settings.setValue("preview_x", self.x())
        settings.setValue("preview_y", self.y())
        zoom = self.view.transform().m11()
        settings.setValue("preview_zoom", zoom)
        settings.sync()
        super().closeEvent(event)


class PreviewPane(QWidget):
    """Inline docked preview panel — embeddable in main window splitter."""

    navigated = Signal(str)  # asset_id when user navigates via arrow keys
    popout_requested = Signal()  # request to pop out to floating window
    studio_requested = Signal()  # open current asset in Studio

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("preview_pane")
        self._asset = None
        self._assets: list = []
        self._nav_index: int = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Compact info bar
        self._info_bar = QWidget()
        info_layout = QHBoxLayout(self._info_bar)
        _f = ui_font_size()
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)
        info_layout.setContentsMargins(_pad_lg, _pad, _pad_lg, _pad)
        self._info_label = QLabel()
        self._info_label.setObjectName("preview_info")
        info_layout.addWidget(self._info_label)
        info_layout.addStretch()
        self._fit_btn = QPushButton("Fit")
        self._fit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fit_btn.setToolTip("Fit image to view (Ctrl+0)")
        self._fit_btn.clicked.connect(self._fit_to_view)
        info_layout.addWidget(self._fit_btn)
        self._studio_btn = QPushButton("Studio")
        self._studio_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._studio_btn.setToolTip("Open this asset in Studio")
        self._studio_btn.clicked.connect(
            lambda: self.studio_requested.emit() if self._asset else None)
        info_layout.addWidget(self._studio_btn)
        self._popout_btn = QPushButton("Pop Out")
        self._popout_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._popout_btn.setToolTip("Open in floating preview window")
        self._popout_btn.clicked.connect(lambda: self.popout_requested.emit() if self._asset else None)
        info_layout.addWidget(self._popout_btn)

        # Graphics view via shared BaseImageViewer. Scene + view + pan
        # + wheel zoom + theme-aware background all come from there;
        # PreviewPane owns the info bar + navigation chrome on top.
        from doxyedit.imageviewer import BaseImageViewer
        _dt_pane = THEMES[DEFAULT_THEME]
        self._viewer = BaseImageViewer(self, theme=_dt_pane)
        # Keep the legacy attribute names so the rest of PreviewPane
        # (load_asset, keyPress, etc) doesn't need rewriting.
        self._scene = self._viewer.scene
        self._view = self._viewer.view
        layout.addWidget(self._viewer, 1)
        layout.addWidget(self._info_bar)

        self.setMinimumWidth(0)  # browse splitter handles collapsing

    def update_theme(self, theme):
        """Update QGraphicsScene background from theme (can't use QSS for scenes)."""
        self._viewer.set_theme(theme)

    def show_asset(self, asset, assets: list = None, index: int = 0):
        """Display an asset in the docked pane."""
        if assets is not None:
            self._assets = assets
            self._nav_index = index
        elif self._assets:
            # Update index if same list
            try:
                self._nav_index = next(
                    i for i, a in enumerate(self._assets) if a.id == asset.id)
            except StopIteration:
                self._nav_index = 0
        self._load_asset(asset)

    def _load_asset(self, asset):
        self._asset = asset
        pm, w, h = load_pixmap(asset.source_path)
        name = Path(asset.source_path).name
        self._info_label.setText(f"{name}  |  {w} x {h}")
        self._scene.clear()
        if not pm.isNull():
            item = QGraphicsPixmapItem(pm)
            item.setTransformationMode(_preview_xform_mode())
            self._scene.addItem(item)
            margin = max(w, h, 4000)
            self._scene.setSceneRect(
                QRectF(-margin, -margin, w + margin * 2, h + margin * 2))
            self._view.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)
            self._view.centerOn(item)


    def _fit_to_view(self):
        fit_view_to_items(self._view, self._scene)

    def _wheel_zoom(self, event):
        wheel_zoom_view(self._view, event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._copy_image_to_clipboard()
            return
        # Press S to jump current asset into Studio (matches the "Studio"
        # button on the info bar).
        if key == Qt.Key.Key_S and self._asset:
            self.studio_requested.emit()
            return
        if self._assets:
            # Arrow keys reserved for text fields. Space / Backspace step
            # through assets in the preview pane.
            if key == Qt.Key.Key_Space:
                self._navigate(1)
                return
            if key == Qt.Key.Key_Backspace:
                self._navigate(-1)
                return
        super().keyPressEvent(event)

    def _copy_image_to_clipboard(self):
        """Copy the current preview image to clipboard."""
        item = getattr(self, '_pixmap_item', None)
        if item and item.pixmap() and not item.pixmap().isNull():
            QApplication.clipboard().setPixmap(item.pixmap())
            if hasattr(self, '_hint_lbl'):
                self._hint_lbl.setText("Copied to clipboard")

    def _navigate(self, direction: int):
        if not self._assets:
            return
        self._nav_index = (self._nav_index + direction) % len(self._assets)
        asset = self._assets[self._nav_index]
        self._load_asset(asset)
        self.navigated.emit(asset.id)
