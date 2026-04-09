# DoxyEdit v2.2 — Testing Checklist

Test with at least 2 themes (Soot dark + Bone light).

## New Panels

### File Browser (Ctrl+B)
- [ ] Files button in toolbar toggles file browser
- [ ] Ctrl+B toggles file browser
- [ ] Tree shows folder hierarchy
- [ ] Asset count badges on folders with project assets
- [ ] Empty folders dimmed
- [ ] Click folder → grid filters to that folder + subfolders
- [ ] "Clear Filter" button resets grid
- [ ] Pin a folder → appears in pin bar
- [ ] Unpin works
- [ ] Search box filters folder names
- [ ] Drag folder from tree → imports into project
- [ ] Right-click → Import, Pin, Open in Explorer, Copy Path
- [ ] Select asset in grid → tree highlights its folder

### Info Panel (left sidebar)
- [ ] Shows below tags in left sidebar (always visible)
- [ ] Select single asset → shows filename, path, format, size, dimensions, star rating
- [ ] Tags display as editable pills with × remove
- [ ] Click × on tag pill → tag removed, grid refreshes
- [ ] Click + → inline text input with autocomplete
- [ ] Type tag name → press Enter → tag added
- [ ] Notes section editable (QTextEdit)
- [ ] Edit notes → saved to asset
- [ ] Platform assignments show with status icons
- [ ] Color palette swatches visible (after thumbnails cached)
- [ ] Select multiple assets → shows common tags, counts
- [ ] Select nothing → shows "No selection"

### Kanban Board (Platforms tab)
- [ ] Visible on right side of Platforms tab
- [ ] Shows 4 columns: Pending, Ready, Posted, Skip
- [ ] Empty state shows help text explaining workflow
- [ ] Assign asset to platform (right-click → Assign to Platform)
- [ ] Card appears in Pending column
- [ ] Drag card from Pending to Ready → status updates
- [ ] Drag card to Posted → status updates
- [ ] Platforms panel refreshes when kanban card dropped
- [ ] Checklist visible on top of Platforms tab

## Preview

### Docked Preview (Ctrl+D)
- [ ] Ctrl+D toggles docked preview (NOT Ctrl+Shift+D which is deselect)
- [ ] Pop-out button (⬔) opens floating preview dialog
- [ ] Docked pane hides when popped out

### Crop Tool (C key in preview)
- [ ] C key toggles crop mode in floating preview
- [ ] Crop preset dropdown grouped by platform with headers
- [ ] Draw crop region → orange rect with dark mask
- [ ] After drawing → rect stays with 8 resize handles
- [ ] Drag handles to resize → crop updates
- [ ] Drag body to move → crop updates
- [ ] Load asset with existing crops → overlays appear
- [ ] Delete key removes selected crop
- [ ] Multiple crops per asset (different platform labels)

### Multi-Monitor
- [ ] Move preview to second monitor, close, reopen → appears on correct monitor

## Smart Folders
- [ ] Edit > Save Filter as Smart Folder → name dialog
- [ ] View > Smart Folders → shows saved presets
- [ ] Click preset → filter state restored
- [ ] Clear All Smart Folders works

## Find Similar (Perceptual Hash)
- [ ] Browse thumbnails first (hashes compute during caching)
- [ ] Tools > Analysis > Find Similar Images
- [ ] Groups shown with "keep" / "variant" markers
- [ ] "Tag as variant" → adds "variant" tag
- [ ] "Remove extras" → removes from project (files stay on disk)

## YAML Config
- [ ] Tools > Config > Edit Project Config → creates/opens config.yaml
- [ ] Add custom platform in YAML → reload project → platform appears

## Collections
- [ ] File > Collections > Save Collection
- [ ] File > Collections > Reload Collection
- [ ] Close app, delete one project file, reopen → warning about missing projects

## Folder View (By Folder sort)
- [ ] Sort dropdown → "By Folder"
- [ ] Sections show with depth indentation
- [ ] Sub-folders indented under parents
- [ ] Sections with many items fill viewport height (not narrow band)
- [ ] Thumbnails don't overflow right edge
- [ ] Collapse/expand folder sections works
- [ ] Click folder header → collapses
- [ ] Scroll between sections smooth

## Toolbar
- [ ] Files, Tags, Tray buttons visible in toolbar
- [ ] Files button toggles file browser
- [ ] Tags button toggles tag panel
- [ ] Tray button toggles work tray
- [ ] Recursive, Hover Preview, Cache All, Folder Scan checkboxes present
- [ ] All toolbar buttons clickable (no dead zones)
- [ ] Tab bar buttons stretch to full width
- [ ] No vertical offset on toolbar buttons

## Menus
- [ ] File menu: 6 top-level items + submenus (Recent, Import/Export, Collections, Settings)
- [ ] Edit menu: grouped with separators (selection, asset actions, move, tags)
- [ ] View menu: 8 top-level + submenus (Display, Font & Size, Hover Preview, Theme)
- [ ] Tools menu: 5 top-level + submenus (Cache, Tags, Import/Export, Project Info)
- [ ] Help > What's New (v2.2) → dialog with feature list
- [ ] No menu item has mismatched font on hover

## Theme
- [ ] Switch to Bone (light) → ALL panels update colors
- [ ] Switch to Soot (dark) → ALL panels update colors
- [ ] Kanban columns match theme background
- [ ] Kanban cards match theme raised surface
- [ ] Info Panel tags/notes match theme
- [ ] File Browser tree/badges match theme
- [ ] Splitter handles highlight on hover
- [ ] Thumbnail delegate text uses theme colors
- [ ] Notes tab markdown preview uses theme colors (headings, code blocks, links)

## Tray
- [ ] Tray resizes freely (no max width cap)
- [ ] Drag asset from grid to tray
- [ ] Tray thumbnails appear (may pop in if not cached)
- [ ] Named trays: + button creates new tray tab
- [ ] Rename/close tray tabs via right-click

## Overview Tab
- [ ] Stats on left
- [ ] Project Info + Health stacked vertically on right
- [ ] Health scan works from this panel

## Bugs Fixed (verify)
- [ ] Preview position remembered correctly across monitors
- [ ] Tray drag-drop works from normal view (click any item, drag)
- [ ] Collection reload warns about missing projects
- [ ] Folder filter doesn't show empty results (path normalization)
