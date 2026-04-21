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


def _export_for_platform(asset: Asset, sub: SubPlatform, project: Project,
                         cache=None) -> str:
    """Export an asset with appropriate censors/overlays for a platform.

    If `cache` (ExportCache) is provided, the source PSD decode and the
    censor/overlay composition are reused across repeated calls for the
    same asset in one batch.
    """
    try:
        src = Path(asset.source_path)
        if not src.exists():
            return ""

        censored = sub.needs_censor and bool(asset.censors)
        with_overlays = bool(asset.overlays)
        project_dir = str(Path(asset.source_path).parent)

        if cache is not None:
            img = cache.get_processed(
                asset, censored=censored, with_overlays=with_overlays,
                project_dir=project_dir,
            )
            if img is None:
                return ""
        else:
            from doxyedit.imaging import load_image_for_export
            from doxyedit.exporter import apply_censors, apply_overlays
            img = load_image_for_export(str(src))
            if censored:
                img = apply_censors(img, asset.censors)
            if with_overlays:
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


def get_pending_sub_platforms(post: SocialPost) -> list[str]:
    """Return subscription platform IDs from the post that haven't been posted yet."""
    return [
        pid for pid in post.platforms
        if pid in SUB_PLATFORMS
        and post.sub_platform_status.get(pid, {}).get("status") != "posted"
    ]


def batch_quick_post(project: Project, post: SocialPost, pending: list[str]):
    """Yield one QuickPostResult per platform, opening each in browser sequence.

    Caller should wait for user confirmation between each (they need to
    manually paste + upload in the browser).
    """
    for plat_id in pending:
        result = quick_post(project, post, plat_id)
        yield plat_id, result


def post_everywhere(project, post, project_dir=".", auto_submit=False):
    """Post to all checked subscription/direct platforms using best available method.

    Fallback chain per platform:
      1. Direct API (Telegram, Discord, Bluesky)
      2. Browser automation (Playwright + CDP)
      3. Quick-post (clipboard + browser open)

    OneUp platforms are handled separately by _push_post_to_oneup.
    Returns dict[platform_id, QuickPostResult] with status per platform.
    """
    from doxyedit.models import SUB_PLATFORMS, DIRECT_POST_PLATFORMS
    from doxyedit.export_cache import ExportCache
    results = {}
    export_cache = ExportCache()  # one decode, many variants, thrown away at function exit

    # Direct API platforms
    try:
        from doxyedit.directpost import push_to_direct
        direct_results = push_to_direct(post, project, project_dir, cache=export_cache)
        for r in direct_results:
            results[r.platform] = QuickPostResult(
                success=r.success, caption="", exported_path="",
                url_opened="", error=r.error,
            )
    except Exception as e:
        print(f"[PostEverywhere] Direct-post error: {e}")

    # Subscription platforms — try browser automation, fall back to quick-post
    chrome_available = False
    try:
        from doxyedit.browserpost import is_chrome_running, post_to_platform_sync
        chrome_available = is_chrome_running()
    except Exception:
        pass

    for plat_id in post.platforms:
        if plat_id not in SUB_PLATFORMS:
            continue
        if post.sub_platform_status.get(plat_id, {}).get("status") == "posted":
            continue

        browser_ok = False
        try:
            if chrome_available:
                sub = SUB_PLATFORMS[plat_id]
                identity = project.get_identity()
                base_url = getattr(identity, sub.url_field, "") if identity else ""
                caption = post.captions.get(plat_id, post.caption_default)

                # Export image
                image_path = ""
                if post.asset_ids:
                    asset = project.get_asset(post.asset_ids[0])
                    if asset:
                        image_path = _export_for_platform(asset, sub, project,
                                                         cache=export_cache)

                br = post_to_platform_sync(
                    plat_id, caption, image_path,
                    base_url=base_url, project_dir=project_dir,
                    auto_submit=auto_submit,
                )
                if br.success:
                    browser_ok = True
                    results[plat_id] = QuickPostResult(
                        success=True, caption=caption,
                        exported_path=image_path, url_opened=br.url,
                    )
                    print(f"[PostEverywhere] {plat_id}: browser automation OK")
        except Exception as e:
            print(f"[PostEverywhere] {plat_id}: browser failed ({e}), falling back to quick-post")

        # Fallback to quick-post
        if not browser_ok:
            result = quick_post(project, post, plat_id)
            results[plat_id] = result
            print(f"[PostEverywhere] {plat_id}: quick-post {'OK' if result.success else 'FAIL'}")

    return results
