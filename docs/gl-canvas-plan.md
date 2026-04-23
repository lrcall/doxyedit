# DoxyEdit — GL Canvas Plan

A dedicated, executable plan for getting GPU-accelerated rendering into
Studio. Three tiers from lowest-risk-lowest-win to highest-win-highest-
risk. Each tier is shippable on its own; higher tiers build on lower.

## Context

- QGraphicsView currently uses Qt's CPU raster paint engine. Per-frame
  blit cost is the bottleneck on large canvases / many overlays.
- I already committed scaffolding (`canvas_skia.py`) that uses Skia's
  CPU raster. That's useful for correctness testing but doesn't win
  the GPU-composite throughput fight.
- The gap between "current raster" and "actual GPU render" is filled
  by these three tiers.

## State of the GL work today

Already landed:

- **`a992abe`** — `QOpenGLWidget` can be used as the QGraphicsView
  viewport via the `studio_use_gl_viewport` QSettings key. Default
  off because it forces `FullViewportUpdate`, which on the current
  tuned raster path is net slower.
- **`canvas_skia.py`** — CPU raster Skia backend with every overlay
  type ported. Renders via `skia.Surface.MakeRaster` + readback into
  a QImage that gets blitted via QPainter.
- **Shift+S preview** — dedicated window shows the CPU Skia render
  of the live asset, auto-refreshes every 500ms.

This plan goes further: actually GPU-composite the scene.

---

## Tier 1 — QOpenGLWidget viewport, smart opt-in (1–2 days)

Minimum intervention. Keep the whole QGraphicsView stack, just swap
the viewport widget. Qt's GL paint engine takes over compositing.

**Day 1 — re-enable + measure**

- Flip `studio_use_gl_viewport` default back to `True` BEHIND a
  detection gate: probe at startup via `QOpenGLContext.create()` to
  confirm a usable context. If it fails, silently fall back to raster.
- Add a perf-log tag indicating which backend is active per session.
- Re-measure on the same benchmark scenes that produced the 9→31 FPS
  win in the raster path. Confirm GL is equal or better, not worse.

**Day 2 — fix the FullViewportUpdate regression**

Root cause of why GL was slower: Qt requires `FullViewportUpdate`
when the viewport is a GL widget, and the raster path's tuned
`MinimalViewportUpdate` + item caches win on small dirty rects.

Fix strategies (pick one):

- **(a)** Render only dirty items into a persistent offscreen FBO,
  composite to screen via `glBlitFramebuffer`. Qt has
  `QOpenGLFramebufferObject` for this.
- **(b)** Skip Qt's dirty-rect machinery entirely — override
  `paintGL` on the viewport, walk scene items ourselves, call
  `item.paint(painter, option, widget)` with the GL-backed QPainter.
  This is what Qt does internally but doing it ourselves lets us
  pin the dirty region to the moving overlay's swept rect.

Target: GL path matches or beats the raster path on every
benchmarked scene. Ship it as default-on if so.

**Deliverable:** GL viewport wins for users on modern GPUs; raster
remains as automatic fallback on Intel HD / Windows without proper
drivers.

**Risk:** medium. GL driver quirks, high-DPI scaling, hybrid-GPU
context loss.

**Ceiling:** ~2x perf ceiling over raster. Not the big win.

---

## Tier 2 — Skia-GPU backend via GrDirectContext (4–7 days)

The real win. Take the canvas_skia.py CPU raster surface and swap
it for Skia's `GrDirectContext`-backed GPU surface wrapping Qt's
GL context. Skia's Ganesh renderer (same one Chrome uses) handles
batching, atlas caching, shader compilation.

**Day 1 — GL context handoff**

- `CanvasSkia` inherits from `QOpenGLWidget` instead of QWidget.
- `initializeGL()` creates a `skia.GrDirectContext.MakeGL()` wrapping
  the already-current GL context.
- `resizeGL()` tears down + rebuilds the `skia.Surface.MakeFromBackendRenderTarget`
  so it wraps the new backing FBO.
- `paintGL()` calls existing `_render_to_skia()` but against the GL
  surface. `canvas.flush()` then `surface.flushAndSubmit()` pushes
  the batch to GL, then Qt swaps the buffer.

Reference: Skia docs on GL backend + `skia-python` binding's
`GrBackendRenderTarget` example.

**Day 2 — DPR + resize robustness**

- High-DPI is already handled on the raster path via
  `devicePixelRatioF()`. On GL, the framebuffer is at physical res
  automatically. `canvas.scale(dpr, dpr)` still applies so logical-
  pixel coords produce physical-pixel output.
- `resizeGL` tears down and rebuilds the render target. Any cached
  skia.Image handles stay valid; only the Surface recreates.

**Day 3 — context loss handling**

- Hybrid GPU laptops can lose the GL context on GPU switch.
  `QOpenGLWidget.aboutToResize` signal lets us flush cached state
  before teardown.
- Catch `skia.GrBackendContextState` invalidation and re-init on
  next paint.

**Day 4 — benchmark + harden**

- Rerun the full benchmark suite vs the raster Skia path.
- Expected: ~10x win on `thought_bubble` overdraw, ~5x on text with
  stroke+shadow (Skia's Ganesh batches those into one atlas lookup).
- Edge cases: text rendering at non-integer scale, blend modes,
  drop shadow with large blur radius.

**Day 5 — tool-drag integration**

- Currently the Shift+S preview is read-only. For GPU Skia to
  actually matter users need to edit through it. Wire mouse events
  through `hit_test_image` → direct item manipulation → repaint.
- This implicitly depends on the Day-14-full-cutover compat shim
  already committed in `935b4f6`.

**Day 6–7 — feature flag rollout**

- `studio_compositor = gl_skia` (in addition to `qgraphics` raster
  and the existing partial `skia` CPU path).
- Smoke test via `tools/skia_build_smoke.py` against the Nuitka
  onefile exe confirming `GrDirectContext.MakeGL()` doesn't fail
  in the bundled environment.
- Ship as beta: default off, Shift+S preview uses it automatically
  when a user opts in, one-week bake period, default on if no
  bug reports.

**Deliverable:** GPU-accelerated Skia render as the Shift+S preview
backend, then as a main-canvas option behind a flag.

**Risk:** medium-high. GL driver conflicts on Windows Intel HD
reportedly cause Ganesh to fall back to CPU silently. Need the
`GrDirectContext` null-check + `Surface` validation at every
re-init.

**Ceiling:** 10–20x on composite throughput. Text / shadow / filter
perf becomes sub-millisecond.

---

## Tier 3 — Custom QOpenGLWidget compositor (12–15 days)

Full replacement. No QGraphicsScene, no QGraphicsView, no Qt paint
engine. Hand-written GL draw loop + shader program, overlays are
pure data records, no QGraphicsItem subclasses.

This is the SAI2-class architecture from the deep-dive. Only pick
this if Tier 2 fundamentally underperforms on the target hardware
AND we can commit the full engineering cost.

**Core architecture**

```python
class CanvasGL(QOpenGLWidget):
    # State: base image texture, overlay list (Overlay dataclass),
    # view transform (pan + zoom).

    def initializeGL(self):
        self._program = self._build_shader_program()
        self._base_tex = self._upload_base()
        self._overlay_textures: dict[int, Texture] = {}

    def paintGL(self):
        self._apply_view_transform()
        self._draw_checker()
        self._draw_base()
        for ov in sorted(self._overlays, key=lambda o: o.z):
            self._bind_overlay_texture(ov)
            self._draw_quad(ov.bbox, rotation=ov.rotation)
        self._draw_handles_and_guides()
```

**Milestones** (see deep-dive Section 2C for the full 15-day breakdown):

- Days 1–2: shader program, base texture upload, quad primitive,
  pan/zoom via uniform matrix.
- Days 3–5: overlay textures per item, dynamic upload, draw calls
  with per-overlay blend mode.
- Days 6–7: text renderer — text rasterizes to offscreen QImage,
  uploads as glyph atlas, re-binds on font/content change.
- Days 8–9: shape renderer — SDF paths via fragment shader, or
  pre-rasterize to texture.
- Days 10–11: censor shader (solid rect + fragment-shader Gaussian
  blur for blur style).
- Days 12–13: selection handles via overlay pass, marching ants via
  time-animated dash offset.
- Days 14–15: export path rendering to offscreen FBO + readback,
  theming + settings wiring, feature-flag rollout.

**Deliverable:** a full GL canvas that completely replaces
QGraphicsView in Studio for all users.

**Risk:** high. Everything from text antialiasing quality to
Windows GL driver quirks to IME input routing has to be solved
from scratch.

**Ceiling:** matches Tier 2 (Skia Ganesh already approaches
theoretical GPU throughput), but with no Skia runtime dependency
(~45 MB bundle saved).

---

## Recommendation

**Ship Tier 1 Day 1 first, this week.** Re-enabling the GL viewport
with a detection gate is ~2 days of low-risk work that either
confirms GL is a net-win (default it on) or confirms it's not
(leave default off, unblock Tier 2). Either way we get a measurement.

**Then ship Tier 2 Days 1–4 over the following week.** That's the
first real GPU composite path. The Shift+S preview becomes a GPU-
backed render, user validates parity, we see the 10x speedup on
complex scenes.

**Tier 2 Days 5–7 iterate based on user feedback.**

**Tier 3 is reserved** for a dedicated long sprint only if Tier 2
hits a wall on the target hardware. The most likely reason to go
to Tier 3 is bundle-size pressure (the 45 MB Skia wheel), not perf.

## Kill-switch / rollback

Every tier ships behind `studio_compositor`:
- `qgraphics` — current tuned raster path (proven stable, 31 FPS).
- `gl_viewport` — Tier 1.
- `skia_cpu` — current Shift+S preview backend.
- `skia_gl` — Tier 2.
- `custom_gl` — Tier 3 (future).

Default stays at `qgraphics` during every rollout. User flips to
beta when they want to test. If a regression is reported we flip
them back; the tier in question stays opt-in until the issue is
fixed.

## Not-doing list

- **Tiled backing store** — Krita-style 64×64 tiles are a storage
  optimization for painting apps with sparse layer edits. DoxyEdit
  has one read-only base + a handful of overlays; tiling adds
  overhead with no gain.
- **Custom GLSL for each overlay shape** — Skia already has optimized
  shaders for every primitive we use. Writing our own SDF shape
  shaders is a deep rabbit hole with no perf win over Ganesh.
- **Replacing Qt input handling** — keep QGraphicsView's mouse/key
  routing. Only the render pipeline changes.

## Checkpoints

Each tier produces a measurable artifact:

- Tier 1: perf-log entry showing `gl_viewport` active + average
  paint-ms delta vs raster on same scene.
- Tier 2: Shift+S preview running on GPU, paint-ms <0.5 on a scene
  that's 3 ms on the raster Skia path.
- Tier 3: pure GL canvas, no QGraphicsScene allocated.

Without one of those artifacts, the tier isn't done.
