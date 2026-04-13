"""CLI entry point — python -m doxyedit [command] [args]

Commands:
    run                       Launch the GUI (default)
    summary <project.json>    Print project status summary
    tags <project.json>       List all assets and their tags
    untagged <project.json>   List assets with no tags
    status <project.json>     Platform assignment status
    search <project.json> <q> Search assets by name or tag
    starred <project.json>    List starred assets
    ignored <project.json>    List ignored assets
    add-tag <project.json> <asset_id> <tag>   Add tag to asset
    remove-tag <project.json> <asset_id> <tag> Remove tag from asset
    set-star <project.json> <asset_id> <0-5>  Set star rating
    export-json <project.json>                Full project as JSON
    notes <project.json>      List assets with notes
    schedule <project.json>   Show upcoming post schedule
    gaps <project.json>       Find days with no scheduled posts
    suggest <project.json>    Suggest unposted assets to schedule
    post create <project.json> [options]   Create a draft post
    post update <project.json> <post-id> [options]  Update a post
    post push <project.json> [post-id|--all-drafts]  Push to OneUp
    post sync <project.json>  Sync post statuses from OneUp
    post delete <project.json> <post-id>  Delete a post
"""
import sys
import os
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path


def cmd_summary(path: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    s = proj.summary()
    total = s.get("total_assets", 0)
    starred = s.get("starred", 0)
    tagged = sum(1 for a in proj.assets if a.tags)
    ignored = sum(1 for a in proj.assets if "ignore" in a.tags)
    print(f"Assets: {total} | Tagged: {tagged} | Starred: {starred} | Ignored: {ignored}")
    print(f"Custom tags: {len(proj.custom_tags)} | Tray: {len(proj.tray_items)}")
    for pid, info in s.get("platforms", {}).items():
        print(f"  {info['name']}: {info['assigned']}/{info['slots_total']} slots, {info['posted']} posted")


def cmd_tags(path: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    for a in proj.assets:
        tags = ", ".join(a.tags) if a.tags else "(none)"
        star = f" [{a.starred}*]" if a.starred else ""
        print(f"{a.stem}{star}: {tags}")
    print(f"\n--- {len(proj.assets)} assets, {sum(1 for a in proj.assets if a.tags)} tagged ---")


def cmd_untagged(path: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    untagged = [a for a in proj.assets if not a.tags]
    for a in untagged:
        print(f"{a.stem}  ({a.source_path})")
    print(f"\n--- {len(untagged)}/{len(proj.assets)} untagged ---")


def cmd_starred(path: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    for a in proj.assets:
        if a.starred > 0:
            print(f"[{a.starred}*] {a.stem}: {', '.join(a.tags)}")
    print(f"\n--- {sum(1 for a in proj.assets if a.starred > 0)} starred ---")


def cmd_ignored(path: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    for a in proj.assets:
        if "ignore" in a.tags:
            print(a.stem)
    print(f"\n--- {sum(1 for a in proj.assets if 'ignore' in a.tags)} ignored ---")


def cmd_notes(path: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    for a in proj.assets:
        if a.notes.strip():
            print(f"=== {a.stem} ===")
            print(a.notes.strip())
            print()


def cmd_search(path: str, query: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    q = query.lower()
    results = [a for a in proj.assets
               if q in a.stem.lower() or any(q in t for t in a.tags)]
    for a in results:
        print(f"{a.stem}: {', '.join(a.tags)}")
    print(f"\n--- {len(results)} matches ---")


def cmd_add_tag(path: str, asset_id: str, tag: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    asset = proj.get_asset(asset_id)
    if not asset:
        print(f"Asset '{asset_id}' not found")
        sys.exit(1)
    if tag not in asset.tags:
        asset.tags.append(tag)
        proj.save(path)
        print(f"Added '{tag}' to {asset.stem}")
    else:
        print(f"'{tag}' already on {asset.stem}")


def cmd_remove_tag(path: str, asset_id: str, tag: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    asset = proj.get_asset(asset_id)
    if not asset:
        print(f"Asset '{asset_id}' not found")
        sys.exit(1)
    if tag in asset.tags:
        asset.tags.remove(tag)
        proj.save(path)
        print(f"Removed '{tag}' from {asset.stem}")
    else:
        print(f"'{tag}' not on {asset.stem}")


def cmd_set_star(path: str, asset_id: str, value: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    asset = proj.get_asset(asset_id)
    if not asset:
        print(f"Asset '{asset_id}' not found")
        sys.exit(1)
    asset.starred = int(value)
    proj.save(path)
    print(f"Set star={value} on {asset.stem}")


def cmd_export_json(path: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    print(Path(path).read_text())


def cmd_sync_tags(path: str, registry_path: str):
    """Merge tags bidirectionally between doxyproj and an external registry JSON."""
    from doxyedit.models import Project
    proj = Project.load(path)
    reg = json.loads(Path(registry_path).read_text())
    reg_assets = {Path(a["path"]).stem: a for a in reg.get("assets", [])}

    merged = 0
    for asset in proj.assets:
        key = asset.stem
        if key in reg_assets:
            reg_asset = reg_assets[key]
            reg_tags = set(reg_asset.get("tags", []))
            proj_tags = set(asset.tags)
            combined = proj_tags | reg_tags
            if combined != proj_tags:
                asset.tags = list(combined)
                merged += 1
            if combined != reg_tags:
                reg_asset["tags"] = list(combined)
                merged += 1

    proj.save(path)
    Path(registry_path).write_text(json.dumps(reg, indent=2))
    print(f"Synced {merged} tag changes between {Path(path).name} and {Path(registry_path).name}")


def cmd_strip_tags(path: str, tags_to_strip: str):
    """Bulk remove specific tags from all assets."""
    from doxyedit.models import Project
    proj = Project.load(path)
    strip = set(tags_to_strip.split(","))
    count = 0
    for asset in proj.assets:
        before = len(asset.tags)
        asset.tags = [t for t in asset.tags if t not in strip]
        if len(asset.tags) < before:
            count += 1
    proj.save(path)
    print(f"Stripped {strip} from {count} assets")


def cmd_find_dupes(path: str, threshold: int = 10):
    """Perceptual hash scan for duplicates."""
    from doxyedit.models import Project
    from PIL import Image as PILImage
    proj = Project.load(path)

    # Simple average hash
    def ahash(img_path, size=8):
        try:
            img = PILImage.open(img_path).convert("L").resize((size, size))
            avg = sum(img.getdata()) / (size * size)
            return sum(1 << i for i, p in enumerate(img.getdata()) if p > avg)
        except Exception:
            return None

    print("Computing hashes...")
    hashes = {}
    for a in proj.assets:
        h = ahash(a.source_path)
        if h is not None:
            hashes.setdefault(h, []).append(a)

    groups = {h: assets for h, assets in hashes.items() if len(assets) > 1}
    tagged = 0
    for h, assets in groups.items():
        assets.sort(key=lambda a: -os.path.getsize(a.source_path) if os.path.exists(a.source_path) else 0)
        print(f"\nDuplicate group ({len(assets)} files):")
        for i, a in enumerate(assets):
            size = os.path.getsize(a.source_path) if os.path.exists(a.source_path) else 0
            marker = " (KEEP)" if i == 0 else " → tagged duplicate"
            print(f"  {a.stem} ({size//1024}KB){marker}")
            if i > 0 and "duplicate" not in a.tags:
                a.tags.append("duplicate")
                tagged += 1

    proj.save(path)
    print(f"\n{len(groups)} duplicate groups found, {tagged} assets tagged as duplicate")


def cmd_assign_slots(path: str):
    """Auto-suggest best-fit images for each platform slot."""
    from doxyedit.models import Project, PLATFORMS, check_fitness
    from PIL import Image as PILImage
    proj = Project.load(path)

    for pid in proj.platforms:
        platform = PLATFORMS.get(pid)
        if not platform:
            continue
        print(f"\n=== {platform.name} ===")
        for slot in platform.slots:
            best = None
            best_score = -1
            tag_preset = type('P', (), {'width': slot.width, 'height': slot.height})()
            for a in proj.assets:
                if "ignore" in a.tags or "duplicate" in a.tags:
                    continue
                try:
                    img = PILImage.open(a.source_path)
                    w, h = img.size
                    img.close()
                except Exception:
                    continue
                fitness = check_fitness(w, h, tag_preset)
                score = {"green": 3, "yellow": 2, "red": 0}.get(fitness, 0)
                score += a.starred
                if score > best_score:
                    best_score = score
                    best = (a, w, h, fitness)
            if best:
                a, w, h, fit = best
                print(f"  {slot.label} ({slot.width}x{slot.height}): {a.stem} [{w}x{h}] fitness={fit} star={a.starred}")
            else:
                print(f"  {slot.label} ({slot.width}x{slot.height}): no candidates")


def cmd_export_platform(path: str, platform_id: str, output: str):
    """Export assigned slot images resized to platform specs."""
    from doxyedit.models import Project
    from doxyedit.exporter import export_project
    proj = Project.load(path)
    # Filter to just this platform
    orig = proj.platforms
    proj.platforms = [platform_id]
    manifest = export_project(proj, output)
    proj.platforms = orig
    n = len(manifest["exports"])
    print(f"Exported {n} files to {output}")
    for e in manifest["exports"]:
        print(f"  {e['slot']}: {e['file']} ({e['size']})")


def cmd_search_advanced(path: str, tag: str = None, min_width: int = 0, aspect: str = None):
    """Advanced search by tag, dimensions, aspect."""
    from doxyedit.models import Project
    proj = Project.load(path)
    results = proj.assets
    if tag:
        results = [a for a in results if tag in a.tags]
    if min_width > 0:
        from PIL import Image as PILImage
        filtered = []
        for a in results:
            try:
                img = PILImage.open(a.source_path)
                if img.width >= min_width:
                    filtered.append((a, img.width, img.height))
                img.close()
            except Exception:
                pass
        results = filtered
    else:
        results = [(a, 0, 0) for a in results]
    if aspect:
        final = []
        for a, w, h in results:
            if w == 0:
                try:
                    from PIL import Image as PILImage
                    img = PILImage.open(a.source_path)
                    w, h = img.size
                    img.close()
                except Exception:
                    continue
            ratio = w / h if h else 1
            if aspect == "landscape" and ratio > 1.2:
                final.append((a, w, h))
            elif aspect == "portrait" and ratio < 0.8:
                final.append((a, w, h))
            elif aspect == "square" and 0.8 <= ratio <= 1.2:
                final.append((a, w, h))
        results = final

    for a, w, h in results:
        dim = f" ({w}x{h})" if w else ""
        print(f"{a.stem}{dim}: {', '.join(a.tags)}")
    print(f"\n--- {len(results)} matches ---")


def cmd_extract_thumbs(path: str, size: int = 512, output: str = None):
    """Extract proxy thumbnails for all assets that don't have one yet."""
    from doxyedit.models import Project
    from doxyedit.imaging import open_for_thumb, pil_to_qpixmap
    from PIL import Image as PILImage

    proj = Project.load(path)
    out_dir = Path(output) if output else Path(path).parent / "thumbnails"
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(proj.assets)
    exported = 0
    skipped = 0
    failed = 0

    for i, asset in enumerate(proj.assets):
        out_file = out_dir / f"{asset.id}.png"
        if out_file.exists():
            skipped += 1
            continue
        try:
            img, w, h = open_for_thumb(asset.source_path, size)
            img.thumbnail((size, size), PILImage.LANCZOS)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            img.save(str(out_file), "PNG")
            exported += 1
            if (i + 1) % 20 == 0:
                print(f"  [{i+1}/{total}] exported {exported}, skipped {skipped}, failed {failed}")
        except Exception as e:
            failed += 1

    print(f"\nDone: {exported} exported, {skipped} already existed, {failed} failed")
    print(f"Output: {out_dir}")


def cmd_status(path: str):
    from doxyedit.models import Project, PLATFORMS
    proj = Project.load(path)
    for pid in proj.platforms:
        platform = PLATFORMS.get(pid)
        if not platform:
            continue
        print(f"\n=== {platform.name} ===")
        for slot in platform.slots:
            assigned = None
            for a in proj.assets:
                for pa in a.assignments:
                    if pa.platform == pid and pa.slot == slot.name:
                        assigned = (a, pa)
                        break
                if assigned:
                    break
            if assigned:
                a, pa = assigned
                print(f"  {slot.label} ({slot.width}x{slot.height}): {a.stem} [{pa.status}]")
            else:
                req = " (REQUIRED)" if slot.required else ""
                print(f"  {slot.label} ({slot.width}x{slot.height}): -- empty --{req}")


def cmd_schedule(project_path: str, args: list):
    """Show upcoming post schedule with optional filters."""
    from doxyedit.models import Project, SocialPostStatus
    proj = Project.load(project_path)

    from_date = to_date = status_filter = fmt = None
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

    posts = sorted(proj.posts, key=lambda p: p.scheduled_time or "")
    if from_date:
        posts = [p for p in posts if p.scheduled_time and p.scheduled_time[:10] >= from_date]
    if to_date:
        posts = [p for p in posts if p.scheduled_time and p.scheduled_time[:10] <= to_date]
    if status_filter:
        posts = [p for p in posts if p.status == status_filter]

    if fmt == "json":
        print(json.dumps([p.to_dict() for p in posts], indent=2))
        return

    STATUS_ICONS = {
        SocialPostStatus.DRAFT: "[ ]",
        SocialPostStatus.QUEUED: "[~]",
        SocialPostStatus.POSTED: "[x]",
        SocialPostStatus.FAILED: "[!]",
        SocialPostStatus.PARTIAL: "[/]",
    }

    asset_map = {a.id: a for a in proj.assets}

    if not posts:
        print("No posts found.")
        return

    for p in posts:
        icon = STATUS_ICONS.get(p.status, "?")
        dt = p.scheduled_time[:16] if p.scheduled_time else "(unscheduled)"
        asset_names = ", ".join(
            asset_map[aid].stem if aid in asset_map else aid
            for aid in p.asset_ids
        ) or "(no assets)"
        platforms = ", ".join(p.platforms) or "(no platforms)"
        caption_preview = (p.caption_default[:40] + "...") if len(p.caption_default) > 40 else p.caption_default
        print(f"{icon} [{p.status:<7}] {dt}  |  {asset_names}  |  {platforms}  |  {caption_preview!r}  |  {p.id}")

    print(f"\n--- {len(posts)} post(s) ---")


def cmd_gaps(project_path: str, args: list):
    """Find days with no scheduled posts."""
    from doxyedit.models import Project
    proj = Project.load(project_path)

    from_date = None
    days = 30
    fmt = None
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

    if from_date is None:
        from_date = datetime.now().strftime("%Y-%m-%d")

    scheduled_days = set()
    for p in proj.posts:
        if p.scheduled_time:
            scheduled_days.add(p.scheduled_time[:10])

    start = datetime.strptime(from_date, "%Y-%m-%d")
    gaps = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
        if day not in scheduled_days:
            gaps.append(day)

    if fmt == "json":
        print(json.dumps(gaps))
        return

    if not gaps:
        print(f"No gaps in the next {days} days from {from_date}.")
        return

    for day in gaps:
        print(day)
    print(f"\n--- {len(gaps)} gap day(s) in {days}-day window from {from_date} ---")


def cmd_post_create(project_path: str, args: list):
    """Create a draft post."""
    from doxyedit.models import Project, SocialPost, SocialPostStatus

    asset_ids = []
    platforms = []
    caption_default = ""
    captions = {}
    links = []
    scheduled_time = ""
    reply_templates = []
    fmt = None

    i = 0
    while i < len(args):
        if args[i] == "--assets" and i + 1 < len(args):
            asset_ids = [x.strip() for x in args[i + 1].split(",")]; i += 2
        elif args[i] == "--platforms" and i + 1 < len(args):
            platforms = [x.strip() for x in args[i + 1].split(",")]; i += 2
        elif args[i] == "--caption" and i + 1 < len(args):
            caption_default = args[i + 1]; i += 2
        elif args[i].startswith("--caption-") and i + 1 < len(args):
            plat_key = args[i][len("--caption-"):]
            captions[plat_key] = args[i + 1]; i += 2
        elif args[i] == "--link" and i + 1 < len(args):
            links.append(args[i + 1]); i += 2
        elif args[i] == "--schedule" and i + 1 < len(args):
            scheduled_time = args[i + 1]; i += 2
        elif args[i] == "--reply-template" and i + 1 < len(args):
            reply_templates.append(args[i + 1]); i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    proj = Project.load(project_path)
    now = datetime.now().isoformat()
    post = SocialPost(
        id=str(uuid.uuid4()),
        asset_ids=asset_ids,
        platforms=platforms,
        captions=captions,
        caption_default=caption_default,
        links=links,
        scheduled_time=scheduled_time,
        status=SocialPostStatus.DRAFT,
        reply_templates=reply_templates,
        created_at=now,
        updated_at=now,
    )
    proj.posts.append(post)
    proj.save(project_path)

    if fmt == "json":
        print(json.dumps(post.to_dict(), indent=2))
    else:
        print(f"Created post {post.id}")
        print(f"  Assets:    {', '.join(asset_ids) or '(none)'}")
        print(f"  Platforms: {', '.join(platforms) or '(none)'}")
        print(f"  Caption:   {caption_default!r}")
        print(f"  Schedule:  {scheduled_time or '(unscheduled)'}")


def cmd_post_update(project_path: str, post_id: str, args: list):
    """Update an existing post."""
    from doxyedit.models import Project, SocialPostStatus

    proj = Project.load(project_path)
    post = proj.get_post(post_id)
    if not post:
        print(f"Post '{post_id}' not found")
        sys.exit(1)

    i = 0
    while i < len(args):
        if args[i] == "--caption" and i + 1 < len(args):
            post.caption_default = args[i + 1]; i += 2
        elif args[i].startswith("--caption-") and i + 1 < len(args):
            plat_key = args[i][len("--caption-"):]
            post.captions[plat_key] = args[i + 1]; i += 2
        elif args[i] == "--schedule" and i + 1 < len(args):
            post.scheduled_time = args[i + 1]; i += 2
        elif args[i] == "--add-platform" and i + 1 < len(args):
            p = args[i + 1]
            if p not in post.platforms:
                post.platforms.append(p)
            i += 2
        elif args[i] == "--remove-platform" and i + 1 < len(args):
            p = args[i + 1]
            if p in post.platforms:
                post.platforms.remove(p)
            i += 2
        elif args[i] == "--link" and i + 1 < len(args):
            if args[i + 1] not in post.links:
                post.links.append(args[i + 1])
            i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            post.status = args[i + 1]; i += 2
        elif args[i] == "--reply-template" and i + 1 < len(args):
            post.reply_templates.append(args[i + 1]); i += 2
        else:
            i += 1

    post.updated_at = datetime.now().isoformat()
    proj.save(project_path)
    print(f"Updated post {post.id}")


def cmd_post_push(project_path: str, args: list):
    """Push post(s) to OneUp."""
    from doxyedit.models import Project, SocialPostStatus

    all_drafts = "--all-drafts" in args
    post_id = None
    i = 0
    while i < len(args):
        if args[i] == "--all-drafts":
            i += 1
        elif not args[i].startswith("--"):
            post_id = args[i]; i += 1
        else:
            i += 1

    proj = Project.load(project_path)

    if all_drafts:
        targets = [p for p in proj.posts if p.status == SocialPostStatus.DRAFT]
    elif post_id:
        post = proj.get_post(post_id)
        if not post:
            print(f"Post '{post_id}' not found")
            sys.exit(1)
        targets = [post]
    else:
        print("Usage: python -m doxyedit post push <project.json> <post-id|--all-drafts>")
        sys.exit(1)

    if not targets:
        print("No posts to push.")
        return

    from doxyedit.oneup import get_client_from_config, OneUpClient
    project_dir = str(Path(project_path).parent)
    client = get_client_from_config(project_dir)
    if not client:
        key = (proj.oneup_config or {}).get("api_key", "")
        if key:
            cat = str((proj.oneup_config or {}).get("category_id", ""))
            client = OneUpClient(key, cat)
    if not client:
        print("No OneUp API key. Marking posts as queued (offline mode).")
        for post in targets:
            post.status = SocialPostStatus.QUEUED
            post.updated_at = datetime.now().isoformat()
        proj.save(project_path)
        return

    pushed = failed = 0
    for post in targets:
        # Format scheduled time for OneUp: "YYYY-MM-DD HH:MM"
        sched = ""
        if post.scheduled_time:
            sched = post.scheduled_time[:16].replace("T", " ")
        result = client.schedule_post(
            content=post.caption_default,
            image_urls=None,  # TODO: need public image URLs
            social_network_id="ALL",
            scheduled_date_time=sched,
        )
        if result.success:
            post.oneup_post_id = result.data.get("id", "")
            post.status = SocialPostStatus.QUEUED
            post.updated_at = datetime.now().isoformat()
            pushed += 1
            print(f"  ✓ Pushed {post.id[:8]}... → OneUp")
        else:
            post.status = SocialPostStatus.FAILED
            post.updated_at = datetime.now().isoformat()
            failed += 1
            print(f"  ✗ Failed {post.id[:8]}...: {result.error}")

    proj.save(project_path)
    print(f"\nPushed {pushed}, failed {failed}")


def cmd_post_sync(project_path: str, args: list):
    """Sync post statuses from OneUp."""
    from doxyedit.models import Project, SocialPostStatus

    proj = Project.load(project_path)
    queued = [p for p in proj.posts if p.status == SocialPostStatus.QUEUED and p.oneup_post_id]

    if not queued:
        print("No queued posts with OneUp IDs to sync.")
        return

    from doxyedit.oneup import get_client_from_config, OneUpClient
    project_dir = str(Path(project_path).parent)
    client = get_client_from_config(project_dir)
    if not client:
        key = (proj.oneup_config or {}).get("api_key", "")
        if key:
            client = OneUpClient(key)
    if not client:
        print("No OneUp API key configured.")
        sys.exit(1)

    updated = 0
    for post in queued:
        result = client.get_post(post.oneup_post_id)
        if result.success:
            remote_status = result.data.get("status", "")
            if remote_status in ("published", "posted"):
                post.status = SocialPostStatus.POSTED
                updated += 1
            elif remote_status in ("failed", "error"):
                post.status = SocialPostStatus.FAILED
                updated += 1
            post.updated_at = datetime.now().isoformat()
            print(f"  {post.id[:8]}...: {remote_status} → {post.status}")
        else:
            print(f"  {post.id[:8]}...: sync error — {result.error}")

    proj.save(project_path)
    print(f"\nSynced {updated} post(s)")


def cmd_post_delete(project_path: str, post_id: str):
    """Delete a post (cancels on OneUp if queued)."""
    from doxyedit.models import Project, SocialPostStatus

    proj = Project.load(project_path)
    post = proj.get_post(post_id)
    if not post:
        print(f"Post '{post_id}' not found")
        sys.exit(1)

    if post.status == SocialPostStatus.QUEUED and post.oneup_post_id:
        from doxyedit.oneup import get_client_from_config, OneUpClient
        project_dir = str(Path(project_path).parent)
        client = get_client_from_config(project_dir)
        if not client:
            key = (proj.oneup_config or {}).get("api_key", "")
            if key:
                client = OneUpClient(key)
        if client:
            result = client.delete_post(post.oneup_post_id)
            if result.success:
                print(f"  Cancelled OneUp post {post.oneup_post_id}")
            else:
                print(f"  Could not cancel on OneUp: {result.error}")

    proj.posts = [p for p in proj.posts if p.id != post_id]
    proj.save(project_path)
    print(f"Deleted post {post_id}")


def cmd_suggest(project_path: str, args: list):
    """Suggest unposted assets scored by stars + tag rarity."""
    from doxyedit.models import Project

    count = 10
    exclude_tags = set()
    fmt = None
    i = 0
    while i < len(args):
        if args[i] == "--count" and i + 1 < len(args):
            count = int(args[i + 1]); i += 2
        elif args[i] == "--exclude-tags" and i + 1 < len(args):
            exclude_tags = set(t.strip() for t in args[i + 1].split(",")); i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    proj = Project.load(project_path)

    # Build set of already-scheduled asset IDs
    scheduled_ids = set()
    for p in proj.posts:
        scheduled_ids.update(p.asset_ids)

    # Build tag frequency map for rarity scoring
    tag_counts: dict[str, int] = {}
    for a in proj.assets:
        for t in a.tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    candidates = []
    for a in proj.assets:
        if a.id in scheduled_ids:
            continue
        if exclude_tags and exclude_tags.intersection(a.tags):
            continue
        rarity = sum(1.0 / tag_counts[t] for t in a.tags if t in tag_counts)
        score = a.starred * 10 + rarity
        candidates.append((score, a))

    candidates.sort(key=lambda x: -x[0])
    top = candidates[:count]

    if fmt == "json":
        result = [
            {"id": a.id, "tags": a.tags, "starred": a.starred, "path": a.source_path, "score": round(score, 3)}
            for score, a in top
        ]
        print(json.dumps(result, indent=2))
        return

    if not top:
        print("No unscheduled assets found.")
        return

    for score, a in top:
        star = f"[{a.starred}*] " if a.starred else "     "
        tags = ", ".join(a.tags) if a.tags else "(no tags)"
        print(f"{star}{a.id:<30} score={score:.2f}  tags: {tags}")

    print(f"\n--- {len(top)} suggestion(s) from {len(candidates)} unscheduled assets ---")


def main():
    args = sys.argv[1:]

    if not args or args[0] == "run":
        from doxyedit.main import main as gui_main
        gui_main()
        return

    cmd = args[0]
    cmds_1arg = {
        "summary": cmd_summary, "tags": cmd_tags, "untagged": cmd_untagged,
        "status": cmd_status, "starred": cmd_starred, "ignored": cmd_ignored,
        "notes": cmd_notes, "export-json": cmd_export_json,
    }

    if cmd in cmds_1arg:
        if len(args) < 2:
            print(f"Usage: python -m doxyedit {cmd} <project.doxyproj.json>")
            sys.exit(1)
        cmds_1arg[cmd](args[1])
    elif cmd == "search":
        if len(args) < 3:
            print("Usage: python -m doxyedit search <project.json> <query>")
            sys.exit(1)
        cmd_search(args[1], args[2])
    elif cmd == "add-tag":
        if len(args) < 4:
            print("Usage: python -m doxyedit add-tag <project.json> <asset_id> <tag>")
            sys.exit(1)
        cmd_add_tag(args[1], args[2], args[3])
    elif cmd == "remove-tag":
        if len(args) < 4:
            print("Usage: python -m doxyedit remove-tag <project.json> <asset_id> <tag>")
            sys.exit(1)
        cmd_remove_tag(args[1], args[2], args[3])
    elif cmd == "set-star":
        if len(args) < 4:
            print("Usage: python -m doxyedit set-star <project.json> <asset_id> <0-5>")
            sys.exit(1)
        cmd_set_star(args[1], args[2], args[3])
    elif cmd == "sync-tags":
        if len(args) < 3:
            print("Usage: python -m doxyedit sync-tags <project.json> <registry.json>")
            sys.exit(1)
        cmd_sync_tags(args[1], args[2])
    elif cmd == "strip-tags":
        if len(args) < 3:
            print("Usage: python -m doxyedit strip-tags <project.json> <tag1,tag2,...>")
            sys.exit(1)
        cmd_strip_tags(args[1], args[2])
    elif cmd == "find-dupes":
        if len(args) < 2:
            print("Usage: python -m doxyedit find-dupes <project.json> [--threshold N]")
            sys.exit(1)
        threshold = int(args[3]) if len(args) > 3 and args[2] == "--threshold" else 10
        cmd_find_dupes(args[1], threshold)
    elif cmd == "assign-slots":
        if len(args) < 2:
            print("Usage: python -m doxyedit assign-slots <project.json>")
            sys.exit(1)
        cmd_assign_slots(args[1])
    elif cmd == "export-proxies" or cmd == "extract-thumbs":
        if len(args) < 2:
            print("Usage: python -m doxyedit export-proxies <project.json> [--size N] [--output folder/]")
            sys.exit(1)
        size = 512
        output = None
        i = 2
        while i < len(args):
            if args[i] == "--size" and i + 1 < len(args):
                size = int(args[i + 1]); i += 2
            elif args[i] == "--output" and i + 1 < len(args):
                output = args[i + 1]; i += 2
            else:
                i += 1
        cmd_extract_thumbs(args[1], size, output)
    elif cmd == "export":
        if len(args) < 4 or "--platform" not in args:
            print("Usage: python -m doxyedit export <project.json> --platform <id> --output <folder>")
            sys.exit(1)
        plat = args[args.index("--platform") + 1]
        out = args[args.index("--output") + 1] if "--output" in args else "export/"
        cmd_export_platform(args[1], plat, out)
    elif cmd == "search-advanced":
        if len(args) < 2:
            print("Usage: python -m doxyedit search-advanced <project.json> [--tag X] [--min-width N] [--aspect landscape|portrait|square]")
            sys.exit(1)
        tag = min_w = aspect = None
        i = 2
        while i < len(args):
            if args[i] == "--tag" and i + 1 < len(args):
                tag = args[i + 1]; i += 2
            elif args[i] == "--min-width" and i + 1 < len(args):
                min_w = int(args[i + 1]); i += 2
            elif args[i] == "--aspect" and i + 1 < len(args):
                aspect = args[i + 1]; i += 2
            else:
                i += 1
        cmd_search_advanced(args[1], tag, min_w or 0, aspect)
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
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
