"""bridge.py - three transports from DoxyEdit to the userscript.

Each transport consumes the dict produced by
`bridge_data.build_bridge_data(project, composer_post)`. Running in
parallel is fine - the userscript picks whichever source is live.

Track A - CDP push:
    cdp_push(data) injects the dict as `window.__bridge_data` on the
    currently-open page in the Brave debug instance. Uses Playwright
    over the running CDP endpoint (http://localhost:9222 by default).

Track B - OS clipboard:
    copy_to_clipboard(data) writes a JSON blob with a magic marker
    (`_bridge_panel_v1`). The userscript's paste button recognizes the
    marker and unpacks.

Track C - Local HTTP server:
    start_http_server(port) runs a tiny stdlib `http.server` in a
    daemon thread that serves the current snapshot at GET /doxyedit.json
    with CORS headers. `update_http_snapshot(data)` atomically swaps
    the bytes the next request returns.

All three are best-effort: a failure in any transport doesn't raise;
callers get a bool indicating success.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional


# ──────────────────────────────────────────────────────────────────
# Persistent file log - every bridge call appends here so failures
# are captured without depending on DoxyEdit's UI. Readable by the
# dev without screenshots. Path is stable so Claude / debuggers know
# where to look.
# ──────────────────────────────────────────────────────────────────
_LOG_PATH = os.path.join(
    tempfile.gettempdir(), "doxyedit_bridge.log")


def _log(event: str, **fields) -> None:
    """Append one line of JSON to the bridge log. Never raises."""
    try:
        payload = {"t": round(time.time(), 3), "event": event}
        payload.update(fields)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def bridge_log_path() -> str:
    """Return the bridge log file path. UI callers can surface this
    so the user can share / inspect it."""
    return _LOG_PATH


# ──────────────────────────────────────────────────────────────────
# Shared magic marker. Userscript looks for this key so it doesn't
# clobber random clipboard contents or random HTTP responses with
# DoxyEdit data.
# ──────────────────────────────────────────────────────────────────
DOXYEDIT_PANEL_MARKER = "_bridge_panel_v1"


def _wrap_marker(data: dict, kind: str = "full") -> dict:
    """Add the marker + kind field that the userscript checks for."""
    return {DOXYEDIT_PANEL_MARKER: True, "kind": kind, "payload": data}


def _build_init_script(data: dict) -> str:
    """Render the JS the CDP push / persistent session / worker
    subprocess all inject: assigns `window.__bridge_data` and fires
    a custom event so the userscript reapplies without polling."""
    wrapped = _wrap_marker(data, "full")
    return (
        "window.__bridge_data = " + json.dumps(wrapped) + ";"
        "window.dispatchEvent(new CustomEvent("
        "'doxyedit-data-updated', {detail: window.__bridge_data}));"
    )


# ──────────────────────────────────────────────────────────────────
# Track B - OS clipboard
# ──────────────────────────────────────────────────────────────────

def copy_to_clipboard(data: dict, kind: str = "full") -> bool:
    """Serialize `data` as JSON and write to the OS clipboard via Qt.
    Returns True on success. Tolerates Qt not being available so this
    module imports cleanly in tests without a QApplication."""
    try:
        from PySide6.QtGui import QGuiApplication
    except Exception:
        return False
    app = QGuiApplication.instance()
    if app is None:
        return False
    try:
        blob = json.dumps(_wrap_marker(data, kind), ensure_ascii=False)
        app.clipboard().setText(blob)
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────
# Track C - local HTTP server
# ──────────────────────────────────────────────────────────────────

class _BridgeHTTPState:
    """Module-level container for the running server and its current
    payload bytes. `update_http_snapshot` swaps atomically under a
    lock so concurrent GETs never see a half-written JSON.

    asset_registry maps asset_id -> (abs_path, mime) so the
    /doxyedit-asset endpoint can stream image bytes the userscript
    turns into Files for one-click attach."""

    def __init__(self):
        self.snapshot_bytes: bytes = b'{"' + DOXYEDIT_PANEL_MARKER.encode() + b'": true, "kind": "empty", "payload": {}}'
        self.lock = threading.Lock()
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.port: int = 0
        self.asset_registry: dict = {}
        # Userscript feedback events queued for whatever's listening.
        # Shape per entry: {"t": epoch, "type": str, "...": ...}. The
        # in-DoxyEdit consumer (future Socials-tab reminder panel)
        # drains this list via drain_feedback(). Keeping it at the
        # HTTP state so browser POSTs and Python UI share one list.
        self.feedback: list = []
        # Per-platform API credentials populated by the main window
        # from the active project's CollectionIdentity.credentials. Lets
        # /doxyedit-api-post resolve creds when the caller (userscript
        # or UI button) doesn't pass them explicitly. Shape:
        # platform_id -> {"handle": ..., "app_password": ...} etc.
        self.credentials: dict = {}


_HTTP_STATE = _BridgeHTTPState()


_ASSET_REGISTRY_MAX = 500


def register_asset(asset_id: str, path: str) -> dict:
    """Whitelist a local file to be served via /doxyedit-asset?id=<id>.
    Returns a descriptor {id, name, url, mime} the data builder can
    embed in the payload so the userscript knows what to fetch.

    Bounded at _ASSET_REGISTRY_MAX entries via FIFO eviction so a
    long-running session that touches thousands of distinct assets
    doesn't grow the registry without bound."""
    import mimetypes
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with _HTTP_STATE.lock:
        # Re-registering the same id refreshes its position; new ids
        # past the cap evict the oldest entry (insertion order in
        # py3.7+ dict). Cheap enough that the data builder calling
        # this on every F6 push doesn't notice.
        if asset_id in _HTTP_STATE.asset_registry:
            del _HTTP_STATE.asset_registry[asset_id]
        elif len(_HTTP_STATE.asset_registry) >= _ASSET_REGISTRY_MAX:
            oldest = next(iter(_HTTP_STATE.asset_registry))
            del _HTTP_STATE.asset_registry[oldest]
        _HTTP_STATE.asset_registry[asset_id] = (path, mime)
    port = _HTTP_STATE.port or 8910
    return {
        "id": asset_id,
        "name": os.path.basename(path),
        "url": f"http://127.0.0.1:{port}/doxyedit-asset?id={asset_id}",
        "mime": mime,
    }


def register_assets_bulk(items: list) -> list:
    """items = [(asset_id, path), ...]. Skips missing files."""
    out = []
    for asset_id, path in items:
        if not path or not os.path.exists(path):
            continue
        out.append(register_asset(asset_id, path))
    return out


def set_credentials(creds_by_platform: dict) -> None:
    """Replace the bridge's per-platform credential map. Called by the
    main window after a project loads; the new map shadows whatever
    was there before. Safe to call with {} to clear."""
    with _HTTP_STATE.lock:
        _HTTP_STATE.credentials = dict(creds_by_platform or {})


def _userscript_path() -> Optional[str]:
    """Absolute path to the bundled doxyedit-autofill.user.js. Resolves
    relative to this file so it works regardless of CWD. Returns
    None if the file isn't where we expect (e.g., a Nuitka onefile
    build that didn't include docs/)."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    candidate = os.path.join(root, "docs", "userscripts",
                              "doxyedit-autofill.user.js")
    return candidate if os.path.exists(candidate) else None


class _BridgeHandler(BaseHTTPRequestHandler):
    """Two-endpoint HTTP bridge.

    GET /doxyedit.json   -> latest identity + posts snapshot (JSON).
    GET /doxyedit-autofill.user.js
                      -> bundled Tampermonkey userscript. Wired as
                         @updateURL on the userscript itself so
                         Tampermonkey's "Check for updates" pulls
                         the LOCAL file - edits to the checkout are
                         picked up without a GitHub round-trip.

    CORS wide-open so the userscript's GM_xmlhttpRequest (or a plain
    fetch from the browser page) can read cross-origin."""

    def _send_bytes(self, body, content_type, methods="GET, OPTIONS",
                    cache="no-store"):
        """Reply with body + standard CORS + Content-Length headers."""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", methods)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_status(self, status):
        """Empty reply with just a status code + CORS origin. Used for
        404 / 500 paths where there's no body to write."""
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):  # noqa: N802  (stdlib convention)
        if self.path in ("/doxyedit.json", "/"):
            with _HTTP_STATE.lock:
                body = _HTTP_STATE.snapshot_bytes
            self._send_bytes(body, "application/json; charset=utf-8")
            return
        if self.path.startswith("/doxyedit-asset"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            asset_id = (qs.get("id") or [""])[0]
            with _HTTP_STATE.lock:
                entry = _HTTP_STATE.asset_registry.get(asset_id)
            if entry is None:
                self._send_status(404)
                return
            path, mime = entry
            try:
                with open(path, "rb") as f:
                    body = f.read()
            except Exception:
                self._send_status(500)
                return
            self._send_bytes(body, mime, cache="public, max-age=3600")
            return
        if self.path == "/doxyedit-autofill.user.js":
            us_path = _userscript_path()
            if us_path is None:
                self._send_status(404)
                return
            try:
                with open(us_path, "rb") as f:
                    body = f.read()
            except Exception:
                self._send_status(500)
                return
            # Tampermonkey needs text/javascript (NOT
            # application/javascript) to recognize the install
            # banner on page load.
            self._send_bytes(body, "text/javascript; charset=utf-8")
            return
        self._send_status(404)

    def do_POST(self):  # noqa: N802
        if self.path == "/doxyedit-api-post":
            # API-direct posting bypassing the userscript+browser DOM. Body:
            #   {platformKey: "bluesky"|"mastodon",
            #    text: str,
            #    parent_url?: str (for replies; omit for top-level),
            #    credentials: {handle, app_password} | {instance, access_token},
            #    asset_ids?: [str] (DoxyEdit asset registry ids; resolved
            #                       to bytes locally and uploaded as
            #                       images/media via the platform API)}
            # Returns {ok: true, url: str} or {ok: false, error: str}.
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body_in = json.loads(raw.decode("utf-8") or "{}")
            except Exception as exc:
                self._send_bytes(
                    json.dumps({"ok": False, "error": f"bad json: {exc!r}"}).encode(),
                    "application/json; charset=utf-8",
                    methods="POST, OPTIONS")
                return
            plat = (body_in.get("platformKey") or "").lower()
            text = body_in.get("text") or ""
            parent_url = body_in.get("parent_url") or ""
            creds = body_in.get("credentials") or {}
            # Fallback: userscript and quickpost callers don't carry
            # credentials in the body (the main window does). Resolve
            # from the bridge-side map populated at project load. Both
            # bluesky and bsky map to the same slot so /doxyedit-api-post
            # callers can use either platformKey.
            if not creds:
                with _HTTP_STATE.lock:
                    stored = _HTTP_STATE.credentials
                    creds = dict(stored.get(plat) or {})
                    if not creds and plat in ("bluesky", "bsky"):
                        creds = dict(stored.get("bsky") or
                                      stored.get("bluesky") or {})
            # Resolve asset_ids -> [(bytes, mime, alt)] using the
            # registry the userscript bridge already populates. Top-
            # level posts that include images go through the platform's
            # blob upload before record creation.
            asset_ids = body_in.get("asset_ids") or []
            images: list = []
            for aid in asset_ids[:4]:  # API caps usually 4 images
                with _HTTP_STATE.lock:
                    entry = _HTTP_STATE.asset_registry.get(aid)
                if not entry:
                    continue
                path, mime = entry
                try:
                    with open(path, "rb") as f:
                        images.append((f.read(), mime, ""))
                except Exception:
                    continue
            try:
                if plat in ("bluesky", "bsky"):
                    from doxyedit.platforms import bluesky as _bsky
                    session = _bsky.create_session(
                        creds["handle"], creds["app_password"])
                    if parent_url:
                        result = _bsky.post_reply(session, parent_url, text)
                        url = result.get("uri", "")
                    else:
                        result = _bsky.create_post(session, text,
                                                    images=images or None)
                        url = _bsky.post_url_for(session, result)
                    out = {"ok": True, "url": url, "platform": "bluesky"}
                elif plat == "mastodon":
                    from doxyedit.platforms import mastodon as _masto
                    if parent_url:
                        result = _masto.post_reply(creds, parent_url, text)
                    else:
                        result = _masto.create_post(creds, text,
                                                     images=images or None)
                    out = {"ok": True, "url": result.get("url", ""),
                           "platform": "mastodon"}
                else:
                    out = {"ok": False,
                           "error": f"no API client for platform: {plat}"}
            except Exception as exc:
                _log("api_post.failed", platform=plat, error=repr(exc)[:300])
                out = {"ok": False, "error": repr(exc)[:300]}
            # Distinguish three log states: the no-exception success path
            # (ok=True), the no-exception unsupported-platform path
            # (ok=False, no client found), and the exception path (already
            # logged above). Previously the try/except/else pattern logged
            # api_post.ok for the unsupported branch because no exception
            # was raised, mislabeling refusals as successes in the log.
            if out.get("ok"):
                _log("api_post.ok", platform=plat,
                     url=out.get("url", "")[:200])
            elif "error" in out and "no API client" in out.get("error", ""):
                _log("api_post.unsupported", platform=plat)
            self._send_bytes(
                json.dumps(out).encode(),
                "application/json; charset=utf-8",
                methods="POST, OPTIONS")
            return
        if self.path == "/doxyedit-log":
            # Userscript-side diagnostics. Lands in the same
            # doxyedit_bridge.log file everything else writes to so
            # headless test runs and remote-assist sessions can see
            # browser-side errors without opening DevTools.
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                data = {"_raw": raw.decode("utf-8", errors="replace")[:500]}
            level = str(data.get("level", "info")).lower()
            _log(
                "userscript." + level,
                msg=str(data.get("message", ""))[:500],
                url=str(data.get("url", ""))[:300],
                detail=str(data.get("detail", ""))[:500],
            )
            self._send_bytes(b'{"ok":true}',
                             "application/json; charset=utf-8",
                             methods="POST, OPTIONS")
            return
        if self.path == "/doxyedit-feedback":
            import time
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                payload = {"_raw": raw.decode("utf-8", errors="replace")[:500]}
            entry = {"t": time.time(), **(payload if isinstance(payload, dict) else {"payload": payload})}
            with _HTTP_STATE.lock:
                _HTTP_STATE.feedback.append(entry)
                # Bound the queue so a runaway userscript can't OOM us.
                if len(_HTTP_STATE.feedback) > 1000:
                    _HTTP_STATE.feedback = _HTTP_STATE.feedback[-1000:]
            _log("feedback.received",
                 type=entry.get("type"), host=entry.get("host"))
            self._send_bytes(b'{"ok":true}',
                             "application/json; charset=utf-8",
                             methods="POST, OPTIONS")
            return
        if self.path == "/doxyedit-dom-result":
            # Per-attempt transport result reporting. The userscript's
            # POST NOW dispatcher walks a priority list (api -> dom-paste
            # -> dom-click -> drag -> native) and POSTs one of these on
            # every attempt so we can see, in the bridge log, exactly
            # which transport won and which steps failed before we
            # fell through. Body shape:
            #   {platformKey, transport, outcome, step?, error?,
            #    durationMs?}
            # outcome is one of: "ok", "failed", "skipped". The per-
            # platform transport (api / dom-paste / drag / native) lives
            # in `transport`. Logged as dom_result.<outcome> so log
            # filters can split successes from failures cheaply.
            import time
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                payload = {"_raw": raw.decode("utf-8", errors="replace")[:500]}
            entry = {"t": time.time(),
                     **(payload if isinstance(payload, dict)
                        else {"payload": payload})}
            with _HTTP_STATE.lock:
                _HTTP_STATE.feedback.append(
                    {**entry, "type": "transport_result"})
                if len(_HTTP_STATE.feedback) > 1000:
                    _HTTP_STATE.feedback = _HTTP_STATE.feedback[-1000:]
            outcome = str(entry.get("outcome") or "unknown")[:32]
            _log(
                "dom_result." + outcome,
                platform=str(entry.get("platformKey") or "")[:64],
                transport=str(entry.get("transport") or "")[:32],
                step=str(entry.get("step") or "")[:120],
                error=str(entry.get("error") or "")[:200],
                durationMs=entry.get("durationMs"),
            )
            self._send_bytes(b'{"ok":true}',
                             "application/json; charset=utf-8",
                             methods="POST, OPTIONS")
            return
        if self.path == "/doxyedit-native-input":
            # OS-level input fallback. The dispatcher's `native` rung
            # POSTs here when API + DOM + drag all refused. pyautogui
            # is an optional dep; available()=False on installs that
            # didn't pip install it, in which case typed/clicked
            # actions return ok=false with a clear "unavailable" error
            # so the userscript records the skip cleanly rather than
            # paying a traceback.
            #
            # Body shape:
            #   action: "probe" | "type" | "click" | "paste"
            #   text?: str       (type / paste)
            #   delay_ms?: int   (type, per-character delay)
            #   x?, y?: int      (click, screen coords)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            action = str(payload.get("action") or "probe").lower()
            try:
                from doxyedit.platforms import native_input as _ni
            except Exception as exc:
                out = {"ok": False,
                       "error": "native_input import: " + repr(exc)[:200]}
            else:
                try:
                    if action == "probe":
                        out = {"ok": True, "available": _ni.available()}
                    elif action == "type":
                        _ni.type_text(
                            payload.get("text") or "",
                            int(payload.get("delay_ms") or 20))
                        out = {"ok": True}
                    elif action == "click":
                        _ni.click_at(
                            int(payload.get("x") or 0),
                            int(payload.get("y") or 0))
                        out = {"ok": True}
                    elif action == "paste":
                        _ni.paste_text(payload.get("text") or "")
                        out = {"ok": True}
                    else:
                        out = {"ok": False,
                               "error": "unknown action: " + action}
                except _ni.NativeInputUnavailable as exc:
                    out = {"ok": False, "error": str(exc),
                           "unavailable": True}
                except Exception as exc:
                    out = {"ok": False,
                           "error": repr(exc)[:200]}
            _log("native_input." + action,
                 ok=out.get("ok"),
                 available=out.get("available"),
                 error=str(out.get("error", ""))[:200])
            self._send_bytes(
                json.dumps(out).encode(),
                "application/json; charset=utf-8",
                methods="POST, OPTIONS")
            return
        self._send_status(404)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002  (stdlib sig)
        # Suppress stdout spam - DoxyEdit logs via its own channel.
        return


def start_http_server(port: int = 0) -> int:
    """Spin up the server on 127.0.0.1. `port=0` asks the OS for a
    free port; the returned value is what the userscript should hit.
    Idempotent: a second call returns the already-running port."""
    if _HTTP_STATE.server is not None:
        return _HTTP_STATE.port
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), _BridgeHandler)
        _HTTP_STATE.server = server
        _HTTP_STATE.port = server.server_address[1]
        thread = threading.Thread(
            target=server.serve_forever, daemon=True,
            name="bridge-http-bridge")
        thread.start()
        _HTTP_STATE.thread = thread
        return _HTTP_STATE.port
    except Exception:
        return 0


def stop_http_server() -> None:
    """Shut down the server if running. Safe to call multiple times."""
    srv = _HTTP_STATE.server
    if srv is None:
        return
    try:
        srv.shutdown()
        srv.server_close()
    except Exception:
        pass
    _HTTP_STATE.server = None
    _HTTP_STATE.thread = None
    _HTTP_STATE.port = 0


def update_http_snapshot(data: dict) -> None:
    """Replace the snapshot bytes served by the next GET."""
    try:
        blob = json.dumps(_wrap_marker(data, "full"), ensure_ascii=False)
    except Exception:
        return
    with _HTTP_STATE.lock:
        _HTTP_STATE.snapshot_bytes = blob.encode("utf-8")


def http_bridge_port() -> int:
    """Return the currently-running HTTP bridge port, 0 if not up."""
    return _HTTP_STATE.port


def drain_feedback() -> list:
    """Pop all userscript-feedback entries and return them. The
    Socials-tab poller calls this to render reminders/engagement
    updates from the browser side. Thread-safe."""
    with _HTTP_STATE.lock:
        events = _HTTP_STATE.feedback
        _HTTP_STATE.feedback = []
    return events


def peek_feedback() -> list:
    """Non-destructive read of the current feedback queue. Useful
    for tests and for a 'how many pending?' indicator on the
    Socials tab. Returns a shallow copy."""
    with _HTTP_STATE.lock:
        return list(_HTTP_STATE.feedback)


# ──────────────────────────────────────────────────────────────────
# Track A - CDP push via Playwright
# ──────────────────────────────────────────────────────────────────

def _cdp_push_worker(data: dict, cdp_url: str) -> tuple[bool, str]:
    """The actual Playwright work. Returns (ok, error_message).
    Split out from cdp_push so GUI callers can run it on a worker
    thread - sync_playwright blocks on a subprocess handshake and
    needs its own event loop, which collides with Qt's main loop
    if called directly from the GUI thread."""
    _log("cdp_push.begin",
         cdp_url=cdp_url, python=sys.executable,
         post_count=len((data or {}).get("posts") or {}))
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        err = f"Playwright not installed: {exc!r}"
        _log("cdp_push.no_playwright", error=err,
             python=sys.executable, sys_path_head=sys.path[:3])
        return False, err
    try:
        init_script = _build_init_script(data)
        pages_touched = 0
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            try:
                for context in browser.contexts:
                    context.add_init_script(init_script)
                    for page in context.pages:
                        try:
                            page.evaluate(init_script)
                            pages_touched += 1
                        except Exception:
                            continue
            finally:
                browser.close()
        _log("cdp_push.ok", pages_touched=pages_touched)
        return True, ""
    except Exception as exc:
        _log("cdp_push.failed",
             error=repr(exc), traceback=traceback.format_exc())
        return False, repr(exc)


def cdp_push(data: dict, cdp_url: str = "http://127.0.0.1:9222") -> bool:
    """Inject `data` as `window.__bridge_data` on every open page in
    the running Brave/Chrome debug instance. Also registers an init
    script so the data is present BEFORE userscripts run on future
    navigations - the bridge userscript reads on document-idle, so
    this is the only reliable delivery across page navigations.

    Runs Playwright synchronously (short-lived connection per call).
    Returns True on success. Failures (browser not running, network
    blocked, Playwright missing) return False without raising.

    Callers in Qt apps should NOT call this from the main GUI
    thread - use cdp_push_async or run on a QThreadPool worker so
    Playwright's event loop doesn't deadlock against the Qt loop.
    """
    ok, _err = _cdp_push_worker(data, cdp_url)
    return ok


def cdp_push_async(data: dict, on_done=None,
                   cdp_url: str = "http://127.0.0.1:9222") -> None:
    """Run cdp_push on a background thread via QThreadPool. Designed
    for GUI callers: never blocks the main loop, never deadlocks
    against Qt's async machinery. `on_done(ok: bool, err: str)` is
    invoked back on the thread pool worker - GUI updates inside the
    callback should re-marshal to the main thread (signal, or
    QMetaObject.invokeMethod with Qt.QueuedConnection).

    Short-lived push: each call spins up Playwright, pushes, tears
    down. Playwright clears init-script registrations on disconnect,
    so the data DIES on the next page navigation (F5 in the browser
    zeros window.__bridge_data). For persistence across F5, use
    persistent_push() / ensure_persistent_session() below."""
    try:
        from PySide6.QtCore import QRunnable, QThreadPool
    except Exception:
        # No Qt available (CLI / test context) - fall back to sync.
        ok, err = _cdp_push_worker(data, cdp_url)
        if on_done:
            on_done(ok, err)
        return

    class _Runner(QRunnable):
        def __init__(self):
            super().__init__()
            self.setAutoDelete(True)

        def run(self):
            ok, err = _cdp_push_worker(data, cdp_url)
            if on_done:
                try:
                    on_done(ok, err)
                except Exception:
                    pass

    QThreadPool.globalInstance().start(_Runner())


# ──────────────────────────────────────────────────────────────────
# Persistent CDP session - a dedicated daemon thread holds one
# sync_playwright instance open for as long as DoxyEdit runs so
# init-script registrations survive page navigations (F5 keeps the
# data). Short-lived cdp_push clears those on every call because
# Playwright tears down registrations on disconnect.
#
# Usage:
#   ensure_persistent_session()              # idempotent start
#   persistent_push(data, on_done)           # queues a push; thread
#                                            # applies + keeps the
#                                            # init-script live
#   stop_persistent_session()                # shut down on exit
#
# Thread comms via queue.Queue: the main thread posts commands
# ('push' | 'stop'); the worker drains, talks to Playwright, emits
# result via done callback.
# ──────────────────────────────────────────────────────────────────

from queue import Queue, Empty


class _BridgePersistentSession:
    def __init__(self, cdp_url: str = "http://127.0.0.1:9222"):
        self._cdp_url = cdp_url
        self._cmd_queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest_script: str = ""
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True,
            name="bridge-cdp-session")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._cmd_queue.put({"type": "stop"})
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def push(self, data: dict, on_done=None) -> None:
        """Queue a push. on_done(ok, err) fires from the worker thread."""
        self._cmd_queue.put({
            "type": "push",
            "data": data,
            "on_done": on_done or (lambda ok, err: None),
        })

    def _run(self):
        """Worker-thread entry. Drives Playwright's ASYNC API via a
        dedicated asyncio event loop owned by this thread.

        Sync API would've been simpler but is hard-locked to the
        main thread (greenlet signal-handler setup).

        On Windows the loop MUST be a ProactorEventLoop because
        Playwright spawns a node subprocess for its driver. Qt /
        PySide6 sometimes flips the default policy to
        WindowsSelectorEventLoopPolicy, which would make
        asyncio.new_event_loop() return a SelectorEventLoop - that
        one can't spawn subprocesses and the driver connect fails
        with 'Connection closed while reading from the driver' the
        moment async_playwright() tries to start node.

        Instantiating ProactorEventLoop directly bypasses whatever
        policy the main thread installed."""
        _log("persistent_session.start", cdp_url=self._cdp_url,
             python=sys.executable, platform=sys.platform)
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            _log("persistent_session.no_playwright", error=repr(exc))
            self._drain_with_error(f"Playwright not installed: {exc!r}")
            return
        import asyncio
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
            _log("persistent_session.loop_kind", kind="ProactorEventLoop")
        else:
            loop = asyncio.new_event_loop()
            _log("persistent_session.loop_kind",
                 kind=type(loop).__name__)
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                self._async_main(async_playwright))
        except Exception as exc:
            _log("persistent_session.crashed",
                 error=repr(exc), traceback=traceback.format_exc())
            self._drain_with_error(f"Session crashed: {exc!r}")
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _async_main(self, async_playwright):
        """Own the Playwright lifecycle on this thread's loop."""
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.connect_over_cdp(
                    self._cdp_url)
            except Exception as exc:
                _log("persistent_session.connect_failed",
                     error=repr(exc), traceback=traceback.format_exc())
                self._drain_with_error(f"CDP connect failed: {exc!r}")
                return
            self._connected = True
            _log("persistent_session.connected",
                 contexts=len(browser.contexts))
            try:
                await self._async_event_loop(browser)
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
                self._connected = False
                _log("persistent_session.stop")

    def _drain_with_error(self, err: str):
        """Reply to every queued push with the same error so callers
        don't wait forever on a broken session."""
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
            except Empty:
                break
            if cmd.get("type") == "push":
                try:
                    cmd["on_done"](False, err)
                except Exception:
                    pass

    async def _async_event_loop(self, browser):
        """Async drain of the command queue. Each 'push' re-registers
        the init-script on every context + pushes live to every open
        page. Re-registering repeatedly is wasteful but Playwright's
        async API doesn't expose remove_init_script either; the
        duplicated scripts all set the same window.__bridge_data so
        the last registration wins, and registered scripts are
        per-context memory only (<1KB each). Queue polled with a
        short sleep so the asyncio loop stays responsive to stop."""
        import asyncio
        while not self._stop_event.is_set():
            try:
                cmd = self._cmd_queue.get_nowait()
            except Empty:
                await asyncio.sleep(0.1)
                continue
            ctype = cmd.get("type")
            if ctype == "stop":
                return
            if ctype != "push":
                continue
            data = cmd["data"]
            on_done = cmd["on_done"]
            init_script = _build_init_script(data)
            self._latest_script = init_script
            pages_touched = 0
            err_msg = ""
            try:
                for context in browser.contexts:
                    await context.add_init_script(init_script)
                    for page in context.pages:
                        try:
                            await page.evaluate(init_script)
                            pages_touched += 1
                        except Exception:
                            continue
                _log("persistent_session.push_ok",
                     pages_touched=pages_touched)
            except Exception as exc:
                err_msg = repr(exc)
                _log("persistent_session.push_failed",
                     error=err_msg, traceback=traceback.format_exc())
            try:
                on_done(not err_msg, err_msg)
            except Exception:
                pass


_persistent_session: Optional[_BridgePersistentSession] = None


def ensure_persistent_session(
        cdp_url: str = "http://127.0.0.1:9222") -> bool:
    """Start the persistent CDP session if not already running.
    Idempotent. Returns True when the thread is alive (doesn't
    guarantee CDP connected yet - the first push result indicates
    that)."""
    global _persistent_session
    if _persistent_session is None:
        _persistent_session = _BridgePersistentSession(cdp_url)
    if not (_persistent_session._thread
            and _persistent_session._thread.is_alive()):
        _persistent_session.start()
    return True


def persistent_push(data: dict, on_done=None,
                    cdp_url: str = "http://127.0.0.1:9222") -> None:
    """Push `data` through the persistent CDP session, starting it
    if needed. Init-script registrations survive page navigations
    for the life of the session - F5 keeps the green indicator."""
    ensure_persistent_session(cdp_url)
    assert _persistent_session is not None
    _persistent_session.push(data, on_done)


def stop_persistent_session() -> None:
    """Tear down the persistent session. Called on app exit so the
    daemon thread doesn't outlive Qt."""
    global _persistent_session
    if _persistent_session is not None:
        _persistent_session.stop()
        _persistent_session = None


def persistent_session_connected() -> bool:
    """True iff the persistent session's Playwright connection is
    currently live. Useful for UI status indicators."""
    return bool(_persistent_session and _persistent_session.connected)


# ──────────────────────────────────────────────────────────────────
# Worker subprocess - Playwright in a SEPARATE Python process.
#
# In-process async Playwright collides with Qt/PySide6's asyncio
# state on Python 3.11 (driver subprocess pipe handles get corrupted
# by Qt's main-thread asyncio setup; every connect fails with
# "Connection closed while reading from the driver"). Running
# Playwright in a clean interpreter avoids the whole class of
# interference and keeps the init-script registered for the life of
# the subprocess (F5 keeps the userscript green).
#
# Protocol: newline-delimited JSON over stdin/stdout. See
# doxyedit.bridge_worker for the worker side.
# ──────────────────────────────────────────────────────────────────

import subprocess


class _BridgeWorkerProcess:
    def __init__(self, cdp_url: str = "http://127.0.0.1:9222"):
        self._cdp_url = cdp_url
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._stdout_thread: Optional[threading.Thread] = None
        # Callbacks waiting for the next response. Order-preserving
        # deque - worker replies in-order per push.
        from collections import deque
        self._pending: deque = deque()
        self._pending_lock = threading.Lock()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected and self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            _log("worker.spawn", python=sys.executable)
            try:
                self._proc = subprocess.Popen(
                    [sys.executable, "-m", "doxyedit.bridge_worker"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    # CREATE_NO_WINDOW on Windows so the helper
                    # doesn't flash a console window (0x08000000).
                    creationflags=(0x08000000
                                   if sys.platform == "win32" else 0),
                    text=True,
                    encoding="utf-8",
                    bufsize=1,  # line-buffered
                )
                _log("worker.spawned", pid=self._proc.pid)
            except Exception as exc:
                _log("worker.spawn_failed",
                     error=repr(exc), traceback=traceback.format_exc())
                self._proc = None
                return
            self._connected = True
            self._stdout_thread = threading.Thread(
                target=self._stdout_loop, daemon=True,
                name="bridge-worker-stdout")
            self._stdout_thread.start()
            # Drain stderr so Playwright / Python warnings that bypass
            # the JSON protocol can't fill the 64 KiB pipe buffer and
            # block the worker mid-command.
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop, daemon=True,
                name="bridge-worker-stderr")
            self._stderr_thread.start()

    def _stderr_loop(self) -> None:
        """Drain the worker's stderr. Each non-empty line is logged
        so tracebacks that escape the JSON protocol still land in
        the persistent file log."""
        if self._proc is None or self._proc.stderr is None:
            return
        try:
            for line in self._proc.stderr:
                line = line.rstrip()
                if not line:
                    continue
                _log("worker.stderr", line=line[:500])
        except Exception as exc:
            _log("worker.stderr_loop_crashed", error=repr(exc))

    def _stdout_loop(self) -> None:
        """Read worker responses line-by-line; dispatch to pending
        callbacks in FIFO order."""
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    resp = json.loads(line)
                except Exception:
                    _log("worker.bad_response", raw=line[:200])
                    continue
                cb = None
                with self._pending_lock:
                    if self._pending:
                        cb = self._pending.popleft()
                if cb is not None:
                    try:
                        cb(bool(resp.get("ok")), resp.get("err") or "")
                    except Exception:
                        pass
                _log("worker.response",
                     ok=resp.get("ok"), err=resp.get("err"),
                     pages_touched=resp.get("pages_touched"))
        except Exception as exc:
            _log("worker.stdout_loop_crashed",
                 error=repr(exc), traceback=traceback.format_exc())
        finally:
            self._connected = False
            # Drain pending with a failure so no callback hangs.
            with self._pending_lock:
                while self._pending:
                    cb = self._pending.popleft()
                    try:
                        cb(False, "worker exited")
                    except Exception:
                        pass

    def push(self, data: dict, on_done=None) -> None:
        """Send a push command to the worker. on_done(ok, err) fires
        from the stdout reader thread when the response arrives."""
        if self._proc is None or self._proc.poll() is not None:
            self.start()
        if self._proc is None or self._proc.stdin is None:
            if on_done:
                on_done(False, "worker not running")
            return
        init_script = _build_init_script(data)
        cmd = {
            "cmd": "push",
            "cdp_url": self._cdp_url,
            "script": init_script,
        }
        with self._pending_lock:
            self._pending.append(on_done or (lambda ok, err: None))
        try:
            self._proc.stdin.write(json.dumps(cmd) + "\n")
            self._proc.stdin.flush()
        except Exception as exc:
            _log("worker.stdin_write_failed", error=repr(exc))
            # Roll back the callback we just enqueued.
            with self._pending_lock:
                try:
                    self._pending.pop()
                except IndexError:
                    pass
            if on_done:
                on_done(False, f"stdin write failed: {exc!r}")

    def stop(self) -> None:
        with self._lock:
            if self._proc is None:
                return
            if self._proc.poll() is None:
                try:
                    self._proc.stdin.write(json.dumps({"cmd": "stop"}) + "\n")
                    self._proc.stdin.flush()
                except Exception:
                    pass
                try:
                    self._proc.wait(timeout=3.0)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
            self._proc = None
            self._connected = False


_worker_process: Optional[_BridgeWorkerProcess] = None


def ensure_worker_process(
        cdp_url: str = "http://127.0.0.1:9222") -> bool:
    """Start the Playwright subprocess worker if not already running."""
    global _worker_process
    if _worker_process is None:
        _worker_process = _BridgeWorkerProcess(cdp_url)
    _worker_process.start()
    return _worker_process.connected


def worker_push(data: dict, on_done=None,
                cdp_url: str = "http://127.0.0.1:9222") -> None:
    """Push via the subprocess worker. Auto-starts the worker on
    first call. Persistent - init-script registrations live for the
    life of the subprocess, so F5 keeps the userscript green."""
    ensure_worker_process(cdp_url)
    assert _worker_process is not None
    _worker_process.push(data, on_done)


def stop_worker_process() -> None:
    """Tear down the subprocess on app exit."""
    global _worker_process
    if _worker_process is not None:
        _worker_process.stop()
        _worker_process = None


def worker_process_connected() -> bool:
    return bool(_worker_process and _worker_process.connected)


def worker_upload_files(
        files: list,
        selector: str = 'input[type="file"]',
        url_contains: str = "",
        on_done=None,
        cdp_url: str = "http://127.0.0.1:9222") -> None:
    """Upload local files into a file-input on one of the open
    debug-browser pages. Auto-starts the worker subprocess.

    files:        list of absolute paths to upload.
    selector:     CSS selector for the target input[type=file].
                  Default catches Bluesky, Mastodon, ko-fi and most
                  other platforms that use a hidden file input.
    url_contains: optional URL substring to narrow which page the
                  upload lands on. e.g. 'bsky.app' ensures Bluesky
                  gets the files even when reddit / twitter tabs
                  are also open with their own file inputs.

    on_done(ok: bool, err: str) fires when the worker replies."""
    ensure_worker_process(cdp_url)
    assert _worker_process is not None
    proc = _worker_process._proc
    if proc is None or proc.stdin is None or proc.poll() is not None:
        if on_done:
            on_done(False, "worker not running")
        return
    cmd = {
        "cmd": "upload_files",
        "cdp_url": cdp_url,
        "selector": selector,
        "files": list(files),
        "url_contains": url_contains,
    }
    with _worker_process._pending_lock:
        _worker_process._pending.append(on_done or (lambda ok, err: None))
    try:
        proc.stdin.write(json.dumps(cmd) + "\n")
        proc.stdin.flush()
    except Exception as exc:
        with _worker_process._pending_lock:
            try:
                _worker_process._pending.pop()
            except IndexError:
                pass
        if on_done:
            on_done(False, f"stdin write failed: {exc!r}")


# Module-level exit hook: MainWindow.closeEvent already tears these
# down, but it only runs on a clean Qt shutdown. Interpreter exits
# via sys.exit(), unhandled exceptions, or QApplication.quit without
# going through the main window all skip closeEvent and leave the
# worker subprocess, HTTP server thread, and persistent session
# running as zombies. Registering at the module level covers every
# path Python can exit through short of a hard crash.
import atexit as _atexit

def _bridge_atexit() -> None:
    for fn in (stop_worker_process, stop_persistent_session,
               stop_http_server):
        try:
            fn()
        except Exception:
            pass

_atexit.register(_bridge_atexit)
