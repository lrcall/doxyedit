# DoxyEdit Changelog

## v2.5.3 (2026-04-24) - Posting bridge polish + resilience

Follow-up session to v2.5.2. Keeps the one-click flow working
through real-world breakage: bridge restarts between submits, a
site DOM that doesn't match our default selectors, multi-
subreddit sessions, and the user needing to come back later and
see what landed where.

### Backchannel resilience

- **localStorage retry queue** (`doxyedit_feedback_queue_v1`) for
  feedback events that failed to reach the bridge. Up to 50
  unsent entries persist across browser restart + tab reload;
  every successful `notifyFeedback` opportunistically flushes
  the backlog, and `init()` schedules a flush 1.2s after page
  load. A DoxyEdit restart or port change between submit and
  notification no longer loses the record of a post we already
  submitted on the platform.
- **SPA navigation detector** - 2s poll of `location.href` +
  `window.focus` listener re-runs `tryCdpInjection` and flushes
  the feedback queue so the panel follows route changes inside
  Bluesky / X / Reddit / Threads (which swap between feed /
  compose / profile without full reloads).
- **Bounding-rect size filter** (40x20 floor) on the paste-target
  scan. Sites like Threads / Instagram / Bluesky mount several
  contentEditable nodes (reply boxes, emoji pickers, decorative
  placeholders); the old "first visible contentEditable" heuristic
  latched onto the wrong one. Anything smaller than 40x20 is
  always decoration.

### Per-platform tuning

- **Reddit title selectors** include the faceplate design-system
  forms new.reddit.com actually uses today:
  `faceplate-textarea-input[name="title"] textarea`,
  `faceplate-input[name="title"] input`,
  `shreddit-composer [slot="title"]`,
  `[data-testid="post-title-input"]`.
- **Per-subreddit-aware resolver** - `currentHostPostKey` on
  reddit.com now scans the `reddit_*` keys and picks the one
  whose subreddit segment appears in the current URL path (case
  insensitive, bracketed to avoid prefix collisions like
  pixelart vs pixelart_wip). Alphabetical first is only the
  fallback. Prevents the "posted indiedev content into
  /r/pixelart" wrong-sub class of bug.
- **POST NOW stubs** for gamejolt, tumblr, ko-fi, newgrounds,
  itch, indiedb. Each carries best-guess submit-button
  selectors; unmatched hosts fall through to the existing
  "no submit button found, click manually" status line.

### Error recovery + status feedback

- **POST NOW history panel** persists up to 20 most-recent
  attempts in localStorage (`doxyedit_post_history_v1`). Every
  branch of the flow (verified, unverified, skipped, failed
  at image / fill / submit) records an entry. Panel renders a
  collapsed "recent posts (N)" section with color-coded rows:
  green verified, amber unverified, red failed, gray skipped.
- **Retry link** on non-verified history rows re-fires
  `postNowOnCurrentPlatform` in place. Safety guard: retry
  only runs if the current host's platformKey still matches
  what the history row targeted.
- **/doxyedit-log** endpoint on the bridge accepts
  `{level, message, url, detail}` from the userscript and
  funnels each line into `%TEMP%/doxyedit_bridge.log` tagged
  `userscript.<level>`. `logToBridge(level, msg, detail)`
  wraps a console.log + fire-and-forget fetch; used for retry-
  queue warnings, asset-fetch debug traces, and cascade-winner
  info so headless tests and remote-assist see browser-side
  diagnostics without DevTools.
- **Text-transform reset** on panel classes so host CSS
  (Bluesky applies `text-transform:uppercase` on `button{}`)
  can't render the panel in SHOUTING CAPS.

### Socials-tab UI

- **Published URLs** clickable in the composer's Links box:
  rich-text QLabel under the URL field renders each
  `(platform, live_url)` pair from `post.published_urls` as an
  anchor with `openExternalLinks(True)`. Unverified platforms
  get an amber `[UNVERIFIED]` tag next to the URL.
- **Per-platform override count** on the composer's
  Per-platform captions toggle: "Per-platform captions v (3 set)"
  when three platforms carry overrides, live-updated via
  `textChanged` on each textedit and cached across collapsed
  state so the count is right even before the section is
  expanded.
- **Engagement checks scheduled** on backchannel POSTED flip.
  When `_consume_bridge_feedback` promotes a post QUEUED/PARTIAL
  -> POSTED for the first time, it calls
  `generate_engagement_windows` and stores the resulting
  EngagementWindow dicts on `post.engagement_checks`. Live
  URLs from `published_urls` override template URLs so
  reminder links land on the actual post. Idempotent: repeat
  events find engagement_checks non-empty and skip.

### Extension + MCP

- **Manifest V3 browser extension** at `docs/extension/`.
  Mirror of the userscript as a content script + MV3 manifest.
  `host_permissions` cover bridge ports 8910-8912 plus every
  platform the userscript targets. Dodges the Tampermonkey
  `@connect` reapproval issue that broke asset fetches during
  the psyai -> bridge rename. Install via
  `brave://extensions -> Load unpacked -> docs/extension/`.
- **MCP server** at `bin/doxyedit_mcp.py`. Read-only tools let
  Claude Desktop / Claude Code / Cowork query projects without
  the GUI running: `list_projects`, `get_project_summary`,
  `list_posts`, `get_post`, `get_active_page`. Project discovery
  via `DOXYEDIT_PROJECT_DIRS` env var. Requires
  `pip install mcp` (opt-in; server only runs when the user
  registers it in their client config).

### Misc

- **atexit cleanup** in bridge.py so the worker subprocess +
  HTTP server thread + persistent Playwright session don't
  zombie when DoxyEdit exits through `sys.exit`, an unhandled
  exception, or bare `QApplication.quit()`.
- **HTTP bridge self-heal**: userscript drops the cached winning
  port on a miss and re-probes all candidates next poll, so a
  DoxyEdit restart on a different port is rediscovered within
  one poll interval.
- **Double-attach mutex** in `_finalizeLoadedFile` uses
  `_pickedFiles[0].name + .size` as the signal, so a slow
  fetch variant that completes after a faster sibling already
  attached bails instead of firing a second paste event (the
  "posts 2 images" bug on Bluesky).

---

## v2.5.2 (2026-04-24) - One-click cross-platform posting

Session goal: press ONE button in the browser, the game-promotion
post lands on the target social platform with image, caption, and
submit all chained. Built on top of the v2.5.1 userscript bridge;
this slice turns the bridge from an autofill helper into an actual
posting pipeline.

### Rename: psyai -> bridge

Infrastructure cleanup before the posting work. The userscript
system was named after a prior project; everything renamed in one
pass (git mv preserves history):

- `doxyedit/psyai_bridge.py` -> `doxyedit/bridge.py`
- `doxyedit/psyai_data.py`   -> `doxyedit/bridge_data.py`
- `doxyedit/psyai_worker.py` -> `doxyedit/bridge_worker.py`
- `docs/userscripts/psyai-autofill.user.js`
                             -> `docs/userscripts/doxyedit-autofill.user.js`
- HTTP endpoints: `/psyai.json` -> `/doxyedit.json`, `/psyai-asset`
  -> `/doxyedit-asset`, `/psyai-autofill.user.js`
  -> `/doxyedit-autofill.user.js`
- Window global `window.__psyai_data` -> `window.__bridge_data`
- CSS classes, Python identifiers, log file path, panel brand,
  all updated in lockstep

### One-click POST NOW flow

- **Green POST NOW button** appears in the userscript panel when
  the current host is recognized AND the payload carries a matching
  posts[<key>]. Chains image attach -> caption fill -> submit click
  in sequence, reporting each step to the status strip.
- **Per-host submit selectors** in `POST_NOW_HOSTS`:
  - Bluesky: `[data-testid="composerPublishBtn"]`, `aria-label="Publish post"`
  - X / Twitter: `[data-testid="tweetButtonInline"]`, `tweetButton`
  - Threads: `div[role="dialog"] div[role="button"][tabindex="0"]`
  - Mastodon: `button.compose-form__publish-button-wrapper button`
  - Reddit: `shreddit-composer button[type="submit"]`,
    `button[slot="submit-button"]`, `button.btn[name="submit"]`
    for old.reddit
- **Debounced** via `_postInFlight` so a second click while a post
  is mid-flight is ignored.
- **Post-submit verification**. After clicking submit, polls 8s
  for the button to detach from the DOM, become disabled, or the
  compose container to close (universal accepted-post signal).
  Emits `verified:true` on success, `verified:false` with a note
  on timeout so the user can spot-check instead of trusting a
  false-positive POSTED.

### Image attach: fetch cascade

Tampermonkey's `GM_xmlhttpRequest` started stalling on multi-MB
responses after the rename (script re-registered under new
`@namespace` + `@name`; `@connect 127.0.0.1` approval never
invisibly carried over). Ship a cascade of non-GM fetch paths,
confirmed working by the user:

- v4: plain `fetch()`
- v5: plain `XMLHttpRequest`
- v6: `<img>` + `canvas.toBlob()` (re-encodes; no byte transit)

Cascade fires each variant in order with a 4s race timeout.
Double-attach mutex in `_finalizeLoadedFile` checks
`_pickedFiles[0].name + .size` so a slow variant that completes
after a faster sibling already attached bails instead of firing
a second paste event (had been producing the "two face.png"
result on Bluesky). GM variants removed entirely rather than
carried as dead code.

### Feedback backchannel

The other half of the pipeline: when the userscript successfully
submits, DoxyEdit needs to know so the project can flip the post's
status and record the live URL.

- **POST /doxyedit-feedback** on the same HTTP bridge server.
  Accepts JSON, stamps `t=epoch`, appends to `_HTTP_STATE.feedback`
  (queue bounded at 1000).
- `peek_feedback()` / `drain_feedback()` helpers on `bridge.py`.
- Userscript `notifyFeedback(entry)` fires a plain fetch POST
  stamped with `host` and `pageUrl`; called after every successful
  POST NOW.
- **MainWindow `_consume_bridge_feedback`** QTimer drains every 3s,
  matches by `platformKey` (with Reddit root-matching so
  `reddit_indiedev` maps to a `platforms=["reddit"]` post), sets
  `platform_status[key] = "posted"` or `"posted_unverified"`,
  records `published_urls[key] = pageUrl`, flips the overall
  `status` to `POSTED` when every listed platform is accounted for
  (or `PARTIAL` when some are). Calls `_refresh_social_panels()`
  so the timeline / calendar / gantt / platform panel all repaint
  without a manual tab switch.

### Reddit-specific handling

- Payload shape is `{title, body}`, not a plain caption string,
  so the POST NOW flow branches to `fillPostPayload` which targets
  title + body editors separately (Shreddit web components,
  Draft.js contentEditable, old.reddit textareas).
- **Subreddit-aware URL check**. plat_key is `reddit_<sub>`, so on
  generic `/submit` we know which community and bail with a status
  pointing at `/r/<sub>/submit` rather than failing silently at the
  subreddit picker.
- **Post-type tab stub**. Best-effort click on a visible Text tab
  before the field scan, so `/submit` pages that default to the
  Images tab get the title + body fields mounted.

### UX polish

- **F6 themed progress modal** (QProgressDialog styled via the
  existing `claude_progress` QSS selectors) during CDP push.
  Windows title bar tinted to the active theme.
- **Auto-focus compose editor** before dispatching the synthetic
  paste, so clicking the asset button no longer requires the user
  to first click into the compose field themselves.
- **Search-bar paste filter**: paste-friendly host check now
  requires the focused element to sit inside a compose container
  (`role=dialog`, `aria-modal`, form.compose-form, etc.) - a
  focused search input on bsky.app no longer silently swallows
  the paste event.
- **atexit cleanup** so the worker subprocess + HTTP server thread
  + persistent Playwright session don't zombie when DoxyEdit exits
  through `sys.exit`, an unhandled exception, or bare
  `QApplication.quit()`.
- **HTTP bridge self-heal**: userscript drops the cached winning
  port on a miss and re-probes all candidates next poll, so a
  DoxyEdit restart on a different port is rediscovered within one
  poll interval.
- **Help line** in the userscript FAB panel documents all four
  Alt shortcuts (P/N/B/V) and the transport color legend (cdp /
  http / clipboard / fallback).
- **Text-transform reset** on panel classes so host CSS (Bluesky
  applies `text-transform:uppercase` on `button{}`) can't leak
  into our buttons and render them in SHOUTING CAPS.

### Misc

- `_slugify_handle` collapses every non-[a-z0-9] run to a single
  underscore so display names like `B.D. INC / Yacky` produce a
  usable handle `b_d_inc_yacky` instead of `b.d._inc_/_yacky`.
- Worker `stderr` is drained on a daemon thread so Playwright's
  Node driver warnings / tracebacks can't fill the 64 KiB pipe
  buffer and stall pushes; stderr lines land in the persistent
  log for diagnosis.
- Quiet CDP failure fallback: when CDP push fails but the HTTP
  bridge is live, the userscript already has the same snapshot
  mirrored, so `_bridge_push_done` degrades to a status-bar line
  instead of a modal dialog.
- `docs/userscripts/README.md` covers install, the F6 flow,
  transport legend, shortcuts, per-platform notes, and the three
  common failure modes.

---

## v2.5.1 (2026-04-24) — Bubble + text polish, perf instrumentation, Brave migration

Follow-up session to v2.5: bubble-deformer feature completion, text
rendering fixes, perf log visibility, and infrastructure work to let
the posting pipeline switch from Chrome to Brave.

### Bubble deformer overhaul
- **Range doubled** on every existing deformer. Roundness 0..2 (past
  1.0 overshoots into a puffier ellipse), Oval stretch -1.2..1.2,
  Wobble 0..2, Tail curve -2..2.
- **New modifiers** on `CanvasOverlay`:
  - `bubble_tail_width` (0.2..3.0, default 1.0) — thicker/chunkier
    vs needle-thin tail base.
  - `bubble_tail_taper` (-1..1) — slides the tip sideways along the
    tail axis so the tail leans instead of pointing symmetrically.
  - `bubble_skew_x` (-1..1) — horizontal shear around body center.
  - `bubble_wobble_waves` (2..32, default 8) — sin-cycle count around
    the perimeter. Renamed from the prior `bubble_wobble_complexity`
    (which controlled frequency, not vertex density).
  - `bubble_wobble_complexity` (16..512, default 72) — actual vertex
    count along the outline. Low → polygonal silhouette, high →
    smooth curves, independent of wave count.
  - `bubble_wobble_seed` (0..999) — phase shift so two bubbles on
    the same canvas don't wobble in lockstep when copy-pasted.
- **Shape Controls dialog** exposes all new sliders with "Reset
  Deformers" restoring the full set to defaults.
- **Shared path builder** (`_build_speech_bubble_path` and
  `_build_thought_bubble_body_path`) so the off-thread QImage cache
  renderer and the live paint path produce pixel-identical output
  across every deformer. Previously the cache only applied
  `bubble_roundness` and "reverted" the shape once async render
  settled.
- **Skia preview (Shift+S)** brought to parity with every deformer
  via `canvas_skia._append_speech_bubble_path`, including
  `skia.PathMeasure`-based wobble when the Skia-Python build
  supports it.
- **Bounding rect inflation** covers every deformer's worst-case
  extent — wobble amp, oval-stretch expansion, skew shear, roundness
  overshoot, tail-curve bezier excursion, and stroke half-width —
  so selection dashes, hit-tests, and Qt invalidation never crop
  the painted shape.
- **Text ↔ bubble reverse linking**: dragging a text item that's the
  `linked_text_id` of a speech/thought bubble now moves the bubble
  in lockstep. Previously the link was one-way (bubble drag → text
  followed) so dragging the text decoupled the pair.

### Text rendering
- **Line-height mode** switched from `ProportionalHeight` to
  `LineDistanceHeight` (Qt's additive-leading mode). Glyphs always
  render at natural height; only the baseline advance changes. At
  `lh < 1.0` lines overlap typographic-comics style without
  shrinking the line box; at `lh > 1.0` leading expands normally.
- **Descender clipping fixed** — main text routed through
  `QAbstractTextDocumentLayout.draw()` instead of the default
  `QGraphicsTextItem.paint()` which clipped to the document's
  reported bounds and ate the last line's descenders. Edit mode
  still routes through super().paint() so the caret + selection
  highlight render normally.

### Text Controls dialog
- **Painted `_StudioIcons` for Weight + Align** (`text_bold`,
  `text_italic`, `text_underline`, `text_strike`, `align_left`,
  `align_center`, `align_right`). Replaces raw glyph letters and
  unicode line-drawing chars that rendered blank on some UI fonts.
- **Compressed button token** (`studio_prop_btn`) applied to every
  Shape Controls action button (Reset Transform, Save/Apply Default,
  Swap fill↔stroke, Make square, Clear, Rand, Reset Deformers,
  Reset Adjustments, etc).
- **Shadow row split** into two rows: toggle + color swatch + Clear
  on top, labelled Off / Blur sliders on bottom.
- **Dividers** above the Outline/Kerning/Line Height/Rotation/Width
  slider stack and above the Shadow section.
- **Min width raised** so the Qt.Tool title bar never truncates the
  "Text Controls" caption to "xt Controls" with the close X on top.
  Derived from `font_size * ratio` so the floor scales with the
  active theme's UI size.
- **Chars / words / lines** count label moved to its own form row
  so it no longer overlaps the text edit above.
- **Position combo** stays in the main top toolbar instead of being
  re-parented into the Text Controls popup on dialog build.

### Theme + icon contrast
- **Light-theme icon tuning** — `_StudioIcons._fg()` returns
  `#101010` on themes whose `bg_main` luminance is over 160, and
  `_pen()` adds 0.4px of stroke width on light themes so painted
  glyphs carry visible weight against bright chrome.

### Browser → Studio routing
- **Ctrl+Enter** on a browser thumbnail emits the new
  `AssetBrowser.asset_to_studio` signal, which window.py wires to
  the existing `_send_to_studio` handler.
- **S key** (plain, no modifiers) sends the current asset to Studio
  from anywhere in the main window: browser selection wins first,
  then the docked preview pane's asset, then a Studio-tab fallback.
- **Paint → Studio**: fill-color swatch in the quickbar now opens
  `QColorDialog` when nothing is selected and persists the picked
  color as the default shape fill, so the left-side swatch is never
  a dead click.

### Posting pipeline
- **Brave browser auto-detect** (`browserpost._BROWSER_CANDIDATES`,
  `launch_debug_browser`). Chrome now requires phone-number
  verification for fresh profiles, so the user's posting workflow
  is shifting to Brave. Brave is preferred by default, Chrome is
  a fallback, per-browser profile dirs isolate login state, and
  the deprecated `launch_debug_chrome` shim keeps every existing
  call site working.
- `detect_running_browser(cdp_url)` reports whichever is actually
  answering the CDP port so UI messages can say "Debug Brave
  launched..." instead of a stale "Debug Chrome launched...".

### Userscript bridge (psyai)
New Tampermonkey userscript at `docs/userscripts/psyai-autofill.user.js`
gives one-click identity + caption + asset autofill on social compose
pages (Bluesky, X, Mastodon, Reddit, Threads). DoxyEdit is the source
of truth; the userscript renders a draggable FAB panel that pulls the
current project's snapshot.

- **F6 = Push Identity+Posts to Browser.** Auto-starts the local HTTP
  bridge if not running and keeps the snapshot live for the session
  (`_psyai_push_cdp` / `_psyai_push_done` / `update_http_snapshot`).
- **Three transports, one payload.** `build_psyai_data()` in
  `psyai_data.py` is the single source:
  - **CDP push** (`psyai_bridge.cdp_push`) injects `window.__psyai_data`
    on every page under the Brave debug instance via
    `Page.addScriptToEvaluateOnNewDocument`, so F5 keeps the
    userscript green until DoxyEdit closes.
  - **HTTP bridge** (`psyai_bridge.start_http_server`) serves
    `GET /psyai.json`, the userscript itself at
    `/psyai-autofill.user.js` (wired through `@updateURL`/
    `@downloadURL` for Tampermonkey auto-update), and asset bytes at
    `/psyai-asset?id=…`.
  - **Clipboard** fallback so the userscript's "paste from DoxyEdit"
    button works even when neither browser transport is reachable.
- **Isolated Playwright subprocess** (`psyai_worker.py`) - Qt/PySide6
  asyncio state corrupts the driver subprocess's pipe handles, so all
  Playwright calls run in a fresh Python interpreter spawned via
  subprocess using a newline-delimited JSON protocol. Long-lived
  connection survives F5; init scripts persist.
- **ProactorEventLoop pinned** on Windows in the worker so driver
  subprocess pipes attach correctly (Selector-on-Windows failed with
  "Connection closed while reading from the driver").
- **Five injection strategies** in the userscript (existing
  `input[type=file]`, click image button + input, paste on focused
  compose, synthetic DataTransfer drag, clipboard write) so at least
  one path works per platform variant.
- **One-click image attach** - DoxyEdit registers composer-post asset
  bytes with the HTTP bridge (`register_assets_bulk`) and the panel
  renders thumbnail buttons that fetch via `GM_xmlhttpRequest`,
  sidestepping the mixed-content block from HTTPS pages to
  `http://127.0.0.1`.
- **Per-host post filter** (`HOST_POST_TAGS`) - panel only shows the
  caption for the current platform (bsky.app → bluesky, x.com → x,
  etc.) instead of dumping every platform's post.
- **Draggable FAB** with position persisted via Tampermonkey storage;
  dblclick resets. Min-size floors keep it readable even with empty
  `displayName`.
- **Composer-post fallback** - when F6 fires with no composer open,
  the bridge pushes the first project post that has `asset_ids` so
  the userscript still has real content to work with.
- **Short-form caption fallback** - bluesky/threads/mastodon fall
  back to `x` or `twitter` caption when no dedicated key exists, so
  short-form idiom copy doesn't need duplication per platform.
- **Persistent log** at `%TEMP%/doxyedit_psyai_bridge.log` captures
  CDP push attempts, worker spawns, and failure tracebacks for
  post-hoc diagnosis.

### Performance
- **Image-enhance PIL off GUI thread** — the brightness / contrast /
  saturation PIL passes on image overlays now run on
  `QThreadPool.globalInstance()` via `_ImageEnhanceWorker` +
  `_ImageEnhanceSignals`. Per-item monotonic tokens prevent stale
  mid-drag workers from overwriting newer slider positions.
- **Shared speech-bubble path builder** removes the divergence
  guard so decorated bubbles can hit the fast-blit cache path after
  the first async build, instead of being stuck on the 72-sample
  live path forever.
- **OverlayShapeItem X/Y slider fix** — `_on_pos_field_changed`
  bypasses `setPos()` for shape items (which stay anchored at scene
  (0,0) and paint from `overlay.x/y` directly). Previously setPos
  triggered itemChange which added the slider delta a SECOND time,
  leaving ghost-tail paint artifacts as the bounding rect drifted
  away from the painted geometry.

### Perf log instrumentation
- **`slow_paint`** events fire unconditionally when a single paint
  is ≥ 33ms (30fps budget). Payload carries scene_items + zoom +
  dirty-rect dimensions to distinguish "full viewport invalidation"
  slow paints from "big moving item" slow paints. Prior 1-in-N
  sampler missed most stutter frames.
- **`frame_gap`** events fire when the inter-paint interval is
  ≥ 100ms. Catches the class of stutter where each paint is fast
  but the event loop was blocked between them (autosave / JSON I/O
  / signal-handler work). Payload carries gap_ms + current paint_ms.
- **`session_start`** no longer misreports `gl_probe_ok=false` /
  `gl_probe_err=""` when the probe was never attempted; now records
  `gl_probe_attempted=false` instead.

### Tokenization + cleanup
- **`BUBBLE_*` and `THOUGHT_BUBBLE_*` constants** at module top of
  `studio_items.py` so every bubble geometry ratio has a single
  source of truth. Prior duplication between the live path and
  bounding-rect inflation was the source of multiple "ghost trail"
  regressions this session.
- **Session tokenization pass** (`/tokenize session`) named every
  magic number this session introduced — text-controls button sizing
  ratios, deformer slider widths, worker state (`_brightness`
  instead of `_br`, etc), last-line headroom + shrink compensation.
- **`QFrame` import fix** in `studio.py` — missing from the Widgets
  import block caused a startup `NameError` when the Text Controls
  dialog tried to build its dividers.

---

## v2.5 (2026-04-22) — Studio full-graphics-product push

Session goal: "the closer it is to a full graphic product the better."
Delivered ~80 commits covering tools, polish, and workflow upgrades.

### New Studio tools
- **Eyedropper (I)** — click to sample a pixel color. Applies to
  selected text overlay color, otherwise copies hex to clipboard.
- **Arrow (A)** — click-drag to draw an annotation arrow. Draggable
  endpoints (yellow handles when selected). Color, stroke width,
  duplicate, delete all work. Exporter renders via PIL.

### Canvas / view
- **Horizontal + vertical rulers** with major/minor ticks, auto-scale
  (5px–5000px step based on zoom), live cursor indicator. Toggleable.
- **Drag-out guides** from either ruler; dashed lines in the active
  theme accent. Guides are snap candidates, movable (drag), and
  double-click to delete. Right-click ruler → Clear All Guides.
- **Rule-of-thirds overlay** toggle (toolbar ⅓ checkbox).
- **Checkerboard background** beneath the image so transparent pixels
  show through as the classic Photoshop pattern.
- **Drop shadow + workspace margin** so the image feels like a
  document on a canvas, not edge-to-edge filler.
- **Ruler corner click** = Fit view; **zoom % label click** = prompt
  for numeric zoom (5–4000%).
- **Zoom shortcuts**: Ctrl+0 (Fit), Ctrl+Shift+0 (zoom to selection),
  Ctrl+1 (100%), Ctrl++ / Ctrl+- (in/out). Wheel zoom updates the
  label and refreshes rulers.
- **Spacebar pan** (Photoshop convention) — hold Space to temp-swap
  to the hand tool.

### Tools / toolbar
- **Undo / Redo toolbar buttons** (↶ / ↷) wired to the QUndoStack,
  auto-disabled when the stack is empty.
- **Active tool highlight** — tool buttons are checkable; the current
  tool lights up via QSS :checked.
- **Shortcut rebinds**: Q=Select, X=Censor, E=Watermark, T=Text,
  C=Crop, N=Note, I=Eyedropper, A=Arrow, . (period) = Focus mode.
- **Focus mode** — hides the layer panel + filmstrip so the canvas
  takes the whole area (toolbar toggle + period hotkey).
- **Rulers on/off**, **Grid on/off** checkboxes persist across
  sessions alongside grid spacing, rule-of-thirds, and canvas
  splitter geometry.

### Selection / editing
- **Alt+click on an overlay or censor** duplicates it in place, then
  drag the duplicate (Photoshop / Figma convention).
- **Tab / Shift+Tab** cycle through scene items (sorted top-to-bottom,
  left-to-right), re-centering the view on the newly selected item.
- **Ctrl+Shift+I** inverts selection.
- **Number keys 0-9** set opacity on selected overlays: 1=10%, 5=50%,
  0=100%.
- **Shift-drag to constrain** censor/crop rectangles to a perfect
  square. **Shift+rotate** snaps censor rotation to 15° steps.
- **Ctrl+D** now duplicates overlays, censors, arrows, and crops.
- **Grid snap** on drag when the grid overlay is visible (smart guides
  still win over grid snap when available).
- **Double-click a crop** to rename; **double-click a guide** to
  remove it.
- **Shift+click layer row** toggles visibility; **Ctrl+click** toggles
  lock.

### Layer panel
- **Section headers** — `-- Overlays --` / `-- Censors --` dividers.
- **(hidden)** prefix on invisible layers in addition to grey-out.
- **Right-click row** → Hide/Show, Lock/Unlock, Rename, Delete.
- **Double-click row** → rename (or enter text-edit for text overlays).

### Status bar
- **Cursor position** (scene-space X,Y) updates live as you hover.
- **Selection count** ("0 selected" / "1 selected" / "N selected").
- **Selected-item geometry** (X,Y  W×H) when exactly one item
  selected.
- **X/Y spinboxes** in the layer properties panel for numeric
  positioning of the selected overlay.

### Overlays
- **Text background fill** — new CanvasOverlay.background_color,
  rendered as a rounded pill behind the text in both Studio and the
  PIL exporter.
- **Export honors text_width** — new _wrap_text_to_width helper
  measures words and inserts line breaks so exported text matches
  the wrapped multi-line layout shown in Studio.
- **Save/Reset Default Text Style** (right-click text → menu).
  Stores the 13 text style fields to QSettings; new text overlays
  pick them up automatically.
- **Save/Reset Default Watermark Style** — same pattern for
  scale/opacity/rotation/position/flip.
- **Preferred censor style** (black/blur/pixelate) persists across
  sessions.
- **Copy Style / Paste Style** — right-click any overlay. Per-type
  slot so text styles can't be pasted onto watermarks.
- **Change Color... / Change Background...** context menu entries
  with QColorDialog including alpha channel.
- **Rotate 90° CW / CCW** context menu actions for quick quarter
  turns.

### Crops
- **Right-click a crop** for Export this crop / Rename / Duplicate /
  Delete. **Double-click** to rename.
- Crop right-click duplicates preserve platform_id + aspect lock.

### Preview pane
- **Studio button** on both the docked preview pane and floating
  preview dialog (auto-closes the dialog after jumping to Studio).

### F-key tab jumps (main window)
- **F1** Assets, **F2** Studio, **F3** Social, **F4** Platforms,
  **F5** Overview, **F6** Notes. Shift+F2 keeps the rename-file
  shortcut.

### Bug fixes
- **Export Platform button** now has a 3-fallback resolution: combo
  selection → selected crop's platform_id/slot_name → single
  platform-scoped crop on the asset → message guiding the user.
- **Folder Scan** respects per-import method (type=file vs type=folder
  in import_sources).
- **Tag colors grey** — placeholder colors promoted to VINIK cycle.
- **Tiny window flash** on project load suppressed by deferring
  show() until async load fires.

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
