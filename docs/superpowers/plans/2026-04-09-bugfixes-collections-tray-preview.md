# Bug Fixes: Collections, Tray Drag-Drop, Preview Position — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three reported bugs: collections not loading/reloading, drag-drop to tray not working in normal view, and preview dialog not remembering its position across monitors.

**Architecture:** Three independent fixes in separate files. Collections fix addresses silent failures and adds reload UI. Preview fix adds multi-monitor screen validation on restore. Tray drag-drop fix ensures the browser's eventFilter drag path works consistently in flat view.

**Tech Stack:** PySide6 (QSettings, QApplication.screens(), QDrag/QMimeData)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `doxyedit/window.py` | Modify | Collections: warn on missing projects, add Reload Collection action |
| `doxyedit/preview.py` | Modify | Multi-monitor position validation on ImagePreviewDialog open |
| `doxyedit/browser.py` | Modify | Ensure drag-out works in flat view by fixing model reference |

---

### Task 1: Fix Collections — Warn on Missing Projects + Reload Action

The core collection bugs: silent filtering of missing projects, no reload action, no feedback when projects fail to load.

**Files:**
- Modify: `doxyedit/window.py`

- [ ] **Step 1: Add warning when projects are filtered out during restore**

Find `_restore_collection` (line 464). The current code silently filters missing projects at line 470:

```python
paths = [p for p in data.get("projects", []) if Path(p).exists()]
```

Replace the method body (lines 466-491) with a version that warns:

```python
    def _restore_collection(self, coll_path: str) -> bool:
        """Load all projects from a collection file as tabs. Returns True on success."""
        try:
            data = json.loads(Path(coll_path).read_text(encoding="utf-8"))
        except Exception:
            return False
        all_paths = data.get("projects", [])
        paths = [p for p in all_paths if Path(p).exists()]
        missing = [p for p in all_paths if not Path(p).exists()]
        if not paths:
            return False
        # Load first project into the initial slot
        first = paths[0]
        self.project = Project.load(first)
        self._project_path = first
        self._register_initial_slot(first, Path(first).stem)
        self._rebind_project()
        self.setWindowTitle(f"DoxyEdit — {Path(first).name}")
        # Load remaining projects as additional tabs
        failed = []
        for path in paths[1:]:
            try:
                project = Project.load(path)
                self._add_project_tab(project, path, Path(path).stem)
            except Exception:
                failed.append(path)
        # Switch back to first tab
        self._proj_tab_bar.setCurrentIndex(0)
        self._switch_to_slot(0)
        # Report results
        loaded = len(paths) - len(failed)
        msg = f"Restored collection: {loaded} project(s)"
        if missing:
            msg += f" | {len(missing)} missing"
        if failed:
            msg += f" | {len(failed)} failed to load"
        self.status.showMessage(msg, 5000)
        # Show warning dialog if anything was lost
        if missing or failed:
            from PySide6.QtWidgets import QMessageBox
            details = []
            if missing:
                details.append("Missing files (not found on disk):")
                details.extend(f"  • {p}" for p in missing)
            if failed:
                details.append("Failed to load:")
                details.extend(f"  • {p}" for p in failed)
            QMessageBox.warning(self, "Collection",
                                f"Some projects could not be loaded:\n\n" + "\n".join(details))
        return True
```

- [ ] **Step 2: Add "Reload Collection" action to File menu**

Find where "Save Collection..." is added to the File menu (search for `_save_collection`). Add nearby:

```python
        file_menu.addAction("Reload Collection", self._reload_collection)
```

- [ ] **Step 3: Implement _reload_collection**

```python
def _reload_collection(self):
    """Reload the last saved collection file."""
    coll_path = self._settings.value("last_collection", "")
    if not coll_path or not Path(coll_path).exists():
        self.status.showMessage("No collection to reload", 3000)
        return
    # Close all tabs except the first
    while self._proj_tab_bar.count() > 1:
        self._close_project_tab(self._proj_tab_bar.count() - 1)
    # Restore from file
    if not self._restore_collection(coll_path):
        self.status.showMessage("Collection reload failed", 3000)
```

- [ ] **Step 4: Verify compile**

Run: `python -m py_compile doxyedit/window.py`

- [ ] **Step 5: Commit**

```bash
git add doxyedit/window.py
git commit -m "fix(collections): warn on missing projects, add Reload Collection action"
```

---

### Task 2: Fix Preview Dialog Multi-Monitor Position

The preview dialog saves raw x/y coordinates but doesn't validate them against available screens on restore. On multi-monitor setups, the window can appear off-screen.

**Files:**
- Modify: `doxyedit/preview.py`

- [ ] **Step 1: Add screen validation to position restore**

Find the constructor of `ImagePreviewDialog` (around line 140). Find lines 156-159:

```python
        px = settings.value("preview_x", -1, type=int)
        py = settings.value("preview_y", -1, type=int)
        if px >= 0 and py >= 0:
            self.move(px, py)
```

Replace with:

```python
        px = settings.value("preview_x", -1, type=int)
        py = settings.value("preview_y", -1, type=int)
        if px >= 0 and py >= 0:
            # Validate position is on a connected screen
            from PySide6.QtCore import QPoint
            target = QPoint(px + self.width() // 2, py + 30)  # check center-top of window
            screen = QApplication.screenAt(target)
            if screen:
                # Clamp to screen bounds
                geom = screen.availableGeometry()
                px = max(geom.left(), min(px, geom.right() - self.width()))
                py = max(geom.top(), min(py, geom.bottom() - self.height()))
                self.move(px, py)
            else:
                # Saved position is off-screen — center on primary screen
                primary = QApplication.primaryScreen()
                if primary:
                    geom = primary.availableGeometry()
                    self.move(
                        geom.left() + (geom.width() - self.width()) // 2,
                        geom.top() + (geom.height() - self.height()) // 2)
```

- [ ] **Step 2: Verify compile**

Run: `python -m py_compile doxyedit/preview.py`

- [ ] **Step 3: Commit**

```bash
git add doxyedit/preview.py
git commit -m "fix(preview): validate saved position against connected screens"
```

---

### Task 3: Fix Tray Drag-Drop in Normal View

The drag-out from the browser's flat view uses `self._model._pixmaps` for the drag icon, but the drag itself should work regardless. The actual issue may be that in normal view, the `_selected_ids` set isn't populated correctly when the selection model changes, or the eventFilter doesn't fire for the flat view's viewport. Investigate and fix.

**Files:**
- Modify: `doxyedit/browser.py`

- [ ] **Step 1: Ensure eventFilter is installed on flat view viewport**

Find where event filters are installed on the list view. Search for `installEventFilter` in `_build` or `__init__`. Verify that BOTH `self._list_view` and `self._list_view.viewport()` have the filter installed. If only one is installed, add the other.

The event filter check at line 2396 uses `_view_for_obj` which checks both the view and its viewport. So both must have filters installed.

Look for a line like:
```python
self._list_view.viewport().installEventFilter(self)
```

If the viewport filter isn't installed, add it after the view filter:
```python
self._list_view.installEventFilter(self)
self._list_view.viewport().installEventFilter(self)
```

- [ ] **Step 2: Ensure selection sync in flat view**

The flat view uses `self._list_view.selectionModel().selectionChanged` to update `_selected_ids`. Find where this signal is connected (search for `selectionChanged`). Verify the handler properly populates `_selected_ids` for the flat view.

If there's a disconnect — for example, the handler only runs for folder view sections — fix it by ensuring the flat view's selection model is also connected.

- [ ] **Step 3: Add "Send to Tray" drag hint for tray visibility**

In the drag initiation code (around line 2496-2507), after the drag completes successfully, check if the tray is visible. If not, this might explain why users think drag-to-tray doesn't work — they can't see the target.

This is a UX improvement rather than a code fix: if the user drags to where the tray would be but it's hidden, show a status message. In the eventFilter, after `drag.exec()` returns, add:

```python
                        result = drag.exec(Qt.DropAction.CopyAction)
                        return True
```

No code change needed here — just verify the flow works. The key fix is Steps 1 and 2.

- [ ] **Step 4: Verify compile**

Run: `python -m py_compile doxyedit/browser.py`

- [ ] **Step 5: Commit**

```bash
git add doxyedit/browser.py
git commit -m "fix(browser): ensure drag-out works in flat view for tray drops"
```

---

## Summary

| Task | What | Risk |
|------|------|------|
| 1 | Collections: warn missing, reload action | Low — adds feedback, new menu action |
| 2 | Preview: multi-monitor position validation | Low — only changes position restore logic |
| 3 | Tray drag-drop: verify eventFilter + selection in flat view | Medium — needs investigation first |

Task 3 is investigative — the subagent should read the code, verify the hypothesis, and only change what's actually broken. If the drag-out works correctly in flat view and the bug is actually something else (e.g., tray not visible), report DONE_WITH_CONCERNS.
