"""Strategy briefing generator for social media posts.

Analyzes asset tags, posting history, identity/brand, calendar context,
tag frequency, platform fit, and past strategy notes to produce a structured
markdown briefing for a given SocialPost.

Two modes:
  - generate_strategy_briefing(): local data analysis (fast, no API call)
  - generate_ai_strategy(): sends images + context to Claude for real insight
"""
from __future__ import annotations

import subprocess
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from doxyedit.models import Asset, CollectionIdentity, Project, SocialPost, SocialPostStatus


# ---------------------------------------------------------------------------
# Tag category heuristics
# ---------------------------------------------------------------------------

# Known character tags (depth-1 folder names from CLAUDE.md).  Lowercase.
_CHARACTER_TAGS = {
    "angel", "boku", "devil", "devil_futa", "devils", "elf", "fem", "furry",
    "futa", "gorl", "horse", "hyakpu", "jenni", "jenni_01", "judy", "kisuka",
    "marty", "milfs", "nintendo", "onta", "peach", "peach2", "philomaus",
    "rarity", "sailor_moon", "squids", "thezackrabbit", "victor",
    "ych_a_bonfirefox", "ych_b_commanderwolf47", "yacky", "chimereon_site",
}

# Content-type / workflow tags
_CONTENT_TAGS = {
    "color", "sketch", "lineart", "flat", "illustration", "comic", "animation",
    "wip", "final", "nsfw", "sfw", "pinup", "sequence", "variant",
}

# Campaign / sub-project tags
_CAMPAIGN_TAGS = {
    "kickstarter", "patreon", "gumroad", "steam", "merch", "polished_merch",
    "comission", "completed_comms", "hardblush", "design", "logo", "gamedit",
    "unigan_manga", "younigans", "usedup",
}


def _classify_tags(
    tags: list[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Split tags into (characters, content_types, campaigns, other)."""
    characters: list[str] = []
    content: list[str] = []
    campaigns: list[str] = []
    other: list[str] = []
    for t in tags:
        tl = t.lower()
        if tl in _CHARACTER_TAGS:
            characters.append(t)
        elif tl in _CONTENT_TAGS:
            content.append(t)
        elif tl in _CAMPAIGN_TAGS:
            campaigns.append(t)
        else:
            other.append(t)
    return characters, content, campaigns, other


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

_TIME_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
]


def _parse_dt(s: str) -> Optional[datetime]:
    """Try several datetime formats, return None on failure."""
    if not s:
        return None
    # Strip trailing Z / timezone suffix for simplicity
    s = s.rstrip("Z")
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _fmt_date(dt: datetime) -> str:
    """Short human date: 'Tue Apr 15'."""
    return dt.strftime("%a %b %d").replace("  ", " ")


def _fmt_datetime(dt: datetime) -> str:
    """Short human datetime: 'Tue Apr 15, 10:00 AM'."""
    return dt.strftime("%a %b %d, %I:%M %p").replace("  ", " ").lstrip("0")


def _days_ago(dt: datetime, ref: datetime) -> int:
    return (ref.date() - dt.date()).days


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def _build_tag_post_history(
    posts: list[SocialPost], project: Project,
) -> dict[str, list[SocialPost]]:
    """Map tag → list of posts whose assets carry that tag."""
    tag_posts: dict[str, list[SocialPost]] = {}
    for p in posts:
        tags_for_post: set[str] = set()
        for aid in p.asset_ids:
            asset = project.get_asset(aid)
            if asset:
                tags_for_post.update(asset.tags)
        for t in tags_for_post:
            tag_posts.setdefault(t, []).append(p)
    return tag_posts


def _post_status_counts(
    posts: list[SocialPost],
) -> tuple[int, int]:
    """Return (posted_count, queued_count) from a list of posts."""
    posted = sum(1 for p in posts if p.status == SocialPostStatus.POSTED)
    queued = sum(1 for p in posts if p.status == SocialPostStatus.QUEUED)
    return posted, queued


def _last_posted(posts: list[SocialPost]) -> Optional[tuple[datetime, str]]:
    """Find the most recent posted entry, return (datetime, platform_str)."""
    best_dt: Optional[datetime] = None
    best_plat = ""
    for p in posts:
        if p.status != SocialPostStatus.POSTED:
            continue
        dt = _parse_dt(p.scheduled_time) or _parse_dt(p.updated_at) or _parse_dt(p.created_at)
        if dt and (best_dt is None or dt > best_dt):
            best_dt = dt
            best_plat = ", ".join(p.platforms) if p.platforms else "unknown"
    return (best_dt, best_plat) if best_dt else None


def _asset_ever_posted(asset_id: str, posts: list[SocialPost]) -> bool:
    for p in posts:
        if asset_id in p.asset_ids and p.status == SocialPostStatus.POSTED:
            return True
    return False


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_asset_context(
    assets: list[Asset], project: Project,
) -> str:
    """## Asset Context"""
    if not assets:
        return "## Asset Context\n- No assets linked to this post\n"

    all_tags: list[str] = []
    for a in assets:
        all_tags.extend(a.tags)
    unique_tags = list(dict.fromkeys(all_tags))  # preserve order, dedupe

    characters, content, campaigns, other = _classify_tags(unique_tags)
    starred = any(a.starred for a in assets)

    tag_defs = project.tag_definitions
    def _label(t: str) -> str:
        d = tag_defs.get(t)
        if d and isinstance(d, dict):
            return d.get("label", t)
        return t

    lines = ["## Asset Context"]
    if characters:
        lines.append(f"- **Characters:** {', '.join(_label(c) for c in characters)}")
    if content:
        lines.append(f"- **Content type:** {', '.join(_label(c) for c in content)}")
    if campaigns:
        lines.append(f"- **Campaign:** {', '.join(_label(c) for c in campaigns)}")
    lines.append(f"- **Tags:** {', '.join(_label(t) for t in unique_tags) if unique_tags else 'none'}")
    lines.append(f"- **Starred:** {'Yes' if starred else 'No'}")
    if len(assets) > 1:
        lines.append(f"- **Asset count:** {len(assets)}")
    return "\n".join(lines) + "\n"


def _section_posting_history(
    assets: list[Asset],
    post: SocialPost,
    project: Project,
) -> str:
    """## Posting History"""
    posts = project.posts
    tag_history = _build_tag_post_history(posts, project)

    all_tags: list[str] = []
    for a in assets:
        all_tags.extend(a.tags)
    unique_tags = list(dict.fromkeys(all_tags))
    characters, _, _, _ = _classify_tags(unique_tags)

    lines = ["## Posting History"]

    # Per-character history
    focus_tags = characters if characters else unique_tags[:5]
    for tag in focus_tags:
        tag_posts = tag_history.get(tag, [])
        posted, queued = _post_status_counts(tag_posts)
        last = _last_posted(tag_posts)
        parts = [f"{tag}: posted {posted}x"]
        if last:
            dt, plat = last
            parts.append(f"(last: {_fmt_date(dt)} {plat})")
        if queued:
            parts.append(f"queued {queued}x")
        if posted == 0 and queued == 0:
            parts.append("— FRESH, good for engagement")
        lines.append(f"- {' '.join(parts)}")

    # This asset specifically
    for a in assets:
        ever = _asset_ever_posted(a.id, posts)
        label = a.id
        if ever:
            lines.append(f"- Asset {label}: previously posted")
        else:
            lines.append(f"- Asset {label}: never posted")

    if not assets and not focus_tags:
        lines.append("- No posting history available")

    return "\n".join(lines) + "\n"


def _section_platform_analysis(
    assets: list[Asset],
    post: SocialPost,
    project: Project,
) -> str:
    """## Platform Analysis"""
    platforms = post.platforms or []
    if not platforms:
        identity = project.get_identity()
        platforms = identity.default_platforms or []
    if not platforms:
        return "## Platform Analysis\n- No platforms selected\n"

    all_tags: list[str] = []
    for a in assets:
        all_tags.extend(a.tags)
    characters, _, _, _ = _classify_tags(list(dict.fromkeys(all_tags)))

    tag_history = _build_tag_post_history(project.posts, project)
    identity = project.get_identity()
    now = datetime.now()

    lines = ["## Platform Analysis"]
    for plat in platforms:
        notes: list[str] = []

        # Check character recency on this platform
        for char in characters[:3]:
            char_posts = tag_history.get(char, [])
            plat_posts = [p for p in char_posts
                          if plat in p.platforms and p.status == SocialPostStatus.POSTED]
            if plat_posts:
                last = _last_posted(plat_posts)
                if last:
                    days = _days_ago(last[0], now)
                    notes.append(f"{char} last posted {days}d ago on {plat}")
            else:
                notes.append(f"{char} never posted on {plat} — fresh")

        # Monetization hints
        if plat in ("patreon",) and identity.patreon_url:
            notes.append(f"Link Patreon: {identity.patreon_url}")
        if plat in ("twitter", "instagram", "bluesky") and identity.gumroad_url:
            notes.append(f"Consider linking Gumroad in caption")

        # Multi-asset hint
        if len(assets) > 1 and plat == "instagram":
            notes.append("Consider carousel with multiple assets")

        detail = "; ".join(notes) if notes else "No specific notes"
        lines.append(f"- **{plat}:** {detail}")

    return "\n".join(lines) + "\n"


def _section_calendar_context(
    post: SocialPost,
    project: Project,
) -> str:
    """## Calendar Context"""
    sched_dt = _parse_dt(post.scheduled_time)
    if not sched_dt:
        return "## Calendar Context\n- No scheduled time set\n"

    lines = ["## Calendar Context"]
    lines.append(f"- **Scheduled for:** {_fmt_datetime(sched_dt)}")

    # Nearby posts (within ±3 days)
    window_start = sched_dt - timedelta(days=3)
    window_end = sched_dt + timedelta(days=3)

    day_posts: dict[str, list[SocialPost]] = {}
    for p in project.posts:
        if p.id == post.id:
            continue
        pdt = _parse_dt(p.scheduled_time)
        if pdt and window_start <= pdt <= window_end:
            day_key = pdt.strftime("%a %b %d")
            day_posts.setdefault(day_key, []).append(p)

    if day_posts:
        nearby_lines = []
        for day_str in sorted(day_posts.keys()):
            posts_on_day = day_posts[day_str]
            plats = set()
            for p in posts_on_day:
                plats.update(p.platforms)
            nearby_lines.append(
                f"{day_str}: {len(posts_on_day)} post(s) ({', '.join(sorted(plats)) if plats else 'no platform'})"
            )
        lines.append(f"- **Nearby posts:** {'; '.join(nearby_lines)}")
    else:
        lines.append("- **Nearby posts:** None within ±3 days")

    # Week gap analysis (Mon-Sun of scheduled week)
    week_start = sched_dt - timedelta(days=sched_dt.weekday())
    filled_days = set()
    filled_days.add(sched_dt.date())
    for p in project.posts:
        if p.id == post.id:
            continue
        pdt = _parse_dt(p.scheduled_time)
        if pdt:
            d = pdt.date()
            if week_start.date() <= d < week_start.date() + timedelta(days=7):
                filled_days.add(d)

    gaps = 7 - len(filled_days)
    lines.append(f"- **Gaps this week:** {gaps} day(s) unfilled")
    if gaps >= 4:
        lines.append("- **Recommendation:** Lots of open slots — good time to post")
    elif gaps <= 1:
        lines.append("- **Recommendation:** Busy week — consider spacing for visibility")
    else:
        lines.append("- **Recommendation:** Good slot, fills a gap")

    return "\n".join(lines) + "\n"


def _section_tag_trends(
    assets: list[Asset],
    project: Project,
) -> str:
    """## Tag Trends"""
    tag_history = _build_tag_post_history(project.posts, project)

    # Count total posted entries per tag (only POSTED status)
    tag_posted: Counter[str] = Counter()
    for tag, posts in tag_history.items():
        tag_posted[tag] = sum(1 for p in posts if p.status == SocialPostStatus.POSTED)

    # Focus on the tags from this post's assets
    all_tags: list[str] = []
    for a in assets:
        all_tags.extend(a.tags)
    unique_tags = list(dict.fromkeys(all_tags))

    if not unique_tags:
        return "## Tag Trends\n- No tags to analyze\n"

    lines = ["## Tag Trends"]
    for tag in unique_tags:
        count = tag_posted.get(tag, 0)
        if count == 0:
            note = "UNDERREPRESENTED, boost priority"
        elif count >= 10:
            note = "high frequency — consider spacing"
        elif count >= 5:
            note = "moderate"
        else:
            note = "low"
        lines.append(f"- {tag}: {count} post(s) total ({note})")

    return "\n".join(lines) + "\n"


def _section_brand_notes(project: Project) -> str:
    """## Brand Notes"""
    identity = project.get_identity()
    lines = ["## Brand Notes"]

    if identity.voice:
        lines.append(f"- **Voice:** {identity.voice}")
    else:
        lines.append("- **Voice:** Not set")

    if identity.hashtags:
        lines.append(f"- **Default hashtags:** {' '.join(identity.hashtags)}")

    links: list[str] = []
    if identity.gumroad_url:
        links.append(f"Gumroad: {identity.gumroad_url}")
    if identity.patreon_url:
        links.append(f"Patreon: {identity.patreon_url}")
    if links:
        lines.append(f"- **Monetization:** {', '.join(links)}")

    if identity.bio_blurb:
        lines.append(f"- **Bio:** {identity.bio_blurb}")

    if identity.content_notes:
        lines.append(f"- **Content notes:** {identity.content_notes}")

    if len(lines) == 1:
        lines.append("- No identity configured")

    return "\n".join(lines) + "\n"


def _section_past_strategy(
    post: SocialPost,
    project: Project,
    max_recent: int = 3,
) -> str:
    """## Past Strategy Continuity"""
    # Collect recent posts with strategy notes, excluding current
    recent: list[tuple[str, str]] = []
    for p in reversed(project.posts):
        if p.id == post.id:
            continue
        if p.strategy_notes and p.strategy_notes.strip():
            dt = _parse_dt(p.scheduled_time) or _parse_dt(p.created_at)
            label = _fmt_date(dt) if dt else p.id
            # Truncate long notes
            note = p.strategy_notes.strip()
            if len(note) > 200:
                note = note[:200] + "..."
            recent.append((label, note))
        if len(recent) >= max_recent:
            break

    lines = ["## Past Strategy Continuity"]
    if recent:
        for label, note in recent:
            # Collapse to single line summary
            first_line = note.split("\n")[0]
            lines.append(f"- **{label}:** {first_line}")
    else:
        lines.append("- No previous strategy notes found")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_strategy_briefing(project: Project, post: SocialPost) -> str:
    """Assemble a full strategy briefing for a social media post.

    Analyzes the post's assets, tags, posting history, calendar position,
    brand identity, and past strategy notes to produce a structured markdown
    briefing suitable for storing in ``post.strategy_notes``.

    Args:
        project: The loaded Project with assets, posts, tags, identity.
        post: The SocialPost being planned.

    Returns:
        Structured markdown string.
    """
    # Resolve assets
    assets: list[Asset] = []
    for aid in post.asset_ids:
        a = project.get_asset(aid)
        if a:
            assets.append(a)

    sections = [
        _section_asset_context(assets, project),
        _section_posting_history(assets, post, project),
        _section_platform_analysis(assets, post, project),
        _section_calendar_context(post, project),
        _section_tag_trends(assets, project),
        _section_brand_notes(project),
        _section_past_strategy(post, project),
    ]

    return "\n".join(sections).rstrip() + "\n"


# ---------------------------------------------------------------------------
# AI-powered strategy (calls Claude via CLI)
# ---------------------------------------------------------------------------

def generate_ai_strategy(
    project: Project,
    post: SocialPost,
) -> str:
    """Call Claude API with images + project context for real strategy.

    Uses the Anthropic Python SDK with vision to analyze the actual images.
    Falls back to local briefing if the SDK or API key is unavailable.
    """
    # 1. Gather local context briefing
    local_briefing = generate_strategy_briefing(project, post)

    # 2. Resolve assets for context
    assets: list[Asset] = []
    for aid in post.asset_ids:
        a = project.get_asset(aid)
        if a:
            assets.append(a)

    # 3. Build the prompt
    identity = project.get_identity()
    platform_list = ", ".join(post.platforms) if post.platforms else "not yet selected"

    recent_posts = []
    for p in sorted(project.posts, key=lambda x: x.scheduled_time or "")[-15:]:
        if p.id == post.id:
            continue
        status = p.status if isinstance(p.status, str) else p.status
        caption_preview = (p.caption_default or "")[:60]
        plats = ", ".join(p.platforms) if p.platforms else "?"
        dt = p.scheduled_time[:10] if p.scheduled_time else "unscheduled"
        recent_posts.append(f"  - {dt} [{status}] {plats}: {caption_preview}")
    recent_block = "\n".join(recent_posts) if recent_posts else "  (no other posts)"

    text_prompt = f"""You are a senior social media marketing strategist specializing in art/illustration creators. You've managed accounts with 100k+ followers. Be direct, opinionated, and specific. No filler.

**Creator:** {identity.name or 'indie artist'} · Voice: {identity.voice or 'casual'} · {identity.content_notes or 'no content notes'}
**Platforms:** {platform_list}
**Scheduled:** {post.scheduled_time or 'TBD'}
**Tags:** {', '.join(t for a in assets for t in a.tags) if assets else 'none'}
**Hashtags:** {' '.join(identity.hashtags) if identity.hashtags else 'none'}
{f"**Gumroad:** {identity.gumroad_url}" if identity.gumroad_url else ""}{f"  **Patreon:** {identity.patreon_url}" if identity.patreon_url else ""}

## Data
{local_briefing}

## Recent Posts
{recent_block}

## Deliverables (be concise, no generic advice)

**Captions** — One ready-to-copy caption per platform. Short, punchy, in the creator's voice. Include 3-5 hashtags inline. No placeholder text.

**Timing** — Is the scheduled slot good? If not, what's better and why. One sentence.

**Platform play** — For each platform: the one specific format/tactic that fits THIS content. Carousel, thread, reel, static, story — pick one and say why. Don't list all options.

**Hook** — One question or CTA that drives replies, not just likes.

**Monetization** — Only if there's a natural angle. Skip if forced.

**Flags** — Content warnings, age-gating needs, or platform-specific restrictions. Skip if none.

Skip sections that don't apply. Don't pad. Write like you're texting a colleague, not writing a report."""

    # 4. Use claude CLI — uses the same subscription/auth as Claude Code
    return _generate_ai_strategy_cli(text_prompt, local_briefing)


def _generate_ai_strategy_cli(prompt: str, fallback: str) -> str:
    """Pipe prompt to claude CLI — uses the same auth/subscription as Claude Code.
    No extra API key or billing needed."""
    import sys
    print("[AI Strategy] Starting claude CLI subprocess...", file=sys.stderr, flush=True)
    print(f"[AI Strategy] Prompt length: {len(prompt)} chars", file=sys.stderr, flush=True)
    try:
        proc = subprocess.Popen(
            ["claude", "-p", prompt],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        print("[AI Strategy] Process started, waiting for response...", file=sys.stderr, flush=True)

        try:
            stdout, stderr = proc.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            proc.kill()
            print("[AI Strategy] TIMEOUT after 180s", file=sys.stderr, flush=True)
            return f"[Claude CLI timed out after 180s]\n\nLocal analysis:\n\n{fallback}"

        print(f"[AI Strategy] Process finished — exit code {proc.returncode}", file=sys.stderr, flush=True)
        if stderr.strip():
            print(f"[AI Strategy] stderr: {stderr.strip()[:200]}", file=sys.stderr, flush=True)

        if proc.returncode == 0 and stdout.strip():
            print(f"[AI Strategy] Got {len(stdout.strip())} chars of response", file=sys.stderr, flush=True)
            return stdout.strip()

        err = stderr.strip() if stderr else "Unknown error"
        print(f"[AI Strategy] FAILED: {err[:200]}", file=sys.stderr, flush=True)
        return f"[Claude CLI error: {err}]\n\nLocal analysis:\n\n{fallback}"
    except FileNotFoundError:
        print("[AI Strategy] ERROR: claude CLI not found", file=sys.stderr, flush=True)
        return f"[Claude CLI not found — is claude-code installed?]\n\nLocal analysis:\n\n{fallback}"
    except Exception as e:
        print(f"[AI Strategy] ERROR: {e}", file=sys.stderr, flush=True)
        return f"[Error: {e}]\n\nLocal analysis:\n\n{fallback}"
