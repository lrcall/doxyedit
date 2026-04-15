"""claude_modal.py — Reusable themed progress modal for Claude CLI calls."""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtWidgets import QProgressDialog, QWidget
from PySide6.QtCore import Qt, QThread, Signal


class ClaudeWorker(QThread):
    """Background thread that runs a claude -p prompt."""
    finished = Signal(str)

    def __init__(self, prompt: str, parent=None):
        super().__init__(parent)
        self._prompt = prompt

    def run(self):
        try:
            kwargs = dict(
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=180,
            )
            if sys.platform == "win32":
                kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            result = subprocess.run(["claude", "-p", self._prompt], **kwargs)
            self.finished.emit(result.stdout.strip() if result.returncode == 0 else "")
        except Exception:
            self.finished.emit("")


def show_claude_modal(
    parent: QWidget,
    message: str,
    prompt: str,
    callback,
) -> tuple[QProgressDialog, ClaudeWorker]:
    """Show a themed modal progress dialog and run a Claude prompt in background.

    Args:
        parent: Parent widget
        message: Display text (e.g., "Generating strategy...")
        prompt: The prompt to send to claude -p
        callback: Function(str) called with Claude's response when done

    Returns:
        (dialog, worker) tuple — caller should store worker to prevent GC
    """
    dlg = QProgressDialog(message, None, 0, 0, parent)
    dlg.setObjectName("claude_progress")
    dlg.setWindowTitle("Claude")
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.setCancelButton(None)
    dlg.setMinimumDuration(0)
    from PySide6.QtCore import QSettings
    _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
    DIALOG_MIN_WIDTH_RATIO = 26.7      # progress dialog minimum width
    dlg.setMinimumWidth(int(_f * DIALOG_MIN_WIDTH_RATIO))
    dlg.show()

    # Theme the title bar on Windows
    try:
        import ctypes
        from PySide6.QtCore import QSettings
        from doxyedit.themes import THEMES, DEFAULT_THEME
        theme_id = QSettings("DoxyEdit", "DoxyEdit").value("theme", DEFAULT_THEME)
        theme = THEMES.get(theme_id, THEMES[DEFAULT_THEME])
        h = theme.bg_raised.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        hwnd = int(dlg.winId())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 35, ctypes.byref(ctypes.c_int(r | (g << 8) | (b << 16))),
            ctypes.sizeof(ctypes.c_int))
    except Exception:
        pass

    worker = ClaudeWorker(prompt, parent)

    def _on_done(result):
        dlg.close()
        callback(result)

    worker.finished.connect(_on_done)
    worker.start()

    return dlg, worker
