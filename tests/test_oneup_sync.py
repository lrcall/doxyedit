"""decide_sync_actions - pure D2 reconciliation logic for OneUp sync.

D2 semantics under test:
- Local posts match remote entries by stored oneup_post_id ONLY.
- Missing-from-remote leaves status unchanged (no DRAFT reset, no
  oneup_post_id clearing).
- published -> set_posted, failed -> set_failed, scheduled -> no action.
- Posts with no oneup_post_id are untouched by sync.
- Identical captions on two posts can never cross-match (the old
  caption-fingerprint bug).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _post(pid: str, *, status="queued", oneup_id="", caption="",
          engagement=None):
    from doxyedit.models import SocialPost
    return SocialPost(
        id=pid,
        status=status,
        oneup_post_id=oneup_id,
        caption_default=caption,
        engagement_checks=list(engagement or []),
    )


class TestDecideSyncActions(unittest.TestCase):
    def _decide(self, posts, remote):
        from doxyedit.oneup_sync import decide_sync_actions
        return decide_sync_actions(posts, remote)

    def _actions_by_id(self, posts, remote):
        return {a.post_id: a for a in self._decide(posts, remote)}

    # -- table: single-id core transitions ---------------------------

    def test_core_transition_table(self):
        from doxyedit.oneup_sync import (
            ACTION_SET_FAILED, ACTION_SET_POSTED)
        table = [
            # (remote status for the post's id, expected action or None)
            ("published", ACTION_SET_POSTED),
            ("failed", ACTION_SET_FAILED),
            ("scheduled", None),
        ]
        for remote_status, expected in table:
            with self.subTest(remote=remote_status):
                post = _post("p1", oneup_id="111")
                actions = self._decide([post], {"111": remote_status})
                if expected is None:
                    self.assertEqual(actions, [])
                else:
                    self.assertEqual(len(actions), 1)
                    self.assertEqual(actions[0].post_id, "p1")
                    self.assertEqual(actions[0].action, expected)
                # Pure function: the post itself is never mutated.
                self.assertEqual(post.status, "queued")
                self.assertEqual(post.oneup_post_id, "111")

    def test_published_sets_needs_engagement_only_when_empty(self):
        no_checks = _post("p1", oneup_id="111")
        has_checks = _post("p2", oneup_id="222",
                           engagement=[{"when": "later"}])
        acts = self._actions_by_id(
            [no_checks, has_checks],
            {"111": "published", "222": "published"})
        self.assertTrue(acts["p1"].needs_engagement)
        self.assertFalse(acts["p2"].needs_engagement)

    # -- D2: missing from remote keeps status ------------------------

    def test_missing_from_remote_keeps_status(self):
        # Old behavior reset the post to DRAFT and wiped oneup_post_id.
        # D2: leave it exactly as it is.
        post = _post("p1", oneup_id="999")
        actions = self._decide([post], {"111": "published"})
        self.assertEqual(actions, [])
        self.assertEqual(post.status, "queued")
        self.assertEqual(post.oneup_post_id, "999")

    def test_sentinel_synced_id_never_matches(self):
        # Legacy sentinel value from the old fingerprint sync - it is
        # not a real remote id, so the post stays untouched.
        post = _post("p1", oneup_id="synced")
        self.assertEqual(self._decide([post], {"111": "failed"}), [])

    # -- D2: no oneup_post_id means untouched ------------------------

    def test_no_id_untouched(self):
        # Even if remote has entries, an unpushed post gets no action
        # (no push action, no state change).
        post = _post("p1", oneup_id="", caption="hello world")
        actions = self._decide([post], {"111": "published",
                                        "222": "failed"})
        self.assertEqual(actions, [])

    # -- the old caption-fingerprint bug -----------------------------

    def test_identical_captions_never_cross_match(self):
        # Two posts with byte-identical captions. Only post A's id is
        # published on remote; post B must NOT ride along (the old
        # fingerprint matcher marked both).
        cap = "Same caption text for both posts, first 40 chars match"
        a = _post("a", oneup_id="111", caption=cap)
        b = _post("b", oneup_id="222", caption=cap)
        acts = self._actions_by_id([a, b], {"111": "published"})
        self.assertIn("a", acts)
        self.assertNotIn("b", acts)

    def test_identical_captions_unpushed_twin_untouched(self):
        # Same-caption twin with NO oneup_post_id must not inherit the
        # pushed twin's remote status either.
        cap = "Same caption text again"
        a = _post("a", oneup_id="111", caption=cap)
        b = _post("b", oneup_id="", caption=cap)
        acts = self._actions_by_id([a, b], {"111": "failed"})
        self.assertIn("a", acts)
        self.assertNotIn("b", acts)

    # -- empties ------------------------------------------------------

    def test_empty_remote(self):
        posts = [_post("p1", oneup_id="111"), _post("p2", oneup_id="")]
        self.assertEqual(self._decide(posts, {}), [])

    def test_empty_local(self):
        self.assertEqual(self._decide([], {"111": "published"}), [])

    def test_both_empty(self):
        self.assertEqual(self._decide([], {}), [])

    # -- only queued posts are considered ----------------------------

    def test_non_queued_posts_skipped(self):
        for status in ("draft", "posted", "failed", "partial"):
            with self.subTest(status=status):
                post = _post("p1", status=status, oneup_id="111")
                self.assertEqual(
                    self._decide([post], {"111": "published"}), [])

    def test_enum_status_accepted(self):
        from doxyedit.models import SocialPostStatus
        from doxyedit.oneup_sync import ACTION_SET_POSTED
        post = _post("p1", status=SocialPostStatus.QUEUED,
                     oneup_id="111")
        actions = self._decide([post], {"111": "published"})
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, ACTION_SET_POSTED)

    # -- multi-id posts (comma-separated oneup_post_id) ---------------

    def test_multi_id_all_published(self):
        from doxyedit.oneup_sync import ACTION_SET_POSTED
        post = _post("p1", oneup_id="111,222,333")
        actions = self._decide(
            [post],
            {"111": "published", "222": "published", "333": "published"})
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, ACTION_SET_POSTED)

    def test_multi_id_any_failed_wins(self):
        from doxyedit.oneup_sync import ACTION_SET_FAILED
        post = _post("p1", oneup_id="111,222")
        actions = self._decide(
            [post], {"111": "published", "222": "failed"})
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, ACTION_SET_FAILED)

    def test_multi_id_partial_publish_waits(self):
        # One id published, one still scheduled: not done yet, no
        # action (stays queued).
        post = _post("p1", oneup_id="111,222")
        self.assertEqual(
            self._decide([post],
                         {"111": "published", "222": "scheduled"}), [])

    def test_multi_id_partial_missing_waits(self):
        # One id published, one absent from remote: conservative, no
        # action (D2: missing never downgrades or completes anything).
        post = _post("p1", oneup_id="111,222")
        self.assertEqual(
            self._decide([post], {"111": "published"}), [])

    def test_multi_id_whitespace_and_empty_segments(self):
        from doxyedit.oneup_sync import ACTION_SET_POSTED
        post = _post("p1", oneup_id=" 111 ,,222, ")
        actions = self._decide(
            [post], {"111": "published", "222": "published"})
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, ACTION_SET_POSTED)

    # -- robustness ----------------------------------------------------

    def test_none_remote_state(self):
        post = _post("p1", oneup_id="111")
        self.assertEqual(self._decide([post], None), [])

    def test_action_order_follows_local_post_order(self):
        posts = [_post("a", oneup_id="1"), _post("b", oneup_id="2"),
                 _post("c", oneup_id="3")]
        remote = {"1": "failed", "2": "published", "3": "failed"}
        self.assertEqual([a.post_id for a in self._decide(posts, remote)],
                         ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
