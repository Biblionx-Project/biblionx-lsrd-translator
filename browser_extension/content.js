/**
 * Biblionx LSRD content script.
 * Floating button + accessible sign player rendered inside a closed Shadow DOM.
 * Network calls are proxied through the background service worker.
 */
(() => {
  if (window.__biblionxLoaded) return;
  window.__biblionxLoaded = true;

  const BASE_STEP_MS = 1500;
  const SPEEDS = { min: 0.5, max: 2, step: 0.25 };
  const EXACT_METHODS = ["exact", "direct", "dictionary", "synonym", "lemma"];
  const ICONS = {
    hand: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 12V6a1.5 1.5 0 0 1 3 0v5m0-6.5a1.5 1.5 0 0 1 3 0V11m0-5a1.5 1.5 0 0 1 3 0v6m0-3a1.5 1.5 0 0 1 3 0v5a7 7 0 0 1-7 7h-1a7 7 0 0 1-5.5-2.7L4 15.5a1.6 1.6 0 0 1 2.4-2L7 14"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l11-6.5z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6.5" y="5" width="4" height="14" rx="1"/><rect x="13.5" y="5" width="4" height="14" rx="1"/></svg>',
    prev: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h2v14H6zM19 5.5v13L9.5 12z"/></svg>',
    next: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 5h2v14h-2zM5 5.5v13L14.5 12z"/></svg>',
    alert: '<svg class="err-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/></svg>',
  };

  let host = null, root = null, shadow = null, cssText = null;
  let fab = null, scrim = null, dialog = null, lastFocus = null;
  let seq = [], idx = 0, playing = false, timer = null, elapsed = 0, speed = 1, lastText = "";
  let apiBase = "http://127.0.0.1:8000";

  const clamp = (v) => Math.min(SPEEDS.max, Math.max(SPEEDS.min, v));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = () => (typeof chrome !== "undefined" && chrome.storage && chrome.storage.sync) || null;
  const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  async function loadSettings() {
    try {
      const s = await store().get({ apiBase, speed: 1 });
      apiBase = String(s.apiBase).replace(/\/+$/, "");
      speed = clamp(Number(s.speed) || 1);
    } catch (e) { /* keep defaults */ }
  }

  async function ensureHost() {
    if (host && host.isConnected) return;
    if (cssText === null) {
      try { cssText = await (await fetch(chrome.runtime.getURL("styles.css"))).text(); } catch (e) { cssText = ""; }
    }
    host = document.createElement("div");
    host.id = "biblionx-host";
    host.style.cssText = "all:initial;position:absolute;top:0;left:0;z-index:2147483647;";
    shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = cssText;
    root = document.createElement("div");
    root.className = "root";
    shadow.append(style, root);
    document.documentElement.appendChild(host);
    fab = scrim = dialog = null;
  }

  /* ---------- Floating button ---------- */
  async function showFab(x, y, text) {
    await ensureHost();
    removeFab();
    fab = document.createElement("button");
    fab.type = "button";
    fab.className = "fab";
    fab.setAttribute("aria-label", "Translate selection to LSRD");
    fab.innerHTML = `<span class="dot">${ICONS.hand}</span>Translate to LSRD`;
    const maxX = document.documentElement.scrollWidth - 210;
    fab.style.left = `${Math.max(8, Math.min(x + 8, maxX))}px`;
    fab.style.top = `${y + 12}px`;
    fab.addEventListener("mousedown", (e) => { e.preventDefault(); e.stopPropagation(); });
    fab.addEventListener("click", (e) => { e.preventDefault(); removeFab(); translate(text); });
    root.appendChild(fab);
  }
  function removeFab() { if (fab) { fab.remove(); fab = null; } }

  function getActiveElement(rootNode = document) {
    let active = rootNode.activeElement;
    while (active && active.shadowRoot && active.shadowRoot.activeElement) {
      active = active.shadowRoot.activeElement;
    }
    return active;
  }

  function getSelectedTextInfo() {
    const active = getActiveElement();
    if (active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA")) {
      try {
        const start = active.selectionStart;
        const end = active.selectionEnd;
        if (typeof start === "number" && typeof end === "number" && start !== end) {
          const val = active.value;
          if (val) {
            const text = val.substring(Math.min(start, end), Math.max(start, end)).trim();
            if (text) return { text, element: active };
          }
        }
      } catch (e) {
        /* Some input types throw when reading selectionStart/selectionEnd */
      }
    }
    const sel = window.getSelection();
    const text = ((sel ? sel.toString() : "") || "").trim();
    return { text, element: null };
  }

  function getSelectionCoords(element) {
    if (element && typeof element.getBoundingClientRect === "function") {
      const rect = element.getBoundingClientRect();
      return {
        x: rect.left + window.scrollX,
        y: rect.bottom + window.scrollY,
      };
    }
    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0) {
      const range = sel.getRangeAt(0);
      const rects = range.getClientRects();
      if (rects.length > 0) {
        const r = rects[rects.length - 1];
        return {
          x: r.right + window.scrollX,
          y: r.bottom + window.scrollY,
        };
      }
      const r = range.getBoundingClientRect();
      if (r && (r.width > 0 || r.height > 0 || r.top > 0 || r.left > 0)) {
        return {
          x: r.right + window.scrollX,
          y: r.bottom + window.scrollY,
        };
      }
    }
    return { x: 16, y: 16 + window.scrollY };
  }

  function checkSelection(x, y) {
    const info = getSelectedTextInfo();
    if (info.text && info.text.length <= 2000) {
      if (x == null || y == null) {
        const coords = getSelectionCoords(info.element);
        x = coords.x;
        y = coords.y;
      }
      showFab(x, y, info.text);
    } else {
      removeFab();
    }
  }

  document.addEventListener("mouseup", (e) => {
    if (host && e.composedPath().includes(host)) return;
    setTimeout(() => {
      checkSelection(e.pageX, e.pageY);
    }, 0);
  });

  document.addEventListener("keyup", (e) => {
    if (scrim) return;
    if (host && e.composedPath().includes(host)) return;

    const isSelectAll = (e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A");
    const isShiftNav = e.shiftKey && (
      e.key === "ArrowLeft" || e.key === "ArrowRight" ||
      e.key === "ArrowUp" || e.key === "ArrowDown" ||
      e.key === "Home" || e.key === "End"
    );
    const isShiftRelease = e.key === "Shift";

    if (isSelectAll || isShiftNav || isShiftRelease) {
      setTimeout(() => {
        if (!scrim) checkSelection();
      }, 0);
    } else {
      const info = getSelectedTextInfo();
      if (!info.text) removeFab();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && fab) {
      e.preventDefault();
      removeFab();
    }
  });

  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((msg) => {
      if (msg && msg.type === "biblionx:translate" && msg.text) translate(String(msg.text).trim());
    });
  }

  /* ---------- Dialog ---------- */
  async function openDialog() {
    await ensureHost();
    closeDialog(false);
    lastFocus = document.activeElement;
    scrim = document.createElement("div");
    scrim.className = "scrim";
    scrim.innerHTML = `
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="bx-title" aria-describedby="bx-live">
        <header class="bar">
          <span class="logo" aria-hidden="true">${ICONS.hand}</span>
          <h2 class="title" id="bx-title">Biblionx LSRD</h2>
          <button class="icon-btn" id="bx-close" type="button" aria-label="Close player">${ICONS.close}</button>
        </header>
        <div class="content" id="bx-body"></div>
        <div class="sr" id="bx-live" aria-live="polite"></div>
      </div>`;
    dialog = scrim.querySelector(".dialog");
    scrim.addEventListener("mousedown", (e) => { if (e.target === scrim) closeDialog(true); });
    scrim.querySelector("#bx-close").addEventListener("click", () => closeDialog(true));
    scrim.addEventListener("keydown", onKey);
    root.appendChild(scrim);
    dialog.querySelector("#bx-close").focus();
  }

  function closeDialog(restore) {
    stop();
    if (scrim) { scrim.remove(); scrim = null; dialog = null; }
    if (restore && lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) { /* noop */ } }
  }

  const body = () => scrim && scrim.querySelector("#bx-body");

  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeDialog(true); return; }
    if (e.key === "Tab") { trapFocus(e); return; }
    if (!seq.length) return;
    const tag = (e.composedPath()[0] || {}).tagName;
    if (e.key === " " && tag !== "BUTTON" && tag !== "INPUT") { e.preventDefault(); togglePlay(); }
    else if (e.key === "ArrowRight" && tag !== "INPUT") { e.preventDefault(); go(idx + 1); }
    else if (e.key === "ArrowLeft" && tag !== "INPUT") { e.preventDefault(); go(idx - 1); }
  }

  function trapFocus(e) {
    const f = [...dialog.querySelectorAll("button:not([disabled]),input")];
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1], active = shadow.activeElement;
    if (e.shiftKey && (active === first || !dialog.contains(active))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (active === last || !dialog.contains(active))) { e.preventDefault(); first.focus(); }
  }

  /* ---------- States ---------- */
  function renderLoading() {
    body().innerHTML = `<div class="state" role="status"><div class="spinner"></div><p>Translating to LSRD...</p></div>`;
  }
  function renderError(title, detail, retry) {
    body().innerHTML = `<div class="state" role="alert">${ICONS.alert}<h4>${esc(title)}</h4><p>${esc(detail)}</p>
      ${retry ? '<button class="cta" id="bx-retry" type="button">Try again</button>' : ""}</div>`;
    const b = body().querySelector("#bx-retry");
    if (b) { b.addEventListener("click", () => translate(lastText, true)); b.focus(); }
  }

  async function translate(text, reuse) {
    if (!text) return;
    lastText = text;
    stop();
    seq = [];
    await loadSettings();
    if (!reuse || !scrim) await openDialog();
    renderLoading();
    let res;
    try { res = await chrome.runtime.sendMessage({ type: "biblionx:api", text }); }
    catch (e) { res = { ok: false }; }
    if (!scrim) return;
    if (res && res.status === 429) {
      const w = res.retryAfter ? ` Please wait about ${res.retryAfter} seconds.` : "";
      renderError("Too many requests", `The translation service is busy.${w} Try again shortly.`, true);
      return;
    }
    if (!res || !res.ok) {
      renderError("Can't reach the translator", `Make sure the LSRD API is running at ${apiBase} and try again.`, true);
      return;
    }
    const list = res.data && res.data.secuencia_senas;
    if (!Array.isArray(list) || !list.length) {
      renderError("No signs found", "There are no LSRD signs available for the selected text.", false);
      return;
    }
    seq = list; idx = 0; elapsed = 0;
    renderPlayer();
    start();
  }

  /* ---------- Player ---------- */
  function imgUrl(u) {
    if (!u) return "";
    try { return new URL(u, apiBase + "/").href; } catch (e) { return ""; }
  }
  const chipLabel = (s) => (s.es_deletreo ? (s.letra || s.palabra_es || "?") : (s.palabra_es || "?"));
  function isFuzzy(s) {
    const m = String(s.match_method || "").toLowerCase();
    if (!m) return false;
    return !EXACT_METHODS.includes(m);
  }

  function renderPlayer() {
    body().innerHTML = `
      <div class="stage" id="bx-stage"></div>
      <div class="caption"><h3 class="word" id="bx-word"></h3><p class="desc" id="bx-desc"></p></div>
      <div class="progress" role="progressbar" aria-label="Sequence progress" aria-valuemin="0" aria-valuemax="100"><i id="bx-bar"></i></div>
      <div class="controls">
        <button class="btn" id="bx-prev" type="button" aria-label="Previous sign">${ICONS.prev}</button>
        <button class="btn primary" id="bx-play" type="button" aria-label="Pause">${ICONS.pause}</button>
        <button class="btn" id="bx-next" type="button" aria-label="Next sign">${ICONS.next}</button>
        <label class="speed">Speed
          <input id="bx-speed" type="range" min="${SPEEDS.min}" max="${SPEEDS.max}" step="${SPEEDS.step}" value="${speed}" aria-label="Playback speed">
          <output id="bx-speed-out">${speed}x</output></label>
      </div>
      <div class="timeline" id="bx-timeline" role="list" aria-label="Sign timeline"></div>`;
    const q = (id) => body().querySelector(id);
    q("#bx-prev").addEventListener("click", () => go(idx - 1));
    q("#bx-next").addEventListener("click", () => go(idx + 1));
    q("#bx-play").addEventListener("click", togglePlay);
    q("#bx-speed").addEventListener("input", (e) => { speed = clamp(Number(e.target.value)); q("#bx-speed-out").textContent = `${speed}x`; });
    q("#bx-speed").addEventListener("change", () => { try { store().set({ speed }); } catch (e) { /* noop */ } });
    const tl = q("#bx-timeline");
    seq.forEach((s, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip" + (s.es_deletreo ? " spell" : "");
      b.setAttribute("role", "listitem");
      const tag = s.es_deletreo ? '<span class="tag">spelled</span>' : isFuzzy(s) ? '<span class="tag ai">AI</span>' : "";
      b.innerHTML = `${esc(chipLabel(s))}${tag}`;
      b.setAttribute("aria-label", `Sign ${i + 1} of ${seq.length}: ${chipLabel(s)}${s.es_deletreo ? ", fingerspelled" : ""}`);
      b.addEventListener("click", () => go(i));
      tl.appendChild(b);
    });
    showSign();
    q("#bx-play").focus();
  }

  // Text card shown when the sign image is unavailable: word + Spanish movement description.
  function textCard(s, letter) {
    const desc = s.descripcion_sena ? `<p class="tc-desc">${esc(s.descripcion_sena)}</p>` : "";
    return `<div class="textcard"><div class="letter" aria-hidden="true">${esc(letter)}</div>`
      + `<strong class="tc-word">${esc(chipLabel(s))}</strong>${desc}</div>`;
  }

  function showSign() {
    if (!scrim || !seq[idx] || !body().querySelector("#bx-stage")) return;
    const s = seq[idx], q = (id) => body().querySelector(id);
    const stage = q("#bx-stage");
    const badges = [];
    if (s.es_deletreo) badges.push('<span class="badge spell">Fingerspelled</span>');
    else if (isFuzzy(s)) {
      const c = typeof s.confidence === "number" ? ` ${Math.round(s.confidence * 100)}%` : "";
      badges.push(`<span class="badge ai">AI match${c}</span>`);
    }
    const missing = s.image_available === false || !s.url_imagen;
    const url = missing ? "" : imgUrl(s.url_imagen);
    const letter = (chipLabel(s) || "?").charAt(0).toUpperCase();
    stage.innerHTML = (url ? `<img src="${esc(url)}" alt="">` : textCard(s, letter))
      + `<div class="badges">${badges.join("")}</div><div class="counter">${idx + 1} / ${seq.length}</div>`;
    const img = stage.querySelector("img");
    if (img) {
      img.alt = `LSRD sign for ${chipLabel(s)}`;
      img.addEventListener("error", () => {
        const t = document.createElement("div");
        t.innerHTML = textCard(s, letter);
        img.replaceWith(t.firstChild);
      });
    }
    q("#bx-word").textContent = s.es_deletreo ? `${s.letra || ""} (letter)` : (s.palabra_es || "");
    q("#bx-desc").textContent = s.descripcion_sena || "";
    body().querySelectorAll(".chip").forEach((c, i) => {
      if (i === idx) {
        c.setAttribute("aria-current", "true");
        c.scrollIntoView({ inline: "center", block: "nearest", behavior: reduced() ? "auto" : "smooth" });
      } else c.removeAttribute("aria-current");
    });
    q("#bx-prev").disabled = idx === 0;
    q("#bx-next").disabled = idx === seq.length - 1;
    const live = scrim.querySelector("#bx-live");
    if (live && !playing) live.textContent = `${chipLabel(s)}, sign ${idx + 1} of ${seq.length}`;
    updateBar();
  }

  function updateBar() {
    if (!scrim || !body()) return;
    const bar = body().querySelector("#bx-bar");
    if (!bar) return;
    const pct = Math.min(100, ((idx + Math.min(1, elapsed / BASE_STEP_MS)) / seq.length) * 100);
    bar.style.width = `${pct}%`;
    bar.parentElement.setAttribute("aria-valuenow", String(Math.round(pct)));
  }

  function go(i) {
    if (i < 0 || i >= seq.length) return;
    idx = i; elapsed = 0;
    showSign();
  }

  function setPlayBtn() {
    const b = body() && body().querySelector("#bx-play");
    if (!b) return;
    b.innerHTML = playing ? ICONS.pause : ICONS.play;
    b.setAttribute("aria-label", playing ? "Pause" : "Play");
  }

  function start() {
    if (timer) clearInterval(timer);
    if (idx >= seq.length - 1 && elapsed >= BASE_STEP_MS) { idx = 0; elapsed = 0; showSign(); }
    playing = true;
    setPlayBtn();
    let last = performance.now();
    timer = setInterval(() => {
      const now = performance.now();
      elapsed += (now - last) * speed;
      last = now;
      if (elapsed >= BASE_STEP_MS) {
        if (idx < seq.length - 1) { idx++; elapsed = 0; showSign(); }
        else { elapsed = BASE_STEP_MS; updateBar(); stop(); return; }
      }
      updateBar();
    }, 40);
  }

  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
    playing = false;
    setPlayBtn();
  }

  function togglePlay() { if (playing) stop(); else start(); }
})();
