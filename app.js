/* Crypto Loser Analytics Tools — wspólne dla wszystkich zakładek:
   znak wodny na wykresach i odświeżanie w trybie aplikacji (ikona na ekranie głównym). */
(function () {
  // Znak wodny: szare logo na środku górnego panelu wykresu — widoczne na ciemnym tle i w PDF (jasne tło),
  // trafia też do zrzutów wykresu (takeScreenshot).
  window.brandWatermark = function (chart) {
    try {
      var L = window.LightweightCharts;
      if (!L || !L.createImageWatermark || !chart) return;
      L.createImageWatermark(chart.panes()[0], 'logo-watermark.svg', {maxWidth: 260, maxHeight: 56, alpha: 0.16});
    } catch (e) { console.warn('watermark', e); }
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
