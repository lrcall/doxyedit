"""ExportCache — per-batch image cache for the export pipeline. The
contract this test pins down: a single source_path is decoded ONCE per
batch even when N platforms request it, and per-(asset, censored,
overlays) processed variants are also cached. If caching regresses,
multi-platform exports silently re-decode 100MB PSDs N times."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _solid(color=(10, 20, 30)):
    return Image.new("RGB", (8, 8), color)


class TestExportCache(unittest.TestCase):
    def test_load_raw_decodes_once_per_path(self):
        from doxyedit.export_cache import ExportCache
        from doxyedit import export_cache as ec_mod

        calls = []
        def fake_load(p):
            calls.append(p)
            return _solid()

        with patch.object(ec_mod, "load_image_for_export", side_effect=fake_load):
            c = ExportCache()
            a = c.load_raw("p.psd")
            b = c.load_raw("p.psd")
            d = c.load_raw("q.psd")

        self.assertIs(a, b)
        self.assertIsNot(a, d)
        self.assertEqual(calls, ["p.psd", "q.psd"])

    def test_load_raw_load_failure_returns_none(self):
        from doxyedit.export_cache import ExportCache
        from doxyedit import export_cache as ec_mod

        def boom(p):
            raise IOError("decode failed")

        with patch.object(ec_mod, "load_image_for_export", side_effect=boom):
            c = ExportCache()
            self.assertIsNone(c.load_raw("bad.psd"))

    def test_get_processed_caches_by_variant(self):
        """Same (asset, censored, with_overlays) triple must return the
        same image object on subsequent calls — that's the whole point."""
        from doxyedit.export_cache import ExportCache
        from doxyedit.models import Asset
        from doxyedit import export_cache as ec_mod

        with patch.object(ec_mod, "load_image_for_export", return_value=_solid()):
            c = ExportCache()
            a = Asset(id="a1", source_path="p.psd")
            v1 = c.get_processed(a, censored=False, with_overlays=False, project_dir="/x")
            v2 = c.get_processed(a, censored=False, with_overlays=False, project_dir="/x")
        self.assertIs(v1, v2)

    def test_get_processed_different_variants_diverge(self):
        from doxyedit.export_cache import ExportCache
        from doxyedit.models import Asset
        from doxyedit import export_cache as ec_mod

        with patch.object(ec_mod, "load_image_for_export", return_value=_solid()):
            c = ExportCache()
            a = Asset(id="a1", source_path="p.psd")
            uncen = c.get_processed(a, censored=False, with_overlays=False, project_dir="/x")
            cen = c.get_processed(a, censored=True, with_overlays=False, project_dir="/x")
        # No censors on the asset means apply_censors is skipped, but
        # the cache key still differs so we get a separate copy.
        self.assertIsNot(uncen, cen)

    def test_get_processed_load_failure_returns_none(self):
        from doxyedit.export_cache import ExportCache
        from doxyedit.models import Asset
        from doxyedit import export_cache as ec_mod

        with patch.object(ec_mod, "load_image_for_export", side_effect=IOError("x")):
            c = ExportCache()
            a = Asset(id="a1", source_path="missing.psd")
            self.assertIsNone(c.get_processed(
                a, censored=False, with_overlays=False, project_dir="/x"))

    def test_clear_drops_both_caches(self):
        from doxyedit.export_cache import ExportCache
        from doxyedit.models import Asset
        from doxyedit import export_cache as ec_mod

        calls = []
        def counting(p):
            calls.append(p)
            return _solid()

        with patch.object(ec_mod, "load_image_for_export", side_effect=counting):
            c = ExportCache()
            a = Asset(id="a1", source_path="p.psd")
            c.get_processed(a, censored=False, with_overlays=False, project_dir="/x")
            c.clear()
            c.get_processed(a, censored=False, with_overlays=False, project_dir="/x")

        # Cleared between calls → load_image_for_export ran twice.
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
