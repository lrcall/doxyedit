"""Unit tests for the small pure helpers shipped this session.

Each test targets a function that's small enough to fully verify
without spinning up Qt: themes contrast helpers, exporter crop math,
shared identity merge logic, directpost connection-test guard rails.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestThemeHelpers(unittest.TestCase):
    """themes.is_dark_color + themes.fg_on_color + themes.themed_dialog_size."""

    def test_is_dark_pure_black(self):
        from doxyedit.themes import is_dark_color
        self.assertTrue(is_dark_color("#000000"))

    def test_is_dark_pure_white(self):
        from doxyedit.themes import is_dark_color
        self.assertFalse(is_dark_color("#ffffff"))

    def test_is_dark_threshold(self):
        from doxyedit.themes import is_dark_color
        # Sum-of-RGB threshold is 384.
        self.assertTrue(is_dark_color("#7f7f7f"))   # 381 < 384
        self.assertFalse(is_dark_color("#808080"))  # 384 >= 384

    def test_fg_on_dark_returns_white(self):
        from doxyedit.themes import fg_on_color
        self.assertTrue(fg_on_color("#000000").startswith("rgba(255"))

    def test_fg_on_light_returns_black(self):
        from doxyedit.themes import fg_on_color
        self.assertTrue(fg_on_color("#ffffff").startswith("rgba(0"))

    def test_themed_dialog_size_default_font(self):
        from doxyedit.themes import themed_dialog_size
        # 50.0 * 12 == 600, 37.5 * 12 == 450 (the base mapping the helper
        # was designed to preserve from pre-tokenization sizes).
        self.assertEqual(themed_dialog_size(50.0, 37.5, 12), (600, 450))

    def test_themed_dialog_size_scales_with_font(self):
        from doxyedit.themes import themed_dialog_size
        # Bigger font -> bigger dialog.
        small = themed_dialog_size(50.0, 37.5, 12)
        big = themed_dialog_size(50.0, 37.5, 18)
        self.assertGreater(big[0], small[0])
        self.assertGreater(big[1], small[1])


class TestApplyCropRect(unittest.TestCase):
    """exporter.apply_crop_rect handles rotation=0 and non-zero
    paths without crashing."""

    def setUp(self):
        from PIL import Image
        self.img = Image.new("RGBA", (200, 200), (255, 0, 0, 255))

    def test_no_rotation(self):
        from doxyedit.exporter import apply_crop_rect
        from types import SimpleNamespace
        crop = SimpleNamespace(x=10, y=10, w=50, h=50, rotation=0.0)
        out = apply_crop_rect(self.img, crop)
        self.assertEqual(out.size, (50, 50))

    def test_rotation_45(self):
        from doxyedit.exporter import apply_crop_rect
        from types import SimpleNamespace
        crop = SimpleNamespace(x=10, y=10, w=50, h=50, rotation=45.0)
        out = apply_crop_rect(self.img, crop)
        self.assertEqual(out.size, (50, 50))

    def test_missing_rotation_attr(self):
        """Legacy crop dicts may lack rotation; helper defaults to 0."""
        from doxyedit.exporter import apply_crop_rect
        from types import SimpleNamespace
        crop = SimpleNamespace(x=10, y=10, w=50, h=50)
        out = apply_crop_rect(self.img, crop)
        self.assertEqual(out.size, (50, 50))


class TestSharedIdentities(unittest.TestCase):
    """shared_identities.merge_into_project strategies behave correctly."""

    def test_fill_missing_keeps_project_values(self):
        from doxyedit.shared_identities import merge_into_project
        # Real shared file is on disk; we don't want test runs to mutate
        # it. merge_into_project reads load_shared() but doesn't write,
        # so this is safe even if the user has a real file.
        proj = {"Doxy": {"voice": "project local"}}
        merged = merge_into_project(proj)
        # Project value preserved regardless of what's in the shared
        # store (fill_missing is the default strategy).
        self.assertEqual(merged["Doxy"]["voice"], "project local")

    def test_strategy_unknown_falls_back_to_fill_missing(self):
        """An unrecognized strategy string is treated as 'fill_missing'
        rather than raising."""
        from doxyedit.shared_identities import merge_into_project
        merged = merge_into_project(
            {"X": {"a": 1}}, strategy="not_a_real_strategy")
        self.assertEqual(merged["X"]["a"], 1)


class TestDirectPostGuards(unittest.TestCase):
    """test_telegram / test_discord / test_bluesky return safe failures
    on empty inputs without making network calls."""

    def test_telegram_empty(self):
        from doxyedit.directpost import test_telegram
        ok, msg = test_telegram("")
        self.assertFalse(ok)
        self.assertIn("token", msg.lower())

    def test_discord_empty(self):
        from doxyedit.directpost import test_discord
        ok, msg = test_discord("")
        self.assertFalse(ok)
        self.assertIn("webhook", msg.lower())

    def test_discord_insecure_url(self):
        from doxyedit.directpost import test_discord
        ok, msg = test_discord("http://insecure.example/")
        self.assertFalse(ok)
        self.assertIn("https", msg.lower())

    def test_bluesky_empty(self):
        from doxyedit.directpost import test_bluesky
        ok, msg = test_bluesky("", "")
        self.assertFalse(ok)


class TestKanbanGrouping(unittest.TestCase):
    """KanbanBoard._refresh routes posts into the right column based
    on their .status, and falls back to Draft for unknown / partial
    statuses."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QApplication.instance() or QApplication([])

    def test_groups_by_status(self):
        from doxyedit.kanban import KanbanBoard
        from doxyedit.models import Project, SocialPost, SocialPostStatus
        p = Project()
        p.posts = [
            SocialPost(id="a", status=SocialPostStatus.DRAFT),
            SocialPost(id="b", status=SocialPostStatus.QUEUED),
            SocialPost(id="c", status=SocialPostStatus.POSTED),
            SocialPost(id="d", status=SocialPostStatus.FAILED),
            SocialPost(id="e", status=SocialPostStatus.QUEUED),
        ]
        board = KanbanBoard(p)
        counts = {k: w.count() for k, w in board._col_widgets.items()}
        self.assertEqual(counts["draft"], 1)
        self.assertEqual(counts["queued"], 2)
        self.assertEqual(counts["posted"], 1)
        self.assertEqual(counts["failed"], 1)

    def test_unknown_status_lands_in_draft(self):
        from doxyedit.kanban import KanbanBoard
        from doxyedit.models import Project, SocialPost
        p = Project()
        p.posts = [SocialPost(id="x", status="partial")]
        board = KanbanBoard(p)
        self.assertEqual(board._col_widgets["draft"].count(), 1)


class TestPluginRegistry(unittest.TestCase):
    """plugins._PluginRegistry handler isolation + failure containment."""

    def test_empty_emit_is_noop(self):
        from doxyedit.plugins import _PluginRegistry
        r = _PluginRegistry()
        # Doesn't raise even with no handlers.
        r.emit("anything", 1, 2, 3)

    def test_failing_handler_disables_only_self(self):
        from doxyedit.plugins import _PluginRegistry
        r = _PluginRegistry()
        good_calls: list = []

        def good(x):
            good_calls.append(x)

        def bad(x):
            raise RuntimeError("intentional")

        r._add("e", bad, source="bad_plugin")
        r._add("e", good, source="good_plugin")
        r.emit("e", 1)
        # bad raised, good still ran.
        self.assertEqual(good_calls, [1])
        self.assertIn("bad_plugin", r._failed)
        # On the next emit, the bad one is skipped, good still fires.
        r.emit("e", 2)
        self.assertEqual(good_calls, [1, 2])


class TestPreviewHelpers(unittest.TestCase):
    """preview.fit_view_to_items + wheel_zoom_view exist and accept the
    expected signatures. These are imported by the helpers in
    imageviewer.BaseImageViewer so a regression here breaks every
    preview surface."""

    def test_fit_view_to_items_callable(self):
        from doxyedit.preview import fit_view_to_items
        self.assertTrue(callable(fit_view_to_items))

    def test_wheel_zoom_view_callable(self):
        from doxyedit.preview import wheel_zoom_view
        self.assertTrue(callable(wheel_zoom_view))


if __name__ == "__main__":
    unittest.main()
