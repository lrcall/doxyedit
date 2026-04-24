"""psyai_data.py — shared data builder for the userscript bridge.

Produces a JSON-serializable dict in the shape the `psyai-autofill`
Tampermonkey userscript expects (matches its PSYAI constant so the
userscript can drop-in replace its hardcoded values).

Three transport paths consume the same dict:
 - Track A (CDP push): `psyai_bridge.cdp_push(data)` injects as
   `window.__psyai_data` on every page under the Brave debug instance.
 - Track B (clipboard): `psyai_bridge.copy_to_clipboard(data)` writes
   as JSON; the userscript's "paste from DoxyEdit" button reads.
 - Track C (local HTTP): `psyai_bridge.start_http_server()` serves the
   latest snapshot at GET /psyai.json for GM_xmlhttpRequest fetches.

Keeping the builder standalone means every transport works off one
source of truth — swapping strategy doesn't re-derive the data.
"""
from __future__ import annotations

from typing import Optional


def _truncate(text: str, max_len: int) -> str:
    """Trim `text` to `max_len` chars on a word boundary when possible."""
    if not text or len(text) <= max_len:
        return text or ""
    cut = text[:max_len].rsplit(" ", 1)
    return (cut[0] if cut[0] else text[:max_len]).rstrip()


def _slugify_handle(name: str) -> str:
    """Collapse an arbitrary display name into a handle-safe slug.

    Output contains only [a-z0-9_]. Runs of any other character
    (spaces, slashes, dots, dashes, unicode) collapse to a single
    underscore; leading/trailing underscores strip. "B.D. INC /
    Yacky" becomes "b_d_inc_yacky", not "b.d._inc_/_yacky" which
    would break URLs and @-style handles on most platforms."""
    import re
    if not name:
        return ""
    lowered = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug


def _split_title_body(caption: str) -> dict:
    """Split a Reddit caption into `{title, body}`. Convention: first
    non-empty line is the title, everything after the first blank line
    (or the remainder) is the body. Captions shorter than a single line
    use the whole string as the title with an empty body."""
    if not caption:
        return {"title": "", "body": ""}
    lines = caption.split("\n")
    # Skip leading blank lines.
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return {"title": "", "body": ""}
    title = lines[i].strip()
    rest = "\n".join(lines[i + 1:]).lstrip("\n")
    return {"title": title, "body": rest}


def build_psyai_data(project, composer_post=None) -> dict:
    """Assemble the userscript payload from a DoxyEdit project.

    When `composer_post` is provided, its captions win over any other
    post's captions for the same platform keys — this lets the UI push
    the currently-editing post live even before it's saved.

    Return shape mirrors the PSYAI constant in psyai-autofill.user.js:
        {
          "handle": str, "displayName": str,
          "taglineShort": str, "oneLine": str,
          "bioShort": str, "bioMedium": str, "bioLong": str,
          "steamURL": str, "itchURL": str, ...,
          "tags": str,
          "posts": {
            "bluesky": str, "x": str, ...,
            "reddit_indiedev": {"title": str, "body": str},
            ...
          }
        }
    """
    identity = project.get_identity() if hasattr(project, "get_identity") else None
    name = (identity.name if identity else "") or ""
    bio_blurb = (identity.bio_blurb if identity else "") or ""
    hashtags = (identity.hashtags if identity else []) or []

    data: dict = {
        # Identity / bio variants. All three "bio*" keys exist so the
        # userscript panel can keep separate buttons; if the source is
        # a single blob the short/medium variants are word-boundary
        # truncations of the long form.
        "handle": _slugify_handle(name),
        "displayName": name,
        "taglineShort": _truncate(bio_blurb, 80),
        "oneLine": _truncate(bio_blurb, 120),
        "bioShort": _truncate(bio_blurb, 160),
        "bioMedium": _truncate(bio_blurb, 500),
        "bioLong": bio_blurb,
        # URLs come straight off the identity. Keys match the userscript.
        "steamURL": "",
        "itchURL": "",
        "discordURL": "",
        "newsletterURL": "",
        "gumroadURL": (identity.gumroad_url if identity else "") or "",
        "patreonURL": (identity.patreon_url if identity else "") or "",
        "fanboxURL": (identity.fanbox_url if identity else "") or "",
        "fantiaURL": (identity.fantia_url if identity else "") or "",
        "kofiURL": (identity.kofi_url if identity else "") or "",
        "subscribestarURL": (identity.subscribestar_url if identity else "") or "",
        "kickstarterURL": (identity.kickstarter_url if identity else "") or "",
        "indiegogoURL": (identity.indiegogo_url if identity else "") or "",
        "tags": " ".join(f"#{t.lstrip('#')}" for t in hashtags),
        "posts": {},
    }

    # Walk project posts for per-platform caption snapshots. Later
    # entries (including the composer_post override below) replace
    # earlier ones for the same platform key — the most recently-
    # touched post wins so the userscript always sees fresh text.
    posts_bag = list(getattr(project, "posts", []) or [])
    if composer_post is not None:
        posts_bag.append(composer_post)

    for post in posts_bag:
        captions = dict(getattr(post, "captions", {}) or {})
        default_caption = getattr(post, "caption_default", "") or ""
        for platform in getattr(post, "platforms", []) or []:
            text = _caption_with_fallback(platform, captions, default_caption)
            if not text:
                continue
            if platform.startswith("reddit") or platform.startswith("r/"):
                data["posts"][_reddit_key(platform)] = _split_title_body(text)
            else:
                data["posts"][platform] = text
        # Also expose captions keyed as "reddit_<subreddit>" even when
        # the platform list doesn't carry the per-sub identifier. Lets
        # users pre-compose per-sub copy inside a single post.
        for key, text in captions.items():
            if not text:
                continue
            if key.startswith("reddit_") or key.startswith("r/"):
                data["posts"][_reddit_key(key)] = _split_title_body(text)

    # Composer-post assets: expose as {id, name, url, mime} so the
    # userscript panel can render one-click "attach this" buttons.
    # DoxyEdit already knows which assets belong to which post —
    # this skips the OS file picker entirely.
    data["assets"] = []
    if composer_post is not None:
        try:
            from doxyedit.psyai_bridge import register_assets_bulk
            items = []
            for aid in (getattr(composer_post, "asset_ids", []) or []):
                asset = (project.get_asset(aid)
                         if hasattr(project, "get_asset") else None)
                if asset and getattr(asset, "source_path", None):
                    items.append((aid, asset.source_path))
            data["assets"] = register_assets_bulk(items)
        except Exception:
            data["assets"] = []

    return data


# Short-form text platforms share idioms, so a caption written for
# one is usually close enough for the others. When the user only
# wrote a caption for twitter/x, fall back to it rather than forcing
# them to copy-paste into every short-form field.
_PLATFORM_CAPTION_FALLBACKS: dict[str, tuple[str, ...]] = {
    "bluesky": ("x", "twitter"),
    "threads": ("x", "twitter"),
    "mastodon": ("x", "twitter"),
    "x": ("twitter",),
    "twitter": ("x",),
}


def _caption_with_fallback(platform: str, captions: dict,
                           default_caption: str) -> str:
    """Pick the best caption for `platform`: own key first, then
    per-platform fallbacks (see `_PLATFORM_CAPTION_FALLBACKS`), then
    the post-wide default."""
    direct = captions.get(platform)
    if direct:
        return direct
    for fb in _PLATFORM_CAPTION_FALLBACKS.get(platform, ()):
        val = captions.get(fb)
        if val:
            return val
    return default_caption


def _reddit_key(platform_or_caption_key: str) -> str:
    """Normalize any of "reddit", "reddit_IndieDev", "r/IndieDev" to
    the userscript's `reddit_<lowercase_slug>` convention."""
    key = platform_or_caption_key.strip()
    if key.startswith("r/"):
        key = "reddit_" + key[2:]
    if not key.startswith("reddit"):
        key = "reddit_" + key
    # Lowercase the subreddit part only; keep the literal `reddit_`
    # prefix as-is for predictability.
    parts = key.split("_", 1)
    if len(parts) == 2:
        return f"{parts[0]}_{parts[1].lower()}"
    return key.lower()
