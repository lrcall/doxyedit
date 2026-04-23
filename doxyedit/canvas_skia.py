"""Skia-backed Studio canvas (Option D from canvas-architecture-deep-dive.md).

Day-1 milestone: minimal CanvasSkia widget that:
- Initializes a Skia Surface wrapping a QImage buffer.
- Paints a solid background + a "Skia active" indicator so we can
  visually confirm the backend is live.
- Exposes set_base_image(path) and paint via QPainter.drawImage.

This is NOT the final rendering path. The final path will use Skia's
GPU backend via GrDirectContext.MakeGL() bound to a QOpenGLWidget's
context. For Day 1 we prove the bundle works and that Skia can draw
into a QImage that Qt displays — the simplest possible end-to-end.

Subsequent milestones:
- Day 2: GPU backend via GrDirectContext + QOpenGLWidget viewport.
- Day 3: OverlayImageItem equivalent (Skia drawImage with blend modes).
- Day 4: OverlayTextItem equivalent (Skia native text with stroke/shadow).
- Day 5: OverlayShapeItem / bubbles (SkPath).
- ... (see docs/canvas-architecture-deep-dive.md Section 2D)

Feature-flag: studio_compositor = "skia" to use this path.
Default is "qgraphics". Fallback to QGraphicsView on any init failure.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QSize
from PySide6.QtGui import QPainter, QImage, QColor, QFont
from PySide6.QtWidgets import QWidget


# Module-level guard so we can detect-and-fallback cleanly.
try:
    import skia  # type: ignore
    _SKIA_OK = True
    _SKIA_ERR = None
except Exception as e:  # pragma: no cover
    skia = None  # type: ignore
    _SKIA_OK = False
    _SKIA_ERR = str(e)


def skia_available() -> bool:
    """Return True if skia-python imported and passes a minimal smoke test.
    Callers should check this BEFORE instantiating CanvasSkia."""
    if not _SKIA_OK:
        return False
    try:
        # Minimal surface allocation to prove the runtime works.
        s = skia.Surface(4, 4)
        s.getCanvas().clear(skia.ColorTRANSPARENT)
        s.makeImageSnapshot()
        return True
    except Exception:
        return False


def skia_error() -> str:
    return _SKIA_ERR or ""


class CanvasSkia(QWidget):
    """Skia-backed canvas widget. Day 1: raster compositor via QImage buffer.

    Renders through a skia.Surface that wraps a QImage's bit buffer, then
    blits the QImage to the widget via QPainter.drawImage in paintEvent.
    This path is CPU-side but proves every link in the pipeline (skia
    install, canvas draw, pixel handoff to Qt) before we tackle the GPU
    path on Day 2.
    """

    # Same signal surface as QGraphicsView so StudioEditor can swap in.
    # Additional signals added per-milestone.
    geometry_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studio_canvas_skia")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMouseTracking(True)
        # RGBA premultiplied is Skia's and Qt's canonical format for
        # painter-composited surfaces — no per-blit conversion cost.
        self._qimg: QImage | None = None
        self._surface = None
        self._base_image: "skia.Image | None" = None  # type: ignore
        # Pan/zoom state — minimal so resize + pan work for milestone 1.
        self._zoom: float = 1.0
        self._pan_x: float = 0.0
        self._pan_y: float = 0.0
        self._resize_buffers(self.size())
        # Record whether Skia is live; surfacing this to the editor lets
        # the FPS HUD show which backend is active.
        self.backend_name = "skia" if skia_available() else "fallback"
        self.resize(640, 480)

    # ------------------------------------------------------------------
    # Buffer management
    # ------------------------------------------------------------------

    def _resize_buffers(self, size: QSize):
        w = max(1, int(size.width()))
        h = max(1, int(size.height()))
        self._qimg = QImage(w, h, QImage.Format.Format_RGBA8888_Premultiplied)
        self._qimg.fill(Qt.GlobalColor.transparent)
        if _SKIA_OK:
            info = skia.ImageInfo.Make(
                w, h,
                skia.ColorType.kRGBA_8888_ColorType,
                skia.AlphaType.kPremul_AlphaType,
            )
            # Wrap the QImage bits directly — Skia paints into Qt's buffer.
            ptr = int(self._qimg.bits())
            self._surface = skia.Surface.MakeRasterDirect(
                info, ptr, self._qimg.bytesPerLine())

    def resizeEvent(self, event):
        self._resize_buffers(event.size())
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # Base image
    # ------------------------------------------------------------------

    def set_base_image_path(self, path: str):
        """Load an image from disk into a Skia cached image handle."""
        if not _SKIA_OK:
            return
        try:
            data = skia.Data.MakeFromFileName(str(path))
            if data is None:
                return
            self._base_image = skia.Image.MakeFromEncoded(data)
        except Exception:
            self._base_image = None
        self.update()

    def base_size(self) -> QSize:
        if self._base_image is None:
            return QSize(0, 0)
        return QSize(self._base_image.width(), self._base_image.height())

    # ------------------------------------------------------------------
    # View transform (panning / zooming)
    # ------------------------------------------------------------------

    def set_zoom(self, z: float):
        self._zoom = max(0.05, min(32.0, z))
        self.update()

    def zoom(self) -> float:
        return self._zoom

    def pan_by(self, dx: float, dy: float):
        self._pan_x += dx
        self._pan_y += dy
        self.update()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._qimg is None:
            return
        if _SKIA_OK and self._surface is not None:
            self._render_to_skia()
        else:
            # Fallback path: clear to a recognizable shade + error text.
            self._qimg.fill(QColor(50, 30, 30))
            p2 = QPainter(self._qimg)
            p2.setPen(QColor(255, 200, 200))
            p2.setFont(QFont("Consolas", 10))
            p2.drawText(
                QRectF(10, 10, self._qimg.width() - 20, 40),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                f"skia-python unavailable: {_SKIA_ERR or 'unknown'}")
            p2.end()
        painter.drawImage(0, 0, self._qimg)

    def _render_to_skia(self):
        """Draw the scene via Skia into self._qimg. Day-1 content:
        gradient background, base image centered, and an HUD string
        confirming the backend is live."""
        canvas = self._surface.getCanvas()
        # Clear with a subtle gradient so the transition from
        # QGraphicsView -> Skia is visually obvious during testing.
        canvas.save()
        canvas.clear(skia.Color(32, 32, 40))
        # Apply pan + zoom.
        canvas.translate(self._pan_x, self._pan_y)
        canvas.scale(self._zoom, self._zoom)
        # Draw base image if loaded.
        if self._base_image is not None:
            paint = skia.Paint()
            canvas.drawImage(self._base_image, 0, 0, paint=paint)
        canvas.restore()
        # HUD — always at screen pixels (no transform).
        hud_paint = skia.Paint()
        hud_paint.setColor(skia.Color(220, 220, 220, 200))
        hud_paint.setAntiAlias(True)
        font = skia.Font(skia.Typeface("Consolas"), 11)
        text = f"SKIA backend  zoom={self._zoom:.2f}  pan=({int(self._pan_x)},{int(self._pan_y)})"
        canvas.drawString(text, 12, 20, font, hud_paint)
        # Flush so the bytes are in the QImage buffer before Qt blits.
        # With raster surfaces, flush() is effectively a no-op but kept
        # for parity with the GPU milestone.
        try:
            canvas.flush()
        except AttributeError:
            pass
