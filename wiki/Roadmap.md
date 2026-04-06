---
tags: [roadmap, todo, planned, future]
description: Planned features and improvements for DoxyEdit — organized by effort and priority.
---

# Roadmap

Features still pending from TODO.md, organized by estimated effort. Items marked as completed in recent versions have been removed; this list reflects what is genuinely still open.

---

## Near-Term (Small Effort)

These are well-scoped features that are close to the existing codebase.

### Drag-Select Over Tag Rows

Rubber-band / drag selection across tag rows in the Tag Panel. Currently you click individual tags or Ctrl+click for multi-select. A drag gesture would let you select a range of tags in one motion.

### Drag-Drop Tags Between Groups

Drag a tag from one section to another (e.g., move a custom tag into a different group), or create a new tag group by dropping. Requires a rethought data model for tag grouping.

### Multiple Tray Views (Named Trays)

The Work Tray currently holds one flat list. Named trays (tabs or labeled slots) would allow multiple staging areas — e.g., one tray per platform or per campaign stage.

### Nuitka Build Optimization

The `build.bat` Nuitka build works but has room for size and speed optimization. The output `.exe` could likely be smaller with better include/exclude tuning.

---

## Medium-Term (Substantial Features)

These require design decisions and moderate implementation work.

### Platform Status Dashboard Tab

A dedicated tab (or panel within Platforms) showing the full per-platform slot grid with:
- Thumbnail previews in each slot
- Status badges (pending / ready / posted / skip)
- Quick status-change buttons
- Export readiness summary

This is distinct from the current Platforms tab which shows slot metadata but not the full dashboard view.

> [!note]
> Currently tracked as "Platform panel with asset thumbnails in slots" in TODO.md (medium priority).

### Crop Region Selector Tool

A visual overlay crop tool that shows the target platform dimensions overlaid on the image and lets you drag-set the crop region. Per platform slot dimensions. Would replace the current manual crop entry.

### Markdown-Driven Project Config

Generate UI elements (platform slots, tag presets, campaign stages) from `.md` configuration files rather than hardcoded Python. Would make adding new platforms or tag sets a data-edit rather than a code change.

### Actual File Browser

A built-in filesystem browser panel where you can navigate folders, preview files before importing them, and drag files directly into the project. Currently all import goes through dialogs or drag-from-Explorer.

### Drag-Drop Tags Between Groups

Full tag group drag-drop with group creation. See near-term section — listed here also because the full version (new group creation) is medium effort.

### Kanban / Gantt Posting Schedule Board

A campaign scheduling view — cards for each platform slot arranged on a timeline or Kanban board. Shows posting dates, readiness status, and links to assigned assets.

> [!note]
> This is one of the original "future vision" features. It would integrate with the posting checklist already present in the project notes panel.

---

## Long-Term / Exploratory

These are large or exploratory features that may require significant architecture work or external dependencies.

### Perceptual Hash Variant Detection

Group visually similar files using perceptual hashing (e.g., pHash or dHash). Mark one file as canonical and others as variants (different resolutions, crops, watermarked versions). Useful for deduplication and managing version sets.

> [!note]
> Partially related to the "Duplicate file finder/unifier" that was completed, but the perceptual (visual similarity) version is a distinct feature.

### Platform-Specific Crop Presets UI

Full visual overlay crop tool with platform presets — shows the crop region for each platform slot as a draggable overlay on the source image. Integrated with the Platforms tab and exportable directly.

### OpenGL Viewport for Grid Rendering

Replace the QListView + delegate painting with an OpenGL viewport for the thumbnail grid. Would allow much larger grids (10,000+ images) without scroll lag. Currently the QListView with virtual scrolling handles ~1000–2000 images well.

### QListView Model-View for Tray

The Work Tray is currently implemented as `QListWidget` (item-based). Migrating to `QListView` + `QAbstractListModel` would match the main browser and allow larger tray lists with the same virtual scrolling benefits.

---

## Known Deferred Issues

### Folder View Overlap / Click Issues

The "By Folder" sort mode has some overlap and click accuracy issues with folder header rows in certain configurations. This has been noted and deferred — it requires reworking folder header rendering in the delegate.

### Folder Fold Plan (Stacked QListViews)

A deeper folder view implementation using stacked `QListView` instances per folder (collapsible). Currently folder view uses in-line headers. The stacked approach would allow true per-folder expand/collapse with independent scroll. Implementation plan exists but not yet started.

---

## Completed Recently (v1.9 / v1.5)

For reference, these were formerly on this list and are now done:

- Cross-project thumbnail cache sharing (content_index.db)
- Fast Cache Mode (BMP thumbnails)
- SQLite cache index (replaces index.json)
- Remove Missing Files (Health panel)
- Preview window single-instance + theming
- Arrow key navigation in thumbnail view with auto-scroll
- Sort by folder with depth-indented headers
- Paste Folder (File menu)
- Scrollbar accent color theming
- F2 rename file on disk
- Reverse tag search (Find Similar)
- Smart export gap detection

---

## Related

- [[Changelog]] — what has already been implemented
- [[Interface Overview]] — current feature set
- [[CLI Reference]] — automation possibilities
