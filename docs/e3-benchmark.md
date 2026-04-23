# E3 off-thread overlay cache — benchmark

Commits: `b4362fd` (infrastructure) + `5fce279` (paint wiring)

## Scene

Single `OverlayShapeItem` with shape_kind=`speech_bubble`, 200×120 body,
white fill + 3px black stroke, `bubble_wobble=0.5`, `tail_curve=0.3`.

Paint target: 400×300 `QImage`, ARGB32 premultiplied. 200 paints per
measurement after 3 warm-up paints + full threadpool drain.

## Numbers

| Path | Per-paint time |
|---|---|
| Cache hit (params unchanged) | **0.035 ms** |
| Live (params invalidate every paint) | 0.787 ms |
| **Speedup** | **22.6x** |

## What the fast path skips

The live path per paint:
- `_paint_speech_bubble`: rounded-rect body + triangular tail + `QPainterPath.united()`
- 72-sample wobble loop (`bubble_wobble > 0.01`)
- Tail bezier evaluation (`tail_curve != 0`)
- `painter.drawPath(path)` + stroke pass

The fast path: one `painter.drawImage()` at the offset position.

## When the fast path hits

The `_cached_render_key` is a tuple of every overlay attribute that
affects appearance (`shape_kind`, `shape_w/h`, `corner_radius`,
`bubble_roundness`, `bubble_oval_stretch`, `bubble_wobble`, `tail_curve`,
tail offset, `star_points`, `inner_ratio`, `polygon_vertices`).

Keys that are NOT in the tuple: `x`, `y`, `rotation`, `opacity`.
Those are applied by `painter` at draw time on top of the cached image,
so dragging an overlay or tuning its opacity HITS the cache.

Keys that ARE in the tuple trigger an off-thread rebuild. The rebuild
takes ~0.8ms on the worker thread; once done, subsequent paints are
0.035ms until the next param change.

## Invalidation story

Scenario: user drags the `bubble_wobble` slider from 0 → 1 over 60 ticks.
- Frame N: wobble changes → `_schedule_cached_render` fires, worker
  runs ~0.8ms, GUI paint is still live (1 expensive paint).
- Frame N+1: wobble changes again → schedule again. Worker is busy, the
  re-schedule is tracked via `_render_token` so only the latest result
  is adopted.
- User releases the slider → worker finishes → cached QImage adopted
  → next paint is the fast 0.035ms path.

Net: the user sees live paints during active slider drag (~0.8ms each,
still under a 16ms frame budget) and instant-feeling once they stop.
Crucially, OTHER scene items (non-dragged overlays) still hit their
cache on every paint, so scene complexity doesn't compound.

## Not yet extended to

- `OverlayTextItem`: already uses Qt's `DeviceCoordinateCache` which
  handles the same case. E3 extension would bypass Qt's cache but adds
  complexity for marginal gain.
- `OverlayImageItem`: has `_source_pixmap` cache for the scale slider
  path; paint is already a simple `drawPixmap`.
- Shapes with blend_mode != "normal": fast path is skipped because the
  cached QImage would composite differently than per-path rendering.
- Gradient fills (`gradient_linear`, `gradient_radial`): the render
  helper doesn't build gradients yet, so these take the live path.
