# Social Media Publishing Pipeline — Design Spec

## Context

DoxyEdit manages art assets across dozens of folders for multi-platform publishing (Kickstarter, Steam, Patreon, social media). The user has ADHD and needs a "set and forget" system — sit down once, batch-prep weeks of content, walk away. Currently DoxyEdit exports images and tracks assignment status, but has no actual posting capability. This spec adds the last mile: scheduling, posting, and tracking via OneUp.

## Architecture

Three systems, clear responsibilities:

| System | Role | Responsibilities |
|--------|------|-----------------|
| **DoxyEdit** | The Truth | Timeline UI, post composition, status tracking, CLI interface |
| **Claude CLI** | The Brain | Suggests art, writes captions, optimizes engagement, fills schedule gaps |
| **OneUp API** | The Muscle | Delivers posts to 8 platforms on schedule, reports back status |

Target platforms: Twitter/X, Instagram, Bluesky, Reddit, Patreon, Discord, TikTok, Pinterest.

## Data Model

### Post object (new, stored in `.doxyproj.json`)

```python
@dataclass
class Post:
    id: str                          # uuid
    asset_ids: list[str]             # 1-2 asset IDs from project
    platforms: list[str]             # ["twitter", "instagram", "bluesky", ...]
    captions: dict[str, str]         # platform_id → caption text (per-platform)
    caption_default: str             # fallback caption if no platform-specific one
    links: list[str]                 # Gumroad/Patreon URLs to include
    scheduled_time: str              # ISO 8601 datetime
    status: str                      # "draft" | "queued" | "posted" | "failed" | "partial"
    platform_status: dict[str, str]  # platform_id → status (per-platform granularity)
    oneup_post_id: str | None        # OneUp's post ID for status sync
    reply_templates: list[str]       # pre-written engagement responses
    created_at: str                  # ISO 8601
    updated_at: str                  # ISO 8601
    notes: str                       # freeform
    collection: str                  # which collection/identity this post belongs to
```

### Project file additions

```json
{
  "posts": [],
  "oneup": {
    "api_key": "",
    "default_platforms": ["twitter", "instagram", "bluesky", "reddit", "pinterest"],
    "posting_times": ["10:00", "14:00", "18:00"],
    "timezone": "America/New_York"
  },
  "gumroad_base_url": "",
  "patreon_base_url": ""
}
```

Alternatively, `oneup.api_key` can live in `config.yaml` to keep secrets out of the project file.

### Collection identity (voice/brand per project)

Each DoxyEdit collection can represent a different artist, brand, or persona. Posts from different collections need different voices, content patterns, and platform targeting.

```python
@dataclass
class CollectionIdentity:
    name: str                        # display name ("Yacky", "BD Inc", etc.)
    voice: str                       # tone description for Claude ("casual, emoji-heavy, hype-focused")
    hashtags: list[str]              # default hashtags per identity
    default_platforms: list[str]     # which platforms this identity posts to
    gumroad_url: str                 # base Gumroad store URL
    patreon_url: str                 # base Patreon page URL
    bio_blurb: str                   # short "about" for Claude context when writing captions
    content_notes: str               # e.g. "NSFW-friendly on Patreon, SFW only on Instagram"
```

Stored per-project in `.doxyproj.json` under `"identity"`. Claude reads this before generating any captions so the voice matches the brand. When working across a collection, Claude knows which persona to write as.

## UI — Platforms Tab Redesign

### Timeline Stream (primary view)

Replaces the current kanban as the main view in the Platforms tab. Scrollable feed sorted by date.

```
┌─────────────────────────────────────────────────────┐
│ [+ New Post]  [Sync OneUp]  [Fill Gaps]   filter: ▼ │
├─────────────────────────────────────────────────────┤
│                                                     │
│ ── Today — Apr 13 ────────────────────────────────  │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🖼 [thumb] Devil Futa pack        ✓ posted 2:30p│ │
│ │           Twitter, Insta, Bluesky               │ │
│ │           gumroad.com/l/devil-pack              │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ ── Tomorrow — Apr 14 ─────────────────────────────  │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🖼 [thumb] Sailor Moon set       ◷ queued 10:00a│ │
│ │           Twitter, Reddit, Pinterest            │ │
│ │           "New Sailor Moon pieces! Link in..."  │ │
│ └─────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 📋 [thumb] Furry commission      ◷ queued 6:00p │ │
│ │           Patreon, Discord                      │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ ── Apr 16 ── ⚠ GAP — no posts ────────────────── │ │
│                                                     │
│ ── Apr 17 ────────────────────────────────────────  │
│ │ ...                                             │ │
└─────────────────────────────────────────────────────┘
```

**Post card shows:**
- Thumbnail(s) of assigned images
- Post title / first line of caption
- Platform badges (colored pills)
- Scheduled time
- Status: draft (gray), queued (orange), posted (green), failed (red), partial (yellow)
- Link URLs
- Click to expand → full caption per platform, reply templates, edit controls

**Gap markers:** Empty days shown as dashed warning rows. "Fill Gaps" button triggers Claude CLI to suggest posts for gaps.

**Toolbar:**
- `+ New Post` — opens post composer
- `Sync OneUp` — pull latest status from OneUp API
- `Fill Gaps` — CLI hook: asks Claude to suggest posts for empty days
- Filter dropdown: All / Drafts / Queued / Posted / Failed

### Post Composer (detail panel or dialog)

When creating or editing a post:

```
┌────────────────────────────────────────────────┐
│ Images: [thumb1] [thumb2] [+ from browser]     │
│                                                │
│ Platforms: [x]Twitter [x]Insta [x]Bluesky      │
│            [ ]Reddit  [ ]Patreon [ ]Discord    │
│            [ ]TikTok  [ ]Pinterest             │
│                                                │
│ Caption (all platforms):                        │
│ ┌────────────────────────────────────────────┐ │
│ │ New piece from the Devil Futa series!      │ │
│ │ Full pack available: gumroad.com/l/...     │ │
│ └────────────────────────────────────────────┘ │
│ [Per-platform captions ▼]  [🤖 Ask Claude]    │
│                                                │
│ Links: [gumroad.com/l/devil-pack        ] [+] │
│                                                │
│ Schedule: [Apr 14] [10:00 AM] [timezone ▼]     │
│                                                │
│ Reply templates:                               │
│ ┌────────────────────────────────────────────┐ │
│ │ "Thanks! Full set on Gumroad: [link]"     │ │
│ │ "Glad you like it! More coming next week" │ │
│ └────────────────────────────────────────────┘ │
│ [🤖 Generate replies]                          │
│                                                │
│ [Save Draft]  [Queue to OneUp]                 │
└────────────────────────────────────────────────┘
```

**"Ask Claude" button:** Shells out to DoxyEdit CLI → Claude generates captions based on asset tags, character, style. Returns per-platform variants.

### Status Dashboard (bottom bar or collapsible section)

Summary stats always visible:
```
📊 This week: 8 queued · 3 posted · 1 failed · 2 gaps | Next post: Tomorrow 10:00am
```

## CLI Interface

All commands operate on the `.doxyproj.json` file. When DoxyEdit is running, changes sync via file watcher (DoxyEdit already watches for external changes).

### Read commands

```bash
# List assets — filterable by tag, unposted, starred
doxyedit assets [--tag furry] [--unposted] [--starred] [--format json|table]

# Show post schedule
doxyedit schedule [--from 2026-04-13] [--to 2026-04-27] [--status queued]

# Find days with no scheduled posts
doxyedit gaps [--from 2026-04-13] [--days 14]

# Show platforms + OneUp connection status
doxyedit platforms

# Show summary stats
doxyedit status
```

### Write commands

```bash
# Create a post (returns post ID)
doxyedit post create \
  --assets "devil_futa_01,devil_futa_02" \
  --platforms "twitter,instagram,bluesky" \
  --caption "New Devil Futa series drop!" \
  --caption-twitter "New Devil Futa series! 🔥 Full pack: {link}" \
  --link "https://gumroad.com/l/devil-pack" \
  --schedule "2026-04-14T10:00:00" \
  --reply-template "Thanks! Full set on Gumroad: {link}" \
  --reply-template "More coming next week!"

# Update a post
doxyedit post update <post-id> [--caption "..."] [--schedule "..."] [--add-platform reddit]

# Push a draft to OneUp (actually schedules it)
doxyedit post push <post-id>

# Push all drafts
doxyedit post push --all-drafts

# Sync status from OneUp (updates posted/failed)
doxyedit post sync

# Delete a post
doxyedit post delete <post-id>
```

### Helper commands (Claude uses these)

```bash
# Suggest next N assets to post based on recency, tags, coverage
doxyedit suggest [--count 5] [--exclude-tags wip]

# Export assets at platform dimensions (already exists, extended)
doxyedit export <asset-id> --platforms twitter,instagram
```

### CLI output format

All commands support `--format json` for Claude to parse and `--format table` for human reading. Default is `table`.

## OneUp Integration

### Setup

API key stored in `config.yaml`:
```yaml
oneup:
  api_key: "your-api-key-here"
```

### Post flow

1. User creates post in DoxyEdit (GUI or CLI) → status: `draft`
2. User/Claude pushes post → DoxyEdit calls OneUp API → status: `queued`
3. OneUp delivers at scheduled time
4. `doxyedit post sync` polls OneUp → updates status to `posted` or `failed`
5. DoxyEdit timeline reflects current state

### API calls needed

- `POST /posts` — create scheduled post (image upload + caption + platforms + time)
- `GET /posts/{id}` — check post status
- `GET /posts` — list scheduled posts (for sync)
- `DELETE /posts/{id}` — cancel a scheduled post

### Error handling

- `failed` status shown in red on timeline with error message from OneUp
- `partial` status when some platforms succeeded, others failed
- `doxyedit post retry <post-id>` to re-push failed posts

## File changes

| File | Change |
|------|--------|
| `doxyedit/models.py` | Add `Post` dataclass, `PostStatus` enum, serialization |
| `doxyedit/platforms.py` | Replace platform cards with timeline stream + post composer |
| `doxyedit/oneup.py` | **New** — OneUp API client (create/sync/delete posts) |
| `doxyedit/cli.py` | **New** — CLI entry point, all commands above |
| `doxyedit/window.py` | Wire new Platforms tab, add Sync action to menu |
| `doxyedit/themes.py` | Add tokens for post status colors, timeline styling |
| `doxyedit/kanban.py` | Deprecate or adapt — timeline stream replaces it |

## Future additions (not in this build)

- **Calendar view** (option C from brainstorm) — mini calendar + detail panel
- **Comment/engagement monitoring** — pull comments from platform APIs, surface to reply
- **Auto-suggest posting times** — analyze engagement data for optimal scheduling
- **Recurring posts** — "post this every Tuesday" templates
- **Analytics dashboard** — engagement metrics per post/platform

## Verification

1. Create a post via CLI with test assets → appears in DoxyEdit timeline
2. Edit the post in DoxyEdit GUI → changes reflected in project file
3. Push to OneUp → status changes to queued
4. Run sync → status updates to posted/failed
5. Claude workflow: `doxyedit gaps` → `doxyedit suggest` → `doxyedit post create` → `doxyedit post push` — full hands-free loop
6. Narrow window → timeline stream wraps properly (FlowWidget)
