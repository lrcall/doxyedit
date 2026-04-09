# UX Polish Pass — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 13 bugs and UX issues from user testing — folder view, shortcuts, theming, layout, menus.

**Architecture:** Grouped into 4 phases by dependency. Phase 1 fixes blocking bugs. Phase 2 fixes layout/structure. Phase 3 fixes theming. Phase 4 does UX improvements.

**Tech Stack:** PySide6, Python. All changes use theme tokens from `themes.py`.

---

## Phase 1: Blocking Bugs (do first)

### Task 1: Fix Ctrl+D shortcut conflict
**Files:** `doxyedit/window.py`
- Ctrl+D is registered TWICE: line 987 "Select None" AND line 1064 "Docked Preview"
- [ ] Change "Select None" shortcut from `Ctrl+D` to `Ctrl+Shift+D` at line 987
- [ ] Verify Ctrl+D now toggles docked preview
- [ ] Commit

### Task 2: Fix folder view section height + width
**Files:** `doxyedit/browser.py`
- `setFixedHeight()` alone doesn't constrain a wrapping QListView — items overflow right
- FolderListView has no sizePolicy set (defaults to Expanding)
- [ ] In FolderListView.__init__ (after line 486), add: `self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)`
- [ ] In FolderSection.update_view_height, change `self._view.setFixedHeight(view_h)` to `self._view.setFixedSize(available_width, view_h)` — constrains BOTH dimensions
- [ ] In _finalize_folder_layout, add a THIRD deferred call at 500ms for slow-rendering projects
- [ ] Compile + commit

### Task 3: Remove tray width restriction
**Files:** `doxyedit/tray.py`
- Lines 79-80: `setMinimumWidth(150)` + `setMaximumWidth(400)`
- [ ] Remove `setMaximumWidth(400)` (line 80) — keep min at 150
- [ ] Compile + commit

---

## Phase 2: Layout Changes

### Task 4: Move InfoPanel into left sidebar
**Files:** `doxyedit/window.py`, `doxyedit/tagpanel.py`
- InfoPanel content should go below tags in the left sidebar's `_tag_notes_split`
- [ ] In window.py: remove `_info_panel` from `_browse_split` (currently widget index 4)
- [ ] In window.py: add `_info_panel` to `tag_panel._tag_notes_split` as a third widget (between tag scroll and notes edit), OR replace the notes_edit area with InfoPanel (which already has notes editing)
- [ ] Update splitter sizes to [300, 200, 60] (tags, info, notes)
- [ ] Remove Ctrl+I toggle (panel is always visible in sidebar now)
- [ ] Update `_browse_split` stretch factors and default sizes (back to 4 widgets: file_browser, tag_panel, browser, preview_pane)
- [ ] Compile + commit

### Task 5: Merge health scan into project details column (Overview tab)
**Files:** `doxyedit/window.py`
- Currently `_overview_split` has 3 widgets: [stats, health, project_info] at [400, 400, 350]
- [ ] Remove health_panel from overview split
- [ ] Create vertical QSplitter: project_info (top) + health_panel (bottom)
- [ ] Add that vertical split as 2nd widget in `_overview_split`: [stats, info+health]
- [ ] Compile + commit

### Task 6: Toolbar buttons for File Browser + Info Panel
**Files:** `doxyedit/browser.py`
- Tags and Tray are QPushButtons at lines 749-759
- [ ] After the Tray button, add `self._files_btn = QPushButton("Files")` with same style, checkable, connected to a signal
- [ ] Add `files_toggled = Signal(bool)` to AssetBrowser
- [ ] In window.py: connect `browser.files_toggled` to `_toggle_file_browser`
- [ ] If InfoPanel moved to sidebar (Task 4), no separate button needed
- [ ] Compile + commit

---

## Phase 3: Theme Fixes

### Task 7: Splitter handle hover indicators
**Files:** `doxyedit/themes.py`
- No `:hover` state on QSplitter::handle
- [ ] Add to generate_stylesheet():
```
QSplitter::handle:hover {{ background: {theme.accent_dim}; }}
```
- [ ] Remove the duplicate `QSplitter::handle` at line 344 (width: 7px conflicts with 8px at line 299)
- [ ] Compile + commit

### Task 8: Menu hover font-size fix
**Files:** `doxyedit/themes.py`
- QMenu::item:hover may have mismatched font-size
- [ ] Verify all QMenu selectors in generate_stylesheet() include `font-size: {f}px` consistently on normal, hover, and selected states
- [ ] Check QMenu::item vs QMenu::item:selected vs QMenu::item:hover — all must have same `font-size: {f}px`
- [ ] Compile + commit

### Task 9: Tray thumbnail delayed display
**Files:** `doxyedit/tray.py`, `doxyedit/window.py`
- Tray items appear without thumbnails initially
- [ ] In window.py `_send_to_tray`: check if pixmap is fetched from `browser._thumb_cache.get(asset_id)` BEFORE adding to tray
- [ ] If pixmap not available, connect to `thumb_loaded` signal for deferred delivery
- [ ] Verify `update_pixmap` in tray.py uses `_id_to_row` for O(1) lookup (already done)
- [ ] Compile + commit

### Task 10: Notes tab markdown styling improvement
**Files:** `doxyedit/window.py`
- Inline CSS for markdown preview already exists (lines 823-842) with theme tokens
- [ ] Verify all hardcoded rgba values in the inline CSS use theme tokens
- [ ] Add list styling: `ul, ol { padding-left: 24px; }`, `li { margin-bottom: 4px; }`
- [ ] Add image styling: `img { max-width: 100%; border-radius: 4px; }`
- [ ] Increase body line-height: `line-height: 1.6;`
- [ ] Compile + commit

---

## Phase 4: UX Improvements

### Task 11: Tag panel / filter bar sync clarification
**Files:** `doxyedit/browser.py`
- Left panel checkboxes = tag ASSIGNMENT. Top bar = tag FILTER. Different operations.
- [ ] Add tooltip to tag bar buttons: "Click to filter grid by this tag"
- [ ] Add tooltip to tag panel checkboxes: "Check to apply this tag to selected assets"
- [ ] Consider: when a tag bar filter is active, highlight the corresponding tag in the left panel
- [ ] Compile + commit

### Task 12: Menu reorganization
**Files:** `doxyedit/window.py`
- 82+ items across 6 menus. Tools has 22 items.
- [ ] Split Tools into logical groups with separators:
  - Project: Reload, Remove Missing, Refresh Thumbs, Rebuild Tags, Clear Unused, Import Sources
  - Cache: Clear Cache, Set Location, Open Folder, Shared Cache, Fast Cache
  - Analysis: Find Duplicates, Find Similar, Tag Stats, Mass Tag Editor
  - Config: Configure Editors, Launch In, Edit Project Config, Folder Scan
- [ ] Move "Posting Checklist" from Tools to File or View (it's project content, not a tool)
- [ ] Move "Save Filter as Smart Folder" from Edit to View > Smart Folders submenu
- [ ] Compile + commit

### Task 13: Menu bar full-width stretch
**Files:** `doxyedit/window.py`
- Tab buttons currently crammed left
- [ ] Find `_TAB_NAMES` and the button creation loop
- [ ] Set `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)` on each tab button
- [ ] Add minimum width: `setMinimumWidth(60)`
- [ ] Compile + commit

---

## Execution Order
1→2→3 (blocking bugs, independent)
4→5→6 (layout, 4 before 6)
7→8→9→10 (theme, independent)
11→12→13 (UX, independent)

## Verification
- `python -m py_compile` on all modified files after each task
- Launch app: Ctrl+D toggles preview, folder view shows proper height/width, tray resizes freely
- Switch between Soot and Bone themes — all panels respond correctly
