"""crossproject.detect_conflicts — surfaces scheduling conflicts
across projects + blackout windows. Pin the four conflict_types the
UI relies on: same_platform_same_day, same_day, blackout, saturation.
A regression mis-categorizes warnings and the user trusts wrong info."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _post(**kw):
    from doxyedit.models import SocialPost
    return SocialPost(**({"id": "p1", "scheduled_time": "2026-04-15T10:00",
                          "platforms": ["bluesky"]} | kw))


def _other(day, project_name, platforms, path="/x.doxy"):
    return {"id": "o1", "scheduled_time": f"{day}T12:00",
            "status": "queued", "platforms": platforms,
            "caption_preview": "", "project_name": project_name,
            "project_path": path}


class TestDetectConflicts(unittest.TestCase):
    def test_no_conflicts_returns_empty(self):
        from doxyedit.crossproject import detect_conflicts
        self.assertEqual(detect_conflicts([_post()], [], []), [])

    def test_no_scheduled_time_skipped(self):
        from doxyedit.crossproject import detect_conflicts
        out = detect_conflicts([_post(scheduled_time="")], [
            _other("2026-04-15", "Other", ["bluesky"])
        ])
        self.assertEqual(out, [])

    def test_same_platform_same_day_yields_warning(self):
        from doxyedit.crossproject import detect_conflicts
        out = detect_conflicts(
            [_post(platforms=["bluesky", "x"])],
            [_other("2026-04-15", "OtherProj", ["bluesky"])],
        )
        types = {w.conflict_type for w in out}
        self.assertIn("same_platform_same_day", types)
        # Severity must be warning (not info) when platforms overlap.
        same_plat = [w for w in out if w.conflict_type == "same_platform_same_day"]
        self.assertEqual(same_plat[0].severity, "warning")

    def test_same_day_different_platform_is_info(self):
        from doxyedit.crossproject import detect_conflicts
        out = detect_conflicts(
            [_post(platforms=["bluesky"])],
            [_other("2026-04-15", "OtherProj", ["telegram"])],
        )
        types = [w.conflict_type for w in out]
        self.assertIn("same_day", types)
        same_day = [w for w in out if w.conflict_type == "same_day"]
        self.assertEqual(same_day[0].severity, "info")

    def test_blackout_yields_conflict_severity(self):
        from doxyedit.crossproject import detect_conflicts
        out = detect_conflicts(
            [_post(scheduled_time="2026-04-02T10:00")],
            [],
            [{"start": "2026-04-01", "end": "2026-04-05", "label": "AX"}],
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].conflict_type, "blackout")
        self.assertEqual(out[0].severity, "conflict")
        self.assertIn("AX", out[0].message)

    def test_blackout_outside_range_no_conflict(self):
        from doxyedit.crossproject import detect_conflicts
        out = detect_conflicts(
            [_post(scheduled_time="2026-05-01T10:00")],
            [],
            [{"start": "2026-04-01", "end": "2026-04-05", "label": "AX"}],
        )
        self.assertEqual(out, [])

    def test_saturation_warning_when_more_than_3_posts(self):
        from doxyedit.crossproject import detect_conflicts
        out = detect_conflicts(
            [_post()],
            [
                _other("2026-04-15", "P1", []),
                _other("2026-04-15", "P2", []),
                _other("2026-04-15", "P3", []),
            ],
        )
        types = [w.conflict_type for w in out]
        self.assertIn("saturation", types)

    def test_no_saturation_at_three_posts(self):
        """Threshold is >3, so exactly 3 (current + 2 others) shouldn't
        trip saturation."""
        from doxyedit.crossproject import detect_conflicts
        out = detect_conflicts(
            [_post()],
            [
                _other("2026-04-15", "P1", []),
                _other("2026-04-15", "P2", []),
            ],
        )
        types = [w.conflict_type for w in out]
        self.assertNotIn("saturation", types)


if __name__ == "__main__":
    unittest.main()
