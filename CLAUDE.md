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
- QGraphicsScene items (QPen, QBrush, QColor) can't use QSS — read from Theme object directly via `set_theme(theme)` method
- NEVER use hardcoded QColor values — even fallbacks must reference theme tokens (e.g., `QColor(self._theme.text_muted)`)
- Scrollbar styling: one global rule using `scrollbar_track`, `scrollbar_handle`, `scrollbar_handle_hover` tokens — no duplicate rules per widget
- For centered text editors with scrollbar at window edge: use `setViewportMargins()` in `resizeEvent()` only — NOT in showEvent (segfaults), NOT document margins (applies to all sides), NOT QSS padding (moves scrollbar inward)
- Qt property selectors (`[prop="val"]`) are unreliable on dynamic properties — use distinct objectNames instead (e.g., `calendar_day_today` not `calendar_day_cell[day_type="today"]`)
- Top-level popup menus (context menus from `createStandardContextMenu()`) don't inherit app QSS on Windows — force inline stylesheet
- Windows title bar color: use `DwmSetWindowAttribute` with `DWMWA_CAPTION_COLOR=35` on dialog `.show()`, not in constructor
- Full spec: `docs/ressources/uidocs/DOXYEDIT_UI_SPEC.md`
- Reference design philosophy: `docs/ressources/uidocs/SHADER_LAB_UI_GUIDE.md`

## Claudelog Rules
When writing to claudelog via `/focus claudenote` or `/focus update claudelog`:
- Every entry needs timestamp + duration: `14:57  ⏱ Feature X — 23m`
- Flag rework: `17:23  ⏱ REWORK: theme migration — 1h19m wasted. Reason: didn't read uidocs/`
- Include root cause on bugs: `14:55  Bug: tray drag. Root cause: eventFilter timing.`
- Mark false completions: `16:14  First "done" — WRONG. Missed uidocs/.`
- Milestones include commit count: `14:51  25 commits in 26m`
- Do NOT append analysis sections — those go in memory files
- Do NOT nuke the timeline to reorganize — improve lines in place
- Do NOT log 0m start/stop pairs — merge into one line
- Each session: one `## YYYY-MM-DD` header with commit count + total duration

## Rules
- The project file is binary-safe JSON — always use `ensure_ascii=False` when writing
- Never sort or reorder assets — order is meaningful (affects display)
- `id` field format is `"{base_filename}_{index}"` — don't change existing IDs
- Re-running `tag-by-folder.py` is idempotent — it checks before adding

## Architecture
- New panels: QWidget subclass with `set_project()`, `refresh()`, `setObjectName()` — wired in `_rebind_project()` in window.py
- Serialization: all new dataclasses get `to_dict()`/`from_dict()` with backward-compat defaults via `.get()`
- Composer save: when adding fields to SocialPost, ALSO update `PostComposerWidget._save()` in composer.py — it manually copies each field
- Subprocess on Windows: always add `creationflags=0x08000000` (CREATE_NO_WINDOW) + `encoding="utf-8", errors="replace"`
- OneUp API: requires both `category_id` AND `scheduled_date_time` — posts silently fail without them. Categories: 86698=Doxy, 176197=Onta, 176198=L3rk, 176199=0rng
- config.yaml is gitignored (contains API keys) — code changes to config structure need manual user update
- Tab indices: never hardcode tab numbers beyond 0 (Assets) — use widget identity checks instead
- HTML in QTextBrowser: Qt doesn't support CSS `linear-gradient` or `%` padding. `max-width` with `margin:auto` works for centering.

## Project File Structure (v2.3 additions)
```
doxyart.doxyproj.json
  .posts             — array of SocialPost objects (social media schedule)
  .identity          — CollectionIdentity dict (brand voice, URLs)
  .identities        — dict of named identities (multi-brand)
  .sub_notes         — dict of tab_name → markdown (tabbed notes)
  .campaigns         — array of Campaign objects (Kickstarter, Steam, merch)
  .release_templates — array of reusable release chain presets
  .default_overlays  — array of CanvasOverlay presets (logo templates)
  .blackout_periods  — array of {start, end, label, scope} (cross-project)
  .oneup_config      — OneUp API config
```
