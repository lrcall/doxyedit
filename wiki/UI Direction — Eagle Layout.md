---
tags: [ui, design, eagle, layout, planned, future]
description: Future UI direction — Eagle-style three-panel layout with folder tree sidebar and right info panel.
---

# UI Direction — Eagle-Style Layout

Reference screenshot: Eagle app showing the three-panel layout that serves as the target visual direction for a future DoxyEdit UI refresh.

---

## Layout Structure

```
┌─────────────────────────────────────────────────────────────────┐
│  [← →]  Current Folder         [zoom] [sort] [filter] [search] │  ← top bar
├──────────────┬──────────────────────────────────┬───────────────┤
│              │                                  │  Preview      │
│  Left Panel  │   Thumbnail Grid                 │  (large thumb)│
│              │                                  │               │
│  All         │   □ □ □ □ □                      │  Color swatches│
│  Untagged    │   □ □ □ □ □                      │               │
│  All Tags    │   □ □ □ □ □                      │  Name         │
│              │                                  │  Notes...     │
│  ─ Folders ─ │                                  │               │
│  ▼ Group A   │                                  │  Tags         │
│    Sub A1    │                                  │  [tag] [tag]+ │
│    Sub A2    │                                  │               │
│  ▼ Group B   │                                  │  Folders      │
│    Sub B1    │                                  │  [folder] +   │
│              │                                  │               │
│  ─ Filter ─  │                                  │  Properties   │
│  [Filter box]│                                  │  Rating ★★★★☆ │
│              │                                  │  Dimensions   │
│              │                                  │  Size         │
│              │                                  │  Type         │
│              │                                  │  Date Added   │
└──────────────┴──────────────────────────────────┴───────────────┘
```

---

## Left Panel (Sidebar)

Replaces the current Tag Panel + By Folder view split.

### Fixed Items (top)
| Label | Description |
|-------|-------------|
| All | All assets in project |
| Uncategorized | Assets with no folder assignment |
| Untagged | Assets with no content tags |
| All Tags | Tag browser view |
| Trash / Ignored | Soft-deleted assets |

### Smart Folders (optional)
User-defined saved filters (e.g. "Starred + Finished", "Needs Censor").

### Folders
Tree view of source folders. Collapsible groups. Item count badge on right. Clicking a folder filters the grid to that folder only.

- Top-level groups have a colored icon (folder color = tag color of that group)
- Sub-folders indent with a connecting line
- Active folder highlighted with accent background

### Bottom
- **Filter box** — live text filter on folder/tag names in the sidebar
- No separate toolbar toggle needed — sidebar is always visible, resizable

---

## Thumbnail Grid (Center)

- No filename label by default — appears on hover only (or toggle)
- Larger default cell size (closer to 200px default vs current 160px)
- Uniform square cells — image letterboxed/pillarboxed to fill cell
- Selection: blue accent border (2px), no background tint
- Zoom slider in top bar (replaces Ctrl+scroll as primary control, but keep Ctrl+scroll too)
- No visible tag dots on thumbnails — cleaner look
- Star shown as small badge bottom-right only if starred

---

## Right Info Panel

Appears when an asset is selected. Fixed width (~220–260px), collapsible.

### Sections

**Preview** — large thumbnail of selected asset (full panel width)

**Color Palette** — extracted dominant colors as small swatches (5–7 circles). Read from `specs.palette` if available.

**Name** — editable inline filename display

**Notes** — multiline editable text field (maps to `asset.notes`)

**Tags** — pill tags with × to remove, `+` to add new. Maps to `asset.tags`.

**Folders** — which source folders this asset belongs to. Read-only, links to sidebar.

**Properties** (read-only)
| Field | Source |
|-------|--------|
| Rating | `asset.starred` → ★ display |
| Dimensions | `asset.specs.w × asset.specs.h` |
| File Size | from disk |
| Type | file extension |
| Date Imported | asset creation time |

---

## Top Bar

Minimal. Left-aligned: back/forward navigation, current folder name.
Right-aligned: zoom slider, sort dropdown, filter toggle, search box.

No floating toolbar. No button rows. No checkbox cluster.

All import actions (+ Folder, + Files, etc.) move to **File menu** or a single **`+`** button that drops a small menu.

---

## Key Visual Differences from Current DoxyEdit

| Current | Eagle-style target |
|---------|-------------------|
| Tags panel (left) + toolbar (top) | Single sidebar: folders + smart filters |
| Tag dots on thumbnails | Clean thumbnails, no dots |
| Filename always visible | Filename on hover only |
| Toolbar row of filter buttons | Right-click → filter, or sidebar click |
| Work Tray (right, persistent) | Replaced by / coexists with Info Panel |
| Tab bar (Assets / Canvas / etc.) | Single view, everything in sidebar |
| Count label in status bar | Count badge on sidebar items |

---

## Implementation Approach

**Recommended: new tab alongside existing Assets tab**, not a full replacement.

1. Add a **"Gallery"** tab — Eagle-style three-panel layout
2. Shares the same project data, same `ThumbCache`, same tag system
3. Right info panel uses existing `asset.tags`, `asset.notes`, `asset.starred`
4. If Gallery tab feels right in daily use, gradually retire the old Assets tab

This avoids breaking the current workflow while the new layout is validated.

### New Components Needed
| Component | Notes |
|-----------|-------|
| `SidebarPanel` | QTreeWidget or custom widget for folder tree + smart filters |
| `InfoPanel` | QWidget with stacked sections (preview, tags, notes, props) |
| `GalleryView` | Three-pane QSplitter wrapping SidebarPanel + QListView + InfoPanel |
| Color palette extractor | Already partially in `specs.palette` via autotag |
| Inline tag editor | Pill-style tag chips with × and + (new widget) |

---

## Color / Typography Notes from Screenshot

- Background: very dark navy/slate (`#1a1d2e` range) — darker than current Soot
- Sidebar active item: solid accent fill, white text
- Thumbnail cells: no border, uniform dark background behind each image
- Right panel: slightly lighter surface than sidebar
- Tag pills: dark fill, light text, `×` on right — no colored dots
- Count badges: right-aligned muted number, no background
- Font: system sans, 12–13px, medium weight for labels

---

## Related

- [[Eagle Integration]] — importing Eagle library metadata
- [[Interface Overview]] — current tab layout
- [[Roadmap]] — feature backlog
- [[Themes & Appearance]] — color palette reference
