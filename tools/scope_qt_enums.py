"""One-shot fixer: convert flat Qt enum accesses to the scoped form
PyQt6 requires and PySide6 also accepts.

    Qt.AlignLeft      -> Qt.AlignmentFlag.AlignLeft
    Qt.Horizontal     -> Qt.Orientation.Horizontal
    Qt.Tool           -> Qt.WindowType.Tool

Usage: ``py tools/scope_qt_enums.py``

Idempotent: already-scoped names are left alone via a negative lookbehind.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "doxyedit"

# (flat_name, scoped_form). Order matters only for overlapping prefixes
# (none here).
SCOPE_MAP: dict[str, str] = {
    # Alignment flags
    "AlignLeft":    "AlignmentFlag.AlignLeft",
    "AlignRight":   "AlignmentFlag.AlignRight",
    "AlignCenter":  "AlignmentFlag.AlignCenter",
    "AlignHCenter": "AlignmentFlag.AlignHCenter",
    "AlignVCenter": "AlignmentFlag.AlignVCenter",
    "AlignTop":     "AlignmentFlag.AlignTop",
    "AlignBottom":  "AlignmentFlag.AlignBottom",
    "AlignBaseline": "AlignmentFlag.AlignBaseline",
    "AlignJustify": "AlignmentFlag.AlignJustify",
    "AlignAbsolute": "AlignmentFlag.AlignAbsolute",
    # Orientation
    "Horizontal": "Orientation.Horizontal",
    "Vertical":   "Orientation.Vertical",
    # Window type flags
    "FramelessWindowHint":    "WindowType.FramelessWindowHint",
    "WindowStaysOnTopHint":   "WindowType.WindowStaysOnTopHint",
    "CustomizeWindowHint":    "WindowType.CustomizeWindowHint",
    "WindowTitleHint":        "WindowType.WindowTitleHint",
    "WindowCloseButtonHint":  "WindowType.WindowCloseButtonHint",
    "WindowMinimizeButtonHint": "WindowType.WindowMinimizeButtonHint",
    "WindowMaximizeButtonHint": "WindowType.WindowMaximizeButtonHint",
    "WindowContextHelpButtonHint": "WindowType.WindowContextHelpButtonHint",
    "WindowSystemMenuHint":   "WindowType.WindowSystemMenuHint",
    "Tool":    "WindowType.Tool",
    "Popup":   "WindowType.Popup",
    "Dialog":  "WindowType.Dialog",
    "Sheet":   "WindowType.Sheet",
    "SplashScreen": "WindowType.SplashScreen",
    # Focus policy
    "NoFocus":      "FocusPolicy.NoFocus",
    "TabFocus":     "FocusPolicy.TabFocus",
    "ClickFocus":   "FocusPolicy.ClickFocus",
    "StrongFocus":  "FocusPolicy.StrongFocus",
    "WheelFocus":   "FocusPolicy.WheelFocus",
    # Text elide mode
    "ElideLeft":   "TextElideMode.ElideLeft",
    "ElideRight":  "TextElideMode.ElideRight",
    "ElideMiddle": "TextElideMode.ElideMiddle",
    "ElideNone":   "TextElideMode.ElideNone",
    # Cursor shape (subset likely used)
    "ArrowCursor": "CursorShape.ArrowCursor",
    "PointingHandCursor": "CursorShape.PointingHandCursor",
    "CrossCursor": "CursorShape.CrossCursor",
    "IBeamCursor": "CursorShape.IBeamCursor",
    "SizeAllCursor": "CursorShape.SizeAllCursor",
    "SizeFDiagCursor": "CursorShape.SizeFDiagCursor",
    "SizeBDiagCursor": "CursorShape.SizeBDiagCursor",
    "SizeHorCursor": "CursorShape.SizeHorCursor",
    "SizeVerCursor": "CursorShape.SizeVerCursor",
    "WaitCursor":   "CursorShape.WaitCursor",
    "BlankCursor":  "CursorShape.BlankCursor",
    "OpenHandCursor": "CursorShape.OpenHandCursor",
    "ClosedHandCursor": "CursorShape.ClosedHandCursor",
    # Context menu policy
    "NoContextMenu": "ContextMenuPolicy.NoContextMenu",
    "DefaultContextMenu": "ContextMenuPolicy.DefaultContextMenu",
    "ActionsContextMenu": "ContextMenuPolicy.ActionsContextMenu",
    "CustomContextMenu": "ContextMenuPolicy.CustomContextMenu",
    "PreventContextMenu": "ContextMenuPolicy.PreventContextMenu",
    # Text interaction
    "NoTextInteraction":    "TextInteractionFlag.NoTextInteraction",
    "TextSelectableByMouse": "TextInteractionFlag.TextSelectableByMouse",
    "TextEditorInteraction": "TextInteractionFlag.TextEditorInteraction",
    "TextBrowserInteraction": "TextInteractionFlag.TextBrowserInteraction",
    # Shortcut context
    "WidgetShortcut": "ShortcutContext.WidgetShortcut",
    "WindowShortcut": "ShortcutContext.WindowShortcut",
    "ApplicationShortcut": "ShortcutContext.ApplicationShortcut",
    # Scrollbar policy
    "ScrollBarAsNeeded": "ScrollBarPolicy.ScrollBarAsNeeded",
    "ScrollBarAlwaysOn": "ScrollBarPolicy.ScrollBarAlwaysOn",
    "ScrollBarAlwaysOff": "ScrollBarPolicy.ScrollBarAlwaysOff",
    # Drop action
    "CopyAction": "DropAction.CopyAction",
    "MoveAction": "DropAction.MoveAction",
    "LinkAction": "DropAction.LinkAction",
    "IgnoreAction": "DropAction.IgnoreAction",
    # Pen / brush styles already use PenStyle./BrushStyle. scope in doxyedit
    # Mouse buttons – no module access for MouseButton.LeftButton in most
    # use, but list anyway for completeness.
    "LeftButton":   "MouseButton.LeftButton",
    "RightButton":  "MouseButton.RightButton",
    "MiddleButton": "MouseButton.MiddleButton",
    "NoButton":     "MouseButton.NoButton",
    # Keyboard modifiers
    "NoModifier":       "KeyboardModifier.NoModifier",
    "ShiftModifier":    "KeyboardModifier.ShiftModifier",
    "ControlModifier":  "KeyboardModifier.ControlModifier",
    "AltModifier":      "KeyboardModifier.AltModifier",
    "MetaModifier":     "KeyboardModifier.MetaModifier",
    "KeypadModifier":   "KeyboardModifier.KeypadModifier",
}


def _compile_re(flat: str) -> re.Pattern:
    # Match Qt.<flat> where <flat> is NOT already preceded by a scope
    # class. Use a negative lookbehind on a dot just before Qt. to avoid
    # re-scoping.
    return re.compile(rf"(?<![\w.])Qt\.{flat}\b")


COMPILED = {flat: _compile_re(flat) for flat in SCOPE_MAP}


def scope_text(text: str) -> tuple[str, int]:
    total = 0
    for flat, scoped in SCOPE_MAP.items():
        pat = COMPILED[flat]
        new_text, n = pat.subn(f"Qt.{scoped}", text)
        text = new_text
        total += n
    return text, total


def main() -> int:
    changed_files = 0
    total_subs = 0
    for py in ROOT.rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text, n = scope_text(text)
        if n:
            py.write_text(new_text, encoding="utf-8")
            print(f"{py.relative_to(ROOT.parent)}: {n} subs")
            changed_files += 1
            total_subs += n
    print(f"\n{changed_files} files updated, {total_subs} replacements total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
