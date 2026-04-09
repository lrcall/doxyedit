---
tags: [roadmap, todo, planned, future]
description: Planned features and improvements for DoxyEdit — organized by effort and priority.
---

# Roadmap

Features still pending from TODO.md, organized by estimated effort. Items marked as completed in recent versions have been removed; this list reflects what is genuinely still open.

---

## Near-Term (Small Effort)

These are well-scoped features that are close to the existing codebase.

### ~~Zoom Slider~~ ✓

Visible drag slider in the toolbar for thumbnail size (80–320px). Supplements Ctrl+scroll. Done.

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

### ~~Open in Native Editor~~ ✓

Right-click → **Open in Native Editor** + **F3** shortcut. `os.startfile()` fallback. **Tools > Configure Editors…** dialog with extension→exe table + Browse button.

Per-file-type editor associations stored in QSettings:

```
native_editor/.psd = C:/Program Files/Adobe/Photoshop/Photoshop.exe
native_editor/.sai = C:/Program Files/SAI/SAI.exe
native_editor/* = (system default)
```

**Tools > Configure Editors…** dialog: table of extension → exe path, with Browse button per row. Falls back to `os.startfile()` (system default) when no custom path is set. Also available as **F3** or **Ctrl+Enter** keyboard shortcut on selected asset.

### ~~Drag from Thumbnail Grid to External Apps~~ ✓

Drag one or more selected thumbnails out of the main grid directly to Photoshop, Explorer, etc. Done — `QDrag` + `QMimeData` with file URLs, initiated when mouse moves past `startDragDistance` threshold.

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

### ~~Quick-Launch Program List~~ ✓

**Tools > Launch In** submenu — lists all configured editors. Click an entry to open selected assets matching that extension. Shares the same `native_editor/<ext>` QSettings table as Configure Editors.

### Quick-Launch Program List (was)

A configurable list of frequently-used apps (Photoshop, SAI, Clip Studio, etc.) accessible from the Tools menu or a toolbar button. Click an entry to open selected assets in that program. Config stored in QSettings — extension → exe path, same table as "Configure Editors". Could also populate a right-click **Send To ▸** submenu if desired (implementation is trivial via `ShellExecuteEx` on the system Send To folder at `%APPDATA%\Microsoft\Windows\SendTo`).

### Nuitka Build Optimization

The `build.bat` Nuitka build works but has room for size and speed optimization. The output `.exe` could likely be smaller with better include/exclude tuning.

---

## Medium-Term (Substantial Features)

These require design decisions and moderate implementation work.

### ~~Docked Preview Panel~~ ✓

Done (v2.2). Docked `PreviewPane` in right splitter with Ctrl+D toggle. Pop-out button to float into `ImagePreviewDialog`. Navigation keys work in both modes. Position persisted in QSettings.

### ~~Platform Status Dashboard Tab~~ ✓

Done (pre-v2.2). Dual-view `PlatformPanel` with cards + dashboard toggle, per-platform progress bars, slot grid with thumbnails + status badges, image hive.

### ~~Crop Region Selector Tool~~ ✓

Done (v2.2). C key toggle in preview, platform aspect ratio dropdown (grouped by platform with separators), dark mask overlay. `ResizableCropItem` with 8 drag handles for post-drawing editing. Crops persist in `asset.crops`.

### ~~Markdown-Driven Project Config~~ ✓

Done (v2.2) as YAML config. `config.yaml` in project directory defines custom platforms with slots. Loaded via `load_config()` + `merge_platforms()` in models.py. Tools > Edit Project Config opens the file.

### ~~Actual File Browser~~ ✓

Done (v2.2). `FileBrowserPanel` with QTreeView + QFileSystemModel, asset count badges, dim empty folders, active highlight, auto-expand to project folders, grid-to-tree sync, subfolder filtering, drag-to-import, inline search, pinned folders. Toggle: Ctrl+B.

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

### ~~Drag-Drop Tags Between Groups~~ ✓

Done (pre-v2.2). `_TagContainer._finish_reorder()` supports cross-section moves with `tag_section_changed` signal. Rubber-band drag-select also implemented.

### ~~Kanban / Gantt Posting Schedule Board~~ ✓

Done (v2.2). `KanbanPanel` with 4 status columns (Pending/Ready/Posted/Skip). Draggable `KanbanCard` widgets. Drop changes `PlatformAssignment.status`. Accessible via Schedule tab.

---

## Long-Term / Exploratory

These are large or exploratory features that may require significant architecture work or external dependencies.

### ~~Perceptual Hash Variant Detection~~ ✓

Done (v2.2). `compute_phash()` in autotag.py (average hash, 8x8 grayscale). Computed during thumbnail `_process_upgrade()`, stored in `asset.specs["phash"]`. Tools > Find Similar Images groups by hamming distance ≤ 8. Tag as "variant" or remove extras.

### ~~Platform-Specific Crop Presets UI~~ ✓

Done (v2.2). Crop preset dropdown grouped by platform with separators + disabled headers. `ResizableCropItem` with 8 resize handles for post-drawing editing. Crops saved per-asset with platform labels.

### ~~OpenGL Viewport for Grid Rendering~~ — Not Needed

Assessed (v2.2): QListView already handles 70k items with virtual scrolling + lazy loading. Bottleneck is thumbnail generation, not rendering. No action needed.

### ~~QListView Model-View for Tray~~ ✓

Optimized (v2.2) with O(1) `_id_to_row` index mapping instead of full migration. Eliminates 5 O(n) linear scans in remove/move/update operations.

---

## ~~Known Deferred Issues~~ — Resolved

### ~~Folder View Overlap / Click Issues~~ ✓

Fixed (v2.2). Added `hasHeightForWidth()` + `heightForWidth()` to `FolderSection`, conservative fallback in `_compute_height()` (300 instead of 1000), scroll viewport resize handler. Eliminates overlap on first layout pass.

### ~~Folder Fold Plan (Stacked QListViews)~~ ✓

Already implemented. `FolderSection` + `FolderListView` is exactly the stacked QListViews architecture. Each folder has its own collapsible `QListView` with independent model. heightForWidth fix completed the implementation.

---

## Completed Recently (v2.2) — 33 commits, 2026-04-09

- File Browser sidebar (Ctrl+B): QTreeView + QFileSystemModel, asset count badges, dim empty folders, theme-aware, auto-expand, grid-to-tree sync, subfolder filtering, drag-to-import, inline search, pinned folders
- Smart Folders: save/load filter presets via View > Smart Folders menu
- Info Panel (Ctrl+I): asset metadata display with inline tag editing (pill widgets + autocomplete), inline notes editing, color palette swatches
- Kanban schedule board: 4-column drag-drop status board (Pending/Ready/Posted/Skip) as Schedule tab
- YAML config: custom platform definitions via config.yaml (Tools > Edit Project Config)
- Perceptual hash: compute_phash in thumbnail pipeline, Tools > Find Similar Images dialog
- Preview pop-out button + resizable crop handles (8 drag handles, persistent overlays)
- Toolbar declutter: 4 checkboxes moved to View/Tools menus
- Folder view overlap fix: heightForWidth on FolderSection
- Nuitka build: 11 new exclusions for smaller output
- Tray performance: O(1) id-to-row index mapping
- Bug fixes: collections warn+reload, preview multi-monitor position, tray drag-drop
- Theme color audit: all new panels use theme tokens

---

## Completed Recently (v2.1)

- Zoom slider in toolbar row2 (80–320px, synced with Ctrl+scroll)
- Drag from thumbnail grid to external apps (QDrag + file URLs)
- Open in Native Editor: F3 shortcut + right-click menu, `os.startfile()` + custom exe per extension via QSettings

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
