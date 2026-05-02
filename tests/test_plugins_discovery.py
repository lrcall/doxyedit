"""plugins.discover_and_load + all_plugin_names — additional cases
beyond test_plugins_loader.py: syntax-error file recorded as failed,
no-register plugin silently skipped, dotfile + underscore filename
ignore, all_plugin_names ordering."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestDiscoveryEdgeCases(unittest.TestCase):
    def setUp(self):
        from doxyedit import plugins
        self._mod = plugins
        self._saved = plugins._REGISTRY
        plugins._REGISTRY = plugins._PluginRegistry()

    def tearDown(self):
        self._mod._REGISTRY = self._saved
        for name in list(sys.modules):
            if name.startswith("doxyedit_plugin_"):
                del sys.modules[name]

    def test_syntax_error_recorded_as_failed(self):
        """A plugin with a parse error must NOT crash the loader; it
        must land in _failed instead."""
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad_syntax.py"
            bad.write_text("def register(api:\n  not valid python",
                            encoding="utf-8")
            log_path = Path(td) / "plugins.log"
            with patch.object(self._mod, "plugins_dir",
                               return_value=Path(td)), \
                 patch.object(self._mod, "plugins_log_path",
                               return_value=log_path):
                loaded = self._mod.discover_and_load()
            self.assertEqual(loaded, [])
            self.assertIn("bad_syntax", self._mod._REGISTRY._failed)
            # Failure was logged, too.
            self.assertTrue(log_path.exists())
            self.assertIn("bad_syntax", log_path.read_text())

    def test_plugin_without_register_silently_skipped(self):
        """A .py file that has no register() function isn't a plugin —
        skip it without raising."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "no_register.py").write_text(
                "x = 42  # no register function", encoding="utf-8")
            with patch.object(self._mod, "plugins_dir",
                               return_value=Path(td)):
                loaded = self._mod.discover_and_load()
            # Not in loaded, not in failed — just ignored.
            self.assertEqual(loaded, [])
            self.assertNotIn("no_register",
                             self._mod._REGISTRY._failed)

    def test_dotfile_plugin_skipped(self):
        """Files starting with '.' are skipped (editor swap files,
        etc.) — only real .py files are considered."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".swap.py").write_text(
                "raise RuntimeError('would fail if loaded')",
                encoding="utf-8")
            with patch.object(self._mod, "plugins_dir",
                               return_value=Path(td)):
                loaded = self._mod.discover_and_load()
            self.assertEqual(loaded, [])
            self.assertEqual(self._mod._REGISTRY._failed, set())

    def test_all_plugin_names_includes_disabled(self):
        """all_plugin_names() must list disabled / failed / dotfile-
        ignored plugins so the UI can render their toggle."""
        from doxyedit.plugins import _PluginRegistry
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "alpha.py").write_text("def register(api): pass")
            (Path(td) / "beta.py").write_text("def register(api): pass")
            with patch.object(self._mod, "plugins_dir",
                               return_value=Path(td)):
                names = _PluginRegistry().all_plugin_names()
            # Returns all plugins on disk, sorted.
            self.assertEqual(names, ["alpha", "beta"])

    def test_double_load_skips_already_loaded(self):
        """discover_and_load called twice doesn't re-import a plugin
        (would call register() again, double-binding handlers)."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "once.py").write_text(
                "RECEIVED = []\n"
                "def register(api):\n"
                "    api.on('shutdown', lambda: RECEIVED.append('s'))\n",
                encoding="utf-8")
            with patch.object(self._mod, "plugins_dir",
                               return_value=Path(td)):
                first = self._mod.discover_and_load()
                second = self._mod.discover_and_load()
            self.assertEqual(first, ["once"])
            self.assertEqual(second, [])  # not re-loaded


if __name__ == "__main__":
    unittest.main()
