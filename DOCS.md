# DoxyEdit Documentation

**Version 0.3** — Art Asset Manager

DoxyEdit is a desktop tool for artists and creators to browse, tag, organize, and export art assets across multiple platforms (Kickstarter, Steam, Patreon, social media).

---

## Getting Started

### Install
```bash
pip install -r requirements.txt
```

### Run
```bash
python run.py
```
Or double-click `doxyedit.bat`.

### Build Standalone Exe
```bash
build.bat
```
Produces `dist/DoxyEdit.exe` (requires Nuitka).

---

## Interface Overview

DoxyEdit has 4 tabs: **Assets**, **Canvas**, **Censor**, **Platforms**.

### Assets Tab (Main View)

The primary workspace. Left sidebar has the tag panel, main area shows the thumbnail grid.

**Importing Images:**
- Click **+ Folder** or **+ Files** in the toolbar
- Drag files/folders from Windows Explorer onto the window
- **Ctrl+V** to paste — accepts images, file paths, folder paths, or URLs
- Supports: PNG, JPG, BMP, GIF, WebP, TIFF, TGA, SVG, PSD, PSB, SAI, SAI2, CLIP, KRA, XCF

**Browsing:**
- **Ctrl+Scroll** — zoom thumbnails (80px to 320px)
- **Double-click** — open full zoomable preview (Scroll to zoom, Drag to pan, N = add note, Esc to close)
- **Recursive** checkbox — when checked, + Folder imports subfolders too
- **Hover** — shows larger preview popup (toggle with "Hover Preview" checkbox)
- Pages of 100 thumbnails — use Prev/Next or page indicator at bottom

**Selecting:**
- **Click** — select one image
- **Ctrl+Click** — toggle multi-select
- **Shift+Click** — select range
- **Alt+Click** — send to Censor tab

**Search & Filter:**
- Type in search box to filter by filename (supports glob patterns like `*.png`, `hero_*`)
- Check **Tags** checkbox to search by tag name instead
- **Starred** / **Untagged** / **Tagged** / **Show Ignored** filter buttons
- Sort by: Name A-Z, Name Z-A, Newest, Oldest, Largest, Smallest

---

## Tagging System

### Quick-Tag Bar (top of grid)
Colored pill buttons for fast tagging. Click to toggle on selected images.
Shows content/workflow tags and discovered tags (not platform/size tags).
- **Alt+Click** a tag button — searches by that tag
- **+** button — add a custom tag

### Keyboard Shortcuts (Assets tab only)
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

### Tag Panel (left sidebar)
Shows all tags with checkboxes. Click to apply/remove on selected image(s).

**Sections:**
- **Content/Workflow** — general-purpose tags (Page, Character, Sketch, etc.)
- **Platform/Size targets** — campaign-specific with target dimensions (Hero 1024x576, Banner 1600x400, etc.)
- **Discovered tags** — auto-generated visual properties and custom tags

**Fitness Dots:**
- Green = image is large enough for this target size
- Yellow = large enough but aspect ratio differs (crop needed)
- Red = image too small

**Right-click a tag to:**
- Rename it
- Hide it from the panel
- Delete it from all assets

**Buttons:**
- **Mark Ignore** — tags selected as ignore
- **Clear All** — removes all tags from selected
- **Show All** — reveals hidden tags

### Auto Tags
On import, images are automatically tagged based on:
- **Filename** — "cover" in name → Cover tag, "sketch" → Sketch, etc.
- **Visual properties** — warm/cool, dark/bright, detailed/flat, portrait/landscape/square/panoramic/tall (computed from pixels)

---

## Star Rating

Click the star button (bottom-right of each thumbnail) to cycle through 5 colors:
1. Gold
2. Blue
3. Green
4. Rose
5. Red
6. (off)

Filter with the **Starred** button. Stars are saved with the project.

---

## Delete / Ignore

- **Delete key** on Assets tab — soft-deletes selected images (tags as "ignore", hides from grid)
- **Show Ignored** button reveals hidden images
- Nothing is actually deleted from disk — just hidden

---

## Canvas Tab

Free-form annotation surface for composing layouts.

**Tools (left toolbar):**
| Tool | Description |
|------|-------------|
| Select (V) | Move and select items |
| Text (T) | Click to place text, double-click to edit |
| Line (L) | Click and drag to draw a line |
| Box (B) | Click and drag to draw a rectangle |
| Marker (G) | Click to place a colored tag marker |

- **Scroll** to zoom
- **Middle-click + drag** to pan
- **Delete** to remove selected items
- **Color** button to change selected item's color

---

## Preview Annotations

In the double-click preview dialog, you can draw annotation notes directly on the image:

1. Press **N** or click **Add Note** button
2. Drag a rectangle on the image
3. Type your note text in the dialog
4. Note is saved to the asset's notes field
5. **Delete** key removes selected notes
6. **Ctrl+0** to fit image to view

Notes are stored as text coordinates in the asset's notes field and persist with the project.

---

## Censor Tab

Non-destructive censoring for platform-specific versions (e.g., Japan releases).

1. Select an image in Assets tab (or Alt+click to jump here)
2. Choose style: **black**, **blur**, or **pixelate**
3. Click **Draw Censor Region** and drag to draw
4. Regions are movable and selectable
5. Click **Export Censored** to save a copy with censoring applied
6. Original file is never modified

---

## Platforms Tab

Shows target platforms with their required image slots and sizes.

**Built-in platforms:**
- Kickstarter, Kickstarter (Japan), Steam, Patreon, Twitter/X, Reddit, Instagram

Each slot shows: name, target size, assigned asset, and status (pending/ready/posted/skip).

---

## File Operations

| Shortcut | Action |
|----------|--------|
| Ctrl+N | New project |
| Ctrl+O | Open project |
| Ctrl+S | Save project |
| Ctrl+Shift+S | Save as |
| Ctrl+E | Export all platforms |
| Ctrl+V | Paste image/path/folder |
| Ctrl+T | Toggle tag panel |
| Ctrl+= | Increase font size |
| Ctrl+- | Decrease font size |
| Ctrl+0 | Reset font size |

### Project File (.doxyproj.json)
Human-readable JSON. Can be edited by Claude CLI or by hand.

```json
{
  "name": "My Project",
  "assets": [
    {
      "id": "cover_0",
      "source_path": "C:/art/cover.png",
      "starred": 2,
      "tags": ["cover", "hero", "warm", "portrait"]
    }
  ],
  "custom_tags": [
    {"id": "marty", "label": "Marty", "color": "#9a4f50"}
  ]
}
```

### Auto-Save
Project auto-saves every 30 seconds if there are unsaved changes. Also saves on window close.

### Recent Files
**File > Recent Projects** and **File > Recent Folders** — last 10 of each.

Last project auto-loads on startup.

---

## CLI Commands

For integration with Claude CLI or scripts:

```bash
python -m doxyedit summary project.doxyproj.json   # JSON status overview
python -m doxyedit tags project.doxyproj.json       # List all assets and tags
python -m doxyedit untagged project.doxyproj.json   # List untagged assets
python -m doxyedit status project.doxyproj.json     # Platform slot assignments
```

---

## Themes

**View > Theme** — 7 built-in themes:

| Theme | Style |
|-------|-------|
| Vinik 24 | Dark purple/teal (default) |
| Warm Charcoal | Warm dark tones |
| Soot | Cool dark purple |
| Bone | Light warm beige |
| Milk Glass | Light cool grey |
| Forest | Dark green |
| Dark | Classic IDE dark |

Windows title bar color matches the active theme. Theme persists across sessions.

---

## Supported Formats

| Format | Thumbnail | Preview | Notes |
|--------|-----------|---------|-------|
| PNG, JPG, BMP, GIF, WebP, TIFF, TGA | Full | Full | Native PIL |
| SVG | Full | Full | Via Qt |
| PSD, PSB | Full | Full | Via psd-tools (composite) |
| SAI, SAI2 | Shell thumb | Shell thumb | Requires SaiThumbs installed |
| CLIP, CSP, KRA, XCF | Shell/Placeholder | Shell/Placeholder | Shell extension dependent |
| ICO, DDS, EXR, HDR | Varies | Varies | PIL support varies |

### SAI/SAI2 Thumbnails
Install [SaiThumbs](https://wunkolo.itch.io/saithumbs) for Windows shell thumbnails. DoxyEdit borrows these via the Windows Shell API.

---

## State Persistence

All of these persist across sessions (via QSettings):
- Last project (auto-loads on startup)
- Last opened folder
- Theme
- Font size
- Thumbnail zoom level
- Preview window size, position, and zoom
- Recent projects and folders lists

---

## Tips

- **Batch tag with multi-select** — Shift+click a range, then press a number key to tag all at once
- **Quick ignore** — select images you don't want, press Delete
- **Find by type** — search `*.psd` or `*.sai2` to filter by format
- **Fresh start** — File > Reset All Tags to clear everything
- **Export workflow** — tag images, assign to platform slots, Ctrl+E exports resized copies with correct names
