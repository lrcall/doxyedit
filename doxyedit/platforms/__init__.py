"""Platform backends + the platform-assignment UI panel.

The PlatformPanel widget lives in panel.py for historical reasons
(this used to be doxyedit/platforms.py at the same level as bridge.py;
when the package was created in 23792ab to host bluesky/mastodon API
clients, the module-vs-package conflict shadowed the panel and broke
the `from doxyedit.platforms import PlatformPanel` import). Re-export
restores the original import path so window.py + every other caller
keep working without churn.

Each API backend module exposes a small surface like
`post_reply(credentials, parent_url, text)` returning {ok, ...}.
"""

from doxyedit.platforms.panel import PlatformPanel  # noqa: F401
