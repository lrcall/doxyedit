"""Project-tab slot management mixin.

MainWindow runs multiple projects as tabs, each backed by a slot dict
(`{"project", "path", "label", "collapsed_folders", "hidden_folders"}`).
This mixin owns:

- adding / closing / detaching tabs
- saving + restoring per-slot UI state on switch
- the right-click context menu and rename helpers

It depends on the host providing:

- `self._project_slots: list[dict]`
- `self._current_slot: int`
- `self._proj_tab_bar: QTabBar`
- `self.project`, `self._project_path`, `self._dirty`
- `self.browser` (collapsed/hidden folder sets)
- `self._save_project_silently` (from SaveLoadMixin)
- `self._rebind_project`, `self._update_title_bar_color`,
  `self._new_project_blank`, `self._register_initial_slot`,
  `self._rename_proj_tab_dialog`

Window/title work is unchanged; only routing moves.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMenu, QMessageBox


class TabManagerMixin:
    """Project tab slot management. Mixed into MainWindow."""

    def _add_project_tab(self, project, path: str | None, label: str):
        self._save_current_slot()
        slot = {"project": project, "path": path, "label": label}
        self._project_slots.append(slot)
        idx = len(self._project_slots) - 1
        self._proj_tab_bar.blockSignals(True)
        self._proj_tab_bar.addTab(label)
        self._proj_tab_bar.blockSignals(False)
        self._proj_tab_bar.setCurrentIndex(idx)
        self._switch_to_slot(idx)

    def _save_current_slot(self):
        if 0 <= self._current_slot < len(self._project_slots):
            slot = self._project_slots[self._current_slot]
            slot["project"] = self.project
            slot["collapsed_folders"] = set(self.browser._collapsed_folders)
            slot["hidden_folders"] = set(self.browser._hidden_folders)
            if self._dirty and slot["path"]:
                self._save_project_silently(slot["path"])
                self._dirty = False

    def _on_proj_tab_changed(self, idx: int):
        if (idx < 0 or idx >= len(self._project_slots)
                or idx == self._current_slot):
            return
        self._save_current_slot()
        self._switch_to_slot(idx)

    def _switch_to_slot(self, idx: int):
        slot = self._project_slots[idx]
        self._current_slot = idx
        self.project = slot["project"]
        self._project_path = slot["path"]
        self._rebind_project(clear_folder_state=True)
        if slot.get("collapsed_folders"):
            self.browser._collapsed_folders = set(slot["collapsed_folders"])
        if slot.get("hidden_folders"):
            self.browser._hidden_folders = set(slot["hidden_folders"])
        if slot.get("collapsed_folders") or slot.get("hidden_folders"):
            self.browser.refresh()
        self.setWindowTitle(f"DoxyEdit - {slot['label']}")
        self._proj_tab_bar.setTabText(idx, slot["label"])

    def _close_proj_tab(self, idx: int):
        if len(self._project_slots) <= 1:
            self._new_project_blank()
            return
        slot = self._project_slots[idx]
        if slot["path"] and self._dirty and self._current_slot == idx:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                f"Save '{slot['label']}' before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                self._save_project_silently(slot["path"])
        self._project_slots.pop(idx)
        self._proj_tab_bar.blockSignals(True)
        self._proj_tab_bar.removeTab(idx)
        self._proj_tab_bar.blockSignals(False)
        new_idx = min(idx, len(self._project_slots) - 1)
        self._current_slot = -1
        self._proj_tab_bar.setCurrentIndex(new_idx)
        self._switch_to_slot(new_idx)

    def _on_proj_tab_moved(self, from_idx: int, to_idx: int):
        slot = self._project_slots.pop(from_idx)
        self._project_slots.insert(to_idx, slot)
        if self._current_slot == from_idx:
            self._current_slot = to_idx
        elif from_idx < self._current_slot <= to_idx:
            self._current_slot -= 1
        elif to_idx <= self._current_slot < from_idx:
            self._current_slot += 1

    def _preset_context_menu(self, idx: int, global_pos):
        """Right-click menu on the project tab bar."""
        if idx < 0 or idx >= len(self._project_slots):
            return
        menu = QMenu(self)
        menu.addAction(
            "Rename Tab...",
            lambda: self._rename_proj_tab_dialog(idx))
        menu.addAction(
            "Open in New Window",
            lambda: self._detach_proj_tab(idx))
        menu.addSeparator()
        menu.addAction("Close Tab", lambda: self._close_proj_tab(idx))
        menu.exec(global_pos)

    def _detach_proj_tab(self, idx: int):
        """Pop a project tab out into its own window. Uses type(self)
        instead of importing MainWindow to avoid an import cycle."""
        if idx < 0 or idx >= len(self._project_slots):
            return
        if idx == self._current_slot:
            self._save_current_slot()
        slot = self._project_slots[idx]
        path = slot.get("path")
        MW = type(self)
        win = MW(_skip_autoload=True)
        MW._open_windows.append(win)
        if path:
            win._load_project_from(path)
            loader = getattr(win, "_open_loader", None)
            if loader is not None:
                loader.loaded.connect(
                    lambda _p, _path, w=win: (
                        w.show(), w._update_title_bar_color()))
                loader.failed.connect(
                    lambda _path, _err, w=win: w.show())
            else:
                win.show()
                win._update_title_bar_color()
        else:
            win.project = slot["project"]
            win._project_path = None
            win._rebind_project(clear_folder_state=True)
            win._register_initial_slot(None, slot["label"])
            win.setWindowTitle(f"DoxyEdit - {slot['label']}")
            win.show()
            win._update_title_bar_color()
        # Remove the tab from this window. We just saved or transferred,
        # so skip the unsaved-changes prompt.
        if len(self._project_slots) <= 1:
            self._new_project_blank()
            self._register_initial_slot(None, "New Project")
        else:
            self._project_slots.pop(idx)
            self._proj_tab_bar.blockSignals(True)
            self._proj_tab_bar.removeTab(idx)
            self._proj_tab_bar.blockSignals(False)
            new_idx = min(idx, len(self._project_slots) - 1)
            if self._current_slot == idx:
                self._current_slot = -1
                self._proj_tab_bar.setCurrentIndex(new_idx)
                self._switch_to_slot(new_idx)
            elif self._current_slot > idx:
                self._current_slot -= 1

    def _rename_proj_tab(self, idx: int, label: str):
        if 0 <= idx < len(self._project_slots):
            self._project_slots[idx]["label"] = label
            self._proj_tab_bar.setTabText(idx, label)
