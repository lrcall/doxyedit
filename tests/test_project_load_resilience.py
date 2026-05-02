"""Project.load — forward-compat key filtering on slots-based
dataclasses (Asset, CropRegion, CensorRegion). The loader filters
unknown JSON keys before calling __init__ so future extra fields
don't crash today's app. Pin so a refactor can't drop the filter."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _save_payload(td: Path, payload: dict) -> Path:
    p = td / "x.doxy"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestProjectLoadResilience(unittest.TestCase):
    def test_unknown_crop_field_filtered(self):
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "assets": [{
                    "id": "a1", "source_path": "x.png",
                    "crops": [
                        {"x": 0, "y": 0, "w": 100, "h": 100,
                         "label": "twitter",
                         "future_field_unknown": "ignored"},
                    ],
                }],
            }
            p = _save_payload(Path(td), payload)
            proj = Project.load(str(p))
            self.assertEqual(len(proj.assets[0].crops), 1)
            self.assertEqual(proj.assets[0].crops[0].label, "twitter")

    def test_unknown_censor_field_filtered(self):
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "assets": [{
                    "id": "a1", "source_path": "x.png",
                    "censors": [
                        {"x": 0, "y": 0, "w": 50, "h": 50,
                         "style": "black",
                         "added_in_v3": True},
                    ],
                }],
            }
            p = _save_payload(Path(td), payload)
            proj = Project.load(str(p))
            self.assertEqual(len(proj.assets[0].censors), 1)
            self.assertEqual(proj.assets[0].censors[0].style, "black")

    def test_unknown_top_level_keys_ignored(self):
        """Future top-level keys (e.g. 'experimental_xyz') must not
        crash Project.load."""
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "name": "T",
                "assets": [],
                "totally_made_up_future_section": {"a": 1},
            }
            p = _save_payload(Path(td), payload)
            proj = Project.load(str(p))
            self.assertEqual(proj.name, "T")

    def test_load_empty_assets_list(self):
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _save_payload(Path(td), {"assets": []})
            proj = Project.load(str(p))
            self.assertEqual(proj.assets, [])

    def test_load_missing_optional_fields_uses_defaults(self):
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "assets": [{"id": "a1", "source_path": "x.png"}],
            }
            p = _save_payload(Path(td), payload)
            proj = Project.load(str(p))
            a = proj.assets[0]
            self.assertEqual(a.tags, [])
            self.assertEqual(a.crops, [])
            self.assertEqual(a.censors, [])
            self.assertEqual(a.overlays, [])
            self.assertEqual(a.starred, 0)


if __name__ == "__main__":
    unittest.main()
