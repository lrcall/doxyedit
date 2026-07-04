"""Deterministic golden-fixture generator.

Writes tests/fixtures/golden_full.doxyproj.json with EVERY schema
section of the project file populated with at least one meaningful
entry. No timestamps, no randomness - re-running this script on an
unchanged schema reproduces the same file byte for byte.

Asset paths are fake relative strings (local_mode=False so they pass
through untouched); the fixture must never depend on real files.

Regenerate after any schema change:

    py scripts/make_golden_fixture.py

then check the updated fixture in alongside the code change.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from doxyedit.models import (  # noqa: E402
    Asset, Campaign, CampaignMilestone, CanvasOverlay, CensorRegion,
    CropRegion, PlatformAssignment, Project, ReleaseStep, SocialPost,
    SubredditConfig,
)

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "golden_full.doxyproj.json"


def build_project() -> Project:
    proj = Project()
    proj.name = "Golden Fixture Project"
    proj.notes = ("Round-trip golden fixture - do not edit by hand; "
                  "regenerate via scripts/make_golden_fixture.py")
    proj.sub_notes = {
        "Plan": "# Plan\n- keep the golden fixture green 夢",
        "Log": "2026-01-01 fixture created",
    }
    proj.local_mode = False
    proj.platforms = ["kickstarter", "twitter", "patreon"]

    # tag_definitions and custom_tags kept in sync (project file rule).
    proj.tag_definitions = {
        "golden": {"label": "Golden", "color": "#ffcc00"},
        "linework": {"label": "Linework", "color": "#88ccff",
                     "parent_id": "golden"},
        "sailor_moon": {"label": "Sailor Moon", "color": "#ff88cc",
                        "width": 1920, "height": 1080, "ratio": "16:9"},
    }
    proj.custom_tags = [
        {"id": "golden", "label": "Golden", "color": "#ffcc00"},
        {"id": "linework", "label": "Linework", "color": "#88ccff",
         "parent_id": "golden"},
        {"id": "sailor_moon", "label": "Sailor Moon", "color": "#ff88cc",
         "width": 1920, "height": 1080, "ratio": "16:9"},
    ]
    proj.tag_aliases = {"old_golden": "golden"}
    proj.custom_shortcuts = {"g": "golden", "l": "linework"}
    proj.hidden_tags = ["linework"]
    proj.eye_hidden_tags = ["sailor_moon"]
    proj.sort_mode = "Name A-Z"
    # Named-tray dict form (the other legal shape is a flat list).
    proj.tray_items = {"main": ["piece_a_0"], "alts": ["piece_b_1"]}
    proj.accent_color = "#aa66ff"
    proj.theme_id = "midnight"
    proj.checklist = ["[x] build fixture", "[ ] verify round trip"]
    proj.excluded_paths = {"fixtures/fake/skip_me.png"}
    proj.import_sources = [{
        "type": "folder",
        "path": "fixtures/fake",
        "recursive": True,
        "added_at": "2026-01-01T00:00:00",
    }]
    proj.folder_presets = [
        {"id": "fp1", "name": "Fake sources", "folders": ["fixtures/fake"]}]
    proj.filter_presets = [{
        "name": "Starred golden", "icon": "star",
        "state": {"tags": ["golden"], "min_star": 1},
    }]

    identity = {
        "name": "Golden Doxy",
        "voice": "warm, direct",
        "hashtags": ["#golden", "#fixture"],
        "default_platforms": ["twitter"],
        "gumroad_url": "https://example.com/gumroad",
        "patreon_url": "https://example.com/patreon",
        "bio_blurb": "Fixture identity 夢",
        "content_notes": "fixture only, never posted",
    }
    proj.identity = dict(identity)
    proj.identities = {
        "Golden Doxy": dict(identity),
        "Alt Brand": {"name": "Alt Brand", "voice": "loud",
                      "hashtags": ["#alt"]},
    }
    proj.oneup_config = {
        "api_key": "", "category_id": "86698", "note": "fixture only"}
    proj.default_overlays = [CanvasOverlay(
        type="watermark", label="Logo preset",
        image_path="fixtures/fake/logo.png",
        opacity=0.5, position="bottom-right", scale=0.15).to_dict()]
    proj.release_templates = [{
        "name": "Standard chain",
        "steps": [
            {"platform": "twitter", "delay_hours": 0},
            {"platform": "patreon", "delay_hours": 24},
        ],
    }]
    proj.blackout_periods = [{
        "start": "2026-02-01", "end": "2026-02-07",
        "label": "KS launch", "scope": "all"}]

    proj.campaigns = [Campaign(
        id="camp_1", name="Golden Kickstarter", platform_id="kickstarter",
        launch_date="2026-03-01", end_date="2026-03-31", status="planning",
        milestones=[CampaignMilestone(
            id="ms_1", label="Prep art", due_date="2026-02-20",
            completed=True, notes="done early")],
        linked_post_ids=["post_1"], notes="fixture campaign",
        color="#00cc88")]

    proj.subreddits = [SubredditConfig(
        name="r/golden", flair_id="f1", flair_text="OC", nsfw=True,
        title_template="{title} [OC]", rules_notes="no reposts",
        min_interval_days=7, last_posted="2026-01-15",
        tags_required=["golden"])]

    proj.posts = [SocialPost(
        id="post_1",
        asset_ids=["piece_a_0"],
        platforms=["twitter", "patreon"],
        captions={"twitter": "tw caption 夢"},
        caption_default="Golden caption",
        links=["https://example.com/art"],
        scheduled_time="2026-03-05T18:00:00",
        status="draft",
        platform_status={"twitter": "queued"},
        oneup_post_id="one_123",
        reply_templates=["Thanks for looking!"],
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-02T00:00:00",
        notes="post note",
        collection="golden set",
        strategy_notes="lead with the header crop",
        nsfw_platforms=["twitter"],
        sfw_asset_ids=["piece_b_1"],
        tier_assets={"gold_tier": ["piece_a_0"]},
        sub_platform_status={"twitter": {"status": "queued",
                                         "posted_at": ""}},
        campaign_id="camp_1",
        category_id="86698",
        release_chain=[ReleaseStep(
            platform="twitter", delay_hours=0, account_id="acct1",
            caption_key="twitter", status="pending", posted_at="",
            tier_level="free", locale="en")],
        published_urls={"twitter": "https://example.com/status/1"},
        engagement_checks=[{
            "post_id": "post_1", "platform": "twitter",
            "account_id": "acct1", "check_at": "2026-03-06T18:00:00",
            "action": "first_reactions", "url": "", "done": False,
            "notes": "check replies"}],
        censor_mode="custom",
        platform_censor={"twitter": True, "patreon": False},
        platform_metrics={"twitter": {
            "likes": 5, "retweets": 1, "replies": 0, "views": 100,
            "clicks": 2, "last_checked": "2026-03-07T00:00:00"}},
        identity_name="Golden Doxy",
        posting_log=[{
            "ts": "2026-03-05T18:00:00", "platform": "twitter",
            "action": "queued", "url": "", "detail": "fixture log"}],
    )]

    # Asset 1: everything populated - crops with rotation, censor with
    # platforms, four overlay flavors, assignment with nested crop and
    # campaign link, specs, notes, stars, variant_exports + guides
    # (the latter two are saved but dropped on load - documented lossy).
    piece_a = Asset(
        id="piece_a_0",
        source_path="fixtures/fake/piece_a.png",
        source_folder="fixtures/fake",
        starred=3,
        tags=["golden", "sailor_moon"],
        notes="fixture asset one 夢",
        specs={"cli_info": "1024x768", "origin": "golden"},
    )
    piece_a.crops.append(CropRegion(
        x=10, y=20, w=300, h=200, label="header",
        platform_id="twitter", slot_name="header", rotation=12.5))
    piece_a.censors.append(CensorRegion(
        x=5, y=5, w=50, h=50, style="pixelate", blur_radius=20,
        pixelate_ratio=8, rotation=0.0, platforms=["twitter"]))
    piece_a.overlays.append(CanvasOverlay(
        type="text", label="title", text="Golden Title 夢",
        font_family="Segoe UI", font_size=32, color="#ffffff",
        opacity=0.9, position="top-left", bold=True,
        letter_spacing=1.5, stroke_color="#000000", stroke_width=2,
        shadow_color="#000000", shadow_offset=2, shadow_blur=4,
        text_align="center", platforms=["twitter"], group_id="grp1"))
    piece_a.overlays.append(CanvasOverlay(
        type="shape", label="badge", shape_kind="star", x=40, y=40,
        shape_w=120, shape_h=120, fill_color="#ff0000",
        star_points=6, inner_ratio=0.5, corner_radius=8, rotation=15.0))
    piece_a.overlays.append(CanvasOverlay(
        type="arrow", label="pointer", x=10, y=10, end_x=200, end_y=150,
        arrowhead_size=24, arrowhead_style="outline", double_headed=True,
        line_style="dashed", tail_curve=0.25, color="#00ff00"))
    piece_a.overlays.append(CanvasOverlay(
        type="bubble", label="speech", x=60, y=60, shape_w=180,
        shape_h=90, tail_x=50, tail_y=140, linked_text_id="grp1",
        bubble_roundness=0.6, bubble_oval_stretch=0.2, bubble_wobble=0.1,
        bubble_tail_width=1.5, bubble_tail_taper=0.3, bubble_skew_x=0.1,
        bubble_wobble_waves=6, bubble_wobble_complexity=48,
        bubble_wobble_seed=7, fill_color="#ffffff"))
    piece_a.assignments.append(PlatformAssignment(
        platform="twitter", slot="header", status="posted",
        crop=CropRegion(x=0, y=0, w=100, h=50, label="assign crop"),
        notes="assignment note", campaign_id="camp_1"))
    piece_a.variant_exports = {
        "twitter_header": "export/piece_a_twitter.png"}
    piece_a.guides = [{"orientation": "h", "position": 128},
                      {"orientation": "v", "position": 64}]

    # Asset 2: exercises the load-time migrations - an aliased tag
    # (old_golden -> golden) and CLI-style dimension notes that move
    # into specs.cli_info when specs is empty.
    piece_b = Asset(
        id="piece_b_1",
        source_path="fixtures/fake/piece_b.png",
        source_folder="fixtures/fake",
        starred=1,
        tags=["old_golden", "linework"],
        notes="800x600 cli export",
        specs={},
    )

    proj.assets = [piece_a, piece_b]
    return proj


def main() -> None:
    proj = build_project()
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    proj.save(str(FIXTURE_PATH))
    print(f"Wrote {FIXTURE_PATH}")


if __name__ == "__main__":
    main()
