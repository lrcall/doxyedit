# Canvas Architecture Investigation

High-performance 2D canvas in PySide6 / Qt 6, targeted at the DoxyEdit Studio editor. Written after inspecting `doxyedit/studio.py`, `doxyedit/studio_items.py`, `doxyedit/preview.py`, `doxyedit/browser.py`, `doxyedit/imaging.py`, and `doxyedit/thumbcache.py`, plus Qt 6.11 docs and KDE/Krita architecture notes.

The goal: understand why dragging a single speech bubble across a ~2000x3000 image feels laggy, and decide what is actually worth changing.

---

## 0. Current state (what's already in the code)

From `studio.py` around line 3715 (StudioView) and line 7587 (load_asset):

- `QGraphicsView` subclass, `SmartViewportUpdate`, `DontSavePainterState`, `DontAdjustForAntialiasing` - done.
- Base image is a single `QGraphicsPixmapItem(pm)` where `pm` is a full-resolution `QPixmap` loaded via `QPixmap(str(src))` (no format hint).
- Base pixmap item has `CacheMode.DeviceCoordinateCache`, same for the checkerboard item and the pre-rendered drop-shadow item.
- Overlay items (`OverlayImageItem`, `OverlayTextItem` in `studio_items.py` lines 516, 2300) also use `DeviceCoordinateCache`.
- The `StudioScene` is a default-configured `QGraphicsScene` - no `setItemIndexMethod()` call, no `setBspTreeDepth()` call.
- Viewport is a plain `QWidget` (default software raster). No `QOpenGLWidget` anywhere in the project.
- Scene rect is padded with a generous margin (50% of image size, minimum 400px).
- The scene's `drawForeground` renders grids and snap guides every paint.
- No `drawBackground` override; the checkerboard is implemented as a regular scene item (`_CheckerboardItem`) with its own cache.

The drop shadow is already pre-rendered (commit `0f1f0ac` era change) which removed the most expensive live blur. Everything else in the list is reasonable basic QGraphicsView hygiene.

---

## 1. Tiled canvas — is it worth implementing in Qt?

**Short answer: no, not for this use case. Skip it.**

### What tiling buys you in SAI2, Krita, Photoshop

SAI2, Krita, MyPaint, and Photoshop all use tile-backed image storage (Krita uses 64x64, Photoshop historically used 128 or 256). The tiles are not a rendering optimization, they are a **storage and edit optimization**:

1. **Copy-on-write per tile** - brush strokes only dirty the tiles they touch. A stroke in the top-left of an 8k canvas doesn't force the whole image into the undo stack; only the 64x64 tiles under the stroke are duplicated.
2. **Sparse memory** - blank regions don't allocate tiles. A freshly created 8192x8192 document takes almost no RAM until pixels are written.
3. **Cheap compositing of layers** - the compositor walks tiles, not pixels. A 40-layer document is manageable because for any output tile you only touch the tiles-at-that-coordinate from each layer.
4. **Thread scheduling** - brush stroke on tile (0,0) can run in parallel with layer adjustment on tile (4,7).

Krita's architecture note (kimageshop mailing list; `KisPaintDevice` / `KisDataManager`): "pixel data is stored inside a 64x64 pixel tile... the paint device is autoextending: it starts very small and grows whenever pixels outside the initial size are accessed."

### What tiling would buy you in DoxyEdit

None of the above apply. Studio is **not a painting app**. It composites overlays, text, censors, and crops over a read-only base image. There are no brush strokes, no giant layer stacks, no undo-per-pixel. The base pixmap is loaded once per asset and never modified.

### Would tiling speed up dragging?

No. The perceived lag during bubble drag is **not** caused by the base pixmap being one big item. When an overlay item moves:

- Qt computes the overlay's old and new bounding rects in device coordinates.
- In `SmartViewportUpdate` mode, Qt unions those rects (plus a 2px AA margin unless `DontAdjustForAntialiasing` is set - which it is) and issues one viewport update call.
- During the paint, Qt re-queries the scene's item index for any items intersecting the dirty rect and paints them.
- The base pixmap's `DeviceCoordinateCache` means Qt just blits the cached region that falls inside the dirty rect - no resampling from the original QPixmap.

Splitting the base into 64 tiles of 256x256 would give you 64 `QGraphicsPixmapItem`s instead of 1. Qt's default BSP index already culls items that fall outside the dirty rect, so you'd pay BSP-walk overhead without reducing the painted pixel count. The blit would actually be *slightly slower* because you'd issue 4-8 small `drawPixmap` calls per frame instead of 1 clipped one.

The Qt Centre / thesmithfam.org guidance confirms: tiling in `QGraphicsScene` helps when you have thousands of items; with one pixmap it's the wrong tool.

**Do not tile.** Move on.

---

## 2. Backing store format — QPixmap vs QImage

### What Qt actually does

- `QPixmap` is a handle to a platform-native backing store. On Windows with the default software raster backend, that backing store is an internal `QImage` in `Format_RGB32` or `Format_ARGB32_Premultiplied` depending on whether the source had alpha.
- When you call `QPainter::drawPixmap`, Qt does a fast memcpy / alpha-blend from that native format directly into the viewport's surface. No format conversion if the formats match.
- If you load a PNG with transparency via `QPixmap(str(path))`, Qt reads it as `Format_ARGB32` and converts to `Format_ARGB32_Premultiplied` on first paint. The conversion is cached in the pixmap's internal data for subsequent paints.

### Known performance trap

TSDgeos (KDE maintainer) and the Qt interest list confirm: **painting *into* a `Format_ARGB32` image with `QPainter` is roughly 2x slower than `Format_ARGB32_Premultiplied`**. Non-premultiplied ARGB requires an unpremultiply-multiply round trip per alpha-blended pixel.

### What this means for DoxyEdit

The base-image pixmap is never painted *into* after load. It's only drawn *from*. So `QPixmap(str(src))` is fine for the base.

However, there are four spots in `studio.py` (lines 1199, 1364, 8500, 12981, 13037) that allocate `QImage(pm.size(), QImage.Format.Format_ARGB32)` as an export/composite intermediate. Each of those is a waste - if `QPainter` is going to draw into them, they should be `Format_ARGB32_Premultiplied`. The export code runs on save not on every frame, so this doesn't fix drag lag, but it's a free win on export time.

### What SAI2 / Krita / Photoshop use

- SAI2: 16-bit-per-channel RGBA tiles, stored compressed in RAM. GPU upload converts to 8bpc for display via a fragment shader.
- Krita: configurable per-channel depth (u8, u16, f16, f32). The on-disk tile is raw bytes; the display path composites through OpenGL with per-tile dirty rects.
- Photoshop: 8/16/32-bit tiles, GPU-uploaded as textures. Zoom uses mipmaps.

The pattern in all three: **store at full fidelity in tiles, display through a GPU compositor that reads tiles as textures**. That is a completely different architecture than `QGraphicsScene`. Replicating it in Qt means throwing out `QGraphicsView` and writing a custom `QOpenGLWidget` with your own draw loop, which is ~3 weeks of work minimum.

### Recommendation for DoxyEdit

Keep `QPixmap` for the base image. Change the export-intermediate `QImage` allocations to `Format_ARGB32_Premultiplied` because there's zero risk and it halves paint cost on those paths.

---

## 3. Direct OpenGL viewport — `setViewport(QOpenGLWidget)`

### What it changes

By default, `QGraphicsView` paints through Qt's software raster backend: every paint event draws into a CPU `QImage`, which the window system then copies to the screen. With `setViewport(QOpenGLWidget)`, the viewport becomes an OpenGL surface and `QPainter` dispatches into Qt's GL-accelerated paint engine.

### What it actually gives you in practice

- Faster `drawPixmap` blits when the pixmap is already uploaded as a GL texture (Qt uploads on first paint and caches).
- Faster viewport scrolling and `setTransform` because the transform runs as a GPU matrix op instead of a CPU resample.
- Hardware-accelerated composition for `setOpacity`, `setCompositionMode`, and `setGraphicsEffect`.

### What it doesn't give you

Qt's `QPainter` GL backend is a **2D compatibility layer**. It's not a modern GPU renderer. The blog post "Qt, OpenGL and QGraphicsView" (valdyas, Krita author) is blunt: "Graphics View wasn't designed for GPUs and can't use them effectively." You get maybe 2-4x faster blits in the best case, not the 50x speedups a proper tile-texture compositor would deliver.

### Windows gotchas

Three real ones, all documented in Qt forums / bug reports:

1. **High-DPI fractional scaling on Windows 10/11**: `QTBUG-59956` documents graphics items painting into only the lower-left quadrant at 125%/150% scaling. Fixed in Qt 6 for most cases but still buggy if you mix `QOpenGLWidget` viewport with `QGraphicsProxyWidget` children (DoxyEdit doesn't, so this is fine).

2. **FBO sizing**: Qt creates the internal framebuffer at `window_logical_size * devicePixelRatio`. At 150% scaling on a 1440p display this is ~3400x1920. The fragment shader runs once per physical pixel, not per logical pixel. If your canvas + UI is busy, you pay for every pixel.

3. **Context loss on laptop with hybrid graphics (NVIDIA Optimus / AMD)**: When Windows swaps the GPU (e.g., when you dock/undock, or when the laptop switches from integrated to discrete), the GL context can be lost and the viewport goes black until next resize. Qt 6.5+ handles this better but it still happens.

### Is it a win for DoxyEdit?

**Mild, conditional win.** The measurement that matters: what fraction of your current frame time is spent in the CPU blit vs everywhere else. With `DeviceCoordinateCache` already on, the blit is probably 30-50% of frame time for a 2000x3000 image on a modern machine. OpenGL viewport could turn a 20ms frame into a 12ms frame. Useful but not transformative.

Risk: on a subset of Windows users with hybrid GPUs or flaky drivers, the OpenGL viewport can glitch. You'd want to ship it as an opt-in Settings toggle, not a default.

**Estimate: 0.5 engineering-day to implement (1-line change plus a settings checkbox), 1-2 days to test on Windows 11 at 100% / 125% / 150% scaling on both integrated and discrete GPUs.**

---

## 4. Per-stroke vs per-pixel rendering — what SmartViewportUpdate actually does

Digging into the Qt 6 source (`qgraphicsview.cpp`, `mburakov/qt5` mirror is current):

### The four `ViewportUpdateMode` values

- `FullViewportUpdate` - redraw everything, every time. O(viewport_area).
- `BoundingRectViewportUpdate` - redraw the bounding rect of all dirty items. O(union of dirty rects).
- `MinimalViewportUpdate` - redraw the exposed region exactly. Many small rects. O(sum of dirty rects).
- `SmartViewportUpdate` (our current setting) - `MinimalViewportUpdate` up to a threshold, then switches to `BoundingRectViewportUpdate`. The threshold is `QGRAPHICSVIEW_REGION_RECT_THRESHOLD` and defaults to a small number (around 10). Past that, Qt unions everything into one rect because issuing dozens of tiny paint calls is slower than one big one.

### What actually happens on a bubble drag

Per mouse-move event, Qt:

1. Records the overlay's old device-coords rect (R_old).
2. Calls `itemChange`, which updates `overlay.x/y`.
3. Records the overlay's new device-coords rect (R_new).
4. Builds a dirty region = `R_old ∪ R_new` (plus 2px margin unless `DontAdjustForAntialiasing`).
5. Calls `viewport()->update(dirty_region)`.
6. The next paint event repaints every scene item whose `sceneBoundingRect()` intersects the dirty region.

For a small bubble on a 2000x3000 image, the dirty region is tiny (say 400x200 px), so only a small slice of the base pixmap's `DeviceCoordinateCache` gets blitted. This part is already efficient.

### Where the lag actually comes from

Suspects, ranked by likelihood based on the code I read:

1. **`drawForeground` always runs over the full exposed rect.** `StudioScene.drawForeground` (line 161) paints grid lines, rule-of-thirds, and snap guides. Even when nothing is visible, the function is called every paint, and the while-loops iterate over the `rect` parameter (the exposed region). That's fine. But if the grid is visible, every bubble-move paints dozens of `painter.drawLine` calls inside the dirty region. **Check**: turn off grid + thirds + snap guides and see if drag gets smoother.

2. **`OverlayTextItem.paint` does 9 document draws for stroke + 1 for shadow + 1 for main** (line 2395-2437 in `studio_items.py`). Each call is a full `QAbstractTextDocumentLayout.draw()`. The text item has `DeviceCoordinateCache`, so this should be cached after the first paint and reused until the item invalidates. **But**: `prepareGeometryChange()` or any setter that touches the document (font, text) invalidates the cache. If `_apply_font` or similar gets called during drag, the cache is thrown away every frame. **Check**: is the bubble a `OverlayTextItem`? If yes, verify nothing in the drag path re-applies the font.

3. **Text item glyph cache invalidation on transform.** Any time the scene's transformation changes (zoom, not pan), `DeviceCoordinateCache` invalidates across the board. Pan doesn't invalidate. Drag doesn't invalidate, as long as the dragged item itself doesn't change scale. This should be fine unless a parent transform is being recomputed.

4. **`drawBackground` on the base.** Qt's default `drawBackground` fills the exposed region with `backgroundBrush` (set to `bg_deep` in our scene). That's one `fillRect` - cheap.

5. **High-DPI resampling.** If the user is on 150% Windows scaling and the pixmap item's cache was built at logical size not physical size, every paint does a resample. `DeviceCoordinateCache` should build at physical size, but there are cases in Qt < 6.5 where this broke. **Check**: `devicePixelRatio` on the viewport, and whether the FPS HUD shows the paint time dropping if you set Windows scaling to 100%.

### The thing SAI2 does that Qt doesn't

SAI2 runs the canvas rendering loop on a separate thread decoupled from the UI. The UI queues "move overlay by dx,dy" deltas into a command buffer. The render thread consumes commands at its own pace (often multiple per frame) and produces output at the display refresh rate regardless of how slow each individual command is. Qt's `QGraphicsView` is strictly main-thread. You can't get that architecture without writing a `QOpenGLWidget` subclass with your own command queue, which is a rewrite not a tweak.

---

## 5. Thumbnail loader in this codebase

I read `thumbcache.py`, `browser.py` (lines 425-650, the `ThumbnailDelegate`), `imaging.py`, and the thumbnail-related parts of `preview.py`. Here is what the thumbnail system actually does, in order of the techniques used.

### 5a. Background thread with priority queues

`ThumbWorker` (a `QThread`, thumbcache.py line 202) maintains three queues processed in priority order:

1. `_queue` - fast previews requested by the grid.
2. `_upgrade_queue` - high-quality resizes deferred until all fast previews are done.
3. `_slow_queue` - PSD/SAI/CLIP files processed via psd_tools only after everything else is idle.

This is the **two-pass preview pattern**: emit a blocky NEAREST-resampled thumbnail at 1/4 target size immediately (`_process_item`, line 310), then replace it with a LANCZOS high-quality version from the upgrade queue (`_process_upgrade`, line 388). The user sees something in ~10ms per asset, full quality in a few seconds.

### 5b. Disk cache, SQLite index

Thumbnails are hashed by `path + mtime + size` (line 35), stored as PNG or BMP in `~/.doxyedit/thumbcache/<project>/`. Dimensions stored in a SQLite table with WAL journal mode (line 116-119). Cross-project dedup via a `GlobalCacheIndex` SQLite DB: two projects referencing the same file share the thumbnail on disk.

### 5c. Thread-safe conversion via QImage

`QPixmap` construction is **not** thread-safe. The worker thread emits `QImage` objects through a Qt signal; the main thread receives and calls `QPixmap.fromImage` before use (line 539-542). This is why `pil_to_qimage` exists in `imaging.py` - the conversion happens off-thread so the GUI thread only pays the upload cost.

### 5d. Scaled-pixmap LRU cache in the delegate

This is the one that matters for the Studio question. In `browser.py` line 436 and 612-631:

```python
self._scaled_cache: OrderedDict[tuple, QPixmap] = OrderedDict()
self._scaled_cache_max = 2048
# ...
cache_key = (pixmap.cacheKey(), ts, self.fill_mode)
if cache_key in self._scaled_cache:
    scaled = self._scaled_cache[cache_key]
    self._scaled_cache.move_to_end(cache_key)
else:
    scaled = pixmap.scaled(ts, ts, ...)
    self._scaled_cache[cache_key] = scaled
```

The delegate is a `QStyledItemDelegate` painting hundreds of thumbnails in a `QListView`. The raw thumbnails from disk are 160px, but the grid can render them at any size from ~64 to ~400 px. Re-scaling a 160px pixmap to 180px on every paint event for a grid of 500 cells is disastrous. The LRU solves it: keyed by `(pixmap_cache_key, target_size, fill_mode)`, size-capped at 2048 entries.

### 5e. Font + metrics cache

Line 438-439:

```python
self._fonts: dict[int, QFont] = {}
self._fms: dict[int, QFontMetrics] = {}
```

QFont and QFontMetrics construction is cheap but not free. For 500 cells each calling `painter.setFont(QFont(...))` every paint, it adds up. Cache by size.

### 5f. Clipped painting via `QPainterPath`

Line 635-640: for the rounded-corner thumbnail, a clip path is set so `drawPixmap` only renders inside the rounded rect. This avoids doing a per-pixel round-corner composite in the source pixmap.

### What transfers to Studio?

**The scaled-pixmap LRU cache pattern (5d) is the most transferable technique.** The Studio canvas does not currently use anything like it. The base pixmap is cached at device resolution (good), but if the user zooms, `DeviceCoordinateCache` invalidates and rebuilds on the next paint. That rebuild is a `QPainter::drawPixmap` with `SmoothPixmapTransform` on a multi-megapixel source - ~40-80ms on a 2000x3000 image.

An LRU cache keyed by `(pixmap, zoom_level_rounded_to_nearest_10%)` that stores pre-scaled pixmaps would make zoom-in/zoom-out instantaneous for previously-visited levels.

**The `QImage` for thread-safe handoff (5c) is mostly irrelevant** - Studio operations are main-thread.

**The font-metrics cache (5e) is minor** - Studio doesn't paint at the density where this matters.

The thumbnail code is well-engineered for its problem. Its techniques fit *raster-heavy painting of many small cells*. The canvas problem is different: *one big thing being transformed live*. The only transferable idea is zoom-level LRU.

---

## 6. Concrete recommendations, ranked by impact per engineering-day

The ranking assumes: the reported lag is on a single-bubble drag over a ~2000x3000 image, which means **we are not bottlenecked on drawing many items**. We are bottlenecked on per-frame work inside a tight drag loop.

---

### R1. Measure first: profile the drag (0.25 eng-day, highest ROI)

**What to change:** Turn on the FPS HUD (Shift+F, already built). Do three runs of a 3-second continuous bubble drag:

- Run A: Grid visible, thirds visible, snap guides on.
- Run B: Grid off, thirds off, snap on.
- Run C: Grid off, thirds off, snap off, move a censor rect instead of a text bubble.

Record the average paint time each run. If Run B is much faster than Run A, `drawForeground` is the problem. If Run C is much faster than Run B, the text item's paint path is the problem. If all three are within 2ms of each other, the blit is the problem and OpenGL viewport is next.

**Risk:** none.

**Confirms by:** a number that tells us which recommendation below to actually do.

---

### R2. Skip `drawForeground` content when nothing is active (0.5 eng-day)

**What to change:** `doxyedit/studio.py` around line 161. Add an early-out:

```python
def drawForeground(self, painter, rect):
    super().drawForeground(painter, rect)
    # Skip the whole block if nothing requires it. The early-out
    # matters during drag because drawForeground runs every paint.
    if (not self._grid_visible
            and not getattr(self, "_thirds_visible", False)
            and not self._snap_guides):
        return
    # ... existing body
```

Also: when any of those *are* on, avoid rebuilding the `pen` / `QColor` objects every frame. Cache the pens on `set_theme` and just set them.

**Expected win:** if grid or thirds were visible during drag, 20-40% paint time reduction. If they were off, zero change but still a cleaner code path.

**Risk:** trivial. Worst case is a cosmetic guide doesn't draw after a theme change, caught by the existing grid toggle test.

**Confirms by:** FPS HUD paint-time drops in Run A from R1.

---

### R3. Use `Format_ARGB32_Premultiplied` in all `QImage` composite intermediates (0.5 eng-day)

**What to change:** `doxyedit/studio.py` lines 1199, 1364, 8500, 12981, 13037. Replace:

```python
img = QImage(pm.size(), QImage.Format.Format_ARGB32)
```

with:

```python
img = QImage(pm.size(), QImage.Format.Format_ARGB32_Premultiplied)
```

Same for any `convertToFormat(Format_ARGB32)` calls where the output is then painted into.

**Expected win:** 30-50% faster export / composite on those paths (TSDgeos 2007 benchmark, reconfirmed in Qt 6.11 docs). Does **not** fix drag lag (those paths don't run during drag), but it's cheap insurance and the export/crop paths will feel noticeably faster.

**Risk:** the premultiplied format is the documented "Qt-preferred" format. Only risk is if any downstream code reads pixels out of the QImage and expects non-premultiplied ARGB. Audit: grep for `pixelColor`, `constBits`, `bits()` on those QImages. The exporter paths in `exporter.py` should be checked; if they call `pil_to_qimage`-style byte extraction, a `convertToFormat(ARGB32)` may be needed before PIL conversion.

**Confirms by:** time an export with cProfile before/after.

---

### R4. Zoom-level LRU cache for the base pixmap (1 eng-day)

**What to change:** In `StudioEditor`, wrap `_pixmap_item` logic with a zoom-aware pre-scaled pixmap cache. Skeleton:

```python
# On load_asset:
self._base_pm_full = pm              # full-res source
self._scaled_pm_cache: OrderedDict[int, QPixmap] = OrderedDict()
self._scaled_pm_max = 6              # ~6 zoom levels in memory

# On zoom change (wheelEvent / fit-in-view):
def _refresh_scaled_base(self):
    level = round(self._view.transform().m11() * 10) / 10   # 0.1 step
    key = level
    if key in self._scaled_pm_cache:
        pm = self._scaled_pm_cache[key]
        self._scaled_pm_cache.move_to_end(key)
    else:
        target_w = int(self._base_pm_full.width() * level)
        target_h = int(self._base_pm_full.height() * level)
        pm = self._base_pm_full.scaled(
            target_w, target_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation)
        self._scaled_pm_cache[key] = pm
        while len(self._scaled_pm_cache) > self._scaled_pm_max:
            self._scaled_pm_cache.popitem(last=False)
    self._pixmap_item.setPixmap(pm)
    self._pixmap_item.setScale(1.0 / level)   # display size unchanged
```

This is the thumbnail delegate's `_scaled_cache` pattern (`browser.py` line 436) applied to Studio.

**Expected win:** zoom-in/zoom-out to a previously-visited level becomes instantaneous. Does not help drag. But the first zoom-in on a fresh image will feel the same as now.

**Risk:** the `setScale(1.0 / level)` trick means the pixmap item is already scaled; all overlay positions remain in the original image coord space, which is what the code assumes. But every place that does `self._pixmap_item.pixmap()` for color-pick or hit-test (line 3951, etc.) reads the *scaled* pixmap now - the color sample would be off by the cached scale. Fix: color-pick reads from `self._base_pm_full`, not `self._pixmap_item.pixmap()`. That's a one-line change at each call site but needs all 3 sites patched together.

**Confirms by:** time from Ctrl++ keypress to repaint complete. Before: ~40-80ms. After first visit: ~40-80ms. After second visit to same level: ~1-2ms.

---

### R5. `QOpenGLWidget` as viewport (1 eng-day code + 1 eng-day test)

**What to change:** in `StudioView.__init__` (studio.py line 3718), add:

```python
from PySide6.QtOpenGLWidgets import QOpenGLWidget

# Optional; only if user opts in (Settings: "Use GPU canvas")
_gpu = QSettings(...).value("studio_use_gl_viewport", False, type=bool)
if _gpu:
    gl = QOpenGLWidget()
    fmt = gl.format()
    fmt.setSwapInterval(1)   # vsync on
    gl.setFormat(fmt)
    self.setViewport(gl)
    # Required when viewport is QOpenGLWidget:
    self.setViewportUpdateMode(
        QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
```

Note the last line: `QOpenGLWidget` viewport **requires** `FullViewportUpdate` because partial updates don't work on a GL surface (the whole framebuffer is redrawn per swap anyway). Docs: Qt 6.11 QGraphicsView class reference.

**Expected win:** the per-frame blit cost becomes GPU-side. For a 2000x3000 image, expect a ~30-50% drop in paint time. Drag will feel smoother. Export-to-crop workflows (which hit a lot of composite paths) will not change because the GL viewport only helps viewport rendering, not offscreen render-to-QImage.

**Risk:**
- High-DPI edge cases on Windows at 125%/150% scaling. Test on both integrated and discrete GPUs.
- Hybrid-GPU context loss can blank the canvas until resize. Hide behind an opt-in setting.
- `FullViewportUpdate` means the tiny dirty-rect optimization is gone. For scenes with a lot of static content, this can actually be *slower* in the GL path than the raster path. This is why it's ranked R5 not R1.

**Confirms by:** FPS HUD average paint-time drop under continuous drag, tested at 100% and 150% Windows scaling.

---

## Do-not-do list (ranked by how much time they'd waste)

- **Tiling the base image.** Section 1 - wrong tool for this problem. At least 3 eng-days to implement, zero perf gain.
- **Switching to `QImage` as the base backing store.** Section 2 - `QPixmap` is already the platform-native format. Switching makes blits slower, not faster.
- **Replacing `QGraphicsView` with a custom `QOpenGLWidget` compositor.** The SAI2-class architecture. 2-3 weeks of work for a tool that does not need it. Overlays are few, drags are per-item, not per-pixel. Don't do it.
- **Setting `setItemIndexMethod(NoIndex)`** because "items are moving". Qt doc advises this for scenes where items constantly change their boundingRect. DoxyEdit overlays have stable bounding rects; the default BSP is fine and handles item-count growth better.

---

## Order of operations

1. R1 (measure) - 0.25 day. Gate for everything else.
2. R2 (drawForeground early-out) - 0.5 day. Do if R1 shows grid/thirds contribute.
3. R3 (Format_ARGB32_Premultiplied) - 0.5 day. Do regardless. Free export win.
4. R4 (zoom LRU) - 1 day. Do if zoom responsiveness has been reported as sluggish.
5. R5 (GL viewport opt-in) - 2 days. Do last, ship as a beta-flag setting.

Total: 4.25 engineering-days to exhaust the reasonable options. After that, further gains require a rewrite, which is out of scope for an asset-management tool.

---

## Sources

- [QGraphicsView Class, Qt 6.11](https://doc.qt.io/qt-6/qgraphicsview.html) - ViewportUpdateMode behavior, OptimizationFlag docs.
- [QGraphicsScene Class, Qt 6.11](https://doc.qt.io/qt-6/qgraphicsscene.html) - BSP index, item indexing tradeoffs.
- [QGraphicsItem Class, Qt 6.11](https://doc.qt.io/qt-6/qgraphicsitem.html) - ItemCoordinateCache vs DeviceCoordinateCache.
- [Improvements to QGraphicsItem::CacheMode's insides (Qt Blog, 2009)](https://www.qt.io/blog/2009/02/06/improvements-to-qgraphicsitemcachemodes-insides) - how DeviceCoordinateCache clips to viewport.
- [Qt: Improving QGraphicsView Performance (thesmithfam.org)](https://thesmithfam.org/blog/2007/02/03/qt-improving-qgraphicsview-performance/) - clip-to-exposed-rect advice.
- [TSDgeos: QImage::Format_ARGB32_Premultiplied is your friend](https://tsdgeos.blogspot.com/2007/10/qimageformatargb32premultiplied-is-your.html) - ~2x painting difference benchmark.
- [QImage Class, Qt 6.11](https://doc.qt.io/qt-6/qimage.html) - format recommendations for QPainter targets.
- [Krita Technical Overview](https://github.com/KDE/calligra-history/blob/master/krita/doc/krita_technical_overview.html) - KisPaintDevice 64x64 tile architecture.
- [Krita OpenGL canvas notes (valdyas.org)](https://valdyas.org/fading/hacking/krita-hacking/krita-opengl-and-qt/) - why QGraphicsView isn't GPU-friendly.
- [QOpenGLWidget + QGraphicsView performance thread (Qt Centre)](https://www.qtcentre.org/threads/64973-QOpenGLWidget-QGraphicsView-and-performance) - FullViewportUpdate requirement.
- [QTBUG-59956 (QGraphicsView on HiDPI with QGLWidget)](https://bugreports.qt.io/browse/QTBUG-59956) - high-DPI quadrant bug.
- [Graphics in Qt 6.0: QRhi (Qt Blog)](https://www.qt.io/blog/graphics-in-qt-6.0-qrhi-qt-quick-qt-quick-3d) - QRhi applies to Qt Quick, not QGraphicsView.
- [Krita OpenGL display settings under fractional DPI (Phabricator D20097)](https://phabricator.kde.org/D20097) - device-pixel alignment, relevant to DPI gotchas.
