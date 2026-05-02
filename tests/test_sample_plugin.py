"""Verify docs/sample_plugin.py is loadable + functional through
the real plugin loader. If we ship a sample plugin to users in the
docs, it had better actually work."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SAMPLE_PATH = REPO_ROOT / "docs" / "sample_plugin.py"


class TestSamplePlugin(unittest.TestCase):
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

    def test_sample_plugin_file_exists(self):
        """Docs reference this file; if it disappears, our docs lie."""
        self.assertTrue(SAMPLE_PATH.exists())

    def test_sample_plugin_loads_without_error(self):
        with tempfile.TemporaryDirectory() as td:
            shutil.copy(SAMPLE_PATH, Path(td) / "sample_plugin.py")
            with patch.object(self._mod, "plugins_dir",
                               return_value=Path(td)):
                loaded = self._mod.discover_and_load()
            self.assertIn("sample_plugin", loaded)
            self.assertNotIn("sample_plugin", self._mod._REGISTRY._failed)

    def test_sample_plugin_handlers_fire(self):
        """Sample plugin registers project_loaded + post_pushed.
        Emit both and verify the plugin log file got both lines.
        Patch plugins_log_path() to a tempfile so we don't write to
        the user's real ~/.doxyedit/plugins.log."""
        with tempfile.TemporaryDirectory() as td:
            shutil.copy(SAMPLE_PATH, Path(td) / "sample_plugin.py")
            log_path = Path(td) / "plugins.log"
            with patch.object(self._mod, "plugins_dir",
                               return_value=Path(td)), \
                 patch.object(self._mod, "plugins_log_path",
                               return_value=log_path):
                self._mod.discover_and_load()
                from doxyedit.models import Project, SocialPost
                self._mod.emit("project_loaded", Project(),
                               "/tmp/x.doxy")
                post = SocialPost(id="abc12345-rest")
                self._mod.emit("post_pushed", post, "bluesky",
                               True, "ok")
            content = log_path.read_text(encoding="utf-8")
        self.assertIn("Project loaded", content)
        self.assertIn("OK push", content)
        self.assertIn("bluesky", content)


if __name__ == "__main__":
    unittest.main()
