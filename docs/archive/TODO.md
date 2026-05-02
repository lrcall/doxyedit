# DoxyEdit — Implemented vs Pending Features

## Implemented (v1.1)

### Core
- [x] PySide6 thumbnail browser with QListView + delegate
- [x] PSD/PSB support via psd-tools (embedded thumb + composite)
- [x] SAI/SAI2 thumbnails via Windows Shell (SaiThumbs)
- [x] Disk thumbnail cache (~/.doxyedit/thumbcache/)
- [x] Cache priority: uncached first, upgrades second
- [x] Project file format (.doxyproj.json)
- [x] Auto-save every 30s + on close
- [x] Project backup (.bak) on open
- [x] CLI pipeline (summary/tags/untagged/status)

### Browsing
- [x] Smooth virtual scrolling (QListView, no paging)
- [x] Ctrl+scroll zoom (80-320px, instant, no rebuild)
- [x] Zoom keeps focus on selected item
- [x] Pixel-based smooth scrolling
- [x] Hover preview (toggleable, 400ms delay)
- [x] Middle-click instant preview (works even with hover off)
- [x] Hover preview size customizable (125-300%)
- [x] Double-click full zoomable preview
- [x] 3px rounded corners on thumbnails
- [x] File extension in thumbnail names
- [x] Ctrl+A select all, Ctrl+D deselect
- [x] Shift+click range select
- [x] Ctrl+click multi-select
- [x] Left/Right arrow scrolling
- [x] F5 refresh thumbnails
- [x] Cache All checkbox
- [x] Progress bar for caching

### Tagging
- [x] 4-section tag panel (Content, Platform, Custom, Visual)
- [x] Keyboard shortcuts 1-9, 0 for tags
- [x] Custom tag shortcuts (right-click → Set Shortcut Key)
- [x] Shortcuts saved per project
- [x] Custom tags via + button
- [x] Auto-tag on import by filename
- [x] Auto visual property tags (warm/cool/dark/bright/detailed/flat/portrait/landscape/square/panoramic/tall)
- [x] Tag dots on thumbnails (tag color)
- [x] Tag color dots in side panel
- [x] Bold tag labels
- [x] Eye toggle per tag (Photoshop-style visibility)
- [x] Eye state persists in project
- [x] Pin tag to top of section
- [x] Right-click: rename, hide, delete, set shortcut, pin
- [x] Ctrl+click multi-select tags for batch operations
- [x] Ctrl+click tag bar button → search/unsearch
- [x] Tag bar excludes platform tags
- [x] Quick Tag in context menu with sections
- [x] Add Tag dialog in context menu
- [x] Auto-hide when tagged with eye-hidden tag

### Import
- [x] + Folder, + Files buttons
- [x] Drag-drop files/folders
- [x] Recursive import with checkbox + prompt
- [x] Ctrl+V paste (images, file URLs, text paths, multi-line)
- [x] Unsupported file types silently discarded
- [x] Remember last folder
- [x] Recent Projects / Recent Folders menus

### Selection & Actions
- [x] Delete key → soft-delete (tag as ignore)
- [x] Show Ignored toggle
- [x] Star cycling (5 Vinik colors) via click
- [x] Unstar via right-click (sets to 0)
- [x] Right-click: Preview, Send to Tray, Send to Canvas, Send to Censor
- [x] Right-click: Open in Explorer, Copy Path
- [x] Remove from Project (with confirmation)
- [x] Edit menu: Select All/None, Invert, Star/Unstar, Clear Tags, Add Tag

### Work Tray
- [x] Collapsible right panel with ◀/▶ handle
- [x] Ctrl+T toggle, toolbar button
- [x] Send to Tray (single + multi-select)
- [x] Tray persists across all tabs
- [x] Tray items saved in project file
- [x] Thumbnails load as cache generates them
- [x] Collapse/expand button in header
- [x] Right-click: Preview, Copy Path, Copy Filename, Open in Explorer
- [x] Move to Top/Bottom
- [x] Clear All

### Preview
- [x] Full zoomable preview dialog
- [x] Remembers window size, position, zoom
- [x] Scroll to zoom, drag to pan
- [x] Note annotations (N key, draw box, type text)
- [x] View Notes toggle (V key)
- [x] Notes saved to asset.notes, persist in project
- [x] Fixed 18pt note text
- [x] Ctrl+0 fit to view

### Canvas / Censor
- [x] Canvas: text, lines, boxes, markers, color
- [x] Censor: black/blur/pixelate regions, non-destructive
- [x] Export censored copy
- [x] Markdown import/export

### Platforms
- [x] 7 platforms defined with slot specs
- [x] Status tracking (pending/ready/posted/skip)
- [x] Export all platforms with auto-resize

### Themes
- [x] 7 themes: Vinik 24, Warm Charcoal, Soot, Bone, Milk Glass, Forest, Grey
- [x] Windows title bar color matches theme
- [x] Tokenized design system (font, padding, radius)
- [x] Font size Ctrl+=/- (8-24px, persists)
- [x] All widgets themed including tray, splitters, progress bar, dialogs, scrollbars

### Menus
- [x] File: New, Open, Save, Save As, Recent, Import/Export MD, Export All, Paste, Reset Tags, Exit
- [x] Edit: Select All/None, Invert, Delete, Remove, Star/Unstar, Clear Tags, Add Tag
- [x] Tools: Refresh, Rebuild Tags, Clear Cache, Set Cache Location, Summary, Show Project File, Open Cache
- [x] View: Tag Panel, Work Tray, Font Size, Thumb Quality, Hover Size, Themes, Show Hidden Tags, Refresh
- [x] Help: Keyboard Shortcuts, About

### State Persistence
- [x] Window position/size
- [x] Theme, font size
- [x] Thumbnail zoom level
- [x] Splitter widths
- [x] Preview window position/size/zoom
- [x] Last project (auto-loads)
- [x] Sort mode per project
- [x] Eye-hidden tags per project
- [x] Hidden tags per project
- [x] Custom shortcuts per project
- [x] Tray items per project
- [x] Hover size, thumb quality

---

## Pending / Requested But Not Yet Implemented

### High Priority
- [x] Hover preview delay time setting (in View or Tools)
- [x] Thumbnail filename text doesn't resize with Ctrl+=/- (hardcoded in delegate)
- [x] Per-thumbnail resolution display toggle (on/off in View)
- [x] Collapsible tag sections (click section header to collapse)
- [x] Name first tag section "Default"
- [x] Tray collapse button in header should close the whole tray (not just content)
- [x] Auto-tagging toggle (on/off in Tools)
- [x] Sort by folder with folder headers in thumbnail mode
- [x] Preview window: single-instance (reuse instead of spawning second window)
- [x] Preview navigation via Space/Tab/Down (next) and Backspace/Up/Left (previous) — always works regardless of focus
- [x] Preview syncs thumbnail selection in browser (flat + folder views)
- [x] Enter key opens preview for selected thumbnail
- [x] Arrow key navigation in thumbnail view scrolls selection into view
- [x] Preview window themed (title bar via DWM, full stylesheet)
- [x] Preview minimize/maximize/restore buttons
- [x] SQLite cache index (O(1) key lookups, WAL mode, auto-migrates from index.json)
- [x] Cross-project thumbnail cache sharing via content_index.db
- [x] Fast Cache Mode (BMP storage, Tools menu)
- [x] Remove Missing Files (Health panel + Tools menu)
- [x] Folder view depth indent (3 spaces per depth level)
- [x] Scrollbar handles use accent color, brighten on hover
- [x] Paste Folder in File menu

### Medium Priority
- [x] Rebuild custom tag bar buttons from tags that exist in project JSON (not hardcoded)
- [x] Move selected assets to another .doxyproj.json (push + remove)
- [x] Kanban/Gantt posting schedule board
- [x] Project color mode (window accent per project)
- [x] Duplicate file finder/unifier
- [x] Platform panel with asset thumbnails in slots
- [x] Markdown-driven project config (YAML config.yaml)
- [x] Shift+E → notes overlay popup (center screen)
- [x] Crop region selector tool
- [x] N key → notes overlay (same as bottom-left but center, via Shift+E)
- [x] Tray group tagging / quick tag for tray items
- [x] Tray column modes (detail/2-col/3-col)
- [x] "Show Hidden Only" filter in View
- [x] Right-click Quick Tag multi-column layout (max 10 per column)
- [x] Drag-select over tag rows (rubber band selection)
- [x] Drag-drop tags between groups / create new tag groups
- [x] Actual file browser (browse filesystem, preview before import, drag into project)
- [x] F2 to rename selected file on disk
- [x] Multiple tray views (tabs or named trays)
- [x] Tag bar buttons function as hide/show toggles (click to filter view) not tag assignment
- [x] Hover preview size as fixed px (e.g. 400px) not percent of thumbnail — consistent size regardless of zoom

### New — From Codebase Review (April 2026)

#### Small
- [x] Status badge on thumbnails — pending/ready/posted indicator per platform (uses existing PlatformAssignment model)
- [x] Quick filter presets bar — Assigned + Posted filter buttons added to toolbar
- [x] Batch platform assignment — multi-select → right-click → "Assign to Platform X"
- [x] Copy stem (no extension) in tray/context menu — "Copy Filename Without Extension"
- [x] Reverse tag search — select asset → "Find similar" → shows all assets with same tag set

#### Medium
- [x] Platform status dashboard tab — per-platform slot grid with thumbnails + status badges
- [x] Smart export gap detection — warn when a required platform slot has no asset assigned
- [x] Posting checklist / campaign timeline — markdown-editable per-project checklist linked to asset readiness

#### Large
- [x] Perceptual hash variant detection — group visually similar files, mark canonical vs. variant
- [x] Platform-specific crop presets UI — visual overlay crop tool per platform slot dimensions

### Low Priority / Future
- [x] Sort by star rating ("Starred First" in sort combo)
- [x] Sort by tag count ("Most Tagged" in sort combo)
- [x] Tag color picker — right-click tag in side panel → Change Color
- [x] Platform assignment status quick-change — right-click thumbnail → Update Status submenu
- [x] Filter active indicator in count label — shows ⬡ FILTERED when grid is filtered
- [x] Open Project File Location — Tools menu → Explorer select
- [x] Scroll/jump to pasted asset after Ctrl+V paste
- [x] Ctrl+V paste → scrolls to newly added asset in grid
- [x] Copy all selected paths to clipboard (right-click when multi-selected)
- [x] Escape clears active tag bar filters
- [x] Tag count badge next to each tag in side panel
- [x] Tag usage stats dialog (Tools menu)
- [x] Needs Censor filter button (assets assigned to censor platforms without censor regions)
- [x] Export selected to folder (right-click when multi-selected)
- [x] Project notes panel (View menu toggle, collapsible at bottom of Assets tab)
- [x] Mass tag editing for AI training prompt files — bulk edit tags as CSV, export .txt sidecar files
- [x] Nuitka build optimization (speed + final size)
- [x] OpenGL viewport for grid rendering — assessed: not needed, QListView handles 70k items
- [x] QListView model-view for tray — optimized with O(1) index mapping instead of full migration
- [x] LRU eviction for in-memory pixmap cache
- [x] Stat syscall caching for sort-by-date/size
- [x] Tray button in menu bar (right side, same line as File/Edit)
- [x] File menu font size still mismatches with hover in some themes
- [x] Save notes area splitter size per project
- [x] Canvas tools hidden when not on Canvas tab
