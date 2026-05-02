# DoxyEdit v2.5

Art asset manager + posting pipeline for artists and creators. Browse,
tag, organize, edit (Studio), schedule, and publish art across many
platforms (Kickstarter, Steam, Patreon, OneUp-fronted socials, plus
direct API for Bluesky/Telegram/Discord/Mastodon).

> [!tip] Quick Navigation
> - [[Getting Started]] — Install, run, first project
> - [[Interface Overview]] — All tabs (Assets / Studio / Social / Platforms / Overview / Notes)
> - [[Tagging System]] — Tags, shortcuts, eye toggles, panel sections
> - [[Preview Window]] — Zoom, pan, annotations, crops
> - [[Thumbnail Cache]] — Cache modes, cross-project sharing
> - [[Platform Publishing]] — Slots, export, status tracking, OneUp
> - [[Health & Stats]] — Missing files, project summary
> - [[Import & Export]] — Formats, drag-drop, paste, CLI export
> - [[Keyboard Shortcuts]] — Full shortcut reference
> - [[Themes & Appearance]] — Built-in themes
> - [[Project File Format]] — .doxy / .doxycol schemas
> - [[CLI Reference]] — Command-line pipeline
> - [[Changelog]] — Version history
> - [[Roadmap]] — Live deferred work

For the canonical changelog with everything that shipped between v1.9
and the current release, see `docs/CHANGELOG.md` in the repo (1700+
lines, far too long to mirror here).

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
