# File Browser Sidebar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the bare-bones FileBrowserPanel into a fully-featured Eagle-style folder navigation sidebar with asset count badges, themed styling, folder-to-grid sync, drag-to-import, recursive counts, and auto-navigation to project folders.

**Architecture:** The panel already exists at `doxyedit/filebrowser.py` (180 lines) with QTreeView + QFileSystemModel, pinned folders, and basic signal wiring. All window.py integration is done (Ctrl+B toggle, splitter slot, folder_selected/import_requested/filter_cleared signals). This plan enhances the existing panel — no new files needed. The browser's `set_folder_filter()` already handles grid filtering.

**Tech Stack:** PySide6 (QTreeView, QFileSystemModel, QStyledItemDelegate), Python pathlib

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `doxyedit/filebrowser.py` | Modify | All panel enhancements: custom delegate, recursive counts, drag support, auto-expand, search filter |
| `doxyedit/window.py` | Modify | Grid-to-tree sync signal, theme application, subfolder filter support |
| `doxyedit/browser.py` | Modify (minor) | Emit signal on selection change with folder path |
| `doxyedit/themes.py` | No change | Already has all tokens needed |

---

### Task 1: Custom Delegate — Asset Count Badges on Folder Rows

The tree currently shows plain folder names. Add a custom `QStyledItemDelegate` that paints an asset count badge right-aligned on each row for folders that contain project assets.

**Files:**
- Modify: `doxyedit/filebrowser.py`

- [ ] **Step 1: Add FolderDelegate class**

Add this class above `FileBrowserPanel` in `filebrowser.py`:

```python
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QPainter, QColor, QPen

class FolderDelegate(QStyledItemDelegate):
    """Custom delegate that paints asset count badges on folder rows."""

    def __init__(self, panel: 'FileBrowserPanel', parent=None):
        super().__init__(parent)
        self._panel = panel

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        # Draw the default folder name + icon
        super().paint(painter, option, index)

        model = index.model()
        path = model.filePath(index).replace("\\", "/")
        count = self._panel.get_folder_count(path)
        if count <= 0:
            return

        painter.save()
        text = str(count)
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text) + 10
        th = fm.height() + 2

        # Badge rect — right-aligned, vertically centered
        badge_rect = QRect(
            option.rect.right() - tw - 6,
            option.rect.top() + (option.rect.height() - th) // 2,
            tw, th)

        # Draw pill background
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 30))
        painter.drawRoundedRect(badge_rect, th // 2, th // 2)

        # Draw count text
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 24))
```

- [ ] **Step 2: Add get_folder_count method and recursive counting**

Add these methods to `FileBrowserPanel`:

```python
def get_folder_count(self, folder_path: str) -> int:
    """Return asset count for a folder (recursive — includes subfolders)."""
    folder_path = folder_path.replace("\\", "/").rstrip("/")
    count = self._folder_counts.get(folder_path, 0)
    # Add counts from subfolders
    prefix = folder_path + "/"
    for path, c in self._folder_counts.items():
        if path.startswith(prefix):
            count += c
    return count
```

- [ ] **Step 3: Wire delegate in _build()**

In `_build()`, after creating `self._tree`, add:

```python
self._delegate = FolderDelegate(self)
self._tree.setItemDelegate(self._delegate)
```

- [ ] **Step 4: Verify compile**

Run: `python -m py_compile doxyedit/filebrowser.py`
Expected: no output (success)

- [ ] **Step 5: Commit**

```bash
git add doxyedit/filebrowser.py
git commit -m "feat(filebrowser): asset count badge delegate on folder rows"
```

---

### Task 2: Dim Empty Folders + Highlight Active Filter

Folders with zero project assets should appear dimmed. The currently-filtered folder should have an accent highlight.

**Files:**
- Modify: `doxyedit/filebrowser.py`

- [ ] **Step 1: Track active filter folder**

Add instance variable in `__init__`:

```python
self._active_folder: str | None = None  # currently filtering on this folder
```

Update `_on_folder_clicked` to track it:

```python
def _on_folder_clicked(self, index: QModelIndex):
    path = self._model.filePath(index)
    if path:
        self._active_folder = path.replace("\\", "/")
        self.folder_selected.emit(path)
        self._tree.viewport().update()  # repaint badges
```

Add a clear method for when filter is cleared:

```python
def clear_active(self):
    """Clear the active folder highlight (called when filter is cleared)."""
    self._active_folder = None
    self._tree.viewport().update()
```

- [ ] **Step 2: Enhance delegate paint for dimming + active highlight**

Update `FolderDelegate.paint()` — replace the existing method:

```python
def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
    model = index.model()
    path = model.filePath(index).replace("\\", "/")
    count = self._panel.get_folder_count(path)
    is_active = (path == self._panel._active_folder)

    # Active folder background highlight
    if is_active:
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 20))
        painter.drawRect(option.rect)
        painter.restore()

    # Dim folders with no assets
    if count == 0:
        painter.save()
        painter.setOpacity(0.4)
        super().paint(painter, option, index)
        painter.restore()
    else:
        super().paint(painter, option, index)

    # Badge
    if count <= 0:
        return

    painter.save()
    text = str(count)
    font = painter.font()
    font.setPointSize(8)
    painter.setFont(font)
    fm = painter.fontMetrics()
    tw = fm.horizontalAdvance(text) + 10
    th = fm.height() + 2

    badge_rect = QRect(
        option.rect.right() - tw - 6,
        option.rect.top() + (option.rect.height() - th) // 2,
        tw, th)

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    badge_bg = QColor(255, 255, 255, 40) if is_active else QColor(255, 255, 255, 25)
    painter.setBrush(badge_bg)
    painter.drawRoundedRect(badge_rect, th // 2, th // 2)

    painter.setPen(QColor(200, 200, 200))
    painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()
```

- [ ] **Step 3: Wire clear_active in window.py**

In `_clear_file_browser_filter()` in `window.py`, add:

```python
def _clear_file_browser_filter(self):
    """Clear any folder filter on the main grid."""
    self.browser.set_folder_filter(None)
    self._file_browser.clear_active()
```

- [ ] **Step 4: Verify compile**

Run: `python -m py_compile doxyedit/filebrowser.py && python -m py_compile doxyedit/window.py`

- [ ] **Step 5: Commit**

```bash
git add doxyedit/filebrowser.py doxyedit/window.py
git commit -m "feat(filebrowser): dim empty folders, highlight active filter folder"
```

---

### Task 3: Theme-Aware Styling

The panel currently has hardcoded colors. Make it respect the app's theme system.

**Files:**
- Modify: `doxyedit/filebrowser.py`
- Modify: `doxyedit/window.py`

- [ ] **Step 1: Add apply_theme method to FileBrowserPanel**

```python
def apply_theme(self, theme):
    """Apply theme colors to the file browser panel."""
    self._theme = theme
    f = theme.font_size
    self.setStyleSheet(f"""
        #file_browser_panel {{
            background: {theme.bg_main};
            color: {theme.text_primary};
            font-family: {theme.font_family};
            font-size: {f}px;
        }}
        QTreeView {{
            background: {theme.bg_deep};
            color: {theme.text_primary};
            border: none;
            font-size: {f}px;
        }}
        QTreeView::item {{
            padding: 2px 0;
        }}
        QTreeView::item:selected {{
            background: {theme.selection_bg};
        }}
        QTreeView::item:hover {{
            background: {theme.bg_hover};
        }}
        QPushButton {{
            background: {theme.bg_raised};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            padding: 2px 8px;
            font-size: {f - 1}px;
        }}
        QPushButton:hover {{
            background: {theme.bg_hover};
        }}
        QLabel {{
            color: {theme.text_primary};
        }}
    """)
    self._tree.viewport().update()
```

- [ ] **Step 2: Store theme ref for delegate use**

In `__init__`, add:

```python
self._theme = None
```

Update `FolderDelegate.paint()` badge colors to use theme when available:

```python
# In FolderDelegate.paint(), replace the hardcoded badge colors:
panel = self._panel
if panel._theme:
    badge_bg = QColor(panel._theme.accent) if is_active else QColor(255, 255, 255, 25)
    if is_active:
        badge_bg.setAlpha(80)
    text_color = QColor(panel._theme.text_primary)
else:
    badge_bg = QColor(255, 255, 255, 40) if is_active else QColor(255, 255, 255, 25)
    text_color = QColor(200, 200, 200)
```

- [ ] **Step 3: Call apply_theme from window.py**

Find the `_apply_theme` method in `window.py`. Add to the end of it:

```python
if hasattr(self, '_file_browser'):
    self._file_browser.apply_theme(theme)
```

- [ ] **Step 4: Verify compile**

Run: `python -m py_compile doxyedit/filebrowser.py && python -m py_compile doxyedit/window.py`

- [ ] **Step 5: Commit**

```bash
git add doxyedit/filebrowser.py doxyedit/window.py
git commit -m "feat(filebrowser): theme-aware styling with accent badges"
```

---

### Task 4: Auto-Expand to Project Folders on Load

When a project is loaded, automatically expand the tree to show folders that contain assets. Navigate to the first pinned folder or the most-populated project folder.

**Files:**
- Modify: `doxyedit/filebrowser.py`

- [ ] **Step 1: Add auto-expand logic to set_project**

Replace the existing `set_project` method:

```python
def set_project(self, project):
    """Update project reference for asset counts, then expand to project folders."""
    self._project = project
    self._update_folder_counts()
    self._auto_expand()
    self._tree.viewport().update()

def _auto_expand(self):
    """Expand tree to reveal folders that contain project assets."""
    if not self._folder_counts:
        return

    # Find the common root of all asset folders
    folders = list(self._folder_counts.keys())
    if not folders:
        return

    # Navigate to first pinned folder if it has assets, else most-populated folder
    target = None
    for pin in self._pinned:
        pin_norm = pin.replace("\\", "/")
        if self.get_folder_count(pin_norm) > 0:
            target = pin
            break

    if not target:
        # Pick the folder with the most assets
        target = max(self._folder_counts, key=self._folder_counts.get)

    if target:
        idx = self._model.index(target)
        if idx.isValid():
            self._tree.setCurrentIndex(idx)
            self._tree.scrollTo(idx)
            # Expand this folder and its parent chain
            parent = idx
            while parent.isValid():
                self._tree.expand(parent)
                parent = parent.parent()
```

- [ ] **Step 2: Verify compile**

Run: `python -m py_compile doxyedit/filebrowser.py`

- [ ] **Step 3: Commit**

```bash
git add doxyedit/filebrowser.py
git commit -m "feat(filebrowser): auto-expand to project folders on load"
```

---

### Task 5: Grid-to-Tree Sync (Select Asset → Highlight Its Folder)

When the user selects an asset in the thumbnail grid, highlight that asset's folder in the file browser tree. This gives spatial context.

**Files:**
- Modify: `doxyedit/filebrowser.py`
- Modify: `doxyedit/window.py`

- [ ] **Step 1: Add highlight_folder method to FileBrowserPanel**

```python
def highlight_folder(self, folder_path: str):
    """Highlight a folder in the tree without triggering a filter.
    Used for grid-to-tree sync — shows where the selected asset lives."""
    if not folder_path:
        return
    folder_path = folder_path.replace("\\", "/")
    idx = self._model.index(folder_path)
    if idx.isValid():
        # Block signals so we don't fire folder_selected (which would filter)
        self._tree.blockSignals(True)
        self._tree.setCurrentIndex(idx)
        self._tree.scrollTo(idx)
        self._tree.blockSignals(False)
```

- [ ] **Step 2: Wire in window.py — on asset selection, sync tree**

Find `_on_asset_selected` or `_on_selection_changed` in `window.py`. Add folder sync:

```python
# In _on_selection_changed (or wherever single-asset selection is handled):
if self._file_browser.isVisible():
    assets = self.browser.get_selected_assets()
    if len(assets) == 1:
        folder = assets[0].source_folder or str(Path(assets[0].source_path).parent)
        self._file_browser.highlight_folder(folder)
```

- [ ] **Step 3: Verify compile**

Run: `python -m py_compile doxyedit/filebrowser.py && python -m py_compile doxyedit/window.py`

- [ ] **Step 4: Commit**

```bash
git add doxyedit/filebrowser.py doxyedit/window.py
git commit -m "feat(filebrowser): grid-to-tree sync on asset selection"
```

---

### Task 6: Subfolder Filtering (Click Parent → Show All Children)

Currently clicking a folder filters to exact match. Enhance so clicking a parent folder shows assets in all its subfolders too.

**Files:**
- Modify: `doxyedit/filebrowser.py`
- Modify: `doxyedit/window.py`
- Modify: `doxyedit/browser.py`

- [ ] **Step 1: Emit folder + subfolders in folder_selected**

Update `_on_folder_clicked` in `FileBrowserPanel`:

```python
def _on_folder_clicked(self, index: QModelIndex):
    path = self._model.filePath(index)
    if not path:
        return
    path = path.replace("\\", "/")
    self._active_folder = path
    self.folder_selected.emit(path)
    self._tree.viewport().update()
```

- [ ] **Step 2: Update window.py handler to collect subfolders**

Replace `_on_file_browser_folder` in `window.py`:

```python
def _on_file_browser_folder(self, folder: str):
    """Filter main grid to show assets from this folder and all subfolders."""
    folder = folder.replace("\\", "/").rstrip("/")
    prefix = folder + "/"
    # Collect this folder + any subfolders that have assets
    matching = [folder]
    if self.project:
        for asset in self.project.assets:
            af = (asset.source_folder or str(Path(asset.source_path).parent)).replace("\\", "/")
            if af.startswith(prefix) and af not in matching:
                matching.append(af)
    self.browser.set_folder_filter(matching)
```

- [ ] **Step 3: Verify compile**

Run: `python -m py_compile doxyedit/window.py`

- [ ] **Step 4: Commit**

```bash
git add doxyedit/filebrowser.py doxyedit/window.py
git commit -m "feat(filebrowser): subfolder-inclusive filtering"
```

---

### Task 7: Drag Folder from Tree → Import into Project

Drag a folder from the tree and drop it on the grid to trigger an import.

**Files:**
- Modify: `doxyedit/filebrowser.py`

- [ ] **Step 1: Enable drag on tree**

In `_build()`, after creating `self._tree`, add:

```python
self._tree.setDragEnabled(True)
self._tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
```

- [ ] **Step 2: Override startDrag to use file URLs**

Add to `FileBrowserPanel.__init__`:

```python
self._tree.startDrag = self._start_drag
```

Add the method:

```python
def _start_drag(self, supported_actions):
    """Start a drag with the selected folder as a file URL."""
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDrag

    index = self._tree.currentIndex()
    if not index.isValid():
        return
    path = self._model.filePath(index)
    if not path:
        return

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    mime.setData("application/x-doxyedit-folder-import", path.encode("utf-8"))

    drag = QDrag(self._tree)
    drag.setMimeData(mime)
    drag.exec(Qt.DropAction.CopyAction)
```

- [ ] **Step 3: Verify compile**

Run: `python -m py_compile doxyedit/filebrowser.py`

- [ ] **Step 4: Commit**

```bash
git add doxyedit/filebrowser.py
git commit -m "feat(filebrowser): drag folder from tree to import"
```

---

### Task 8: Inline Search/Filter Box

Add a text input at the top of the panel that filters the visible tree to matching folder names.

**Files:**
- Modify: `doxyedit/filebrowser.py`

- [ ] **Step 1: Add search input to _build()**

After the header layout and before the pin bar, add:

```python
from PySide6.QtWidgets import QLineEdit

# Search filter
self._search = QLineEdit()
self._search.setPlaceholderText("Filter folders...")
self._search.setClearButtonEnabled(True)
self._search.setFixedHeight(24)
self._search.setContentsMargins(8, 0, 8, 0)
self._search.textChanged.connect(self._on_search_changed)
layout.addWidget(self._search)
```

- [ ] **Step 2: Add filter handler**

```python
def _on_search_changed(self, text: str):
    """Filter tree to folders matching the search text."""
    text = text.strip()
    if text:
        self._model.setNameFilters([f"*{text}*"])
        self._model.setNameFilterDisables(False)
    else:
        self._model.setNameFilters([])
```

- [ ] **Step 3: Verify compile**

Run: `python -m py_compile doxyedit/filebrowser.py`

- [ ] **Step 4: Commit**

```bash
git add doxyedit/filebrowser.py
git commit -m "feat(filebrowser): inline search box to filter folders"
```

---

### Task 9: Refresh Counts on Project Change

Asset counts should update when assets are imported, deleted, or moved. Wire the panel to refresh when the project data changes.

**Files:**
- Modify: `doxyedit/window.py`

- [ ] **Step 1: Add refresh call to project mutation points**

Find these methods in `window.py` and add `self._file_browser._update_folder_counts()` + `self._file_browser._tree.viewport().update()` at the end of each:

In the method that handles imports completing (after `browser.import_folder` or `_import_files`):
```python
if self._file_browser.isVisible():
    self._file_browser.set_project(self.project)
```

Create a helper to avoid repetition:

```python
def _refresh_file_browser(self):
    """Refresh file browser counts after project data changes."""
    if hasattr(self, '_file_browser') and self._file_browser.isVisible() and self.project:
        self._file_browser._update_folder_counts()
        self._file_browser._tree.viewport().update()
```

Call `self._refresh_file_browser()` at the end of:
- `_on_tags_modified()` — tag changes don't affect counts, skip this one
- `_remove_assets()` — asset removal changes counts
- `_import_files()` or wherever import completes
- `_on_project_loaded()` — already calls `set_project`, but verify

- [ ] **Step 2: Verify compile**

Run: `python -m py_compile doxyedit/window.py`

- [ ] **Step 3: Commit**

```bash
git add doxyedit/window.py
git commit -m "feat(filebrowser): refresh asset counts on project mutations"
```

---

## Summary

| Task | What | Lines (est.) |
|------|------|-------------|
| 1 | Badge delegate + recursive counts | ~70 |
| 2 | Dim empty folders + active highlight | ~40 |
| 3 | Theme-aware styling | ~40 |
| 4 | Auto-expand to project folders | ~35 |
| 5 | Grid-to-tree sync | ~20 |
| 6 | Subfolder-inclusive filtering | ~15 |
| 7 | Drag folder → import | ~25 |
| 8 | Inline search box | ~20 |
| 9 | Refresh counts on mutations | ~15 |

Total: ~280 lines of new code across 9 incremental commits. Each task is independently testable by opening the app.
