# DoxyEdit Plugins

DoxyEdit supports user-authored Python plugins that run inside the
app and subscribe to lifecycle events. No pip, no rebuilds — drop
a `.py` file into `~/.doxyedit/plugins/` and it loads on next launch.

## Quickstart

1. Create the plugins folder if it doesn't exist:

   ```
   ~/.doxyedit/plugins/
   ```

2. Drop a `.py` file with a top-level `register(api)` callable:

   ```python
   # ~/.doxyedit/plugins/log_pushes.py

   def register(api):
       def on_push(post, platform, ok, detail):
           tag = "OK" if ok else "FAIL"
           api.log(f"{tag} push {post.id[:8]} -> {platform}: {detail}")
       api.on("post_pushed", on_push)
   ```

3. Restart DoxyEdit. The plugin loads automatically; messages from
   `api.log()` go to `~/.doxyedit/plugins.log`.

## Available events

| Event | Handler signature | Fired when |
|-------|-------------------|------------|
| `project_loaded` | `(project, project_path: str)` | Project finishes loading from disk (open or reload) |
| `post_pushed` | `(post, platform: str, ok: bool, detail: str)` | OneUp push completes for a single platform / sub-account |
| `asset_imported` | `(asset)` | A new asset just got added to the project (file import, paste, drag-drop) |
| `tag_changed` | `(tag_id: str, before: dict, after: dict)` | A tag definition was modified (color picked, parent set, etc). `before` and `after` are full tag_definitions dicts so handlers can diff what changed. |
| `post_saved` | `(post, is_new: bool)` | A SocialPost was saved from the composer (new draft or edit). `is_new` is True for first save, False for updates. |
| `shutdown` | `()` | MainWindow is closing — last chance to flush sockets, files, etc. |

More events will be added as the codebase exposes more hook points.
File a request with the lifecycle moment you want exposed.

## API reference

The `api` object passed to `register()` exposes:

- `api.on(event_name: str, handler: Callable)` - subscribe.
- `api.log(msg: str)` - write to `~/.doxyedit/plugins.log` with an
  ISO timestamp + the plugin's filename prefix. Survives across
  sessions (append mode).

## Failure handling

A plugin that raises during import or during a hook is **logged and
disabled for the rest of the session**. The host app keeps running.
The error and its traceback are written to `~/.doxyedit/plugins.log`
under a `[FAILED]` or `[LOAD FAILED]` heading.

This means:

- A buggy plugin can't crash DoxyEdit.
- Once a plugin fails on one call, its handlers don't fire again
  until the next launch (so you can fix the bug and try again
  without forming a noisy retry loop).

## Enabling and disabling plugins

Open **Help > Plugins...** to see every plugin file in the folder
plus its current status (`loaded`, `FAILED`, `disabled`). Each row
has a checkbox; uncheck to disable, check to enable. Disabled state
persists in QSettings under `plugins/disabled` (a comma-separated
list of plugin stems) and takes effect the next time the loader
runs (re-opening the dialog re-discovers, so toggling and re-opening
is enough to apply).

Use this to park a buggy plugin without deleting it, or to keep a
permanent on-disk plugin library and switch in just the ones you
want for the current project.

## Examples

### Auto-tag freshly-imported assets

```python
def register(api):
    def on_load(project, path):
        for asset in project.assets:
            if "review" not in asset.tags:
                asset.tags.append("review")
        api.log(f"Tagged {len(project.assets)} assets with 'review'")
    api.on("project_loaded", on_load)
```

### Slack webhook on push failure

```python
import json
from urllib.request import Request, urlopen

WEBHOOK = "https://hooks.slack.com/services/..."

def register(api):
    def on_push(post, platform, ok, detail):
        if ok:
            return
        body = json.dumps({
            "text": f"Push failed: {post.id[:8]} -> {platform}: {detail}"
        }).encode()
        try:
            urlopen(Request(WEBHOOK, data=body,
                            headers={"Content-Type": "application/json"}),
                    timeout=5)
        except Exception as e:
            api.log(f"slack webhook error: {e}")
    api.on("post_pushed", on_push)
```

### Reject posts with empty captions

```python
def register(api):
    def warn_empty(project, path):
        empty = [p for p in project.posts if not p.caption_default.strip()]
        if empty:
            api.log(f"WARNING: {len(empty)} post(s) have empty captions")
    api.on("project_loaded", warn_empty)
```

## Source layout

The plugin system lives in `doxyedit/plugins.py`. The `_PluginAPI`
sandbox + `_PluginRegistry` are private — public callers use:

- `doxyedit.plugins.discover_and_load()` — called once at MainWindow
  startup.
- `doxyedit.plugins.emit(event_name, *args)` — called by the host
  at lifecycle points.
- `doxyedit.plugins.loaded()` / `failed()` — list of currently-active
  vs disabled plugin names (useful for debugging).

To add a new event, find the lifecycle moment in `doxyedit/window.py`
or wherever the host triggers it and add `plugins.emit("name", ...)`.
The contract is: handler args are positional, host promises stable
ordering, host swallows any handler exception.
