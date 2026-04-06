---
tags: [performance, scale, sqlite, architecture, planned]
description: Architecture plan for scaling DoxyEdit to 10k–100k+ assets without rewriting the whole app.
---

# Scale Plan

DoxyEdit currently loads the entire project JSON into memory on open. This works well up to ~3–4k assets. Beyond that, startup slows, saves take longer, and memory climbs. This page documents the path to handling 10k–100k+ assets.

---

## Current Bottlenecks

| Bottleneck | Threshold | Symptom |
|------------|-----------|---------|
| Full JSON load on open | ~3k assets | Slow startup, high RAM |
| Full JSON save on every Ctrl+S | ~3k assets | Save lag |
| `project.assets` list scanned on every filter | ~2k assets | Filter lag |
| `get_asset(id)` is O(n) linear scan | ~1k assets | Selection lag |
| Thumbnail pixmap LRU capped at 600 | any size | Blank thumbs on scroll |
| `tag_definitions` + `custom_tags` kept in sync manually | ~200 tags | Data integrity risk |

---

## Phase 1 — Low Hanging Fruit (no architecture change)

Gains without touching the file format or storage model.

### 1a. Asset index on load
Build `_id_index: dict[str, Asset]` once on project load. Already partially done — `project.get_asset(id)` should use it everywhere instead of `next(a for a in assets if a.id == id)`.

### 1b. Lazy filter cache
Cache `_filtered_assets` and only invalidate it when tags/filters change, not on every repaint or scroll event.

### 1c. Incremental save
On Ctrl+S, serialize only changed assets (dirty flag per asset) and patch the JSON file rather than rewriting the whole thing. Falls back to full save if > N assets changed.

### 1d. Background save
Move `json.dumps` + file write to a background thread. Show a subtle "saving…" indicator. The main thread stays responsive.

### 1e. Raise LRU cap dynamically
Scale `_LRU_MAX` based on available RAM at startup (e.g. `min(2000, free_ram_mb // 2)`).

---

## Phase 2 — SQLite Asset Store (medium effort)

Replace the monolithic JSON assets array with a SQLite database. Keep the JSON for project metadata (platforms, tag definitions, settings) — just move assets to DB.

### Schema

```sql
CREATE TABLE assets (
    id          TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_folder TEXT,
    starred     INTEGER DEFAULT 0,
    notes       TEXT DEFAULT '',
    tags        TEXT DEFAULT '[]',   -- JSON array
    crops       TEXT DEFAULT '{}',   -- JSON object
    censors     TEXT DEFAULT '[]',   -- JSON array
    assignments TEXT DEFAULT '{}',   -- JSON object
    specs       TEXT DEFAULT '{}',   -- JSON object
    added_at    INTEGER              -- unix ms
) WITHOUT ROWID;

CREATE INDEX idx_source_folder ON assets(source_folder);
CREATE INDEX idx_starred ON assets(starred);
```

### What changes
- `Project.assets` becomes a lazy-loaded list backed by the DB
- Filtering runs as SQL `WHERE` queries instead of Python list comprehension
- `get_asset(id)` is a single-row lookup
- Save is per-asset `INSERT OR REPLACE` — instant regardless of project size
- Startup loads only metadata + tag definitions; asset rows loaded on demand

### What stays the same
- Asset object model in Python — same fields, same signals
- Tag system — tag IDs still strings, stored as JSON array in the tags column
- Export, CLI, all existing code that reads `asset.tags`, `asset.notes` etc.

### Migration path
- On open, detect if `assets.db` exists alongside the `.doxyproj.json`
- If not, one-time migration: read JSON assets, insert into DB, strip assets array from JSON
- Keep JSON-only mode working for backward compat (small projects, external tools)

---

## Phase 2.5 — Progressive Thumbnail Loading

When the target quality is 256px+ and thumbnails aren't cached yet, show a fast low-res placeholder first and upscale progressively.

### Concept

Instead of waiting for the full 256px thumbnail to generate, serve the smallest available cached size immediately and upgrade it in place:

```
Request 256px →
  64px cached? → show immediately (blurry but fast)
  128px cached? → upgrade (still fast)
  256px generated → final upgrade (sharp)
```

### Worker Priority Tiers

Assign each pending item a tier based on user activity:

| Tier | Condition | Action |
|------|-----------|--------|
| 0 — Urgent | Currently visible + user is idle | Generate at full target size immediately |
| 1 — Active | Currently visible + user is scrolling | Generate at 64px first, then upgrade |
| 2 — Buffer | Just outside viewport (prefetch zone) | Generate at 64px only, queue full upgrade |
| 3 — Background | Off-screen (cache-all) | Full size, low priority |

**Idle detection:** If no scroll/click events for ~400ms, promote visible items from Tier 1 → Tier 0.

### Implementation

1. `DiskCache.get_best(path, target_size)` — returns the largest available cached size below `target_size` (tries 64, 128, 256 etc.)
2. `ThumbnailModel` renders with `Qt.SmoothTransformation` upscale when displaying a lower-res placeholder — looks acceptable while waiting
3. Worker emits `thumb_ready` twice for Tier 1 items: once at 64px (fast), once at full size (later)
4. `_on_thumb_ready` checks if the new gen_size is larger than what's already displayed — only update if it's an upgrade

### User Activity Signals

- **Scrolling:** `valueChanged` on scrollbar → set active mode, reset idle timer
- **Mouse over grid:** `mouseMoveEvent` → reset idle timer  
- **No activity for 400ms:** promote visible items to urgent, start full-res generation

This means: scroll fast through 1000 images, see 64px blurs; stop scrolling, watch them sharpen in ~1-2 seconds.

---

## Phase 3 — Streaming Thumbnail Load (large collections)

For 10k+ assets, even the DB query + model population takes a moment. Virtualize at the data layer too.

### Windowed model
`ThumbnailModel` currently holds all `_filtered_assets` in memory. At 50k assets this is ~50MB of Python objects.

Replace with a windowed model:
- Keep only a rolling window of N rows in memory (e.g. 5000)
- Load more rows from DB as user scrolls toward the edge of the window
- `rowCount()` returns the total DB count; data is fetched on `data()` calls

This is the same pattern Qt's `QSqlTableModel` uses internally.

### Search index
For tag search across 50k+ assets, a simple Python list scan is too slow. Options:
- SQLite FTS5 virtual table on the tags column
- Or a pre-built inverted index (`tag_id → [asset_ids]`) kept in memory (~1MB for 200 tags × 50k assets)

The inverted index approach is simpler and fast enough for most use cases.

---

## Phase 4 — Multi-Library / Library Federation

For users with multiple projects across different drives/folders:

- A global `libraries.json` index listing all known `.doxyproj.json` paths
- Quick-switch between libraries without full reload (keep most-recently-used in memory)
- Cross-library search (search tag across all projects)
- This is essentially what Eagle's "workspace" concept is

Low priority — only matters if the tool grows beyond single-artist use.

---

## Observed Real-World Performance

- **70k image folder** navigated successfully — the virtual QListView + lazy thumb cache holds up at this scale
- The bottleneck at high counts is thumbnail generation queue depth and JSON save time, not the grid rendering itself
- Phase 1 and Phase 2 are only needed if save lag or startup lag becomes noticeable in daily use

## Trigger Thresholds

When to start each phase:

| Phase | Trigger |
|-------|---------|
| Phase 1 (quick wins) | Save lag noticed, or startup > 2 seconds |
| Phase 2 (SQLite) | Regular projects > 10k assets with crops/censors/notes |
| Phase 3 (streaming) | Regular projects > 50k assets |
| Phase 4 (federation) | Multiple projects, cross-project workflow needed |

---

## What NOT to do

- **Don't rewrite in C++** — PySide6 + SQLite is fast enough for 100k assets. The bottleneck is never the Python interpreter.
- **Don't use a remote database** — local SQLite is the right call. No server, no sync complexity.
- **Don't break the JSON format** — external tools (Claude CLI, scripts) read the JSON. Keep it as the interchange format even if assets move to SQLite.
- **Don't over-engineer early** — Phase 1 alone probably buys another 3–4x headroom. Build Phase 2 only when you actually hit the wall.

---

## Related

- [[Project File Format]] — current JSON schema
- [[Thumbnail Cache]] — SQLite already used for cache index
- [[Roadmap]] — feature backlog
- [[CLI Reference]] — external tools that read the project file
