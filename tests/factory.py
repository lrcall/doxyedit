"""Shared test factory - builds small but realistically populated
Project objects backed by real tiny PNG files written with Pillow.

Pure helper module: no TestCase, no QApplication, no Qt import.
Usable from any test after the standard REPO_ROOT header:

    from tests.factory import make_project, make_saved_project

make_project() returns a Project whose assets point at real PNGs
under <tmp_path>/assets/, with tags, crops, censors, assignments,
specs, notes, star ratings, tag_definitions + custom_tags kept in
sync, and (optionally) a draft post.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# Tag ids and labels used by every factory project. Kept in sync
# between tag_definitions (dict) and custom_tags (list) per the
# project file rules.
_FACTORY_TAGS = {
    "factory": {"label": "Factory", "color": "#4488cc"},
    "subject_a": {"label": "Subject A", "color": "#cc8844"},
    "subject_b": {"label": "Subject B", "color": "#44cc88"},
    "starred_pick": {"label": "Starred Pick", "color": "#cccc44"},
}


def _write_png(path: Path, index: int, size: tuple[int, int]) -> None:
    """Write a tiny real PNG. Color varies by index so files differ."""
    color = ((index * 40) % 256, 100, (index * 90 + 30) % 256)
    Image.new("RGB", size, color).save(str(path), "PNG")


def make_project(tmp_path: Path, n_assets: int = 3, *,
                 name: str = "Factory Project",
                 with_posts: bool = True,
                 png_size: tuple[int, int] = (8, 8)):
    """Build a populated Project with n_assets real PNG assets.

    - PNGs land in <tmp_path>/assets/art_NNN.png
    - Asset ids follow the "{base}_{index}" contract: art_NNN_0
    - Asset 0 gets a censor + a platform assignment (with crop)
    - Even-indexed assets get a crop region
    - tag_definitions and custom_tags stay in sync
    - One draft SocialPost referencing asset 0 (with_posts=True)

    Returns the Project (not yet saved to disk).
    """
    from doxyedit.models import (
        Asset, CensorRegion, CropRegion, PlatformAssignment, Project,
        SocialPost,
    )

    tmp_path = Path(tmp_path)
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)

    proj = Project()
    proj.name = name
    proj.notes = "Built by tests/factory.py"
    proj.tag_definitions = {tid: dict(d) for tid, d in _FACTORY_TAGS.items()}
    proj.custom_tags = [
        {"id": tid, "label": d["label"], "color": d["color"]}
        for tid, d in _FACTORY_TAGS.items()
    ]

    for i in range(n_assets):
        stem = f"art_{i:03d}"
        png = asset_dir / f"{stem}.png"
        _write_png(png, i, png_size)

        tags = ["factory", "subject_a" if i % 2 == 0 else "subject_b"]
        starred = i % 6
        if starred:
            tags.append("starred_pick")

        asset = Asset(
            id=f"{stem}_0",
            source_path=str(png),
            source_folder=str(asset_dir),
            starred=starred,
            tags=tags,
            notes=f"factory asset {i}",
            specs={"origin": "tests/factory.py", "index": i},
        )
        if i % 2 == 0:
            asset.crops.append(CropRegion(
                x=1, y=1, w=4, h=4, label="thumb",
                platform_id="twitter", slot_name="header", rotation=0.0))
        if i == 0:
            asset.censors.append(CensorRegion(
                x=2, y=2, w=3, h=3, style="blur", blur_radius=8,
                platforms=["twitter"]))
            asset.assignments.append(PlatformAssignment(
                platform="twitter", slot="header", status="pending",
                crop=CropRegion(x=0, y=0, w=6, h=3, label="assign"),
                notes="factory assignment"))
        proj.assets.append(asset)

    if with_posts and proj.assets:
        proj.posts.append(SocialPost(
            id="factory_post_1",
            asset_ids=[proj.assets[0].id],
            platforms=["twitter"],
            caption_default="Factory caption",
            scheduled_time="2026-07-01T10:00:00",
            status="draft",
            created_at="2026-07-01T00:00:00",
            updated_at="2026-07-01T00:00:00",
        ))

    return proj


def make_saved_project(tmp_path: Path, n_assets: int = 3, *,
                       filename: str = "factory.doxy", **kwargs):
    """make_project() + save. Returns (project, project_file_path)."""
    proj = make_project(tmp_path, n_assets, **kwargs)
    path = Path(tmp_path) / filename
    proj.save(str(path))
    return proj, path
