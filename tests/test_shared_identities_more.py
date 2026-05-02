"""shared_identities — extend coverage beyond the existing
test_helpers.TestSharedIdentities (which covers the fill_missing
default + shared_wins strategy). Pin publish_one + project_wins +
known_names + the overlap behavior for each strategy."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _patch_path(td):
    """Patch shared_identities.shared_path() to a tempdir file."""
    from doxyedit import shared_identities
    return patch.object(shared_identities, "shared_path",
                         return_value=Path(td) / "identities.json")


class TestPublishOne(unittest.TestCase):
    def test_publish_to_empty_store(self):
        from doxyedit import shared_identities
        with tempfile.TemporaryDirectory() as td, _patch_path(td):
            ok = shared_identities.publish_one(
                "Doxy", {"voice": "casual", "patreon_url": "p"})
            self.assertTrue(ok)
            shared = shared_identities.load_shared()
            self.assertEqual(shared["Doxy"]["voice"], "casual")

    def test_publish_preserves_other_names(self):
        from doxyedit import shared_identities
        with tempfile.TemporaryDirectory() as td, _patch_path(td):
            shared_identities.publish_one("Doxy", {"voice": "a"})
            shared_identities.publish_one("Onta", {"voice": "b"})
            shared = shared_identities.load_shared()
            self.assertEqual(set(shared.keys()), {"Doxy", "Onta"})

    def test_blank_name_returns_false(self):
        from doxyedit import shared_identities
        with tempfile.TemporaryDirectory() as td, _patch_path(td):
            self.assertFalse(shared_identities.publish_one("", {"x": 1}))


class TestProjectWins(unittest.TestCase):
    def test_project_overrides_shared_for_same_name(self):
        from doxyedit import shared_identities
        with tempfile.TemporaryDirectory() as td, _patch_path(td):
            shared_identities.publish_one(
                "Doxy", {"voice": "shared_voice", "url": "shared_url"})
            project = {"Doxy": {"voice": "project_voice"}}
            out = shared_identities.merge_into_project(
                project, strategy="project_wins")
            # Project's voice wins; shared url survives because project
            # didn't define it.
            self.assertEqual(out["Doxy"]["voice"], "project_voice")
            self.assertEqual(out["Doxy"]["url"], "shared_url")

    def test_project_wins_adds_missing_shared(self):
        from doxyedit import shared_identities
        with tempfile.TemporaryDirectory() as td, _patch_path(td):
            shared_identities.publish_one("Onta", {"voice": "v"})
            out = shared_identities.merge_into_project(
                {}, strategy="project_wins")
            self.assertIn("Onta", out)


class TestKnownNames(unittest.TestCase):
    def test_empty_store_returns_empty(self):
        from doxyedit import shared_identities
        with tempfile.TemporaryDirectory() as td, _patch_path(td):
            self.assertEqual(shared_identities.known_names(), [])

    def test_returns_sorted(self):
        from doxyedit import shared_identities
        with tempfile.TemporaryDirectory() as td, _patch_path(td):
            shared_identities.publish_one("Zeta", {})
            shared_identities.publish_one("Alpha", {})
            shared_identities.publish_one("Mu", {})
            self.assertEqual(shared_identities.known_names(),
                             ["Alpha", "Mu", "Zeta"])


class TestMergeStrategies(unittest.TestCase):
    def test_fill_missing_does_not_overwrite_project(self):
        from doxyedit import shared_identities
        with tempfile.TemporaryDirectory() as td, _patch_path(td):
            shared_identities.publish_one(
                "Doxy", {"voice": "shared", "url": "shared_url"})
            project = {"Doxy": {"voice": "project"}}
            out = shared_identities.merge_into_project(
                project, strategy="fill_missing")
            # Project's "Doxy" wins outright; shared "Doxy" not merged.
            self.assertEqual(out["Doxy"], {"voice": "project"})
            self.assertNotIn("url", out["Doxy"])

    def test_unknown_strategy_falls_back_to_fill_missing(self):
        from doxyedit import shared_identities
        with tempfile.TemporaryDirectory() as td, _patch_path(td):
            shared_identities.publish_one("Onta", {"voice": "v"})
            out = shared_identities.merge_into_project(
                {}, strategy="not_a_real_strategy")
            # Falls through to the else branch.
            self.assertIn("Onta", out)


if __name__ == "__main__":
    unittest.main()
