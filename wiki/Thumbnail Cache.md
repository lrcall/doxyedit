---
tags: [cache, performance, thumbnails, sqlite]
description: How the thumbnail cache works — storage locations, cross-project sharing, fast cache mode, and management tools.
---

# Thumbnail Cache

DoxyEdit caches generated thumbnails to disk so that reopening a large project loads near-instantly. The cache system uses SQLite for indexing and supports cross-project sharing.

---

## Cache Location

Thumbnails are stored in `~/.doxyedit/thumbcache/` as PNG files (or BMP in Fast Cache Mode).

| File | Purpose |
|------|---------|
| `~/.doxyedit/thumbcache/content_index.db` | Cross-project content hash → PNG path mapping |
| `<project-cache-dir>/cache.db` | Per-project dimension index (SQLite, WAL mode) |

The cache location can be changed via **Tools > Set Cache Location**.

---

## How Caching Works

Thumbnails are keyed by **file path + modification time**. If a file changes on disk, the cached thumbnail is invalidated and regenerated automatically.

The `content_index.db` stores a mapping from content hashes to PNG paths at the base cache directory level. This is what enables cross-project sharing.

### Cache Generation Order

1. Uncached images are prioritized (generated first)
2. Images needing quality upgrades are generated second
3. Background thread handles generation so the UI stays responsive

---

## Cross-Project Cache Sharing

When you open a new project that contains files already cached by another project, the thumbnails are reused instantly — no re-generation needed.

This works because:
1. Each cached file is indexed in `content_index.db` by a content-based key
2. When a new project loads an image, DoxyEdit checks the shared index first
3. If found, the existing PNG is reused; no disk write needed

This is especially useful when working with the same image files across multiple projects.

---

## Fast Cache Mode

**Tools > Fast Cache Mode** stores thumbnails as uncompressed BMP files instead of PNG.

| Mode | Storage | Speed |
|------|---------|-------|
| PNG (default) | Smaller files | Slightly slower to read |
| BMP (Fast Cache) | Larger files | Faster reads, better for slow drives |

Toggle Fast Cache Mode from the Tools menu. Useful for very large projects on spinning-disk drives or network shares.

---

## Cache Management

| Menu Item | Action |
|-----------|--------|
| Tools > Cache All | Pre-generate all thumbnails for the current project in background |
| Tools > Fast Cache Mode | Toggle BMP vs PNG storage |
| Tools > Clear Cache | Delete all cached thumbnails for the current project |
| Tools > Set Cache Location | Move cache to a custom directory |
| Tools > Open Cache | Open the cache folder in Windows Explorer |

### Cache All Checkbox

The **Cache All** checkbox in the browser toolbar triggers background pre-generation for all images in the project. A progress bar tracks completion. When all images are already cached, the progress bar stays hidden.

> [!note] Re-entrant Safety
> In v1.9, a crash from hitting "Cache All" again immediately after completion was fixed. The operation is now guarded against re-entrant calls.

---

## Asset File Watcher

DoxyEdit watches source image files via `QFileSystemWatcher`. If a source file is modified on disk (e.g., you save a new version from Photoshop), the thumbnail is automatically regenerated.

`ThumbCache.invalidate()` is used internally to clear individual cache entries when files change.

---

## Per-Project Dimension Index

Each project maintains a `cache.db` SQLite database (WAL mode) that stores image dimensions alongside the project's cache. This replaces the old `index.json` format.

Old `index.json` files are **auto-migrated** on first run — no manual intervention needed.

---

## Related

- [[Getting Started]] — initial setup
- [[Health & Stats]] — removing missing files
- [[Interface Overview]] — Cache All checkbox in toolbar
