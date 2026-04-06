---
tags: [changelog, versions, history]
description: Full version history for DoxyEdit.
---

# Changelog

---

## v1.9.0 — 2026-04-06

> [!note] Major Release
> Preview window overhaul, cross-project thumbnail cache sharing, health panel, and fast cache mode.

### Preview Window (Major Overhaul)

- **Single-instance preview** — opening preview when one is already open reuses and updates it instead of spawning a second
- Minimize / maximize / restore buttons on preview window
- Preview window fully themed: title bar color via DWM, full stylesheet applied
- Image centered on load and on every navigation
- **Free overpan** — scene rect has a large margin so you can pan past image edges
- Space, Tab, Down = next image; Backspace, Up, Left = previous image
- Keys always navigate regardless of which button has focus
- Add Note / View Notes buttons are non-focusable so they never steal Space key
- View Notes defaults to off on open
- Enter key opens preview for selected thumbnail
- Thumbnail selection syncs with preview navigation in both flat and folder views

### Thumbnail Navigation

- Up/Down arrow keys in the thumbnail view navigate images and sync thumbnail selection
- Arrow key navigation auto-scrolls to keep the selected thumbnail visible (EnsureVisible)
- Fixed: navigating via arrows in preview no longer causes browser scroll-jump on click

### Thumbnail Cache

- **Cross-project cache sharing** — `content_index.db` (SQLite) at the base cache dir maps cache keys to PNG paths across all projects; new projects reuse already-cached thumbnails automatically
- Per-project dimension index moved from `index.json` to `cache.db` (SQLite, WAL mode); old `index.json` files auto-migrate on first run
- **Fast Cache Mode** (Tools menu) — stores thumbnails as uncompressed BMP for faster reads at the cost of disk space
- Fixed re-entrant call crash when Cache All completes and user immediately hits cache again

### Theming

- Scrollbar handles use the accent color (bright on hover)
- Default theme changed from Vinik 24 to Soot

### Folder View

- Section headers indent 3 spaces per depth level relative to the shallowest folder in the current view

### Health Panel

- "Remove Missing" button — removes all assets whose source file no longer exists, with confirmation dialog
- Connected to Tools > Remove Missing Files menu action

### Import

- Paste Folder (File menu) — imports a folder path from clipboard

---

## v1.5.1 — 2026-04-05

### Hover Preview

- Shows full original resolution (e.g., "2475 × 3375px") below preview image
- Shows full file path below resolution
- Larger info text (12px) for readability

### UX Improvements

- Ctrl+Shift+C copies full file path of selected asset(s) to clipboard
- Splitter handles widened by 5px for easier grabbing (tag panel + tray)

---

## v1.5.0 — 2026-04-05

> [!note] UI Overhaul
> Toolbar restructure, Sort by Folder, drag from tray, asset file watcher.

### UI Overhaul

- Left toolbar removed — Tags and Tray toggle buttons moved to browser toolbar
- Browser toolbar uses FlowLayout — buttons wrap on narrow windows
- Tag bar now shows custom/project tags only (built-in presets removed)
- Count label (shown/starred/tagged) moved to status bar
- Tags + Tray buttons positioned first in toolbar, side by side

### Sort by Folder

- New "By Folder" sort mode groups assets by source folder
- Folder labels shown on first item of each group (last 2 path components)
- Collapse All / Expand All buttons appear in By Folder mode
- Collapsed folders persist during session

### Drag & Drop from Tray

- Tray items can be dragged out to external apps (Photoshop, Explorer, etc.)
- Multi-select drag supported
- Uses QDrag with file URL mime data

### Design System Fixes

- Button styles unified — all `_btn_style` methods now include `font-size`
- `Theme.btn_style()` shared method added
- TagPanel scales fonts with Ctrl+=/- (was frozen at hardcoded sizes)
- Custom tag colors in side panel now read from `tag_definitions`
- Tag search is case-insensitive
- Ctrl+Click tag search: text set before mode toggle for reliable filtering

### Asset File Watcher

- Source image changes detected automatically via QFileSystemWatcher
- Thumbnails regenerate when files are modified on disk
- `ThumbCache.invalidate()` method for clearing individual entries

### Bug Fixes

- Clear Unused Tags added to Tools menu
- Auto-tag defaults to off
- Fixed NAME_ROLE self-reference crash in tray
- Fixed `_cb → checkbox` AttributeError in tag panel font scaling

---

## v1.4.0 — 2026-04-05

> [!note] Tag Definitions, Project Management, Work Tray Overhaul

### Tag Definitions & Aliases

- New `tag_definitions` dict in project JSON — maps tag IDs to display properties (label, color, group)
- New `tag_aliases` for backward-compat rename resolution (old → canonical ID auto-resolved on load)
- Legacy `custom_tags` list auto-migrated to `tag_definitions` on save
- Renaming a tag creates an alias so old references resolve automatically
- `TagPreset.from_dict()` class method eliminates repeated construction

### Asset Specs vs Notes

- New `specs` dict field on Asset for CLI/tool metadata (size, palette, relations)
- Auto-migrates CLI-generated notes into `specs.cli_info` on load
- Notes panel now shows only human-written notes

### Project Management

- **Edit > Move to Another Project** — transfer selected assets to existing project
- **Edit > Move to New Project** — create new project from selection
- **F5** reloads project from disk (picks up external edits from Claude CLI)
- **Shift+F5** for thumbnail recache

### Work Tray Overhaul

- Tray fully hides when closed (no more lingering 16px strip)
- Remembers width when toggling with Ctrl+T
- Column view modes: ☰ button cycles list → 2-col grid → 3-col grid
- ✕ close button in header
- Quick Tag submenu in tray right-click context menu
- Tray thumbnails preserved on project reload

### Context Menu Improvements

- Tags submenu shows union of ALL selected assets' tags
- Click tag in submenu removes it from all selected (with − prefix and display labels)
- Quick Tag submenu with ✓ marks, splits into columns when >10 tags
- Copy Filename added alongside Copy Path
- Selection preserved when using any context menu action

### More Shortcuts & Filters

- Escape — deselect all
- Alt+A — add tag to selected
- Ctrl+H — temporary hide/restore
- Ctrl+F — focus search box
- Shift+E — notes overlay popup
- "Has Notes" filter checkbox on search bar
- "Select all with tag" in tag panel right-click

---

## v1.3.0 — 2026-04-05

### Tag System Improvements

- Both tag locations (top bar + side panel) refresh on every tag-modifying event
- Custom tags sorted alphabetically in side panel
- **Collapsible tag sections** — click section header to collapse/expand
- First tag section labeled "Default"
- Tags preserve user's exact casing and spaces
- "Select all with tag" in tag panel right-click menu
- Quick Tag multi-column submenu in browser right-click

### New Shortcuts

- Escape — deselect all
- Alt+A — add tag to selected assets
- Ctrl+H — temporary hide selected
- Ctrl+F — focus search box
- F5 — reload project from disk
- Shift+F5 — refresh thumbnails

### View Menu Additions

- Show Resolution toggle
- Show Tag Bar toggle
- Show Hidden Only filter
- Hover Preview Delay setting (200–1200ms, persisted)
- "Has Notes" filter checkbox

### UI & UX Fixes

- Thumbnail filename text scales with Ctrl+=/- (was hardcoded)
- Notes area splitter size persists across sessions
- Canvas tools hidden when not on Canvas tab
- Hover preview hides before re-triggering delay when moving between thumbnails
- Copy Filename added to browser right-click menu

---

## v1.2.0 — 2026-04-05

> [!note] Claude CLI Integration
> Full bidirectional sync between DoxyEdit and Claude CLI via file watching.

### Claude CLI Integration

- 8 new CLI commands: search, starred, ignored, notes, add-tag, remove-tag, set-star, export-json
- Auto-reload: DoxyEdit watches the project JSON and reloads when Claude CLI modifies it
- Full bidirectional sync — Claude edits JSON, DoxyEdit updates live

### Simplify Round 5

- Removed duplicate auto_suggest_tags (dead code)
- LRU eviction for delegate scaled pixmap cache (500 max)
- `get_asset` uses dirty flag invalidation
- Tag color dots no longer reset on image click

### Fixes

- Star clicking works via delegate hit detection
- Auto-hide images when tagged with eye-hidden tag
- Cache All hides progress bar when nothing to cache
- Ctrl+V handles multiple paths/files
- Tag panel dots show tag color permanently

---

## v1.1.0 — 2026-04-05

### Post-1.0 Fixes & Features

- Star clicking works again (delegate hit detection in star rect area)
- Auto-hide images when tagged with an eye-hidden tag
- Ctrl+V handles multiple paths/files, discards unsupported types
- Cache All hides progress bar when all already cached
- Tag dots show tag's own color (not fitness), labels bolded
- Eye button 120% larger (24px)
- Hint label hidden for cleaner UI
- Tray fully collapses to 16px handle
- Full menu bar: Edit (8 actions), Tools (7 actions), Help (2 actions)
- Project Summary compact dialog
- Comprehensive TODO.md tracking all implemented/pending features

---

## v1.0.0 — 2026-04-05

> [!note] First Stable Release

- Work Tray — collapsible right panel with ◀/▶ handle, persists across all tabs
- Tray context menu: Preview, Copy Path/Filename, Open in Explorer, Move to Top/Bottom
- Progress bar for cache-all and long tasks
- Middle-click instant preview
- Ctrl+click multi-select tag rows for batch Hide/Show/Delete
- Ctrl+T toggles tray, Ctrl+L toggles tag panel
- Resizable notes area (vertical splitter)
- Tokenized design system (font, padding, radius scale together)
- Horizontal scrollbars themed
- 3px rounded corners on thumbnails
- Smooth pixel scrolling, zoom keeps focus on selected item
- Hover preview customizable size (125–300%)
- Thumbnail quality setting (128–1024px)
- 7 themes fully applied to all widgets including tray, splitters, progress bar
- Project backup (.bak) created on open
- Sort mode, eye-hidden tags, tray items all persist in project file

---

## v0.9.0 — 2026-04-05

> [!note] QListView Migration — Major Performance Upgrade

- Replaced QGridLayout with 200+ widget instances with a single QListView
- Custom ThumbnailModel (QAbstractListModel) + ThumbnailDelegate (QStyledItemDelegate)
- **Smooth virtual scrolling** — no more paging, all images accessible by scrolling
- **Instant zoom** — Ctrl+scroll changes grid size without rebuilding
- **Zero widget overhead** — delegate paints directly, no widget creation/destruction
- Selection built-in: Ctrl+click, Shift+click, Ctrl+A all work natively
- ~230 lines removed (1103 → 872 lines)

### Eye Toggle (Photoshop-style Layer Visibility)

- Each tag has an 👁 eye button — click to hide all images with that tag
- Multiple eyes can be toggled independently

---

## v0.6.1 — 2026-04-05

- View Notes button (V key) toggles saved annotations visible/hidden
- Annotations load from asset.notes on preview open
- Per-project persistence: custom tag shortcuts, hidden tags, main window position

---

## v0.6.0 — 2026-04-05

- Grid rebuild wrapped in setUpdatesEnabled (eliminates per-widget repaint flicker)
- Tag changes no longer trigger full grid rebuild (instant tagging)
- "Cache All" checkbox pre-generates all thumbnails in background
- Ctrl+A selects all thumbnails
- Recursive import with "Import recursively?" prompt

---

## v0.5.0 — 2026-04-04

> [!note] Major Consolidation Release

- SAI/SAI2 shell thumbnails via Windows Shell API (SaiThumbs)
- Disk thumbnail cache (`~/.doxyedit/thumbcache/`)
- Preview annotations (N key, draw box, type text)
- 4-section tag panel (Content, Platform, Custom, Visual)
- Pin tag to top of section (gold border)
- Custom keyboard shortcuts (right-click → Set Shortcut Key)
- Search supports glob patterns (`*.png`, `hero_*`)
- Unicode stars ★/☆ cycling 5 Vinik colors
- 7 themes with full object-name-based theming coverage

---

## v0.3.0 — 2026-04-04

- SAI/SAI2 files show real thumbnails via Windows Shell API
- Disk thumbnail cache keyed by file path + modification time
- Preview annotations persist with project
- Custom tags appear in both tag bar AND side panel immediately
- Tag bar excludes platform/size tags

---

## v0.2.0 — 2026-04-04

- PSD/PSB files load with full thumbnail and preview support via psd-tools
- 7 themes: Vinik 24 (default at the time), Warm Charcoal, Soot, Bone, Milk Glass, Forest, Dark
- Tags split into two sections: Content/Workflow and Platform/Size targets
- Custom tags via + button with auto Vinik color assignment
- Star cycles through 5 Vinik colors (gold, blue, green, rose, red)
- Shift+click range select, Ctrl+click multi-select, Alt+click to Censor
- Delete key soft-deletes (tags as "ignore")
- Auto visual property tagging on import
- Ctrl+scroll zoom (80px to 320px)
- Recent Projects and Recent Folders in File menu

---

## v0.1.0 — 2026-04-04

Initial release. PySide6 thumbnail browser with paging, lazy loading, multi-select, tagging, search/sort/filter. Non-destructive censor editor. Canvas annotation. Platform assignment dashboard. Auto-save, drag-drop, keyboard shortcuts. CLI pipeline for Claude integration.
