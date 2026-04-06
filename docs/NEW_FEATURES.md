# DoxyEdit — New Feature Log (Session April 2026)

All features below were implemented during this session. Each entry describes what was added, where it lives, and how to use it.

---

## Tag Bar

### ▼ Filters toggle button (hide/show tag bar)
**File:** `browser.py` — `_on_tag_bar_toggle()`, `toggle_tag_bar()`  
A **▼ Filters** / **▶ Filters** button at the end of the search row collapses the entire tag filter bar. Synced with View → Show Tag Bar.

### Tag bar as filter toggles
**File:** `browser.py` — `_toggle_bar_filter()`, `clear_bar_filters()`, `_rebuild_tag_buttons()`  
Clicking a tag bar button now **filters the grid** to show only assets with that tag (OR logic across multiple active filters). Active buttons appear checked. An **✕ Clear Filters** button appears inline when any filter is active. Escape also clears.

---

## Tag Panel

### Collapse All / Expand All button
**File:** `tagpanel.py` — `_toggle_all_sections()`  
"Collapse All" button in the batch row folds every tag section at once. If all are already collapsed, it becomes "Expand All". Individual sections can still be toggled by clicking their header.

### Section headers more visible
**File:** `tagpanel.py` — `_lbl_style`  
Section headers (▼ Default, ▼ Platform / Size targets, etc.) are now bolder with a subtle background, making them easier to find and click.

### Tag reordering — Move Up / Move Down
**File:** `tagpanel.py` — `_reorder_tag()`, `TagRow.reorder_requested`  
Right-click any custom tag row → **Move Up** or **Move Down**. Moves the row within its section. Order is persisted as `"order"` in `tag_definitions` in the project file and restored on reload.

### Mass tag → apply to assets
**File:** `tagpanel.py` — `_batch_apply_to_assets()`, `TagPanel.batch_apply_tags`  
Ctrl+click multiple tag rows to select them (highlighted in blue), then right-click → **Apply Selected Tags to Assets**. All selected tags are applied to every currently selected asset in the grid.

### Shortcut clear support
**File:** `tagpanel.py` — `_set_shortcut()` / `window.py` — `_on_shortcut_changed()`  
Right-click tag → Set Shortcut Key → **leave blank and press OK** to remove the shortcut. The `[D]`-style hint disappears from the label and the binding is removed from the project file.  
The dialog also now shows the current shortcut in the prompt so you know what's assigned.

---

## Browser

### Ctrl+F focuses search box
**File:** `browser.py` — `QShortcut(QKeySequence("Ctrl+F"))`  
Ctrl+F focuses the search input and selects all text.

---

## Window / Menus

### Shortcut clearing persists to project
**File:** `window.py` — `_on_shortcut_changed()`  
When a shortcut is cleared (empty key), the entry is removed from both `TAG_SHORTCUTS` (runtime) and `project.custom_shortcuts` (saved). Previously only setting worked, clearing was silently ignored.

### Tag reorder persisted
**File:** `window.py` — `_on_tag_reordered()`  
Each time a tag is reordered in the panel, the new `"order"` index is written to `project.tag_definitions[tag_id]["order"]` and `_dirty` is set so the next auto-save picks it up.

### Batch tag apply wired
**File:** `window.py` — `_on_batch_apply_tags()`  
Handles the `batch_apply_tags` signal from the tag panel — applies each tag ID in the list to all selected assets, then refreshes the grid and tag panel display.

---

## Previously this session (earlier in conversation)

| Feature | File | Notes |
|---|---|---|
| LRU eviction for pixmap cache | `thumbcache.py` | Max 600 entries, OrderedDict |
| Stat syscall batching | `browser.py` | One `os.stat()` per asset before sort |
| Tag bar filter toggles | `browser.py` | OR logic, Escape to clear |
| Project accent color | `window.py`, `models.py` | Per-project window accent override |
| Duplicate file finder | `window.py` | MD5 hash scan, grouped results dialog |
| F2 rename file on disk | `window.py` | QInputDialog + os.rename |
| Tray button in menu bar | `window.py` | Corner widget, top-right |
| Tag color picker | `tagpanel.py` | Right-click → Change Color → QColorDialog |
| Tag count badge | `tagpanel.py` | Count label on each row, `update_tag_counts()` |
| Ctrl+V scroll to pasted asset | `browser.py` | `scroll_to_asset(asset_id)` |
| Open Project File Location | `window.py` | Tools → Explorer /select |
| Export selected to folder | `browser.py` | Right-click → Export Selected |
| Platform status badges | `browser.py` | Green ✓ posted, blue R ready, amber … pending |
| Quick filter presets | `browser.py` | Assigned, Posted, Needs Censor buttons |
| Batch platform assignment | `browser.py` | Right-click → Assign to Platform X |
| Copy stem (no ext) | `tray.py` | "Copy Name (no ext)" in tray menu |
| Find similar | `browser.py` | Right-click → Find Similar |
| Smart export gap detection | `window.py` | Warns before export if slot missing |
| Posting checklist | `window.py` | Per-project markdown checklist dialog |
| Tag usage stats dialog | `window.py` | Tools → Tag Usage Stats |
| Mass tag editor + .txt export | `window.py` | Tools → Mass Tag Editor |
| Project notes panel | `window.py` | View toggle, bottom splitter |
| Sort: Starred First, Most Tagged | `browser.py` | Sort combo additions |
| Filter active indicator | `browser.py` | Count label shows ⬡ FILTERED |
| Hover preview fixed px | `browser.py` | Consistent size regardless of zoom |
| Hover delay setting | `window.py` | View → Hover Preview Delay |
| Escape clears tag bar filters | `browser.py` | Also hides ✕ button |
| "Show Hidden Only" filter | `browser.py` | View toggle |
