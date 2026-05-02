# Contributing to DoxyEdit

Quick guide for working on the codebase. The project is solo-maintained
but the docs / tests / validators in this guide make it easy for any
agent or future contributor to land changes without breaking things.

## Setup

Windows is the primary platform. The codebase also imports cleanly on
other platforms but the bridge / launcher path is Windows-tested only.

```
git clone https://github.com/lrcall/doxyedit
cd doxyedit
pip install -r requirements.txt
py run.py        # console launch (recommended for development - shows tracebacks)
```

`pythonw run.py` (or `doxyedit.bat` / `doxyedit.vbs`) launches windowless
and redirects stdout+stderr to `~/.doxyedit/last_run.log`. Use the
console launch while developing so you see tracebacks immediately.

## Running tests

```
py -m unittest discover -s tests -v
```

The CI workflow at `.github/workflows/checks.yml` runs the same command
on every push and PR (Windows runner, Python 3.11, headless via
`QT_QPA_PLATFORM=offscreen`). Locally the suite finishes in ~7 seconds.

There are also two validators that run alongside the test suite:

```
py scripts/tokenize_validate.py     # must report ALL CLEAN
py scripts/check_theme_contrast.py  # all 21 themes must pass WCAG
```

## Coding rules

The most important rules live in [`CLAUDE.md`](CLAUDE.md). Highlights:

- **Never hardcode colors / fonts / sizes via `setStyleSheet()`.** All
  visual properties come from theme tokens in `doxyedit/themes.py`. Use
  the helpers `themes.themed_dialog_size()`,
  `themes.is_dark_color()`, `themes.fg_on_color()`,
  `themes.apply_menu_theme()` for new chrome.
- **Punctuation:** no em-dashes (`—`), no en-dashes (`–`), no smart
  quotes. Use a regular hyphen `-` or restructure the sentence.
- **Project file format:** always `ensure_ascii=False` when writing
  JSON; never sort or reorder assets (order is meaningful).
- **New SocialPost / Asset / Project fields:** must be added with a
  default and round-trip via `to_dict` / `from_dict` using `.get()`
  so legacy project files still load. Add a regression test in
  `tests/test_models.py`.
- **Subprocess on Windows:** always
  `creationflags=0x08000000` (CREATE_NO_WINDOW) +
  `encoding="utf-8", errors="replace"`.
- **Tab indices:** never hardcode tab numbers beyond 0 (Assets) — use
  widget identity checks instead.

## Plugin system

User-authored plugins live in `~/.doxyedit/plugins/*.py`. See
`docs/plugins.md` for the API and `docs/sample_plugin.py` for a
template. To add a new lifecycle event from the host side:

1. Pick the call site (e.g. `_on_docked_save` for "post saved").
2. Add `from doxyedit import plugins as _dp; _dp.emit("name", ...)`
   wrapped in try/except so a buggy plugin can't take down the host.
3. Document the event in `docs/plugins.md` with the handler signature.
4. Optionally add a test in `tests/test_plugins_loader.py`.

## Hardening pattern

Several `_rebind_project` / `_on_inner_tab_changed` /
`Project.from_dict` paths are wrapped in per-step try/except + logging.

When adding a new path that calls into multiple sub-handlers (panel
refreshes, model record loads, etc), follow the same pattern: one
try/except per step + `logging.exception` so a single failure
surfaces in `~/.doxyedit/last_run.log` and the rest of the chain keeps
running. The user keeps a working app and a diagnosable trace instead
of a silent crash.

## Status

- **Tests:** 57 passing, ~7s headless.
- **Tokenization validator:** ALL CLEAN.
- **Theme contrast:** 21 themes pass WCAG AAA.
- **CI:** GitHub Actions on every push/PR.
- **BACKLOG:** all H4 refactors + parked feature ideas shipped as of
  v2.5.6 (May 2026).
