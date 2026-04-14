# DoxyEdit Suite Expansion Roadmap

Three planned expansions designed by separate planning agents. All are incremental and independent.

## 1. Platforms Tab Evolution — Campaign & Launch Planning

**Purpose:** Transform Platforms tab from asset-slot tracker into campaign preparation dashboard (Kickstarter launches, Steam releases, merch drops).

**Key additions:**
- `Campaign` + `CampaignMilestone` data models with launch dates, deadlines, status tracking
- Campaign selector bar on Platforms tab with filtered views
- Milestone checklist per campaign (auto-generated defaults per platform type)
- Campaign launch dates appear as vertical markers on Gantt chart
- Suggested promotional posts at -14d, -7d, -3d, launch day
- `campaign_id` on PlatformAssignment and SocialPost for linking

**6 phases:** Data model, Campaign UI, Gantt integration, Social synergy, UI polish, Theme tokens

---

## 2. Subscription Platform Automation

**Purpose:** Generalize the Patreon quick-post flow to all subscription/monetization platforms.

**Research findings:** None of the 6 target platforms (Patreon, Gumroad, Ko-fi, Pixiv Fanbox, Fantia, Ci-en) have post-creation APIs. All use semi-automated quick-post: clipboard + export + browser launch.

**Key additions:**
- `SubPlatform` registry (patreon, fanbox, fantia, cien, gumroad, kofi) with locale, tier support, URL templates
- `quickpost.py` module — generalized quick-post action for any platform
- New CollectionIdentity fields: fanbox_url, fantia_url, cien_url, kofi_url, voice_ja, hashtags_ja
- `tier_assets` on SocialPost for tiered content (free preview / basic / premium)
- `tier_level` + `locale` on ReleaseStep for per-step targeting
- Dual-language caption generation in AI Strategy
- Japanese platforms auto-apply mosaic censors on export

**4 phases:** Foundation (all 6 platforms), Release chain integration, Content differentiation, Dashboard

---

## 3. Cross-Project Awareness

**Purpose:** Let multiple DoxyEdit projects see each other's schedules to avoid conflicts and coordinate releases.

**Key additions:**
- Central registry at `~/.doxyedit/project_registry.json` (auto-synced from QSettings)
- `crossproject.py` module with lightweight JSON peek (reads only posts, skips assets)
- `CrossProjectCache` with mtime-based invalidation
- Calendar overlay: other projects' posts shown as muted dots
- Gantt overlay: external posts as semi-transparent bars with toggle
- Composer conflict warnings: "Commissions project also posting to Twitter on Apr 15"
- `blackout_periods` on Project for campaign exclusivity windows
- Conflict types: same_day, same_platform_same_day, blackout, saturation

**6 phases:** Foundation, Calendar overlay, Conflict detection, Gantt overlay, Blackout editor, Dashboard

---

## Dependency & Priority

All three are independent. Recommended order:
1. **Subscription automation** (Phase 1 alone covers all 6 platforms immediately — highest value/effort ratio)
2. **Cross-project awareness** (Phase 1-3 give calendar + conflict detection)
3. **Platforms tab evolution** (largest scope, most UI work)
