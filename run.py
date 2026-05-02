"""Quick launcher - run with: python run.py

When launched via pythonw / pyw (no console attached), Python's stdout
and stderr are silently dropped. Without redirection a hard crash leaves
no record on disk, and the user sees only "the app didn't start".
We redirect both streams into ~/.doxyedit/last_run.log before importing
the GUI so any traceback during startup or runtime ends up there.

When launched via console Python (py / python), stdout already goes to
the terminal and we leave it alone."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _wire_log_for_pythonw() -> None:
    """Redirect stdout+stderr to a log file when running headless.

    pythonw replaces stdout/stderr with None on Windows, so any
    .write() raises before redirection. Detect that and point both
    streams at ~/.doxyedit/last_run.log."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_dir = Path.home() / ".doxyedit"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    log_path = log_dir / "last_run.log"
    try:
        # Line-buffered, append, utf-8. Truncating would lose the
        # previous crash before the user could read it.
        f = open(log_path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    sys.stdout = f
    sys.stderr = f
    print(f"\n--- DoxyEdit started, pid={os.getpid()} ---", flush=True)


_wire_log_for_pythonw()

from doxyedit.main import main
main()
