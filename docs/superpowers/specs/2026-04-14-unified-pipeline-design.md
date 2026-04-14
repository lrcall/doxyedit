# Unified Content Pipeline — Design Spec

## Problem

DoxyEdit's asset-to-post pipeline is fragmented across 6+ disconnected steps. Image prep (crop/censor/watermark) happens in Studio, post creation in the Composer, and distribution across three separate mechanisms (OneUp, direct API, browser automation). Nothing validates that an asset is ready for a platform before posting. Censor/overlay coordinates break when images are cropped. There's no visibility into what's prepped and what isn't.

## Goal

One unified flow: asset → platform-ready variants → post → live. Works from any entry point (grid right-click, New Post, Studio). Shows readiness at every step. Blocks posting until prep is complete.

---

## 1. Readiness Model

### Per-asset, per-platform readiness score

New function in `models.py`:

```python
def check_readiness(asset: Asset, platform: Platform, post: SocialPost = None) -> dict:
    """Return readiness status for one asset on one platform.
    
    Returns:
        {
            "status": "green" | "yellow" | "red",
            "crop": "ok" | "missing" | "wrong_ratio",
            "censor": "ok" | "not_needed" | "missing",
            "overlay": "ok" | "none_configured",
            "dimensions": "ok" | "too_small" | "wrong_ratio",
            "issues": ["Needs 16:9 crop for Twitter", ...]
        }
    """
```

**Rules:**
- **Green**: Has crop matching platform slot ratio (within 5%), censor regions exist if `platform.needs_censor`, at least one overlay if project has `default_overlays`
- **Yellow**: Image dimensions work but no explicit crop defined (will be auto-fitted), or missing optional overlay
- **Red**: Wrong aspect ratio with no crop, or platform requires censor but asset has none

All indicators are advisory — the user can always post regardless of readiness status. Red means "you probably want to fix this" not "you can't post."

### Where readiness is displayed

1. **Asset grid thumbnails** — colored dot per platform (top-left cluster, like tag dots but for platforms)
2. **Composer platform checklist** — each checked platform shows green/yellow/red next to the checkbox
3. **Pre-queue validation dialog** — blocks Queue with list of issues + one-click fixes

---

## 2. Prep Pipeline (`doxyedit/pipeline.py` — NEW)

Single module that handles the full export chain for any asset+platform combination.

```python
def prepare_for_platform(
    asset: Asset,
    platform_id: str,
    project: Project,
    *,
    censor_override: bool | None = None,  # None = use platform default
    overlay_ids: list[int] | None = None, # None = all enabled overlays
    output_dir: str = "",                  # empty = temp dir
) -> PrepResult:
    """Full pipeline: load → crop → resize → censor → overlay → save.
    
    Returns PrepResult with output_path, dimensions, and any warnings.
    """
```

**Pipeline steps (in order):**
1. **Load** — PSD composite, or Image.open for standard formats
2. **Crop** — Use platform assignment crop if exists, else auto-fit to slot ratio
3. **Resize** — Scale to platform slot dimensions (e.g., 1200x675 for Twitter post)
4. **Censor** — Apply if `platform.needs_censor` or `censor_override=True`. Transform censor coordinates relative to crop bounds
5. **Overlay** — Apply enabled overlays, transform coordinates relative to crop bounds
6. **Save** — To `_exports/{asset_id}/{platform_id}.png` (cached, reused if asset unchanged)

### Coordinate Transform (fixes the crop bug)

Censors and overlays store absolute coordinates on the original image. When cropping:

```python
def _transform_region(region, crop_box, output_size):
    """Transform absolute coords to cropped+resized space."""
    cx, cy, cw, ch = crop_box
    scale_x = output_size[0] / cw
    scale_y = output_size[1] / ch
    return (
        int((region.x - cx) * scale_x),
        int((region.y - cy) * scale_y),
        int(region.w * scale_x),
        int(region.h * scale_y),
    )
```

Regions that fall entirely outside the crop box are skipped.

### Export Cache

```
_exports/
  {asset_id}/
    twitter_post.png      # 1200x675, censored
    instagram_square.png  # 1080x1080, censored
    patreon_post.png      # 1920x1080, uncensored
    _manifest.json        # {platform: {path, dims, mtime, source_mtime}}
```

Cache invalidated when `asset.source_path` mtime changes or crop/censor/overlay config changes. Checked via manifest's `source_mtime` + hash of crop/censor/overlay dicts.

---

## 3. Composer Prep Strip

### New UI section in composer (between asset preview and platforms)

When assets are selected and platforms checked, a **Prep Strip** appears:

```
┌─────────────────────────────────────────────────┐
│ Platform Prep                                    │
│                                                  │
│ Twitter    [preview 16:9]  ● Ready               │
│ Instagram  [preview 1:1]  ● Needs crop  [Fix]   │
│ Patreon    [preview 16:9]  ● Ready (uncensored)  │
│ Fantia     [preview 16:9]  ● Needs censor [Fix]  │
│                                                  │
│ 2 of 4 ready — fix issues to enable Queue        │
└─────────────────────────────────────────────────┘
```

Each row shows:
- Platform name
- Thumbnail preview at actual output aspect ratio (small, ~80px tall)
- Readiness status with colored dot
- **[Fix]** button for yellow/red items — opens inline mini-editor or jumps to Studio

### Fix Actions

| Issue | Fix Action |
|-------|-----------|
| Needs crop | Open crop dialog with platform ratio pre-set. User draws crop, saves |
| Needs censor | Open Studio with asset loaded, censor tool active |
| Wrong dimensions | Show warning + "Auto-fit" button that crops to closest match |
| No watermark | "Apply project watermark" one-click button |

### Queue Gate (Advisory, Not Blocking)

- **Save Draft** — always available
- **Queue to OneUp** — always available. If platforms have issues, shows a warning banner: "2 platforms need prep — post anyway?" with **Queue Anyway** and **Fix Issues** buttons
- No hard blocks — user can always override and post with whatever they have
- When all green: queue triggers `prepare_for_platform()` for each, caches exports, then pushes
- When bypassed: exports with best-effort (auto-fit crop, no censor if missing, no overlay if unconfigured)

---

## 4. Asset Grid Readiness Dots

### In the thumbnail delegate paint method

For each asset, compute readiness against the identity's `default_platforms`. Show as a row of colored dots below the thumbnail (above tag dots):

```
┌──────────┐
│          │
│  [image] │
│          │
│ ●●●○○    │  ← platform readiness (green/yellow/red/grey)
│ ••••     │  ← tag dots (existing)
│ filename │
└──────────┘
```

- Green dot = ready for that platform
- Yellow dot = partially ready
- Red dot = missing critical prep
- Grey dot = not in default_platforms (dimmed)

Dots are tiny (4px) and only show for assets that have at least one platform assignment or are starred.

### Performance

Readiness computed lazily — only for visible thumbnails. Cached per asset (invalidated when asset.censors/overlays/crops change). Not computed during initial grid load.

---

## 5. Entry Points

### From Asset Grid (right-click)

```
Right-click asset → "Prepare for Posting..."
  → Opens composer with this asset pre-loaded
  → Prep strip shows readiness for identity's default_platforms
  → User checks platforms, fixes issues, writes caption, queues
```

### From New Post Button

```
Timeline → "+ New Post"
  → Opens composer empty
  → User adds assets (drag, type ID, or "Use Selected")
  → Checks platforms → prep strip appears
  → Same flow as above
```

### From Studio

```
Studio → (after editing asset) → "Queue This" button in toolbar
  → Opens composer with current asset pre-loaded
  → Prep already done in Studio carries over (censors, overlays saved on asset)
  → User just checks platforms, writes caption, queues
```

---

## 6. Export-on-Queue

When post transitions from DRAFT → QUEUED:

1. For each checked platform:
   - Call `prepare_for_platform(asset, platform_id, project)`
   - Save to `_exports/{post_id}/{platform_id}/`
2. For OneUp platforms:
   - Export is ready but needs public URL (future: CDN upload)
   - For now: use local export, post caption-only to OneUp (images posted manually or via browser)
3. For Direct platforms (Telegram, Discord, Bluesky):
   - Use the platform-specific export (correct dimensions + censors)
   - Upload directly via API
4. For Browser platforms (Patreon, Fantia, etc.):
   - Use the platform-specific export
   - Browser automation uploads the correct file

---

## 7. Per-Platform Censor Control

Extend the composer's platform section:

```
┌─ Platforms ──────────────────────────────┐
│ Category: [Doxy          v]              │
│ ☑ doxyonta [X]  ☐ poxyclean [X]         │
│                                          │
│ Subscription:                            │
│ ☑ Patreon  ☑ Fantia  ☐ Gumroad          │
│                                          │
│ Censor Mode:                             │
│ ○ Auto (platform default)                │
│ ○ Uncensored everywhere                  │
│ ○ Custom:                                │
│   Patreon: [Uncensored v]                │
│   Fantia:  [Censored   v]               │
│   Twitter: [Censored   v]               │
└──────────────────────────────────────────┘
```

Stored on SocialPost as:
```python
censor_mode: str = "auto"  # "auto" | "uncensored" | "custom"
platform_censor: dict[str, bool] = {}  # platform_id -> should_censor (only for "custom" mode)
```

Pipeline reads this when exporting: if `censor_mode == "auto"`, use `platform.needs_censor`. If `"custom"`, use `platform_censor[platform_id]`.

---

## Files to Create/Modify

| File | Changes |
|------|---------|
| `doxyedit/pipeline.py` | **NEW** — `prepare_for_platform()`, `check_readiness()`, coordinate transform, export cache |
| `doxyedit/models.py` | Add `censor_mode`, `platform_censor` to SocialPost. Add `check_readiness()` |
| `doxyedit/composer_left.py` | Add Prep Strip UI below asset preview |
| `doxyedit/composer_right.py` | Censor Mode radio buttons in platforms section. Queue gate logic |
| `doxyedit/composer.py` | Wire prep strip to platform changes. Export-on-queue |
| `doxyedit/browser.py` | Readiness dots in delegate paint. Lazy computation + cache |
| `doxyedit/exporter.py` | Refactor to use pipeline.py (becomes thin wrapper) |
| `doxyedit/studio.py` | "Queue This" toolbar button |
| `doxyedit/window.py` | Wire "Prepare for Posting" right-click. Route to composer |

## Verification

1. Right-click asset → "Prepare for Posting" → composer opens with asset + prep strip showing readiness
2. Check Twitter (needs 16:9) + Fantia (needs censor) → prep strip shows yellow + red
3. Click [Fix] on Twitter → crop dialog with 16:9 ratio → draw crop → dot turns green
4. Click [Fix] on Fantia → jumps to Studio with censor tool → draw censor → dot turns green
5. All green → Queue enabled → click Queue → exports cached to `_exports/` → pushed to platforms
6. Asset grid shows green dots for prepped platforms
7. Create post with "Custom" censor mode → Patreon uncensored, Fantia censored → exports differ correctly
