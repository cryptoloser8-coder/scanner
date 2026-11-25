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
    {href: 'dziennik.html', ic: 'DZ', name: 'Dziennik — rynek i Twoje decyzje', short: 'Dziennik', rgb: '233,178,92', fg: '#e9b25c', status: 'beta'},   // 134
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
      // 133: na Pulpicie przycisk konta w prawym górnym rogu (jak na zakładkach), nie na dole lewego menu
      h.push('<div class="cl-acct cl-acct-fix" data-cl-acct></div>');
    } else {
      h.push('<nav class="cl-rail" aria-label="Menu"><a class="cl-home" href="index.html" title="Pulpit"><img src="favicon.svg" alt="">Pulpit</a>');
      NAV.forEach(function (n) {
        if (n.sec) { h.push('<span class="cl-sep"></span>'); return; }
        h.push('<a href="' + n.href + '"' + (page === n.href ? ' class="on" aria-current="page"' : '') + ' title="' + esc(n.name) + '">' + ico(n) + esc(n.short) + (n.lamp ? '<span class="cl-lamp" data-cl-lamp hidden></span>' : '') + '</a>');
      });
      h.push('<span class="cl-stat" data-cl-tip><i class="cl-dot" data-cl-dot></i><span data-cl-hm></span></span></nav>');
    }
    h.push('<header class="cl-top" id="cl-top"><a class="cl-logo" href="index.html" aria-label="Pulpit"><img src="logo.svg" alt="Crypto Loser Analytics Tools" width="297" height="64"></a>' +
      '<span class="cl-stat"><i class="cl-dot" data-cl-dot></i><span data-cl-line></span></span>' + tzSelect() + '<span class="cl-acct" data-cl-acct></span></header>');
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


// 128: rysowanie po wykresach (jak w TradingView) — CLDraw.attach({chart, wrap, page, ref, timeLabel}).
//   Pasek narzędzi pionowo z lewej strony wykresu: kursor, linia pozioma, pionowa, trendu, strzałka, prostokąt,
//   Fibo zniesienia, pomiar (% · wartość · dni · świece), pędzel, podpis; kolor, ukryj / pokaż, usuń zaznaczony,
//   usuń wszystkie, „Kopiuj link z rysunkami”.
//   Rysunek jest przypięty do czasu i wartości serii odniesienia (ref() → {id, series}: zwykle seria na prawej osi
//   górnego panelu) — po zmianie zakresu, interwału, przybliżeniu i przewinięciu zostaje w tym samym miejscu na wykresie.
//   Zapis: w tej przeglądarce osobno dla każdej zakładki i serii odniesienia (localStorage „cl-draw:<zakładka>:<seria>”),
//   link: ?rys=… (po otwarciu rysunki dopisują się do zapisanych). Rysuje się tylko w górnym panelu wykresu.
//   Telefon (< 700 px): rysunki widać, paska narzędzi nie ma.
//   Klawisze: Esc — przerwij / odznacz, Delete / Backspace — usuń zaznaczony.
// 136: szkice. To, co rysujemy, trafia do „Roboczego”; „Zapisz jako szkic” zamyka robocze rysunki w nazwanym szkicu
//   (zostaje widoczny). Szkice: pokaż / ukryj (kilka naraz), Edytuj → Gotowe (bez tego rysunki szkicu są zablokowane),
//   zmień nazwę, usuń. Okienko „Szkice” z paska (wariant A), nad osią czasu etykiety widocznych szkiców.
//   Każdy szkic trzyma się serii, na której powstał: strona może podać wszystkie serie górnego panelu
//   (refs() → [{id, series, fmt, name, color}]) — wtedy rysunki każdej serii są widoczne naraz, a dodanie czy usunięcie
//   innej serii nic w nich nie zmienia. Nowe rysunki trafiają do serii z „Rysujesz na” (przycisk na pasku, gdy serii
//   jest kilka; domyślnie ref() jak dotąd). Szkice serii, której nie ma na wykresie: wyszarzone, „Dodaj serię” (add()).
//   Zapis bez zmiany formatu: szkic = wpis {id, k:'sk', p:[], n:nazwa, c:kolor, h:ukryty, at} w tej samej tablicy co
//   rysunki, rysunki szkicu mają pole s = id szkicu. Starsze app.js pokazują wtedy wszystko jak zwykłe rysunki.
(function () {
  var NS = 'http://www.w3.org/2000/svg';
  var COLORS = ['#5b9cf6', '#ffc107', '#4caf7d', '#e05252', '#ce93d8', '#f0f0f0'];
  var FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  var I = function (d) { return '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' + d + '</svg>'; };
  var TOOLS = [
    ['cur', 'Kursor — zaznacz, przesuń, zmień punkty (Esc)', I('<path d="M4 2l10 7-5 1.2L6.5 15z"/>')],
    ['h', 'Linia pozioma — klik w miejscu poziomu', I('<path d="M1.5 9h15"/><circle cx="9" cy="9" r="1.6" fill="currentColor"/>')],
    ['v', 'Linia pionowa — klik w dniu', I('<path d="M9 1.5v15"/><circle cx="9" cy="9" r="1.6" fill="currentColor"/>')],
    ['tl', 'Linia trendu — przeciągnij albo klik, klik', I('<path d="M3 15L15 3"/><circle cx="3" cy="15" r="1.6" fill="currentColor"/><circle cx="15" cy="3" r="1.6" fill="currentColor"/>')],
    ['ar', 'Strzałka — przeciągnij albo klik, klik', I('<path d="M3 15L15 3M15 3H9M15 3v6"/>')],
    ['rc', 'Prostokąt / strefa — przeciągnij po przekątnej', I('<rect x="2.5" y="4.5" width="13" height="9" rx="1"/>')],
    ['fb', 'Fibo zniesienia — od początku do końca ruchu', I('<path d="M2 3h14M2 6.5h14M2 9h14M2 11.5h14M2 15h14" stroke-width="1.2"/>')],
    ['ms', 'Pomiar — zmiana %, wartość, dni i świece między dwoma punktami', I('<path d="M9 2v14M5 6l4-4 4 4M5 12l4 4 4-4"/>')],
    ['br', 'Pędzel — rysuj z wciśniętym przyciskiem', I('<path d="M2.5 14c2-1 2.5-4 5-4.5s3 2 5 0 2.5-6 3-7"/>')],
    ['tx', 'Podpis — klik i wpisz tekst (Enter)', I('<path d="M3 4h12M9 4v11M6.5 15h5"/>')]
  ];
  var css = '.cld-bar{position:absolute;top:0;left:-42px;width:34px;display:flex;flex-direction:column;gap:2px;padding:3px;border:1px solid var(--border,rgba(255,255,255,.08));border-radius:8px;background:var(--bg2,#181818);z-index:6;overflow-y:auto;scrollbar-width:none}' +
    '.cld-bar button{width:26px;height:26px;padding:0;border:0;border-radius:5px;background:transparent;color:var(--text2,#999);cursor:pointer;display:flex;align-items:center;justify-content:center;flex:none;position:relative}' +
    '.cld-bar button:hover{background:rgba(255,255,255,.08);color:var(--text,#f0f0f0)}' +
    '.cld-bar button.on{background:rgba(91,156,246,.25);color:#fff}' +
    '.cld-bar button:focus-visible{outline:2px solid var(--blue,#5b9cf6)}' +
    '.cld-bar .sep{height:1px;background:rgba(255,255,255,.1);margin:3px 2px;flex:none}' +
    '.cld-bar .sw{width:14px;height:14px;border-radius:50%;border:2px solid rgba(255,255,255,.6)}' +
    '.cld-bar button.warn{background:rgba(224,82,82,.35);color:#fff}' +
    '.cld-pop{position:absolute;left:30px;top:0;display:flex;gap:4px;padding:5px;background:#1c1c1c;border:1px solid rgba(255,255,255,.14);border-radius:8px;z-index:7}' +
    '.cld-pop button{width:20px;height:20px;border-radius:50%;border:2px solid transparent}' +
    '.cld-pop button.on{border-color:#fff}' +
    '.cld-wrap{margin-left:42px !important;overflow:visible !important}' +
    '.cld-svg{position:absolute;z-index:5;overflow:hidden;pointer-events:none;touch-action:none}' +
    '.cld-svg.act{pointer-events:all;cursor:crosshair}' +
    '.cld-svg .hit{pointer-events:stroke;cursor:move}' +
    '.cld-svg .hitf{pointer-events:all;cursor:move}' +
    '.cld-svg .hd{pointer-events:all;cursor:grab}' +
    '.cld-svg .hit,.cld-svg .hitf,.cld-svg .hd{touch-action:none}' +
    '.cld-svg.ro .hit,.cld-svg.ro .hitf,.cld-svg.ro .hd{pointer-events:none}' +
    '.cld-svg text{font-family:var(--mono,ui-monospace,monospace);font-size:11px;paint-order:stroke;stroke:#0f0f0f;stroke-width:3px;stroke-linejoin:round}' +
    '.cld-svg text.tx{font-family:inherit;font-size:13px;stroke-width:4px}' +
    '.cld-in{position:absolute;z-index:8;font:13px inherit;font-family:inherit;padding:3px 6px;border-radius:5px;border:1px solid var(--blue,#5b9cf6);background:#111;color:#fff;outline:none;min-width:140px}' +
    '.cld-toast{position:absolute;left:4px;bottom:6px;z-index:8;font-size:12px;padding:4px 9px;border-radius:6px;background:#24324a;color:#fff;border:1px solid var(--blue,#5b9cf6);pointer-events:none}' +
    '.cld-note{position:absolute;left:6px;bottom:8px;z-index:9;max-width:min(460px,calc(100% - 12px));font-size:12.5px;line-height:1.45;padding:9px 11px;border-radius:8px;background:#2a2410;color:#f3e3b0;border:1px solid rgba(255,193,7,.55);box-shadow:0 8px 24px rgba(0,0,0,.5)}' +
    '.cld-note b{color:#ffc107}.cld-note .r{display:flex;gap:6px;margin-top:7px}' +
    '.cld-note button{font:inherit;font-size:12.5px;padding:5px 10px;border-radius:6px;border:1px solid rgba(255,193,7,.6);background:#3a3115;color:#fff;cursor:pointer}' +
    '.cld-bar button.cloud-off{color:#ffc107}.cld-bar button.cloud-on{color:#4caf7d}' +
    '.cld-fab{display:none}' +
    // 136: szkice
    '.cld-svg g.lk *{pointer-events:none !important}' +
    '.cld-bar .bdg{position:absolute;right:-3px;top:-3px;min-width:13px;height:13px;border-radius:7px;background:var(--blue,#5b9cf6);color:#0f0f0f;font-size:9.5px;font-weight:700;line-height:13px;text-align:center;padding:0 2px;box-sizing:border-box;font-family:inherit}' +
    '.cld-bar .sdot{position:absolute;right:2px;bottom:2px;width:9px;height:9px;border-radius:50%;border:1.5px solid #181818}' +
    '.cld-sk,.cld-onp{position:absolute;z-index:9;width:360px;max-width:calc(100vw - 24px);overflow-y:auto;background:#1c1c1c;border:1px solid rgba(255,255,255,.16);border-radius:10px;box-shadow:0 12px 32px rgba(0,0,0,.6);padding:10px;box-sizing:border-box;font-size:13px;line-height:1.35;color:var(--text,#f0f0f0);display:flex;flex-direction:column;gap:4px;text-align:left}' +
    '.cld-onp{width:250px}' +
    '.cld-sk button,.cld-onp button,.cld-sk input{font-family:inherit}' +
    '.cld-sk .hd{display:flex;align-items:baseline;gap:8px}.cld-sk .hd b{font-size:14px}.cld-sk .mu{color:#888;font-size:12px}' +
    '.cld-sk .x{margin-left:auto;width:28px;height:28px;border:0;background:transparent;color:#999;font-size:17px;cursor:pointer;border-radius:5px}' +
    '.cld-sk .lb{font-size:11px;color:#888;margin-top:6px}' +
    '.cld-sk .row{display:flex;align-items:center;gap:8px;padding:5px 6px;border-radius:8px;border:1px solid transparent}' +
    '.cld-sk .row.rob{background:#242424;border:1px dashed rgba(255,255,255,.25);padding:7px 8px}' +
    '.cld-sk .row.ed{background:rgba(255,193,7,.08);border-color:rgba(255,193,7,.35)}' +
    '.cld-sk .row.off{color:#777}' +
    '.cld-sk .dt{width:10px;height:10px;border-radius:50%;flex:none}' +
    '.cld-sk .nm{display:flex;flex-direction:column;min-width:0;flex:1}.cld-sk .nm span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
    '.cld-sk .nm small{font-size:11.5px;color:#888;white-space:normal}.cld-sk .row.ed .nm small{color:#ffc107}' +
    '.cld-sk .ey{width:28px;height:28px;border:0;border-radius:5px;background:transparent;color:#f0f0f0;padding:0;display:flex;align-items:center;justify-content:center;cursor:pointer;flex:none}' +
    '.cld-sk .row.off .ey{color:#666}.cld-sk .ey:disabled{cursor:default;opacity:.4}' +
    '.cld-sk .b{min-height:28px;padding:2px 9px;border-radius:6px;border:1px solid rgba(255,255,255,.18);background:transparent;color:#ddd;font-size:12px;cursor:pointer;white-space:nowrap;flex:none}' +
    '.cld-sk .b.p{border-color:var(--blue,#5b9cf6);background:#24324a;color:#fff}' +
    '.cld-sk .b.y{border-color:rgba(255,193,7,.6);background:#3a3115;color:#fff}' +
    '.cld-sk .b.r{border-color:rgba(224,82,82,.6);background:rgba(224,82,82,.25);color:#fff}' +
    '.cld-sk .b:disabled{opacity:.4;cursor:default}' +
    '.cld-sk .mo{width:28px;height:28px;border:0;background:transparent;color:#999;cursor:pointer;flex:none;border-radius:5px;font-size:15px}' +
    '.cld-sk .ey:hover,.cld-sk .mo:hover,.cld-sk .x:hover{background:rgba(255,255,255,.08)}' +
    '.cld-sk .menu{display:flex;gap:6px;flex-wrap:wrap;margin:-2px 0 4px 44px}' +
    '.cld-sk .frm{display:flex;flex-direction:column;gap:8px;padding:8px;border-radius:8px;background:#242424;border:1px solid rgba(91,156,246,.45)}' +
    '.cld-sk .frm input{min-height:34px;padding:0 9px;border-radius:6px;border:1px solid var(--blue,#5b9cf6);background:#111;color:#fff;font-size:14px;outline:none}' +
    '.cld-sk .frm .sws{display:flex;gap:6px;align-items:center}.cld-sk .frm .sws button{width:22px;height:22px;border-radius:50%;border:2px solid transparent;cursor:pointer;padding:0}' +
    '.cld-sk .frm .sws button.on{border-color:#fff}.cld-sk .frm .r{display:flex;gap:8px;justify-content:flex-end}' +
    '.cld-sk .ri{flex:1;min-width:0;min-height:30px;padding:0 8px;border-radius:6px;border:1px solid var(--blue,#5b9cf6);background:#111;color:#fff;font-size:13px;outline:none}' +
    '.cld-sk .em{color:#888;font-size:12px;padding:4px 6px}' +
    '.cld-sk .ft{font-size:11.5px;color:#888;padding:6px 4px 0;margin-top:4px;border-top:1px solid rgba(255,255,255,.08)}' +
    '.cld-onp .o{display:flex;align-items:center;gap:8px;min-height:34px;padding:0 8px;border:0;border-radius:6px;background:transparent;color:#ddd;font-size:13px;cursor:pointer;text-align:left}' +
    '.cld-onp .o:hover{background:rgba(255,255,255,.07)}.cld-onp .o.on{background:rgba(91,156,246,.18);color:#fff}' +
    '.cld-chips{position:absolute;z-index:6;display:flex;gap:5px;flex-wrap:wrap-reverse;pointer-events:none;max-width:62%;transform:translateY(-100%)}' +
    '.cld-chip{pointer-events:auto;display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:10px;border:1px solid transparent;background:rgba(0,0,0,.62);font:inherit;font-size:11.5px;color:#ccc;cursor:pointer;white-space:nowrap;max-width:220px;overflow:hidden;text-overflow:ellipsis}' +
    '.cld-chip i{width:8px;height:8px;border-radius:50%;flex:none}' +
    '.cld-chip.ed{background:#2a2410;border-color:rgba(255,193,7,.55);color:#f3e3b0;max-width:none}.cld-chip.ed b{color:#ffc107;font-weight:600}' +
    '.cld-chip.ed span{margin-left:4px;padding:1px 8px;border-radius:5px;border:1px solid rgba(255,193,7,.6);background:#3a3115;color:#fff}' +
    // 132: telefon — przycisk ✎ rozwija pasek narzędzi w poziomie nad osią czasu; rysowanie palcem
    '@media (max-width:699px){.cld-wrap{margin-left:0 !important}' +
    '.cld-fab{display:flex;position:absolute;right:66px;bottom:34px;z-index:7;width:42px;height:42px;border-radius:50%;border:1px solid rgba(255,255,255,.28);background:#1c1c1c;color:#e8e8e8;align-items:center;justify-content:center;box-shadow:0 4px 14px rgba(0,0,0,.5);padding:0}' +
    '.cld-fab.on{background:#24324a;border-color:var(--blue,#5b9cf6);color:#fff}' +
    '.cld-bar{display:none;top:auto;bottom:84px;left:4px;right:4px;width:auto;flex-direction:row;overflow-x:auto;overflow-y:hidden;padding:4px;gap:3px;-webkit-overflow-scrolling:touch}' +
    '.cld-bar.open{display:flex}.cld-bar button{width:40px;height:40px}.cld-bar .sep{width:1px;height:auto;margin:3px 2px}' +
    '.cld-pop{top:auto !important;bottom:48px;left:4px}' +
    '.cld-note{top:34px;bottom:auto}' +
    '.cld-sk,.cld-onp{position:fixed;z-index:45;left:8px !important;right:8px;top:auto !important;bottom:calc(68px + env(safe-area-inset-bottom));width:auto;max-width:none;max-height:calc(100vh - 150px) !important;padding:12px}' +
    '.cld-sk .ey,.cld-sk .mo,.cld-sk .x{width:40px;height:40px}.cld-sk .b{min-height:36px;padding:2px 12px;font-size:13px}' +
    '.cld-onp .o{min-height:44px}.cld-chips{max-width:58%}.cld-chip{padding:4px 9px;font-size:12px}}' +
    '@media print{.cld-bar{display:none}.cld-wrap{margin-left:0 !important}}';

  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function num(t) {
    if (t == null) return null;
    if (typeof t === 'number') return t;
    if (typeof t === 'string') return Date.parse(t + 'T00:00:00Z') / 1000;
    if (t.year) return Date.UTC(t.year, t.month - 1, t.day) / 1000;
    return null;
  }
  function hexA(c, a) { var n = parseInt(c.slice(1), 16); return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')'; }
  function pl(x, d) { return x.pl ? x.pl(d) : x.toFixed(d); }
  function sgn(x, d) { return (x > 0 ? '+' : '') + pl(x, d); }
  function load(k) { try { return JSON.parse(localStorage.getItem('cl-draw:' + k) || '[]') || []; } catch (e) { return []; } }
  function save(k, d) { try { if (d.length) localStorage.setItem('cl-draw:' + k, JSON.stringify(d)); else localStorage.removeItem('cl-draw:' + k); } catch (e) {} }
  function b64e(s) { return btoa(unescape(encodeURIComponent(s))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }
  function b64d(s) { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '='; return decodeURIComponent(escape(atob(s))); }
  function rnd(v) { return +(+v).toPrecision(8); }
  function uid() { return Math.random().toString(36).slice(2, 9); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function nRys(n) { return n + (n === 1 ? ' rysunek' : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) ? ' rysunki' : ' rysunków'); }
  function dmy(ms) { var d = new Date(ms), p = function (n) { return (n < 10 ? '0' : '') + n; }; return p(d.getDate()) + '.' + p(d.getMonth() + 1); }
  var EYE = '<path d="M2 9s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z"/><circle cx="9" cy="9" r="2"/>', EYE_OFF = '<path d="M2 9s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z"/><path d="M3 15L15 3"/>';

  // rysunki z linku (?rys=…) — dopisz do zapisanych i usuń z adresu
  (function importLink() {
    try {
      var q = new URLSearchParams(location.search), r = q.get('rys');
      if (!r) return;
      var o = JSON.parse(b64d(r));
      if (o && o.k && Array.isArray(o.d)) {
        var cur = load(o.k), ids = {};
        cur.forEach(function (d) { ids[d.id] = 1; });
        o.d.forEach(function (d) { if (d && d.k && d.p && !ids[d.id]) cur.push(d); });
        save(o.k, cur);
        window.__cldImported = o.k;
      }
      q.delete('rys');
      history.replaceState(null, '', location.pathname + (q.toString() ? '?' + q : '') + location.hash);
    } catch (e) {}
  })();

  window.CLDraw = {
    attach: function (o) {
      var chart = o.chart, wrap = o.wrap || document.querySelector('.chart-wrap');
      if (!chart || !wrap || wrap.__cld) return null;
      wrap.__cld = true;
      if (!document.getElementById('cld-css')) { var st0 = document.createElement('style'); st0.id = 'cld-css'; st0.textContent = css; document.head.appendChild(st0); }
      var page = o.page || location.pathname.split('/').pop().replace('.html', '') || 'index';
      var ts = chart.timeScale();
      var desk = matchMedia('(min-width:700px)');
      var color = (function () { try { return localStorage.getItem('cl-draw-color') || COLORS[0]; } catch (e) { return COLORS[0]; } })();
      var hidden = (function () { try { return localStorage.getItem('cl-draw-hide:' + page) === '1'; } catch (e) { return false; } })();
      var tool = 'cur', sel = null, wip = null, drag = null;
      // 136: kilka serii naraz — każda ma swój zestaw (ST[klucz] = {k, ref, D, cloud}); nowe rysunki idą do onKey
      var R = [], ST = {}, onKey = null, editing = null;
      var sk = {open: false, form: null, menu: null, ren: null, del: 0, fetched: false};

      wrap.classList.add('cld-wrap');
      var svg = el('svg', {'class': 'cld-svg'}); wrap.appendChild(svg);
      var bar = document.createElement('div'); bar.className = 'cld-bar'; bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', 'Rysowanie');
      wrap.appendChild(bar);
      var chips = document.createElement('div'); chips.className = 'cld-chips'; wrap.appendChild(chips);
      var touch = matchMedia('(pointer:coarse)').matches, HW = touch ? 24 : 12, HR = touch ? 9 : 5;
      var fab = document.createElement('button'); fab.type = 'button'; fab.className = 'cld-fab';
      fab.title = 'Rysowanie'; fab.setAttribute('aria-label', 'Rysowanie — pokaż / schowaj narzędzia');
      fab.innerHTML = '<svg width="20" height="20" viewBox="0 0 18 18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 15l1-4 8-8 3 3-8 8z"/><path d="M10.5 4.5l3 3"/></svg>';
      wrap.appendChild(fab);
      fab.addEventListener('click', function (e) {
        e.stopPropagation(); var open = !bar.classList.contains('open');
        bar.classList.toggle('open', open); if (!open) { sel = null; closeSk(); setTool('cur'); } else syncBar();
      });

      // ── zestawy rysunków (jeden na serię) ──
      function allSt() { return Object.keys(ST).map(function (k) { return ST[k]; }); }
      function stOn() { return onKey ? ST[onKey] || null : null; }
      function find(s) { var st = s && ST[s.k]; if (!st) return null; for (var i = 0; i < st.D.length; i++) if (st.D[i].id === s.id) return st.D[i]; return null; }
      function isSel(st, d) { return !!sel && sel.k === st.k && sel.id === d.id; }
      function idOf(k) { return k.slice(page.length + 1); }
      function nameOf(k) {
        if (ST[k] && ST[k].ref.name) return ST[k].ref.name;
        var n = null; try { n = o.name ? o.name(idOf(k)) : null; } catch (e) {}
        return n || idOf(k).split(':').pop();
      }
      function rob(d) { return d.k !== 'sk' && !d.s; }
      // szkice z zapisanych zestawów tej zakładki, których serii nie ma teraz na wykresie (tylko strony z refs())
      function others() {
        if (!o.refs) return [];
        var g = ''; try { g = o.group ? o.group() || '' : ''; } catch (e) {}
        var pre = 'cl-draw:' + page + ':' + g, out = [];
        try {
          for (var i = 0; i < localStorage.length; i++) {
            var lk = localStorage.key(i);
            if (!lk || lk.indexOf(pre) !== 0) continue;
            var k = lk.slice(8); if (ST[k]) continue;
            var D = load(k); if (D.some(function (d) { return d.k === 'sk'; })) out.push({k: k, D: D});
          }
        } catch (e) {}
        return out;
      }
      // szkice: id → {id, n, c, h, at, cnt, keys: {klucz: liczba rysunków}}
      function sketches(withOthers) {
        var M = {}, L = [];
        function add(src, here) {
          src.D.forEach(function (d) {
            var id = d.k === 'sk' ? d.id : d.s; if (!id) return;
            var m = M[id];
            if (!m) { m = M[id] = {id: id, n: 'Szkic', c: '#888', h: 0, at: 0, cnt: 0, keys: {}, meta: false}; L.push(m); }
            if (d.k === 'sk') { if (!m.meta) { m.n = d.n || 'Szkic'; m.c = d.c || '#888'; m.h = d.h ? 1 : 0; m.at = d.at || 0; m.meta = true; } }
            else m.cnt++;
            if (!(src.k in m.keys)) m.keys[src.k] = 0;
            if (d.k !== 'sk') m.keys[src.k]++;
            if (here) m.here = true;
          });
        }
        allSt().forEach(function (st) { add(st, true); });
        if (withOthers) others().forEach(function (x) { add(x, false); });
        L.sort(function (a, b) { return b.at - a.at; });
        return {M: M, L: L};
      }
      function vis(d, M) { if (d.k === 'sk') return false; if (!d.s || d.s === editing) return true; var m = M[d.s]; return !(m && m.h); }

      // ── pasek narzędzi ──
      var btns = {};
      function addBtn(id, title, html) {
        var b = document.createElement('button'); b.type = 'button'; b.title = title; b.setAttribute('aria-label', title); b.innerHTML = html;
        bar.appendChild(b); btns[id] = b; return b;
      }
      function sep() { var s = document.createElement('div'); s.className = 'sep'; bar.appendChild(s); }
      TOOLS.forEach(function (t, i) { addBtn(t[0], t[1], t[2]).addEventListener('click', function () { setTool(tool === t[0] && t[0] !== 'cur' ? 'cur' : t[0]); }); if (i === 0) sep(); });
      sep();
      // 136: „Rysujesz na” — widoczny, gdy w górnym panelu jest kilka serii
      addBtn('on', '', I('<circle cx="9" cy="7" r="3.2"/><path d="M9 10.2V16"/>')).addEventListener('click', function (e) { e.stopPropagation(); toggleOn(); });
      var cb = addBtn('col', 'Kolor (nowe rysunki i zaznaczony)', '<span class="sw"></span>');
      var pop = null;
      cb.addEventListener('click', function (e) {
        e.stopPropagation();
        if (pop) { pop.remove(); pop = null; return; }
        pop = document.createElement('div'); pop.className = 'cld-pop'; pop.style.top = cb.offsetTop + 'px';
        COLORS.forEach(function (c) {
          var b = document.createElement('button'); b.type = 'button'; b.style.background = c; b.title = c; if (c === color) b.className = 'on';
          b.addEventListener('click', function (ev) {
            ev.stopPropagation(); color = c; try { localStorage.setItem('cl-draw-color', c); } catch (er) {}
            if (sel) { var d = find(sel); if (d) { d.c = c; commit(ST[sel.k]); } }
            pop.remove(); pop = null; syncBar(); render();
          });
          pop.appendChild(b);
        });
        bar.appendChild(pop);
      });
      document.addEventListener('click', function (e) {
        if (pop) { pop.remove(); pop = null; }
        var t = e.target;
        if (onp && !onp.contains(t)) { onp.remove(); onp = null; }
        if (sk.open && t.isConnected && !skEl.contains(t) && !btns.sk.contains(t) && !chips.contains(t)) closeSk();
      });
      addBtn('eye', '', '').addEventListener('click', function () {
        hidden = !hidden; try { localStorage.setItem('cl-draw-hide:' + page, hidden ? '1' : '0'); } catch (e) {}
        if (hidden) { sel = null; setTool('cur'); }
        syncBar(); render();
      });
      addBtn('del', 'Usuń zaznaczony rysunek (Delete)', I('<path d="M3 5h12M7 5V3h4v2M5 5l1 10h6l1-10"/>')).addEventListener('click', function () { if (sel) removeSel(); });
      var armed = 0, ALL_T = 'Usuń wszystkie robocze rysunki z tego wykresu — szkice zostają (kliknij dwa razy)';
      addBtn('all', ALL_T, I('<path d="M3 5h12M5 5l1 10h6l1-10M7.5 8l3 4M10.5 8l-3 4"/>')).addEventListener('click', function () {
        var b = btns.all, n = 0;
        allSt().forEach(function (st) { st.D.forEach(function (d) { if (rob(d)) n++; }); });
        if (!n) { toast('Brak roboczych rysunków — szkice usuwa się w okienku „Szkice”'); return; }
        if (Date.now() - armed < 3000) {
          allSt().forEach(function (st) { var l = st.D.length; st.D = st.D.filter(function (d) { return !rob(d); }); if (st.D.length !== l) commit(st); });
          sel = null; armed = 0; b.classList.remove('warn'); toast('Usunięto robocze rysunki (' + n + ')'); syncBar(); render(); return;
        }
        armed = Date.now(); b.classList.add('warn'); b.title = 'Kliknij jeszcze raz — usuń robocze rysunki (' + n + ')';
        setTimeout(function () { b.classList.remove('warn'); b.title = ALL_T; }, 3000);
      });
      sep();
      addBtn('link', 'Kopiuj link z widocznymi rysunkami — dla grupy', I('<path d="M7.5 10.5l3-3M6 8l-2 2a2.5 2.5 0 003.5 3.5l2-2M12 10l2-2a2.5 2.5 0 00-3.5-3.5l-2 2"/>')).addEventListener('click', function () {
        var st = stOn(), M = sketches().M;
        var d = st ? st.D.filter(function (x) { return vis(x, M); }) : [];
        if (!d.length) { toast('Brak widocznych rysunków na tej serii'); return; }
        var used = {}; d.forEach(function (x) { if (x.s) used[x.s] = 1; });
        var out = d.concat(st.D.filter(function (x) { return x.k === 'sk' && used[x.id]; }));
        var q = new URLSearchParams(location.search); q.set('rys', b64e(JSON.stringify({k: st.k, d: out})));
        var url = location.origin + location.pathname + '?' + q + location.hash;
        var ok = function () { toast('Skopiowano link z rysunkami (' + d.length + ')'); };
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(ok, function () { window.prompt('Link z rysunkami:', url); });
        else window.prompt('Link z rysunkami:', url);
      });
      // 131: zapis — konto albo tylko ta przeglądarka
      addBtn('cloud', '', '').addEventListener('click', function () {
        if (window.CLAuth) CLAuth.open(btns.cloud); else toast('Logowanie niedostępne');
      });
      sep();
      addBtn('sk', 'Szkice — zapisz, pokaż / ukryj, edytuj', I('<path d="M9 2l7 3.5-7 3.5-7-3.5z"/><path d="M2 9l7 3.5L16 9M2 12.5L9 16l7-3.5"/>')).addEventListener('click', function (e) {
        e.stopPropagation(); if (sk.open) closeSk(); else openSk();
      });
      function syncBar() {
        var on = cloudOn();
        btns.cloud.className = on ? 'cloud-on' : 'cloud-off';
        btns.cloud.innerHTML = on ? I('<path d="M5 14h8a3 3 0 00.5-6A4.5 4.5 0 004.6 7 3.5 3.5 0 005 14z"/><path d="M6.5 10.5l1.7 1.7 3.3-3.4"/>')
          : I('<path d="M5 14h8a3 3 0 00.5-6A4.5 4.5 0 004.6 7 3.5 3.5 0 005 14z"/><path d="M9 7.5v3M9 12.3v.2"/>');
        btns.cloud.title = on ? 'Rysunki zapisują się na Twoim koncie — na każdym urządzeniu te same'
          : 'Rysunki są zapisane tylko w tej przeglądarce — po wyczyszczeniu danych strony albo na innym urządzeniu ich nie będzie. Kliknij, żeby się zalogować i je zachować.';
        TOOLS.forEach(function (t) { btns[t[0]].classList.toggle('on', tool === t[0]); });
        btns.col.querySelector('.sw').style.background = color;
        btns.eye.innerHTML = I(hidden ? EYE_OFF : EYE);
        btns.eye.title = hidden ? 'Pokaż rysunki' : 'Ukryj wszystkie rysunki (zostają zapisane)';
        btns.eye.classList.toggle('on', hidden);
        btns.del.style.opacity = sel ? '1' : '.35';
        // „Rysujesz na”
        var r = stOn() && stOn().ref;
        btns.on.style.display = R.length > 1 ? '' : 'none';
        if (R.length > 1 && r) {
          var t = 'Rysujesz na: ' + (r.name || idOf(onKey)) + ' — kliknij, żeby wybrać inną serię';
          btns.on.title = t; btns.on.setAttribute('aria-label', t);
          btns.on.innerHTML = I('<circle cx="9" cy="7" r="3.2"/><path d="M9 10.2V16"/>') + '<span class="sdot" style="background:' + esc(r.color || '#888') + '"></span>';
        }
        // szkice — liczba widocznych
        var S = sketches(), nv = S.L.filter(function (m) { return m.here && !m.h; }).length;
        btns.sk.innerHTML = I('<path d="M9 2l7 3.5-7 3.5-7-3.5z"/><path d="M2 9l7 3.5L16 9M2 12.5L9 16l7-3.5"/>') + (nv ? '<span class="bdg">' + nv + '</span>' : '');
        btns.sk.classList.toggle('on', sk.open || !!editing);
        // telefon: zaznaczony rysunek przechwytuje dotyk (przesuwanie palcem bez przewijania strony), klik obok = odznacz
        svg.classList.toggle('act', !hidden && (tool !== 'cur' || (touch && !!sel)));
        svg.classList.toggle('ro', hidden);
        if (fab) fab.classList.toggle('on', bar.classList.contains('open'));
      }
      function setTool(t) { tool = t; wip = null; if (t !== 'cur') sel = null; syncBar(); render(); }
      var tt = null;
      function toast(s) {
        var x = wrap.querySelector('.cld-toast'); if (!x) { x = document.createElement('div'); x.className = 'cld-toast'; wrap.appendChild(x); }
        x.textContent = s; x.style.display = ''; clearTimeout(tt); tt = setTimeout(function () { x.style.display = 'none'; }, 2200);
      }
      function place(p, b) {   // okienko obok przycisku paska (telefon: od dołu ekranu — CSS)
        p.style.left = (bar.offsetLeft + bar.offsetWidth + 6) + 'px';
        var top = bar.offsetTop + b.offsetTop - bar.scrollTop, wh = wrap.clientHeight || 400;
        var mh = Math.max(260, Math.min(560, window.innerHeight - 24));
        p.style.maxHeight = mh + 'px';
        p.style.top = Math.max(0, Math.min(top, wh - Math.min(mh, p.scrollHeight || mh))) + 'px';
      }

      // ── „Rysujesz na” ──
      var onp = null;
      function toggleOn() {
        if (onp) { onp.remove(); onp = null; return; }
        onp = document.createElement('div'); onp.className = 'cld-onp';
        onp.innerHTML = '<div style="font-size:11px;color:#888;padding:0 4px 4px">Nowe rysunki przypinają się do serii:</div>' +
          R.map(function (r, i) { var k = page + ':' + r.id; return '<button type="button" class="o' + (k === onKey ? ' on' : '') + '" data-i="' + i + '"><span style="width:10px;height:10px;border-radius:50%;flex:none;background:' + esc(r.color || '#888') + '"></span>' + esc(r.name || r.id) + '</button>'; }).join('');
        onp.addEventListener('click', function (e) {
          e.stopPropagation(); var b = e.target.closest('[data-i]'); if (!b) return;
          var r = R[+b.getAttribute('data-i')]; if (!r) return;
          try { localStorage.setItem('cl-draw-on:' + page, r.id); } catch (er) {}
          onp.remove(); onp = null; wip = null; scope(true); toast('Rysujesz na: ' + (r.name || r.id));
        });
        wrap.appendChild(onp); place(onp, btns.on);
      }

      // ── przeliczanie czas / wartość ↔ piksele ──
      var G = null;   // geometria liczona raz na klatkę; G.r / G.ref = seria, względem której liczymy wartości
      // biblioteka nie przelicza ułamkowych pozycji (logicalToCoordinate(5839.4) = 0) — liczymy między sąsiednimi świecami
      function L2C(l) { var i = Math.floor(l), f = l - i, c0 = ts.logicalToCoordinate(i); if (c0 == null || !f) return c0; var c1 = ts.logicalToCoordinate(i + 1); return c1 == null ? c0 : c0 + f * (c1 - c0); }
      function C2L(x) {
        var l = ts.coordinateToLogical(x); if (l == null) return null;
        var c = ts.logicalToCoordinate(l), c1 = ts.logicalToCoordinate(l + 1);
        return c == null || c1 == null || c1 === c ? l : l + (x - c) / (c1 - c);
      }
      function tAt(i) { var c = ts.logicalToCoordinate(i); if (c == null) return null; return num(ts.coordinateToTime(c)); }
      function geom() {
        if (!R.length) return null;
        var last = ts.timeToIndex(4e9, true), first = ts.timeToIndex(-4e9, true);
        if (last == null || first == null) return null;
        var tl = tAt(last), tp = tAt(Math.max(first, last - 1)), tf = tAt(first), tn = tAt(Math.min(last, first + 1));
        if (tl == null || tf == null) return null;
        var pane = chart.panes()[0], W = ts.width(), H = pane ? pane.getHeight() : 0;
        var cr = chart.chartElement().getBoundingClientRect(), wr = wrap.getBoundingClientRect();
        var lw = 0; try { lw = chart.priceScale('left').width(); } catch (e) {}
        return {r: null, ref: null, first: first, last: last, tl: tl, tf: tf, dtE: (tl - tp) || 86400, dtS: (tn - tf) || 86400, W: W, H: H,
          left: cr.left - wr.left + lw, top: cr.top - wr.top};
      }
      function use(st) { if (G && st) { G.ref = st.ref; G.r = st.ref.series; } return !!(G && st); }
      function lg(t) {   // czas → pozycja logiczna (ułamkowa)
        if (t >= G.tl) return G.last + (t - G.tl) / G.dtE;
        if (t <= G.tf) return G.first + (t - G.tf) / G.dtS;
        var i = ts.timeToIndex(t, true); if (i == null) return null;
        var ti = tAt(i); if (ti == null) return i;
        if (ti > t && i > G.first) { i--; ti = tAt(i); }
        var tn = tAt(i + 1); if (tn == null || tn === ti) return i;
        return i + (t - ti) / (tn - ti);
      }
      function X(t) { var l = lg(t); if (l == null) return null; return L2C(l); }
      function Y(v) { return G.r.priceToCoordinate(v); }
      function T(x) {
        var l = C2L(x); if (l == null) return null;
        if (l >= G.last) return G.tl + (l - G.last) * G.dtE;
        if (l <= G.first) return G.tf + (l - G.first) * G.dtS;
        var i = Math.floor(l), ti = tAt(i), tn = tAt(i + 1);
        if (ti == null) return null; if (tn == null) return ti;
        return ti + (l - i) * (tn - ti);
      }
      function V(y) { return G.r.coordinateToPrice(y); }
      function fmtV(v) { try { return G.ref && G.ref.fmt ? G.ref.fmt(v) : G.r.priceFormatter().format(v); } catch (e) { return pl(v, 2); } }
      function fmtT(t) {
        if (o.timeLabel) return o.timeLabel(t);
        var d = new Date(t * 1000), p = function (n) { return (n < 10 ? '0' : '') + n; };
        var day = p(d.getUTCDate()) + '.' + p(d.getUTCMonth() + 1) + '.' + d.getUTCFullYear();
        if (t % 86400 === 0) return day;
        return window.CLTZ && CLTZ.fmt ? CLTZ.fmt(t) : day + ' ' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes());
      }

      // ── zapis ──
      function commit(st) { if (st) { save(st.k, st.D); cloudSave(st); } syncBar(); render(); notice(); if (sk.open) renderSk(); }
      // ── 131: zapis na koncie (Firestore users/{uid}/scopes/{klucz}, rysunki jako tekst JSON w polu j) ──
      function cloudOn() { var A = window.CLAuth; return !!(A && A.user && A.allowed && A.F); }
      function cdoc(k) { var A = CLAuth; return A.F.doc(A.db, 'users', A.user.uid, 'scopes', encodeURIComponent(k)); }
      function cloudDetach(st) {
        var c = st.cloud;
        if (c.unsub) { try { c.unsub(); } catch (e) {} }
        c.unsub = null; c.key = null; c.uid = null;
      }
      function cloudAttach(st) {
        cloudDetach(st);
        if (!cloudOn()) return;
        var A = CLAuth, k = st.k, uid = A.user.uid, c = st.cloud; c.key = k; c.uid = uid;
        c.unsub = A.F.onSnapshot(cdoc(k), function (s) {
          if (ST[k] !== st || c.key !== k || (s.metadata && s.metadata.hasPendingWrites)) return;
          var remote = null; try { remote = s.exists() ? JSON.parse(s.data().j || '[]') : null; } catch (e) { remote = null; }
          var mk = 'cl-draw-mig:' + uid + ':' + k, mig = false; try { mig = localStorage.getItem(mk) === '1'; } catch (e) {}
          if (!mig) {   // pierwsze połączenie tego wykresu z kontem — dołącz rysunki z przeglądarki
            var out = (remote || []).slice(), ids = {};
            out.forEach(function (d) { ids[d.id] = 1; });
            var added = 0; st.D.forEach(function (d) { if (!ids[d.id]) { out.push(d); if (d.k !== 'sk') added++; } });
            try { localStorage.setItem(mk, '1'); } catch (e) {}
            st.D = out; save(k, st.D);
            if (added || !remote) cloudSave(st);
            if (added) toast('Rysunki z tej przeglądarki dodane do konta (' + added + ')');
          } else if (remote) { st.D = remote; save(k, st.D); }
          if (sel && !find(sel)) sel = null;
          if (!drag && !wip) { syncBar(); sig = ''; if (sk.open) renderSk(); }
        }, function () { toast('Nie udało się wczytać rysunków z konta — działa zapis w przeglądarce'); });
      }
      function cloudPut(k, D) {
        var A = CLAuth;
        return A.F.setDoc(cdoc(k), {j: JSON.stringify(D), n: D.length, page: page, at: A.F.serverTimestamp()})
          .catch(function () { toast('Nie zapisano na koncie — rysunek jest w tej przeglądarce'); });
      }
      function cloudSave(st) {
        var c = st.cloud;
        if (!cloudOn() || c.key !== st.k) return;
        var k = st.k, data = st.D.slice();
        clearTimeout(c.timer);
        c.timer = setTimeout(function () { cloudPut(k, data); }, 600);
      }
      function persistOther(k, D) { save(k, D); if (cloudOn()) cloudPut(k, D); }
      // szkice z serii, których nie ma na wykresie, a są na koncie (np. z innego urządzenia) — raz po otwarciu okienka
      function fetchOthers() {
        if (sk.fetched || !o.refs || !cloudOn()) return;
        sk.fetched = true;
        var A = CLAuth, F = A.F; if (!F.getDocs || !F.query || !F.where || !F.collection) return;
        var g = ''; try { g = o.group ? o.group() || '' : ''; } catch (e) {}
        F.getDocs(F.query(F.collection(A.db, 'users', A.user.uid, 'scopes'), F.where('page', '==', page))).then(function (qs) {
          var ch = false;
          qs.forEach(function (s) {
            var k = decodeURIComponent(s.id); if (ST[k] || k.indexOf(page + ':' + g) !== 0) return;
            var D = null; try { D = JSON.parse(s.data().j || '[]'); } catch (e) {}
            if (Array.isArray(D) && D.some(function (d) { return d.k === 'sk'; })) { save(k, D); ch = true; }
          });
          if (ch && sk.open) renderSk();
        }).catch(function () {});
      }
      if (window.CLAuth) CLAuth.on(function () { sk.fetched = false; allSt().forEach(cloudAttach); syncBar(); var n = wrap.querySelector('.cld-note'); if (n && cloudOn()) n.remove(); });
      // informacja dla niezalogowanych — raz na sesję, po pierwszym rysunku
      function notice() {
        if (cloudOn() || !allSt().some(function (st) { return st.D.length; })) return;
        try { if (sessionStorage.getItem('cl-draw-note')) return; sessionStorage.setItem('cl-draw-note', '1'); } catch (e) {}
        var n = document.createElement('div'); n.className = 'cld-note'; n.setAttribute('role', 'status');
        n.innerHTML = '<b>Rysunek jest zapisany tylko w tej przeglądarce.</b> Zniknie po wyczyszczeniu danych przeglądarki i nie pojawi się na innych urządzeniach. Zaloguj się, a rysunki zapiszą się na Twoim koncie i będą widoczne wszędzie.' +
          '<div class="r"><button type="button" data-l>Zaloguj</button><button type="button" data-x>Rozumiem</button></div>';
        // telefon: po stuknięciu przeglądarka wysyła jeszcze kliknięcie w to samo miejsce — ramka pojawia się chwilę później
        // i przez 0,6 s nie przyjmuje kliknięć, żeby nie zamknęło jej to samo stuknięcie, którym narysowano linię
        var t0 = 0, live = function () { return Date.now() - t0 > 600; };
        n.querySelector('[data-l]').onclick = function (e) { e.stopPropagation(); if (!live()) return; if (window.CLAuth) CLAuth.open(btns.cloud); n.remove(); };
        n.querySelector('[data-x]').onclick = function () { if (live()) n.remove(); };
        setTimeout(function () { t0 = Date.now(); if (!cloudOn()) wrap.appendChild(n); }, 450);
      }
      function removeSel() { var st = ST[sel.k]; if (st) st.D = st.D.filter(function (d) { return d.id !== sel.id; }); sel = null; commit(st); }
      function refsNow() {
        var def = null; try { def = o.ref ? o.ref() : null; } catch (e) {}
        if (!def || !def.series) { var ps = chart.panes()[0]; var ss = ps ? ps.getSeries() : [];
          var sid = function (s) { return s.options().priceScaleId || 'right'; };   // bez priceScaleId = prawa oś
          var pick = ss.filter(function (s) { return sid(s) === 'right'; })[0] || ss.filter(function (s) { return sid(s) === 'left'; })[0];
          def = pick ? {id: (def && def.id) || 'main', series: pick} : null; }
        var list = null; try { list = o.refs ? o.refs() : null; } catch (e) {}
        list = (list || []).filter(function (r) { return r && r.id && r.series; });
        if (!list.length && def) list = [def];
        return {def: def, list: list};
      }
      function scope(force) {
        var q = refsNow(), keys = {}, ch = !!force;
        R = q.list;
        R.forEach(function (r) {
          var k = page + ':' + r.id; keys[k] = 1;
          if (!ST[k]) { ST[k] = {k: k, ref: r, D: load(k), cloud: {}}; cloudAttach(ST[k]); ch = true; }
          ST[k].ref = r;
        });
        Object.keys(ST).forEach(function (k) { if (!keys[k]) { cloudDetach(ST[k]); delete ST[k]; ch = true; } });
        var want = null; try { want = localStorage.getItem('cl-draw-on:' + page); } catch (e) {}
        var nk = want && keys[page + ':' + want] ? page + ':' + want : q.def && keys[page + ':' + q.def.id] ? page + ':' + q.def.id : R[0] ? page + ':' + R[0].id : null;
        if (nk !== onKey) { onKey = nk; wip = null; ch = true; }
        if (sel && !ST[sel.k]) sel = null;
        if (ch) { syncBar(); sig = ''; if (sk.open) renderSk(); }
      }

      // ── szkice ──
      function metaFrom(id) { var m = sketches(true).M[id]; return m ? {id: id, k: 'sk', p: [], n: m.n, c: m.c, h: m.h, at: m.at || Date.now()} : null; }
      function eachCopy(fn) {   // zmiana we wszystkich zestawach tej zakładki (na wykresie i poza nim)
        allSt().forEach(function (st) { if (fn(st.D)) { save(st.k, st.D); cloudSave(st); } });
        others().forEach(function (x) { if (fn(x.D)) persistOther(x.k, x.D); });
        syncBar(); sig = ''; render(); if (sk.open) renderSk();
      }
      function setMeta(id, patch) {
        eachCopy(function (D) { var c = false; D.forEach(function (d) { if (d.k === 'sk' && d.id === id) { for (var p in patch) d[p] = patch[p]; c = true; } }); return c; });
      }
      function saveSketch(name, c) {
        var id = 'sk' + uid(), at = Date.now(), n = 0;
        allSt().forEach(function (st) {
          var any = 0; st.D.forEach(function (d) { if (rob(d)) { d.s = id; any++; } });
          if (any) { n += any; st.D.push({id: id, k: 'sk', p: [], n: name, c: c, h: 0, at: at}); save(st.k, st.D); cloudSave(st); }
        });
        sel = null; sk.form = null;
        syncBar(); render(); renderSk(); notice();
        toast('Zapisano szkic „' + name + '” (' + nRys(n) + ')');
      }
      function delSketch(id) {
        if (editing === id) editing = null;
        if (sel) { var d = find(sel); if (d && d.s === id) sel = null; }
        eachCopy(function (D) { var l = D.length; for (var i = D.length - 1; i >= 0; i--) if (D[i].id === id || D[i].s === id) D.splice(i, 1); return D.length !== l; });
      }
      function startEdit(id) {
        var m = sketches(true).M[id]; if (!m) return;
        editing = id; sel = null; if (tool !== 'cur') setTool('cur');
        if (m.h) setMeta(id, {h: 0}); else { syncBar(); render(); if (sk.open) renderSk(); }
      }
      function endEdit() { editing = null; sel = null; syncBar(); render(); if (sk.open) renderSk(); }
      // nowy rysunek w czasie edycji szkicu trafia do szkicu (w zestawie tej serii dopisujemy kopię opisu szkicu)
      function tagNew(st, d) {
        if (!editing) return d;
        d.s = editing;
        if (!st.D.some(function (x) { return x.k === 'sk' && x.id === editing; })) { var m = metaFrom(editing); if (m) st.D.push(m); }
        return d;
      }

      var skEl = document.createElement('div'); skEl.className = 'cld-sk'; skEl.setAttribute('role', 'dialog'); skEl.setAttribute('aria-label', 'Szkice');
      function openSk() { if (onp) { onp.remove(); onp = null; } sk.open = true; sk.menu = sk.ren = null; wrap.appendChild(skEl); renderSk(); fetchOthers(); syncBar(); }
      function closeSk() { if (!sk.open) return; sk.open = false; sk.form = sk.menu = sk.ren = null; skEl.remove(); syncBar(); }
      function row(m, present) {
        var ed = editing === m.id, off = !present || (m.h && !ed);
        var nk = Object.keys(m.keys), names = nk.map(function (k) { return nameOf(k) + (ST[k] || !present ? '' : ' (brak na wykresie)'); });
        var sub = [];
        if (ed) sub.push('edytujesz');
        else if (m.h && present) sub.push('ukryty');
        if (o.refs) sub.push('na: ' + names.join(', '));
        if (!present) sub.push('tej serii nie ma teraz na wykresie');
        else sub.push(nRys(m.cnt));
        if (m.at && !ed) sub.push(dmy(m.at));
        var h = '<div class="row' + (ed ? ' ed' : '') + (off ? ' off' : '') + '" data-id="' + esc(m.id) + '">' +
          '<button type="button" class="ey" data-a="eye"' + (present && !ed ? '' : ' disabled') + ' title="' + (m.h ? 'Pokaż szkic' : 'Ukryj szkic') + '" aria-label="' + (m.h ? 'Pokaż' : 'Ukryj') + ' szkic ' + esc(m.n) + '">' + I(m.h && !ed ? EYE_OFF : EYE) + '</button>' +
          '<span class="dt" style="background:' + esc(m.c) + (off ? ';opacity:.5' : '') + '"></span>';
        if (sk.ren === m.id) h += '<input class="ri" data-a="ren-in" value="' + esc(m.n) + '" maxlength="60" aria-label="Nowa nazwa szkicu"><button type="button" class="b p" data-a="ren-ok">OK</button>';
        else {
          h += '<div class="nm"><span>' + esc(m.n) + '</span><small>' + esc(sub.join(' · ')) + '</small></div>';
          if (!present) { if (o.add) h += '<button type="button" class="b" data-a="add" style="color:var(--blue,#5b9cf6)">Dodaj serię</button>'; }
          else h += ed ? '<button type="button" class="b y" data-a="done">Gotowe</button>' : '<button type="button" class="b" data-a="edit">Edytuj</button>';
          h += '<button type="button" class="mo" data-a="menu" title="Więcej" aria-label="Więcej — ' + esc(m.n) + '">⋯</button>';
        }
        h += '</div>';
        if (sk.menu === m.id) {
          var armedDel = sk.del && sk.del.id === m.id && Date.now() - sk.del.t < 4000;
          h += '<div class="menu"><button type="button" class="b" data-a="ren" data-id="' + esc(m.id) + '">Zmień nazwę</button>' +
            '<button type="button" class="b' + (armedDel ? ' r' : '') + '" data-a="del" data-id="' + esc(m.id) + '">' + (armedDel ? 'Na pewno usunąć? (' + nRys(m.cnt) + ')' : 'Usuń szkic') + '</button></div>';
        }
        return h;
      }
      function renderSk() {
        if (!sk.open) return;
        var S = sketches(true), nr = 0;
        allSt().forEach(function (st) { st.D.forEach(function (d) { if (rob(d)) nr++; }); });
        var here = S.L.filter(function (m) { return m.here; }), gone = S.L.filter(function (m) { return !m.here; });
        var on = stOn(), em = editing && S.M[editing];
        var h = '<div class="hd"><b>Szkice</b><span class="mu">' + esc(on && R.length > 1 ? 'nowe rysunki: ' + (on.ref.name || idOf(on.k)) : '') + '</span>' +
          '<button type="button" class="x" data-a="close" title="Zamknij" aria-label="Zamknij">×</button></div>';
        if (sk.form) {
          h += '<div class="frm"><b style="font-size:13px">Zapisz jako szkic</b>' +
            '<input data-a="nm" value="' + esc(sk.form.n) + '" maxlength="60" aria-label="Nazwa szkicu">' +
            '<div class="sws"><span class="mu" style="margin-right:4px">Kolor na liście</span>' + COLORS.map(function (c) { return '<button type="button" data-a="fc" data-c="' + c + '" class="' + (c === sk.form.c ? 'on' : '') + '" style="background:' + c + '" aria-label="Kolor ' + c + '"></button>'; }).join('') + '</div>' +
            '<div class="mu">Do szkicu trafi ' + nRys(nr) + ' z „Roboczego”. Szkic zostaje widoczny.</div>' +
            '<div class="r"><button type="button" class="b" data-a="f-no">Anuluj</button><button type="button" class="b p" data-a="f-ok">Zapisz</button></div></div>';
        } else {
          h += '<div class="row rob"><span class="dt" style="background:#f0f0f0"></span><div class="nm"><span>Roboczy</span><small>' +
            (em ? 'nowe rysunki trafiają teraz do szkicu „' + esc(em.n) + '”' + (nr ? ' · ' + nRys(nr) + ' roboczych' : '') : nr ? nRys(nr) + ' niezapisanych w szkicu' : 'pusto — to, co narysujesz, trafia tutaj') +
            '</small></div><button type="button" class="b p" data-a="save"' + (nr ? '' : ' disabled') + '>Zapisz jako szkic</button></div>';
        }
        h += '<div class="lb">Szkice tego wykresu</div>';
        h += here.length ? here.map(function (m) { return row(m, true); }).join('') : '<div class="em">' + (gone.length ? 'Brak szkiców na seriach, które są teraz na wykresie.' : 'Brak zapisanych szkiców. Narysuj coś i kliknij „Zapisz jako szkic”.') + '</div>';
        if (gone.length) h += '<div class="lb">Serii nie ma teraz na wykresie</div>' + gone.map(function (m) { return row(m, false); }).join('');
        if (o.refs) h += '<div class="ft">Każdy szkic trzyma się swojej serii. Dodanie albo usunięcie innej serii nic w szkicach nie zmienia.</div>';
        skEl.innerHTML = h;
        place(skEl, btns.sk);
        var f = skEl.querySelector('[data-a=nm]'); if (f && sk.form && sk.form.focus) { sk.form.focus = false; f.focus(); f.select(); }
        var ri = skEl.querySelector('[data-a=ren-in]'); if (ri && sk.renFocus) { sk.renFocus = false; ri.focus(); ri.select(); }
      }
      function doRen() { var i = skEl.querySelector('[data-a=ren-in]'), id = sk.ren; sk.ren = null; sk.menu = null; if (i && i.value.trim()) setMeta(id, {n: i.value.trim().slice(0, 60)}); else renderSk(); }
      function doSave() { var i = skEl.querySelector('[data-a=nm]'); var n = (i && i.value.trim()) || sk.form.n; saveSketch(n.slice(0, 60), sk.form.c); }
      skEl.addEventListener('click', function (e) {
        e.stopPropagation();
        var b = e.target.closest('[data-a]'); if (!b || b.disabled) return;
        var a = b.getAttribute('data-a'), rw = b.closest('[data-id]'), id = rw && rw.getAttribute('data-id');
        if (a === 'close') closeSk();
        else if (a === 'save') { var used = {}; sketches(true).L.forEach(function (m) { used[m.c] = 1; }); sk.form = {n: 'Szkic ' + dmy(Date.now()), c: COLORS.filter(function (c) { return !used[c]; })[0] || COLORS[0], focus: true}; renderSk(); }
        else if (a === 'fc') { var nm = skEl.querySelector('[data-a=nm]'); if (nm) sk.form.n = nm.value; sk.form.c = b.getAttribute('data-c'); renderSk(); }
        else if (a === 'f-no') { sk.form = null; renderSk(); }
        else if (a === 'f-ok') doSave();
        else if (a === 'eye') { var m = sketches(true).M[id]; if (m) setMeta(id, {h: m.h ? 0 : 1}); }
        else if (a === 'edit') startEdit(id);
        else if (a === 'done') endEdit();
        else if (a === 'menu') { sk.menu = sk.menu === id ? null : id; sk.del = 0; renderSk(); }
        else if (a === 'ren') { sk.ren = id; sk.renFocus = true; renderSk(); }
        else if (a === 'ren-ok') doRen();
        else if (a === 'del') { if (sk.del && sk.del.id === id && Date.now() - sk.del.t < 4000) { sk.del = 0; sk.menu = null; delSketch(id); toast('Usunięto szkic'); } else { sk.del = {id: id, t: Date.now()}; renderSk(); } }
        else if (a === 'add') { var mm = sketches(true).M[id]; var k = mm && Object.keys(mm.keys).filter(function (x) { return !ST[x]; })[0]; if (k && o.add) { try { o.add(idOf(k)); } catch (er) {} } }
      });
      skEl.addEventListener('keydown', function (e) {
        e.stopPropagation();
        var a = e.target.getAttribute && e.target.getAttribute('data-a');
        if (e.key === 'Enter' && a === 'nm') doSave();
        else if (e.key === 'Enter' && a === 'ren-in') doRen();
        else if (e.key === 'Escape') { if (sk.form || sk.ren) { sk.form = null; sk.ren = null; renderSk(); } else closeSk(); }
      });
      // etykiety widocznych szkiców nad osią czasu; w czasie edycji — „Edytujesz … Gotowe”
      chips.addEventListener('click', function (e) {
        e.stopPropagation();
        if (e.target.closest('[data-a=done]')) { endEdit(); return; }
        if (!sk.open) openSk();
      });
      function renderChips(S) {
        if (!G || hidden) { chips.style.display = 'none'; return; }
        var L = S.L.filter(function (m) { return m.here && (!m.h || m.id === editing); });
        if (!L.length) { chips.style.display = 'none'; return; }
        chips.style.display = '';
        chips.style.left = (G.left + 6) + 'px'; chips.style.top = (G.top + G.H - 6) + 'px';
        var h = L.map(function (m) {
          if (m.id === editing) return '<button type="button" class="cld-chip ed" title="Nowe rysunki trafiają do tego szkicu"><i style="background:' + esc(m.c) + '"></i>Edytujesz <b>' + esc(m.n) + '</b><span data-a="done">Gotowe</span></button>';
          return '<button type="button" class="cld-chip" title="Szkic „' + esc(m.n) + '” — kliknij, żeby otworzyć listę szkiców"><i style="background:' + esc(m.c) + '"></i>' + esc(m.n) + '</button>';
        }).join('');
        if (chips.__h !== h) { chips.innerHTML = h; chips.__h = h; }
      }

      // ── rysowanie ──
      function line(g, x1, y1, x2, y2, c, w, dash) { return el('line', {x1: x1, y1: y1, x2: x2, y2: y2, stroke: c, 'stroke-width': w || 1.5, 'stroke-dasharray': dash || null}, g); }
      function label(g, x, y, s, c, anchor) {
        var t = el('text', {x: x, y: y, fill: c, 'text-anchor': anchor || 'start'}, g); t.textContent = s; return t;
      }
      function tag(g, x, y, s, c, right) {   // napis na pełnym tle (oś)
        var w = s.length * 6.8 + 10, xx = right ? x - w : x;
        el('rect', {x: xx, y: y - 9, width: w, height: 18, rx: 3, fill: c}, g);
        var t = el('text', {x: xx + 5, y: y + 4, fill: '#0f0f0f', style: 'stroke:none'}, g); t.textContent = s;
      }
      function draw(d, isSel, k, lock) {
        var c = d.c || COLORS[0], g = el('g', {'data-id': d.id, 'data-k': k, 'class': lock ? 'lk' : null}, svg), P = d.p.map(function (p) { return [X(p[0]), Y(p[1])]; });
        if (P.some(function (p) { return p[0] == null || p[1] == null; }) && d.k !== 'v' && d.k !== 'h') return;
        var hit = function (x1, y1, x2, y2) { el('line', {x1: x1, y1: y1, x2: x2, y2: y2, stroke: 'transparent', 'stroke-width': HW, 'class': 'hit'}, g); };
        var a = P[0], b = P[1] || P[0];
        if (!a) return;
        if (d.k === 'h') { if (a[1] == null) return; line(g, 0, a[1], G.W, a[1], c, 1.5); hit(0, a[1], G.W, a[1]); tag(g, G.W - 2, a[1], fmtV(d.p[0][1]), c, true); }
        else if (d.k === 'v') { if (a[0] == null) return; line(g, a[0], 0, a[0], G.H, c, 1.5); hit(a[0], 0, a[0], G.H); tag(g, a[0] + 3, G.H - 12, fmtT(d.p[0][0]), c); }
        else if (d.k === 'tl' || d.k === 'ar') {
          line(g, a[0], a[1], b[0], b[1], c, 2); hit(a[0], a[1], b[0], b[1]);
          if (d.k === 'ar') { var an = Math.atan2(b[1] - a[1], b[0] - a[0]), L = 12;
            el('path', {d: 'M' + b[0] + ' ' + b[1] + 'L' + (b[0] - L * Math.cos(an - .45)) + ' ' + (b[1] - L * Math.sin(an - .45)) + 'L' + (b[0] - L * Math.cos(an + .45)) + ' ' + (b[1] - L * Math.sin(an + .45)) + 'Z', fill: c}, g); }
        }
        else if (d.k === 'rc') {
          var x = Math.min(a[0], b[0]), y = Math.min(a[1], b[1]), w = Math.abs(b[0] - a[0]), h = Math.abs(b[1] - a[1]);
          el('rect', {x: x, y: y, width: w, height: h, fill: hexA(c, .13), stroke: c, 'stroke-width': 1.5, 'class': 'hitf'}, g);
        }
        else if (d.k === 'ms') {
          var v1 = d.p[0][1], v2 = d.p[1][1], up = v2 >= v1, mc = up ? '#4caf7d' : '#e05252';
          var x0 = Math.min(a[0], b[0]), y0 = Math.min(a[1], b[1]);
          el('rect', {x: x0, y: y0, width: Math.abs(b[0] - a[0]), height: Math.abs(b[1] - a[1]), fill: hexA(mc, .14), stroke: hexA(mc, .5), 'class': 'hitf'}, g);
          var mx = (a[0] + b[0]) / 2; line(g, mx, a[1], mx, b[1], mc, 1.2); line(g, a[0], (a[1] + b[1]) / 2, b[0], (a[1] + b[1]) / 2, mc, 1.2, '3 3');
          var pct = v1 > 0 && v2 > 0 ? sgn((v2 / v1 - 1) * 100, 2) + '%' : null;
          var dv = v2 - v1, dvs = (dv > 0 ? '+' : dv < 0 ? '−' : '') + fmtV(Math.abs(dv)).replace(/^[−-]/, '');
          var dt = Math.abs(d.p[1][0] - d.p[0][0]) / 86400, bars = Math.round(Math.abs(lg(d.p[1][0]) - lg(d.p[0][0])));
          var dts = dt >= 2 ? Math.round(dt) + ' dni' : dt >= 1 ? pl(dt, 1) + ' dnia' : Math.round(dt * 24) + ' h';
          var l1 = (pct ? pct + '  (' + dvs + ')' : dvs), l2 = dts + ' · ' + bars + (bars === 1 ? ' świeca' : (bars % 10 >= 2 && bars % 10 <= 4 && (bars % 100 < 10 || bars % 100 >= 20)) ? ' świece' : ' świec');
          var bw = Math.max(l1.length, l2.length) * 6.8 + 14, by = up ? Math.min(a[1], b[1]) - 42 : Math.max(a[1], b[1]) + 6;
          if (by < 2) by = Math.max(a[1], b[1]) + 6; if (by + 38 > G.H) by = Math.min(a[1], b[1]) - 42;
          var bx = Math.min(Math.max(2, mx - bw / 2), G.W - bw - 2);
          el('rect', {x: bx, y: by, width: bw, height: 36, rx: 5, fill: '#141414', stroke: mc}, g);
          var t1 = el('text', {x: bx + 7, y: by + 15, fill: '#fff', style: 'stroke:none'}, g); t1.textContent = l1;
          var t2 = el('text', {x: bx + 7, y: by + 30, fill: '#bbb', style: 'stroke:none'}, g); t2.textContent = l2;
        }
        else if (d.k === 'fb') {
          var xl = Math.min(a[0], b[0]), xr = Math.max(a[0], b[0]), va = d.p[0][1], vb = d.p[1][1];
          var ys = FIB.map(function (f) { var v = vb + (va - vb) * f; return [f, v, Y(v)]; });
          for (var i = 0; i < ys.length - 1; i++) if (ys[i][2] != null && ys[i + 1][2] != null)
            el('rect', {x: xl, y: Math.min(ys[i][2], ys[i + 1][2]), width: xr - xl, height: Math.abs(ys[i + 1][2] - ys[i][2]), fill: hexA(c, i % 2 ? .05 : .1)}, g);
          ys.forEach(function (q) { if (q[2] == null) return; line(g, xl, q[2], xr, q[2], c, q[0] === 0 || q[0] === 1 ? 1.5 : 1); label(g, xl + 4, q[2] - 3, pl(q[0], 3).replace(/,?0+$/, '').replace(/^0$/, '0') + ' (' + fmtV(q[1]) + ')', c); });
          line(g, a[0], a[1], b[0], b[1], hexA(c, .5), 1, '4 4');
          el('rect', {x: xl, y: Math.min(a[1], b[1]), width: Math.max(4, xr - xl), height: Math.abs(b[1] - a[1]), fill: 'transparent', 'class': 'hitf'}, g);
        }
        else if (d.k === 'br') {
          var pts = P.filter(function (p) { return p[0] != null && p[1] != null; }).map(function (p) { return p[0] + ',' + p[1]; }).join(' ');
          el('polyline', {points: pts, fill: 'none', stroke: c, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}, g);
          el('polyline', {points: pts, fill: 'none', stroke: 'transparent', 'stroke-width': HW, 'class': 'hit'}, g);
        }
        else if (d.k === 'tx') {
          var t = el('text', {x: a[0], y: a[1], fill: c, 'class': 'tx hitf'}, g); t.textContent = d.txt || '';
        }
        if (isSel && d.k !== 'br') d.p.forEach(function (p, j) {
          var x = d.k === 'h' ? G.W / 2 : P[j][0], y = d.k === 'v' ? G.H / 2 : P[j][1];
          if (x != null && y != null) el('circle', {cx: x, cy: y, r: HR, fill: '#0f0f0f', stroke: c, 'stroke-width': 2, 'class': 'hd', 'data-h': j}, g);
        });
        if (isSel && d.k === 'br') g.setAttribute('opacity', '.8');
      }
      var sig = '';
      function render() {
        G = geom();
        while (svg.firstChild) svg.removeChild(svg.firstChild);
        if (!G) { svg.style.display = 'none'; chips.style.display = 'none'; return; }
        svg.style.display = '';
        svg.style.left = G.left + 'px'; svg.style.top = G.top + 'px'; svg.setAttribute('width', G.W); svg.setAttribute('height', G.H);
        svg.style.width = G.W + 'px'; svg.style.height = G.H + 'px';
        var S = sketches();
        renderChips(S);
        if (hidden) return;
        allSt().forEach(function (st) {
          use(st);
          st.D.forEach(function (d) { if (vis(d, S.M) && !(wip && d === wip)) draw(d, isSel(st, d), st.k, !!d.s && d.s !== editing); });
        });
        if (wip && use(stOn())) draw(wip, true, onKey, false);
      }
      function frame() {
        {
          scope();
          var vr = ts.getVisibleLogicalRange(), s = [onKey, vr && vr.from, vr && vr.to, ts.width(), hidden, editing,
            chart.panes()[0] && chart.panes()[0].getHeight(), wrap.getBoundingClientRect().width];
          allSt().forEach(function (st) { var r = st.ref.series; s.push(st.k, st.D.length, r.priceToCoordinate(1), r.priceToCoordinate(1000)); });
          s = s.join('|');
          if (s !== sig && !drag) { sig = s; render(); }
        }
        requestAnimationFrame(frame);
      }

      // ── mysz ──
      function pos(e) { var r = svg.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
      // punkt przyklejony do najbliższej świecy (jak w TradingView); pędzel — bez przyklejania
      function Ts(x) {
        var l = C2L(x); if (l == null) return null; l = Math.round(l);
        if (l >= G.last) return G.tl + (l - G.last) * G.dtE;
        if (l <= G.first) return G.tf + (l - G.first) * G.dtS;
        return tAt(l);
      }
      function pt(e, free) { var p = pos(e); var t = free ? T(p[0]) : Ts(p[0]), v = V(p[1]); return t == null || v == null ? null : [Math.round(t), rnd(v)]; }
      var two = {tl: 1, ar: 1, rc: 1, fb: 1, ms: 1};
      function add(d) { var st = stOn(); st.D.push(tagNew(st, d)); sel = {k: st.k, id: d.id}; }
      svg.addEventListener('pointerdown', function (e) {
        if (e.button !== 0 || hidden) return;
        G = geom(); if (!G) return;
        if (tool === 'cur') {
          var g = e.target.closest('g[data-id]');
          if (!g || g.classList.contains('lk')) { if (sel) { sel = null; syncBar(); render(); } return; }
          var st = ST[g.getAttribute('data-k')]; if (!use(st)) return;
          var q0 = pt(e); if (!q0) return;
          e.preventDefault(); e.stopPropagation();
          sel = {k: st.k, id: g.getAttribute('data-id')}; var d = find(sel); if (!d) return;
          var h = e.target.getAttribute('data-h');
          drag = {st: st, d: d, h: h == null ? null : +h, q0: q0, p0: JSON.parse(JSON.stringify(d.p)), moved: false};
          svg.setPointerCapture(e.pointerId); syncBar(); render(); return;
        }
        if (!use(stOn())) return;
        var q = pt(e); if (!q) return;
        e.preventDefault(); e.stopPropagation();
        if (tool === 'tx') { askText(pos(e), q, stOn(), null); return; }
        if (tool === 'h' || tool === 'v') { var n = {id: uid(), k: tool, c: color, p: [q]}; setTool('cur'); add(n); commit(stOn()); return; }
        if (tool === 'br') { wip = {id: uid(), k: 'br', c: color, p: [q]}; drag = {brush: true, last: pos(e)}; svg.setPointerCapture(e.pointerId); render(); return; }
        if (two[tool]) {
          if (wip && wip.second) { wip.p[1] = q; finish(); return; }
          wip = {id: uid(), k: tool, c: color, p: [q, q]}; drag = {make: true, start: pos(e)}; svg.setPointerCapture(e.pointerId); render();
        }
      });
      svg.addEventListener('pointermove', function (e) {
        if (!G) return;
        if (!use(drag && drag.st ? drag.st : stOn())) return;
        if (wip && wip.second && !drag) { var q2 = pt(e); if (q2) { wip.p[1] = q2; render(); } return; }
        if (!drag) return;
        var q = pt(e); if (!q) return;
        if (drag.brush) { q = pt(e, true) || q; var p = pos(e); if (Math.hypot(p[0] - drag.last[0], p[1] - drag.last[1]) >= 3) { wip.p.push(q); drag.last = p; render(); } return; }
        if (drag.make) { wip.p[1] = q; render(); return; }
        var d = drag.d, dt = q[0] - drag.q0[0], dv = q[1] - drag.q0[1];
        if (!drag.moved && Math.abs(dt) + Math.abs(dv) === 0) return;
        drag.moved = true;
        // przesuwanie w pikselach (osie logarytmiczne / różne skale) — przelicz punkt początkowy na piksele i z powrotem
        var s0 = [X(drag.q0[0]), Y(drag.q0[1])], s1 = pos(e), dx = s1[0] - s0[0], dy = s1[1] - s0[1];
        d.p = drag.p0.map(function (p0, j) {
          if (drag.h != null && j !== drag.h) return p0.slice();
          var x = X(p0[0]), y = Y(p0[1]);
          var nt = d.k === 'h' ? p0[0] : (d.k === 'br' ? T(x + dx) : Ts(x + dx)), nv = d.k === 'v' ? p0[1] : V(y + dy);
          return [nt == null ? p0[0] : Math.round(nt), nv == null ? p0[1] : rnd(nv)];
        });
        render();
      });
      svg.addEventListener('pointerup', function (e) {
        if (!drag) return;
        var dd = drag; drag = null;
        try { svg.releasePointerCapture(e.pointerId); } catch (er) {}
        if (dd.brush) { var w = wip; wip = null; if (w.p.length > 1) add(w); setTool('cur'); commit(stOn()); return; }
        if (dd.make) {
          var p = pos(e);
          if (Math.hypot(p[0] - dd.start[0], p[1] - dd.start[1]) < 5) { wip.second = true; render(); return; }   // klik, klik
          finish(); return;
        }
        if (dd.moved) commit(dd.st);
      });
      svg.addEventListener('dblclick', function (e) {
        var g = e.target.closest('g[data-id]'); if (!g || g.classList.contains('lk')) return;
        var st = ST[g.getAttribute('data-k')], d = find({k: g.getAttribute('data-k'), id: g.getAttribute('data-id')});
        if (d && d.k === 'tx') { G = geom(); if (use(st)) askText([X(d.p[0][0]), Y(d.p[0][1])], d.p[0], st, d); }
      });
      function finish() {
        var d = wip; wip = null; delete d.second;
        if (!use(stOn())) return;
        var a = [X(d.p[0][0]), Y(d.p[0][1])], b = [X(d.p[1][0]), Y(d.p[1][1])];
        if (Math.hypot(a[0] - b[0], a[1] - b[1]) >= 4) add(d);
        tool = 'cur'; commit(stOn());
      }
      function askText(p, q, st, d) {
        var inp = document.createElement('input'); inp.className = 'cld-in'; inp.value = d ? d.txt : ''; inp.placeholder = 'Podpis… (Enter)';
        inp.style.left = (G.left + p[0]) + 'px'; inp.style.top = (G.top + p[1] - 14) + 'px';
        wrap.appendChild(inp); inp.focus();
        var done = false;
        var end = function (ok) {
          if (done) return; done = true; var s = inp.value.trim(); inp.remove();
          if (!ST[st.k]) return;
          if (ok && s) { if (d) d.txt = s; else { var n = {id: uid(), k: 'tx', c: color, p: [q], txt: s}; st.D.push(tagNew(st, n)); sel = {k: st.k, id: n.id}; } }
          else if (ok && d && !s) st.D = st.D.filter(function (x) { return x !== d; });
          tool = 'cur'; commit(st);
        };
        inp.addEventListener('keydown', function (ev) { ev.stopPropagation(); if (ev.key === 'Enter') end(true); if (ev.key === 'Escape') end(false); });
        inp.addEventListener('blur', function () { end(true); });
      }
      document.addEventListener('keydown', function (e) {
        if (e.target.closest && e.target.closest('input,textarea,select,[contenteditable]')) return;
        if (e.key === 'Escape') {
          if (onp) { onp.remove(); onp = null; }
          else if (wip || tool !== 'cur' || sel) { wip = null; sel = null; setTool('cur'); }
          else if (sk.open) closeSk();
        }
        else if ((e.key === 'Delete' || e.key === 'Backspace') && sel) { e.preventDefault(); removeSel(); }
      });
      desk.addEventListener('change', function () { setTool('cur'); });
      // klik w pusty wykres (poza rysunkiem) — odznacz
      chart.subscribeClick(function () { if (sel && !drag) { sel = null; syncBar(); render(); } });

      scope(true); syncBar(); requestAnimationFrame(frame);
      if (window.__cldImported && ST[window.__cldImported]) toast('Dodano rysunki z linku');
      return {redraw: function () { sig = ''; }, count: function () { return allSt().reduce(function (n, st) { return n + st.D.filter(function (d) { return d.k !== 'sk'; }).length; }, 0); }};
    }
  };
})();


// 131: konto (Firebase) — przycisk „Zaloguj” w pasku z logo (na Pulpicie w lewym menu), logowanie przez Google
//   albo link na e-mail (bez hasła). Biblioteka Firebase (vendor/firebase-cl.js, ~200 KB) wczytuje się dopiero przy
//   logowaniu albo gdy ktoś był już zalogowany w tej przeglądarce (localStorage „cl-fb-on”).
//   Dostęp: każdy zalogowany z potwierdzonym e-mailem, oprócz zablokowanych przez admina (reguły: firebase/firestore.rules).
//   window.CLAuth: {ready, user, allowed, admin, F, db, on(fn), open(), signOut()} — CLDraw synchronizuje rysunki z kontem.
(function () {
  var V = '131', FLAG = 'cl-fb-on', MAIL = 'cl-fb-mail';
  var css = '.cl-acct{display:inline-flex;position:relative}' +
    '.cl-acct>button{display:inline-flex;align-items:center;gap:7px;font:inherit;font-size:12.5px;padding:5px 11px;min-height:32px;border-radius:8px;border:1px solid rgba(255,255,255,.18);background:#1c1c1c;color:#e8e8e8;cursor:pointer;white-space:nowrap}' +
    '.cl-acct>button:hover{border-color:#5b9cf6}' +
    '.cl-acct>button.in{background:transparent}' +
    '.cl-acct .av{width:22px;height:22px;border-radius:50%;background:#5b9cf6;color:#0f0f0f;font-weight:700;font-size:12px;display:inline-flex;align-items:center;justify-content:center;flex:none}' +
    '.cl-acct .av.ban{background:#e05252}' +
    '.cl-acct-pop{position:fixed;z-index:80;width:320px;max-width:calc(100vw - 16px);background:#1c1c1c;border:1px solid rgba(255,255,255,.16);border-radius:12px;box-shadow:0 14px 40px rgba(0,0,0,.6);padding:14px;font-size:13.5px;color:#e8e8e8;line-height:1.45;white-space:normal}' +
    '.cl-acct-pop h3{font-size:15px;margin:0 0 6px}' +
    '.cl-acct-pop p{margin:0 0 10px;color:#a8a8a8;font-size:12.5px}' +
    '.cl-acct-pop button,.cl-acct-pop a.btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;box-sizing:border-box;font:inherit;font-size:14px;padding:9px 12px;min-height:42px;border-radius:8px;border:1px solid rgba(255,255,255,.18);background:#262626;color:#f0f0f0;cursor:pointer;text-decoration:none;margin-top:6px}' +
    '.cl-acct-pop button.pri{background:#24324a;border-color:#5b9cf6}' +
    '.cl-acct-pop button:hover,.cl-acct-pop a.btn:hover{border-color:#5b9cf6}' +
    '.cl-acct-pop input{width:100%;box-sizing:border-box;font:inherit;font-size:16px;padding:8px 10px;min-height:42px;border-radius:8px;border:1px solid rgba(255,255,255,.18);background:#0f0f0f;color:#fff;margin-top:6px}' +
    '.cl-acct-pop .or{text-align:center;color:#777;font-size:12px;margin:10px 0 2px}' +
    '.cl-acct-pop .msg{margin-top:8px;font-size:12.5px;color:#ffc107}' +
    '.cl-acct-pop .ok{color:#4caf7d}' +
    '.cl-acct-fix{position:absolute;top:22px;right:24px;z-index:38}' +
    '@media (max-width:640px){.cl-acct>button{padding:4px 8px;font-size:11.5px}.cl-acct>button .nm{display:none}.cl-acct-fix{display:none}}' +
    '@media print{.cl-acct,.cl-acct-pop{display:none!important}}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  var A = window.CLAuth = {ready: false, loading: false, user: null, allowed: false, admin: false, banned: false, F: null, db: null, auth: null, cfg: null,
    _fns: [], on: function (fn) { this._fns.push(fn); }, open: function (el) { openPop(el); }, signOut: function () { if (A.F) A.F.signOut(A.auth); }};
  function emit() { renderBtn(); A._fns.forEach(function (f) { try { f(A); } catch (e) {} }); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function flag(v) { try { if (v) localStorage.setItem(FLAG, '1'); else localStorage.removeItem(FLAG); } catch (e) {} }
  function script(src) { return new Promise(function (ok, bad) { var s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = bad; document.head.appendChild(s); }); }
  var loadP = null;
  function load() {
    if (loadP) return loadP;
    A.loading = true; renderBtn();
    loadP = script('firebase/config.js?v=' + V).then(function () { return window.CLFB ? null : script('vendor/firebase-cl.js?v=' + V); }).then(function () {
      var F = A.F = window.CLFB, C = A.cfg = window.CL_FIREBASE;
      var app = F.initializeApp(C.config);
      A.auth = F.getAuth(app); A.db = F.getFirestore(app);
      F.onAuthStateChanged(A.auth, function (u) {
        A.user = u; A.admin = !!(u && u.emailVerified && u.email && u.email.toLowerCase() === C.admin);
        A.allowed = false; A.banned = false;
        if (!u) { A.ready = true; A.loading = false; flag(false); emit(); return; }
        flag(true);
        var m = (u.email || '').toLowerCase();
        (A.admin ? Promise.resolve(false) : F.getDoc(F.doc(A.db, 'banned', m)).then(function (s) { return s.exists(); }, function () { return false; })).then(function (ban) {
          A.banned = ban; A.allowed = u.emailVerified && !ban;
          A.ready = true; A.loading = false;
          if (A.allowed) F.setDoc(F.doc(A.db, 'users', u.uid), {email: m, name: u.displayName || m.split('@')[0], last: F.serverTimestamp()}).catch(function () {});
          emit();
        });
      });
      // powrót z linku z e-maila
      if (F.isSignInWithEmailLink(A.auth, location.href)) {
        var m = ''; try { m = localStorage.getItem(MAIL) || ''; } catch (e) {}
        if (!m) m = window.prompt('Podaj e-mail, na który przyszedł link do logowania:') || '';
        F.signInWithEmailLink(A.auth, m, location.href).then(function () {
          try { localStorage.removeItem(MAIL); } catch (e) {}
          var q = new URLSearchParams(location.search); ['apiKey', 'oobCode', 'mode', 'lang', 'continueUrl'].forEach(function (k) { q.delete(k); });
          history.replaceState(null, '', location.pathname + (q.toString() ? '?' + q : '') + location.hash);
        }, function (e) { alert('Link do logowania nie zadziałał (jest jednorazowy i ważny ok. godziny): ' + (e.code || e.message)); });
      }
    }).catch(function () { A.loading = false; loadP = null; renderBtn(); });
    return loadP;
  }

  // ── przycisk ──
  function renderBtn() {
    document.querySelectorAll('[data-cl-acct]').forEach(function (box) {
      var u = A.user, h;
      if (A.loading && !A.ready) h = '<button type="button" disabled>…</button>';
      else if (!u) h = '<button type="button" title="Zaloguj się — rysunki na wykresach i Dziennik zapiszą się na Twoim koncie">' +
        '<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="5.5" r="3"/><path d="M2.5 14.5c.8-3 3-4.5 5.5-4.5s4.7 1.5 5.5 4.5"/></svg>Zaloguj</button>';
      else {
        var n = (u.displayName || u.email || '?'), ini = n.trim().charAt(0).toUpperCase();
        h = '<button type="button" class="in" title="' + esc(u.email) + (A.banned ? ' — konto zablokowane' : '') + '"><span class="av' + (A.banned ? ' ban' : '') + '">' + esc(ini) + '</span><span class="nm">' + esc(n.split(' ')[0].split('@')[0]) + '</span></button>';
      }
      box.innerHTML = h;
      var b = box.querySelector('button'); if (b) b.onclick = function (e) { e.stopPropagation(); openPop(b); };
    });
  }
  var pop = null;
  function closePop() { if (pop) { pop.remove(); pop = null; } }
  document.addEventListener('click', function (e) { if (pop && !pop.contains(e.target)) closePop(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closePop(); });
  function openPop(anchor) {
    if (pop) { closePop(); return; }
    anchor = anchor || document.querySelector('[data-cl-acct] button');
    pop = document.createElement('div'); pop.className = 'cl-acct-pop'; pop.setAttribute('role', 'dialog');
    pop.addEventListener('click', function (e) { e.stopPropagation(); });
    var u = A.user;
    if (!u) {
      pop.innerHTML = '<h3>Zaloguj się</h3>' +
        '<p>Bez logowania rysunki na wykresach są zapisane tylko w tej przeglądarce: znikną po wyczyszczeniu jej danych i nie pojawią się na innych urządzeniach. Dziennik można wtedy tylko oglądać. Po zalogowaniu rysunki i Twój Dziennik zapisują się na koncie i są dostępne na każdym urządzeniu.</p>' +
        '<button type="button" class="pri" data-g>Zaloguj przez Google</button>' +
        '<div class="or">albo dowolny e-mail — przyjdzie link, bez hasła</div>' +
        '<input type="email" autocomplete="email" placeholder="np. jan@wp.pl" data-m><button type="button" data-s>Wyślij link do logowania</button><div class="msg" data-msg></div>';
      pop.querySelector('[data-g]').onclick = function () {
        var msg = pop.querySelector('[data-msg]'); msg.textContent = 'Otwieram okno Google…';
        load().then(function () { return A.F.signInWithPopup(A.auth, new A.F.GoogleAuthProvider()); })
          .then(function () { closePop(); }, function (e) { if (pop) pop.querySelector('[data-msg]').textContent = 'Logowanie nie wyszło: ' + (e && (e.code || e.message)); });
      };
      pop.querySelector('[data-s]').onclick = function () {
        var m = pop.querySelector('[data-m]').value.trim(), msg = pop.querySelector('[data-msg]');
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(m)) { msg.textContent = 'Wpisz poprawny e-mail.'; return; }
        msg.textContent = 'Wysyłam…';
        load().then(function () { return A.F.sendSignInLinkToEmail(A.auth, m, {url: location.origin + location.pathname, handleCodeInApp: true}); }).then(function () {
          try { localStorage.setItem(MAIL, m); } catch (e) {}
          msg.className = 'msg ok'; msg.textContent = 'Wysłano link na ' + m + '. Otwórz go w tej przeglądarce (sprawdź też spam). Link jest jednorazowy.';
        }, function (e) { msg.textContent = 'Nie udało się wysłać: ' + (e && (e.code || e.message)); });
      };
    } else {
      pop.innerHTML = '<h3>' + esc(u.displayName || u.email) + '</h3><p>' + esc(u.email) + (A.admin ? ' · admin' : '') + '</p>' +
        (A.banned ? '<p style="color:#e05252">To konto jest zablokowane — rysunki zapisują się tylko w tej przeglądarce, a Dziennik można tylko oglądać.</p>'
          : '<p class="ok">✓ Rysunki na wykresach i Twój Dziennik zapisują się na tym koncie — na każdym urządzeniu te same.</p>') +
        (A.admin ? '<a class="btn" href="sonda-firebase.html">Użytkownicy i blokady</a>' : '') +
        '<button type="button" data-o>Wyloguj</button>';
      pop.querySelector('[data-o]').onclick = function () { A.signOut(); closePop(); };
    }
    document.body.appendChild(pop);
    var r = anchor ? anchor.getBoundingClientRect() : {right: innerWidth - 8, bottom: 60, left: 8};
    var w = pop.offsetWidth, left = Math.min(innerWidth - w - 8, Math.max(8, r.right - w));
    pop.style.left = left + 'px'; pop.style.top = Math.min(innerHeight - pop.offsetHeight - 8, r.bottom + 6) + 'px';
    var f = pop.querySelector('input,button'); if (f && !u) setTimeout(function () { f.focus(); }, 0);
  }

  function boot() {
    renderBtn();
    var was = false; try { was = localStorage.getItem(FLAG) === '1'; } catch (e) {}
    var link = /[?&]oobCode=/.test(location.search) && /[?&]mode=signIn/.test(location.search);
    if (was || link) load(); else { A.ready = true; }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 0); }); else setTimeout(boot, 0);
})();
