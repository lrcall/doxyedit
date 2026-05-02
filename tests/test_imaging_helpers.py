"""imaging.py — testable helpers that don't require Qt or actual image
decoding: get_export_dir (sidecar folder naming), _preview_cache_key
(stable hash for caching). The rest of imaging.py touches Win32 shell
thumb APIs / psd_tools and isn't unit-testable headless."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestGetExportDir(unittest.TestCase):
    def test_creates_sidecar_for_doxy_project(self):
        from doxyedit.imaging import get_export_dir
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "socials.doxy"
            proj.touch()
            out = get_export_dir(str(proj))
            self.assertTrue(out.is_dir())
            self.assertEqual(out.name, "socials_assets")

    def test_strips_doxyproj_double_ext(self):
        """Legacy .doxyproj.json extensions: stem-stripping must remove
        the inner .doxyproj segment too, otherwise the sidecar name
        gets a .doxyproj prefix."""
        from doxyedit.imaging import get_export_dir
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "art.doxyproj.json"
            proj.touch()
            out = get_export_dir(str(proj))
            self.assertEqual(out.name, "art_assets")

    def test_returns_existing_dir_unchanged(self):
        from doxyedit.imaging import get_export_dir
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "x.doxy"
            proj.touch()
            existing = Path(td) / "x_assets"
            existing.mkdir()
            (existing / "marker.txt").touch()
            out = get_export_dir(str(proj))
            self.assertEqual(out, existing)
            self.assertTrue((out / "marker.txt").exists())

    def test_collision_with_file_picks_suffix(self):
        """If a non-dir file already squats the sidecar name, the
        function must dodge to a numbered alternate."""
        from doxyedit.imaging import get_export_dir
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "y.doxy"
            proj.touch()
            blocker = Path(td) / "y_assets"
            blocker.touch()  # file, not dir
            out = get_export_dir(str(proj))
            self.assertTrue(out.is_dir())
            self.assertNotEqual(out, blocker)
            self.assertTrue(out.name.startswith("y_assets_"))


class TestPreviewCacheKey(unittest.TestCase):
    def test_stable_for_same_file_same_mtime(self):
        from doxyedit.imaging import _preview_cache_key
        with tempfile.NamedTemporaryFile(delete=False, suffix=".psd") as f:
            p = f.name
        try:
            k1 = _preview_cache_key(p)
            k2 = _preview_cache_key(p)
            self.assertEqual(k1, k2)
            self.assertEqual(len(k1), 32)  # md5 hex
        finally:
            os.unlink(p)

    def test_different_paths_different_keys(self):
        from doxyedit.imaging import _preview_cache_key
        with tempfile.NamedTemporaryFile(delete=False) as f1:
            p1 = f1.name
        with tempfile.NamedTemporaryFile(delete=False) as f2:
            p2 = f2.name
        try:
            self.assertNotEqual(_preview_cache_key(p1), _preview_cache_key(p2))
        finally:
            os.unlink(p1)
            os.unlink(p2)


if __name__ == "__main__":
    unittest.main()
