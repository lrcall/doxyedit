"""Perf regression gate - a 10k-asset project timed through the real
model hot paths: in-memory object construction, build_save_dict, save
to a temp file, Project.load back, and summary(). Budgets are
GENEROUS (windows-latest CI runner variance) so only a real
O(n^2)-class regression trips them. Measured times are baked into
every assert message so CI logs show the trend even on failure.

Deselect quickly if ever needed: py -m pytest -k "not PerfBudget".
"""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

N_ASSETS = 10_000

# Generous CI-safe budgets in seconds. Local runs are typically 10-50x
# faster; these exist only to catch an accidental O(n^2) in the loops.
BUDGET_BUILD_OBJECTS = 5.0
BUDGET_SAVE_DICT = 5.0
BUDGET_SAVE_PLUS_LOAD = 15.0
BUDGET_SUMMARY = 5.0

# Non-ASCII test data built via chr() so this source file stays pure
# ASCII while the JSON round trip still exercises ensure_ascii=False.
KATAKANA = chr(0x30C6) + chr(0x30B9) + chr(0x30C8)  # "tesuto"
E_ACUTE = chr(0x00E9)
STAR = chr(0x2605)


def _build_project(models, n: int):
    """Construct a Project with n assets of realistic variety: tags
    (incl. an aliased tag), crops with rotation, censors with
    per-platform lists, overlays, assignments with nested crops and
    posted statuses, specs dicts, star ratings, non-ASCII notes."""
    tag_pools = [
        ["furry", "marty"],
        ["futa", "color"],
        ["sailor_moon"],
        ["furry", "sailor_moon", "color"],
    ]
    platforms_cycle = ["kickstarter", "patreon", "twitter"]
    censor_styles = ["black", "blur", "pixelate"]

    assets = []
    for i in range(n):
        tags = list(tag_pools[i % len(tag_pools)])
        if i % 13 == 0:
            tags.append("old_futa")  # resolved to "futa" by tag_aliases
        a = models.Asset(
            id=f"file{i:05d}_{i % 7}",
            source_path=f"E:/fake/art/batch{i % 40:02d}/file{i:05d}.png",
            source_folder=f"E:/fake/art/batch{i % 40:02d}",
            starred=i % 6,
            tags=tags,
        )
        if i % 3 == 0:
            a.specs = {"cli_info": f"{800 + i % 400}x{600 + i % 300}",
                       "seed": i}
        if i % 5 == 0:
            a.crops.append(models.CropRegion(
                x=i % 100, y=10, w=800, h=600, label="cover",
                platform_id="kickstarter", slot_name="main",
                rotation=1.5))
        if i % 7 == 0:
            a.censors.append(models.CensorRegion(
                x=5, y=5, w=64, h=64,
                style=censor_styles[i % len(censor_styles)],
                blur_radius=25, pixelate_ratio=8, rotation=0.5,
                platforms=["twitter", "kickstarter_jp"]))
        if i % 11 == 0:
            a.assignments.append(models.PlatformAssignment(
                platform=platforms_cycle[i % len(platforms_cycle)],
                slot="main",
                status=(models.PostStatus.POSTED if i % 22 == 0
                        else models.PostStatus.PENDING),
                crop=models.CropRegion(x=1, y=2, w=640, h=480),
                campaign_id="camp_1"))
        if i % 17 == 0:
            a.overlays.append(models.CanvasOverlay(
                type="text", text=f"wm {i}", font_size=18,
                position="bottom-right", opacity=0.8))
        if i % 19 == 0:
            a.notes = f"memo {E_ACUTE}{KATAKANA} {i}"
        assets.append(a)

    proj = models.Project(name=f"PerfBudget {STAR} 10k", assets=assets)
    proj.tag_definitions = {
        "furry": {"label": "Furry", "color": "#aa5522"},
        "marty": {"label": "Marty", "color": "#2255aa",
                  "parent_id": "furry"},
        "futa": {"label": "Futa", "color": "#aa22aa"},
        "color": {"label": "Color", "color": "#22aa55"},
        "sailor_moon": {"label": "Sailor Moon", "color": "#5522aa"},
    }
    proj.tag_aliases = {"old_futa": "futa"}
    return proj


class TestPerfBudget(unittest.TestCase):
    """10k-asset budgets. Named so `-k "not PerfBudget"` skips it."""

    def test_10k_pipeline_budgets(self):
        import doxyedit.models as models

        # --- Phase 1: in-memory construction (10k Asset objects) ---
        t0 = time.perf_counter()
        proj = _build_project(models, N_ASSETS)
        t_build = time.perf_counter() - t0
        self.assertEqual(len(proj.assets), N_ASSETS)
        self.assertLess(
            t_build, BUDGET_BUILD_OBJECTS,
            f"[perf-budget] building {N_ASSETS} assets in memory took "
            f"{t_build:.3f}s (budget {BUDGET_BUILD_OBJECTS}s)")

        with tempfile.TemporaryDirectory() as td:
            # No config.yaml in td, so Project.load skips the custom
            # platform merge - the fixture dir stays hermetic.
            path = str(Path(td) / "perf_budget.doxyproj.json")

            # --- Phase 2: build_save_dict (pure dict construction) ---
            t0 = time.perf_counter()
            data = proj.build_save_dict(path)
            t_save_dict = time.perf_counter() - t0
            self.assertEqual(len(data["assets"]), N_ASSETS)
            self.assertLess(
                t_save_dict, BUDGET_SAVE_DICT,
                f"[perf-budget] build_save_dict took {t_save_dict:.3f}s "
                f"(budget {BUDGET_SAVE_DICT}s)")

            # --- Phase 3: full save (migrate + dict + json + write) ---
            t0 = time.perf_counter()
            proj.save(path)
            t_save = time.perf_counter() - t0
            self.assertTrue(Path(path).exists())
            self.assertGreater(Path(path).stat().st_size, 1_000_000,
                               "10k-asset file should be >1MB")

            # --- Phase 4: load from disk (the real load path) ---
            # Patch shared identities so a dev machine's
            # ~/.doxyedit/identities.json can't leak into the load.
            t0 = time.perf_counter()
            with mock.patch("doxyedit.shared_identities.load_shared",
                            return_value={}):
                proj2 = models.Project.load(path)
            t_load = time.perf_counter() - t0

            self.assertLess(
                t_save + t_load, BUDGET_SAVE_PLUS_LOAD,
                f"[perf-budget] save {t_save:.3f}s + load {t_load:.3f}s "
                f"= {t_save + t_load:.3f}s "
                f"(combined budget {BUDGET_SAVE_PLUS_LOAD}s)")

            # Light correctness checks so the budgets guard the REAL
            # path, not a short-circuited one.
            self.assertEqual(len(proj2.assets), N_ASSETS)
            self.assertEqual(proj2.assets[0].id, proj.assets[0].id)
            self.assertEqual(proj2.assets[-1].id, proj.assets[-1].id)
            # Alias resolution ran: old_futa -> futa, no dupes.
            aliased = proj2.assets[13]  # i=13 has old_futa
            self.assertIn("futa", aliased.tags)
            self.assertNotIn("old_futa", aliased.tags)
            # Non-ASCII survived the round trip (ensure_ascii=False).
            self.assertIn(KATAKANA, proj2.assets[19].notes)

            # --- Phase 5: summary() on the loaded project ---
            t0 = time.perf_counter()
            s = proj2.summary()
            t_summary = time.perf_counter() - t0
            self.assertEqual(s["total_assets"], N_ASSETS)
            self.assertGreater(s["starred"], 0)
            self.assertGreater(s["needs_censor"], 0)
            self.assertGreater(s["platforms"]["kickstarter"]["assigned"], 0)
            self.assertGreater(s["platforms"]["kickstarter"]["posted"], 0)
            self.assertLess(
                t_summary, BUDGET_SUMMARY,
                f"[perf-budget] summary() took {t_summary:.3f}s "
                f"(budget {BUDGET_SUMMARY}s)")

        # Trend line for CI logs (visible with -s / on failure).
        print(
            f"[perf-budget] n={N_ASSETS} build={t_build:.3f}s "
            f"save_dict={t_save_dict:.3f}s save={t_save:.3f}s "
            f"load={t_load:.3f}s summary={t_summary:.3f}s")


if __name__ == "__main__":
    unittest.main()
