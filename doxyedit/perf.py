"""Lightweight perf telemetry. Logs slow operations to ~/.doxyedit/perf.log
so we can see what's actually hot on big projects without running a profiler.

Usage:
    from doxyedit.perf import perf_time

    @perf_time("refresh_grid")
    def _refresh_grid(self):
        ...

Only logs when an op exceeds the threshold (default 100ms). No-op cheap;
zero allocation on the fast path.
"""
from __future__ import annotations

import time
import functools
from pathlib import Path

_LOG_PATH = Path.home() / ".doxyedit" / "perf.log"
_THRESHOLD_MS = 100.0
_handle = None


def _ensure_handle():
    global _handle
    if _handle is None:
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _handle = open(str(_LOG_PATH), "a", buffering=1, encoding="utf-8")
            _handle.write(f"\n=== perf log opened {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception:
            _handle = False  # disabled
    return _handle


def perf_time(label: str, threshold_ms: float = _THRESHOLD_MS):
    """Decorator: log call duration to perf.log when it exceeds threshold_ms."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                dt = (time.perf_counter() - t0) * 1000.0
                if dt >= threshold_ms:
                    h = _ensure_handle()
                    if h:
                        h.write(f"{time.strftime('%H:%M:%S')} {label:<30s} {dt:7.0f} ms\n")
        return wrapper
    return deco


def perf_block(label: str, dt_ms: float, threshold_ms: float = _THRESHOLD_MS):
    """Manual variant for `with`-style timing where decoration is awkward."""
    if dt_ms < threshold_ms:
        return
    h = _ensure_handle()
    if h:
        h.write(f"{time.strftime('%H:%M:%S')} {label:<30s} {dt_ms:7.0f} ms\n")
