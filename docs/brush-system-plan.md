# Studio Brush System — Primitive but Smooth

## Goal

A basic brush tool that feels **smooth and responsive**, not feature-rich.
No pressure sensitivity, no blending modes beyond normal, no smudge/erase
cleverness. Just: pick a color, pick a size, drag on canvas, get a clean
stroke. Like MS Paint but without the stairstepping.

## Scope — what lands in v1

| In | Out |
|----|-----|
| Round brush with soft-ish edges (one hard + one 50% alpha falloff) | Texture brushes, dual brush, scatter |
| Size slider (2-300 px) | Pressure, tilt |
| Color picker (reuse existing palette dots) | Gradients, patterns |
| Single color, single opacity | Color dynamics, jitter |
| Stroke smoothing (lag cursor by N samples, average) | Pressure-driven taper |
| Eraser mode (alpha-erase, not a "soft" rubber) | Blur/smudge |
| Per-brush layer (one QGraphicsPixmapItem per stroke session) | Infinite history |
| Undo via existing QUndoStack | Per-layer masks |

## Architecture — one component, one file

`doxyedit/brush.py`. ~400 lines max. Imported by studio.py.

### Data model (added to CanvasOverlay)

```python
@dataclass
class CanvasOverlay:
    type: str                 # new value: "brush"
    brush_strokes: list       # list of BrushStroke dicts (for "brush" type)
    ...

# BrushStroke is a dict, not a class — keeps it JSON-roundtrippable:
{
    "points": [(x1, y1), (x2, y2), ...],
    "size": 24,
    "color": "#ff4080",
    "opacity": 1.0,
    "erase": False,
}
```

One `CanvasOverlay(type="brush")` = one "brush layer" in the layer
panel. A user can have multiple brush layers. Each stroke within a
layer is recorded as a BrushStroke dict and flattened to the layer's
pixmap after release.

### Runtime item

`BrushLayerItem(QGraphicsPixmapItem)` — subclass of
`QGraphicsPixmapItem` sized to the base image rect. Holds a QPixmap
backing buffer. When the user draws, we blit directly into the buffer
using a QPainter with a round brush.

- Cache mode: DeviceCoordinateCache (same as other overlays)
- Z-value: 250 (above watermarks/text at 200-249, below annotations at 300+)

### Drawing loop

In `StudioScene.mousePressEvent` when tool is BRUSH:

```
1. If active brush layer is None:
     create new BrushLayerItem, add to scene, push BeginStrokeCmd
2. Start a new BrushStroke: record (x,y) at press, size, color, opacity, erase
3. Draw single dot at (x,y) into layer.pixmap
```

In mouseMoveEvent:

```
1. Append (x,y) to current stroke's points
2. Draw line from prev_point → current_point into layer.pixmap with
   brush painter (round pen, alpha, CompositionMode_SourceOver or
   CompositionMode_DestinationOut for erase)
3. Call layer.update(dirty_rect) where dirty_rect = bbox(prev, current)
   expanded by brush size. This is why SmartViewportUpdate matters —
   only that small region repaints.
```

In mouseReleaseEvent:

```
1. Finalize stroke, append BrushStroke dict to layer.overlay.brush_strokes
2. Push FinishStrokeCmd (for undo)
3. Sync to asset.overlays via debounced _sync_overlays_to_asset()
```

### Smoothing (the "smooth" in primitive but smooth)

Cursor position arrives jittery — every OS mousemove has subpixel
wobble. Two cheap smoothing passes before blit:

1. **Sample buffer**: keep last N=4 raw points in a deque. Draw using
   the weighted average (newest 40%, prev 30%, ...). Adds a ~1 frame
   lag but kills 90% of zigzag.

2. **Catmull-Rom spline**: between recorded points, interpolate 3-4
   intermediate points and draw short line segments between them.
   Basically treats the deque as control points and blits a smooth
   curve instead of a polyline.

Both together = smooth strokes at any mouse speed without needing
pressure input or a tablet. Cost: 4 extra drawLine calls per move event.
Cheap.

## Persistence

BrushStrokes round-trip via the overlay dict:

```json
{
    "type": "brush",
    "brush_strokes": [
        {"points": [[100, 50], [102, 51], ...], "size": 24, "color": "#ff0", "opacity": 1.0, "erase": false},
        {"points": [[200, 80], ...], "size": 12, "color": "#000", "opacity": 0.5, "erase": true}
    ],
    "x": 0, "y": 0, "opacity": 1.0, "rotation": 0
}
```

On load: create BrushLayerItem with empty pixmap, replay all strokes
into its buffer. Expensive only once per load.

Export: `brush_strokes` replays into the export pipeline's PIL
composite — same replay code path, targeting PIL.ImageDraw instead of
QPainter.

## UI

New toolbar button: **🖌 Brush** (toggle). When active:

```
[Size: ────●─────── 24px]  [Color: ●]  [Opacity: ──●──]  [Eraser: ☐]
```

- Size slider is the same shape as the existing Scale slider (reuse
  component and style).
- Color picker is a single swatch button that opens QColorDialog.
  Below it: five recent colors as clickable mini-swatches.
- Opacity slider shares look with the existing Opacity slider.
- Eraser checkbox — when on, draws with CompositionMode_DestinationOut
  against the layer. (Does NOT erase the base image. The base is
  untouched.)

Bracket keys (`[` / `]`) change size by ±2px — Photoshop muscle memory.

## Perf budget

At 60fps we have 16ms per frame. A typical brush session looks like:

- mouseMove fires ~60-120/sec on a fast mouse
- Each move: smoothing (0.1ms) + QPainter blit (0.5-2ms) + repaint
  the dirty region (0.5-1ms) = **< 4ms worst case**

Guardrail: if `_fps_rolling_ms` goes > 10ms during an active stroke,
suspend the Catmull-Rom pass and fall back to raw polyline. The user
won't see quality change mid-stroke; we just widen the shot budget.

## Phases

| Phase | Deliverable | Days |
|-------|-------------|------|
| 1 | Data model (CanvasOverlay.type="brush", BrushStroke dict) | 0.5 |
| 2 | BrushLayerItem class, empty buffer, round-brush painter | 1 |
| 3 | StudioScene.mousePress/Move/Release routing when tool=BRUSH | 1 |
| 4 | Smoothing (deque average + Catmull-Rom) | 0.5 |
| 5 | Eraser mode via CompositionMode_DestinationOut | 0.25 |
| 6 | Toolbar UI: button + size + color + opacity + eraser checkbox | 0.5 |
| 7 | Save/load roundtrip via brush_strokes dict | 0.5 |
| 8 | Export pipeline integration (PIL replay) | 0.5 |
| 9 | Undo integration (BeginStrokeCmd / FinishStrokeCmd) | 0.5 |
| 10 | Layer panel integration (brush layers show up, reorder, hide) | 0.25 |

Total: ~5.5 days of focused work.

## Definition of "smooth"

- 60fps sustained on a 4096×4096 base image with 10 existing brush
  strokes already in the scene.
- No visible stairstepping at any brush size.
- No perceptible lag between cursor and stroke (< 1 frame).
- Zooming in 4x mid-stroke doesn't hitch.

FPS HUD (Shift+F) confirms the numbers during QA.

## Risk log

- **QPainter into QPixmap is not hardware-accelerated on Windows**.
  Fine at brush sizes ≤ 100, can stutter at 300px on very large
  canvases. Mitigation: clamp max brush size to `min(300, image_w // 8)`.

- **Undo memory**: storing every stroke's point list grows quickly.
  A single dense stroke = 200-500 points = ~5KB. 50 strokes = 250KB.
  Acceptable. If it becomes a problem, compress the polyline with
  Ramer-Douglas-Peucker (ε = 0.5px).

- **Eraser scope**: eraser only erases within the current brush layer.
  Users expecting it to erase overlays or the base image will be
  confused. Add a tooltip: "Erase brush strokes on this layer".

## Out of scope — deliberate

No pressure sensitivity. No tilt. No texture brushes. No lasso/fill.
No layer masks. No blending modes beyond normal + erase. No filters
applied to brush layers.

Those belong in v2 if v1 proves valuable. Shipping v1 first lets us
see if anyone actually draws in DoxyEdit or just uses watermarks and
text overlays.
