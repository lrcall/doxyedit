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

Interactive paths (`_save_project_as`, `_open_project`, `_reload_project`,
etc.) remain on MainWindow because they own dialog flow + rebind logic.
`_save_project` lives here since it has no dialog flow — only UI-state
sync + file write. This module is the save/load glue.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, QMutex, QMutexLocker, QWaitCondition, Signal, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from doxyedit.formats import ensure_project_ext, ensure_collection_ext
from doxyedit.models import Project
from doxyedit.perf import perf_time
from doxyedit.session import ProjectLoader
from doxyedit.themes import THEMES


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
            # Tuple shape: (kind, payload, compact). kind="dict" => payload is
            # a pre-built dict (legacy path); kind="project" => payload is a
            # Project instance and the worker calls build_save_dict itself.
            self._queue[path] = ("dict", data, compact)
            self._idle = False
            self._cond.wakeAll()

    def submit_project(self, path: str, project, *, compact: bool = False):
        """Submit a Project; worker builds the save dict + serializes + writes.
        Caller must have run project._migrate_custom_tags() on the UI thread.
        Most expensive step (asdict on every asset) moves off the UI thread."""
        with QMutexLocker(self._mutex):
            self._queue[path] = ("project", project, compact)
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
            for path, payload in batch.items():
                try:
                    kind, body, compact = payload
                    if kind == "project":
                        # Build the dict here (off UI thread) - covers ~80%
                        # of save cost on big projects (asdict per asset)
                        data = body.build_save_dict(path)
                    else:
                        data = body
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

    @perf_time("autosave_uithread")
    def _autosave(self):
        if not (self._dirty and self._project_path):
            return
        target = self._project_path
        # UI-thread mutation step (cheap - <1ms even on big projects)
        try:
            self.project._migrate_custom_tags()
        except Exception as e:
            self.status.showMessage(f"Autosave prep failed: {e}", 5000)
            return
        # Drop the watcher around the write to avoid self-trigger
        if target in self._file_watcher.files():
            self._file_watcher.removePath(target)
        self._own_save_pending = getattr(self, "_own_save_pending", 0) + 1
        # Worker thread builds the save dict (asdict per asset) AND serializes
        # AND writes - the entire heavy save cost moves off the UI thread.
        self._ensure_bg_saver().submit_project(target, self.project, compact=True)
        self._dirty = False
        self.status.showMessage("Auto-saving…", 1500)
        self._autosave_collection()

    def _save_project(self):
        """Interactive save — syncs UI state, writes to current path, and
        flashes the status bar. Falls back to _save_project_as if no path
        is set yet. MainWindow provides browser/tag_panel/work_tray/theme/
        _add_recent_project; the file IO is delegated to
        _save_project_silently."""
        if self._project_path:
            # Sync all UI state to project before saving
            self.project.sort_mode = self.browser.sort_combo.currentText()
            self.project.eye_hidden_tags = list(self.browser._eye_hidden_tags)
            self.project.hidden_tags = list(self.tag_panel._hidden_tags)
            self.project.tray_items = self.work_tray.save_state()
            self._save_project_silently(self._project_path)
            self._dirty = False
            self._settings.setValue("last_project", self._project_path)
            self._add_recent_project(self._project_path)
            self.status.showMessage(f"Saved {Path(self._project_path).name}")
            self.status.setStyleSheet(
                f"QStatusBar {{ background: {self._theme.accent}; "
                f"color: {self._theme.text_on_accent}; }}")
            QTimer.singleShot(800, lambda: self.status.setStyleSheet(""))
            self._autosave_collection()
        else:
            self._save_project_as()

    def _reload_project(self):
        """Reload the current project file from disk (F5). Load runs
        off-thread via ProjectLoader. MainWindow provides browser /
        status / _rebind_project / _apply_theme."""
        if not self._project_path or not Path(self._project_path).exists():
            self.browser.refresh()
            self.status.showMessage(
                "No project file to reload, refreshed grid", 2000)
            return
        saved_filters = self.browser.get_filter_state()
        path = self._project_path
        self.status.showMessage("Reloading project...", 0)

        loader = ProjectLoader(path, self)
        # keep reference so GC does not kill the thread
        self._reload_loader = loader

        def _on_loaded(project, loaded_path):
            self.project = project
            self._rebind_project()
            self.browser.set_filter_state(saved_filters)
            if self.project.theme_id and self.project.theme_id in THEMES:
                self._apply_theme(self.project.theme_id)
            self._dirty = False
            self.status.showMessage("Reloaded project from disk", 2000)
            try:
                from doxyedit import plugins as _dp
                _dp.emit("project_loaded", project, loaded_path)
            except Exception:
                pass

        def _on_failed(_path, err):
            self.status.showMessage(f"Reload failed: {err}", 5000)

        loader.loaded.connect(_on_loaded)
        loader.failed.connect(_on_failed)
        loader.start()

    def _locate_last_collection(self):
        """Show where the last saved collection is (or was) on disk."""
        path = self._settings.value("last_collection", "")
        if not path:
            QMessageBox.information(
                self, "Last Collection",
                "No collection has been saved yet.")
            return
        if Path(path).exists():
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            QMessageBox.warning(
                self, "Last Collection",
                f"File no longer exists:\n{path}\n\n"
                "Use 'Save Collection...' to create a new one.")

    def _save_collection_quick(self):
        """Quick save: overwrite the last collection file, or fall back
        to the full Save As dialog."""
        last = self._settings.value("last_collection", "")
        if not last or not Path(last).parent.exists():
            self._save_collection()
            return
        projects = self._collect_open_project_paths()
        if not projects:
            self.status.showMessage("No saved projects open", 3000)
            return
        try:
            Path(last).write_text(
                json.dumps({"_type": "doxycoll", "projects": projects},
                           indent=2),
                encoding="utf-8")
            self.status.showMessage(
                f"Collection saved -> {Path(last).name}", 3000)
        except Exception as e:
            self.status.showMessage(f"Save failed: {e}", 5000)

    def _save_collection(self):
        """Save all open project tabs/windows as a named collection
        (.doxycol). MainWindow provides _collect_open_project_paths,
        _dialog_dir, _remember_dir."""
        projects = self._collect_open_project_paths()
        if not projects:
            QMessageBox.information(
                self, "Save Collection",
                "No saved projects are open. Save each project to disk "
                "first (Ctrl+S).")
            return
        last = self._settings.value("last_collection", "")
        if last and Path(last).parent.exists():
            default_path = last
        elif projects:
            default_path = str(
                Path(projects[0]).parent / "workspace.doxycol")
        else:
            default_path = (
                str(Path(self._dialog_dir()) / "workspace.doxycol")
                if self._dialog_dir() else "workspace.doxycol")
        path, selected = QFileDialog.getSaveFileName(
            self, "Save Collection", default_path,
            "DoxyEdit Collection (*.doxycol);;"
            "Legacy JSON (*.doxycoll.json)")
        if not path:
            return
        path = ensure_collection_ext(
            path, prefer_legacy="doxycoll.json" in selected)
        try:
            Path(path).write_text(
                json.dumps({"_type": "doxycoll", "projects": projects},
                           indent=2),
                encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(
                self, "Save Collection",
                f"Failed to write file:\n{e}")
            return
        self._remember_dir(path)
        self._settings.setValue("last_collection", path)
        names = ", ".join(Path(p).stem for p in projects)
        QMessageBox.information(
            self, "Collection Saved",
            f"Saved {len(projects)} project(s) to:\n{path}\n\n{names}")
        self.status.showMessage(f"Collection saved -> {path}")

    def _reload_collection(self):
        """Reload the last saved collection file. Closes extra project
        tabs first; restore is delegated to MainWindow._restore_collection."""
        coll_path = self._settings.value("last_collection", "")
        if not coll_path or not Path(coll_path).exists():
            self.status.showMessage("No collection to reload", 3000)
            return
        while self._proj_tab_bar.count() > 1:
            self._close_proj_tab(self._proj_tab_bar.count() - 1)
        if not self._restore_collection(coll_path):
            self.status.showMessage("Collection reload failed", 3000)

    def _open_collection(self):
        """Open a saved collection: each project opens in its own
        window. show() is delayed until ProjectLoader finishes so empty
        MainWindow frames don't flash while the async load runs.

        Uses type(self) to spawn fresh MainWindow instances without an
        import-cycle on doxyedit.window.
        """
        MW = type(self)
        last = self._settings.value("last_collection", "")
        start = last if last and Path(last).exists() else self._dialog_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Collection", start,
            "DoxyEdit Collection (*.doxycol *.doxycoll *.doxycoll.json);;"
            "All Files (*)")
        if not path:
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        proj_paths = data.get("projects", [])
        all_wins = [self] + [w for w in MW._open_windows if w.isVisible()]
        already_open = {w._project_path for w in all_wins if w._project_path}
        opened = 0
        for proj_path in proj_paths:
            if not Path(proj_path).exists():
                continue
            if proj_path in already_open:
                continue
            win = MW(_skip_autoload=True)
            MW._open_windows.append(win)
            loader = getattr(win, "_open_loader", None)
            win._load_project_from(proj_path)
            new_loader = getattr(win, "_open_loader", None)
            if new_loader is not None and new_loader is not loader:
                new_loader.loaded.connect(
                    lambda _p, _path, w=win: (
                        w.show(), w._update_title_bar_color()))
                new_loader.failed.connect(
                    lambda _path, _err, w=win: w.show())
            else:
                win.show()
            already_open.add(proj_path)
            opened += 1
        self._settings.setValue("last_collection", path)
        self.status.showMessage(
            f"Collection loaded: {opened} new window(s), "
            f"{len(proj_paths) - opened} already open")

    def _load_project_from(self, path: str):
        """Load a project file off the UI thread so File>Open and
        recent-click don't freeze the window. Applies the loaded
        project and rebinds panels on the ProjectLoader.loaded signal.
        MainWindow provides _rebind_project, _add_recent_project,
        _rename_proj_tab, _project_slots, _current_slot, _apply_theme."""
        bak = path + ".bak"
        try:
            shutil.copy2(path, bak)
        except Exception:
            pass
        self.status.showMessage(f"Opening {Path(path).name}...", 0)

        loader = ProjectLoader(path, self)
        self._open_loader = loader  # keep reference

        def _on_loaded(project, loaded_path):
            self.project = project
            self._rebind_project(clear_folder_state=True)
            self._project_path = loaded_path
            self._watch_project()
            self._settings.setValue("last_project", loaded_path)
            self._add_recent_project(loaded_path)
            label = Path(loaded_path).stem
            self.setWindowTitle(f"DoxyEdit - {Path(loaded_path).name}")
            self._rename_proj_tab(self._current_slot, label)
            if 0 <= self._current_slot < len(self._project_slots):
                self._project_slots[self._current_slot]["project"] = self.project
                self._project_slots[self._current_slot]["path"] = loaded_path
            if self.project.theme_id and self.project.theme_id in THEMES:
                self._apply_theme(self.project.theme_id)
            self.status.showMessage(f"Opened {Path(loaded_path).name}", 3000)
            try:
                from doxyedit import plugins as _dp
                _dp.emit("project_loaded", project, loaded_path)
            except Exception:
                pass

        def _on_failed(_path, err):
            self.status.showMessage(f"Open failed: {err}", 5000)

        loader.loaded.connect(_on_loaded)
        loader.failed.connect(_on_failed)
        loader.start()

    def _open_project(self):
        """Open dialog → delegate to _load_project_from on MainWindow."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            "DoxyEdit Projects (*.doxy *.doxyproj.json);;All Files (*)"
        )
        if path:
            self._load_project_from(path)

    def _save_project_as(self):
        """Save As… dialog. Picks a new path, writes silently, then
        re-binds the watcher and updates window title / tab label /
        slot record. MainWindow provides _dialog_dir, _remember_dir,
        _add_recent_project, _proj_tab_bar, _project_slots,
        _current_slot."""
        hint = self._project_path or (
            str(Path(self._dialog_dir()) / "project.doxy")
            if self._dialog_dir() else "project.doxy")
        path, selected = QFileDialog.getSaveFileName(
            self, "Save Project", hint,
            "DoxyEdit Project (*.doxy);;Legacy JSON (*.doxyproj.json)"
        )
        if path:
            path = ensure_project_ext(
                path, prefer_legacy="doxyproj.json" in selected)
            self._remember_dir(path)
            self._save_project_silently(path)
            self._project_path = path
            self._watch_project()
            self._dirty = False
            self._settings.setValue("last_project", path)
            self._add_recent_project(path)
            self.setWindowTitle(f"DoxyEdit - {Path(path).name}")
            self._proj_tab_bar.setTabText(0, Path(path).stem)
            if 0 <= self._current_slot < len(self._project_slots):
                self._project_slots[self._current_slot]["path"] = path
                self._project_slots[self._current_slot]["label"] = Path(path).stem
            self.status.showMessage(f"Saved {Path(path).name}")
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
