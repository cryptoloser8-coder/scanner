/* Crypto Loser Analytics Tools — wspólne dla wszystkich zakładek:
   menu i pasek z logo (poprawka 77), znak wodny na wykresach i odświeżanie w trybie aplikacji (ikona na ekranie głównym). */

/* Wspólny układ (poprawka 77): menu dla wszystkich zakładek.
   Pulpit (index.html, <html data-shell="full">) — pełne lewe menu z nazwami.
   Zakładki — wąskie menu (ikona + krótki podpis) i pasek z logo na górze, zawsze widoczny.
   Telefon (≤ 640 px) — pasek z logo na górze i dolny pasek: Pulpit / OI / Altsezon / Raporty / Więcej.
   Treść stron bez zmian: znika tylko stare logo nad nagłówkiem i link „← Menu” (zastępuje je menu).
   Kropki w menu: stan źródeł i świecąca lampka Altsezonu (meta.json z gałęzi data). Druk (PDF) — bez menu. */
(function () {
  var html = document.documentElement;
  if (html.dataset.shell === 'off') return;
  var full = html.dataset.shell === 'full';
  html.classList.add('cl-shell', full ? 'cl-full' : 'cl-narrow');

  var NAV = [
    {sec: 'Rynek'},
    {href: 'oi.html', ic: 'OI', name: 'OI & TOTAL', short: 'OI', rgb: '206,147,216', fg: '#ce93d8'},
    {href: 'liq.html', ic: 'LIQ', name: 'Likwidacje i funding', short: 'Likwid.', rgb: '224,82,82', fg: '#e05252'},
    {href: 'sieci.html', ic: 'NET', name: 'Sieci', short: 'Sieci', rgb: '129,199,132', fg: '#81c784'},
    {sec: 'Alty'},
    {href: 'alt.html', ic: 'ALT', name: 'Altsezon', short: 'Altsezon', rgb: '244,143,177', fg: '#f48fb1', lamp: true},
    {href: 'ema.html', ic: 'EMA', name: 'EMA200 i RSI', short: 'EMA200', rgb: '255,193,7', fg: '#ffc107'},
    {href: 'rsi.html', ic: 'RSI', name: 'RSI Hyperliquid', short: 'RSI HL', rgb: '76,175,125', fg: '#4caf7d'},
    {sec: 'Raporty'},
    {href: 'raporty.html', ic: 'RAP', name: 'Raporty', short: 'Raporty', rgb: '38,198,218', fg: '#26c6da'},
    {href: 'fib.html', ic: 'Fib', name: 'Fibo · zawieszone', short: 'Fibo', rgb: '255,255,255', fg: '#8a8a8a', paused: true}
  ];
  var MOBILE = ['index.html', 'oi.html', 'alt.html', 'raporty.html'];
  var page = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  if (page.indexOf('.') < 0) page = 'index.html';

  var css = '@media screen{' +
    'html.cl-shell .brand,html.cl-shell .menu-link{display:none!important}' +
    '.cl-ico{width:34px;height:24px;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;letter-spacing:-.2px;flex:none}' +
    '.cl-dot{width:8px;height:8px;border-radius:50%;flex:none;background:#555}' +
    '.cl-dot.ok{background:#4caf7d}.cl-dot.bad{background:#e05252}.cl-dot.warn{background:#ffc107}' +
    '.cl-lamp{position:absolute;width:8px;height:8px;border-radius:50%;background:var(--lc,#5b9cf6);box-shadow:0 0 8px var(--lc,#5b9cf6);animation:cl-blink 1.4s ease-in-out infinite}' +
    '@keyframes cl-blink{0%,100%{opacity:1}50%{opacity:.2}}' +
    '@media (prefers-reduced-motion:reduce){.cl-lamp{animation:none}}' +
    // wąskie menu (zakładki)
    '.cl-rail{position:fixed;left:0;top:0;bottom:0;width:76px;z-index:40;box-sizing:border-box;padding:8px 6px 10px;background:#121212;border-right:1px solid rgba(255,255,255,.08);display:flex;flex-direction:column;gap:2px;overflow-y:auto;scrollbar-width:none}' +
    '.cl-rail a{position:relative;display:flex;flex-direction:column;align-items:center;gap:4px;padding:7px 2px;border-radius:9px;color:#a8a8a8;text-decoration:none;font-size:10px;line-height:1.1;text-align:center}' +
    '.cl-rail a:hover{background:#1c1c1c;color:#fff}.cl-rail a.on{background:#262626;color:#fff}' +
    '.cl-rail .cl-home img{width:30px;height:30px;display:block}' +
    '.cl-rail .cl-sep{height:1px;background:rgba(255,255,255,.08);margin:5px 8px;flex:none}' +
    '.cl-rail .cl-lamp{top:5px;right:12px}' +
    '.cl-rail .cl-stat{margin-top:auto;display:flex;flex-direction:column;align-items:center;gap:4px;font-size:10px;color:#8a8a8a;padding-top:8px}' +
    // pasek z logo (zakładki; na telefonie także Pulpit)
    '.cl-top{position:fixed;top:0;left:76px;right:0;height:64px;z-index:39;box-sizing:border-box;padding:0 24px;display:flex;align-items:center;gap:16px;background:rgba(15,15,15,.94);border-bottom:1px solid rgba(255,255,255,.08);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}' +
    '.cl-top .cl-logo{display:block;line-height:0}.cl-top .cl-logo img{height:40px;width:auto;display:block}' +
    '.cl-top .cl-stat{margin-left:auto;display:flex;align-items:center;gap:7px;font-size:11px;color:#8a8a8a;white-space:nowrap}' +
    'html.cl-narrow body{padding-left:100px!important;padding-top:82px!important}' +
    'html.cl-narrow{scroll-padding-top:76px}' +
    'html.cl-narrow .layout .side{top:80px}' +
    // pełne menu (Pulpit)
    '.cl-side{position:fixed;left:0;top:0;bottom:0;width:232px;z-index:40;box-sizing:border-box;padding:18px 12px 14px;background:#121212;border-right:1px solid rgba(255,255,255,.08);display:flex;flex-direction:column;gap:2px;overflow-y:auto}' +
    '.cl-side .cl-logo{display:block;margin:2px 6px 16px;line-height:0}.cl-side .cl-logo img{width:186px;height:auto}' +
    '.cl-side a.it{position:relative;display:flex;align-items:center;gap:10px;padding:7px 9px;border-radius:8px;color:#c8c8c8;text-decoration:none;font-size:13px;min-height:24px}' +
    '.cl-side a.it:hover{background:#1c1c1c;color:#fff}.cl-side a.it.on{background:#242424;color:#fff}' +
    '.cl-side a.it.paused{color:#8a8a8a}' +
    '.cl-side .cl-lamp{position:static;margin-left:auto}' +
    '.cl-side .cl-h{font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#7a7a7a;padding:14px 9px 5px}' +
    '.cl-side .cl-stat{margin-top:auto;padding:12px 9px 2px;border-top:1px solid rgba(255,255,255,.08);display:flex;flex-direction:column;gap:5px;font-size:11px;color:#8a8a8a}' +
    '.cl-side .cl-stat span{display:flex;align-items:center;gap:8px}' +
    'html.cl-full body{padding-left:256px!important}' +
    'html.cl-full .cl-top{display:none}' +
    // dolny pasek i „Więcej” (telefon)
    '.cl-bottom,.cl-sheet{display:none}' +
    '@media (max-width:640px){' +
    '.cl-rail,.cl-side{display:none}' +
    'html.cl-shell .cl-top{display:flex;left:0;height:54px;padding:0 14px}.cl-top .cl-logo img{height:32px}' +
    'html.cl-shell body{padding-left:14px!important;padding-top:66px!important;padding-bottom:calc(76px + env(safe-area-inset-bottom))!important}' +
    'html.cl-narrow .layout .side{top:66px}' +
    'html.cl-shell{scroll-padding-top:62px}' +
    '.cl-bottom{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:41;box-sizing:border-box;height:calc(60px + env(safe-area-inset-bottom));padding:4px 4px env(safe-area-inset-bottom);background:#121212;border-top:1px solid rgba(255,255,255,.1)}' +
    '.cl-bottom a,.cl-bottom button{position:relative;flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;min-height:52px;color:#9a9a9a;font:inherit;font-size:10px;text-decoration:none;background:none;border:0;cursor:pointer;-webkit-tap-highlight-color:transparent}' +
    '.cl-bottom .on{color:#fff}.cl-bottom .on .cl-ico{outline:1px solid rgba(255,255,255,.35)}' +
    '.cl-bottom .cl-lamp{top:4px;right:calc(50% - 22px)}' +
    '.cl-sheet{position:fixed;left:8px;right:8px;bottom:calc(68px + env(safe-area-inset-bottom));z-index:42;background:#1a1a1a;border:1px solid rgba(255,255,255,.14);border-radius:14px;padding:6px;box-shadow:0 -10px 40px rgba(0,0,0,.6);flex-direction:column}' +
    '.cl-sheet.open{display:flex}' +
    '.cl-sheet a{position:relative;display:flex;align-items:center;gap:12px;padding:11px 12px;border-radius:9px;color:#d8d8d8;text-decoration:none;font-size:14px;min-height:22px}' +
    '.cl-sheet a.on{background:#262626;color:#fff}.cl-sheet .cl-lamp{position:static;margin-left:auto}' +
    '}' +
    '}' +
    '@media print{.cl-rail,.cl-side,.cl-top,.cl-bottom,.cl-sheet{display:none!important}}';
  var st = document.createElement('style');
  st.id = 'cl-shell-css';
  st.textContent = css;
  document.head.appendChild(st);

  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
  function ico(n, size) {
    return '<span class="cl-ico" style="background:rgba(' + n.rgb + ',' + (n.paused ? '.06' : '.14') + ');color:' + n.fg + (size ? ';' + size : '') + '">' + n.ic + '</span>';
  }
  var items = NAV.filter(function (n) { return n.href; });
  function build() {
    if (document.getElementById('cl-top')) return;
    var b = document.body, h = [];
    if (full) {
      h.push('<nav class="cl-side" aria-label="Menu"><a class="cl-logo" href="index.html"><img src="logo.svg" alt="Crypto Loser Analytics Tools" width="297" height="64"></a>');
      h.push('<a class="it' + (page === 'index.html' ? ' on' : '') + '" href="index.html"><span class="cl-ico" style="background:rgba(255,255,255,.1);color:#f0f0f0">◧</span>Pulpit</a>');
      NAV.forEach(function (n) {
        if (n.sec) { h.push('<div class="cl-h">' + n.sec + '</div>'); return; }
        h.push('<a class="it' + (page === n.href ? ' on' : '') + (n.paused ? ' paused' : '') + '" href="' + n.href + '">' + ico(n) + esc(n.name) + (n.lamp ? '<span class="cl-lamp" data-cl-lamp hidden></span>' : '') + '</a>');
      });
      h.push('<div class="cl-stat"><span><i class="cl-dot" data-cl-dot></i><b style="font-weight:400" data-cl-src>Źródła: …</b></span><span data-cl-time></span></div></nav>');
    } else {
      h.push('<nav class="cl-rail" aria-label="Menu"><a class="cl-home" href="index.html" title="Pulpit"><img src="favicon.svg" alt="">Pulpit</a>');
      NAV.forEach(function (n) {
        if (n.sec) { h.push('<span class="cl-sep"></span>'); return; }
        h.push('<a href="' + n.href + '"' + (page === n.href ? ' class="on" aria-current="page"' : '') + ' title="' + esc(n.name) + '">' + ico(n) + esc(n.short) + (n.lamp ? '<span class="cl-lamp" data-cl-lamp hidden></span>' : '') + '</a>');
      });
      h.push('<span class="cl-stat" data-cl-tip><i class="cl-dot" data-cl-dot></i><span data-cl-hm></span></span></nav>');
    }
    h.push('<header class="cl-top" id="cl-top"><a class="cl-logo" href="index.html" aria-label="Pulpit"><img src="logo.svg" alt="Crypto Loser Analytics Tools" width="297" height="64"></a>' +
      '<span class="cl-stat"><i class="cl-dot" data-cl-dot></i><span data-cl-line></span></span></header>');
    // telefon
    h.push('<nav class="cl-bottom" aria-label="Menu">');
    MOBILE.forEach(function (href) {
      var n = href === 'index.html' ? {ic: '◧', rgb: '255,255,255', fg: '#f0f0f0', short: 'Pulpit'} : items.filter(function (x) { return x.href === href; })[0];
      h.push('<a href="' + href + '"' + (page === href ? ' class="on" aria-current="page"' : '') + '>' + ico(n) + esc(n.short) + (n.lamp ? '<span class="cl-lamp" data-cl-lamp hidden></span>' : '') + '</a>');
    });
    var other = MOBILE.indexOf(page) < 0;
    h.push('<button type="button" id="cl-more"' + (other ? ' class="on"' : '') + ' aria-expanded="false" aria-controls="cl-sheet"><span class="cl-ico" style="background:rgba(255,255,255,.08);color:#d8d8d8">•••</span>Więcej</button></nav>');
    h.push('<div class="cl-sheet" id="cl-sheet" role="menu">');
    items.forEach(function (n) {
      h.push('<a role="menuitem" href="' + n.href + '"' + (page === n.href ? ' class="on"' : '') + '>' + ico(n) + esc(n.name) + (n.lamp ? '<span class="cl-lamp" data-cl-lamp hidden></span>' : '') + '</a>');
    });
    h.push('</div>');
    b.insertAdjacentHTML('afterbegin', h.join(''));
    var more = document.getElementById('cl-more'), sheet = document.getElementById('cl-sheet');
    more.addEventListener('click', function (e) {
      e.stopPropagation();
      var o = sheet.classList.toggle('open');
      more.setAttribute('aria-expanded', o ? 'true' : 'false');
    });
    document.addEventListener('click', function (e) {
      if (sheet.classList.contains('open') && !sheet.contains(e.target)) { sheet.classList.remove('open'); more.setAttribute('aria-expanded', 'false'); }
    });
    loadStatus();
  }

  // stan źródeł i lampki Altsezonu — meta.json z gałęzi data (ta sama ścieżka co na stronach)
  function dataBase() {
    var q = new URLSearchParams(location.search);
    if (q.get('data')) return q.get('data').replace(/\/?$/, '/');
    if (location.hostname.slice(-9) === 'github.io') {
      var owner = location.hostname.split('.')[0], repo = location.pathname.split('/').filter(Boolean)[0] || '';
      return 'https://raw.githubusercontent.com/' + owner + '/' + repo + '/data/';
    }
    return 'data/';
  }
  var GROUP_COL = {rajd: '#4caf7d', przegrzanie: '#ff5a36', 'wyprzedaż': '#5b9cf6'};
  function all(sel, f) { Array.prototype.forEach.call(document.querySelectorAll(sel), f); }
  function loadStatus() {
    fetch(dataBase() + 'meta.json?v=' + Math.floor(Date.now() / 300000), {cache: 'no-cache'}).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (m) {
      window.CL_META = m;
      var hl = m.health || {}, keys = Object.keys(hl), ok = keys.filter(function (k) { return hl[k] === 'ok'; }).length;
      var bad = keys.filter(function (k) { return hl[k] !== 'ok'; });
      var t = m.updated ? new Date(m.updated * 1000) : null;
      var tz = {timeZone: 'Europe/Warsaw'};
      var hm = t ? t.toLocaleTimeString('pl-PL', Object.assign({hour: '2-digit', minute: '2-digit'}, tz)) : '—';
      var sameDay = t && t.toLocaleDateString('pl-PL', tz) === new Date().toLocaleDateString('pl-PL', tz);
      var when = t ? (sameDay ? 'dziś ' + hm : t.toLocaleDateString('pl-PL', Object.assign({day: '2-digit', month: '2-digit'}, tz)) + ' ' + hm) : '—';
      var cls = !keys.length ? '' : ok === keys.length ? 'ok' : ok ? 'warn' : 'bad';
      var src = keys.length ? 'Źródła: ' + ok + ' z ' + keys.length + ' ok' : 'Źródła: brak danych';
      var tip = src + (bad.length ? ' (problem: ' + bad.join(', ') + ')' : '') + ' · ostatni skan: ' + when;
      all('[data-cl-dot]', function (el) { el.className = 'cl-dot ' + cls; });
      all('[data-cl-src]', function (el) { el.textContent = src; });
      all('[data-cl-time]', function (el) { el.textContent = 'Ostatni skan: ' + when; });
      all('[data-cl-hm]', function (el) { el.textContent = hm; });
      all('[data-cl-line]', function (el) { el.textContent = src + ' · skan ' + when; });
      all('[data-cl-tip]', function (el) { el.title = tip; });
      var L = (m.alt_lamps || {}).lamps || {}, on = Object.keys(L).filter(function (k) { return L[k] && L[k].on; });
      all('[data-cl-lamp]', function (el) {
        el.hidden = !on.length;
        if (!on.length) return;
        el.style.setProperty('--lc', GROUP_COL[L[on[0]].group] || '#5b9cf6');
        el.title = 'Świeci: ' + on.map(function (k) { return L[k].name; }).join(', ');
      });
      document.dispatchEvent(new CustomEvent('cl-meta', {detail: m}));
    }).catch(function () {
      all('[data-cl-src]', function (el) { el.textContent = 'Źródła: brak połączenia'; });
      all('[data-cl-line]', function (el) { el.textContent = 'Brak połączenia z danymi'; });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();


(function () {
  // Znak wodny: szare logo na środku górnego panelu wykresu — widoczne na ciemnym tle i w PDF (jasne tło),
  // trafia też do zrzutów wykresu (takeScreenshot).
  // Znak wodny siedzi na górnym panelu; gdy strona przy przerysowaniu usunie wszystkie serie, biblioteka kasuje
  // pusty panel razem ze znakiem wodnym (np. oi.html z dwoma panelami po kliknięciu „Log”). Dlatego po każdym
  // przerysowaniu (addSeries / removeSeries / removePane — raz na partię zmian) znak wodny zakładamy od nowa.
  window.brandWatermark = function (chart) {
    var L = window.LightweightCharts;
    if (!L || !L.createImageWatermark || !chart) return;
    function attach() {
      chart.__wmPending = false;
      try {
        var p = chart.panes()[0];
        if (!p) return;
        if (chart.__wm) { try { chart.__wm.detach(); } catch (e) { /* panel już usunięty */ } }
        chart.__wm = L.createImageWatermark(p, 'logo-watermark.svg', {maxWidth: 260, maxHeight: 56, alpha: 0.16});
      } catch (e) { console.warn('watermark', e); }
    }
    function later() { if (!chart.__wmPending) { chart.__wmPending = true; Promise.resolve().then(attach); } }
    attach();
    if (chart.__wmHooked) return;
    chart.__wmHooked = true;
    ['addSeries', 'removePane', 'removeSeries'].forEach(function (name) {
      var orig = chart[name];
      if (typeof orig !== 'function') return;
      chart[name] = function () { var r = orig.apply(chart, arguments); later(); return r; };
    });
  };

  // Serie z polem `since` w katalogu (meta.json) pokazujemy dopiero od tej chwili — np. CRYPTOCAP z TradingView przed
  // 14.07.2017 liczył niepełny rynek (bez ETH i części altów). Punkty zostają w plikach, strony je pomijają.
  // series = {id: [[t, v], ...]}, catalog = meta.catalog; zmienia series w miejscu i je zwraca.
  window.trimSince = function (series, catalog) {
    if (!series || !catalog) return series;
    Object.keys(series).forEach(function (id) {
      var since = catalog[id] && catalog[id].since, arr = series[id];
      if (!since || !Array.isArray(arr) || !arr.length || arr[0][0] >= since) return;
      series[id] = arr.filter(function (p) { return p[0] >= since; });
    });
    return series;
  };

  // Świece ceny BTC / ETH z zamknięć (px_btc) i knotów (px_btc_hi / px_btc_lo, Binance perp przez Coinalyze).
  // Open = zamknięcie poprzedniej świecy (rynek 24/7 — na Binance różnica to zwykle centy); high / low obejmują
  // też open i close. bucket(t) → początek dłuższej świecy (np. 4H, 1W) albo brak = świece jak w danych.
  // → {candles: [{time, open, high, low, close}], line: [[t, close]] — zamknięcia sprzed pierwszego knota}.
  window.priceCandles = function (closes, his, los, bucket) {
    var H = new Map(his || []), L = new Map(los || []), out = [], line = [], prev = null, cur = null;
    for (var i = 0; i < closes.length; i++) {
      var t = closes[i][0], c = closes[i][1], h = H.get(t), l = L.get(t);
      if (h == null || l == null) {
        if (!out.length && !cur) line.push([t, c]);
        prev = c;
        continue;
      }
      var b = bucket ? bucket(t) : t;
      if (!cur || cur.time !== b) {
        if (cur) out.push(cur);
        var o = prev == null ? c : prev;
        cur = {time: b, open: o, high: Math.max(h, o, c), low: Math.min(l, o, c), close: c};
      } else {
        cur.high = Math.max(cur.high, h, c); cur.low = Math.min(cur.low, l, c); cur.close = c;
      }
      prev = c;
    }
    if (cur) out.push(cur);
    return {candles: out, line: line};
  };
  window.CANDLE_OPTS = {upColor: '#4caf7d', downColor: '#e05252', borderUpColor: '#4caf7d', borderDownColor: '#e05252',
    wickUpColor: '#4caf7d', wickDownColor: '#e05252', priceLineVisible: false, lastValueVisible: true};

  // ── Historyczne wydarzenia (poprawka 63): pionowe przerywane linie z podpisami na wykresie ──
  // Lista z meta.json → history_events (config.yaml). histEvents(chart, wrap) → {set(list), show(on), update()}:
  // update() po każdym przerysowaniu danych (czasy świec), show() — przycisk na stronie.
  // Wydarzenie trafia na świecę, w której się zdarzyło (ostatnia świeca o czasie ≤ data; 1W/1M też).
  var HK = {
    krach: ['#e05252', 'krach'], upadek: ['#ff7043', 'upadek firmy / projektu'], hack: ['#ffb74d', 'kradzież (hack)'],
    prawo: ['#b39ddb', 'prawo i regulacje'], etf: ['#4dd0e1', 'instytucje (ETF, CME)'], polityka: ['#f48fb1', 'polityka'],
    inne: ['#9e9e9e', 'inne']
  };
  window.HIST_KINDS = HK;
  var cssDone = false;
  function hevCss() {
    if (cssDone) return;
    cssDone = true;
    var s = document.createElement('style');
    s.textContent =
      '.hev{position:absolute;inset:0;pointer-events:none;z-index:2;overflow:hidden;}' +
      '.hev-l{position:absolute;top:0;width:0;border-left:1px dashed var(--c);opacity:.7;}' +
      '.hev-t{position:absolute;left:3px;font-size:10px;font-family:var(--mono,monospace);color:var(--c);white-space:nowrap;' +
      'background:rgba(15,15,15,.8);padding:0 3px;border-radius:3px;pointer-events:auto;cursor:pointer;}' +
      '.hev-l.flip .hev-t{left:auto;right:3px;}' +
      '.hev-pop{position:absolute;z-index:5;max-width:260px;background:#1d1d1d;border:1px solid rgba(255,255,255,.18);' +
      'border-radius:6px;padding:7px 9px;font-size:11px;line-height:1.5;color:#e0e0e0;pointer-events:auto;box-shadow:0 6px 24px rgba(0,0,0,.5);}' +
      '.hev-pop b{color:var(--c);}' +
      '.hev-legend{display:none;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--text2,#aaa);margin-top:6px;align-items:center;}' +
      '.hev-legend.on{display:flex;}' +
      '.hev-legend .k::before{content:"";display:inline-block;width:0;height:11px;border-left:1px dashed var(--c);margin-right:5px;vertical-align:-1px;}';
    document.head.appendChild(s);
  }
  function hesc(x) {
    return String(x == null ? '' : x).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function hdate(t) { var d = new Date(t * 1000); return ('0' + d.getUTCDate()).slice(-2) + '.' + ('0' + (d.getUTCMonth() + 1)).slice(-2) + '.' + d.getUTCFullYear(); }
  window.histEvents = function (chart, wrap) {
    hevCss();
    var el = document.createElement('div');
    el.className = 'hev';
    wrap.appendChild(el);
    var lg = document.createElement('div');
    lg.className = 'hev-legend';
    wrap.parentNode.insertBefore(lg, wrap.nextSibling);
    var list = [], times = [], on = false, popT = null;
    function refreshTimes() {
      var set = new Set();
      try {
        chart.panes().forEach(function (p) {
          p.getSeries().forEach(function (s) { s.data().forEach(function (d) { if (typeof d.time === 'number') set.add(d.time); }); });
        });
      } catch (e) { /* starsza biblioteka — bez wydarzeń */ }
      times = Array.from(set).sort(function (a, b) { return a - b; });
    }
    function barFor(t) {                               // ostatnia świeca o czasie ≤ t (najwyżej 35 dni wcześniej)
      var lo = 0, hi = times.length;
      while (lo < hi) { var m = (lo + hi) >> 1; if (times[m] <= t) lo = m + 1; else hi = m; }
      var i = lo - 1;
      if (i < 0 || t - times[i] > 35 * 86400) return null;
      return times[i];
    }
    function draw() {
      if (!on || !list.length || !times.length) { el.innerHTML = ''; return; }
      var ts = chart.timeScale(), lw = 0, rw = 0;
      try { lw = chart.priceScale('left').width(); rw = chart.priceScale('right').width(); } catch (e) { /* brak osi */ }
      var W = el.clientWidth, axisH = ts.height ? ts.height() : 26;
      // podpisy w dwóch rzędach u góry; tam, gdzie wisi legenda wykresu (.legend), rzędy schodzą pod nią
      var leg = wrap.querySelector('.legend'), lgR = 0, lgB = 0;
      if (leg && leg.offsetHeight) { var WR = wrap.getBoundingClientRect(), LR = leg.getBoundingClientRect(); lgR = LR.right - WR.left; lgB = LR.bottom - WR.top; }
      var rows = [6, 22, lgB + 4, lgB + 20], nextLeft = [Infinity, Infinity, Infinity, Infinity];
      var html = list.slice().sort(function (a, b) { return b.t - a.t; }).map(function (e) {
        var bt = barFor(e.t), x = bt == null ? null : ts.timeToCoordinate(bt);
        if (x == null || x < 0 || lw + x > W - rw) return '';
        var X = lw + x, c = (HK[e.kind] || HK.inne)[0], w = 6.2 * e.label.length + 10, flip = X + w > W - rw;
        var a = flip ? X - w : X, row = -1, r0 = lgB && a < lgR + 4 ? 2 : 0;   // pod legendą albo u góry
        for (var r = r0; r < r0 + 2; r++) if (a + w <= nextLeft[r] - 4) { row = r; nextLeft[r] = a; break; }
        var tip = hdate(e.t) + ' — ' + e.label + (e.desc ? ': ' + e.desc : '');
        return '<div class="hev-l' + (flip ? ' flip' : '') + '" style="left:' + X.toFixed(1) + 'px;bottom:' + axisH + 'px;--c:' + c + '">' +
          (row >= 0 ? '<span class="hev-t" data-t="' + e.t + '" title="' + hesc(tip) + '" style="top:' + rows[row] + 'px">' + hesc(e.label) + '</span>' : '') + '</div>';
      }).join('');
      el.innerHTML = html;
      if (popT != null) pop(popT);
    }
    function pop(t) {
      var old = el.querySelector('.hev-pop');
      if (old) old.remove();
      popT = t;
      if (t == null) return;
      var e = list.filter(function (x) { return x.t === t; })[0], sp = el.querySelector('.hev-t[data-t="' + t + '"]');
      if (!e || !sp) { popT = null; return; }
      var c = (HK[e.kind] || HK.inne)[0], r = sp.getBoundingClientRect(), R = el.getBoundingClientRect();
      var p = document.createElement('div');
      p.className = 'hev-pop';
      p.style.setProperty('--c', c);
      p.innerHTML = '<b>' + hesc(e.label) + '</b> · ' + hdate(e.t) + '<br>' + hesc(e.desc || '') +
        '<br><span style="color:#888">' + hesc((HK[e.kind] || HK.inne)[1]) + '</span>';
      el.appendChild(p);
      var left = Math.min(Math.max(4, r.left - R.left), R.width - p.offsetWidth - 4);
      p.style.left = left + 'px';
      p.style.top = (r.bottom - R.top + 4) + 'px';
    }
    el.addEventListener('click', function (ev) {
      var sp = ev.target.closest('.hev-t');
      if (sp) { ev.stopPropagation(); pop(popT === +sp.dataset.t ? null : +sp.dataset.t); }
    });
    document.addEventListener('click', function (ev) { if (popT != null && !el.contains(ev.target)) pop(null); });
    function legend() {
      var vis = on && list.length && times.length;
      lg.classList.toggle('on', !!vis);
      if (!vis) { lg.innerHTML = ''; return; }
      var used = {};
      list.forEach(function (e) { used[HK[e.kind] ? e.kind : 'inne'] = 1; });
      lg.innerHTML = Object.keys(HK).filter(function (k) { return used[k]; }).map(function (k) {
        return '<span class="k" style="--c:' + HK[k][0] + '">' + HK[k][1] + '</span>';
      }).join('') + '<span>Historyczne wydarzenia (lista w config.yaml → history_events). Kliknij podpis, żeby zobaczyć opis; ' +
        'gdy podpisy się nie mieszczą, widać tylko linię — przybliż wykres.</span>';
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(function () { requestAnimationFrame(draw); });
    if (window.ResizeObserver) new ResizeObserver(function () { requestAnimationFrame(draw); }).observe(wrap);
    return {
      set: function (l) { list = (l || []).filter(function (e) { return e && e.t && e.label; }); legend(); draw(); },
      show: function (v) { on = !!v; if (!on) popT = null; legend(); draw(); },
      update: function () { refreshTimes(); legend(); requestAnimationFrame(function () { requestAnimationFrame(draw); }); },
      has: function () { return list.length > 0; }
    };
  };

  // Tryb aplikacji nie ma przycisku „odśwież”: po powrocie po ponad 10 minutach przeładuj stronę (świeże dane).
  var standalone = (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true;
  if (standalone) {
    var hiddenAt = 0;
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) hiddenAt = Date.now();
      else if (hiddenAt && Date.now() - hiddenAt > 10 * 60 * 1000) location.reload();
    });
  }
})();
