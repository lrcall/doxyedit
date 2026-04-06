# DoxyEdit v1.9

Art asset manager for artists and creators. Browse, tag, organize, and export art across multiple platforms (Kickstarter, Steam, Patreon, social media).

> [!tip] Quick Navigation
> - [[Getting Started]] — Install, run, first project
> - [[Interface Overview]] — All four tabs explained
> - [[Tagging System]] — Tags, shortcuts, eye toggles, panel sections
> - [[Preview Window]] — Zoom, pan, annotations
> - [[Thumbnail Cache]] — Cache modes, cross-project sharing
> - [[Platform Publishing]] — Slots, export, status tracking
> - [[Health & Stats]] — Missing files, project summary
> - [[Import & Export]] — Formats, drag-drop, paste, CLI export
> - [[Keyboard Shortcuts]] — Full shortcut reference
> - [[Themes & Appearance]] — 7 built-in themes
> - [[Project File Format]] — .doxyproj.json schema
> - [[CLI Reference]] — Command-line pipeline
> - [[Changelog]] — Version history
> - [[Roadmap]] — Pending and planned features

---

## What's New in v1.9

> [!note] v1.9.0 — 2026-04-06
> **Preview Window Overhaul** — Single-instance preview window reuses itself instead of spawning a second. Minimize/maximize/restore buttons added. Full DWM theming on title bar. Free overpan (pan past image edges).
>
> **Thumbnail Navigation** — Up/Down arrows in the browser navigate images and auto-scroll to keep the selection visible.
>
> **Cross-Project Cache Sharing** — New `content_index.db` (SQLite) at the base cache dir maps cache keys across all projects. Open a new project containing already-cached files and they load instantly.
>
> **Fast Cache Mode** — Tools menu option to store thumbnails as uncompressed BMP for faster reads at the cost of disk space.
>
> **Health Panel** — "Remove Missing" button scans all assets and removes entries whose source file no longer exists on disk (with confirmation).
>
> **Scrollbars** — Handles use the theme accent color and brighten on hover.

---

## Quick Reference

### File Operations

| Shortcut | Action |
|----------|--------|
| Ctrl+N | New project |
| Ctrl+O | Open project |
| Ctrl+S | Save project |
| Ctrl+Shift+S | Save As |
| Ctrl+E | Export all platforms |
| Ctrl+V | Paste image / path / folder |
| F5 | Refresh thumbnails |

### Navigation

| Shortcut | Action |
|----------|--------|
| Up / Down | Navigate thumbnails |
| Enter | Open preview |
| Ctrl+Scroll | Zoom thumbnail grid |
| Ctrl+F | Focus search box |
| Escape | Deselect all / clear filters |

### Tagging (Assets Tab)

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

### View Controls

| Shortcut | Action |
|----------|--------|
| Ctrl+T | Toggle Work Tray |
| Ctrl+L | Toggle Tag Panel |
| Ctrl+= | Increase font size |
| Ctrl+- | Decrease font size |
| Ctrl+0 | Reset font size |

---

## Project Status

- **Current version:** 1.9.0
- **Stack:** PySide6 + Pillow + psd-tools
- **Platform:** Windows (pywin32 for SAI thumbnails)
- **Project file:** `.doxyproj.json` (human-readable JSON)
- **Cache:** `~/.doxyedit/thumbcache/` (SQLite-indexed)
