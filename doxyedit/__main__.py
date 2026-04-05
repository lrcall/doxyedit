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
"""
import sys
import json
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
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
