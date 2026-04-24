"""psyai_worker.py — long-lived Playwright subprocess for the CDP bridge.

Runs as a standalone Python process spawned by DoxyEdit
(subprocess.Popen). Reads newline-delimited JSON commands on stdin,
writes newline-delimited JSON responses on stdout.

Why a subprocess: async_playwright() inside DoxyEdit's process fails
with "Connection closed while reading from the driver" on Python 3.11
because Qt / PySide6's main-thread asyncio state corrupts the driver
subprocess's pipe handles. Running Playwright in a fresh interpreter
sidesteps every Qt-related interference.

Protocol (one JSON object per line on both streams):

  -> stdin   {"cmd": "push", "cdp_url": "...", "data": {...}}
  <- stdout  {"ok": true, "pages_touched": 7}

  -> stdin   {"cmd": "stop"}
  <- stdout  {"ok": true}   then the worker exits

  <- stdout  {"ok": false, "err": "repr(exc)"}    on errors

The long-lived Playwright connection means add_init_script
registrations survive for the life of the subprocess, so F5 in the
debug browser keeps the userscript green until DoxyEdit closes.
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback


async def _main():
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover
        _emit({"ok": False, "err": f"Playwright not installed: {exc!r}"})
        return

    loop = asyncio.get_event_loop()
    # Protocol driver: reads stdin, queues commands; main async task
    # processes them and holds the Playwright connection open.
    command_queue: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()

    def _reader_thread():
        """Blocking readline loop on a thread executor — pushing each
        parsed command into the async queue. Using a thread instead
        of loop.add_reader on stdin because Windows asyncio has no
        add_reader for pipes (only sockets)."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except Exception:
                asyncio.run_coroutine_threadsafe(
                    command_queue.put(
                        {"cmd": "_bad_json", "raw": line}),
                    loop)
                continue
            asyncio.run_coroutine_threadsafe(
                command_queue.put(cmd), loop)
        # EOF on stdin — treat as stop request.
        asyncio.run_coroutine_threadsafe(
            command_queue.put({"cmd": "stop"}), loop)

    import threading
    threading.Thread(target=_reader_thread, daemon=True,
                     name="psyai-worker-stdin").start()

    browser = None
    async with async_playwright() as pw:
        while not stop_event.is_set():
            cmd = await command_queue.get()
            ctype = cmd.get("cmd")
            if ctype == "stop":
                _emit({"ok": True})
                stop_event.set()
                break
            if ctype == "_bad_json":
                _emit({"ok": False, "err": f"bad json: {cmd.get('raw','')[:80]}"})
                continue
            if ctype == "push":
                try:
                    if browser is None:
                        cdp_url = cmd.get("cdp_url", "http://127.0.0.1:9222")
                        browser = await pw.chromium.connect_over_cdp(cdp_url)
                    init_script = cmd.get("script", "")
                    pages_touched = 0
                    for context in browser.contexts:
                        if init_script:
                            await context.add_init_script(init_script)
                        for page in context.pages:
                            try:
                                if init_script:
                                    await page.evaluate(init_script)
                                pages_touched += 1
                            except Exception:
                                continue
                    _emit({"ok": True, "pages_touched": pages_touched})
                except Exception as exc:
                    _emit({
                        "ok": False,
                        "err": repr(exc),
                        "traceback": traceback.format_exc(),
                    })
                continue
            if ctype == "upload_files":
                # Find the ACTIVE page (first page in its context
                # that has a matching URL, or the last-focused page)
                # and set files on the element matching `selector`.
                # When url_contains is provided we pick the first
                # page whose url contains that substring; otherwise
                # the first page with the selector present wins.
                try:
                    if browser is None:
                        cdp_url = cmd.get("cdp_url", "http://127.0.0.1:9222")
                        browser = await pw.chromium.connect_over_cdp(cdp_url)
                    selector = cmd.get("selector",
                                       'input[type="file"]')
                    files = cmd.get("files", []) or []
                    url_contains = (cmd.get("url_contains") or "").lower()
                    target_page = None
                    candidates = []
                    for context in browser.contexts:
                        for page in context.pages:
                            candidates.append(page)
                    # Narrow by URL substring if provided.
                    if url_contains:
                        candidates = [p for p in candidates
                                      if url_contains in (p.url or "").lower()]
                    # Pick the first page that has the selector.
                    for page in candidates:
                        try:
                            locator = page.locator(selector).first
                            count = await locator.count()
                            if count > 0:
                                target_page = page
                                break
                        except Exception:
                            continue
                    if target_page is None:
                        _emit({
                            "ok": False,
                            "err": (f"no page with selector "
                                    f"{selector!r} (url_contains="
                                    f"{url_contains!r})"),
                        })
                        continue
                    await target_page.locator(selector).first.set_input_files(files)
                    _emit({
                        "ok": True,
                        "url": target_page.url,
                        "selector": selector,
                        "files": files,
                    })
                except Exception as exc:
                    _emit({
                        "ok": False,
                        "err": repr(exc),
                        "traceback": traceback.format_exc(),
                    })
                continue
            _emit({"ok": False, "err": f"unknown cmd: {ctype!r}"})
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


def _emit(obj: dict) -> None:
    """Write one JSON line to stdout + flush. Parent reads this."""
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def main() -> None:
    # Windows: Playwright's driver subprocess needs ProactorEventLoop.
    # Explicit instantiation bypasses any policy the parent process
    # may have set (unlikely here since this is a fresh interpreter,
    # but belt-and-braces).
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_main())
    except Exception as exc:
        _emit({
            "ok": False,
            "err": f"worker crashed: {exc!r}",
            "traceback": traceback.format_exc(),
        })
    finally:
        try:
            loop.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
