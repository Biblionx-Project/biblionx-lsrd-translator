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
  var state = { items: [], idx: 0, playing: false, timer: null, speed: 1 };

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
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
        return d;
      });
    }).then(function (data) {
      if (my !== reqId) return;
      render(data);
    }).catch(function (err) {
      if (my !== reqId) return;
      result.hidden = true;
      setStatus('Could not translate: ' + err.message, true);
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

  function render(data) {
    var items = data.secuencia_senas || [];
    state.items = items; state.idx = 0;
    if (!items.length) { result.hidden = true; setStatus('No signs found for this text.', true); return; }
    var seq = (data.nlp_analysis && data.nlp_analysis.secuencia_lsrd) || [];
    $('nlpSeq').textContent = seq.length ? seq.join(' · ') : '-';
    var tl = $('timeline'); tl.textContent = '';
    items.forEach(function (it, i) {
      var li = document.createElement('li');
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'tl';
      b.appendChild(document.createTextNode(label(it)));
      var k = kind(it);
      if (BADGE[k]) {
        var s = document.createElement('span');
        s.className = 'badge ' + k; s.textContent = BADGE[k];
        b.appendChild(s);
      }
      b.addEventListener('click', function () { stop(); show(i); });
      li.appendChild(b); tl.appendChild(li);
    });
    result.hidden = false;
    setStatus(items.length + ' sign' + (items.length === 1 ? '' : 's') + ' found.');
    show(0);
  }

  function show(i) {
    var it = state.items[i]; if (!it) return;
    state.idx = i;
    var img = $('stageImg'), fb = $('stageFallback');
    var src = it.url_imagen || (it.ruta_imagen ? '/' + it.ruta_imagen : '');
    img.alt = 'Sign for ' + label(it);
    fb.hidden = true; img.hidden = !src;
    if (src) {
      img.onerror = function () { img.hidden = true; fb.hidden = false; };
      img.src = src;
    } else { fb.hidden = false; }
    $('stageWord').textContent = label(it);
    $('stagePos').textContent = (i + 1) + ' / ' + state.items.length;
    var k = kind(it), bd = $('stageBadge');
    bd.hidden = !BADGE[k]; bd.className = 'badge ' + k; bd.textContent = BADGE[k] || '';
    $('dDesc').textContent = it.descripcion_sena || 'No description available.';
    $('dPage').textContent = it.pagina != null && it.pagina !== '' ? 'Page ' + it.pagina : '-';
    $('dCat').textContent = it.categoria || '-';
    $('dMatch').textContent = it.es_deletreo ? 'Fingerspelling' :
      (it.match_method ? it.match_method + confText(it) : 'Exact dictionary match');
    var cur = $('timeline').querySelectorAll('.tl');
    for (var j = 0; j < cur.length; j++) {
      if (j === i) cur[j].setAttribute('aria-current', 'true'); else cur[j].removeAttribute('aria-current');
    }
    if (cur[i] && cur[i].scrollIntoView && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      cur[i].scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  }

  /* ---------- player ---------- */
  function setPlaying(p) {
    state.playing = p;
    var b = $('play');
    b.innerHTML = p ? '&#9208;' : '&#9654;';
    b.setAttribute('aria-label', p ? 'Pause' : 'Play');
    b.setAttribute('aria-pressed', String(p));
  }
  function stop() { clearTimeout(state.timer); setPlaying(false); }
  function tick() {
    if (!state.playing) return;
    if (state.idx >= state.items.length - 1) { stop(); return; }
    show(state.idx + 1);
    state.timer = setTimeout(tick, 1400 / state.speed);
  }
  function play() {
    if (!state.items.length) return;
    if (state.idx >= state.items.length - 1) show(0);
    setPlaying(true);
    state.timer = setTimeout(tick, 1400 / state.speed);
  }
  $('play').addEventListener('click', function () { if (state.playing) stop(); else play(); });
  $('prev').addEventListener('click', function () { stop(); show(Math.max(0, state.idx - 1)); });
  $('next').addEventListener('click', function () { stop(); show(Math.min(state.items.length - 1, state.idx + 1)); });
  $('speed').addEventListener('change', function (e) {
    state.speed = parseFloat(e.target.value) || 1;
    if (state.playing) { clearTimeout(state.timer); state.timer = setTimeout(tick, 1400 / state.speed); }
  });
  document.addEventListener('keydown', function (e) {
    if (result.hidden || /^(TEXTAREA|INPUT|SELECT)$/.test(e.target.tagName)) return;
    if (e.key === 'ArrowRight') { $('next').click(); }
    else if (e.key === 'ArrowLeft') { $('prev').click(); }
    else if (e.key === ' ' && e.target.tagName !== 'BUTTON') { e.preventDefault(); $('play').click(); }
  });
  updateCount();
})();
