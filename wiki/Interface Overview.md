---
tags: [ui, tabs, browser, studio, social, platforms, overview, notes]
description: Overview of all six tabs and the main workspace layout.
---

# Interface Overview

> [!note] Updated for v2.5
> Older versions had four tabs (Assets / Canvas / Censor / Platforms).
> The Canvas and Censor tabs were merged into a single **Studio** tab
> in v2.0+, and three new tabs were added: **Social**, **Overview**,
> **Notes**. The legacy Canvas and Censor sections below describe
> features that now live inside Studio.

DoxyEdit has six main tabs:

1. **Assets** - thumbnail browser, tagging, work tray (this page's
   first section, still accurate).
2. **Studio** - canvas + censor + crop + overlay + post-prep all
   in one editor with layer panel, undo/redo, snap guides, rulers,
   etc. Successor to the old Canvas + Censor tabs.
3. **Social** - timeline + calendar + checklist + Gantt for
   scheduling and pushing posts to OneUp / direct-API platforms.
4. **Platforms** - per-platform slot grid showing assigned assets +
   readiness + export status (still accurate).
5. **Overview** - project summary, asset folders, source roots,
   campaign + identity status.
6. **Notes** - markdown notes per project, with Claude actions on
   selection (rewrite / summarize / etc).

The Work Tray is a persistent panel on the right side that stays
visible across all tabs (Ctrl+T to toggle).

---

## Assets Tab (Main View)

The primary workspace. The left sidebar holds the Tag Panel, the main area shows the thumbnail grid.

### Toolbar

The browser toolbar uses a FlowLayout — buttons wrap on narrow windows. From left to right:
- **Tags** and **Tray** toggle buttons (leftmost, always visible)
- **+ Folder** and **+ Files** — import buttons
- **Recursive** checkbox — when checked, folder import scans subfolders
- **Search box** — filter by filename (supports glob patterns like `*.png`, `hero_*`)
- **Tags** checkbox — switch search from filename to tag name
- **Hover Preview** checkbox — toggle the hover popup
- **Cache All** checkbox — pre-generate all thumbnails in background
- Sort combo — Name A-Z, Name Z-A, Newest, Oldest, Largest, Smallest, By Folder, Starred First, Most Tagged

### Filter Buttons (toolbar)

| Button | What It Shows |
|--------|--------------|
| Starred | Only starred images |
| Untagged | Images with no content/workflow tags |
| Tagged | Images with at least one tag |
| Show Ignored | Reveals soft-deleted images |
| Has Notes | Images with note annotations |

### Thumbnail Grid

- **Click** — select one image
- **Ctrl+Click** — toggle multi-select
- **Shift+Click** — select range
- **Alt+Click** — send to Studio (legacy: was "send to Censor" in v1.x)
- **Enter** or **Double-click** — open preview window
- **Middle-click** — instant preview (works even with hover disabled)
- **Up/Down arrows** — navigate between thumbnails; auto-scrolls to keep selection visible
- **Ctrl+Scroll** — zoom thumbnails (80px to 320px, no rebuild)
- **Delete** — soft-delete selected images (tags as "ignore", hides from grid)

Each thumbnail shows:
- The image (3px rounded corners)
- Filename with extension
- Resolution (toggleable via View menu)
- Colored tag dots (one per tag, tag's own color)
- Star indicator (bottom-right)
- Platform status badge

> [!tip] Batch Tagging
> Shift+click a range of thumbnails, then press a number key (1-8) to tag all selected images at once.

### Status Bar

Shows count of shown / starred / tagged images. Displays a filter indicator (⬡ FILTERED) when any filter is active.

---

## Canvas Tab (legacy — now part of Studio)

> [!warning] Merged into Studio in v2.0
> The standalone Canvas tab no longer exists. Its tools (text, line,
> box, marker, color) plus a lot more (overlays, watermarks, shapes,
> arrows, eyedropper, layer panel, snap guides, rulers, undo/redo)
> live in the **Studio** tab. The descriptions below match the old
> Canvas tab and are kept as reference for v1.x users; for the
> current toolset see Studio's own keyboard shortcut cheatsheet
> (F1 / `?` button inside Studio).

Free-form annotation surface for composing layouts and planning.

### Canvas Tools (left toolbar)

| Tool | Key | Description |
|------|-----|-------------|
| Select | V | Move and select items |
| Text | T | Click to place text, double-click to edit |
| Line | L | Click and drag to draw a line |
| Box | B | Click and drag to draw a rectangle |
| Marker | G | Click to place a colored tag marker |
| Color | — | Change selected item's color |

- **Scroll** to zoom
- **Middle-click + drag** to pan
- **Delete** removes selected items

Canvas tools in the toolbar are hidden when you are not on the Canvas tab.

---

## Censor Tab (legacy — now part of Studio)

> [!warning] Merged into Studio in v2.0
> Censor regions are drawn from the same Studio tab that owns crops
> and overlays. The X key activates the censor tool inside Studio.
> The dedicated Censor tab no longer exists.

Non-destructive censoring for platform-specific versions (e.g., Japan releases, age-gated platforms).

### Workflow

1. Select an image in the Assets tab (or **Alt+Click** a thumbnail to jump directly here)
2. Choose censor style: **black**, **blur**, or **pixelate**
3. Click **Draw Censor Region** and drag to mark an area
4. Regions are movable and selectable after drawing
5. Click **Export Censored** to save a copy with censoring applied
6. The original file is never modified

---

## Platforms Tab

Shows target platforms with their required image slots and sizes.

### Built-in Platforms

- Kickstarter
- Kickstarter (Japan)
- Steam
- Patreon
- Twitter / X
- Reddit
- Instagram

Each slot displays: name, target size, assigned asset thumbnail, and status (pending / ready / posted / skip).

**Ctrl+E** exports all platforms with auto-resize to the correct dimensions.

---

## Work Tray (Right Panel)

The Work Tray is a collapsible right panel that persists across all six tabs. Use it as a staging area for assets you're actively working with.

- **Ctrl+T** toggles it open/closed
- Remembers its width when toggled
- Tray items are saved in the project file
- Column view modes: ☰ button cycles list → 2-col grid → 3-col grid
- Right-click tray items: Preview, Copy Path, Copy Filename, Open in Explorer, Move to Top/Bottom, Quick Tag, Clear All

Tray items can be dragged out to external applications (Photoshop, Explorer, etc.). Multi-select drag is supported.

---

## Tag Panel (Left Sidebar)

The Tag Panel slides in/out with **Ctrl+L** or the **Tags** toolbar button. See [[Tagging System]] for full details.

---

## Related

- [[Tagging System]] — tag panel sections, eye toggles, shortcuts
- [[Preview Window]] — zoom, pan, notes
- [[Platform Publishing]] — slot assignments, export
- [[Keyboard Shortcuts]] — complete list
