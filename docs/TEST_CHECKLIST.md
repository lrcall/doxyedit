# DoxyEdit — Testing Checklist

Run with `doxyedit.bat` or `python run.py`

## Assets Tab

### Import
- [ ] Click "+ Folder" — open a folder with images, thumbnails appear
- [ ] Click "+ Files" — pick individual images
- [ ] Drag a folder from Explorer onto the window
- [ ] Drag individual image files onto the window
- [ ] Ctrl+V paste an image from clipboard
- [ ] Auto-tag: import a file named "cover_final.png" — does it get "cover" and "final" tags?

### Thumbnails
- [ ] Thumbnails load in background (not frozen UI)
- [ ] Ctrl+scroll wheel zooms thumbnails in/out (80px to 320px)
- [ ] Zoomed-in thumbnails are sharp (not blurry upscale)
- [ ] Hover over a thumbnail — preview popup appears after 400ms
- [ ] Uncheck "Hover Preview" — popup stops appearing
- [ ] Double-click a thumbnail — full zoomable preview opens
- [ ] Preview dialog: scroll to zoom, drag to pan, Esc to close
- [ ] Paging works: with 100+ images, prev/next buttons appear, page counter is correct

### Selection
- [ ] Click a thumbnail — it highlights, tag panel shows its info
- [ ] Click another — first deselects, new one selects
- [ ] Ctrl+click — adds to selection (multi-select)
- [ ] Ctrl+click a selected item — deselects it
- [ ] Shift+click — selects range between last clicked and this one
- [ ] Status bar shows selection count

### Tagging
- [ ] Select an image, check a tag in the right panel — tag applies
- [ ] Tag dots appear on the thumbnail
- [ ] Keyboard shortcuts: select image, press 1 — "Hero" toggles
- [ ] Press 0 — "Ignore" toggles
- [ ] Quick-tag bar at top: click a tag button — applies to selected
- [ ] Multi-select 5 images, press 3 — all get "Cover" tag
- [ ] Fitness dots: green/yellow for images that fit, red for too-small
- [ ] "Mark Ignore" button in tag panel works
- [ ] "Clear All Tags" button works

### Filtering & Search
- [ ] Type in search box — grid filters by filename
- [ ] Click "Starred" — only starred images show
- [ ] Click "Untagged" — only untagged show
- [ ] Click "Tagged" — only tagged show
- [ ] Sort dropdown: Name A-Z, Z-A, Newest, Oldest, Largest, Smallest all work
- [ ] Filter counts update correctly

### Starring
- [ ] Click star button (.) on a thumbnail — turns gold (*)
- [ ] Click again — unstars

### Right-Click Menu
- [ ] Right-click a thumbnail — context menu appears
- [ ] "Preview" — opens preview dialog
- [ ] "Send to Canvas" — switches to Canvas tab with image loaded
- [ ] "Send to Censor" — switches to Censor tab with image loaded
- [ ] "Open in Explorer" — opens file location in Windows Explorer
- [ ] "Copy Path" — copies file path to clipboard
- [ ] "Star" / "Unstar" — toggles star
- [ ] "Quick Tag" submenu — tags toggle with checkmarks
- [ ] "Remove from Project" — removes from grid

### Tag Panel (right sidebar)
- [ ] Shows image name and dimensions when selected
- [ ] Shows "No tags yet" hint when unselected
- [ ] Ctrl+T hides the panel
- [ ] Ctrl+T again shows it
- [ ] View > Show/Hide Tag Panel works
- [ ] Notes field saves text per asset

## Canvas Tab
- [ ] Press T — click to place text, double-click to edit it
- [ ] Press L — draw a line
- [ ] Press B — draw a box
- [ ] Press G — click to place a tag marker
- [ ] Press V — back to select mode, can move items
- [ ] Scroll wheel zooms
- [ ] Middle-click + drag pans
- [ ] Delete key removes selected items
- [ ] Color button changes selected item's color

## Censor Tab
- [ ] Select an image in Assets, it loads here too
- [ ] Alt+click an image in Assets — jumps to Censor tab
- [ ] Click "Draw Censor Region" — draw a rectangle
- [ ] Style dropdown: black, blur, pixelate (each looks different)
- [ ] Censor rects are draggable
- [ ] "Delete Selected" removes a censor rect
- [ ] "Export Censored" — saves a copy with censoring applied
- [ ] Original file is NOT modified

## Platforms Tab
- [ ] All 7 platforms show with their slots and sizes
- [ ] Required slots marked with *
- [ ] Status dropdowns work (pending/ready/posted/skip)
- [ ] Empty slots show "-- empty --"

## File Operations
- [ ] Ctrl+S — save project (.doxyproj.json)
- [ ] Ctrl+O — open a saved project, all data restores
- [ ] Auto-save: wait 30s after changes, check status bar says "Auto-saved"
- [ ] Ctrl+N — new project clears everything
- [ ] Ctrl+E — export all platforms (creates folders with resized images)

## Themes
- [ ] View > Theme > each theme applies immediately
- [ ] Vinik 24 — dark purple/teal
- [ ] Warm Charcoal — warm dark
- [ ] Soot — cool purple dark
- [ ] Bone — light warm
- [ ] Milk Glass — light cool
- [ ] Forest — green dark
- [ ] Dark — classic IDE dark

## CLI (run in terminal)
- [ ] `python -m doxyedit summary project.doxyproj.json` — prints JSON status
- [ ] `python -m doxyedit tags project.doxyproj.json` — lists assets and tags
- [ ] `python -m doxyedit untagged project.doxyproj.json` — lists untagged assets
- [ ] `python -m doxyedit status project.doxyproj.json` — platform slot status

## Bugs / Notes
- [ ] _write issues here as you find them_
-
-
-
