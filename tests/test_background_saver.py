"""BackgroundSaver (doxyedit/project_io.py) - lifecycle, coalescing,
and the failure path.

The integrity seam under test: `_autosave` optimistically clears
`self._dirty` the moment it enqueues a background save. If the worker
write then FAILS, the change exists only in memory - `_dirty` must be
re-marked so the next autosave tick (and closeEvent's sync save, which
is gated on `_dirty`) retries. Silently staying clean loses data.

Runs offscreen: conftest.py seeds QT_QPA_PLATFORM=offscreen; unittest
files self-manage the QApplication singleton (never quit it).
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, QFileSystemWatcher
from PySide6.QtWidgets import QApplication

from doxyedit.models import Project
from doxyedit.project_io import BackgroundSaver, SaveLoadMixin
from tests.factory import make_project


def _app():
    return QApplication.instance() or QApplication([])


def _pump(condition, timeout_s: float = 5.0) -> bool:
    """Process Qt events until condition() or timeout. Needed because
    BackgroundSaver signals cross threads (queued delivery)."""
    app = _app()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


class _StubStatus:
    def __init__(self):
        self.messages: list[str] = []

    def showMessage(self, msg, timeout=0):
        self.messages.append(str(msg))

    def setStyleSheet(self, *_):
        pass


class _StubWindow(SaveLoadMixin, QObject):
    """Minimal MainWindow stand-in for the autosave path. Mirrors the
    MRO used by the real window (SaveLoadMixin before the Qt class)."""

    def __init__(self, project, path: str):
        QObject.__init__(self)
        self.project = project
        self._project_path = path
        self._dirty = True
        self._file_watcher = QFileSystemWatcher(self)
        self.status = _StubStatus()

    def _autosave_collection(self):
        pass


class TestBackgroundSaverLifecycle(unittest.TestCase):
    def setUp(self):
        _app()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_submit_dict_flush_stop_writes_file(self):
        saver = BackgroundSaver()
        saver.start()
        try:
            target = self.tmp / "out.doxyproj.json"
            saver.submit(str(target), {"name": "Dict Payload", "assets": []})
            self.assertTrue(saver.flush())
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(data["name"], "Dict Payload")
        finally:
            saver.stop()

    def test_submit_project_writes_loadable_file(self):
        proj = make_project(self.tmp, n_assets=3)
        proj._migrate_custom_tags()  # UI-thread step, per contract
        target = self.tmp / "factory.doxy"
        saver = BackgroundSaver()
        saver.start()
        try:
            saver.submit_project(str(target), proj, compact=True)
            self.assertTrue(saver.flush())
        finally:
            saver.stop()
        loaded = Project.load(str(target))
        self.assertEqual(loaded.name, proj.name)
        self.assertEqual(len(loaded.assets), 3)
        self.assertEqual(loaded.assets[0].tags, proj.assets[0].tags)
        # tag_definitions / custom_tags stayed in sync through the save
        self.assertEqual(set(loaded.tag_definitions),
                         {ct["id"] for ct in loaded.custom_tags})

    def test_coalescing_keeps_only_latest_per_path(self):
        # Not started yet -> deterministic look at the queue.
        saver = BackgroundSaver()
        target = self.tmp / "coalesce.doxyproj.json"
        saver.submit(str(target), {"name": "first"})
        saver.submit(str(target), {"name": "second"})
        self.assertEqual(len(saver._queue), 1)
        kind, body, _compact = saver._queue[str(target)]
        self.assertEqual(kind, "dict")
        self.assertEqual(body["name"], "second")
        saver.start()
        try:
            self.assertTrue(saver.flush())
        finally:
            saver.stop()
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "second")

    def test_saved_signal_emitted_with_path(self):
        got: list[str] = []
        saver = BackgroundSaver()
        saver.saved.connect(got.append, Qt.ConnectionType.DirectConnection)
        saver.start()
        try:
            target = self.tmp / "sig.doxyproj.json"
            saver.submit(str(target), {"name": "sig"})
            self.assertTrue(saver.flush())
        finally:
            saver.stop()
        self.assertEqual(got, [str(target)])


class TestBackgroundSaverFailure(unittest.TestCase):
    def setUp(self):
        _app()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_failed_signal_on_write_error_then_recovers(self):
        failures: list[tuple[str, str]] = []
        saver = BackgroundSaver()
        saver.failed.connect(lambda p, e: failures.append((p, e)),
                             Qt.ConnectionType.DirectConnection)
        saver.start()
        target = self.tmp / "fail.doxyproj.json"
        try:
            with patch.object(Project, "write_save_dict",
                              side_effect=OSError("disk full")):
                saver.submit(str(target), {"name": "boom"})
                self.assertTrue(saver.flush())
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0][0], str(target))
            self.assertIn("disk full", failures[0][1])
            self.assertFalse(target.exists())
            # Worker must survive the failure and take the next job.
            saver.submit(str(target), {"name": "after"})
            self.assertTrue(saver.flush())
        finally:
            saver.stop()
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "after")

    def test_autosave_failure_re_marks_dirty(self):
        """THE durability seam: write fails in the worker -> the window
        must not stay clean, or the edit is silently never re-saved
        (autosave skips on clean, closeEvent skips its sync save)."""
        proj = make_project(self.tmp, n_assets=1)
        target = self.tmp / "auto.doxy"
        win = _StubWindow(proj, str(target))
        try:
            with patch.object(Project, "write_save_dict",
                              side_effect=OSError("disk full")):
                win._autosave()
                # Optimistic clear is expected at submit time...
                self.assertFalse(win._dirty)
                self.assertTrue(win._bg_saver.flush())
                # ...but once the failed signal lands, dirty must return.
                self.assertTrue(
                    _pump(lambda: win._dirty),
                    "project stayed clean after a failed background save "
                    "- the change would be silently lost")
            self.assertTrue(any("failed" in m.lower()
                                for m in win.status.messages))
        finally:
            win._bg_saver.stop()

    def test_autosave_success_stays_clean(self):
        proj = make_project(self.tmp, n_assets=1)
        target = self.tmp / "auto_ok.doxy"
        win = _StubWindow(proj, str(target))
        try:
            win._autosave()
            self.assertTrue(win._bg_saver.flush())
            _pump(lambda: target.exists(), timeout_s=2.0)
            # Give the queued saved-signal a chance to land, then check
            # nothing re-dirtied the window.
            _pump(lambda: False, timeout_s=0.2)
            self.assertFalse(win._dirty)
            self.assertTrue(target.exists())
        finally:
            win._bg_saver.stop()

    def test_failed_handler_ignores_other_paths(self):
        """A failure for a path that is no longer the current project
        must not re-dirty the window (a newer project owns _dirty)."""
        proj = make_project(self.tmp, n_assets=1)
        win = _StubWindow(proj, str(self.tmp / "current.doxy"))
        win._dirty = False
        win._on_bg_save_failed(str(self.tmp / "other.doxy"), "boom")
        self.assertFalse(win._dirty)
        win._on_bg_save_failed(str(self.tmp / "current.doxy"), "boom")
        self.assertTrue(win._dirty)


if __name__ == "__main__":
    unittest.main()
