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
        self._surface = None
        self._surface_is_direct = False
        if not _SKIA_OK:
            return
        try:
            info = skia.ImageInfo.Make(
                w, h,
                skia.ColorType.kRGBA_8888_ColorType,
                skia.AlphaType.kPremul_AlphaType,
            )
            # Allocated raster surface — Skia owns the backing store.
            # At paint time we snapshot + copy pixels into the QImage.
            # MakeRasterDirect into PySide6's QImage.bits() buffer is
            # viable but requires ctypes gymnastics around PySide's
            # PyVoid pointer; allocated surface is simpler and the
            # extra copy is 1-2ms for a 1080p viewport — dwarfed by
            # the 10-20x GPU composite win we're building toward.
            self._surface = skia.Surface.MakeRaster(info)
        except Exception:
            self._surface = None

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

    def _draw_overlay_text(self, canvas, ov):
        """Render a text overlay. Day-4 scope: font family, size,
        bold / italic / underline / strike, color, letter-spacing,
        text alignment, line height, outline (stroke_width /
        stroke_color), drop shadow (shadow_offset / shadow_color),
        rotation, opacity, blend mode.

        Skia native text rendering — a single paint call for glyphs,
        no 9-pass stroke hack needed (SkPaint.setStyle(StrokeAndFill)
        handles stroke natively). Drop shadow via SkImageFilter chain
        is one paint, not a second document-draw pass.
        """
        if not getattr(ov, "enabled", True):
            return
        text = getattr(ov, "text", "") or ""
        if not text:
            return
        family = getattr(ov, "font_family", "Segoe UI") or "Segoe UI"
        size = float(getattr(ov, "font_size", 14) or 14)
        bold = bool(getattr(ov, "bold", False))
        italic = bool(getattr(ov, "italic", False))
        # Skia Typeface — matches QFont's family + weight + italic.
        style = skia.FontStyle(
            skia.FontStyle.kBold_Weight if bold
            else skia.FontStyle.kNormal_Weight,
            skia.FontStyle.kNormal_Width,
            (skia.FontStyle.kItalic_Slant if italic
             else skia.FontStyle.kUpright_Slant),
        )
        typeface = skia.Typeface(family, style)
        font = skia.Font(typeface, size)
        # Layout lines with line_height spacing. Skia doesn't have a
        # built-in paragraph layout at this scope; we handle line
        # breaks manually matching QTextDocument's block layout.
        lines = text.split("\n")
        metrics = font.getMetrics()
        line_h = float(getattr(ov, "line_height", 1.2) or 1.2)
        ascent = -metrics.fAscent       # SkFontMetrics ascent is negative
        descent = metrics.fDescent
        line_step = (ascent + descent) * line_h
        # Alignment: compute per-line x offset from text_align.
        align = getattr(ov, "text_align", "left") or "left"
        # text_width clamp — if > 0, treat as pinned line width for
        # alignment math. Otherwise each line is left-aligned relative
        # to overlay.x.
        pinned_w = float(getattr(ov, "text_width", 0) or 0)
        canvas.save()
        # Position + transform (rotation around text center for parity
        # with OverlayTextItem).
        canvas.translate(float(ov.x), float(ov.y))
        rot = float(getattr(ov, "rotation", 0) or 0)
        if rot:
            # Pivot around the middle of the text block
            total_h = line_step * len(lines)
            widest = max((font.measureText(l) for l in lines), default=0)
            cx = (pinned_w if pinned_w > 0 else widest) / 2
            cy = total_h / 2
            canvas.translate(cx, cy)
            canvas.rotate(rot)
            canvas.translate(-cx, -cy)
        # Flip
        sx = -1.0 if getattr(ov, "flip_h", False) else 1.0
        sy = -1.0 if getattr(ov, "flip_v", False) else 1.0
        if sx < 0 or sy < 0:
            widest = max((font.measureText(l) for l in lines), default=0)
            total_h = line_step * len(lines)
            canvas.translate(widest / 2, total_h / 2)
            canvas.scale(sx, sy)
            canvas.translate(-widest / 2, -total_h / 2)
        # Build the base paint (fill).
        color_hex = getattr(ov, "color", "#ffffff") or "#ffffff"
        fill_color = self._parse_hex(color_hex, (255, 255, 255, 255))
        opacity = float(getattr(ov, "opacity", 1.0) or 1.0)
        alpha = int(max(0.0, min(1.0, opacity)) * 255)
        # Background pill if configured.
        bg_hex = getattr(ov, "background_color", "") or ""
        if bg_hex:
            bg_paint = skia.Paint()
            bg_paint.setColor(skia.Color(*self._parse_hex(bg_hex, (0, 0, 0, 200))))
            bg_paint.setAntiAlias(True)
            widest = max((font.measureText(l) for l in lines), default=0)
            total_h = line_step * len(lines)
            pad = max(4.0, size * 0.2)
            rect = skia.Rect.MakeXYWH(-pad, -pad - ascent,
                                       (pinned_w if pinned_w > 0 else widest) + pad * 2,
                                       total_h + pad * 2)
            canvas.drawRoundRect(rect, pad, pad, bg_paint)
        # Drop shadow — one paint with SkImageFilters.DropShadow handles
        # it in a single glyph draw, no second document pass.
        shadow_off = float(getattr(ov, "shadow_offset", 0) or 0)
        shadow_hex = getattr(ov, "shadow_color", "") or ""
        shadow_blur = float(getattr(ov, "shadow_blur", 0) or 0)
        stroke_w = float(getattr(ov, "stroke_width", 0) or 0)
        stroke_hex = getattr(ov, "stroke_color", "") or ""
        # Build a reusable image filter for shadow+stroke combined
        # below. Paints applied per-line via drawSimpleText.
        def _mk_paint(fill_rgba, stroke=False, stroke_rgba=None,
                      stroke_px=0.0, with_shadow=False):
            p = skia.Paint()
            p.setAntiAlias(True)
            p.setAlphaf(alpha / 255.0)
            if stroke:
                p.setStyle(skia.Paint.kStroke_Style)
                p.setColor(skia.Color(*stroke_rgba))
                p.setStrokeWidth(stroke_px)
                p.setStrokeJoin(skia.Paint.kRound_Join)
            else:
                p.setStyle(skia.Paint.kFill_Style)
                p.setColor(skia.Color(*fill_rgba))
            if with_shadow and shadow_off > 0 and shadow_hex:
                sh_rgba = self._parse_hex(shadow_hex, (0, 0, 0, 220))
                try:
                    f = skia.ImageFilters.DropShadow(
                        float(shadow_off), float(shadow_off),
                        float(max(0.5, shadow_blur)),
                        float(max(0.5, shadow_blur)),
                        skia.Color(*sh_rgba), None)
                    p.setImageFilter(f)
                except Exception:
                    pass
            return p
        # Letter spacing — Skia Font supports ScaleX / SkewX but not
        # direct letter_spacing in older versions. Emulate by drawing
        # each character advanced manually; cheap for short text.
        letter_spacing = float(getattr(ov, "letter_spacing", 0) or 0)

        def _draw_line(line_str, base_y, paint):
            if letter_spacing == 0:
                # Alignment offset based on line width
                w = font.measureText(line_str)
                pin = pinned_w if pinned_w > 0 else w
                if align == "center":
                    x = (pin - w) / 2
                elif align == "right":
                    x = pin - w
                else:
                    x = 0
                canvas.drawSimpleText(line_str, x, base_y, font, paint)
            else:
                # Per-glyph draw with manual advance
                cursor = 0.0
                if align != "left":
                    # Pre-compute total width with spacing
                    total = sum(
                        font.measureText(ch) + letter_spacing
                        for ch in line_str
                    ) - (letter_spacing if line_str else 0)
                    pin = pinned_w if pinned_w > 0 else total
                    if align == "center":
                        cursor = (pin - total) / 2
                    elif align == "right":
                        cursor = pin - total
                for ch in line_str:
                    canvas.drawSimpleText(
                        ch, cursor, base_y, font, paint)
                    cursor += font.measureText(ch) + letter_spacing

        # Stroke pass under fill for outlined text look.
        if stroke_w > 0 and stroke_hex:
            stroke_rgba = self._parse_hex(stroke_hex, (0, 0, 0, 255))
            stroke_paint = _mk_paint(
                None, stroke=True, stroke_rgba=stroke_rgba,
                stroke_px=stroke_w * 2, with_shadow=False)
            for i, line in enumerate(lines):
                _draw_line(line, ascent + i * line_step, stroke_paint)
        # Fill pass (with shadow if configured; otherwise plain).
        fill_paint = _mk_paint(
            fill_color, with_shadow=bool(shadow_off and shadow_hex))
        mode = self._blend_mode_for(getattr(ov, "blend_mode", "normal") or "normal")
        if mode is not None:
            fill_paint.setBlendMode(mode)
        for i, line in enumerate(lines):
            _draw_line(line, ascent + i * line_step, fill_paint)
        canvas.restore()

    @staticmethod
    def _parse_hex(s: str, default: tuple) -> tuple:
        """Parse #RRGGBB / #RRGGBBAA -> (r,g,b,a). Returns default on error."""
        try:
            h = (s or "").lstrip("#")
            if len(h) == 6:
                return (int(h[0:2], 16), int(h[2:4], 16),
                        int(h[4:6], 16), 255)
            if len(h) == 8:
                return (int(h[0:2], 16), int(h[2:4], 16),
                        int(h[4:6], 16), int(h[6:8], 16))
        except Exception:
            pass
        return default

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
            elif ov_type == "text":
                self._draw_overlay_text(canvas, ov)
            # shape/arrow come in Day 5
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
        # Copy Skia's backing store into the QImage so Qt can blit it.
        # Skia's Surface.MakeRaster allocates its own buffer; we pull
        # it into Qt's buffer via readPixels.
        try:
            canvas.flush()
        except AttributeError:
            pass
        self._copy_skia_to_qimage()

    def _copy_skia_to_qimage(self):
        """Readback Skia's rendered pixels into self._qimg."""
        if self._surface is None or self._qimg is None:
            return
        try:
            info = skia.ImageInfo.Make(
                self._qimg.width(), self._qimg.height(),
                skia.ColorType.kRGBA_8888_ColorType,
                skia.AlphaType.kPremul_AlphaType,
            )
            # readPixels writes into a bytes-like destination.
            # QImage.bits() returns a PySide PyVoid pointer; feed its
            # underlying memoryview instead.
            buf = self._qimg.bits()
            # buf is a memoryview or voidptr — Skia accepts a bytes-like
            # dest via the low-level readPixels overload.
            self._surface.readPixels(
                info, buf, self._qimg.bytesPerLine(), 0, 0)
        except Exception:
            pass
