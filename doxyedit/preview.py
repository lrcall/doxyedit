"""Image preview — hover tooltip and full-screen preview dialog."""
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QGraphicsScene, QGraphicsView,
    QGraphicsPixmapItem, QPushButton, QHBoxLayout, QApplication,
)
from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QRectF
from PySide6.QtGui import QPixmap, QPainter, QFont, QColor, QKeySequence, QShortcut


class HoverPreview(QLabel):
    """Floating preview that appears near the cursor on hover."""

    _instance = None  # singleton — only one hover preview at a time

    PREVIEW_SIZE = 500  # at least 3x typical 160px thumb

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
        pm = QPixmap(image_path)
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

        # Position to the right of cursor, or left if near screen edge
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
        self.resize(1100, 800)
        self.setStyleSheet("QDialog { background: #111; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Info bar
        info_bar = QHBoxLayout()
        info_bar.setContentsMargins(12, 8, 12, 4)

        pm = QPixmap(image_path)
        name = Path(image_path).name
        w, h = pm.width(), pm.height()
        ratio = f"{w/h:.2f}" if h else "?"

        info = QLabel(f"{name}  |  {w} x {h}  |  ratio {ratio}")
        info.setFont(QFont("Segoe UI", 11))
        info.setStyleSheet("color: #aaa;")
        info_bar.addWidget(info)
        info_bar.addStretch()

        hint = QLabel("Scroll to zoom  |  Middle-click to pan  |  Esc to close")
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
            self.view.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)

        # Override wheel for zoom
        self.view.wheelEvent = self._wheel_zoom

        # Esc to close
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _wheel_zoom(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.view.scale(factor, factor)
