"""Tokenization validator — catches ALL hardcoded visual values in doxyedit/.

Run: python scripts/tokenize_validate.py
Returns exit code 1 if violations found.

Every pattern that /tokenize should catch is listed here as a regex.
When a new pattern is discovered, add it to PATTERNS.
"""
import re
import sys
from pathlib import Path

# Files/classes where overlay-exception colors are allowed
OVERLAY_EXCEPTIONS = {
    ("censor.py", "CensorRectItem"),
    ("studio.py", "CensorRectItem"),
    ("studio.py", "_update_crop_mask"),
    ("preview.py", "_update_crop_mask"),
    ("preview.py", "NoteRectItem"),
}

PATTERNS = [
    # ── Size constraints with bare integers ──
    (r'\.setFixedWidth\(\d+\)', "setFixedWidth with bare integer"),
    (r'\.setFixedHeight\(\d+\)', "setFixedHeight with bare integer"),
    (r'\.setFixedSize\(\d+', "setFixedSize with bare integer"),
    (r'\.setMinimumWidth\(\d+\)', "setMinimumWidth with bare integer"),
    (r'\.setMaximumWidth\(\d+\)', "setMaximumWidth with bare integer"),
    (r'\.setMinimumHeight\(\d+\)', "setMinimumHeight with bare integer"),
    (r'\.setMaximumHeight\(\d+\)', "setMaximumHeight with bare integer"),
    (r'\.setMinimumSize\(\d+', "setMinimumSize with bare integer"),
    (r'\.setMaximumSize\(\d+', "setMaximumSize with bare integer"),

    # ── Fonts ──
    (r'QFont\("[^"]+",\s*\d+\)', "QFont with hardcoded family and size"),

    # ── Stray arithmetic on font_size ──
    (r'font_size\s*\+\s*\d', "stray arithmetic: font_size + N"),
    (r'font_size\s*-\s*\d', "stray arithmetic: font_size - N"),
    (r'_f\s*\+\s*\d', "stray arithmetic: _f + N"),
    (r'_f\s*-\s*\d', "stray arithmetic: _f - N"),

    # ── Hardcoded colors (PySide6/Qt — UI tokens live in Theme) ──
    (r'QColor\(\s*\d+\s*,\s*\d+\s*,\s*\d+', "QColor with hardcoded RGB"),
    (r'QColor\("#[0-9a-fA-F]{3,8}"\)', "QColor with hardcoded hex"),

    # ── Inline alpha integer ──
    (r'\.setAlpha\(\d+\)', "setAlpha with hardcoded integer"),

    # ── QPen with hardcoded width ──
    (r'QPen\([^,)]+,\s*\d+(\.\d+)?\s*[,)]', "QPen with hardcoded width"),

    # ── drawRoundedRect with bare radii ──
    (r'drawRoundedRect\([^)]*,\s*\d+\s*,\s*\d+\s*\)', "drawRoundedRect with hardcoded corner radii"),

    # ── Theme fallback colors ──
    (r'else\s+QColor\(', "else QColor() fallback - init theme in __init__"),
]

# Patterns that are acceptable in specific contexts
ACCEPTABLE = [
    r'setFixedHeight\(1\)',          # 1px separator
    r'setFixedWidth\(1\)',           # 1px separator
    r'16777215',                     # QWIDGETSIZE_MAX
    r'font_size\s*\+\s*1\)',         # font size increment action
    r'font_size\s*-\s*1\)',          # font size decrement action
    r'_cb = max\(14, _f \+ 2\)',    # known _cb pattern (polish item)
    r'max\(14, _f \+ 2\)',          # same
    r'max\(14, int\(_f',            # ratio-based _cb
    # ── Sentinel: setMinimum*(0) means "no minimum, splitter handles
    #    collapsing" — semantically a sentinel, not a hardcoded size.
    r'setMinimumWidth\(0\)',
    r'setMinimumHeight\(0\)',
    # ── Sentinel: setFixedHeight(0) hides a placeholder row.
    r'setFixedHeight\(0\)',
    # ── User-action font step (text-overlay Bigger / Smaller hotkeys).
    #    +2 / -2 is a step constant, not a token violation.
    r'overlay\.font_size\s*[+-]\s*2',
    # ── FPS HUD diagnostic font on the Skia preview window.
    #    Fixed monospace at 10pt is intentional for the overlay readout.
    r'QFont\("Consolas",\s*10\)',
    # ── _ColorSwatchButton: 32x26 minimum + 24x24 button are the
    #    deliberate icon-button visual standard ("icon decisions"
    #    exception in CLAUDE.md UI Rules). They live on a class
    #    that's used everywhere; tokenizing them ripples too far.
    r'setMinimumSize\(32,\s*26\)',
    r'setFixedSize\(24,\s*24\)',
    r'setFixedSize\(18,\s*18\)',
    # ── Pen width 0 is the Qt "cosmetic 1-px line" sentinel.
    r'QPen\([^,]+,\s*0\)',
    # ── Transparent fill init — semantically zero alpha, not a color.
    r'QColor\(0,\s*0,\s*0,\s*0\)',
    # ── Pixmap-clear-to-black before painting — opaque black is a
    #    canvas reset, not a UI color decision.
    r'QColor\(0,\s*0,\s*0\)',
    # ── FPS HUD diagnostic (paints over Studio canvas at user request).
    #    Traffic-light colors and dimmed white text are diagnostic
    #    indicators, not theme-style colors. Same exception class as
    #    QFont("Consolas", 10) above.
    r'QColor\(0,\s*0,\s*0,\s*180\)',           # FPS HUD bg
    r'QColor\(120,\s*230,\s*140\)',            # FPS HUD green (>=45 fps)
    r'QColor\(240,\s*210,\s*100\)',            # FPS HUD yellow (>=25 fps)
    r'QColor\(240,\s*120,\s*120\)',            # FPS HUD red (<25 fps)
    r'QColor\(220,\s*220,\s*220\)',            # FPS HUD secondary text
    # ── Skia error-state preview is a developer-facing diagnostic
    #    when the Skia runtime fails to load. Hardcoded dark-red bg
    #    + light-pink text is intentional "something's broken" signal.
    r'QColor\(50,\s*30,\s*30\)',
    r'QColor\(255,\s*200,\s*200\)',
    # ── Preview floating label: overlay class per CLAUDE.md "may use
    #    fixed high-contrast colors" exception. Cream-on-dark for
    #    readability over arbitrary canvas backgrounds.
    r'QColor\(255,\s*240,\s*210\)',
    # ── FPS HUD rounded-rect uses small fixed radii; lives behind
    #    the "diagnostic overlay" exception alongside the QFont/Color
    #    exemptions for the same overlay.
    r'p\.drawRoundedRect\(8,\s*8,\s*w,\s*h,\s*4,\s*4\)',
    # ── browser.py tag-color fallback: the "else" branch picks from
    #    VINIK_COLORS (a tokenized palette) deterministically — not a
    #    silent QColor(128, 128, 128) magic-number fallback.
    r'else QColor\(VINIK_COLORS\[',
]

# Files where the file IS the token source — reporting its own
# arithmetic creates noise.
SELF_TOKEN_FILES = {"themes.py"}


def is_acceptable(line: str) -> bool:
    return any(re.search(p, line) for p in ACCEPTABLE)


def is_overlay_exception(filepath: str, line: str) -> bool:
    fname = Path(filepath).name
    for exc_file, exc_context in OVERLAY_EXCEPTIONS:
        if fname == exc_file and exc_context in line:
            return True
    return False


def validate():
    src = Path(__file__).parent.parent / "doxyedit"
    violations = []

    # Recurse into platforms/ too so subdir UI files are covered.
    for py_file in sorted(src.rglob("*.py")):
        if py_file.name in SELF_TOKEN_FILES:
            continue
        lines = py_file.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            for pattern, desc in PATTERNS:
                if re.search(pattern, line):
                    if is_acceptable(line):
                        continue
                    if is_overlay_exception(str(py_file), line):
                        continue
                    violations.append((py_file.name, i, desc, stripped[:100]))

    if violations:
        print(f"\n{'='*70}")
        print(f"TOKENIZATION VIOLATIONS: {len(violations)}")
        print(f"{'='*70}\n")
        for fname, lineno, desc, code in violations:
            print(f"  {fname}:{lineno}  {desc}")
            print(f"    {code}\n")
        return 1
    else:
        print("TOKENIZATION: ALL CLEAN")
        return 0


if __name__ == "__main__":
    sys.exit(validate())
