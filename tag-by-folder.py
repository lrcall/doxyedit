"""
Tag assets in doxyart.doxyproj.json based on their subfolder path under -- COMPLETED --.

Layer depth:
  Depth 0 = the root (-- COMPLETED -- itself) — no tag applied
  Depth 1 = first subfolder, e.g. "Furry"     → tag: furry
  Depth 2 = second subfolder, e.g. "Marty"    → tag: marty
  Depth 3+ = deeper subfolders                → tag: <normalized name>

All non-skipped depth levels are applied as tags simultaneously.
To restrict to a specific depth in the future, filter `parts` by index before tagging.

Example:
  source_folder = ...COMPLETED--\\Furry\\Marty
  → parts = ["Furry", "Marty"]
  → tags applied: ["furry", "marty"]
"""

import json
import re

PROJECT_FILE = r"E:\git\doxyedit\doxyart.doxyproj.json"
BASE_PATH = r"G:\B.D. INC Dropbox\Team TODO\-- COMPLETED --"

# Palette for new tags (cycles)
COLORS = [
    "#5a7a6e", "#7a5a6e", "#6e7a5a", "#5a6e7a", "#7a6e5a",
    "#8a6060", "#608a60", "#60608a", "#8a7a50", "#507a8a",
    "#7a508a", "#8a5070", "#508a70", "#708a50", "#705080",
]

# Generic folder names to skip — not useful as tags
SKIP_FOLDERS = {
    "new folder", "", "export", "source", "jpg", "psd", "png",
    "web", "high", "medium", "low", "resize", "images", "misc",
    "posted", "deliverables", "on server", "ressources",
}


def folder_to_tag_id(folder_name):
    """Normalize a folder name to a valid tag ID."""
    tag = folder_name.strip().lower()
    tag = re.sub(r"[^a-z0-9]+", "_", tag)
    return tag.strip("_")


def get_all_subfolder_tags(source_folder):
    """
    Return list of (tag_id, original_label) for every path segment
    between BASE_PATH and source_folder, skipping generic names.

    Depth 1 = first segment, depth 2 = second, etc.
    All depths are returned; filter by index to layer by depth.
    """
    base = BASE_PATH.lower().rstrip("\\")
    folder = source_folder.lower().rstrip("\\")

    if folder == base:
        return []

    if not folder.startswith(base + "\\"):
        return []

    remainder = source_folder[len(BASE_PATH):].strip("\\")
    parts = remainder.split("\\")

    results = []
    for part in parts:
        tag_id = folder_to_tag_id(part)
        if tag_id and tag_id not in SKIP_FOLDERS:
            results.append((tag_id, part))

    return results


def main():
    with open(PROJECT_FILE, "r", encoding="utf-8") as f:
        proj = json.load(f)

    existing_tag_ids = {t["id"] for t in proj.get("custom_tags", [])}
    color_index = len(existing_tag_ids)

    new_tags_added = {}  # id -> {id, label, color}

    for asset in proj.get("assets", []):
        source_folder = asset.get("source_folder", "")
        tag_pairs = get_all_subfolder_tags(source_folder)

        for tag_id, label in tag_pairs:
            # Register new tag if needed
            if tag_id not in existing_tag_ids and tag_id not in new_tags_added:
                color = COLORS[color_index % len(COLORS)]
                color_index += 1
                new_tags_added[tag_id] = {"id": tag_id, "label": label, "color": color}

            # Add tag to asset if missing
            if tag_id not in asset.get("tags", []):
                asset.setdefault("tags", []).append(tag_id)

    # Register new tags in both custom_tags and tag_definitions
    for tag_id, tag_def in new_tags_added.items():
        proj.setdefault("custom_tags", []).append(tag_def)
        proj.setdefault("tag_definitions", {})[tag_id] = {
            "label": tag_def["label"],
            "color": tag_def["color"],
        }

    print(f"New tags added: {len(new_tags_added)}")
    for tid, tdef in sorted(new_tags_added.items()):
        print(f"  {tid!r} ({tdef['label']})")

    with open(PROJECT_FILE, "w", encoding="utf-8") as f:
        json.dump(proj, f, indent=2, ensure_ascii=False)

    print("\nDone. Project file updated.")


if __name__ == "__main__":
    main()
