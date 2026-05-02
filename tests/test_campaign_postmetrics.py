"""Campaign nested-milestone round-trip + PostMetrics defaults.

These dataclasses are saved into the project file as part of every
save and re-hydrated on every load. The Campaign nested-milestone
test catches a particularly easy regression: from_dict needs to
recursively rebuild milestones, not just store the raw dicts."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestCampaignMilestoneNesting(unittest.TestCase):
    def test_milestones_round_trip_as_objects(self):
        from doxyedit.models import Campaign, CampaignMilestone
        m1 = CampaignMilestone(id="m1", label="Page goes live",
                                due_date="2026-05-01", completed=False)
        m2 = CampaignMilestone(id="m2", label="Art finalized",
                                due_date="2026-04-15", completed=True,
                                notes="includes tier cards")
        c = Campaign(id="ks1", name="KS Vol 2", platform_id="kickstarter",
                     milestones=[m1, m2])
        d = c.to_dict()
        c2 = Campaign.from_dict(d)
        self.assertEqual(len(c2.milestones), 2)
        self.assertIsInstance(c2.milestones[0], CampaignMilestone)
        self.assertEqual(c2.milestones[0].id, "m1")
        self.assertEqual(c2.milestones[1].notes, "includes tier cards")
        self.assertTrue(c2.milestones[1].completed)

    def test_empty_milestones_default(self):
        from doxyedit.models import Campaign
        c = Campaign.from_dict({"id": "x"})
        self.assertEqual(c.milestones, [])

    def test_unknown_status_kept(self):
        """Save format may use status values future versions add. Don't
        validate / strip — pass them through so old DoxyEdit doesn't
        wipe the field."""
        from doxyedit.models import Campaign
        c = Campaign.from_dict({"id": "x", "status": "future_value"})
        self.assertEqual(c.status, "future_value")

    def test_default_status_is_planning(self):
        from doxyedit.models import Campaign
        c = Campaign.from_dict({"id": "x"})
        self.assertEqual(c.status, "planning")


class TestPostMetrics(unittest.TestCase):
    def test_round_trip(self):
        from doxyedit.models import PostMetrics
        m = PostMetrics(likes=100, retweets=20, replies=5, views=1000,
                         clicks=42, last_checked="2026-04-15T10:00")
        m2 = PostMetrics.from_dict(m.to_dict())
        self.assertEqual(m.likes, m2.likes)
        self.assertEqual(m.retweets, m2.retweets)
        self.assertEqual(m.last_checked, m2.last_checked)

    def test_defaults_when_keys_missing(self):
        from doxyedit.models import PostMetrics
        m = PostMetrics.from_dict({})
        self.assertEqual(m.likes, 0)
        self.assertEqual(m.last_checked, "")

    def test_partial_dict_fills_with_defaults(self):
        from doxyedit.models import PostMetrics
        m = PostMetrics.from_dict({"likes": 50})
        self.assertEqual(m.likes, 50)
        self.assertEqual(m.retweets, 0)
        self.assertEqual(m.replies, 0)


if __name__ == "__main__":
    unittest.main()
