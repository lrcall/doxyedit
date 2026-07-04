"""Composer save parity - every SocialPost dataclass field must be
accounted for by the composer save path, so a new field can never be
silently reverted by _save() again.

Two layers:
  1. Static parity: composer.py declares three named frozensets
     (COMPOSER_UI_FIELDS, COMPOSER_DIRECT_FIELDS,
     COMPOSER_PRESERVED_FIELDS) that must exactly partition
     SocialPost.__dataclass_fields__. Adding a SocialPost field
     without classifying it fails here. COMPOSER_UI_FIELDS is also
     cross-checked against the keys ContentPanel.get_post_data()
     actually returns.
  2. Behavior: apply_post_data() (the dict-merge used by _save)
     is exercised without any GUI - it must update every UI field
     in place, coerce release_chain dicts to ReleaseStep, and leave
     pipeline-owned fields untouched even if a data dict names them.
"""
from __future__ import annotations

import inspect
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# Type-appropriate sentinel value per UI-owned field. Keys must match
# composer.COMPOSER_UI_FIELDS exactly (guarded below) so that adding a
# new UI field forces an explicit sentinel here too.
UI_SENTINELS = {
    "platforms": ["twitter", "bluesky"],
    "caption_default": "parity default caption",
    "captions": {"twitter": "parity twitter caption"},
    "links": ["https://example.com/parity"],
    "scheduled_time": "2026-07-04T12:34:00",
    "reply_templates": ["parity reply one", "parity reply two"],
    "strategy_notes": "parity strategy",
    "release_chain": [{"platform": "twitter", "delay_hours": 2}],
    "collection": "parity_identity",
    "identity_name": "parity_identity",
    "category_id": "86698",
    "censor_mode": "custom",
}


def _make_pipeline_post():
    """A SocialPost with every pipeline-owned field populated and
    UI fields set to old values, so both drift directions show."""
    from doxyedit.models import ReleaseStep, SocialPost
    return SocialPost(
        id="post_parity_1",
        asset_ids=["art_000_0"],
        platforms=["patreon"],
        captions={"patreon": "old caption"},
        caption_default="old default",
        links=["https://example.com/old"],
        scheduled_time="2026-01-01T00:00:00",
        status="draft",
        platform_status={"twitter": "posted_unverified"},
        oneup_post_id="12345,67890",
        reply_templates=["old reply"],
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        notes="pipeline notes",
        collection="old_collection",
        strategy_notes="old strategy",
        nsfw_platforms=["twitter"],
        sfw_asset_ids=["art_001_0"],
        tier_assets={"premium": ["art_002_0"]},
        sub_platform_status={"twitter": {"status": "posted",
                                         "posted_at": "2026-01-02"}},
        campaign_id="camp_1",
        category_id="176197",
        release_chain=[ReleaseStep(platform="patreon", delay_hours=0)],
        published_urls={"twitter": "https://x.com/x/status/1"},
        engagement_checks=[{"post_id": "post_parity_1"}],
        censor_mode="auto",
        platform_censor={"twitter": True},
        platform_metrics={"twitter": {"likes": 3}},
        identity_name="old_identity",
        posting_log=[{"ts": "2026-01-02T00:00:00", "platform": "twitter",
                      "action": "posted", "url": "", "detail": ""}],
    )


class TestStaticParity(unittest.TestCase):
    """The three ownership sets must exactly partition SocialPost."""

    def test_field_sets_partition_socialpost(self):
        from doxyedit import composer
        from doxyedit.models import SocialPost

        ui = composer.COMPOSER_UI_FIELDS
        direct = composer.COMPOSER_DIRECT_FIELDS
        preserved = composer.COMPOSER_PRESERVED_FIELDS
        all_fields = set(SocialPost.__dataclass_fields__)

        self.assertEqual(
            ui | direct | preserved, all_fields,
            "Every SocialPost dataclass field must be classified in "
            "exactly one composer ownership set. Unclassified: "
            f"{sorted(all_fields - (ui | direct | preserved))}; "
            f"stale: {sorted((ui | direct | preserved) - all_fields)}")
        self.assertFalse(ui & direct, f"overlap: {sorted(ui & direct)}")
        self.assertFalse(ui & preserved,
                         f"overlap: {sorted(ui & preserved)}")
        self.assertFalse(direct & preserved,
                         f"overlap: {sorted(direct & preserved)}")

    def test_ui_fields_match_get_post_data_keys(self):
        """COMPOSER_UI_FIELDS must mirror what get_post_data() returns.

        Static source check (no widget instantiation): extract the
        quoted keys of the dict literal in the final return statement
        of ContentPanel.get_post_data.
        """
        from doxyedit import composer
        from doxyedit.composer_right import ContentPanel
        from doxyedit.models import SocialPost

        src = inspect.getsource(ContentPanel.get_post_data)
        _, _, ret = src.rpartition("return {")
        self.assertTrue(ret, "get_post_data no longer ends in a dict "
                             "literal - update this parity test")
        keys = set(re.findall(r'"(\w+)"\s*:', ret))
        field_keys = keys & set(SocialPost.__dataclass_fields__)

        self.assertEqual(
            field_keys, set(composer.COMPOSER_UI_FIELDS),
            "get_post_data() and COMPOSER_UI_FIELDS drifted apart. "
            f"Returned but unclassified: "
            f"{sorted(field_keys - set(composer.COMPOSER_UI_FIELDS))}; "
            f"classified but not returned: "
            f"{sorted(set(composer.COMPOSER_UI_FIELDS) - field_keys)}")

    def test_sentinels_cover_ui_fields(self):
        from doxyedit import composer
        self.assertEqual(
            set(UI_SENTINELS), set(composer.COMPOSER_UI_FIELDS),
            "UI_SENTINELS in this test must provide a value for every "
            "COMPOSER_UI_FIELDS entry (and nothing else)")


class TestApplyPostData(unittest.TestCase):
    """apply_post_data() dict-merge behavior, GUI-free."""

    def test_every_ui_field_is_applied_in_place(self):
        from doxyedit.composer import apply_post_data
        from doxyedit.models import ReleaseStep

        post = _make_pipeline_post()
        result = apply_post_data(post, dict(UI_SENTINELS))

        self.assertIs(result, post,
                      "merge must mutate the live post in place - "
                      "timeline/window hold references to it")
        for field, expected in UI_SENTINELS.items():
            got = getattr(post, field)
            if field == "release_chain":
                self.assertTrue(
                    all(isinstance(s, ReleaseStep) for s in got),
                    "release_chain dicts must be coerced to ReleaseStep")
                self.assertEqual([s.platform for s in got], ["twitter"])
                self.assertEqual([s.delay_hours for s in got], [2])
            else:
                self.assertEqual(got, expected,
                                 f"UI field {field!r} was not applied "
                                 "by the composer save merge")

    def test_category_id_and_censor_mode_regression(self):
        """The original bug: get_post_data returned these but _save
        dropped them, silently reverting composer edits."""
        from doxyedit.composer import apply_post_data

        post = _make_pipeline_post()
        apply_post_data(post, {"category_id": "999", "censor_mode":
                               "uncensored"})
        self.assertEqual(post.category_id, "999")
        self.assertEqual(post.censor_mode, "uncensored")

    def test_direct_fields_flow_through(self):
        from doxyedit.composer import apply_post_data

        post = _make_pipeline_post()
        apply_post_data(post, {
            "asset_ids": ["art_009_0"],
            "status": "queued",
            "nsfw_platforms": ["bluesky"],
            "sfw_asset_ids": ["art_010_0"],
            "updated_at": "2026-07-04T13:00:00",
        })
        self.assertEqual(post.asset_ids, ["art_009_0"])
        self.assertEqual(post.status, "queued")
        self.assertEqual(post.nsfw_platforms, ["bluesky"])
        self.assertEqual(post.sfw_asset_ids, ["art_010_0"])
        self.assertEqual(post.updated_at, "2026-07-04T13:00:00")

    def test_pipeline_fields_are_never_written(self):
        from doxyedit import composer
        from doxyedit.composer import apply_post_data

        post = _make_pipeline_post()
        before = post.to_dict()

        # A hostile/buggy data dict naming every preserved field must
        # leave all of them untouched.
        attack = {f: "CLOBBERED" for f in
                  composer.COMPOSER_PRESERVED_FIELDS}
        attack.update(UI_SENTINELS)
        apply_post_data(post, attack)

        after = post.to_dict()
        for field in composer.COMPOSER_PRESERVED_FIELDS:
            self.assertEqual(
                after[field], before[field],
                f"pipeline-owned field {field!r} was overwritten by "
                "the composer save merge")

    def test_none_values_are_skipped(self):
        """identity_name (and any absent-widget key) arriving as None
        must not clobber the stored value."""
        from doxyedit.composer import apply_post_data

        post = _make_pipeline_post()
        apply_post_data(post, {"identity_name": None,
                               "caption_default": "kept edit"})
        self.assertEqual(post.identity_name, "old_identity")
        self.assertEqual(post.caption_default, "kept edit")

    def test_unknown_keys_ignored(self):
        from doxyedit.composer import apply_post_data

        post = _make_pipeline_post()
        apply_post_data(post, {"not_a_field": 123,
                               "caption_default": "still works"})
        self.assertEqual(post.caption_default, "still works")
        self.assertFalse(hasattr(post, "not_a_field"))

    def test_release_chain_accepts_existing_releasestep_objects(self):
        """Callers may hand ReleaseStep instances instead of raw
        dicts; both must survive the round-trip."""
        from doxyedit.composer import apply_post_data
        from doxyedit.models import ReleaseStep

        post = _make_pipeline_post()
        apply_post_data(post, {"release_chain": [
            ReleaseStep(platform="bluesky", delay_hours=6),
            {"platform": "mastodon", "delay_hours": 12},
        ]})
        self.assertEqual([s.platform for s in post.release_chain],
                         ["bluesky", "mastodon"])
        self.assertEqual([s.delay_hours for s in post.release_chain],
                         [6, 12])

    def test_absent_keys_preserve_existing_values(self):
        """A key not present in data (e.g. campaign_id, which
        get_post_data never returns) must keep the stored value."""
        from doxyedit.composer import apply_post_data

        post = _make_pipeline_post()
        apply_post_data(post, {"caption_default": "only this"})
        self.assertEqual(post.campaign_id, "camp_1")
        self.assertEqual(post.collection, "old_collection")
        self.assertEqual(post.scheduled_time, "2026-01-01T00:00:00")

    def test_new_post_construction_path(self):
        """The new-post branch of _save applies the same merge to a
        fresh SocialPost carrying only id/created_at."""
        from doxyedit.composer import apply_post_data
        from doxyedit.models import SocialPost

        fresh = SocialPost(id="new_1", created_at="2026-07-04T14:00:00")
        data = dict(UI_SENTINELS)
        data.update({
            "asset_ids": ["art_000_0"],
            "status": "draft",
            "nsfw_platforms": [],
            "sfw_asset_ids": [],
            "updated_at": "2026-07-04T14:00:00",
        })
        apply_post_data(fresh, data)
        self.assertEqual(fresh.id, "new_1")
        self.assertEqual(fresh.created_at, "2026-07-04T14:00:00")
        self.assertEqual(fresh.category_id, "86698")
        self.assertEqual(fresh.censor_mode, "custom")
        self.assertEqual(fresh.campaign_id, "")


if __name__ == "__main__":
    unittest.main()
