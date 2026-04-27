"""Central data model — everything saves to readable JSON."""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field, asdict, MISSING
from enum import Enum
from pathlib import Path
from typing import Optional


class PostStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    POSTED = "posted"
    SKIP = "skip"


class SocialPostStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    POSTED = "posted"
    FAILED = "failed"
    PARTIAL = "partial"


# ---- Use-case tags with target sizes ----

@dataclass
class TagPreset:
    """A use-case tag with optional target dimensions for fitness checking."""
    id: str
    label: str
    width: Optional[int] = None   # None = any size OK
    height: Optional[int] = None  # None = flexible height
    ratio: str = ""               # display hint like "16:9"
    color: str = "#888888"

    @classmethod
    def from_dict(cls, tid: str, d: dict) -> "TagPreset":
        return cls(id=tid, label=d.get("label", tid),
                   width=d.get("width"), height=d.get("height"),
                   ratio=d.get("ratio", ""), color=d.get("color", "#888"))


# Vinik24 color cycle for auto-assigning colors to new tags
VINIK_COLORS = [
    "#9a4f50", "#c28d75", "#be955c", "#7ca1c0", "#416aa3",
    "#68aca9", "#666092", "#a593a5", "#c38890", "#9a9a97",
    "#6eaa78", "#8b5580", "#7e9e99", "#93a167", "#9d9f7f",
    "#5d6872", "#387080", "#557064", "#6e6962", "#6f6776",
]


# Star rating colors (1-5), from Vinik24 palette
STAR_COLORS = {
    1: "#be955c",  # gold
    2: "#7ca1c0",  # blue
    3: "#6eaa78",  # green
    4: "#c38890",  # rose
    5: "#9a4f50",  # red
}
STAR_SYMBOLS = {0: ".", 1: "*", 2: "*", 3: "*", 4: "*", 5: "*"}


def next_tag_color(existing_tags: dict) -> str:
    """Pick the next Vinik color not yet used by existing tags."""
    used = {t.color for t in existing_tags.values()}
    for c in VINIK_COLORS:
        if c not in used:
            return c
    # All used — cycle from start
    return VINIK_COLORS[len(existing_tags) % len(VINIK_COLORS)]


# Default tag presets — colors from the Vinik24 palette for visual harmony.
# Content/workflow tags first, sized/platform tags after the separator.
TAG_PRESETS: dict[str, TagPreset] = {
    # --- Content types (no size requirement) ---
    "page":      TagPreset("page",      "Page / Panel",    None, None, "",     "#a593a5"),
    "character": TagPreset("character", "Character Art",   None, None, "",     "#c38890"),
    "sketch":    TagPreset("sketch",    "Sketch / WIP",    None, None, "",     "#9a9a97"),
    "asset":     TagPreset("asset",     "Game Asset",      None, None, "",     "#6eaa78"),
    "merch":     TagPreset("merch",     "Merch Source",    None, None, "",     "#8b5580"),
    "reference": TagPreset("reference", "Reference",       None, None, "",     "#7e9e99"),
    # --- Workflow ---
    "final":     TagPreset("final",     "Final / Approved",None, None, "",     "#93a167"),
    "wip":       TagPreset("wip",       "Work in Progress",None, None, "",     "#9d9f7f"),
    "ignore":    TagPreset("ignore",    "Ignore / Skip",   None, None, "",     "#5d6872"),
}

# Sized tags — have target dimensions, shown below a separator in the tag panel
TAG_SIZED: dict[str, TagPreset] = {
    "hero":         TagPreset("hero",         "Hero",          1024, 576,  "16:9", "#9a4f50"),
    "banner":       TagPreset("banner",       "Banner",        1600, 400,  "4:1",  "#c28d75"),
    "cover":        TagPreset("cover",        "Cover",         1800, 2700, "2:3",  "#be955c"),
    "interior":     TagPreset("interior",     "Interior",      None, None, "",     "#a593a5"),
    "promo":        TagPreset("promo",        "Promo",         1200, 675,  "16:9", "#7ca1c0"),
    "tier_card":    TagPreset("tier_card",    "Tier Card",     680,  382,  "16:9", "#416aa3"),
    "stretch_goal": TagPreset("stretch_goal", "Stretch Goal",  680,  None, "flex", "#68aca9"),
    "icon":         TagPreset("icon",         "Icon / Avatar", 512,  512,  "1:1",  "#666092"),
}

# Combined for lookups (content first, sized after)
TAG_ALL: dict[str, TagPreset] = {**TAG_PRESETS, **TAG_SIZED}

# Visual property tags (auto-generated from image analysis)
VISUAL_TAGS = {
    "warm", "cool", "dark", "bright",
    "detailed", "flat",
    "portrait", "landscape", "square", "panoramic", "tall",
}

# Keyboard shortcuts — only for content/workflow tags, not sized ones
TAG_SHORTCUTS_DEFAULT: dict[str, str] = {
    "1": "page",
    "2": "character",
    "3": "sketch",
    "4": "asset",
    "5": "merch",
    "6": "reference",
    "7": "final",
    "8": "wip",
    "0": "ignore",
}
TAG_SHORTCUTS: dict[str, str] = dict(TAG_SHORTCUTS_DEFAULT)


def check_fitness(img_w: int, img_h: int, tag: TagPreset) -> str:
    """Check if image dimensions fit a tag's target size.

    Returns: "green", "yellow", or "red".
    - green: image is large enough and ratio is close
    - yellow: image is large enough but ratio is very different
    - red: image is too small
    - green if tag has no size requirements
    """
    if tag.width is None and tag.height is None:
        return "green"

    tw = tag.width or 1
    th = tag.height or img_h  # flexible height → accept image's own height

    # Size check
    if img_w < tw or img_h < th:
        return "red"

    # Ratio check
    target_ratio = tw / th
    img_ratio = img_w / img_h if img_h > 0 else 1
    ratio_diff = abs(target_ratio - img_ratio) / max(target_ratio, 0.01)

    if ratio_diff < 0.15:
        return "green"
    else:
        return "yellow"  # usable with cropping since image is large enough


@dataclass(slots=True)
class CropRegion:
    """A rectangular crop selection on an asset.

    `platform_id` scopes a crop to a specific platform (matches pipeline's
    resolution by exact platform_id). Empty string means legacy label-only
    matching. New crops created against a platform should set it; existing
    crops still resolve via the label fallback chain in pipeline.py.
    """
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    label: str = ""
    platform_id: str = ""
    slot_name: str = ""


@dataclass(slots=True)
class CensorRegion:
    """A non-destructive censor overlay rectangle."""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    style: str = "black"  # "black", "blur", "pixelate"
    blur_radius: int = 20     # Gaussian blur radius (blur style)
    pixelate_ratio: int = 10  # downscale factor (pixelate style)
    rotation: float = 0.0     # degrees
    platforms: list[str] = field(default_factory=list)  # empty = all platforms


@dataclass(slots=True)
class CanvasOverlay:
    """Non-destructive overlay (watermark, text, or logo) applied on export."""
    type: str = "watermark"  # "watermark", "text", "logo"
    label: str = ""
    image_path: str = ""      # for watermark/logo
    text: str = ""            # for text type
    font_family: str = "Segoe UI"
    font_size: int = 24
    color: str = "#ffffff"
    opacity: float = 0.3
    position: str = "bottom-right"  # bottom-right, bottom-left, center, custom
    x: int = 0
    y: int = 0
    scale: float = 0.2        # fraction of image width for watermark/logo
    enabled: bool = True
    rotation: float = 0.0     # degrees
    bold: bool = False
    italic: bool = False
    text_width: int = 0       # 0 = no wrapping
    letter_spacing: float = 0.0  # kerning
    line_height: float = 1.2  # line spacing multiplier (1.0 = tight, 1.5 = loose)
    stroke_color: str = ""    # text outline color (empty = no outline)
    stroke_width: int = 0     # text outline width in px
    shadow_color: str = ""    # drop shadow color (empty = no shadow)
    shadow_offset: int = 0    # shadow offset in px (both x and y)
    shadow_blur: int = 0      # shadow blur radius
    flip_h: bool = False      # mirror horizontally (negative X scale)
    flip_v: bool = False      # mirror vertically (negative Y scale)
    locked: bool = False      # lock from selection/drag in Studio canvas
    background_color: str = ""  # solid fill behind text (empty = no bg)
    # Arrow endpoints (tail is x,y from above; tip is end_x,end_y).
    # Used when type="arrow" — zero-default for all other overlays.
    end_x: int = 0
    end_y: int = 0
    arrowhead_size: int = 18  # arrowhead length in px
    arrowhead_style: str = "filled"  # filled / outline / none
    double_headed: bool = False      # also draw head at start (for arrows)
    line_style: str = "solid"  # "solid", "dash", "dot" — for arrows/shapes
    blend_mode: str = "normal"  # normal / multiply / screen / overlay / darken / lighten
    filter_mode: str = ""        # "grayscale" / "invert" for image overlays
    underline: bool = False
    strikethrough: bool = False
    text_align: str = "left"   # left / center / right
    corner_radius: int = 0  # for shape type="shape" with shape_kind="rect"
    # Gradient shapes: stored hex colors + angle in degrees (linear).
    gradient_start_color: str = ""
    gradient_end_color: str = ""
    gradient_angle: int = 0
    # Comic bubble support (shape_kind="speech_bubble" / "thought_bubble" /
    # "burst"). tail_x / tail_y = tail tip in scene coords; 0,0 disables.
    # linked_text_id points at a CanvasOverlay.label used as the pair's
    # text overlay so drag moves them together.
    tail_x: int = 0
    tail_y: int = 0
    linked_text_id: str = ""
    # Shape overlay — type="shape" paints a rectangle or ellipse with
    # optional fill + stroke. x, y is the top-left; shape_w / shape_h are
    # the dimensions in image pixels.
    shape_kind: str = "rect"   # rect / ellipse / speech_bubble / thought_bubble / burst / gradient_linear / gradient_radial
    shape_w: int = 0
    shape_h: int = 0
    fill_color: str = ""       # empty = hollow
    platforms: list[str] = field(default_factory=list)  # empty = all platforms
    # Grouping: any non-empty value ties overlays together so selecting
    # one selects the whole group. Set via Studio's Ctrl+G; cleared by
    # Ctrl+Shift+G. Empty string means 'not grouped'.
    group_id: str = ""
    # Skew angles in degrees (Ctrl+T Transform dialog). Shape overlays
    # apply via QTransform.shear; images / text honor them through their
    # respective _apply_flip / _apply_flip_text transform composition.
    skew_x: float = 0.0
    skew_y: float = 0.0
    # Bubble deformers — applied on top of the speech/thought paint
    # path. bubble_roundness 0.0 = default rounded-rect, 1.0 = fully
    # elliptical. bubble_oval_stretch expands the horizontal axis of
    # the body relative to the vertical (0.0 = square body, positive
    # = wider, negative = taller). bubble_wobble adds a sinusoidal
    # perturbation to the body outline (0.0 = smooth, 1.0 = very
    # wobbly). All three stack on top of each other.
    bubble_roundness: float = 0.0
    bubble_oval_stretch: float = 0.0
    bubble_wobble: float = 0.0
    # Extra bubble modifiers stacked on top of the trio above.
    # bubble_tail_width (default 1.0) scales the tail base length; >1
    # makes a thicker, chunkier tail, <1 a narrow, needle-like tail.
    # bubble_tail_taper biases the tip position along the tail;
    # 0.0 = centered bezier/triangle, positive pulls the tip toward
    # the tail's far side, negative toward the near side (think
    # "skew the tip sideways relative to the base").
    # bubble_skew_x applies a horizontal shear to the entire body so
    # the bubble leans left or right without rotating its contents.
    bubble_tail_width: float = 1.0
    bubble_tail_taper: float = 0.0
    bubble_skew_x: float = 0.0
    # Wobble tuning.
    # - bubble_wobble_waves (2..32, default 8): sin-cycle count around
    #   the perimeter. Higher = choppier, lower = slower organic
    #   undulation. (Formerly named bubble_wobble_complexity — renamed
    #   because "waves" describes the frequency behavior; complexity
    #   now means vertex density, see below.)
    # - bubble_wobble_complexity (16..512, default 72): vertex count
    #   along the path. Low = polygonal look with straight segments,
    #   high = smooth curves at a fixed wave count.
    # - bubble_wobble_seed (0..999): phase shift in 0.1-rad increments
    #   so two bubbles on the same canvas don't wobble in lockstep
    #   when the user copy-pastes.
    bubble_wobble_waves: int = 8
    bubble_wobble_complexity: int = 72
    bubble_wobble_seed: int = 0
    # Star / polygon shape params. shape_kind="star" -> n-pointed star,
    # "polygon" -> n-sided regular polygon. star_points doubles as
    # point-count for both. inner_ratio is the star's inner/outer
    # radius fraction (0.4 = classic five-point star).
    star_points: int = 5
    inner_ratio: float = 0.4
    # Image adjustments (applied by OverlayImageItem.refresh via PIL
    # ImageEnhance). 0.0 = no change. Range usually -1.0 to 1.0 for
    # brightness/contrast (PIL factor = 1.0 + value); saturation uses
    # the same shape (-1 = grayscale, 0 = normal, 1 = double).
    img_brightness: float = 0.0
    img_contrast: float = 0.0
    img_saturation: float = 0.0
    # Bubble tail curve amount (-1.0 .. 1.0). 0 = straight triangle
    # tail; positive = tail curves clockwise around the body when
    # viewed tip-up; negative = counter-clockwise. Rendered via
    # quadratic bezier sides instead of straight lines.
    tail_curve: float = 0.0
    # Stroke alignment for shape outlines. "center" (default) is Qt's
    # native behavior - the pen centers on the edge. "inside" draws the
    # stroke entirely inside the shape's bounds; "outside" entirely
    # outside. Matters for pixel-perfect alignment against image edges.
    stroke_align: str = "center"
    # Layer organization tag color. Empty = no tag. Rendered as a
    # small colored dot in the layer panel prefix so users can group
    # related overlays visually. Accepted values: red / orange /
    # yellow / green / blue / purple / pink / gray, or a hex string.
    tag_color: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CanvasOverlay":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class ReleaseStep:
    """One step in a staggered release chain."""
    platform: str = ""          # platform ID or account ID
    delay_hours: int = 0        # hours after the anchor (first step)
    account_id: str = ""        # specific OneUp connected account ID
    caption_key: str = ""       # key into SocialPost.captions for this step
    status: str = "pending"     # pending, posted, skipped
    posted_at: str = ""         # ISO timestamp when actually posted
    tier_level: str = ""        # "free", "basic", "premium"
    locale: str = ""            # "en" or "ja"

    def to_dict(self) -> dict:
        return {
            "platform": self.platform, "delay_hours": self.delay_hours,
            "account_id": self.account_id, "caption_key": self.caption_key,
            "status": self.status, "posted_at": self.posted_at,
            "tier_level": self.tier_level, "locale": self.locale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReleaseStep":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class EngagementWindow:
    """A scheduled engagement check after a post goes live."""
    post_id: str = ""
    platform: str = ""
    account_id: str = ""
    check_at: str = ""          # ISO datetime
    action: str = ""            # "first_reactions", "peak_engagement", "follow_up", "next_day", "metrics"
    url: str = ""               # URL to open (profile page)
    done: bool = False
    notes: str = ""             # engagement advice

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "EngagementWindow":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class CampaignMilestone:
    """A milestone in a campaign's preparation timeline."""
    id: str = ""
    label: str = ""            # e.g. "Art assets finalized", "Page goes live"
    due_date: str = ""         # ISO date
    completed: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "due_date": self.due_date,
                "completed": self.completed, "notes": self.notes}

    @classmethod
    def from_dict(cls, d: dict) -> "CampaignMilestone":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Campaign:
    """A publishing campaign (Kickstarter launch, Steam release, merch drop)."""
    id: str = ""
    name: str = ""             # e.g. "Kickstarter Volume 2"
    platform_id: str = ""      # links to PLATFORMS key
    launch_date: str = ""      # ISO date
    end_date: str = ""         # ISO date
    status: str = "planning"   # planning, preparing, live, completed, cancelled
    milestones: list[CampaignMilestone] = field(default_factory=list)
    linked_post_ids: list[str] = field(default_factory=list)  # SocialPost IDs
    notes: str = ""
    color: str = ""            # accent color for Gantt display

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "platform_id": self.platform_id,
            "launch_date": self.launch_date, "end_date": self.end_date,
            "status": self.status,
            "milestones": [m.to_dict() for m in self.milestones],
            "linked_post_ids": self.linked_post_ids,
            "notes": self.notes, "color": self.color,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Campaign":
        milestones = [CampaignMilestone.from_dict(m) for m in d.get("milestones", [])]
        return cls(
            id=d.get("id", ""), name=d.get("name", ""),
            platform_id=d.get("platform_id", ""),
            launch_date=d.get("launch_date", ""), end_date=d.get("end_date", ""),
            status=d.get("status", "planning"), milestones=milestones,
            linked_post_ids=d.get("linked_post_ids", []),
            notes=d.get("notes", ""), color=d.get("color", ""),
        )


@dataclass(slots=True)
class PlatformAssignment:
    """Tracks an asset assigned to a specific platform slot."""
    platform: str = ""
    slot: str = ""          # e.g. "header", "capsule", "gallery_1"
    status: str = PostStatus.PENDING
    crop: Optional[CropRegion] = None
    notes: str = ""
    campaign_id: str = ""  # links assignment to a specific campaign


@dataclass
class CollectionIdentity:
    name: str = ""
    voice: str = ""
    hashtags: list[str] = field(default_factory=list)
    default_platforms: list[str] = field(default_factory=list)
    gumroad_url: str = ""
    patreon_url: str = ""
    fanbox_url: str = ""        # Pixiv Fanbox creator page
    fantia_url: str = ""        # Fantia creator page
    cien_url: str = ""          # Ci-en/DLsite creator page
    kofi_url: str = ""          # Ko-fi page
    subscribestar_url: str = "" # SubscribeStar page
    kickstarter_url: str = ""   # Kickstarter project page
    indiegogo_url: str = ""     # Indiegogo project page
    voice_ja: str = ""          # Japanese brand voice
    hashtags_ja: list[str] = field(default_factory=list)  # Japanese hashtags
    bio_blurb: str = ""
    content_notes: str = ""
    chrome_profiles: dict = field(default_factory=dict)  # account_id -> Chrome profile directory name
    # Per-platform API credentials. Shape: platform_id -> {key: value}.
    # Only populated for free-tier APIs (app passwords / personal
    # access tokens). Examples:
    #   bluesky:  {"handle": "alice.bsky.social", "app_password": "..."}
    #   mastodon: {"instance": "mastodon.example", "access_token": "..."}
    # Read via get_credentials(); the bridge's /doxyedit-api-post
    # endpoint uses these when the caller doesn't supply its own.
    credentials: dict = field(default_factory=dict)

    def get_credentials(self, platform_id: str) -> dict:
        """Return the per-platform credential dict, empty if missing.
        Always returns a dict so callers can safely do `.get(key)`."""
        creds = self.credentials.get(platform_id)
        return creds if isinstance(creds, dict) else {}


@dataclass
class SubPlatform:
    """A subscription/monetization platform for semi-automated posting."""
    id: str = ""
    name: str = ""
    locale: str = "en"           # "en" or "ja"
    post_url_template: str = ""  # "{base_url}/posts/new"
    needs_censor: bool = False   # Japanese platforms need mosaic
    monetization_type: str = ""  # "subscription", "product", "tips"
    tier_support: bool = False
    url_field: str = ""          # which CollectionIdentity field holds the URL


# Platforms with direct API posting (not via OneUp, not semi-auto browser)
DIRECT_POST_PLATFORMS: dict[str, str] = {
    "discord_webhook": "Discord (Webhook)",
    "telegram": "Telegram",
    "bluesky": "Bluesky",
}


@dataclass
class SubredditConfig:
    """A subreddit with its posting rules and metadata."""
    name: str = ""              # e.g. "hentai", "rule34"
    flair_id: str = ""          # Reddit flair ID
    flair_text: str = ""        # Display text for flair
    nsfw: bool = True
    title_template: str = ""    # e.g. "{character} [OC]"
    rules_notes: str = ""       # Free-text posting rules
    min_interval_days: int = 0  # Cooldown between posts
    last_posted: str = ""       # ISO date
    tags_required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SubredditConfig":
        fields = {f.name: f.default if f.default is not MISSING
                  else f.default_factory() for f in cls.__dataclass_fields__.values()}
        return cls(**{k: d.get(k, v) for k, v in fields.items()})


SUB_PLATFORMS: dict[str, SubPlatform] = {
    "patreon": SubPlatform("patreon", "Patreon", "en", "{base_url}/posts/new", False, "subscription", True, "patreon_url"),
    "fanbox": SubPlatform("fanbox", "Pixiv Fanbox", "ja", "{base_url}/manage/posts/new", True, "subscription", True, "fanbox_url"),
    "fantia": SubPlatform("fantia", "Fantia", "ja", "{base_url}/posts/new", True, "subscription", True, "fantia_url"),
    "cien": SubPlatform("cien", "Ci-en", "ja", "{base_url}/creator/posting", True, "subscription", True, "cien_url"),
    "gumroad": SubPlatform("gumroad", "Gumroad", "en", "https://gumroad.com/products/new", False, "product", False, "gumroad_url"),
    "kofi": SubPlatform("kofi", "Ko-fi", "en", "https://ko-fi.com/post/create", False, "tips", True, "kofi_url"),
    "subscribestar": SubPlatform("subscribestar", "SubscribeStar", "en", "{base_url}/posts/new", False, "subscription", True, "subscribestar_url"),
    "kickstarter": SubPlatform("kickstarter", "Kickstarter", "en", "{base_url}/updates/new", False, "crowdfunding", False, "kickstarter_url"),
    "indiegogo": SubPlatform("indiegogo", "Indiegogo", "en", "{base_url}/edit/updates/new", False, "crowdfunding", False, "indiegogo_url"),
}


@dataclass
class PostMetrics:
    """Engagement metrics for a posted social media post."""
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    views: int = 0
    clicks: int = 0
    last_checked: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PostMetrics":
        return cls(**{k: d.get(k, getattr(cls, k, 0) if k != "last_checked" else "") for k in cls.__dataclass_fields__})


@dataclass
class SocialPost:
    id: str = ""
    asset_ids: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    captions: dict[str, str] = field(default_factory=dict)
    caption_default: str = ""
    links: list[str] = field(default_factory=list)
    scheduled_time: str = ""
    status: str = SocialPostStatus.DRAFT
    platform_status: dict[str, str] = field(default_factory=dict)
    oneup_post_id: str = ""
    reply_templates: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""
    collection: str = ""
    strategy_notes: str = ""  # AI-generated posting strategy, advice, long-term vision
    nsfw_platforms: list[str] = field(default_factory=list)  # platforms that get NSFW/uncensored version
    sfw_asset_ids: list[str] = field(default_factory=list)   # alternate censored asset IDs (empty = auto-censor)
    tier_assets: dict = field(default_factory=dict)  # tier_name -> [asset_ids]
    sub_platform_status: dict = field(default_factory=dict)  # platform_id -> {status, posted_at}
    campaign_id: str = ""  # links post to a campaign for promo tracking
    category_id: str = ""  # OneUp category ID for posting
    release_chain: list[ReleaseStep] = field(default_factory=list)
    published_urls: dict = field(default_factory=dict)           # platform_id -> post URL
    engagement_checks: list[dict] = field(default_factory=list)  # list of EngagementWindow dicts
    censor_mode: str = "auto"  # "auto" | "uncensored" | "custom"
    platform_censor: dict[str, bool] = field(default_factory=dict)  # platform_id -> should_censor
    platform_metrics: dict[str, dict] = field(default_factory=dict)  # platform_id -> PostMetrics dict

    def to_dict(self) -> dict:
        return {
            "id": self.id, "asset_ids": self.asset_ids, "platforms": self.platforms,
            "captions": self.captions, "caption_default": self.caption_default,
            "links": self.links, "scheduled_time": self.scheduled_time,
            "status": self.status, "platform_status": self.platform_status,
            "oneup_post_id": self.oneup_post_id, "reply_templates": self.reply_templates,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "notes": self.notes, "collection": self.collection,
            "strategy_notes": self.strategy_notes,
            "nsfw_platforms": self.nsfw_platforms,
            "sfw_asset_ids": self.sfw_asset_ids,
            "tier_assets": self.tier_assets,
            "sub_platform_status": self.sub_platform_status,
            "campaign_id": self.campaign_id,
            "category_id": self.category_id,
            "release_chain": [s.to_dict() for s in self.release_chain],
            "published_urls": self.published_urls,
            "engagement_checks": self.engagement_checks,
            "censor_mode": self.censor_mode,
            "platform_censor": self.platform_censor,
            "platform_metrics": self.platform_metrics,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SocialPost":
        return cls(
            id=d.get("id", ""), asset_ids=d.get("asset_ids", []),
            platforms=d.get("platforms", []), captions=d.get("captions", {}),
            caption_default=d.get("caption_default", ""), links=d.get("links", []),
            scheduled_time=d.get("scheduled_time", ""),
            status=d.get("status", SocialPostStatus.DRAFT),
            platform_status=d.get("platform_status", {}),
            oneup_post_id=d.get("oneup_post_id", ""),
            reply_templates=d.get("reply_templates", []),
            created_at=d.get("created_at", ""), updated_at=d.get("updated_at", ""),
            notes=d.get("notes", ""), collection=d.get("collection", ""),
            strategy_notes=d.get("strategy_notes", ""),
            nsfw_platforms=d.get("nsfw_platforms", []),
            sfw_asset_ids=d.get("sfw_asset_ids", []),
            tier_assets=d.get("tier_assets", {}),
            sub_platform_status=d.get("sub_platform_status", {}),
            campaign_id=d.get("campaign_id", ""),
            category_id=d.get("category_id", ""),
            release_chain=[ReleaseStep.from_dict(s) for s in d.get("release_chain", [])],
            published_urls=d.get("published_urls", {}),
            engagement_checks=d.get("engagement_checks", []),
            censor_mode=d.get("censor_mode", "auto"),
            platform_censor=d.get("platform_censor", {}),
            platform_metrics=d.get("platform_metrics", {}),
        )


@dataclass(slots=True)
class Asset:
    """A single image asset in the project.
    slots=True saves ~30% memory per instance and speeds up attribute
    access. At 67k assets the dict-overhead saving is real."""
    id: str = ""
    source_path: str = ""       # original file path
    source_folder: str = ""     # which folder it came from
    starred: int = 0  # 0=off, 1-5=color rating
    crops: list[CropRegion] = field(default_factory=list)
    censors: list[CensorRegion] = field(default_factory=list)
    overlays: list[CanvasOverlay] = field(default_factory=list)
    assignments: list[PlatformAssignment] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    specs: dict = field(default_factory=dict)  # CLI/tool metadata (size, relations, etc.)
    variant_exports: dict[str, str] = field(default_factory=dict)  # "platform_slot" → export path
    # Studio drag-out guides: list of {"orientation": "h"|"v", "position": int}
    guides: list = field(default_factory=list)

    @property
    def stem(self) -> str:
        return Path(self.source_path).stem

    @property
    def name(self) -> str:
        return Path(self.source_path).name

    def cycle_star(self):
        """Cycle star rating: 0 → 1 → 2 → 3 → 4 → 5 → 0."""
        self.starred = (self.starred + 1) % 6


def toggle_tags(assets: list[Asset], tag_id: str) -> bool:
    """Toggle a tag on a list of assets. Returns True if tag was added, False if removed."""
    all_have = all(tag_id in a.tags for a in assets)
    for a in assets:
        if all_have:
            if tag_id in a.tags:
                a.tags.remove(tag_id)
        else:
            if tag_id not in a.tags:
                a.tags.append(tag_id)
    return not all_have


@dataclass
class PlatformSlot:
    """A named slot within a platform that needs an image."""
    name: str = ""
    label: str = ""
    width: int = 0
    height: int = 0
    required: bool = True
    description: str = ""


@dataclass
class Platform:
    """A target platform with its image requirements."""
    id: str = ""
    name: str = ""
    slots: list[PlatformSlot] = field(default_factory=list)
    export_prefix: str = ""     # filename prefix for exports
    needs_censor: bool = False  # e.g. Japan versions


# ---- Built-in platform definitions ----

PLATFORMS: dict[str, Platform] = {
    "kickstarter": Platform(
        id="kickstarter",
        name="Kickstarter",
        export_prefix="ks",
        slots=[
            PlatformSlot("header", "Project Header", 1024, 576, True, "Main project image"),
            PlatformSlot("gallery_1", "Gallery 1", 1024, 576, False, "Gallery image"),
            PlatformSlot("gallery_2", "Gallery 2", 1024, 576, False, "Gallery image"),
            PlatformSlot("gallery_3", "Gallery 3", 1024, 576, False, "Gallery image"),
            PlatformSlot("avatar", "Creator Avatar", 200, 200, False, "Your profile pic"),
        ],
    ),
    "steam": Platform(
        id="steam",
        name="Steam",
        export_prefix="steam",
        slots=[
            PlatformSlot("capsule_main", "Main Capsule", 460, 215, True, "Store page capsule"),
            PlatformSlot("capsule_small", "Small Capsule", 231, 87, True, "Browse capsule"),
            PlatformSlot("header", "Header Capsule", 460, 215, True, "Header image"),
            PlatformSlot("hero", "Hero Graphic", 3840, 1240, False, "Library hero"),
            PlatformSlot("logo", "Logo", 1280, 720, False, "Library logo"),
            PlatformSlot("page_bg", "Page Background", 1438, 810, False, "Store page background"),
            PlatformSlot("screenshot_1", "Screenshot 1", 1920, 1080, True, "Store screenshot"),
            PlatformSlot("screenshot_2", "Screenshot 2", 1920, 1080, False, "Store screenshot"),
            PlatformSlot("screenshot_3", "Screenshot 3", 1920, 1080, False, "Store screenshot"),
            PlatformSlot("screenshot_4", "Screenshot 4", 1920, 1080, False, "Store screenshot"),
            PlatformSlot("screenshot_5", "Screenshot 5", 1920, 1080, False, "Store screenshot"),
        ],
    ),
    "patreon": Platform(
        id="patreon",
        name="Patreon",
        export_prefix="patreon",
        slots=[
            PlatformSlot("banner", "Page Banner", 1600, 400, True, "Profile banner"),
            PlatformSlot("avatar", "Avatar", 256, 256, False, "Profile picture"),
            PlatformSlot("post_image", "Post Image", 1920, 1080, False, "Tier/post image"),
        ],
    ),
    "twitter": Platform(
        id="twitter",
        name="Twitter / X",
        export_prefix="tw",
        slots=[
            PlatformSlot("post", "Post Image", 1200, 675, False, "Tweet image (16:9)"),
            PlatformSlot("header", "Profile Header", 1500, 500, False, "Profile banner"),
            PlatformSlot("avatar", "Avatar", 400, 400, False, "Profile pic"),
        ],
    ),
    "reddit": Platform(
        id="reddit",
        name="Reddit",
        export_prefix="reddit",
        slots=[
            PlatformSlot("post", "Post Image", 1200, 900, False, "Post image"),
            PlatformSlot("banner", "Subreddit Banner", 4000, 192, False, "Community banner"),
        ],
    ),
    "instagram": Platform(
        id="instagram",
        name="Instagram",
        export_prefix="ig",
        slots=[
            PlatformSlot("post_square", "Square Post", 1080, 1080, False, "Feed post (1:1)"),
            PlatformSlot("post_portrait", "Portrait Post", 1080, 1350, False, "Feed post (4:5)"),
            PlatformSlot("story", "Story", 1080, 1920, False, "Story (9:16)"),
        ],
    ),
    "kickstarter_jp": Platform(
        id="kickstarter_jp",
        name="Kickstarter (Japan)",
        export_prefix="ks_jp",
        needs_censor=True,
        slots=[
            PlatformSlot("header", "Project Header", 1024, 576, True, "Main project image (censored)"),
            PlatformSlot("gallery_1", "Gallery 1", 1024, 576, False, "Gallery image (censored)"),
            PlatformSlot("gallery_2", "Gallery 2", 1024, 576, False, "Gallery image (censored)"),
        ],
    ),
}


def load_config(project_dir: str) -> dict:
    """Load config.yaml from project directory if present. Returns merged platform dict."""
    config_path = Path(project_dir) / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def merge_platforms(config: dict) -> dict[str, 'Platform']:
    """Merge custom platform definitions from config into built-in PLATFORMS."""
    merged = dict(PLATFORMS)
    custom_platforms = config.get("platforms", {})
    if not isinstance(custom_platforms, dict):
        return merged
    for pid, pdata in custom_platforms.items():
        if not isinstance(pdata, dict):
            continue
        slots = []
        for sdata in pdata.get("slots", []):
            if not isinstance(sdata, dict):
                continue
            slots.append(PlatformSlot(
                name=sdata.get("name", "slot"),
                label=sdata.get("label", sdata.get("name", "Slot")),
                width=int(sdata.get("width", 1080)),
                height=int(sdata.get("height", 1080)),
                required=bool(sdata.get("required", False)),
                description=sdata.get("description", ""),
            ))
        merged[pid] = Platform(
            id=pid,
            name=pdata.get("name", pid),
            export_prefix=pdata.get("export_prefix", pid),
            needs_censor=bool(pdata.get("needs_censor", False)),
            slots=slots,
        )
    return merged


CONFIG_TEMPLATE = """# DoxyEdit Project Config
# Add custom platforms here. They will appear alongside built-in platforms.
# Restart the app or reload the project after editing.

platforms:
  # Example custom platform:
  # my_platform:
  #   name: "My Platform"
  #   export_prefix: "myp"
  #   needs_censor: false
  #   slots:
  #     - name: "header"
  #       label: "Header Image"
  #       width: 1200
  #       height: 630
  #       required: true
  #       description: "Main header banner"
  #     - name: "avatar"
  #       label: "Profile Avatar"
  #       width: 400
  #       height: 400
  #       required: false
"""


# ---- Project file I/O ----

@dataclass
class Project:
    """Top-level project — serializes to .doxyproj.json."""
    name: str = "Untitled"
    assets: list[Asset] = field(default_factory=list)
    platforms: list[str] = field(default_factory=lambda: list(PLATFORMS.keys()))
    custom_tags: list[dict] = field(default_factory=list)  # legacy — migrated to tag_definitions
    tag_definitions: dict[str, dict] = field(default_factory=dict)  # id → {label, color, group}
    tag_aliases: dict[str, str] = field(default_factory=dict)  # old_id → canonical_id
    custom_shortcuts: dict[str, str] = field(default_factory=dict)  # key → tag_id
    hidden_tags: list[str] = field(default_factory=list)  # tags hidden from side panel
    eye_hidden_tags: list[str] = field(default_factory=list)  # tags with eye off (filter from grid)
    sort_mode: str = "Name A-Z"
    tray_items: list | dict = field(default_factory=list)  # list[str] or dict[str, list[str]] for named trays
    notes: str = ""
    sub_notes: dict = field(default_factory=dict)  # tab_name → markdown content (tabbed notes)
    accent_color: str = ""  # project-level accent override (hex, e.g. "#7ca1c0")
    theme_id: str = ""  # per-project theme override (empty = use app default)
    checklist: list[str] = field(default_factory=list)  # posting checklist items (prefix "[ ] " or "[x] ")
    excluded_paths: set[str] = field(default_factory=set)  # paths permanently excluded (moved/deleted)
    import_sources: list[dict] = field(default_factory=list)  # [{type, path, recursive, added_at}]
    folder_presets: list[dict] = field(default_factory=list)  # [{id, name, folders: [str]}]
    filter_presets: list[dict] = field(default_factory=list)  # [{name, icon, state: {filter dict}}]
    local_mode: bool = False  # store paths relative to project file (for repo/multi-PC use)
    posts: list[SocialPost] = field(default_factory=list)
    identity: dict = field(default_factory=dict)
    oneup_config: dict = field(default_factory=dict)
    default_overlays: list[dict] = field(default_factory=list)  # project-wide overlay presets
    release_templates: list[dict] = field(default_factory=list)  # reusable release chain templates
    identities: dict = field(default_factory=dict)  # name -> CollectionIdentity dict + patreon_schedule
    blackout_periods: list[dict] = field(default_factory=list)
    # Each: {"start": "2026-05-01", "end": "2026-05-07", "label": "KS launch", "scope": "all"}
    campaigns: list[Campaign] = field(default_factory=list)
    subreddits: list[SubredditConfig] = field(default_factory=list)

    def get_tags(self) -> dict[str, TagPreset]:
        """Get merged tag presets — defaults + tag_definitions + legacy custom_tags."""
        tags = dict(TAG_ALL)
        # New-style tag_definitions (preferred)
        for tid, defn in self.tag_definitions.items():
            if isinstance(defn, dict):
                tags[tid] = TagPreset.from_dict(tid, defn)
        # Legacy custom_tags (backward compat — migrated on save)
        for ct in self.custom_tags:
            if not isinstance(ct, dict):
                continue
            try:
                tid = ct["id"]
                if tid not in tags:
                    tags[tid] = TagPreset.from_dict(tid, ct)
            except (KeyError, TypeError):
                continue
        return tags

    @staticmethod
    def _to_rel(abs_path: str, base: Path) -> str:
        """Convert absolute path to POSIX-relative. Falls back to absolute on different drive."""
        try:
            return Path(abs_path).relative_to(base).as_posix()
        except ValueError:
            return abs_path

    @staticmethod
    def _to_abs(stored: str, base: Path) -> str:
        """Resolve a stored path against base. If already absolute, return as-is."""
        p = Path(stored)
        if p.is_absolute():
            return stored
        return str((base / p).resolve())

    def _migrate_custom_tags(self):
        """One-time UI-thread mutation. Call before background save so the
        worker thread doesn't have to mutate tag_definitions."""
        for ct in self.custom_tags:
            if isinstance(ct, dict) and ct.get("id") and ct["id"] not in self.tag_definitions:
                self.tag_definitions[ct["id"]] = {
                    "label": ct.get("label", ct["id"]),
                    "color": ct.get("color", "#888"),
                }
                if ct.get("width"): self.tag_definitions[ct["id"]]["width"] = ct["width"]
                if ct.get("height"): self.tag_definitions[ct["id"]]["height"] = ct["height"]
                if ct.get("ratio"): self.tag_definitions[ct["id"]]["ratio"] = ct["ratio"]

    def build_save_dict(self, path: str) -> dict:
        """Build the save payload as a plain dict. Reads Project state but
        does not mutate it - safe to call from any thread provided the
        caller has run _migrate_custom_tags first on the UI thread.

        Edits to assets concurrent with this call are racey but not
        corrupting: at worst, one asset's saved entry reflects a stale
        snapshot. The next autosave fixes it.
        """
        base = Path(path).parent

        def _asset_dict(a):
            d = asdict(a)
            if self.local_mode:
                d["source_path"]   = self._to_rel(a.source_path, base)
                d["source_folder"] = self._to_rel(a.source_folder, base) if a.source_folder else ""
            d["overlays"] = [ov.to_dict() for ov in a.overlays]
            return d

        data = {
            "_comment": "DoxyEdit project — edit with Claude CLI or by hand",
            "name": self.name,
            "notes": self.notes,
            "sub_notes": self.sub_notes,
            "local_mode": self.local_mode,
            "platforms": self.platforms,
            "tag_definitions": self.tag_definitions,
            "tag_aliases": self.tag_aliases,
            "custom_tags": self.custom_tags,  # kept for backward compat
            "custom_shortcuts": self.custom_shortcuts,
            "hidden_tags": self.hidden_tags,
            "eye_hidden_tags": self.eye_hidden_tags,
            "sort_mode": self.sort_mode,
            "tray_items": self.tray_items,
            "accent_color": self.accent_color,
            "theme_id": self.theme_id,
            "checklist": self.checklist,
            "excluded_paths": sorted(
                self._to_rel(p, base) if self.local_mode else p
                for p in self.excluded_paths),
            "import_sources": [
                {**src, "path": self._to_rel(src["path"], base) if self.local_mode else src["path"]}
                for src in self.import_sources],
            "folder_presets": self.folder_presets,
            "filter_presets": self.filter_presets,
            "posts": [p.to_dict() for p in self.posts],
            "identity": self.identity,
            "oneup_config": self.oneup_config,
            "default_overlays": self.default_overlays,
            "release_templates": self.release_templates,
            "identities": self.identities,
            "blackout_periods": self.blackout_periods,
            "campaigns": [c.to_dict() for c in self.campaigns],
            "subreddits": [s.to_dict() for s in self.subreddits],
            "assets": [_asset_dict(a) for a in self.assets],
        }
        return data

    @staticmethod
    def write_save_dict(data: dict, path: str, *, compact: bool = False):
        """Serialize a save payload + atomic write. Safe to call from a
        background thread - touches no Project state, no Qt objects."""
        if compact:
            payload = json.dumps(data, separators=(",", ":"), default=str, ensure_ascii=False)
        else:
            payload = json.dumps(data, indent=2, default=str, ensure_ascii=False)
        tmp = Path(path).with_suffix(Path(path).suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(str(tmp), str(path))

    def save(self, path: str, *, compact: bool = False):
        """Synchronous save. Use BackgroundSaver for autosave on big projects."""
        self._migrate_custom_tags()
        data = self.build_save_dict(path)
        self.write_save_dict(data, path, compact=compact)

    @classmethod
    def load(cls, path: str) -> "Project":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        base = Path(path).parent
        local = bool(raw.get("local_mode", False))
        proj = cls(
            name=raw.get("name", "Untitled"),
            notes=raw.get("notes", ""),
            sub_notes=raw.get("sub_notes", {}),
            local_mode=local,
            platforms=raw.get("platforms", list(PLATFORMS.keys())),
            custom_tags=raw.get("custom_tags", []),
            tag_definitions=raw.get("tag_definitions", {}),
            tag_aliases=raw.get("tag_aliases", {}),
            custom_shortcuts=raw.get("custom_shortcuts", {}),
            hidden_tags=raw.get("hidden_tags", []),
            eye_hidden_tags=raw.get("eye_hidden_tags", []),
            sort_mode=raw.get("sort_mode", "Name A-Z"),
            tray_items=raw.get("tray_items", []),
            accent_color=raw.get("accent_color", ""),
            theme_id=raw.get("theme_id", ""),
            checklist=raw.get("checklist", []),
            excluded_paths={
                cls._to_abs(p, base) if local else p
                for p in raw.get("excluded_paths", [])},
            import_sources=[
                {**src, "path": cls._to_abs(src["path"], base) if local else src["path"]}
                for src in raw.get("import_sources", [])],
            folder_presets=raw.get("folder_presets", []),
            filter_presets=raw.get("filter_presets", []),
        )
        proj.identity = raw.get("identity", {})
        proj.oneup_config = raw.get("oneup_config", {})
        proj.default_overlays = raw.get("default_overlays", [])
        proj.release_templates = raw.get("release_templates", [])
        proj.identities = raw.get("identities", {})
        proj.blackout_periods = raw.get("blackout_periods", [])
        for c in raw.get("campaigns", []):
            proj.campaigns.append(Campaign.from_dict(c))
        for s in raw.get("subreddits", []):
            proj.subreddits.append(SubredditConfig.from_dict(s))
        for p in raw.get("posts", []):
            proj.posts.append(SocialPost.from_dict(p))

        # Load config.yaml and merge custom platforms
        config = load_config(str(base))
        if config:
            proj._custom_platforms = merge_platforms(config)
        else:
            proj._custom_platforms = {}

        aliases = proj.tag_aliases
        for a in raw.get("assets", []):
            # Resolve tag aliases
            raw_tags = a.get("tags", [])
            if aliases:
                seen: set[str] = set()
                resolved = []
                for t in raw_tags:
                    canonical = aliases.get(t, t)
                    if canonical not in seen:
                        seen.add(canonical)
                        resolved.append(canonical)
                raw_tags = resolved
            raw_notes = a.get("notes", "")
            raw_specs = a.get("specs", {})
            # Auto-migrate CLI-generated notes to specs
            if raw_notes and not raw_specs and re.match(r'^\d+x\d+', raw_notes.strip()):
                raw_specs["cli_info"] = raw_notes.strip()
                raw_notes = ""
            raw_sp = a.get("source_path", "")
            raw_sf = a.get("source_folder", "")
            asset = Asset(
                id=a.get("id", ""),
                source_path=cls._to_abs(raw_sp, base) if local and raw_sp else raw_sp,
                source_folder=cls._to_abs(raw_sf, base) if local and raw_sf else raw_sf,
                starred=int(a.get("starred", 0)) if not isinstance(a.get("starred"), bool) else (1 if a.get("starred") else 0),
                tags=raw_tags,
                notes=raw_notes,
                specs=raw_specs,
            )
            for c in a.get("crops", []):
                asset.crops.append(CropRegion(**c))
            for c in a.get("censors", []):
                asset.censors.append(CensorRegion(**{k: v for k, v in c.items() if k in CensorRegion.__dataclass_fields__}))
            for ov in a.get("overlays", []):
                asset.overlays.append(CanvasOverlay.from_dict(ov))
            for p in a.get("assignments", []):
                pa = PlatformAssignment(
                    platform=p.get("platform", ""),
                    slot=p.get("slot", ""),
                    status=p.get("status", PostStatus.PENDING),
                    notes=p.get("notes", ""),
                    campaign_id=p.get("campaign_id", ""),
                )
                if p.get("crop"):
                    pa.crop = CropRegion(**p["crop"])
                asset.assignments.append(pa)
            proj.assets.append(asset)
        # Eager-build indexes so the first refresh after load doesn't pay
        # the index-build cost during the user's first interaction.
        proj._ensure_indexes()
        return proj

    def get_post(self, post_id: str) -> Optional[SocialPost]:
        for p in self.posts:
            if p.id == post_id:
                return p
        return None

    def get_campaign(self, campaign_id: str) -> "Campaign | None":
        for c in self.campaigns:
            if c.id == campaign_id:
                return c
        return None

    def get_identity(self) -> CollectionIdentity:
        return CollectionIdentity(**self.identity) if self.identity else CollectionIdentity()

    def get_platforms(self) -> dict:
        """Get merged platforms (built-in + config.yaml custom)."""
        if hasattr(self, '_custom_platforms') and self._custom_platforms:
            return self._custom_platforms
        return dict(PLATFORMS)

    def invalidate_index(self):
        """Clear cached indexes. Idempotent - does NOT bump version. Safe
        to call from non-mutating refresh paths."""
        self._asset_index = None
        self._path_index = None
        self._tag_users = None

    def mark_mutated(self):
        """Call this after any mutation of self.assets or asset.tags /
        source_path. Clears indexes AND bumps version so filter caches
        keyed on version know to recompute."""
        self.invalidate_index()
        self._version = getattr(self, '_version', 0) + 1

    def _ensure_indexes(self):
        if not getattr(self, '_asset_index', None):
            self._asset_index = {a.id: a for a in self.assets}
        if getattr(self, '_path_index', None) is None:
            self._path_index = {a.source_path for a in self.assets}
        if getattr(self, '_tag_users', None) is None:
            d: dict[str, set] = {}
            for a in self.assets:
                for t in a.tags:
                    d.setdefault(t, set()).add(a.id)
            self._tag_users = d

    def get_asset(self, asset_id: str) -> Optional[Asset]:
        self._ensure_indexes()
        return self._asset_index.get(asset_id)

    @property
    def path_index(self) -> set:
        """Set of source_paths for fast existence checks during import."""
        self._ensure_indexes()
        return self._path_index

    @property
    def tag_users(self) -> dict:
        """tag_id -> set[asset_id]. Inverted index."""
        self._ensure_indexes()
        return self._tag_users

    @property
    def version(self) -> int:
        """Mutation counter for cache invalidation keys."""
        return getattr(self, '_version', 0)

    def summary(self) -> dict:
        """Quick status summary — useful for Claude CLI queries."""
        total = len(self.assets)
        starred = sum(1 for a in self.assets if a.starred)
        by_platform = {}
        for pid in self.platforms:
            p = PLATFORMS.get(pid)
            if not p:
                continue
            assigned = 0
            posted = 0
            for a in self.assets:
                for pa in a.assignments:
                    if pa.platform == pid:
                        assigned += 1
                        if pa.status == PostStatus.POSTED:
                            posted += 1
            by_platform[pid] = {
                "name": p.name,
                "assigned": assigned,
                "posted": posted,
                "slots_total": len(p.slots),
                "slots_required": sum(1 for s in p.slots if s.required),
            }
        return {
            "total_assets": total,
            "starred": starred,
            "needs_censor": sum(1 for a in self.assets if a.censors),
            "platforms": by_platform,
        }
