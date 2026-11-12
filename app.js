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
