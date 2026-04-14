# DoxyEdit Documentation

**Version 2.3** — Art Asset Manager + Social Media Pipeline

DoxyEdit is a desktop tool for artists and creators to browse, tag, organize, and export art assets across multiple platforms (Kickstarter, Steam, Patreon, social media). v2.3 adds a full social media publishing pipeline with scheduling, cross-platform release chains, subscription platform automation, and AI-assisted strategy.

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

DoxyEdit has 6 tabs: **Assets**, **Studio**, **Social**, **Platforms**, **Overview**, **Notes**.

### Assets Tab (Main View)

The primary workspace. Left sidebar has the tag panel, main area shows the thumbnail grid.

**Importing Images:**
- Click **+ Folder** or **+ Files** in the toolbar
- Drag files/folders from Windows Explorer onto the window
- **Ctrl+V** to paste — accepts images, file paths, folder paths, or URLs
- **File > Paste Folder** — imports a folder path currently on the clipboard
- Supports: PNG, JPG, BMP, GIF, WebP, TIFF, TGA, SVG, PSD, PSB, SAI, SAI2, CLIP, KRA, XCF

**File Browser Panel (Ctrl+B):**
- Opens a docked folder-tree panel on the left for navigating the filesystem
- Click any folder to browse its images directly without importing
- Integrates with the asset grid — selected folder filters the displayed images
- Keyboard shortcut: **Ctrl+B** toggles the panel open/closed

**Browsing:**
- **Smooth virtual scrolling** — no paging, all images accessible by scrolling
- **Ctrl+Scroll** — zoom thumbnails instantly (80px to 320px, no rebuild)
- **Enter** or **Double-click** — open full zoomable preview (Scroll to zoom, Drag to pan, N = add note, Esc to close)
- **Up/Down arrows** — navigate between thumbnails; auto-scrolls to keep selection visible
- **Recursive** checkbox — when checked, + Folder imports subfolders too
- **Hover** — shows larger preview popup (toggle with "Hover Preview" checkbox)
- **Cache All** checkbox — pre-generate thumbnails for entire project in background

**Selecting:**
- **Click** — select one image
- **Ctrl+Click** — toggle multi-select
- **Shift+Click** — select range
- **Alt+Click** — send to Studio tab

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

### Global Keyboard Shortcuts
| Shortcut | Action |
|----------|--------|
| Ctrl+B | Toggle File Browser panel |
| Ctrl+I | Toggle Info Panel |
| Ctrl+D | Toggle Docked Preview |
| C | Crop (in preview — enters crop handle mode) |

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

**Eye Toggle (👁):**
Each tag has an eye button. Click to hide all images with that tag from the grid.
Click again to show them. Works like Photoshop layer visibility — multiple eyes
can be toggled independently.

**Right-click a tag to:**
- **Pin to top** — moves it to the top of its section (gold border)
- **Set Shortcut Key** — assign any single key as a keyboard shortcut
- Rename it
- Hide it from the panel
- Delete it from all assets

**Tag Panel Sections (top to bottom):**
1. Content/Workflow — Page, Character, Sketch, Game Asset, etc.
2. Platform/Size targets — Hero 1024x576, Banner 1600x400, etc.
3. Custom/Project — user-added tags (hardblush, marty, etc.)
4. Visual/Mood/Dimension — warm, cool, dark, portrait, landscape, etc.

**Buttons:**
- **Mark Ignore** — tags selected as ignore
- **Clear All** — removes all tags from selected
- **Show All** — reveals hidden tags

### Info Panel (Ctrl+I)

A docked side panel showing metadata for the selected asset:
- **Editable tags** — add or remove tags directly in the panel
- **Editable notes** — freeform notes field, saved with the asset
- **Color palette swatches** — dominant colors extracted from the image, shown as clickable swatches
- Toggle with **Ctrl+I** or via View menu

### Smart Folders

**View > Smart Folders** opens a saved-search panel:
- Create named virtual folders based on tag combinations or filename filters
- Click a smart folder to apply its filter to the asset grid
- Smart folders are saved with the project

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

## Studio Tab

Unified editor combining canvas, censor, and overlay tools in a single layered scene.

### Layer System
| Z-Range | Layer | Persistence |
|---------|-------|-------------|
| Z=0 | Base image | Source file |
| Z=100+ | Censors | Saved to project |
| Z=200+ | Overlays (watermark, text, logo) | Saved to project |
| Z=300+ | Annotations | Ephemeral (not saved) |

### Toolbar
A single toolbar provides access to all editing modes:
- **Censor draw** — black/blur/pixelate overlays for platform-specific versions
- **Overlay tools** — watermark, text, and logo placement with drag positioning, opacity/scale sliders, and template presets
- **Annotation tools** — free-form text, lines, boxes, markers for temporary notes

### Controls
- **Scroll** to zoom
- **Middle-click + drag** to pan
- **Delete** to remove selected items
- **Color** button to change selected item's color

### Export
Censors and overlays are composited during export only — the source file is never modified. The `apply_overlays()` function is shared between the GUI export and the CLI `watermark` command.

---

## Preview Window

Open by pressing **Enter** or **double-clicking** a thumbnail. Only one preview window is ever open at a time — opening again on a different image updates the same window.

**Navigation inside preview:**
| Key | Action |
|-----|--------|
| Space / Tab / Down | Next image |
| Backspace / Up / Left | Previous image |
| Esc | Close preview |
| Ctrl+0 | Fit image to view |
| N | Add note annotation |
| V | Toggle View Notes |

Navigation also syncs the thumbnail selection in the main browser grid.

**Mouse:**
- Scroll to zoom
- Drag to pan (free overpan — you can scroll past image edges)

**Window controls:**
- Minimize, maximize, and restore buttons in the preview title bar
- **Pop-out button** — detaches the preview into a floating window
- **Ctrl+D** — toggles the preview into a docked panel alongside the asset grid
- Title bar and buttons are fully themed (accent color via DWM)
- Scrollbar handles use the accent color and brighten on hover

**Crop mode (C key):**
Press **C** while the preview is open to enter crop handle mode. Drag the corner/edge handles to define a crop region. The crop is saved per-asset and used for platform exports.

### Preview Annotations

Draw annotation notes directly on the image:

1. Press **N** or click **Add Note** button
2. Drag a rectangle on the image
3. Type your note text in the dialog
4. Note is saved to the asset's notes field
5. **Delete** key removes selected notes
6. **Ctrl+0** to fit image to view

**View Notes** button (or **V** key) toggles saved annotations visible/hidden. View Notes defaults to off when the preview opens.

Notes are stored as text coordinates in the asset's notes field and persist with the project.

---

## Platforms Tab

Shows target platforms with their required image slots and sizes.

**Built-in platforms:**
- Kickstarter, Kickstarter (Japan), Steam, Patreon, Twitter/X, Reddit, Instagram

Each slot shows: name, target size, assigned asset, and status (pending/ready/posted/skip).

**Campaign UI:**
The Platforms tab includes a campaign management panel with a campaign selector, CRUD dialog for creating/editing campaigns, and a milestone checklist. Platform cards can be filtered by campaign_id to focus on a specific launch. Platform assignments are linked to campaigns for coordinated milestone tracking and blackout period enforcement. See [Campaign System](#campaign-system) below.

**Kanban Board:**
The Platforms tab includes a kanban-style board view for tracking publish status across platforms. Each platform column shows cards for its image slots, which can be dragged between status columns (Backlog, Ready, Posted, Skip). The board and the slot list stay in sync — updating one updates the other.

**Checklist:**
Each platform slot has an optional checklist for tracking sub-tasks (e.g., "resize", "watermark", "upload"). Checklists are stored with the project.

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
| Ctrl+B | Toggle File Browser panel |
| Ctrl+I | Toggle Info Panel |
| Ctrl+D | Toggle Docked Preview |
| Ctrl+= | Increase font size |
| Ctrl+- | Decrease font size |
| Ctrl+0 | Reset font size |
| Up/Down arrows | Navigate thumbnails (browser) |
| Enter | Open preview for selected thumbnail |
| Space / Tab / Down | Next image (inside preview) |
| Backspace / Up / Left | Previous image (inside preview) |
| C | Crop mode (inside preview) |

### Collections

A **Collection** is a saved subset of assets — a named list of asset IDs — stored as a lightweight file alongside the project.

| Menu | Action |
|------|--------|
| File > Save Collection | Save current filtered/selected set as a named collection |
| File > Open Collection | Load a collection, filtering the grid to its assets |
| File > Reload Collection | Refresh an open collection (re-applies filter) |

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

## Social Tab

The Social tab is the publishing pipeline hub. It contains four sub-panels: **Calendar**, **Timeline**, **Gantt Chart**, and **Checklist**.

### Calendar Pane

A month-view grid showing scheduled posts as colored status dots:
- **Green** = posted, **Blue** = queued, **Yellow** = draft, **Red** = failed
- Click a day to filter the timeline to that date
- **World clock** — shows JST, EST, and PST alongside the calendar
- Navigate months with arrow buttons

### Timeline

A chronological list of all social posts for the project. Each entry shows:
- Asset thumbnail, caption preview, scheduled date/time
- Platform badges (Twitter/X, Reddit, Patreon, etc.)
- Status indicator (draft/queued/posted/failed)
- Click to open the post in the Composer

### Gantt Chart

Visual timeline rendering all posts as horizontal colored bars on a date axis:
- **Stagger connection lines** — shows release chain relationships between posts
- **Gap detection** — highlights periods with no scheduled content
- **Today marker** — vertical line indicating the current date
- **Zoom slider** — adjust the time scale from days to months
- **Date range picker** — focus on a specific window
- Click any bar to open that post in the Composer

### Checklist

Task checklist for tracking publishing sub-tasks per post or per platform slot.

---

## Post Composer

The redesigned two-column composer for creating and scheduling social posts.

### Left Column — Image Preview
- Large asset preview that fills available space, rescales on resize
- **SFW/NSFW toggle** — switches between safe and explicit versions
- **Crop status** — shows whether the asset has platform-specific crops defined
- Censored preview toggle for platforms that require it

### Right Column — Content & Scheduling

**Strategy Section:**
- **Strategy Briefing** button — runs local data analysis (tags, posting history, content gaps, platform fit) and displays a structured brief
- **AI Strategy** button — sends project context to Claude CLI, which returns captions, timing recommendations, platform play, and hooks. Results append (don't replace existing notes). **Apply** button extracts structured data from the AI response into the post's caption, hashtags, and schedule fields.
- Markdown strategy notes with Edit/Preview toggle and theme-aware CSS rendering

**Caption & Hashtags:**
- Per-platform caption editing
- Hashtag suggestions from identity profile
- Dual-language support (Japanese + English) for Fanbox/Fantia/Ci-en

**Schedule:**
- Date/time picker with JST/EST/PST display
- Platform checkboxes in a flow layout (wrap when window narrows)
- Shows connected OneUp accounts (Twitter/X, Reddit) with greyed-out unconnected platforms

**Release Chains:**
- Define staggered cross-platform posting sequences (e.g., Twitter first, Patreon 48h later)
- Release step editor with per-step platform, delay, account, tier level, and locale
- Load from saved release templates

**Docking:**
- Toggle button to float the composer as a dialog or dock it into the Social tab
- Compact mode when docked, persists preference across sessions

---

## Notes Tab

The Notes tab provides a structured notepad for project documentation.

### Tab System
- **General** (permanent) — freeform project notes
- **Agent Primer** (permanent) — context document for Claude/AI interactions
- **Custom tabs** — add/remove named tabs for organizing notes by topic

### Markdown Preview
- **Edit/Preview toggle** — switch between raw markdown editing and rendered HTML
- Live markdown preview with theme-aware CSS
- Centered 1200px content column with scrollbar at the window edge
- Accent-colored horizontal rules (2px styled `<hr>`)

### Claude Actions
Right-click selected text to invoke Claude actions:
- **Refine** — polish and tighten the selected text
- **Expand** — elaborate on the selection with more detail
- **Research** — look up relevant context and add findings
- **Simplify** — reduce complexity and jargon
- **[Instruct]** — custom freeform instruction sent to Claude with the selection

---

## Subscription Platforms

Generalized quick-post workflow for 7 subscription/monetization platforms:

| Platform | Locale | Censor | Monetization |
|----------|--------|--------|--------------|
| Patreon | en | No | Subscription |
| Pixiv Fanbox | ja | Yes | Subscription |
| Fantia | ja | Yes | Subscription |
| Ci-en | ja | Yes | Subscription |
| Gumroad | en | No | Per-item |
| Ko-fi | en | No | Tips/Shop |
| SubscribeStar | en | No | Subscription |

### Quick-Post Flow
1. Select an asset and open the quick-post dialog
2. Choose the target platform
3. Caption is copied to clipboard (dual-language for Japanese platforms)
4. Image is exported with appropriate overlays and censoring applied
5. Platform's post URL opens in the browser
6. Paste caption, attach exported image, publish

### Tier-Based Content
Each platform supports free preview vs paid full version. The tier level is set per release step in a release chain.

---

## Campaign System

Campaigns represent major launches (Kickstarter, Steam, merch drops) with milestone tracking.

### Campaign Data
- **Name, type** (kickstarter/steam/merch/other), **status** (planning/preparing/live/completed)
- **Launch date** and **end date**
- **Campaign milestones** — named checkpoints with target dates and completion status

### Integration
- Platform assignments can be linked to a campaign via `campaign_id`
- Social posts can be linked to a campaign for coordinated promotion
- Blackout periods prevent scheduling conflicting content during campaign exclusivity windows

---

## Cross-Project Awareness

DoxyEdit can detect scheduling conflicts across multiple projects.

### Project Registry
A global registry at `~/.doxyedit/project_registry.json` tracks all known DoxyEdit projects on the machine.

### Conflict Detection
When scheduling a post, DoxyEdit performs a lightweight JSON peek into other registered projects (reads only post data, skips assets for performance) and warns about:
- **Same-day conflicts** — another project posting to the same platform on the same day
- **Blackout periods** — the target date falls within another project's campaign exclusivity window
- **Saturation warnings** — too many posts across projects in a short timeframe

---

## CLI Commands

For integration with Claude CLI or scripts:

```bash
python -m doxyedit summary project.doxyproj.json     # JSON status overview
python -m doxyedit tags project.doxyproj.json         # List all assets and tags
python -m doxyedit untagged project.doxyproj.json     # List untagged assets
python -m doxyedit status project.doxyproj.json       # Platform slot assignments
python -m doxyedit reminders project.doxyproj.json    # Check due release chain steps and Patreon cadence
python -m doxyedit patreon-prep project.doxyproj.json # Export image + copy caption for Patreon quick-post
python -m doxyedit plan-posts project.doxyproj.json   # Generate full briefing for Claude to plan posting strategy
python -m doxyedit flatten project.doxyproj.json      # PSD flattening + crop extraction
python -m doxyedit watermark project.doxyproj.json    # Apply watermark overlays to exported images
```

---

## Themes

**View > Theme** — 7 built-in themes:

| Theme | Style |
|-------|-------|
| Soot | Cool dark purple (default) |
| Vinik 24 | Dark purple/teal |
| Warm Charcoal | Warm dark tones |
| Bone | Light warm beige |
| Milk Glass | Light cool grey |
| Forest | Dark green |
| Dark | Classic IDE dark |

Windows title bar color matches the active theme. Theme persists across sessions. Scrollbar handles use the theme accent color and highlight on hover.

---

## Thumbnail Cache

Thumbnails are cached to `~/.doxyedit/thumbcache/` as PNGs and reused across sessions.

**Cross-project cache sharing:** A shared `content_index.db` (SQLite) at the base cache directory maps cache keys to PNG paths. When you open a new project containing files already cached by another project, the thumbnails are reused instantly — no re-generation needed.

**Per-project dims index:** Stored in `cache.db` (SQLite, WAL mode) alongside each project's cache. Old `index.json` files auto-migrate on first run.

**Fast Cache Mode** (Tools menu): stores thumbnails as uncompressed BMP files instead of PNG for faster reads, at the cost of more disk space. Useful for very large projects on slow drives.

See [Tools Menu](#tools-menu) for all cache-related commands.

---

## Health Panel

Accessible via **Tools > Remove Missing Files** or the Remove Missing button in the Health panel.

- **Remove Missing**: scans all assets and removes any whose source file no longer exists on disk. Shows a confirmation dialog listing how many will be removed before proceeding.

---

## Tools Menu

| Item | Description |
|------|-------------|
| Cache All | Pre-generate all thumbnails for the current project |
| Fast Cache Mode | Toggle BMP vs PNG thumbnail storage |
| Clear Cache | Delete all cached thumbnails for the current project |
| Set Cache Location | Move cache to a custom directory |
| Open Cache | Open cache folder in Explorer |
| Remove Missing Files | Scan and remove assets whose files no longer exist |
| Find Similar Images | Perceptual hash scan — finds visually duplicate or near-duplicate images in the project. Results show thumbnail pairs with a similarity score. |
| Edit Project Config | Opens the project's YAML config file in a built-in editor. Allows tweaking platform definitions, tag rules, and other project-level settings without hand-editing JSON. |

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
