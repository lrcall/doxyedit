# DoxyEdit

Art asset manager for artists and creators. Browse, tag, organize, and export art across multiple platforms.

![PySide6](https://img.shields.io/badge/PySide6-Qt-green) ![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)

## Features

### Asset Management
- **Thumbnail Browser** — QListView with smooth virtual scrolling, Ctrl+scroll zoom, hover/middle-click preview
- **File Browser** — folder tree with asset counts, search, pinned folders, drag-to-import (Ctrl+B)
- **Info Panel** — asset metadata with editable tag pills, inline notes, color palette swatches (Ctrl+I)
- **PSD/SAI Support** — PSD compositing via psd-tools, SAI/SAI2 via Windows shell thumbnails (SaiThumbs)
- **Tagging System** — keyboard shortcuts, custom tags, auto visual property tags (warm/cool/dark/portrait etc.)
- **4-Section Tag Panel** — Content, Platform/Size, Custom/Project, Visual/Mood with eye toggles and pin-to-top
- **Smart Folders** — save/load filter presets (View > Smart Folders)
- **Studio Tab** — unified editor combining censor, overlay, and annotation tools in a layered scene (base Z=0, censors Z=100+, overlays Z=200+, annotations Z=300+)
- **Non-Destructive Censor** — black/blur/pixelate overlays, export censored copies
- **Overlay Editor** — asset-bound watermark, text, and logo placement with drag positioning, opacity/scale sliders
- **Preview Annotations** — draw note boxes on images, persist with project
- **Work Tray** — collapsible quickslot panel, persists across all tabs
- **Crop Handles** — 8 drag handles on crop regions with persistent overlays
- **Asset Groups** — duplicate detection (MD5) and variant linking (perceptual hash, filename, manual). Link Mode highlights related assets on click
- **Rich Copy/Paste** — Ctrl+C/V carries full metadata (tags, crops, censors) across project tabs
- **Drag-drop** .doxyproj/.doxycoll files onto window to open

### Social Media Pipeline
- **Post Composer** — two-column layout with image preview, SFW/NSFW toggle, strategy notes, captions, scheduling
- **Calendar Pane** — month grid with colored status dots, JST/EST/PST world clock
- **Gantt Chart** — visual timeline with colored bars, stagger lines, gap detection, zoom slider
- **Release Chains** — staggered cross-platform posting (e.g., Twitter first, Patreon 48h later)
- **AI Strategy** — Claude CLI analyzes posting context, returns captions, timing, platform play, hooks
- **Multi-Identity** — multiple brand identities per project with voice, hashtags, locale settings
- **Reminder Engine** — scans release chains + Patreon cadence for due actions, status bar alerts

### Subscription Platform Automation
- **7 platforms** — Patreon, Pixiv Fanbox, Fantia, Ci-en, Gumroad, Ko-fi, SubscribeStar
- **Quick-Post** — clipboard + export + browser launch workflow for all platforms
- **Tier-based content** — free preview vs paid full version per platform
- **Dual-language** — Japanese + English captions for Fanbox/Fantia/Ci-en

### Cross-Project & Campaigns
- **Campaign System** — Kickstarter, Steam, merch launch tracking with milestones and blackout periods
- **Cross-Project Awareness** — conflict detection across projects (same day, same platform, saturation warnings)
- **Project Registry** — global registry at ~/.doxyedit/project_registry.json

### Platform & Infrastructure
- **Kanban Board** — 4 status columns (Pending/Ready/Posted/Skip) embedded in Platforms tab
- **7 Themes** — Vinik 24, Warm Charcoal, Soot, Bone, Milk Glass, Forest, Grey
- **Platform Export** — Kickstarter, Steam, Patreon, Twitter, Reddit, Instagram with auto-resize
- **OneUp Integration** — connected accounts for Twitter/X and Reddit via OneUp MCP server
- **YAML Config** — custom platform definitions via config.yaml (Tools > Edit Project Config)
- **Perceptual Hash** — Find Similar Images grouping via Tools menu
- **Disk Cache** — persistent thumbnail cache with color palette extraction
- **CLI Pipeline** — `python -m doxyedit summary/tags/untagged/status/reminders/plan-posts project.json`
- **Tabbed Notes** — General + Agent Primer + custom tabs with markdown preview and Claude actions

## Install

```bash
pip install -r requirements.txt
python run.py
```

Or double-click `doxyedit.bat`.

## Build Standalone

```bash
build.bat
```

Produces `dist/DoxyEdit.exe` via Nuitka.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Ctrl+S | Save |
| Ctrl+O | Open |
| Ctrl+N | New |
| Ctrl+T | Toggle Work Tray |
| Ctrl+L | Toggle Tag Panel |
| Ctrl+B | Toggle File Browser |
| Ctrl+I | Toggle Info Panel |
| Ctrl+A | Select All |
| Ctrl+D | Deselect |
| Ctrl+Scroll | Zoom thumbnails |
| Delete | Soft-delete (tag as ignore) |
| F5 | Refresh thumbnails |
| 1-8 | Toggle content tags |
| 0 | Toggle Ignore |
| C | Crop mode |
| Middle-click | Instant preview |
| Alt+click tag | Search by tag |

## Requirements

- Python 3.10+
- PySide6
- Pillow
- psd-tools
- pyyaml>=6.0
- pywin32 (optional, for SAI thumbnails)

## License

MIT
