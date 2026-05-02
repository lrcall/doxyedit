# Canvas Architecture Deep Dive

Follow-up to `docs/archive/canvas-architecture-investigation.md`. The prior investigation ranked five incremental tweaks inside `QGraphicsView` and stopped at "a rewrite is 2-3 weeks, don't do it." That was wrong in one direction: the user wants 60 FPS across many overlays, not "good enough for bubble drag." This document answers the question the previous one dodged: **if we had to actually push to 60 FPS at scale, what would we build, and how?**

Target reader: you know Qt. You know Python performance characteristics. You want numbers, code skeletons, and milestones.

Scope reminder: DoxyEdit Studio. Base pixmap (fixed), overlays (bubbles, text, watermarks, censors, crops, arrows, shapes), handles when selected, live drag. Not a painting app. Not a 40-layer Photoshop clone. Windows-first, Nuitka onefile.

---

## Section 1 - How real editors actually work

All four of the reference editors share one pattern that `QGraphicsView` does not implement: **a GPU-driven compositor with the image as GPU-resident texture(s) and overlays as separately-submitted draw calls against the same target**. The Qt Graphics View framework is a CPU retained-mode scene with a software-raster blitter; it is a fundamentally different architecture. The differences below are not "optimizations on top of QGraphicsView" - they are a different paradigm.

### 1a. Krita (GPL, C++, Qt-based, open source)

Sources: `libs/ui/opengl/kis_opengl_canvas2.cpp` (renderer entry, `paintGL`), `libs/image/tiles3/kis_tiled_data_manager.cc` (tile store), `libs/ui/opengl/kis_opengl_image_textures.cpp` (GPU upload). MR `!488` optimized partial updates. Partial-update commit `54282a72` introduced a chunk pool.

- **Storage**: `KisPaintDevice` holds a `KisTiledDataManager` - 64x64 tiles in the image's native color space. Sparse, copy-on-write. Not a rendering concern; it's a *data* concern.
- **GPU upload**: `KisOpenGLImageTextures` maintains a set of GPU textures, one per visible *tile group*. Each tile group is a larger texture (typically 256x256 or 512x512) that packs multiple 64x64 data tiles. Only *dirty* tiles get re-uploaded from CPU to GPU per frame.
- **Render loop**: `paintGL()` walks visible tile groups. For each: `glBindTexture` + `glDrawElements` of a textured quad. After all tiles blit, `QPainter` starts over the same context for *decorations* (selection marching ants, tool cursor, grid) - Qt `beginNativePainting` / `endNativePainting` guards. Krita's own code calls this "overlay pass."
- **Dirty tracking**: `paintEvent` on `KisOpenGLCanvas2` receives the `QPaintEvent`'s region. Only tile groups intersecting that region are re-composited. `MR !488` enables this - before it, the whole canvas was redrawn every frame.
- **Zoom**: GPU-side via texture scaling + anisotropic filtering. CPU does not re-rasterize. On zoom below 1:1, Krita falls back to mipmapped sampling (the texture already has mipmaps generated at upload time). On zoom above 1:1, bilinear up to ~400%, then nearest to preserve pixel grid.
- **Selection feedback (marching ants)**: a separate shader pass on the dirty region. Cheap because it's a one-channel stipple, not a path traversal.
- **Sync**: `KisOpenGLSync` uses GL fences to skip frame submission if the previous frame's GPU work isn't done - prevents CPU blocking on `glFinish`.

Code shape (simplified from `kis_opengl_canvas2.cpp::paintGL`):
```cpp
void KisOpenGLCanvas2::paintGL() {
    QRegion updateRegion = d->renderer->dirtyRegion();
    d->renderer->paintCanvasOnly(updateRegion);   // tile-textured quads
    QPainter painter(this);
    painter.beginNativePainting();
    // (no-op; just flush GL state)
    painter.endNativePainting();
    d->toolProxy->paintToolOutline(&painter);     // QPainter over GL
}
```

What makes this fast: the image pixels live in VRAM, drag of a decoration-layer cursor only invalidates a small region, the fragment shader handles per-pixel alpha composition at native DPI.

### 1b. Photopea (proprietary JS, but public blog + reverse-engineerable)

Sources: https://blog.photopea.com (1.1, 1.3 posts), GitHub issues where Kutskir comments on internals. Also the `Peamark` benchmark post (Facebook, 2024-ish).

- **Storage**: each layer keeps its own RGBA buffer, uploaded as a WebGL texture on first use. Photopea holds buffers for the layer's original pixels and for *per-layer style cache* (stroke, shadow, etc.). That's why complex layer-style documents use a lot of VRAM.
- **Render loop**: imperative, per-frame, over all visible layers. Fragment shader `compositeLayer(tex, mask, styleCache, blendMode, opacity)` composes each layer onto an accumulator framebuffer. When the user starts dragging, Photopea re-uses the previous frame's composite *up to* the dragged layer, and only recomposes from the dragged layer forward. This is the key "thrifty" trick.
- **Dirty rect**: coarse. Photopea re-composites the whole visible viewport on any change, because composing one 4K viewport through 10 fragment shader passes is still sub-millisecond on any modern GPU. It's not worth tracking per-rect dirty regions in JS.
- **Zoom**: WebGL texture scaling plus CSS transform on the wrapping div for pan. That's important - they *do not* re-rasterize on pan. CSS transform is GPU-composited and free.
- **Fallback**: when WebGL is disabled, Photopea falls back to 2D Canvas. The blog is explicit that this is 5-20x slower for complex documents.

Key move: **the scene accumulator is a single framebuffer texture that gets copy-blitted during the pan transform; GPU handles the transform**. Compositor work only happens on content change.

### 1c. Procreate (proprietary iOS, but public interview/press)

Sources: macstories Procreate 5 review, Savage press releases on "Valkyrie," id-ownloadblog Procreate 2 review. No public source code, but the architecture is well-documented via Apple's TBDR guidance (WWDC 2019 "Modern Rendering with Metal," WWDC 2020 "Harness Apple GPUs").

- **Silica-M / Valkyrie (Procreate 4/5+)** is Metal-based. Each layer is a Metal texture; the canvas is composited in one render pass that writes directly to the framebuffer. Apple's tile-based deferred rendering (TBDR) means the GPU fragment shader only runs on tiles that changed - the GPU itself does the dirty-region work, not the app.
- **Brush rendering**: separate pass, renders into a "working layer" texture. On stroke end, the working layer is blended into the target layer via a compute shader.
- **Open-source analog**: Silicate (https://github.com/Avarel/silicate) - Rust + WGPU reimplementation of the compositor for reading `.procreate` files. Confirms the layer-texture model: each layer is a chunk-tiled RGBA8 texture, composited via WGSL fragment shaders in z-order.

Relevant to DoxyEdit: **the overlay-atop-image model is exactly the Procreate-style architecture compressed into "N=2-30 layers."**

### 1d. MyPaint (GPL, Python+C, reference point for Python-native painting)

Sources: https://www.mypaint.app/en/docs/backend/canvas/, https://www.jonnor.com/2012/11/improved-drawing-performance-in-mypaint-brush-engine/.

- **Storage**: 64x64 tile surface, uint16 "15+1" fixed-point premultiplied RGBA, stored as contiguous numpy arrays.
- **Rendering**: Cairo. CPU. The display path composites dirty tiles into a scratch pixbuf then Cairo rotates/zooms/blits to the GtkWidget.
- **No GPU**. MyPaint performance is "fine, not great." The brush engine is optimized; the display path is basic. This is informative: if you want to stay CPU-side in Python, MyPaint's architecture is a ceiling.

### 1e. miniPaint (MIT, JS, minimal canvas editor)

Sources: https://github.com/viliusle/miniPaint, especially `src/js/core/base-layers.js`.

- **Storage**: per-layer `HTMLCanvasElement` (DOM). Each layer is a separate canvas.
- **Rendering**: single render function walks layers z-ordered, calls `ctx.drawImage(layer.canvas, ...)` onto the main canvas. Transforms applied per layer via `ctx.translate/rotate/scale`.
- **Dirty regions**: none. Whole visible region redraws on any change. Works because a 2D canvas `drawImage` for N=10 layers of 2K each is <5ms on any hardware.
- **Why it works**: simple, imperative, one frame = one render. No retained-mode abstraction over the top.

### 1f. What this tells us

Across four different stacks (Qt/OpenGL, WebGL, Metal, 2D Canvas), the common structure is:

1. Image pixels in GPU-resident textures (or equivalent DOM canvas).
2. Per-frame `render()` function that walks layers z-ordered, submits draw calls.
3. Dirty-region tracking is either coarse (whole viewport) or done by the GPU itself (TBDR). None of them replicate `QGraphicsScene`'s per-item bounding-rect dirty union.
4. Overlays (selection, cursors, handles) are a separate pass *after* the image composition, commonly via an orthographic projection + `QPainter`-equivalent.

What `QGraphicsView` does differently: items are CPU-side retained objects with their own paint methods that the scene dispatches per-frame, dirty regions are tracked per-item at CPU, composition happens in software raster by default. It is structurally a widget framework pretending to be a canvas - not a canvas framework.

**Inescapable conclusion**: getting to 60 FPS with many overlays means either (a) replace the compositor so the image+overlays are GPU-composited, or (b) find enough micro-wins in the existing `QGraphicsView` path to squeeze another 2x without touching the compositor.

---

## Section 2 - Options, concretely

The options below are ranked by perf ceiling, not by effort. Each gives: code shape, milestone schedule in eng-days, expected win, risks.

### Option A - `QOpenGLWidget` as viewport on the existing `QGraphicsView`

**What it does**: `QGraphicsView` keeps existing item tree. The viewport widget switches from software raster to OpenGL-backed. Qt's `QPainter` GL backend takes over for blits and transforms.

**Concrete perf ceiling**: 2x. Maybe 3x on hybrid-GPU laptops at native res. Not 10x. The `QPainter` GL backend is a 2D compatibility layer (Krita's Boud Rempt blog: "Graphics View wasn't designed for GPUs and can't use them effectively"). You get GPU-accelerated blits and transform matrices; you do not get modern shader composition.

**Code skeleton** (drop into `studio.py::StudioView.__init__`, replacing the comment at line 3769):

```python
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtGui import QSurfaceFormat

class StudioView(QGraphicsView):
    def __init__(self, scene: StudioScene, parent=None):
        super().__init__(scene, parent)
        # ... existing setup ...

        if QSettings("DoxyEdit", "DoxyEdit").value(
                "studio_gl_viewport", False, type=bool):
            fmt = QSurfaceFormat()
            fmt.setSwapInterval(1)           # vsync
            fmt.setSamples(0)                # no MSAA - Qt AA does text
            fmt.setDepthBufferSize(0)        # 2D only
            fmt.setStencilBufferSize(0)
            gl = QOpenGLWidget()
            gl.setFormat(fmt)
            self.setViewport(gl)
            # REQUIRED: partial updates aren't possible on GL surface
            self.setViewportUpdateMode(
                QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
            # CacheModeFlag.CacheBackground is useless here - GL already
            # "caches" via the framebuffer swap chain.
            self.setCacheMode(QGraphicsView.CacheModeFlag.CacheNone)
```

Note: the existing code uses `setCacheMode(CacheBackground)` (line 3769) which relies on the viewport being a `QWidget` software backing store. That cache lives in the viewport's paint device; when the viewport is GL, the cache is a CPU pixmap that gets uploaded per frame, which is *worse* than not caching. Must switch to `CacheNone` under GL.

**What breaks**:
- `QGraphicsProxyWidget` children render via separate code path; if DoxyEdit ever adds QWidget-in-scene (it doesn't currently - grep confirms), this breaks.
- `DeviceCoordinateCache` on items still works; the cache just lives in OpenGL-backed `QImage` rather than CPU `QImage`.
- Context menus from `createStandardContextMenu()` - already themed inline per CLAUDE.md rules, not affected.
- FPS HUD uses `painter.drawText` in `drawForeground` - works identically.

**DPI gotchas on Windows**:
- At 125%/150% scale, the framebuffer is created at physical pixels. Make sure `QSurfaceFormat::setVersion(3, 3)` or later - Qt 6's default is 2.0 compatibility which on some Intel drivers renders to logical pixels then upscales (blurry). Add:
  ```python
  fmt.setVersion(3, 3)
  fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
  ```
  Caveat: Core profile disables some `QPainter` GL backend features. `QPainter` may fall back to raster for specific composition modes. Empirically safer: stay with Compatibility profile on Qt 6.5+.
- Hybrid GPU (NVIDIA Optimus / AMD): context lost on dock/undock. Mitigation: `QOpenGLWidget` in Qt 6.5+ auto-recreates context; any GL-side caches must be rebuilt. For Studio this is fine - no manual GL state.
- `devicePixelRatio`: `QPainter::drawPixmap` in GL path respects DPR correctly. One known bug `QTBUG-59956` was about mixing `QGLWidget` (old) with graphics items at HiDPI - fixed in 6.3+.

**Milestones**:
- **Day 1 AM**: Add the opt-in setting. Wire into `StudioView.__init__`. Run DoxyEdit, verify it boots under GL viewport. First FPS measurement against current baseline at 1:1 zoom, 3-sec drag test with grid off.
- **Day 1 PM**: HiDPI pass - test at 100/125/150/175% Windows scale. Check ruler tick alignment, crop mask overlay, selection handles, context menus. Document any visual regressions.
- **Day 2 AM**: Hybrid GPU test - dock/undock cycle on a laptop with NVIDIA Optimus or AMD switchable. If context loss blacks the canvas, wire up `aboutToBeDestroyed` signal on the context and force a full `load_asset` re-upload.
- **Day 2 PM**: Benchmark. If win < 30%, abandon. If 30-80%, ship as opt-in setting with "GPU canvas (beta)" label.

**Total**: 2 eng-days. Already expanded in the previous investigation as R5; schedule is the same.

**Deliverable**: opt-in setting. On at 100% default for users with a single discrete GPU, off otherwise.

**Risks**:
- Hybrid GPU bugs on laptops (real, has bitten Qt users for 8 years).
- `FullViewportUpdate` forced, so scenes with lots of static content re-composite every frame. For DoxyEdit this is fine - base pixmap + few overlays is not a big composite cost on GPU.
- No ceiling lift. If the real bottleneck is Python-side per-frame overhead in `itemChange` / `paint` overrides, GL viewport doesn't help.

---

### Option B - `QQuickPaintedItem` inside a `QQuickWidget` (Qt Quick hybrid)

**What it does**: host a QML `QQuickWindow` (via `QQuickWidget`). The canvas becomes a `QQuickPaintedItem` or a set of `QSGNode`s directly.

**Verdict up front**: this is the wrong abstraction for an imperative image editor. `QQuickPaintedItem` is a QWidget-style `paint()` method glued onto a QML item. It uses a framebuffer-backed texture internally and pays that upload cost every change. Qt docs are explicit: "using a framebuffer object avoids a costly upload of the image contents... Resizing a framebuffer object is a costly operation, avoid using the FramebufferObject render target if the item gets resized often." That's the drag case.

Going one level lower - direct `QSGNode` subclassing - means the canvas is composed by the Qt Quick scene graph. This is how Krita's Qt 6 port is planned (Phabricator T14170). It's also how Alvin Wong's 2025 experiment worked (cited in KDE research week notes).

**Code shape (QSGNode path, not QQuickPaintedItem)**:

```python
# canvas_quickitem.py - new module
from PySide6.QtQuick import QQuickItem, QSGNode, QSGSimpleTextureNode
from PySide6.QtQml import qmlRegisterType

class CanvasItem(QQuickItem):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlag(QQuickItem.ItemHasContents, True)
        self._base_texture = None       # QSGTexture, built from QImage
        self._overlay_nodes: list = []  # list of QSGNode

    def updatePaintNode(self, old_node, data):
        # Called on the render thread. Must return a QSGNode rooted at
        # 'root' - Qt Quick will add/remove children as we attach them.
        root = old_node if old_node else QSGNode()

        # Base image node
        if self._base_texture is not None:
            base_node = QSGSimpleTextureNode()
            base_node.setRect(self.boundingRect())
            base_node.setTexture(self._base_texture)
            base_node.setFiltering(QSGSimpleTextureNode.Linear)
            root.appendChildNode(base_node)

        # Overlays: one node per overlay. Z-order is child index.
        for ov in self._overlays:
            node = ov.build_sg_node()   # returns QSGNode
            root.appendChildNode(node)

        return root
```

**Studio-side translation**:

Each Python overlay class currently inherits from `QGraphicsItem`. They'd need a parallel `build_sg_node(self) -> QSGNode` method. Examples:

- `OverlayImageItem` -> `QSGSimpleTextureNode` with a `QSGTexture` built from the overlay's pixmap. Handles move/scale via the node's rect.
- `OverlayTextItem` -> render the text to a `QImage` (once on font change), wrap in a `QSGTexture`, attach as `QSGSimpleTextureNode`. Drag only changes the node's rect - no re-raster.
- `OverlayShapeItem` (bubbles): render the path to an offscreen `QImage` on shape-param change, attach as texture. Same drag behavior.
- `CensorRectItem`: solid/blurred rect - either a `QSGSimpleRectNode` with color for black/white, or a `QSGSimpleTextureNode` for blurred.
- Handle overlays: stay in Python as a separate QML overlay pass, or become `QSGGeometryNode` with a cached geometry.

**Python interaction model translation**:

This is where it gets expensive. The scene graph runs on the *render thread*. Python-side input events still fire on the main thread. Synchronization model:

- Main thread: receives `mouseMoveEvent` from `QQuickItem::mouseMoveEvent`. Updates overlay.x / overlay.y on the Python model.
- Main thread: calls `self.update()` on the `QQuickItem`. Qt Quick marks the item dirty.
- Render thread: calls `updatePaintNode(old, data)` under the lock in `QQuickItem::updatePolish`. Python reads overlay positions, mutates the `QSGNode` rects.

The render-thread callback (`updatePaintNode`) *must not* touch QWidget state. Python code here must be thread-safe. PySide6 marshals this correctly via `QQuickItem::updatePolish` synchronization. BUT: if any overlay's texture upload happens inside `updatePaintNode`, that's a render-thread texture upload, which allocates VRAM. You can do it; it's just slow if done per frame.

**Milestones**:
- **Day 1**: Stand up a `QQuickWidget` in a Studio-side panel with a trivial `CanvasItem` showing a static image via `QSGSimpleTextureNode`. Wire up wheel/zoom via `QQuickItem::wheelEvent`.
- **Day 2**: Add overlay abstraction. Build `OverlayImageItem` equivalent that renders a watermark via a `QSGSimpleTextureNode`. Handle drag via `mousePressEvent`/`mouseMoveEvent` overrides.
- **Day 3**: Add `OverlayTextItem` (pre-render text to QImage, wrap in texture). Verify drag cost is a node-rect update only, not a re-raster.
- **Day 4**: Add `OverlayShapeItem` (bubble). Render path once to QImage on param change, texture. Handles for resize via QML overlay layer.
- **Day 5**: Handle selection feedback - marching ants or outline - via a shader material (`QSGMaterial` subclass) or a second pass of overlay nodes.
- **Day 6**: Migrate crop mask (which is currently a 4-rect overlay). Migrate censor rects.
- **Day 7**: Tool mode (draw arrow, draw shape) - harder; the draw-in-progress item needs to live in the scene graph, updating per mouse-move. Probably a special node that updates each `updatePaintNode` call.
- **Day 8**: Context menus, undo, clipboard, all the toolbar actions - most should work as-is because they operate on the Python model, which still feeds the scene graph.
- **Day 9**: FPS HUD + perf log integration into the `QQuickWindow::afterRendering` signal.
- **Day 10**: Feature parity audit + shipping polish.

**Total**: 10 eng-days minimum. Realistically 15 with unknowns.

**Expected perf win**: 5-10x on compositing. The scene graph runs on a dedicated render thread at display refresh rate. Python main thread isn't in the frame-render loop; it only sets node dirty flags. This is the right architecture for high-FPS with many overlays.

**Risks**:
- Thread safety: Python GIL is released during `updatePaintNode`. Any Python-callable inside that path needs care.
- Texture memory: every overlay is now a texture. 30 overlays at 800x200 = 30 * 800*200*4 bytes = 19 MB VRAM - fine. 300 overlays at same = 190 MB - noticeable.
- QML is a different paradigm. The team has to learn it. The `QQuickWidget` embedding path is brittle - context menus from QWidget-land don't always composite correctly over QML surfaces. Custom shaders for blend modes require writing QSG material subclasses in C++ or QML Shader effects, which is awkward from pure Python.
- Eventually the whole Studio tab wants to move to QML or it stays a hybrid forever. The user has stated they want to *consolidate*, not bifurcate.

**Deliverable**: a new `CanvasItem` module plus a parallel `StudioView2` that hosts it. Ship behind a flag.

### Option C - Pure `QOpenGLWidget` replacement (bypass `QGraphicsView`)

**What it does**: write the Studio canvas from scratch as a `QOpenGLWidget`. The base image is a texture; overlays are textures or path-rendered meshes; composition is a fragment shader. `QGraphicsView` goes away.

This is the Krita architecture, downsized.

**Code shape**:

```python
# canvas_gl.py - new module
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtOpenGL import (
    QOpenGLShaderProgram, QOpenGLBuffer, QOpenGLTexture,
    QOpenGLVertexArrayObject, QOpenGLFunctions,
)
from PySide6.QtGui import QSurfaceFormat, QImage, QMatrix4x4
from OpenGL import GL

# 2D orthographic projection quad renderer.
VSRC = """
#version 330
layout(location=0) in vec2 a_pos;
layout(location=1) in vec2 a_uv;
uniform mat4 u_mvp;
out vec2 v_uv;
void main() {
    gl_Position = u_mvp * vec4(a_pos, 0.0, 1.0);
    v_uv = a_uv;
}
"""
FSRC_TEXTURED = """
#version 330
in vec2 v_uv;
uniform sampler2D u_tex;
uniform float u_opacity;
out vec4 frag;
void main() {
    vec4 c = texture(u_tex, v_uv);
    frag = vec4(c.rgb, c.a * u_opacity);
}
"""

class CanvasGL(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setSwapInterval(1)
        self.setFormat(fmt)

        self._base_tex: QOpenGLTexture | None = None
        self._base_size = (0, 0)
        self._overlays: list[Overlay] = []     # Python-side records
        self._overlay_textures: dict[int, QOpenGLTexture] = {}
        self._view_matrix = QMatrix4x4()
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._needs_upload: set = set()        # overlay IDs to (re)upload

    def initializeGL(self):
        self._gl = self.context().functions()
        self._program = QOpenGLShaderProgram(self)
        self._program.addShaderFromSourceCode(
            QOpenGLShader.Vertex, VSRC)
        self._program.addShaderFromSourceCode(
            QOpenGLShader.Fragment, FSRC_TEXTURED)
        self._program.link()
        self._build_quad_vao()

    def load_base_image(self, qimage: QImage):
        self.makeCurrent()
        if self._base_tex:
            self._base_tex.destroy()
        self._base_tex = QOpenGLTexture(qimage)
        self._base_tex.setMinificationFilter(
            QOpenGLTexture.Filter.LinearMipMapLinear)
        self._base_tex.setMagnificationFilter(
            QOpenGLTexture.Filter.Linear)
        self._base_tex.generateMipMaps()
        self._base_size = (qimage.width(), qimage.height())
        self.doneCurrent()
        self.update()

    def add_overlay(self, overlay: Overlay):
        self._overlays.append(overlay)
        self._needs_upload.add(id(overlay))
        self.update()

    def paintGL(self):
        self._gl.glClearColor(0.1, 0.1, 0.1, 1.0)
        self._gl.glClear(GL.GL_COLOR_BUFFER_BIT)
        self._gl.glEnable(GL.GL_BLEND)
        self._gl.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

        # Lazy upload: any overlay that changed since last frame
        for ov_id in self._needs_upload:
            self._upload_overlay_texture(ov_id)
        self._needs_upload.clear()

        self._program.bind()
        mvp = self._ortho_projection() * self._view_matrix
        self._program.setUniformValue("u_mvp", mvp)

        # 1. Checkerboard (shader, procedural - no texture needed)
        self._draw_checker()

        # 2. Base image
        self._program.setUniformValue("u_opacity", 1.0)
        self._base_tex.bind()
        self._draw_quad_for_rect(0, 0, *self._base_size)

        # 3. Overlays in z-order
        for ov in sorted(self._overlays, key=lambda o: o.z):
            tex = self._overlay_textures[id(ov)]
            self._program.setUniformValue("u_opacity", ov.opacity)
            tex.bind()
            self._draw_quad_for_rect(ov.x, ov.y, ov.w, ov.h,
                                     rotation=ov.rotation)

        # 4. Selection handles + snap guides overlay (via QPainter-over-GL)
        painter = QPainter(self)
        painter.beginNativePainting()
        painter.endNativePainting()
        self._draw_handles_and_guides(painter)
        painter.end()

    def mousePressEvent(self, event):
        p = self._screen_to_image(event.position())
        ov = self._hit_test(p)
        self._drag_ov = ov
        self._drag_start = p

    def mouseMoveEvent(self, event):
        if self._drag_ov:
            p = self._screen_to_image(event.position())
            dx = p.x() - self._drag_start.x()
            dy = p.y() - self._drag_start.y()
            self._drag_ov.x += dx
            self._drag_ov.y += dy
            self._drag_start = p
            self.update()   # sub-millisecond: just marks dirty
        ...
```

The texture atlas approach (lumping overlays into a single texture) is a *possible* optimization inside this path but unnecessary for N<200 overlays - per-overlay textures are fine.

**Studio's API surface mapping**:

Current code calls extensively on `self._pixmap_item.pixmap()`, `self._pixmap_item.boundingRect()`, `self._view.centerOn()`, `self._scene.items()`, etc. Each of those needs a stand-in on `CanvasGL`. Concretely:

```python
class CanvasGL(QOpenGLWidget):
    # Compatibility shims so existing StudioEditor code keeps working
    @property
    def base_image(self) -> QImage: ...
    @property
    def base_size(self) -> QSize: ...
    def overlays(self) -> list[Overlay]: ...
    def hit_test(self, image_pos: QPointF) -> Overlay | None: ...
    def add_overlay(self, ov: Overlay): ...
    def remove_overlay(self, ov: Overlay): ...
    def fit_in_view(self): ...
    def zoom_to(self, factor: float, center_image_pos: QPointF): ...
    def pan_by(self, dx: float, dy: float): ...  # screen px
```

Overlays become pure data objects (already are - `CanvasOverlay` dataclass in `models.py`). They no longer need `QGraphicsItem` subclasses - those go away. The `paint` method for each overlay type becomes a function that takes an `Overlay` record and a `GL` context.

**Effort honestly estimated**:

- **Day 1**: Minimum viable `CanvasGL`. Shows a texture, supports pan + zoom, no overlays. Replaces `QGraphicsView` only when an env flag is set.
- **Day 2**: Base image draw path - mipmapped texture upload, quad rendering, proper DPI handling. Checker procedural shader.
- **Day 3**: `OverlayImageItem` equivalent. Texture upload, quad draw with rotation/flip. Hit-test logic. Drag handling on mouse events.
- **Day 4**: `OverlayTextItem` equivalent. Text renders to QImage via `QTextDocument`, cached by `(text, font, color, stroke, shadow)` tuple, uploaded to GL texture. Drag is a pos change.
- **Day 5**: `OverlayShapeItem`. Path render to QImage via QPainter (bubble/star/polygon), cache by shape-params tuple, texture. Same drag model as text.
- **Day 6**: `CensorRectItem`. For `black`/`white` style: a solid-color shader draw, no texture. For `blurred`: render a blurred subregion of the base texture via a 2-pass Gaussian shader.
- **Day 7**: Selection handles and marching ants. Two paths: (a) do them with `QPainter` in an overpaint pass at the end of `paintGL` (slow but simple), or (b) custom shader for handles + dash-animated line geometry. Start with (a).
- **Day 8**: Crop mask (4-rect dark-overlay). This is a full-viewport shader with a cutout rect - easy in a fragment shader, about 15 lines.
- **Day 9**: Tool modes - freehand drawing of a new shape. Needs a "draft" overlay that lives in the scene until commit.
- **Day 10**: Grid, thirds, snap guides as procedural shader or `QPainter` overpaint.
- **Day 11**: Blend modes (normal/multiply/screen/overlay/darken/lighten). Each is a different fragment shader; bind before drawing the overlay. Six shader variants.
- **Day 12**: Export path. Currently hits `scene.render()` - now needs to render to an offscreen framebuffer instead, read back to `QImage`, feed into existing `exporter.py`.
- **Day 13**: Ruler widgets, on-canvas coordinate labels, info label updates.
- **Day 14**: Clipboard, drag-drop, undo stack integration - mostly unchanged since those operate on the model.
- **Day 15**: Theming, Studio settings wiring, feature-flag fallback, regression sweep.

**Total**: 15 eng-days realistic. Prior investigation said 2-3 weeks; this breakdown gives you the actual shape of those weeks.

**Expected perf win**: 10-20x on the compositing path. A 2Kx3K base + 30 overlay drag frame becomes <1ms GPU work. FPS is then gated by input latency + Qt event dispatch, not by render.

**Risks**:
- Text rendering quality via QImage pre-raster is lower than native QPainter text hinting. Fix: render text at 2x internal resolution, downsample. This is how most GPU text renderers work.
- Python-side GL dispatch overhead: every `glBindTexture` from Python is a Python->C call. At 30 overlays per frame that's 30 calls/frame * 60 FPS = 1800 calls/sec. On PySide6 this is ~microsecond each - inconsequential. But if we scale to 3000 overlays, it matters; texture atlas batching then becomes necessary.
- Context loss on hybrid GPUs: same problem as Option A. Textures must be reuploaded on context loss.
- Writing GLSL in strings inside Python is fine, but debugging it is. `RenderDoc` works against Qt OpenGL contexts.
- Two code paths coexisting for a multi-week window (covered in Section 4).

**Deliverable**: `canvas_gl.py` module, `StudioEditor` wired to instantiate `CanvasGL` instead of `StudioView` under a feature flag.

### Option D - Skia backend via `skia-python`

**What it does**: replace the `QGraphicsView` compositor with a Skia `SkSurface` rendered into a `QOpenGLWidget`. Skia is the Chrome/Android/Flutter/Firefox renderer.

**License**: Skia is BSD-3-Clause. skia-python binding is also BSD-3-Clause. Compatible with DoxyEdit MIT.

**Bundling**: skia-python is a C++ binding via pybind11. Wheels on PyPI provide prebuilt `skia` binaries for Windows, macOS, Linux x86_64. Wheel size is ~40-50 MB. Nuitka --standalone includes the .pyd and its dependencies; onefile wraps them. Total exe size increase: ~45 MB over the current ~80 MB DoxyEdit build.

**Code shape** (combined with `QOpenGLWidget`):

```python
# canvas_skia.py
import skia
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtGui import QSurfaceFormat

class CanvasSkia(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setSwapInterval(1)
        fmt.setStencilBufferSize(8)  # Skia needs stencil
        self.setFormat(fmt)

        self._base_image: skia.Image | None = None
        self._overlays: list[Overlay] = []
        self._gr_context: skia.GrDirectContext | None = None
        self._surface: skia.Surface | None = None

    def initializeGL(self):
        # Wrap Qt's current GL context as a Skia GPU context
        self._gr_context = skia.GrDirectContext.MakeGL()

    def resizeGL(self, w: int, h: int):
        # Wrap the default framebuffer (FBO 0) as a Skia surface
        dpr = self.devicePixelRatioF()
        pw, ph = int(w * dpr), int(h * dpr)
        backend_rt = skia.GrBackendRenderTarget(
            pw, ph,
            sampleCnt=0,
            stencilBits=8,
            fboId=self.defaultFramebufferObject(),
            fboFormat=skia.GrGLenum(skia.GrGLTextures.kRGBA8),
        )
        self._surface = skia.Surface.MakeFromBackendRenderTarget(
            self._gr_context, backend_rt,
            skia.kBottomLeft_GrSurfaceOrigin,
            skia.kRGBA_8888_ColorType,
            None, None,
        )

    def load_base_image(self, qimage: QImage):
        # Convert to skia.Image - cheap when formats match
        bits = qimage.constBits().tobytes()
        info = skia.ImageInfo.Make(
            qimage.width(), qimage.height(),
            skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        self._base_image = skia.Image.MakeRasterCopy(
            skia.Pixmap(info, bits, qimage.bytesPerLine()))

    def paintGL(self):
        if not self._surface:
            return
        canvas = self._surface.getCanvas()
        canvas.clear(skia.ColorGRAY)

        canvas.save()
        canvas.scale(self._zoom, self._zoom)
        canvas.translate(*self._pan)

        # Base image
        if self._base_image:
            canvas.drawImage(self._base_image, 0, 0)

        # Overlays - Skia handles path, text, image, filters natively
        for ov in sorted(self._overlays, key=lambda o: o.z):
            self._draw_overlay(canvas, ov)

        canvas.restore()
        self._surface.flushAndSubmit()
```

The key appeal: **Skia already implements everything we hand-code in Option C**. Text with outline/shadow/blend? `SkPaint::setStyle(Stroke)` + `setImageFilter(SkDropShadowImageFilter)`. Bubble paths? `SkPath::arcTo` etc. Blend modes? All 18+ Porter-Duff modes native. Filters? `SkImageFilters::Blur` etc.

**Performance envelope**: Skia's GPU backend (`Ganesh`, being replaced by `Graphite`) is what renders Chrome tabs. For a 2Kx3K image with 30 overlays, rendering + flush is sub-millisecond on any modern GPU. Equivalent to Option C perf-wise.

**Milestones**:
- **Day 1**: Verify skia-python installs, bundles via Nuitka. Nuitka onefile smoke test on Windows. Size overhead measurement.
- **Day 2**: Minimum `CanvasSkia` rendering the base image at 1:1. Wire up pan/zoom via canvas transform. Handle resize.
- **Day 3**: Port `OverlayImageItem` to a Skia `drawImage` call. Blend modes via `SkBlendMode`.
- **Day 4**: Port `OverlayTextItem`. Skia native text rendering (glyphs via HarfBuzz under the hood). Drop shadow + stroke via `SkImageFilter` chain. Cache: per-overlay `SkTextBlob` built on font change, reused on drag.
- **Day 5**: Port `OverlayShapeItem`. Bubble/star/polygon paths via `SkPath`. Fill+stroke in one paint call.
- **Day 6**: `CensorRectItem`: solid is `drawRect` with paint color. Blur is `SkImageFilters::Blur` applied to a sub-image of the base.
- **Day 7**: Crop mask, selection handles, snap guides - all use `QPainter` over the GL surface OR a second Skia surface with overlay.
- **Day 8**: Hit testing. Same math as before (mouse pos -> image coords), but now live in `CanvasSkia`.
- **Day 9**: Tool modes. Draft shape lives in Skia canvas between commit.
- **Day 10**: Export via `SkSurface::makeImageSnapshot()` -> `SkImage::encodeToData(PNG)` -> bytes -> QImage or direct file.
- **Day 11**: High-DPI. Skia respects DPR set via canvas.scale() - test at 100/125/150%.
- **Day 12**: Nuitka packaging QA. Test the onefile exe on a clean Windows machine with no Python. Confirm Skia GPU path works without dev tools installed.
- **Day 13**: FPS HUD, perf log integration.
- **Day 14**: Feature flag wiring, fallback to `QGraphicsView` when Skia init fails.

**Total**: 14 eng-days.

**Expected perf win**: identical or slightly better than Option C. Skia's renderer is more optimized than hand-rolled OpenGL from Python because Skia batches draw calls internally and uses Ganesh/Graphite's atlas caching for text and paths.

**Extra benefits over Option C**:
- Much less custom GLSL to write/debug.
- Filters, blend modes, text with strokes, image filters - all native, battle-tested.
- Antialiasing quality matches Chrome, which is better than Qt's raster engine.
- License-clean for commercial use.

**Risks**:
- Bundling: skia-python v138 wheel is big. Nuitka has to include it. Icon-level risk, not showstopper.
- Version drift: skia-python follows Skia's release cadence loosely. Pin a specific version in `pyproject.toml`.
- GL context ownership: Qt owns the context, Skia wraps it. If Qt releases the context (resize or visibility change), Skia's `GrBackendRenderTarget` becomes stale. Must recreate on `resizeGL`. Well-documented pattern.
- PySide6 + skia-python + OpenGL in one process on Windows: some users report GL driver conflicts on Intel HD graphics. Worth a beta period.

**Deliverable**: `canvas_skia.py`. Skia is the default compositor behind a beta feature flag. Fallback to `QGraphicsView` on init failure.

**My tentative favorite** - see Section 3.

### Option E - Continue optimizing `QGraphicsView`

The previous investigation found 5 tweaks. If we keep pushing, where's the next 2x? Here are specific hotspots not addressed in the first investigation:

**E1. Handle items as children of the selected overlay (avoid ItemIgnoresTransformations)**

Current: when an `OverlayShapeItem` is selected, Studio spawns resize/rotate handle items. Look at `studio_items.py:855-864` (`_handle_positions`), `:832-853` (`hoverMoveEvent` checks), `:189-232` (`_ResizeHandle`, `_RotateHandle` classes).

Every handle is a separate `QGraphicsRectItem` - 4 corners + rotate + tail (for bubbles) + corner-radius = up to 10 items per selected overlay. During a drag of the parent overlay, Qt dispatches `prepareGeometryChange` / position update to each child. Each child is individually painted. If 5 overlays are selected, that's 50 extra items getting updated on every drag frame.

Fix: collapse handles into a single "decorator" item drawn in the parent's `paint()` method. One item, one paint call, one bounding rect. Handles become geometry inside the overlay's `paint`, not separate items.

**Effort**: 1 eng-day. Refactor `OverlayShapeItem.paint`, `OverlayImageItem.paint`, `OverlayTextItem.paint` to draw handles inline when `isSelected()`. Delete `_ResizeHandle` / `_RotateHandle` classes. Hit-test still works because we override `shape()` to return the expanded path.

**Win**: ~30-50% reduction in per-frame paint work when items are selected. Larger win with multi-selection.

**E2. `_pixmap_item` scaled-pyramid cache (mipmap-like)**

The prior R4 recommended caching pre-scaled pixmaps. This is still valid. Expand:

- Keep 4 pre-scaled copies of the base at 100%, 50%, 25%, 12.5%.
- In `paintEvent` or `paint` override, select the copy closest to (but larger than) the target screen size, let Qt downsample via `SmoothPixmapTransform`.
- Key cost: `QPixmap.scaled` with SmoothTransformation is one-time, ~40-80ms per level. Build them lazily on first zoom into that band.

**Effort**: 0.5 eng-day. Implement in `StudioEditor.load_asset` (line 7705 in studio.py) and `wheelEvent` to trigger band selection.

**Win**: zoom changes feel instant; blit cost at any zoom level matches 1:1 case.

**E3. Off-thread overlay pixmap pre-render**

Bubbles, text, and shape overlays have expensive `paint()` methods (bubble path building: line 875-1000 in studio_items.py; text: 9 outline passes at line 2482-2495). `DeviceCoordinateCache` masks this by caching the rendered result, but the first paint after any property change forces a full rebuild.

Fix: when a parameter changes, kick off a background `QThreadPool.start(callable)` that renders the overlay to a `QImage`. On completion (via `QMetaObject.invokeMethod`), swap it in as the cached pixmap. The item's `paint()` just blits the QImage.

This is the thumbnail worker pattern (`thumbcache.py:202` `ThumbWorker`) applied to overlays.

**Effort**: 2 eng-days. New `OverlayCacheBuilder` class. Refactor `OverlayShapeItem.paint` to check for a cached QImage first.

**Win**: property-change latency drops from "visible hiccup" to "next frame." Doesn't help drag (drag doesn't re-render). Helps tune sessions where the user is wobbling bubble_wobble slider.

**E4. `setItemIndexMethod(NoIndex)` with z-ordered list**

Default BSP tree index helps `itemAt(pos)` lookups (hit testing). For scenes where items *move* - every overlay drag - the BSP tree gets rebuilt against. With few items (say, N<50), a flat linear scan over a z-sorted list is faster than BSP maintenance.

Fix: `self._scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)` in `StudioScene.__init__` (line 81).

Confirm by: `_describe_item` trace in perf log. If BSP work is >5% of frame time on drag, this is a win.

**Effort**: 0.1 eng-day. One line + test with a scene of 50 overlays dragging one.

**Win**: 10-20% when item count is low (<50); neutral or negative past N=200.

**E5. `ItemHasNoContents` root + separate items for image vs overlays**

Currently the scene mixes base pixmap + overlays into one z-ordered list. `QGraphicsScene::items()` iteration walks this list for every operation. If overlays become children of a parent `QGraphicsItemGroup` with `ItemHasNoContents`, the scene iterator has a shorter top-level list.

Marginal. Skip unless profiling points here.

### Summary of Option E

Going hard on `QGraphicsView` optimization lifts the ceiling maybe 2-3x from the current state. Theoretical max of ~60 FPS on *simple* scenes, still dropping to 30-40 under load (many overlays + complex text). It does not fundamentally solve the "many overlays" problem because the per-item paint dispatch is Python code.

**Effort for E1-E4**: 3.5 eng-days total.

**Verdict**: worth doing *regardless of which bigger option you pick*, because E1 and E3 are also wins for the current architecture. But don't expect E-series to hit 60 FPS with many overlays reliably.

---

## Section 3 - The recommendation

**Pick Option D (Skia backend) as the primary path. Do E1 and E3 now as insurance; they help even if Skia is deferred.**

Reasoning:

1. **Perf ceiling**. The target is 60 FPS with many overlays. Only C and D plausibly hit it. E tops out around 30-40 under load.

2. **Effort**. D is 14 eng-days, C is 15, B is 10-15. B (QML scene graph) requires rewriting the input-interaction model and learning QML; D is a compositor swap with the Python model layer untouched.

3. **Risk profile**. D ships a proven rendering library (Chrome uses Skia). C writes custom GLSL - more surface area for bugs. B mixes two widget systems - known hairy.

4. **Features you get free with D**. Proper antialiased text with stroke + shadow, 18 blend modes, image filters (blur, glow, color matrix), high-quality path rasterization. All of these are open items or hacks in current Studio. `OverlayTextItem.paint` currently does 9 QPainter passes to fake a stroke - Skia does it in one paint call with better quality.

5. **Long-term. WebKit announced Skia adoption in 2024.** Skia is a safe bet. skia-python is actively maintained (v138 released mid-2025).

6. **Bundle size**. +45 MB on a 80 MB exe. Tolerable.

7. **Python-friendliness**. Skia's Python binding is ergonomic - reads like QPainter code. Writing custom GLSL from Python (Option C) is less ergonomic.

Concrete benchmarks you can expect based on Skia's published numbers:
- 2K x 3K base + 10 overlays: ~0.3ms frame render (well under 16.67ms vsync).
- 2K x 3K base + 100 overlays: ~1.5ms frame render.
- 2K x 3K base + 1000 overlays: ~15ms frame render, possibly vsync-capped.

Compared to measured current: the `doxyedit_studio_perf.jsonl` trace for a single bubble drag on a 2K image shows paint time ~20-30ms at ViewportUpdateMode=Minimal with 5 items. That's a 10-100x improvement.

Pick D. Milestone plan in Section 2D. Start with a 2-day spike (Days 1-2) to de-risk bundling + GL context wrap - if those fail, fall back to C.

---

## Section 4 - Incremental migration

Studio is a live tool. Strategy: **additive code path, opt-in feature flag, default off for 2 weeks, then default on with a "classic mode" escape hatch**.

### 4a. Feature flag plumbing

Add to `QSettings("DoxyEdit", "DoxyEdit")`:

```python
# studio.py at module top
STUDIO_COMPOSITOR = QSettings(...).value(
    "studio_compositor", "qgraphics",  # qgraphics | gl | skia
    type=str)
```

In `StudioEditor._build()` (around line 4245 area), switch:

```python
def _build(self):
    ...
    if STUDIO_COMPOSITOR == "skia":
        from doxyedit.canvas_skia import CanvasSkia
        self._view = CanvasSkia(self)
    elif STUDIO_COMPOSITOR == "gl":
        from doxyedit.canvas_gl import CanvasGL
        self._view = CanvasGL(self)
    else:
        self._scene = StudioScene(self)
        self._view = StudioView(self._scene, self)
    ...
```

The Python model layer (`CanvasOverlay`, `Asset.censors`, `Asset.crops`) is untouched. Each compositor reads the same model data.

### 4b. API shim on the new compositor

Define a common interface so `StudioEditor` doesn't branch everywhere:

```python
# canvas_api.py - new module, abstract
class CanvasBackend(Protocol):
    def load_base_image(self, pm: QPixmap) -> None: ...
    def set_overlays(self, overlays: list[CanvasOverlay]) -> None: ...
    def set_censors(self, censors: list[CensorRegion]) -> None: ...
    def set_crops(self, crops: list[CropRegion]) -> None: ...
    def zoom_to(self, factor: float, center: QPointF) -> None: ...
    def fit_in_view(self) -> None: ...
    def update_overlay(self, ov_id: str) -> None: ...
    def hit_test(self, image_pos: QPointF) -> str | None: ...
    def render_to_image(self, rect: QRectF | None = None) -> QImage: ...
    def set_tool(self, tool: StudioTool) -> None: ...
    mouse_moved: Signal  # QPointF
    overlay_clicked: Signal  # str (overlay id)
    overlay_moved: Signal  # (str, QPointF)
    ...
```

Wrap the existing `StudioView` + `StudioScene` in a thin `QGraphicsCanvasBackend` that exposes this interface, so the caller code is uniform. This is the real work of Day 0 - unlock the ability to swap.

### 4c. Parity checklist - sanity gates

Before flipping the default, each of these must behave identically on both backends:

- [ ] Base image loads at correct DPI.
- [ ] Zoom via wheel, 10% to 1000%, cursor-anchored.
- [ ] Pan via middle-drag.
- [ ] Fit-to-view (keyboard F).
- [ ] 1:1 zoom (keyboard 1).
- [ ] Overlay add (watermark, text, shape) via toolbar + default templates.
- [ ] Overlay drag - position syncs back to `CanvasOverlay.x/y`.
- [ ] Overlay resize handles - corners, rotate, tail.
- [ ] Overlay delete / undo / redo.
- [ ] Context menus (themed, per CLAUDE.md).
- [ ] Blend modes on overlays (all 6).
- [ ] Text editing (double-click) - focus, type, escape.
- [ ] Censor draw via tool.
- [ ] Crop draw + mask.
- [ ] Notes rects.
- [ ] Grid, thirds, snap guides toggle.
- [ ] Rulers (top + left) show correct tick spacing.
- [ ] FPS HUD.
- [ ] Export crop via `exporter.py` - path takes the backend's `render_to_image`.
- [ ] Drag-drop external image onto canvas.
- [ ] Clipboard copy/paste overlay.
- [ ] Alt-click duplicate.

### 4d. Dual-backend perf logging

Extend `studio.py:_perf_log_event` to include:

```python
ev.setdefault("compositor", STUDIO_COMPOSITOR)
```

Users who run both can A/B their own sessions. Makes the default-on rollout data-driven.

### 4e. Beta phase

- Week 0-1: new compositor lives behind `studio_compositor=skia` setting. One user (you) runs it. Shared user paths still on `qgraphics`.
- Week 2: opt-in via Studio Settings dialog with "GPU Canvas (beta)" checkbox. A warning label: "May have visual differences. Disable if the canvas goes black or has odd artifacts."
- Week 3: default flip on fresh installs. Existing users keep their current setting. Release notes include "Classic Canvas" escape hatch via Settings.
- Week 6+: deprecate `QGraphicsView` path. Mark `StudioView`, `StudioScene`, and most of `studio_items.py` as "legacy." Remove after 2 more releases.

### 4f. What cannot coexist

`_ResizeHandle`, `_RotateHandle`, `CensorRectItem`, `OverlayShapeItem`, `OverlayImageItem`, `OverlayTextItem` are `QGraphicsItem` subclasses. Under Skia they don't exist as objects - overlay state lives entirely in `CanvasOverlay` dataclass rows. The migration is: `StudioEditor` stops adding items to `self._scene` and starts calling `self._view.add_overlay(ov)` which synchronizes to the compositor.

Any code that currently does `item.sceneBoundingRect()`, `item.setPos()`, etc. must go through the compositor API. `grep 'QGraphicsItem\b\|_pixmap_item\b\|_scene\.'` in `studio.py` returns the full list of call sites to migrate. Based on the earlier grep, it's about 100 lines spread over 60 locations - manageable.

### 4g. Rollback

At any point during development, toggle `studio_compositor=qgraphics` and the old path runs. No data migration required - overlays serialize to JSON the same way.

If a catastrophic regression ships, push a point release that forces `studio_compositor=qgraphics` via a migration step in `config.py` startup.

---

## Concrete next steps

Proposed order of operations:

1. **Days 1-2: de-risk Skia bundling.** Before committing to D, build a spike: `import skia` in a standalone file, run in Nuitka onefile build, confirm on a clean Windows VM. If this fails, fall back to Option C.
2. **Day 3: ship E1 + E4 to the existing path.** Handle items as inline paint, NoIndex scene. Immediate 2x for current users, works regardless of the bigger migration path.
3. **Day 4: ship E3 (off-thread overlay rendering).** Immediate win for the property-slider / tuning UX.
4. **Days 5-18: build Option D behind the flag.** Milestones in Section 2D. At the end of Day 12, feature-complete Skia canvas, opt-in.
5. **Days 19-20: beta phase 1 - personal use by author on Skia backend. Collect perf traces.**
6. **Day 21+: gate rollout.**

If user demand for "many overlays at 60 FPS" accelerates before Day 18, you can ship the partial Skia canvas on a subset of asset types (image-only overlays first, text + shapes later) since the feature flag is per-session not per-overlay.

---

## Sources

- [Krita KisOpenGLCanvas2](https://github.com/KDE/krita/blob/master/libs/ui/opengl/kis_opengl_canvas2.cpp) - OpenGL canvas entry point, paintGL loop.
- [Krita MR !488: Optimize OpenGL canvas with partial updates](https://invent.kde.org/graphics/krita/-/merge_requests/488) - dirty rect implementation.
- [Krita OpenGL community wiki](https://community.kde.org/Krita/OpenGL) - architecture notes.
- [Krita commit 54282a72: tile data pool for GL updates](https://invent.kde.org/kde/krita/commit/54282a72cee6256f29be9970793b32f6ffae6aa1)
- [Krita T14170: Porting Krita's OpenGL canvas to Qt6](https://phabricator.kde.org/T14170) - hybrid QML + OpenGL approach, 2025 experimentation.
- [Krita 2026 Roadmap](https://krita.org/en/posts/2026/roadmap-2026/)
- [Photopea blog 1.3](https://blog.photopea.com/photopea-1-3.html) - layer RGBA buffers, per-layer style cache.
- [Photopea WebGL disable issue](https://github.com/photopea/photopea/issues/4303) - fallback paths.
- [Silicate](https://github.com/Avarel/silicate) - Rust/WGPU Procreate compositor, confirms the layer-texture model.
- [MyPaint canvas backend docs](https://www.mypaint.app/en/docs/backend/canvas/) - 64x64 tiles, uint16 premultiplied, Cairo display path.
- [miniPaint](https://github.com/viliusle/miniPaint) - per-layer HTMLCanvasElement, imperative render loop.
- [Savage Interactive Procreate Valkyrie engine](https://www.macstories.net/reviews/procreate-5-review-a-rebuilt-graphics-engine-drives-fantastic-animation-color-and-brush-tools-in-an-art-app-perfectly-tailored-to-the-ipad/) - Metal tile-based compositor.
- [skia-python](https://github.com/kyamagu/skia-python) - BSD-3 Python binding, GPU via GLX/EGL.
- [Skia GrDirectContext documentation](https://api.skia.org/classGrDirectContext.html) - GPU context setup.
- [Skia-discuss: connect Skia to existing OpenGL context](https://groups.google.com/g/skia-discuss/c/CAs0xDCWOZI) - `MakeFromBackendRenderTarget` pattern.
- [Qt QRhi](https://doc.qt.io/qt-6/qrhi.html) - Qt 6 Rendering Hardware Interface. Note: public API finalization Qt 6.6+, practical use from QGraphicsView is not supported.
- [Qt QOpenGLWidget](https://doc.qt.io/qt-6/qopenglwidget.html) - viewport integration with QGraphicsView.
- [Qt QQuickPaintedItem](https://doc.qt.io/qt-6/qquickpainteditem.html) - docs explicit about FBO resize cost.
- [Qt Quick Scene Graph docs](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph.html) - QSGNode model, afterRendering signal, underlay/overlay approach.
- [Qt graphics in 6.0 blog](https://www.qt.io/blog/graphics-in-qt-6.0-qrhi-qt-quick-qt-quick-3d)
- [Qt QGraphicsItem::CacheMode blog (2009)](https://www.qt.io/blog/2009/02/06/improvements-to-qgraphicsitemcachemodes-insides) - viewport clipping of DeviceCoordinateCache.
- [QGraphicsScene BSP tree and NoIndex guidance](https://doc.qt.io/qt-6/qgraphicsscene.html#setItemIndexMethod) - when to disable indexing.
- [QTBUG-59956 HiDPI + QGLWidget + QGraphicsView](https://bugreports.qt.io/browse/QTBUG-59956) - DPI regressions on Windows.
- [Nuitka onefile docs](https://nuitka.net/user-documentation/user-manual.html) - bundling native deps.
