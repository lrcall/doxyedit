---
tags: [setup, install, quickstart]
description: How to install, run, and create your first DoxyEdit project.
---

# Getting Started

DoxyEdit is a desktop art asset manager for Windows. It uses PySide6 (Qt) and requires Python 3.10+.

---

## Installation

### Requirements

- Python 3.10 or newer
- PySide6
- Pillow
- psd-tools
- pywin32 (optional — needed for SAI/SAI2 thumbnails)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run from Source

```bash
python run.py
```

Or double-click **`doxyedit.bat`** from Windows Explorer.

### Build Standalone Exe

```bash
build.bat
```

Produces `dist/DoxyEdit.exe` via Nuitka. The build script clears the Nuitka cache for a clean build and bundles psd-tools + numpy.

> [!note] Nuitka Required
> Building the standalone exe requires Nuitka. Install it separately: `pip install nuitka`

---

## First Launch

On first launch DoxyEdit opens with an empty project. It remembers your last project and auto-loads it on subsequent launches.

### Creating a Project

1. **File > New** (Ctrl+N) — start fresh
2. Import images using one of:
   - Click **+ Folder** in the toolbar (imports a folder, asks about subfolders)
   - Click **+ Files** in the toolbar
   - Drag files or folders from Windows Explorer onto the window
   - **Ctrl+V** to paste — accepts images, file paths, folder paths, or URLs
   - **File > Paste Folder** — imports a folder path on the clipboard

### Saving a Project

- **Ctrl+S** — save to current file (`.doxyproj.json`)
- **Ctrl+Shift+S** — Save As to a new location
- Auto-save runs every 30 seconds if there are unsaved changes
- A `.bak` backup file is created each time you open a project

> [!tip] Project File Location
> Keep your `.doxyproj.json` file somewhere stable. The project stores absolute file paths to your images — moving the images will break the links unless you update the paths.

---

## Supported File Formats

| Format | Thumbnails | Preview | Notes |
|--------|-----------|---------|-------|
| PNG, JPG, BMP, GIF, WebP, TIFF, TGA | Full | Full | Native PIL |
| SVG | Full | Full | Via Qt |
| PSD, PSB | Full | Full | Via psd-tools (composite) |
| SAI, SAI2 | Shell thumb | Shell thumb | Requires SaiThumbs installed |
| CLIP, CSP, KRA, XCF | Shell / Placeholder | Shell / Placeholder | Shell extension dependent |
| ICO, DDS, EXR, HDR | Varies | Varies | PIL support varies |

### SAI / SAI2 Thumbnails

Install [SaiThumbs](https://wunkolo.itch.io/saithumbs) for Windows shell thumbnails. DoxyEdit borrows these via the Windows Shell API. Without it, SAI files show a placeholder.

---

## What Persists Between Sessions

All of the following are saved and restored automatically:

- Last project (auto-loads on startup)
- Last opened folder
- Theme
- Font size
- Thumbnail zoom level
- Preview window size, position, and zoom
- Recent projects and folders lists (last 10 of each)
- Sort mode, eye-hidden tags, tray items (stored in project file)

---

## Related

- [[Interface Overview]] — learn the four tabs
- [[Tagging System]] — start tagging your assets
- [[Keyboard Shortcuts]] — full shortcut reference
- [[Thumbnail Cache]] — how caching works
