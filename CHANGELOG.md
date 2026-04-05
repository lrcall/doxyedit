# DoxyEdit Changelog

## v1.4.0 — 2026-04-05

### Tag Definitions & Aliases
- New `tag_definitions` dict in project JSON — maps tag IDs to display properties (label, color, group)
- New `tag_aliases` for backward-compat rename resolution (old → canonical ID auto-resolved on load)
- Legacy `custom_tags` list auto-migrated to `tag_definitions` on save
- Renaming a tag creates an alias so old references resolve automatically
- `TagPreset.from_dict()` class method eliminates repeated construction

### Asset Specs vs Notes
- New `specs` dict field on Asset for CLI/tool metadata (size, palette, relations)
- Auto-migrates CLI-generated notes (e.g. "2356x3333 | palette:...") into `specs.cli_info` on load
- Notes panel now only shows human-written notes

### Project Management
- Edit > Move to Another Project — pick existing .doxyproj.json, transfer selected assets
- Edit > Move to New Project — create new .doxyproj.json from selection with Save dialog
- F5 reloads project from disk (picks up external edits from Claude CLI)
- Shift+F5 for thumbnail recache

### Work Tray Overhaul
- Tray fully hides when closed (no more lingering 16px strip)
- Remembers width when toggling with Ctrl+T
- Column view modes: ☰ button cycles list → 2-col grid → 3-col grid (icon-only, clean layout)
- ✕ close button in header
- Quick Tag submenu in tray right-click context menu
- Tray thumbnails preserved on project reload

### Context Menu Improvements
- Tags submenu shows union of ALL selected assets' tags (not just clicked asset)
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
- Ctrl+Click tag bar → search by tag (was Alt+Click)
- "Has Notes" filter checkbox on search bar
- "Select all with tag" in tag panel right-click

### Code Quality (simplify round)
- NAME_ROLE constant replaces magic UserRole+1
- Dead _collapsed state and _toggle_collapse removed from tray
- _remove_assets_by_ids helper deduplicates move methods
- blockSignals during selection restore (avoids N redundant emissions)
- hasattr guards removed (proper __init__ instead)
- import re moved to module level

### Checklist: 22 items completed, 13 remaining (all medium-to-large features)

## v1.3.0 — 2026-04-05

### Tag System Improvements
- Both tag locations (top bar + side panel) now refresh on every tag-modifying event
- Custom tags sorted alphabetically in side panel
- Collapsible tag sections — click section header (▼/▶) to collapse/expand
- First tag section labeled "Default"
- Tags preserve user's exact casing and spaces (no more forced lowercase/underscores)
- "Select all with tag" in tag panel right-click menu
- Quick Tag multi-column submenu in browser right-click (✓ marks, splits at 10)
- Tray Quick Tag — right-click tray items to tag them directly
- Auto-tag toggle in Tools menu (guards filename + visual auto-tagging)

### New Shortcuts & Controls
- Escape — deselect all
- Alt+A — add tag to selected assets
- Ctrl+H — temporary hide selected (Ctrl+H again with nothing selected restores all)
- Ctrl+F — focus search box
- Ctrl+Click tag bar button — search by tag (was Alt+Click)
- F5 — reload project from disk (picks up external edits from Claude CLI)
- Shift+F5 — refresh thumbnails

### View Menu Additions
- Show Resolution toggle (per-thumbnail dimensions on/off)
- Show Tag Bar toggle (hide/show top tag buttons)
- Show Hidden Only filter (invert eye filter to see hidden items)
- Hover Preview Delay setting (200-1200ms, persisted)
- "Has Notes" filter checkbox on search bar

### UI & UX Fixes
- Thumbnail filename text now scales with Ctrl+=/- (was hardcoded)
- Menu font hover no longer mismatches in some themes
- Notes area splitter size persists across sessions
- Canvas tools (Select/Text/Line/Box/Marker/Color) hidden when not on Canvas tab
- Tray collapse button closes the entire tray (not just content)
- Hover preview hides before re-triggering delay when moving between thumbnails
- Middle-click drag properly updates preview without interfering with hover timer
- Clear All Tags now refreshes the browser grid
- Copy Filename added to browser right-click menu
- Filter button tooltips (Starred/Untagged/Tagged)

### Checklist Progress
- 17 items completed from TODO.md (7 high, 6 medium, 4 low priority)
- Added future items: rebuild tag bar from JSON, move assets between projects, drag-drop tag groups

## v1.2.0 — 2026-04-05

### Claude CLI Integration
- 8 new CLI commands: search, starred, ignored, notes, add-tag, remove-tag, set-star, export-json
- Auto-reload: DoxyEdit watches the project JSON and reloads when Claude CLI modifies it
- Full bidirectional sync — Claude edits JSON, DoxyEdit updates live

### Simplify Round 5
- Removed duplicate auto_suggest_tags (dead code)
- LRU eviction for delegate scaled pixmap cache (500 max)
- get_asset uses dirty flag invalidation
- Tag color dots no longer reset on image click (fitness overwrite removed)

### Fixes
- Star clicking works via delegate hit detection
- Auto-hide images when tagged with eye-hidden tag
- Cache All hides progress bar when nothing to cache
- Ctrl+V handles multiple paths/files
- Tag panel dots show tag color permanently

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

## v1.0.0 — 2026-04-05

### v1.0 Release
- Work Tray — collapsible right panel with ◀/▶ handle, persists across all tabs
- Tray context menu: Preview, Copy Path/Filename, Open in Explorer, Move to Top/Bottom
- Progress bar for cache-all and long tasks
- Middle-click instant preview (works even with hover disabled)
- Ctrl+click multi-select tag rows for batch Hide/Show/Delete
- Ctrl+T toggles tray, Ctrl+L toggles tag panel
- Tray button in left toolbar
- Resizable notes area (vertical splitter)
- Tokenized design system (font, padding, radius scale together)
- Horizontal scrollbars themed
- 3px rounded corners on thumbnails
- Smooth pixel scrolling, zoom keeps focus on selected item
- Hover preview customizable size (125-300%)
- Thumbnail quality setting (128-1024px)
- Alt+click tag toggles search on/off
- Theme: Dark renamed to Grey
- 7 themes fully applied to all widgets including tray, splitters, progress bar
- Project backup (.bak) created on open
- Sort mode, eye-hidden tags, tray items all persist in project file

## v0.9.0 — 2026-04-05

### QListView Migration (Major Performance Upgrade)
- Replaced QGridLayout with 200+ widget instances with a single QListView
- Custom ThumbnailModel (QAbstractListModel) + ThumbnailDelegate (QStyledItemDelegate)
- **Smooth virtual scrolling** — no more paging, all images accessible by scrolling
- **Instant zoom** — Ctrl+scroll changes grid size without rebuilding
- **Zero widget overhead** — delegate paints directly, no widget creation/destruction
- Selection built-in: Ctrl+click, Shift+click, Ctrl+A all work natively
- ~230 lines removed (1103 → 872 lines)
- Scaled pixmap cache with proper Qt cacheKey

### Eye Toggle (Photoshop-style Layer Visibility)
- Each tag in the left panel has an 👁 eye button
- Click to hide all images with that tag from the grid
- Click again to show them
- Multiple eyes can be toggled independently
- Works like Photoshop layer visibility

### Fixes
- Repeating thumbnail images fixed (cache key collision)
- Removed paging system (no longer needed with virtual scrolling)
- Removed Thumbnails Per Page menu (replaced by smooth scroll)

## v0.6.1 — 2026-04-05

### Preview Annotations
- View Notes button (V key) toggles saved annotations visible/hidden
- Annotations load from asset.notes on preview open
- Large bold text with dark background for readability
- Font size matches UI setting

### Per-Project Persistence
- Custom tag shortcuts saved to .doxyproj.json
- Hidden tags saved to .doxyproj.json and restored on load
- Main window position/size restored across sessions

### Fixes
- Ctrl+S / Ctrl+O now work (removed duplicate shortcut conflict)
- Right-click Unstar sets to 0 (Cycle Star Color is separate option)
- Thumb size clamped on load (prevents zoom corruption)
- Note font matches UI font size setting

## v0.6.0 — 2026-04-05

### Performance
- Grid rebuild wrapped in setUpdatesEnabled (eliminates per-widget repaint flicker)
- Immediate widget cleanup with setParent(None) during page rebuild
- Tag changes no longer trigger full grid rebuild (instant tagging)
- "Cache All" checkbox pre-generates all thumbnails in background
- F5 force-recache for externally edited images
- PERFORMANCE.md documents QListView migration roadmap

### Selection & Navigation
- Ctrl+A selects all thumbnails on current page
- Left/Right arrow keys page through thumbnails

### Folder Import
- Asks "Import recursively?" when folder has subfolders
- Nuitka build script clears cache for fresh builds, includes psd_tools + numpy

### State Persistence
- Main window position and size saved/restored across sessions
- All settings persist: theme, font, zoom, page size, window geometry

### Fixes
- Thumbnail widget height increased to clear dimension/name overlap
- Regenerated clean single-size 256x256 ICO (was corrupted multi-size)
- Tag add shows status bar confirmation

## v0.5.0 — 2026-04-04

Major release consolidating all v0.3.x work.

### SAI/SAI2 Shell Thumbnails
- SAI and SAI2 files show real thumbnails via Windows Shell API (SaiThumbs)
- Unsupported formats show styled placeholder with extension label
- Shell thumbnail integration for CLIP, KRA, XCF when extensions installed

### Disk Thumbnail Cache
- Thumbnails cached as PNGs in `~/.doxyedit/thumbcache/`
- Keyed by file path + modification time — changed files auto-regenerate
- Reopening large projects loads near-instantly

### Preview Annotations
- Press N or "Add Note" to draw annotation boxes on images
- Type note text, saved to asset's notes field
- Delete key removes selected annotations

### Tag Panel — 4 Sections
- Content/Workflow (Page, Character, Sketch, etc.)
- Platform/Size targets (Hero, Banner, Cover, etc.)
- Custom/Project tags (user-added, project-specific)
- Visual/Mood/Dimension (warm, cool, dark, portrait, etc.)
- Tags insert into their correct section, no mixing

### Tag Management
- Right-click tag → Pin to top of own section (gold border)
- Right-click tag → Set Shortcut Key (any single key)
- Right-click tag → Rename across all assets
- Right-click tag → Delete from project
- Custom tags appear in both tag bar and side panel
- Tag bar excludes platform/size tags (side panel only)
- All discovered tags show colored dots on thumbnails

### Navigation & Settings
- Left/Right arrow keys for page navigation
- View > Thumbnails Per Page: 50/100/150/200/300/500
- Recursive checkbox for folder imports
- Ctrl+V accepts plain text file/folder paths
- Search supports glob patterns (*.png, hero_*)
- Alt+click tag bar button → search by that tag

### UI Polish
- Unicode stars ★/☆ cycling 5 Vinik colors
- File extension shown in thumbnail labels
- Resolution text properly spaced below thumbnails
- Green flash on status bar when saving
- Wider note and rename dialogs
- App icon (Vinik-themed D) in titlebar
- Windows title bar matches theme color
- All dialogs themed (New Tag, Rename, Reset, etc.)
- Tag panel scroll area transparent for theme

### Theme Coverage
- Object-name selectors for reliable theming across all widgets
- All hardcoded hex colors replaced with rgba
- Grid area, scroll areas, dialogs all respect active theme
- 7 themes: Vinik 24, Warm Charcoal, Soot, Bone, Milk Glass, Forest, Dark

### Code Quality (4 simplify rounds)
- Extracted imaging.py for shared PIL/Qt conversion
- Public APIs: rebuild_tag_bar, import_folder, import_files, etc.
- Single-pass tag discovery, dedup separator helpers
- Robust get_tags with error handling
- Disk cache with MD5 keys and index
- .gitignore for dist/pycache

### v0.3.1 — Tag Panel Sections
- Left panel now has 4 clear sections with proper separators:
  1. Content/Workflow (Page, Character, Sketch, etc.)
  2. Platform/Size targets (Hero, Banner, Cover, etc.)
  3. Custom/Project tags (user-added, project-specific)
  4. Visual/Mood/Dimension (warm, cool, dark, portrait, etc.)
- Tags insert into their correct section, no more mixing

### Pin Tags
- Right-click tag → "Pin to top" moves it to the top of its own section
- Gold left border indicates pinned tags
- Right-click again to unpin

### Custom Keyboard Shortcuts
- Right-click tag → "Set Shortcut Key" assigns any single key
- Custom shortcuts register live and show as [K] in the tag label
- Works alongside built-in 1-9 shortcuts

### Navigation & Settings
- Left/Right arrow keys page through thumbnails
- View > Thumbnails Per Page: choose 50/100/150/200/300/500 (persists)

### Fixes
- Tag dots now show for all discovered tags (warm, portrait, etc.)
- Custom tags appear in both tag bar and side panel
- Wider note and rename dialogs (500px/400px)

## v0.3.0 — 2026-04-04

### SAI/SAI2 Shell Thumbnails
- SAI and SAI2 files now show real thumbnails via Windows Shell API (requires SaiThumbs installed)
- Unsupported formats show styled placeholder with extension and filename
- Shell thumbnail integration works for CLIP, KRA, XCF if shell extensions are installed

### Disk Thumbnail Cache
- Thumbnails cached as PNGs in `~/.doxyedit/thumbcache/`
- Keyed by file path + modification time — changed files auto-regenerate
- Second launch of a 600-image project loads near-instantly

### Preview Annotations
- Press N or click "Add Note" in preview to draw annotation boxes on images
- Type note text after drawing, saved to asset's notes field
- Delete key removes selected annotations
- Annotations persist with the project

### Tag System Improvements
- Custom tags now appear in both the tag bar AND the side panel immediately
- Tag bar excludes platform/size tags (Hero, Banner, etc.) — they're side panel only
- All discovered tags (auto visual properties, custom) show in the tag bar
- Right-click tag to rename it across all assets
- Quick Tag context menu now shows all tags in sections with separators
- Notes field changes now mark project dirty (saves properly)

### UI Polish
- Star uses unicode ★/☆ characters at 18px — visible on all themes
- Resolution text moved down 8px to clear thumbnail overlap
- Green flash on status bar when saving (visual feedback)
- Recursive checkbox for folder imports (scans subfolders)
- Ctrl+V accepts plain text file/folder paths from clipboard
- File extension shown in thumbnail labels (e.g. "art.psd" not "art")
- Search supports glob patterns (*.png, hero_*)
- Dialog boxes (New Tag, etc.) themed properly
- Tag panel scroll area transparent (theme shows through)
- App icon (Vinik-themed) in title bar and taskbar
- Full DOCS.md documentation

### Theme Coverage
- Object-name-based selectors for reliable theming
- Grid area, scroll areas, dialogs all pick up active theme
- Removed all remaining hardcoded hex colors (rgba throughout)

### Code Quality
- Extracted _rebuild_tag_bar for consistent tag bar updates
- Robust get_tags handles corrupt custom_tags gracefully
- setParent(None) for immediate widget cleanup in FlowLayout

## v0.2.0 — 2026-04-04

### PSD & Format Support
- PSD/PSB files now load with full thumbnail and preview support via psd-tools
- Uses embedded PSD thumbnail for fast grid loading, falls back to full composite when needed
- Added support for PSB, TGA, DDS, EXR, HDR, ICO file extensions
- SAI, CLIP, KRA, XCF files accepted (show placeholder if PIL can't read them)

### Theme System
- 7 themes: Vinik 24 (default), Warm Charcoal, Soot, Bone, Milk Glass, Forest, Dark
- Windows title bar color matches the active theme
- Theme-neutral rgba colors throughout — light themes (Bone, Milk Glass) now work properly
- All widgets inherit from theme stylesheet (removed hardcoded dark colors)
- Theme persists across sessions

### Tag System Overhaul
- Tags split into two sections: Content/Workflow (top) and Platform/Size targets (bottom) with separator
- Campaign tags corrected to real Kickstarter specs (Hero 1024x576, Banner 1600x400, etc.)
- Added Tier Card, Stretch Goal, Interior tags
- Custom tags: click "+" button to add project-specific tags with auto Vinik color assignment
- Delete tags: right-click any tag row to delete it from all assets
- Hide tags: right-click to hide, "Show All" button to restore
- Reset All Tags: File menu option to nuke all tags for a fresh start (with confirmation)
- Tags checkbox shows error message when trying to add a duplicate
- Auto visual property tagging on import: warm/cool, dark/bright, detailed/flat, portrait/landscape/square/panoramic/tall

### Star System
- Star button now cycles through 5 Vinik colors (gold, blue, green, rose, red) then off
- Backwards compatible with old bool values in project files

### Selection & Navigation
- Shift+click for range select (standard Windows behavior)
- Ctrl+click for multi-select toggle
- Alt+click sends image to Censor tab
- Delete key on Assets tab soft-deletes (tags as "ignore" and hides)
- Assets tagged "ignore" auto-hide from grid, "Show Ignored" toggle button to reveal
- Search toggles between filename and tag search via checkbox

### Performance
- Thumbnails generated at 512px for sharp display at any zoom level
- Background thread thumbnail loading with paging (100 per page)
- Lazy PSD composite — only when embedded thumbnail is too small
- Single-pass progress counter instead of 4 iterations
- Scroll position preserved when tags change (no more jumping to top)
- Debounced resize rebuilds

### UI Polish
- Tag panel moved to left side
- Left toolbar reorganized: tab nav, file ops, asset import, canvas tools
- Tag bar uses FlowLayout — wraps to multiple rows instead of forcing window width
- Tag dots on thumbnails doubled to 12px with subtle border shadow
- Font size controls: Ctrl+= / Ctrl+- / Ctrl+0 (8px to 24px, persists)
- Tag buttons scale with font size
- Preview dialog remembers window size, position, and zoom level
- Hover preview toggleable via checkbox, 500px preview size
- Right-click context menu: Preview, Send to Canvas, Send to Censor, Open in Explorer, Copy Path, Quick Tag submenu
- Recent Projects and Recent Folders submenus in File menu
- Last project auto-loads on startup, last folder remembered for dialogs
- Ctrl+scroll zooms thumbnail grid (80px to 320px, persists)
- ASCII art header in bat launcher

### Code Quality (3 simplify rounds)
- Extracted imaging.py — shared PIL/Qt conversion, PSD loading
- Asset.stem/name properties, Asset.cycle_star(), toggle_tags() helper
- Public APIs on browser (import_folder, import_files, refresh, shutdown, open_folder_dialog, add_images_dialog)
- Theme mutation bug fixed (dataclass copy instead of mutating global)
- Deque for thumb worker queue (was list with O(n) pop)
- Selected IDs as set for O(1) lookups
- Project.get_asset() with lazy dict index
- .gitignore added (dist/, __pycache__/, *.pyc, *.exe)

### Build
- Nuitka build.bat tested and working
- psd-tools added to requirements.txt

## v0.1.0 — 2026-04-04

Initial release. PySide6 thumbnail browser with paging, lazy loading, multi-select, tagging, search/sort/filter. Non-destructive censor editor. Canvas annotation. Platform assignment dashboard. Auto-save, drag-drop, keyboard shortcuts. CLI pipeline for Claude integration.
