# API-direct posting clients

Stdlib-only HTTP clients for posting to social platforms without going through the userscript+browser DOM. Bypasses every selector-breakage class of bug because the platform's public API stays stable across UI redesigns.

Currently:

- `bluesky.py` - ATProto. `create_post`, `post_reply`, `like_post`. App-password auth.
- `mastodon.py` - REST. `create_post`, `post_reply`, `favourite`. Access-token auth.

Reddit needs an OAuth "script" app and is out for now (separate credential dance, app review).

## Wiring

Server endpoint: `POST /doxyedit-api-post` on the existing HTTP bridge.

```json
{
  "platformKey": "bluesky" | "mastodon",
  "text": "the post body",
  "parent_url": "optional - reply target",
  "credentials": { ... per-platform ... }
}
```

Returns `{"ok": true, "url": "<live URL>", "platform": "..."}` on success or `{"ok": false, "error": "..."}` on failure. The error string is the upstream API's message verbatim so an HTTP 401 from Bluesky reads `BlueskyError('HTTP 401 AuthenticationRequired: ...')`.

## Bluesky setup

1. Log in at bsky.app, go to **Settings -> Privacy and security -> App passwords**.
2. Click **Add App Password**, name it (e.g. `doxyedit`), copy the generated password (looks like `xxxx-xxxx-xxxx-xxxx`).
3. Credentials shape:

```json
{
  "handle": "yourname.bsky.social",
  "app_password": "xxxx-xxxx-xxxx-xxxx"
}
```

Store wherever DoxyEdit reads them - per-project on the `CollectionIdentity` is the obvious spot, or a project-level `credentials` dict keyed by platform.

## Mastodon setup

1. Log in to your Mastodon instance, go to **Preferences -> Development -> New application**.
2. Name it `doxyedit`, leave redirect_uri default, scopes need at least `write:statuses` and `write:favourites`.
3. After creating, copy the **Your access token** field.
4. Credentials shape:

```json
{
  "instance": "mastodon.gamedev.place",
  "access_token": "xxxx..."
}
```

`instance` is the host name, no `https://`.

## Why this exists alongside the userscript

| | Userscript / extension | API-direct |
|--|--|--|
| Browser required | Yes | No |
| Survives DOM redesigns | No (selectors break) | Yes |
| Image attachments | Yes | Coming soon (Bluesky needs uploadBlob, Mastodon needs `/api/v2/media`) |
| Post types covered | Anything the user can click | Text + reply only for now |
| One-off testing | One-click | Requires credentials setup |
| Scheduled / headless | Needs Brave running | Pure HTTP |

The userscript stays the primary path for ad-hoc one-click posts because zero setup. The API-direct path becomes the better choice for scheduled posts that fire while the user is asleep, or for posts that require reliability (a launch announcement that absolutely must land).

## Borrowed from

This module is a port of `E:/git/autofill/bin/platforms/{bluesky,mastodon}.py`, with a `create_post` function added on top for new top-level posts (autofill's flow was reply-focused).
