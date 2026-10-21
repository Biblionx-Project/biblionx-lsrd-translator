/**
 * Biblionx LSRD content script.
 * Floating button + accessible sign player rendered inside a closed Shadow DOM.
 * Network calls are proxied through the background service worker.
 */
(() => {
  if (window.__biblionxLoaded) return;
  window.__biblionxLoaded = true;

  const BASE_STEP_MS = 1500;
  // Fingerspelled letters stay on screen for a fraction of a lexical sign.
  const SPELL_FACTOR = 0.45;
  const SPEEDS = { min: 0.5, max: 2, step: 0.25 };
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
  let seq = [], groups = [], gof = [], idx = 0, playing = false, timer = null, elapsed = 0, speed = 1, lastText = "";
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

  // Concurrent callers (a triple click fires several mouseup events) share one
  // creation promise; otherwise each would append its own host while the first
  // one is still awaiting styles.css, leaving orphaned floating buttons behind.
  let hostPending = null;
  function ensureHost() {
    if (host && host.isConnected) return Promise.resolve();
    if (!hostPending) hostPending = createHost().finally(() => { hostPending = null; });
    return hostPending;
  }

  async function createHost() {
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
    else if (e.key === "ArrowRight" && tag !== "INPUT") { e.preventDefault(); goGroup(1); }
    else if (e.key === "ArrowLeft" && tag !== "INPUT") { e.preventDefault(); goGroup(-1); }
    else if ((e.key === "Home" || e.key === "End") && tag !== "INPUT") {
      e.preventDefault();
      go(e.key === "Home" ? 0 : groups[groups.length - 1].start);
    }
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
    groupSeq();
    renderPlayer();
    start();
  }

  /* ---------- Player ---------- */
  const imageCache = new Map();
  function loadImage(url) {
    if (!imageCache.has(url)) {
      const p = chrome.runtime.sendMessage({ type: "biblionx:image", url }).then((res) => {
        if (res && res.ok && res.dataUrl) return res.dataUrl;
        throw new Error((res && res.error) || "image unavailable");
      });
      p.catch(() => imageCache.delete(url));
      imageCache.set(url, p);
    }
    return imageCache.get(url);
  }

  function imgUrl(u) {
    if (!u) return "";
    try { return new URL(u, apiBase + "/").href; } catch (e) { return ""; }
  }
  const chipLabel = (s) => (s.es_deletreo ? (s.letra || s.palabra_es || "?") : (s.palabra_es || "?"));
  const upper = (t) => String(t).toLocaleUpperCase("es");

  // One group per lexical sign and one per fingerspelled word. Uses the
  // spelled_word / spelled_index fields when the API sends them; otherwise
  // consecutive es_deletreo items are merged into one word.
  function groupSeq() {
    groups = []; gof = [];
    let cur = null, prev = -1;
    seq.forEach((s, i) => {
      if (!s.es_deletreo) {
        groups.push({ start: i, end: i, spelled: false });
        cur = null; prev = -1; gof.push(groups.length - 1);
        return;
      }
      const si = typeof s.spelled_index === "number" ? s.spelled_index : null;
      const sw = typeof s.spelled_word === "string" && s.spelled_word ? s.spelled_word : "";
      const fresh = !cur || (si !== null && si <= prev) || (sw && cur.word && sw !== cur.word);
      if (fresh) { cur = { start: i, end: i, spelled: true, word: sw }; groups.push(cur); }
      else { cur.end = i; if (!cur.word && sw) cur.word = sw; }
      prev = si !== null ? si : prev + 1;
      gof.push(groups.length - 1);
    });
    groups.forEach((g) => {
      if (!g.spelled) return;
      const n = g.end - g.start + 1;
      let chars = g.word ? Array.from(g.word) : [];
      if (chars.length !== n) chars = seq.slice(g.start, g.end + 1).map((s) => s.letra || "?");
      g.letters = chars.map(upper);
      g.word = upper(g.word || g.letters.join(""));
    });
  }
  const groupName = (g) => (g.spelled ? g.word : chipLabel(seq[g.start]));
  // Time (in speed-scaled ms) the item at index i stays on screen.
  const stepMs = (i) => BASE_STEP_MS * (seq[i] && seq[i].es_deletreo && !reduced() ? SPELL_FACTOR : 1);
  // Badge only the non-deterministic matches. Morphology, phrases and dictionary
  // synonyms are exact lookups of a known form, so they get no badge.
  const MATCH_BADGES = {
    fuzzy: { chip: "approx", label: "Approximate match" },
    ai: { chip: "AI", label: "AI match" },
    curated_synonym: { chip: "syn", label: "Synonym" },
  };
  function matchBadge(s) {
    return MATCH_BADGES[String(s.match_method || "").toLowerCase()] || null;
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
    q("#bx-prev").addEventListener("click", () => goGroup(-1));
    q("#bx-next").addEventListener("click", () => goGroup(1));
    q("#bx-play").addEventListener("click", togglePlay);
    q("#bx-speed").addEventListener("input", (e) => { speed = clamp(Number(e.target.value)); q("#bx-speed-out").textContent = `${speed}x`; });
    q("#bx-speed").addEventListener("change", () => { try { store().set({ speed }); } catch (e) { /* noop */ } });
    const tl = q("#bx-timeline");
    groups.forEach((g, gi) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip" + (g.spelled ? " spell" : "");
      b.setAttribute("role", "listitem");
      const mb = g.spelled ? null : matchBadge(seq[g.start]);
      const tag = g.spelled ? '<span class="tag">spelled</span>' : mb ? `<span class="tag ai">${esc(mb.chip)}</span>` : "";
      b.innerHTML = `${esc(groupName(g))}${tag}`;
      const extra = g.spelled
        ? `, fingerspelled word, ${g.letters.length} letter${g.letters.length === 1 ? "" : "s"}`
        : mb ? `, ${mb.label.toLowerCase()}` : "";
      b.setAttribute("aria-label", `Sign ${gi + 1} of ${groups.length}: ${groupName(g)}${extra}`);
      b.addEventListener("click", () => go(g.start));
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
    const gi = gof[idx], g = groups[gi], pos = idx - g.start;
    const stage = q("#bx-stage");
    const badges = [];
    if (s.es_deletreo) badges.push('<span class="badge spell">Fingerspelled</span>');
    else if (matchBadge(s)) {
      const c = typeof s.confidence === "number" ? ` ${Math.round(s.confidence * 100)}%` : "";
      badges.push(`<span class="badge ai">${esc(matchBadge(s).label)}${c}</span>`);
    }
    const counter = `${gi + 1} / ${groups.length}` + (g.spelled ? ` · letter ${pos + 1} of ${g.letters.length}` : "");
    const missing = s.image_available === false || !s.url_imagen;
    const url = missing ? "" : imgUrl(s.url_imagen);
    const letter = (chipLabel(s) || "?").charAt(0).toUpperCase();
    stage.innerHTML = (url ? `<img alt="">` : textCard(s, letter))
      + `<div class="badges">${badges.join("")}</div><div class="counter">${esc(counter)}</div>`;
    const img = stage.querySelector("img");
    if (img) {
      img.alt = g.spelled ? `LSRD fingerspelling: letter ${chipLabel(s)} of ${g.word}` : `LSRD sign for ${chipLabel(s)}`;
      const fallback = () => {
        if (!img.isConnected) return;
        const t = document.createElement("div");
        t.innerHTML = textCard(s, letter);
        img.replaceWith(t.firstChild);
      };
      img.addEventListener("error", fallback);
      // Images come through the service worker: on HTTPS pages a direct
      // http://127.0.0.1 <img> is blocked as mixed content.
      loadImage(url).then((data) => { if (img.isConnected) img.src = data; }, fallback);
    }
    const word = q("#bx-word");
    if (g.spelled) {
      // Whole word under the hand-shape image, current letter highlighted.
      word.setAttribute("aria-label", `${g.word}, fingerspelled`);
      word.innerHTML = g.letters
        .map((ch, j) => `<span class="sl${j === pos ? " on" : ""}" aria-hidden="true">${esc(ch)}</span>`).join("");
      q("#bx-desc").textContent = `${g.word} — fingerspelled (no sign in the official dictionary)`;
    } else {
      word.removeAttribute("aria-label");
      word.textContent = s.palabra_es || "";
      q("#bx-desc").textContent = s.descripcion_sena || "";
    }
    body().querySelectorAll(".chip").forEach((c, i) => {
      if (i === gi) {
        c.setAttribute("aria-current", "true");
        c.scrollIntoView({ inline: "center", block: "nearest", behavior: reduced() ? "auto" : "smooth" });
      } else c.removeAttribute("aria-current");
    });
    q("#bx-prev").disabled = gi === 0;
    q("#bx-next").disabled = gi === groups.length - 1;
    const live = scrim.querySelector("#bx-live");
    if (live && !playing) {
      live.textContent = g.spelled
        ? `${g.word}, fingerspelled, letter ${chipLabel(s)}, ${pos + 1} of ${g.letters.length}, sign ${gi + 1} of ${groups.length}`
        : `${chipLabel(s)}, sign ${gi + 1} of ${groups.length}`;
    }
    updateBar();
  }

  function updateBar() {
    if (!scrim || !body()) return;
    const bar = body().querySelector("#bx-bar");
    if (!bar) return;
    // Weighted by step duration so a long spelled word does not distort progress.
    let total = 0, before = 0;
    for (let i = 0; i < seq.length; i++) { const d = stepMs(i); total += d; if (i < idx) before += d; }
    const pct = Math.min(100, ((before + Math.min(elapsed, stepMs(idx))) / total) * 100);
    bar.style.width = `${pct}%`;
    bar.parentElement.setAttribute("aria-valuenow", String(Math.round(pct)));
  }

  function go(i) {
    if (i < 0 || i >= seq.length) return;
    idx = i; elapsed = 0;
    showSign();
  }

  // Previous/next move by sign or by whole fingerspelled word, not by letter.
  function goGroup(d) {
    const gi = gof[idx] + d;
    if (gi >= 0 && gi < groups.length) go(groups[gi].start);
  }

  function setPlayBtn() {
    const b = body() && body().querySelector("#bx-play");
    if (!b) return;
    b.innerHTML = playing ? ICONS.pause : ICONS.play;
    b.setAttribute("aria-label", playing ? "Pause" : "Play");
  }

  function start() {
    if (timer) clearInterval(timer);
    if (idx >= seq.length - 1 && elapsed >= stepMs(idx)) { idx = 0; elapsed = 0; showSign(); }
    playing = true;
    setPlayBtn();
    let last = performance.now();
    timer = setInterval(() => {
      const now = performance.now();
      elapsed += (now - last) * speed;
      last = now;
      if (elapsed >= stepMs(idx)) {
        if (idx < seq.length - 1) { idx++; elapsed = 0; showSign(); }
        else { elapsed = stepMs(idx); updateBar(); stop(); return; }
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
