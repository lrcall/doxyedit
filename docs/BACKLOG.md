# DoxyEdit Backlog

Snapshot of deferred work after the v2.4 session. `docs/TODO.md` tracks
legacy v1.1 feature parity — this file is scoped to what's been planned
but not shipped as of v2.4.

## Plan-H remainders

### H4.1 Stage 2 — more window.py → project_io.py
Stage 1 moved `_watch_project`, `_save_project_silently`, `_autosave`,
`_autosave_collection` into `SaveLoadMixin`. Stage 2 should move:
- `_save_project`, `_save_project_as` (interactive save dialogs)
- `_open_project`, `_load_project_from`, `_reload_project`
- `_save_collection`, `_save_collection_quick`, `_open_collection`,
  `_reload_collection`, `_locate_last_collection`

**Why deferred.** Each of these owns a QFileDialog or QMessageBox plus
side-effects that chain back into `_rebind_project`. Moving them
requires either passing the MainWindow as `parent=` for the dialogs
(mixin can do that — `self` is the MainWindow) or splitting out a
`DialogHelper` seam. The mixin approach is fine; just wanted one
pass of real-world testing on Stage 1 before proceeding.

**Effort.** M. Mechanical copy + delete, verify `py run.py` after each
method move.

### H4.2 — tab_manager.py
Move tab slot management out of window.py into `doxyedit/tab_manager.py`
(~500 lines):
- `_project_slots` list + getters
- `_switch_to_slot`, `_save_current_slot`
- `_close_proj_tab`, `_detach_proj_tab`, `_add_project_tab`
- `_on_proj_tab_changed`, `_on_proj_tab_moved`
- `_preset_context_menu`, `_rename_proj_tab`

**Prereq.** Stage 2 of H4.1 first, so both mixins are proven.

### H4.3 — OneUp push phase off UI thread
`_on_sync_oneup_fetched` currently loops `_push_post_to_oneup` on the
UI thread after the fetch. Each push is a synchronous MCP HTTP call.
For a sync with 10 queued posts on 3 accounts each, that's 30×
sequential network calls on the main thread.

**Approach.** Extract a `_OneUpPushThread(QThread)` that runs the
push queue. Per-post signal updates `self.status.showMessage`. After
the last push, emit `pushed_summary` which triggers
`_refresh_social_panels` + autosave.

**Risk.** Medium. `_push_post_to_oneup` touches status bar, post
model fields, and `self._dirty`. All mutations on self.project.posts
are fine from a worker (pure data); the status calls need to marshal
via signal.

**Effort.** M. Similar shape to the G3 fetch-off-thread work.

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
- **window.py inline stylesheets** — progress label padding (828),
  status bar save-flashes (2576, 2587, 6357). H5.4 did the tab bar +
  new-tab button; these remain.
- **OneUp sync debug prints** — ~30 `print("[Sync] ...")` calls scattered
  through `_on_sync_oneup_fetched` and helpers. Route through `logging`
  or remove.
- **Unified ImageViewer component** — preview.py + composer_left +
  stray `QPixmap(path)` sites. Three near-duplicate preview
  implementations. Consolidate.
- **imagehost.py `_upload_cache`** — unbounded dict. Add LRU.
- **config system doc** — 4 parallel sources (`config.py`,
  `config.yaml`, per-project JSON, QSettings). No diagram. Add header
  comment in config.py or a `docs/config-layering.md`.

### Parked as "not a bug"
- `_update_progress` 4-pass claim (reviewer misread; it's single-pass)
- `imgur` hardcoded anonymous client_id (public key, documented)
- Kanban CSS selectors in themes.py (harmless; rules don't match
  anything after kanban.py deletion)

## Studio v2 follow-up polish (small)

### Accessibility / affordance
- **Context menu entries for shortcuts**. Right-clicking an overlay
  should show "Flip Horizontal (Ctrl+Shift+H)" so users discover
  keyboard shortcuts.
- **Tooltip on the Align dropdown** explaining the 2+ / 3+ selection
  requirement.
- **Visual indicator for locked layers** in the layer list
  (e.g., a 🔒 prefix).

### Feature rounding
- **Rotate handle on crops** — user-visible inconsistency since
  censors and overlays rotate but crops are axis-only. CropRegion
  would need a `rotation` field; exporter would need to rotate-before-
  crop. Non-trivial, but rounds out the system.
- **Grid spacing spinner** — toolbar input for the snap grid spacing
  (currently hardcoded via `STUDIO_GRID_SPACING`).
- **"Reset Transform" context menu entry** — one click clears
  rotation + flip_h + flip_v + scale back to identity.
- **Per-layer "Use on all platforms" reset** — one click clears
  `overlay.platforms` so it applies everywhere.

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
