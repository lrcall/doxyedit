"""imageviewer._xform_mode + preview._preview_xform_mode — both
read the QSettings 'preview_bilinear' bool to decide between Smooth
and Fast pixmap transformations. Pin so a regression doesn't flip
every preview between bilinear and nearest silently."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _setup_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _FakeSettings:
    def __init__(self, value):
        self._value = value

    def value(self, key, default, type=None):
        return self._value


class TestXformModeImageviewer(unittest.TestCase):
    def setUp(self):
        self.app = _setup_qt()

    def test_bilinear_returns_smooth(self):
        from PySide6.QtCore import Qt
        from doxyedit import imageviewer
        with patch.object(imageviewer, "QSettings",
                          lambda *a: _FakeSettings(True)):
            self.assertEqual(imageviewer._xform_mode(),
                             Qt.TransformationMode.SmoothTransformation)

    def test_off_returns_fast(self):
        from PySide6.QtCore import Qt
        from doxyedit import imageviewer
        with patch.object(imageviewer, "QSettings",
                          lambda *a: _FakeSettings(False)):
            self.assertEqual(imageviewer._xform_mode(),
                             Qt.TransformationMode.FastTransformation)


class TestXformModePreview(unittest.TestCase):
    def setUp(self):
        self.app = _setup_qt()

    def test_bilinear_returns_smooth(self):
        from PySide6.QtCore import Qt
        from doxyedit import preview
        with patch.object(preview, "QSettings",
                          lambda *a: _FakeSettings(True)):
            self.assertEqual(preview._preview_xform_mode(),
                             Qt.TransformationMode.SmoothTransformation)

    def test_off_returns_fast(self):
        from PySide6.QtCore import Qt
        from doxyedit import preview
        with patch.object(preview, "QSettings",
                          lambda *a: _FakeSettings(False)):
            self.assertEqual(preview._preview_xform_mode(),
                             Qt.TransformationMode.FastTransformation)


if __name__ == "__main__":
    unittest.main()
