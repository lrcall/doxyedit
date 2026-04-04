# DoxyEdit Changelog

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
