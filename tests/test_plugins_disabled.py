"""plugins.set_disabled / is_disabled / _disabled_plugins — the
QSettings-backed enable/disable flag. Tests use a clean QSettings
scope so the user's real plugin disable state isn't touched."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _setup_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestPluginsDisabled(unittest.TestCase):
    """Use a unique organization name per test so reads don't leak
    into the user's real DoxyEdit settings."""

    def setUp(self):
        self.app = _setup_qt()
        from PySide6.QtCore import QSettings
        # Ensure a clean slate for the QSettings scope.
        qs = QSettings("DoxyEdit", "DoxyEdit")
        self._saved = qs.value("plugins/disabled", "")
        qs.setValue("plugins/disabled", "")

    def tearDown(self):
        from PySide6.QtCore import QSettings
        QSettings("DoxyEdit", "DoxyEdit").setValue(
            "plugins/disabled", self._saved or "")

    def test_initial_state_empty(self):
        from doxyedit.plugins import _disabled_plugins, is_disabled
        self.assertEqual(_disabled_plugins(), set())
        self.assertFalse(is_disabled("anything"))

    def test_set_disabled_persists(self):
        from doxyedit.plugins import set_disabled, is_disabled, _disabled_plugins
        set_disabled("broken_plugin", True)
        self.assertTrue(is_disabled("broken_plugin"))
        self.assertIn("broken_plugin", _disabled_plugins())

    def test_set_disabled_false_removes(self):
        from doxyedit.plugins import set_disabled, is_disabled
        set_disabled("p1", True)
        set_disabled("p1", False)
        self.assertFalse(is_disabled("p1"))

    def test_multiple_disabled_persisted(self):
        from doxyedit.plugins import set_disabled, _disabled_plugins
        set_disabled("a", True)
        set_disabled("b", True)
        set_disabled("c", True)
        self.assertEqual(_disabled_plugins(), {"a", "b", "c"})

    def test_idempotent_disable(self):
        """Calling set_disabled(True) twice doesn't duplicate the entry."""
        from doxyedit.plugins import set_disabled, _disabled_plugins
        set_disabled("p1", True)
        set_disabled("p1", True)
        self.assertEqual(_disabled_plugins(), {"p1"})


if __name__ == "__main__":
    unittest.main()
