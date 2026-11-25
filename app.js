/* Crypto Loser Analytics Tools — wspólne dla wszystkich zakładek:
   menu i pasek z logo (poprawka 77), znak wodny na wykresach i odświeżanie w trybie aplikacji (ikona na ekranie głównym). */

/* Wspólny układ (poprawka 77): menu dla wszystkich zakładek.
   Pulpit (index.html, <html data-shell="full">) — pełne lewe menu z nazwami.
   Zakładki — wąskie menu (ikona + krótki podpis) i pasek z logo na górze, zawsze widoczny.
   Telefon (≤ 640 px) — pasek z logo na górze i dolny pasek: Pulpit / OI / Likwid. / Altsezon / Dźwignia / Raporty / Więcej.
   Treść stron bez zmian: znika tylko stare logo nad nagłówkiem i link „← Menu” (zastępuje je menu).
   Kropki w menu: stan źródeł i świecąca lampka Altsezonu (meta.json z gałęzi data). Druk (PDF) — bez menu.
   Stan źródeł (poprawka 84) liczy też wiek danych: skan OI/TOTAL (4 h), EMA/Fibo z Orange Pi (1 h), Sieci (30 h) —
   wcześniej kropka była zielona także wtedy, gdy dane stały.
   Po zmianie tego pliku podnieś numer w <script src="app.js?v=NN"> we wszystkich stronach (zamiast Ctrl+F5). */
// 102: jeden format liczb na wszystkich stronach — przecinek w ułamkach, prawdziwy minus (−).
// x.pl(2) = jak toFixed(2), x.plp(4) = jak toPrecision(4); tylko do wyświetlania (do obliczeń i stylów dalej toFixed).
if (!Number.prototype.pl) {
  Number.prototype.pl = function (d) { return this.toFixed(d).replace('.', ',').replace('-', '\u2212'); };
  Number.prototype.plp = function (d) { return this.toPrecision(d).replace('.', ',').replace(/^-/, '\u2212'); };
}
// 115: strefa czasowa godzin na stronie — przełącznik w menu: Polska (domyślnie) / mój czas / UTC, zapamiętany w tej
// przeglądarce. Dane i zamknięcia świec zawsze w UTC (doba = 00:00–24:00 UTC) — zmienia się tylko to, jak pokazana jest
// godzina. Daty świec dziennych, tygodniowych i miesięcznych to doby UTC — tych przełącznik nie rusza.
// Raporty i Telegram zostają w czasie polskim (jedna wiadomość dla wszystkich).
//   CLTZ.fmt(t)                 „19.11, 14:05” w wybranej strefie (t = sekundy; drugi parametr: opcje toLocaleString)
//   CLTZ.opts({...})            opcje toLocaleString z dopisaną strefą
//   CLTZ.apply(chart, fn)       oś czasu i etykieta krzyża wykresu; fn() → true, gdy świece krótsze niż doba
//   CLTZ.closeTxt()             „01:00 czasu polskiego” — o której w wybranej strefie zamyka się doba UTC
window.CLTZ = (function () {
  var KEY = 'cl-tz', ZONES = {pl: 'Europe/Warsaw', utc: 'UTC'}, mode = 'pl';
  var chosen = false, canStore = false;              // chosen: wybór już zapisany w tej przeglądarce
  try {
    var m = localStorage.getItem(KEY);
    canStore = true;
    if (m === 'pl' || m === 'utc' || m === 'local') { mode = m; chosen = true; }
  } catch (e) { /* brak pamięci przeglądarki (tryb prywatny) — czas polski, bez planszy */ }
  function opts(o) {
    var r = {}, k;
    for (k in (o || {})) r[k] = o[k];
    if (mode !== 'local') r.timeZone = ZONES[mode];
    return r;
  }
  function fmt(t, o) { return new Date(t * 1000).toLocaleString('pl-PL', opts(o || {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'})); }
  function date(t, o) { return new Date(t * 1000).toLocaleDateString('pl-PL', opts(o || {day: '2-digit', month: '2-digit', year: 'numeric'})); }
  function time(t) { return new Date(t * 1000).toLocaleTimeString('pl-PL', opts({hour: '2-digit', minute: '2-digit'})); }
  function utcDate(t) { return new Date(t * 1000).toLocaleDateString('pl-PL', {day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC'}); }
  var NAMES = {pl: ['czasu polskiego', 'w czasie polskim', 'PL'], utc: ['UTC', 'w UTC', 'UTC'], local: ['Twojego czasu', 'w Twoim czasie', 'mój']};
  function closeTxt() { var now = Date.now() / 1000; return time(now - now % 86400) + ' ' + NAMES[mode][0]; }
  function zoneName() {
    if (mode !== 'local') return ZONES[mode];
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'czas tego urządzenia'; } catch (e) { return 'czas tego urządzenia'; }
  }
  function set(m) {
    if (m !== 'pl' && m !== 'utc' && m !== 'local') return;
    try { localStorage.setItem(KEY, m); } catch (e) { /* tryb prywatny — wybór tylko do odświeżenia */ }
    location.reload();
  }
  function ts(time) {                                  // czas świecy z biblioteki wykresów → sekundy (albo null)
    if (typeof time === 'number') return time;
    if (typeof time === 'string') { var d = Date.parse(time + 'T00:00:00Z'); return isNaN(d) ? null : d / 1000; }
    if (time && time.year) return Date.UTC(time.year, time.month - 1, time.day) / 1000;
    return null;
  }
  function apply(chart, intraday) {
    if (!chart || !chart.applyOptions) return;
    var intra = function () { try { return !!intraday(); } catch (e) { return false; } };
    chart.applyOptions({
      localization: {
        timeFormatter: function (time) {
          var t = ts(time);
          if (t == null) return '';
          return intra() ? fmt(t, {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : utcDate(t);
        }
      },
      timeScale: {
        // typ znacznika: 0 rok, 1 miesiąc, 2 dzień, 3 i 4 godzina. Świece dzienne i dłuższe → null = domyślny opis biblioteki (UTC).
        tickMarkFormatter: function (time, type) {
          var t = ts(time);
          if (t == null || !intra()) return null;
          var d = new Date(t * 1000);
          if (type === 0) return d.toLocaleDateString('pl-PL', opts({year: 'numeric'}));
          if (type === 1) return d.toLocaleDateString('pl-PL', opts({month: 'short'}));
          if (type === 2) return d.toLocaleDateString('pl-PL', opts({day: 'numeric'}));
          return time_(t);
        }
      }
    });
  }
  var time_ = time;

  // Plansza przy pierwszym wejściu (115): wybór strefy na środku ekranu — trzeba wybrać, żeby przejść dalej.
  // Pokazuje się raz na przeglądarkę (wybór zapisany w localStorage); później zmiana przełącznikiem w menu.
  function sample(z) {
    var o = {hour: '2-digit', minute: '2-digit'};
    if (z) o.timeZone = z;
    try { return new Date().toLocaleTimeString('pl-PL', o); } catch (e) { return ''; }
  }
  function ask() {
    if (chosen || !canStore || document.getElementById('cl-tzask') || document.documentElement.dataset.shell === 'off') return;
    var local = 'czas tego urządzenia';
    try { local = Intl.DateTimeFormat().resolvedOptions().timeZone || local; } catch (e) { /* stara przeglądarka */ }
    var css = '#cl-tzask{position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box;background:rgba(0,0,0,.72);-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);font-family:inherit}' +
      '#cl-tzask .box{width:100%;max-width:440px;max-height:100%;overflow:auto;box-sizing:border-box;background:#1a1a1a;border:1px solid rgba(255,255,255,.16);border-radius:14px;padding:22px 20px 18px;color:#e6e6e6;box-shadow:0 20px 60px rgba(0,0,0,.6)}' +
      '#cl-tzask h2{margin:0 0 8px;font-size:19px;font-weight:600;color:#fff}' +
      '#cl-tzask p{margin:0 0 14px;font-size:14px;line-height:1.5;color:#b4b4b4}' +
      '#cl-tzask button{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;box-sizing:border-box;margin:0 0 8px;padding:13px 14px;min-height:52px;border-radius:10px;border:1px solid rgba(255,255,255,.16);background:#242424;color:#f0f0f0;font:inherit;font-size:15px;text-align:left;cursor:pointer}' +
      '#cl-tzask button:hover,#cl-tzask button:focus{border-color:#5b9cf6;background:#2a2f3a;outline:none}' +
      '#cl-tzask button small{display:block;font-size:12px;color:#9a9a9a;margin-top:2px}' +
      '#cl-tzask button b{font-weight:600;font-size:16px;white-space:nowrap;font-variant-numeric:tabular-nums}' +
      '#cl-tzask .foot{margin:8px 0 0;font-size:12px;color:#8a8a8a}' +
      '@media print{#cl-tzask{display:none}}';
    var st = document.createElement('style');
    st.textContent = css;
    document.head.appendChild(st);
    function btn(v, name, sub, z) {
      return '<button type="button" data-v="' + v + '"><span>' + name + '<small>' + sub + '</small></span><b>' + sample(z) + '</b></button>';
    }
    var el = document.createElement('div');
    el.id = 'cl-tzask';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-labelledby', 'cl-tzask-h');
    el.innerHTML = '<div class="box"><h2 id="cl-tzask-h">W jakiej strefie pokazywać godziny?</h2>' +
      '<p>Wybierz, w jakim czasie strona ma pokazywać godziny na wykresach i w opisach. Dane się nie zmieniają — ' +
      'świece dzienne zawsze zamykają się o 00:00 UTC.</p>' +
      btn('pl', 'Czas polski', 'Europe/Warsaw — jak w raportach i na Telegramie', 'Europe/Warsaw') +
      btn('local', 'Mój czas', String(local).replace(/&/g, '&amp;').replace(/</g, '&lt;') + ' — czas tego urządzenia', null) +
      btn('utc', 'UTC', 'czas zamknięć świec', 'UTC') +
      '<p class="foot">Wybór zapamięta ta przeglądarka. Zmienisz go później przełącznikiem „Czas” w menu.</p></div>';
    document.body.appendChild(el);
    el.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('button[data-v]') : null;
      if (!b) return;                                   // kliknięcie obok — plansza zostaje, trzeba wybrać
      var v = b.getAttribute('data-v');
      try { localStorage.setItem(KEY, v); } catch (err) { /* nie zapisało się — zapytamy przy następnym wejściu */ }
      chosen = true;
      if (v !== mode) { location.reload(); return; }
      el.parentNode.removeChild(el);
    });
    var first = el.querySelector('button');
    if (first && first.focus) first.focus();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ask);
  else ask();

  return {mode: function () { return mode; }, set: set, opts: opts, fmt: fmt, date: date, time: time, utcDate: utcDate, apply: apply,
    closeTxt: closeTxt, zoneName: zoneName,
    name: function () { return NAMES[mode][0]; }, inName: function () { return NAMES[mode][1]; }, short: function () { return NAMES[mode][2]; }};
})();
(function () {
  var html = document.documentElement;
  if (html.dataset.shell === 'off') return;
  var full = html.dataset.shell === 'full';
  html.classList.add('cl-shell', full ? 'cl-full' : 'cl-narrow');

  // kolejność menu (poprawka 111): Pulpit na górze (osobno), niżej jedna lista bez działów
  var NAV = [
    {href: 'oi.html', ic: 'OI', name: 'OI & TOTAL', short: 'OI', rgb: '206,147,216', fg: '#ce93d8', status: 'live'},
    {href: 'ema.html', ic: 'EMA', name: 'EMA200 i RSI', short: 'EMA200', rgb: '255,193,7', fg: '#ffc107', status: 'live'},
    {href: 'alt.html', ic: 'ALT', name: 'Altsezon', short: 'Altsezon', rgb: '244,143,177', fg: '#f48fb1', lamp: true, status: 'beta'},
    {href: 'sieci.html', ic: 'NET', name: 'Sieci', short: 'Sieci', rgb: '129,199,132', fg: '#81c784', status: 'beta'},
    {href: 'liq.html', ic: 'LIQ', name: 'Likwidacje i funding', short: 'Likwid.', rgb: '224,82,82', fg: '#e05252', status: 'live'},
    {href: 'hl.html', ic: 'LEW', name: 'Dźwignia — zarabiający vs reszta', short: 'Dźwignia', rgb: '91,156,246', fg: '#5b9cf6', status: 'beta'},
    {href: 'raporty.html', ic: 'RAP', name: 'Raporty', short: 'Raporty', rgb: '38,198,218', fg: '#26c6da', status: 'beta'},
    {href: 'sandbox.html', ic: 'SBX', name: 'Chart Sandbox — nakładanie wykresów', short: 'Sandbox', rgb: '255,138,101', fg: '#ff8a65', status: 'beta'},
    {href: 'rsi.html', ic: 'RSI', name: 'RSI Hyperliquid', short: 'RSI HL', rgb: '76,175,125', fg: '#4caf7d', status: 'live'},
    {href: 'fib.html', ic: 'Fib', name: 'Fibo · zawieszone', short: 'Fibo', rgb: '255,255,255', fg: '#8a8a8a', paused: true, status: 'paused'}
  ];
  // Status zakładki — znaczek przy tytule strony (poprawka 78). Zmiana statusu: pole status w NAV wyżej.
  var STATUS = {
    live: ['Live', 'Działa stabilnie — dane i alerty na bieżąco.'],
    beta: ['Beta', 'Działa, ale jeszcze dopracowywane — możliwe zmiany i drobne błędy.'],
    paused: ['Zawieszone', 'Wstrzymane do dopracowania — wyniki mogą być nietrafione.']
  };
  var MOBILE = ['index.html', 'oi.html', 'alt.html', 'liq.html', 'hl.html', 'raporty.html'];   // 101: + Likwidacje i Dźwignia
  var page = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  if (page.indexOf('.') < 0) page = 'index.html';

  var css = '@media screen{' +
    'html.cl-shell .brand,html.cl-shell .menu-link{display:none!important}' +
    '.cl-ico{width:34px;height:24px;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;letter-spacing:-.2px;flex:none}' +
    '.cl-dot{width:8px;height:8px;border-radius:50%;flex:none;background:#555}' +
    '.cl-dot.ok{background:#4caf7d}.cl-dot.bad{background:#e05252}.cl-dot.warn{background:#ffc107}' +
    '.cl-lamp{position:absolute;width:8px;height:8px;border-radius:50%;background:var(--lc,#5b9cf6);box-shadow:0 0 8px var(--lc,#5b9cf6);animation:cl-blink 1.4s ease-in-out infinite}' +
    '@keyframes cl-blink{0%,100%{opacity:1}50%{opacity:.2}}' +
    '.cl-status{display:inline-flex;align-items:center;gap:5px;margin-left:10px;vertical-align:middle;position:relative;top:-2px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;line-height:1;padding:4px 8px;border-radius:5px;white-space:nowrap;cursor:help}' +
    '.cl-status::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}' +
    '.cl-status.live{background:rgba(76,175,125,.15);color:#4caf7d}' +
    '.cl-status.beta{background:rgba(91,156,246,.15);color:#5b9cf6}' +
    '.cl-status.paused{background:rgba(255,193,7,.14);color:#ffc107}' +
    '@media (prefers-reduced-motion:reduce){.cl-lamp{animation:none}}' +
    // 115: przełącznik strefy czasowej
    '.cl-tz{flex:none;background:#1c1c1c;color:#c8c8c8;border:1px solid rgba(255,255,255,.14);border-radius:7px;font:inherit;font-size:12px;line-height:1.2;padding:5px 6px;cursor:pointer;max-width:100%}' +
    '.cl-tz:hover,.cl-tz:focus{border-color:rgba(255,255,255,.35);color:#fff;outline:none}' +
    // wąskie menu (zakładki)
    '.cl-rail{position:fixed;left:0;top:0;bottom:0;width:76px;z-index:40;box-sizing:border-box;padding:8px 6px 10px;background:#121212;border-right:1px solid rgba(255,255,255,.08);display:flex;flex-direction:column;gap:2px;overflow-y:auto;scrollbar-width:none}' +
    '.cl-rail a{position:relative;display:flex;flex-direction:column;align-items:center;gap:4px;padding:7px 2px;border-radius:9px;color:#a8a8a8;text-decoration:none;font-size:11px;line-height:1.1;text-align:center}' +
    '.cl-rail a:hover{background:#1c1c1c;color:#fff}.cl-rail a.on{background:#262626;color:#fff}' +
    '.cl-rail .cl-home img{width:30px;height:30px;display:block}' +
    '.cl-rail .cl-sep{height:1px;background:rgba(255,255,255,.08);margin:5px 8px;flex:none}' +
    '.cl-rail .cl-lamp{top:5px;right:12px}' +
    '.cl-rail .cl-stat{margin-top:auto;display:flex;flex-direction:column;align-items:center;gap:4px;font-size:11px;color:#8a8a8a;padding-top:8px}' +
    // pasek z logo (zakładki; na telefonie także Pulpit)
    '.cl-top{position:fixed;top:0;left:76px;right:0;height:64px;z-index:39;box-sizing:border-box;padding:0 24px;display:flex;align-items:center;gap:16px;background:rgba(15,15,15,.94);border-bottom:1px solid rgba(255,255,255,.08);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}' +
    '.cl-top .cl-logo{display:block;line-height:0}.cl-top .cl-logo img{height:40px;width:auto;display:block}' +
    '.cl-top .cl-stat{margin-left:auto;display:flex;align-items:center;gap:7px;font-size:12px;color:#8a8a8a;white-space:nowrap}' +
    'html.cl-narrow body{padding-left:100px!important;padding-top:82px!important}' +
    'html.cl-narrow{scroll-padding-top:76px}' +
    'html.cl-narrow .layout .side{top:80px}' +
    // pełne menu (Pulpit)
    '.cl-side{position:fixed;left:0;top:0;bottom:0;width:232px;z-index:40;box-sizing:border-box;padding:18px 12px 14px;background:#121212;border-right:1px solid rgba(255,255,255,.08);display:flex;flex-direction:column;gap:2px;overflow-y:auto}' +
    '.cl-side .cl-logo{display:block;margin:2px 6px 16px;line-height:0}.cl-side .cl-logo img{width:186px;height:auto}' +
    '.cl-side a.it{position:relative;display:flex;align-items:center;gap:10px;padding:7px 9px;border-radius:8px;color:#c8c8c8;text-decoration:none;font-size:14px;min-height:24px}' +
    '.cl-side a.it:hover{background:#1c1c1c;color:#fff}.cl-side a.it.on{background:#242424;color:#fff}' +
    '.cl-side a.it.paused{color:#8a8a8a}' +
    '.cl-side .cl-lamp{position:static;margin-left:auto}' +
    '.cl-side .cl-h{font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#7a7a7a;padding:14px 9px 5px}' +
    '.cl-side .cl-stat{margin-top:auto;padding:12px 9px 2px;border-top:1px solid rgba(255,255,255,.08);display:flex;flex-direction:column;gap:5px;font-size:12px;color:#8a8a8a}' +
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
    '.cl-top .cl-stat{font-size:10.5px;gap:5px;min-width:0;overflow:hidden;text-overflow:ellipsis}' +
    '.cl-top{gap:8px}.cl-top .cl-tz{font-size:11px;padding:4px 3px}' +
    '.cl-bottom{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:41;box-sizing:border-box;height:calc(60px + env(safe-area-inset-bottom));padding:4px 4px env(safe-area-inset-bottom);background:#121212;border-top:1px solid rgba(255,255,255,.1)}' +
    '.cl-bottom a,.cl-bottom button{position:relative;flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;min-height:52px;min-width:0;color:#9a9a9a;font:inherit;font-size:10.5px;white-space:nowrap;text-decoration:none;background:none;border:0;cursor:pointer;-webkit-tap-highlight-color:transparent}' +
    '.cl-bottom .on{color:#fff}.cl-bottom .on .cl-ico{outline:1px solid rgba(255,255,255,.35)}' +
    '.cl-bottom .cl-lamp{top:4px;right:calc(50% - 22px)}' +
    '.cl-sheet{position:fixed;left:8px;right:8px;bottom:calc(68px + env(safe-area-inset-bottom));z-index:42;background:#1a1a1a;border:1px solid rgba(255,255,255,.14);border-radius:14px;padding:6px;box-shadow:0 -10px 40px rgba(0,0,0,.6);flex-direction:column}' +
    '.cl-sheet.open{display:flex}' +
    '.cl-sheet a{position:relative;display:flex;align-items:center;gap:12px;padding:11px 12px;border-radius:9px;color:#d8d8d8;text-decoration:none;font-size:15px;min-height:22px}' +
    '.cl-sheet a.on{background:#262626;color:#fff}.cl-sheet .cl-lamp{position:static;margin-left:auto}' +
    '}' +
    '}' +
    '@media print{.cl-rail,.cl-side,.cl-top,.cl-bottom,.cl-sheet,.cl-status,.cl-tz{display:none!important}}';
  var st = document.createElement('style');
  st.id = 'cl-shell-css';
  st.textContent = css;
  document.head.appendChild(st);

  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
  function ico(n, size) {
    return '<span class="cl-ico" style="background:rgba(' + n.rgb + ',' + (n.paused ? '.06' : '.14') + ');color:' + n.fg + (size ? ';' + size : '') + '">' + n.ic + '</span>';
  }
  var items = NAV.filter(function (n) { return n.href; });
  // 115: przełącznik strefy czasowej (pasek z logo; na Pulpicie — dół lewego menu)
  function tzSelect() {
    var T = window.CLTZ, cur = T.mode();
    var tip = 'Strefa czasowa godzin na stronie (teraz: ' + T.zoneName() + '). Dane i zamknięcia świec są zawsze w UTC — doba zamyka się o ' +
      T.closeTxt() + '. Raporty i Telegram: czas polski.';
    return '<select class="cl-tz" data-cl-tz aria-label="Strefa czasowa godzin" title="' + esc(tip).replace(/"/g, '&quot;') + '">' +
      [['pl', 'Czas: PL'], ['local', 'Czas: mój'], ['utc', 'Czas: UTC']].map(function (o) {
        return '<option value="' + o[0] + '"' + (o[0] === cur ? ' selected' : '') + '>' + o[1] + '</option>';
      }).join('') + '</select>';
  }
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
      h.push('<div class="cl-stat"><span><i class="cl-dot" data-cl-dot></i><b style="font-weight:400" data-cl-src>Źródła: …</b></span><span data-cl-bad style="display:none;color:#ffc107;line-height:1.35"></span><span data-cl-time></span><span>' + tzSelect() + '</span></div></nav>');
    } else {
      h.push('<nav class="cl-rail" aria-label="Menu"><a class="cl-home" href="index.html" title="Pulpit"><img src="favicon.svg" alt="">Pulpit</a>');
      NAV.forEach(function (n) {
        if (n.sec) { h.push('<span class="cl-sep"></span>'); return; }
        h.push('<a href="' + n.href + '"' + (page === n.href ? ' class="on" aria-current="page"' : '') + ' title="' + esc(n.name) + '">' + ico(n) + esc(n.short) + (n.lamp ? '<span class="cl-lamp" data-cl-lamp hidden></span>' : '') + '</a>');
      });
      h.push('<span class="cl-stat" data-cl-tip><i class="cl-dot" data-cl-dot></i><span data-cl-hm></span></span></nav>');
    }
    h.push('<header class="cl-top" id="cl-top"><a class="cl-logo" href="index.html" aria-label="Pulpit"><img src="logo.svg" alt="Crypto Loser Analytics Tools" width="297" height="64"></a>' +
      '<span class="cl-stat"><i class="cl-dot" data-cl-dot></i><span data-cl-line></span></span>' + tzSelect() + '</header>');
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
    var cur = items.filter(function (n) { return n.href === page; })[0], st = cur && STATUS[cur.status];
    var h1 = st && (document.querySelector('.header h1') || document.querySelector('main h1, body > h1'));
    if (h1 && !h1.querySelector('.cl-status')) {
      h1.insertAdjacentHTML('beforeend', ' <span class="cl-status ' + cur.status + '" title="' + esc(st[1]) + '">' + st[0] + '</span>');
    }
    all('[data-cl-tz]', function (el) { el.addEventListener('change', function () { window.CLTZ.set(el.value); }); });
    all('[data-cl-tz-in]', function (el) { el.textContent = 'godziny ' + window.CLTZ.inName(); });   // np. „godziny w czasie polskim”
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
  // gałąź obok `data` (ema, chains) — ta sama zasada co na stronach; własny adres ?data=… → nie zgadujemy
  function branchBase(branch) {
    var q = new URLSearchParams(location.search);
    if (q.get(branch)) return q.get(branch).replace(/\/?$/, '/');
    if (q.get('data')) return null;
    if (location.hostname.slice(-9) === 'github.io') return dataBase().replace(/data\/$/, branch + '/');
    return branch === 'ema' ? 'ema-data/' : branch + '/';
  }
  var MAX_AGE_H = {scan: 4, ema: 1, chains: 30};     // jak w collector/watchdog.py
  function ageTxt(sec) { var h = sec / 3600; return h < 48 ? Math.round(h) + ' h' : Math.round(h / 24) + ' dni'; }
  function renderStatus(m, ages) {
    var hl = m.health || {}, keys = Object.keys(hl), now = Date.now() / 1000;
    var bad = keys.filter(function (k) { return hl[k] !== 'ok'; });
    var total = keys.length, stale = false;
    // wiek danych: [nazwa, czas zapisu, limit w godzinach]
    [['Skan OI/TOTAL', m.updated, MAX_AGE_H.scan], ['EMA/Fibo (Orange Pi)', ages.ema, MAX_AGE_H.ema], ['Sieci', ages.chains, MAX_AGE_H.chains]].forEach(function (x) {
      if (!x[1] || !keys.length) return;
      total++;
      if (now - x[1] > x[2] * 3600) { bad.push(x[0] + ' — dane sprzed ' + ageTxt(now - x[1])); if (x[0].indexOf('Skan') === 0) stale = true; }
    });
    var ok = total - bad.length;
    var t = m.updated ? new Date(m.updated * 1000) : null;
    var tz = window.CLTZ.opts({});
    var hm = t ? t.toLocaleTimeString('pl-PL', Object.assign({hour: '2-digit', minute: '2-digit'}, tz)) : '—';
    var sameDay = t && t.toLocaleDateString('pl-PL', tz) === new Date().toLocaleDateString('pl-PL', tz);
    var when = t ? (sameDay ? 'dziś ' + hm : t.toLocaleDateString('pl-PL', Object.assign({day: '2-digit', month: '2-digit'}, tz)) + ' ' + hm) : '—';
    var cls = !keys.length ? '' : ok === total ? 'ok' : (ok && !stale) ? 'warn' : 'bad';
    var src = keys.length ? 'Źródła: ' + ok + ' z ' + total + ' ok' : 'Źródła: brak danych';
    var short = bad.map(function (b) { return b.split(' — ')[0]; });
    var prob = bad.length ? 'Problem: ' + short.slice(0, 2).join(', ') + (short.length > 2 ? ' +' + (short.length - 2) : '') : '';
    var tip = src + (bad.length ? ' (problem: ' + bad.join(', ') + ')' : '') + ' · ostatni skan: ' + when;
    all('[data-cl-dot]', function (el) { el.className = 'cl-dot ' + cls; el.title = tip; });
    all('[data-cl-src]', function (el) { el.textContent = src; });
    all('[data-cl-bad]', function (el) { el.textContent = bad.join(' · '); el.style.display = bad.length ? '' : 'none'; });
    all('[data-cl-time]', function (el) { el.textContent = 'Ostatni skan: ' + when; });
    all('[data-cl-hm]', function (el) { el.textContent = hm; });
    all('[data-cl-line]', function (el) { el.textContent = (prob || src) + ' · skan ' + when; el.title = tip; });
    all('[data-cl-tip]', function (el) { el.title = tip; });
  }
  function loadStatus() {
    fetch(dataBase() + 'meta.json?v=' + Math.floor(Date.now() / 300000), {cache: 'no-cache'}).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (m) {
      window.CL_META = m;
      renderStatus(m, {});
      // wiek danych z pozostałych gałęzi: EMA/Fibo (Orange Pi) i Sieci — małe pliki; błąd pobrania = nie liczymy
      var ages = {};
      [['ema', 'fib.json'], ['chains', 'chains.json']].forEach(function (x) {
        var base = branchBase(x[0]);
        if (!base) return;
        fetch(base + x[1] + '?v=' + Math.floor(Date.now() / 300000), {cache: 'no-cache'}).then(function (r) {
          return r.ok ? r.json() : null;
        }).then(function (j) {
          if (j && j.updated) { ages[x[0]] = j.updated; renderStatus(m, ages); }
        }).catch(function () { /* brak pliku / sieci — bez zmian */ });
      });
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
      '.hev-t{position:absolute;left:3px;font-size:11px;font-family:var(--mono,monospace);color:var(--c);white-space:nowrap;' +
      'background:rgba(15,15,15,.8);padding:0 3px;border-radius:3px;pointer-events:auto;cursor:pointer;}' +
      '.hev-l.flip .hev-t{left:auto;right:3px;}' +
      '.hev-pop{position:absolute;z-index:5;max-width:260px;background:#1d1d1d;border:1px solid rgba(255,255,255,.18);' +
      'border-radius:6px;padding:7px 9px;font-size:12px;line-height:1.5;color:#e0e0e0;pointer-events:auto;box-shadow:0 6px 24px rgba(0,0,0,.5);}' +
      '.hev-pop b{color:var(--c);}' +
      '.hev-legend{display:none;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--text2,#aaa);margin-top:6px;align-items:center;}' +
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


// 124: pasek nad wykresem jak w TradingView — rozwijane przyciski zamiast rzędów pigułek.
// Strona wywołuje CLBar.mount([...]) na końcu skryptu. Stare przyciski zostają w kodzie strony (schowane) i dalej
// trzymają stan — nowy pasek tylko je „klika” i co chwilę odczytuje (aktywny = klasa active, nieaktywny = disabled).
// Rzeczy, które na tym wykresie nic by nie pokazały (disabled), są ukryte zamiast wyszarzone; w rozwijanej liście
// zostaje na dole szara linijka „Ukryte: …” z powodem (data-why na przycisku, jeśli strona go poda).
// Elementy listy:
//   {g: '#res-pills', label: 'Interwał', extra: ['#log-btn'], none: 'własny'}  — jeden wybór z pigułek (+ przełączniki w tej samej liście)
//   {sel: '#preset', label: 'Zestaw', acts: ['#save-preset'], skipEmpty: true, emptyText: 'brak'}  — lista <select>
//   {menu: 'Warstwy', icon: 'fx', items: ['#bar-btn', ...]}  — przełączniki z ptaszkami (licznik włączonych na przycisku)
//   {tog: '#cdl-btn', icon: 'candle', label: 'Świece'}  — pojedynczy przełącznik na pasku
//   {btn: '#link'}  — zwykły przycisk (akcja)
(function () {
  var ICON = {
    candle: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M5 2v12M11 2v12" stroke="currentColor" stroke-width="1.2"/><rect x="3" y="4" width="4" height="7" fill="var(--bg2,#181818)" stroke="currentColor" stroke-width="1.2"/><rect x="9" y="6" width="4" height="5" fill="currentColor"/></svg>',
    fx: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 12 6 7l3 3 5-6" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M11 4h3v3" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>',
    layers: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2 14 5 8 8 2 5z M2 8l6 3 6-3 M2 11l6 3 6-3" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>'
  };
  var CHEV = '<svg class="clb-chev" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>';
  var css = '.cl-src{display:none !important}' +
    '.clb{display:flex;align-items:center;gap:2px;flex-wrap:wrap;flex:1 1 auto;min-width:0}' +
    '.clb-sep{width:1px;height:20px;background:var(--border2,rgba(255,255,255,.14));margin:0 4px}' +
    '.clb-dd{position:relative}' +
    '.clb-b{display:inline-flex;align-items:center;gap:6px;min-height:32px;padding:4px 8px;border-radius:6px;border:0;background:transparent;color:var(--text,#f0f0f0);font-family:inherit;font-size:13px;font-weight:500;line-height:1.2;cursor:pointer;white-space:nowrap;max-width:100%}' +
    '.clb-b:hover{background:rgba(255,255,255,.08)}' +
    '.clb-b.open{background:rgba(255,255,255,.12)}' +
    '.clb-b.on{background:rgba(255,255,255,.14)}' +
    '.clb-b.off{color:var(--text2,#888)}' +
    '.clb-b:focus-visible,.clb-i:focus-visible{outline:2px solid var(--blue,#5b9cf6);outline-offset:1px}' +
    '.clb-l{color:var(--text2,#888);font-weight:400}' +
    '.clb-v{overflow:hidden;text-overflow:ellipsis;max-width:190px}' +
    '.clb-n{font-size:11px;padding:0 6px;border-radius:8px;background:rgba(91,156,246,.3);font-family:var(--mono,monospace)}' +
    '.clb-chev{opacity:.6;flex:none}' +
    '.clb-m{position:absolute;top:calc(100% + 4px);left:0;z-index:60;background:#1c1c1c;border:1px solid var(--border2,rgba(255,255,255,.14));border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.6);padding:4px;min-width:280px;max-width:min(380px,calc(100vw - 16px));max-height:min(70vh,560px);overflow-y:auto;display:flex;flex-direction:column}' +
    '.clb-m[hidden]{display:none}' +
    '.clb-h{font-size:11px;color:var(--text2,#888);padding:6px 10px 3px}' +
    '.clb-i{display:flex;align-items:flex-start;gap:8px;width:100%;padding:7px 10px;border:0;border-radius:6px;background:transparent;color:var(--text,#f0f0f0);font-family:inherit;font-size:13px;line-height:1.3;cursor:pointer;text-align:left}' +
    '.clb-i:hover{background:rgba(255,255,255,.07)}' +
    '.clb-i.sel{background:rgba(255,255,255,.09)}' +
    '.clb-k{width:16px;flex:none;color:var(--blue,#5b9cf6);font-weight:700;text-align:center}' +
    '.clb-c{width:16px;height:16px;flex:none;margin-top:1px;border-radius:4px;border:1px solid rgba(255,255,255,.25);display:inline-flex;align-items:center;justify-content:center;font-size:11px;color:#fff}' +
    '.clb-c.on{background:var(--blue,#5b9cf6);border-color:var(--blue,#5b9cf6)}' +
    '.clb-t{display:flex;flex-direction:column;gap:1px;min-width:0}' +
    '.clb-d{font-size:11.5px;color:var(--text2,#888);line-height:1.35}' +
    '.clb-x{height:1px;background:rgba(255,255,255,.1);margin:4px 0}' +
    '.clb-f{font-size:11px;color:var(--text3,#777);padding:6px 10px 4px;border-top:1px solid rgba(255,255,255,.08);margin-top:4px;line-height:1.4}' +
    '@media (max-width:640px){.clb-sep{display:none}}' +
    '@media print{.clb{display:none}}';

  function $(s) { return typeof s === 'string' ? document.querySelector(s) : s; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function txt(el) { return (el.dataset.label || el.textContent || '').replace(/\s+/g, ' ').trim(); }
  // element schowany przez samą stronę (style.display = 'none' / hidden) — tak, jakby go nie było
  function gone(el) {
    for (var e = el; e && e !== document.body; e = e.parentElement) {
      if (e.hidden || e.style.display === 'none') return true;
    }
    return false;
  }
  function usable(el) { return el && !gone(el) && !el.disabled; }
  function hiddenNote(els) {
    var by = {}, order = [];
    els.forEach(function (el) {
      if (!el || gone(el) || !el.disabled) return;
      var w = el.dataset.why || '';
      if (!by[w]) { by[w] = []; order.push(w); }
      by[w].push(txt(el));
    });
    if (!order.length) return '';
    return 'Ukryte — nic by tu nie pokazały: ' + order.map(function (w) { return by[w].join(', ') + (w ? ' (' + w + ')' : ''); }).join(' · ');
  }
  function itemBtn(i, kind, on, label, desc) {
    var mark = kind === 'check' ? '<span class="clb-c' + (on ? ' on' : '') + '">' + (on ? '✓' : '') + '</span>' : '<span class="clb-k">' + (on ? '✓' : (kind === 'act' ? '›' : '')) + '</span>';
    return '<button type="button" class="clb-i' + (on && kind === 'radio' ? ' sel' : '') + '" data-i="' + i + '" role="menuitem">' + mark +
      '<span class="clb-t"><span>' + esc(label) + '</span>' + (desc ? '<span class="clb-d">' + esc(desc) + '</span>' : '') + '</span></button>';
  }

  var openDD = null, proxying = false;
  function closeAll() { if (openDD) { openDD.close(); openDD = null; } }
  // kliknięcie „w imieniu” użytkownika w schowany przycisk strony nie zamyka listy
  function press(el) { proxying = true; try { el.click(); } finally { proxying = false; } }
  document.addEventListener('click', function (e) { if (openDD && !proxying && !openDD.root.contains(e.target)) closeAll(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && openDD) { var b = openDD.btn; closeAll(); b.focus(); } });

  // jedna rozwijana pozycja paska; spec.items() → lista {el, kind, on, label, desc, run} albo {head}/{sep}; spec.note() → stopka
  function dropdown(bar, spec) {
    var root = document.createElement('div'); root.className = 'clb-dd';
    var btn = document.createElement('button'); btn.type = 'button'; btn.className = 'clb-b';
    btn.setAttribute('aria-haspopup', 'menu'); btn.setAttribute('aria-expanded', 'false');
    var menu = document.createElement('div'); menu.className = 'clb-m'; menu.hidden = true; menu.setAttribute('role', 'menu');
    root.appendChild(btn); root.appendChild(menu); bar.appendChild(root);
    var cur = [];
    var me = {
      root: root, btn: btn,
      close: function () { menu.hidden = true; btn.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); },
      render: function () {
        cur = spec.items();
        var h = cur.map(function (it, i) {
          if (it.head) return '<div class="clb-h">' + esc(it.head) + '</div>';
          if (it.sep) return '<div class="clb-x"></div>';
          return itemBtn(i, it.kind, it.on, it.label, it.desc);
        }).join('');
        var n = spec.note ? spec.note() : '';
        menu.innerHTML = h + (n ? '<div class="clb-f">' + esc(n) + '</div>' : '');
      },
      update: function () {
        var s = spec.button();
        root.style.display = s.show === false ? 'none' : '';
        btn.innerHTML = s.html + CHEV;
        if (s.title) btn.title = s.title; else btn.removeAttribute('title');
        if (!menu.hidden) me.render();
      }
    };
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (!menu.hidden) { closeAll(); return; }
      closeAll();
      me.render(); menu.hidden = false; btn.classList.add('open'); btn.setAttribute('aria-expanded', 'true'); openDD = me;
      // nie wychodzić poza ekran z prawej (telefon)
      menu.style.left = '0px';
      var r = menu.getBoundingClientRect(), over = r.right - (window.innerWidth - 8);
      if (over > 0) menu.style.left = Math.max(-root.getBoundingClientRect().left + 8, -over) + 'px';
    });
    menu.addEventListener('click', function (e) {
      var b = e.target.closest('.clb-i'); if (!b) return;
      e.stopPropagation();
      var it = cur[+b.dataset.i]; if (!it) return;
      it.run();
      if (it.kind === 'check') requestAnimationFrame(function () { me.render(); });
      else closeAll();
    });
    return me;
  }

  window.CLBar = {
    mount: function (list) {
      if (!document.getElementById('clb-css')) {
        var st = document.createElement('style'); st.id = 'clb-css'; st.textContent = css; document.head.appendChild(st);
      }
      var srcs = [], first = null;
      list.forEach(function (it) {
        var ids = [it.g, it.sel, it.tog, it.btn].concat(it.items || [], it.extra || [], it.acts || []);
        ids.forEach(function (s) { var el = s && $(s); if (el) { srcs.push(el); if (!first) first = el; } });
      });
      if (!first) return null;
      var host = first.closest('.controls') || first.parentElement;
      var bar = document.createElement('div'); bar.className = 'clb'; bar.setAttribute('role', 'toolbar');
      host.insertBefore(bar, host.firstChild);
      var parts = [];

      list.forEach(function (it, k) {
        if (it.sep) { var sp = document.createElement('div'); sp.className = 'clb-sep'; bar.appendChild(sp); parts.push({update: function () {}}); return; }
        if (it.g) {
          var box = $(it.g); if (!box) return;
          var extras = (it.extra || []).map($).filter(Boolean);
          parts.push(dropdown(bar, {
            button: function () {
              var bs = [].slice.call(box.querySelectorAll('button')).filter(function (b) { return !gone(b); });
              var a = bs.filter(function (b) { return b.classList.contains('active'); })[0];
              var ex = extras.filter(function (b) { return usable(b) && b.classList.contains('active'); }).map(function (b) { return txt(b).toLowerCase(); });
              return {show: !gone(box) && bs.some(function (b) { return !b.disabled; }),
                html: '<span class="clb-l">' + esc(it.label) + '</span><span class="clb-v">' + esc((a ? txt(a) : (it.none || '—')) + (ex.length ? ' · ' + ex.join(' · ') : '')) + '</span>'};
            },
            items: function () {
              var out = [{head: it.label}];
              [].slice.call(box.querySelectorAll('button')).forEach(function (b) {
                if (!usable(b)) return;
                out.push({kind: 'radio', on: b.classList.contains('active'), label: txt(b), desc: b.dataset.desc || b.title || '', run: function () { press(b); }});
              });
              var ex = extras.filter(usable);
              if (ex.length) out.push({sep: 1});
              ex.forEach(function (b) { out.push({kind: 'check', on: b.classList.contains('active'), label: txt(b), desc: b.dataset.desc || b.title || '', run: function () { press(b); }}); });
              return out;
            },
            note: function () { return hiddenNote([].slice.call(box.querySelectorAll('button')).concat(extras)); }
          }));
        } else if (it.sel) {
          var sel = $(it.sel); if (!sel) return;
          var acts = (it.acts || []).map($).filter(Boolean);
          var optText = function (o) { return !o.value && it.emptyText ? it.emptyText : o.textContent.trim(); };
          parts.push(dropdown(bar, {
            button: function () {
              var o = sel.options[sel.selectedIndex];
              return {show: !gone(sel) && sel.options.length > 0, title: o ? optText(o) : '',
                html: '<span class="clb-l">' + esc(it.label) + '</span><span class="clb-v">' + esc(o ? optText(o).replace(/^—\s*|\s*—$/g, '') : '—') + '</span>'};
            },
            items: function () {
              var out = [], last = null;
              [].slice.call(sel.options).forEach(function (o) {
                if (it.skipEmpty && !o.value) return;
                var g = o.parentElement.tagName === 'OPTGROUP' ? o.parentElement.label : null;
                if (g !== last) { if (g) out.push({head: g}); last = g; }
                out.push({kind: 'radio', on: o.selected, label: optText(o), run: function () {
                  sel.value = o.value; sel.dispatchEvent(new Event('change', {bubbles: true}));
                }});
              });
              var av = acts.filter(usable);
              if (av.length) out.push({sep: 1});
              av.forEach(function (b) { out.push({kind: 'act', label: b.dataset.label || b.title || txt(b), run: function () { press(b); }}); });
              return out;
            }
          }));
        } else if (it.menu) {
          var els = it.items.map($).filter(Boolean);
          parts.push(dropdown(bar, {
            button: function () {
              var vis = els.filter(usable), n = vis.filter(function (b) { return b.classList.contains('active'); }).length;
              return {show: vis.length > 0, html: (ICON[it.icon] || '') + '<span>' + esc(it.menu) + '</span>' + (n ? '<span class="clb-n">' + n + '</span>' : '')};
            },
            items: function () {
              return [{head: it.head || it.menu}].concat(els.filter(usable).map(function (b) {
                return {kind: 'check', on: b.classList.contains('active'), label: txt(b), desc: b.dataset.desc || b.title || '', run: function () { press(b); }};
              }));
            },
            note: function () { return hiddenNote(els); }
          }));
        } else if (it.tog || it.btn) {
          var src = $(it.tog || it.btn); if (!src) return;
          var b = document.createElement('button'); b.type = 'button'; b.className = 'clb-b';
          bar.appendChild(b);
          b.addEventListener('click', function (e) { e.stopPropagation(); closeAll(); press(src); });
          parts.push({update: function () {
            b.style.display = usable(src) ? '' : 'none';
            b.innerHTML = (ICON[it.icon] || '') + '<span>' + esc(it.label || txt(src)) + '</span>';
            b.title = src.dataset.desc || src.title || '';
            if (it.tog) { var on = src.classList.contains('active'); b.classList.toggle('on', on); b.classList.toggle('off', !on); b.setAttribute('aria-pressed', on ? 'true' : 'false'); }
          }});
        }
      });

      // schowaj stare grupy (całe .ctrl-group / .pills, jeśli wszystko w nich przejął nowy pasek) i ich kreski .sep
      var taken = new Set(srcs);
      srcs.forEach(function (el) {
        var c = el.closest('.ctrl-group') || el.closest('.pills') || el;
        if (!c.closest('.controls')) c = el;
        var rest = [].slice.call(c.querySelectorAll('button,select,input')).filter(function (x) {
          return !taken.has(x) && !srcs.some(function (s) { return s !== x && s.contains(x); });
        });
        (rest.length ? el : c).classList.add('cl-src');
      });
      document.querySelectorAll('.controls').forEach(function (row) {
        if (!row.querySelector('.cl-src')) return;
        [].slice.call(row.children).forEach(function (ch) { if (ch.classList.contains('sep')) ch.classList.add('cl-src'); });
        if (row !== host && ![].slice.call(row.children).some(function (ch) { return !ch.classList.contains('cl-src'); })) row.classList.add('cl-src');
      });

      var pend = false;
      function update() { pend = false; parts.forEach(function (p) { p.update(); }); }
      function soon() { if (!pend) { pend = true; requestAnimationFrame(update); } }
      update();
      var mo = new MutationObserver(soon);
      srcs.forEach(function (el) { mo.observe(el, {attributes: true, childList: true, subtree: true, attributeFilter: ['class', 'disabled', 'style', 'hidden', 'title', 'data-why']}); });
      // kontenery, które strona chowa (style.display) — np. grupa „Okres” w Sieciach
      srcs.forEach(function (el) { var g = el.closest('.ctrl-group'); if (g) mo.observe(g, {attributes: true, attributeFilter: ['style', 'hidden']}); });
      document.addEventListener('change', soon, true);
      document.addEventListener('click', soon, true);
      return {update: update, bar: bar};
    }
  };
})();


// 125: większy wykres i przeciągane granice (jak w TradingView).
//   CLSplit.mount({layout, main, side, chart, key, merge, sideW, reverse})
//   • wykres domyślnie sięga do dołu okna (zamiast stałych 52–70% wysokości); uchwyt pod wykresem = przeciąganie w górę / w dół;
//   • na szerokim ekranie (≥ 1200 px) uchwyt między wykresem a kolumną boczną = przeciąganie w lewo / w prawo,
//     przeciągnięcie do krawędzi albo przycisk ▸ zwija kolumnę (◂ rozwija); merge: true = wykres i kolumna w jednym panelu;
//   • dwuklik na uchwycie = ustawienie domyślne; rozmiary zapamiętane w tej przeglądarce (localStorage „cl-split:<key>”).
//   Telefon / wąskie okno: bez zmian (wysokość z CSS strony, kolumna nad wykresem).
(function () {
  var css = '.cl-split{gap:0 !important;align-items:stretch !important}' +
    '.cl-split.cl-merge{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius-lg)}' +
    '.cl-merge > .cl-m{background:transparent !important;border:0 !important;border-radius:0 !important;margin-top:0 !important}' +
    '.cl-merge > .cl-s{background:transparent !important;border:0 !important;border-radius:0 !important;position:relative !important;top:auto !important;max-height:none !important}' +
    '.cl-split > .cl-s{flex:none !important;min-width:0}' +
    '.cl-split:not(.cl-merge) > .cl-s{align-self:flex-start}' +
    '.cl-split.cl-col > .cl-s{display:none !important}' +
    '.cl-h{flex:none;width:14px;position:relative;cursor:col-resize;touch-action:none;align-self:stretch;z-index:3}' +
    '.cl-h::before{content:"";position:absolute;top:0;bottom:0;left:6px;width:2px;background:rgba(255,255,255,.12)}' +
    '.cl-h:hover::before,.cl-h.drag::before{left:5px;width:4px;background:var(--blue,#5b9cf6)}' +
    '.cl-h button{position:sticky;top:calc(50vh - 40px);margin:40vh 0 0 -5px;width:24px;height:80px;border-radius:7px;border:1px solid rgba(255,255,255,.28);background:var(--bg3,#222);color:var(--text,#ddd);cursor:col-resize;font-size:13px;line-height:1;padding:0;display:flex;align-items:center;justify-content:center;touch-action:none;letter-spacing:-2px}' +
    '.cl-h:hover button,.cl-h.drag button{border-color:var(--blue,#5b9cf6);color:#fff;background:#24324a}' +
    '.cl-col > .cl-h{width:32px;margin-left:6px;cursor:pointer}' +
    '.cl-col > .cl-h button{margin:16px 0 0 3px;top:90px;height:auto;padding:10px 0;flex-direction:column;gap:8px;cursor:pointer;letter-spacing:.04em}' +
    '.cl-hn{writing-mode:vertical-rl;font-size:12px;letter-spacing:.04em}' +
    '.cl-hgt{height:max(var(--clh),var(--pgh,0px)) !important;min-height:0 !important}' +
    '.cl-v{height:22px;margin:0 0 8px;cursor:row-resize;touch-action:none;position:relative;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.035);border-top:2px solid rgba(255,255,255,.12);border-radius:0 0 6px 6px}' +
    '.cl-v span{font-size:11px;color:var(--text2,#999);padding:1px 12px;border:1px solid rgba(255,255,255,.22);border-radius:10px;background:var(--bg3,#222);white-space:nowrap;pointer-events:none}' +
    '.cl-v:hover,.cl-v.drag{border-top-color:var(--blue,#5b9cf6);background:rgba(91,156,246,.10)}' +
    '.cl-v:hover span,.cl-v.drag span{color:#fff;border-color:var(--blue,#5b9cf6);background:#24324a}' +
    '.cl-dragging,.cl-dragging *{user-select:none !important;cursor:inherit}' +
    '@media print{.cl-h,.cl-v{display:none !important}}';

  function load(k) { try { return JSON.parse(localStorage.getItem('cl-split:' + k) || '{}') || {}; } catch (e) { return {}; } }
  function save(k, v) { try { localStorage.setItem('cl-split:' + k, JSON.stringify(v)); } catch (e) {} }
  function docTop(el) { return el.getBoundingClientRect().top + window.scrollY; }
  function drag(handle, onMove, onEnd, onTap) {
    handle.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      e.preventDefault();
      var x0 = e.clientX, y0 = e.clientY, moved = false;
      handle.setPointerCapture(e.pointerId); handle.classList.add('drag');
      document.documentElement.classList.add('cl-dragging');
      document.documentElement.style.cursor = getComputedStyle(handle).cursor;
      function mv(ev) { if (!moved && Math.abs(ev.clientX - x0) + Math.abs(ev.clientY - y0) < 4) return; moved = true; onMove(ev); }
      function up(ev) {
        handle.releasePointerCapture(e.pointerId); handle.classList.remove('drag');
        document.documentElement.classList.remove('cl-dragging'); document.documentElement.style.cursor = '';
        handle.removeEventListener('pointermove', mv); handle.removeEventListener('pointerup', up); handle.removeEventListener('pointercancel', up);
        if (moved) { if (onEnd) onEnd(ev); } else if (onTap) onTap(ev);
      }
      handle.addEventListener('pointermove', mv); handle.addEventListener('pointerup', up); handle.addEventListener('pointercancel', up);
    });
  }

  window.CLSplit = {
    mount: function (o) {
      if (!document.getElementById('cl-split-css')) {
        var st = document.createElement('style'); st.id = 'cl-split-css'; st.textContent = css; document.head.appendChild(st);
      }
      var key = o.key || location.pathname.split('/').pop().replace('.html', '') || 'index';
      var S = load(key);
      var wrap = document.querySelector(o.chart || '.chart-wrap');
      var layout = o.layout && document.querySelector(o.layout);
      var main = o.main && document.querySelector(o.main), side = o.side && document.querySelector(o.side);
      var wideMQ = matchMedia('(min-width:1200px)'), tallMQ = matchMedia('(min-width:700px)');

      // ── wysokość wykresu ──
      var vh = null;
      function autoH() {
        var top = docTop(wrap), lt = layout ? docTop(layout) : top - 60;
        // wykres kończy się na dole okna: przy pierwszym widoku albo po przewinięciu do panelu (pod paskiem z logo)
        var off = top <= window.innerHeight * 0.4 ? top : 64 + (top - lt);
        return Math.max(340, Math.round(window.innerHeight - off - 40));
      }
      function applyH() {
        if (!wrap) return;
        if (!tallMQ.matches) { wrap.classList.remove('cl-hgt'); if (vh) vh.style.display = 'none'; return; }
        var h = S.h ? Math.max(260, Math.min(S.h, window.innerHeight * 3)) : autoH();
        wrap.style.setProperty('--clh', h + 'px'); wrap.classList.add('cl-hgt');
        if (vh) vh.style.display = '';
      }
      if (wrap) {
        // strona sama ustawia wysokość (Sandbox „Pod sobą”) — wtedy bierzemy większą z dwóch
        var pg = function () { var v = wrap.style.height; if (v) wrap.style.setProperty('--pgh', v); else wrap.style.removeProperty('--pgh'); };
        new MutationObserver(pg).observe(wrap, {attributes: true, attributeFilter: ['style']}); pg();
        vh = document.createElement('div'); vh.className = 'cl-v'; vh.title = 'Przeciągnij w górę / w dół — wysokość wykresu · dwuklik = do dołu okna';
        vh.innerHTML = '<span>⇕ przeciągnij — wysokość wykresu</span>';
        vh.setAttribute('role', 'separator'); vh.setAttribute('aria-orientation', 'horizontal');
        wrap.parentNode.insertBefore(vh, wrap.nextSibling);
        // legenda wydarzeń / faz wstawiana później tuż pod wykresem — uchwyt zawsze zaraz pod wykresem
        new MutationObserver(function () { if (wrap.nextSibling !== vh) wrap.parentNode.insertBefore(vh, wrap.nextSibling); })
          .observe(wrap.parentNode, {childList: true});
        var y0 = 0, h0 = 0;
        vh.addEventListener('pointerdown', function (e) { y0 = e.clientY; h0 = wrap.getBoundingClientRect().height; }, true);
        drag(vh, function (e) { S.h = Math.round(Math.max(260, h0 + e.clientY - y0)); applyH(); }, function () { save(key, S); });
        vh.addEventListener('dblclick', function () { delete S.h; save(key, S); applyH(); });
      }

      // ── szerokość kolumny bocznej ──
      var hh = null, btn = null, defW = o.sideW || 400;
      function applyW() {
        if (!layout || !side || !main) return;
        var on = wideMQ.matches;
        layout.classList.toggle('cl-split', on);
        layout.classList.toggle('cl-merge', on && !!o.merge);
        main.classList.toggle('cl-m', on); side.classList.toggle('cl-s', on);
        if (hh) hh.style.display = on ? '' : 'none';
        if (!on) { side.style.removeProperty('width'); layout.classList.remove('cl-col'); return; }
        layout.classList.toggle('cl-col', !!S.c);
        var max = Math.max(240, layout.getBoundingClientRect().width - 520);
        side.style.setProperty('width', Math.max(220, Math.min(S.w || defW, max)) + 'px', 'important');
        if (btn) {
          var r = !o.reverse;   // kolumna po prawej (oi-layout ma row-reverse w CSS) — strzałka „▸” chowa ją w prawo
          btn.innerHTML = S.c ? (r ? '◂' : '▸') + '<span class="cl-hn">' + (o.name || 'Serie') + '</span>' : '⋮⋮';
          btn.title = S.c ? 'Kliknij albo przeciągnij — pokaż kolumnę „' + (o.name || 'Serie') + '”'
            : 'Złap i przeciągnij w lewo / w prawo — szerokość kolumny „' + (o.name || 'Serie') + '”; do krawędzi = schowaj · dwuklik = domyślnie';
          btn.setAttribute('aria-expanded', S.c ? 'false' : 'true');
        }
      }
      if (layout && side && main) {
        hh = document.createElement('div'); hh.className = 'cl-h';
        hh.title = 'Przeciągnij w lewo / w prawo — szerokość kolumny · dwuklik = domyślnie';
        hh.setAttribute('role', 'separator'); hh.setAttribute('aria-orientation', 'vertical');
        btn = document.createElement('button'); btn.type = 'button'; hh.appendChild(btn);
        // uchwyt między kolumną a wykresem (w kolejności w kodzie strony: zawsze tuż przed / za kolumną)
        if (side.nextElementSibling === main) layout.insertBefore(hh, main); else layout.insertBefore(hh, side);
        var right = !o.reverse, wStart = null;
        hh.addEventListener('pointerdown', function () { wStart = S.c ? null : (S.w || null); }, true);
        drag(hh, function (e) {
          var r = layout.getBoundingClientRect();
          var w = right ? r.right - e.clientX - 6 : e.clientX - r.left - 6;
          if (w < 150) { if (!S.c) { S.c = true; if (wStart) S.w = wStart; else delete S.w; applyW(); } return; }
          S.c = false; S.w = Math.max(220, Math.round(w)); applyW();
        }, function () { save(key, S); }, function () { if (S.c) { S.c = false; save(key, S); applyW(); } });
        hh.addEventListener('dblclick', function () { delete S.w; S.c = false; save(key, S); applyW(); });
      }

      var t = null;
      function all() { applyW(); applyH(); }
      window.addEventListener('resize', function () { clearTimeout(t); t = setTimeout(all, 80); });
      all();
      // pierwszy pomiar po wczytaniu danych (nagłówek nad wykresem może jeszcze urosnąć)
      setTimeout(applyH, 600); window.addEventListener('load', function () { setTimeout(applyH, 50); });
      return {update: all};
    }
  };
})();
