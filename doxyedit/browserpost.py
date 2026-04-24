"""browserpost.py — Automated posting to subscription platforms via Playwright + CDP.

Connects to a running Chromium-family browser (Chrome or Brave) with
--remote-debugging-port enabled, then fills forms, uploads images, and
submits posts on platforms that have no posting API.

Brave is preferred by default because Chrome now forces phone-number
verification for fresh profiles. Brave is Chromium under the hood, so
every CDP / Playwright call works identically — only the binary path
and the default profile-dir name differ.

Requires: pip install playwright
Setup: User launches the chosen browser once with the debug port and
logs into each platform. Per-browser profile dirs keep Chrome and
Brave login state isolated.
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


# Per-browser binary candidates. First match wins inside each family.
# Brave is listed first in the auto-detect order because the user's
# primary workflow moved to Brave (Chrome now demands phone-number
# verification on new profiles). Chrome stays as a fallback so
# installations that still use it keep working untouched.
_BROWSER_CANDIDATES: dict[str, list[str]] = {
    "brave": [
        os.path.expandvars(
            r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.expandvars(
            r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.expandvars(
            r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
    "chrome": [
        os.path.expandvars(
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ],
}

_BROWSER_DISPLAY = {"brave": "Brave", "chrome": "Chrome"}

# Auto-detect preference order: Brave, then Chrome. Applied when config
# neither specifies a browser nor a binary path.
_BROWSER_AUTO_ORDER = ("brave", "chrome")


def _detect_browser_binary(preferred: str = "auto") -> tuple[str, str]:
    """Return (browser_name, binary_path) for the first existing browser.
    preferred = 'brave' / 'chrome' / 'auto'. Empty tuple on no match."""
    if preferred and preferred != "auto":
        for p in _BROWSER_CANDIDATES.get(preferred.lower(), []):
            if os.path.exists(p):
                return preferred.lower(), p
        # Preference missed — fall through to auto-detect rather than
        # failing outright, so the caller still gets a working browser.
    for name in _BROWSER_AUTO_ORDER:
        for p in _BROWSER_CANDIDATES.get(name, []):
            if os.path.exists(p):
                return name, p
    return "", ""


def _profile_dir_for(browser_name: str) -> str:
    """Dedicated user-data-dir per browser so login state is isolated.
    Preserves legacy chrome profile name so users who already logged in
    via the old path keep their session on upgrade."""
    if browser_name == "chrome":
        return str(Path.home() / ".doxyedit_chrome_profile")
    return str(Path.home() / f".doxyedit_{browser_name}_profile")


def is_chrome_running(cdp_url: str = DEFAULT_CDP) -> bool:
    """Check if a debug-mode Chromium browser (Chrome or Brave) is
    accessible on the CDP port. Name kept for back-compat with older
    callers; the CDP endpoint is browser-agnostic."""
    try:
        with urlopen(f"{cdp_url}/json/version", timeout=2) as resp:
            data = json.loads(resp.read())
            return bool(data.get("webSocketDebuggerUrl"))
    except Exception:
        return False


# Preferred name for new callers.
is_debug_browser_running = is_chrome_running


def detect_running_browser(cdp_url: str = DEFAULT_CDP) -> str:
    """Return 'Brave' / 'Chrome' / '' for the browser backing the debug
    port, extracted from the Browser field of /json/version."""
    try:
        with urlopen(f"{cdp_url}/json/version", timeout=2) as resp:
            data = json.loads(resp.read())
            ua = (data.get("Browser") or "") + " " + (data.get("User-Agent") or "")
            if "Brave" in ua:
                return "Brave"
            if "Chrome" in ua:
                return "Chrome"
    except Exception:
        pass
    return ""


def get_chrome_ws_url(cdp_url: str = DEFAULT_CDP) -> str:
    """Get the WebSocket URL for CDP connection."""
    try:
        with urlopen(f"{cdp_url}/json/version", timeout=3) as resp:
            data = json.loads(resp.read())
            return data.get("webSocketDebuggerUrl", "")
    except Exception:
        return ""


def launch_debug_browser(
    browser_path: str = "",
    port: int = 9222,
    preferred: str = "auto",
) -> tuple[Optional[subprocess.Popen], str]:
    """Launch a Chromium-family browser with --remote-debugging-port.

    browser_path: explicit binary path. Wins if set AND exists.
    preferred:    'brave' / 'chrome' / 'auto' (Brave preferred, Chrome
                  as fallback). Ignored when browser_path is set.

    Returns (Popen, display_name). On failure returns (None, "").
    """
    browser_name = ""
    if browser_path and os.path.exists(browser_path):
        # Infer name from path so the profile dir / log message matches.
        lower = browser_path.lower()
        if "brave" in lower:
            browser_name = "brave"
        elif "chrome" in lower:
            browser_name = "chrome"
        else:
            # Unknown Chromium fork — treat as its own profile bucket.
            browser_name = Path(browser_path).stem
    else:
        browser_name, browser_path = _detect_browser_binary(preferred)

    if not browser_path or not os.path.exists(browser_path):
        print(
            f"[BrowserPost] No Chromium-family browser found "
            f"(preferred={preferred!r}). Install Brave or Chrome, or set "
            f"browser_automation.browser_path in config.yaml.")
        return None, ""

    display = _BROWSER_DISPLAY.get(browser_name, browser_name.capitalize())
    profile_dir = _profile_dir_for(browser_name)
    args = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    print(
        f"[BrowserPost] Launching {display}: {browser_path} on port {port}")
    try:
        proc = subprocess.Popen(
            args,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        return proc, display
    except Exception as e:
        print(f"[BrowserPost] Failed to launch {display}: {e}")
        return None, ""


def launch_debug_chrome(chrome_path: str = "", port: int = 9222) -> Optional[subprocess.Popen]:
    """Deprecated shim — kept for back-compat with older callers that
    may pass a Chrome binary path. New code should call
    launch_debug_browser(...) directly so Brave is preferred by default.

    When chrome_path is empty this routes through the new auto-detect
    logic, so "no path set" gives the user Brave-preferred behavior
    without any config change."""
    proc, _ = launch_debug_browser(
        browser_path=chrome_path, port=port, preferred="auto")
    return proc


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
