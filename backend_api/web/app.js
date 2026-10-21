(function () {
  'use strict';
  var EXAMPLES = [
    'Buenos días, ¿cómo estás?',
    'Yo quiero comer arroz con habichuelas',
    'Mi mamá trabaja en el hospital',
    'Mañana vamos a la playa con la familia',
    'Necesito un abogado',
    'Gracias por tu ayuda'
  ];
  var $ = function (id) { return document.getElementById(id); };
  var input = $('input'), statusEl = $('status'), result = $('result');
  var STEP_MS = 1400;       // base time per lexical sign
  var SPELL_FACTOR = 0.45;  // fingerspelled letters play faster than lexical signs
  var state = { items: [], groups: [], gof: [], idx: 0, playing: false, timer: null, speed: 1 };

  /* ---------- theme ---------- */
  var root = document.documentElement;
  function isDark() {
    var t = root.getAttribute('data-theme');
    return t === 'dark' || (t === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
  }
  try { var saved = localStorage.getItem('biblionx-theme'); if (saved) root.setAttribute('data-theme', saved); } catch (e) {}
  function syncToggle() { $('themeToggle').setAttribute('aria-pressed', String(isDark())); }
  $('themeToggle').addEventListener('click', function () {
    var next = isDark() ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('biblionx-theme', next); } catch (e) {}
    syncToggle();
  });
  syncToggle();

  /* ---------- examples ---------- */
  EXAMPLES.forEach(function (t) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'chip'; b.lang = 'es'; b.textContent = t;
    b.addEventListener('click', function () { input.value = t; updateCount(); translate(); });
    $('chips').appendChild(b);
  });

  function updateCount() { $('count').textContent = input.value.length + '/500'; }
  input.addEventListener('input', updateCount);
  input.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); translate(); }
  });
  $('form').addEventListener('submit', function (e) { e.preventDefault(); translate(); });
  $('clear').addEventListener('click', function () {
    input.value = ''; updateCount(); stop(); reqId++; result.hidden = true; setStatus(''); input.focus();
  });

  function setStatus(msg, err) { statusEl.textContent = msg; statusEl.classList.toggle('error', !!err); }

  /* ---------- translate ---------- */
  var reqId = 0;
  function translate() {
    var texto = input.value.trim();
    if (!texto) { setStatus('Please enter some text to translate.', true); input.focus(); return; }
    var my = ++reqId;
    stop();
    $('submit').disabled = true;
    setStatus('Translating…');
    fetch('/api/v1/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texto: texto })
    }).then(function (r) {
      if (r.status === 429) {
        var ra = parseInt(r.headers.get('Retry-After'), 10);
        throw new Error(ra > 0 ? 'Too many requests. Please retry in ' + ra + ' second' + (ra === 1 ? '' : 's') + '.'
                               : 'Too many requests. Please wait a moment and try again.');
      }
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (r.status >= 500) throw new Error('The server had a problem (HTTP ' + r.status + '). Please try again shortly.');
        if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
        return d;
      });
    }).then(function (data) {
      if (my !== reqId) return;
      render(data);
    }).catch(function (err) {
      if (my !== reqId) return;
      result.hidden = true;
      setStatus(err instanceof TypeError ? 'Could not reach the server. Check your connection.' : 'Could not translate: ' + err.message, true);
    }).then(function () { if (my === reqId) $('submit').disabled = false; });
  }

  function kind(it) {
    if (it.es_deletreo) return 'spell';
    var m = String(it.match_method || '').toLowerCase();
    if (/ai|ml|semantic|embed|model/.test(m)) return 'ai';
    if (/fuzzy|approx|levenshtein|similar/.test(m)) return 'fuzzy';
    return 'exact';
  }
  var BADGE = { spell: 'Fingerspelling', fuzzy: 'Fuzzy', ai: 'AI' };
  function label(it) { return it.es_deletreo ? (it.letra || '?') : (it.palabra_es || '?'); }
  function confText(it) {
    return typeof it.confidence === 'number' ? ' (' + Math.round(it.confidence * 100) + '%)' : '';
  }

  /* ---------- grouping of fingerspelled letters ---------- */
  // One group per lexical sign and one group per fingerspelled word. Uses the
  // spelled_word / spelled_index fields when the API sends them and falls back
  // to merging consecutive es_deletreo items when they are absent.
  function upper(s) { return String(s).toLocaleUpperCase('es'); }
  function groupItems(items) {
    var groups = [], gof = [], cur = null, prev = -1;
    items.forEach(function (it, i) {
      if (!it.es_deletreo) {
        groups.push({ start: i, end: i, spelled: false }); cur = null; prev = -1;
        gof.push(groups.length - 1);
        return;
      }
      var si = typeof it.spelled_index === 'number' ? it.spelled_index : null;
      var sw = typeof it.spelled_word === 'string' && it.spelled_word ? it.spelled_word : '';
      var fresh = !cur || (si !== null && si <= prev) || (sw && cur.word && sw !== cur.word);
      if (fresh) { cur = { start: i, end: i, spelled: true, word: sw }; groups.push(cur); }
      else { cur.end = i; if (!cur.word && sw) cur.word = sw; }
      prev = si !== null ? si : prev + 1;
      gof.push(groups.length - 1);
    });
    groups.forEach(function (g) {
      if (!g.spelled) return;
      var n = g.end - g.start + 1, chars = g.word ? Array.from(g.word) : [];
      if (chars.length !== n) {
        chars = items.slice(g.start, g.end + 1).map(function (it) { return it.letra || '?'; });
      }
      g.letters = chars.map(upper);
      g.word = upper(g.word || g.letters.join(''));
    });
    state.groups = groups; state.gof = gof;
  }
  function groupLabel(g, items) { return g.spelled ? g.word : label(items[g.start]); }

  function render(data) {
    var items = data.secuencia_senas || [];
    state.items = items; state.idx = 0;
    if (!items.length) {
      state.groups = []; state.gof = [];
      result.hidden = true; setStatus('No signs found for this text.', true); return;
    }
    groupItems(items);
    var groups = state.groups;
    var seq = (data.nlp_analysis && data.nlp_analysis.secuencia_lsrd) || [];
    $('nlpSeq').textContent = seq.length ? seq.join(' · ') : '-';
    var tl = $('timeline'); tl.textContent = '';
    groups.forEach(function (g, gi) {
      var li = document.createElement('li');
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'tl';
      var name = groupLabel(g, items);
      b.appendChild(document.createTextNode(name));
      var k = kind(items[g.start]);
      if (BADGE[k]) {
        var s = document.createElement('span');
        s.className = 'badge ' + k; s.textContent = BADGE[k];
        b.appendChild(s);
      }
      var aria = 'Sign ' + (gi + 1) + ' of ' + groups.length + ': ' + name;
      if (g.spelled) aria += ', fingerspelled word, ' + g.letters.length + ' letter' + (g.letters.length === 1 ? '' : 's');
      else if (k === 'fuzzy') aria += ', approximate match';
      else if (k === 'ai') aria += ', AI match';
      b.setAttribute('aria-label', aria);
      b.addEventListener('click', function () { stop(); show(g.start); });
      li.appendChild(b); tl.appendChild(li);
    });
    result.hidden = false;
    var spelledN = groups.filter(function (g) { return g.spelled; }).length;
    setStatus(groups.length + ' sign' + (groups.length === 1 ? '' : 's') + ' found' +
      (spelledN ? ' (' + spelledN + ' fingerspelled word' + (spelledN === 1 ? '' : 's') + ')' : '') + '.');
    show(0);
  }

  function show(i) {
    var it = state.items[i]; if (!it) return;
    state.idx = i;
    var gi = state.gof[i], g = state.groups[gi], pos = i - g.start;
    var img = $('stageImg'), fb = $('stageFallback');
    var src = it.image_available === false ? '' : (it.url_imagen || '');
    var desc = it.descripcion_sena || '';
    img.onerror = null;
    function showCard() {
      img.hidden = true; img.removeAttribute('src');
      $('fbWord').textContent = label(it);
      $('fbDesc').textContent = desc || 'No movement description available.';
      fb.hidden = false;
    }
    if (src) {
      img.alt = g.spelled ? 'Fingerspelled letter ' + label(it) + ' of ' + g.word : 'Sign for ' + label(it);
      fb.hidden = true; img.hidden = false;
      img.onerror = showCard;
      img.src = src;
    } else { showCard(); }
    var sw = $('stageWord'), note = $('stageNote');
    sw.textContent = '';
    if (g.spelled) {
      g.letters.forEach(function (ch, j) {
        var sp = document.createElement('span');
        sp.className = 'sl' + (j === pos ? ' on' : ''); sp.textContent = ch;
        sw.appendChild(sp);
      });
      sw.setAttribute('aria-hidden', 'true');
      note.textContent = g.word + ' — fingerspelled (no sign in the official dictionary)';
      note.hidden = false;
    } else {
      sw.textContent = label(it);
      sw.removeAttribute('aria-hidden');
      note.textContent = ''; note.hidden = true;
    }
    $('stagePos').textContent = (gi + 1) + ' / ' + state.groups.length +
      (g.spelled ? ' · letter ' + (pos + 1) + ' of ' + g.letters.length : '');
    var k = kind(it), bd = $('stageBadge');
    bd.hidden = !BADGE[k]; bd.className = 'badge ' + k; bd.textContent = BADGE[k] || '';
    $('dDesc').textContent = desc || 'No description available.';
    $('dPage').textContent = it.pagina != null && it.pagina !== '' ? 'Page ' + it.pagina : '-';
    $('dCat').textContent = it.categoria || '-';
    $('dMatch').textContent = it.es_deletreo ? 'Fingerspelling' :
      (it.match_method ? it.match_method + confText(it) : 'Exact dictionary match');
    var cur = $('timeline').querySelectorAll('.tl');
    for (var j = 0; j < cur.length; j++) {
      if (j === gi) cur[j].setAttribute('aria-current', 'true'); else cur[j].removeAttribute('aria-current');
    }
    if (cur[gi] && cur[gi].scrollIntoView && !reducedMotion()) {
      cur[gi].scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  }

  /* ---------- player ---------- */
  function reducedMotion() { return matchMedia('(prefers-reduced-motion: reduce)').matches; }
  // Time the item at index i stays on screen. Letters of a spelled word go faster
  // (unless the user prefers reduced motion); the speed selector scales everything.
  function stepMs(i) {
    var it = state.items[i];
    var f = it && it.es_deletreo && !reducedMotion() ? SPELL_FACTOR : 1;
    return STEP_MS * f / state.speed;
  }
  function setPlaying(p) {
    state.playing = p;
    var b = $('play');
    b.textContent = p ? '⏸' : '▶';
    b.setAttribute('aria-label', p ? 'Pause' : 'Play');
    b.setAttribute('aria-pressed', String(p));
  }
  function stop() { clearTimeout(state.timer); setPlaying(false); }
  function tick() {
    if (!state.playing) return;
    if (state.idx >= state.items.length - 1) { stop(); return; }
    show(state.idx + 1);
    state.timer = setTimeout(tick, stepMs(state.idx));
  }
  function play() {
    if (!state.items.length) return;
    if (state.idx >= state.items.length - 1) show(0);
    setPlaying(true);
    state.timer = setTimeout(tick, stepMs(state.idx));
  }
  // Previous/next move by sign or by whole fingerspelled word, not by letter.
  function stepGroup(d) {
    if (!state.items.length) return;
    var gi = state.gof[state.idx] + d;
    if (gi < 0 || gi >= state.groups.length) return;
    show(state.groups[gi].start);
  }
  $('play').addEventListener('click', function () { if (state.playing) stop(); else play(); });
  $('prev').addEventListener('click', function () { stop(); stepGroup(-1); });
  $('next').addEventListener('click', function () { stop(); stepGroup(1); });
  $('speed').addEventListener('change', function (e) {
    state.speed = parseFloat(e.target.value) || 1;
    if (state.playing) { clearTimeout(state.timer); state.timer = setTimeout(tick, stepMs(state.idx)); }
  });
  document.addEventListener('keydown', function (e) {
    if (result.hidden || e.altKey || e.ctrlKey || e.metaKey || /^(TEXTAREA|INPUT|SELECT)$/.test(e.target.tagName)) return;
    if (e.key === 'ArrowRight') { $('next').click(); }
    else if (e.key === 'ArrowLeft') { $('prev').click(); }
    else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault(); stop();
      show(e.key === 'Home' ? 0 : state.groups[state.groups.length - 1].start);
    }
    else if (e.key === ' ' && e.target.tagName !== 'BUTTON') { e.preventDefault(); $('play').click(); }
  });
  updateCount();
})();
