"""Global hotkey + WM_DROPFILES simulation for Windows.

Ctrl+Shift+Alt+Insert reads file/folder paths from the clipboard and simulates
dropping them onto whatever window is currently under the mouse cursor.

Supports:
- Single path (plain text)
- Multiple paths (one per line)
- Paths with or without quotes

Works with any app that accepts WM_DROPFILES (Explorer, Photoshop, SAI,
Clip Studio, most Win32 creative apps). Does not work with UWP/sandboxed apps
or apps that use OLE IDropTarget instead of raw WM_DROPFILES.

Notes:
- WM_HOTKEY arrives as "windows_dispatcher_MSG" in Qt's native event filter,
  not "windows_generic_MSG". Must check eventType in nativeEventFilter.
- UIPI (Windows 7+) silently blocks WM_DROPFILES across privilege levels.
  We call ChangeWindowMessageFilterEx on the target to allow it.
"""
import ctypes
import ctypes.wintypes as wintypes
import struct
from pathlib import Path

# Win32 constants
WM_DROPFILES    = 0x0233
WM_HOTKEY       = 0x0312
GMEM_MOVEABLE   = 0x0002
GMEM_ZEROINIT   = 0x0040
MOD_ALT         = 0x0001
MOD_CONTROL     = 0x0002
MOD_SHIFT       = 0x0004
VK_INSERT       = 0x2D
MSGFLT_ALLOW    = 1

HOTKEY_ID = 0xD0E1  # arbitrary app-specific ID

_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

# WM_HOTKEY is delivered as this event type in Qt's native event filter
DISPATCHER_MSG_TYPE = b"windows_dispatcher_MSG"


def register_hotkey(hwnd: int) -> bool:
    """Register Ctrl+Shift+Alt+Insert as a global hotkey on the given HWND.
    Returns True on success. Call once after the window is shown.
    """
    return bool(_user32.RegisterHotKey(
        hwnd,
        HOTKEY_ID,
        MOD_CONTROL | MOD_ALT | MOD_SHIFT,
        VK_INSERT,
    ))


def unregister_hotkey(hwnd: int):
    """Unregister the global hotkey. Call on window close."""
    _user32.UnregisterHotKey(hwnd, HOTKEY_ID)


def is_hotkey_message(event_type: bytes, msg_ptr: int) -> bool:
    """Return True if a native Windows dispatcher message is our WM_HOTKEY."""
    if event_type != DISPATCHER_MSG_TYPE:
        return False
    msg = wintypes.MSG.from_address(msg_ptr)
    return msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID


def _allow_drop_message(hwnd: int):
    """Call ChangeWindowMessageFilterEx to allow WM_DROPFILES through UIPI."""
    try:
        _user32.ChangeWindowMessageFilterEx(hwnd, WM_DROPFILES, MSGFLT_ALLOW, None)
        _user32.ChangeWindowMessageFilterEx(hwnd, 0x0049, MSGFLT_ALLOW, None)  # undocumented helper
    except Exception:
        pass


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def parse_paths(text: str) -> list[str]:
    """Parse one or more file/folder paths from clipboard text.
    Handles quoted paths, mixed separators, blank lines.
    Returns only paths that exist on disk.
    """
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    paths = []
    for line in lines:
        line = line.strip().strip('"').strip("'")
        if not line:
            continue
        p = Path(line)
        if p.exists():
            paths.append(str(p))
    return paths


def drop_files_on_hwnd(hwnd: int, paths: list[str], x: int, y: int) -> bool:
    """Simulate dropping a list of files onto hwnd at screen coordinates (x, y).

    Builds a DROPFILES structure in global memory and posts WM_DROPFILES.
    Returns True if PostMessage succeeded.
    """
    if not paths or not hwnd:
        return False

    # Allow WM_DROPFILES through UIPI on the target window
    _allow_drop_message(hwnd)

    # Build the null-separated, double-null-terminated UTF-16LE filename list
    filelist = '\0'.join(paths) + '\0\0'
    filelist_bytes = filelist.encode('utf-16-le')

    # DROPFILES header (20 bytes):
    #   DWORD pFiles  — offset to filename list from start of struct
    #   POINT pt      — drop point (2× LONG = 8 bytes)
    #   BOOL  fNC     — FALSE = client coordinates
    #   BOOL  fWide   — TRUE = Unicode filenames
    HEADER_SIZE = 20
    header = struct.pack('<IIIII',
        HEADER_SIZE,   # pFiles
        x, y,          # pt.x, pt.y
        0,             # fNC = client coords
        1,             # fWide = Unicode
    )

    data = header + filelist_bytes

    # Allocate moveable global memory (required for WM_DROPFILES)
    h_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
    if not h_mem:
        return False

    ptr = _kernel32.GlobalLock(h_mem)
    if not ptr:
        _kernel32.GlobalFree(h_mem)
        return False

    ctypes.memmove(ptr, data, len(data))
    _kernel32.GlobalUnlock(h_mem)

    # PostMessage is async — the target app owns the memory after this call
    ok = bool(_user32.PostMessageW(hwnd, WM_DROPFILES, h_mem, 0))
    if not ok:
        _kernel32.GlobalFree(h_mem)
    return ok


def simulate_drop_from_clipboard(clipboard_text: str) -> tuple[bool, str]:
    """Full pipeline: parse clipboard → find window under cursor → drop.

    Returns (success, message) for status bar display.
    """
    paths = parse_paths(clipboard_text)
    if not paths:
        return False, "Clipboard contains no valid file paths"

    x, y = cursor_pos()
    hwnd = _user32.WindowFromPoint(wintypes.POINT(x, y))
    if not hwnd:
        return False, "No window found under cursor"

    ok = drop_files_on_hwnd(hwnd, paths, x, y)
    if ok:
        n = len(paths)
        noun = "file" if n == 1 else "files"
        return True, f"Dropped {n} {noun} → window 0x{hwnd:x}"
    else:
        return False, "Drop failed (target may not accept WM_DROPFILES)"
