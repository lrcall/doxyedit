# DoxyEdit Changelog

## v2.4 (2026-04-21) — Studio v2, Export Pipeline, threading, architecture

### Studio v2 — closer to a real graphics program
- **Complete undo for slider + font + color mutations** — opacity,
  scale, rotation, outline, kerning, line height, text width, font
  family, font size, bold/italic, text color, outline color. Plus
  Z-order (Bring Forward / Send Backward) and platform scope changes
  via the right-click menu. Consecutive ticks fuse into one undo step
  via merge-by-(target, attr).
- **Lock/unlock layer** — checkbox in Layer Properties panel makes
  an overlay non-selectable, non-movable. Useful for background
  watermarks. Undoable. Persists to CanvasOverlay.locked.
- **Keyboard shortcuts**: Ctrl+A (select all), Ctrl+Shift+H/V (flip),
  Ctrl+]/[ (bring forward / send backward).
- **Layer panel drag-reorder** — dragging a row rewrites asset.overlays
  and asset.censors, re-assigns Z-values. Band separation preserved
  (censors stay below overlays).
- **Smart snap guides** — dragging an overlay/censor/crop/note shows
  dashed magenta guides when edges align with other items or the
  canvas center. 5px snap threshold.
- **Ctrl+C / Ctrl+V on scene items** — serializes overlays + censors
  to clipboard JSON under a custom MIME type. Paste offsets 20px.
- **Alignment + distribute** — new toolbar "Align ▾" dropdown:
  align left/right/top/bottom, center H/V, distribute H/V. Works on
  any mix of selected item types.
- **Rotate handle on censors** — small blue handle 20px above the top
  edge; drag to rotate. Persists to CensorRegion.rotation (new field).
- **Flip Horizontal / Flip Vertical** — right-click overlay. Persists
  to CanvasOverlay.flip_h/flip_v (new fields); exporter applies via
  PIL transpose before compositing.
- **Layer properties panel** — below the layer list. Selected layer's
  opacity slider + enabled checkbox update via undo-wrapped commands.
- **Arrow-key nudge** now covers crops and notes too (previously only
  censors + overlays).

### Architecture
- **SaveLoadMixin** (`doxyedit/project_io.py`) — extracts
  `_watch_project`, `_save_project_silently`, `_autosave`,
  `_autosave_collection` out of window.py. First stage of a staged
  god-object decomposition; follow-ups will move interactive save/
  load paths once their dialog dependencies are cleaned.

### Quality-of-life polish (autonomous batch)
- **Folder Scan respects import method** — individual file drops are
  tagged `type='file'` in import_sources. Folder Scan only walks
  `type='folder'` entries, so dropping 7 files from a folder of 100
  won't suck in the other 93 on the next auto-scan. Per-folder
  recursive flag preserved.
- **OneUp prints → logging** — 33 `print("[Sync] ...")` calls moved
  to `logging.info/warning/error`. Visible in `~/.doxyedit/doxyedit.log`
  instead of swallowed by the Nuitka `--windows-console-mode=disable`
  build.
- **imagehost upload cache LRU** — `_upload_cache` now bounded at 512
  entries.
- **Autosave interval configurable** via
  `QSettings("autosave_interval_ms")` (5s-10min clamp).
- **Studio v2 polish**:
  - Lock icon (🔒) prefix on locked layers in the layer list.
  - Reset Transform context menu entry (clears rotation + flip).
  - Keyboard-shortcut hints in context menus: `Duplicate (Ctrl+D)`,
    `Flip Horizontal (Ctrl+Shift+H)`, `Bring Forward (Ctrl+])`, etc.
  - Censor context menu reaches parity with overlays (Duplicate +
    Bring Forward / Send Backward).
  - Flip + Reset Transform on text overlays (was image-only).
  - Censor style and platform changes are now undoable.
  - Align button tooltip explains selection requirements.
- **docs/config-layering.md** — new contributor doc covering the four
  config sources (models defaults, config.json, config.yaml,
  per-project JSON, QSettings) with a precedence table and a
  decision tree.
- **progress_label** styling moved from inline setStyleSheet to theme
  QSS selector.



### Studio Export Pipeline (original v2.4 focus)
- **Escape in Studio now works**. Deleted app-level event filter and four
  redundant handlers; single mousePressEvent commits any focused text item.
- **CropRegion gains platform_id + slot_name** as first-class fields.
  Pipeline prefers exact platform_id match over label substring. Legacy
  projects keep working via fallback (now logs a warning on ambiguity).
- **Export All** per-crop overlay/censor scoping uses platform_id instead
  of the brittle substring match that could mix "twitter" with "twitter_header".
- **Export Platform** respects the crop combo selection (already wired;
  H3.1 made slot_name authoritative).
- **Identity Import/Export** — File → Import/Export → Identity. JSON
  round-trip. Import does NOT regenerate captions (CLAUDE.md rule).

### Threading — UI stays responsive during I/O
- **Splash screen** with Cancel Load / Quit buttons. Window paints before
  autoload. Splash reads saved theme from QSettings.
- **Project load off UI thread** — ProjectLoader QThread. Startup
  autoload, File→Open, Recent, drag-drop, collection restore, Reload (F5)
  all non-blocking.
- **Find Duplicates / Find Similar** off UI thread with cancellable progress.
- **Stats Disk Size** computed off UI thread, cached per asset-count.
- **Cross-project schedule peek** parallelized across projects.
- **OneUp sync fetch phase** off UI thread — duplicate-warning dialog stays
  on UI thread.
- **Auto-Post Playwright batch** off UI thread with real cancel button.
- **File watcher suppression** — `_save_project_silently()` replaces
  fragile `_own_save_pending` counter.

### Perf
- **Lazy panel refresh** — StatsPanel, HealthPanel, ChecklistPanel,
  PlatformPanel, GanttPanel, TimelineStream, CalendarPane migrated to
  LazyRefreshMixin. Tab swap no longer rebuilds 14 panels.
- **Notes tabs** deferred to Notes tab activation; theme change re-renders
  only the active preview.
- **Export cache** — per-batch PSD decode + censor/overlay memoization.
  5-platform post on a 100MB PSD drops from ~20s to ~4s.
- **Splitter non-opaque resize** — dragging the tray handle no longer
  re-lays out the 70k-asset grid on every pixel.
- **Preview cache eviction** — `~/.doxyedit/preview_cache/` prunes files
  older than 30 days, caps total at 2 GB.
- **Browser scaled-cache** gets LRU with 2048-entry cap.
- **Filebrowser** recursive folder counts O(K²) → O(K·depth) via parent-chain propagation.
- **Folder compact/expand** asset-path repair: one rglob instead of per-asset.
- **Health panel** shared rename-index replaces per-asset recursive scans.
- **autosave_collection** skip-when-unchanged.
- **UI font size cached** — replaces 31 per-render QSettings reads with one
  module-level cache invalidated on Ctrl+=/-/0.
- **File→Open async** — project file dialog no longer freezes on large
  projects; ProjectLoader QThread handles the hydrate, UI updates on
  loader signal.
- **New-window show() deferred** until the async load fires, removing the
  empty-frame flash on collection open and tab detach.

### New format / project file
- **`.doxy`** (projects) and **`.doxycol`** (collections) as default save
  extensions. Legacy `.doxyproj.json` / `.doxycoll.json` still load; user
  picks format in save dialog.
- **formats.py** helper module for extension checks.

### Bug fixes
- **Tag colors** — tag bar and InfoPanel pills were silently grey because
  projects saved empty `color` fields. Placeholder colors now promote to
  VINIK cycle.
- **Multi-window TAG_SHORTCUTS** no longer stomps other open windows.
- **GDI handle leak** in `get_shell_thumbnail` on exception paths.
- **asyncio loop leak** in `post_to_platform_sync` on exception paths.
- **platforms.py** drop-event NameError on non-asset files.
- **Export dropped** all but the first asset (`post.asset_ids[:1]`).
- **Duplicate `_rebuild_per_platform_captions`** call in composer_right.
- **Composer cross-project identities** — ContentPanel accepts
  `extra_projects` to reuse identities across related projects.
- **New-window flash** — windows created for collection open / tab detach
  now `show()` only after async load fires, instead of flashing an empty
  tiny frame at center-screen.

### Architecture / code hygiene
- **Dead modules deleted** (-1300 lines): `canvas.py`, `censor.py`,
  `kanban.py`, `overlay_editor.py`, `project.py`.
- **session.py** extracted — AsyncLoadHandle + ProjectLoader.
- **export_cache.py** new module.
- **panel_mixin.py** new module with LazyRefreshMixin.
- **MCP helpers extracted** — `oneup.mcp_init_session()` +
  `mcp_tool_call()` replace three duplicated init/call blocks.
- **Hoisted hot-path imports** — theme tokens in preview.py, markdown in
  window.py.
- **OneUp sync debug prints** converted to `logging` where useful.
- **formats.py** + helpers consolidate `.doxy` / `.doxyproj.json` /
  `.doxycol` / `.doxycoll.json` checks.

### UI polish
- **Themed splash** reads active theme from QSettings.
- **Shortcuts dialog** generated from QAction registry (no more drift).
- **What's New** reads `docs/CHANGELOG.md` (this file).
- **Tab bar + "new tab" button** styling moved from inline stylesheets
  to theme QSS.
- **Tab breakout** — right-click a project tab → Open in New Window.
- **StatsPanel** folder bar color from theme instead of hardcoded.
- **Posting state audit** — `docs/state-machine-posts.md` documents the
  post lifecycle and double-post guards. No bugs found.

## v2.3.1 (2026-04-16) — Asset Groups, Tokenization & Platform Rework

### Asset Groups: Duplicates & Variants
- **Link Mode** toggle on browser toolbar — click an asset to highlight its group
- **Corner dots** — red (top-right) for duplicate groups, teal (top-left) for variant sets
- **4 creation paths** — duplicate scanner (MD5), similar scanner (perceptual hash), manual linking (right-click), filename stem auto-detect (Tools menu)
- **Right-click management** — Select All, Mark as Keeper, Add to Set, Remove, Dissolve
- **Progress dialogs** on duplicate and similar scanners (cancellable)

### Rich Copy/Paste
- **Ctrl+C/V across project tabs** carries full asset metadata (tags, crops, censors, overlays, notes)
- Plain paste from Explorer still works as file import

### Platform Panel Rework
- **3-pane splitter** — sidebar (campaign/filter/export) | cards (scrollable) | dashboard (flow-wrapping)
- **Campaign management** — edit name/status/launch date, delete with confirmation
- **Campaign selection persists** across sessions
- **Dashboard cells** wrap to new rows via FlowLayout, request thumbnails from cache

### Performance
- **Lazy censor editor** — only loads full PSD when censor tab is active
- **Deferred rebind** — file watchers, notes rendering, cross-project cache after UI paints
- **Shared thumb cache** keeps in-memory pixmaps on project switch (same folder = no clear)
- **Tab switch** — removed double theme apply + double browser refresh
- **Social tab** auto-refreshes every 60s (timeline + gantt "today" markers)
- **Grid size** synced on font_size change (was stale from init)

### UI/Layout
- **Vertical screen support** — window narrows to ~400px (QTabWidget minSizeHint override, status bar SizePolicy.Ignored, all splitters collapsible)
- **Grid cells** — tokenized height, tighter ratios (DIMS 1.0, NAME 1.2), proper top padding
- **Fill Thumbnails** persists across sessions
- **Files/Tags/Tray** button states saved/restored correctly on startup
- **Notes tabs** don't leak across projects on tab switch
- **Project tab** right-click: Rename Tab + Close Tab
- **Info panel** — bg_raised background + accent_bright section headers for light theme contrast
- **Quick Tag** — shows used/custom tags flat at top, unused presets in "More Tags"
- **Styled QInputDialog** — tag dialogs inherit app theme on Windows
- **Drag-drop** .doxyproj.json and .doxycoll.json onto window to load

### Whole-Codebase Tokenization
- **125+ violations fixed** across ~20 files → 0 remaining
- 20 alpha fields added to Theme dataclass
- All setAlpha, setSpacing, setContentsMargins, setFixed*, QPen, setPointSize, setStyleSheet values tokenized
- Named constants for all max() minimums, ratios at class/module level
- **scripts/check_theme_contrast.py** — WCAG contrast validator
- **/check-contrast** skill created for any project
- **All 13 themes** pass WCAG contrast (AAA primary, AA secondary, AA muted)

### Theme Contrast Fixes
- Darkened text on all light themes (Bone, Milk Glass, Dawn, Citrus, Candy)
- Lightened text on all dark themes (Vinik24, Soot, Dark, Neon, Ember, Midnight, Forest)
- Adjusted accent/statusbar colors where text_on_accent failed

---

## v2.3.0 (2026-04-14) — Social Media Suite Expansion

### New Tabs & Panels
- **Studio Tab** — Canvas and Censor tabs merged into unified "Studio" tab. Layered scene: base image (Z=0), censors (Z=100+), overlays (Z=200+), annotations (Z=300+). Single toolbar with censor draw, overlay watermark/text/template, and annotation tools. Drag-drop from tray to load assets. Rich text editing: font family, size, bold, italic, color picker, kerning, rotation. Watermark templates for batch application. Annotations are ephemeral (not saved); censors and overlays persist.
- **Engagement Follow-Up System** — Auto-generates 5 timed check windows per platform after posting (+15m, +1h, +4h, +24h, +48h). EngagementPanel at top of timeline with Open/Done/Snooze buttons for each check window. Test button in Tools menu for dry-run testing.
- **Gantt Chart** — Visual timeline in Social tab showing all posts as colored bars, stagger connection lines, gap detection, today marker. Zoom slider + date range picker. Click bar to edit post.
- **Tabbed Notes** — General + Agent Primer (permanent) + custom tabs. Live markdown preview with Edit/Preview toggle. Right-click Claude actions (Refine, Expand, Research, Simplify, [Instruct]).

### Social Media Pipeline
- **Strategy Briefing** — Local data analysis (tags, history, gaps, platform fit) + AI Strategy via Claude CLI with full project context
- **AI Strategy** — Claude analyzes posting context, returns captions, timing, platform play, hooks. Append mode (doesn't replace). Apply button extracts structured data into post fields.
- **Calendar Pane** — Month grid with colored status dots, JST/EST/PST clock, day click filters timeline
- **Release Chains** — Staggered cross-platform posting (e.g., Twitter first, Patreon 48h later). Release step editor in composer with template loading.
- **Multi-Identity** — Multiple brand identities per project with voice, hashtags, Patreon schedules. Identity selector in composer.
- **Reminder Engine** — Scans release chains + Patreon cadence for due actions. QTimer checks every 5 minutes, status bar alerts.
- **Patreon Quick-Post** — Copies caption, exports image with overlays/censors, opens Patreon post URL in browser.

### Manual Social Platforms
- **Third platform section** for track-only platforms: Bluesky, Pixiv, Instagram, TikTok, Tumblr, Threads, Mastodon, Newgrounds
- Manual platforms appear in composer for caption/scheduling but require manual posting (no API push)
- Status tracking (draft/posted/skipped) works the same as automated platforms

### Subscription Platform Automation
- **7 platforms**: Patreon, Pixiv Fanbox, Fantia, Ci-en, Gumroad, Ko-fi, SubscribeStar
- **Quick-post module** — Generalized clipboard + export + browser launch for all platforms
- **Tier-based content** — Free preview vs paid full version per platform
- **Dual-language** — Japanese + English captions for Fanbox/Fantia/Ci-en
- **SubPlatform registry** with locale, censor flags, URL templates

### Cross-Project Awareness
- **Project registry** at ~/.doxyedit/project_registry.json
- **Lightweight JSON peek** — Reads only posts from other projects (skips assets)
- **Conflict detection** — Same day, same platform, blackout periods, saturation warnings
- **Blackout periods** — Campaign exclusivity windows

### Campaign System
- **Campaign + CampaignMilestone** data models for Kickstarter, Steam, merch launches
- **campaign_id** on PlatformAssignment and SocialPost for linking
- Launch dates, end dates, status tracking (planning/preparing/live/completed)
- **Campaign UI in Platforms tab** — selector, CRUD dialog, milestone checklist
- Filter platform cards by campaign_id
- Campaign spans and milestone markers on Gantt chart (planned)

### Composer Redesign
- **Two-column layout** — Left: image preview + SFW/NSFW toggle + crop status. Right: strategy + captions + schedule.
- **Schedule picker on left panel** — Moved to top of composer left side with EST/PST/JST world clock display, scroll wheel disabled to prevent accidental changes
- **Per-platform captions** — Caption fields only appear for checked/enabled platforms, fields rebuild dynamically on toggle
- **Dockable composer** — Float as dialog or dock into Social tab with compact mode. Toggle button persists preference.
- **Connected platforms** — Shows actual OneUp accounts (8 Twitter/X + Reddit), greyed-out unconnected platforms
- **Image preview** — Large preview fills available space, rescales on resize, censored toggle
- **Platform flow layout** — Checkboxes wrap when window narrows
- **Markdown strategy notes** — Rendered HTML with Edit/Preview toggle, theme-aware CSS

### Canvas Overlays
- **CanvasOverlay data model** — Watermark, text, logo overlays per asset
- **Export pipeline** — apply_overlays() composites during export (not on source)
- **Shared compositing** — CLI watermark command and GUI export use same pipeline

### OneUp Integration Fixes
- **Category ID fix** — Was using wrong ID (49839), now uses correct (86698=Doxy, 176197=Onta, etc.)
- **Account sync from MCP** — Fetches connected accounts directly from OneUp MCP server
- **Category-based accounts** — Config supports categories with per-category account lists
- **Push posts via MCP** — REST API was broken; switched to MCP for post pushing
- **Sync by content fingerprint** — Matches by 40-char content fingerprint, not post ID
- **5-minute protection** — Recently-pushed posts protected from duplicate pushes
- **Queue to OneUp button** — Now pushes directly from GUI
- **Subscription platforms filtered** — Subscription platforms use quick-post, filtered from OneUp push

### Platforms Tab Upgrade
- **Kanban removed** — replaced with full-width platform cards for cleaner layout
- **Hive click bug fixed** — platform card clicks now register correctly
- **Assignment notes** — PlatformAssignment.notes shown as tooltip on cards + Edit Note context menu
- **Campaign filtering** — campaign selector properly filters platform cards

### Tray Multi-Select
- **Ctrl+Click / Shift+Click** in tray for multi-selection
- **Group actions on right-click** — Copy All Paths, Quick Tag all, Send to Tray all, Remove all
- **Quick Tag shows user tags only** — filters out built-in presets

### Tray Right-Click Parity with Browser
- **Open in Studio** — load tray asset into Studio tab
- **Star/Unstar** — toggle star directly from tray context menu
- **Open in Native Editor** — launch associated app for the file type
- **Tags submenu** — shows applied tags, click to remove

### Composer Preview Modes
- **Raw / Studio / Platform** toggle buttons above image preview in composer
- Raw shows the unmodified source, Studio shows with overlays/censors, Platform shows final export crop

### Studio Fixes
- **Props row always visible** — no layout shift when toggling tools
- **Font size + text width as sliders** — replaces fixed increment buttons
- **Rotation from center of mass** — text/overlay rotation pivots correctly
- **Drag-drop from tray** — drag assets from tray into Studio scene

### Engagement Panel Fix
- **Properly embedded in timeline** — was floating as unparented window, now docked correctly

### Identity Editor Rebuild
- **5 tabs**: Profile, Platforms, Credentials, Chrome, Posting
- **Chrome profile launcher** — per-account Chrome profiles for multi-identity browser sessions

### CensorRegion Tolerance
- **Unknown fields tolerated** — CensorRegion no longer crashes on unexpected keys (e.g. blur_radius from newer project files)

### Bug Fixes
- **campaign_id preserved on composer save** — was silently dropped
- **Notes custom tabs persist** across restarts
- **Notes tab switch guard** — prevents stale content when switching tabs rapidly
- **Notes preview re-renders on theme change**
- **Identity manager dialog restored** — duplicate stub removed
- **Per-platform captions** only show for checked platforms
- **PST added to timeline** time display
- **Context menu text** explicitly colored for readability
- **Overlay editor tab removed** — absorbed into Studio
- **Notes left padding** — 100px left padding on markdown editor for readability

### UI & Theming
- **Tokenized scrollbars** — Single global rule with track/handle/hover tokens
- **Social post badges** — D/Q/P/! badges on thumbnails for draft/queued/posted/failed
- **Themed context menus** — Right-click menus match theme on Windows
- **Themed progress dialogs** — Claude progress spinner uses theme colors + DWM title bar
- **JST clock** — Calendar pane + schedule picker show JST alongside EST/PST
- **Centered notes editor** — 1200px content column with scrollbar at window edge
- **Styled horizontal rules** — Accent-colored 2px rules in markdown
- **Full QColor tokenization** — 12 hardcoded color violations fixed across codebase

### Data Model Additions
- `CanvasOverlay` — type, image_path, text, font, color, opacity, position, scale
- `ReleaseStep` — platform, delay_hours, account_id, status, tier_level, locale
- `SubPlatform` — id, name, locale, post_url_template, needs_censor, monetization_type
- `Campaign` + `CampaignMilestone` — launch planning with milestones
- `SocialPost` gains: release_chain, nsfw_platforms, sfw_asset_ids, tier_assets, sub_platform_status, campaign_id
- `CollectionIdentity` gains: fanbox_url, fantia_url, cien_url, kofi_url, voice_ja, hashtags_ja
- `Project` gains: sub_notes, default_overlays, release_templates, identities, blackout_periods, campaigns

### New Files
- `doxyedit/strategy.py` — Strategy briefing generator (local + AI)
- `doxyedit/calendar_pane.py` — Month calendar widget
- `doxyedit/gantt.py` — Gantt chart with QGraphicsScene
- `doxyedit/composer_left.py` — Image preview panel
- `doxyedit/composer_right.py` — Content panel (strategy, captions, schedule)
- `doxyedit/reminders.py` — Release chain + Patreon cadence reminders
- `doxyedit/quickpost.py` — Generalized quick-post for subscription platforms
- `doxyedit/crossproject.py` — Cross-project registry + conflict detection
- `doxyedit/overlay_editor.py` — Overlay tools (absorbed into Studio tab)

## v2.2.0 — 2026-04-09

### New Panels
- File Browser (Ctrl+B): folder tree with asset counts, search, pinned folders, drag-to-import
- Info Panel (Ctrl+I): asset metadata with editable tag pills, inline notes, color palette swatches
- Kanban board: 4 status columns (Pending/Ready/Posted/Skip) embedded in Platforms tab

### New Features
- Smart Folders: save/load filter presets (View > Smart Folders)
- Find Similar Images: perceptual hash grouping (Tools menu)
- YAML config: custom platform definitions via config.yaml (Tools > Edit Project Config)
- Preview pop-out button: float docked preview into full dialog
- Resizable crop handles: 8 drag handles on crop regions, persistent overlays
- Grouped crop presets: dropdown organized by platform with section headers
- Color palette extraction: 5 dominant colors computed during thumbnail generation
- What's New dialog in Help menu
- Collection reload with missing-file warnings (File > Reload Collection)

### Bug Fixes
- Preview remembers position correctly across monitors (screen validation)
- Tray drag-drop works from normal view (was only pre-selected items)
- Collections warn on missing projects instead of silently dropping them
- Folder filter paths normalized for Windows backslash compatibility
- Folder view sections capped to viewport height with internal scroll

### UI & Performance
- Toolbar declutter: Recursive, Hover Preview, Cache All, Folder Scan moved to View/Tools menus
- Folder view overlap fix: heightForWidth on FolderSection
- Theme migration: all new panels use centralized generate_stylesheet()
- Nuitka build: 11 new exclusions for smaller output
- Tray: O(1) asset lookup with id-to-row index mapping
- Pre-computed recursive folder counts in file browser (O(1) paint)
- Removed hardcoded QFont calls — inherits from theme stylesheet

### Infrastructure
- Focus stopwatch mode for plan tracking (count-up timer + claudelog)
- DOXYEDIT_UI_SPEC.md design system documentation
- UI Rules section added to CLAUDE.md

## v1.9.0 — 2026-04-06

### Preview Window (Major Overhaul)
- Single preview window: opening preview when one is already open reuses and updates it instead of spawning a second
- Minimize/maximize/restore buttons on preview window
- Preview window fully themed: title bar color via DWM, full stylesheet applied
- Image centered on load and on every navigation
- Free overpan: scene rect has a large margin so you can pan past image edges
- Space, Tab, Down arrow = next image; Backspace, Up arrow, Left arrow = previous image
- Keys always navigate regardless of which button has focus
- Add Note / View Notes buttons are non-focusable so they never steal Space key
- View Notes defaults to off on open
- Enter key opens preview for selected thumbnail
- Thumbnail selection syncs with preview navigation in both flat and folder views (uses ClearAndSelect so highlight is always visible)

### Thumbnail Navigation
- Up/Down arrow keys in the thumbnail view navigate images and sync thumbnail selection
- Arrow key navigation auto-scrolls to keep the selected thumbnail visible (EnsureVisible)
- Fixed: navigating via arrows in preview no longer causes browser scroll-jump on click (jump_to no longer emits navigated signal)

### Thumbnail Cache
- Cross-project cache sharing: `content_index.db` (SQLite) stored at the base cache dir maps cache keys to PNG paths across all projects — new projects automatically reuse already-cached thumbnails from other projects
- Per-project dimension index moved from `index.json` to `cache.db` (SQLite, WAL mode); old `index.json` files auto-migrate on first run
- Fast Cache Mode (Tools menu): stores thumbnails as uncompressed BMP for faster reads at the cost of disk space
- Fixed re-entrant call crash when Cache All completes and the user immediately hits cache again

### Theming
- Scrollbar handles use the accent color (bright on hover)
- Default theme changed from Vinik 24 to Soot

### Folder View
- Section headers indent 3 spaces per depth level relative to the shallowest folder in the current view

### Health Panel
- "Remove Missing" button: removes all assets whose source file no longer exists, with confirmation dialog
- Connected to Tools > Remove Missing Files menu action

### Import
- Paste Folder (File menu): imports a folder path from clipboard

## v1.5.1 — 2026-04-05

### Hover Preview
- Shows full original resolution (e.g. "2475 x 3375px") below preview image
- Shows full file path below resolution
- Larger info text (12px) for readability

### UX Improvements
- Ctrl+Shift+C copies full file path of selected asset(s) to clipboard
- Splitter handles widened by 5px for easier grabbing (tag panel + tray)

## v1.5.0 — 2026-04-05

### UI Overhaul
- Left toolbar removed — Tags and Tray toggle buttons moved to browser toolbar
- Browser toolbar uses FlowLayout — buttons wrap on narrow windows
- Tag bar now shows custom/project tags only (built-in presets removed)
- Count label (shown/starred/tagged) moved to status bar
- Tags + Tray buttons positioned first in toolbar, side by side

### Sort by Folder
- New "By Folder" sort mode groups assets by source folder
- Folder labels shown on first item of each group (last 2 path components)
- Collapse All / Expand All buttons appear in By Folder mode
- Collapsed folders persist during session

### Drag & Drop
- Tray items can be dragged out to external apps (Photoshop, Explorer, etc.)
- Multi-select drag supported — select multiple items then drag
- Uses QDrag with file URL mime data

### Design System Fixes
- Button styles unified — all _btn_style methods now include font-size
- Theme.btn_style() shared method added for future use
- TagPanel scales fonts with Ctrl+=/- (was frozen at hardcoded sizes)
- Custom tag colors in side panel now read from tag_definitions
- Tag search is case-insensitive (works with preserved-case tags)
- Ctrl+Click tag search: text set before mode toggle for reliable filtering

### Asset File Watcher
- Source image changes detected automatically via QFileSystemWatcher
- Thumbnails regenerate when files are modified on disk
- ThumbCache.invalidate() method for clearing individual entries

### Bug Fixes
- Clear Unused Tags added to Tools menu
- Auto-tag defaults to off
- Fixed NAME_ROLE self-reference crash in tray
- Fixed _cb → checkbox AttributeError in tag panel font scaling

## v1.4.0 — 2026-04-05

### Tag Definitions & Aliases
- New `tag_definitions` dict in project JSON — maps tag IDs to display properties (label, color, group)
- New `tag_aliases` for backward-compat rename resolution (old → canonical ID auto-resolved on load)
- Legacy `custom_tags` list auto-migrated to `tag_definitions` on save
- Renaming a tag creates an alias so old references resolve automatically
- `TagPreset.from_dict()` class method eliminates repeated construction

### Asset Specs vs Notes
- New `specs` dict field on Asset for CLI/tool metadata (size, palette, relations)
- Auto-migrates CLI-generated notes (e.g. "2356x3333 | palette:...") into `specs.cli_info` on load
- Notes panel now only shows human-written notes

### Project Management
- Edit > Move to Another Project — pick existing .doxyproj.json, transfer selected assets
- Edit > Move to New Project — create new .doxyproj.json from selection with Save dialog
- F5 reloads project from disk (picks up external edits from Claude CLI)
- Shift+F5 for thumbnail recache

### Work Tray Overhaul
- Tray fully hides when closed (no more lingering 16px strip)
- Remembers width when toggling with Ctrl+T
- Column view modes: ☰ button cycles list → 2-col grid → 3-col grid (icon-only, clean layout)
- ✕ close button in header
- Quick Tag submenu in tray right-click context menu
- Tray thumbnails preserved on project reload

### Context Menu Improvements
- Tags submenu shows union of ALL selected assets' tags (not just clicked asset)
- Click tag in submenu removes it from all selected (with − prefix and display labels)
- Quick Tag submenu with ✓ marks, splits into columns when >10 tags
- Copy Filename added alongside Copy Path
- Selection preserved when using any context menu action

### More Shortcuts & Filters
- Escape — deselect all
- Alt+A — add tag to selected
- Ctrl+H — temporary hide/restore
- Ctrl+F — focus search box
- Shift+E — notes overlay popup
- Ctrl+Click tag bar → search by tag (was Alt+Click)
- "Has Notes" filter checkbox on search bar
- "Select all with tag" in tag panel right-click

### Code Quality (simplify round)
- NAME_ROLE constant replaces magic UserRole+1
- Dead _collapsed state and _toggle_collapse removed from tray
- _remove_assets_by_ids helper deduplicates move methods
- blockSignals during selection restore (avoids N redundant emissions)
- hasattr guards removed (proper __init__ instead)
- import re moved to module level

### Checklist: 22 items completed, 13 remaining (all medium-to-large features)

## v1.3.0 — 2026-04-05

### Tag System Improvements
- Both tag locations (top bar + side panel) now refresh on every tag-modifying event
- Custom tags sorted alphabetically in side panel
- Collapsible tag sections — click section header (▼/▶) to collapse/expand
- First tag section labeled "Default"
- Tags preserve user's exact casing and spaces (no more forced lowercase/underscores)
- "Select all with tag" in tag panel right-click menu
- Quick Tag multi-column submenu in browser right-click (✓ marks, splits at 10)
- Tray Quick Tag — right-click tray items to tag them directly
- Auto-tag toggle in Tools menu (guards filename + visual auto-tagging)

### New Shortcuts & Controls
- Escape — deselect all
- Alt+A — add tag to selected assets
- Ctrl+H — temporary hide selected (Ctrl+H again with nothing selected restores all)
- Ctrl+F — focus search box
- Ctrl+Click tag bar button — search by tag (was Alt+Click)
- F5 — reload project from disk (picks up external edits from Claude CLI)
- Shift+F5 — refresh thumbnails

### View Menu Additions
- Show Resolution toggle (per-thumbnail dimensions on/off)
- Show Tag Bar toggle (hide/show top tag buttons)
- Show Hidden Only filter (invert eye filter to see hidden items)
- Hover Preview Delay setting (200-1200ms, persisted)
- "Has Notes" filter checkbox on search bar

### UI & UX Fixes
- Thumbnail filename text now scales with Ctrl+=/- (was hardcoded)
- Menu font hover no longer mismatches in some themes
- Notes area splitter size persists across sessions
- Canvas tools (Select/Text/Line/Box/Marker/Color) hidden when not on Canvas tab
- Tray collapse button closes the entire tray (not just content)
- Hover preview hides before re-triggering delay when moving between thumbnails
- Middle-click drag properly updates preview without interfering with hover timer
- Clear All Tags now refreshes the browser grid
- Copy Filename added to browser right-click menu
- Filter button tooltips (Starred/Untagged/Tagged)

### Checklist Progress
- 17 items completed from TODO.md (7 high, 6 medium, 4 low priority)
- Added future items: rebuild tag bar from JSON, move assets between projects, drag-drop tag groups

## v1.2.0 — 2026-04-05

### Claude CLI Integration
- 8 new CLI commands: search, starred, ignored, notes, add-tag, remove-tag, set-star, export-json
- Auto-reload: DoxyEdit watches the project JSON and reloads when Claude CLI modifies it
- Full bidirectional sync — Claude edits JSON, DoxyEdit updates live

### Simplify Round 5
- Removed duplicate auto_suggest_tags (dead code)
- LRU eviction for delegate scaled pixmap cache (500 max)
- get_asset uses dirty flag invalidation
- Tag color dots no longer reset on image click (fitness overwrite removed)

### Fixes
- Star clicking works via delegate hit detection
- Auto-hide images when tagged with eye-hidden tag
- Cache All hides progress bar when nothing to cache
- Ctrl+V handles multiple paths/files
- Tag panel dots show tag color permanently

## v1.1.0 — 2026-04-05

### Post-1.0 Fixes & Features
- Star clicking works again (delegate hit detection in star rect area)
- Auto-hide images when tagged with an eye-hidden tag
- Ctrl+V handles multiple paths/files, discards unsupported types
- Cache All hides progress bar when all already cached
- Tag dots show tag's own color (not fitness), labels bolded
- Eye button 120% larger (24px)
- Hint label hidden for cleaner UI
- Tray fully collapses to 16px handle
- Full menu bar: Edit (8 actions), Tools (7 actions), Help (2 actions)
- Project Summary compact dialog
- Comprehensive TODO.md tracking all implemented/pending features

## v1.0.0 — 2026-04-05

### v1.0 Release
- Work Tray — collapsible right panel with ◀/▶ handle, persists across all tabs
- Tray context menu: Preview, Copy Path/Filename, Open in Explorer, Move to Top/Bottom
- Progress bar for cache-all and long tasks
- Middle-click instant preview (works even with hover disabled)
- Ctrl+click multi-select tag rows for batch Hide/Show/Delete
- Ctrl+T toggles tray, Ctrl+L toggles tag panel
- Tray button in left toolbar
- Resizable notes area (vertical splitter)
- Tokenized design system (font, padding, radius scale together)
- Horizontal scrollbars themed
- 3px rounded corners on thumbnails
- Smooth pixel scrolling, zoom keeps focus on selected item
- Hover preview customizable size (125-300%)
- Thumbnail quality setting (128-1024px)
- Alt+click tag toggles search on/off
- Theme: Dark renamed to Grey
- 7 themes fully applied to all widgets including tray, splitters, progress bar
- Project backup (.bak) created on open
- Sort mode, eye-hidden tags, tray items all persist in project file

## v0.9.0 — 2026-04-05

### QListView Migration (Major Performance Upgrade)
- Replaced QGridLayout with 200+ widget instances with a single QListView
- Custom ThumbnailModel (QAbstractListModel) + ThumbnailDelegate (QStyledItemDelegate)
- **Smooth virtual scrolling** — no more paging, all images accessible by scrolling
- **Instant zoom** — Ctrl+scroll changes grid size without rebuilding
- **Zero widget overhead** — delegate paints directly, no widget creation/destruction
- Selection built-in: Ctrl+click, Shift+click, Ctrl+A all work natively
- ~230 lines removed (1103 → 872 lines)
- Scaled pixmap cache with proper Qt cacheKey

### Eye Toggle (Photoshop-style Layer Visibility)
- Each tag in the left panel has an 👁 eye button
- Click to hide all images with that tag from the grid
- Click again to show them
- Multiple eyes can be toggled independently
- Works like Photoshop layer visibility

### Fixes
- Repeating thumbnail images fixed (cache key collision)
- Removed paging system (no longer needed with virtual scrolling)
- Removed Thumbnails Per Page menu (replaced by smooth scroll)

## v0.6.1 — 2026-04-05

### Preview Annotations
- View Notes button (V key) toggles saved annotations visible/hidden
- Annotations load from asset.notes on preview open
- Large bold text with dark background for readability
- Font size matches UI setting

### Per-Project Persistence
- Custom tag shortcuts saved to .doxyproj.json
- Hidden tags saved to .doxyproj.json and restored on load
- Main window position/size restored across sessions

### Fixes
- Ctrl+S / Ctrl+O now work (removed duplicate shortcut conflict)
- Right-click Unstar sets to 0 (Cycle Star Color is separate option)
- Thumb size clamped on load (prevents zoom corruption)
- Note font matches UI font size setting

## v0.6.0 — 2026-04-05

### Performance
- Grid rebuild wrapped in setUpdatesEnabled (eliminates per-widget repaint flicker)
- Immediate widget cleanup with setParent(None) during page rebuild
- Tag changes no longer trigger full grid rebuild (instant tagging)
- "Cache All" checkbox pre-generates all thumbnails in background
- F5 force-recache for externally edited images
- PERFORMANCE.md documents QListView migration roadmap

### Selection & Navigation
- Ctrl+A selects all thumbnails on current page
- Left/Right arrow keys page through thumbnails

### Folder Import
- Asks "Import recursively?" when folder has subfolders
- Nuitka build script clears cache for fresh builds, includes psd_tools + numpy

### State Persistence
- Main window position and size saved/restored across sessions
- All settings persist: theme, font, zoom, page size, window geometry

### Fixes
- Thumbnail widget height increased to clear dimension/name overlap
- Regenerated clean single-size 256x256 ICO (was corrupted multi-size)
- Tag add shows status bar confirmation

## v0.5.0 — 2026-04-04

Major release consolidating all v0.3.x work.

### SAI/SAI2 Shell Thumbnails
- SAI and SAI2 files show real thumbnails via Windows Shell API (SaiThumbs)
- Unsupported formats show styled placeholder with extension label
- Shell thumbnail integration for CLIP, KRA, XCF when extensions installed

### Disk Thumbnail Cache
- Thumbnails cached as PNGs in `~/.doxyedit/thumbcache/`
- Keyed by file path + modification time — changed files auto-regenerate
- Reopening large projects loads near-instantly

### Preview Annotations
- Press N or "Add Note" to draw annotation boxes on images
- Type note text, saved to asset's notes field
- Delete key removes selected annotations

### Tag Panel — 4 Sections
- Content/Workflow (Page, Character, Sketch, etc.)
- Platform/Size targets (Hero, Banner, Cover, etc.)
- Custom/Project tags (user-added, project-specific)
- Visual/Mood/Dimension (warm, cool, dark, portrait, etc.)
- Tags insert into their correct section, no mixing

### Tag Management
- Right-click tag → Pin to top of own section (gold border)
- Right-click tag → Set Shortcut Key (any single key)
- Right-click tag → Rename across all assets
- Right-click tag → Delete from project
- Custom tags appear in both tag bar and side panel
- Tag bar excludes platform/size tags (side panel only)
- All discovered tags show colored dots on thumbnails

### Navigation & Settings
- Left/Right arrow keys for page navigation
- View > Thumbnails Per Page: 50/100/150/200/300/500
- Recursive checkbox for folder imports
- Ctrl+V accepts plain text file/folder paths
- Search supports glob patterns (*.png, hero_*)
- Alt+click tag bar button → search by that tag

### UI Polish
- Unicode stars ★/☆ cycling 5 Vinik colors
- File extension shown in thumbnail labels
- Resolution text properly spaced below thumbnails
- Green flash on status bar when saving
- Wider note and rename dialogs
- App icon (Vinik-themed D) in titlebar
- Windows title bar matches theme color
- All dialogs themed (New Tag, Rename, Reset, etc.)
- Tag panel scroll area transparent for theme

### Theme Coverage
- Object-name selectors for reliable theming across all widgets
- All hardcoded hex colors replaced with rgba
- Grid area, scroll areas, dialogs all respect active theme
- 7 themes: Vinik 24, Warm Charcoal, Soot, Bone, Milk Glass, Forest, Dark

### Code Quality (4 simplify rounds)
- Extracted imaging.py for shared PIL/Qt conversion
- Public APIs: rebuild_tag_bar, import_folder, import_files, etc.
- Single-pass tag discovery, dedup separator helpers
- Robust get_tags with error handling
- Disk cache with MD5 keys and index
- .gitignore for dist/pycache

### v0.3.1 — Tag Panel Sections
- Left panel now has 4 clear sections with proper separators:
  1. Content/Workflow (Page, Character, Sketch, etc.)
  2. Platform/Size targets (Hero, Banner, Cover, etc.)
  3. Custom/Project tags (user-added, project-specific)
  4. Visual/Mood/Dimension (warm, cool, dark, portrait, etc.)
- Tags insert into their correct section, no more mixing

### Pin Tags
- Right-click tag → "Pin to top" moves it to the top of its own section
- Gold left border indicates pinned tags
- Right-click again to unpin

### Custom Keyboard Shortcuts
- Right-click tag → "Set Shortcut Key" assigns any single key
- Custom shortcuts register live and show as [K] in the tag label
- Works alongside built-in 1-9 shortcuts

### Navigation & Settings
- Left/Right arrow keys page through thumbnails
- View > Thumbnails Per Page: choose 50/100/150/200/300/500 (persists)

### Fixes
- Tag dots now show for all discovered tags (warm, portrait, etc.)
- Custom tags appear in both tag bar and side panel
- Wider note and rename dialogs (500px/400px)

## v0.3.0 — 2026-04-04

### SAI/SAI2 Shell Thumbnails
- SAI and SAI2 files now show real thumbnails via Windows Shell API (requires SaiThumbs installed)
- Unsupported formats show styled placeholder with extension and filename
- Shell thumbnail integration works for CLIP, KRA, XCF if shell extensions are installed

### Disk Thumbnail Cache
- Thumbnails cached as PNGs in `~/.doxyedit/thumbcache/`
- Keyed by file path + modification time — changed files auto-regenerate
- Second launch of a 600-image project loads near-instantly

### Preview Annotations
- Press N or click "Add Note" in preview to draw annotation boxes on images
- Type note text after drawing, saved to asset's notes field
- Delete key removes selected annotations
- Annotations persist with the project

### Tag System Improvements
- Custom tags now appear in both the tag bar AND the side panel immediately
- Tag bar excludes platform/size tags (Hero, Banner, etc.) — they're side panel only
- All discovered tags (auto visual properties, custom) show in the tag bar
- Right-click tag to rename it across all assets
- Quick Tag context menu now shows all tags in sections with separators
- Notes field changes now mark project dirty (saves properly)

### UI Polish
- Star uses unicode ★/☆ characters at 18px — visible on all themes
- Resolution text moved down 8px to clear thumbnail overlap
- Green flash on status bar when saving (visual feedback)
- Recursive checkbox for folder imports (scans subfolders)
- Ctrl+V accepts plain text file/folder paths from clipboard
- File extension shown in thumbnail labels (e.g. "art.psd" not "art")
- Search supports glob patterns (*.png, hero_*)
- Dialog boxes (New Tag, etc.) themed properly
- Tag panel scroll area transparent (theme shows through)
- App icon (Vinik-themed) in title bar and taskbar
- Full DOCS.md documentation

### Theme Coverage
- Object-name-based selectors for reliable theming
- Grid area, scroll areas, dialogs all pick up active theme
- Removed all remaining hardcoded hex colors (rgba throughout)

### Code Quality
- Extracted _rebuild_tag_bar for consistent tag bar updates
- Robust get_tags handles corrupt custom_tags gracefully
- setParent(None) for immediate widget cleanup in FlowLayout

## v0.2.0 — 2026-04-04

### PSD & Format Support
- PSD/PSB files now load with full thumbnail and preview support via psd-tools
- Uses embedded PSD thumbnail for fast grid loading, falls back to full composite when needed
- Added support for PSB, TGA, DDS, EXR, HDR, ICO file extensions
- SAI, CLIP, KRA, XCF files accepted (show placeholder if PIL can't read them)

### Theme System
- 7 themes: Vinik 24 (default), Warm Charcoal, Soot, Bone, Milk Glass, Forest, Dark
- Windows title bar color matches the active theme
- Theme-neutral rgba colors throughout — light themes (Bone, Milk Glass) now work properly
- All widgets inherit from theme stylesheet (removed hardcoded dark colors)
- Theme persists across sessions

### Tag System Overhaul
- Tags split into two sections: Content/Workflow (top) and Platform/Size targets (bottom) with separator
- Campaign tags corrected to real Kickstarter specs (Hero 1024x576, Banner 1600x400, etc.)
- Added Tier Card, Stretch Goal, Interior tags
- Custom tags: click "+" button to add project-specific tags with auto Vinik color assignment
- Delete tags: right-click any tag row to delete it from all assets
- Hide tags: right-click to hide, "Show All" button to restore
- Reset All Tags: File menu option to nuke all tags for a fresh start (with confirmation)
- Tags checkbox shows error message when trying to add a duplicate
- Auto visual property tagging on import: warm/cool, dark/bright, detailed/flat, portrait/landscape/square/panoramic/tall

### Star System
- Star button now cycles through 5 Vinik colors (gold, blue, green, rose, red) then off
- Backwards compatible with old bool values in project files

### Selection & Navigation
- Shift+click for range select (standard Windows behavior)
- Ctrl+click for multi-select toggle
- Alt+click sends image to Censor tab
- Delete key on Assets tab soft-deletes (tags as "ignore" and hides)
- Assets tagged "ignore" auto-hide from grid, "Show Ignored" toggle button to reveal
- Search toggles between filename and tag search via checkbox

### Performance
- Thumbnails generated at 512px for sharp display at any zoom level
- Background thread thumbnail loading with paging (100 per page)
- Lazy PSD composite — only when embedded thumbnail is too small
- Single-pass progress counter instead of 4 iterations
- Scroll position preserved when tags change (no more jumping to top)
- Debounced resize rebuilds

### UI Polish
- Tag panel moved to left side
- Left toolbar reorganized: tab nav, file ops, asset import, canvas tools
- Tag bar uses FlowLayout — wraps to multiple rows instead of forcing window width
- Tag dots on thumbnails doubled to 12px with subtle border shadow
- Font size controls: Ctrl+= / Ctrl+- / Ctrl+0 (8px to 24px, persists)
- Tag buttons scale with font size
- Preview dialog remembers window size, position, and zoom level
- Hover preview toggleable via checkbox, 500px preview size
- Right-click context menu: Preview, Send to Canvas, Send to Censor, Open in Explorer, Copy Path, Quick Tag submenu
- Recent Projects and Recent Folders submenus in File menu
- Last project auto-loads on startup, last folder remembered for dialogs
- Ctrl+scroll zooms thumbnail grid (80px to 320px, persists)
- ASCII art header in bat launcher

### Code Quality (3 simplify rounds)
- Extracted imaging.py — shared PIL/Qt conversion, PSD loading
- Asset.stem/name properties, Asset.cycle_star(), toggle_tags() helper
- Public APIs on browser (import_folder, import_files, refresh, shutdown, open_folder_dialog, add_images_dialog)
- Theme mutation bug fixed (dataclass copy instead of mutating global)
- Deque for thumb worker queue (was list with O(n) pop)
- Selected IDs as set for O(1) lookups
- Project.get_asset() with lazy dict index
- .gitignore added (dist/, __pycache__/, *.pyc, *.exe)

### Build
- Nuitka build.bat tested and working
- psd-tools added to requirements.txt

## v0.1.0 — 2026-04-04

Initial release. PySide6 thumbnail browser with paging, lazy loading, multi-select, tagging, search/sort/filter. Non-destructive censor editor. Canvas annotation. Platform assignment dashboard. Auto-save, drag-drop, keyboard shortcuts. CLI pipeline for Claude integration.
