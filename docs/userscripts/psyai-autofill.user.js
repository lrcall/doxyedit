// ==UserScript==
// @name         psyai autofill (DoxyEdit bridge)
// @namespace    https://psyai.game
// @version      2.1
// @description  Auto-fills bio / display name / post content on social platforms. Reads live data from DoxyEdit via CDP-injected globals, a local HTTP bridge, or the OS clipboard — with the old hardcoded library as last-resort fallback.
// @author       psyai
// @updateURL    https://raw.githubusercontent.com/lrcall/doxyedit/main/docs/userscripts/psyai-autofill.user.js
// @downloadURL  https://raw.githubusercontent.com/lrcall/doxyedit/main/docs/userscripts/psyai-autofill.user.js
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
//   A. window.__psyai_data injected via CDP (preferred — live)
//   B. HTTP bridge fetched from 127.0.0.1:{PORT}/psyai.json
//   C. "paste from clipboard" button (manual, always available)
// If none respond, the hardcoded PSYAI_FALLBACK below is used.

const HTTP_BRIDGE_PORTS = [8910, 8911, 8912];  // DoxyEdit tries first free
const HTTP_BRIDGE_POLL_MS = 8000;              // refetch every 8s if active
const PSYAI_MARKER = "_psyai_panel_v1";        // matches psyai_bridge.py

// ── HARDCODED FALLBACK ─────────────────────────────────────────────────────
// Used only when no DoxyEdit transport is live. Lets the script work
// standalone on a machine that doesn't have DoxyEdit running.
const PSYAI_FALLBACK = {
  handle: "psyai_game",
  displayName: "psyai",
  taglineShort: "a retro sci-fi point-and-click.",
  oneLine: "retro sci-fi point-and-click VN. wishlist on steam ↓",
  bioShort: "psyai — retro sci-fi point-and-click VN. dialogue trees, crt glow, bad decisions. demo at steam next fest · june 2026.",
  bioMedium: "psyai: a retro sci-fi point-and-click VN.\ndialogue trees, crt glow, bad decisions.\nren'py · hand-drawn pixel · shipping 2026.\ndemo at steam next fest.",
  bioLong: "psyai is a retro sci-fi point-and-click visual novel.\na diagnostic. a unit you shouldn't have kept talking to. a city that was never supposed to hold this many ghosts.\n\nchoice-driven dialogue trees, hand-drawn pixel backgrounds, a synth score, and enough arcade machines to make the long conversations survivable.\n\ncurrently in development — playable at Steam Next Fest, June 2026.",
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
let currentData = PSYAI_FALLBACK;
let currentSource = "fallback";

function unwrapPayload(obj) {
  // Accept both plain-dict and marker-wrapped payloads.
  if (obj && obj[PSYAI_MARKER] === true && obj.payload) return obj.payload;
  return obj;
}

function applyData(data, source) {
  if (!data || typeof data !== "object") return false;
  currentData = Object.assign({}, PSYAI_FALLBACK, data);
  if (!currentData.posts) currentData.posts = {};
  currentSource = source;
  rebuildPanel();
  updateFab();
  return true;
}

// ── TRANSPORT A: window.__psyai_data (CDP push) ────────────────────────────
function tryCdpInjection() {
  if (window.__psyai_data) {
    const payload = unwrapPayload(window.__psyai_data);
    applyData(payload, "cdp");
  }
  window.addEventListener("psyai-data-updated", (ev) => {
    const payload = unwrapPayload(ev.detail || window.__psyai_data);
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
  // Continuous poll on whichever port answered.
  if (httpPollTimer === null) {
    httpPollTimer = setInterval(() => {
      if (httpBridgePort) fetchFromPort(httpBridgePort, false);
    }, HTTP_BRIDGE_POLL_MS);
  }
}

function fetchFromPort(port, isProbe) {
  if (typeof GM_xmlhttpRequest !== "function") return;
  GM_xmlhttpRequest({
    method: "GET",
    url: `http://127.0.0.1:${port}/psyai.json`,
    timeout: 1500,
    onload: (resp) => {
      if (resp.status !== 200) return;
      try {
        const parsed = JSON.parse(resp.responseText);
        if (parsed[PSYAI_MARKER] !== true) return;
        const payload = unwrapPayload(parsed);
        // CDP-injected data wins over HTTP (CDP is always more live).
        if (currentSource === "cdp") return;
        if (isProbe) httpBridgePort = port;
        applyData(payload, "http");
      } catch (e) { /* not valid JSON, ignore */ }
    },
    onerror: () => { /* bridge not up on this port, silent */ },
    ontimeout: () => { /* same */ }
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
    if (parsed[PSYAI_MARKER] !== true) {
      alert("Clipboard JSON doesn't carry the DoxyEdit marker.");
      return;
    }
    const payload = unwrapPayload(parsed);
    const kind = parsed.kind || "full";
    if (kind === "full") {
      applyData(payload, "clipboard");
      alert(`DoxyEdit data loaded (${Object.keys(payload.posts || {}).length} posts, ${currentData.displayName}).`);
    } else if (kind === "post") {
      // Single-post clipboard payload — fill current field(s) directly.
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
    const titleField = document.querySelector(
      'textarea[placeholder*="Title" i], input[placeholder*="Title" i], textarea[name="title"]');
    if (titleField && payload.title) setReactValue(titleField, payload.title);
    else if (payload.title) copyToClipboard(payload.title);
    const active = document.activeElement;
    if ((active.tagName === "TEXTAREA" || active.isContentEditable) && payload.body) {
      fillFocusedField(payload.body);
    } else if (payload.body) {
      copyToClipboard(payload.body);
      alert("Body copied to clipboard — paste into body field.");
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
    alert("Field is not directly fillable — text copied to clipboard. Paste manually.");
  }
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
const FAB_POSITION_STORAGE = "psyai_fab_position_v1";

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
  catch (e) { /* quota exceeded — ignore */ }
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
  if (document.getElementById("psyai-autofill-panel")) return;
  const panel = document.createElement("div");
  panel.id = "psyai-autofill-panel";
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
  styleEl.textContent = `
    .psyai-btn { background:#222; color:#eee; border:1px solid #444; padding:6px 8px;
                 cursor:pointer; font:inherit; text-align:left; border-radius:3px;
                 margin-top:2px; width:100%; box-sizing:border-box; }
    .psyai-btn:hover { background:#333; border-color:#ff6b6b; }
    .psyai-btn.primary { border-color:#ff6b6b; background:#221818; }
    .psyai-section { color:#ff6b6b; font-size:10px; letter-spacing:0.1em;
                     margin:8px 0 2px 0; text-transform:uppercase; }
    .psyai-source { color:#888; font-size:10px; margin-top:4px; }
    .psyai-source .dot { display:inline-block; width:8px; height:8px;
                         border-radius:4px; margin-right:4px; vertical-align:middle; }
  `;
  document.head.appendChild(styleEl);

  const fab = document.createElement("button");
  fab.id = "psyai-fab";
  fab.title = "drag to reposition · click to toggle panel · double-click to reset";
  fab.style.cssText = `
    position: fixed; bottom: 20px; right: 20px; z-index: 2147483646;
    background: #ff6b6b; color: #111; border: none; border-radius: 20px;
    padding: 8px 14px; font-family: monospace; font-weight: bold; cursor: grab;
    box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    user-select: none; touch-action: none;
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
      // Tap — toggle the panel.
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
  if (source === "cdp") return "#6bff6b";       // bright green — live
  if (source === "http") return "#ffd76b";      // amber — periodic poll
  if (source === "clipboard") return "#6bbcff"; // blue — manual
  return "#888";                                // gray — fallback
}

function updateFab() {
  if (!fabEl) return;
  const name = (currentData && currentData.displayName) || "psyai";
  fabEl.innerHTML = `<span style="display:inline-block;width:8px;height:8px;` +
    `border-radius:4px;background:${sourceDotColor(currentSource)};` +
    `margin-right:6px;vertical-align:middle;"></span>${name}`;
}

function rebuildPanel() {
  if (!panelEl) return;
  const d = currentData;
  const postKeys = Object.keys(d.posts || {});
  const html = [
    `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">`,
    `  <b style="color:#ff6b6b;">${d.displayName || "psyai"} autofill</b>`,
    `  <button class="psyai-close" style="background:transparent;border:none;color:#888;cursor:pointer;font-size:16px;">×</button>`,
    `</div>`,
    `<div class="psyai-source"><span class="dot" style="background:${sourceDotColor(currentSource)};"></span>source: ${currentSource}</div>`,
    `<button class="psyai-btn primary psyai-clipboard">📋 paste from DoxyEdit</button>`,
    `<div class="psyai-section">identity</div>`,
    `<button class="psyai-btn" data-fill="displayName">display name</button>`,
    `<button class="psyai-btn" data-fill="handle">handle</button>`,
    `<button class="psyai-btn" data-fill="oneLine">one-liner</button>`,
    `<button class="psyai-btn" data-fill="bioShort">short bio</button>`,
    `<button class="psyai-btn" data-fill="bioMedium">medium bio</button>`,
    `<button class="psyai-btn" data-fill="bioLong">long bio</button>`,
    postKeys.length ? `<div class="psyai-section">posts</div>` : "",
    ...postKeys.map(k => {
      const v = d.posts[k];
      const label = typeof v === "object"
        ? `${k} (title+body)` : `${k}`;
      return `<button class="psyai-btn" data-post="${k}">${label}</button>`;
    }),
    `<div style="margin-top:8px;color:#888;font-size:10px;">`,
    `tip: click into the target field first, then click a button.<br>`,
    `<kbd>Alt+P</kbd> panel · <kbd>Alt+B</kbd> short bio · <kbd>Alt+V</kbd> paste from DoxyEdit`,
    `</div>`,
  ].join("\n");
  panelEl.innerHTML = html;

  panelEl.querySelector(".psyai-close").addEventListener("click", () => {
    panelEl.style.display = "none";
  });
  panelEl.querySelector(".psyai-clipboard").addEventListener("click", pasteFromClipboard);
  panelEl.querySelectorAll(".psyai-btn[data-fill]").forEach(btn => {
    btn.addEventListener("click", () => {
      fillFocusedField(currentData[btn.dataset.fill] || "");
    });
  });
  panelEl.querySelectorAll(".psyai-btn[data-post]").forEach(btn => {
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
  applyData(PSYAI_FALLBACK, "fallback");
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
