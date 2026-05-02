"""exporter.export_project — end-to-end batch export. Pin manifest
shape, skip/error categorization, output filename layout, and the
sidecar manifest.json the CLI consumes."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _png_at(path: str, size=(200, 200)):
    Image.new("RGB", size, (10, 20, 30)).save(path, "PNG")


class TestExportProjectEndToEnd(unittest.TestCase):
    def test_no_assignments_writes_empty_manifest(self):
        from doxyedit.exporter import export_project
        from doxyedit.models import Project, Asset
        with tempfile.TemporaryDirectory() as td:
            p = Project()
            p.assets = [Asset(id="a1")]
            manifest = export_project(p, td)
            self.assertEqual(manifest["exports"], [])
            self.assertEqual(manifest["skipped"], [])
            self.assertEqual(manifest["errors"], [])
            # manifest sidecar always written.
            self.assertTrue((Path(td) / "export_manifest.json").exists())

    def test_skip_status_added_to_skipped(self):
        from doxyedit.exporter import export_project
        from doxyedit.models import Project, Asset, PlatformAssignment, PostStatus, PLATFORMS
        plat_id = next(iter(PLATFORMS))
        with tempfile.TemporaryDirectory() as td:
            p = Project()
            p.assets = [Asset(id="a1", source_path="/nope/x.png",
                               assignments=[PlatformAssignment(
                                   platform=plat_id, slot="x",
                                   status=PostStatus.SKIP)])]
            manifest = export_project(p, td)
            self.assertEqual(len(manifest["skipped"]), 1)
            self.assertEqual(manifest["skipped"][0]["asset"], "a1")

    def test_missing_source_recorded_as_error(self):
        """Asset with non-skip assignment but missing source file →
        captured under 'errors' with the asset id, not silently dropped."""
        from doxyedit.exporter import export_project
        from doxyedit.models import (Project, Asset, PlatformAssignment,
                                      PLATFORMS)
        plat_id = next(p_id for p_id, plat in PLATFORMS.items() if plat.slots)
        plat = PLATFORMS[plat_id]
        with tempfile.TemporaryDirectory() as td:
            p = Project()
            p.assets = [Asset(id="a1", source_path="/nope/missing.png",
                              assignments=[PlatformAssignment(
                                  platform=plat_id, slot=plat.slots[0].name)])]
            manifest = export_project(p, td)
            self.assertEqual(len(manifest["errors"]), 1)
            self.assertEqual(manifest["errors"][0]["asset"], "a1")

    def test_successful_export_writes_png_and_manifest_entry(self):
        from doxyedit.exporter import export_project
        from doxyedit.models import (Project, Asset, PlatformAssignment,
                                      PLATFORMS)
        # Pick a platform with at least one non-censor slot
        plat_id, plat = next((pid, p) for pid, p in PLATFORMS.items()
                             if p.slots and not p.needs_censor)
        slot = plat.slots[0]
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.png"
            _png_at(str(src))
            p = Project()
            p.assets = [Asset(id="a1", source_path=str(src),
                              assignments=[PlatformAssignment(
                                  platform=plat_id, slot=slot.name)])]
            manifest = export_project(p, td)
            self.assertEqual(len(manifest["exports"]), 1)
            export = manifest["exports"][0]
            # Output file actually exists.
            self.assertTrue(Path(export["file"]).exists())
            # Filename layout: platform_dir / prefix_slotname.png
            self.assertEqual(Path(export["file"]).suffix, ".png")
            self.assertIn(slot.name, Path(export["file"]).name)

    def test_manifest_sidecar_is_valid_json(self):
        from doxyedit.exporter import export_project
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            export_project(Project(), td)
            manifest_path = Path(td) / "export_manifest.json"
            data = json.loads(manifest_path.read_text())
            for k in ("project", "exports", "skipped", "errors"):
                self.assertIn(k, data)


if __name__ == "__main__":
    unittest.main()
