"""pipeline.check_readiness — traffic-light readiness check the
Health panel shows for every asset/platform combination. The user
relies on these statuses to decide what to fix before exporting,
so a regression silently green-lights broken assets."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _real_file() -> str:
    """Return a path to a temp file that exists for the test duration."""
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    f.close()
    return f.name


class TestCheckReadiness(unittest.TestCase):
    def setUp(self):
        self._tmp = _real_file()

    def tearDown(self):
        try:
            Path(self._tmp).unlink()
        except OSError:
            pass

    def test_unknown_platform_red(self):
        from doxyedit.pipeline import check_readiness
        from doxyedit.models import Asset
        a = Asset(id="a1", source_path=self._tmp)
        out = check_readiness(a, "fictional_platform_xyz")
        self.assertEqual(out["status"], "red")
        self.assertIn("Unknown platform", out["issues"][0])

    def test_missing_source_file_red(self):
        from doxyedit.pipeline import check_readiness
        from doxyedit.models import Asset, PLATFORMS
        plat = next(iter(PLATFORMS))
        a = Asset(id="a1", source_path="/nonexistent/missing.png")
        out = check_readiness(a, plat)
        self.assertEqual(out["status"], "red")

    def test_no_crop_no_overlay_yields_auto_fit_yellow(self):
        from doxyedit.pipeline import check_readiness
        from doxyedit.models import Asset, PLATFORMS
        plat_id = next(p for p, pl in PLATFORMS.items() if not pl.needs_censor)
        a = Asset(id="a1", source_path=self._tmp)
        out = check_readiness(a, plat_id)
        # crop is auto-fit (yellow trigger)
        self.assertEqual(out["crop"], "auto-fit")
        self.assertEqual(out["status"], "yellow")

    def test_explicit_crop_green(self):
        from doxyedit.pipeline import check_readiness
        from doxyedit.models import Asset, CropRegion, PLATFORMS
        plat_id = next(p for p, pl in PLATFORMS.items() if not pl.needs_censor)
        a = Asset(id="a1", source_path=self._tmp,
                  crops=[CropRegion(label=plat_id, x=0, y=0, w=100, h=100)])
        out = check_readiness(a, plat_id)
        self.assertEqual(out["crop"], "explicit")
        self.assertEqual(out["status"], "green")

    def test_censor_required_but_missing_red(self):
        from doxyedit.pipeline import check_readiness
        from doxyedit.models import Asset, CropRegion, PLATFORMS
        # Find a platform that needs censor.
        plat_id = next((p for p, pl in PLATFORMS.items() if pl.needs_censor),
                       None)
        if plat_id is None:
            self.skipTest("no censor-requiring platform configured")
        a = Asset(id="a1", source_path=self._tmp,
                  crops=[CropRegion(label=plat_id, x=0, y=0, w=100, h=100)])
        out = check_readiness(a, plat_id)
        self.assertEqual(out["censor"], "missing")
        self.assertEqual(out["status"], "red")

    def test_overlay_present_marks_present(self):
        from doxyedit.pipeline import check_readiness
        from doxyedit.models import Asset, CropRegion, CanvasOverlay, PLATFORMS
        plat_id = next(p for p, pl in PLATFORMS.items() if not pl.needs_censor)
        a = Asset(id="a1", source_path=self._tmp,
                  crops=[CropRegion(label=plat_id, x=0, y=0, w=100, h=100)],
                  overlays=[CanvasOverlay(type="logo", x=0, y=0)])
        out = check_readiness(a, plat_id)
        self.assertEqual(out["overlay"], "present")

    def test_assignment_crop_counts_as_explicit(self):
        from doxyedit.pipeline import check_readiness
        from doxyedit.models import (Asset, CropRegion, PlatformAssignment,
                                      PLATFORMS)
        plat_id = next(p for p, pl in PLATFORMS.items() if not pl.needs_censor)
        a = Asset(id="a1", source_path=self._tmp,
                  assignments=[PlatformAssignment(
                      platform=plat_id,
                      crop=CropRegion(x=0, y=0, w=100, h=100))])
        out = check_readiness(a, plat_id)
        self.assertEqual(out["crop"], "explicit")


if __name__ == "__main__":
    unittest.main()
