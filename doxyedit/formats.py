"""File format constants and path helpers for DoxyEdit projects and collections.

Projects save as `.doxy`; collections save as `.doxycol`. Legacy JSON
extensions (`.doxyproj.json`, `.doxycoll.json`) still load but are never
written by new code. Content is identical in either extension.
"""

PROJECT_EXTS = (".doxy", ".doxyproj.json")
COLLECTION_EXTS = (".doxycol", ".doxycoll", ".doxycoll.json")

PROJECT_DEFAULT_EXT = ".doxy"
COLLECTION_DEFAULT_EXT = ".doxycol"


def is_project_path(path: str) -> bool:
    p = path.lower()
    return any(p.endswith(ext) for ext in PROJECT_EXTS)


def is_collection_path(path: str) -> bool:
    p = path.lower()
    return any(p.endswith(ext) for ext in COLLECTION_EXTS)


def ensure_project_ext(path: str, prefer_legacy: bool = False) -> str:
    """Append an extension to `path` if none of the known project extensions match."""
    if is_project_path(path):
        return path
    return path + (".doxyproj.json" if prefer_legacy else PROJECT_DEFAULT_EXT)


def ensure_collection_ext(path: str, prefer_legacy: bool = False) -> str:
    """Append an extension to `path` if none of the known collection extensions match."""
    if is_collection_path(path):
        return path
    return path + (".doxycoll.json" if prefer_legacy else COLLECTION_DEFAULT_EXT)
