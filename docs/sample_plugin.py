"""Sample DoxyEdit plugin.

Copy this file to ~/.doxyedit/plugins/log_pushes.py (or any name
ending in .py - the underscore-prefixed names are reserved for
DoxyEdit internals and are skipped by the loader).

On next launch, DoxyEdit's plugin loader will:
  1. Import this module.
  2. Call `register(api)` once.
  3. Route every emitted event through any handlers you registered.

The host app is forgiving: if your handler raises, your plugin gets
disabled for the rest of the session and the error is logged - the
host keeps running.
"""


def register(api):
    """Required entry point. api exposes:
        api.on(event_name, handler)
        api.log(msg)   # writes to ~/.doxyedit/plugins.log
    """

    def on_project_loaded(project, project_path):
        n_assets = len(project.assets)
        n_posts = len(project.posts) if hasattr(project, "posts") else 0
        api.log(
            f"Project loaded: {project_path} "
            f"({n_assets} assets, {n_posts} posts)")

    def on_post_pushed(post, platform, ok, detail):
        tag = "OK" if ok else "FAIL"
        api.log(
            f"{tag} push  post={post.id[:8]}  platform={platform}  "
            f"detail={detail[:60]}")

    api.on("project_loaded", on_project_loaded)
    api.on("post_pushed", on_post_pushed)
