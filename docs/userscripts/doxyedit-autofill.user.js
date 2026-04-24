// ==UserScript==
// @name         doxyedit autofill (DoxyEdit bridge)
// @namespace    https://doxyedit.local
// @version      2.17
// @description  Auto-fills bio / display name / post content on social platforms. Reads live data from DoxyEdit via CDP-injected globals, a local HTTP bridge, or the OS clipboard - with the old hardcoded library as last-resort fallback.
// @author       doxyedit
// @updateURL    http://127.0.0.1:8910/doxyedit-autofill.user.js
// @downloadURL  http://127.0.0.1:8910/doxyedit-autofill.user.js
// @match        https://bsky.app/*
// @match        https://mastodon.gamedev.place/*
// @match        https://x.com/*
// @match        https://twitter.com/*
// @match        https://www.reddit.com/*
// @match        https://reddit.com/*
// @match        https://old.reddit.com/*
// @match        https://gamejolt.com/*
// @match        https://ko-fi.com/*
// @match        https://www.indiedb.com/*
// @match        https://www.newgrounds.com/*
// @match        https://*.newgrounds.com/*
// @match        https://itch.io/*
// @match        https://buttondown.com/*
// @match        https://lemmasoft.renai.us/*
// @grant        GM_setClipboard
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==/UserScript==

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
    // Title field: try a broad selector list so new.reddit.com's
    // Shreddit web components and the old compose form are both
    // covered. Tests each candidate in order; first match wins.
    const TITLE_SELECTORS = [
      'textarea[name="title"]',                      // old.reddit
      'textarea[placeholder*="Title" i]',            // generic
      'input[placeholder*="Title" i]',
      'textarea[aria-label*="title" i]',
      'input[aria-label*="title" i]',
      'shreddit-composer-title-input textarea',      // new.reddit
      'shreddit-composer-title-input input',
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
function loadAssetFromBridge(asset) {
  return new Promise((resolve) => {
    if (!asset || !asset.url) {
      setUploadStatus(
        "✗ asset has no url; was DoxyEdit restarted with the bridge?",
        false);
      resolve(false); return;
    }
    if (typeof GM_xmlhttpRequest !== "function") {
      setUploadStatus(
        "✗ GM_xmlhttpRequest unavailable - userscript missing @grant", false);
      resolve(false);
      return;
    }
    // Show the URL we're about to hit so a 404 / no-route failure
    // points the user straight at the mismatch (wrong port, stale
    // cached URL from a pre-rename DoxyEdit, etc.).
    console.log("[doxyedit] fetching asset:", asset.url);
    setUploadStatus(`fetching ${asset.name} from ${asset.url}`, true);
    GM_xmlhttpRequest({
      method: "GET",
      url: asset.url,
      responseType: "blob",
      timeout: 10000,
      onload: async (resp) => {
        if (resp.status !== 200) {
          setUploadStatus(
            `✗ ${asset.name}: HTTP ${resp.status} from ${asset.url}`,
            false);
          console.log("[doxyedit] fetch failed:", resp.status, asset.url);
          resolve(false);
          return;
        }
        const blob = resp.response;
        if (!blob || !(blob instanceof Blob)) {
          setUploadStatus(
            `✗ ${asset.name}: response not a blob (got ${typeof blob})`,
            false);
          resolve(false);
          return;
        }
        const f = new File(
          [blob], asset.name || "image.png",
          { type: asset.mime || blob.type || "image/png" });
        _pickedFiles = [f];
        refreshPickedBadge();
        renderDragThumb();
        setUploadStatus(`loaded ${f.name} - auto-injecting...`, true);
        await autoInject();
        resolve(true);
      },
      onerror: (err) => {
        setUploadStatus(
          `✗ ${asset.name}: network error on ${asset.url} - bridge down?`,
          false);
        console.log("[doxyedit] fetch network error:", err, asset.url);
        resolve(false);
      },
      ontimeout: () => {
        setUploadStatus(
          `✗ fetch ${asset.name} timed out after 10s`, false);
        resolve(false);
      },
    });
  });
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
    const isComposeTarget = (el) => el && (
      (el.isContentEditable || el.tagName === "TEXTAREA")
      && el.closest(COMPOSE_PASTE_CONTEXT));
    let target = document.activeElement;
    if (!isComposeTarget(target)) {
      target = null;
      for (const ctx of document.querySelectorAll(COMPOSE_PASTE_CONTEXT)) {
        const cand = ctx.querySelector(
          '[contenteditable="true"], [contenteditable=""], textarea');
        if (cand && cand.offsetParent !== null) {
          target = cand;
          break;
        }
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
  if (typeof GM_xmlhttpRequest !== "function") return;
  let anyStarted = false;
  for (const a of assets || []) {
    if (!a || !a.id || !a.url) continue;
    if (_assetThumbCache[a.id]) continue;  // cached, loading, or errored
    _assetThumbCache[a.id] = "loading";
    anyStarted = true;
    GM_xmlhttpRequest({
      method: "GET",
      url: a.url,
      responseType: "blob",
      timeout: 10000,
      onload: (resp) => {
        if (resp.status === 200 && resp.response instanceof Blob) {
          _assetThumbCache[a.id] = URL.createObjectURL(resp.response);
        } else {
          _assetThumbCache[a.id] = "error";
        }
        // Re-render so the new thumb shows up.
        rebuildPanel();
      },
      onerror: () => {
        _assetThumbCache[a.id] = "error";
        rebuildPanel();
      },
      ontimeout: () => {
        _assetThumbCache[a.id] = "error";
        rebuildPanel();
      },
    });
  }
  // Note: rebuildPanel called inside onload; no need to call here.
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
  // Pushed-asset buttons - one-click attach, no OS picker.
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
