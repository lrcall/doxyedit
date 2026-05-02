"""Scriptable plugin hooks.

A minimal plugin system that lets users drop Python files into
`~/.doxyedit/plugins/` and subscribe to app lifecycle events (post
pushed, asset imported, project loaded, etc.) without modifying
DoxyEdit's source.

Why a custom plugin loader instead of entry-points / pip / etc.:
DoxyEdit ships as a Nuitka-built exe for end users; pip is not in the
loop. A drop-folder + importlib approach lets users iterate scripts
without rebuilding anything.

## Plugin shape

A plugin is a `.py` file under `~/.doxyedit/plugins/`. On load, the
module gets imported and its top-level `register(api)` callable is
invoked exactly once. The api object exposes:

    api.on(event_name: str, handler: Callable)
    api.log(msg: str)         # writes to ~/.doxyedit/plugins.log

The handler signature matches the event:

    "post_pushed"     handler(post, platform, ok: bool, detail: str)
    "asset_imported"  handler(asset)
    "project_loaded"  handler(project, project_path: str)
    "tag_changed"     handler(tag_id: str, before: dict, after: dict)
    "shutdown"        handler()

## Failure isolation

A plugin that raises during import or during a hook call is logged
and disabled for the rest of the session. The host app never crashes
because of a plugin error.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import traceback
from pathlib import Path
from typing import Any, Callable


_LOG = logging.getLogger(__name__)


def plugins_dir() -> Path:
    """User plugin folder under ~/.doxyedit/plugins/."""
    return Path.home() / ".doxyedit" / "plugins"


def plugins_log_path() -> Path:
    return Path.home() / ".doxyedit" / "plugins.log"


class _PluginAPI:
    """Per-plugin sandbox handle. Each plugin file gets its own
    instance so a faulting plugin only loses its own handlers."""

    def __init__(self, registry: "_PluginRegistry", plugin_name: str):
        self._reg = registry
        self._name = plugin_name

    def on(self, event_name: str, handler: Callable) -> None:
        self._reg._add(event_name, handler, source=self._name)

    def log(self, msg: str) -> None:
        try:
            with plugins_log_path().open("a", encoding="utf-8") as f:
                from datetime import datetime
                f.write(
                    f"[{datetime.now().isoformat(timespec='seconds')}] "
                    f"{self._name}: {msg}\n")
        except OSError:
            pass


class _PluginRegistry:
    """Process-wide registry of (event_name -> [handler...])."""

    def __init__(self):
        self._hooks: dict[str, list[tuple[Callable, str]]] = {}
        self._loaded: set[str] = set()
        self._failed: set[str] = set()

    def _add(self, event_name: str, handler: Callable, *, source: str):
        self._hooks.setdefault(event_name, []).append((handler, source))

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """Call every registered handler for event_name. A handler that
        raises is logged and disabled for the remainder of the session."""
        for handler, source in list(self._hooks.get(event_name, [])):
            if source in self._failed:
                continue
            try:
                handler(*args, **kwargs)
            except Exception:
                self._failed.add(source)
                tb = traceback.format_exc()
                _LOG.error("Plugin %s failed on %s: %s",
                           source, event_name, tb)
                try:
                    with plugins_log_path().open("a", encoding="utf-8") as f:
                        f.write(
                            f"\n[FAILED] {source} on {event_name}\n{tb}\n")
                except OSError:
                    pass

    def discover_and_load(self) -> list[str]:
        """Scan ~/.doxyedit/plugins/ for .py files and load each.
        Returns the list of successfully-loaded plugin names. Failures
        are logged to plugins.log but never raise."""
        d = plugins_dir()
        if not d.exists():
            return []
        loaded: list[str] = []
        for path in sorted(d.glob("*.py")):
            if path.name.startswith("_") or path.name.startswith("."):
                continue
            name = path.stem
            if name in self._loaded:
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"doxyedit_plugin_{name}", path)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                register = getattr(module, "register", None)
                if not callable(register):
                    continue
                api = _PluginAPI(self, name)
                register(api)
                self._loaded.add(name)
                loaded.append(name)
            except Exception:
                self._failed.add(name)
                tb = traceback.format_exc()
                _LOG.error("Plugin %s failed to load: %s", name, tb)
                try:
                    with plugins_log_path().open("a", encoding="utf-8") as f:
                        from datetime import datetime
                        f.write(
                            f"\n[{datetime.now().isoformat(timespec='seconds')}] "
                            f"[LOAD FAILED] {name}\n{tb}\n")
                except OSError:
                    pass
        return loaded

    def loaded_plugins(self) -> list[str]:
        return sorted(self._loaded)

    def failed_plugins(self) -> list[str]:
        return sorted(self._failed)


# Single process-wide registry. The host app calls discover_and_load()
# once at startup and emit() at lifecycle points.
_REGISTRY = _PluginRegistry()


def discover_and_load() -> list[str]:
    return _REGISTRY.discover_and_load()


def emit(event_name: str, *args: Any, **kwargs: Any) -> None:
    _REGISTRY.emit(event_name, *args, **kwargs)


def loaded() -> list[str]:
    return _REGISTRY.loaded_plugins()


def failed() -> list[str]:
    return _REGISTRY.failed_plugins()
