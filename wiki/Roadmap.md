---
tags: [roadmap, todo, planned, future]
description: Live roadmap for DoxyEdit. Most past entries shipped — see linked archives below for the historical list.
---

# Roadmap

Live deferred work. Anything previously on this page that ships moves
to the changelog instead of staying here as a struck-through entry, so
this file stays scannable.

---

## Live (deferred / not yet started)

### Eagle Gallery 3-panel tab

Three-pane layout matching Eagle's gallery look: folder tree on the
left, thumbnail grid in the middle, asset detail on the right. Hooked
on `View > Layout > Eagle` once built. Pairs with the existing
File Browser sidebar (Ctrl+B) which already provides the folder tree
and asset count badges. Reference: `wiki/UI Direction — Eagle Layout.md`.

### Studio Tier-3 (each is weeks of work)

Listed in `docs/studio-v2-spec.md` "Deferred". If the user wants more
canvas power beyond what shipped in v2.5:

- **Layer masks** — per-layer alpha mask painted via brush
- **Blend modes** — multiply / screen / overlay per layer
  (non-destructive composite in the exporter)
- **Shape primitives as overlays** — rectangle / ellipse / line /
  arrow with stroke + fill that persist to `asset.overlays` (new
  `overlay.type=shape`)
- **Pen tool** — vector path drawing
- **Non-destructive filters** — blur, color adjust, levels per layer
- **Multi-canvas compositing** — arrange multiple images as layers
  in one canvas

### Feature ideas (all shipped in v2.5.5 / v2.5.6 - kept here as record)

All seven previously-parked items shipped during the May 2026 cron
session. Listed for traceability rather than as live roadmap.

- ~~Kanban board~~ - shipped 6b7921d as Tools > Kanban Board.
- ~~Bulk operations UI~~ - shipped 31c263d as Edit > Bulk Actions.
- ~~Notification center~~ - shipped 0bcfddb as Tools > Posting
  Notifications.
- ~~Tag hierarchy~~ - shipped 66032c3 + 970bb68 (parent_id field +
  Set Parent picker).
- ~~Per-post export history / log~~ - shipped 8eda67c + 4f27920
  (SocialPost.posting_log + View Posting Log dialog).
- ~~Onboarding walkthrough~~ - shipped 65d7640 (Help > Welcome /
  First Run + auto-open on first run).
- ~~Scriptable plugin surface~~ - shipped 249101a + 4f80493 +
  49f0b52 (full doxyedit/plugins.py + 6 lifecycle events + Help >
  Plugins... enable/disable dialog + docs/plugins.md).

### Cleanup / non-urgent

- Consolidate `doxyedit/formats.py` helpers + dead-code module
  deletion post-mortem into a single architecture note
- Migrate user-authored slash commands / `Skill` entries to a
  `CLAUDE.md`-style project rules doc

---

## Related

- [[Changelog]] — what shipped
- [[Interface Overview]] — current feature set
- [[CLI Reference]] — automation possibilities
- `docs/BACKLOG.md` — refactor plans + smaller follow-ups
- `docs/archive/TODO.md` — historical v1.1-era todo list (all
  items done; kept for reference)
- `docs/archive/NEW_FEATURES.md` — April 2026 session changelog
