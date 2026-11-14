"""Lampki zakładki Altsezon (poprawka 70, badanie claude/altsezon-strategia.md, 14.11.2026).

Każda lampka = sprawdzony na historii warunek na danych dziennych. Epizod = dni spełnienia warunku, przerwy
≤ `gap_days` łączone (krótkie przygaśnięcie nie zmienia daty „świeci od”). Lampka świeci, gdy warunek jest
spełniony w ostatnim dniu z danymi.

Lampki (progi: config.yaml → alt_lamps):
  rally     szeroki rajd: szerokość rynku ≥ 80% (poziom 2: ≥ 90%)                   — ema.json (Orange Pi)
  big_wave  duża fala w toku: indeks altów ≥ +40% nad dołkiem, do potwierdzenia końca — altindex.json (Pi)
  leverage  lewar altów OI OTHERS / OI BTC ≥ 0,90 / 0,95 / 1,0                         — Coinalyze (ten bot)
  rsi3d     RSI 3D: ≥ 30% coinów wykupionych (zamknięte świece 3D)                     — ema.json (Pi)
  selloff   wyprzedaż: indeks altów ≤ −20% w 30 dni i (MVRV-Z ≤ 0,5 lub BTC ≤ −10% w 30 dni)

Liczy bot GitHuba (main.py) w każdym przebiegu: wynik idzie do meta.json → `alt_lamps` (zakładka alt.html tylko
go wyświetla — te same liczby co w alercie), a zmiany (zapalenie, wyższy poziom, zgaszenie) → Telegram.
Moduł bez zależności poza biblioteką standardową.
"""
import html
import math
from statistics import median

DAY = 86400

DEFAULTS = {
    "enabled": True,
    "gap_days": 14,          # przerwa w warunku, po której epizod się kończy (lampka „gaśnie” na dobre)
    "lag_days": 3,           # dane starsze niż tyle dni od dziś = lampka nie świeci (brak danych)
    "min_coins": 50,         # szerokość i RSI liczone z co najmniej tylu coinów
    "rally": {"levels": [80, 90]},
    "big_wave": {"wave_pct": 40, "max_days": 200},
    "leverage": {"levels": [0.90, 0.95, 1.0]},
    "rsi3d": {"overbought_pct": 30},
    "selloff": {"alt_drop_pct": 20, "btc_drop_pct": 10, "mvrvz_max": 0.5, "days": 30},
    "notify_off": True,      # wiadomość, gdy epizod się skończy (po gap_days bez warunku)
}

LAMPS = ("rally", "big_wave", "leverage", "rsi3d", "selloff")
GROUP = {"rally": "rajd", "big_wave": "rajd", "leverage": "przegrzanie", "rsi3d": "przegrzanie", "selloff": "wyprzedaż"}
NAME = {"rally": "Szeroki rajd", "big_wave": "Duża fala w toku", "leverage": "Lewar altów",
        "rsi3d": "RSI 3D wykupione", "selloff": "Wyprzedaż"}
# po zapaleniu: która strona się „sprawdza” (rajd → alty wyżej, reszta → niżej)
WANT_UP = {"rally": True, "big_wave": True, "leverage": False, "rsi3d": False, "selloff": False}


def config(cfg):
    c = dict(DEFAULTS)
    user = (cfg or {}).get("alt_lamps") or {}
    for k, v in user.items():
        c[k] = {**DEFAULTS[k], **v} if isinstance(DEFAULTS.get(k), dict) and isinstance(v, dict) else v
    return c


def fmt_num(v, d=2):
    return f"{v:.{d}f}".replace(".", ",")


def dmy(t):
    import time as _t
    g = _t.gmtime(t)
    return f"{g.tm_mday:02d}.{g.tm_mon:02d}.{g.tm_year}"


# ── siatka dzienna ───────────────────────────────────────────
def day_of(t):
    return int(t) // DAY * DAY


def to_daily(points, ffill=5):
    """points: dict t→v albo [[t, v], …] → dict dzień→v (ostatnia wartość dnia)."""
    items = points.items() if isinstance(points, dict) else ((p[0], p[1]) for p in points or [])
    out = {}
    for t, v in sorted(items):
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out[day_of(t)] = v
    out["_ffill"] = ffill
    return out


def on_grid(d, grid, src=None):
    """dict dzień→v → lista wartości na siatce (z przeniesieniem ostatniej wartości ≤ ffill dni).
    src (lista) — dopisuje dzień, z którego pochodzi wartość."""
    ff = d.get("_ffill", 5)
    out, last_t, last_v = [], None, None
    for t in grid:
        if t in d:
            last_t, last_v = t, d[t]
        ok = last_t is not None and (t - last_t) <= ff * DAY
        out.append(last_v if ok else None)
        if src is not None:
            src.append(last_t if ok else None)
    return out


def change(vals, i, back):
    """% zmiany vals[i] względem vals[i − back]."""
    if i - back < 0 or vals[i] is None or vals[i - back] in (None, 0):
        return None
    return (vals[i] / vals[i - back] - 1) * 100


# ── fale (zigzag — ten sam co w alt.html) ────────────────────
def zigzag(x, th):
    piv, hi, lo, trend = [], 0, 0, 0
    for i in range(1, len(x)):
        if trend >= 0:
            if x[i] > x[hi]:
                hi = i
            if x[hi] - x[i] >= th:
                if trend == 0 and lo < hi:
                    piv.append(lo)
                piv.append(hi)
                trend, lo = -1, i
        if trend <= 0:
            if x[i] < x[lo]:
                lo = i
            if x[i] - x[lo] >= th:
                if trend == 0 and hi < lo:
                    piv.append(hi)
                piv.append(lo)
                trend, hi = 1, i
    return sorted(set(piv)), trend, hi, lo


def big_wave_days(x, th, max_days):
    """→ lista bool: dzień w dużej fali (od potwierdzenia: indeks ≥ próg nad dołkiem, do potwierdzenia końca:
    spadek o tyle samo w skali log od szczytu); fala w toku — do dziś. Plus {dzień potwierdzenia: indeks dołka}."""
    n = len(x)
    out, lows = [False] * n, {}
    if n < 3:
        return out, lows, 0
    piv, trend, hi, lo = zigzag(x, th)
    eps = 1e-12

    def mark(a, c, done):
        if c - a > max_days or x[c] <= x[a]:
            return
        conf = next((i for i in range(a, c + 1) if x[i] - x[a] >= th - eps), None)
        if conf is None:
            return
        end = n
        if done:
            end = next((i for i in range(c, n) if x[c] - x[i] >= th - eps), n)
        for i in range(conf, end):
            out[i] = True
        lows[conf] = a

    for a, c in zip(piv, piv[1:]):
        mark(a, c, True)
    if trend == 1:
        mark(lo, hi, False)
    return out, lows, lo                     # lo = najniższy punkt od ostatniego szczytu (dołek ewentualnej fali)


# ── epizody ──────────────────────────────────────────────────
def episodes(levels, gap):
    """levels: lista int (0 = warunek niespełniony, 1.. = poziom) → [[start, koniec, maks. poziom], …] (indeksy)."""
    out, s, last, mx = [], None, None, 0
    for i, lv in enumerate(levels):
        if not lv:
            continue
        if s is None or i - last > gap:
            if s is not None:
                out.append([s, last, mx])
            s, mx = i, 0
        last, mx = i, max(mx, lv)
    if s is not None:
        out.append([s, last, mx])
    return out


def after(x, i, days=30):
    """% zmiany indeksu altów (log x) po `days` dniach od dnia i; None, gdy jeszcze za wcześnie."""
    j = i + days
    if j >= len(x) or x[i] is None or x[j] is None:
        return None
    return (math.exp(x[j] - x[i]) - 1) * 100


# ── główne liczenie ──────────────────────────────────────────
def build(cfg, now, idx=None, breadth=None, rsi_d3=None, lev=None, lev_now=None, mvrvz=None, btc=None):
    """Wejście (surowe, z plików):
      idx     altindex.json → d: [[t, wartość, coinów], …]
      breadth ema.json → breadth: [[t, %, coinów], …]
      rsi_d3  ema.json → rsi.d3: [[t_otwarcia, % wyprzedanych, % wykupionych, coinów], …]
      lev     dict t→v (1d), lev_now (t, v) najnowszy (1h); mvrvz, btc — dict t→v (1d)
    → {updated, cfg, days: [t…], lamps: {id: {...}}}"""
    c = config(cfg)
    gap, lag, mc = int(c["gap_days"]), int(c["lag_days"]), int(c["min_coins"])
    idx_d = to_daily({p[0]: p[1] for p in (idx or []) if p[1] and p[1] > 0}, ffill=0)   # tylko prawdziwe dni
    if not [k for k in idx_d if k != "_ffill"]:
        return None
    start = min(k for k in idx_d if k != "_ffill")
    today = day_of(now)
    grid = list(range(start, today + DAY, DAY))
    n = len(grid)
    src = {k: [] for k in LAMPS}
    iv = on_grid(idx_d, grid, src["selloff"])
    src["big_wave"] = src["selloff"]
    x = [math.log(v) if v else None for v in iv]

    br = on_grid(to_daily({p[0]: p[1] for p in (breadth or []) if len(p) > 2 and (p[2] or 0) >= mc}, ffill=3), grid, src["rally"])
    rsi = on_grid(to_daily({p[0] + 2 * DAY: p[2] for p in (rsi_d3 or []) if len(p) > 3 and (p[3] or 0) >= mc}, ffill=4), grid, src["rsi3d"])
    lv_d = to_daily(lev or {}, ffill=3)
    if lev_now and lev_now[1] is not None:
        lv_d[day_of(lev_now[0])] = float(lev_now[1])
    lv = on_grid(lv_d, grid, src["leverage"])
    mz = on_grid(to_daily(mvrvz or {}, ffill=5), grid)
    bt = on_grid(to_daily(btc or {}, ffill=3), grid)

    # poziomy na każdy dzień
    L = {k: [0] * n for k in LAMPS}
    vals = {k: [None] * n for k in LAMPS}
    rl = sorted(float(v) for v in c["rally"]["levels"])
    ll = sorted(float(v) for v in c["leverage"]["levels"])
    ob = float(c["rsi3d"]["overbought_pct"])
    so = c["selloff"]
    sd = int(so.get("days", 30))
    # duża fala: zigzag tylko na dniach z indeksem (ciągłe od startu; ffill ≤ 3 dni)
    have = [i for i in range(n) if x[i] is not None]
    xs = [x[i] for i in have]
    th = math.log(1 + float(c["big_wave"]["wave_pct"]) / 100)
    bw, lows, zlo = big_wave_days(xs, th, int(c["big_wave"]["max_days"]))
    low_at = {}
    cur_low = None
    for k, i in enumerate(have):
        if k in lows:
            cur_low = have[lows[k]]
        if bw[k]:
            L["big_wave"][i] = 1
            if cur_low is not None:
                vals["big_wave"][i] = (math.exp(x[i] - x[cur_low]) - 1) * 100
                low_at[i] = cur_low
    if have and not bw[-1]:                  # bez fali: ile indeks jest nad obecnym dołkiem (fala od +wave_pct%)
        i, a = have[-1], have[zlo]
        vals["big_wave"][i] = (math.exp(x[i] - x[a]) - 1) * 100
        low_at[i] = a
    for i in range(n):
        if br[i] is not None:
            vals["rally"][i] = br[i]
            L["rally"][i] = sum(br[i] >= v for v in rl)
        if lv[i] is not None:
            vals["leverage"][i] = lv[i]
            L["leverage"][i] = sum(lv[i] >= v for v in ll)
        if rsi[i] is not None:
            vals["rsi3d"][i] = rsi[i]
            L["rsi3d"][i] = int(rsi[i] >= ob)
        a = change(iv, i, sd)
        if a is not None:
            b, m = change(bt, i, sd), mz[i]
            vals["selloff"][i] = a
            cheap = m is not None and m <= float(so["mvrvz_max"])
            fell = b is not None and b <= -float(so["btc_drop_pct"])
            L["selloff"][i] = int(a <= -float(so["alt_drop_pct"]) and (cheap or fell))

    out = {}
    for k in LAMPS:
        lev_k = L[k]
        data_days = [i for i in range(n) if vals[k][i] is not None]
        if not data_days:
            continue
        last = data_days[-1]
        fresh = (n - 1 - last) <= lag
        g = 1 if k == "big_wave" else gap          # duża fala ma własny koniec (potwierdzenie spadku)
        eps_ = episodes(lev_k, g)
        rows = []
        for s, e, mx in eps_:
            f = after(x, s)
            rows.append([grid[s], grid[e], mx, None if f is None else round(f, 1)])
        on = fresh and lev_k[last] > 0
        cur = eps_[-1] if eps_ and (on or (n - 1 - eps_[-1][1]) <= g) else None
        # statystyki po zapaleniu — osobno dla każdego poziomu (epizody warunku ≥ poziom); bez bieżącego epizodu
        nlev = max(1, len(rl) if k == "rally" else len(ll) if k == "leverage" else 1)
        stats = []
        for p in range(1, nlev + 1):
            ep_p = episodes([1 if v >= p else 0 for v in lev_k], g)
            fs = [after(x, s) for s, e, mx in ep_p]
            fs = [f for f in fs if f is not None]
            good = sum((f > 0) if WANT_UP[k] else (f < 0) for f in fs)
            stats.append({"n": len(fs), "good": good, "med": round(median(fs), 1) if fs else None,
                          "count": len(ep_p)})
        info = {"name": NAME[k], "group": GROUP[k], "on": bool(on), "level": int(lev_k[last]) if on else 0,
                "value": None if vals[k][last] is None else round(vals[k][last], 4),
                "value_t": src[k][last] if src[k] and src[k][last] else grid[last],
                "fresh": fresh, "episodes": rows, "stats": stats, "want_up": WANT_UP[k]}
        if cur:
            info["since"] = grid[cur[0]]
            info["last_true"] = grid[cur[1]]
            info["max_level"] = cur[2]
        if k == "big_wave" and last in low_at:
            info["low_t"] = grid[low_at[last]]
        if k == "selloff" and vals[k][last] is not None:
            info["btc_chg"] = None if change(bt, last, sd) is None else round(change(bt, last, sd), 1)
            info["mvrvz"] = mz[last]
        out[k] = info
    return {"updated": int(now), "cfg": {k: c[k] for k in ("gap_days", "rally", "big_wave", "leverage", "rsi3d", "selloff")},
            "start": start, "lamps": out}


# ── alerty ───────────────────────────────────────────────────
def _stat_txt(k, s):
    if not s or not s.get("n"):
        return ""
    word = "wyżej" if WANT_UP[k] else "niżej"
    med = "" if s["med"] is None else f", mediana {s['med']:+.0f}%"
    return f" Historycznie 30 dni po zapaleniu alty były {word} {s['good']} z {s['n']} razy{med} (historia, nie prognoza)."


def describe(k, info, c, level):
    """Jedno zdanie o lampce na danym poziomie (do Telegrama i strony)."""
    v = info.get("value")
    if k == "rally":
        thr = c["rally"]["levels"][level - 1]
        return (f"🟢 <b>Szeroki rajd</b>: {fmt_num(v, 0)}% coinów nad EMA200 (≥ {thr:g}%). "
                "Rajd trwa — to nie jest sygnał sprzedaży.")
    if k == "big_wave":
        low = f" od dołka {dmy(info['low_t'])}" if info.get("low_t") else ""
        return (f"🟢 <b>Duża fala altów potwierdzona</b>: indeks altów {v:+.0f}%{low} (próg +{c['big_wave']['wave_pct']:g}%). "
                "Spora część fali zwykle już za nami — pilnuj lampek przegrzania.")
    if k == "leverage":
        thr = c["leverage"]["levels"][level - 1]
        txt = {1: "uwaga, przegrzanie blisko", 2: "przegrzanie — historycznie czas sprzedaży",
               3: "skrajne przegrzanie"}.get(level, "przegrzanie")
        icon = "🟡" if level == 1 else "🔴"
        return f"{icon} <b>Lewar altów</b> {fmt_num(v, 3)}× (≥ {fmt_num(thr, 2)}): {txt}."
    if k == "rsi3d":
        return (f"🟠 <b>RSI 3D</b>: {fmt_num(v, 0)}% coinów wykupionych (≥ {c['rsi3d']['overbought_pct']:g}%). "
                "Rynek rozgrzany — sprzedaż części; w silnej hossie bywa za wcześnie.")
    if k == "selloff":
        so = c["selloff"]
        why = []
        if info.get("mvrvz") is not None and info["mvrvz"] <= float(so["mvrvz_max"]):
            why.append(f"BTC tani (MVRV-Z {fmt_num(info['mvrvz'], 2)})")
        if info.get("btc_chg") is not None and info["btc_chg"] <= -float(so["btc_drop_pct"]):
            why.append(f"BTC {info['btc_chg']:+.0f}% w {so['days']} dni")
        return (f"🔵 <b>Wyprzedaż</b>: indeks altów {v:+.0f}% w {so['days']} dni, " + " i ".join(why) + ". "
                "To opis, nie sygnał kupna — historycznie alty zwykle spadały dalej.")
    return NAME.get(k, k)


def check(result, cfg, state, page_url="", arm_only=False):
    """Porównuje lampki ze stanem (state['lamps']) → lista wiadomości. Pierwszy przebieg (brak stanu)
    albo arm_only — zapisuje stan po cichu (bez starych zapaleń)."""
    if not result:
        return []
    c = config(cfg)
    first = "lamps" not in state
    st = state.setdefault("lamps", {})
    msgs = []
    for k in LAMPS:
        info = result["lamps"].get(k)
        if not info:
            continue
        s = st.get(k, {})
        since = info.get("since")
        if info["on"]:
            new_ep = s.get("ep") != since
            lvl = info["level"]
            if first or arm_only:
                new_ep = True                          # uzbrojenie po cichu
            elif new_ep:
                msgs.append(describe(k, info, c, lvl) + f" Zapaliła się {dmy(since)}." +
                            _stat_txt(k, info["stats"][lvl - 1] if lvl - 1 < len(info["stats"]) else None))
            elif lvl > s.get("lvl", 0):
                msgs.append(describe(k, info, c, lvl) + f" Wyższy poziom (świeci od {dmy(since)})." +
                            _stat_txt(k, info["stats"][lvl - 1] if lvl - 1 < len(info["stats"]) else None))
            s = {"ep": since, "lvl": max(lvl, 0 if new_ep else s.get("lvl", 0)), "on": True}
        else:
            if since is not None and not s.get("ep"):
                s = {"ep": since, "lvl": info.get("max_level", 0)}       # przygasła w trwającym epizodzie (np. przy uzbrajaniu)
            if since is None and s.get("ep") and s.get("done") != s["ep"]:
                # epizod skończony (gap_days bez warunku)
                ep = next((e for e in reversed(info["episodes"]) if e[0] == s["ep"]), None)
                if ep and c.get("notify_off", True) and not (first or arm_only):
                    msgs.append(f"💤 <b>{NAME[k]}</b> — lampka zgasła. Świeciła {dmy(ep[0])}–{dmy(ep[1])} "
                                f"({(ep[1] - ep[0]) // DAY + 1} dni).")
                s["done"] = s["ep"]
            if first or arm_only:
                s["done"] = s.get("ep")                # bez spóźnionych „zgasła” po pierwszym przebiegu
            s["on"] = False
        st[k] = s
    if msgs and page_url:
        base = page_url.rsplit("/", 1)[0] if page_url.endswith(".html") else page_url.rstrip("/")
        msgs.append(f'<a href="{html.escape(base)}/alt.html">Altsezon — wszystkie lampki</a>')
    return msgs
