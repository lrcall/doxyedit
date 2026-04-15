"""Image preview — hover tooltip, full preview with annotation notes, crop tool."""
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsScene, QGraphicsView,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsPathItem, QGraphicsItem,
    QApplication, QPushButton, QInputDialog, QWidget, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Qt, QPoint, QRectF, QSettings, QPointF, Signal, QEvent, QTimer
from PySide6.QtGui import (
    QPixmap, QPainter, QFont, QColor, QKeySequence, QShortcut,
    QTransform, QPen, QBrush, QPainterPath,
)

from doxyedit.imaging import load_pixmap
from doxyedit.models import CropRegion, PLATFORMS


class HoverPreview(QWidget):
    """Floating preview that appears near the cursor on hover."""

    _instance = None
    PREVIEW_SIZE = 500

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("hover_preview")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
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
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        _nc = QColor(_dt.note_border)
        _nc.setAlpha(220)
        self.setPen(QPen(_nc, _dt.crop_border_width))
        _nf = QColor(_dt.note_border)
        _nf.setAlpha(50)
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
        painter.fillRect(bg, QColor(0, 0, 0, 160))
        painter.setPen(QColor(255, 240, 210, 240))
        painter.drawText(bg.adjusted(pad_x, pad_y, -pad_x, -pad_y), self.text)

        painter.restore()


class ResizableCropItem(QGraphicsRectItem):
    """Crop rectangle with 8 resize handles and drag-to-move."""

    HANDLE_SIZE = 14

    def __init__(self, rect: QRectF, label: str = "", aspect: float | None = None, parent=None):
        super().__init__(rect, parent)
        self.label = label
        self._aspect = aspect
        self._handle_dragging = -1  # which handle is being dragged (-1 = none)
        self._drag_start_rect = QRectF()
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        _cc = QColor(_dt.crop_border)
        _cc.setAlpha(220)
        self.setPen(QPen(_cc, _dt.crop_border_width))
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setZValue(101)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.on_changed = None  # callback when rect changes

    def paint(self, painter, option, widget=None):
        # Draw main rect
        painter.setPen(self.pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect())
        # Draw label
        if self.label:
            from doxyedit.themes import THEMES, DEFAULT_THEME
            _dt = THEMES[DEFAULT_THEME]
            _lc = QColor(_dt.crop_border)
            _lc.setAlpha(200)
            painter.setPen(_lc)
            font = painter.font()
            font.setPixelSize(_dt.font_size)
            painter.setFont(font)
            painter.drawText(self.rect().adjusted(6, 4, 0, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, self.label)
        # Draw handles if selected
        if self.isSelected():
            from doxyedit.themes import THEMES, DEFAULT_THEME
            _dt2 = THEMES[DEFAULT_THEME]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(_dt2.crop_border))
            for hr in self._handle_rects():
                painter.drawRect(hr)

    def _handle_rects(self) -> list[QRectF]:
        """Return 8 handle rects: TL, TC, TR, ML, MR, BL, BC, BR."""
        r = self.rect()
        s = self.HANDLE_SIZE
        hs = s / 2
        cx, cy = r.center().x(), r.center().y()
        return [
            QRectF(r.left() - hs, r.top() - hs, s, s),          # 0: TL
            QRectF(cx - hs, r.top() - hs, s, s),                 # 1: TC
            QRectF(r.right() - hs, r.top() - hs, s, s),          # 2: TR
            QRectF(r.left() - hs, cy - hs, s, s),                # 3: ML
            QRectF(r.right() - hs, cy - hs, s, s),               # 4: MR
            QRectF(r.left() - hs, r.bottom() - hs, s, s),        # 5: BL
            QRectF(cx - hs, r.bottom() - hs, s, s),              # 6: BC
            QRectF(r.right() - hs, r.bottom() - hs, s, s),       # 7: BR
        ]

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
        if self._handle_dragging >= 0:
            pos = event.pos()
            r = QRectF(self._drag_start_rect)
            h = self._handle_dragging
            # Resize based on which handle
            if h in (0, 3, 5):  # left handles
                r.setLeft(pos.x())
            if h in (2, 4, 7):  # right handles
                r.setRight(pos.x())
            if h in (0, 1, 2):  # top handles
                r.setTop(pos.y())
            if h in (5, 6, 7):  # bottom handles
                r.setBottom(pos.y())
            # Normalize (swap if inverted)
            r = r.normalized()
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
        """Return current bounds as a CropRegion."""
        r = self.rect().translated(self.pos())
        return CropRegion(x=int(r.x()), y=int(r.y()), w=int(r.width()), h=int(r.height()), label=self.label)


class ImagePreviewDialog(QDialog):
    """Full image preview — zoomable, with annotation notes and prev/next navigation."""

    navigated = Signal(str)   # emitted with asset_id when user navigates to a different asset
    dock_requested = Signal()  # emitted when user clicks the Dock button

    DIALOG_MIN_WIDTH_RATIO = 66.7      # preview dialog minimum width
    DIALOG_MIN_HEIGHT_RATIO = 50.0     # preview dialog minimum height

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
        self.setMinimumSize(int(_f * self.DIALOG_MIN_WIDTH_RATIO),
                            int(_f * self.DIALOG_MIN_HEIGHT_RATIO))
        _cb = max(14, _f + 2)
        w_size = settings.value("preview_width", 1100, type=int)
        h_size = settings.value("preview_height", 800, type=int)
        self.resize(w_size, h_size)
        px = settings.value("preview_x", -1, type=int)
        py = settings.value("preview_y", -1, type=int)
        if px >= 0 and py >= 0:
            # Validate position is on a connected screen
            from PySide6.QtCore import QPoint
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
        info_bar.setContentsMargins(12, 8, 12, 4)

        pm, w, h = load_pixmap(image_path)
        name = Path(image_path).name
        ratio = f"{w/h:.2f}" if h else "?"

        info = QLabel(f"{name}  |  {w} x {h}  |  ratio {ratio}")
        info.setObjectName("preview_info")
        info_bar.addWidget(info)
        info_bar.addStretch()

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

        self._fs_btn = QPushButton("⛶")
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

        # Zoomable view
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QColor(_dt.bg_deep))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # Allow panning beyond the image edges
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.view)

        self._pixmap_item = None
        if not pm.isNull():
            self._pixmap_item = QGraphicsPixmapItem(pm)
            self._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
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

        # Navigation keys — intercept before any child widget
        if event.type() == QEvent.Type.KeyPress and self._assets:
            key = event.key()
            if key in (Qt.Key.Key_Space, Qt.Key.Key_Right, Qt.Key.Key_Tab,
                       Qt.Key.Key_Down):
                self._navigate(1)
                return True
            if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Left, Qt.Key.Key_Up):
                self._navigate(-1)
                return True
        return super().eventFilter(obj, event)

    def _load_saved_notes(self):
        """Parse annotation notes from asset.notes and display them."""
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
        self._crop_mask_item.setBrush(QBrush(QColor(0, 0, 0, 140)))
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
            from doxyedit.themes import THEMES, DEFAULT_THEME
            _dt = THEMES[DEFAULT_THEME]
            _cc = QColor(_dt.crop_border); _cc.setAlpha(220)
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
                dlg.resize(500, 140)
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
            self._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
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

    def _toggle_fullscreen(self):
        if self._is_fullscreen:
            self.showNormal()
            self._is_fullscreen = False
        else:
            self.showFullScreen()
            self._is_fullscreen = True

    def _fit_to_view(self):
        items = self.scene.items()
        if items:
            self.view.fitInView(items[-1], Qt.AspectRatioMode.KeepAspectRatio)

    def _wheel_zoom(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.view.scale(factor, factor)

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
        info_layout.setContentsMargins(8, 4, 8, 4)
        self._info_label = QLabel()
        self._info_label.setObjectName("preview_info")
        info_layout.addWidget(self._info_label)
        info_layout.addStretch()
        self._fit_btn = QPushButton("Fit")
        self._fit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fit_btn.setToolTip("Fit image to view (Ctrl+0)")
        self._fit_btn.clicked.connect(self._fit_to_view)
        info_layout.addWidget(self._fit_btn)
        self._popout_btn = QPushButton("Pop Out")
        self._popout_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._popout_btn.setToolTip("Open in floating preview window")
        self._popout_btn.clicked.connect(lambda: self.popout_requested.emit() if self._asset else None)
        info_layout.addWidget(self._popout_btn)
        layout.addWidget(self._info_bar)

        # Graphics view
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt_pane = THEMES[DEFAULT_THEME]
        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(QColor(_dt_pane.bg_deep))
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.wheelEvent = self._wheel_zoom
        layout.addWidget(self._view)

        from PySide6.QtCore import QSettings
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        PANE_MIN_WIDTH_RATIO = 16.7        # preview pane minimum width
        self.setMinimumWidth(int(_f * PANE_MIN_WIDTH_RATIO))

    def update_theme(self, theme):
        """Update QGraphicsScene background from theme (can't use QSS for scenes)."""
        self._scene.setBackgroundBrush(QColor(theme.bg_deep))

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
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self._scene.addItem(item)
            margin = max(w, h, 4000)
            self._scene.setSceneRect(
                QRectF(-margin, -margin, w + margin * 2, h + margin * 2))
            self._view.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)
            self._view.centerOn(item)


    def _fit_to_view(self):
        items = self._scene.items()
        if items:
            self._view.fitInView(items[-1], Qt.AspectRatioMode.KeepAspectRatio)

    def _wheel_zoom(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self._view.scale(factor, factor)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._copy_image_to_clipboard()
            return
        if self._assets:
            if key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space):
                self._navigate(1)
                return
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backspace):
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
