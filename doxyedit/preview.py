"""Image preview — hover tooltip, full preview with annotation notes."""
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsScene, QGraphicsView,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsTextItem,
    QApplication, QPushButton, QInputDialog, QWidget,
)
from PySide6.QtCore import Qt, QPoint, QRectF, QSettings, QPointF
from PySide6.QtGui import (
    QPixmap, QPainter, QFont, QColor, QKeySequence, QShortcut,
    QTransform, QPen, QBrush,
)

from doxyedit.imaging import load_pixmap


class HoverPreview(QWidget):
    """Floating preview that appears near the cursor on hover."""

    _instance = None
    PREVIEW_SIZE = 500

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(
            "HoverPreview { background: rgba(20,20,20,0.95); border: 2px solid rgba(128,128,128,0.3); border-radius: 6px; padding: 4px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._img_label)
        self._info_label = QLabel()
        self._info_label.setStyleSheet("color: rgba(200,200,200,0.8); font-size: 9px;")
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
    """A draggable note box with text label on the preview."""

    def __init__(self, rect: QRectF, text: str = ""):
        super().__init__(rect)
        self.setPen(QPen(QColor(190, 149, 92, 220), 3))
        self.setBrush(QBrush(QColor(190, 149, 92, 50)))
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
        )
        # Fixed font size — 18pt looks readable at all zoom levels
        self._text_item = QGraphicsTextItem(text, self)
        self._text_item.setDefaultTextColor(QColor(255, 240, 210, 240))
        self._text_item.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self._text_item.setPos(rect.x() + 8, rect.y() + 6)
        # Add a dark background behind text for readability
        self._bg = QGraphicsRectItem(self)
        self._bg.setBrush(QBrush(QColor(0, 0, 0, 140)))
        self._bg.setPen(QPen(Qt.PenStyle.NoPen))
        self._bg.setZValue(-1)
        self.text = text
        self._update_text_bg()

    def _update_text_bg(self):
        br = self._text_item.boundingRect()
        self._bg.setRect(
            self._text_item.x(), self._text_item.y(),
            br.width() + 8, br.height() + 4)

    def update_text(self, text: str):
        self.text = text
        self._text_item.setPlainText(text)
        self._update_text_bg()


class ImagePreviewDialog(QDialog):
    """Full image preview — zoomable, with annotation notes."""

    def __init__(self, image_path: str, asset=None, parent=None):
        super().__init__(parent)
        self._asset = asset
        self.setWindowTitle(f"Preview — {Path(image_path).name}")
        self.setMinimumSize(800, 600)
        settings = QSettings("DoxyEdit", "DoxyEdit")
        w_size = settings.value("preview_width", 1100, type=int)
        h_size = settings.value("preview_height", 800, type=int)
        self.resize(w_size, h_size)
        px = settings.value("preview_x", -1, type=int)
        py = settings.value("preview_y", -1, type=int)
        if px >= 0 and py >= 0:
            self.move(px, py)
        self.setStyleSheet("QDialog { background: rgba(20,20,20,0.95); }")

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
        info.setFont(QFont("Segoe UI", 11))
        info.setStyleSheet("color: rgba(200,200,200,0.8);")
        info_bar.addWidget(info)
        info_bar.addStretch()

        # Note button
        self._note_btn = QPushButton("Add Note")
        self._note_btn.setCheckable(True)
        self._note_btn.setStyleSheet(
            "QPushButton { padding: 4px 12px; }"
            "QPushButton:checked { background: rgba(190,149,92,0.5); }")
        self._note_btn.toggled.connect(self._toggle_note_mode)
        info_bar.addWidget(self._note_btn)

        self._view_notes_btn = QPushButton("View Notes")
        self._view_notes_btn.setCheckable(True)
        self._view_notes_btn.setChecked(True)
        self._view_notes_btn.setStyleSheet(
            "QPushButton { padding: 4px 12px; }"
            "QPushButton:checked { background: rgba(190,149,92,0.3); }")
        self._view_notes_btn.toggled.connect(self._toggle_view_notes)
        info_bar.addWidget(self._view_notes_btn)

        hint = QLabel("Scroll to zoom  |  Drag to pan  |  N = note  |  V = toggle  |  Esc = close")
        hint.setFont(QFont("Segoe UI", 9))
        hint.setStyleSheet("color: rgba(128,128,128,0.5);")
        info_bar.addWidget(hint)

        layout.addLayout(info_bar)

        # Zoomable view
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QColor("#111"))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setStyleSheet("border: none;")
        layout.addWidget(self.view)

        if not pm.isNull():
            item = QGraphicsPixmapItem(pm)
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.scene.addItem(item)
            self.scene.setSceneRect(QRectF(pm.rect()))

            saved_zoom = settings.value("preview_zoom", 0.0, type=float)
            if saved_zoom > 0:
                self.view.setTransform(QTransform.fromScale(saved_zoom, saved_zoom))
            else:
                self.view.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)

        # Override mouse events for annotation
        self.view.mousePressEvent = self._view_mouse_press
        self.view.mouseMoveEvent = self._view_mouse_move
        self.view.mouseReleaseEvent = self._view_mouse_release
        self.view.wheelEvent = self._wheel_zoom

        QShortcut(QKeySequence("Escape"), self, self.close)
        QShortcut(QKeySequence("Ctrl+0"), self, self._fit_to_view)
        QShortcut(QKeySequence("N"), self, lambda: self._note_btn.toggle())
        QShortcut(QKeySequence("V"), self, lambda: self._view_notes_btn.toggle())
        QShortcut(QKeySequence("Delete"), self, self._delete_selected_note)

        # Load existing annotations from asset notes
        self._load_saved_notes()

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
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.view.setCursor(Qt.CursorShape.ArrowCursor)

    def _view_mouse_press(self, event):
        if self._annotating and event.button() == Qt.MouseButton.LeftButton:
            self._draw_start = self.view.mapToScene(event.position().toPoint())
            self._temp_rect = NoteRectItem(QRectF(self._draw_start, self._draw_start), "")
            self.scene.addItem(self._temp_rect)
            return
        QGraphicsView.mousePressEvent(self.view, event)

    def _view_mouse_move(self, event):
        if self._annotating and self._draw_start and self._temp_rect:
            pos = self.view.mapToScene(event.position().toPoint())
            r = QRectF(self._draw_start, pos).normalized()
            self._temp_rect.setRect(r)
            self._temp_rect._text_item.setPos(r.x() + 4, r.y() + 2)
            return
        QGraphicsView.mouseMoveEvent(self.view, event)

    def _view_mouse_release(self, event):
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
            if isinstance(item, NoteRectItem):
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

    def _fit_to_view(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _wheel_zoom(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.view.scale(factor, factor)

    def closeEvent(self, event):
        settings = QSettings("DoxyEdit", "DoxyEdit")
        settings.setValue("preview_width", self.width())
        settings.setValue("preview_height", self.height())
        settings.setValue("preview_x", self.x())
        settings.setValue("preview_y", self.y())
        zoom = self.view.transform().m11()
        settings.setValue("preview_zoom", zoom)
        event.accept()
