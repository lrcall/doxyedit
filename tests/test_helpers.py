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

    def test_apply_menu_theme_writes_stylesheet(self):
        """apply_menu_theme should populate the menu's styleSheet so
        Windows top-level popups stop rendering with the OS default."""
        from PySide6.QtWidgets import QApplication, QMenu
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        from doxyedit.themes import apply_menu_theme, THEMES, DEFAULT_THEME
        m = QMenu()
        self.assertEqual(m.styleSheet(), "")
        apply_menu_theme(m, THEMES[DEFAULT_THEME])
        # Should have written a non-empty stylesheet.
        self.assertGreater(len(m.styleSheet()), 50)
        # Stylesheet references the theme's bg_raised.
        self.assertIn(THEMES[DEFAULT_THEME].bg_raised, m.styleSheet())

    def test_apply_menu_theme_reads_from_qsettings_when_no_arg(self):
        """If no theme is passed, apply_menu_theme should fall back to
        the QSettings-stored theme name. We don't test the QSettings
        side directly; just confirm the no-arg path doesn't raise and
        produces a non-empty stylesheet."""
        from PySide6.QtWidgets import QApplication, QMenu
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        from doxyedit.themes import apply_menu_theme
        m = QMenu()
        apply_menu_theme(m)  # no theme arg
        self.assertGreater(len(m.styleSheet()), 50)


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

    def test_negative_rotation(self):
        from doxyedit.exporter import apply_crop_rect
        from types import SimpleNamespace
        crop = SimpleNamespace(x=10, y=10, w=50, h=50, rotation=-30.0)
        out = apply_crop_rect(self.img, crop)
        self.assertEqual(out.size, (50, 50))

    def test_full_360_rotation(self):
        """360deg should be equivalent to 0deg - no real visual change.
        Just confirms apply_crop_rect doesn't crash on full rotation."""
        from doxyedit.exporter import apply_crop_rect
        from types import SimpleNamespace
        crop = SimpleNamespace(x=10, y=10, w=50, h=50, rotation=360.0)
        out = apply_crop_rect(self.img, crop)
        self.assertEqual(out.size, (50, 50))

    def test_rotation_none_treated_as_zero(self):
        """A None rotation (e.g. JSON null leaking through) defaults to 0."""
        from doxyedit.exporter import apply_crop_rect
        from types import SimpleNamespace
        crop = SimpleNamespace(x=10, y=10, w=50, h=50, rotation=None)
        out = apply_crop_rect(self.img, crop)
        self.assertEqual(out.size, (50, 50))


class TestSharedIdentities(unittest.TestCase):
    """shared_identities round-trip + merge strategies behave correctly."""

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

    def test_save_load_round_trip_via_publish_one(self):
        """publish_one writes to shared_path(); load_shared reads back.
        Use a tempdir + monkeypatched shared_path so the user's real
        ~/.doxyedit/identities.json isn't touched."""
        import tempfile
        from unittest.mock import patch
        from pathlib import Path
        from doxyedit import shared_identities as si
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "identities.json"
            with patch.object(si, "shared_path", return_value=target):
                self.assertEqual(si.load_shared(), {})  # missing file -> {}
                ok = si.publish_one(
                    "Doxy", {"voice": "playful", "hashtags": ["#a"]})
                self.assertTrue(ok)
                stored = si.load_shared()
                self.assertEqual(set(stored.keys()), {"Doxy"})
                self.assertEqual(stored["Doxy"]["voice"], "playful")
                # Writing a second identity preserves the first.
                si.publish_one("Onta", {"voice": "subtle"})
                self.assertEqual(
                    set(si.load_shared().keys()), {"Doxy", "Onta"})

    def test_corrupt_shared_file_loads_empty(self):
        """A corrupt JSON file in the shared store should not block
        project load; load_shared returns {}."""
        import tempfile
        from unittest.mock import patch
        from pathlib import Path
        from doxyedit import shared_identities as si
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "identities.json"
            target.write_text("not valid {json", encoding="utf-8")
            with patch.object(si, "shared_path", return_value=target):
                self.assertEqual(si.load_shared(), {})

    def test_shared_wins_strategy(self):
        """shared_wins overrides project values for keys in both."""
        import tempfile
        from unittest.mock import patch
        from pathlib import Path
        from doxyedit import shared_identities as si
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "identities.json"
            with patch.object(si, "shared_path", return_value=target):
                si.publish_one("Doxy", {"voice": "shared voice"})
                merged = si.merge_into_project(
                    {"Doxy": {"voice": "local voice"}},
                    strategy="shared_wins")
                self.assertEqual(merged["Doxy"]["voice"], "shared voice")


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


class TestBaseImageViewer(unittest.TestCase):
    """BaseImageViewer set_pixmap / set_path / clear / fit_to_view
    smoke + signal contract guard."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QApplication.instance() or QApplication([])

    def test_empty_pixmap_emits_failed(self):
        from doxyedit.imageviewer import BaseImageViewer
        from PySide6.QtGui import QPixmap
        v = BaseImageViewer()
        seen = []
        v.pixmap_failed.connect(lambda path: seen.append(path))
        v.set_pixmap(QPixmap())
        self.assertEqual(seen, [""])
        self.assertIsNone(v._pixmap_item)

    def test_valid_pixmap_emits_loaded(self):
        from doxyedit.imageviewer import BaseImageViewer
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import Qt
        v = BaseImageViewer()
        seen = []
        v.pixmap_loaded.connect(lambda pm: seen.append(pm.size().width()))
        pm = QPixmap(100, 50)
        pm.fill(Qt.GlobalColor.red)
        v.set_pixmap(pm)
        self.assertEqual(seen, [100])
        self.assertIsNotNone(v._pixmap_item)

    def test_clear_drops_item(self):
        from doxyedit.imageviewer import BaseImageViewer
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import Qt
        v = BaseImageViewer()
        pm = QPixmap(50, 50)
        pm.fill(Qt.GlobalColor.blue)
        v.set_pixmap(pm)
        self.assertIsNotNone(v._pixmap_item)
        v.clear()
        self.assertIsNone(v._pixmap_item)

    def test_set_path_missing_file_fails_gracefully(self):
        from doxyedit.imageviewer import BaseImageViewer
        v = BaseImageViewer()
        seen = []
        v.pixmap_failed.connect(lambda path: seen.append(path))
        v.set_path("/this/path/does/not/exist.png")
        self.assertEqual(len(seen), 1)
        self.assertIn("does", seen[0])

    def test_set_path_real_file_loads_pixmap(self):
        """Regression guard: load_pixmap returns (pixmap, w, h) — set_path
        used to crash on .isNull() because it didn't unpack the tuple.
        Fixed in this commit; test pins it down."""
        import tempfile
        from doxyedit.imageviewer import BaseImageViewer
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import Qt
        # Build a tiny PNG to disk.
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        try:
            pm = QPixmap(20, 20)
            pm.fill(Qt.GlobalColor.green)
            pm.save(tmp_path, "PNG")
            v = BaseImageViewer()
            failed = []
            loaded = []
            v.pixmap_failed.connect(lambda p: failed.append(p))
            v.pixmap_loaded.connect(lambda px: loaded.append(px))
            v.set_path(tmp_path)
            self.assertEqual(failed, [])
            self.assertEqual(len(loaded), 1)
            self.assertIsNotNone(v._pixmap_item)
        finally:
            import os
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


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


class TestResizableCropItemRotation(unittest.TestCase):
    """ResizableCropItem.get_crop_region carries rotation_deg through
    so dragging / resizing a rotated crop doesn't silently zero the
    rotation. Regression covered originally by 1dccaa6."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QApplication.instance() or QApplication([])

    def test_rotation_preserved_on_get_crop_region(self):
        from PySide6.QtCore import QRectF
        from doxyedit.preview import ResizableCropItem
        item = ResizableCropItem(QRectF(0, 0, 100, 100), label="test")
        item.rotation_deg = 30.0
        cr = item.get_crop_region()
        self.assertEqual(cr.rotation, 30.0)
        self.assertEqual(cr.label, "test")

    def test_default_rotation_is_zero(self):
        from PySide6.QtCore import QRectF
        from doxyedit.preview import ResizableCropItem
        item = ResizableCropItem(QRectF(0, 0, 100, 100))
        cr = item.get_crop_region()
        self.assertEqual(cr.rotation, 0.0)

    def test_rotate_handle_added_to_handle_rects(self):
        """The visual rotate handle (shipped in 910279a) is the 9th
        entry. Regression guard so a future paint refactor doesn't
        accidentally drop it."""
        from PySide6.QtCore import QRectF
        from doxyedit.preview import ResizableCropItem
        item = ResizableCropItem(QRectF(0, 0, 100, 100))
        rects = item._handle_rects()
        self.assertEqual(len(rects), 9)
        # Handle 8 (rotate) sits above the rect's top edge.
        self.assertLess(rects[8].center().y(), 0)


if __name__ == "__main__":
    unittest.main()
