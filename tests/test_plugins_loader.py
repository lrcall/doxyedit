"""Integration test for the plugin loader.

Drops a real .py file into a temp 'plugins' directory, monkeypatches
plugins.plugins_dir() to point at it, runs discover_and_load(), and
verifies the plugin's register() ran and its handlers fire on emit.
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


PLUGIN_SOURCE = '''
"""Test plugin: records events into a module-level list."""
RECEIVED = []


def register(api):
    def on_proj(project, path):
        RECEIVED.append(("project_loaded", path))

    def on_push(post, platform, ok, detail):
        RECEIVED.append(("post_pushed", platform, ok))

    api.on("project_loaded", on_proj)
    api.on("post_pushed", on_push)
'''


class TestPluginLoader(unittest.TestCase):
    def setUp(self):
        # Fresh registry per test so handlers from a previous test don't
        # leak. We swap _REGISTRY out and back.
        from doxyedit import plugins as dp
        self._dp = dp
        self._saved_reg = dp._REGISTRY
        dp._REGISTRY = dp._PluginRegistry()

    def tearDown(self):
        self._dp._REGISTRY = self._saved_reg
        # Drop any module we imported via the loader so subsequent
        # tests don't see cached state.
        for mod_name in list(sys.modules.keys()):
            if mod_name.startswith("doxyedit_plugin_"):
                del sys.modules[mod_name]

    def test_real_plugin_loads_and_receives_events(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            plugin_path = d / "log_recorder.py"
            plugin_path.write_text(PLUGIN_SOURCE, encoding="utf-8")

            with patch.object(self._dp, "plugins_dir", return_value=d):
                loaded = self._dp.discover_and_load()

            self.assertIn("log_recorder", loaded)
            # Reach into the loaded module to grab its RECEIVED list.
            mod = sys.modules["doxyedit_plugin_log_recorder"]

            # Fire two events; both should be captured.
            self._dp.emit("project_loaded", None, "/tmp/test.doxy")
            self._dp.emit("post_pushed", None, "bluesky", True, "ok")

            self.assertEqual(len(mod.RECEIVED), 2)
            self.assertEqual(mod.RECEIVED[0],
                             ("project_loaded", "/tmp/test.doxy"))
            self.assertEqual(mod.RECEIVED[1],
                             ("post_pushed", "bluesky", True))

    def test_underscore_plugin_skipped(self):
        """Files starting with _ are skipped (reserved for internals)."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "_skip_me.py").write_text(
                "raise RuntimeError('would have failed if loaded')",
                encoding="utf-8")

            with patch.object(self._dp, "plugins_dir", return_value=d):
                loaded = self._dp.discover_and_load()

            self.assertEqual(loaded, [])
            self.assertEqual(self._dp._REGISTRY._failed, set())

    def test_failed_plugin_is_recorded(self):
        """A plugin whose register() raises gets logged + disabled."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "broken.py").write_text(
                "def register(api):\n    raise RuntimeError('boom')\n",
                encoding="utf-8")

            with patch.object(self._dp, "plugins_dir", return_value=d):
                loaded = self._dp.discover_and_load()

            self.assertEqual(loaded, [])
            self.assertIn("broken", self._dp._REGISTRY._failed)

    def test_disabled_plugin_skipped_during_load(self):
        """A plugin name listed in the disabled set is recognized by
        all_plugin_names() but never imported by discover_and_load()."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "alpha.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
            (d / "beta.py").write_text(PLUGIN_SOURCE, encoding="utf-8")

            with patch.object(self._dp, "plugins_dir", return_value=d), \
                    patch.object(self._dp, "_disabled_plugins",
                                 return_value={"beta"}):
                names = self._dp._REGISTRY.all_plugin_names()
                loaded = self._dp.discover_and_load()

            self.assertEqual(set(names), {"alpha", "beta"})
            self.assertEqual(loaded, ["alpha"])

    def test_all_six_lifecycle_events_emit_to_handlers(self):
        """End-to-end: a plugin subscribes to all six events; emit
        each one with realistic payload; verify each handler ran with
        the right args. Regression guard for the event surface
        (project_loaded, post_pushed, asset_imported, tag_changed,
        post_saved, shutdown). If a future refactor changes the
        signatures, this test pins them down."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "all_events.py").write_text(
                "RECEIVED = []\n"
                "def register(api):\n"
                "    api.on('project_loaded', lambda p, path: "
                "RECEIVED.append(('project_loaded', path)))\n"
                "    api.on('post_pushed', lambda post, plat, ok, det: "
                "RECEIVED.append(('post_pushed', plat, ok)))\n"
                "    api.on('asset_imported', lambda asset: "
                "RECEIVED.append(('asset_imported', asset)))\n"
                "    api.on('tag_changed', lambda tid, before, after: "
                "RECEIVED.append(('tag_changed', tid)))\n"
                "    api.on('post_saved', lambda post, is_new: "
                "RECEIVED.append(('post_saved', is_new)))\n"
                "    api.on('shutdown', lambda: "
                "RECEIVED.append(('shutdown',)))\n",
                encoding="utf-8")
            with patch.object(self._dp, "plugins_dir", return_value=d):
                self._dp.discover_and_load()

            mod = sys.modules["doxyedit_plugin_all_events"]

            # Fire each event with sensible args.
            self._dp.emit("project_loaded", None, "/tmp/x.doxy")
            self._dp.emit("post_pushed", None, "bluesky", True, "ok")
            self._dp.emit("asset_imported", "asset_obj")
            self._dp.emit("tag_changed", "char", {}, {"label": "Char"})
            self._dp.emit("post_saved", None, True)
            self._dp.emit("shutdown")

            received = mod.RECEIVED
            self.assertEqual(len(received), 6)
            self.assertEqual(received[0], ("project_loaded", "/tmp/x.doxy"))
            self.assertEqual(received[1], ("post_pushed", "bluesky", True))
            self.assertEqual(received[2], ("asset_imported", "asset_obj"))
            self.assertEqual(received[3], ("tag_changed", "char"))
            self.assertEqual(received[4], ("post_saved", True))
            self.assertEqual(received[5], ("shutdown",))


if __name__ == "__main__":
    unittest.main()
