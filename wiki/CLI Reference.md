---
tags: [cli, command-line, claude, pipeline, integration]
description: CLI commands for integrating DoxyEdit with Claude CLI and external scripts.
---

# CLI Reference

DoxyEdit exposes a command-line interface for integration with Claude CLI, automation scripts, and external tools. The CLI reads and writes the `.doxyproj.json` project file directly.

---

## Running CLI Commands

```bash
python -m doxyedit <command> <project.doxyproj.json>
```

All commands accept a path to the project file as the final argument.

---

## Commands

### `summary`

```bash
python -m doxyedit summary project.doxyproj.json
```

Outputs a JSON status overview of the project:
- Total asset count
- Tagged / untagged counts
- Starred count
- Platform slot fill status

### `tags`

```bash
python -m doxyedit tags project.doxyproj.json
```

Lists all assets and their current tags. Output is JSON.

### `untagged`

```bash
python -m doxyedit untagged project.doxyproj.json
```

Lists all assets with no content/workflow tags. Useful for finding assets that still need review.

### `status`

```bash
python -m doxyedit status project.doxyproj.json
```

Shows platform slot assignments — which slots are filled, which are pending.

### `search`

```bash
python -m doxyedit search project.doxyproj.json <query>
```

Returns assets matching the search query (filename or tag).

### `starred`

```bash
python -m doxyedit starred project.doxyproj.json
```

Lists all starred assets with their star color/level.

### `ignored`

```bash
python -m doxyedit ignored project.doxyproj.json
```

Lists all assets tagged as "ignore".

### `notes`

```bash
python -m doxyedit notes project.doxyproj.json
```

Lists all assets that have note annotations.

### `add-tag`

```bash
python -m doxyedit add-tag project.doxyproj.json <asset-id> <tag-id>
```

Adds a tag to a specific asset by ID.

### `remove-tag`

```bash
python -m doxyedit remove-tag project.doxyproj.json <asset-id> <tag-id>
```

Removes a tag from a specific asset by ID.

### `set-star`

```bash
python -m doxyedit set-star project.doxyproj.json <asset-id> <0-5>
```

Sets the star value on a specific asset (0 = unstarred, 1–5 = color).

### `export-json`

```bash
python -m doxyedit export-json project.doxyproj.json
```

Exports the project as clean JSON (can be redirected to a file for further processing).

---

## Auto-Reload Integration

DoxyEdit watches the project JSON file via **QFileSystemWatcher**. When the CLI modifies the file, DoxyEdit detects the change and automatically reloads.

This enables a bidirectional workflow:
1. DoxyEdit shows the live asset view
2. Claude CLI modifies the JSON
3. DoxyEdit detects the change and reloads — no manual F5 needed

You can also press **F5** manually to reload from disk at any time.

---

## Claude CLI Workflow

The CLI was designed for integration with Claude AI (via Claude CLI / claude-code). Typical use cases:

- Ask Claude to find untagged assets and suggest tags
- Ask Claude to batch-add or remove tags based on rules
- Ask Claude to generate a campaign status report from `summary` + `status` output
- Ask Claude to move sets of assets to a new project based on tag criteria

> [!tip] Working with Claude
> Point Claude at your `.doxyproj.json` file. Use `summary` to orient it first, then use `tags` and `untagged` for batch operations. Claude can write Python to call `add-tag`/`remove-tag` in a loop.

---

## tag-by-folder.py

A standalone script for auto-tagging all assets by their folder path:

```bash
python tag-by-folder.py
```

Tags assets based on depth layers of their folder structure:

```
-- COMPLETED --\        ← root (no tag)
  Furry\                ← depth 1 → tag: furry
    Marty\              ← depth 2 → tag: marty
```

Safe to re-run — checks before adding, never creates duplicates.

### Skip List

These generic folder names are excluded from becoming tags:
`new folder`, `export`, `source`, `jpg`, `psd`, `png`, `web`, `high`, `medium`, `low`, `resize`, `images`, `misc`, `posted`, `deliverables`, `on server`, `ressources`

---

## Project File Rules for Scripts

When writing to the project file from a script:

- Use `ensure_ascii=False` (full Unicode support)
- Never sort or reorder the `assets` array
- Never change existing `id` fields
- Write both `tag_definitions` and `custom_tags` in sync when adding tags

---

## Related

- [[Project File Format]] — full JSON schema reference
- [[Health & Stats]] — GUI equivalents of CLI commands
- [[Import & Export]] — moving assets between projects
