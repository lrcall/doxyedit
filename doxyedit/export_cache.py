"""Per-batch cache for the export pipeline.

Avoids redundant PSD decode + censor/overlay composition when the same asset
is exported to multiple platforms in one batch (quick-post, auto-post,
OneUp sync re-export). Scope is a single batch operation. Discard after.

Typical savings on a 5-platform post with a 100MB PSD:
- Without cache: 5 x load_image_for_export + 5 x apply_censors + 5 x apply_overlays
- With cache: 1 x load_image_for_export + up to 2 x (censors, overlays)
"""
from __future__ import annotations

from typing import Optional

from PIL import Image

from doxyedit.imaging import load_image_for_export
from doxyedit.exporter import apply_censors, apply_overlays
from doxyedit.models import Asset


class ExportCache:
    """Cache loaded source images and their censor/overlay variants."""

    def __init__(self) -> None:
        self._raw: dict[str, Image.Image] = {}        # source_path -> raw PIL
        self._processed: dict[tuple, Image.Image] = {}  # (asset_id, censored, with_overlays) -> PIL

    def load_raw(self, source_path: str) -> Optional[Image.Image]:
        """Load + decode the image once per batch. Subsequent calls return the cached PIL."""
        cached = self._raw.get(source_path)
        if cached is not None:
            return cached
        try:
            img = load_image_for_export(source_path)
        except Exception:
            return None
        self._raw[source_path] = img
        return img

    def get_processed(self, asset: Asset, *, censored: bool, with_overlays: bool,
                      project_dir: str) -> Optional[Image.Image]:
        """Return a PIL image with the requested variant applied.

        Cache hit: same (asset.id, censored, with_overlays) triple returns the
        cached processed image. Caller must not mutate the returned image.
        """
        key = (asset.id, bool(censored), bool(with_overlays))
        cached = self._processed.get(key)
        if cached is not None:
            return cached

        raw = self.load_raw(asset.source_path)
        if raw is None:
            return None

        img = raw.copy()  # raw stays pristine for other variants
        if censored and asset.censors:
            img = apply_censors(img, asset.censors)
        if with_overlays and asset.overlays:
            img = apply_overlays(img, asset.overlays, project_dir)
        self._processed[key] = img
        return img

    def clear(self) -> None:
        self._raw.clear()
        self._processed.clear()
