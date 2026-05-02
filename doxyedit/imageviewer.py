"""Shared image viewer widget.

A single QGraphicsView + QGraphicsScene wrapper that handles the
mechanics every preview pane in the app needs:

- set_pixmap(QPixmap) or set_path(path)
- fit-to-view + manual wheel zoom
- pan via ScrollHandDrag
- theme-aware scene background
- transformation mode driven by the user's preview_bilinear setting

Domain-specific UI (info bars, navigation buttons, crop tool, notes)
goes in subclasses or wrapper widgets that own a BaseImageViewer
instance. Keep this file shell-only — no posting, no annotation, no
asset model coupling.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QSettings, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QSizePolicy, QWidget,
    QVBoxLayout,
)

from doxyedit.themes import THEMES, DEFAULT_THEME


def _xform_mode():
    """Mirror preview._preview_xform_mode without importing it.
    Returns the QGraphicsPixmapItem.TransformationMode the user
    last chose for previews. Cached only via QSettings."""
    bilinear = QSettings("DoxyEdit", "DoxyEdit").value(
        "preview_bilinear", True, type=bool)
    return (
        Qt.TransformationMode.SmoothTransformation
        if bilinear
        else Qt.TransformationMode.FastTransformation
    )


class BaseImageViewer(QWidget):
    """Generic pan/zoom image viewer. Holds one pixmap item.

    Subclasses or wrapper widgets are responsible for any chrome
    (info bar, navigation, crop tool, etc); this class is intentionally
    just the canvas.
    """

    pixmap_loaded = Signal(QPixmap)  # emits after a successful set_pixmap
    pixmap_failed = Signal(str)       # emits the failing path on load error

    def __init__(self, parent: QWidget | None = None,
                 *, theme=None) -> None:
        super().__init__(parent)
        self.setObjectName("base_image_viewer")
        if theme is None:
            theme = THEMES[DEFAULT_THEME]
        self._theme = theme
        self._pixmap_item: QGraphicsPixmapItem | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(QColor(theme.bg_deep))
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Wheel zoom routed through the central helper so every viewer
        # in the app has the same feel.
        self._view.wheelEvent = self._wheel_zoom
        layout.addWidget(self._view, 1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def view(self) -> QGraphicsView:
        return self._view

    @property
    def scene(self) -> QGraphicsScene:
        return self._scene

    def set_theme(self, theme) -> None:
        """Update scene background color from a Theme object. QSS
        cannot reach QGraphicsScene, so callers re-bind here on theme
        change just like the existing PreviewPane.update_theme."""
        self._theme = theme
        self._scene.setBackgroundBrush(QColor(theme.bg_deep))

    def set_pixmap(self, pix: QPixmap) -> None:
        """Replace the displayed pixmap. fit_to_view is left to the
        caller so it can decide whether to keep the current zoom."""
        self._scene.clear()
        if pix.isNull():
            self._pixmap_item = None
            self.pixmap_failed.emit("")
            return
        item = QGraphicsPixmapItem(pix)
        item.setTransformationMode(_xform_mode())
        self._scene.addItem(item)
        self._scene.setSceneRect(QRectF(pix.rect()))
        self._pixmap_item = item
        self.pixmap_loaded.emit(pix)

    def set_path(self, path: str | Path) -> None:
        """Convenience: load a file path. Skips load_pixmap on missing
        files (emits pixmap_failed) so callers can surface a status."""
        p = Path(path) if path else None
        if not p or not p.exists():
            self.pixmap_failed.emit(str(path))
            return
        # Use the existing imaging.load_pixmap pipeline for PSD / SAI
        # support, falling back to QPixmap for ordinary files.
        try:
            from doxyedit.imaging import load_pixmap
            pix = load_pixmap(str(p))
        except Exception:
            pix = QPixmap(str(p))
        if pix is None or pix.isNull():
            self.pixmap_failed.emit(str(p))
            return
        self.set_pixmap(pix)

    def clear(self) -> None:
        """Drop the current pixmap and reset the scene."""
        self._scene.clear()
        self._pixmap_item = None

    def fit_to_view(self) -> None:
        """Fit the pixmap into the viewport, preserving aspect ratio."""
        if self._pixmap_item is not None:
            self._view.fitInView(
                self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _wheel_zoom(self, event) -> None:
        from doxyedit.preview import wheel_zoom_view
        wheel_zoom_view(self._view, event)
