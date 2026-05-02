# DoxyEdit Backlog

Snapshot of deferred work after the v2.4 session. The historical v1.1
feature-parity list lives at `docs/archive/TODO.md` (every item shipped);
this file is scoped to what's been planned but not yet shipped.

## Plan-H remainders

### ~~H4.1 Stage 2 — more window.py → project_io.py~~ ✓ shipped
All 10 target methods moved into `SaveLoadMixin` in commits
54d4288 → e1ac354 (April 2026 cron session). `_save_project`,
`_save_project_as`, `_open_project`, `_load_project_from`,
`_reload_project`, `_save_collection`, `_save_collection_quick`,
`_open_collection`, `_reload_collection`, `_locate_last_collection`
all live in `doxyedit/project_io.py` now.

### ~~H4.2 — tab_manager.py~~ ✓ shipped
Commit 9ae61f9 created `doxyedit/tab_manager.py` with
`TabManagerMixin`. All 9 listed methods plus `_rename_proj_tab` moved
out of window.py. window.py shrunk ~150 lines.

### ~~H4.3 — OneUp push phase off UI thread~~ ✓ shipped
- 5c320d5 prepped `_push_post_to_oneup` with a `status_cb` parameter.
- 532d968 added `_OneUpPushThread(QThread)` skeleton.
- 61e366b wired the thread into `_check_autopost`.
- 3cacb4f split sync reconciliation from push pass.
- 796be3a wired the thread into `_on_sync_oneup_fetched` proper.
The 30+ HTTP calls on the UI thread are gone.

### H6 — interactive verification pass
User-driven. Walk through every commit's verification steps on a
70k-asset project:
- Tab swap latency
- Cancel button on Auto-Post mid-Playwright
- Duplicate-post dialog still fires after fetch split
- `_save_project_silently` on external edits
- Tag colors across all 13 themes
- Every `dist/DoxyEdit-*.exe` snapshot still launches (rollback drill)
- Studio v2: undo for every slider, copy/paste across projects,
  alignment, snap guides, rotate handle on censor, flip export
  correctness

## Studio v2 Tier-3 — plan-i candidates

Listed in `docs/studio-v2-spec.md` under "Deferred". If user wants
more canvas power beyond the v2 shipped items:

- **Layer masks** — per-layer alpha mask painted via brush
- **Blend modes** — multiply/screen/overlay per layer (non-destructive
  composite in the exporter)
- **Shape primitives** — rectangle, ellipse, line, arrow with
  stroke/fill that persist to asset.overlays (new overlay.type=shape)
- **Pen tool** — vector path drawing
- **Non-destructive filters** — blur, color adjust, levels applied
  per layer
- **Multi-canvas compositing** — arrange multiple images as layers
  in one canvas

Scope: weeks per item. Each warrants its own plan-i-Nx file.

## Review findings from review.md not yet addressed

### Still live
- **window.py inline stylesheets** — ~~progress label padding~~ (done
  via theme QSS). Status bar save-flashes at 2576, 2587, 6357 still
  inline; they use theme tokens so low priority. Most other inline
  styles have been swept; tokenization validator passes clean
  (commit b75752d).
- ~~**Unified ImageViewer component**~~ ✓ shipped. New
  `doxyedit/imageviewer.py` `BaseImageViewer` (commits 195bec3 +
  a583ea3 helpers). `PreviewPane` and `ImagePreviewDialog` migrated
  (c50062a, ac15b89). The third site (composer_left.ImagePreviewPanel)
  is QLabel + scaled QPixmap — different rendering category, not a
  duplicate of the QGraphicsView path.

### Done in the autonomous batch after v2.4 docs
- ~~OneUp sync debug prints~~ → `logging` (commit d061c84)
- ~~imagehost.py `_upload_cache` LRU~~ (commit 09f3985)
- ~~config system doc~~ → `docs/config-layering.md` (commit 2dcd54b)

### Parked as "not a bug"
- `_update_progress` 4-pass claim (reviewer misread; it's single-pass)
- `imgur` hardcoded anonymous client_id (public key, documented)
- Kanban CSS selectors in themes.py (harmless; rules don't match
  anything after kanban.py deletion)

## Studio v2 follow-up polish (small)

### Accessibility / affordance
- ~~**Context menu entries for shortcuts**~~ — done (commits 24f7f51,
  461f897, d665978).
- ~~**Tooltip on the Align dropdown**~~ — done (commit 3e9373c).
- ~~**Visual indicator for locked layers**~~ — done (commit 3e9373c).

### Feature rounding
- ~~**Rotate handle on crops**~~ ✓ shipped end-to-end. CropRegion
  gained a `rotation` field (9e99fea), exporter rotates-before-crop
  across all 5 export paths via `apply_crop_rect` (bc15e60),
  context-menu Set Rotation... entry (4556b18), dashed rotated
  outline indicator (33e1a8a), drag-and-resize preserves rotation
  (1dccaa6), visual rotate handle on ResizableCropItem with Shift
  snap to 15° (910279a).
- ~~**Grid spacing spinner**~~ — done in v2.5 (commit 0134247) plus
  a grid-on/off checkbox, rule-of-thirds toggle, and QSettings
  persistence.
- ~~**"Reset Transform" context menu entry**~~ — done for both image
  and text overlays (commits 24f7f51, d665978).
- **Per-layer "Use on all platforms" reset** — already available via
  the platform submenu's "All Platforms" entry which clears
  `overlay.platforms`.

### Done in v2.5 Studio full-graphics-product push
- Eyedropper tool (I key / Pick toolbar button)
- Arrow annotation tool (A key / Arrow button + endpoint handles)
- Shape annotation tool — rectangle / ellipse with stroke/fill,
  corner resize handles (Shift = square), snap-integrated
- Layer panel thumbnails for all overlay/censor types
- Persistent guides (saved to Asset.guides)
- Recent-color swatches strip in toolbar
- Rulers (horizontal + vertical) with drag-out guides
- Rule-of-thirds composition overlay
- Checkerboard transparency background + drop shadow on canvas
- Undo/Redo toolbar buttons with auto-enable state
- Active tool highlight via QSS :checked on checkable tool buttons
- Focus mode (. key / Focus button)
- Spacebar pan (Photoshop convention)
- Ctrl+0 / Ctrl+Shift+0 / Ctrl+1 / Ctrl+ / Ctrl- zoom shortcuts
- Alt+click duplicate, Tab/Shift+Tab cycling, Ctrl+Shift+I invert
- Number keys 0-9 set opacity on selected overlays
- Shift-drag constrains censor/crop to square, Shift+rotate to 15°,
  Shift+arrow-draw snaps to 45°
- Text background color (new CanvasOverlay.background_color)
- _wrap_text_to_width helper so export honors text overlay width
- Save/Reset Default Text Style, Watermark Style, preferred Censor
  style — all persisted via QSettings
- Copy Style / Paste Style per-type
- Rotate 90 CW / CCW context menu
- Crop right-click Rename / Duplicate / Export / Delete;
  double-click-to-rename
- Cursor XY, selection count, and selected-item geometry in status bar
- X/Y spinboxes in layer properties panel
- Layer panel section headers, (hidden) prefix, Shift+click hide,
  Ctrl+click lock, right-click menu, double-click rename
- Canvas right-click menu (fit, zoom, grid/thirds toggle, copy image,
  canvas bg color)
- Ruler corner click = fit view; right-click ruler = Clear All Guides
- Guides draggable along perp axis, double-click to delete, snap on
  drag
- Flip canvas preview (⇄) for composition checks
- Replace Image on existing watermark/logo
- Align > Center on Canvas (H / V / Both)
- Escape returns to Select tool
- Studio button in preview pane + floating preview dialog (S key too)
- F1-F6 tab jumps (Shift+F2 for rename)
- Arrow keys nudge arrows too; arrows participate in snap, select-all,
  delete, copy/paste style

### Done (v2.4 polish autonomous batch)
- Censor context menu reaches parity with overlays (Duplicate +
  Z-order) — 461f897
- Undo for censor style + platform changes — 1fc4e00
- Autosave interval configurable via QSettings — e300594
- Flip + Reset Transform on text overlays — d665978
- Individual-file drag-drops don't feed Folder Scan auto-rescan —
  d016a69

### Post-fix items
- **Tiny window flash on project load** — fix shipped for
  `_open_collection` and `_detach_proj_tab`. User reported it may
  still happen in other paths; awaiting a screenshot to pinpoint.

## Feature ideas (not in any plan)

Parked here so they don't get lost.

- **Kanban board** — was deleted as dead code; could be reimagined if
  there's a workflow need.
- **Bulk operations UI** — multi-select browser + batch tag / star /
  delete / export.
- **Notification center** for posting results across platforms.
- **Tag hierarchy** — parent tags, children inherit.
- **Per-post export history / log** showing what went where on which
  date.
- **Onboarding walkthrough** for first-time users.
- **Scriptable plugin surface** — load user-authored Python hooks for
  custom export pipelines, tag rules.

## Non-urgent cleanup

- Collapse `doxyedit/formats.py` helpers and dead-code module deletion
  post-mortem into a consolidated architecture note.
- Consider switching to `CLAUDE.md`-style project rules doc for the
  user-authored slash commands / `Skill` entries.
- `nuitka-crash-report.xml` appears in working tree after failed
  builds; add to `.gitignore`.
