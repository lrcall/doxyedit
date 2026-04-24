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
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional


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

def cdp_push(data: dict, cdp_url: str = "http://127.0.0.1:9222") -> bool:
    """Inject `data` as `window.__psyai_data` on every open page in
    the running Brave/Chrome debug instance. Also registers an init
    script so the data is present BEFORE userscripts run on future
    navigations — the psyai userscript reads on document-idle, so
    this is the only reliable delivery across page navigations.

    Runs Playwright synchronously (short-lived connection per call).
    Returns True on success. Failures (browser not running, network
    blocked, Playwright missing) return False without raising."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        # Magic-marker-wrapped payload so the userscript can
        # differentiate "live data from DoxyEdit" from "whatever else
        # set window.__psyai_data".
        wrapped = _wrap_marker(data, "full")
        init_script = (
            "window.__psyai_data = " + json.dumps(wrapped) + ";"
            "window.dispatchEvent(new CustomEvent('psyai-data-updated', "
            "{detail: window.__psyai_data}));"
        )
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            try:
                for context in browser.contexts:
                    # Future navigations see the data before any
                    # document-idle userscript fires.
                    context.add_init_script(init_script)
                    # Currently-open pages need the live injection.
                    for page in context.pages:
                        try:
                            page.evaluate(init_script)
                        except Exception:
                            # A closed / navigating page shouldn't
                            # abort the whole push.
                            continue
            finally:
                browser.close()
        return True
    except Exception:
        return False
