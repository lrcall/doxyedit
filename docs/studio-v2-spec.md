# Studio v2 Spec

## Context

Mid-session user asked for "much more robust canvas options, close to a
real graphics program." Current Studio (`studio.py`, 2500 lines) is a
crop-plus-overlay editor. Survey of what's there:

- 9 scene item types (crop, censor, text overlay, image overlay, note,
  annotations).
- 9 tools with Q/W/E/R/C/N shortcuts.
- Layer panel exists (right sidebar, L to toggle) but drag-reorder is
  wired UI-side with no handler.
- Rubber-band multi-select works.
- Rotation on overlays; resize on crops + censors.
- Arrow-key nudge for most items.
- Undo covers Add/Delete only — every other mutation goes direct.
- Snap grid available, snap guides between items do not exist.
- Rotate handles exist for overlays; censors lack them.

Good foundation. The gap to "real graphics program" is not a rewrite,
it's closing the rough edges.

## Goals

1. **Every mutation undoable.** Mixed direct-writes are the biggest
   single bug surface.
2. **Selection transforms feel first-class.** Rotate, flip, align,
   distribute, snap guides, nudge on anything selected.
3. **Layer panel actually operates on layers.** Drag to reorder
   z-order, click to toggle visibility, inline opacity slider.
4. **Copy/paste scene items** across sessions (clipboard JSON).
5. **Smart guides** when dragging — show snap lines to other items'
   edges and the canvas center.

Not goals (yet): layer masks, blend modes, vector shape library, pen
tool, non-destructive filters, multi-canvas compositing. Those are
plan-j material if you still want them after v2.

## Out of scope

- Changing the underlying QGraphicsScene architecture.
- Replacing PIL-based export with a new pipeline.
- Adding raster paint tools (brush, bucket, clone).
- Plugin / scripting surface.

## Proposed work, in order

### Milestone A — Undo coverage (2 days)

Gap: overlay opacity/font/color/rotation sliders write directly to
`overlay.*` without emitting a command. Same for crop edits, note
creation, platform-scope toggle, z-order shifts.

**Approach.** Add `MutateOverlayCmd`, `MutateCropCmd`, `MutateCensorCmd`
commands in `studio.py`. Each stores `(item, field, old, new)`. Every
slider handler wraps the mutation in a command. Undo stack size stays 50.

**Done when.** Ctrl+Z reverses any slider move, context-menu action,
crop edit, or text color change.

### Milestone B — Layer panel drag-reorder (half day)

Gap: `_layer_panel.setDragDropMode(InternalMove)` set without a model
change handler. Drag currently visually reorders the list but the scene
item Z-values stay put.

**Approach.** Wire `_layer_panel.model().rowsMoved` to a handler that
remaps Z-values based on new row order. Keep the 100/200/400 band
separation (censor < overlay < crop) so dragging a censor below an
overlay is prevented or auto-bounded.

**Done when.** Dragging a layer row up/down changes its Z-order
visibly in the scene.

### Milestone C — Smart snap guides (1-2 days)

Gap: canvas has a grid; no guides between items or to canvas edges.

**Approach.** Override `StudioScene.mouseMoveEvent` to compute edge
positions of the currently-dragged item and every other item. For each
edge (left/right/top/bottom/centerH/centerV), if within 5px of another
item's matching edge or the canvas center, snap and render a dashed
line in `drawForeground`. Guide lines disappear on mouse release.

**Done when.** Dragging a text overlay shows dashed guides that align
to other overlays and the canvas center. Drop snaps to within 1px.

### Milestone D — Copy/paste + duplicate offset (half day)

Gap: Ctrl+D duplicates in place with 20px offset; no cross-session
copy/paste.

**Approach.** On Ctrl+C, serialize selected items' dataclass state to
clipboard as JSON with a `doxyedit/scene-items` MIME type. On Ctrl+V,
deserialize, add to scene with a 20px offset from cursor. Extends
existing duplicate logic.

**Done when.** Copy a text overlay in project A, paste into project B,
styling preserved.

### Milestone E — Alignment + distribute (half day)

Gap: no alignment tools.

**Approach.** Toolbar button with 6-item dropdown: Align Left, Align
Right, Align Top, Align Bottom, Distribute Horizontal, Distribute
Vertical. Operates on 2+ selected items. Align = snap to the common
edge of the selection bounding box. Distribute = even spacing between
outer items.

**Done when.** Select 3 text overlays, click "Align Left" → all three
share the leftmost x.

### Milestone F — Rotate handles on censors (half day)

Gap: censors can't rotate; overlays can.

**Approach.** Add a `_RotateHandle` subclass alongside `_ResizeHandle`.
Render it above the top edge centerpoint. Drag computes angle from
item center; `setRotation`.

**Done when.** Right-click a censor → "Rotate" shows an angle slider
OR a rotate handle appears when the item is selected.

### Milestone G — Opacity slider per layer (half day)

Gap: overlays have `opacity` field on the dataclass; slider exists at
the top-level panel only for the selected item. Should be per-row in
the layer panel too.

**Approach.** Layer panel row gets an inline slider (small, right-
aligned) that updates item.setOpacity on change + emits
MutateOverlayCmd for undo.

**Done when.** Layer panel row has a slider that changes just that
layer's opacity, persists across save/reload.

### Milestone H — Flip H / Flip V (half day)

Gap: no flip.

**Approach.** Context menu entries on overlays and crops. `setScale(-1, 1)`
or `(1, -1)` via QTransform. Wrapped in MutateOverlayCmd for undo.

**Done when.** Flip a logo horizontally via right-click, save, reload —
flip persists.

### Milestone I — Unified nudge (quarter day)

Gap: arrow-key nudge works for censors/overlays; crops/notes skipped.

**Approach.** Extend the nudge handler at studio.py:916-939 to include
all selected scene items regardless of type. Respect snap grid if
active.

**Done when.** Arrow key nudges any selected item by 1px (Shift: 10px).
Selected crops and notes move too.

## Total estimate

Tier-1 (A-I): ~1 week of focused work. Each milestone is an independent
commit; user can test between.

Deferred (post-v2): layer masks, blend modes, shape library, pen tool,
non-destructive filters, multi-canvas compositing. Fork to plan-j when
scope is picked.

## Risks

- **Undo command proliferation.** Adding a command class per
  mutation type will bloat studio.py. Mitigation: generic
  `SetAttrCmd(item, attr, old, new)` that most handlers can use.
- **Smart guides performance.** Computing snap targets on every
  mouseMoveEvent is O(N) per move event. Mitigation: only compute when
  drag starts, cache edge lists, invalidate on scene change.
- **Layer panel drag reorder** must not cross z-band (censors below
  overlays below crops). Need a "bounce back" animation or a soft
  prevent if user tries to drag a censor above an overlay.
- **Copy/paste JSON** across different DoxyEdit versions has a schema
  compat question. Mitigation: version tag in the MIME payload, reject
  older.

## Open questions

1. **Rotate handle vs slider?** Overlays already have a rotation slider.
   Add a visible rotate handle on selection, keep slider, or replace
   slider with a handle?
2. **Layer panel drag semantics.** Hard-prevent cross-band drags, or
   allow with a "these layers have different depths" tooltip?
3. **Smart guide color.** Use `theme.accent` (visible on any bg) or a
   fixed magenta like most vector apps?
4. **Copy/paste between projects with different platforms** — if a
   platform-scoped overlay is pasted into a project that lacks that
   platform, drop the scope or keep (inactive) it?

## Files touched

Primary: `E:\git\doxyedit\doxyedit\studio.py`.
Secondary: `E:\git\doxyedit\doxyedit\preview.py` (ResizableCropItem
if rotate handles extend to crops too).
New: none; v2 stays in-place.
