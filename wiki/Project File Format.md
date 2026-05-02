---
tags: [project-file, json, schema, format, doxy]
description: Complete schema reference for the .doxy / .doxyproj.json project file format.
---

# Project File Format

DoxyEdit stores all project data in a single human-readable JSON file.
The current preferred extension is `.doxy`; the legacy `.doxyproj.json`
extension still loads and saves correctly so older projects keep
working without migration. Both extensions hold byte-identical JSON.

A `.doxycol` (legacy `.doxycoll.json`) is a separate "collection" file
that lists multiple projects to open together in tabs/windows; see
`SaveLoadMixin._save_collection` / `_open_collection` in
`doxyedit/project_io.py` for the format, which is just
`{"_type":"doxycoll","projects":["path1.doxy","path2.doxy"]}`.

The `.doxy` file can be edited by Claude CLI, custom scripts, or by
hand. Any field listed below that's missing on load defaults to its
documented value (back-compat is part of the contract).

---

## Top-Level Structure

```json
{
  "name": "My Project",
  "platforms": ["kickstarter", "steam", "patreon"],
  "tag_definitions": { ... },
  "custom_tags": [ ... ],
  "tag_aliases": { ... },
  "custom_shortcuts": { ... },
  "hidden_tags": ["some_tag"],
  "eye_hidden_tags": ["another_tag"],
  "assets": [ ... ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Project name |
| `platforms` | array of strings | List of active platform IDs |
| `tag_definitions` | object | Keyed by tag ID → `{ label, color, group }` |
| `custom_tags` | array | `[{ id, label, color }]` — mirrors tag_definitions |
| `tag_aliases` | object | Maps old tag IDs to canonical IDs (for renames) |
| `custom_shortcuts` | object | Single-key shortcut → tag ID |
| `hidden_tags` | array | Tag IDs hidden from the tag panel |
| `eye_hidden_tags` | array | Tag IDs currently hidden from the grid (eye toggle state) |
| `assets` | array | All asset records |

---

## Asset Object

```json
{
  "id": "cover_0",
  "source_path": "C:/art/cover.png",
  "source_folder": "C:/art",
  "tags": ["cover", "hero", "warm", "portrait"],
  "starred": 2,
  "crops": {},
  "censors": [],
  "assignments": {},
  "notes": "",
  "specs": {}
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | `"{base_filename}_{index}"` e.g. `"cover_0"`, `"007_4"` |
| `source_path` | string | Full absolute path to the file |
| `source_folder` | string | Full absolute path to containing folder |
| `tags` | array of strings | Applied tag IDs |
| `starred` | integer | 0 = unstarred; 1–5 = star color (gold, blue, green, rose, red) |
| `crops` | object | Platform crop regions |
| `censors` | array | Censor overlay records |
| `assignments` | object | Platform slot assignment records |
| `notes` | string | Human-written note annotations (with coordinates) |
| `specs` | object | CLI/tool metadata (size, palette, relations, cli_info) |

### ID Format

The `id` field is `"{base_filename}_{index}"`:
- `base_filename` is the filename stem (no extension)
- `index` is a numeric suffix ensuring uniqueness across the project
- Examples: `"cover_0"`, `"007_4"`, `"hero_banner_1"`

> [!warning] Do Not Change Existing IDs
> The `id` field is used to reference assets throughout the project. Changing existing IDs will break all references. New assets should get the next available index.

---

## Tag Definitions

```json
"tag_definitions": {
  "marty": { "label": "Marty", "color": "#9a4f50", "group": "custom" },
  "cover":  { "label": "Cover", "color": "#8d5f8d", "group": "content" }
}
```

Every tag must appear in **both** `tag_definitions` (as a key) and `custom_tags` (as an array element). They must stay in sync.

### Tag ID Rules

- Lowercase only
- Underscores instead of spaces
- No special characters
- Examples: `devil_futa`, `sailor_moon`, `marty`

### Tag Aliases

```json
"tag_aliases": {
  "old_tag_name": "new_canonical_tag_id"
}
```

When a tag is renamed, an alias is created automatically so that assets using the old tag ID continue to resolve correctly on load.

---

## Custom Shortcuts

```json
"custom_shortcuts": {
  "m": "marty",
  "h": "hardblush"
}
```

Maps single-character keys to tag IDs. These are project-specific and saved with the project.

---

## Star Values

| Value | Color |
|-------|-------|
| 0 | Unstarred |
| 1 | Gold |
| 2 | Blue |
| 3 | Green |
| 4 | Rose |
| 5 | Red |

Old boolean values (`true`/`false`) from pre-v0.2 project files are backward compatible.

---

## Writing / Editing the File

When writing the project file programmatically:

- Use `ensure_ascii=False` — the file is binary-safe JSON with full Unicode support
- **Never sort or reorder assets** — order is meaningful (affects display order)
- Never change existing `id` fields

When editing with Claude CLI:
- Use `F5` in DoxyEdit to reload after external edits
- DoxyEdit's file watcher will auto-detect changes and offer to reload

---

## Minimal Example

```json
{
  "name": "My Project",
  "assets": [
    {
      "id": "cover_0",
      "source_path": "C:/art/cover.png",
      "starred": 2,
      "tags": ["cover", "hero", "warm", "portrait"]
    }
  ],
  "custom_tags": [
    {"id": "marty", "label": "Marty", "color": "#9a4f50"}
  ]
}
```

---

## Backup File

DoxyEdit automatically creates a `.bak` backup when opening a project. The backup is a copy of the project file as it was when you opened it — useful for rollback.

---

## Related

- [[CLI Reference]] — reading and modifying the project file via CLI
- [[Tagging System]] — tag ID naming rules
- [[Health & Stats]] — project maintenance tools
- [[Import & Export]] — moving assets between projects
