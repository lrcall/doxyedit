"""browserpost.py — Automated posting to subscription platforms via Playwright + CDP.

Connects to a running Chrome instance (with --remote-debugging-port) to fill
forms, upload images, and submit posts on platforms that have no posting API.

Requires: pip install playwright
Setup: User launches Chrome once with debug port, logs into platforms.
"""
from __future__ import annotations
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.request import urlopen


@dataclass
class BrowserPostResult:
    success: bool = False
    platform: str = ""
    url: str = ""
    error: str = ""


# Default CDP endpoint
DEFAULT_CDP = "http://localhost:9222"

# Shared step templates — most platforms use one of these two patterns
_STEPS_CONTENTEDITABLE = [
    {"action": "wait", "selector": "[contenteditable]", "timeout": 10000},
    {"action": "fill_contenteditable", "selector": "[contenteditable]", "field": "caption"},
    {"action": "upload", "selector": "input[type='file']", "field": "image"},
]
_STEPS_TEXTAREA = [
    {"action": "wait", "selector": "textarea, [contenteditable]", "timeout": 10000},
    {"action": "fill", "selector": "textarea", "field": "caption"},
    {"action": "upload", "selector": "input[type='file']", "field": "image"},
]

# Default platform selectors (can be overridden in config.yaml)
DEFAULT_SELECTORS: dict[str, dict] = {
    "patreon":      {"url": "{base_url}/posts/new",           "steps": _STEPS_CONTENTEDITABLE + [{"action": "wait", "ms": 1000}]},
    "fanbox":       {"url": "{base_url}/manage/posts/new",    "steps": _STEPS_CONTENTEDITABLE},
    "kofi":         {"url": "https://ko-fi.com/post/create",  "steps": _STEPS_CONTENTEDITABLE},
    "subscribestar": {"url": "{base_url}/posts/new",          "steps": _STEPS_CONTENTEDITABLE},
    "kickstarter":  {"url": "{base_url}/updates/new",         "steps": _STEPS_CONTENTEDITABLE},
    "indiegogo":    {"url": "{base_url}/edit/updates/new",    "steps": _STEPS_CONTENTEDITABLE},
    "fantia":       {"url": "{base_url}/posts/new",           "steps": _STEPS_TEXTAREA},
    "cien":         {"url": "{base_url}/creator/posting",     "steps": _STEPS_TEXTAREA},
    "gumroad": {
        "url": "https://gumroad.com/products/new",
        "steps": [
            {"action": "wait", "selector": "textarea, input[name='name']", "timeout": 10000},
            {"action": "fill", "selector": "input[name='name']", "field": "caption"},
            {"action": "upload", "selector": "input[type='file']", "field": "image"},
        ],
    },
}


def is_chrome_running(cdp_url: str = DEFAULT_CDP) -> bool:
    """Check if a Chrome instance is accessible on the debug port."""
    try:
        with urlopen(f"{cdp_url}/json/version", timeout=2) as resp:
            data = json.loads(resp.read())
            return bool(data.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def get_chrome_ws_url(cdp_url: str = DEFAULT_CDP) -> str:
    """Get the WebSocket URL for CDP connection."""
    try:
        with urlopen(f"{cdp_url}/json/version", timeout=3) as resp:
            data = json.loads(resp.read())
            return data.get("webSocketDebuggerUrl", "")
    except Exception:
        return ""


def launch_debug_chrome(chrome_path: str = "", port: int = 9222) -> Optional[subprocess.Popen]:
    """Launch Chrome with --remote-debugging-port.

    Uses the system Chrome if chrome_path is empty.
    Returns the Popen object, or None on failure.
    """
    if not chrome_path:
        # Try common Windows paths
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                chrome_path = c
                break

    if not chrome_path or not os.path.exists(chrome_path):
        print(f"[BrowserPost] Chrome not found at: {chrome_path}")
        return None

    # Use a separate user-data-dir to avoid conflicting with main Chrome
    profile_dir = str(Path.home() / ".doxyedit_chrome_profile")

    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    print(f"[BrowserPost] Launching Chrome: {chrome_path} on port {port}")
    try:
        proc = subprocess.Popen(
            args,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        return proc
    except Exception as e:
        print(f"[BrowserPost] Failed to launch Chrome: {e}")
        return None


def _load_selectors(project_dir: str) -> dict[str, dict]:
    """Load platform selectors from config.yaml, falling back to defaults."""
    from doxyedit.oneup import _find_config
    config_path = _find_config(project_dir)
    selectors = dict(DEFAULT_SELECTORS)

    if config_path.exists():
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            browser_cfg = config.get("browser_automation", {})
            custom = browser_cfg.get("platforms", {})
            for plat_id, plat_cfg in custom.items():
                if isinstance(plat_cfg, dict):
                    selectors[plat_id] = {**selectors.get(plat_id, {}), **plat_cfg}
        except Exception:
            pass

    return selectors


async def _run_steps(page, steps: list[dict], fields: dict[str, str]) -> None:
    """Execute a sequence of automation steps on a page.

    Each step is retried up to 2 times (3 attempts total) with a 1-second
    wait between attempts.
    """
    max_retries = 2
    for step in steps:
        action = step.get("action", "")
        selector = step.get("selector", "")
        field_key = step.get("field", "")
        value = fields.get(field_key, "")

        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                await _execute_step(page, action, selector, value, step)
                break
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    print(f"[BrowserPost] Step '{action}' failed (attempt {attempt + 1}), retrying: {e}")
                    await asyncio.sleep(1)
        else:
            # All retries exhausted — raise the last error
            raise last_err  # type: ignore[misc]


async def _execute_step(page, action: str, selector: str, value: str, step: dict) -> None:
    """Execute a single automation step."""
    if action == "wait":
        timeout = step.get("timeout", 5000)
        await page.wait_for_selector(selector, timeout=timeout)

    elif action == "fill" and selector and value:
        await page.locator(selector).first.fill(value)

    elif action == "fill_contenteditable" and selector and value:
        el = page.locator(selector).first
        await el.click()
        await page.keyboard.press("Control+a")
        await page.keyboard.type(value, delay=5)

    elif action == "upload" and selector and value:
        if os.path.exists(value):
            loc = page.locator(selector).first
            visible = await loc.is_visible()
            if not visible:
                # Temporarily reveal hidden file input so we can set files
                await page.evaluate(
                    """(sel) => {
                        const el = document.querySelector(sel);
                        if (el) {
                            el.dataset._origDisplay = el.style.display;
                            el.dataset._origVisibility = el.style.visibility;
                            el.dataset._origOpacity = el.style.opacity;
                            el.style.display = 'block';
                            el.style.visibility = 'visible';
                            el.style.opacity = '1';
                        }
                    }""",
                    selector,
                )
            await loc.set_input_files(value)
            if not visible:
                # Restore original hidden state
                await page.evaluate(
                    """(sel) => {
                        const el = document.querySelector(sel);
                        if (el) {
                            el.style.display = el.dataset._origDisplay || '';
                            el.style.visibility = el.dataset._origVisibility || '';
                            el.style.opacity = el.dataset._origOpacity || '';
                            delete el.dataset._origDisplay;
                            delete el.dataset._origVisibility;
                            delete el.dataset._origOpacity;
                        }
                    }""",
                    selector,
                )

    elif action == "click" and selector:
        await page.locator(selector).first.click()

    elif action == "wait_ms" or (action == "wait" and "ms" in step):
        ms = step.get("ms", 1000)
        await page.wait_for_timeout(ms)


async def post_to_platform(
    platform_id: str,
    caption: str,
    image_path: str,
    base_url: str = "",
    project_dir: str = ".",
    cdp_url: str = DEFAULT_CDP,
    auto_submit: bool = False,
) -> BrowserPostResult:
    """Automate posting to a subscription platform via Playwright + CDP.

    Args:
        platform_id: key from SUB_PLATFORMS (e.g. "patreon", "fantia")
        caption: post text/caption
        image_path: path to exported image file
        base_url: platform base URL from identity config
        project_dir: for loading config.yaml selectors
        cdp_url: Chrome DevTools Protocol endpoint
        auto_submit: if True, click the submit/publish button (default: leave for user)
    """
    selectors = _load_selectors(project_dir)
    plat_cfg = selectors.get(platform_id)
    if not plat_cfg:
        return BrowserPostResult(error=f"No selectors configured for {platform_id}")

    # Build URL
    url_template = plat_cfg.get("url", "")
    if "{base_url}" in url_template:
        if not base_url:
            return BrowserPostResult(error=f"No base URL for {platform_id}")
        url = url_template.replace("{base_url}", base_url.rstrip("/"))
    else:
        url = url_template

    if not url:
        return BrowserPostResult(error=f"No URL for {platform_id}")

    # Get CDP websocket
    ws_url = get_chrome_ws_url(cdp_url)
    if not ws_url:
        return BrowserPostResult(
            platform=platform_id,
            error="Debug Chrome not running. Launch it from Tools > Launch Debug Chrome.",
        )

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(ws_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()

            print(f"[BrowserPost] Navigating to {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)

            # Run automation steps
            fields = {"caption": caption, "image": image_path}
            steps = plat_cfg.get("steps", [])
            await _run_steps(page, steps, fields)

            # Optionally click submit
            if auto_submit:
                submit_sel = plat_cfg.get("submit_selector", "")
                if submit_sel:
                    await page.locator(submit_sel).first.click()
                    await page.wait_for_timeout(2000)

            print(f"[BrowserPost] Done: {platform_id} — form filled, waiting for user review")
            return BrowserPostResult(
                success=True,
                platform=platform_id,
                url=url,
            )

    except Exception as e:
        print(f"[BrowserPost] Error on {platform_id}: {e}")
        return BrowserPostResult(platform=platform_id, error=str(e))


def post_to_platform_sync(
    platform_id: str,
    caption: str,
    image_path: str,
    base_url: str = "",
    project_dir: str = ".",
    cdp_url: str = DEFAULT_CDP,
    auto_submit: bool = False,
) -> BrowserPostResult:
    """Synchronous wrapper around post_to_platform for use from Qt."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            post_to_platform(
                platform_id, caption, image_path,
                base_url, project_dir, cdp_url, auto_submit,
            )
        )
    except Exception as e:
        return BrowserPostResult(platform=platform_id, error=str(e))
    finally:
        loop.close()
