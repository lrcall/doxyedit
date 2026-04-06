---
tags: [import, export, drag-drop, clipboard, formats, markdown]
description: Importing images, pasting paths, exporting platform copies, markdown import/export, and moving assets between projects.
---

# Import & Export

---

## Importing Images

### Methods

| Method | How |
|--------|-----|
| + Folder button | Browse for a folder (asks about subfolders) |
| + Files button | Browse for individual files |
| Drag & Drop | Drag files or folders from Windows Explorer onto the window |
| Ctrl+V | Paste — accepts images, file paths, folder paths, or URLs |
| File > Paste Folder | Import a folder path currently on the clipboard |

### Recursive Import

The **Recursive** checkbox in the toolbar controls whether folder imports scan subfolders. When importing a folder that has subfolders, DoxyEdit asks "Import recursively?" as a prompt.

### Supported Formats on Import

PNG, JPG, BMP, GIF, WebP, TIFF, TGA, SVG, PSD, PSB, SAI, SAI2, CLIP, KRA, XCF

Unsupported file types are silently discarded when pasting or drag-dropping mixed content.

### Ctrl+V Paste

Ctrl+V accepts:
- A copied image from the clipboard
- A file path (text)
- A folder path (text)
- Multiple paths (one per line)
- A URL

After paste, the view scrolls to the newly added asset.

---

## Auto-Tags on Import

When images are imported, DoxyEdit can automatically apply tags based on:
- **Filename keywords** (e.g., `cover` → Cover tag, `sketch` → Sketch tag)
- **Visual properties** computed from pixels (warm/cool, dark/bright, portrait/landscape, etc.)

Auto-tagging is toggled via **Tools > Auto-Tag** (defaults to off).

See [[Tagging System]] for the full list of auto-tags.

---

## Exporting Platform Images

**Ctrl+E** — exports all platforms at once.

DoxyEdit auto-resizes each assigned asset to the target platform dimensions and saves copies. Original files are never modified.

> [!tip] Export Workflow
> 1. Tag your images
> 2. Assign images to platform slots (Platforms tab or right-click → Assign to Platform)
> 3. Press Ctrl+E to export everything

If a required slot has no assigned asset, DoxyEdit warns you before proceeding (Smart Export Gap Detection).

---

## Exporting Selected Assets

**Right-click selected thumbnails → Export Selected to Folder** — saves copies of the selected images to a folder of your choice, without resizing.

---

## Moving Assets Between Projects

### Move to Another Project

**Edit > Move to Another Project** — opens a file dialog to pick an existing `.doxyproj.json`. Selected assets are transferred to the other project and removed from the current one.

### Move to New Project

**Edit > Move to New Project** — opens a Save dialog to create a new `.doxyproj.json`. Selected assets move to the new project file.

---

## Markdown Import / Export

**File > Import MD** and **File > Export MD** — import and export project data as Markdown. Useful for documentation, Claude CLI integration, or sharing project structure outside DoxyEdit.

---

## Drag from Work Tray

Work Tray items can be dragged out to external applications (Photoshop, Explorer, etc.). Multi-select drag is supported — select multiple tray items then drag them all at once.

Uses `QDrag` with file URL mime data, compatible with any application that accepts dragged files.

---

## Copy Paths to Clipboard

| Action | Method |
|--------|--------|
| Copy path of selected asset | Right-click → Copy Path |
| Copy filename | Right-click → Copy Filename |
| Copy filename without extension | Right-click → Copy Filename Without Extension |
| Copy all selected paths | Right-click (multi-select) → Copy All Paths |
| Copy full file path | Ctrl+Shift+C |

---

## Rename File on Disk

**F2** with an asset selected — opens a rename dialog to rename the actual source file on disk. The project reference is updated automatically.

---

## Recent Files

**File > Recent Projects** — last 10 projects.
**File > Recent Folders** — last 10 folders used for import.

Last project auto-loads on startup.

---

## Related

- [[Getting Started]] — first import walkthrough
- [[Platform Publishing]] — platform export workflow
- [[Tagging System]] — auto-tagging on import
- [[CLI Reference]] — CLI export commands
