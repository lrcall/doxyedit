# DoxyEdit Config Layering

DoxyEdit reads settings from **four** layered sources. Understanding
which owns what is important when debugging "why isn't this setting
taking effect?" problems.

## The four sources

### 1. `doxyedit/models.py` module defaults

Hardcoded default lists, dictionaries, dataclass defaults. The base layer.

Examples:
- `TAG_PRESETS`, `TAG_SIZED`, `TAG_ALL` — default tag set.
- `TAG_SHORTCUTS_DEFAULT` — keyboard shortcuts for default tags.
- `VINIK_COLORS` — the cycle used for auto-assigned tag colors.
- `PLATFORMS`, `SUB_PLATFORMS`, `DIRECT_POST_PLATFORMS` — platform
  definitions.

Edit these only for repo-wide changes. Users never edit this file
directly.

### 2. `doxyedit.config.json` (user config overrides)

Optional file in the DoxyEdit install dir. Loaded by `config.py` at
startup via `get_config()`. Overrides the module defaults from (1)
without changing the code.

Fields (see `config.py`):
- `tag_presets` — overrides `TAG_PRESETS`
- `tag_sized` — overrides `TAG_SIZED`
- `tag_shortcuts` — overrides `TAG_SHORTCUTS_DEFAULT`
- `platforms` — overrides `PLATFORMS`

Used by advanced users who want a per-install custom tag or platform
set without hacking the source.

### 3. `config.yaml` (API credentials + platform selectors)

Project-adjacent YAML file (discovered via `_find_config()` walking up
from the project directory). Holds:
- `oneup:` — OneUp API keys + active account
- `direct_post:` — Telegram/Discord/Bluesky credentials
- `browser_automation:` — Chrome path, CDP URL
- `image_hosting:` — Imgur/imgbb keys

**Gitignored.** Contains secrets. One file per project / workspace.

### 4. Per-project JSON (`.doxy` / `.doxyproj.json`)

The project file itself. Holds all project-specific state:
- `assets` — every asset + its tags, crops, censors, overlays
- `posts` — scheduled social posts
- `identities` — brand voices / URL mappings
- `platforms`, `subreddits`, `campaigns` — project-scoped configs
- `custom_shortcuts` — per-project tag shortcut overrides
- `theme_id` — saved theme choice for this project
- `local_mode` — relative-path setting

This is the authoritative per-project state. Saved through
`Project.save(path)`.

### 5. `QSettings("DoxyEdit", "DoxyEdit")`

Windows registry. User preferences that span projects:
- `last_project` — autoload path
- `last_collection` — autoload collection
- `font_size` — UI font scale
- `theme` — global theme fallback
- `recent_projects`, `recent_folders`, `pinned_folders`
- `cache_dir` — thumbnail cache location
- `shared_cache` — bool
- Splitter sizes, tray visibility, collapsed/hidden folders
- `autosave_interval_ms`

Per-user, not per-project. Survives reinstalls unless the user wipes
the registry key.

## Precedence at read time

For tag definitions and similar:

```
QSettings  ──▶  per-project JSON  ──▶  config.yaml   ──▶  config.json
(user prefs)    (project state)       (credentials)      (install overrides)
                                                          ──▶  models.py
                                                              (module defaults)
```

Most settings live in exactly one of these, so precedence only
matters for the overlapping ones:

| Setting | Owned by | Notes |
|---|---|---|
| Tag list | module defaults + per-project | Per-project `tag_definitions` additively extends module defaults |
| Tag shortcuts | module defaults + per-project `custom_shortcuts` | Per-project wins |
| Theme | QSettings → per-project `theme_id` | Project override wins if set |
| Font size | QSettings only | Global |
| Platforms | module defaults + project `platforms` list | Project filters which platforms are shown |
| OneUp API key | `config.yaml` only | Secrets never go in project file |

## Common bugs this layout avoids

- **Secrets in git**: API keys live in `config.yaml` which is
  gitignored. Project files are shareable.
- **Shared thumbnails**: the thumbnail cache is keyed by `cache_dir`
  in QSettings, shared across projects by default, so moving to a
  new project doesn't re-decode every PSD.
- **Multi-machine projects**: `local_mode` on the project flips asset
  paths to relative, so a project synced via cloud storage works
  across machines without path rewriting.

## Adding a new setting

Ask:
1. Is it a secret? → `config.yaml`.
2. Is it per-project state that needs to round-trip with `.doxy`? →
   project JSON + dataclass field.
3. Is it a user preference that spans projects? → `QSettings`.
4. Is it a repo-wide default that some users might want to override? →
   `models.py` default + optional `config.json` override.

## Files

- `doxyedit/config.py` — `config.json` loader
- `doxyedit/oneup.py` — `config.yaml` loader (`_find_config`)
- `doxyedit/models.py` — Project dataclass + module defaults
- Qt's `QSettings` used ad-hoc from many modules; 38 font-size call
  sites were consolidated in v2.4 via `themes.ui_font_size()` cache.
