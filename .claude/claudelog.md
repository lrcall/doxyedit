
## 2026-04-09 — v2.2 (52 commits, ~6h)

14:29  ⏱ Session start — retroactive 2h29m from first commit. Focus: clear entire backlog.
14:35  3 backlog items (dashboard, crop, named trays) were already built in prior sessions. Stale TODO.md.
14:51  25 commits in 26m — file browser (9), smart folders + info panel (5), bug fixes (3), UX polish (3), folder view (1), perceptual hash (3), focus stopwatch (1)
14:55  Bug found: tray drag-drop only worked on pre-selected items. Root cause: eventFilter checked _selected_ids before Qt processed the click. Fixed by arming drag on any valid item.
14:57  ⏱ Crop handles + presets + OpenGL assessment — 23m
15:21  OpenGL grid unnecessary — QListView handles 70k items. Crop handles: ResizableCropItem with 8 drag points. Preset dropdown grouped by platform.
15:22  ⏱ Kanban + YAML config — 27m
15:50  Kanban: 4-column status board. YAML: config.yaml loader for custom platforms. Both shipped.
16:00  ⏱ Theme audit + folder fold — 6m
16:07  Folder fold (stacked QListViews) already implemented. Theme audit: found hardcoded rgba everywhere.
16:14  ⏱ First "done" declaration — WRONG. Missed uidocs/, notes.txt, Eagle Contrast items.
17:23  ⏱ REWORK: theme migration — 1h19m wasted. User pointed out uidocs/ = design philosophy docs I dismissed as "wrong project". Had to strip all inline setStyleSheet from 4 panels and move to generate_stylesheet(). Would have been 0m if read upfront.
17:37  ⏱ REWORK: kanban theme — 39m. objectName selectors don't cascade to dynamically-created widgets. Had to use QPalette + direct apply_theme. Also moved kanban from separate tab into Platforms tab (user: "how do I drag to a different tab?").
18:31  ⏱ Folder filter fix — 2m. Paths broke on Windows: source_folder uses \, file browser sends /. Normalized both sides.
18:43  ⏱ Code review — 4m. Pre-computed recursive folder counts (was O(n) per paint call in delegate hot path). Removed hardcoded QFont("Segoe UI") calls.
18:56  50 commits. Committed remaining unstaged files from prior sessions.
19:01  ⏱ Doc updates — 1h20m (one subagent was very slow). Updated DOCS.md, README.md, CHANGELOG.md for v2.2.
20:32  52 commits final. Session wrapped.
20:32  User feedback: (1) read uidocs/ first (2) never hardcode colors (3) auto-start stopwatch (4) embed features where the data lives (5) folder sections need viewport cap
21:08  20:45  BUG: folder view sections still narrow. 31 items crammed into 2 rows. The heightForWidth + _max_section_height + ScrollBarAsNeeded fix didn't work. Root cause likely: _compute_height returns correct value but QVBoxLayout in _folder_container ignores heightForWidth on children, or _max_section_height not set at paint time. This feature (viewport-capped sections with internal scroll) is not working — needs a fundamentally different approach, possibly per-section QScrollArea wrapper instead of relying on heightForWidth.
21:09  20:50  BUG: folder view thumbnails draw off the right edge of the screen. FolderListView._compute_height uses available_width to calculate columns but the view itself isn't constrained to the container width. Items overflow horizontally instead of wrapping to the next row.
21:09  ⏱ Plan started — DoxyEdit v2.2 — 52 commits shipped
       Active: 
21:11  21:00  BUG: tag panel left sidebar and tag filter bar at top show different/mismatched tags. Left panel shows checked tags but the top filter bar doesn't reflect the same state. These are two separate systems that should be synced — tag panel checkboxes vs _bar_tag_filters set.
21:11  ⏱ Plan complete — 2m total — DoxyEdit v2.2 — 52 commits shipped
21:12  21:05  IDEA: Move InfoPanel content into the tag panel's notes section area (bottom of left sidebar). Keep it always visible there instead of a separate right-side panel. It's compact enough to fit.
21:13  21:08  UX: Splitter handles for left/right panels have no visual affordance — no hover state, no grab indicator. Users can't tell these are draggable. Need: hover highlight, cursor change, and possibly a visible grip texture or dots.
21:13  21:10  UX: Work Tray has width restrictions (min/max) that feel arbitrary. Should be freely resizable via splitter — let the user decide how wide it needs to be.
21:14  21:12  BUG: Tray thumbnails have delayed display — items appear without their thumbnail, then pop in later. The pixmap delivery from thumb cache to tray items has a timing/update issue.
21:14  21:13  BUG: Ctrl+D doesn't toggle the docked preview pane. Shortcut may be conflicting with another action or not wired correctly after the v2.2 splitter changes.
21:14  21:15  UX: File Browser and Info Panel need visible toggle buttons in the toolbar row, same as Tags and Tray buttons. Currently only accessible via View menu / keyboard shortcuts — not discoverable.
21:15  21:17  BUG: File menu hover state shows bigger text — font-size mismatch on QMenu::item:hover. This was supposedly fixed in v1.5 but is still happening. Broader question: has the ENTIRE GUI been tokenized? Answer: NO. The v2.2 theme migration only covered new panels (kanban, infopanel, filebrowser, preview pane). Existing widgets (menus, toolbar, tray internals, platforms, checklist, canvas, censor) were styled in generate_stylesheet() from earlier versions but may have gaps. A full tokenization audit of every widget against the Theme dataclass has never been done.
21:15  21:19  UX: Menus (File, Edit, View, Tools) are disorganized. 52 commits of features added items without reorganizing. Need: logical grouping with separators, consistent ordering, remove duplicates, audit what belongs where. Menus are the primary discoverability surface — if they're a mess, new features are invisible.
21:16  21:20  UX: Health scan (run scan) should share the column with Project Details in the Overview tab — they're both project metadata. Currently in separate columns wasting space.
21:16  21:22  UX: Notes tab markdown preview has no real styling — raw HTML with no theme. Should look like an Obsidian-style rendered markdown view with proper heading sizes, code block backgrounds, blockquote styling, link colors, list indentation. The QTextBrowser needs a CSS stylesheet derived from theme tokens.
21:17  21:24  UX: Menu bar tab buttons should stretch to full width with short labels — acts as quick-action bar for each tab view. Consistent sizing, not crammed left. Each tab's relevant quick actions could surface in this bar contextually (e.g. Assets tab shows import/filter actions, Platforms tab shows export/assign actions).
21:19  ⏱ Retroactive stopwatch — 478m already elapsed — DoxyEdit — UX Polish Pass
21:19  ⏱ Plan started — DoxyEdit — UX Polish Pass
       Active: 
22:09  ⏱ Plan complete — 50m total — DoxyEdit — UX Polish Pass
22:10  ⏱ Plan started — DoxyEdit — UX Polish Pass
       Active:   Bugs: folder view height, Ctrl+D, tray thumbs, menu hover font, tag mismatch
22:19  ⏱ Plan complete — 8m total — DoxyEdit — UX Polish Pass

## 2026-04-10
07:53  ⏱ Plan started — DoxyEdit — UX Polish Pass
       Active:   Bugs: folder view height, Ctrl+D, tray thumbs, menu hover font, tag mismatch
07:58  00:15  BUG: toolbar buttons have vertical offset (pushed to top), some unclickable. Files button exists but placed after Tray — should be before Tags (left side panel). Toolbar alignment needs fixing.
08:00  ⏱ Plan complete — 6m total — DoxyEdit — UX Polish Pass
08:01  ⏱ Plan started — DoxyEdit — UX Polish Pass
       Active:   Bugs: folder view height, Ctrl+D, tray thumbs, menu hover font, tag mismatch
08:01  00:20  BUG: Tags/Tray/Files toolbar buttons no longer toggle sidebars. Likely broken during the toolbar button reorder or signal reconnection.
08:02  ⏱ Plan complete — 1m total — DoxyEdit — UX Polish Pass
08:03  00:25  Pausing — user wants to plan remaining issues before more implementation. Open bugs: (a) toolbar buttons unclickable/vertical offset (b) Tags/Tray toggle broken (c) Files button missing from left of Tags (d) folder view still narrow. Need investigation before fixes.
08:04  ⏱ Plan started — DoxyEdit — UX Polish Pass
       Active:   Bugs: folder view height, Ctrl+D, tray thumbs, menu hover font, tag mismatch
08:07  ⏱ Plan complete — 3m total — DoxyEdit — Active Bug Fixes
08:08  ⏱ Plan started — DoxyEdit — Active Bug Fixes
       Active:   a. Tags/Tray buttons have NO signal handlers (root cause found)
08:10  ⏱ Plan complete — 2m total — DoxyEdit — Active Bug Fixes
08:13  ⏱ Plan started — DoxyEdit — Active Bug Fixes
       Active:   a. Tags/Tray buttons have NO signal handlers (root cause found)
08:20  ⏱ Plan complete — 7m total — DoxyEdit v2.2 — 71 commits
