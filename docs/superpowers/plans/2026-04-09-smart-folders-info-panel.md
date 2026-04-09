# Smart Folders + Right Info Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add saved filter presets ("Smart Folders") to the sidebar and an asset metadata Info Panel below the docked preview pane, bringing DoxyEdit closer to Eagle's UX.

**Architecture:** Smart Folders are serialized filter state objects stored in the project file's `filter_presets` list. The browser gets `get_filter_state()` / `set_filter_state()` methods for capture/restore. The Info Panel extends the existing `_browse_split` as a 5th widget (vertical sub-splitter with PreviewPane + InfoPanel on the right side). Both features follow existing panel integration patterns.

**Tech Stack:** PySide6, Python dataclasses, JSON project file serialization

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `doxyedit/browser.py` | Modify | `get_filter_state()` / `set_filter_state()` methods for smart folder capture/restore |
| `doxyedit/models.py` | Modify | Add `filter_presets` field to Project, include in save/load |
| `doxyedit/infopanel.py` | Create | New `InfoPanel(QWidget)` — asset metadata display |
| `doxyedit/window.py` | Modify | Smart folder UI (save/load menu), info panel integration, splitter wiring |

---

## Part A: Smart Folders

### Task 1: Browser Filter State Capture/Restore

Add methods to `AssetBrowser` that serialize and restore the full filter state as a dict.

**Files:**
- Modify: `doxyedit/browser.py`

- [ ] **Step 1: Add get_filter_state method**

Add this method to `AssetBrowser`:

```python
def get_filter_state(self) -> dict:
    """Capture the current filter state as a serializable dict."""
    return {
        "search_text": self.search_box.text(),
        "search_tags": self.search_tags_check.isChecked(),
        "starred": self.filter_starred.isChecked(),
        "untagged": self.filter_untagged.isChecked(),
        "tagged": self.filter_tagged.isChecked(),
        "assigned": self.filter_assigned.isChecked(),
        "posted": self.filter_posted.isChecked(),
        "needs_censor": self.filter_needs_censor.isChecked(),
        "show_ignored": self.filter_show_ignored.isChecked(),
        "has_notes": self.filter_has_notes.isChecked(),
        "format": self._format_filter,
        "tag_filters": sorted(self._bar_tag_filters),
        "folders": sorted(self._folder_filter) if self._folder_filter else None,
    }
```

- [ ] **Step 2: Add set_filter_state method**

```python
def set_filter_state(self, state: dict):
    """Restore a previously captured filter state."""
    self.search_box.setText(state.get("search_text", ""))
    self.search_tags_check.setChecked(state.get("search_tags", False))
    self.filter_starred.setChecked(state.get("starred", False))
    self.filter_untagged.setChecked(state.get("untagged", False))
    self.filter_tagged.setChecked(state.get("tagged", False))
    self.filter_assigned.setChecked(state.get("assigned", False))
    self.filter_posted.setChecked(state.get("posted", False))
    self.filter_needs_censor.setChecked(state.get("needs_censor", False))
    self.filter_show_ignored.setChecked(state.get("show_ignored", False))
    self.filter_has_notes.setChecked(state.get("has_notes", False))
    # Format filter
    fmt = state.get("format", "")
    self._format_filter = fmt
    if hasattr(self, '_format_combo'):
        idx = self._format_combo.findText(fmt.upper() if fmt else "All",
                                           Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            self._format_combo.setCurrentIndex(idx)
        else:
            self._format_combo.setCurrentIndex(0)
    # Tag bar filters
    self._bar_tag_filters = set(state.get("tag_filters", []))
    self._rebuild_tag_buttons()
    # Folder filter
    folders = state.get("folders")
    self._folder_filter = set(folders) if folders else None
    # Refresh
    self._refresh_grid()
```

- [ ] **Step 3: Verify compile**

Run: `python -m py_compile doxyedit/browser.py`

- [ ] **Step 4: Commit**

```bash
git add doxyedit/browser.py
git commit -m "feat(browser): get/set filter state for smart folder presets"
```

---

### Task 2: Project Model — filter_presets Field

Add `filter_presets` to the Project dataclass save/load cycle.

**Files:**
- Modify: `doxyedit/models.py`

- [ ] **Step 1: Add field to Project dataclass**

In the `Project` dataclass (line 329), the field `filter_presets` does NOT exist yet. Add it after `folder_presets`:

```python
filter_presets: list[dict] = field(default_factory=list)  # [{name, icon, state: {filter dict}}]
```

- [ ] **Step 2: Add to save()**

In `Project.save()`, in the `data = {` dict (line 406), add after `"folder_presets"`:

```python
            "filter_presets": self.filter_presets,
```

- [ ] **Step 3: Add to load()**

In `Project.load()`, in the `cls(` constructor call (line 438), add:

```python
            filter_presets=raw.get("filter_presets", []),
```

- [ ] **Step 4: Verify compile**

Run: `python -m py_compile doxyedit/models.py`

- [ ] **Step 5: Commit**

```bash
git add doxyedit/models.py
git commit -m "feat(models): filter_presets field for smart folders"
```

---

### Task 3: Smart Folder Save/Load UI in Window

Add menu items and a sidebar section for managing smart folder presets.

**Files:**
- Modify: `doxyedit/window.py`

- [ ] **Step 1: Add "Save Current Filter" action to Edit menu**

Find where the Edit menu is built (search for `edit_menu`). Add at the end of the edit menu:

```python
        edit_menu.addSeparator()
        edit_menu.addAction("Save Filter as Smart Folder...", self._save_smart_folder)
```

- [ ] **Step 2: Add smart folder submenu to View menu**

Find where the View menu is built. Add:

```python
        self._smart_folder_menu = view_menu.addMenu("Smart Folders")
        self._rebuild_smart_folder_menu()
```

- [ ] **Step 3: Implement _save_smart_folder**

```python
def _save_smart_folder(self):
    """Save the current browser filter state as a named smart folder."""
    from PySide6.QtWidgets import QInputDialog
    name, ok = QInputDialog.getText(self, "Smart Folder", "Name for this filter preset:")
    if not ok or not name.strip():
        return
    state = self.browser.get_filter_state()
    preset = {
        "name": name.strip(),
        "icon": "🔍",
        "state": state,
    }
    self.project.filter_presets.append(preset)
    self._dirty = True
    self._rebuild_smart_folder_menu()
    self.status.showMessage(f"Smart folder saved: {name.strip()}", 3000)
```

- [ ] **Step 4: Implement _rebuild_smart_folder_menu**

```python
def _rebuild_smart_folder_menu(self):
    """Rebuild the Smart Folders submenu from project presets."""
    menu = self._smart_folder_menu
    menu.clear()
    menu.addAction("Save Current Filter...", self._save_smart_folder)
    if not self.project or not self.project.filter_presets:
        return
    menu.addSeparator()
    for i, preset in enumerate(self.project.filter_presets):
        name = preset.get("name", f"Preset {i+1}")
        icon = preset.get("icon", "🔍")
        action = menu.addAction(f"{icon} {name}",
                                 lambda _, idx=i: self._load_smart_folder(idx))
        # Right-click to delete
    menu.addSeparator()
    menu.addAction("Clear All Smart Folders", self._clear_smart_folders)
```

- [ ] **Step 5: Implement _load_smart_folder and _clear_smart_folders**

```python
def _load_smart_folder(self, index: int):
    """Load a smart folder preset by index."""
    if not self.project or index >= len(self.project.filter_presets):
        return
    preset = self.project.filter_presets[index]
    state = preset.get("state", {})
    self.browser.set_filter_state(state)
    name = preset.get("name", "Untitled")
    self.status.showMessage(f"Smart folder loaded: {name}", 3000)

def _clear_smart_folders(self):
    """Remove all smart folder presets."""
    from PySide6.QtWidgets import QMessageBox
    if QMessageBox.question(self, "Clear Smart Folders",
                             "Remove all saved filter presets?") != QMessageBox.StandardButton.Yes:
        return
    self.project.filter_presets.clear()
    self._dirty = True
    self._rebuild_smart_folder_menu()
```

- [ ] **Step 6: Wire rebuild on project load**

Find where the project is loaded and UI is rebuilt (search for `_file_browser.set_project`). Near that block (around line 3005), add:

```python
        if hasattr(self, '_smart_folder_menu'):
            self._rebuild_smart_folder_menu()
```

- [ ] **Step 7: Verify compile**

Run: `python -m py_compile doxyedit/window.py`

- [ ] **Step 8: Commit**

```bash
git add doxyedit/window.py
git commit -m "feat(window): smart folder save/load UI with View menu"
```

---

## Part B: Right Info Panel

### Task 4: InfoPanel Widget

Create the asset metadata display panel.

**Files:**
- Create: `doxyedit/infopanel.py`

- [ ] **Step 1: Create infopanel.py**

```python
"""Info panel — asset metadata display for the right sidebar."""
import os
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor


class InfoPanel(QWidget):
    """Right sidebar showing metadata for the selected asset(s)."""

    tags_modified = Signal()  # emitted when user edits tags/notes inline

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("info_panel")
        self._assets = []
        self._theme = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        self._header = QLabel("No selection")
        self._header.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._header.setStyleSheet("padding: 8px;")
        self._header.setWordWrap(True)
        outer.addWidget(self._header)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(8, 4, 8, 8)
        self._layout.setSpacing(6)

        # Filename
        self._name_label = QLabel()
        self._name_label.setWordWrap(True)
        self._name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._layout.addWidget(self._name_label)

        # Separator
        self._layout.addWidget(self._separator())

        # Properties section
        self._props_label = QLabel()
        self._props_label.setWordWrap(True)
        self._props_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._layout.addWidget(self._props_label)

        # Separator
        self._layout.addWidget(self._separator())

        # Tags section
        self._tags_header = QLabel("Tags")
        self._tags_header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._layout.addWidget(self._tags_header)
        self._tags_label = QLabel()
        self._tags_label.setWordWrap(True)
        self._tags_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._layout.addWidget(self._tags_label)

        # Separator
        self._layout.addWidget(self._separator())

        # Assignments section
        self._assign_header = QLabel("Platforms")
        self._assign_header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._layout.addWidget(self._assign_header)
        self._assign_label = QLabel()
        self._assign_label.setWordWrap(True)
        self._layout.addWidget(self._assign_label)

        # Separator
        self._layout.addWidget(self._separator())

        # Notes section
        self._notes_header = QLabel("Notes")
        self._notes_header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._layout.addWidget(self._notes_header)
        self._notes_label = QLabel()
        self._notes_label.setWordWrap(True)
        self._notes_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._layout.addWidget(self._notes_label)

        self._layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.setMinimumWidth(200)
        self.setMaximumWidth(350)

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: rgba(255,255,255,0.1);")
        line.setFixedHeight(1)
        return line

    def set_assets(self, assets: list):
        """Update the panel to show info for the given asset(s)."""
        self._assets = assets

        if not assets:
            self._header.setText("No selection")
            self._name_label.setText("")
            self._props_label.setText("")
            self._tags_label.setText("")
            self._assign_label.setText("")
            self._notes_label.setText("")
            return

        if len(assets) == 1:
            self._show_single(assets[0])
        else:
            self._show_multi(assets)

    def _show_single(self, asset):
        """Display detailed info for a single asset."""
        p = Path(asset.source_path)
        self._header.setText(p.name)
        self._name_label.setText(f"<b>Path:</b> {p.parent}")

        # Properties
        props = []
        ext = p.suffix.upper().lstrip(".")
        props.append(f"<b>Format:</b> {ext}")
        # File size
        try:
            size = os.path.getsize(asset.source_path)
            if size < 1024:
                props.append(f"<b>Size:</b> {size} B")
            elif size < 1024 * 1024:
                props.append(f"<b>Size:</b> {size / 1024:.1f} KB")
            else:
                props.append(f"<b>Size:</b> {size / (1024*1024):.1f} MB")
        except OSError:
            props.append("<b>Size:</b> unknown")
        # Dimensions from specs
        w = asset.specs.get("w", "")
        h = asset.specs.get("h", "")
        if w and h:
            props.append(f"<b>Dimensions:</b> {w} × {h}")
        # Star
        if asset.starred:
            stars = "★" * asset.starred
            props.append(f"<b>Rating:</b> {stars}")
        self._props_label.setText("<br>".join(props))

        # Tags
        if asset.tags:
            tag_pills = " ".join(f'<span style="background:rgba(255,255,255,0.1);'
                                  f'padding:1px 6px;border-radius:3px;">{t}</span>'
                                  for t in asset.tags)
            self._tags_label.setText(tag_pills)
        else:
            self._tags_label.setText("<i>No tags</i>")

        # Assignments
        if asset.assignments:
            lines = []
            for a in asset.assignments:
                status_icon = {"posted": "✓", "ready": "●", "pending": "○", "skip": "—"}.get(
                    a.status, "?")
                lines.append(f"{status_icon} {a.platform} / {a.slot} — {a.status}")
            self._assign_label.setText("<br>".join(lines))
        else:
            self._assign_label.setText("<i>Not assigned</i>")

        # Notes
        if asset.notes:
            self._notes_label.setText(asset.notes)
        else:
            self._notes_label.setText("<i>No notes</i>")

    def _show_multi(self, assets):
        """Display summary info for multiple selected assets."""
        n = len(assets)
        self._header.setText(f"{n} assets selected")
        self._name_label.setText("")

        # Common tags
        tag_sets = [set(a.tags) for a in assets]
        common = tag_sets[0]
        for s in tag_sets[1:]:
            common &= s
        all_tags = set()
        for s in tag_sets:
            all_tags |= s

        self._props_label.setText(
            f"<b>Total tags:</b> {len(all_tags)}<br>"
            f"<b>Common tags:</b> {len(common)}<br>"
            f"<b>Starred:</b> {sum(1 for a in assets if a.starred)}"
        )

        if common:
            tag_pills = " ".join(f'<span style="background:rgba(255,255,255,0.1);'
                                  f'padding:1px 6px;border-radius:3px;">{t}</span>'
                                  for t in sorted(common))
            self._tags_label.setText(f"Common: {tag_pills}")
        else:
            self._tags_label.setText("<i>No common tags</i>")

        self._assign_label.setText(
            f"{sum(1 for a in assets if a.assignments)} assigned")
        self._notes_label.setText(
            f"{sum(1 for a in assets if a.notes)} with notes")

    def apply_theme(self, theme):
        """Apply theme colors to the info panel."""
        self._theme = theme
        f = theme.font_size
        self.setStyleSheet(f"""
            #info_panel {{
                background: {theme.bg_main};
                color: {theme.text_primary};
                font-family: {theme.font_family};
                font-size: {f}px;
            }}
            QLabel {{
                color: {theme.text_primary};
            }}
            QScrollArea {{
                background: {theme.bg_main};
                border: none;
            }}
        """)
```

- [ ] **Step 2: Verify compile**

Run: `python -m py_compile doxyedit/infopanel.py`

- [ ] **Step 3: Commit**

```bash
git add doxyedit/infopanel.py
git commit -m "feat(infopanel): asset metadata display widget"
```

---

### Task 5: Integrate Info Panel into Main Window

Wire the InfoPanel into the splitter layout and connect it to asset selection.

**Files:**
- Modify: `doxyedit/window.py`

- [ ] **Step 1: Import InfoPanel**

At the top of window.py, near the other panel imports, add:

```python
from doxyedit.infopanel import InfoPanel
```

- [ ] **Step 2: Create info panel and add to browse_split**

Find where `_preview_pane` is created and added (around line 178-182). After the preview pane is added but before the stretch factors are set, add:

```python
        # Info panel (right side, after preview, initially hidden)
        self._info_panel = InfoPanel()
        self._info_panel.hide()
        self._browse_split.addWidget(self._info_panel)
```

- [ ] **Step 3: Update stretch factors**

The splitter now has 5 widgets: file_browser(0), tag_panel(1), browser(2), preview_pane(3), info_panel(4). Update the stretch factors:

```python
        self._browse_split.setStretchFactor(0, 0)  # file browser
        self._browse_split.setStretchFactor(1, 0)  # tag panel
        self._browse_split.setStretchFactor(2, 1)  # browser (stretches)
        self._browse_split.setStretchFactor(3, 0)  # preview pane
        self._browse_split.setStretchFactor(4, 0)  # info panel
```

- [ ] **Step 4: Update splitter size handling**

Find the saved_split restore logic (around line 187-194). Update to handle 5 sizes:

```python
        saved_split = self._settings_early.value("splitter_sizes", None)
        if saved_split:
            sizes = [int(s) for s in saved_split]
            if len(sizes) == 5:
                self._browse_split.setSizes(sizes)
            elif len(sizes) == 4:
                # Migrate from 4-panel to 5-panel: add 0 for info panel
                self._browse_split.setSizes(sizes + [0])
            else:
                self._browse_split.setSizes([0, 260, 1000, 400, 0])
        else:
            self._browse_split.setSizes([0, 260, 1000, 400, 0])
```

- [ ] **Step 5: Add View menu toggle**

Find where the docked preview toggle is added to the View menu. Add nearby:

```python
        self._toggle_info_panel_action = view_menu.addAction(
            "Info Panel", self._toggle_info_panel, QKeySequence("Ctrl+I"))
        self._toggle_info_panel_action.setCheckable(True)
        self._toggle_info_panel_action.setChecked(False)
```

- [ ] **Step 6: Implement toggle**

```python
def _toggle_info_panel(self):
    vis = not self._info_panel.isVisible()
    self._info_panel.setVisible(vis)
    self._settings.setValue("info_panel_visible", vis)
    self._toggle_info_panel_action.setChecked(vis)
```

- [ ] **Step 7: Restore visibility from settings**

Near the existing `if self._settings_early.value("preview_docked"...)` block, add:

```python
        if self._settings_early.value("info_panel_visible", False, type=bool):
            self._info_panel.show()
            self._toggle_info_panel_action.setChecked(True)
```

- [ ] **Step 8: Wire to asset selection**

In `_on_asset_selected` (around line 1750), after the existing panel updates, add:

```python
            if self._info_panel.isVisible():
                self._info_panel.set_assets([asset])
```

In `_on_selection_changed` (around line 2023), add:

```python
        if self._info_panel.isVisible():
            self._info_panel.set_assets(assets)
```

- [ ] **Step 9: Wire theme**

In `_apply_theme`, where `_file_browser.apply_theme` is called, add:

```python
        if hasattr(self, '_info_panel'):
            self._info_panel.apply_theme(self._theme)
```

- [ ] **Step 10: Verify compile**

Run: `python -m py_compile doxyedit/window.py`

- [ ] **Step 11: Commit**

```bash
git add doxyedit/window.py
git commit -m "feat(window): info panel integration with Ctrl+I toggle"
```

---

## Summary

| Task | What | Lines (est.) |
|------|------|-------------|
| 1 | Browser filter capture/restore | ~50 |
| 2 | Project model filter_presets | ~10 |
| 3 | Smart folder UI (save/load menu) | ~70 |
| 4 | InfoPanel widget | ~210 |
| 5 | Info panel window integration | ~40 |

Total: ~380 lines of new code across 5 tasks, 5 commits. Smart Folders and Info Panel are independent — either can ship alone.
