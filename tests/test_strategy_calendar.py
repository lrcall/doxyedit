"""strategy._section_calendar_context — analyzes nearby posts and
weekly fill-rate to produce a calendar-context block. Pin the
"no scheduled time", "nearby posts", and gap-recommendation
branches so a refactor doesn't drop the recommendations the user
relies on for pacing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _post(**kw):
    from doxyedit.models import SocialPost
    return SocialPost(**({"id": "p_main",
                          "scheduled_time": "2026-04-15T10:00",
                          "platforms": ["bluesky"]} | kw))


def _project(posts):
    from doxyedit.models import Project
    p = Project()
    p.posts = list(posts)
    return p


class TestSectionCalendarContext(unittest.TestCase):
    def test_no_scheduled_time_short_circuits(self):
        from doxyedit.strategy import _section_calendar_context
        from doxyedit.models import Project, SocialPost
        out = _section_calendar_context(SocialPost(id="x"), Project())
        self.assertIn("## Calendar Context", out)
        self.assertIn("No scheduled time set", out)

    def test_nearby_posts_listed(self):
        from doxyedit.strategy import _section_calendar_context
        main = _post()
        # Within +- 3 days
        nearby = _post(id="p2", scheduled_time="2026-04-14T12:00",
                       platforms=["telegram"])
        out = _section_calendar_context(main, _project([main, nearby]))
        self.assertIn("Nearby posts", out)
        self.assertIn("telegram", out)

    def test_far_posts_excluded_from_nearby(self):
        from doxyedit.strategy import _section_calendar_context
        main = _post()
        # 5 days away — outside the ±3 day window
        far = _post(id="p2", scheduled_time="2026-04-20T12:00",
                    platforms=["telegram"])
        out = _section_calendar_context(main, _project([main, far]))
        self.assertIn("None within", out)

    def test_excludes_self_from_nearby(self):
        """The current post must not list itself as a nearby post —
        otherwise every post looks like it has a neighbor."""
        from doxyedit.strategy import _section_calendar_context
        main = _post()
        out = _section_calendar_context(main, _project([main]))
        self.assertIn("None within", out)

    def test_lots_of_gaps_recommendation(self):
        from doxyedit.strategy import _section_calendar_context
        # Only the main post in the week → 6 gaps
        out = _section_calendar_context(_post(),
                                        _project([_post()]))
        self.assertIn("good time to post", out)

    def test_full_week_no_gaps_recommendation(self):
        """When 7+ posts already cover the week, the function may
        recommend skipping or moving — at minimum it must report 0/1
        gaps and not suggest "good time to post"."""
        from doxyedit.strategy import _section_calendar_context
        from doxyedit.models import SocialPost
        # 7 posts on consecutive days that week (Mon-Sun)
        posts = [SocialPost(id=f"p{i}",
                            scheduled_time=f"2026-04-{13+i:02d}T10:00")
                 for i in range(7)]  # Apr 13 (Mon) → Apr 19 (Sun)
        # Add the main post on Apr 15 (already in posts)
        main = posts[2]  # Apr 15
        out = _section_calendar_context(main, _project(posts))
        self.assertNotIn("good time to post", out)


if __name__ == "__main__":
    unittest.main()
