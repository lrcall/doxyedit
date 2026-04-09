# CLAUDE.md — DoxyEdit Repo Context

## What This Is
DoxyEdit is a custom art asset management tool. The main project file is `doxyart.doxyproj.json` — a large JSON file (~1MB+) that tracks every asset, its tags, crops, censors, assignments, and platform specs.

## Project File Structure
```
doxyart.doxyproj.json
  .name              — project name
  .platforms         — list of platform IDs (kickstarter, patreon, twitter, etc.)
  .tag_definitions   — object keyed by tag ID → { label, color }
  .custom_tags       — array of { id, label, color } (mirrors tag_definitions)
  .tag_aliases       — remapping old tag IDs to new ones
  .custom_shortcuts  — single-key keyboard shortcuts → tag ID
  .hidden_tags       — tags hidden from default view
  .eye_hidden_tags   — tags hidden from eye/publish view
  .assets            — array of asset objects (see below)

Asset object:
  .id                — "{filename}_{index}" e.g. "007_4"
  .source_path       — full absolute path to file
  .source_folder     — full absolute path to containing folder
  .tags              — array of tag ID strings
  .starred           — 0 or 1
  .crops             — platform crop regions
  .censors           — censor overlays
  .assignments       — platform assignment records
  .notes             — freeform string
  .specs             — platform-specific metadata
```

## Tag System

### Naming Rules
- Tag IDs: lowercase, underscores only (e.g. `devil_futa`, `sailor_moon`)
- Tag labels: human-readable display name (e.g. "Devil Futa", "Sailor Moon")
- Every tag must appear in BOTH `tag_definitions` (object) AND `custom_tags` (array)
- When renaming a tag: update both `custom_tags[].id` AND `tag_definitions` key together — they must stay in sync

### Folder-Based Tagging (tag-by-folder.py)

Assets are stored under:
```
G:\B.D. INC Dropbox\Team TODO\-- COMPLETED --\
```

The folder structure maps directly to tags by **depth layer**:

```
-- COMPLETED --\               ← Depth 0 (root) — no tag
  Furry\                       ← Depth 1 → tag: furry
    Marty\                     ← Depth 2 → tag: marty
      Color\                   ← Depth 3 → tag: color (if not in skip list)
```

An asset at `Furry\Marty\file.psd` receives tags: `["furry", "marty"]`

**To restrict to a single depth layer in the future:** filter `parts` list by index in `get_all_subfolder_tags()` before returning — e.g. `parts[:1]` for depth-1 only.

**Skip list** (generic folder names that don't make useful tags):
`new folder`, `export`, `source`, `jpg`, `psd`, `png`, `web`, `high`, `medium`, `low`, `resize`, `images`, `misc`, `posted`, `deliverables`, `on server`, `ressources`

### Known Top-Level Folders (Depth 1 Tags)
| Folder | Tag ID |
|--------|--------|
| ANGEL | angel |
| Boku | boku |
| Comission | comission |
| Completed Comms | completed_comms |
| DESIGN | design |
| Devil | devil |
| Devil Futa | devil_futa |
| Devils | devils |
| Elf | elf |
| Fem | fem |
| Furry | furry |
| Futa | futa |
| Gorl | gorl |
| Hardblush | hardblush |
| Horse | horse |
| Hyakpu | hyakpu |
| Jenni / Jenni_01 | jenni / jenni_01 |
| Judy | judy |
| KISUKA | kisuka |
| logo | logo |
| Marty | marty |
| merch | merch |
| MILFS | milfs |
| Misc | misc |
| Nintendo | nintendo |
| ONTA | onta |
| Peach / Peach2 | peach / peach2 |
| Philomaus | philomaus |
| Polished Merch | polished_merch |
| Rarity | rarity |
| Sailor Moon | sailor_moon |
| Squids | squids |
| Steam | steam |
| Thezackrabbit | thezackrabbit |
| USEDUP | usedup |
| Unigan manga | unigan_manga |
| Victor | victor |
| YCH_A_Bonfirefox | ych_a_bonfirefox |
| YCH_B_Commanderwolf47 | ych_b_commanderwolf47 |
| YOUNIGANS | younigans |
| Yacky | yacky |
| chimereon site | chimereon_site |
| gamedit | gamedit |

## Scripts
- `tag-by-folder.py` — auto-tags all assets by folder path (all depth levels). Safe to re-run; won't duplicate tags.

## UI Rules
- **NEVER** hardcode colors, fonts, or sizes on individual widgets via `setStyleSheet()`
- ALL visual properties come from Theme tokens in `doxyedit/themes.py`
- New panels: set `objectName`, add selectors to `generate_stylesheet()` — do NOT create `apply_theme()` methods
- The global stylesheet cascades to all children automatically — no per-widget overrides needed
- Use `setProperty()` + property selectors for dynamic state (status colors, etc.)
- Exception: overlays (crop handles, censor rects, note annotations) may use fixed high-contrast colors
- Full spec: `docs/ressources/uidocs/DOXYEDIT_UI_SPEC.md`
- Reference design philosophy: `docs/ressources/uidocs/SHADER_LAB_UI_GUIDE.md`

## Rules
- The project file is binary-safe JSON — always use `ensure_ascii=False` when writing
- Never sort or reorder assets — order is meaningful (affects display)
- `id` field format is `"{base_filename}_{index}"` — don't change existing IDs
- Re-running `tag-by-folder.py` is idempotent — it checks before adding
