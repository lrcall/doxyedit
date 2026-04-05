"""Global app configuration — lives as doxyedit.config.json next to the executable.

Stores settings that are shared across all projects and all viewers:
  - Default tag presets (labels, colors, dimensions)
  - Default keyboard shortcuts
  - Platform definitions

The file is only written when the user explicitly changes one of these values.
If the file doesn't exist the hardcoded defaults in models.py are used as-is.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doxyedit.models import TagPreset, Platform


def _config_path() -> Path:
    """Return the path for doxyedit.config.json, next to the executable in builds
    or next to the repo root in development."""
    if getattr(sys, 'frozen', False):
        # Nuitka / PyInstaller — next to the .exe
        return Path(sys.executable).parent / "doxyedit.config.json"
    # Dev — repo root (one level above doxyedit/ package)
    return Path(__file__).parent.parent / "doxyedit.config.json"


CONFIG_PATH = _config_path()


class AppConfig:
    """Mutable global config. Call save() after any change."""

    def __init__(self):
        # These are populated by load() from JSON or left as None to signal
        # "use hardcoded model defaults".
        self._tag_presets: dict | None = None   # id → dict (label/color/width/height/ratio)
        self._tag_sized: dict | None = None
        self._tag_shortcuts: dict | None = None  # key → tag_id
        self._platforms: dict | None = None      # id → dict

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def load(self) -> "AppConfig":
        if not CONFIG_PATH.exists():
            return self
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return self
        if "tag_presets" in raw:
            self._tag_presets = raw["tag_presets"]
        if "tag_sized" in raw:
            self._tag_sized = raw["tag_sized"]
        if "tag_shortcuts" in raw:
            self._tag_shortcuts = raw["tag_shortcuts"]
        if "platforms" in raw:
            self._platforms = raw["platforms"]
        return self

    def save(self):
        """Write current overrides to disk. Creates the file on first call."""
        from doxyedit.models import TAG_PRESETS, TAG_SIZED, TAG_SHORTCUTS_DEFAULT, PLATFORMS

        def _platform_dict(pl) -> dict:
            return {
                "name": pl.name,
                "export_prefix": pl.export_prefix,
                "needs_censor": pl.needs_censor,
                "slots": [
                    {
                        "name": s.name, "label": s.label,
                        "width": s.width, "height": s.height,
                        "required": s.required, "description": s.description,
                    }
                    for s in pl.slots
                ],
            }

        # Use stored overrides or fall back to current live dicts
        presets = self._tag_presets or {tid: self._preset_to_dict(p) for tid, p in TAG_PRESETS.items()}
        sized   = self._tag_sized   or {tid: self._preset_to_dict(p) for tid, p in TAG_SIZED.items()}
        shorts  = self._tag_shortcuts or dict(TAG_SHORTCUTS_DEFAULT)
        plats   = self._platforms or {pid: _platform_dict(pl) for pid, pl in PLATFORMS.items()}

        data = {
            "_comment": "DoxyEdit global config — shared across all projects. Edit with Claude CLI or by hand.",
            "tag_presets": presets,
            "tag_sized": sized,
            "tag_shortcuts": shorts,
            "platforms": plats,
        }
        CONFIG_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # Accessors — return live merged dicts (config overrides > hardcoded)
    # ------------------------------------------------------------------

    def get_tag_presets(self) -> dict:
        """Return {id: TagPreset} for non-sized tags, merging config over defaults."""
        from doxyedit.models import TAG_PRESETS, TagPreset
        if self._tag_presets is None:
            return dict(TAG_PRESETS)
        result = dict(TAG_PRESETS)
        for tid, d in self._tag_presets.items():
            result[tid] = TagPreset.from_dict(tid, d)
        return result

    def get_tag_sized(self) -> dict:
        """Return {id: TagPreset} for sized tags, merging config over defaults."""
        from doxyedit.models import TAG_SIZED, TagPreset
        if self._tag_sized is None:
            return dict(TAG_SIZED)
        result = dict(TAG_SIZED)
        for tid, d in self._tag_sized.items():
            result[tid] = TagPreset.from_dict(tid, d)
        return result

    def get_tag_all(self) -> dict:
        return {**self.get_tag_presets(), **self.get_tag_sized()}

    def get_tag_shortcuts(self) -> dict:
        """Return {key: tag_id} default shortcuts."""
        from doxyedit.models import TAG_SHORTCUTS_DEFAULT
        if self._tag_shortcuts is None:
            return dict(TAG_SHORTCUTS_DEFAULT)
        return dict(self._tag_shortcuts)

    def get_platforms(self) -> dict:
        """Return {id: Platform}, merging config over defaults."""
        from doxyedit.models import PLATFORMS, Platform, PlatformSlot
        if self._platforms is None:
            return dict(PLATFORMS)
        result = dict(PLATFORMS)
        for pid, d in self._platforms.items():
            slots = [
                PlatformSlot(
                    name=s.get("name", ""), label=s.get("label", ""),
                    width=s.get("width", 0), height=s.get("height", 0),
                    required=s.get("required", True),
                    description=s.get("description", ""),
                )
                for s in d.get("slots", [])
            ]
            result[pid] = Platform(
                id=pid,
                name=d.get("name", pid),
                export_prefix=d.get("export_prefix", ""),
                needs_censor=d.get("needs_censor", False),
                slots=slots,
            )
        return result

    # ------------------------------------------------------------------
    # Mutation helpers — call these from UI handlers, then call save()
    # ------------------------------------------------------------------

    def _preset_to_dict(self, p) -> dict:
        d: dict = {"label": p.label, "color": p.color}
        if p.width is not None:
            d["width"] = p.width
        if p.height is not None:
            d["height"] = p.height
        if p.ratio:
            d["ratio"] = p.ratio
        return d

    def set_tag_preset(self, tag_id: str, label: str = None, color: str = None,
                       width: int = None, height: int = None, ratio: str = None):
        """Override a tag preset field. Only non-None values are written."""
        from doxyedit.models import TAG_PRESETS, TAG_SIZED
        in_sized = tag_id in TAG_SIZED
        # Lazy-initialise the right dict from current defaults
        if in_sized:
            if self._tag_sized is None:
                self._tag_sized = {tid: self._preset_to_dict(p) for tid, p in TAG_SIZED.items()}
            target = self._tag_sized
        else:
            if self._tag_presets is None:
                self._tag_presets = {tid: self._preset_to_dict(p) for tid, p in TAG_PRESETS.items()}
            target = self._tag_presets
        if tag_id not in target:
            target[tag_id] = {}
        entry = target[tag_id]
        if label is not None:
            entry["label"] = label
        if color is not None:
            entry["color"] = color
        if width is not None:
            entry["width"] = width
        if height is not None:
            entry["height"] = height
        if ratio is not None:
            entry["ratio"] = ratio

    def set_shortcut(self, key: str, tag_id: str | None):
        """Set or clear a default shortcut. tag_id=None clears the key."""
        from doxyedit.models import TAG_SHORTCUTS_DEFAULT
        if self._tag_shortcuts is None:
            self._tag_shortcuts = dict(TAG_SHORTCUTS_DEFAULT)
        # Remove any existing binding for this tag
        if tag_id:
            self._tag_shortcuts = {k: v for k, v in self._tag_shortcuts.items() if v != tag_id}
        if key and tag_id:
            self._tag_shortcuts[key] = tag_id
        elif key:
            self._tag_shortcuts.pop(key, None)


# Singleton loaded at import time
_app_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _app_config
    if _app_config is None:
        _app_config = AppConfig().load()
    return _app_config
