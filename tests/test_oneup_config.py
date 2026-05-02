"""oneup.py — config.yaml parsing for the OneUp posting integration.

Tests use a tempdir-mocked _find_config so they never read the user's
real config.yaml (which carries live API keys). They cover the multi-
account format, the legacy flat format, and the missing/corrupt
fallbacks. Pin these because a regression here either silently posts
to the wrong account or drops the OneUp button entirely."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _write_config(d: Path, content: str) -> Path:
    p = d / "config.yaml"
    p.write_text(content, encoding="utf-8")
    return p


class TestGetActiveAccountLabel(unittest.TestCase):
    def test_missing_config_returns_empty(self):
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            with patch.object(oneup, "_find_config",
                              return_value=Path(td) / "missing.yaml"):
                self.assertEqual(oneup.get_active_account_label(td), "")

    def test_active_account_returns_label(self):
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_config(Path(td), """
oneup:
  active_account: main
  accounts:
    main:
      api_key: K
      label: Main Acct
    other:
      api_key: K2
      label: Other Acct
""")
            with patch.object(oneup, "_find_config", return_value=cfg):
                self.assertEqual(oneup.get_active_account_label(td), "Main Acct")

    def test_flat_format_returns_empty(self):
        """Legacy flat format has no labels — empty string is the
        documented behavior."""
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_config(Path(td), "oneup:\n  api_key: K\n")
            with patch.object(oneup, "_find_config", return_value=cfg):
                self.assertEqual(oneup.get_active_account_label(td), "")


class TestGetCategories(unittest.TestCase):
    def test_returns_list_for_active_account(self):
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_config(Path(td), """
oneup:
  active_account: main
  accounts:
    main:
      api_key: K
      categories:
        - {id: 86698, name: Doxy}
        - {id: 176197, name: Onta}
""")
            with patch.object(oneup, "_find_config", return_value=cfg):
                cats = oneup.get_categories(td)
                self.assertEqual(len(cats), 2)
                self.assertEqual(cats[0]["name"], "Doxy")

    def test_empty_when_no_categories(self):
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_config(Path(td), "oneup:\n  api_key: K\n")
            with patch.object(oneup, "_find_config", return_value=cfg):
                self.assertEqual(oneup.get_categories(td), [])

    def test_corrupt_yaml_returns_empty(self):
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_config(Path(td), ":\n: bad")
            with patch.object(oneup, "_find_config", return_value=cfg):
                self.assertEqual(oneup.get_categories(td), [])


class TestGetConnectedPlatforms(unittest.TestCase):
    def test_returns_configured_list(self):
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_config(Path(td), """
oneup:
  active_account: main
  accounts:
    main:
      api_key: K
      connected:
        - {id: bluesky, name: Bluesky}
""")
            with patch.object(oneup, "_find_config", return_value=cfg):
                out = oneup.get_connected_platforms(td)
                self.assertEqual(out, [{"id": "bluesky", "name": "Bluesky"}])

    def test_falls_back_to_default_list(self):
        """When no connected list is configured, default to the bundled
        platform list. UI relies on getting *something* back."""
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_config(Path(td), "oneup:\n  api_key: K\n")
            with patch.object(oneup, "_find_config", return_value=cfg):
                out = oneup.get_connected_platforms(td)
                ids = {p["id"] for p in out}
                self.assertIn("twitter", ids)
                self.assertIn("bluesky", ids)


class TestListAccountNames(unittest.TestCase):
    def test_lists_all_accounts(self):
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_config(Path(td), """
oneup:
  active_account: a
  accounts:
    a: {api_key: K1, label: First}
    b: {api_key: K2, label: Second}
""")
            with patch.object(oneup, "_find_config", return_value=cfg):
                out = dict(oneup.list_account_names(td))
                self.assertEqual(out, {"a": "First", "b": "Second"})

    def test_empty_when_flat_format(self):
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            cfg = _write_config(Path(td), "oneup:\n  api_key: K\n")
            with patch.object(oneup, "_find_config", return_value=cfg):
                self.assertEqual(oneup.list_account_names(td), [])

    def test_empty_when_no_config(self):
        from doxyedit import oneup
        with tempfile.TemporaryDirectory() as td:
            with patch.object(oneup, "_find_config",
                              return_value=Path(td) / "missing.yaml"):
                self.assertEqual(oneup.list_account_names(td), [])


if __name__ == "__main__":
    unittest.main()
