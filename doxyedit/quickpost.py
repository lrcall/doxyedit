"""quickpost.py — Semi-automated posting to subscription platforms.

Copies caption to clipboard, exports image with overlays/censors,
opens the platform's post creation page in the browser.
"""
from __future__ import annotations
import webbrowser
import tempfile
from pathlib import Path
from dataclasses import dataclass

from doxyedit.models import (
    Project, SocialPost, Asset, SUB_PLATFORMS, SubPlatform,
    CollectionIdentity,
)


@dataclass
class QuickPostResult:
    success: bool = False
    caption: str = ""
    exported_path: str = ""
    url_opened: str = ""
    error: str = ""


def quick_post(
    project: Project,
    post: SocialPost,
    platform_id: str,
    tier: str = "",
) -> QuickPostResult:
    """Execute a quick-post action for a subscription platform.

    1. Look up platform config
    2. Get identity URL for this platform
    3. Select caption (per-platform or default, locale-aware)
    4. Select assets (tier-based or default)
    5. Export image with censors + overlays
    6. Copy caption to clipboard
    7. Open platform post URL in browser
    """
    sub = SUB_PLATFORMS.get(platform_id)
    if not sub:
        return QuickPostResult(error=f"Unknown platform: {platform_id}")

    identity = project.get_identity()

    # Get base URL from identity
    base_url = getattr(identity, sub.url_field, "") if identity else ""
    if not base_url and sub.post_url_template.startswith("{base_url}"):
        return QuickPostResult(error=f"No {sub.name} URL configured in identity")

    # Build post URL
    if "{base_url}" in sub.post_url_template:
        post_url = sub.post_url_template.replace("{base_url}", base_url.rstrip("/"))
    else:
        post_url = sub.post_url_template

    # Select caption (locale-aware)
    caption = post.captions.get(platform_id, "")
    if not caption:
        caption = post.caption_default

    # Select assets (tier-based)
    asset_ids = post.asset_ids
    if tier and post.tier_assets.get(tier):
        asset_ids = post.tier_assets[tier]

    # Export first asset with censors + overlays
    exported_path = ""
    if asset_ids:
        asset = project.get_asset(asset_ids[0])
        if asset and asset.source_path:
            exported_path = _export_for_platform(asset, sub, project)

    # Copy caption to clipboard
    try:
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(caption)
    except Exception:
        pass

    # Open browser
    if post_url:
        webbrowser.open(post_url)

    return QuickPostResult(
        success=True,
        caption=caption,
        exported_path=exported_path,
        url_opened=post_url,
    )


def _export_for_platform(asset: Asset, sub: SubPlatform, project: Project) -> str:
    """Export an asset with appropriate censors/overlays for a platform."""
    try:
        from PIL import Image
        from doxyedit.exporter import apply_censors, apply_overlays

        src = Path(asset.source_path)
        if not src.exists():
            return ""

        ext = src.suffix.lower()
        if ext in (".psd", ".psb"):
            from doxyedit.imaging import load_psd
            img, _, _ = load_psd(str(src))
        else:
            img = Image.open(str(src)).convert("RGBA")

        # Apply censors if platform needs them (Japanese platforms)
        if sub.needs_censor and asset.censors:
            img = apply_censors(img, asset.censors)

        # Apply overlays (watermarks etc.)
        if asset.overlays:
            project_dir = str(Path(asset.source_path).parent)
            img = apply_overlays(img, asset.overlays, project_dir)

        # Save to temp
        tmp = Path(tempfile.gettempdir()) / f"doxyedit_qp_{sub.id}_{asset.id}.png"
        img.save(str(tmp), "PNG")
        return str(tmp)
    except Exception:
        return ""


def get_available_platforms(identity: CollectionIdentity | None) -> list[SubPlatform]:
    """Return subscription platforms that have URLs configured."""
    if not identity:
        return []
    result = []
    for sub in SUB_PLATFORMS.values():
        url = getattr(identity, sub.url_field, "")
        if url:
            result.append(sub)
    return result
