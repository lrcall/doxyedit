---
tags: [roadmap, todo, planned, future]
description: Planned features and improvements for DoxyEdit — organized by effort and priority.
---

# Roadmap

Features still pending from TODO.md, organized by estimated effort. Items marked as completed in recent versions have been removed; this list reflects what is genuinely still open.

---

## Near-Term (Small Effort)

These are well-scoped features that are close to the existing codebase.

### Zoom Slider (remaining near-term)

Visible drag slider in the toolbar for thumbnail size (80–320px). Supplements Ctrl+scroll.

### Rename Detection for Missing Files

When the Health scan finds a missing file, check if it was renamed rather than deleted. Strategy:
1. Look in `asset.source_folder` for files with the same extension that aren't already in the project
2. If exactly one candidate exists, auto-suggest "Renamed to X?" with an **Update Path** button
3. If multiple candidates, show a picker
4. Could also match by file size as a secondary signal for confidence

Implementation: add a `_find_rename_candidates(asset)` helper in `health.py`. In `_build_asset_row` for missing assets, show a "Find Rename" button that calls it. On confirm, update `asset.source_path` and `asset.source_folder` and re-scan.

### Right-Click to Dismiss from Recent Lists

Right-click any entry in File > Recent Projects or File > Recent Folders to get a "Remove from list" option. Recent lists are stored in QSettings — just filter out the chosen path and rebuild the menu. Wire to the existing `_rebuild_recent_menus()` call in `window.py`.

### Project Accent Color — Title Bar Tint

When a project accent color is set, apply it to the Windows title bar as well. Use `DwmSetWindowAttribute` with `DWMWA_CAPTION_COLOR` (Windows 11) or `DWMWA_COLORIZATION_COLOR` (Windows 10) via ctypes. Fall back gracefully on older Windows. Wire to the existing `_set_project_color` / `_apply_theme` flow in `window.py`.

### Taskbar Flash on Cache Complete

Flash the DoxyEdit taskbar button when a Cache All operation finishes. Use `QWinTaskbarButton` (Qt Windows Extras / `PySide6.QtWinExtras` if available) or the raw Win32 `FlashWindowEx` API (`FLASHWINFO` struct, `FLASHW_TRAY | FLASHW_TIMERNOFG` flags so it only flashes when DoxyEdit is not the foreground window). Wire to the existing cache-all completion signal in `browser.py`.

### Zoom Slider

Visible drag slider in the toolbar for thumbnail size (80–320px). Supplements existing Ctrl+scroll. One `QSlider` wired to the existing `_thumb_size` logic. Show current px value as a label next to it.

### Full Screen Button in Preview

A fullscreen toggle button in the `ImagePreviewDialog` toolbar. `showFullScreen()` / `showNormal()` toggle, or wire to the existing `_toggle_fullscreen()` method which already exists but may not have a visible button.

### Open in Native Editor

Right-click → **Open in Native Editor** on any asset. Per-file-type editor associations stored in QSettings:

```
native_editor/.psd = C:/Program Files/Adobe/Photoshop/Photoshop.exe
native_editor/.sai = C:/Program Files/SAI/SAI.exe
native_editor/* = (system default)
```

**Tools > Configure Editors…** dialog: table of extension → exe path, with Browse button per row. Falls back to `os.startfile()` (system default) when no custom path is set. Also available as **F3** or **Ctrl+Enter** keyboard shortcut on selected asset.

### Drag from Thumbnail Grid to External Apps

Drag one or more selected thumbnails out of the main grid directly to Photoshop, Explorer, etc. Uses `QDrag` with `QMimeData` file URLs — same pattern already implemented for the Work Tray. Wire `mouseMoveEvent` on `QListView` to initiate drag when threshold distance is exceeded.

> [!note]
> Work Tray drag-out already works. This extends the same behavior to the main grid.

### Hover-Only Filenames

View menu toggle: **Show Filenames** (always / hover only / never). When set to hover-only, the delegate suppresses the text draw unless the item is hovered. Cleaner grid at small zoom levels. Store in QSettings.

### Format Filter

Filter the grid by file extension. A dropdown or button group: All / PSD / PNG / JPG / SAI / Other. Filters `_filtered_assets` by `Path(source_path).suffix.lower()`. Useful in mixed-format folders.

### Drag-Select Over Tag Rows

Rubber-band / drag selection across tag rows in the Tag Panel. Currently you click individual tags or Ctrl+click for multi-select. A drag gesture would let you select a range of tags in one motion.

### Drag-Drop Tags Between Groups

Drag a tag from one section to another (e.g., move a custom tag into a different group), or create a new tag group by dropping. Requires a rethought data model for tag grouping.

### Multiple Tray Views (Named Trays)

The Work Tray currently holds one flat list. Named trays (tabs or labeled slots) would allow multiple staging areas — e.g., one tray per platform or per campaign stage.

### Quick-Launch Program List

A configurable list of frequently-used apps (Photoshop, SAI, Clip Studio, etc.) accessible from the Tools menu or a toolbar button. Click an entry to open selected assets in that program. Config stored in QSettings — extension → exe path, same table as "Configure Editors". Could also populate a right-click **Send To ▸** submenu if desired (implementation is trivial via `ShellExecuteEx` on the system Send To folder at `%APPDATA%\Microsoft\Windows\SendTo`).

### Nuitka Build Optimization

The `build.bat` Nuitka build works but has room for size and speed optimization. The output `.exe` could likely be smaller with better include/exclude tuning.

---

## Medium-Term (Substantial Features)

These require design decisions and moderate implementation work.

### Docked Preview Panel

An optional inline preview panel docked inside the main window (right side or bottom), so you can see the full-resolution image without a floating window. Toggle between docked and floating modes. The existing `ImagePreviewDialog` content (viewer, notes, nav buttons) moves into a `QSplitter` pane.

- Docked mode: preview fills right pane, thumbnail grid shrinks left
- Floating mode: current behavior (separate window)
- Remembered per session in QSettings
- Docked panel has the same navigation (Space/arrow keys) as the floating preview

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

A built-in filesystem tree panel for navigating the local filesystem, previewing files before importing, and dragging files directly into the project. Currently all import goes through dialogs or drag-from-Explorer.

**Reference design:** Eagle-style collapsible folder tree (see screenshot reference). Key features:
- Root folder pinning — pin one or more top-level directories as roots
- Collapsible tree with `▶ / ▼` toggles per folder
- Asset count badge right-aligned on each row (only shown if > 0 DoxyEdit assets in that folder)
- Clicking a folder filters the main grid to that folder's assets
- Right-click → Import This Folder, Open in Explorer, Pin as Root
- Drag a folder from the panel into the grid = import
- Indent lines (connecting guide lines) showing hierarchy depth
- Folders with no imported assets shown dimmed; folders with assets shown at full opacity

**Implementation notes:**
- Use `QTreeView` + `QFileSystemModel` for the filesystem tree (Qt provides this natively)
- Override the model to inject asset counts per folder from `project.assets`
- Asset counts are derived from `asset.source_folder` — group by folder path on project load
- Panel lives in the left sidebar, below or replacing the current Tag Panel toggle
- Width matches the existing tag panel (~220px default)
- Pairs naturally with the Eagle-style Gallery tab (see [[UI Direction — Eagle Layout]])

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

## Completed Recently (v2.0)

- Rename detection in Health panel (auto-suggest + Locate… button)
- Right-click to dismiss from Recent Projects / Recent Folders
- Windows 11 title bar tinted to project accent color (DwmSetWindowAttribute)
- Taskbar flash on Cache All complete (FlashWindowEx, only when unfocused)
- Full screen button in preview toolbar
- Preview hint bar folds gracefully when window is narrow
- Hover-only filenames (View > Filenames — Always / Hover Only / Never)
- Format filter dropdown in browser toolbar (All / PSD / PNG / JPG / SAI / WEBP / CLIP / Other)
- Ctrl+C copies selected assets as file objects (Explorer-compatible)
- Global Ctrl+Shift+Alt+Insert drop hotkey (WM_DROPFILES to window under cursor)
- Local mode (repo-relative paths for multi-PC git projects)
- Remove Folder from Project (right-click folder header)
- Fix Escape deselect; fix cross-folder sticky selection
- On Top / Pin buttons in preview window fixed

---

## Completed (v1.9 / v1.5)

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
