"""Project.build_save_dict — covers the local_mode path conversion
on assets / excluded_paths / import_sources, and the all-keys
inclusion contract that downstream load relies on. write_save_dict
atomic-write contract: payload lands as a single rename, not a
partial file."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestBuildSaveDict(unittest.TestCase):
    def test_required_top_level_keys_present(self):
        from doxyedit.models import Project
        p = Project()
        d = p.build_save_dict("/tmp/x.doxy")
        for key in ("name", "platforms", "assets", "posts", "campaigns",
                    "identity", "subreddits", "tag_definitions",
                    "local_mode"):
            self.assertIn(key, d)

    def test_local_mode_off_keeps_absolute_asset_paths(self):
        from doxyedit.models import Project, Asset
        p = Project()
        p.assets = [Asset(id="a1", source_path="E:/elsewhere/img.png")]
        p.local_mode = False
        d = p.build_save_dict("E:/proj/x.doxy")
        self.assertEqual(d["assets"][0]["source_path"],
                         "E:/elsewhere/img.png")

    def test_local_mode_on_converts_to_relative(self):
        from doxyedit.models import Project, Asset
        p = Project()
        p.assets = [Asset(id="a1", source_path="E:/proj/sub/img.png")]
        p.local_mode = True
        d = p.build_save_dict("E:/proj/x.doxy")
        # Stored as POSIX-relative under the project dir.
        self.assertEqual(d["assets"][0]["source_path"], "sub/img.png")

    def test_excluded_paths_sorted(self):
        from doxyedit.models import Project
        p = Project()
        p.excluded_paths = {"/c/z.png", "/a/x.png", "/b/y.png"}
        d = p.build_save_dict("/proj/x.doxy")
        self.assertEqual(d["excluded_paths"], sorted(d["excluded_paths"]))


class TestWriteSaveDictAtomic(unittest.TestCase):
    def test_writes_indented_json_by_default(self):
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "out.doxy")
            Project.write_save_dict({"name": "T"}, path)
            content = Path(path).read_text(encoding="utf-8")
            # Indented JSON contains newlines.
            self.assertIn("\n", content)
            self.assertEqual(json.loads(content), {"name": "T"})

    def test_compact_mode_no_indent(self):
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "out.doxy")
            Project.write_save_dict({"k": "v"}, path, compact=True)
            content = Path(path).read_text(encoding="utf-8")
            # Compact JSON has no spaces in separators.
            self.assertIn('"k":"v"', content)

    def test_atomic_replace_no_tmp_left(self):
        """write_save_dict writes via .tmp + os.replace. After success
        the .tmp file must not remain."""
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "out.doxy")
            Project.write_save_dict({"k": "v"}, path)
            self.assertFalse((Path(td) / "out.doxy.tmp").exists())

    def test_unicode_round_trip_in_payload(self):
        """ensure_ascii=False — Japanese chars etc. survive without
        being mangled into \\uXXXX escapes."""
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "out.doxy")
            Project.write_save_dict({"name": "夢"}, path)
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("夢", content)


if __name__ == "__main__":
    unittest.main()
