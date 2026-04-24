# psyai-autofill userscript

Tampermonkey userscript that bridges DoxyEdit's current project to
social compose pages. Fills identity fields, per-platform captions,
and attaches images with one click.

## Install

1. Install [Tampermonkey](https://www.tampermonkey.net/) in your
   browser (Brave or Chrome recommended for the CDP transport).
2. In DoxyEdit, open the Tools menu and pick "Start HTTP Bridge"
   once (or just press F6, which auto-starts it).
3. Open Tampermonkey -> Dashboard -> + tab, paste the contents of
   `psyai-autofill.user.js`, save.
4. The `@updateURL` header points at `http://127.0.0.1:8910/
   psyai-autofill.user.js`, so every time the bridge is running
   Tampermonkey will pull the latest script version on its own
   update cycle. No manual re-paste after DoxyEdit ships a new
   userscript revision.

## Use

1. Open DoxyEdit with the project you want to post from.
2. Open the social compose page (bsky.app, x.com, mastodon.social,
   reddit.com/submit, etc.) in Brave/Chrome.
3. Press F6 in DoxyEdit. The userscript panel's FAB (bottom-left
   by default) lights up green.
4. Click into the compose field, then click a panel button to
   autofill. The asset buttons attach images in one click when
   DoxyEdit has pushed composer-post assets.

Drag the FAB to move it. Double-click to reset its position.

## Transport indicator

The colored dot on the FAB and in the panel header shows which
transport is currently feeding data:

| Color | Source     | Meaning                                           |
|-------|------------|---------------------------------------------------|
| green | `cdp`      | Live. DoxyEdit's Playwright worker injected the  |
|       |            | payload directly into this page.                  |
| amber | `http`     | Periodic poll of the local HTTP bridge            |
|       |            | (`http://127.0.0.1:8910/psyai.json`).             |
| blue  | `clipboard`| You pasted via "paste from DoxyEdit" button.      |
| gray  | `fallback` | Built-in defaults only. DoxyEdit is not running  |
|       |            | or no transport reached the page yet.             |

Gray is the failure mode to watch for. Press F6 in DoxyEdit to
refresh; if the dot stays gray, check `%TEMP%/doxyedit_psyai_bridge.log`
for errors.

## Keyboard shortcuts

| Shortcut | Action                                            |
|----------|---------------------------------------------------|
| Alt+P    | Toggle the autofill panel                         |
| Alt+N    | Fill the focused field with displayName           |
| Alt+B    | Fill the focused field with bioShort              |
| Alt+V    | Paste the latest DoxyEdit snapshot from clipboard |

All shortcuts require the compose field (or target input) to be
focused first - they fill whatever field has focus.

## Per-platform notes

| Platform     | Caption path                                | Image attach                              |
|--------------|---------------------------------------------|-------------------------------------------|
| Bluesky      | posts.bluesky (falls back to posts.x)       | Strategy 1 (existing input[type=file])    |
| X / Twitter  | posts.x or posts.twitter                    | Strategy 1 or 4 (click media button)      |
| Mastodon     | posts.mastodon (falls back to posts.x)      | Strategy 1 (matches form.compose-form)    |
| Threads      | posts.threads (falls back to posts.x)       | Strategy 4 (click media button)           |
| Reddit       | posts.reddit_<sub> with title + body split  | Strategy 1 (pick image from within modal) |
| Newgrounds   | posts.newgrounds                            | Strategy 1 (matches form[action*=upload]) |

Short-form platforms (Bluesky, Mastodon, Threads) fall back to the
twitter/x caption when no dedicated key exists. See
`doxyedit/psyai_data.py::_PLATFORM_CAPTION_FALLBACKS`.

## Troubleshooting

- **FAB is gray.** No transport reached this page. Press F6 in
  DoxyEdit. If green still doesn't light up, make sure Brave or
  Chrome was launched via "Launch Debug Browser" (port 9222).
- **Panel is empty / "no posts tagged for <host>".** DoxyEdit
  filters post buttons by hostname (`HOST_POST_TAGS` in the
  userscript). The post exists but isn't tagged for this platform.
  Tag the post for bluesky/x/etc in the composer.
- **Asset button does nothing.** Check DevTools console for
  "failed to fetch". The HTTP bridge serves asset bytes via
  `GM_xmlhttpRequest`; if the browser blocks it despite the
  `@connect 127.0.0.1` header, confirm the bridge is running
  (`http://127.0.0.1:8910/psyai.json` should return JSON).
- **Image opens OS file picker when attached.** Strategy 4 fires
  a click on the media button, which mounts the hidden input
  but also opens the native dialog as a side effect. The image
  still attaches; close the dialog with Escape.
