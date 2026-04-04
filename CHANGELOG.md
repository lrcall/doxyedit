# DoxyEdit Changelog

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
