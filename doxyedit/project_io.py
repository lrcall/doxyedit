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

from PySide6.QtCore import QThread, QMutex, QMutexLocker, QWaitCondition, Signal

from doxyedit.models import Project


class BackgroundSaver(QThread):
    """One-shot save worker thread.

    Coalesces saves: only the most recent payload per path is kept.
    UI thread builds the dict (cheap, ~ms) and submits via `submit()`;
    worker serializes JSON + writes atomically (~hundreds of ms on big
    projects) without blocking the UI. `flush()` waits for the queue
    to drain - call from closeEvent.
    """

    saved = Signal(str)   # emitted with path on successful write
    failed = Signal(str, str)  # path, error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        # path -> (data_dict, compact_flag)
        self._queue: dict = {}
        self._stop = False
        self._idle = True

    def submit(self, path: str, data: dict, *, compact: bool = False):
        with QMutexLocker(self._mutex):
            self._queue[path] = (data, compact)
            self._idle = False
            self._cond.wakeAll()

    def flush(self, timeout_ms: int = 10_000):
        """Block until the queue is empty + last save completed."""
        import time
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            with QMutexLocker(self._mutex):
                if not self._queue and self._idle:
                    return True
            self.msleep(20)
        return False

    def stop(self):
        with QMutexLocker(self._mutex):
            self._stop = True
            self._cond.wakeAll()
        self.wait(2000)

    def run(self):
        while True:
            with QMutexLocker(self._mutex):
                while not self._queue and not self._stop:
                    self._idle = True
                    self._cond.wait(self._mutex)
                if self._stop:
                    return
                self._idle = False
                # Drain whatever is queued at this moment
                batch = self._queue
                self._queue = {}
            for path, (data, compact) in batch.items():
                try:
                    Project.write_save_dict(data, path, compact=compact)
                    self.saved.emit(path)
                except Exception as e:
                    self.failed.emit(path, str(e))


class SaveLoadMixin:
    """Self-contained save + watcher helpers shared across MainWindow."""

    def _watch_project(self):
        """Start watching the current project file for external changes."""
        old = self._file_watcher.files()
        if old:
            self._file_watcher.removePaths(old)
        if self._project_path and Path(self._project_path).exists():
            self._file_watcher.addPath(self._project_path)

    def _save_project_silently(self, path: str | None = None, *, compact: bool = False):
        """Save without tripping our own file watcher.

        Removes `path` from the watcher, saves, re-adds. Replaces the
        fragile `_own_save_pending` counter pattern at save sites. Still
        increments the counter for any legacy reader. If `path` is None,
        uses `self._project_path`. `compact=True` skips JSON indenting -
        used for autosaves where file diffability doesn't matter.
        """
        target = path or self._project_path
        if not target:
            return
        watched = target in self._file_watcher.files()
        if watched:
            self._file_watcher.removePath(target)
        try:
            self.project.save(target, compact=compact)
        finally:
            self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1
            if watched and Path(target).exists():
                self._file_watcher.addPath(target)

    def _ensure_bg_saver(self) -> BackgroundSaver:
        bs = getattr(self, "_bg_saver", None)
        if bs is None:
            bs = BackgroundSaver(self)
            bs.saved.connect(self._on_bg_saved)
            bs.failed.connect(self._on_bg_save_failed)
            bs.start()
            self._bg_saver = bs
        return bs

    def _on_bg_saved(self, path: str):
        try:
            self.status.showMessage(f"Saved {Path(path).name}", 2500)
        except Exception:
            pass
        # Re-arm the file watcher now that the write is done. Match the
        # silent-save semantics so external-change detection still works.
        try:
            if path and Path(path).exists() and path not in self._file_watcher.files():
                self._file_watcher.addPath(path)
        except Exception:
            pass

    def _on_bg_save_failed(self, path: str, err: str):
        try:
            self.status.showMessage(f"Save failed: {err[:80]}", 8000)
        except Exception:
            pass

    def _autosave(self):
        if not (self._dirty and self._project_path):
            return
        target = self._project_path
        # Build the dict on the UI thread so no Project state mutates
        # under the worker. Then hand off serialize+write to the thread.
        try:
            data = self.project.build_save_dict(target)
        except Exception as e:
            self.status.showMessage(f"Autosave prep failed: {e}", 5000)
            return
        # Drop the watcher around the write to avoid self-trigger
        if target in self._file_watcher.files():
            self._file_watcher.removePath(target)
        self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1
        self._ensure_bg_saver().submit(target, data, compact=True)
        self._dirty = False
        self.status.showMessage("Auto-saving…", 1500)
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
