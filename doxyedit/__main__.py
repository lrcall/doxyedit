"""CLI entry point — python -m doxyedit [command] [args]

Commands:
    run                     Launch the GUI (default)
    summary <project.json>  Print project status summary (for Claude CLI)
    tags <project.json>     List all assets and their tags
    untagged <project.json> List assets with no tags
    status <project.json>   Platform assignment status
"""
import sys
import json
from pathlib import Path


def cmd_summary(path: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    print(json.dumps(proj.summary(), indent=2))


def cmd_tags(path: str):
    from doxyedit.models import Project, TAG_PRESETS
    proj = Project.load(path)
    for a in proj.assets:
        name = Path(a.source_path).stem
        tags = ", ".join(a.tags) if a.tags else "(none)"
        star = " *" if a.starred else ""
        print(f"{name}{star}: {tags}")
    print(f"\n--- {len(proj.assets)} assets, {sum(1 for a in proj.assets if a.tags)} tagged ---")


def cmd_untagged(path: str):
    from doxyedit.models import Project
    proj = Project.load(path)
    untagged = [a for a in proj.assets if not a.tags]
    for a in untagged:
        print(Path(a.source_path).stem)
    print(f"\n--- {len(untagged)}/{len(proj.assets)} untagged ---")


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
                name = Path(a.source_path).stem
                print(f"  {slot.label} ({slot.width}x{slot.height}): {name} [{pa.status}]")
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
    if cmd in ("summary", "tags", "untagged", "status"):
        if len(args) < 2:
            print(f"Usage: python -m doxyedit {cmd} <project.doxyproj.json>")
            sys.exit(1)
        path = args[1]
        if not Path(path).exists():
            print(f"File not found: {path}")
            sys.exit(1)
        {"summary": cmd_summary, "tags": cmd_tags, "untagged": cmd_untagged, "status": cmd_status}[cmd](path)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
