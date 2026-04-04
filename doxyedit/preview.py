"""Image preview — hover tooltip and full-screen preview dialog."""
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QGraphicsScene, QGraphicsView,
    QGraphicsPixmapItem, QHBoxLayout, QApplication,
)
from PySide6.QtCore import Qt, QPoint, QRectF, QSettings
from PySide6.QtGui import QPixmap, QPainter, QFont, QColor, QKeySequence, QShortcut, QTransform

from doxyedit.imaging import load_pixmap


class HoverPreview(QLabel):
    """Floating preview that appears near the cursor on hover."""

    _instance = None
    PREVIEW_SIZE = 500

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet(
            "QLabel { background: #1a1a1a; border: 2px solid #444; border-radius: 6px; padding: 4px; }"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        pm, _, _ = load_pixmap(image_path)
        if pm.isNull():
            self.hide()
            return
        pm = pm.scaled(
            self.PREVIEW_SIZE, self.PREVIEW_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pm)
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


class ImagePreviewDialog(QDialog):
    """Full image preview — zoomable, opened on double-click."""

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Preview — {Path(image_path).name}")
        self.setMinimumSize(800, 600)
        settings = QSettings("DoxyEdit", "DoxyEdit")
        w_size = settings.value("preview_width", 1100, type=int)
        h_size = settings.value("preview_height", 800, type=int)
        self.resize(w_size, h_size)
        self.setStyleSheet("QDialog { background: #111; }")

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
        info.setStyleSheet("color: #aaa;")
        info_bar.addWidget(info)
        info_bar.addStretch()

        hint = QLabel("Scroll to zoom  |  Drag to pan  |  Esc to close")
        hint.setFont(QFont("Segoe UI", 9))
        hint.setStyleSheet("color: #555;")
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

            # Restore last zoom level, or fit to view on first use
            saved_zoom = settings.value("preview_zoom", 0.0, type=float)
            if saved_zoom > 0:
                self.view.setTransform(QTransform.fromScale(saved_zoom, saved_zoom))
            else:
                self.view.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)

        self.view.wheelEvent = self._wheel_zoom
        QShortcut(QKeySequence("Escape"), self, self.close)
        QShortcut(QKeySequence("Ctrl+0"), self, self._fit_to_view)

    def _fit_to_view(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _wheel_zoom(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.view.scale(factor, factor)

    def closeEvent(self, event):
        settings = QSettings("DoxyEdit", "DoxyEdit")
        settings.setValue("preview_width", self.width())
        settings.setValue("preview_height", self.height())
        zoom = self.view.transform().m11()
        settings.setValue("preview_zoom", zoom)
        event.accept()
