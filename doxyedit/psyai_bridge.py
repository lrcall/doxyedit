"""psyai_bridge.py — three transports from DoxyEdit to the userscript.

Each transport consumes the dict produced by
`psyai_data.build_psyai_data(project, composer_post)`. Running in
parallel is fine — the userscript picks whichever source is live.

Track A — CDP push:
    cdp_push(data) injects the dict as `window.__psyai_data` on the
    currently-open page in the Brave debug instance. Uses Playwright
    over the running CDP endpoint (http://localhost:9222 by default).

Track B — OS clipboard:
    copy_to_clipboard(data) writes a JSON blob with a magic marker
    (`_psyai_panel_v1`). The userscript's paste button recognizes the
    marker and unpacks.

Track C — Local HTTP server:
    start_http_server(port) runs a tiny stdlib `http.server` in a
    daemon thread that serves the current snapshot at GET /psyai.json
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
# Persistent file log — every bridge call appends here so failures
# are captured without depending on DoxyEdit's UI. Readable by the
# dev without screenshots. Path is stable so Claude / debuggers know
# where to look.
# ──────────────────────────────────────────────────────────────────
_LOG_PATH = os.path.join(
    tempfile.gettempdir(), "doxyedit_psyai_bridge.log")


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
PSYAI_PANEL_MARKER = "_psyai_panel_v1"


def _wrap_marker(data: dict, kind: str = "full") -> dict:
    """Add the marker + kind field that the userscript checks for."""
    return {PSYAI_PANEL_MARKER: True, "kind": kind, "payload": data}


# ──────────────────────────────────────────────────────────────────
# Track B — OS clipboard
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
# Track C — local HTTP server
# ──────────────────────────────────────────────────────────────────

class _PsyaiHTTPState:
    """Module-level container for the running server and its current
    payload bytes. `update_http_snapshot` swaps atomically under a
    lock so concurrent GETs never see a half-written JSON."""

    def __init__(self):
        self.snapshot_bytes: bytes = b'{"' + PSYAI_PANEL_MARKER.encode() + b'": true, "kind": "empty", "payload": {}}'
        self.lock = threading.Lock()
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.port: int = 0


_HTTP_STATE = _PsyaiHTTPState()


class _PsyaiHandler(BaseHTTPRequestHandler):
    """Single-endpoint handler that returns the current snapshot JSON.
    CORS wide-open so the userscript's GM_xmlhttpRequest (or a plain
    fetch from the browser page) can read cross-origin."""

    def do_GET(self):  # noqa: N802  (stdlib convention)
        if self.path in ("/psyai.json", "/"):
            with _HTTP_STATE.lock:
                body = _HTTP_STATE.snapshot_bytes
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002  (stdlib sig)
        # Suppress stdout spam — DoxyEdit logs via its own channel.
        return


def start_http_server(port: int = 0) -> int:
    """Spin up the server on 127.0.0.1. `port=0` asks the OS for a
    free port; the returned value is what the userscript should hit.
    Idempotent: a second call returns the already-running port."""
    if _HTTP_STATE.server is not None:
        return _HTTP_STATE.port
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), _PsyaiHandler)
        _HTTP_STATE.server = server
        _HTTP_STATE.port = server.server_address[1]
        thread = threading.Thread(
            target=server.serve_forever, daemon=True,
            name="psyai-http-bridge")
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


# ──────────────────────────────────────────────────────────────────
# Track A — CDP push via Playwright
# ──────────────────────────────────────────────────────────────────

def _cdp_push_worker(data: dict, cdp_url: str) -> tuple[bool, str]:
    """The actual Playwright work. Returns (ok, error_message).
    Split out from cdp_push so GUI callers can run it on a worker
    thread — sync_playwright blocks on a subprocess handshake and
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
        wrapped = _wrap_marker(data, "full")
        init_script = (
            "window.__psyai_data = " + json.dumps(wrapped) + ";"
            "window.dispatchEvent(new CustomEvent('psyai-data-updated', "
            "{detail: window.__psyai_data}));"
        )
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
    """Inject `data` as `window.__psyai_data` on every open page in
    the running Brave/Chrome debug instance. Also registers an init
    script so the data is present BEFORE userscripts run on future
    navigations — the psyai userscript reads on document-idle, so
    this is the only reliable delivery across page navigations.

    Runs Playwright synchronously (short-lived connection per call).
    Returns True on success. Failures (browser not running, network
    blocked, Playwright missing) return False without raising.

    Callers in Qt apps should NOT call this from the main GUI
    thread — use cdp_push_async or run on a QThreadPool worker so
    Playwright's event loop doesn't deadlock against the Qt loop.
    """
    ok, _err = _cdp_push_worker(data, cdp_url)
    return ok


def cdp_push_async(data: dict, on_done=None,
                   cdp_url: str = "http://127.0.0.1:9222") -> None:
    """Run cdp_push on a background thread via QThreadPool. Designed
    for GUI callers: never blocks the main loop, never deadlocks
    against Qt's async machinery. `on_done(ok: bool, err: str)` is
    invoked back on the thread pool worker — GUI updates inside the
    callback should re-marshal to the main thread (signal, or
    QMetaObject.invokeMethod with Qt.QueuedConnection).

    Short-lived push: each call spins up Playwright, pushes, tears
    down. Playwright clears init-script registrations on disconnect,
    so the data DIES on the next page navigation (F5 in the browser
    zeros window.__psyai_data). For persistence across F5, use
    persistent_push() / ensure_persistent_session() below."""
    try:
        from PySide6.QtCore import QRunnable, QThreadPool
    except Exception:
        # No Qt available (CLI / test context) — fall back to sync.
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
# Persistent CDP session — a dedicated daemon thread holds one
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


class _PsyaiPersistentSession:
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
            name="psyai-cdp-session")
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
        _log("persistent_session.start", cdp_url=self._cdp_url)
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            _log("persistent_session.no_playwright", error=repr(exc))
            self._drain_with_error(f"Playwright not installed: {exc!r}")
            return
        try:
            with sync_playwright() as pw:
                try:
                    browser = pw.chromium.connect_over_cdp(self._cdp_url)
                except Exception as exc:
                    _log("persistent_session.connect_failed",
                         error=repr(exc), traceback=traceback.format_exc())
                    self._drain_with_error(f"CDP connect failed: {exc!r}")
                    return
                self._connected = True
                _log("persistent_session.connected",
                     contexts=len(browser.contexts))
                try:
                    self._event_loop(browser)
                finally:
                    try:
                        browser.close()
                    except Exception:
                        pass
                    self._connected = False
                    _log("persistent_session.stop")
        except Exception as exc:
            _log("persistent_session.crashed",
                 error=repr(exc), traceback=traceback.format_exc())
            self._drain_with_error(f"Session crashed: {exc!r}")

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

    def _event_loop(self, browser):
        """Drain commands until stop. Each 'push' re-registers the
        init-script on every context and pushes live to every open
        page. Re-registering repeatedly IS wasteful — Playwright
        doesn't expose removeScriptToEvaluateOnNewDocument in its
        public sync API — but the duplicated scripts all set the
        same window.__psyai_data so the last one wins; the cost is
        memory per registered script, negligible for < 1000 pushes
        per session."""
        while not self._stop_event.is_set():
            try:
                cmd = self._cmd_queue.get(timeout=0.5)
            except Empty:
                continue
            ctype = cmd.get("type")
            if ctype == "stop":
                return
            if ctype != "push":
                continue
            data = cmd["data"]
            on_done = cmd["on_done"]
            wrapped = _wrap_marker(data, "full")
            init_script = (
                "window.__psyai_data = " + json.dumps(wrapped) + ";"
                "window.dispatchEvent(new CustomEvent("
                "'psyai-data-updated', {detail: window.__psyai_data}));"
            )
            self._latest_script = init_script
            pages_touched = 0
            err_msg = ""
            try:
                for context in browser.contexts:
                    context.add_init_script(init_script)
                    for page in context.pages:
                        try:
                            page.evaluate(init_script)
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


_persistent_session: Optional[_PsyaiPersistentSession] = None


def ensure_persistent_session(
        cdp_url: str = "http://127.0.0.1:9222") -> bool:
    """Start the persistent CDP session if not already running.
    Idempotent. Returns True when the thread is alive (doesn't
    guarantee CDP connected yet — the first push result indicates
    that)."""
    global _persistent_session
    if _persistent_session is None:
        _persistent_session = _PsyaiPersistentSession(cdp_url)
    if not (_persistent_session._thread
            and _persistent_session._thread.is_alive()):
        _persistent_session.start()
    return True


def persistent_push(data: dict, on_done=None,
                    cdp_url: str = "http://127.0.0.1:9222") -> None:
    """Push `data` through the persistent CDP session, starting it
    if needed. Init-script registrations survive page navigations
    for the life of the session — F5 keeps the green indicator."""
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
