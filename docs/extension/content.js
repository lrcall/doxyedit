// doxyedit autofill - browser extension content script.
//
// This is the Manifest V3 extension flavor of the userscript at
// docs/userscripts/doxyedit-autofill.user.js. The JS source is kept
// byte-identical between the two so only one surface needs
// maintenance; the shim below replaces the features the userscript
// header grants (GM_setClipboard, GM_xmlhttpRequest, @connect
// whitelisting) with equivalent extension-context calls or no-ops.
//
// Why ship both:
//   - Userscript: fast to iterate via the HTTP bridge's
//     @updateURL auto-pull; zero browser config to install.
//   - Extension: persistent across Brave profiles; no
//     Tampermonkey @connect reapproval when DoxyEdit renames
//     identifiers (the exact bug that broke asset fetches after
//     the psyai -> bridge rename); survives Tampermonkey updates.
//
// To build the extension bundle:
//   1. cp docs/userscripts/doxyedit-autofill.user.js docs/extension/content.js
//   2. git apply the header-stripping patch below (or run the
//      shim manually) - the userscript header's // ==UserScript==
//      block is harmless in extension context but contributes
//      nothing, so it's left in place.
//
// The shim:
//   - GM_setClipboard -> navigator.clipboard.writeText (already
//     defined via @grant fallback in the userscript source)
//   - GM_xmlhttpRequest -> not needed; fetch works natively in the
//     extension because host_permissions in manifest.json
//     whitelists 127.0.0.1:8910-8912
//   - @connect -> replaced by host_permissions in manifest.json
//
// Install:
//   1. Open brave://extensions (or chrome://extensions)
//   2. Enable Developer mode
//   3. Load unpacked -> select this folder (docs/extension/)
//   4. The amber FAB appears on every supported compose page.
//
// To sync this file with the userscript after an edit:
//   cp docs/userscripts/doxyedit-autofill.user.js docs/extension/content.js

// Shim: Tampermonkey's GM_* symbols don't exist in extension
// context, but our userscript guards every call site with
// `typeof GM_xxx === "function"` checks. When those return false
// the fallbacks already present in the code path fire (plain
// fetch instead of GM_xmlhttpRequest, navigator.clipboard instead
// of GM_setClipboard). So no extra shim is needed - the userscript
// code below runs as-is.

// -------------------------------------------------------------------
// USERSCRIPT SOURCE BELOW. Keep in sync with
// docs/userscripts/doxyedit-autofill.user.js.
// -------------------------------------------------------------------


// ── DOXYEDIT BRIDGE CONFIG ─────────────────────────────────────────────────
// One of three transports will be active at any given moment:
//   A. window.__bridge_data injected via CDP (preferred - live)
//   B. HTTP bridge fetched from 127.0.0.1:{PORT}/doxyedit.json
//   C. "paste from clipboard" button (manual, always available)
// If none respond, the hardcoded DOXYEDIT_FALLBACK below is used.

const HTTP_BRIDGE_PORTS = [8910, 8911, 8912];  // DoxyEdit tries first free
const HTTP_BRIDGE_POLL_MS = 8000;              // refetch every 8s if active
const DOXYEDIT_PANEL_MARKER = "_bridge_panel_v1";        // matches bridge.py

// ── HARDCODED FALLBACK ─────────────────────────────────────────────────────
// Used only when no DoxyEdit transport is live. Lets the script work
// standalone on a machine that doesn't have DoxyEdit running.
const DOXYEDIT_FALLBACK = {
  handle: "doxyedit_user",
  displayName: "bridge",
  taglineShort: "a retro sci-fi point-and-click.",
  oneLine: "retro sci-fi point-and-click VN. wishlist on steam ↓",
  bioShort: "bridge - retro sci-fi point-and-click VN. dialogue trees, crt glow, bad decisions. demo at steam next fest · june 2026.",
  bioMedium: "bridge: a retro sci-fi point-and-click VN.\ndialogue trees, crt glow, bad decisions.\nren'py · hand-drawn pixel · shipping 2026.\ndemo at steam next fest.",
  bioLong: "bridge is a retro sci-fi point-and-click visual novel.\na diagnostic. a unit you shouldn't have kept talking to. a city that was never supposed to hold this many ghosts.\n\nchoice-driven dialogue trees, hand-drawn pixel backgrounds, a synth score, and enough arcade machines to make the long conversations survivable.\n\ncurrently in development - playable at Steam Next Fest, June 2026.",
  steamURL: "https://store.steampowered.com/",
  itchURL: "https://itch.io/",
  discordURL: "",
  newsletterURL: "",
  tags: "#gamedev #indiedev #visualnovel #renpy #pixelart",
  posts: {}
};

// ── LIVE DATA ──────────────────────────────────────────────────────────────
// currentData holds whichever source is active. source flags the
// provenance for the status dot in the floating FAB.
let currentData = DOXYEDIT_FALLBACK;
let currentSource = "fallback";

function unwrapPayload(obj) {
  // Accept both plain-dict and marker-wrapped payloads.
  if (obj && obj[DOXYEDIT_PANEL_MARKER] === true && obj.payload) return obj.payload;
  return obj;
}

function applyData(data, source) {
  if (!data || typeof data !== "object") return false;
  currentData = Object.assign({}, DOXYEDIT_FALLBACK, data);
  if (!currentData.posts) currentData.posts = {};
  currentSource = source;
  rebuildPanel();
  updateFab();
  return true;
}

// ── TRANSPORT A: window.__bridge_data (CDP push) ────────────────────────────
function tryCdpInjection() {
  if (window.__bridge_data) {
    const payload = unwrapPayload(window.__bridge_data);
    applyData(payload, "cdp");
  }
  window.addEventListener("doxyedit-data-updated", (ev) => {
    const payload = unwrapPayload(ev.detail || window.__bridge_data);
    applyData(payload, "cdp");
  });
}

// ── TRANSPORT B: HTTP bridge ───────────────────────────────────────────────
let httpPollTimer = null;
let httpBridgePort = null;

function tryHttpBridge() {
  // Probe each candidate port once. First one that answers wins;
  // subsequent polls only hit that port.
  for (const port of HTTP_BRIDGE_PORTS) {
    fetchFromPort(port, true);
  }
  // Continuous poll. When a winning port is known, poll it. When
  // the port is unknown (never found, or dropped after a miss)
  // re-probe all candidates so the userscript rediscovers the
  // bridge if DoxyEdit is started or restarted on a different port
  // after this page loaded.
  if (httpPollTimer === null) {
    httpPollTimer = setInterval(() => {
      if (httpBridgePort) {
        fetchFromPort(httpBridgePort, false);
      } else {
        for (const port of HTTP_BRIDGE_PORTS) {
          fetchFromPort(port, true);
        }
      }
    }, HTTP_BRIDGE_POLL_MS);
  }
}

function fetchFromPort(port, isProbe) {
  if (typeof GM_xmlhttpRequest !== "function") return;
  // If the cached winning port stops answering (bridge shut down,
  // DoxyEdit restarted on a different port, wrong endpoint mounted),
  // drop it so the next poll tick re-probes every candidate.
  const handleMiss = () => {
    if (!isProbe && httpBridgePort === port) {
      httpBridgePort = null;
    }
  };
  GM_xmlhttpRequest({
    method: "GET",
    url: `http://127.0.0.1:${port}/doxyedit.json`,
    timeout: 1500,
    onload: (resp) => {
      if (resp.status !== 200) { handleMiss(); return; }
      try {
        const parsed = JSON.parse(resp.responseText);
        if (parsed[DOXYEDIT_PANEL_MARKER] !== true) { handleMiss(); return; }
        const payload = unwrapPayload(parsed);
        // CDP-injected data wins over HTTP (CDP is always more live).
        if (currentSource === "cdp") return;
        if (isProbe) httpBridgePort = port;
        applyData(payload, "http");
      } catch (e) { handleMiss(); }
    },
    onerror: handleMiss,
    ontimeout: handleMiss,
  });
}

// ── TRANSPORT C: clipboard paste ───────────────────────────────────────────
async function pasteFromClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    if (!text) {
      alert("Clipboard is empty.");
      return;
    }
    let parsed;
    try { parsed = JSON.parse(text); }
    catch (e) {
      alert("Clipboard doesn't contain DoxyEdit JSON.\nCopy a post from DoxyEdit first.");
      return;
    }
    if (parsed[DOXYEDIT_PANEL_MARKER] !== true) {
      alert("Clipboard JSON doesn't carry the DoxyEdit marker.");
      return;
    }
    const payload = unwrapPayload(parsed);
    const kind = parsed.kind || "full";
    if (kind === "full") {
      applyData(payload, "clipboard");
      alert(`DoxyEdit data loaded (${Object.keys(payload.posts || {}).length} posts, ${currentData.displayName}).`);
    } else if (kind === "post") {
      // Single-post clipboard payload - fill current field(s) directly.
      fillPostPayload(payload);
    } else if (kind === "identity") {
      fillFocusedField(payload.text || "");
    }
  } catch (err) {
    alert("Clipboard read failed: " + err.message);
  }
}

function fillPostPayload(payload) {
  // Shape: { platform: "reddit_indiedev", title?: str, body?: str, text?: str }
  if (payload.title !== undefined || payload.body !== undefined) {
    // Reddit post-type tabs: new.reddit.com defaults to the Images
    // tab for some users and on some subreddits. Text post fields
    // aren't mounted on those tabs, so look for a visible "Text" tab
    // button and click it first to ensure title + body fields exist.
    // Selector list is a best-effort stub; unknown UIs silently fall
    // through and the existing field scan handles or fails loudly.
    const TEXT_TAB_SELECTORS = [
      'button[role="tab"][aria-label*="Text" i]',
      'button[data-post-type="text" i]',
      'a[href*="type=TEXT"]',
      'shreddit-composer button[slot*="text" i]',
    ];
    for (const sel of TEXT_TAB_SELECTORS) {
      try {
        const tab = document.querySelector(sel);
        if (tab && tab.offsetParent !== null
            && tab.getAttribute("aria-selected") !== "true") {
          tab.click();
          break;
        }
      } catch (e) { /* bad selector, skip */ }
    }
    // Title field: try a broad selector list so new.reddit.com's
    // Shreddit web components and the old compose form are both
    // covered. Tests each candidate in order; first match wins.
    const TITLE_SELECTORS = [
      'textarea[name="title"]',                      // old.reddit
      'textarea[placeholder*="Title" i]',            // generic
      'input[placeholder*="Title" i]',
      'textarea[aria-label*="title" i]',
      'input[aria-label*="title" i]',
      // new.reddit uses the faceplate design system for form inputs.
      // Selectors below borrowed from the autofill reference project
      // (E:/git/autofill/userscript/autofill.user.js) where they're
      // known to hit the title field on live /submit pages.
      'faceplate-textarea-input[name="title"] textarea',
      'faceplate-input[name="title"] input',
      'shreddit-composer [slot="title"]',
      'shreddit-composer-title-input textarea',
      'shreddit-composer-title-input input',
      '[data-testid="post-title-input"]',
      '[name="title"]',                              // form fallback
    ];
    let titleField = null;
    let titleMatched = null;
    for (const sel of TITLE_SELECTORS) {
      const el = document.querySelector(sel);
      if (el) { titleField = el; titleMatched = sel; break; }
    }
    if (titleField && payload.title) {
      setReactValue(titleField, payload.title);
      setUploadStatus(
        `title filled via ${titleMatched}`, true);
    } else if (payload.title) {
      copyToClipboard(payload.title);
      setUploadStatus(
        "no title field found; title copied to clipboard", false);
    }
    // Body: prefer a paste-style injection into the first body-like
    // editor (Draft.js / Slate / generic contenteditable) inside a
    // compose container. setReactValue doesn't stick in rich editors;
    // paste events are what Reddit's body editor actually listens on.
    if (payload.body) {
      const BODY_SELECTORS = [
        'shreddit-composer [contenteditable="true"]', // new.reddit
        '[role="dialog"] [contenteditable="true"]',
        '[aria-modal="true"] [contenteditable="true"]',
        '[data-testid*="post" i] [contenteditable="true"]',
        '[data-testid*="compos" i] [contenteditable="true"]',
        'textarea[name="text"]',                     // old.reddit body
        'textarea[placeholder*="body" i]',
        'div.DraftEditor-root [contenteditable="true"]',
      ];
      let bodyField = null;
      let bodyMatched = null;
      for (const sel of BODY_SELECTORS) {
        const el = document.querySelector(sel);
        if (el && el.offsetParent !== null) {
          bodyField = el; bodyMatched = sel; break;
        }
      }
      if (bodyField) {
        try {
          bodyField.focus();
          if (bodyField.tagName === "TEXTAREA") {
            setReactValue(bodyField, payload.body);
          } else {
            const dt = new DataTransfer();
            dt.setData("text/plain", payload.body);
            bodyField.dispatchEvent(new ClipboardEvent("paste", {
              clipboardData: dt, bubbles: true, cancelable: true,
            }));
          }
          setUploadStatus(
            `body filled via ${bodyMatched}`, true);
        } catch (e) {
          copyToClipboard(payload.body);
          setUploadStatus(
            `body fill failed (${e.message}); copied to clipboard`,
            false);
        }
      } else {
        copyToClipboard(payload.body);
        setUploadStatus(
          "no body editor found; body copied to clipboard", false);
      }
    }
  } else if (payload.text) {
    fillFocusedField(payload.text);
  }
}

// ── UTILITIES ──────────────────────────────────────────────────────────────

function copyToClipboard(text) {
  if (typeof GM_setClipboard === "function") {
    GM_setClipboard(text, "text");
  } else if (navigator.clipboard) {
    navigator.clipboard.writeText(text);
  }
}

function setReactValue(el, value) {
  const proto = el.tagName === "TEXTAREA"
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function fillFocusedField(text) {
  const el = document.activeElement;
  if (!el) { alert("No focused field. Click into a text field first."); return; }
  if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
    setReactValue(el, text);
  } else if (el.isContentEditable) {
    el.focus();
    document.execCommand("selectAll", false, null);
    document.execCommand("insertText", false, text);
  } else {
    copyToClipboard(text);
    alert("Field is not directly fillable - text copied to clipboard. Paste manually.");
  }
}

// ── ONE-CLICK POST ─────────────────────────────────────────────────────────
// Fill image + fill caption + click the platform's submit button, all
// in sequence. Per-host submit-button selectors live in POST_NOW_HOSTS
// below. Missing selectors for a host degrade to a clear status
// message rather than a silent failure; the user can still hit their
// platform's native submit button manually.

// Short keyword each host corresponds to in currentData.posts.
// Same shape as HOST_POST_TAGS but narrower: 1:1 host->key, no
// compound matching. Reddit is special-cased below because its posts
// are keyed reddit_<subreddit> and resolve to {title, body} objects,
// not plain strings.
const HOST_TO_POST_KEY = {
  "bsky.app": "bluesky",
  "x.com": "x",
  "twitter.com": "twitter",
  "threads.net": "threads",
  // Game / art-promotion platforms. Selector stubs; these use the
  // short-form POST NOW flow (attach first asset + fill single
  // caption + click submit) which may or may not fit each
  // platform's actual post shape. Fill fails surface as clear
  // status messages per the cron stub-friendly principle.
  "ko-fi.com": "kofi",
  "newgrounds.com": "newgrounds",
  "itch.io": "itch",
  "indiedb.com": "indiedb",
  "gamejolt.com": "gamejolt",
  "tumblr.com": "tumblr",
};
function currentHostPostKey() {
  const host = (location.host || "").toLowerCase();
  if (host.includes("mastodon")) return "mastodon";
  // Reddit: pick the first reddit_<sub> caption the user has in their
  // posts bag. User pre-navigates to the right subreddit's /submit
  // page; we just fill and submit once they're there.
  if (host === "reddit.com" || host.endsWith(".reddit.com")) {
    const keys = Object.keys((currentData && currentData.posts) || {});
    return keys.find((k) => k.startsWith("reddit_")) || null;
  }
  for (const h in HOST_TO_POST_KEY) {
    if (host === h || host.endsWith("." + h)) return HOST_TO_POST_KEY[h];
  }
  return null;
}

// Ordered list of submit-button selectors per host. First visible
// match wins. Empty list = not supported yet for one-click post.
const POST_NOW_HOSTS = {
  "bsky.app": [
    '[data-testid="composerPublishBtn"]',
    'button[aria-label="Publish post"]',
    'div[role="dialog"] button[aria-label*="Post" i]',
  ],
  "x.com": [
    '[data-testid="tweetButtonInline"]',
    '[data-testid="tweetButton"]',
  ],
  "twitter.com": [
    '[data-testid="tweetButtonInline"]',
    '[data-testid="tweetButton"]',
  ],
  "threads.net": [
    'div[role="dialog"] div[role="button"][tabindex="0"]',
  ],
  "mastodon": [
    'button.compose-form__publish-button-wrapper button',
    'button[type="submit"].button.button--block',
  ],
  "reddit.com": [
    // new.reddit.com (Shreddit web components)
    'shreddit-composer button[type="submit"]',
    'shreddit-post-composer button[type="submit"]',
    'button[slot="submit-button"]',
    // Generic modal submit
    '[role="dialog"] button[type="submit"]',
    // old.reddit.com
    'button.btn[name="submit"]',
    'button.submit-link',
  ],
  "old.reddit.com": [
    'button.btn[name="submit"]',
    'button.submit-link',
  ],
  // Stub selectors - best-guess without live inspection. Any host
  // in this group that matches nothing surfaces a clear "no submit
  // button found, click manually" status, which is preferable to a
  // silent fail per the cron rule.
  "ko-fi.com": [
    'button[aria-label*="Post" i]',
    'button[type="submit"]',
    'button.post-button',
  ],
  "newgrounds.com": [
    'input[type="submit"][value*="Post" i]',
    'input[type="submit"][value*="Submit" i]',
    'button[type="submit"]',
  ],
  "itch.io": [
    // Devlog / comment submit; itch.io uses named form buttons.
    'button[name="commit"]',
    'button.btn[type="submit"]',
    'input[type="submit"]',
  ],
  "indiedb.com": [
    'input[type="submit"][value*="Post" i]',
    'button[type="submit"]',
  ],
  "gamejolt.com": [
    // Game page comment composer + blog post submit. Gamejolt
    // uses Vue with class-based buttons; best-guess list until
    // live inspection pins the actual slot.
    'button[type="submit"]',
    'button.button.primary',
    'button[name*="post" i]',
  ],
  "tumblr.com": [
    // New post modal has a "Post" button identified by data-testid
    // on current dashboard, plus a generic fallback.
    'button[data-testid*="post" i]',
    'button[aria-label*="Post" i]',
    'button[type="submit"]',
  ],
};
function postNowSelectorsForHost() {
  const host = (location.host || "").toLowerCase();
  if (host.includes("mastodon")) return POST_NOW_HOSTS.mastodon;
  for (const h in POST_NOW_HOSTS) {
    if (host === h || host.endsWith("." + h)) return POST_NOW_HOSTS[h];
  }
  return null;
}

function _wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

// Backchannel: POST an event to DoxyEdit's /doxyedit-feedback
// endpoint. Used to tell DoxyEdit "I just posted on <platform>" so
// the project can mark the post as POSTED and schedule engagement
// follow-ups.
//
// Resilient: if the bridge is down when we submit, the entry is
// queued in localStorage and retried on every subsequent
// notifyFeedback call plus on page load. DoxyEdit eventually sees
// the event as soon as the bridge comes back up, so a transient
// outage (DoxyEdit restart, port change) doesn't lose the record
// of a post we already submitted on the platform.
const FEEDBACK_QUEUE_KEY = "doxyedit_feedback_queue_v1";
const FEEDBACK_QUEUE_MAX = 50;
// Separate localStorage key for POST NOW attempt history. Status
// strip messages vanish in seconds - this gives the user a short
// scrollback so they can spot which platform came back UNVERIFIED
// after they looked away from the panel for a minute.
const POST_HISTORY_KEY = "doxyedit_post_history_v1";
const POST_HISTORY_MAX = 20;

function _postHistoryLoad() {
  try {
    return JSON.parse(localStorage.getItem(POST_HISTORY_KEY) || "[]");
  } catch (e) { return []; }
}
function _postHistorySave(h) {
  try {
    localStorage.setItem(
      POST_HISTORY_KEY,
      JSON.stringify(h.slice(-POST_HISTORY_MAX)));
  } catch (e) { /* quota full, drop */ }
}
function recordPostAttempt(entry) {
  const h = _postHistoryLoad();
  h.push(Object.assign({t: Date.now(), host: location.host,
                         pageUrl: location.href}, entry));
  _postHistorySave(h);
}
function _formatPostAgo(t) {
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function _feedbackQueueLoad() {
  try {
    return JSON.parse(localStorage.getItem(FEEDBACK_QUEUE_KEY) || "[]");
  } catch (e) { return []; }
}
function _feedbackQueueSave(q) {
  try {
    // Keep only the most recent MAX entries so a persistent outage
    // can't pin localStorage.
    localStorage.setItem(
      FEEDBACK_QUEUE_KEY,
      JSON.stringify(q.slice(-FEEDBACK_QUEUE_MAX)));
  } catch (e) { /* quota full, drop silently */ }
}
function _feedbackUrl() {
  const port = httpBridgePort || HTTP_BRIDGE_PORTS[0];
  return `http://127.0.0.1:${port}/doxyedit-feedback`;
}

// Best-effort diagnostic log that lands in %TEMP%/doxyedit_bridge.log
// on the DoxyEdit side. Lets us ship errors and verbose traces
// from the browser without the user having to open DevTools.
// Mirrors console.log on the client side too.
function logToBridge(level, message, detail) {
  try { console.log(`[doxyedit ${level}]`, message, detail || ""); }
  catch (e) {}
  const port = httpBridgePort || HTTP_BRIDGE_PORTS[0];
  try {
    fetch(`http://127.0.0.1:${port}/doxyedit-log`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        level, message, detail, url: location.href,
      }),
    }).catch(() => { /* bridge down, not fatal */ });
  } catch (e) { /* host blocks fetch, not fatal */ }
}
async function _feedbackPostOne(entry) {
  const r = await fetch(_feedbackUrl(), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(entry),
  });
  return r.ok;
}

async function _flushFeedbackQueue() {
  const queue = _feedbackQueueLoad();
  if (!queue.length) return;
  const remaining = [];
  for (let i = 0; i < queue.length; i++) {
    const entry = queue[i];
    try {
      const ok = await _feedbackPostOne(entry);
      if (!ok) {
        // Non-200: bridge is up but rejecting; drop this one, keep going.
        continue;
      }
    } catch (e) {
      // Network error mid-flush - bridge went down again. Keep the
      // rest of the queue intact for later.
      remaining.push(...queue.slice(i));
      break;
    }
  }
  _feedbackQueueSave(remaining);
  if (queue.length > remaining.length) {
    console.log(`[doxyedit] flushed ${queue.length - remaining.length} queued feedback entry(ies)`);
  }
}

function notifyFeedback(entry) {
  const full = Object.assign(
    {host: location.host, pageUrl: location.href}, entry);
  // Attempt POST. On success, opportunistically flush anything else
  // that was queued from a previous outage. On failure, append to
  // queue for retry.
  _feedbackPostOne(full).then((ok) => {
    if (ok) { _flushFeedbackQueue(); return; }
    // Bridge up but returned non-2xx; don't retry this particular
    // one, bridge is telling us it refused.
  }).catch(() => {
    const q = _feedbackQueueLoad();
    q.push(full);
    _feedbackQueueSave(q);
    logToBridge("warn", "feedback queued for retry (bridge down)");
  });
}

async function postNowOnCurrentPlatform() {
  const postKey = currentHostPostKey();
  const selectors = postNowSelectorsForHost();
  if (!postKey || !selectors) {
    setUploadStatus(
      `one-click post not supported on ${location.host} yet`, false);
    return false;
  }
  const caption = (currentData.posts || {})[postKey];
  if (!caption) {
    setUploadStatus(
      `no "${postKey}" post in DoxyEdit - tag a post for this platform`,
      false);
    return false;
  }
  // Reddit posts come through as {title, body} objects and need a
  // separate fill path that targets both fields distinctly. Asset
  // attach is skipped on Reddit because image posts require a
  // different post-type tab we don't auto-select yet; user should
  // start from /r/<sub>/submit for a text post.
  const isReddit = postKey.startsWith("reddit_");
  if (isReddit) {
    // Subreddit-awareness: plat_key is "reddit_<sub>", so we know
    // which community this post targets. If the user is on the
    // generic /submit (no subreddit selected in the URL), bail out
    // with a direct link to /r/<sub>/submit - that's the one-click
    // path that skips the subreddit picker entirely. Navigating
    // programmatically is tempting but loses the userscript's panel
    // state since Reddit's SPA tears down the script on each full
    // nav.
    const subredditFromKey = postKey.slice("reddit_".length);
    const pathLower = location.pathname.toLowerCase();
    const pathInSub = pathLower.includes(`/r/${subredditFromKey.toLowerCase()}/`);
    if (!pathInSub) {
      const suggestedUrl = `https://${location.host}/r/${subredditFromKey}/submit`;
      setUploadStatus(
        `open ${suggestedUrl} first (Reddit submit needs /r/<sub>/submit)`,
        false);
      // Log for convenience - user can copy from DevTools console.
      console.log(`[doxyedit] navigate to ${suggestedUrl} to post`);
      recordPostAttempt({platformKey: postKey, outcome: "skipped",
                          note: "subreddit not in URL"});
      return false;
    }
    setUploadStatus(`post 1/2: filling title + body on r/${subredditFromKey}...`, true);
    fillPostPayload(Object.assign({}, caption, {platform: postKey}));
    await _wait(500);
  } else {
    // Step 1: attach the first asset if DoxyEdit pushed any. The
    // cascade inside loadAssetFromBridge handles fetch fallbacks and
    // paste-injection on our supported short-form hosts.
    const asset = (currentData.assets || [])[0];
    if (asset) {
      setUploadStatus(`post 1/3: attaching ${asset.name}...`, true);
      const ok = await loadAssetFromBridge(asset);
      if (!ok) {
        setUploadStatus(
          `post 1/3 FAILED: image attach did not complete`, false);
        recordPostAttempt({platformKey: postKey, outcome: "failed",
                            note: "image attach failed"});
        return false;
      }
      await _wait(500);
    }
    // Step 2: fill the caption. For rich-text composers (Bluesky, X
    // contentEditable, Threads) the image attach already focused the
    // compose editor, so paste-style fill is safe. Plain text captions
    // go straight in via insertText.
    setUploadStatus(`post 2/3: filling caption...`, true);
    const captionText = (typeof caption === "string")
      ? caption : (caption.text || caption.body || caption.title || "");
    const active = document.activeElement;
    if (active && (active.isContentEditable || active.tagName === "TEXTAREA"
                    || active.tagName === "INPUT")) {
      if (active.isContentEditable) {
        active.focus();
        document.execCommand("insertText", false, captionText);
      } else {
        setReactValue(active, captionText);
      }
    } else {
      // Try paste on the compose editor found via DOM scan.
      const editor = document.querySelector(
        '[role="dialog"] [contenteditable="true"], ' +
        '[role="dialog"] textarea, ' +
        'form.compose-form textarea');
      if (editor) {
        editor.focus();
        if (editor.isContentEditable) {
          document.execCommand("insertText", false, captionText);
        } else {
          setReactValue(editor, captionText);
        }
      } else {
        setUploadStatus(
          `post 2/3 FAILED: no compose editor found`, false);
        recordPostAttempt({platformKey: postKey, outcome: "failed",
                            note: "no compose editor"});
        return false;
      }
    }
    await _wait(400);
  }
  // Final step: click the submit button. Pick the first visible match
  // from the host's selector list.
  const stepLabel = isReddit ? "post 2/2" : "post 3/3";
  setUploadStatus(`${stepLabel}: clicking submit...`, true);
  let btn = null;
  for (const sel of selectors) {
    try {
      for (const el of document.querySelectorAll(sel)) {
        if (el.offsetParent !== null && !el.disabled
            && el.getAttribute("aria-disabled") !== "true") {
          btn = el; break;
        }
      }
    } catch (e) { /* bad selector, skip */ }
    if (btn) break;
  }
  if (!btn) {
    setUploadStatus(
      `${stepLabel} FAILED: no submit button found - click it manually`,
      false);
    recordPostAttempt({platformKey: postKey, outcome: "failed",
                        note: "no submit button"});
    return false;
  }
  btn.click();
  setUploadStatus(`${stepLabel}: clicked, verifying...`, true);
  // Post-submit verification: poll for the submit button to go away
  // (button detached from DOM, disabled, or its compose container
  // closed). That's a near-universal signal the platform accepted
  // the post. Time out at 8s if no signal - in that case we still
  // notify DoxyEdit but flag as unverified so the Socials tab can
  // warn instead of showing a false-positive POSTED.
  const verifyDeadline = Date.now() + 8000;
  const btnRef = btn;
  let verified = false;
  while (Date.now() < verifyDeadline) {
    await _wait(400);
    // Detached from the document tree entirely?
    if (!document.body.contains(btnRef)) { verified = true; break; }
    // Disabled / aria-disabled after click? (X, Bluesky do this while
    // the request is in flight and then remove the button on success.)
    if (btnRef.disabled
        || btnRef.getAttribute("aria-disabled") === "true"
        || btnRef.offsetParent === null) {
      // Button disabled isn't definitive on its own; confirm by also
      // checking that none of the selector list matches any visible
      // button anymore (compose modal closed).
      let stillVisible = false;
      for (const sel of selectors) {
        try {
          for (const el of document.querySelectorAll(sel)) {
            if (el.offsetParent !== null && !el.disabled
                && el.getAttribute("aria-disabled") !== "true") {
              stillVisible = true; break;
            }
          }
        } catch (e) {}
        if (stillVisible) break;
      }
      if (!stillVisible) { verified = true; break; }
    }
  }
  if (verified) {
    setUploadStatus(`✓ posted to ${postKey} (verified)`, true);
    notifyFeedback({type: "posted", platformKey: postKey,
                    verified: true});
    recordPostAttempt({platformKey: postKey, outcome: "verified"});
  } else {
    setUploadStatus(
      `submitted to ${postKey} but compose didn't close - check the page`,
      false);
    notifyFeedback({type: "posted", platformKey: postKey,
                    verified: false,
                    note: "submit clicked; compose still open after 8s"});
    recordPostAttempt({platformKey: postKey, outcome: "unverified"});
  }
  return verified;
}

// ── IMAGE INJECTION ──────────────────────────────────────────────────────
// Bluesky, X, Mastodon, Reddit, Discord - each platform's compose
// accepts images via a different low-level path. Rather than guess,
// we expose FIVE separate injection strategies as isolated buttons
// so the user can try them on each platform and keep a mental map
// of which works where.
//
// Shared state: once the user picks a file via "📁 pick image", the
// File is cached and every subsequent strategy button runs against
// that same file. Re-pick to swap.
//
// Strategies:
//   1. File Input  - find input[type="file"], set DataTransfer.files
//                    + dispatch input/change. Works when the compose
//                    modal has a file input in the DOM (opened the
//                    image picker at least once).
//   2. Paste       - ClipboardEvent("paste") with the file on the
//                    focused textbox. Bluesky / Twitter / Mastodon /
//                    Discord all handle image paste natively.
//   3. Drop        - DragEvent("drop") on the focused element. Some
//                    platforms (Newgrounds, older Mastodon) accept.
//   4. Click+Input - walk the DOM for a button labelled "image" /
//                    "attach" / "photo", click it (creates the
//                    hidden input[type=file]), then run strategy 1.
//                    Needed on Bluesky when the modal's open but the
//                    user hasn't clicked the image button yet.
//   5. Drag Thumb  - render a draggable <img> preview in the panel
//                    with the File preloaded into DataTransfer on
//                    dragstart. User drags onto the compose's own
//                    drop zone (real drag origin - passes platforms
//                    that reject synthesized drops).
//
// Kept entirely inside the userscript - no DoxyEdit Qt drag, no
// focus splintering.

let _fileInputEl = null;       // hidden <input> for the optional local pick
let _pickedFiles = [];         // cached Files from either DoxyEdit push or local pick
let _uploadStatusEl = null;    // status line under the upload buttons
let _dragThumbEl = null;       // draggable preview <img>
// Thumbnail cache: asset.id -> object URL (or 'loading' / 'error').
// Avoids re-fetching the same asset on every panel rebuild.
const _assetThumbCache = {};

function ensureFileInput() {
  if (_fileInputEl) return _fileInputEl;
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = "image/*";
  inp.multiple = true;
  inp.style.cssText = "position:fixed;left:-9999px;top:-9999px;";
  inp.addEventListener("change", onUploadFilesPicked);
  document.body.appendChild(inp);
  _fileInputEl = inp;
  return inp;
}

function triggerFilePick() {
  const inp = ensureFileInput();
  inp.value = "";
  inp.click();
}

// Fetch a pushed-from-DoxyEdit asset URL, construct a File object,
// stash it in _pickedFiles so the injection strategies run against
// it. One-click: no OS picker, no typing a filename.
//
// Uses GM_xmlhttpRequest (not plain fetch) because the bridge runs
// on http://127.0.0.1 and most social platforms are HTTPS -
// browsers block mixed-content fetches from HTTPS to HTTP, but
// GM_xmlhttpRequest has cross-origin privileges declared by
// @connect in the userscript header and bypasses that check.
// ── FETCH VARIANTS ─────────────────────────────────────────────────────────
// Six different ways to pull asset bytes from the DoxyEdit bridge into
// a browser-side File object, so the user can try each and report
// which one survives whatever Tampermonkey / Brave / Bluesky combo is
// in play today. All accept the same (asset) descriptor and finish
// by handing _pickedFiles to autoInject the same way. Each logs its
// exact code path to the status strip + console.
async function _finalizeLoadedFile(asset, blob) {
  // Mutex against double-attach: the cascade fires multiple variants
  // in sequence with a 4s race timeout; a slow variant that completes
  // AFTER a faster sibling has already attached would otherwise run
  // its own finalize and dispatch a second paste event, producing the
  // two-image result on Bluesky. Use _pickedFiles content as the
  // signal: if a File with the same name and size is already there,
  // skip. Variants return the same bytes so name+size match uniquely.
  const expectedName = asset.name || "image.png";
  if (_pickedFiles.length > 0 &&
      _pickedFiles[0].name === expectedName &&
      _pickedFiles[0].size === blob.size) {
    console.log("[doxyedit] finalize skipped (sibling already attached)");
    return;
  }
  const mime = asset.mime || blob.type || "image/png";
  const f = new File([blob], expectedName, { type: mime });
  _pickedFiles = [f];
  refreshPickedBadge();
  renderDragThumb();
  setUploadStatus(`loaded ${f.name} - auto-injecting...`, true);
  await autoInject();
}

// Variant 4: plain fetch(). Blocked by mixed-content on HTTPS pages
// hitting http://127.0.0.1, but works fine on HTTP pages or when the
// browser has the "Insecure content" permission for the site.
// (v1/v2/v3 GM_xmlhttpRequest variants were dropped: confirmed broken
// on this install because the psyai -> bridge rename re-registered
// the script under a new (@namespace, @name) and Tampermonkey never
// re-granted @connect 127.0.0.1 transparently. Plain fetch / XHR /
// img+canvas all work reliably so the cascade goes through those.)
function loadAssetV4_PlainFetch(asset) {
  setUploadStatus(`v4 (plain fetch) -> ${asset.url}`, true);
  return fetch(asset.url)
    .then(async (r) => {
      if (!r.ok) {
        setUploadStatus(`v4: HTTP ${r.status}`, false);
        return false;
      }
      const buf = await r.arrayBuffer();
      await _finalizeLoadedFile(
        asset, new Blob([buf], {type: asset.mime || "image/png"}));
      setUploadStatus(`v4 OK (${buf.byteLength}B)`, true);
      return true;
    })
    .catch((e) => {
      setUploadStatus(`v4: ${e.message}`, false);
      return false;
    });
}

// Variant 5: plain XMLHttpRequest (non-GM). Same mixed-content
// limitations as fetch but some Tampermonkey environments route
// differently.
function loadAssetV5_PlainXHR(asset) {
  return new Promise((resolve) => {
    setUploadStatus(`v5 (plain XHR) -> ${asset.url}`, true);
    const xhr = new XMLHttpRequest();
    xhr.open("GET", asset.url, true);
    xhr.responseType = "arraybuffer";
    xhr.timeout = 15000;
    xhr.onload = async () => {
      if (xhr.status !== 200) {
        setUploadStatus(`v5: HTTP ${xhr.status}`, false);
        resolve(false); return;
      }
      const buf = xhr.response;
      await _finalizeLoadedFile(
        asset, new Blob([buf], {type: asset.mime || "image/png"}));
      setUploadStatus(`v5 OK (${buf.byteLength}B)`, true);
      resolve(true);
    };
    xhr.onerror = () => { setUploadStatus(`v5: network error (mixed-content?)`, false); resolve(false); };
    xhr.ontimeout = () => { setUploadStatus(`v5: timeout 15s`, false); resolve(false); };
    try { xhr.send(); }
    catch (e) { setUploadStatus(`v5: ${e.message}`, false); resolve(false); }
  });
}

// Variant 6: load into an <img>, draw to canvas, canvas.toBlob. Every
// step is sync except the final toBlob. Bypasses responseType quirks
// entirely because the browser does the decoding. Loses the original
// bytes (re-encodes as PNG from canvas) but that's fine for posting.
function loadAssetV6_ImgCanvas(asset) {
  return new Promise((resolve) => {
    setUploadStatus(`v6 (img+canvas) -> ${asset.url}`, true);
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0);
        canvas.toBlob(async (blob) => {
          if (!blob) {
            setUploadStatus(`v6: toBlob returned null`, false);
            resolve(false); return;
          }
          await _finalizeLoadedFile(asset, blob);
          setUploadStatus(`v6 OK (${blob.size}B, re-encoded PNG)`, true);
          resolve(true);
        }, "image/png");
      } catch (e) {
        setUploadStatus(`v6: canvas exception ${e.message}`, false);
        resolve(false);
      }
    };
    img.onerror = (e) => {
      setUploadStatus(`v6: img onerror (CORS / mixed-content)`, false);
      resolve(false);
    };
    img.src = asset.url;
  });
}

// Default entry point cascades through the three working fetch
// variants. GM_xmlhttpRequest-based paths were dropped entirely
// (confirmed broken on this install; Tampermonkey never re-granted
// @connect after the rename). Double-attach protection lives in
// _finalizeLoadedFile via a _pickedFiles content check.
const _ASSET_CASCADE = [
  ["v4 plain fetch", loadAssetV4_PlainFetch],
  ["v5 plain XHR",   loadAssetV5_PlainXHR],
  ["v6 img+canvas",  loadAssetV6_ImgCanvas],
];
async function loadAssetFromBridge(asset) {
  if (!asset || !asset.url) {
    setUploadStatus("✗ asset has no url", false);
    return false;
  }
  logToBridge("debug", "fetching asset", asset.url);
  for (const [label, fn] of _ASSET_CASCADE) {
    setUploadStatus(`trying ${label}...`, true);
    // Race the variant against a 4s hint. If the variant's own
    // timeout (10-15s) hasn't fired by then we move on. Late
    // completers that still try to finalize are blocked by the
    // content-match guard in _finalizeLoadedFile.
    const result = await Promise.race([
      fn(asset).then((ok) => ({winner: label, ok})),
      new Promise((r) => setTimeout(() => r({winner: null, ok: false}), 4000)),
    ]);
    if (result.ok) {
      logToBridge("info", "cascade winner", label);
      return true;
    }
    if (result.winner === null) {
      setUploadStatus(`${label} stalled 4s, moving on`, false);
    }
  }
  setUploadStatus("✗ every variant failed; try manual via click image btn", false);
  return false;
}

// Try strategies 1 -> 4 (2 needs explicit focus, not auto). Stops
// on first success. Used by the click-an-asset-button flow.
async function autoInject() {
  if (!_pickedFiles.length) return;
  // On paste-friendly hosts (Bluesky, X, Mastodon, Threads) the
  // file input is a React-managed ghost: reading its .files doesn't
  // reflect the site's own image state, and writing to it triggers
  // a second attach even when a paste has already happened. Going
  // paste-only there means one attach, one code path. If the compose
  // isn't focused we fall through to the click strategy so the user
  // can still recover (even though that opens the OS dialog).
  const host = location.hostname.toLowerCase();
  const pasteFriendly = (
    host.endsWith("bsky.app") ||
    host === "x.com" || host.endsWith(".x.com") ||
    host.endsWith("twitter.com") ||
    host.includes("mastodon") ||
    host.endsWith("threads.net")
  );
  if (pasteFriendly) {
    // Find a compose editor. First check if one is already focused;
    // if not, look for contentEditable / textarea inside a compose
    // container and focus it ourselves so the user doesn't have to
    // click into the field before hitting the attach button.
    const COMPOSE_PASTE_CONTEXT = (
      '[role="dialog"], [aria-modal="true"], ' +
      '[data-testid*="compos" i], [data-testid*="post" i], ' +
      'form[class*="compose" i], form[id*="compose" i]'
    );
    // Bounding-rect size filter rejects hidden / placeholder-stub /
    // emoji-picker contentEditable nodes that sites like Threads,
    // Instagram, and Bluesky mount on the same page as the real
    // compose. 40x20 is the empirical floor from the autofill
    // reference project - anything smaller is always a decoration.
    const isBigEnough = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      return r.width > 40 && r.height > 20;
    };
    const isComposeTarget = (el) => el && (
      (el.isContentEditable || el.tagName === "TEXTAREA")
      && el.closest(COMPOSE_PASTE_CONTEXT)
      && isBigEnough(el));
    let target = document.activeElement;
    if (!isComposeTarget(target)) {
      target = null;
      for (const ctx of document.querySelectorAll(COMPOSE_PASTE_CONTEXT)) {
        const cands = ctx.querySelectorAll(
          '[contenteditable="true"], [contenteditable=""], textarea');
        for (const cand of cands) {
          if (cand.offsetParent !== null && isBigEnough(cand)) {
            target = cand;
            break;
          }
        }
        if (target) break;
      }
    }
    if (target) {
      try {
        target.focus();
        const dt2 = new DataTransfer();
        for (const f of _pickedFiles) dt2.items.add(f);
        const pasteEv = new ClipboardEvent("paste", {
          clipboardData: dt2, bubbles: true, cancelable: true,
        });
        target.dispatchEvent(pasteEv);
        setUploadStatus(`✓ attached via paste (no dialog)`, true);
        return;
      } catch (e) { /* fall through to click strategy */ }
    }
    // Paste-friendly host but no compose editor found anywhere on
    // the page. Rare: the modal may have been closed or the page
    // is not on a compose route. Don't fall through to Strategy 1
    // because that causes dup-attach on these sites.
    setUploadStatus(
      "no compose editor found on this page; open a compose first",
      false);
    return;
  }
  // Strategy 1: existing input[type=file]. Only runs on non-paste-
  // friendly hosts (Newgrounds, Reddit upload, ko-fi, etc.) where the
  // file-input is the actual source of truth for attachments.
  const candidates = Array.from(
    document.querySelectorAll('input[type="file"]'));
  // Exclude profile-picture uploaders that might be on the same page
  // (settings tabs beside compose, user menus). Match is against the
  // input's own name/id/class only; the compose-context match below
  // handles container-level disambiguation.
  const isNotAvatar = (el) => {
    const attrs = [el.name, el.id, el.className].join(" ").toLowerCase();
    return !/\b(avatar|banner|profile_pic|profilepic|header_image|headerimage|favicon)\b/.test(attrs);
  };
  // Compose-context selector list covers upload forms (Newgrounds:
  // form[action*=upload]) and inline composers that live in a plain
  // <form class="compose-form">. Modal composers (Bluesky, X) never
  // reach here because pasteFriendly caught them above.
  const COMPOSE_CONTEXT = (
    '[role="dialog"], [aria-modal="true"], ' +
    '[data-testid*="compos" i], [data-testid*="post" i], ' +
    'form[class*="compose" i], form[id*="compose" i], ' +
    'form[action*="upload" i]'
  );
  let target = candidates.find((el) => {
    if (!isNotAvatar(el)) return false;
    const accept = (el.getAttribute("accept") || "").toLowerCase();
    if (accept && !accept.includes("image") && accept !== "*/*") return false;
    return el.closest(COMPOSE_CONTEXT);
  }) || candidates.find((el) => {
    if (!isNotAvatar(el)) return false;
    const accept = (el.getAttribute("accept") || "").toLowerCase();
    return !accept || accept.includes("image") || accept === "*/*";
  });
  if (target) {
    try {
      const dt = new DataTransfer();
      for (const f of _pickedFiles) dt.items.add(f);
      target.files = dt.files;
      target.dispatchEvent(new Event("input", { bubbles: true }));
      target.dispatchEvent(new Event("change", { bubbles: true }));
      setUploadStatus(`✓ attached via file input`, true);
      return;
    } catch (e) { /* fall through */ }
  }
  // Strategy 4: click image/photo/attach button, retry input.
  const btnPatterns = [
    'button[aria-label*="image" i]',
    'button[aria-label*="photo" i]',
    'button[aria-label*="attach" i]',
    'button[aria-label*="media" i]',
    '[data-testid*="image" i][role="button"]',
    '[data-testid*="photo" i][role="button"]',
    '[data-testid*="attach" i]',
  ];
  let imgBtn = null;
  for (const sel of btnPatterns) {
    for (const el of document.querySelectorAll(sel)) {
      if (el.closest('[role="dialog"], [aria-modal="true"], [data-testid*="compos" i]')) {
        imgBtn = el; break;
      }
    }
    if (imgBtn) break;
  }
  if (imgBtn) {
    imgBtn.click();
    await new Promise((r) => setTimeout(r, 200));
    const inp = Array.from(
      document.querySelectorAll('input[type="file"]')).find(
      (el) => !el.closest('#doxyedit-autofill-panel'));
    if (inp) {
      try {
        const dt = new DataTransfer();
        for (const f of _pickedFiles) dt.items.add(f);
        inp.files = dt.files;
        inp.dispatchEvent(new Event("input", { bubbles: true }));
        inp.dispatchEvent(new Event("change", { bubbles: true }));
        setUploadStatus(`✓ attached via click+input`, true);
        return;
      } catch (e) { /* fall through */ }
    }
  }
  // Strategy 2: paste on focused contenteditable.
  const active = document.activeElement;
  if (active && (active.isContentEditable
                  || active.tagName === "TEXTAREA"
                  || active.tagName === "INPUT")) {
    try {
      const dt = new DataTransfer();
      for (const f of _pickedFiles) dt.items.add(f);
      active.dispatchEvent(new ClipboardEvent("paste", {
        clipboardData: dt, bubbles: true, cancelable: true,
      }));
      setUploadStatus(`✓ attached via paste`, true);
      return;
    } catch (e) { /* fall through */ }
  }
  setUploadStatus(
    "⚠ all auto-inject strategies failed - click into compose + try the strategy buttons below",
    false);
}

function onUploadFilesPicked(ev) {
  _pickedFiles = Array.from(ev.target.files || []);
  if (!_pickedFiles.length) return;
  refreshPickedBadge();
  renderDragThumb();
  setUploadStatus(
    `picked ${_pickedFiles.length} file(s) - try a strategy below`, true);
}

function refreshPickedBadge() {
  const badge = document.getElementById("doxyedit-picked-name");
  if (!badge) return;
  badge.textContent = _pickedFiles.length
    ? `📎 ${_pickedFiles[0].name}${_pickedFiles.length > 1
        ? ` (+${_pickedFiles.length - 1})` : ""}`
    : "(no file picked)";
}

function renderDragThumb() {
  const holder = document.getElementById("doxyedit-drag-thumb-holder");
  if (!holder) return;
  holder.innerHTML = "";
  _dragThumbEl = null;
  if (!_pickedFiles.length) return;
  const first = _pickedFiles[0];
  const img = document.createElement("img");
  img.draggable = true;
  img.style.cssText = `
    max-width: 100%; max-height: 80px; border: 2px dashed #ff6b6b;
    border-radius: 4px; cursor: grab; object-fit: contain;
    background: #222;
  `;
  img.title = "drag this onto the compose area";
  // Preload as object URL so the thumb is visible + the File is
  // already constructed for dragstart.
  img.src = URL.createObjectURL(first);
  img.addEventListener("dragstart", (ev) => {
    try {
      for (const f of _pickedFiles) ev.dataTransfer.items.add(f);
      ev.dataTransfer.effectAllowed = "copy";
    } catch (e) { /* ignore */ }
  });
  holder.appendChild(img);
  _dragThumbEl = img;
}

function setUploadStatus(msg, ok) {
  if (!_uploadStatusEl) return;
  _uploadStatusEl.textContent = msg;
  _uploadStatusEl.style.color = ok ? "#6bff6b" : "#ffb36b";
  setTimeout(() => {
    if (_uploadStatusEl) _uploadStatusEl.textContent = "";
  }, 6000);
}

function preloadAssetThumbs(assets) {
  // Use plain fetch first (v4 in the cascade) since it's confirmed
  // working on this install. Fall back to XHR then GM_xmlhttpRequest
  // so the thumb works regardless of which transport is available.
  for (const a of assets || []) {
    if (!a || !a.id || !a.url) continue;
    if (_assetThumbCache[a.id]) continue;  // cached, loading, or errored
    _assetThumbCache[a.id] = "loading";
    _preloadOneThumb(a).then((objectUrl) => {
      _assetThumbCache[a.id] = objectUrl || "error";
      rebuildPanel();
    });
  }
}

async function _preloadOneThumb(a) {
  const mime = a.mime || "image/png";
  // Try plain fetch first.
  try {
    const r = await fetch(a.url);
    if (r.ok) {
      const buf = await r.arrayBuffer();
      return URL.createObjectURL(new Blob([buf], {type: mime}));
    }
  } catch (e) { /* fall through */ }
  // XHR fallback (same mixed-content constraints as fetch but
  // different Tampermonkey proxy path).
  try {
    const xhr = await new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("GET", a.url, true);
      x.responseType = "arraybuffer";
      x.onload = () => (x.status === 200 ? resolve(x) : reject(new Error(String(x.status))));
      x.onerror = () => reject(new Error("net"));
      x.timeout = 10000;
      x.ontimeout = () => reject(new Error("timeout"));
      x.send();
    });
    return URL.createObjectURL(new Blob([xhr.response], {type: mime}));
  } catch (e) { /* fall through */ }
  // GM_xmlhttpRequest last resort (may stall, but at worst we get "error").
  if (typeof GM_xmlhttpRequest === "function") {
    return new Promise((resolve) => {
      GM_xmlhttpRequest({
        method: "GET", url: a.url,
        responseType: "arraybuffer", timeout: 5000,
        onload: (resp) => {
          if (resp.status === 200 && resp.response instanceof ArrayBuffer) {
            resolve(URL.createObjectURL(new Blob([resp.response], {type: mime})));
          } else { resolve(null); }
        },
        onerror: () => resolve(null),
        ontimeout: () => resolve(null),
      });
    });
  }
  return null;
}

function requirePicked() {
  if (!_pickedFiles.length) {
    setUploadStatus("✗ pick a file first", false);
    return false;
  }
  return true;
}

// Strategy 1 - set .files on an existing <input type="file">.
function strategyFileInput() {
  if (!requirePicked()) return;
  const candidates = Array.from(
    document.querySelectorAll('input[type="file"]'));
  let target = candidates.find((el) => {
    const accept = (el.getAttribute("accept") || "").toLowerCase();
    if (accept && !accept.includes("image") && accept !== "*/*") return false;
    return el.closest('[role="dialog"], [aria-modal="true"], [data-testid*="compos" i], [data-testid*="post" i]');
  }) || candidates.find((el) => {
    const accept = (el.getAttribute("accept") || "").toLowerCase();
    return !accept || accept.includes("image") || accept === "*/*";
  });
  if (!target) {
    setUploadStatus(
      "✗ no input[type=file] found (click image button first)", false);
    return;
  }
  try {
    const dt = new DataTransfer();
    for (const f of _pickedFiles) dt.items.add(f);
    target.files = dt.files;
    target.dispatchEvent(new Event("input", { bubbles: true }));
    target.dispatchEvent(new Event("change", { bubbles: true }));
    setUploadStatus(
      `✓ strategy 1 (file input) - ${_pickedFiles.length} file(s) injected`, true);
  } catch (e) {
    setUploadStatus(`✗ strategy 1 failed: ${e.message}`, false);
  }
}

// Strategy 2 - paste event on the focused compose element.
function strategyPaste() {
  if (!requirePicked()) return;
  const active = document.activeElement;
  if (!active || !(active.isContentEditable
                    || active.tagName === "TEXTAREA"
                    || active.tagName === "INPUT")) {
    setUploadStatus(
      "✗ no focused text field - click into compose first", false);
    return;
  }
  try {
    const dt = new DataTransfer();
    for (const f of _pickedFiles) dt.items.add(f);
    const pasteEv = new ClipboardEvent("paste", {
      clipboardData: dt, bubbles: true, cancelable: true,
    });
    active.dispatchEvent(pasteEv);
    setUploadStatus(
      `✓ strategy 2 (paste) - dispatched on ${active.tagName}`, true);
  } catch (e) {
    setUploadStatus(`✗ strategy 2 failed: ${e.message}`, false);
  }
}

// Strategy 3 - drop event on the focused element.
function strategyDrop() {
  if (!requirePicked()) return;
  const active = document.activeElement;
  if (!active) {
    setUploadStatus("✗ nothing focused - click compose first", false);
    return;
  }
  try {
    const dt = new DataTransfer();
    for (const f of _pickedFiles) dt.items.add(f);
    const dropEv = new DragEvent("drop", {
      dataTransfer: dt, bubbles: true, cancelable: true,
    });
    active.dispatchEvent(dropEv);
    setUploadStatus(
      `✓ strategy 3 (drop) - dispatched on ${active.tagName}`, true);
  } catch (e) {
    setUploadStatus(`✗ strategy 3 failed: ${e.message}`, false);
  }
}

// Strategy 4 - find + click an "attach image" button, then run
// strategy 1. Gives the compose modal a chance to mount the hidden
// input[type=file] if it hasn't yet.
function strategyClickThenInput() {
  if (!requirePicked()) return;
  const patterns = [
    'button[aria-label*="image" i]',
    'button[aria-label*="photo" i]',
    'button[aria-label*="attach" i]',
    'button[aria-label*="media" i]',
    '[data-testid*="image" i][role="button"]',
    '[data-testid*="photo" i][role="button"]',
    '[data-testid*="attach" i]',
  ];
  let btn = null;
  for (const sel of patterns) {
    const found = document.querySelectorAll(sel);
    for (const el of found) {
      // Prefer buttons inside a compose modal.
      if (el.closest('[role="dialog"], [aria-modal="true"], [data-testid*="compos" i]')) {
        btn = el; break;
      }
    }
    if (btn) break;
  }
  if (!btn) {
    setUploadStatus(
      "✗ no image/photo/attach button found on page", false);
    return;
  }
  btn.click();
  // Give the DOM a beat to mount the file input before running
  // strategy 1 against it.
  setTimeout(() => {
    strategyFileInput();
  }, 200);
  setUploadStatus(
    `→ clicked ${btn.getAttribute("aria-label")
        || btn.getAttribute("data-testid")
        || btn.tagName} - retrying file input in 200ms...`, true);
}

// ── PANEL ──────────────────────────────────────────────────────────────────
// Rebuilt on data changes so the per-post button list reflects the
// current DoxyEdit snapshot.

let panelEl = null;
let fabEl = null;

// Saved position for the FAB (and, by derivation, the panel just
// above it). Persisted to localStorage so the user's placement
// survives page reloads, nav, and browser restarts. Defaults to
// bottom-right on first run.
const FAB_POSITION_STORAGE = "bridge_fab_position_v1";

function loadFabPosition() {
  try {
    const raw = localStorage.getItem(FAB_POSITION_STORAGE);
    if (!raw) return null;
    const pos = JSON.parse(raw);
    if (typeof pos.left === "number" && typeof pos.top === "number") {
      return pos;
    }
  } catch (e) { /* fall through */ }
  return null;
}

function saveFabPosition(pos) {
  try { localStorage.setItem(FAB_POSITION_STORAGE, JSON.stringify(pos)); }
  catch (e) { /* quota exceeded - ignore */ }
}

function applyFabPosition(left, top) {
  if (!fabEl) return;
  // Clamp to viewport so the FAB never lands fully off-screen (can
  // happen after resolution change). Leave an 8px breather.
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const fabW = fabEl.offsetWidth || 90;
  const fabH = fabEl.offsetHeight || 32;
  left = Math.max(8, Math.min(vw - fabW - 8, left));
  top = Math.max(8, Math.min(vh - fabH - 8, top));
  fabEl.style.left = left + "px";
  fabEl.style.top = top + "px";
  fabEl.style.right = "auto";
  fabEl.style.bottom = "auto";
  // Panel anchors above the FAB with the same left edge so they
  // track together. If the panel would flow below the viewport we
  // flip it to anchor at the TOP of the FAB instead.
  if (panelEl) {
    panelEl.style.left = left + "px";
    panelEl.style.right = "auto";
    const panelH = panelEl.offsetHeight || 300;
    // Prefer panel ABOVE the FAB. Flip below if no room above.
    let panelTop = top - panelH - 10;
    if (panelTop < 8) panelTop = top + fabH + 10;
    panelEl.style.top = panelTop + "px";
    panelEl.style.bottom = "auto";
  }
}

function buildPanelScaffold() {
  if (document.getElementById("doxyedit-autofill-panel")) return;
  const panel = document.createElement("div");
  panel.id = "doxyedit-autofill-panel";
  // Position is set by applyFabPosition once the FAB is laid out.
  // Default placement is bottom-right until the user moves it.
  panel.style.cssText = `
    position: fixed; bottom: 60px; right: 20px; z-index: 2147483647;
    background: #111; color: #eee; border: 2px solid #ff6b6b; border-radius: 8px;
    padding: 10px; font-family: ui-monospace, monospace; font-size: 12px;
    max-width: 320px; max-height: 70vh; overflow-y: auto;
    box-shadow: 0 4px 20px rgba(0,0,0,0.6); display: none;
  `;
  document.body.appendChild(panel);
  panelEl = panel;

  const styleEl = document.createElement("style");
  // Explicit text-transform:none on every panel class so host CSS
  // (Bluesky's shell applies uppercase to button{}, which leaked
  // into our buttons post-rename and made everything SHOUT) can't
  // override the intended casing.
  styleEl.textContent = `
    #doxyedit-autofill-panel, #doxyedit-autofill-panel * {
      text-transform: none;
    }
    .doxyedit-btn { background:#222; color:#eee; border:1px solid #444; padding:6px 8px;
                 cursor:pointer; font:inherit; text-align:left; border-radius:3px;
                 margin-top:2px; width:100%; box-sizing:border-box;
                 text-transform: none; }
    .doxyedit-btn:hover { background:#333; border-color:#ff6b6b; }
    .doxyedit-btn.primary { border-color:#ff6b6b; background:#221818; }
    .doxyedit-section { color:#ff6b6b; font-size:10px; letter-spacing:0.1em;
                     margin:8px 0 2px 0; text-transform:uppercase; }
    .doxyedit-source { color:#888; font-size:10px; margin-top:4px; }
    .doxyedit-source .dot { display:inline-block; width:8px; height:8px;
                         border-radius:4px; margin-right:4px; vertical-align:middle; }
  `;
  document.head.appendChild(styleEl);

  const fab = document.createElement("button");
  fab.id = "bridge-fab";
  fab.title = "drag to reposition · click to toggle panel · double-click to reset";
  fab.style.cssText = `
    position: fixed; bottom: 20px; right: 20px; z-index: 2147483646;
    background: #ff6b6b; color: #111; border: none; border-radius: 16px;
    padding: 6px 12px; font-family: monospace; font-weight: bold; cursor: grab;
    box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    user-select: none; touch-action: none;
    min-width: 84px; min-height: 28px; font-size: 12px;
    display: inline-flex; align-items: center; justify-content: center;
    white-space: nowrap;
  `;
  // Click toggles the panel, drag moves the FAB. Distinguish between
  // the two by tracking total mouse travel between down and up; a
  // click that moved less than DRAG_THRESHOLD px counts as a tap.
  const DRAG_THRESHOLD = 4;
  let dragState = null;
  fab.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    fab.setPointerCapture(ev.pointerId);
    const rect = fab.getBoundingClientRect();
    dragState = {
      startX: ev.clientX, startY: ev.clientY,
      offsetX: ev.clientX - rect.left, offsetY: ev.clientY - rect.top,
      moved: 0,
    };
    fab.style.cursor = "grabbing";
  });
  fab.addEventListener("pointermove", (ev) => {
    if (!dragState) return;
    dragState.moved = Math.max(dragState.moved,
      Math.hypot(ev.clientX - dragState.startX, ev.clientY - dragState.startY));
    if (dragState.moved >= DRAG_THRESHOLD) {
      applyFabPosition(
        ev.clientX - dragState.offsetX, ev.clientY - dragState.offsetY);
    }
  });
  fab.addEventListener("pointerup", (ev) => {
    if (!dragState) return;
    const wasDrag = dragState.moved >= DRAG_THRESHOLD;
    if (wasDrag) {
      // Persist the new position. Parse from the computed style so
      // we save the clamped value, not the raw cursor location.
      const left = parseFloat(fab.style.left) || 0;
      const top = parseFloat(fab.style.top) || 0;
      saveFabPosition({left, top});
    } else {
      // Tap - toggle the panel.
      panelEl.style.display = panelEl.style.display === "none" ? "block" : "none";
      // Reposition the panel now that it's visible (offsetHeight
      // read when hidden was 0, leading to a stale flip decision).
      if (panelEl.style.display !== "none") {
        const left = parseFloat(fab.style.left);
        const top = parseFloat(fab.style.top);
        if (!isNaN(left) && !isNaN(top)) applyFabPosition(left, top);
      }
    }
    fab.releasePointerCapture(ev.pointerId);
    fab.style.cursor = "grab";
    dragState = null;
  });
  // Double-click to reset to bottom-right.
  fab.addEventListener("dblclick", (ev) => {
    ev.preventDefault();
    try { localStorage.removeItem(FAB_POSITION_STORAGE); } catch (e) {}
    fab.style.left = "auto";
    fab.style.top = "auto";
    fab.style.right = "20px";
    fab.style.bottom = "20px";
    if (panelEl) {
      panelEl.style.left = "auto";
      panelEl.style.top = "auto";
      panelEl.style.right = "20px";
      panelEl.style.bottom = "60px";
    }
  });
  document.body.appendChild(fab);
  fabEl = fab;
}

function sourceDotColor(source) {
  if (source === "cdp") return "#6bff6b";       // bright green - live
  if (source === "http") return "#ffd76b";      // amber - periodic poll
  if (source === "clipboard") return "#6bbcff"; // blue - manual
  return "#888";                                // gray - fallback
}

function updateFab() {
  if (!fabEl) return;
  const name = (currentData && currentData.displayName) || "bridge";
  fabEl.innerHTML = `<span style="display:inline-block;width:8px;height:8px;` +
    `border-radius:4px;background:${sourceDotColor(currentSource)};` +
    `margin-right:6px;vertical-align:middle;"></span>${name}`;
}

// Hostname -> list of substring tags. A post key matches the
// current host when its lowercase form contains any of the tags.
// Unknown hosts fall through to "show all keys" so a niche domain
// still gets the full post list rather than a silent empty panel.
const HOST_POST_TAGS = {
  "bsky.app": ["bluesky", "bsky"],
  "x.com": ["twitter", "_x_", "x_"],
  "twitter.com": ["twitter"],
  "threads.net": ["threads"],
  "reddit.com": ["reddit"],
  "old.reddit.com": ["reddit"],
  "ko-fi.com": ["kofi", "ko-fi"],
  "newgrounds.com": ["newgrounds"],
  "itch.io": ["itch"],
  "gamejolt.com": ["gamejolt"],
  "indiedb.com": ["indiedb"],
  "buttondown.com": ["newsletter", "buttondown"],
  "lemmasoft.renai.us": ["lemma"],
};

function currentHostTags() {
  const host = (location.host || "").toLowerCase();
  // Any mastodon instance matches 'mastodon'. Handles custom
  // mastodon hosts like mastodon.gamedev.place.
  if (host.includes("mastodon")) return ["mastodon"];
  for (const h in HOST_POST_TAGS) {
    if (host === h || host.endsWith("." + h)) return HOST_POST_TAGS[h];
  }
  return null;
}

function filterPostKeysForHost(keys) {
  const tags = currentHostTags();
  if (!tags) return keys;
  return keys.filter((k) => {
    const low = k.toLowerCase();
    return tags.some((t) => low.includes(t));
  });
}

function rebuildPanel() {
  if (!panelEl) return;
  const d = currentData;
  const allPostKeys = Object.keys(d.posts || {});
  const postKeys = filterPostKeysForHost(allPostKeys);
  const html = [
    `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">`,
    `  <b style="color:#ff6b6b;">${d.displayName || "bridge"} autofill</b>`,
    `  <button class="doxyedit-close" style="background:transparent;border:none;color:#888;cursor:pointer;font-size:16px;">×</button>`,
    `</div>`,
    `<div class="doxyedit-source"><span class="dot" style="background:${sourceDotColor(currentSource)};"></span>source: ${currentSource}</div>`,
    // One-click post button appears only on hosts with known
    // submit-button selectors + a matching post key in the payload.
    // Everywhere else it stays hidden so the user isn't promised a
    // flow we can't actually deliver.
    (() => {
      const k = currentHostPostKey();
      const sels = postNowSelectorsForHost();
      if (!k || !sels || !d.posts || !d.posts[k]) return "";
      return `<button class="doxyedit-btn primary doxyedit-post-now" ` +
             `style="background:#1f3a1f;border-color:#6bff6b;">` +
             `🚀 POST NOW to ${k}` +
             `</button>`;
    })(),
    `<button class="doxyedit-btn primary doxyedit-clipboard">📋 paste from DoxyEdit</button>`,
    // Asset buttons auto-attach in one click when DoxyEdit has
    // pushed composer_post.asset_ids. Falls through to the manual
    // pick + strategy buttons when no assets were pushed.
    (d.assets && d.assets.length)
      ? `<div class="doxyedit-section">images (1-click attach)</div>` +
        d.assets.map((a, i) => {
          const thumbUrl = _assetThumbCache[a.id];
          const hasThumb = thumbUrl && thumbUrl !== "loading" && thumbUrl !== "error";
          const thumbHtml = hasThumb
            ? `<img src="${thumbUrl}" style="width:40px;height:40px;object-fit:cover;border-radius:3px;margin-right:6px;vertical-align:middle;flex-shrink:0;">`
            : `<span style="width:40px;height:40px;display:inline-block;background:#333;border-radius:3px;margin-right:6px;vertical-align:middle;text-align:center;line-height:40px;flex-shrink:0;">📎</span>`;
          return `<button class="doxyedit-btn primary doxyedit-asset" data-idx="${i}" style="display:flex;align-items:center;">${thumbHtml}<span>${a.name || a.id}</span></button>`;
        }).join("\n")
      : "",
    `<div class="doxyedit-section">image injection (manual)</div>`,
    `<button class="doxyedit-btn doxyedit-pick">📁 pick local image instead</button>`,
    `<div id="doxyedit-picked-name" style="font-size:10px;color:#aaa;margin:2px 0 4px 2px;">(no file picked)</div>`,
    `<div id="doxyedit-drag-thumb-holder" style="margin:2px 0;"></div>`,
    `<button class="doxyedit-btn doxyedit-s1">1. set input[type=file].files</button>`,
    `<button class="doxyedit-btn doxyedit-s2">2. paste into focused field</button>`,
    `<button class="doxyedit-btn doxyedit-s3">3. drop on focused element</button>`,
    `<button class="doxyedit-btn doxyedit-s4">4. click image btn + set input</button>`,
    `<div style="font-size:10px;color:#aaa;margin-top:4px;">5. drag the thumb above onto the compose drop zone</div>`,
    `<div id="doxyedit-upload-status" style="font-size:10px;margin-top:4px;min-height:14px;"></div>`,
    `<div class="doxyedit-section">identity</div>`,
    `<button class="doxyedit-btn" data-fill="displayName">display name</button>`,
    `<button class="doxyedit-btn" data-fill="handle">handle</button>`,
    `<button class="doxyedit-btn" data-fill="oneLine">one-liner</button>`,
    `<button class="doxyedit-btn" data-fill="bioShort">short bio</button>`,
    `<button class="doxyedit-btn" data-fill="bioMedium">medium bio</button>`,
    `<button class="doxyedit-btn" data-fill="bioLong">long bio</button>`,
    postKeys.length
      ? `<div class="doxyedit-section">posts for ${location.host}</div>`
      : (allPostKeys.length
          ? `<div class="doxyedit-source" style="margin-top:6px;">no posts tagged for ${location.host} - ${allPostKeys.length} post(s) hidden for other platforms</div>`
          : ""),
    ...postKeys.map(k => {
      const v = d.posts[k];
      const label = typeof v === "object"
        ? `${k} (title+body)` : `${k}`;
      return `<button class="doxyedit-btn" data-post="${k}">${label}</button>`;
    }),
    // Recent POST NOW attempts. Collapsed by default; click the
    // header to expand. Survives browser restart + tab reload via
    // localStorage so the user can come back and see what landed
    // where, including UNVERIFIED entries that need manual check.
    (() => {
      const h = _postHistoryLoad();
      if (!h.length) return "";
      // Attach a retry affordance to any entry that didn't come back
      // verified. Clicking "retry" re-runs postNowOnCurrentPlatform
      // for the same platformKey - only works on the original host
      // (since that's where POST NOW knows how to target), but it
      // saves the user from having to re-open the panel + click
      // again on the main button.
      const rows = h.slice().reverse().slice(0, POST_HISTORY_MAX).map((e) => {
        const when = _formatPostAgo(e.t);
        const color = e.outcome === "verified" ? "#6bff6b"
                    : e.outcome === "unverified" ? "#ffd76b"
                    : e.outcome === "skipped" ? "#888"
                    : "#ff6b6b";
        const note = e.note ? ` <span style="color:#888;">(${e.note})</span>` : "";
        const retry = (e.outcome !== "verified" && e.platformKey)
          ? ` <a href="#" class="doxyedit-history-retry" data-plat="${e.platformKey}" `
          + `style="color:#6bbcff;text-decoration:underline;">retry</a>`
          : "";
        return `<div style="font-size:10px;color:${color};padding:1px 0;">`
             + `${when} - ${e.platformKey} ${e.outcome}${note}${retry}`
             + `</div>`;
      }).join("");
      return `<details style="margin-top:4px;">`
           + `<summary class="doxyedit-section" style="cursor:pointer;">recent posts (${h.length})</summary>`
           + `<div style="padding:2px 4px;">${rows}</div>`
           + `</details>`;
    })(),
    `<div style="margin-top:8px;color:#888;font-size:10px;line-height:1.45;">`,
    `tip: click into the target field first, then click a button.<br>`,
    `<kbd>Alt+P</kbd> panel · <kbd>Alt+N</kbd> name · <kbd>Alt+B</kbd> short bio · <kbd>Alt+V</kbd> paste<br>`,
    `source: <span style="color:#6bff6b;">●</span> cdp live · <span style="color:#ffd76b;">●</span> http poll · <span style="color:#6bbcff;">●</span> clipboard · <span style="color:#888;">●</span> fallback`,
    `</div>`,
  ].join("\n");
  panelEl.innerHTML = html;

  panelEl.querySelector(".doxyedit-close").addEventListener("click", () => {
    panelEl.style.display = "none";
  });
  panelEl.querySelector(".doxyedit-clipboard").addEventListener("click", pasteFromClipboard);
  // One-click post button: fill image + fill caption + click submit.
  // Debounce so a second click while a post is mid-flight is ignored.
  const postNowBtn = panelEl.querySelector(".doxyedit-post-now");
  if (postNowBtn) {
    let _postInFlight = false;
    postNowBtn.addEventListener("click", async () => {
      if (_postInFlight) {
        setUploadStatus("post in flight, ignoring duplicate click", false);
        return;
      }
      _postInFlight = true;
      postNowBtn.disabled = true;
      try {
        await postNowOnCurrentPlatform();
      } finally {
        _postInFlight = false;
        postNowBtn.disabled = false;
      }
    });
  }
  // Retry links on history rows that failed or came back unverified.
  // Each re-runs postNowOnCurrentPlatform only if the current host
  // + platform key still match what the history row targeted -
  // retrying a Bluesky row while on X isn't helpful.
  panelEl.querySelectorAll(".doxyedit-history-retry").forEach((link) => {
    link.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const histPlat = link.dataset.plat || "";
      const currentPlat = currentHostPostKey() || "";
      if (currentPlat !== histPlat) {
        setUploadStatus(
          `retry skipped: on ${location.host} but row targets ${histPlat}`,
          false);
        return;
      }
      setUploadStatus(`retrying post for ${histPlat}...`, true);
      try { await postNowOnCurrentPlatform(); }
      catch (e) { logToBridge("error", "retry failed", String(e)); }
    });
  });
  // Pushed-asset buttons - one-click attach, no OS picker. The
  // cascade inside loadAssetFromBridge tries v4 -> v5 -> v6 fetch
  // paths automatically so there's no per-variant button UI.
  panelEl.querySelectorAll(".doxyedit-asset").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      const asset = (currentData.assets || [])[idx];
      if (asset) loadAssetFromBridge(asset);
    });
  });
  // Kick off thumbnail preloads for any assets we haven't cached
  // yet. When each lands we re-render the panel so the placeholder
  // swaps to the real <img>.
  preloadAssetThumbs(currentData.assets || []);
  const pickBtn = panelEl.querySelector(".doxyedit-pick");
  if (pickBtn) pickBtn.addEventListener("click", triggerFilePick);
  const s1 = panelEl.querySelector(".doxyedit-s1");
  if (s1) s1.addEventListener("click", strategyFileInput);
  const s2 = panelEl.querySelector(".doxyedit-s2");
  if (s2) s2.addEventListener("click", strategyPaste);
  const s3 = panelEl.querySelector(".doxyedit-s3");
  if (s3) s3.addEventListener("click", strategyDrop);
  const s4 = panelEl.querySelector(".doxyedit-s4");
  if (s4) s4.addEventListener("click", strategyClickThenInput);
  _uploadStatusEl = panelEl.querySelector("#doxyedit-upload-status");
  // Re-render the picked badge + drag thumb from cached state after
  // a rebuild (e.g. after a CDP push repaints the panel).
  refreshPickedBadge();
  renderDragThumb();
  panelEl.querySelectorAll(".doxyedit-btn[data-fill]").forEach(btn => {
    btn.addEventListener("click", () => {
      fillFocusedField(currentData[btn.dataset.fill] || "");
    });
  });
  panelEl.querySelectorAll(".doxyedit-btn[data-post]").forEach(btn => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.post;
      const payload = currentData.posts[key];
      if (typeof payload === "object" && payload.title !== undefined) {
        fillPostPayload(Object.assign({}, payload, { platform: key }));
      } else if (typeof payload === "string") {
        fillFocusedField(payload);
      }
    });
  });
}

// ── KEYBOARD SHORTCUTS ─────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (!e.altKey) return;
  const key = e.key.toLowerCase();
  if (key === "p") {
    e.preventDefault();
    if (panelEl) panelEl.style.display = panelEl.style.display === "none" ? "block" : "none";
  } else if (key === "b") {
    e.preventDefault();
    fillFocusedField(currentData.bioShort);
  } else if (key === "n") {
    e.preventDefault();
    fillFocusedField(currentData.displayName);
  } else if (key === "v") {
    e.preventDefault();
    pasteFromClipboard();
  }
});

// ── INIT ───────────────────────────────────────────────────────────────────
function init() {
  buildPanelScaffold();
  applyData(DOXYEDIT_FALLBACK, "fallback");
  tryCdpInjection();
  tryHttpBridge();
  // Retry any feedback events that failed to reach DoxyEdit last
  // time (bridge was down, DoxyEdit restarting, etc.). Deferred a
  // tick so the HTTP probe has a chance to discover the port first.
  setTimeout(_flushFeedbackQueue, 1200);
  // Restore saved FAB position (user may have moved it last session).
  const saved = loadFabPosition();
  if (saved) {
    // Defer one tick so fabEl.offsetHeight reports a real value for
    // the panel's above/below flip calc inside applyFabPosition.
    setTimeout(() => applyFabPosition(saved.left, saved.top), 0);
  }
}

if (document.body) init();
else window.addEventListener("DOMContentLoaded", init);

// SPA navigation: Bluesky / X / Reddit / Threads route between
// feed / compose / profile without a full page reload, so
// location.href drifts while our panel keeps showing context from
// the page we loaded on. Poll every 2s and re-run tryCdpInjection +
// tryHttpBridge so the panel picks up post changes after a route
// change. Focus listener covers the cross-tab case where the user
// switches back with DoxyEdit having pushed fresh data. Borrowed
// verbatim from the autofill reference project's SPA detector.
let _lastObservedURL = location.href;
setInterval(() => {
  if (location.href !== _lastObservedURL) {
    _lastObservedURL = location.href;
    try { tryCdpInjection(); } catch (e) {}
    try { _flushFeedbackQueue(); } catch (e) {}
  }
}, 2000);
window.addEventListener("focus", () => {
  try { tryCdpInjection(); } catch (e) {}
});
