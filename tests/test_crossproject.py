"""crossproject.py — registry I/O + peek helpers used by the
schedule-coordination dialog. Tests use a tempdir-monkeypatched
_REGISTRY_PATH so they don't touch the user's real ~/.doxyedit."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _RegFixture:
    """Patch the module-level registry path to a tempdir for the test."""
    def __enter__(self):
        from doxyedit import crossproject
        self._td = tempfile.TemporaryDirectory()
        self._dir = Path(self._td.name)
        self._mod = crossproject
        self._patches = [
            patch.object(crossproject, "_REGISTRY_DIR", self._dir),
            patch.object(crossproject, "_REGISTRY_PATH",
                         self._dir / "project_registry.json"),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *args):
        for p in reversed(self._patches):
            p.stop()
        self._td.cleanup()


class TestRegistry(unittest.TestCase):
    def test_load_missing_returns_skeleton(self):
        with _RegFixture() as f:
            reg = f._mod.load_registry()
            self.assertEqual(reg, {"projects": [], "groups": {}})

    def test_load_corrupt_returns_skeleton(self):
        with _RegFixture() as f:
            (f._dir / "project_registry.json").write_text("not json")
            reg = f._mod.load_registry()
            self.assertEqual(reg["projects"], [])

    def test_save_then_load_roundtrip(self):
        with _RegFixture() as f:
            data = {"projects": [{"path": "/x.doxy", "alias": "x",
                                  "group": "", "enabled": True}],
                    "groups": {"g1": {"members": []}}}
            f._mod.save_registry(data)
            self.assertEqual(f._mod.load_registry(), data)

    def test_register_project_adds_new(self):
        with _RegFixture() as f:
            f._mod.register_project("/p.doxy", alias="P", group="A")
            reg = f._mod.load_registry()
            self.assertEqual(len(reg["projects"]), 1)
            entry = reg["projects"][0]
            self.assertEqual(entry["path"], "/p.doxy")
            self.assertEqual(entry["alias"], "P")
            self.assertEqual(entry["group"], "A")

    def test_register_project_updates_existing(self):
        with _RegFixture() as f:
            f._mod.register_project("/p.doxy", alias="A")
            f._mod.register_project("/p.doxy", alias="B", group="G2")
            reg = f._mod.load_registry()
            self.assertEqual(len(reg["projects"]), 1)
            self.assertEqual(reg["projects"][0]["alias"], "B")
            self.assertEqual(reg["projects"][0]["group"], "G2")

    def test_register_project_default_alias_strips_doxyproj(self):
        with _RegFixture() as f:
            f._mod.register_project("/path/to/art.doxyproj.json")
            reg = f._mod.load_registry()
            # Path.stem strips one extension; the function then strips ".doxyproj"
            self.assertEqual(reg["projects"][0]["alias"], "art")


class TestPeek(unittest.TestCase):
    def test_peek_schedule_returns_summary(self):
        from doxyedit.crossproject import peek_project_schedule
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.doxy"
            p.write_text(json.dumps({
                "name": "MyProj",
                "posts": [
                    {"id": "p1", "scheduled_time": "2026-04-15T10:00",
                     "status": "queued", "platforms": ["bluesky"],
                     "caption_default": "Hello world " * 10},
                ],
            }), encoding="utf-8")
            out = peek_project_schedule(str(p))
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["id"], "p1")
            self.assertEqual(out[0]["project_name"], "MyProj")
            self.assertEqual(out[0]["project_path"], str(p))
            self.assertLessEqual(len(out[0]["caption_preview"]), 60)

    def test_peek_schedule_handles_missing_file(self):
        from doxyedit.crossproject import peek_project_schedule
        self.assertEqual(peek_project_schedule("/nonexistent/path.doxy"), [])

    def test_peek_schedule_handles_corrupt_json(self):
        from doxyedit.crossproject import peek_project_schedule
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.doxy"
            p.write_text("not json", encoding="utf-8")
            self.assertEqual(peek_project_schedule(str(p)), [])

    def test_peek_blackouts_returns_list(self):
        from doxyedit.crossproject import peek_project_blackouts
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.doxy"
            p.write_text(json.dumps({
                "blackout_periods": [
                    {"start": "2026-04-01", "end": "2026-04-03",
                     "label": "AX", "scope": "all"},
                ],
            }), encoding="utf-8")
            out = peek_project_blackouts(str(p))
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["label"], "AX")

    def test_peek_blackouts_empty_when_missing_key(self):
        from doxyedit.crossproject import peek_project_blackouts
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.doxy"
            p.write_text(json.dumps({"name": "x"}), encoding="utf-8")
            self.assertEqual(peek_project_blackouts(str(p)), [])


if __name__ == "__main__":
    unittest.main()
