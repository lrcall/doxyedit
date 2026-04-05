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
- [x] Alt+click tag bar button → search/unsearch
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
- [ ] Hover preview delay time setting (in View or Tools)
- [ ] Thumbnail filename text doesn't resize with Ctrl+=/- (hardcoded in delegate)
- [ ] Per-thumbnail resolution display toggle (on/off in View)
- [ ] Collapsible tag sections (click section header to collapse)
- [ ] Name first tag section "Default"
- [ ] Tray collapse button in header should close the whole tray (not just content)
- [ ] Auto-tagging toggle (on/off in Tools)
- [ ] Sort by folder with folder headers in thumbnail mode

### Medium Priority
- [ ] Kanban/Gantt posting schedule board
- [ ] Project color mode (window accent per project)
- [ ] Duplicate file finder/unifier
- [ ] Platform panel with asset thumbnails in slots
- [ ] Markdown-driven project config (UI from .md files)
- [ ] Shift+E → notes overlay popup (center screen)
- [ ] Crop region selector tool
- [ ] N key → notes overlay (same as bottom-left but center)
- [ ] Tray group tagging / quick tag for tray items
- [ ] Tray column modes (detail/2-col/3-col)
- [ ] "Show Hidden Only" filter in View
- [ ] Right-click Quick Tag multi-column layout (max 10 per column)
- [ ] Drag-select over tag rows (rubber band selection)

### Low Priority / Future
- [ ] Mass tag editing for AI training prompt files
- [ ] Nuitka build optimization (speed + final size)
- [ ] OpenGL viewport for grid rendering
- [ ] QListView model-view for tray (currently QListWidget)
- [ ] LRU eviction for in-memory pixmap cache
- [ ] Stat syscall caching for sort-by-date/size
- [ ] Tray button in menu bar (right side, same line as File/Edit)
- [ ] File menu font size still mismatches with hover in some themes
- [ ] Save notes area splitter size per project
- [ ] Canvas tools hidden when not on Canvas tab
