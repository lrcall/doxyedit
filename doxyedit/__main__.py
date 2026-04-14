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
    post list <project.json> [--status S]  List all posts
    post show <project.json> <post-id>    Show all fields for a post
    post create <project.json> [options]  Create a draft post
    post update <project.json> <post-id> [options]  Update a post
    post push <project.json> [post-id|--all-drafts]  Push to OneUp
    post sync <project.json>  Sync post statuses from OneUp
    post delete <project.json> <post-id>  Delete a post
    plan-posts <project.json> [options]   Full briefing for Claude to plan posting strategy
    flatten <project.json> --asset <id>   Flatten PSD layers + optional crop extraction
    watermark <project.json> --asset <id> Apply watermark/text overlay to exported image
    reminders <project.json>  Show pending release chain steps and cadence reminders
    transport <project.json> [--dry-run] [--compact]  Package assets + enable local mode
    untransport <project.json>            Restore original paths from transport metadata
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


def cmd_post_list(project_path: str, args: list):
    """List all posts with status, schedule, platforms, caption preview."""
    from doxyedit.models import Project
    proj = Project.load(project_path)

    status_filter = None
    fmt = "table"
    i = 0
    while i < len(args):
        if args[i] == "--status" and i + 1 < len(args):
            status_filter = args[i + 1]; i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    posts = proj.posts
    if status_filter:
        posts = [p for p in posts if p.status == status_filter]

    if fmt == "json":
        print(json.dumps([p.to_dict() for p in posts], indent=2))
        return

    if not posts:
        print("No posts found.")
        return

    for p in posts:
        sched = p.scheduled_time[:16] if p.scheduled_time else "(unscheduled)"
        cap = p.caption_default[:50] if p.caption_default else "(no caption)"
        plats = ",".join(p.platforms[:3]) if p.platforms else "(none)"
        assets = ",".join(p.asset_ids[:2]) if p.asset_ids else "(none)"
        status = p.status.upper() if isinstance(p.status, str) else p.status.value.upper()
        print(f"  {p.id[:8]}  {status:<8}  {sched}  [{plats}]  {cap}")
    print(f"\n--- {len(posts)} post(s) ---")


def cmd_post_show(project_path: str, post_id: str):
    """Show all fields for a single post."""
    from doxyedit.models import Project
    proj = Project.load(project_path)
    post = proj.get_post(post_id)
    if not post:
        # Try partial match
        matches = [p for p in proj.posts if p.id.startswith(post_id)]
        if len(matches) == 1:
            post = matches[0]
        elif matches:
            print(f"Ambiguous ID '{post_id}' — matches: {[p.id[:8] for p in matches]}")
            sys.exit(1)
        else:
            print(f"Post '{post_id}' not found")
            sys.exit(1)

    print(f"ID:         {post.id}")
    print(f"Status:     {post.status}")
    print(f"Schedule:   {post.scheduled_time or '(unscheduled)'}")
    print(f"Assets:     {', '.join(post.asset_ids) or '(none)'}")
    print(f"Platforms:  {', '.join(post.platforms) or '(none)'}")
    print(f"Caption:    {post.caption_default!r}")
    if post.captions:
        for plat, cap in post.captions.items():
            print(f"  [{plat}]: {cap!r}")
    print(f"Links:      {', '.join(post.links) or '(none)'}")
    print(f"Collection: {post.collection or '(none)'}")
    print(f"Campaign:   {post.campaign_id or '(none)'}")
    print(f"Category:   {post.category_id or '(none)'}")
    print(f"OneUp ID:   {post.oneup_post_id or '(none)'}")
    if post.nsfw_platforms:
        print(f"NSFW plats: {', '.join(post.nsfw_platforms)}")
    if post.release_chain:
        print(f"Chain:      {' > '.join(f'{s.platform} +{s.delay_hours}h' for s in post.release_chain)}")
    if post.reply_templates:
        print(f"Replies:    {len(post.reply_templates)} template(s)")
    if post.strategy_notes:
        print(f"Strategy:   {post.strategy_notes[:80]}...")
    print(f"Created:    {post.created_at}")
    print(f"Updated:    {post.updated_at}")


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
    strategy_notes = ""
    collection = ""
    category_id = ""
    nsfw_platforms = []
    campaign_id = ""
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
        elif args[i] == "--strategy-notes" and i + 1 < len(args):
            strategy_notes = args[i + 1]; i += 2
        elif args[i] == "--collection" and i + 1 < len(args):
            collection = args[i + 1]; i += 2
        elif args[i] == "--category" and i + 1 < len(args):
            category_id = args[i + 1]; i += 2
        elif args[i] == "--nsfw-platforms" and i + 1 < len(args):
            nsfw_platforms = [x.strip() for x in args[i + 1].split(",")]; i += 2
        elif args[i] == "--campaign" and i + 1 < len(args):
            campaign_id = args[i + 1]; i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    proj = Project.load(project_path)

    # Duplicate / similarity check
    new_ids = set(asset_ids)
    new_plats = set(platforms)
    warnings = []
    for existing in proj.posts:
        overlap_ids = new_ids & set(existing.asset_ids)
        overlap_plats = new_plats & set(existing.platforms)
        if not overlap_ids:
            continue
        if overlap_plats:
            status_str = existing.status.value if hasattr(existing.status, 'value') else existing.status
            warnings.append(
                f"  ⚠ DUPLICATE: {', '.join(overlap_ids)} already {status_str} "
                f"on {', '.join(overlap_plats)} (post {existing.id[:8]}... "
                f"scheduled {existing.scheduled_time[:10] if existing.scheduled_time else 'unscheduled'})")
        else:
            warnings.append(
                f"  ℹ SIMILAR: {', '.join(overlap_ids)} already in post {existing.id[:8]}... "
                f"on different platforms")
    if warnings:
        print("Duplicate check:")
        for w in warnings:
            print(w)
        if any("DUPLICATE" in w for w in warnings):
            print("  Proceeding anyway — review the timeline to avoid double-posting.")
        print()

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
        strategy_notes=strategy_notes,
        collection=collection,
        category_id=category_id,
        nsfw_platforms=nsfw_platforms,
        campaign_id=campaign_id,
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
        elif args[i] == "--strategy-notes" and i + 1 < len(args):
            post.strategy_notes = args[i + 1]; i += 2
        elif args[i] == "--collection" and i + 1 < len(args):
            post.collection = args[i + 1]; i += 2
        elif args[i] == "--category" and i + 1 < len(args):
            post.category_id = args[i + 1]; i += 2
        elif args[i] == "--nsfw-platforms" and i + 1 < len(args):
            post.nsfw_platforms = [x.strip() for x in args[i + 1].split(",")]; i += 2
        elif args[i] == "--campaign" and i + 1 < len(args):
            post.campaign_id = args[i + 1]; i += 2
        elif args[i] == "--assets" and i + 1 < len(args):
            post.asset_ids = [x.strip() for x in args[i + 1].split(",")]; i += 2
        elif args[i] == "--platforms" and i + 1 < len(args):
            post.platforms = [x.strip() for x in args[i + 1].split(",")]; i += 2
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
        sched = ""
        if post.scheduled_time:
            sched = post.scheduled_time[:16].replace("T", " ")

        accounts = post.platforms if post.platforms else ["ALL"]
        oneup_ids = []
        for account_id in accounts:
            caption = post.captions.get(account_id, post.caption_default)
            result = client.schedule_post(
                content=caption,
                image_urls=None,
                social_network_id=account_id,
                scheduled_date_time=sched,
            )
            if result.success:
                oneup_ids.append(str(result.data.get("id", "")))
                pushed += 1
                print(f"  ✓ Pushed {post.id[:8]}... → {account_id}")
            else:
                failed += 1
                print(f"  ✗ Failed {post.id[:8]}... → {account_id}: {result.error[:60]}")

        if oneup_ids:
            post.oneup_post_id = ",".join(oneup_ids)
            post.status = SocialPostStatus.QUEUED
        else:
            post.status = SocialPostStatus.FAILED
        post.updated_at = datetime.now().isoformat()

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


def cmd_watermark(project_path: str, args: list):
    """Apply a watermark overlay to an image. Watermark config from config.yaml."""
    from doxyedit.models import Project
    from pathlib import Path as _Path
    from PIL import Image, ImageDraw, ImageFont

    proj = Project.load(project_path)
    project_dir = _Path(project_path).parent

    asset_id = None
    output_dir = "export/"
    watermark_path = None
    text = None
    opacity = 0.3
    position = "bottom-right"  # bottom-right, bottom-left, center, tile
    i = 0
    while i < len(args):
        if args[i] == "--asset" and i + 1 < len(args):
            asset_id = args[i + 1]; i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_dir = args[i + 1]; i += 2
        elif args[i] == "--watermark" and i + 1 < len(args):
            watermark_path = args[i + 1]; i += 2
        elif args[i] == "--text" and i + 1 < len(args):
            text = args[i + 1]; i += 2
        elif args[i] == "--opacity" and i + 1 < len(args):
            opacity = float(args[i + 1]); i += 2
        elif args[i] == "--position" and i + 1 < len(args):
            position = args[i + 1]; i += 2
        else:
            i += 1

    if not asset_id:
        print("Usage: python -m doxyedit watermark <project.json> --asset <id> [--watermark image.png] [--text 'text'] [--opacity 0.3] [--position bottom-right|center|tile] [--output dir]")
        sys.exit(1)

    asset = proj.get_asset(asset_id)
    if not asset:
        print(f"Asset not found: {asset_id}")
        sys.exit(1)

    src = _Path(asset.source_path)
    if not src.exists():
        print(f"Source not found: {src}")
        sys.exit(1)

    # Load config.yaml watermark defaults if no flags given
    if not watermark_path and not text:
        try:
            import yaml
            config_path = project_dir / "config.yaml"
            if config_path.exists():
                config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                wm = config.get("watermark", {})
                watermark_path = wm.get("image", "")
                text = wm.get("text", "")
                opacity = float(wm.get("opacity", opacity))
                position = wm.get("position", position)
        except Exception:
            pass

    if not watermark_path and not text:
        print("No watermark specified. Use --watermark image.png or --text 'text', or set in config.yaml under watermark:")
        sys.exit(1)

    # Load source image
    ext = src.suffix.lower()
    if ext in (".psd", ".psb"):
        from doxyedit.imaging import load_psd
        img, _, _ = load_psd(str(src))
    else:
        img = Image.open(str(src)).convert("RGBA")

    # Create watermark layer
    wm_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))

    if watermark_path and _Path(watermark_path).exists():
        wm_img = Image.open(watermark_path).convert("RGBA")
        # Scale watermark to ~20% of image width
        scale = (img.width * 0.2) / max(wm_img.width, 1)
        wm_img = wm_img.resize((int(wm_img.width * scale), int(wm_img.height * scale)), Image.LANCZOS)
        # Apply opacity
        alpha = wm_img.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        wm_img.putalpha(alpha)
        # Position
        if position == "bottom-right":
            x = img.width - wm_img.width - 20
            y = img.height - wm_img.height - 20
        elif position == "bottom-left":
            x, y = 20, img.height - wm_img.height - 20
        elif position == "center":
            x = (img.width - wm_img.width) // 2
            y = (img.height - wm_img.height) // 2
        else:
            x = img.width - wm_img.width - 20
            y = img.height - wm_img.height - 20
        wm_layer.paste(wm_img, (x, y))
    elif text:
        draw = ImageDraw.Draw(wm_layer)
        try:
            font = ImageFont.truetype("arial.ttf", max(20, img.width // 30))
        except Exception:
            font = ImageFont.load_default()
        alpha_val = int(255 * opacity)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if position == "bottom-right":
            x, y = img.width - tw - 20, img.height - th - 20
        elif position == "bottom-left":
            x, y = 20, img.height - th - 20
        elif position == "center":
            x, y = (img.width - tw) // 2, (img.height - th) // 2
        else:
            x, y = img.width - tw - 20, img.height - th - 20
        draw.text((x, y), text, fill=(255, 255, 255, alpha_val), font=font)

    # Composite
    result = Image.alpha_composite(img, wm_layer)

    # Save
    out_dir = _Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{asset_id}_watermarked.png"
    result.save(str(out_path), "PNG")
    print(f"  Saved: {out_path} ({result.width}x{result.height})")


def cmd_flatten(project_path: str, args: list):
    """Flatten PSD/PSB files to PNG/JPG for posting. Also handles crop regions."""
    from doxyedit.models import Project
    from pathlib import Path as _Path

    proj = Project.load(project_path)

    asset_id = None
    output_dir = "export/"
    crop_label = None
    fmt_out = "png"
    size = 0  # 0 = original size
    i = 0
    while i < len(args):
        if args[i] == "--asset" and i + 1 < len(args):
            asset_id = args[i + 1]; i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_dir = args[i + 1]; i += 2
        elif args[i] == "--crop" and i + 1 < len(args):
            crop_label = args[i + 1]; i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt_out = args[i + 1]; i += 2
        elif args[i] == "--size" and i + 1 < len(args):
            size = int(args[i + 1]); i += 2
        else:
            i += 1

    if not asset_id:
        print("Usage: python -m doxyedit flatten <project.json> --asset <id> [--output dir] [--crop label] [--format png|jpg] [--size max_px]")
        sys.exit(1)

    asset = proj.get_asset(asset_id)
    if not asset:
        print(f"Asset not found: {asset_id}")
        sys.exit(1)

    src = _Path(asset.source_path)
    if not src.exists():
        print(f"Source file not found: {src}")
        sys.exit(1)

    from PIL import Image
    ext = src.suffix.lower()
    if ext in (".psd", ".psb"):
        from doxyedit.imaging import load_psd
        img, _, _ = load_psd(str(src))
    else:
        img = Image.open(str(src)).convert("RGBA")

    # Apply crop if requested
    if crop_label:
        crop = next((c for c in asset.crops if c.label == crop_label), None)
        if crop:
            img = img.crop((crop.x, crop.y, crop.x + crop.w, crop.y + crop.h))
            print(f"  Cropped to '{crop_label}': {crop.w}x{crop.h}")
        else:
            labels = [c.label for c in asset.crops]
            print(f"  Crop '{crop_label}' not found. Available: {labels}")
            sys.exit(1)

    # Resize if requested
    if size > 0 and max(img.size) > size:
        img.thumbnail((size, size), Image.LANCZOS)
        print(f"  Resized to {img.width}x{img.height}")

    # Save
    out_dir = _Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{asset_id}.{fmt_out}"
    out_path = out_dir / out_name

    if fmt_out == "jpg":
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        img.save(str(out_path), "JPEG", quality=90)
    else:
        img.save(str(out_path), "PNG")

    print(f"  Saved: {out_path} ({img.width}x{img.height})")


def cmd_plan_posts(project_path: str, args: list):
    """Generate a posting plan briefing — asset inventory, post history, gaps, identity.
    Outputs everything Claude needs to plan months of posts."""
    from doxyedit.models import Project, SocialPost, SocialPostStatus
    import json as _json

    proj = Project.load(project_path)

    # Parse args
    tag_filter = None
    folder_filter = None
    days = 90
    export_previews = False
    preview_dir = ""
    fmt = "table"
    i = 0
    while i < len(args):
        if args[i] == "--tag" and i + 1 < len(args):
            tag_filter = args[i + 1]; i += 2
        elif args[i] == "--folder" and i + 1 < len(args):
            folder_filter = args[i + 1]; i += 2
        elif args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1]); i += 2
        elif args[i] == "--export-previews" and i + 1 < len(args):
            export_previews = True
            preview_dir = args[i + 1]; i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    # Filter assets
    candidates = list(proj.assets)
    if tag_filter:
        candidates = [a for a in candidates if tag_filter in a.tags]
    if folder_filter:
        folder_filter_lower = folder_filter.lower().replace("\\", "/")
        candidates = [a for a in candidates
                      if folder_filter_lower in (a.source_folder or "").lower().replace("\\", "/")]

    # Build posted history
    posted_ids = set()
    scheduled_ids = set()
    for p in proj.posts:
        status = p.status.value if hasattr(p.status, 'value') else p.status
        if status == "posted":
            posted_ids.update(p.asset_ids)
        if status in ("draft", "queued"):
            scheduled_ids.update(p.asset_ids)

    # Categorize
    unposted = [a for a in candidates if a.id not in posted_ids and a.id not in scheduled_ids]
    already_posted = [a for a in candidates if a.id in posted_ids]
    already_scheduled = [a for a in candidates if a.id in scheduled_ids]

    # Identity
    identity = proj.get_identity()

    # Export previews if requested
    if export_previews and preview_dir:
        from pathlib import Path as _Path
        from PIL import Image
        out = _Path(preview_dir)
        out.mkdir(parents=True, exist_ok=True)
        exported = 0
        for a in unposted[:50]:  # cap at 50
            try:
                src = _Path(a.source_path)
                if not src.exists():
                    continue
                ext = src.suffix.lower()
                if ext in (".psd", ".psb"):
                    from doxyedit.imaging import load_psd
                    img, _, _ = load_psd(str(src))
                else:
                    img = Image.open(str(src))
                img.thumbnail((512, 512), Image.LANCZOS)
                img.save(str(out / f"{a.id}.jpg"), "JPEG", quality=85)
                exported += 1
            except Exception:
                pass
        if fmt != "json":
            print(f"Exported {exported} preview images to {preview_dir}/")

    # Gaps
    today = datetime.now()
    posted_days = set()
    for p in proj.posts:
        if p.scheduled_time:
            posted_days.add(p.scheduled_time[:10])
    gap_days = []
    for d in range(days):
        day = (today + timedelta(days=d)).strftime("%Y-%m-%d")
        if day not in posted_days:
            gap_days.append(day)

    # Past strategy notes (for continuity)
    past_strategies = []
    for p in sorted(proj.posts, key=lambda x: x.scheduled_time or ""):
        if p.strategy_notes:
            past_strategies.append({
                "date": p.scheduled_time[:10] if p.scheduled_time else "?",
                "assets": p.asset_ids,
                "platforms": p.platforms,
                "notes": p.strategy_notes[:200],
            })

    if fmt == "json":
        data = {
            "identity": {
                "name": identity.name,
                "voice": identity.voice,
                "bio": identity.bio_blurb,
                "default_platforms": identity.default_platforms,
                "content_notes": identity.content_notes,
                "hashtags": identity.hashtags,
                "gumroad_url": identity.gumroad_url,
                "patreon_url": identity.patreon_url,
            },
            "stats": {
                "total_assets": len(candidates),
                "unposted": len(unposted),
                "already_posted": len(already_posted),
                "already_scheduled": len(already_scheduled),
                "gap_days_in_window": len(gap_days),
                "planning_window_days": days,
            },
            "unposted_assets": [
                {
                    "id": a.id,
                    "tags": a.tags,
                    "starred": a.starred,
                    "path": a.source_path,
                    "folder": a.source_folder,
                    "notes": a.notes,
                }
                for a in unposted[:100]
            ],
            "already_posted": [
                {"id": a.id, "tags": a.tags}
                for a in already_posted[:50]
            ],
            "gap_days": gap_days[:30],
            "past_strategy_notes": past_strategies[-10:],
            "existing_posts": [
                {
                    "id": p.id,
                    "date": p.scheduled_time[:10] if p.scheduled_time else "?",
                    "status": p.status.value if hasattr(p.status, 'value') else p.status,
                    "assets": p.asset_ids,
                    "platforms": p.platforms,
                    "caption": p.caption_default[:80],
                }
                for p in sorted(proj.posts, key=lambda x: x.scheduled_time or "")
            ],
        }
        print(_json.dumps(data, indent=2, ensure_ascii=False))
        return

    # Table format
    print(f"=== POSTING PLAN BRIEFING ===")
    print(f"Project: {proj.name}")
    if identity.name:
        print(f"Identity: {identity.name}")
        if identity.voice:
            print(f"Voice: {identity.voice}")
        if identity.content_notes:
            print(f"Content notes: {identity.content_notes}")
    print()

    print(f"Planning window: {days} days")
    print(f"Total matching assets: {len(candidates)}")
    print(f"  Unposted: {len(unposted)}")
    print(f"  Already posted: {len(already_posted)}")
    print(f"  Already scheduled: {len(already_scheduled)}")
    print(f"  Gap days (no posts): {len(gap_days)}")
    print()

    if unposted:
        print(f"-- Unposted assets ({min(len(unposted), 30)} shown) --")
        for a in unposted[:30]:
            star = "*" if a.starred else " "
            tags = ", ".join(a.tags[:5]) if a.tags else "untagged"
            print(f"  {star} {a.id:30s}  [{tags}]")
        if len(unposted) > 30:
            print(f"  ... and {len(unposted) - 30} more")
        print()

    if gap_days:
        print(f"-- Gap days (next 14 shown) --")
        for day in gap_days[:14]:
            print(f"  ! {day}")
        print()

    if past_strategies:
        print(f"-- Past strategy notes --")
        for s in past_strategies[-5:]:
            print(f"  {s['date']}: {s['notes'][:100]}")
        print()

    print("To create posts from this briefing:")
    print("  python -m doxyedit post create <project.json> --assets ID --platforms twitter,instagram --caption '...' --schedule '2026-04-20T10:00:00' --strategy-notes '...'")


def cmd_post_history(project_path: str, args: list):
    """Show what's been posted — full history for reference."""
    from doxyedit.models import Project
    proj = Project.load(project_path)
    fmt = "table"
    i = 0
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    posted = [p for p in proj.posts if (p.status.value if hasattr(p.status, 'value') else p.status) == "posted"]
    posted.sort(key=lambda p: p.scheduled_time or "")

    if fmt == "json":
        print(json.dumps([p.to_dict() for p in posted], indent=2))
        return

    if not posted:
        print("No posts have been posted yet.")
        return

    print(f"Post history ({len(posted)} posted):")
    asset_post_count: dict[str, int] = {}
    for p in posted:
        dt = p.scheduled_time[:10] if p.scheduled_time else "?"
        plats = ", ".join(p.platforms)
        names = ", ".join(p.asset_ids[:2])
        cap = (p.caption_default[:40] + "...") if len(p.caption_default) > 40 else p.caption_default
        print(f"  ✓ {dt}  {names}  →  {plats}")
        if cap:
            print(f"    \"{cap}\"")
        for aid in p.asset_ids:
            asset_post_count[aid] = asset_post_count.get(aid, 0) + 1

    # Flag assets posted multiple times
    dupes = {k: v for k, v in asset_post_count.items() if v > 1}
    if dupes:
        print(f"\nAssets posted multiple times:")
        for aid, count in sorted(dupes.items(), key=lambda x: -x[1]):
            print(f"  ⚠ {aid}: {count} times")


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


def cmd_transport(project_path: str, args: list):
    """Copy all referenced files into _assets/ next to the project file.

    Preserves folder structure relative to detected common roots.
    Stores original paths in each asset's specs.original_path / specs.original_folder.
    Enables local_mode so the project becomes fully portable.
    """
    import shutil
    from doxyedit.models import Project

    dry_run = "--dry-run" in args
    compact = "--compact" in args
    proj = Project.load(project_path)
    proj_dir = Path(project_path).parent
    assets_dir = proj_dir / "_assets"

    if not dry_run:
        assets_dir.mkdir(exist_ok=True)

    # Known roots — strip these prefixes to get the meaningful relative path.
    # Order matters: longer/more-specific roots first.
    KNOWN_ROOTS = [
        os.path.normpath(r"G:\B.D. INC Dropbox\Team TODO\-- COMPLETED --"),
        os.path.normpath(r"G:\B.D. INC Dropbox\Team Yacky"),
        os.path.normpath(r"G:\B.D. INC Dropbox"),
    ]

    def _relative_under_root(abs_path: str) -> str:
        """Strip the longest matching known root to get the meaningful relative path."""
        normed = os.path.normpath(abs_path)
        for root in KNOWN_ROOTS:
            if normed.lower().startswith(root.lower() + os.sep) or normed.lower() == root.lower():
                remainder = normed[len(root):].lstrip(os.sep)
                return remainder
        # Fallback: use last 3 path segments (avoids collisions while staying readable)
        parts = Path(normed).parts
        return str(Path(*parts[-3:])) if len(parts) >= 3 else str(Path(*parts))

    copied = 0
    skipped = 0
    missing = 0
    errors = 0
    already_local = 0

    for asset in proj.assets:
        if not asset.source_path:
            skipped += 1
            continue

        src = Path(asset.source_path)

        # Already under _assets (previously transported)
        try:
            src.relative_to(assets_dir)
            already_local += 1
            continue
        except ValueError:
            pass

        if not src.exists():
            missing += 1
            if dry_run:
                print(f"  MISSING: {asset.source_path}")
            continue

        # Compute destination
        rel = _relative_under_root(asset.source_path)
        dest = assets_dir / rel

        # Handle filename collision (different source, same relative path)
        if dest.exists() and not os.path.samefile(src, dest):
            stem = dest.stem
            suffix = dest.suffix
            counter = 2
            while dest.exists():
                dest = dest.parent / f"{stem}_{counter}{suffix}"
                rel = str(dest.relative_to(assets_dir))
                counter += 1

        if dry_run:
            print(f"  {asset.source_path}")
            print(f"    -> _assets/{rel}")
            copied += 1
            continue

        # Copy file
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dest))
        except Exception as e:
            print(f"  ERROR copying {asset.source_path}: {e}")
            errors += 1
            continue

        # Store original paths in specs
        asset.specs["original_path"] = asset.source_path
        asset.specs["original_folder"] = asset.source_folder

        # Update to local path
        asset.source_path = str(dest)
        asset.source_folder = str(dest.parent)
        copied += 1

    # Compact: collapse single-child folder chains (A/B/C → A_B_C)
    compacted = 0
    if compact and not dry_run and copied > 0:
        # Build path index for updating asset refs
        path_map: dict[str, str] = {}  # old_path → new_path

        def _collapse_chain(d: Path) -> None:
            """Walk bottom-up and collapse single-child directories."""
            nonlocal compacted
            if not d.is_dir():
                return
            children = list(d.iterdir())
            # Recurse first
            for c in children:
                if c.is_dir():
                    _collapse_chain(c)
            # Re-check after recursion
            children = list(d.iterdir())
            if len(children) == 1 and children[0].is_dir() and d != assets_dir:
                child = children[0]
                merged_name = f"{d.name}_{child.name}"
                merged = d.parent / merged_name
                # Move child contents up into merged name
                import shutil as _sh
                child.rename(merged)
                d.rmdir()  # now empty
                compacted += 1

        _collapse_chain(assets_dir)

        # Update asset paths to match collapsed folders
        if compacted:
            for asset in proj.assets:
                p = Path(asset.source_path)
                try:
                    p.relative_to(assets_dir)
                except ValueError:
                    continue
                if not p.exists():
                    # Path changed due to collapse — find the file
                    fname = p.name
                    for found in assets_dir.rglob(fname):
                        asset.source_path = str(found)
                        asset.source_folder = str(found.parent)
                        break

    if not dry_run:
        # Store transport metadata on the project
        proj.local_mode = True
        now = datetime.now().isoformat()
        proj.oneup_config.setdefault("transport", {})
        proj.oneup_config["transport"] = {
            "transported_at": now,
            "known_roots": [str(r) for r in KNOWN_ROOTS],
            "assets_dir": "_assets",
            "compact": compact,
        }
        proj.save(project_path)

    label = "DRY RUN — " if dry_run else ""
    print(f"\n{label}Transport complete:")
    print(f"  Copied:        {copied}")
    if compacted:
        print(f"  Compacted:     {compacted} folder chains collapsed")
    print(f"  Already local: {already_local}")
    print(f"  Skipped:       {skipped} (no source_path)")
    print(f"  Missing:       {missing} (file not found)")
    if errors:
        print(f"  Errors:        {errors}")
    if not dry_run:
        print(f"\nProject saved with local_mode=True.")
        print(f"Assets stored in: {assets_dir}")


def cmd_untransport(project_path: str):
    """Restore original absolute paths from transport metadata in specs."""
    from doxyedit.models import Project

    proj = Project.load(project_path)
    restored = 0
    no_meta = 0

    for asset in proj.assets:
        original = asset.specs.get("original_path", "")
        if original:
            asset.source_path = original
            asset.source_folder = asset.specs.get("original_folder", "")
            del asset.specs["original_path"]
            if "original_folder" in asset.specs:
                del asset.specs["original_folder"]
            restored += 1
        else:
            no_meta += 1

    proj.local_mode = False
    if "transport" in proj.oneup_config:
        del proj.oneup_config["transport"]
    proj.save(project_path)

    print(f"Untransport complete:")
    print(f"  Restored: {restored}")
    print(f"  No metadata: {no_meta} (left unchanged)")
    print(f"\nProject saved with local_mode=False.")


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
            print("Usage: python -m doxyedit post <list|show|create|update|push|sync|delete> <project.json> [options]")
            sys.exit(1)
        subcmd = args[1]
        proj_path = args[2]
        if subcmd == "list":
            cmd_post_list(proj_path, args[3:])
        elif subcmd == "show":
            if len(args) < 4:
                print("Usage: python -m doxyedit post show <project.json> <post-id>")
                sys.exit(1)
            cmd_post_show(proj_path, args[3])
        elif subcmd == "create":
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
    elif cmd == "post-history":
        if len(args) < 2:
            print("Usage: python -m doxyedit post-history <project.json> [--format json|table]")
            sys.exit(1)
        cmd_post_history(args[1], args[2:])
    elif cmd == "plan-posts":
        if len(args) < 2:
            print("Usage: python -m doxyedit plan-posts <project.json> [--tag TAG] [--folder PATH] [--days N] [--export-previews DIR] [--format json|table]")
            sys.exit(1)
        cmd_plan_posts(args[1], args[2:])
    elif cmd == "flatten":
        if len(args) < 2:
            print("Usage: python -m doxyedit flatten <project.json> --asset <id> [--output dir] [--crop label] [--format png|jpg] [--size max_px]")
            sys.exit(1)
        cmd_flatten(args[1], args[2:])
    elif cmd == "watermark":
        if len(args) < 2:
            print("Usage: python -m doxyedit watermark <project.json> --asset <id> [--watermark img.png] [--text 'text'] [--opacity 0.3] [--position bottom-right] [--output dir]")
            sys.exit(1)
        cmd_watermark(args[1], args[2:])
    elif cmd == "transport":
        if len(args) < 2:
            print("Usage: python -m doxyedit transport <project.json> [--dry-run]")
            sys.exit(1)
        cmd_transport(args[1], args[2:])
    elif cmd == "untransport":
        if len(args) < 2:
            print("Usage: python -m doxyedit untransport <project.json>")
            sys.exit(1)
        cmd_untransport(args[1])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
