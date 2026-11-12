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
