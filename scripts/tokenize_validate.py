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

    for py_file in sorted(src.glob("*.py")):
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
