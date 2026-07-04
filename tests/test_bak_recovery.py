"""Backup (.bak) recovery on project open (doxyedit/project_io.py).

Integrity seams under test in `_load_project_from`:

1. The .bak must be refreshed only AFTER a successful parse. The old
   behavior copied path -> path.bak BEFORE parsing, so opening a
   corrupt file destroyed the last good backup at the exact moment it
   was needed.
2. When the main file fails to parse and a valid .bak exists, the load
   must recover from the .bak: the project data comes from the backup,
   `_project_path` stays the ORIGINAL path (so the next save repairs
   the corrupt file), and the window is marked dirty so autosave writes
   the recovered data back out.

Runs offscreen with a stub window driving the real SaveLoadMixin code.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QFileSystemWatcher
from PySide6.QtWidgets import QApplication

from doxyedit.project_io import SaveLoadMixin
from tests.factory import make_saved_project


def _app():
    return QApplication.instance() or QApplication([])


def _pump(condition, timeout_s: float = 8.0) -> bool:
    """Process Qt events until condition() or timeout. ProjectLoader
    emits from a worker thread; delivery to the stub is queued."""
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


class _StubSettings:
    def __init__(self):
        self.values: dict = {}

    def setValue(self, key, value):
        self.values[key] = value

    def value(self, key, default=None, **_):
        return self.values.get(key, default)


class _StubWindow(SaveLoadMixin, QObject):
    """Minimal MainWindow stand-in exposing everything the mixin's
    `_load_project_from` touches. UI-side hooks are recorded no-ops."""

    def __init__(self):
        QObject.__init__(self)
        self.project = None
        self._project_path = None
        self._dirty = False
        self._file_watcher = QFileSystemWatcher(self)
        self.status = _StubStatus()
        self._settings = _StubSettings()
        self._current_slot = 0
        self._project_slots = [{"project": None, "path": None, "label": ""}]
        self.window_title = ""
        self.load_finished = False  # set by both outcome paths below

    # UI hooks the load path calls - no-ops for the test
    def _rebind_project(self, clear_folder_state=False):
        pass

    def _add_recent_project(self, path):
        pass

    def setWindowTitle(self, title):
        self.window_title = title

    def _rename_proj_tab(self, slot, label):
        pass

    def _apply_theme(self, theme_id):
        pass


def _wait_for_load(win: _StubWindow) -> bool:
    """Wait for the open attempt to settle: either a project got
    applied or a terminal status message landed."""
    def done():
        if win.project is not None:
            return True
        return any("failed" in m.lower() for m in win.status.messages)
    return _pump(done)


class TestBakRecovery(unittest.TestCase):
    def setUp(self):
        _app()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.proj, self.path = make_saved_project(
            self.tmp, n_assets=3, filename="factory.doxyproj.json")
        self.path = str(self.path)
        self.bak = self.path + ".bak"

    def tearDown(self):
        self._tmp.cleanup()

    def test_successful_open_refreshes_bak_after_parse(self):
        win = _StubWindow()
        win._load_project_from(self.path)
        self.assertTrue(_wait_for_load(win))
        self.assertIsNotNone(win.project)
        self.assertEqual(win.project.name, "Factory Project")
        self.assertEqual(win._project_path, self.path)
        # Backup exists and matches the (valid) main file.
        self.assertTrue(Path(self.bak).exists())
        self.assertEqual(Path(self.bak).read_text(encoding="utf-8"),
                         Path(self.path).read_text(encoding="utf-8"))

    def test_corrupt_open_recovers_from_bak(self):
        # A previous good session left a valid backup...
        shutil.copy2(self.path, self.bak)
        good_bak_text = Path(self.bak).read_text(encoding="utf-8")
        # ...then the main file got corrupted.
        Path(self.path).write_text("{ this is not json", encoding="utf-8")

        win = _StubWindow()
        win._load_project_from(self.path)
        self.assertTrue(_wait_for_load(win))

        # Recovery loaded the backup's data.
        self.assertIsNotNone(
            win.project,
            "corrupt main file with a valid .bak must recover, not fail")
        self.assertEqual(win.project.name, "Factory Project")
        self.assertEqual(len(win.project.assets), 3)
        # The window still points at the ORIGINAL file so the next save
        # repairs it - never at the .bak.
        self.assertEqual(win._project_path, self.path)
        # Recovered state differs from what is on disk -> must be dirty
        # so autosave writes the recovered data back out.
        self.assertTrue(win._dirty)
        # The good backup must NOT have been clobbered by the corrupt
        # main file (the old copy-before-parse bug).
        self.assertEqual(Path(self.bak).read_text(encoding="utf-8"),
                         good_bak_text)
        json.loads(Path(self.bak).read_text(encoding="utf-8"))  # still valid
        # User is told this was a recovery, not a normal open.
        self.assertTrue(any("recover" in m.lower()
                            for m in win.status.messages))

    def test_corrupt_open_without_bak_fails_cleanly(self):
        Path(self.path).write_text("{ this is not json", encoding="utf-8")
        self.assertFalse(Path(self.bak).exists())

        win = _StubWindow()
        win._load_project_from(self.path)
        self.assertTrue(_wait_for_load(win))
        self.assertIsNone(win.project)
        self.assertTrue(any("open failed" in m.lower()
                            for m in win.status.messages))
        # And no bogus .bak of the corrupt file appeared.
        self.assertFalse(Path(self.bak).exists())

    def test_corrupt_open_with_corrupt_bak_fails_cleanly(self):
        Path(self.bak).write_text("also { not json", encoding="utf-8")
        Path(self.path).write_text("{ this is not json", encoding="utf-8")

        win = _StubWindow()
        win._load_project_from(self.path)
        self.assertTrue(_wait_for_load(win))
        self.assertIsNone(win.project)
        self.assertTrue(any("open failed" in m.lower()
                            for m in win.status.messages))


if __name__ == "__main__":
    unittest.main()
