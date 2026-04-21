"""Build a PyQt6 exe of DoxyEdit for side-by-side comparison with the
PySide6 build. Usage:

    py tools/build_pyqt.py

What it does:
  1. Verify PyQt6 is installed (prompts pip-install if missing).
  2. Copy the doxyedit source tree to ``build_pyqt_tmp/``.
  3. Codemod every ``from PySide6.X`` / ``import PySide6`` to its PyQt6
     equivalent, and translate ``Signal`` / ``Slot`` → ``pyqtSignal`` /
     ``pyqtSlot`` (PyQt6 uses those names).
  4. Try to run ``py build_pyqt_tmp/run.py`` as a smoke test before
     compiling — fails fast with a clear error if a PySide6-specific
     idiom survived the codemod.
  5. Compile with Nuitka into ``dist/DoxyEdit-pyqt.exe``.

Caveats — see docs/pyqt-build.md for the full list. The two bindings
are 95% compatible but not identical; expect to patch a handful of
call sites by hand the first time. Known deltas:

- Enum scoping: PySide6 accepts both ``Qt.AlignLeft`` (flat) and
  ``Qt.AlignmentFlag.AlignLeft`` (scoped). PyQt6 requires the scoped
  path on some enums. We already use scoped paths in doxyedit.
- ``exec_`` vs ``exec``: both accept ``exec()`` on modern Qt; fine.
- Qt property system: we don't use ``@Property`` heavily, so no codemod.
- ``QTextStream``, ``QByteArray`` signatures differ slightly for bytes
  vs bytearray inputs — rarely relevant here.

Run-to-run this script is idempotent: re-running rebuilds from fresh.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRATCH = ROOT / "build_pyqt_tmp"
DIST = ROOT / "dist"

# Top-level package renames are simple word-boundary substitutions.
_PACKAGE_SUBS: list[tuple[str, str]] = [
    (r"\bfrom PySide6\.QtWidgets\b", "from PyQt6.QtWidgets"),
    (r"\bfrom PySide6\.QtCore\b",    "from PyQt6.QtCore"),
    (r"\bfrom PySide6\.QtGui\b",     "from PyQt6.QtGui"),
    (r"\bfrom PySide6\.QtSvg\b",     "from PyQt6.QtSvg"),
    (r"\bfrom PySide6\.QtNetwork\b", "from PyQt6.QtNetwork"),
    (r"\bimport PySide6\b",          "import PyQt6"),
]

# After the package rename, QtCore imports need `Signal` / `Slot` re-aliased
# to `pyqtSignal as Signal` / `pyqtSlot as Slot`. Match BOTH forms:
#   from PyQt6.QtCore import Signal, Slot                     (single-line)
#   from PyQt6.QtCore import (\n    Signal,\n    Slot,\n)     (parenthesized)
_QTCORE_SINGLE_RE = re.compile(
    r"^(from PyQt6\.QtCore import )([^\n(][^\n]*)$",
    re.MULTILINE,
)
_QTCORE_PAREN_RE = re.compile(
    r"(from PyQt6\.QtCore import\s*\()([^)]*)(\))",
    re.DOTALL,
)


def _translate_signal_slot(body: str) -> str:
    """Inside a QtCore import body, rewrite bare ``Signal`` / ``Slot`` to
    ``pyqtSignal as Signal`` / ``pyqtSlot as Slot``. Word-boundaries avoid
    matching things like ``QSignalMapper``. Already-aliased names are
    untouched so the transform is idempotent."""
    def _sub_signal(m: re.Match) -> str:
        return "pyqtSignal as Signal"
    def _sub_slot(m: re.Match) -> str:
        return "pyqtSlot as Slot"
    # Negative lookahead: don't double-rewrite if `pyqtSignal as Signal`
    # is already present.
    body = re.sub(r"(?<!pyqtSignal as )\bSignal\b", _sub_signal, body)
    body = re.sub(r"(?<!pyqtSlot as )\bSlot\b", _sub_slot, body)
    return body


def _apply_subs(text: str) -> str:
    for pattern, repl in _PACKAGE_SUBS:
        text = re.sub(pattern, repl, text)
    text = _QTCORE_SINGLE_RE.sub(
        lambda m: m.group(1) + _translate_signal_slot(m.group(2)), text)
    text = _QTCORE_PAREN_RE.sub(
        lambda m: m.group(1) + _translate_signal_slot(m.group(2)) + m.group(3),
        text)
    return text


def _verify_pyqt6() -> None:
    try:
        import PyQt6  # noqa: F401
    except ImportError:
        print("PyQt6 not installed. Installing via pip...", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "PyQt6"])


def _codemod_tree() -> None:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    shutil.copytree(ROOT, SCRATCH, ignore=shutil.ignore_patterns(
        "build_pyqt_tmp", "dist", "__pycache__", "*.pyc", ".git", ".venv",
        "*.doxyproj.json", "run.build", "run.dist", "run.onefile-build"))
    for py in SCRATCH.rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text = _apply_subs(text)
        if new_text != text:
            py.write_text(new_text, encoding="utf-8")


def _smoke_test() -> bool:
    """Import the transformed doxyedit.window module in a subprocess to
    catch binding incompatibilities before we start a 3-minute Nuitka
    build."""
    result = subprocess.run(
        [sys.executable, "-c", "import doxyedit.window; print('OK')"],
        cwd=SCRATCH, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("== PyQt6 smoke test failed ==", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return False
    print("PyQt6 smoke test: import OK")
    return True


def _nuitka_build() -> None:
    DIST.mkdir(exist_ok=True)
    exe_name = "DoxyEdit-pyqt.exe"
    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--standalone",
        "--enable-plugin=pyqt6",
        "--windows-console-mode=disable",
        "--assume-yes-for-downloads",
        "--output-dir=" + str(DIST),
        "--output-filename=" + exe_name,
        str(SCRATCH / "run.py"),
    ]
    print("Running Nuitka (this takes 3-10 minutes)...")
    subprocess.check_call(cmd)
    print(f"Built: {DIST / exe_name}")


def main() -> int:
    _verify_pyqt6()
    print("Codemodding PySide6 -> PyQt6 into", SCRATCH)
    _codemod_tree()
    if not _smoke_test():
        print("Smoke test failed. Inspect build_pyqt_tmp/ and fix any\n"
              "PySide6-specific idioms the regex couldn't translate.")
        return 1
    _nuitka_build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
