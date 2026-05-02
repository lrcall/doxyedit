"""Boot smoke tests.

These don't validate behavior - they validate that the app builds at
all. Catches the kind of regressions that have bitten us in this
project: a tab construction path that crashes on a real project
("Social tab crash"), a QFont warning at launch, an import cycle
sneaking back in via a misplaced helper.

Run: py -m pytest tests/ -q
or:  py tests/test_smoke.py  (uses unittest fallback)
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Headless Qt for CI / unattended runs. Must precede the QApplication
# import to take effect.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestImports(unittest.TestCase):
    """All major modules import without raising."""

    MODULES = [
        "doxyedit.window",
        "doxyedit.studio",
        "doxyedit.preview",
        "doxyedit.composer",
        "doxyedit.composer_left",
        "doxyedit.composer_right",
        "doxyedit.imageviewer",
        "doxyedit.shared_identities",
        "doxyedit.tab_manager",
        "doxyedit.project_io",
        "doxyedit.themes",
        "doxyedit.directpost",
        "doxyedit.exporter",
        "doxyedit.pipeline",
    ]

    def test_imports(self):
        for mod in self.MODULES:
            with self.subTest(module=mod):
                __import__(mod)


class TestBoot(unittest.TestCase):
    """MainWindow constructs and every tab can be activated without
    raising. Catches the class of bug that hides behind pythonw."""

    def setUp(self):
        self.app = _ensure_app()

    def test_window_builds(self):
        from doxyedit.window import MainWindow
        w = MainWindow()
        self.assertGreater(w.tabs.count(), 0,
                           "MainWindow should have at least one tab")
        w.close()

    def test_every_tab_activates(self):
        from doxyedit.window import MainWindow
        w = MainWindow()
        names = []
        try:
            for i in range(w.tabs.count()):
                w.tabs.setCurrentIndex(i)
                names.append(w.tabs.tabText(i))
        finally:
            w.close()
        # v2.5 layout: Assets / Studio / Social / Platforms / Overview / Notes
        self.assertIn("Assets", names)
        self.assertIn("Studio", names)
        self.assertIn("Social", names)


class TestThemeContrast(unittest.TestCase):
    """All themes pass the WCAG contrast checker. The script returns
    0 on clean; non-zero on any violation."""

    def test_all_themes_pass(self):
        import subprocess
        script = REPO_ROOT / "scripts" / "check_theme_contrast.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(
            result.returncode, 0,
            f"check_theme_contrast.py reported failures:\n"
            f"{result.stdout}\n{result.stderr}")


class TestTokenization(unittest.TestCase):
    """No hardcoded chrome sizes / fonts in doxyedit/."""

    def test_validator_clean(self):
        import subprocess
        script = REPO_ROOT / "scripts" / "tokenize_validate.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(
            result.returncode, 0,
            f"tokenize_validate.py reported violations:\n"
            f"{result.stdout}\n{result.stderr}")


class TestModelRoundTrip(unittest.TestCase):
    """Project + SocialPost serialize and deserialize cleanly so a
    new field doesn't silently break legacy project files."""

    def test_socialpost_roundtrip(self):
        from doxyedit.models import SocialPost
        p = SocialPost(id="x", identity_name="Doxy", caption_default="hi")
        d = p.to_dict()
        p2 = SocialPost.from_dict(d)
        self.assertEqual(p2.id, "x")
        self.assertEqual(p2.identity_name, "Doxy")
        self.assertEqual(p2.caption_default, "hi")
        # Old data without identity_name still loads.
        legacy = SocialPost.from_dict({"id": "y", "caption_default": "ok"})
        self.assertEqual(legacy.identity_name, "")

    def test_cropregion_rotation(self):
        from doxyedit.models import CropRegion
        c = CropRegion(x=0, y=0, w=10, h=10, rotation=45.0)
        from dataclasses import asdict
        d = asdict(c)
        c2 = CropRegion(**d)
        self.assertEqual(c2.rotation, 45.0)
        # Old data without rotation still loads with default 0.
        c3 = CropRegion(**{"x": 0, "y": 0, "w": 10, "h": 10, "label": ""})
        self.assertEqual(c3.rotation, 0.0)


if __name__ == "__main__":
    unittest.main()
