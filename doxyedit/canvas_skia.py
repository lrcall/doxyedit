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
        # Day 3: image overlays. List of CanvasOverlay data objects;
        # paint iterates these after the base image. Per-path Skia
        # image cache keyed on image_path + cacheKey() to avoid
        # decoding the file on every paint.
        self._overlays: list = []
        self._overlay_image_cache: dict = {}  # path -> skia.Image
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
    # Overlays (Day 3: image overlays / watermarks)
    # ------------------------------------------------------------------

    def set_overlays(self, overlays: list):
        """Set the full overlay list. Replaces any previous list.

        Accepts CanvasOverlay dataclasses from doxyedit.models — the
        same objects used by the QGraphicsView path. No conversion
        needed; Skia reads type / image_path / x / y / opacity /
        rotation / blend_mode / enabled directly off the overlay.
        """
        self._overlays = list(overlays)
        self.update()

    def add_overlay(self, ov):
        self._overlays.append(ov)
        self.update()

    def remove_overlay(self, ov):
        try:
            self._overlays.remove(ov)
        except ValueError:
            pass
        self._overlay_image_cache.pop(getattr(ov, "image_path", ""), None)
        self.update()

    def _skia_image_for_overlay(self, ov):
        """Lazy-load and cache the skia.Image for an overlay's image_path."""
        path = getattr(ov, "image_path", "")
        if not path:
            return None
        img = self._overlay_image_cache.get(path)
        if img is not None:
            return img
        try:
            data = skia.Data.MakeFromFileName(str(path))
            if data is None:
                return None
            img = skia.Image.MakeFromEncoded(data)
            if img is None:
                return None
            self._overlay_image_cache[path] = img
            return img
        except Exception:
            return None

    # Blend-mode map: matches the QPainter CompositionMode map in
    # doxyedit/studio_items.py — so overlays composite identically
    # between the QGraphicsView path and Skia.
    _BLEND_MODE_SKIA = {
        "normal": None,  # default SourceOver — no explicit set needed
    }

    def _blend_mode_for(self, name: str):
        if not _SKIA_OK:
            return None
        # Lazy-init since skia.BlendMode enum constants are attributes
        # on the module and we want to keep import side-effect free.
        if name == "multiply":
            return skia.BlendMode.kMultiply
        if name == "screen":
            return skia.BlendMode.kScreen
        if name == "overlay":
            return skia.BlendMode.kOverlay
        if name == "darken":
            return skia.BlendMode.kDarken
        if name == "lighten":
            return skia.BlendMode.kLighten
        return None  # default kSrcOver for "normal" and unknowns

    def _draw_overlay_image(self, canvas, ov):
        """Render an image overlay (watermark / logo). Day-3 scope:
        position, scale, opacity, rotation, flip, blend mode. No
        per-pixel filter effects (grayscale / blur / brightness) yet —
        those arrive with Day 4 text + filter pipeline infrastructure.
        """
        img = self._skia_image_for_overlay(ov)
        if img is None:
            return
        if not getattr(ov, "enabled", True):
            return
        canvas.save()
        # Translate to overlay position.
        canvas.translate(float(ov.x), float(ov.y))
        # Rotate around center of the image rect.
        w, h = img.width(), img.height()
        rot = float(getattr(ov, "rotation", 0) or 0)
        if rot:
            canvas.translate(w / 2, h / 2)
            canvas.rotate(rot)
            canvas.translate(-w / 2, -h / 2)
        # Flip via negative scale.
        sx = -1.0 if getattr(ov, "flip_h", False) else 1.0
        sy = -1.0 if getattr(ov, "flip_v", False) else 1.0
        if sx < 0 or sy < 0:
            canvas.translate(w / 2, h / 2)
            canvas.scale(sx, sy)
            canvas.translate(-w / 2, -h / 2)
        # Scale. OverlayImageItem in QGraphicsView pre-scales the pixmap;
        # here we scale the canvas at draw time so the source image
        # stays un-mutated and the cache stays valid regardless of
        # scale slider changes.
        scale = float(getattr(ov, "scale", 1.0) or 1.0)
        if scale != 1.0 and self._base_image is not None:
            base_w = self._base_image.width()
            target_w = max(10, base_w * scale)
            s = target_w / max(1, w)
            canvas.scale(s, s)
        paint = skia.Paint()
        opacity = float(getattr(ov, "opacity", 1.0) or 1.0)
        # Skia takes alpha via paint.setAlpha(0..255).
        paint.setAlpha(max(0, min(255, int(opacity * 255))))
        mode = self._blend_mode_for(getattr(ov, "blend_mode", "normal") or "normal")
        if mode is not None:
            paint.setBlendMode(mode)
        canvas.drawImage(img, 0, 0, paint=paint)
        canvas.restore()

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
        """Draw the scene via Skia into self._qimg. Content order:
        background fill → base image → overlays in z-order → HUD.
        """
        canvas = self._surface.getCanvas()
        canvas.save()
        canvas.clear(skia.Color(32, 32, 40))
        # Apply pan + zoom.
        canvas.translate(self._pan_x, self._pan_y)
        canvas.scale(self._zoom, self._zoom)
        # Base image.
        if self._base_image is not None:
            paint = skia.Paint()
            canvas.drawImage(self._base_image, 0, 0, paint=paint)
        # Overlays (Day 3: image overlays only; text + shapes come Day 4/5).
        # Draw in list order — caller is responsible for z-order via
        # the order it passes to set_overlays().
        for ov in self._overlays:
            ov_type = getattr(ov, "type", "")
            if ov_type in ("watermark", "logo"):
                self._draw_overlay_image(canvas, ov)
            # text/shape/arrow come in future milestones
        canvas.restore()
        # HUD — always at screen pixels (no transform).
        hud_paint = skia.Paint()
        hud_paint.setColor(skia.Color(220, 220, 220, 200))
        hud_paint.setAntiAlias(True)
        font = skia.Font(skia.Typeface("Consolas"), 11)
        text = (f"SKIA backend  zoom={self._zoom:.2f}  "
                f"pan=({int(self._pan_x)},{int(self._pan_y)})  "
                f"overlays={len(self._overlays)}")
        canvas.drawString(text, 12, 20, font, hud_paint)
        # Flush so the bytes are in the QImage buffer before Qt blits.
        # With raster surfaces, flush() is effectively a no-op but kept
        # for parity with the GPU milestone.
        try:
            canvas.flush()
        except AttributeError:
            pass
