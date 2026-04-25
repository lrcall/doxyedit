"""
native_input.py - pyautogui-driven OS-level input as final-fallback transport.

The dispatcher's [api, dom-paste, dom-click, drag, native] cascade lands
here when every other transport refused. Useful for hosts that don't
expose stable selectors and that block the synthetic drag chain
(some Cloudflare-fronted composers, anti-automation overlays).

pyautogui is OPTIONAL. The module imports cleanly without it; available()
returns False; every action raises NativeInputUnavailable. We avoid
shipping it as a hard dep because on Windows it pulls PyScreeze,
PyMsgBox, and pillow-image-detection - extras that are not free for
users who never reach this fallback.

Public surface:
    available() -> bool
    type_text(text: str, delay_ms: int = 20) -> None
    click_at(x: int, y: int) -> None
    paste_text(text: str) -> None     # clipboard + Ctrl+V
"""

import subprocess


class NativeInputUnavailable(RuntimeError):
    """Raised when an action is attempted but pyautogui isn't installed.
    Callers should treat this as a "skip transport" signal, not a fatal
    error - the dispatcher's job is to fall through to the next rung."""


def _import_pyautogui():
    try:
        import pyautogui  # type: ignore
        return pyautogui
    except ImportError:
        return None
    except Exception:
        # pyautogui can also fail at import time on headless WSL boxes
        # (no DISPLAY) or when its X11 bridge can't reach a display
        # server. Those are also "unavailable" for our purposes.
        return None


def available() -> bool:
    """True iff pyautogui imports cleanly. The dispatcher's userscript-
    side _nativeTransport probes this before issuing typed actions so
    it can record "skipped: pyautogui not installed" rather than
    "failed: <traceback>" when the user is on a stock install."""
    return _import_pyautogui() is not None


def type_text(text: str, delay_ms: int = 20) -> None:
    pa = _import_pyautogui()
    if pa is None:
        raise NativeInputUnavailable(
            "pyautogui not installed (pip install pyautogui)")
    pa.typewrite(str(text), interval=max(0.0, delay_ms / 1000.0))


def click_at(x: int, y: int) -> None:
    pa = _import_pyautogui()
    if pa is None:
        raise NativeInputUnavailable(
            "pyautogui not installed (pip install pyautogui)")
    pa.click(x=int(x), y=int(y))


def paste_text(text: str) -> None:
    """Push text to the system clipboard, then send Ctrl+V. More
    reliable than typewrite for non-ASCII strings since typewrite
    silently drops characters that aren't in pyautogui's keyboard
    layout map.

    Clipboard write order: Qt's QGuiApplication.clipboard() (preferred -
    DoxyEdit's main process is already a Qt app), then Windows' clip.exe
    as a last resort. Both are tried before raising; if neither lands,
    the paste step is skipped and the caller sees a clear error."""
    pa = _import_pyautogui()
    if pa is None:
        raise NativeInputUnavailable(
            "pyautogui not installed (pip install pyautogui)")
    text_str = str(text)
    pushed = False
    try:
        from PySide6.QtGui import QGuiApplication  # type: ignore
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text_str)
            pushed = True
    except Exception:
        pass
    if not pushed:
        try:
            # Windows-only fallback. CREATE_NO_WINDOW (0x08000000)
            # avoids the brief console flash that subprocess.run
            # otherwise produces.
            subprocess.run(["clip"], input=text_str, encoding="utf-8",
                            check=False, creationflags=0x08000000)
            pushed = True
        except Exception:
            pass
    if not pushed:
        raise NativeInputUnavailable(
            "no clipboard backend reachable (Qt or clip.exe)")
    pa.hotkey("ctrl", "v")
