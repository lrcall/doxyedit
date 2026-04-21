"""File watcher + autosave + silent-save helpers.

MainWindow mixes in `SaveLoadMixin` to keep window.py focused on UI
construction. The methods here depend on MainWindow providing:

- `self._project_path: str | None` — current project file path
- `self._file_watcher: QFileSystemWatcher` — external-change watcher
- `self.project` — Project instance with `.save(path)`
- `self._dirty: bool` — unsaved-changes flag
- `self._settings: QSettings` — app settings
- `self.status` — status bar
- `self._collect_open_project_paths()` — returns list of open project paths
- `self._last_collection_projects: list | None` — last-written collection list

Interactive paths (`_save_project`, `_save_project_as`, `_open_project`,
`_reload_project`, etc.) remain on MainWindow because they own dialog
flow + rebind logic. This module is just the non-interactive glue.
"""
from __future__ import annotations

import json
from pathlib import Path


class SaveLoadMixin:
    """Self-contained save + watcher helpers shared across MainWindow."""

    def _watch_project(self):
        """Start watching the current project file for external changes."""
        old = self._file_watcher.files()
        if old:
            self._file_watcher.removePaths(old)
        if self._project_path and Path(self._project_path).exists():
            self._file_watcher.addPath(self._project_path)

    def _save_project_silently(self, path: str | None = None):
        """Save without tripping our own file watcher.

        Removes `path` from the watcher, saves, re-adds. Replaces the
        fragile `_own_save_pending` counter pattern at save sites. Still
        increments the counter for any legacy reader. If `path` is None,
        uses `self._project_path`.
        """
        target = path or self._project_path
        if not target:
            return
        watched = target in self._file_watcher.files()
        if watched:
            self._file_watcher.removePath(target)
        try:
            self.project.save(target)
        finally:
            self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1
            if watched and Path(target).exists():
                self._file_watcher.addPath(target)

    def _autosave(self):
        if self._dirty and self._project_path:
            self._save_project_silently(self._project_path)
            self._dirty = False
            self.status.showMessage("Auto-saved", 3000)
            self._autosave_collection()

    def _autosave_collection(self):
        """Silently overwrite the last-saved collection file if the project
        list has actually changed since the last autosave."""
        coll_path = self._settings.value("last_collection", "")
        if not coll_path:
            return
        projects = self._collect_open_project_paths()
        if not projects:
            return
        # Compare against the last-written project list to avoid redundant writes
        last = getattr(self, "_last_collection_projects", None)
        if last == projects:
            return
        try:
            Path(coll_path).write_text(
                json.dumps({"_type": "doxycoll", "projects": projects}, indent=2),
                encoding="utf-8")
            self._last_collection_projects = list(projects)
        except Exception:
            pass
