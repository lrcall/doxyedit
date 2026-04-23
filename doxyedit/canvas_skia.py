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
import bisect
import functools
import json
import math

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


@functools.lru_cache(maxsize=256)
def _parse_hex_cached(s: str):
    """Memoised #RRGGBB / #RRGGBBAA parser. Returns (r,g,b,a) or None on
    bad input. Separate from CanvasSkia._parse_hex because lru_cache
    can't wrap a staticmethod cleanly AND we want the cache shared
    across every canvas instance (colors repeat — same palette used
    on many overlays)."""
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
    return None


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
        self._panning: bool = False
        self._pan_start: QPointF = QPointF(0, 0)
        # Day 3: image overlays. List of CanvasOverlay data objects;
        # paint iterates these after the base image. Per-path Skia
        # image cache keyed on image_path + cacheKey() to avoid
        # decoding the file on every paint.
        self._overlays: list = []
        self._overlay_image_cache: dict = {}  # path -> skia.Image
        # Typeface / Font caches — the OS font lookup + Skia typeface
        # creation is 50-500us per call depending on the font. Without
        # caching, every paint builds a fresh Typeface + Font for EACH
        # text overlay, scaling linearly with overlay count. With a cache
        # it's a dict lookup after warm-up.
        # Key: (family, bold, italic) -> skia.Typeface
        self._skia_typeface_cache: dict = {}
        # Key: (typeface_id, size) -> skia.Font
        self._skia_font_cache: dict = {}
        # Shape path cache: key id(overlay) -> (fingerprint, skia.Path).
        # _build_shape_path compares the overlay's current geometry
        # fingerprint against the cached one; hit on match, rebuild on
        # miss. Keyed on id() not the overlay itself so dict doesn't
        # hold the overlay alive (the overlay is owned by the Asset
        # model which owns the canvas).
        self._skia_path_cache: dict = {}
        # Dash-effect cache: key = intervals tuple -> SkDashPathEffect.
        # Pre-allocated here so _get_dash_effect can skip the first-call
        # getattr-or-create path on every paint.
        self._skia_dash_cache: dict = {}
        # Day 6: censor regions. List of CensorRegion dataclasses.
        # Drawn after overlays so they mask / blur the base image.
        self._censors: list = []
        # Day 7: selection + snap guides. Selection stored as a set of
        # id(overlay) — using object identity not label so duplicate
        # labels don't collide. Snap guides are 4-tuple line segments
        # in scene coords, drawn as dashed overlay above everything.
        self._selected_ids: set = set()
        self._snap_guides: list = []
        # Day 9: draft shape. Populated by tool mode while the user is
        # drawing a new overlay (rect / ellipse / line / arrow). Rendered
        # at the end of the scene pass so it appears above everything
        # and can be stylized differently (dashed outline etc.).
        # Shape: {"kind": "rect"|"ellipse"|"line"|"arrow",
        #         "x": float, "y": float, "w": float, "h": float,
        #         "color": "#rrggbb", "stroke_width": float,
        #         "x2": float (for line/arrow), "y2": float}
        self._draft_shape: dict | None = None
        # Day 13: FPS HUD timing state.
        import time as _t
        self._fps_time = _t
        self._fps_last_ms: float = 0.0
        self._fps_rolling_ms: float = 0.0
        self._fps_samples: list = []  # (timestamp, paint_ms)
        self._fps_perf_log = None    # optional file handle
        self._resize_buffers(self.size())
        # Record whether Skia is live; surfacing this to the editor lets
        # the FPS HUD show which backend is active.
        self.backend_name = "skia" if skia_available() else "fallback"
        self.resize(640, 480)

    # ------------------------------------------------------------------
    # Buffer management
    # ------------------------------------------------------------------

    def _resize_buffers(self, size: QSize):
        # Day 11: high-DPI. Scale the backing store by devicePixelRatio
        # so Skia renders at native display resolution on 125%/150%/200%
        # screens. The QImage carries the same DPR so QPainter blits 1:1
        # at device pixels without resampling.
        dpr = float(self.devicePixelRatioF() or 1.0)
        self._dpr = dpr
        logical_w = max(1, int(size.width()))
        logical_h = max(1, int(size.height()))
        phys_w = max(1, int(round(logical_w * dpr)))
        phys_h = max(1, int(round(logical_h * dpr)))
        self._qimg = QImage(
            phys_w, phys_h, QImage.Format.Format_RGBA8888_Premultiplied)
        self._qimg.setDevicePixelRatio(dpr)
        self._qimg.fill(Qt.GlobalColor.transparent)
        self._surface = None
        self._surface_is_direct = False
        if not _SKIA_OK:
            return
        try:
            info = skia.ImageInfo.Make(
                phys_w, phys_h,
                skia.ColorType.kRGBA_8888_ColorType,
                skia.AlphaType.kPremul_AlphaType,
            )
            # Allocated raster surface — Skia owns the backing store.
            # At paint time we readPixels into the QImage buffer.
            self._surface = skia.Surface.MakeRaster(info)
        except Exception:
            self._surface = None

    def resizeEvent(self, event):
        self._resize_buffers(event.size())
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # Interactive pan + zoom (wheel + middle-drag)
    # ------------------------------------------------------------------

    def wheelEvent(self, event):
        """Wheel zoom centered on cursor. Ctrl+wheel = larger step."""
        is_ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        step = 1.25 if is_ctrl else 1.1
        factor = step if event.angleDelta().y() > 0 else 1.0 / step
        # Cursor-anchored zoom: translate so the scene point under the
        # cursor stays put after the zoom.
        try:
            pos = event.position()
        except AttributeError:
            pos = event.pos()
        wx, wy = float(pos.x()), float(pos.y())
        old_zoom = self._zoom
        new_zoom = max(0.05, min(32.0, old_zoom * factor))
        if new_zoom == old_zoom:
            return
        # Scene point currently at cursor:
        #   sx = (wx - pan_x) / old_zoom
        # We want new pan such that (wx - new_pan_x) / new_zoom == sx.
        sx = (wx - self._pan_x) / old_zoom
        sy = (wy - self._pan_y) / old_zoom
        self._zoom = new_zoom
        self._pan_x = wx - sx * new_zoom
        self._pan_y = wy - sy * new_zoom
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            try:
                self._pan_start = event.position()
            except AttributeError:
                # PySide6 >= 6.0 always has event.position(); the older
                # fallback path stayed for defensive coverage. QPointF
                # is module-imported already (see top of file) so drop
                # the redundant inline import.
                self._pan_start = QPointF(event.pos())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_panning", False):
            try:
                pos = event.position()
            except AttributeError:
                pos = QPointF(event.pos())
            delta = pos - self._pan_start
            self._pan_start = pos
            self._pan_x += delta.x()
            self._pan_y += delta.y()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and getattr(self, "_panning", False):
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

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
        # Pixelate censors cache the down-sampled intermediate keyed
        # on id(base_image); a fresh load invalidates all entries.
        pc = getattr(self, "_pixelate_cache", None)
        if pc:
            pc.clear()
        self.update()

    def base_size(self) -> QSize:
        if self._base_image is None:
            return QSize(0, 0)
        return QSize(self._base_image.width(), self._base_image.height())

    # ------------------------------------------------------------------
    # View transform (panning / zooming)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Day 8 — hit testing
    # ------------------------------------------------------------------

    def hit_test_image(self, image_pos: QPointF):
        """Return the topmost overlay whose shape contains image_pos.
        image_pos is in image (scene) coordinates, not widget pixels.
        Mirrors the behavior of QGraphicsScene.itemAt()."""
        x = image_pos.x()
        y = image_pos.y()
        # Walk overlays in reverse so the topmost (last-drawn) wins.
        for ov in reversed(self._overlays):
            if not ov.enabled:
                continue
            if self._overlay_contains(ov, x, y):
                return ov
        return None

    def _overlay_contains(self, ov, x: float, y: float) -> bool:
        """Point-in-overlay hit test. Uses the overlay's bounding rect
        for quick rejection; shape overlays use SkPath.contains() for
        accurate hit tests on curved shapes."""
        ov_type = getattr(ov, "type", "")
        if ov_type == "arrow":
            # Stroke-based hit test: close to the line segment.
            x1 = float(getattr(ov, "x", 0) or 0)
            y1 = float(getattr(ov, "y", 0) or 0)
            x2 = float(getattr(ov, "end_x", 0) or 0)
            y2 = float(getattr(ov, "end_y", 0) or 0)
            return self._dist_to_segment(x, y, x1, y1, x2, y2) <= \
                max(6.0, float(getattr(ov, "stroke_width", 4) or 4))
        if ov_type == "shape":
            w = float(getattr(ov, "shape_w", 0) or 0)
            h = float(getattr(ov, "shape_h", 0) or 0)
            ox = float(getattr(ov, "x", 0) or 0)
            oy = float(getattr(ov, "y", 0) or 0)
            # Quick bbox reject in local coords (account for rotation
            # with a generous padding equal to half the diagonal).
            if w <= 0 or h <= 0:
                return False
            # Transform point into local shape coords (undo rotation)
            rot = float(getattr(ov, "rotation", 0) or 0)
            lx = x - ox
            ly = y - oy
            if rot:
                rad = -math.radians(rot)
                cx, cy = w / 2, h / 2
                dx = lx - cx
                dy = ly - cy
                c, s = math.cos(rad), math.sin(rad)
                lx = cx + dx * c - dy * s
                ly = cy + dx * s + dy * c
            if lx < 0 or ly < 0 or lx > w or ly > h:
                return False
            try:
                path = self._build_shape_path(ov)
                return path.contains(lx, ly)
            except Exception:
                return True  # bbox hit, accept
        # Text + image overlays: bounding-rect hit test.
        if ov_type == "text":
            # Approximate bounds from text metrics — good enough for
            # click routing; exact layout bounds would require a Skia
            # text blob measure pass, deferred to Day 9.
            size = float(getattr(ov, "font_size", 14) or 14)
            text = getattr(ov, "text", "") or ""
            lines = text.split("\n")
            lh = float(getattr(ov, "line_height", 1.2) or 1.2)
            # Rough width: longest line × avg char width (0.6 × size)
            widest = max((len(l) for l in lines), default=0)
            w = float(getattr(ov, "text_width", 0) or 0) or \
                widest * size * 0.6
            h = len(lines) * size * lh
            ox = float(getattr(ov, "x", 0) or 0)
            oy = float(getattr(ov, "y", 0) or 0)
            return ox <= x <= ox + w and oy <= y <= oy + h
        if ov_type in ("watermark", "logo"):
            img = self._skia_image_for_overlay(ov)
            if img is None:
                return False
            w = img.width()
            h = img.height()
            scale = float(getattr(ov, "scale", 1.0) or 1.0)
            if scale != 1.0 and self._base_image is not None:
                base_w = self._base_image.width()
                target_w = max(10, base_w * scale)
                s = target_w / max(1, w)
                w *= s
                h *= s
            ox = float(getattr(ov, "x", 0) or 0)
            oy = float(getattr(ov, "y", 0) or 0)
            return ox <= x <= ox + w and oy <= y <= oy + h
        return False

    @staticmethod
    def _dist_to_segment(px: float, py: float,
                          x1: float, y1: float,
                          x2: float, y2: float) -> float:
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0,
            ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.hypot(px - proj_x, py - proj_y)

    def widget_to_image_pos(self, widget_pos: QPointF) -> QPointF:
        """Map a widget-space position (mouse event) into image (scene)
        coordinates, undoing the pan + zoom transforms."""
        x = (widget_pos.x() - self._pan_x) / max(0.01, self._zoom)
        y = (widget_pos.y() - self._pan_y) / max(0.01, self._zoom)
        return QPointF(x, y)

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
        new_list = list(overlays)
        # Prune stale path-cache entries. Keys are id(overlay); once an
        # overlay is removed from the list the entry can't be hit again
        # but continues to consume memory until the canvas is destroyed.
        if self._skia_path_cache:
            live_ids = {id(ov) for ov in new_list}
            self._skia_path_cache = {
                k: v for k, v in self._skia_path_cache.items()
                if k in live_ids
            }
        # Prune the overlay-image cache for paths that are no longer
        # referenced by any overlay. A decoded skia.Image for a multi-MB
        # watermark carries the full decoded pixel buffer, so stale
        # entries aren't free. Keep the entry if ANY overlay still uses
        # that path so repeat decodes are avoided.
        if self._overlay_image_cache:
            live_paths = {
                getattr(ov, "image_path", "") for ov in new_list
                if getattr(ov, "image_path", "")
            }
            self._overlay_image_cache = {
                p: img for p, img in self._overlay_image_cache.items()
                if p in live_paths
            }
        self._overlays = new_list
        self.update()

    def add_overlay(self, ov):
        self._overlays.append(ov)
        self.update()

    def set_censors(self, censors: list):
        self._censors = list(censors)
        self.update()

    def add_censor(self, cr):
        self._censors.append(cr)
        self.update()

    def remove_censor(self, cr):
        try:
            self._censors.remove(cr)
        except ValueError:
            pass
        self.update()

    # ------------------------------------------------------------------
    # Day 7 — selection state + snap guides
    # ------------------------------------------------------------------

    def set_selected(self, overlays: list):
        """Mark which overlays are selected. Accepts the SAME overlay
        objects held in self._overlays; identity comparison. Early-out
        when the selection set is unchanged — an unnecessary update()
        here schedules a full Skia re-render."""
        new_ids = set(id(ov) for ov in overlays)
        if new_ids == self._selected_ids:
            return
        self._selected_ids = new_ids
        self.update()

    def select(self, ov):
        if ov is None:
            return
        _id = id(ov)
        if _id in self._selected_ids:
            return
        self._selected_ids.add(_id)
        self.update()

    def deselect_all(self):
        if self._selected_ids:
            self._selected_ids.clear()
            self.update()

    def is_selected(self, ov) -> bool:
        return id(ov) in self._selected_ids

    # ------------------------------------------------------------------
    # Day 10 — export
    # ------------------------------------------------------------------

    def export_to_qimage(self, include_decorators: bool = False) -> QImage | None:
        """Render the current scene at the base image's native resolution
        (no pan/zoom applied) and return a QImage. Selection decorators
        and snap guides are omitted by default — exports should look like
        the final asset, not the editing UI.

        If no base image is loaded, falls back to the current viewport
        size. Returns None on failure (skia unavailable, render error)."""
        if not _SKIA_OK:
            return None
        base = self._base_image
        if base is not None:
            w, h = base.width(), base.height()
        else:
            w = max(1, self.width())
            h = max(1, self.height())
        try:
            info = skia.ImageInfo.Make(
                w, h,
                skia.ColorType.kRGBA_8888_ColorType,
                skia.AlphaType.kPremul_AlphaType,
            )
            surface = skia.Surface.MakeRaster(info)
            if surface is None:
                return None
            canvas = surface.getCanvas()
            canvas.clear(skia.Color(0, 0, 0, 0))
            # No pan / zoom for export — render at native coords.
            if base is not None:
                canvas.drawImage(base, 0, 0)
            for ov in self._overlays:
                t = getattr(ov, "type", "")
                if t in ("watermark", "logo"):
                    self._draw_overlay_image(canvas, ov)
                elif t == "text":
                    self._draw_overlay_text(canvas, ov)
                elif t == "shape":
                    self._draw_overlay_shape(canvas, ov)
                elif t == "arrow":
                    self._draw_overlay_arrow(canvas, ov)
            for cr in self._censors:
                self._draw_censor(canvas, cr, base)
            if include_decorators:
                for ov in self._overlays:
                    if id(ov) in self._selected_ids:
                        self._draw_selection_decor(canvas, ov)
                if self._snap_guides:
                    self._draw_snap_guides(canvas)
            try:
                canvas.flush()
            except AttributeError:
                pass
            out = QImage(w, h, QImage.Format.Format_RGBA8888_Premultiplied)
            out.fill(Qt.GlobalColor.transparent)
            surface.readPixels(info, out.bits(),
                               out.bytesPerLine(), 0, 0)
            return out
        except Exception:
            return None

    def export_to_png(self, path: str) -> bool:
        """Export the scene to a PNG file via Skia's native encoder.
        Returns True on success. Bypasses QImage for a cleaner pipeline
        when the caller just wants a file on disk."""
        if not _SKIA_OK:
            return False
        base = self._base_image
        if base is not None:
            w, h = base.width(), base.height()
        else:
            w = max(1, self.width())
            h = max(1, self.height())
        try:
            info = skia.ImageInfo.Make(
                w, h,
                skia.ColorType.kRGBA_8888_ColorType,
                skia.AlphaType.kPremul_AlphaType,
            )
            surface = skia.Surface.MakeRaster(info)
            if surface is None:
                return False
            canvas = surface.getCanvas()
            canvas.clear(skia.Color(0, 0, 0, 0))
            if base is not None:
                canvas.drawImage(base, 0, 0)
            for ov in self._overlays:
                t = getattr(ov, "type", "")
                if t in ("watermark", "logo"):
                    self._draw_overlay_image(canvas, ov)
                elif t == "text":
                    self._draw_overlay_text(canvas, ov)
                elif t == "shape":
                    self._draw_overlay_shape(canvas, ov)
                elif t == "arrow":
                    self._draw_overlay_arrow(canvas, ov)
            for cr in self._censors:
                self._draw_censor(canvas, cr, base)
            try:
                canvas.flush()
            except AttributeError:
                pass
            img = surface.makeImageSnapshot()
            data = img.encodeToData(skia.EncodedImageFormat.kPNG, 100)
            if data is None:
                return False
            with open(path, "wb") as f:
                f.write(bytes(data))
            return True
        except Exception:
            return False

    def set_snap_guides(self, guides: list):
        """List of (x1, y1, x2, y2) tuples in scene coords. Drawn
        dashed-cyan over everything while active during drag. Early-out
        when the guide list is identical — prevents a full Skia re-render
        on every mouse move of a drag where no new snap target fired."""
        new_list = list(guides)
        if self._snap_guides == new_list:
            return
        self._snap_guides = new_list
        self.update()

    def set_draft_shape(self, draft: dict | None):
        """Set the in-progress shape being drawn (tool modes). Pass a
        dict with keys kind/x/y/w/h/... or None to clear. Re-renders.
        Early-out when the draft dict hasn't changed — tool-drag fires
        on every mouse move and often the draft is identical to the
        prior frame's (Ctrl held, tool-drag without movement)."""
        if self._draft_shape == draft:
            return
        self._draft_shape = draft
        self.update()

    def clear_draft_shape(self):
        if self._draft_shape is not None:
            self._draft_shape = None
            self.update()

    def attach_perf_log(self, file_handle):
        """Attach a writable file handle (e.g. open('path','w')) to
        receive per-paint JSONL events. Pass None to detach."""
        self._fps_perf_log = file_handle

    # ------------------------------------------------------------------
    # QGraphicsScene-compatible API (Day 14 cutover shim)
    #
    # Provides drop-in replacements for the QGraphicsScene methods that
    # StudioEditor calls most often. When the full cutover happens,
    # existing `self._scene.itemAt(pos)` / `self._scene.selectedItems()`
    # / etc. calls continue to work unchanged against a CanvasSkia
    # instance.
    # ------------------------------------------------------------------

    def itemAt(self, scene_pos: QPointF, _device_transform=None):
        """QGraphicsScene.itemAt() shim. Returns the topmost overlay at
        the given scene position, or None. _device_transform ignored —
        accepted for signature compat with Qt's 2-arg form."""
        return self.hit_test_image(scene_pos)

    def items(self, rect=None):
        """QGraphicsScene.items() shim. Returns list of overlays in
        z-order (front-to-back). If `rect` provided (QRectF), filters
        to overlays whose bbox intersects. Censors are returned after
        overlays to match the 'draw censors above overlays' semantics."""
        result = []
        if rect is None:
            result.extend(reversed(self._overlays))
            result.extend(reversed(self._censors))
            return result
        # Rect-filtered: test each overlay's bbox against rect
        for ov in reversed(self._overlays):
            try:
                ox, oy, w, h = self._selection_bbox_local(ov)
                if QRectF(ox, oy, w, h).intersects(rect):
                    result.append(ov)
            except Exception:
                continue
        return result

    def selectedItems(self):
        """Return selected overlays in current z-order."""
        return [ov for ov in self._overlays if id(ov) in self._selected_ids]

    def clearSelection(self):
        if self._selected_ids:
            self._selected_ids.clear()
            self.update()

    def addItem(self, ov):
        """QGraphicsScene.addItem() shim. Accepts a CanvasOverlay or a
        CensorRegion and routes to the appropriate list."""
        # Detect type by attribute presence — CanvasOverlay has 'type',
        # CensorRegion has 'style' + 'w'/'h'.
        if hasattr(ov, "type"):
            self._overlays.append(ov)
        elif hasattr(ov, "style") and hasattr(ov, "w"):
            self._censors.append(ov)
        self.update()

    def removeItem(self, ov):
        """QGraphicsScene.removeItem() shim."""
        if ov in self._overlays:
            self._overlays.remove(ov)
        elif ov in self._censors:
            self._censors.remove(ov)
        self._selected_ids.discard(id(ov))
        self.update()

    def sceneRect(self) -> QRectF:
        """Return the base image's rect in scene coords (top-left at
        origin). QGraphicsScene returns the unioned bbox of all items
        by default; we pin to the base image since overlays always
        position relative to it in this codebase."""
        if self._base_image is None:
            return QRectF(0, 0, 0, 0)
        return QRectF(
            0, 0,
            float(self._base_image.width()),
            float(self._base_image.height()))

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
        if not ov.enabled:
            return
        text = getattr(ov, "text", "") or ""
        if not text:
            return
        family = getattr(ov, "font_family", "Segoe UI") or "Segoe UI"
        size = float(getattr(ov, "font_size", 14) or 14)
        bold = bool(getattr(ov, "bold", False))
        italic = bool(getattr(ov, "italic", False))
        # Typeface cache: OS font lookup runs once per (family, bold,
        # italic) combo for the lifetime of the canvas. Prior code was
        # calling skia.Typeface() every paint for every text overlay
        # which is a 50-500us system call each time.
        tf_key = (family, bold, italic)
        typeface = self._skia_typeface_cache.get(tf_key)
        if typeface is None:
            style = skia.FontStyle(
                skia.FontStyle.kBold_Weight if bold
                else skia.FontStyle.kNormal_Weight,
                skia.FontStyle.kNormal_Width,
                (skia.FontStyle.kItalic_Slant if italic
                 else skia.FontStyle.kUpright_Slant),
            )
            typeface = skia.Typeface(family, style)
            self._skia_typeface_cache[tf_key] = typeface
        # Font cache: (typeface identity, size) is stable across frames.
        # Key on id(typeface) so different typeface objects with same
        # family+style (shouldn't happen post-cache) don't collide.
        font_key = (id(typeface), size)
        font = self._skia_font_cache.get(font_key)
        if font is None:
            font = skia.Font(typeface, size)
            self._skia_font_cache[font_key] = font
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
        """Parse #RRGGBB / #RRGGBBAA -> (r,g,b,a). Returns default on error.

        Hot path: every overlay paint resolves 1-3 hex colors. A scene
        with 20 overlays at 60fps = 1200-3600 parses/sec. lru_cache
        memoises against the string alone, so repeat colors (most of a
        palette) return the pre-parsed tuple without int() calls.
        """
        cached = _parse_hex_cached(s)
        if cached is not None:
            return cached
        return default

    # ------------------------------------------------------------------
    # Day 5 — shape overlays (OverlayShapeItem port)
    # ------------------------------------------------------------------

    def _build_shape_path(self, ov) -> "skia.Path":
        """Return a SkPath for the shape's kind. Geometry is in the
        shape's local coord system (top-left at origin); the caller
        translates the canvas to overlay.x/y before drawing.

        Mirrors the shape_kind dispatch in studio_items.py so the
        Skia path matches OverlayShapeItem.paint visually.

        Path cache: built paths are stored per-overlay keyed on a
        geometry fingerprint. Speech / thought bubbles run path.united()
        plus up to 72 wobble samples, rebuilding per frame during drag
        dominates paintGL time. Position (overlay.x / y) is NOT in the
        key because the path is in local coords; the caller translates.
        """
        # Build a fingerprint of every attribute that affects path
        # geometry. Kept in sync with the SHAPE_PATH_KEYS set below.
        kind = getattr(ov, "shape_kind", "rect") or "rect"
        w = float(getattr(ov, "shape_w", 100) or 100)
        h = float(getattr(ov, "shape_h", 100) or 100)
        # tail_x / tail_y only matter for bubble kinds; for everything
        # else skip them (less cache churn when a user toggles between
        # bubble tail positions on unrelated shapes).
        tail_dx = tail_dy = 0.0
        if kind in ("speech_bubble", "thought_bubble"):
            tx = float(getattr(ov, "tail_x", 0) or 0)
            ty = float(getattr(ov, "tail_y", 0) or 0)
            if tx != 0 or ty != 0:
                tail_dx = tx - float(getattr(ov, "x", 0) or 0)
                tail_dy = ty - float(getattr(ov, "y", 0) or 0)
        fingerprint = (
            kind, w, h,
            float(getattr(ov, "corner_radius", 0) or 0),
            int(getattr(ov, "star_points", 5) or 5),
            float(getattr(ov, "inner_ratio", 0.5) or 0.5),
            tail_dx, tail_dy,
        )
        key = id(ov)
        cached = self._skia_path_cache.get(key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]

        rect = skia.Rect.MakeXYWH(0, 0, w, h)
        path = skia.Path()
        if kind == "rect":
            radius = float(getattr(ov, "corner_radius", 0) or 0)
            if radius > 0:
                path.addRoundRect(rect, radius, radius)
            else:
                path.addRect(rect)
        elif kind == "ellipse":
            path.addOval(rect)
        elif kind == "star":
            self._append_star_path(path, w, h, ov)
        elif kind == "polygon":
            self._append_polygon_path(path, w, h, ov)
        elif kind == "burst":
            self._append_burst_path(path, w, h)
        elif kind in ("speech_bubble", "thought_bubble"):
            # Bubble geometry needs the overlay's scene-coord tail_tip
            # projected into local space. Compute relative-to-origin
            # here so the path is local-coord just like the other kinds.
            if kind == "speech_bubble":
                self._append_speech_bubble_path(path, w, h, ov)
            else:
                self._append_thought_bubble_path(path, w, h, ov)
        else:
            path.addRect(rect)
        self._skia_path_cache[key] = (fingerprint, path)
        return path

    def _append_star_path(self, path, w, h, ov):
        n = max(3, int(getattr(ov, "star_points", 5) or 5))
        inner = max(0.1, min(0.95,
            float(getattr(ov, "inner_ratio", 0.4) or 0.4)))
        cx, cy = w / 2, h / 2
        rx, ry = w / 2, h / 2
        pts = []
        for i in range(n * 2):
            frac = (2 * math.pi * i) / (n * 2) - math.pi / 2
            s = 1.0 if i % 2 == 0 else inner
            pts.append((cx + math.cos(frac) * rx * s,
                        cy + math.sin(frac) * ry * s))
        path.moveTo(*pts[0])
        for p in pts[1:]:
            path.lineTo(*p)
        path.close()

    def _append_polygon_path(self, path, w, h, ov):
        n = max(3, int(getattr(ov, "star_points", 6) or 6))
        cx, cy = w / 2, h / 2
        rx, ry = w / 2, h / 2
        pts = []
        for i in range(n):
            frac = (2 * math.pi * i) / n - math.pi / 2
            pts.append((cx + math.cos(frac) * rx,
                        cy + math.sin(frac) * ry))
        path.moveTo(*pts[0])
        for p in pts[1:]:
            path.lineTo(*p)
        path.close()

    def _append_burst_path(self, path, w, h):
        cx, cy = w / 2, h / 2
        rx, ry = w / 2, h / 2
        n = 14
        inner = 0.62
        pts = []
        for i in range(n * 2):
            frac = (2 * math.pi * i) / (n * 2)
            s = 1.0 if i % 2 == 0 else inner
            pts.append((cx + math.cos(frac - math.pi / 2) * rx * s,
                        cy + math.sin(frac - math.pi / 2) * ry * s))
        path.moveTo(*pts[0])
        for p in pts[1:]:
            path.lineTo(*p)
        path.close()

    def _append_speech_bubble_path(self, path, w, h, ov):
        """Rounded-rect body + triangular tail, unioned. Tail tip is
        stored in scene coords on the overlay; convert to local by
        subtracting overlay.x/y."""
        # Body
        roundness = max(0.0, min(1.0,
            getattr(ov, "bubble_roundness", 0.0) or 0.0))
        pad = min(w, h) * 0.18
        effective_pad = pad + (min(w, h) / 2 - pad) * roundness
        body = skia.Path()
        if roundness >= 0.99:
            body.addOval(skia.Rect.MakeXYWH(0, 0, w, h))
        else:
            body.addRoundRect(skia.Rect.MakeXYWH(0, 0, w, h),
                              effective_pad, effective_pad)
        # Tail — tip in local coords
        tip_sx = getattr(ov, "tail_x", 0) or 0
        tip_sy = getattr(ov, "tail_y", 0) or 0
        if tip_sx == 0 and tip_sy == 0:
            tip_x, tip_y = -w * 0.15, h + h * 0.35
        else:
            tip_x = float(tip_sx) - float(ov.x)
            tip_y = float(tip_sy) - float(ov.y)
        cx, cy = w / 2, h / 2
        dx, dy = tip_x - cx, tip_y - cy
        horiz = abs(dx) > abs(dy)
        base_len = min(w, h) * 0.25
        overlap = max(4.0, min(w, h) * 0.08)
        if horiz:
            edge_x = (w - overlap) if dx > 0 else overlap
            mid_y = max(pad, min(h - pad, tip_y * 0.5 + cy * 0.5))
            b1 = (edge_x, mid_y - base_len / 2)
            b2 = (edge_x, mid_y + base_len / 2)
        else:
            edge_y = (h - overlap) if dy > 0 else overlap
            mid_x = max(pad, min(w - pad, tip_x * 0.5 + cx * 0.5))
            b1 = (mid_x - base_len / 2, edge_y)
            b2 = (mid_x + base_len / 2, edge_y)
        tail = skia.Path()
        tail.moveTo(*b1)
        tail_curve = max(-1.0, min(1.0,
            float(getattr(ov, "tail_curve", 0.0) or 0.0)))
        if abs(tail_curve) > 0.02:
            amt = tail_curve * base_len * 1.2
            def _perp(src, dst, a):
                mx = (src[0] + dst[0]) / 2
                my = (src[1] + dst[1]) / 2
                vdx = dst[0] - src[0]
                vdy = dst[1] - src[1]
                ln = math.hypot(vdx, vdy) or 1.0
                nx, ny = -vdy / ln, vdx / ln
                return (mx + nx * a, my + ny * a)
            c1 = _perp(b1, (tip_x, tip_y), amt)
            c2 = _perp((tip_x, tip_y), b2, amt)
            tail.quadTo(c1[0], c1[1], tip_x, tip_y)
            tail.quadTo(c2[0], c2[1], b2[0], b2[1])
        else:
            tail.lineTo(tip_x, tip_y)
            tail.lineTo(*b2)
        tail.close()
        # Union body + tail
        try:
            merged = body.op(tail, skia.PathOp.kUnion_PathOp)
            if merged is not None:
                path.addPath(merged)
            else:
                path.addPath(body)
                path.addPath(tail)
        except Exception:
            path.addPath(body)
            path.addPath(tail)

    def _append_thought_bubble_path(self, path, w, h, ov):
        """Cloud body via ellipse + 10 peripheral puffs unioned."""
        cx, cy = w / 2, h / 2
        rx, ry = w / 2, h / 2
        base = skia.Path()
        base.addOval(skia.Rect.MakeXYWH(rx * 0.22, ry * 0.22,
                                          w - rx * 0.44, h - ry * 0.44))
        n_puffs = 10
        puff_r = min(rx, ry) * 0.28
        cloud = base
        for i in range(n_puffs):
            ang = (2 * math.pi * i) / n_puffs
            px = cx + math.cos(ang) * (rx - puff_r * 0.4)
            py = cy + math.sin(ang) * (ry - puff_r * 0.4)
            sub = skia.Path()
            sub.addOval(skia.Rect.MakeLTRB(
                px - puff_r, py - puff_r,
                px + puff_r, py + puff_r))
            try:
                cloud = cloud.op(sub, skia.PathOp.kUnion_PathOp) or cloud
            except Exception:
                pass
        path.addPath(cloud)

    def _draw_overlay_shape(self, canvas, ov):
        """Render a shape overlay. Day-5 scope: all shape_kind variants
        (rect/ellipse/star/polygon/burst/bubbles), stroke, fill,
        gradient fills (linear/radial), rotation, opacity, blend mode.
        """
        if not ov.enabled:
            return
        w = float(getattr(ov, "shape_w", 100) or 100)
        h = float(getattr(ov, "shape_h", 100) or 100)
        if w <= 0 or h <= 0:
            return
        path = self._build_shape_path(ov)
        canvas.save()
        canvas.translate(float(ov.x), float(ov.y))
        rot = float(getattr(ov, "rotation", 0) or 0)
        if rot:
            canvas.translate(w / 2, h / 2)
            canvas.rotate(rot)
            canvas.translate(-w / 2, -h / 2)
        opacity = float(getattr(ov, "opacity", 1.0) or 1.0)
        kind = getattr(ov, "shape_kind", "rect") or "rect"
        blend_mode = self._blend_mode_for(
            getattr(ov, "blend_mode", "normal") or "normal")
        # Fill
        if kind in ("gradient_linear", "gradient_radial"):
            self._fill_gradient(canvas, path, ov, w, h, blend_mode, opacity)
        else:
            fill_hex = getattr(ov, "fill_color", "") or ""
            if fill_hex:
                fill_rgba = self._parse_hex(fill_hex, (0, 0, 0, 255))
                fp = skia.Paint()
                fp.setAntiAlias(True)
                fp.setStyle(skia.Paint.kFill_Style)
                fp.setColor(skia.Color(*fill_rgba))
                fp.setAlphaf(opacity * (fill_rgba[3] / 255.0))
                if blend_mode is not None:
                    fp.setBlendMode(blend_mode)
                canvas.drawPath(path, fp)
        # Stroke
        stroke_w = float(getattr(ov, "stroke_width", 0) or 0)
        stroke_hex = (getattr(ov, "stroke_color", "") or
                      getattr(ov, "color", "") or "")
        if stroke_w > 0 and stroke_hex:
            stroke_rgba = self._parse_hex(stroke_hex, (0, 0, 0, 255))
            sp = skia.Paint()
            sp.setAntiAlias(True)
            sp.setStyle(skia.Paint.kStroke_Style)
            sp.setColor(skia.Color(*stroke_rgba))
            sp.setStrokeWidth(stroke_w)
            sp.setStrokeJoin(skia.Paint.kRound_Join)
            sp.setAlphaf(opacity * (stroke_rgba[3] / 255.0))
            # Line style
            style = getattr(ov, "line_style", "solid") or "solid"
            if style in ("dash", "dot"):
                intervals = ((stroke_w * 3, stroke_w * 2) if style == "dash"
                             else (stroke_w, stroke_w))
                dash = self._get_dash_effect(intervals)
                if dash is not None:
                    sp.setPathEffect(dash)
            if blend_mode is not None:
                sp.setBlendMode(blend_mode)
            canvas.drawPath(path, sp)
        canvas.restore()

    def _fill_gradient(self, canvas, path, ov, w, h, blend_mode, opacity):
        start_hex = getattr(ov, "gradient_start_color", "") or "#000000"
        end_hex = getattr(ov, "gradient_end_color", "") or "#ffffff"
        c0 = self._parse_hex(start_hex, (0, 0, 0, 255))
        c1 = self._parse_hex(end_hex, (255, 255, 255, 255))
        kind = getattr(ov, "shape_kind", "")
        colors = [skia.Color(*c0), skia.Color(*c1)]
        try:
            if kind == "gradient_linear":
                ang = math.radians(getattr(ov, "gradient_angle", 0) or 0)
                cx, cy = w / 2, h / 2
                half = w / 2
                p0 = skia.Point(cx - math.cos(ang) * half,
                                 cy - math.sin(ang) * half)
                p1 = skia.Point(cx + math.cos(ang) * half,
                                 cy + math.sin(ang) * half)
                shader = skia.GradientShader.MakeLinear([p0, p1], colors)
            else:
                shader = skia.GradientShader.MakeRadial(
                    skia.Point(w / 2, h / 2),
                    max(w, h) / 2, colors)
        except Exception:
            shader = None
        gp = skia.Paint()
        gp.setAntiAlias(True)
        gp.setStyle(skia.Paint.kFill_Style)
        gp.setAlphaf(opacity)
        if shader is not None:
            gp.setShader(shader)
        if blend_mode is not None:
            gp.setBlendMode(blend_mode)
        canvas.drawPath(path, gp)

    # ------------------------------------------------------------------
    # Day 7 — selection decorators + snap guides
    # ------------------------------------------------------------------

    # Visual constants for selection decorators. Match the values used
    # in OverlayShapeItem.paint when self.isSelected() so switching
    # between QGraphicsView and Skia compositors is visually stable.
    _SEL_LINE_COLOR = (0x55, 0xaa, 0xff, 0xcc)   # dashed bbox
    _HANDLE_FILL = (0xff, 0xff, 0xff, 0xff)
    _HANDLE_BORDER = (0x22, 0x22, 0x22, 0xff)
    _ROTATE_FILL = (0x33, 0xcc, 0x77, 0xff)
    _TAIL_FILL = (0x00, 0xdd, 0xdd, 0xff)
    _SNAP_COLOR = (0x00, 0xdd, 0xdd, 0xcc)

    def _selection_bbox_local(self, ov) -> tuple:
        """Return (ox, oy, w, h) in scene coords for a selection bbox.
        Skips rotation — decorators drawn in scene coords, not rotated."""
        t = getattr(ov, "type", "")
        if t == "shape":
            return (float(ov.x), float(ov.y),
                    float(getattr(ov, "shape_w", 0) or 0),
                    float(getattr(ov, "shape_h", 0) or 0))
        if t == "arrow":
            x1 = float(getattr(ov, "x", 0) or 0)
            y1 = float(getattr(ov, "y", 0) or 0)
            x2 = float(getattr(ov, "end_x", 0) or 0)
            y2 = float(getattr(ov, "end_y", 0) or 0)
            return (min(x1, x2), min(y1, y2),
                    abs(x2 - x1), abs(y2 - y1))
        if t == "text":
            size = float(getattr(ov, "font_size", 14) or 14)
            text = getattr(ov, "text", "") or ""
            lines = text.split("\n")
            widest = max((len(l) for l in lines), default=0)
            lh = float(getattr(ov, "line_height", 1.2) or 1.2)
            w = float(getattr(ov, "text_width", 0) or 0) or \
                max(20, widest * size * 0.6)
            h = max(size, len(lines) * size * lh)
            return (float(ov.x), float(ov.y), w, h)
        if t in ("watermark", "logo"):
            img = self._skia_image_for_overlay(ov)
            if img is None:
                return (float(ov.x), float(ov.y), 20, 20)
            w = img.width()
            h = img.height()
            scale = float(getattr(ov, "scale", 1.0) or 1.0)
            if scale != 1.0 and self._base_image is not None:
                s = (self._base_image.width() * scale) / max(1, w)
                w *= s
                h *= s
            return (float(ov.x), float(ov.y), w, h)
        return (float(getattr(ov, "x", 0) or 0),
                float(getattr(ov, "y", 0) or 0), 20, 20)

    def _get_dash_effect(self, intervals_tuple):
        """Return a cached SkDashPathEffect for the given intervals.
        Path effects are immutable; caching one per pattern means N
        selected overlays share a single effect instance instead of
        each allocating their own. _skia_dash_cache is pre-allocated
        in __init__ so no getattr guard is needed here."""
        cache = self._skia_dash_cache
        eff = cache.get(intervals_tuple)
        if eff is None:
            try:
                eff = skia.DashPathEffect.Make(list(intervals_tuple), 0.0)
            except Exception:
                eff = None
            cache[intervals_tuple] = eff
        return eff

    def _draw_selection_decor(self, canvas, ov):
        """Dashed bounding rect + corner handles + rotate handle on
        top-center for shapes/texts/images. Arrows get endpoint dots."""
        ox, oy, w, h = self._selection_bbox_local(ov)
        ov_type = getattr(ov, "type", "")
        # Dashed outline. Paint rebuilt per call (stroke width is zoom-
        # dependent so reusing one would require pre-draw mutation);
        # DashPathEffect is cached since it's pattern-keyed and immutable.
        outline = skia.Paint()
        outline.setAntiAlias(True)
        outline.setStyle(skia.Paint.kStroke_Style)
        outline.setColor(skia.Color(*self._SEL_LINE_COLOR))
        outline.setStrokeWidth(max(1.0, 1.2 / max(0.01, self._zoom)))
        dash = self._get_dash_effect((6.0, 4.0))
        if dash is not None:
            outline.setPathEffect(dash)
        canvas.drawRect(skia.Rect.MakeXYWH(ox, oy, w, h), outline)
        if ov_type == "arrow":
            # Endpoint dots (start + end)
            x1 = float(getattr(ov, "x", 0) or 0)
            y1 = float(getattr(ov, "y", 0) or 0)
            x2 = float(getattr(ov, "end_x", 0) or 0)
            y2 = float(getattr(ov, "end_y", 0) or 0)
            r = max(3.0, 5.0 / max(0.01, self._zoom))
            for px, py in ((x1, y1), (x2, y2)):
                self._draw_handle_dot(canvas, px, py, r)
            return
        # Corner + edge handles (up to 8) plus rotate handle for shapes
        r = max(3.0, 4.0 / max(0.01, self._zoom))
        corners = [
            (ox, oy), (ox + w, oy),
            (ox, oy + h), (ox + w, oy + h),
        ]
        for px, py in corners:
            self._draw_handle_dot(canvas, px, py, r)
        if ov_type == "shape":
            # Rotate handle ~20 screen-px above the top edge
            rh_off = 20.0 / max(0.01, self._zoom)
            rhx = ox + w / 2
            rhy = oy - rh_off
            # Connector line (dashed)
            conn = skia.Paint()
            conn.setAntiAlias(True)
            conn.setStyle(skia.Paint.kStroke_Style)
            conn.setColor(skia.Color(*self._SEL_LINE_COLOR))
            conn.setStrokeWidth(max(1.0, 1.0 / max(0.01, self._zoom)))
            conn_dash = self._get_dash_effect((3.0, 3.0))
            if conn_dash is not None:
                conn.setPathEffect(conn_dash)
            canvas.drawLine(rhx, oy, rhx, rhy, conn)
            # Rotate handle circle
            rot_fill = skia.Paint()
            rot_fill.setAntiAlias(True)
            rot_fill.setStyle(skia.Paint.kFill_Style)
            rot_fill.setColor(skia.Color(*self._ROTATE_FILL))
            canvas.drawCircle(rhx, rhy,
                              max(4.0, 6.0 / max(0.01, self._zoom)),
                              rot_fill)
            rot_border = skia.Paint()
            rot_border.setAntiAlias(True)
            rot_border.setStyle(skia.Paint.kStroke_Style)
            rot_border.setStrokeWidth(max(1.0, 1.0 / max(0.01, self._zoom)))
            rot_border.setColor(skia.Color(*self._HANDLE_BORDER))
            canvas.drawCircle(rhx, rhy,
                              max(4.0, 6.0 / max(0.01, self._zoom)),
                              rot_border)
            # Tail handle for bubbles
            if getattr(ov, "shape_kind", "") in ("speech_bubble", "thought_bubble"):
                tx = float(getattr(ov, "tail_x", 0) or 0)
                ty = float(getattr(ov, "tail_y", 0) or 0)
                if tx or ty:
                    tp = skia.Paint()
                    tp.setAntiAlias(True)
                    tp.setStyle(skia.Paint.kFill_Style)
                    tp.setColor(skia.Color(*self._TAIL_FILL))
                    canvas.drawCircle(tx, ty,
                                      max(4.0, 6.0 / max(0.01, self._zoom)),
                                      tp)

    def _draw_handle_dot(self, canvas, cx, cy, r):
        """Filled white square with dark border — standard corner handle."""
        rect = skia.Rect.MakeLTRB(cx - r, cy - r, cx + r, cy + r)
        fp = skia.Paint()
        fp.setAntiAlias(True)
        fp.setStyle(skia.Paint.kFill_Style)
        fp.setColor(skia.Color(*self._HANDLE_FILL))
        canvas.drawRect(rect, fp)
        bp = skia.Paint()
        bp.setAntiAlias(True)
        bp.setStyle(skia.Paint.kStroke_Style)
        bp.setStrokeWidth(max(1.0, 1.0 / max(0.01, self._zoom)))
        bp.setColor(skia.Color(*self._HANDLE_BORDER))
        canvas.drawRect(rect, bp)

    def _draw_draft_shape(self, canvas, draft):
        """Render the in-progress shape from tool-drag state. Dashed
        outline to signal 'not committed yet'."""
        kind = draft.get("kind", "rect")
        color_hex = draft.get("color", "#88ccff")
        rgba = self._parse_hex(color_hex, (0x88, 0xcc, 0xff, 0xff))
        sw = float(draft.get("stroke_width", 1.5))
        paint = skia.Paint()
        paint.setAntiAlias(True)
        paint.setStyle(skia.Paint.kStroke_Style)
        paint.setColor(skia.Color(*rgba))
        paint.setStrokeWidth(max(1.0, sw / max(0.01, self._zoom)))
        dash = self._get_dash_effect((6.0, 4.0))
        if dash is not None:
            paint.setPathEffect(dash)
        if kind == "rect":
            x = float(draft.get("x", 0))
            y = float(draft.get("y", 0))
            w = float(draft.get("w", 0))
            h = float(draft.get("h", 0))
            canvas.drawRect(skia.Rect.MakeXYWH(x, y, w, h), paint)
        elif kind == "ellipse":
            x = float(draft.get("x", 0))
            y = float(draft.get("y", 0))
            w = float(draft.get("w", 0))
            h = float(draft.get("h", 0))
            canvas.drawOval(skia.Rect.MakeXYWH(x, y, w, h), paint)
        elif kind in ("line", "arrow"):
            x1 = float(draft.get("x", 0))
            y1 = float(draft.get("y", 0))
            x2 = float(draft.get("x2", 0))
            y2 = float(draft.get("y2", 0))
            # Draft uses round caps for a softer look
            paint.setStrokeCap(skia.Paint.kRound_Cap)
            canvas.drawLine(x1, y1, x2, y2, paint)

    def _draw_snap_guides(self, canvas):
        """Dashed cyan lines over the canvas for snap-alignment feedback."""
        gp = skia.Paint()
        gp.setAntiAlias(True)
        gp.setStyle(skia.Paint.kStroke_Style)
        gp.setColor(skia.Color(*self._SNAP_COLOR))
        gp.setStrokeWidth(max(1.0, 1.0 / max(0.01, self._zoom)))
        dash = self._get_dash_effect((4.0, 3.0))
        if dash is not None:
            gp.setPathEffect(dash)
        for seg in self._snap_guides:
            try:
                x1, y1, x2, y2 = seg
                canvas.drawLine(float(x1), float(y1),
                                 float(x2), float(y2), gp)
            except Exception:
                continue

    # ------------------------------------------------------------------
    # Day 6 — arrow + censor overlays
    # ------------------------------------------------------------------

    def _draw_overlay_arrow(self, canvas, ov):
        """Render an arrow overlay. Line from (x, y) to (end_x, end_y)
        with an arrowhead at the tip. Optional double-heading."""
        if not ov.enabled:
            return
        x1 = float(getattr(ov, "x", 0) or 0)
        y1 = float(getattr(ov, "y", 0) or 0)
        x2 = float(getattr(ov, "end_x", 0) or 0)
        y2 = float(getattr(ov, "end_y", 0) or 0)
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1:
            return
        color_hex = getattr(ov, "color", "#000000") or "#000000"
        rgba = self._parse_hex(color_hex, (0, 0, 0, 255))
        opacity = float(getattr(ov, "opacity", 1.0) or 1.0)
        stroke_w = max(1.0, float(getattr(ov, "stroke_width", 4) or 4))
        # Line paint
        lp = skia.Paint()
        lp.setAntiAlias(True)
        lp.setStyle(skia.Paint.kStroke_Style)
        lp.setColor(skia.Color(*rgba))
        lp.setAlphaf(opacity)
        lp.setStrokeWidth(stroke_w)
        lp.setStrokeCap(skia.Paint.kRound_Cap)
        style = getattr(ov, "line_style", "solid") or "solid"
        if style in ("dash", "dot"):
            intervals = ((stroke_w * 3, stroke_w * 2) if style == "dash"
                         else (stroke_w, stroke_w))
            dash = self._get_dash_effect(intervals)
            if dash is not None:
                lp.setPathEffect(dash)
        canvas.drawLine(x1, y1, x2, y2, lp)
        # Arrowhead
        head_style = getattr(ov, "arrowhead_style", "filled") or "filled"
        if head_style == "none":
            return
        ux, uy = dx / length, dy / length
        hs = max(6.0, float(getattr(ov, "arrowhead_size", 12) or 12))
        px, py = -uy, ux

        def _head(tip_x, tip_y, direction):
            base_x = tip_x - direction * ux * hs
            base_y = tip_y - direction * uy * hs
            p1 = (base_x + px * hs * 0.5, base_y + py * hs * 0.5)
            p2 = (base_x - px * hs * 0.5, base_y - py * hs * 0.5)
            path = skia.Path()
            path.moveTo(tip_x, tip_y)
            path.lineTo(*p1)
            path.lineTo(*p2)
            path.close()
            hp = skia.Paint()
            hp.setAntiAlias(True)
            if head_style == "outline":
                hp.setStyle(skia.Paint.kStroke_Style)
                hp.setStrokeWidth(max(1.0, stroke_w * 0.5))
            else:
                hp.setStyle(skia.Paint.kFill_Style)
            hp.setColor(skia.Color(*rgba))
            hp.setAlphaf(opacity)
            canvas.drawPath(path, hp)

        _head(x2, y2, 1)
        if getattr(ov, "double_headed", False):
            _head(x1, y1, -1)

    def _draw_censor(self, canvas, censor, base_image):
        """Render a censor region. style='black'/'white' is a solid
        fill; style='blur' uses SkImageFilters.Blur on a crop of the
        base image. style='pixelate' scales down-then-up via nearest
        to produce the blocky pixelate effect.
        """
        x = float(getattr(censor, "x", 0) or 0)
        y = float(getattr(censor, "y", 0) or 0)
        w = float(getattr(censor, "w", 0) or 0)
        h = float(getattr(censor, "h", 0) or 0)
        if w <= 0 or h <= 0:
            return
        rect = skia.Rect.MakeXYWH(x, y, w, h)
        style = getattr(censor, "style", "black") or "black"
        if style == "black":
            p = skia.Paint()
            p.setColor(skia.Color(0, 0, 0, 255))
            p.setStyle(skia.Paint.kFill_Style)
            canvas.drawRect(rect, p)
            return
        if style == "white":
            p = skia.Paint()
            p.setColor(skia.Color(255, 255, 255, 255))
            p.setStyle(skia.Paint.kFill_Style)
            canvas.drawRect(rect, p)
            return
        if style == "blur":
            if base_image is None:
                return
            radius = float(getattr(censor, "blur_radius", 20) or 20)
            # Crop the base image to the censor rect, blur, draw back.
            src_rect = skia.Rect.MakeXYWH(x, y, w, h)
            paint = skia.Paint()
            paint.setImageFilter(
                skia.ImageFilters.Blur(radius, radius, None))
            # saveLayer bounds the blur's effective area to the rect.
            canvas.saveLayer(src_rect, paint)
            canvas.drawImageRect(base_image, src_rect, src_rect)
            canvas.restore()
            return
        if style == "pixelate":
            if base_image is None:
                return
            ratio = max(2, int(getattr(censor, "pixelate_ratio", 10) or 10))
            # Downscale-upscale via drawImageRect with nearest sampling.
            small_w = max(1, int(w / ratio))
            small_h = max(1, int(h / ratio))
            sampling = skia.SamplingOptions(
                skia.FilterMode.kNearest, skia.MipmapMode.kNone)
            # Cache the down-sampled intermediate. Invalidates naturally
            # when the base image is reloaded (_pixelate_cache is cleared
            # in set_base_image_path). Without the cache, every paint
            # allocates a fresh SkSurface + copies pixels — tens of MB
            # per frame for a full-canvas pixelate censor.
            cache = getattr(self, "_pixelate_cache", None)
            if cache is None:
                cache = {}
                self._pixelate_cache = cache
            key = (id(base_image), int(x), int(y), int(w), int(h),
                   ratio, small_w, small_h)
            small_img = cache.get(key)
            if small_img is None:
                small_info = skia.ImageInfo.Make(
                    small_w, small_h,
                    skia.ColorType.kRGBA_8888_ColorType,
                    skia.AlphaType.kPremul_AlphaType)
                tmp = skia.Surface.MakeRaster(small_info)
                if tmp is None:
                    return
                tmp_canvas = tmp.getCanvas()
                tmp_canvas.drawImageRect(
                    base_image,
                    skia.Rect.MakeXYWH(x, y, w, h),
                    skia.Rect.MakeXYWH(0, 0, small_w, small_h),
                    sampling, skia.Paint())
                try:
                    tmp_canvas.flush()
                except AttributeError:
                    pass
                small_img = tmp.makeImageSnapshot()
                cache[key] = small_img
            canvas.drawImageRect(
                small_img,
                skia.Rect.MakeXYWH(0, 0, small_w, small_h),
                rect, sampling, skia.Paint())

    def _draw_overlay_image(self, canvas, ov):
        """Render an image overlay (watermark / logo). Day-3 scope:
        position, scale, opacity, rotation, flip, blend mode. No
        per-pixel filter effects (grayscale / blur / brightness) yet —
        those arrive with Day 4 text + filter pipeline infrastructure.
        """
        img = self._skia_image_for_overlay(ov)
        if img is None:
            return
        if not ov.enabled:
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
        t0 = self._fps_time.perf_counter()
        canvas = self._surface.getCanvas()
        canvas.save()
        canvas.clear(skia.Color(32, 32, 40))
        # Day 11: apply devicePixelRatio scale so logical-pixel coords
        # (what the rest of the code uses) render at physical resolution
        # on high-DPI screens. pan_x/pan_y are in logical pixels too.
        dpr = getattr(self, "_dpr", 1.0)
        if dpr != 1.0:
            canvas.scale(dpr, dpr)
        # Apply pan + zoom.
        canvas.translate(self._pan_x, self._pan_y)
        canvas.scale(self._zoom, self._zoom)
        # Base image. paint omitted so Skia uses its internal default —
        # prior code allocated a fresh default skia.Paint every frame
        # for no configuration.
        if self._base_image is not None:
            canvas.drawImage(self._base_image, 0, 0)
        # Overlays (Day 3: image overlays only; text + shapes come Day 4/5).
        # Draw in list order — caller is responsible for z-order via
        # the order it passes to set_overlays().
        for ov in self._overlays:
            ov_type = getattr(ov, "type", "")
            if ov_type in ("watermark", "logo"):
                self._draw_overlay_image(canvas, ov)
            elif ov_type == "text":
                self._draw_overlay_text(canvas, ov)
            elif ov_type == "shape":
                self._draw_overlay_shape(canvas, ov)
            elif ov_type == "arrow":
                self._draw_overlay_arrow(canvas, ov)
        # Censors draw after overlays so they cover / blur content.
        for cr in self._censors:
            self._draw_censor(canvas, cr, self._base_image)
        # Day 7: selection decorators (dashed bbox + corner handles +
        # rotate handle) drawn above everything so they're visible
        # even when the selected overlay is under another.
        for ov in self._overlays:
            if id(ov) in self._selected_ids:
                self._draw_selection_decor(canvas, ov)
        # Draft shape (in-progress tool drag) drawn above everything
        # except snap guides so it remains visible during creation.
        if self._draft_shape is not None:
            self._draw_draft_shape(canvas, self._draft_shape)
        # Snap guides drawn last, cyan dashed lines.
        if self._snap_guides:
            self._draw_snap_guides(canvas)
        canvas.restore()
        # HUD — always at screen pixels (no transform).
        # Reuse paint + font across frames; they have no per-frame
        # state. Matches the CanvasSkiaGL HUD cache path.
        hud_paint = getattr(self, "_hud_paint", None)
        if hud_paint is None:
            hud_paint = skia.Paint()
            hud_paint.setColor(skia.Color(220, 220, 220, 200))
            hud_paint.setAntiAlias(True)
            self._hud_paint = hud_paint
        font = getattr(self, "_hud_font", None)
        if font is None:
            font = skia.Font(skia.Typeface("Consolas"), 11)
            self._hud_font = font
        dpr = getattr(self, "_dpr", 1.0)
        # Use paint_ms from the PREVIOUS frame; current frame's ms isn't
        # known until after drawString returns.
        prev_ms = self._fps_last_ms
        text = (f"SKIA  zoom={self._zoom:.2f}  "
                f"pan=({int(self._pan_x)},{int(self._pan_y)})  "
                f"ovl={len(self._overlays)}  dpr={dpr:.1f}  "
                f"paint={prev_ms:.1f}ms")
        # HUD drawn at physical px — so position adjusts by DPR too so
        # it still lands in the top-left corner of the widget.
        canvas.drawString(text, 12 * dpr, 20 * dpr, font, hud_paint)
        # Copy Skia's backing store into the QImage so Qt can blit it.
        # Skia's Surface.MakeRaster allocates its own buffer; we pull
        # it into Qt's buffer via readPixels.
        try:
            canvas.flush()
        except AttributeError:
            pass
        self._copy_skia_to_qimage()
        # Day 13: record paint time, update rolling average, emit perf
        # log sample if a log file is wired up.
        t1 = self._fps_time.perf_counter()
        self._fps_last_ms = (t1 - t0) * 1000.0
        self._fps_rolling_ms = (0.9 * self._fps_rolling_ms
                                 + 0.1 * self._fps_last_ms)
        self._fps_samples.append(t1)
        cutoff = t1 - 2.0
        while self._fps_samples and self._fps_samples[0] < cutoff:
            self._fps_samples.pop(0)
        if self._fps_perf_log is not None:
            try:
                # _fps_samples is strictly monotonic; bisect is O(log N)
                # vs the generator's O(N).
                fps = len(self._fps_samples) - bisect.bisect_left(
                    self._fps_samples, t1 - 1.0)
                self._fps_perf_log.write(json.dumps({
                    "t": round(t1, 4),
                    "type": "skia_paint",
                    "fps": fps,
                    "paint_ms": round(self._fps_last_ms, 2),
                    "avg_ms": round(self._fps_rolling_ms, 2),
                    "overlays": len(self._overlays),
                    "censors": len(self._censors),
                    "zoom": round(self._zoom, 3),
                }) + "\n")
                self._fps_perf_log.flush()
            except Exception:
                pass

    def _copy_skia_to_qimage(self):
        """Readback Skia's rendered pixels into self._qimg."""
        if self._surface is None or self._qimg is None:
            return
        try:
            # Cache the ImageInfo by (w, h, format) — canvas size is
            # stable for long stretches and re-allocating the info
            # every paint was pure churn. Invalidated naturally when
            # the window is resized (the key flips).
            w = self._qimg.width()
            h = self._qimg.height()
            cur = getattr(self, "_readback_info_key", None)
            info = getattr(self, "_readback_info", None)
            if cur != (w, h) or info is None:
                info = skia.ImageInfo.Make(
                    w, h,
                    skia.ColorType.kRGBA_8888_ColorType,
                    skia.AlphaType.kPremul_AlphaType,
                )
                self._readback_info = info
                self._readback_info_key = (w, h)
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


# ----------------------------------------------------------------------
# GL plan Tier 2 Day 1 — Skia Ganesh GPU backend via QOpenGLWidget
# ----------------------------------------------------------------------

try:
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    _QOGW_OK = True
except Exception:  # pragma: no cover
    _QOGW_OK = False


class CanvasSkiaGL(CanvasSkia if False else object):
    """Skia GPU-backed canvas. Wraps Qt's GL context via
    skia.GrDirectContext.MakeGL() and renders into a backend render
    target bound to the QOpenGLWidget's default FBO.

    Shares the overlay / censor / selection / hit-test API with
    CanvasSkia — only the render surface differs. This is the Tier 2
    target from docs/gl-canvas-plan.md: all the per-shape paths we
    wrote for CanvasSkia become shader-accelerated batches inside
    Ganesh's atlas/path cache.

    Tier 2 Day 1 scope: class exists, initializes GrDirectContext,
    allocates a backend-bound Surface on resize, wires paintGL to
    the same _render_to_skia() used by the raster path. No overlays,
    no hit-test integration yet — that arrives Day 2 when we prove
    the context round-trips correctly on the target hardware.

    Inherits at runtime from QOpenGLWidget if available, else refuses
    instantiation. Use canvas_skia_gl_available() before constructing.
    """

    # Placeholder for the real runtime class definition below. This
    # outer class body exists only so `from canvas_skia import
    # CanvasSkiaGL` always resolves (static references in other
    # modules don't crash at import time when QtOpenGLWidgets is
    # missing on the platform).


if _QOGW_OK and _SKIA_OK:
    class CanvasSkiaGL(QOpenGLWidget):  # type: ignore[no-redef]
        """Real CanvasSkiaGL — only defined when QOpenGLWidget and
        skia are both importable. See the placeholder above for the
        full intent."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("studio_canvas_skia_gl")
            self._gr_context = None           # skia.GrDirectContext
            self._surface = None              # skia.Surface
            self._base_image = None           # skia.Image | None
            self._overlays: list = []
            self._censors: list = []
            self._selected_ids: set = set()
            self._snap_guides: list = []
            self._draft_shape: dict | None = None
            self._overlay_image_cache: dict = {}
            # Shared with CanvasSkia's _draw_overlay_text path — the
            # helpers are bound methods on this instance (see below), so
            # they read these attrs directly. Without these caches every
            # paintGL would rebuild every typeface/font from scratch.
            self._skia_typeface_cache: dict = {}
            self._skia_font_cache: dict = {}
            self._skia_path_cache: dict = {}
            self._skia_dash_cache: dict = {}
            self._zoom = 1.0
            self._pan_x = 0.0
            self._pan_y = 0.0
            self._panning = False
            self._pan_start = QPointF(0, 0)
            self._dpr = float(self.devicePixelRatioF() or 1.0)
            self.backend_name = "skia_gl"
            # Error trail for context loss / init failure. Surfaced
            # to the perf log's session_start event and shown in the
            # HUD if present.
            self._last_init_error: str = ""
            # Perf timing — same shape as CanvasSkia so the same perf
            # log consumer works.
            import time as _t
            self._fps_time = _t
            self._fps_last_ms = 0.0
            self._fps_rolling_ms = 0.0
            self._fps_samples: list = []
            self._fps_perf_log = None
            # Shared drawing helpers from CanvasSkia — mirror as
            # unbound methods so we don't reimplement the per-shape
            # render paths.
            self._draw_overlay_image = CanvasSkia._draw_overlay_image.__get__(self)
            self._draw_overlay_text = CanvasSkia._draw_overlay_text.__get__(self)
            self._draw_overlay_shape = CanvasSkia._draw_overlay_shape.__get__(self)
            self._draw_overlay_arrow = CanvasSkia._draw_overlay_arrow.__get__(self)
            self._draw_censor = CanvasSkia._draw_censor.__get__(self)
            self._draw_selection_decor = CanvasSkia._draw_selection_decor.__get__(self)
            self._draw_snap_guides = CanvasSkia._draw_snap_guides.__get__(self)
            self._draw_draft_shape = CanvasSkia._draw_draft_shape.__get__(self)
            self._selection_bbox_local = CanvasSkia._selection_bbox_local.__get__(self)
            self._skia_image_for_overlay = CanvasSkia._skia_image_for_overlay.__get__(self)
            self._build_shape_path = CanvasSkia._build_shape_path.__get__(self)
            self._append_star_path = CanvasSkia._append_star_path.__get__(self)
            self._append_polygon_path = CanvasSkia._append_polygon_path.__get__(self)
            self._append_burst_path = CanvasSkia._append_burst_path.__get__(self)
            self._append_speech_bubble_path = CanvasSkia._append_speech_bubble_path.__get__(self)
            self._append_thought_bubble_path = CanvasSkia._append_thought_bubble_path.__get__(self)
            self._fill_gradient = CanvasSkia._fill_gradient.__get__(self)
            self._blend_mode_for = CanvasSkia._blend_mode_for.__get__(self)
            self._parse_hex = CanvasSkia._parse_hex  # staticmethod
            # Constants
            for k in ("_SEL_LINE_COLOR", "_HANDLE_FILL", "_HANDLE_BORDER",
                      "_ROTATE_FILL", "_TAIL_FILL", "_SNAP_COLOR",
                      "_BLEND_MODE_SKIA"):
                if hasattr(CanvasSkia, k):
                    setattr(self, k, getattr(CanvasSkia, k))
            self._draw_handle_dot = CanvasSkia._draw_handle_dot.__get__(self)

        # ---- GL lifecycle ----

        def initializeGL(self):
            """Called once after the GL context is current. Build the
            Ganesh direct context wrapping this widget's GL context.

            Also hook aboutToBeDestroyed so we can release Skia's GL
            resources (textures, programs) BEFORE the context goes
            away — otherwise Skia dereferences a dead context on its
            next cleanup cycle and segfaults."""
            try:
                self._gr_context = skia.GrDirectContext.MakeGL()
                self._last_init_error = ""
            except Exception as e:
                self._gr_context = None
                self._last_init_error = str(e)
            # Context-loss hook: QOpenGLContext emits aboutToBeDestroyed
            # on hybrid-GPU switch or widget teardown. We release the
            # GrDirectContext there; the next paint will re-init.
            try:
                ctx = self.context()
                if ctx is not None:
                    ctx.aboutToBeDestroyed.connect(self._release_gl)
            except Exception:
                pass

        def _release_gl(self):
            """Called when the GL context is about to die (hybrid GPU
            switch, widget teardown). Release Skia's GL resources so
            they don't dangle. Next paint kicks off re-init."""
            try:
                if self._gr_context is not None:
                    self._gr_context.abandonContext()
            except Exception:
                pass
            self._gr_context = None
            self._surface = None

        def resizeGL(self, w: int, h: int):
            """Rebuild the backend render target + Surface whenever
            the widget resizes (framebuffer changes)."""
            if self._gr_context is None:
                # Context might have been released by _release_gl on a
                # GPU switch. Attempt to re-init; if it still fails,
                # paintGL will early-return until next resize.
                try:
                    self._gr_context = skia.GrDirectContext.MakeGL()
                except Exception as e:
                    self._last_init_error = str(e)
                    self._gr_context = None
                    return
            if self._gr_context is None:
                return
            dpr = float(self.devicePixelRatioF() or 1.0)
            self._dpr = dpr
            pw = max(1, int(w * dpr))
            ph = max(1, int(h * dpr))
            try:
                # QOpenGLWidget composites into its OWN FBO, not GL FBO 0.
                # The default framebuffer ID must be queried every resize
                # because Qt may recreate the compositing FBO when the
                # widget is shown/hidden or the surface format changes.
                # Passing 0 here worked only when QOpenGLWidget happened
                # to be the sole top-level GL widget (fbo 0 = window fb);
                # in a layout with other widgets Qt allocates a non-zero
                # fbo for composition and drawing to 0 would write to
                # the wrong surface, producing blank or garbled output.
                fbo_id = int(self.defaultFramebufferObject() or 0)
                # 0 stencil, kRGBA8 format.
                backend_rt = skia.GrBackendRenderTarget(
                    pw, ph, 0, 8, skia.GrGLFramebufferInfo(
                        fbo_id, 0x8058  # GL_RGBA8
                    ))
                self._surface = skia.Surface.MakeFromBackendRenderTarget(
                    self._gr_context,
                    backend_rt,
                    skia.kBottomLeft_GrSurfaceOrigin,
                    skia.ColorType.kRGBA_8888_ColorType,
                    None, None,
                )
                if self._surface is None:
                    self._last_init_error = (
                        f"MakeFromBackendRenderTarget returned None "
                        f"(fbo={fbo_id} {pw}x{ph})")
                else:
                    # Remember which FBO this surface was built for so
                    # paintGL can rebuild if Qt swaps the backing FBO
                    # out from under us.
                    self._surface_fbo = fbo_id
            except Exception as e:
                self._surface = None
                self._last_init_error = str(e)

        def paintGL(self):
            """Draw the scene via Skia into the GL surface. paintGL
            fires whenever the widget needs redraw; Qt has already
            made our GL context current."""
            # Lazy re-init: if the surface is gone (context loss) but
            # we're back here, rebuild. Happens on hybrid-GPU laptops
            # when the OS switches between integrated + discrete GPUs.
            if self._surface is None and self._gr_context is not None:
                self.resizeGL(self.width(), self.height())
            # FBO-ID drift: Qt can re-allocate the QOpenGLWidget's
            # composition FBO between paintGL calls (e.g. when the
            # widget is hidden+reshown, or the surface format changes).
            # The Skia surface was built against the old FBO; if we
            # don't rebuild, paintGL draws to the wrong target.
            cur_fbo = int(self.defaultFramebufferObject() or 0)
            if (self._surface is not None
                    and getattr(self, "_surface_fbo", -1) != cur_fbo):
                self.resizeGL(self.width(), self.height())
            if self._surface is None or self._gr_context is None:
                # Fell through re-init — paint nothing; hopefully next
                # resize event will succeed.
                return
            t0 = self._fps_time.perf_counter()
            try:
                canvas = self._surface.getCanvas()
                canvas.save()
                canvas.clear(skia.Color(32, 32, 40))
                # DPR scale for high-DPI
                if self._dpr != 1.0:
                    canvas.scale(self._dpr, self._dpr)
                # Pan + zoom
                canvas.translate(self._pan_x, self._pan_y)
                canvas.scale(self._zoom, self._zoom)
                # Base + overlays (reuses CanvasSkia helpers bound in __init__)
                # paint omitted — Skia uses an internal default when absent.
                if self._base_image is not None:
                    canvas.drawImage(self._base_image, 0, 0)
                for ov in self._overlays:
                    t = getattr(ov, "type", "")
                    if t in ("watermark", "logo"):
                        self._draw_overlay_image(canvas, ov)
                    elif t == "text":
                        self._draw_overlay_text(canvas, ov)
                    elif t == "shape":
                        self._draw_overlay_shape(canvas, ov)
                    elif t == "arrow":
                        self._draw_overlay_arrow(canvas, ov)
                for cr in self._censors:
                    self._draw_censor(canvas, cr, self._base_image)
                for ov in self._overlays:
                    if id(ov) in self._selected_ids:
                        self._draw_selection_decor(canvas, ov)
                if self._draft_shape is not None:
                    self._draw_draft_shape(canvas, self._draft_shape)
                if self._snap_guides:
                    self._draw_snap_guides(canvas)
                canvas.restore()
                # HUD (screen-space, outside the pan/zoom transform).
                # Shows backend + perf-ms so GPU vs CPU comparison is
                # visible in-app without flipping to the perf log.
                self._draw_gl_hud(canvas)
                self._surface.flushAndSubmit()
            except Exception:
                pass
            t1 = self._fps_time.perf_counter()
            self._fps_last_ms = (t1 - t0) * 1000.0
            self._fps_rolling_ms = (0.9 * self._fps_rolling_ms
                                     + 0.1 * self._fps_last_ms)
            self._fps_samples.append(t1)
            cutoff = t1 - 2.0
            while self._fps_samples and self._fps_samples[0] < cutoff:
                self._fps_samples.pop(0)

        def _draw_gl_hud(self, canvas):
            """Draw the Skia-GL HUD line: backend + zoom + paint-ms.
            Matches the style of the CanvasSkia CPU HUD so visual
            comparison across the Shift+S backend picker is immediate."""
            try:
                # Reuse the paint + font across frames — they have no
                # per-frame state. Prior code allocated a fresh
                # skia.Typeface("Consolas") every paint which is a
                # system font lookup; the HUD alone was accounting for
                # the equivalent of 60 font-lookups/sec at 60fps.
                paint = getattr(self, "_hud_paint", None)
                if paint is None:
                    paint = skia.Paint()
                    paint.setColor(skia.Color(220, 220, 220, 210))
                    paint.setAntiAlias(True)
                    self._hud_paint = paint
                font = getattr(self, "_hud_font", None)
                if font is None:
                    font = skia.Font(skia.Typeface("Consolas"), 11)
                    self._hud_font = font
                prev = self._fps_last_ms
                # Bisect over the strictly-monotonic _fps_samples is
                # O(log N) vs the generator's O(N).
                fps = len(self._fps_samples) - bisect.bisect_left(
                    self._fps_samples,
                    self._fps_time.perf_counter() - 1.0)
                dpr = getattr(self, "_dpr", 1.0)
                err = f"  err={self._last_init_error}" if self._last_init_error else ""
                txt = (f"SKIA-GL  zoom={self._zoom:.2f}  "
                       f"ovl={len(self._overlays)}  dpr={dpr:.1f}  "
                       f"paint={prev:.2f}ms  fps={fps}{err}")
                canvas.drawString(txt, 12 * dpr, 20 * dpr, font, paint)
            except Exception:
                pass

        # Minimal overlay API — enough for the preview to render data.
        def set_base_image_path(self, path: str):
            try:
                data = skia.Data.MakeFromFileName(str(path))
                if data is None:
                    return
                self._base_image = skia.Image.MakeFromEncoded(data)
            except Exception:
                self._base_image = None
            pc = getattr(self, "_pixelate_cache", None)
            if pc:
                pc.clear()
            self.update()

        def set_overlays(self, overlays):
            new_list = list(overlays)
            # Mirror CanvasSkia.set_overlays' cache prunes — the GL
            # subclass uses the same _build_shape_path helper (bound as
            # a method in __init__) which writes into _skia_path_cache,
            # and the same _skia_image_for_overlay helper which writes
            # into _overlay_image_cache.
            if self._skia_path_cache:
                live_ids = {id(ov) for ov in new_list}
                self._skia_path_cache = {
                    k: v for k, v in self._skia_path_cache.items()
                    if k in live_ids
                }
            if self._overlay_image_cache:
                live_paths = {
                    getattr(ov, "image_path", "") for ov in new_list
                    if getattr(ov, "image_path", "")
                }
                self._overlay_image_cache = {
                    p: img for p, img in self._overlay_image_cache.items()
                    if p in live_paths
                }
            self._overlays = new_list
            self.update()

        def set_censors(self, censors):
            self._censors = list(censors)
            self.update()

        def base_size(self) -> QSize:
            if self._base_image is None:
                return QSize(0, 0)
            return QSize(self._base_image.width(), self._base_image.height())

        def set_zoom(self, z: float):
            self._zoom = max(0.05, min(32.0, z))
            self.update()


def canvas_skia_gl_available() -> bool:
    """Return True if CanvasSkiaGL can be instantiated on this platform.
    Gate construction on this; falls back to CPU CanvasSkia otherwise."""
    return _QOGW_OK and _SKIA_OK
