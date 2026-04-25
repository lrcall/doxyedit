# DoxyEdit autofill (userscript + extension)

Browser-side companion that bridges DoxyEdit's current project to social compose pages. Fills identity fields, per-platform captions, attaches images, and (the headline feature) submits the post in one click via the green **POST NOW** button.

Two install options sharing the same code; pick whichever fits.

| | Userscript (Tampermonkey) | Extension (Manifest V3) |
|--|--|--|
| File | `docs/userscripts/doxyedit-autofill.user.js` | `docs/extension/` |
| Install | Tampermonkey -> Dashboard -> paste | `brave://extensions` -> Load unpacked |
| Per Brave profile? | Yes (each profile installs separately) | No (extension persists across profiles) |
| Auto-update from DoxyEdit | Yes via `@updateURL` (when the bridge is running) | Manual: Reload the extension after editing `content.js` |
| `@connect` reapproval after major edits | Tampermonkey may force re-approval (renames, etc.) | Not needed - `host_permissions` granted at install |

The extension content.js is rebuilt from the userscript body so behavior is identical; pick the install method, not the feature set.

## Install

### Userscript path

1. Install [Tampermonkey](https://www.tampermonkey.net/) in Brave or Chrome.
2. Open Tampermonkey -> Dashboard -> + tab.
3. Paste the contents of `docs/userscripts/doxyedit-autofill.user.js`. Save.
4. Press F6 in DoxyEdit. The HTTP bridge starts on `http://127.0.0.1:8910` and the userscript's `@updateURL` will pull future revisions automatically while the bridge is running.

### Extension path

1. Open `brave://extensions` (or `chrome://extensions`). Toggle Developer mode on.
2. Click "Load unpacked" and select `docs/extension/`.
3. The amber FAB appears on every supported compose page.
4. After editing `content.js`, click the reload icon on the extension card. No re-install required.

## One-click POST NOW

Pre-conditions:

1. DoxyEdit is open with a project containing a post tagged for the platform you want to post on (e.g. `platforms = ["bluesky"]` for `bsky.app`, `platforms = ["reddit"]` with a `reddit_<sub>` caption for Reddit, etc.).
2. Press F6 in DoxyEdit to push identity + posts + asset bytes to the bridge.
3. Open the platform's compose page in the debug Brave/Chrome instance.

Click the green **POST NOW to <platform>** button in the panel. The userscript:

1. Attaches the first asset from the post via the fetch cascade (v4 plain fetch -> v5 plain XHR -> v6 img+canvas; GM_xmlhttpRequest variants are dropped because they stall on this Tampermonkey/Brave combo).
2. Fills the caption (auto-focuses the compose editor first; for Reddit, fills both title and body via per-host selectors that cover faceplate web components and old.reddit textareas).
3. Clicks the platform's submit button.
4. Polls 8s for the submit to be accepted (button detached from DOM, disabled, or no other matching submit button visible) and emits a `verified:true|false` feedback event back to DoxyEdit.

The POST NOW button only appears when the current host is recognized AND `posts[<platform_key>]` exists in the payload, so unsupported routes don't dangle a fake one-click button.

### Supported hosts

| Host | Status | Caption shape |
|------|--------|---------------|
| `bsky.app` | live | single string |
| `x.com` / `twitter.com` | live | single string |
| `mastodon.*` | live | single string |
| `threads.net` | live | single string |
| `reddit.com` / `old.reddit.com` | live (text posts; subreddit picker manual) | `{title, body}`, key is `reddit_<sub>` |
| `ko-fi.com` / `newgrounds.com` / `itch.io` / `indiedb.com` / `gamejolt.com` / `tumblr.com` | stubs | live-DOM verification pending |

Stubs surface a clear status line ("no submit button found, click manually") instead of silently failing when their guessed selectors don't match real markup.

### Reddit specifics

- Plat key is `reddit_<sub>`; on `reddit.com` the panel picks the `reddit_*` post whose subreddit appears in the current URL path (case-insensitive). Falls back to the first alphabetically when no match.
- POST NOW bails with a clear "open `https://reddit.com/r/<sub>/submit` first" message if the URL doesn't include the target subreddit. Programmatic navigation isn't done because Reddit's SPA tears down the userscript on full nav.
- Best-effort click on a visible "Text" post-type tab before filling so `/submit` pages that defaulted to Images get title + body fields mounted.

## Transport indicator

Colored dot on the FAB + panel header:

| Color | Source | Meaning |
|-------|--------|---------|
| green | `cdp` | Live: DoxyEdit's Playwright worker injected the payload directly. |
| amber | `http` | Periodic poll of `http://127.0.0.1:8910/doxyedit.json`. |
| blue | `clipboard` | You used "paste from DoxyEdit" manually. |
| gray | `fallback` | No transport reached the page; built-in defaults only. |

Gray is the failure mode to watch for. Press F6 in DoxyEdit; if it stays gray check `%TEMP%/doxyedit_bridge.log`. The HTTP bridge auto-rediscovers itself on a different port if DoxyEdit restarts mid-session (drops the cached winning port on a miss, re-probes 8910/8911/8912 on the next poll).

## Recent posts panel

Below the post buttons, a collapsible "recent posts (N)" section shows up to 20 most-recent POST NOW attempts persisted in `localStorage` under `doxyedit_post_history_v1`. Color-coded:

- green = verified (submit clicked, compose closed within 8s)
- amber = unverified (submit clicked, compose stayed open; spot-check the platform)
- red = failed (image attach / fill / submit-button-not-found)
- gray = skipped (e.g. wrong subreddit URL)

Failed/unverified rows carry a blue "retry" link. Clicking it re-fires POST NOW in place, but only if the current host's platform key still matches the row's target (a Bluesky row on x.com surfaces "retry skipped" instead of running something that can't work).

## Feedback backchannel

The userscript reports outcomes back to DoxyEdit via `POST /doxyedit-feedback`:

- `{type: "posted", platformKey, pageUrl, verified}` after a POST NOW attempt.
- Failed feedback POSTs queue in `localStorage` under `doxyedit_feedback_queue_v1` (up to 50 entries) and flush opportunistically on every successful subsequent call + once 1.2s after page load.

Project side, DoxyEdit's `_consume_bridge_feedback` QTimer drains the queue every 3s, matches each `posted` event to a queued post by `platformKey`, sets `platform_status[<key>] = "posted"` (or `"posted_unverified"`), records `published_urls[<key>] = pageUrl`, flips overall `status` to POSTED when every platform on the post is accounted for, and schedules engagement follow-ups via `generate_engagement_windows`. The composer's Links box renders each `(platform, live URL)` pair as a clickable anchor; unverified ones get an amber `[UNVERIFIED]` tag.

## Diagnostic logging

The userscript posts client-side logs to `POST /doxyedit-log` (level + message + url + detail). Lines land in `%TEMP%/doxyedit_bridge.log` tagged `userscript.<level>` so headless tests and remote-assist see browser-side errors without DevTools.

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| Alt+P | Toggle the autofill panel |
| Alt+N | Fill the focused field with displayName |
| Alt+B | Fill the focused field with bioShort |
| Alt+V | Paste the latest DoxyEdit snapshot from clipboard |

All shortcuts require a compose field to be focused first.

## MCP server

`bin/doxyedit_mcp.py` is a read-only MCP server that exposes DoxyEdit projects to any MCP client (Claude Desktop, Claude Code, Cowork). Tools: `list_projects`, `get_project_summary`, `list_posts`, `get_post`, `get_active_page`. Setup details in `bin/README.md`. Requires `pip install mcp` (opt-in).

## Troubleshooting

- **FAB is gray.** No transport reached this page. Press F6 in DoxyEdit. If still gray, confirm Brave/Chrome was launched via "Launch Debug Browser" (port 9222) and the HTTP bridge is up at `http://127.0.0.1:8910/doxyedit.json`.
- **Panel says "no posts tagged for <host>".** Add a post tagged for that platform in the DoxyEdit composer. Reddit needs a `reddit_<sub>` caption shape.
- **POST NOW reports UNVERIFIED.** Submit fired but the compose didn't close within 8s. Spot-check the platform - the post may have landed but the page state didn't tell us. Use the retry link in the recent-posts panel if it didn't.
- **Asset button does nothing.** Check the DevTools console for the URL the userscript is hitting (`[doxyedit] fetching asset: <url>`). If you see `HTTP 404`, DoxyEdit's bridge doesn't have that asset registered; restart DoxyEdit. If you see no logs at all, the userscript may not be running on this host - check Tampermonkey/extension is enabled.
