"""Round-trip tests for the smaller dataclasses' to_dict/from_dict
methods that aren't otherwise covered by test_models.py. These run
on every project save/load — silent regression mangles user data."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestCanvasOverlay(unittest.TestCase):
    def test_round_trip(self):
        from doxyedit.models import CanvasOverlay
        ov = CanvasOverlay(type="text", x=10, y=20, scale=1.5,
                            opacity=0.8, enabled=True, position="center",
                            text="hello")
        d = ov.to_dict()
        ov2 = CanvasOverlay.from_dict(d)
        self.assertEqual(ov.type, ov2.type)
        self.assertEqual(ov.x, ov2.x)
        self.assertEqual(ov.opacity, ov2.opacity)
        self.assertEqual(ov.text, ov2.text)

    def test_from_dict_ignores_unknown_keys(self):
        """Forward-compat: a project saved by a newer DoxyEdit version
        with extra fields must not crash from_dict on an older version."""
        from doxyedit.models import CanvasOverlay
        ov = CanvasOverlay.from_dict({
            "type": "logo", "x": 0, "y": 0,
            "future_field_we_dont_know": 99,
        })
        self.assertEqual(ov.type, "logo")


class TestReleaseStep(unittest.TestCase):
    def test_round_trip(self):
        from doxyedit.models import ReleaseStep
        step = ReleaseStep(platform="bluesky", delay_hours=24,
                           account_id="acct_main", caption_key="bsky",
                           status="posted", posted_at="2026-04-15T10:00",
                           tier_level="premium", locale="en")
        d = step.to_dict()
        step2 = ReleaseStep.from_dict(d)
        self.assertEqual(step.platform, step2.platform)
        self.assertEqual(step.delay_hours, step2.delay_hours)
        self.assertEqual(step.status, step2.status)
        self.assertEqual(step.posted_at, step2.posted_at)
        self.assertEqual(step.tier_level, step2.tier_level)

    def test_defaults_round_trip(self):
        from doxyedit.models import ReleaseStep
        d = ReleaseStep().to_dict()
        # All fields present in the saved form so future loads have them.
        for k in ("platform", "delay_hours", "account_id", "caption_key",
                  "status", "posted_at", "tier_level", "locale"):
            self.assertIn(k, d)


class TestEngagementWindow(unittest.TestCase):
    def test_round_trip(self):
        from doxyedit.models import EngagementWindow
        ew = EngagementWindow(post_id="p1", platform="bluesky",
                              account_id="acct", check_at="2026-04-15T11:00",
                              action="peak_engagement",
                              url="https://bsky.app/x", done=False,
                              notes="check replies")
        ew2 = EngagementWindow.from_dict(ew.to_dict())
        self.assertEqual(ew.post_id, ew2.post_id)
        self.assertEqual(ew.action, ew2.action)
        self.assertEqual(ew.done, ew2.done)
        self.assertEqual(ew.notes, ew2.notes)


class TestAssetCycleStar(unittest.TestCase):
    """Asset.cycle_star bumps the star value through 0..5 then wraps."""

    def test_increments(self):
        from doxyedit.models import Asset
        a = Asset(starred=0)
        for expected in (1, 2, 3, 4, 5):
            a.cycle_star()
            self.assertEqual(a.starred, expected)

    def test_wraps_at_5(self):
        from doxyedit.models import Asset
        a = Asset(starred=5)
        a.cycle_star()
        self.assertEqual(a.starred, 0)


if __name__ == "__main__":
    unittest.main()
