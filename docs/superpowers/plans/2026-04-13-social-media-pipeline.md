# Social Media Publishing Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete social media publishing pipeline to DoxyEdit — data model for posts, CLI commands for Claude-driven scheduling, OneUp API client for delivery, and a timeline stream UI replacing the current Platforms tab kanban.

**Architecture:** Three-layer system. (1) `Post` dataclass + `CollectionIdentity` in models.py with JSON persistence. (2) `oneup.py` API client that talks to OneUp's REST API. (3) CLI commands in `__main__.py` for Claude to create/push/sync posts. (4) Timeline stream widget replacing the kanban in the Platforms tab. Each layer is independently testable.

**Tech Stack:** PySide6, Python requests (OneUp HTTP), existing JSON project file, existing theme system.

**Spec:** `docs/superpowers/specs/2026-04-13-social-media-pipeline-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `doxyedit/models.py` | Modify | Add `SocialPost`, `CollectionIdentity` dataclasses, new `PostStatus` values, serialize in Project save/load |
| `doxyedit/oneup.py` | Create | OneUp REST API client — create/list/sync/delete posts |
| `doxyedit/__main__.py` | Modify | Add CLI commands: `schedule`, `gaps`, `post create/update/push/sync/delete`, `suggest` |
| `doxyedit/timeline.py` | Create | Timeline stream widget — scrollable post feed with day headers and gap markers |
| `doxyedit/composer.py` | Create | Post composer dialog — image picker, platform checkboxes, caption editor, schedule picker |
| `doxyedit/window.py` | Modify | Wire timeline into Platforms tab, replace kanban as primary view |
| `doxyedit/themes.py` | Modify | Add post status color tokens + timeline QSS selectors |
| `doxyedit/kanban.py` | Keep | Keep as secondary view (toggle), not deleted |

---

### Task 1: Data Model — SocialPost + CollectionIdentity

**Files:**
- Modify: `doxyedit/models.py`

- [ ] **Step 1: Add SocialPostStatus enum after existing PostStatus**

```python
# Add after PostStatus (line 15) in models.py

class SocialPostStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    POSTED = "posted"
    FAILED = "failed"
    PARTIAL = "partial"
```

- [ ] **Step 2: Add CollectionIdentity dataclass**

```python
# Add after PlatformAssignment (line 177)

@dataclass
class CollectionIdentity:
    name: str = ""
    voice: str = ""                    # tone description for Claude
    hashtags: list[str] = field(default_factory=list)
    default_platforms: list[str] = field(default_factory=list)
    gumroad_url: str = ""
    patreon_url: str = ""
    bio_blurb: str = ""
    content_notes: str = ""            # e.g. "NSFW on Patreon, SFW on Instagram"
```

- [ ] **Step 3: Add SocialPost dataclass**

```python
@dataclass
class SocialPost:
    id: str = ""                                    # uuid
    asset_ids: list[str] = field(default_factory=list)  # 1-2 asset IDs
    platforms: list[str] = field(default_factory=list)
    captions: dict[str, str] = field(default_factory=dict)  # platform → text
    caption_default: str = ""
    links: list[str] = field(default_factory=list)
    scheduled_time: str = ""                        # ISO 8601
    status: str = SocialPostStatus.DRAFT
    platform_status: dict[str, str] = field(default_factory=dict)
    oneup_post_id: str = ""
    reply_templates: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""
    collection: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset_ids": self.asset_ids,
            "platforms": self.platforms,
            "captions": self.captions,
            "caption_default": self.caption_default,
            "links": self.links,
            "scheduled_time": self.scheduled_time,
            "status": self.status,
            "platform_status": self.platform_status,
            "oneup_post_id": self.oneup_post_id,
            "reply_templates": self.reply_templates,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
            "collection": self.collection,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SocialPost":
        return cls(
            id=d.get("id", ""),
            asset_ids=d.get("asset_ids", []),
            platforms=d.get("platforms", []),
            captions=d.get("captions", {}),
            caption_default=d.get("caption_default", ""),
            links=d.get("links", []),
            scheduled_time=d.get("scheduled_time", ""),
            status=d.get("status", SocialPostStatus.DRAFT),
            platform_status=d.get("platform_status", {}),
            oneup_post_id=d.get("oneup_post_id", ""),
            reply_templates=d.get("reply_templates", []),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            notes=d.get("notes", ""),
            collection=d.get("collection", ""),
        )
```

- [ ] **Step 4: Add posts + identity + oneup config to Project class**

In the `Project.__init__` (around line 403), add these fields:

```python
    posts: list[SocialPost] = field(default_factory=list)
    identity: dict = field(default_factory=dict)     # CollectionIdentity as dict
    oneup_config: dict = field(default_factory=dict)  # api_key, default_platforms, posting_times, timezone
```

- [ ] **Step 5: Add posts/identity/oneup_config to Project.save()**

In `Project.save()` (line 481), add to the `data` dict before `"assets"`:

```python
            "posts": [p.to_dict() for p in self.posts],
            "identity": self.identity,
            "oneup_config": self.oneup_config,
```

- [ ] **Step 6: Add posts/identity/oneup_config to Project.load()**

In `Project.load()` (after line 537, before config loading), add:

```python
        proj.identity = raw.get("identity", {})
        proj.oneup_config = raw.get("oneup_config", {})
        for p in raw.get("posts", []):
            proj.posts.append(SocialPost.from_dict(p))
```

- [ ] **Step 7: Add helper methods to Project**

```python
    def get_post(self, post_id: str) -> Optional[SocialPost]:
        for p in self.posts:
            if p.id == post_id:
                return p
        return None

    def get_identity(self) -> CollectionIdentity:
        return CollectionIdentity(**self.identity) if self.identity else CollectionIdentity()
```

- [ ] **Step 8: Test round-trip save/load**

Run:
```bash
cd E:/git/doxyedit && python -c "
from doxyedit.models import *
import uuid, json
from datetime import datetime

# Create project, add a post
proj = Project(name='test')
post = SocialPost(
    id=str(uuid.uuid4()),
    asset_ids=['test_01'],
    platforms=['twitter', 'instagram'],
    caption_default='Test post!',
    scheduled_time=datetime.now().isoformat(),
    status=SocialPostStatus.DRAFT,
    created_at=datetime.now().isoformat(),
    updated_at=datetime.now().isoformat(),
)
proj.posts.append(post)
proj.identity = {'name': 'TestArtist', 'voice': 'casual, fun'}
proj.oneup_config = {'api_key': 'test123', 'default_platforms': ['twitter']}

# Save
proj.save('_test_project.doxyproj.json')

# Load
proj2 = Project.load('_test_project.doxyproj.json')
assert len(proj2.posts) == 1
assert proj2.posts[0].caption_default == 'Test post!'
assert proj2.identity['name'] == 'TestArtist'
assert proj2.oneup_config['api_key'] == 'test123'
print('PASS: round-trip save/load works')

import os; os.remove('_test_project.doxyproj.json')
"
```
Expected: `PASS: round-trip save/load works`

- [ ] **Step 9: Commit**

```bash
git add doxyedit/models.py
git commit -m "feat: add SocialPost + CollectionIdentity data models for publishing pipeline"
```

---

### Task 2: OneUp API Client

**Files:**
- Create: `doxyedit/oneup.py`

- [ ] **Step 1: Create OneUp client with auth and post creation**

```python
"""OneUp API client — schedules and syncs social media posts."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError


BASE_URL = "https://www.oneupapp.io/api"


@dataclass
class OneUpResult:
    success: bool
    data: dict
    error: str = ""


class OneUpClient:
    """Thin wrapper around OneUp REST API. Uses stdlib urllib — no extra deps."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _url(self, endpoint: str) -> str:
        sep = "&" if "?" in endpoint else "?"
        return f"{BASE_URL}/{endpoint}{sep}apiKey={self.api_key}"

    def _request(self, method: str, endpoint: str, body: Optional[dict] = None) -> OneUpResult:
        url = self._url(endpoint)
        data = json.dumps(body).encode("utf-8") if body else None
        headers = {"Content-Type": "application/json"} if body else {}
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return OneUpResult(success=True, data=result)
        except HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            return OneUpResult(success=False, data={}, error=f"HTTP {e.code}: {error_body}")
        except Exception as e:
            return OneUpResult(success=False, data={}, error=str(e))

    def test_connection(self) -> OneUpResult:
        """Verify API key works by listing social accounts."""
        return self._request("GET", "social-accounts")

    def list_social_accounts(self) -> OneUpResult:
        """Get connected social media accounts."""
        return self._request("GET", "social-accounts")

    def create_post(self, *, image_urls: list[str], caption: str,
                    social_account_ids: list[str],
                    scheduled_time: Optional[str] = None) -> OneUpResult:
        """Create a scheduled post on OneUp.

        Args:
            image_urls: Public URLs to images (OneUp fetches them)
            caption: Post text/caption
            social_account_ids: OneUp account IDs to post to
            scheduled_time: ISO 8601 datetime, or None for immediate
        """
        body = {
            "type": "image",
            "mediaUrls": image_urls,
            "body": caption,
            "socialAccountIds": social_account_ids,
        }
        if scheduled_time:
            body["scheduledTime"] = scheduled_time
        return self._request("POST", "posts", body)

    def get_post(self, post_id: str) -> OneUpResult:
        """Get a single post by ID."""
        return self._request("GET", f"posts/{post_id}")

    def list_posts(self, status: str = "scheduled") -> OneUpResult:
        """List posts by status: scheduled, published, failed."""
        return self._request("GET", f"posts?status={status}")

    def delete_post(self, post_id: str) -> OneUpResult:
        """Cancel/delete a scheduled post."""
        return self._request("DELETE", f"posts/{post_id}")


def get_client_from_config(project_dir: str) -> Optional[OneUpClient]:
    """Load OneUp client from config.yaml or project file."""
    # Try config.yaml first
    config_path = Path(project_dir) / "config.yaml"
    if config_path.exists():
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            key = (config.get("oneup") or {}).get("api_key", "")
            if key:
                return OneUpClient(key)
        except Exception:
            pass
    # Try env var
    key = os.environ.get("ONEUP_API_KEY", "")
    if key:
        return OneUpClient(key)
    return None
```

- [ ] **Step 2: Test client instantiation (offline)**

```bash
cd E:/git/doxyedit && python -c "
from doxyedit.oneup import OneUpClient, OneUpResult, get_client_from_config

# Test client creation
client = OneUpClient('fake-key')
assert client.api_key == 'fake-key'
assert 'apiKey=fake-key' in client._url('posts')

# Test result dataclass
r = OneUpResult(success=True, data={'id': '123'})
assert r.success and r.data['id'] == '123'

# get_client_from_config returns None when no config
result = get_client_from_config('.')
# May or may not return depending on env, just verify no crash
print('PASS: OneUp client instantiation works')
"
```
Expected: `PASS: OneUp client instantiation works`

- [ ] **Step 3: Commit**

```bash
git add doxyedit/oneup.py
git commit -m "feat: add OneUp API client for social media scheduling"
```

---

### Task 3: CLI Commands — Post Management

**Files:**
- Modify: `doxyedit/__main__.py`

- [ ] **Step 1: Add imports at top of __main__.py**

```python
import uuid
from datetime import datetime, timedelta
```

- [ ] **Step 2: Add `cmd_schedule` function**

Add before the `main()` function:

```python
def cmd_schedule(project_path: str, args: list[str]):
    """Show upcoming post schedule."""
    proj = Project.load(project_path)
    from_date = None
    to_date = None
    status_filter = None
    fmt = "table"
    i = 0
    while i < len(args):
        if args[i] == "--from" and i + 1 < len(args):
            from_date = args[i + 1]; i += 2
        elif args[i] == "--to" and i + 1 < len(args):
            to_date = args[i + 1]; i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            status_filter = args[i + 1]; i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    posts = sorted(proj.posts, key=lambda p: p.scheduled_time or "9999")
    if from_date:
        posts = [p for p in posts if (p.scheduled_time or "") >= from_date]
    if to_date:
        posts = [p for p in posts if (p.scheduled_time or "") <= to_date]
    if status_filter:
        posts = [p for p in posts if p.status == status_filter]

    if fmt == "json":
        import json as _json
        print(_json.dumps([p.to_dict() for p in posts], indent=2))
        return

    if not posts:
        print("No posts scheduled.")
        return
    for p in posts:
        dt = p.scheduled_time[:16] if p.scheduled_time else "unscheduled"
        plats = ", ".join(p.platforms) if p.platforms else "no platforms"
        caption = (p.caption_default[:50] + "...") if len(p.caption_default) > 50 else p.caption_default
        status_icon = {"draft": "○", "queued": "◷", "posted": "✓", "failed": "✗", "partial": "◑"}.get(p.status, "?")
        asset_names = ", ".join(p.asset_ids[:2]) if p.asset_ids else "no images"
        print(f"  {status_icon} [{p.status:7s}] {dt}  {asset_names}")
        print(f"    {plats}")
        if caption:
            print(f"    \"{caption}\"")
        print(f"    id: {p.id}")
        print()
```

- [ ] **Step 3: Add `cmd_gaps` function**

```python
def cmd_gaps(project_path: str, args: list[str]):
    """Find days with no scheduled posts."""
    proj = Project.load(project_path)
    from_date = datetime.now().strftime("%Y-%m-%d")
    days = 14
    fmt = "table"
    i = 0
    while i < len(args):
        if args[i] == "--from" and i + 1 < len(args):
            from_date = args[i + 1]; i += 2
        elif args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1]); i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    # Build set of days that have posts
    posted_days = set()
    for p in proj.posts:
        if p.scheduled_time and p.status not in ("failed",):
            posted_days.add(p.scheduled_time[:10])

    start = datetime.strptime(from_date, "%Y-%m-%d")
    gap_days = []
    for d in range(days):
        day = (start + timedelta(days=d)).strftime("%Y-%m-%d")
        if day not in posted_days:
            gap_days.append(day)

    if fmt == "json":
        import json as _json
        print(_json.dumps(gap_days))
        return

    if not gap_days:
        print(f"No gaps in the next {days} days!")
    else:
        print(f"Gaps ({len(gap_days)} empty days in next {days}):")
        for day in gap_days:
            print(f"  ⚠ {day}")
```

- [ ] **Step 4: Add `cmd_post_create` function**

```python
def cmd_post_create(project_path: str, args: list[str]):
    """Create a new post draft."""
    from doxyedit.models import SocialPost, SocialPostStatus
    proj = Project.load(project_path)

    assets = platforms = caption = schedule = ""
    links = []
    reply_templates = []
    captions_per_platform = {}
    fmt = "table"
    i = 0
    while i < len(args):
        if args[i] == "--assets" and i + 1 < len(args):
            assets = args[i + 1]; i += 2
        elif args[i] == "--platforms" and i + 1 < len(args):
            platforms = args[i + 1]; i += 2
        elif args[i] == "--caption" and i + 1 < len(args):
            caption = args[i + 1]; i += 2
        elif args[i].startswith("--caption-") and i + 1 < len(args):
            plat = args[i][len("--caption-"):]
            captions_per_platform[plat] = args[i + 1]; i += 2
        elif args[i] == "--link" and i + 1 < len(args):
            links.append(args[i + 1]); i += 2
        elif args[i] == "--schedule" and i + 1 < len(args):
            schedule = args[i + 1]; i += 2
        elif args[i] == "--reply-template" and i + 1 < len(args):
            reply_templates.append(args[i + 1]); i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    now = datetime.now().isoformat()
    post = SocialPost(
        id=str(uuid.uuid4()),
        asset_ids=[a.strip() for a in assets.split(",") if a.strip()] if assets else [],
        platforms=[p.strip() for p in platforms.split(",") if p.strip()] if platforms else [],
        captions=captions_per_platform,
        caption_default=caption,
        links=links,
        scheduled_time=schedule,
        status=SocialPostStatus.DRAFT,
        reply_templates=reply_templates,
        created_at=now,
        updated_at=now,
    )
    proj.posts.append(post)
    proj.save(project_path)

    if fmt == "json":
        import json as _json
        print(_json.dumps(post.to_dict(), indent=2))
    else:
        print(f"Created post: {post.id}")
        print(f"  Assets: {', '.join(post.asset_ids)}")
        print(f"  Platforms: {', '.join(post.platforms)}")
        print(f"  Scheduled: {post.scheduled_time or 'not scheduled'}")
        print(f"  Status: {post.status}")
```

- [ ] **Step 5: Add `cmd_post_update` function**

```python
def cmd_post_update(project_path: str, post_id: str, args: list[str]):
    """Update an existing post."""
    proj = Project.load(project_path)
    post = proj.get_post(post_id)
    if not post:
        print(f"Post not found: {post_id}")
        sys.exit(1)

    i = 0
    while i < len(args):
        if args[i] == "--caption" and i + 1 < len(args):
            post.caption_default = args[i + 1]; i += 2
        elif args[i].startswith("--caption-") and i + 1 < len(args):
            plat = args[i][len("--caption-"):]
            post.captions[plat] = args[i + 1]; i += 2
        elif args[i] == "--schedule" and i + 1 < len(args):
            post.scheduled_time = args[i + 1]; i += 2
        elif args[i] == "--add-platform" and i + 1 < len(args):
            plat = args[i + 1]
            if plat not in post.platforms:
                post.platforms.append(plat)
            i += 2
        elif args[i] == "--remove-platform" and i + 1 < len(args):
            plat = args[i + 1]
            if plat in post.platforms:
                post.platforms.remove(plat)
            i += 2
        elif args[i] == "--link" and i + 1 < len(args):
            post.links.append(args[i + 1]); i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            post.status = args[i + 1]; i += 2
        elif args[i] == "--reply-template" and i + 1 < len(args):
            post.reply_templates.append(args[i + 1]); i += 2
        else:
            i += 1

    post.updated_at = datetime.now().isoformat()
    proj.save(project_path)
    print(f"Updated post: {post_id}")
```

- [ ] **Step 6: Add `cmd_post_push` function**

```python
def cmd_post_push(project_path: str, args: list[str]):
    """Push post(s) to OneUp for scheduling."""
    from doxyedit.models import SocialPostStatus
    from doxyedit.oneup import get_client_from_config
    proj = Project.load(project_path)
    project_dir = str(Path(project_path).parent)

    client = get_client_from_config(project_dir)
    if not client:
        # Also try project-level oneup_config
        key = (proj.oneup_config or {}).get("api_key", "")
        if key:
            from doxyedit.oneup import OneUpClient
            client = OneUpClient(key)
    if not client:
        print("No OneUp API key found. Set it in config.yaml under oneup.api_key")
        sys.exit(1)

    push_all = "--all-drafts" in args
    post_id = args[0] if args and not args[0].startswith("--") else None

    targets = []
    if push_all:
        targets = [p for p in proj.posts if p.status == SocialPostStatus.DRAFT]
    elif post_id:
        post = proj.get_post(post_id)
        if not post:
            print(f"Post not found: {post_id}")
            sys.exit(1)
        targets = [post]
    else:
        print("Usage: doxyedit post push <post-id> OR --all-drafts")
        sys.exit(1)

    if not targets:
        print("No posts to push.")
        return

    for post in targets:
        # For now, we need image URLs — OneUp requires publicly accessible URLs
        # This is a placeholder: in practice, images would be uploaded to a host first
        # or the user provides URLs. For local files, we'll note this limitation.
        image_urls = []
        for aid in post.asset_ids:
            asset = proj.get_asset(aid)
            if asset and asset.source_path:
                image_urls.append(asset.source_path)

        caption = post.caption_default
        result = client.create_post(
            image_urls=image_urls,
            caption=caption,
            social_account_ids=post.platforms,  # maps to OneUp account IDs
            scheduled_time=post.scheduled_time or None,
        )

        if result.success:
            post.status = SocialPostStatus.QUEUED
            post.oneup_post_id = result.data.get("id", "")
            post.updated_at = datetime.now().isoformat()
            print(f"  ✓ Pushed: {post.id[:8]}... → OneUp ({post.oneup_post_id})")
        else:
            post.status = SocialPostStatus.FAILED
            post.updated_at = datetime.now().isoformat()
            print(f"  ✗ Failed: {post.id[:8]}... — {result.error}")

    proj.save(project_path)
```

- [ ] **Step 7: Add `cmd_post_sync` function**

```python
def cmd_post_sync(project_path: str, args: list[str]):
    """Sync post statuses from OneUp."""
    from doxyedit.models import SocialPostStatus
    from doxyedit.oneup import get_client_from_config, OneUpClient
    proj = Project.load(project_path)
    project_dir = str(Path(project_path).parent)

    client = get_client_from_config(project_dir)
    if not client:
        key = (proj.oneup_config or {}).get("api_key", "")
        if key:
            client = OneUpClient(key)
    if not client:
        print("No OneUp API key found.")
        sys.exit(1)

    queued = [p for p in proj.posts if p.status == SocialPostStatus.QUEUED and p.oneup_post_id]
    if not queued:
        print("No queued posts to sync.")
        return

    updated = 0
    for post in queued:
        result = client.get_post(post.oneup_post_id)
        if result.success:
            remote_status = result.data.get("status", "")
            if remote_status == "published":
                post.status = SocialPostStatus.POSTED
                updated += 1
            elif remote_status == "failed":
                post.status = SocialPostStatus.FAILED
                updated += 1
            post.updated_at = datetime.now().isoformat()

    if updated:
        proj.save(project_path)
    print(f"Synced {updated} post(s) of {len(queued)} queued.")
```

- [ ] **Step 8: Add `cmd_post_delete` function**

```python
def cmd_post_delete(project_path: str, post_id: str):
    """Delete a post from the project."""
    proj = Project.load(project_path)
    post = proj.get_post(post_id)
    if not post:
        print(f"Post not found: {post_id}")
        sys.exit(1)

    # If queued on OneUp, try to cancel
    if post.oneup_post_id and post.status == "queued":
        from doxyedit.oneup import get_client_from_config, OneUpClient
        project_dir = str(Path(project_path).parent)
        client = get_client_from_config(project_dir)
        if not client:
            key = (proj.oneup_config or {}).get("api_key", "")
            if key:
                client = OneUpClient(key)
        if client:
            client.delete_post(post.oneup_post_id)

    proj.posts = [p for p in proj.posts if p.id != post_id]
    proj.save(project_path)
    print(f"Deleted post: {post_id}")
```

- [ ] **Step 9: Add `cmd_suggest` function**

```python
def cmd_suggest(project_path: str, args: list[str]):
    """Suggest assets to post next — unposted, starred first, diverse tags."""
    proj = Project.load(project_path)
    count = 5
    exclude_tags = set()
    fmt = "table"
    i = 0
    while i < len(args):
        if args[i] == "--count" and i + 1 < len(args):
            count = int(args[i + 1]); i += 2
        elif args[i] == "--exclude-tags" and i + 1 < len(args):
            exclude_tags = {t.strip() for t in args[i + 1].split(",")}; i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    # Assets already scheduled
    scheduled_ids = set()
    for p in proj.posts:
        scheduled_ids.update(p.asset_ids)

    # Filter candidates
    candidates = []
    for a in proj.assets:
        if a.id in scheduled_ids:
            continue
        if exclude_tags and exclude_tags.intersection(a.tags):
            continue
        candidates.append(a)

    # Score: starred first, then by tag diversity
    tag_counts: dict[str, int] = {}
    for a in candidates:
        for t in a.tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    def score(a):
        star_score = a.starred * 10
        # Prefer assets with rarer tags (more diverse schedule)
        tag_rarity = sum(1.0 / max(tag_counts.get(t, 1), 1) for t in a.tags) if a.tags else 0
        return star_score + tag_rarity

    candidates.sort(key=score, reverse=True)
    suggestions = candidates[:count]

    if fmt == "json":
        import json as _json
        print(_json.dumps([{"id": a.id, "tags": a.tags, "starred": a.starred, "path": a.source_path} for a in suggestions], indent=2))
        return

    if not suggestions:
        print("No suggestions — all assets are scheduled or excluded.")
        return
    print(f"Suggested assets ({len(suggestions)}):")
    for a in suggestions:
        star = "★" if a.starred else " "
        tags = ", ".join(a.tags[:5]) if a.tags else "untagged"
        print(f"  {star} {a.id}  [{tags}]")
```

- [ ] **Step 10: Wire all new commands into main()**

In the `main()` function, add these new command handlers. Add after the `elif cmd == "search-advanced":` block (around line 484):

```python
    elif cmd == "schedule":
        if len(args) < 2:
            print("Usage: python -m doxyedit schedule <project.json> [--from DATE] [--to DATE] [--status S] [--format json|table]")
            sys.exit(1)
        cmd_schedule(args[1], args[2:])
    elif cmd == "gaps":
        if len(args) < 2:
            print("Usage: python -m doxyedit gaps <project.json> [--from DATE] [--days N] [--format json|table]")
            sys.exit(1)
        cmd_gaps(args[1], args[2:])
    elif cmd == "post":
        if len(args) < 3:
            print("Usage: python -m doxyedit post <create|update|push|sync|delete> <project.json> [options]")
            sys.exit(1)
        subcmd = args[1]
        proj_path = args[2]
        if subcmd == "create":
            cmd_post_create(proj_path, args[3:])
        elif subcmd == "update":
            if len(args) < 4:
                print("Usage: python -m doxyedit post update <project.json> <post-id> [options]")
                sys.exit(1)
            cmd_post_update(proj_path, args[3], args[4:])
        elif subcmd == "push":
            cmd_post_push(proj_path, args[3:])
        elif subcmd == "sync":
            cmd_post_sync(proj_path, args[3:])
        elif subcmd == "delete":
            if len(args) < 4:
                print("Usage: python -m doxyedit post delete <project.json> <post-id>")
                sys.exit(1)
            cmd_post_delete(proj_path, args[3])
        else:
            print(f"Unknown post subcommand: {subcmd}")
            sys.exit(1)
    elif cmd == "suggest":
        if len(args) < 2:
            print("Usage: python -m doxyedit suggest <project.json> [--count N] [--exclude-tags wip]")
            sys.exit(1)
        cmd_suggest(args[1], args[2:])
```

- [ ] **Step 11: Test CLI commands end-to-end**

```bash
cd E:/git/doxyedit && python -c "
from doxyedit.models import *
import uuid
from datetime import datetime, timedelta

# Create a test project with some assets and posts
proj = Project(name='cli_test')
for i in range(5):
    proj.assets.append(Asset(
        id=f'test_{i}',
        source_path=f'/fake/path/art_{i}.png',
        source_folder='/fake/path/',
        tags=['furry', 'color'] if i % 2 == 0 else ['devil', 'sketch'],
        starred=1 if i == 0 else 0,
    ))

# Add a post
post = SocialPost(
    id='test-post-1',
    asset_ids=['test_0'],
    platforms=['twitter', 'instagram'],
    caption_default='Test post!',
    scheduled_time=(datetime.now() + timedelta(days=1)).isoformat(),
    status=SocialPostStatus.DRAFT,
    created_at=datetime.now().isoformat(),
    updated_at=datetime.now().isoformat(),
)
proj.posts.append(post)
proj.save('_cli_test.doxyproj.json')
print('Test project created.')
"

# Test schedule command
python -m doxyedit schedule _cli_test.doxyproj.json

# Test gaps command
python -m doxyedit gaps _cli_test.doxyproj.json --days 7

# Test suggest command
python -m doxyedit suggest _cli_test.doxyproj.json --count 3

# Test post create
python -m doxyedit post create _cli_test.doxyproj.json --assets "test_1,test_2" --platforms "twitter,bluesky" --caption "New art drop!" --schedule "2026-04-20T10:00:00"

# Verify the new post shows in schedule
python -m doxyedit schedule _cli_test.doxyproj.json

# Cleanup
python -c "import os; os.remove('_cli_test.doxyproj.json')"
```

Expected: All commands run without errors, schedule shows 2 posts, gaps shows empty days, suggest returns unscheduled assets.

- [ ] **Step 12: Commit**

```bash
git add doxyedit/__main__.py
git commit -m "feat: add CLI commands for post scheduling — schedule, gaps, suggest, post create/update/push/sync/delete"
```

---

### Task 4: Theme Tokens for Post Status + Timeline

**Files:**
- Modify: `doxyedit/themes.py`

- [ ] **Step 1: Add post status color tokens to Theme dataclass**

In the Theme dataclass (after `star: str = "#be955c"` around line 62), add:

```python
    # Social post status
    post_draft: str = "#888888"
    post_queued: str = "#e8a87c"
    post_posted: str = "#6eaa78"
    post_failed: str = "#cc4444"
    post_partial: str = "#ccaa55"
    # Timeline
    timeline_gap: str = "#664444"
    timeline_day_header: str = ""  # defaults to text_secondary
```

- [ ] **Step 2: Add timeline QSS to generate_stylesheet()**

At the end of `generate_stylesheet()` (before the final `return`), add:

```python
    day_hdr = theme.timeline_day_header or theme.text_secondary
    qss += f"""
    /* ---- Timeline stream ---- */
    QWidget#timeline_stream {{
        background: {theme.bg_deep};
    }}
    QLabel#timeline_day_header {{
        color: {day_hdr};
        font-size: {fl}px;
        font-weight: bold;
        padding: {pad}px 0;
    }}
    QFrame#timeline_post_card {{
        background: {theme.bg_raised};
        border: 1px solid {theme.border};
        border-radius: {rad}px;
        padding: {pad}px;
    }}
    QFrame#timeline_post_card:hover {{
        border-color: {theme.accent_dim};
    }}
    QLabel#post_status_badge {{
        border-radius: {rad}px;
        padding: 2px {pad}px;
        font-size: {fs}px;
        font-weight: bold;
    }}
    QLabel#post_status_badge[status="draft"] {{
        background: {theme.post_draft}40;
        color: {theme.post_draft};
    }}
    QLabel#post_status_badge[status="queued"] {{
        background: {theme.post_queued}40;
        color: {theme.post_queued};
    }}
    QLabel#post_status_badge[status="posted"] {{
        background: {theme.post_posted}40;
        color: {theme.post_posted};
    }}
    QLabel#post_status_badge[status="failed"] {{
        background: {theme.post_failed}40;
        color: {theme.post_failed};
    }}
    QLabel#post_status_badge[status="partial"] {{
        background: {theme.post_partial}40;
        color: {theme.post_partial};
    }}
    QFrame#timeline_gap {{
        border: 1px dashed {theme.timeline_gap};
        border-radius: {rad}px;
        padding: {pad}px;
        background: {theme.timeline_gap}15;
    }}
    QLabel#platform_badge {{
        background: {theme.accent_dim};
        color: {theme.text_on_accent};
        border-radius: {max(rad - 1, 2)}px;
        padding: 1px {pad}px;
        font-size: {fxs}px;
    }}
    """
```

- [ ] **Step 3: Test stylesheet generation includes new selectors**

```bash
cd E:/git/doxyedit && python -c "
from doxyedit.themes import THEMES, generate_stylesheet
qss = generate_stylesheet(THEMES['soot'])
assert 'timeline_stream' in qss
assert 'timeline_post_card' in qss
assert 'post_status_badge' in qss
assert 'timeline_gap' in qss
assert 'platform_badge' in qss
print('PASS: timeline QSS generated correctly')
"
```

- [ ] **Step 4: Commit**

```bash
git add doxyedit/themes.py
git commit -m "feat: add theme tokens + QSS for post timeline and status badges"
```

---

### Task 5: Timeline Stream Widget

**Files:**
- Create: `doxyedit/timeline.py`

- [ ] **Step 1: Create the timeline stream widget**

```python
"""Timeline stream — scrollable feed of scheduled posts grouped by day."""
from __future__ import annotations
from datetime import datetime, timedelta
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QPushButton, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Signal, Qt
from doxyedit.models import Project, SocialPost, SocialPostStatus


class PlatformBadge(QLabel):
    """Small colored pill showing a platform name."""
    def __init__(self, name: str, parent=None):
        super().__init__(name, parent)
        self.setObjectName("platform_badge")


class StatusBadge(QLabel):
    """Post status indicator with property-based styling."""
    _ICONS = {
        "draft": "○", "queued": "◷", "posted": "✓",
        "failed": "✗", "partial": "◑",
    }

    def __init__(self, status: str, parent=None):
        icon = self._ICONS.get(status, "?")
        super().__init__(f"{icon} {status}", parent)
        self.setObjectName("post_status_badge")
        self.setProperty("status", status)


class PostCard(QFrame):
    """Single post in the timeline — shows thumbnail, caption, platforms, status."""
    clicked = Signal(str)  # post_id

    def __init__(self, post: SocialPost, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("timeline_post_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._post_id = post.id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Row 1: asset names + status + time
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        # Asset names
        asset_names = []
        for aid in post.asset_ids[:2]:
            a = project.get_asset(aid)
            asset_names.append(a.stem if a else aid)
        name_label = QLabel(" + ".join(asset_names) if asset_names else "No images")
        name_label.setStyleSheet("font-weight: bold;")
        top_row.addWidget(name_label)
        top_row.addStretch()

        # Status badge
        top_row.addWidget(StatusBadge(post.status))

        # Time
        if post.scheduled_time:
            try:
                dt = datetime.fromisoformat(post.scheduled_time)
                time_str = dt.strftime("%I:%M%p").lstrip("0").lower()
            except (ValueError, TypeError):
                time_str = post.scheduled_time[:16]
            time_label = QLabel(time_str)
            time_label.setStyleSheet("opacity: 0.6;")
            top_row.addWidget(time_label)

        layout.addLayout(top_row)

        # Row 2: platform badges
        plat_row = QHBoxLayout()
        plat_row.setSpacing(4)
        for p in post.platforms:
            plat_row.addWidget(PlatformBadge(p))
        plat_row.addStretch()
        layout.addLayout(plat_row)

        # Row 3: caption preview
        caption = post.caption_default
        if caption:
            preview = caption[:80] + ("..." if len(caption) > 80 else "")
            cap_label = QLabel(f'"{preview}"')
            cap_label.setWordWrap(True)
            cap_label.setStyleSheet("opacity: 0.7; font-style: italic;")
            layout.addWidget(cap_label)

        # Row 4: links
        if post.links:
            for link in post.links[:2]:
                link_label = QLabel(link)
                link_label.setStyleSheet("opacity: 0.5; font-size: small;")
                layout.addWidget(link_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._post_id)
        super().mousePressEvent(event)


class GapMarker(QFrame):
    """Warning marker for days with no scheduled posts."""
    fill_requested = Signal(str)  # date string

    def __init__(self, date_str: str, parent=None):
        super().__init__(parent)
        self.setObjectName("timeline_gap")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        label = QLabel(f"⚠ {date_str} — no posts scheduled")
        label.setStyleSheet("opacity: 0.6;")
        layout.addWidget(label)
        layout.addStretch()


class TimelineStream(QWidget):
    """Main timeline widget — scrollable post feed grouped by day."""
    post_selected = Signal(str)     # post_id
    new_post_requested = Signal()
    sync_requested = Signal()
    fill_gaps_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeline_stream")
        self._project: Project | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(6)

        new_btn = QPushButton("+ New Post")
        new_btn.setObjectName("toolbar_btn")
        new_btn.clicked.connect(self.new_post_requested.emit)
        toolbar.addWidget(new_btn)

        sync_btn = QPushButton("Sync OneUp")
        sync_btn.setObjectName("toolbar_btn")
        sync_btn.clicked.connect(self.sync_requested.emit)
        toolbar.addWidget(sync_btn)

        fill_btn = QPushButton("Fill Gaps")
        fill_btn.setObjectName("toolbar_btn")
        fill_btn.clicked.connect(self.fill_gaps_requested.emit)
        toolbar.addWidget(fill_btn)

        toolbar.addStretch()

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All", "Drafts", "Queued", "Posted", "Failed"])
        self._filter_combo.currentTextChanged.connect(lambda _: self.refresh())
        toolbar.addWidget(QLabel("Filter:"))
        toolbar.addWidget(self._filter_combo)

        outer.addLayout(toolbar)

        # Summary bar
        self._summary_label = QLabel()
        self._summary_label.setContentsMargins(8, 2, 8, 2)
        outer.addWidget(self._summary_label)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 4, 8, 4)
        self._content_layout.setSpacing(6)
        self._content_layout.addStretch()
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

    def set_project(self, project: Project):
        self._project = project
        self.refresh()

    def refresh(self):
        if not self._project:
            return

        # Clear existing cards
        while self._content_layout.count() > 1:  # keep stretch
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Filter
        status_filter = self._filter_combo.currentText().lower()
        posts = list(self._project.posts)
        if status_filter != "all":
            # "drafts" -> "draft", "queued" -> "queued", etc.
            sf = status_filter.rstrip("s") if status_filter.endswith("s") else status_filter
            posts = [p for p in posts if p.status == sf]

        # Sort by scheduled_time
        posts.sort(key=lambda p: p.scheduled_time or "9999")

        # Group by day
        days: dict[str, list[SocialPost]] = {}
        for p in posts:
            day = p.scheduled_time[:10] if p.scheduled_time else "Unscheduled"
            days.setdefault(day, []).append(p)

        # Build date range for gap detection (next 14 days)
        today = datetime.now()
        all_days = set(days.keys())
        date_range = []
        for i in range(14):
            d = (today + timedelta(days=i)).strftime("%Y-%m-%d")
            date_range.append(d)

        # Render timeline
        idx = 0  # insert index (before stretch)
        for day_str in date_range:
            if day_str in days:
                # Day header
                try:
                    dt = datetime.strptime(day_str, "%Y-%m-%d")
                    if dt.date() == today.date():
                        header_text = f"Today — {dt.strftime('%b %d')}"
                    elif dt.date() == (today + timedelta(days=1)).date():
                        header_text = f"Tomorrow — {dt.strftime('%b %d')}"
                    else:
                        header_text = dt.strftime("%b %d — %A")
                except ValueError:
                    header_text = day_str

                header = QLabel(header_text)
                header.setObjectName("timeline_day_header")
                self._content_layout.insertWidget(idx, header)
                idx += 1

                for post in days[day_str]:
                    card = PostCard(post, self._project)
                    card.clicked.connect(self.post_selected.emit)
                    self._content_layout.insertWidget(idx, card)
                    idx += 1
            else:
                # Gap
                gap = GapMarker(day_str)
                self._content_layout.insertWidget(idx, gap)
                idx += 1

        # Render unscheduled posts at end
        if "Unscheduled" in days:
            header = QLabel("Unscheduled")
            header.setObjectName("timeline_day_header")
            self._content_layout.insertWidget(idx, header)
            idx += 1
            for post in days["Unscheduled"]:
                card = PostCard(post, self._project)
                card.clicked.connect(self.post_selected.emit)
                self._content_layout.insertWidget(idx, card)
                idx += 1

        # Summary
        total = len(self._project.posts)
        by_status = {}
        for p in self._project.posts:
            by_status[p.status] = by_status.get(p.status, 0) + 1
        gap_count = len([d for d in date_range if d not in all_days])
        parts = [f"{total} posts"]
        for s in ["draft", "queued", "posted", "failed"]:
            if by_status.get(s, 0):
                parts.append(f"{by_status[s]} {s}")
        if gap_count:
            parts.append(f"{gap_count} gaps")
        self._summary_label.setText(" · ".join(parts))
```

- [ ] **Step 2: Test widget instantiation (headless)**

```bash
cd E:/git/doxyedit && python -c "
from doxyedit.models import Project, SocialPost, SocialPostStatus
from datetime import datetime, timedelta

# Verify imports work
from doxyedit.timeline import TimelineStream, PostCard, GapMarker, StatusBadge, PlatformBadge
print('PASS: timeline module imports correctly')
"
```

- [ ] **Step 3: Commit**

```bash
git add doxyedit/timeline.py
git commit -m "feat: add TimelineStream widget — scrollable post feed with day groups and gap markers"
```

---

### Task 6: Post Composer Dialog

**Files:**
- Create: `doxyedit/composer.py`

- [ ] **Step 1: Create post composer dialog**

```python
"""Post composer — create or edit a social media post."""
from __future__ import annotations
import uuid
from datetime import datetime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QCheckBox, QDateTimeEdit, QFrame,
    QScrollArea, QWidget, QSizePolicy, QGroupBox,
)
from PySide6.QtCore import Qt, QDateTime
from doxyedit.models import Project, SocialPost, SocialPostStatus


# Social platforms supported via OneUp
SOCIAL_PLATFORMS = [
    "twitter", "instagram", "bluesky", "reddit",
    "patreon", "discord", "tiktok", "pinterest",
]


class PostComposer(QDialog):
    """Dialog for creating or editing a social media post."""

    def __init__(self, project: Project, post: SocialPost | None = None, parent=None):
        super().__init__(parent)
        self._project = project
        self._editing = post
        self.result_post: SocialPost | None = None

        self.setWindowTitle("Edit Post" if post else "New Post")
        self.setMinimumSize(500, 600)
        self.resize(600, 700)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # --- Images ---
        img_group = QGroupBox("Images")
        img_layout = QVBoxLayout(img_group)
        self._asset_input = QLineEdit()
        self._asset_input.setPlaceholderText("Asset IDs, comma-separated (e.g. devil_01, devil_02)")
        if post:
            self._asset_input.setText(", ".join(post.asset_ids))
        img_layout.addWidget(self._asset_input)
        layout.addWidget(img_group)

        # --- Platforms ---
        plat_group = QGroupBox("Platforms")
        plat_layout = QHBoxLayout(plat_group)
        plat_layout.setSpacing(8)
        self._plat_checks: dict[str, QCheckBox] = {}

        identity = project.get_identity()
        default_plats = set(identity.default_platforms) if identity.default_platforms else set()
        active_plats = set(post.platforms) if post else default_plats

        for p in SOCIAL_PLATFORMS:
            cb = QCheckBox(p.title())
            cb.setChecked(p in active_plats)
            plat_layout.addWidget(cb)
            self._plat_checks[p] = cb
        layout.addWidget(plat_group)

        # --- Caption ---
        cap_group = QGroupBox("Caption")
        cap_layout = QVBoxLayout(cap_group)
        self._caption_edit = QTextEdit()
        self._caption_edit.setPlaceholderText("Write your caption here...")
        self._caption_edit.setMaximumHeight(120)
        if post:
            self._caption_edit.setPlainText(post.caption_default)
        cap_layout.addWidget(self._caption_edit)

        # Per-platform toggle
        self._per_plat_btn = QPushButton("Per-platform captions ▼")
        self._per_plat_btn.setCheckable(True)
        self._per_plat_btn.toggled.connect(self._toggle_per_platform)
        cap_layout.addWidget(self._per_plat_btn)

        self._per_plat_container = QWidget()
        self._per_plat_container.setVisible(False)
        self._per_plat_layout = QVBoxLayout(self._per_plat_container)
        self._per_plat_layout.setContentsMargins(0, 0, 0, 0)
        self._per_plat_edits: dict[str, QTextEdit] = {}
        for p in SOCIAL_PLATFORMS:
            row = QHBoxLayout()
            lbl = QLabel(f"{p.title()}:")
            lbl.setFixedWidth(80)
            row.addWidget(lbl)
            edit = QTextEdit()
            edit.setMaximumHeight(60)
            edit.setPlaceholderText(f"Override caption for {p}...")
            if post and p in post.captions:
                edit.setPlainText(post.captions[p])
            row.addWidget(edit)
            self._per_plat_edits[p] = edit
            self._per_plat_layout.addLayout(row)
        cap_layout.addWidget(self._per_plat_container)

        layout.addWidget(cap_group)

        # --- Links ---
        link_group = QGroupBox("Links")
        link_layout = QVBoxLayout(link_group)
        self._link_input = QLineEdit()
        self._link_input.setPlaceholderText("Gumroad/Patreon URL")
        if post and post.links:
            self._link_input.setText(post.links[0])
        link_layout.addWidget(self._link_input)
        layout.addWidget(link_group)

        # --- Schedule ---
        sched_group = QGroupBox("Schedule")
        sched_layout = QHBoxLayout(sched_group)
        self._datetime_edit = QDateTimeEdit()
        self._datetime_edit.setCalendarPopup(True)
        self._datetime_edit.setDisplayFormat("yyyy-MM-dd hh:mm AP")
        if post and post.scheduled_time:
            try:
                dt = datetime.fromisoformat(post.scheduled_time)
                self._datetime_edit.setDateTime(QDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute))
            except (ValueError, TypeError):
                self._datetime_edit.setDateTime(QDateTime.currentDateTime())
        else:
            self._datetime_edit.setDateTime(QDateTime.currentDateTime().addDays(1))
        sched_layout.addWidget(self._datetime_edit)
        layout.addWidget(sched_group)

        # --- Reply templates ---
        reply_group = QGroupBox("Reply Templates")
        reply_layout = QVBoxLayout(reply_group)
        self._reply_edit = QTextEdit()
        self._reply_edit.setPlaceholderText("One reply per line — pre-written responses for engagement")
        self._reply_edit.setMaximumHeight(80)
        if post and post.reply_templates:
            self._reply_edit.setPlainText("\n".join(post.reply_templates))
        reply_layout.addWidget(self._reply_edit)
        layout.addWidget(reply_group)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save Draft")
        save_btn.clicked.connect(lambda: self._save(SocialPostStatus.DRAFT))
        btn_row.addWidget(save_btn)
        queue_btn = QPushButton("Queue to OneUp")
        queue_btn.clicked.connect(lambda: self._save(SocialPostStatus.QUEUED))
        btn_row.addWidget(queue_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _toggle_per_platform(self, checked: bool):
        self._per_plat_container.setVisible(checked)
        self._per_plat_btn.setText("Per-platform captions ▲" if checked else "Per-platform captions ▼")

    def _save(self, status: str):
        now = datetime.now().isoformat()
        asset_ids = [a.strip() for a in self._asset_input.text().split(",") if a.strip()]
        platforms = [p for p, cb in self._plat_checks.items() if cb.isChecked()]
        caption = self._caption_edit.toPlainText().strip()
        captions = {}
        for p, edit in self._per_plat_edits.items():
            text = edit.toPlainText().strip()
            if text:
                captions[p] = text
        links = [self._link_input.text().strip()] if self._link_input.text().strip() else []
        dt = self._datetime_edit.dateTime().toPython()
        replies = [r.strip() for r in self._reply_edit.toPlainText().split("\n") if r.strip()]

        if self._editing:
            post = self._editing
            post.asset_ids = asset_ids
            post.platforms = platforms
            post.caption_default = caption
            post.captions = captions
            post.links = links
            post.scheduled_time = dt.isoformat()
            post.status = status
            post.reply_templates = replies
            post.updated_at = now
        else:
            post = SocialPost(
                id=str(uuid.uuid4()),
                asset_ids=asset_ids,
                platforms=platforms,
                caption_default=caption,
                captions=captions,
                links=links,
                scheduled_time=dt.isoformat(),
                status=status,
                reply_templates=replies,
                created_at=now,
                updated_at=now,
            )

        self.result_post = post
        self.accept()
```

- [ ] **Step 2: Test import**

```bash
cd E:/git/doxyedit && python -c "
from doxyedit.composer import PostComposer, SOCIAL_PLATFORMS
assert len(SOCIAL_PLATFORMS) == 8
print('PASS: composer imports correctly')
"
```

- [ ] **Step 3: Commit**

```bash
git add doxyedit/composer.py
git commit -m "feat: add PostComposer dialog — create/edit posts with platform, caption, schedule, reply templates"
```

---

### Task 7: Wire Timeline into Platforms Tab

**Files:**
- Modify: `doxyedit/window.py`

- [ ] **Step 1: Add imports to window.py**

At the top of `window.py`, add:

```python
from doxyedit.timeline import TimelineStream
from doxyedit.composer import PostComposer
```

- [ ] **Step 2: Replace kanban with timeline as primary, keep kanban as toggle**

In the Platforms tab assembly section (around lines 268-297), replace the right column setup. The new structure:

```
Left: PlatformPanel (existing slot assignments)
Right: TimelineStream (new, replaces kanban as primary)
       KanbanPanel (toggle with a "Kanban" button)
       ChecklistPanel (below)
```

Replace the right column assembly (lines 271-288) with:

```python
        # Line 271: Timeline (new primary) + Kanban (toggle)
        self._timeline = TimelineStream()
        self._timeline.set_project(self.project)
        self._timeline.post_selected.connect(self._on_post_selected)
        self._timeline.new_post_requested.connect(self._on_new_post)
        self._timeline.sync_requested.connect(self._on_sync_oneup)

        self._kanban_panel = KanbanPanel()
        self._kanban_panel.status_changed.connect(self._on_data_changed)
        self._kanban_panel.status_changed.connect(lambda: self.platform_panel.refresh())

        # Toggle between timeline and kanban
        from PySide6.QtWidgets import QStackedWidget as _SW
        self._plat_stack = _SW()
        self._plat_stack.addWidget(self._timeline)       # page 0
        self._plat_stack.addWidget(self._kanban_panel)    # page 1

        self.checklist_panel = ChecklistPanel(self.project)

        _right_col = QSplitter(Qt.Orientation.Vertical)
        _right_col.addWidget(self._plat_stack)
        _right_col.addWidget(self.checklist_panel)
        _right_col.setSizes([500, 150])

        _plat_top = QSplitter(Qt.Orientation.Horizontal)
        _plat_top.addWidget(self.platform_panel)
        _plat_top.addWidget(_right_col)
        _plat_top.setSizes([400, 600])
```

- [ ] **Step 3: Add handler methods to the main window class**

```python
    def _on_post_selected(self, post_id: str):
        """Open composer to edit an existing post."""
        post = self.project.get_post(post_id)
        if not post:
            return
        dlg = PostComposer(self.project, post=post, parent=self)
        if dlg.exec() and dlg.result_post:
            # Post was edited in-place by the composer
            self._dirty = True
            self._timeline.refresh()
            self.platform_panel.refresh()

    def _on_new_post(self):
        """Open composer to create a new post."""
        dlg = PostComposer(self.project, parent=self)
        if dlg.exec() and dlg.result_post:
            self.project.posts.append(dlg.result_post)
            self._dirty = True
            self._timeline.refresh()

    def _on_sync_oneup(self):
        """Sync post statuses from OneUp API."""
        from doxyedit.oneup import get_client_from_config, OneUpClient
        from doxyedit.models import SocialPostStatus
        project_dir = str(Path(self._project_path).parent) if hasattr(self, '_project_path') else "."

        client = get_client_from_config(project_dir)
        if not client:
            key = (self.project.oneup_config or {}).get("api_key", "")
            if key:
                client = OneUpClient(key)
        if not client:
            self.statusBar().showMessage("No OneUp API key configured", 5000)
            return

        updated = 0
        for post in self.project.posts:
            if post.status == SocialPostStatus.QUEUED and post.oneup_post_id:
                result = client.get_post(post.oneup_post_id)
                if result.success:
                    rs = result.data.get("status", "")
                    if rs == "published":
                        post.status = SocialPostStatus.POSTED
                        updated += 1
                    elif rs == "failed":
                        post.status = SocialPostStatus.FAILED
                        updated += 1

        if updated:
            self._dirty = True
            self._timeline.refresh()
        self.statusBar().showMessage(f"Synced: {updated} post(s) updated", 3000)
```

- [ ] **Step 4: Add "Timeline / Kanban" toggle to View menu or toolbar**

In the menu setup, add a toggle action:

```python
        self._timeline_toggle = view_menu.addAction("Show Kanban (legacy)")
        self._timeline_toggle.setCheckable(True)
        self._timeline_toggle.setChecked(False)
        self._timeline_toggle.toggled.connect(
            lambda show_kanban: self._plat_stack.setCurrentIndex(1 if show_kanban else 0))
```

- [ ] **Step 5: Update refresh calls to include timeline**

Anywhere the window calls `self.platform_panel.refresh()` or `self._kanban_panel.refresh()`, add `self._timeline.refresh()` too. Key spots:
- After project load
- After `_on_data_changed`
- After assignment changes

- [ ] **Step 6: Test launch**

```bash
cd E:/git/doxyedit && python -m doxyedit run
```

Verify:
1. Platforms tab shows timeline stream on the right (not kanban)
2. "+ New Post" button opens composer dialog
3. Creating a post adds it to the timeline
4. Clicking a post card opens it for editing
5. Filter dropdown filters posts by status
6. View menu has "Show Kanban (legacy)" toggle

- [ ] **Step 7: Commit**

```bash
git add doxyedit/window.py doxyedit/timeline.py doxyedit/composer.py
git commit -m "feat: wire TimelineStream + PostComposer into Platforms tab, kanban becomes toggle"
```

---

### Task 8: Integration Test — Full CLI-to-GUI Round Trip

- [ ] **Step 1: Create test post via CLI, verify in GUI**

```bash
# Create a post via CLI
cd E:/git/doxyedit
python -m doxyedit post create doxyart.doxyproj.json \
  --assets "007_4" \
  --platforms "twitter,instagram,bluesky" \
  --caption "Test post from CLI!" \
  --schedule "2026-04-15T10:00:00" \
  --link "https://gumroad.com/test"

# Show schedule
python -m doxyedit schedule doxyart.doxyproj.json

# Show gaps
python -m doxyedit gaps doxyart.doxyproj.json --days 7

# Show suggestions
python -m doxyedit suggest doxyart.doxyproj.json --count 3

# Launch GUI — verify the post appears in timeline
python -m doxyedit run
```

- [ ] **Step 2: Edit post in GUI, verify via CLI**

1. In the GUI, click the test post in timeline → opens composer
2. Change caption, add a platform
3. Save
4. Back in terminal: `python -m doxyedit schedule doxyart.doxyproj.json`
5. Verify changes appear

- [ ] **Step 3: Clean up test post**

```bash
# Get the post ID from the schedule output, then:
python -m doxyedit post delete doxyart.doxyproj.json <post-id>
```

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -u
git commit -m "fix: integration fixes from CLI-to-GUI round trip testing"
```

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | Data model (SocialPost, CollectionIdentity) | models.py | 1 |
| 2 | OneUp API client | oneup.py (new) | 1 |
| 3 | CLI commands (schedule, gaps, post CRUD, suggest) | __main__.py | 1 |
| 4 | Theme tokens + timeline QSS | themes.py | 1 |
| 5 | TimelineStream widget | timeline.py (new) | 1 |
| 6 | PostComposer dialog | composer.py (new) | 1 |
| 7 | Wire into Platforms tab | window.py | 1 |
| 8 | Integration test | all | 0-1 |

Total: ~7-8 commits, 3 new files, 4 modified files.
