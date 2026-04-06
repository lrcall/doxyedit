---
tags: [tags, tagging, shortcuts, tag-panel, eye-toggle]
description: Complete guide to the DoxyEdit tag system — panel sections, shortcuts, auto-tags, eye toggles, and tag management.
---

# Tagging System

DoxyEdit's tag system is the core of asset organization. Tags are stored in the project file and are used for filtering, search, platform assignment, and export.

---

## Tag Panel (Left Sidebar)

The Tag Panel shows all tags grouped into four sections. Toggle it with **Ctrl+L** or the **Tags** button in the toolbar.

### Sections (top to bottom)

1. **Content / Workflow** — general-purpose tags (Page, Character, Sketch, Game Asset, Merch Source, Reference, Final/Approved, WIP, Ignore)
2. **Platform / Size targets** — campaign-specific with target dimensions (Hero 1024×576, Banner 1600×400, etc.)
3. **Custom / Project** — user-added tags specific to this project (e.g., marty, hardblush)
4. **Visual / Mood / Dimension** — auto-generated visual properties (warm, cool, dark, bright, portrait, landscape, square, panoramic, tall, detailed, flat)

Click a section header (▼/▶) to collapse or expand it.

### Fitness Dots

Each Platform/Size tag shows a colored dot indicating whether the selected image meets the size requirement:

| Color | Meaning |
|-------|---------|
| Green | Image is large enough for this target size |
| Yellow | Large enough but aspect ratio differs — a crop will be needed |
| Red | Image is too small for this target |

### Eye Toggle (Photoshop-style Visibility)

Each tag has an 👁 eye button. Click it to hide all images with that tag from the grid. Click again to restore them. Multiple eye toggles can be active simultaneously, just like Photoshop layer visibility.

Eye states persist in the project file between sessions.

### Right-Click a Tag to:

- **Pin to top** — moves it to the top of its section (gold left border indicates pinned)
- **Set Shortcut Key** — assign any single key as a keyboard shortcut (shown as `[K]` in the label)
- **Rename** — renames the tag across all assets (creates an alias for backward compat)
- **Select all with tag** — selects every asset that has this tag
- **Change Color** — opens a color picker
- **Hide** — removes it from the panel view (use "Show All" button to restore)
- **Delete from project** — removes the tag from all assets and from the project

### Panel Buttons

| Button | Action |
|--------|--------|
| Mark Ignore | Tags selected images as "ignore" |
| Clear All | Removes all tags from selected images |
| Show All | Reveals any hidden tags |
| + | Add a new custom tag |

---

## Quick-Tag Bar (Top of Grid)

Colored pill buttons above the thumbnail grid for fast tagging. Shows content/workflow tags and discovered/custom tags (not platform/size tags).

- **Click a button** — toggle that tag on all selected images
- **Ctrl+Click a button** — search/filter by that tag (click again to clear)
- **Alt+Click a button** — search by that tag (legacy behavior)
- **+ button** — add a new custom tag

---

## Keyboard Shortcuts for Tags

Number keys 1–8 and 0 toggle tags on selected images. These are the default bindings:

| Key | Tag |
|-----|-----|
| 1 | Page / Panel |
| 2 | Character Art |
| 3 | Sketch / WIP |
| 4 | Game Asset |
| 5 | Merch Source |
| 6 | Reference |
| 7 | Final / Approved |
| 8 | Work in Progress |
| 0 | Ignore / Skip |

### Custom Keyboard Shortcuts

Right-click any tag in the Tag Panel → **Set Shortcut Key** → press any single key. Custom shortcuts:
- Register live immediately
- Appear as `[K]` in the tag label
- Are saved per-project in the `.doxyproj.json` file
- Work alongside the default 1–9 shortcuts

---

## Auto-Tags

On import, images are automatically tagged based on:

### Filename Patterns

Common keywords in the filename trigger tags automatically:
- `cover` → Cover tag
- `sketch` → Sketch tag
- etc.

### Visual Properties

Computed from the image pixels on import:

| Tag | Condition |
|-----|-----------|
| warm | Dominant warm color channel |
| cool | Dominant cool color channel |
| dark | Low average brightness |
| bright | High average brightness |
| detailed | High variance / complexity |
| flat | Low variance |
| portrait | Height > Width |
| landscape | Width > Height by threshold |
| square | Roughly 1:1 ratio |
| panoramic | Very wide aspect ratio |
| tall | Very tall aspect ratio |

Auto-tagging can be toggled on/off via **Tools > Auto-Tag** (defaults to off).

---

## Tag Data Structure

Tags are stored in two places in the project file (they must stay in sync):

- **`tag_definitions`** — object keyed by tag ID → `{ label, color, group }`
- **`custom_tags`** — array of `{ id, label, color }` (mirrors tag_definitions)
- **`tag_aliases`** — maps old tag IDs to canonical IDs for rename backward compat

Tag ID rules:
- Lowercase
- Underscores only (no spaces)
- Example: `devil_futa`, `sailor_moon`

Tag label: human-readable display name (e.g., "Devil Futa", "Sailor Moon")

When renaming a tag, an alias is automatically created so old references continue to resolve.

---

## Searching by Tag

- Check the **Tags** checkbox in the toolbar search box, then type a tag name
- **Ctrl+Click** a tag bar button to filter the grid to that tag
- **Alt+A** — open "Add Tag" dialog for selected assets
- **Right-click → Quick Tag** — submenu with all tags, ✓ marks for applied tags; splits into columns when more than 10 tags

---

## Folder-Based Tagging (tag-by-folder.py)

The `tag-by-folder.py` script auto-tags all assets by folder path. Assets are tagged based on the depth layers of their folder:

```
-- COMPLETED --\        ← root (no tag)
  Furry\                ← depth 1 → tag: furry
    Marty\              ← depth 2 → tag: marty
```

An asset at `Furry\Marty\file.psd` receives tags: `["furry", "marty"]`

The script is safe to re-run — it checks before adding and won't create duplicates.

---

## Related

- [[Interface Overview]] — tag panel location in UI
- [[Keyboard Shortcuts]] — all shortcuts including tag shortcuts
- [[Project File Format]] — tag storage schema
- [[Import & Export]] — auto-tagging on import
