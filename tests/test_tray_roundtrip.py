"""WorkTray save_state -> load_state -> save_state round-trip
(doxyedit/tray.py, read-only for this test - behavior lock only).

Persisted shapes:
- single default tray named "Tray 1" -> plain list of asset ids
  (backward compat with old project files)
- anything else -> dict of tray_name -> asset id list, in tab display
  order (insertion-ordered dict)

QSettings is patched with an in-memory fake so the test never reads or
writes the real per-user settings (tray_default_name / tray_icon_size /
tray_view_mode would otherwise leak in from the machine).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tests.factory import make_project


def _app():
    return QApplication.instance() or QApplication([])


class _FakeSettings:
    """Deterministic QSettings stand-in: always returns the default."""

    def __init__(self, *args, **kwargs):
        pass

    def value(self, key, default=None, type=None):
        return default

    def setValue(self, key, value):
        pass


class TestTrayRoundtrip(unittest.TestCase):
    def setUp(self):
        _app()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.project = make_project(self.tmp, n_assets=5)
        self.ids = [a.id for a in self.project.assets]
        self._settings_patch = patch("doxyedit.tray.QSettings",
                                     _FakeSettings)
        self._settings_patch.start()
        from doxyedit.tray import WorkTray
        self.tray = WorkTray()

    def tearDown(self):
        self.tray.deleteLater()
        self._settings_patch.stop()
        self._tmp.cleanup()

    def test_single_default_tray_saves_as_list(self):
        data = [self.ids[0], self.ids[2]]
        self.tray.load_state(data, self.project)
        state = self.tray.save_state()
        self.assertIsInstance(state, list)
        self.assertEqual(state, data)

    def test_list_roundtrip_is_stable(self):
        data = [self.ids[1], self.ids[3], self.ids[4]]
        self.tray.load_state(data, self.project)
        s1 = self.tray.save_state()
        self.tray.load_state(s1, self.project)
        s2 = self.tray.save_state()
        self.assertEqual(s1, s2)
        self.assertEqual(s2, data)

    def test_multi_tray_dict_roundtrip(self):
        data = {
            "Tray 1": [self.ids[0]],
            "Alt": [self.ids[1], self.ids[2]],
            "Empty": [],
        }
        self.tray.load_state(data, self.project)
        s1 = self.tray.save_state()
        self.assertIsInstance(s1, dict)
        self.assertEqual(s1, data)
        # Insertion / tab order preserved, not just membership.
        self.assertEqual(list(s1), list(data))
        self.tray.load_state(s1, self.project)
        s2 = self.tray.save_state()
        self.assertEqual(s1, s2)
        self.assertEqual(list(s1), list(s2))

    def test_single_named_tray_stays_dict(self):
        # Only the literal "Tray 1" single-tray case collapses to a
        # list; a renamed single tray must keep its name via the dict.
        data = {"Refs": [self.ids[0], self.ids[4]]}
        self.tray.load_state(data, self.project)
        s1 = self.tray.save_state()
        self.assertIsInstance(s1, dict)
        self.assertEqual(s1, data)
        self.tray.load_state(s1, self.project)
        self.assertEqual(self.tray.save_state(), s1)

    def test_unresolvable_ids_dropped_from_active_tray(self):
        # load_state only re-adds ids that still resolve via
        # project.get_asset; the active tray is re-flushed from the
        # visible list on save, so ghosts do not round-trip.
        data = [self.ids[0], "ghost_asset_9"]
        self.tray.load_state(data, self.project)
        state = self.tray.save_state()
        self.assertEqual(state, [self.ids[0]])

    def test_garbage_state_falls_back_to_empty_default(self):
        self.tray.load_state(42, self.project)
        state = self.tray.save_state()
        self.assertEqual(state, [])


if __name__ == "__main__":
    unittest.main()
