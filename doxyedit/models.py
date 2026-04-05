"""Central data model — everything saves to readable JSON."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


class PostStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    POSTED = "posted"
    SKIP = "skip"


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
TAG_SHORTCUTS: dict[str, str] = {
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


@dataclass
class CropRegion:
    """A rectangular crop selection on an asset."""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    label: str = ""


@dataclass
class CensorRegion:
    """A non-destructive censor overlay rectangle."""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    style: str = "black"  # "black", "blur", "pixelate"


@dataclass
class PlatformAssignment:
    """Tracks an asset assigned to a specific platform slot."""
    platform: str = ""
    slot: str = ""          # e.g. "header", "capsule", "gallery_1"
    status: str = PostStatus.PENDING
    crop: Optional[CropRegion] = None
    notes: str = ""


@dataclass
class Asset:
    """A single image asset in the project."""
    id: str = ""
    source_path: str = ""       # original file path
    source_folder: str = ""     # which folder it came from
    starred: int = 0  # 0=off, 1-5=color rating
    crops: list[CropRegion] = field(default_factory=list)
    censors: list[CensorRegion] = field(default_factory=list)
    assignments: list[PlatformAssignment] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""

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
    tray_items: list[str] = field(default_factory=list)  # asset IDs in work tray
    notes: str = ""

    def get_tags(self) -> dict[str, TagPreset]:
        """Get merged tag presets — defaults + tag_definitions + legacy custom_tags."""
        tags = dict(TAG_ALL)
        # New-style tag_definitions (preferred)
        for tid, defn in self.tag_definitions.items():
            if not isinstance(defn, dict):
                continue
            tags[tid] = TagPreset(
                id=tid, label=defn.get("label", tid),
                width=defn.get("width"), height=defn.get("height"),
                ratio=defn.get("ratio", ""), color=defn.get("color", "#888"),
            )
        # Legacy custom_tags (backward compat — migrated on save)
        for ct in self.custom_tags:
            if not isinstance(ct, dict):
                continue
            try:
                tid = ct["id"]
                if tid not in tags:  # don't overwrite tag_definitions
                    tags[tid] = TagPreset(
                        id=tid, label=ct.get("label", tid),
                        width=ct.get("width"), height=ct.get("height"),
                        ratio=ct.get("ratio", ""), color=ct.get("color", "#888"),
                    )
            except (KeyError, TypeError):
                continue
        return tags

    def save(self, path: str):
        # Migrate any legacy custom_tags into tag_definitions before saving
        for ct in self.custom_tags:
            if isinstance(ct, dict) and ct.get("id") and ct["id"] not in self.tag_definitions:
                self.tag_definitions[ct["id"]] = {
                    "label": ct.get("label", ct["id"]),
                    "color": ct.get("color", "#888"),
                }
                if ct.get("width"): self.tag_definitions[ct["id"]]["width"] = ct["width"]
                if ct.get("height"): self.tag_definitions[ct["id"]]["height"] = ct["height"]
                if ct.get("ratio"): self.tag_definitions[ct["id"]]["ratio"] = ct["ratio"]
        data = {
            "_comment": "DoxyEdit project — edit with Claude CLI or by hand",
            "name": self.name,
            "notes": self.notes,
            "platforms": self.platforms,
            "tag_definitions": self.tag_definitions,
            "tag_aliases": self.tag_aliases,
            "custom_tags": self.custom_tags,  # kept for backward compat
            "custom_shortcuts": self.custom_shortcuts,
            "hidden_tags": self.hidden_tags,
            "eye_hidden_tags": self.eye_hidden_tags,
            "sort_mode": self.sort_mode,
            "tray_items": self.tray_items,
            "assets": [asdict(a) for a in self.assets],
        }
        Path(path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "Project":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        proj = cls(
            name=raw.get("name", "Untitled"),
            notes=raw.get("notes", ""),
            platforms=raw.get("platforms", list(PLATFORMS.keys())),
            custom_tags=raw.get("custom_tags", []),
            tag_definitions=raw.get("tag_definitions", {}),
            tag_aliases=raw.get("tag_aliases", {}),
            custom_shortcuts=raw.get("custom_shortcuts", {}),
            hidden_tags=raw.get("hidden_tags", []),
            eye_hidden_tags=raw.get("eye_hidden_tags", []),
            sort_mode=raw.get("sort_mode", "Name A-Z"),
            tray_items=raw.get("tray_items", []),
        )
        aliases = proj.tag_aliases
        for a in raw.get("assets", []):
            # Resolve tag aliases
            raw_tags = a.get("tags", [])
            if aliases:
                resolved = []
                for t in raw_tags:
                    canonical = aliases.get(t, t)
                    if canonical not in resolved:
                        resolved.append(canonical)
                raw_tags = resolved
            asset = Asset(
                id=a.get("id", ""),
                source_path=a.get("source_path", ""),
                source_folder=a.get("source_folder", ""),
                starred=int(a.get("starred", 0)) if not isinstance(a.get("starred"), bool) else (1 if a.get("starred") else 0),
                tags=raw_tags,
                notes=a.get("notes", ""),
            )
            for c in a.get("crops", []):
                asset.crops.append(CropRegion(**c))
            for c in a.get("censors", []):
                asset.censors.append(CensorRegion(**c))
            for p in a.get("assignments", []):
                pa = PlatformAssignment(
                    platform=p.get("platform", ""),
                    slot=p.get("slot", ""),
                    status=p.get("status", PostStatus.PENDING),
                    notes=p.get("notes", ""),
                )
                if p.get("crop"):
                    pa.crop = CropRegion(**p["crop"])
                asset.assignments.append(pa)
            proj.assets.append(asset)
        return proj

    def invalidate_index(self):
        """Call after adding/removing assets."""
        self._asset_index = None

    def get_asset(self, asset_id: str) -> Optional[Asset]:
        if not getattr(self, '_asset_index', None):
            self._asset_index = {a.id: a for a in self.assets}
        return self._asset_index.get(asset_id)

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
