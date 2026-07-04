"""Shared pytest configuration for the DoxyEdit test suite.

Sets headless-safe Qt environment defaults at collection time, BEFORE
any test module (and therefore any Qt binding) is imported. Existing
unittest-style tests self-manage their QApplication via private
helpers - this conftest must not interfere with them, so it only:

  1. seeds QT_QPA_PLATFORM / QT_LOGGING_RULES via os.environ.setdefault
     (a value already set by the shell or a test module wins), and
  2. offers an optional session-scoped `qapp` fixture for future
     pytest-style widget tests.

The QApplication is a process singleton that is never quit, matching
the convention used by the unittest helpers (see tests/test_smoke.py).
No Qt import happens at module scope here - only inside the fixture.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Headless rendering for every collected test, unless already set.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Quiet Qt's chatty categories (font/dpi/qpa probing) in test output.
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.qpa.*=false")

# Match the repo-wide test header convention so bare `pytest` from any
# CWD still resolves the doxyedit package.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for pytest-style widget tests.

    Returns the existing singleton if a unittest helper already built
    one; never quits it (other tests in the process may still need it).
    """
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
