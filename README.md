# DoxyEdit

Art asset manager for artists and creators. Browse, tag, organize, and export art across multiple platforms.

![PySide6](https://img.shields.io/badge/PySide6-Qt-green) ![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)

## Features

- **Thumbnail Browser** — QListView with smooth virtual scrolling, Ctrl+scroll zoom, hover/middle-click preview
- **File Browser** — folder tree with asset counts, search, pinned folders, drag-to-import (Ctrl+B)
- **Info Panel** — asset metadata with editable tag pills, inline notes, color palette swatches (Ctrl+I)
- **PSD/SAI Support** — PSD compositing via psd-tools, SAI/SAI2 via Windows shell thumbnails (SaiThumbs)
- **Tagging System** — keyboard shortcuts, custom tags, auto visual property tags (warm/cool/dark/portrait etc.)
- **4-Section Tag Panel** — Content, Platform/Size, Custom/Project, Visual/Mood with eye toggles and pin-to-top
- **Smart Folders** — save/load filter presets (View > Smart Folders)
- **Non-Destructive Censor** — black/blur/pixelate overlays, export censored copies
- **Canvas Annotation** — free-form text, lines, boxes, markers
- **Preview Annotations** — draw note boxes on images, persist with project
- **Work Tray** — collapsible quickslot panel, persists across all tabs
- **Kanban Board** — 4 status columns (Pending/Ready/Posted/Skip) embedded in Platforms tab
- **7 Themes** — Vinik 24, Warm Charcoal, Soot, Bone, Milk Glass, Forest, Grey
- **Platform Export** — Kickstarter, Steam, Patreon, Twitter, Reddit, Instagram with auto-resize
- **YAML Config** — custom platform definitions via config.yaml (Tools > Edit Project Config)
- **Perceptual Hash** — Find Similar Images grouping via Tools menu
- **Disk Cache** — persistent thumbnail cache with color palette extraction
- **CLI Pipeline** — `python -m doxyedit summary/tags/untagged/status project.json`
- **Crop Handles** — 8 drag handles on crop regions with persistent overlays

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
