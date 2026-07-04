"""PSD Thumbnail Rule enforcement (see CLAUDE.md).

PSD/PSB thumbnails must come from the Windows shell thumbnail cache ONLY.
Opening the PSD itself (psd_tools) for a thumbnail is opt-in via the
psd_source_thumbs setting, default OFF. These tests are the tripwire that
keeps that behavior from regressing:

1. Behavior: with the gate off and no shell thumbnail, thumbnail code must
   NEVER call load_psd_thumb / load_psd - it returns a placeholder.
2. Source scan: UI modules that draw thumbnails must not call load_psd* directly.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _boom(*a, **k):
    raise AssertionError(
        "psd_tools was invoked for a thumbnail while the psd_source_thumbs "
        "gate was OFF - this violates the PSD Thumbnail Rule in CLAUDE.md")


class TestPsdThumbGateBehavior(unittest.TestCase):
    """With gate off + shell miss, psd_tools must never be touched."""

    def setUp(self):
        import doxyedit.imaging as imaging
        self.imaging = imaging
        self._orig = (imaging.get_shell_thumbnail,
                      imaging.psd_source_thumbs_enabled,
                      imaging.load_psd_thumb,
                      imaging.load_psd)
        imaging.get_shell_thumbnail = lambda path, size=256: None
        imaging.psd_source_thumbs_enabled = lambda: False
        imaging.load_psd_thumb = _boom
        imaging.load_psd = _boom

    def tearDown(self):
        (self.imaging.get_shell_thumbnail,
         self.imaging.psd_source_thumbs_enabled,
         self.imaging.load_psd_thumb,
         self.imaging.load_psd) = self._orig

    def test_open_for_thumb_returns_placeholder_not_psd_read(self):
        img, w, h = self.imaging.open_for_thumb("/no/such/file.psd", 160)
        self.assertEqual((w, h), (0, 0))          # placeholder contract
        self.assertEqual(img.size, (256, 256))

    def test_get_psd_thumb_pil_returns_none_not_psd_read(self):
        self.assertIsNone(self.imaging.get_psd_thumb_pil("/no/such/file.psd"))

    def test_gate_on_allows_fallback(self):
        self.imaging.psd_source_thumbs_enabled = lambda: True
        calls = []
        self.imaging.load_psd_thumb = lambda p, min_size=0: calls.append(p) or None
        self.imaging.get_psd_thumb_pil("/no/such/file.psd")
        self.assertEqual(calls, ["/no/such/file.psd"])


class TestNoDirectPsdReadsInThumbnailCode(unittest.TestCase):
    """Source tripwire: thumbnail-drawing modules must route PSDs through
    get_psd_thumb_pil / get_shell_thumbnail, never load_psd / load_psd_thumb.
    imaging.py (gated helpers) and thumbcache.py (gated slow pass) own the
    only sanctioned references."""

    THUMB_MODULES = ["composer_left.py", "timeline.py", "browser.py",
                     "tray.py", "tray_items.py", "gantt.py"]

    def test_no_load_psd_in_thumbnail_modules(self):
        pat = re.compile(r"\bload_psd(_thumb)?\b")
        offenders = []
        for name in self.THUMB_MODULES:
            src_file = REPO_ROOT / "doxyedit" / name
            if not src_file.exists():
                continue
            for i, line in enumerate(src_file.read_text(
                    encoding="utf-8", errors="replace").splitlines(), 1):
                if pat.search(line):
                    offenders.append(f"{name}:{i}: {line.strip()}")
        self.assertEqual(offenders, [], msg=(
            "Direct psd_tools thumbnail reads found - use "
            "imaging.get_psd_thumb_pil() instead (PSD Thumbnail Rule, "
            "CLAUDE.md):\n" + "\n".join(offenders)))

    def test_thumbcache_slow_pass_is_gated(self):
        src = (REPO_ROOT / "doxyedit" / "thumbcache.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("psd_source_thumbs_enabled", src, msg=(
            "thumbcache.py lost the psd_source_thumbs_enabled() gate on its "
            "psd_tools slow pass (PSD Thumbnail Rule, CLAUDE.md)"))


if __name__ == "__main__":
    unittest.main()
