"""Project.from_dict — tag-alias resolution. When a project's
tag_aliases maps old_id → canonical_id, every asset's tag list gets
re-mapped on load. Pin so user-renamed tags (the canonical case for
aliases) keep working across save/load cycles."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _save_and_load(payload):
    """Write payload as a project file, load it, return the Project."""
    from doxyedit.models import Project
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.doxy"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return Project.load(str(p))


class TestTagAliasResolution(unittest.TestCase):
    def test_alias_remaps_asset_tag_on_load(self):
        from doxyedit.models import PostStatus
        proj = _save_and_load({
            "name": "T",
            "tag_aliases": {"old_marty": "marty"},
            "assets": [
                {"id": "a1", "source_path": "x.png",
                 "tags": ["old_marty", "color"]},
            ],
        })
        self.assertEqual(set(proj.assets[0].tags), {"marty", "color"})

    def test_alias_dedupes_when_canonical_already_present(self):
        """Asset has both old + new id. Load drops the duplicate."""
        proj = _save_and_load({
            "tag_aliases": {"old_marty": "marty"},
            "assets": [
                {"id": "a1", "source_path": "x.png",
                 "tags": ["old_marty", "marty", "color"]},
            ],
        })
        self.assertEqual(proj.assets[0].tags.count("marty"), 1)
        self.assertIn("color", proj.assets[0].tags)

    def test_no_aliases_pass_through(self):
        proj = _save_and_load({
            "assets": [
                {"id": "a1", "source_path": "x.png",
                 "tags": ["marty", "color"]},
            ],
        })
        self.assertEqual(set(proj.assets[0].tags), {"marty", "color"})

    def test_alias_chain_not_walked(self):
        """tag_aliases is a single-step lookup. If a→b→c, an asset
        tagged 'a' becomes 'b' (not 'c'). This is the documented
        behavior — chained renames need a re-save to fully collapse."""
        proj = _save_and_load({
            "tag_aliases": {"a": "b", "b": "c"},
            "assets": [{"id": "a1", "source_path": "x.png",
                        "tags": ["a"]}],
        })
        # Documented single-step behavior.
        self.assertIn("b", proj.assets[0].tags)
        self.assertNotIn("a", proj.assets[0].tags)


if __name__ == "__main__":
    unittest.main()
