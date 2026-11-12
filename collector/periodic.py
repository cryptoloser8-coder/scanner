"""Raporty tygodniowe i miesięczne (poprawka 30) — uzupełnienie raportów dziennych.

Każdy odpowiada na inne pytanie niż dzienny:
  tygodniowy  — jaki był tydzień i w jakim trendzie jesteśmy (zamknięcie świecy tygodniowej, pon. 00:00 UTC),
  miesięczny  — gdzie jesteśmy w cyklu i co zmieniło się w strukturze rynku (zamknięcie miesiąca, 1. dzień 00:00 UTC).
Okres = ostatni pełny tydzień / miesiąc przed chwilą `now` (raport z ręki w środku tygodnia → poprzedni pełny tydzień).
Wartość „na zamknięcie” = dzienny punkt z ostatniego dnia okresu (mamy zamknięcia dzienne, bez knotów — zakresy
okresu są liczone z zamknięć). Bloki jak w raporcie dziennym (report.py), bez interpretacji.
"""
import statistics
from datetime import datetime, timezone

import alerts
import econ
import report as R

DAY = 86400
WEEK = 7 * DAY
PERIODIC = ("weekly", "monthly")
MONTHS = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień",
          "październik", "listopad", "grudzień"]
DAYS_SHORT = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]
PHASE_NAMES = {"bull": "hossa", "bear": "bessa", "acc": "akumulacja"}
# wskaźniki cyklu w raportach; Pi Cycle tylko w zakładce (nie przeciął się przy szczytach 11.2021 i 10.2025)
REPORT_CYCLE_SIDS = ("mvrv_btc", "mvrvz_btc", "mayer_btc", "p200w_btc", "ssr")
RANGE_FROM = {"default": 1483228800, "ssr": 1577836800}      # 01.01.2017 (3 ostatnie cykle), SSR: 01.01.2020


# ── okres ────────────────────────────────────────────────────
def _dt(t):
    return datetime.fromtimestamp(int(t), timezone.utc)


def _ts(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def month_start(t, back=0):
    """Początek miesiąca zawierającego t, cofnięty o `back` miesięcy."""
    d = _dt(t)
    y, m = d.year, d.month - back
    while m < 1:
        m += 12
        y -= 1
    return _ts(datetime(y, m, 1))


def period(kind, now):
    """→ (start, end): ostatni pełny tydzień (pon.–nd.) albo miesiąc przed `now`, w UTC."""
    day = int(now) - int(now) % DAY
    if kind == "weekly":
        end = day - _dt(day).weekday() * DAY
        return end - WEEK, end
    end = month_start(now)
    return month_start(end - DAY), end


def title(kind, start, end):
    last = end - DAY
    if kind == "weekly":
        return f"Raport tygodniowy — {R.utc(start, '%d.%m')}–{R.utc(last, '%d.%m.%Y')}"
    d = _dt(start)
    return f"Raport miesięczny — {MONTHS[d.month - 1]} {d.year}"


# ── formatowanie ─────────────────────────────────────────────
DIFF_FMTS = ("pct", "pct0", "yield", "pp", "z", "fund")


def fmt_of(d, sid):
    c = d.catalog.get(sid) or {}
    return c.get("fmt") or c.get("group") or ""


def fv(v, f):
    if v is None:
        return "—"
    if f in ("mcap", "oi", "liq") or (f == "usd" and abs(v) >= 1e6):
        return alerts.fmt_value(v, "mcap")
    if f in ("price", "usd"):
        return R.fmt_price(v)
    if f == "pct":
        return f"{v:.2f}%"
    if f == "pct0":
        return f"{v:.0f}%"
    if f == "fund":
        return f"{v:+.1f}%/r"
    if f == "pair":
        return f"{v:.5f}" if abs(v) < 1 else f"{v:.4g}"
    if f == "ratio":
        return f"{v:.3f}×"
    if f == "x":
        return f"{v:.2f}×"
    if f == "z":
        return f"{v:.2f}"
    if f == "yield":
        return f"{v:.2f}%"
    if f == "pp":
        return f"{v:+.2f} pp"
    if f == "num":
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}"
    return f"{v:.4g}"


def chg(v, before, f):
    if v is None or before is None:
        return "—"
    if f == "z":                     # MVRV-Z: różnica z dwoma miejscami (jak wartość)
        x = round(v - before, 2)
        return "•0.00" if x == 0 else ("▲" if x > 0 else "▼") + f"{x:+.2f}"
    if f == "pct0":                  # szerokość rynku: wartość w całych %, różnica z jednym miejscem
        x = round(v - before, 1)
        return "•0.0 pp" if x == 0 else ("▲" if x > 0 else "▼") + f"{x:+.1f} pp"
    if f in DIFF_FMTS:
        return R.fmt_chg(v - before, " pp" if f in ("pct", "yield", "pp", "fund") else "")
    return R.fmt_chg(R.pct_change(v, before))


SLOW = {"m2": 62 * DAY}         # serie miesięczne: ostatni odczyt bywa sprzed ~2 miesięcy (M2 z opóźnieniem)


def close(pts, t, sid=None):
    """Wartość z dnia t (albo ostatnia wcześniejsza, najwyżej 3 dni; serie wolne — dłużej)."""
    return R.at(pts, t, SLOW.get(sid, 3 * DAY))


def in_period(pts, start, end):
    return [p for p in pts if start <= p[0] < end]


# ── serie z fallbackami (jak w raporcie dziennym) ────────────
def pts_of(d, sid, ema=None):
    if sid == "alts_vs_btc":
        return R.alts_btc_pts(d)
    if sid == "stable_mcap":
        return R.ratio_pts(d, sid, lambda t, tes: t - tes, "total", "totales")
    if sid == "stable_d":
        return R.ratio_pts(d, sid, lambda t, tes: (t - tes) / t * 100, "total", "totales")
    if sid == "breadth":
        return R.breadth_series(ema)
    if sid == "binance_share":
        return R.ratio_pts(d, sid, lambda a, b: a / b * 100 if b else None, "oi_btc_binance", "oi_btc")
    return d.pts("1d", sid)


EXTRA = {"breadth": ("Szerokość rynku (% nad EMA200)", "pct0"), "binance_share": ("Udział Binance w OI BTC", "pct"),
         "stable_mcap": ("Kapitał w stablecoinach", "mcap"), "stable_d": ("Udział stablecoinów", "pct"),
         "alts_vs_btc": ("Kapitał: Alty / BTC", "ratio")}


def label_fmt(d, sid):
    if sid in EXTRA and sid not in d.catalog:
        return EXTRA[sid]
    return d.name(sid), fmt_of(d, sid)


WICKS = {"px_btc": ("px_btc_lo", "px_btc_hi"), "px_eth": ("px_eth_lo", "px_eth_hi")}   # knoty (low / high) cen


def period_range(d, sid, pts, start, end, res="1d"):
    """(min, max, z_knotów) w [start, end): dla cen BTC/ETH najniższa i najwyższa cena w trakcie świec (knoty, jak na
    wykresie świecowym), dla reszty — zamknięcia. Brak knotów w części okresu → zamknięcia też się liczą."""
    w = [x[1] for x in in_period(pts, start, end)]
    if sid in WICKS:
        lo = [x[1] for x in in_period(d.pts(res, WICKS[sid][0]), start, end)]
        hi = [x[1] for x in in_period(d.pts(res, WICKS[sid][1]), start, end)]
        if lo and hi:
            return min(lo + w), max(hi + w), True
    return (min(w), max(w), False) if w else (None, None, False)


def change_table(d, ema, sids, t_end, start, end, horizons, title_, desc, note="", rng=True, labels=None):
    """Wiersze: zamknięcie okresu, zmiany do wcześniejszych zamknięć, zakres okresu z zamknięć dziennych."""
    rows, wicks = [], False
    for sid in sids:
        pts = pts_of(d, sid, ema)
        v = close(pts, t_end, sid)
        if v is None:
            continue
        name, f = label_fmt(d, sid)
        name = (labels or {}).get(sid, name)
        shift = 0
        if sid in SLOW:
            last_t = max(p[0] for p in pts if p[0] <= t_end)
            name += f" (odczyt za {R.utc(last_t, '%m.%Y')})"
            shift = t_end - last_t          # porównanie z odczytem o tyle samo wcześniejszym (nie z tym samym odczytem)
        row = [name, fv(v, f)] + [chg(v, close(pts, tb - shift, sid), f) for _, tb in horizons]
        if rng:
            lo, hi, wick = period_range(d, sid, pts, start, end)
            wicks = wicks or wick
            row.append(f"{fv(lo, f)} – {fv(hi, f)}" if lo is not None else "—")
        rows.append(row)
    if not rows:
        return []
    cols = ["Wskaźnik", "Zamknięcie"] + [h for h, _ in horizons] + (["Zakres w okresie"] if rng else [])
    note = note or ("Zmiany do zamknięć wcześniejszych okresów; dla wartości w % (dominacje, rentowności, funding) "
                    "różnica w punktach procentowych." + (" Zakres = najniższe i najwyższe zamknięcie dnia w okresie"
                                                           + ("; dla cen BTC i ETH — najniższa i najwyższa cena w trakcie "
                                                              "dnia (knoty, Binance perp przez Coinalyze), jak na wykresie "
                                                              "świecowym." if wicks else ".") if rng else ""))
    return [{"type": "table", "title": title_, "cols": cols, "rows": rows, "left": [0], "desc": desc, "note": note}]


# ── świece ceny w raportach (poprawka 58) ────────────────────
def ohlc_groups(d, sid, t_end, key, since):
    """Świece z dziennych zamknięć i knotów (px_*_hi / _lo): [[t_ostatniego_dnia, open, high, low, close]], grupy wg key(t).
    Open = zamknięcie poprzedniej świecy; dzień bez knota liczy się samym zamknięciem."""
    hi = dict((t, v) for t, v in d.pts("1d", sid + "_hi"))
    lo = dict((t, v) for t, v in d.pts("1d", sid + "_lo"))
    out, prev = [], None
    for t, c in d.pts("1d", sid):
        if t > t_end:
            break
        k = key(t)
        h, l_ = max(hi.get(t, c), c), min(lo.get(t, c), c)
        if out and out[-1][5] == k:
            o = out[-1]
            o[0], o[2], o[3], o[4] = t, max(o[2], h), min(o[3], l_), c
        else:
            o_ = prev if prev is not None else c
            out.append([t, o_, max(h, o_), min(l_, o_), c, k])
        prev = c
    return [x[:5] for x in out if x[0] >= since]


def _week_key(t):
    return (int(t) // DAY + 3) // 7                       # tydzień pon.–nd. UTC


def _month_key(t):
    x = _dt(t)
    return x.year * 12 + x.month


# ── tygodniowe średnie BTC ───────────────────────────────────
def weekly_closes(pts, t_end):
    """Zamknięcia tygodni (niedziela) do t_end włącznie → [[t_niedzieli, v]]."""
    return [[t, v] for t, v in pts if t <= t_end and _dt(t).weekday() == 6]


def sma_last(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def btc_weekly_mas(d, t_end):
    wk = weekly_closes(d.pts("1d", "px_btc"), t_end)
    if len(wk) < 21:
        return []
    vals = [v for _, v in wk]
    rows = []
    for n in (20, 50, 200):
        if len(vals) < n:
            continue
        ma = sma_last(vals, n)
        side = 1 if vals[-1] >= ma else -1
        weeks = 0
        for i in range(len(vals) - 1, n - 2, -1):        # ile tygodni z rzędu po tej stronie
            m_i = sum(vals[i - n + 1:i + 1]) / n
            if (1 if vals[i] >= m_i else -1) != side:
                break
            weeks += 1
        rows.append([f"Średnia {n} tygodni", R.fmt_price(ma), f"{(vals[-1] / ma - 1) * 100:+.1f}%",
                     "nad" if side > 0 else "pod", str(weeks)])
    since = _ts(datetime(2011, 1, 1))
    candles = [c for c in ohlc_groups(d, "px_btc", t_end, _week_key, since) if _dt(c[0]).weekday() == 6]
    series = [{"name": "BTC — świece tygodniowe", "color": "#f7931a", "fmt": "price", "scale": "right",
               "data": [p for p in wk if p[0] >= since], "ohlc": candles}]
    for n, col in ((20, "#4fc3f7"), (50, "#ffd54f"), (200, "#e05252")):
        ma_pts = [[wk[i][0], sum(vals[i - n + 1:i + 1]) / n] for i in range(n - 1, len(vals))
                  if wk[i][0] >= since]
        if ma_pts:
            series.append({"name": f"Średnia {n} tyg.", "color": col, "fmt": "price", "scale": "right", "data": ma_pts})
    return [{"type": "table", "title": "BTC na tle średnich tygodniowych", "cols": ["Średnia", "Wartość", "Cena vs średnia",
                                                                              "Strona", "Tygodni po tej stronie"],
             "rows": rows, "left": [0], "plain": True,
             "desc": "Gdzie jest zamknięcie tygodnia BTC względem średnich z 20, 50 i 200 tygodni (zwykłe średnie z "
                     "zamknięć tygodni). Długo nad średnimi = trend wzrostowy, pod = spadkowy.",
             "note": f"Zamknięcie tygodnia: {R.fmt_price(vals[-1])} ({R.utc(wk[-1][0], '%d.%m.%Y')})."},
            {"type": "chart", "title": "BTC i średnie tygodniowe — od 2011", "log": True, "series": series,
             "desc": "Świece tygodniowe BTC (poniedziałek–niedziela UTC, skala logarytmiczna) ze średnimi 20, 50 i 200 tygodni "
                     "z zamknięć tygodni. Knoty z dziennych świec: do 2019–2020 indeks TradingView, potem Binance perp."}]


# ── derywaty ─────────────────────────────────────────────────
def oi_rows(d, start, end, flat):
    rows = []
    for coin in ("BTC", "ETH"):
        oi, px, fund = d.pts("1d", f"oi_{coin.lower()}"), d.pts("1d", f"px_{coin.lower()}"), d.pts("1d", f"fund_{coin.lower()}")
        t1, t0 = end - DAY, start - DAY
        o1, p1, o0, p0 = close(oi, t1), close(px, t1), close(oi, t0), close(px, t0)
        if None in (o1, p1, o0, p0) or not (o0 and p0 and p1):
            continue
        px_ch = R.pct_change(p1, p0)
        oi_coin = ((o1 / p1) / (o0 / p0) - 1) * 100
        f_now = [v for t, v in in_period(fund, start, end)]
        span = end - start
        f_prev = [v for t, v in fund if end - 12 * span <= t < start] if span <= WEEK else \
            [v for t, v in fund if start - 365 * DAY <= t < start]
        rows.append([coin, R.fmt_chg(px_ch), R.fmt_chg(oi_coin), R.fmt_chg(R.pct_change(o1, o0)),
                     R.oi_case(px_ch, oi_coin, flat),
                     f"{statistics.mean(f_now):+.1f}%" if f_now else "—",
                     f"{statistics.mean(f_prev):+.1f}%" if f_prev else "—"])
    return rows


def cvd_weekly(d, start, end, cfg):
    """CVD spot vs perp w tygodniu (poprawka 44) — bloki liczy cvd.py; brak danych lub błąd → pominięte."""
    try:
        import cvd
        return cvd.weekly_blocks(d, start, end, cfg or {}) if cvd.enabled(cfg or {}) else []
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("periodic").warning("CVD w raporcie tygodniowym: %s", e)
        return []


def sums_by(pts_long, pts_short, starts):
    """Sumy long/short w przedziałach [starts[i], starts[i+1])."""
    sh = dict(pts_short)
    out = []
    for a, b in zip(starts, starts[1:]):
        lv = sum(v for t, v in pts_long if a <= t < b)
        sv = sum(v for t, v in sh.items() if a <= t < b)
        out.append((a, lv, sv))
    return out


LIQ_WORDS = {
    "weekly": {"plural_loc": "tygodniach", "gen_pl": "tygodni", "this": "Ten tydzień", "in_this": "tym tygodniu",
               "big": "duży tydzień", "col": "Tydzień od (UTC)"},
    "monthly": {"plural_loc": "miesiącach", "gen_pl": "miesięcy", "this": "Ten miesiąc", "in_this": "tym miesiącu",
                "big": "duży miesiąc", "col": "Miesiąc"},
}


def liq_block(d, kind, starts, label_fn, cur_start, cur_end, hist_from):
    """Słupki sum likwidacji w kolejnych okresach (ostatnie 12) + linia p90 sum z historii + top 3 dni okresu."""
    w = LIQ_WORDS[kind]
    lg, sh = d.pts("1d", "liq_total_long"), d.pts("1d", "liq_total_short")
    if not lg:
        return []
    sums = [s for s in sums_by(lg, sh, starts) if s[0] >= lg[0][0]]
    if not sums:
        return []
    hist = [lv + sv for a, lv, sv in sums if a >= hist_from]
    cur = next((s for s in sums if s[0] == cur_start), None)
    big = sorted(hist)[min(len(hist) - 1, int(len(hist) * 0.9))] if len(hist) >= 5 else None
    rows = []
    for a, lv, sv in sums[-12:]:
        tot = lv + sv
        rows.append({"label": label_fn(a), "long": lv, "short": sv, "current": a == cur_start,
                     "text": f"{alerts.fmt_value(tot, 'liq')} · {100 * lv / tot:.0f}% long" if tot else "$0"})
    note = "Suma z Binance, Bybit i OKX (bez Hyperliquid) — dolne oszacowanie; dane od 09.2022."
    if cur:
        tot = cur[1] + cur[2]
        pr = R.percentile_rank(hist, tot)
        if pr is not None:
            note = (f"{w['this']}: {alerts.fmt_value(tot, 'liq')} — więcej lub tyle samo co w {pr:.0f}% {w['gen_pl']} "
                    f"od {R.utc(max(hist_from, sums[0][0]), '%m.%Y')}. ") + note
    out = [{"type": "bars", "title": f"Likwidacje — ostatnie {len(rows)} {w['gen_pl']}", "rows": rows, "label_col": w["col"],
            "parts": [{"key": "long", "name": "longi", "color": "#e05252"},
                      {"key": "short", "name": "shorty", "color": "#4caf7d"}],
            "line": {"value": big, "label": f"{w['big']}: {alerts.fmt_value(big, 'liq')} (więcej tylko w 10% {w['gen_pl']})"}
            if big else None,
            "desc": f"Suma likwidacji w kolejnych {w['plural_loc']}. Duże likwidacje longów = wypłukanie lewara w dół, "
                    "shortów = short squeeze.", "note": note}]
    if cur:
        shd = dict(sh)
        days = sorted(((t, v, shd.get(t, 0.0)) for t, v in lg if cur_start <= t < cur_end), key=lambda x: -(x[1] + x[2]))
        top = [[R.utc(t, "%d.%m"), alerts.fmt_value(lv + sv, "liq"), f"{100 * lv / (lv + sv):.0f}%" if lv + sv else "—"]
               for t, lv, sv in days[:3]]
        if top:
            out.append({"type": "table", "title": f"Największe dni likwidacji w {w['in_this']}", "plain": True,
                        "cols": ["Dzień (UTC)", "Suma", "Udział longów"], "rows": top})
    return out


# ── EMA200: świeca tygodniowa i przecięcia w tygodniu ────────
def _week_pct(br, t):
    for tt, v, n in br or []:
        if tt == t:
            return v, n
    return None, None


def ema_weekly(ema, t_end, cfg):
    """EMA200 na świecy tygodniowej (Orange Pi, ema.json → weekly + pola w* coinów) z zamknięcia tygodnia t_end."""
    w = (ema or {}).get("weekly")
    if not w:
        return []
    per, min_w = int(ema.get("period") or 200), int(w.get("min_weeks") or 300)
    title = f"EMA{per} na świecy tygodniowej — zamknięcie tygodnia"
    if w.get("t") != t_end:
        last = R.utc(w["t"], "%d.%m.%Y") if w.get("t") else "brak"
        return [{"type": "text", "title": title,
                 "text": f"Brak danych z zamknięcia tego tygodnia (ostatnie zamknięcie tygodnia w danych z Orange Pi: {last})."}]
    allc = {c["s"]: c for c in ema.get("coins") or []}
    wcoins = [c for c in allc.values() if c.get("wside") is not None]
    want = R.layout(cfg)["weekly_ema_coins"]
    rows = []
    for s in [x.upper() for x in want]:
        c = allc.get(s)
        if not c:
            continue
        if c.get("wside") is None:
            rows.append([s, "—", "—", "—", f"za krótka historia ({c.get('weeks', 0)} z {min_w} tyg.)", "—", "—"])
            continue
        new = c.get("wcross_t") == t_end
        side = ("nad" if c["wside"] > 0 else "pod") + (" (przecięcie w tym tygodniu)" if new else "")
        rows.append([s, R.fmt_price(c["wc"]), R.fmt_price(c["wec"]), f"{(c['wc'] / c['wec'] - 1) * 100:+.1f}%", side,
                     str(c.get("wsince")), R.utc(c["wcross_t"], "%d.%m.%Y") if c.get("wcross_t") else "—"])
    br = w.get("breadth") or []
    v0, n0 = _week_pct(br, t_end)
    v1, _ = _week_pct(br, t_end - WEEK)
    v4, _ = _week_pct(br, t_end - 4 * WEEK)
    up = sorted(c["s"] for c in wcoins if c.get("wcross_t") == t_end and c["wside"] > 0)
    dn = sorted(c["s"] for c in wcoins if c.get("wcross_t") == t_end and c["wside"] < 0)
    cross = ("Przecięcia na zamknięciu tygodnia (wszystkie coiny z EMA200 1W): "
             + ("; ".join(x for x in ((f"w górę: {', '.join(up)}" if up else ""),
                                       (f"w dół: {', '.join(dn)}" if dn else "")) if x) if up or dn else "brak") + ".")
    note = cross
    if v0 is not None:
        above = sum(1 for c in wcoins if c["wside"] > 0)
        note = (f"Nad EMA200 1W na zamknięciu tygodnia: {above} z {n0} coinów ({v0:.0f}%)"
                + (f"; tydzień wcześniej {v1:.0f}%" if v1 is not None else "")
                + (f", 4 tygodnie wcześniej {v4:.0f}%" if v4 is not None else "")
                + (f" (historia od {R.utc(br[0][0], '%m.%Y')})" if br else "") + ". " + cross)
    out = []
    if rows:
        out.append({"type": "table", "title": title,
                    "cols": ["Coin", "Zamknięcie tygodnia", f"EMA{per} 1W", "Odległość", "Strona", "Tygodni po tej stronie",
                             "Ostatnie przecięcie (zamknięcie tygodnia)"],
                    "rows": rows, "left": [0, 4], "plain": True,
                    "desc": f"Zamknięcie świecy tygodniowej (niedziela 24:00 UTC, Binance spot */USDT) względem EMA{per} "
                            f"liczonej na świecach tygodniowych — te same wartości pokazuje TradingView na wykresie 1W pary "
                            f"z Binance. Tylko coiny z co najmniej {min_w} tygodniami historii (ok. "
                            f"{min_w * 7 / 365.25:.1f} roku).",
                    "note": note})
    else:
        out.append({"type": "text", "title": title, "text": note})
    return out


def ema_crosses(ema, start, end, min_vol, head=True):
    coins = (ema or {}).get("coins") or []
    hits = [c for c in coins if c.get("cross_t") and start <= c["cross_t"] < end]
    up = sum(1 for c in hits if c.get("side", 0) > 0)
    big = [c for c in hits if (c.get("vol") or 0) >= min_vol]
    big.sort(key=lambda c: -(c.get("vol") or 0))
    rows = [[c["s"], "w górę" if c.get("side", 0) > 0 else "w dół", R.utc(c["cross_t"], "%d.%m"),
             R.fmt_price(c.get("p")), f"{c.get('d', 0):+.1f}%", alerts.fmt_value(c.get("vol"), "liq")] for c in big[:20]]
    head = [{"type": "section", "title": "EMA200 — przecięcia w tygodniu"}] if head else []
    txt = (f"W tygodniu {len(hits)} coinów przecięło EMA200 na zamknięciu dnia: {up} w górę, {len(hits) - up} w dół "
           f"(wszystkie coiny, bez progu obrotu).")
    if not rows:
        return head + [{"type": "text", "title": "EMA200 na świecy dziennej — przecięcia w tygodniu",
                        "text": txt + f" Żaden z obrotem ≥ {alerts.fmt_value(min_vol, 'liq')} dziennie."}]
    return head + [{"type": "table", "title": f"EMA200 na świecy dziennej — przecięcia coinów z obrotem ≥ {alerts.fmt_value(min_vol, 'liq')} dziennie",
                   "cols": ["Coin", "Kierunek", "Dzień", "Cena dziś", "Odległość od EMA dziś", "Obrót/dzień"],
                   "rows": rows, "plain": True, "desc": txt,
                   "note": "Binance spot */USDT, świeca dzienna. Kierunek i dzień ostatniego przecięcia; jeśli coin przeciął "
                           "średnią kilka razy, liczy się ostatnie."}]


# ── makro ────────────────────────────────────────────────────
def _pl_day(ts):
    from zoneinfo import ZoneInfo
    dt = datetime.fromtimestamp(ts, ZoneInfo("Europe/Warsaw"))
    return f"{DAYS_SHORT[dt.weekday()]} {dt.strftime('%d.%m')}"


def macro_blocks(macro, start, end, plan_from, plan_end, cfg, plan_min_imp, word):
    """Wyniki ★★★ z okresu [start, end) i plan na [plan_from, plan_end) — plan od chwili budowy raportu
    (raport z ręki w środku tygodnia/miesiąca nie pokazuje publikacji, które już były)."""
    head = {"type": "section", "title": "Makro USA"}
    if macro is None:
        return [head]
    if macro.get("error"):
        return [head, {"type": "text", "title": "", "text": f"Kalendarz ekonomiczny niedostępny ({macro['error']})."}]
    evs = [dict(e, _ts=econ._ts(e)) for e in macro.get("events") or [] if e.get("date")]
    st = econ.settings(cfg)
    countries = [c.upper() for c in st["countries"] or []]
    evs = [e for e in evs if not countries or str(e.get("country") or "").upper() in countries]
    out = [head]
    past = econ._sorted([e for e in evs if start <= e["_ts"] < end and (e.get("importance") or 0) >= 1])
    if past:
        out.append({"type": "table", "title": f"Wyniki publikacji ★★★ — {word}",
                    "cols": ["Dzień", "Godz. PL", "Publikacja", "Wynik", "Prognoza", "Poprzednio", "Wynik − prognoza"],
                    "rows": [[_pl_day(e["_ts"]), econ.pl_hm(e["_ts"]), econ._name(e), econ.fmt_num(e.get("actual"), e),
                              econ.fmt_num(e.get("forecast"), e), econ.fmt_num(e.get("previous"), e), econ.diff_text(e)]
                             for e in past],
                    "plain": True, "left": [2],
                    "desc": "Najważniejsze dane z USA (wysoka ważność według TradingView) z okresu raportu.",
                    "note": "Prognoza = oczekiwanie rynku przed publikacją. Godziny w czasie polskim. Wystąpienia nie mają liczb."})
    else:
        out.append({"type": "text", "title": "", "text": f"Brak publikacji ★★★ — {word}."})
    nxt = econ._sorted([e for e in evs if plan_from <= e["_ts"] < plan_end and (e.get("importance") or 0) >= plan_min_imp])
    stars = "★★ i ★★★" if plan_min_imp <= 0 else "★★★"
    if nxt:
        out.append({"type": "table", "title": f"Plan — {stars}, {R.utc(plan_from, '%d.%m')}–{R.utc(plan_end - DAY, '%d.%m.%Y')}",
                    "cols": ["Dzień", "Godz. PL", "Publikacja", "Ważność", "Prognoza", "Poprzednio"],
                    "rows": [[_pl_day(e["_ts"]), econ.pl_hm(e["_ts"]), econ._name(e), econ.STARS.get(e.get("importance"), ""),
                              econ.fmt_num(e.get("forecast"), e), econ.fmt_num(e.get("previous"), e)] for e in nxt],
                    "plain": True, "left": [2],
                    "desc": "Co i kiedy wyjdzie w USA od chwili raportu (według kalendarza TradingView; terminy i prognozy mogą się "
                            "zmienić).",
                    "note": "Godziny w czasie polskim."})
    return out


MACRO_SIDS = ["net_liq", "m2", "dxy", "spx", "ndx", "vix", "us10y", "yc_10y2y", "gold"]


# ── cykl BTC (miesięczny) ────────────────────────────────────
def cycle_blocks(d, t_end, cfg=None):
    import cycle as C
    cc = C.ccfg(cfg or {})
    manual = cc.get("bottoms") or ()
    px_pts = d.pts("1d", "px_btc")
    px = {t: v for t, v in px_pts if t <= t_end}
    if not px:
        return []
    out = [{"type": "section", "title": "Gdzie jesteśmy w cyklu BTC"}]
    v = px[max(px)]
    t_ath = max(px, key=px.get)
    halv = [C.day_of(h) for h in C.HALVINGS]
    h_now = max(h for h in halv if h <= t_end)
    rp = close(d.pts("1d", "rprice_btc"), t_end)
    items = [{"label": "Cena BTC (zamknięcie)", "value": R.fmt_price(v), "sub": R.utc(max(px), "%d.%m.%Y"), "zone": None, "note": ""},
             {"label": "Od szczytu (ATH)", "value": f"{(v / px[t_ath] - 1) * 100:+.1f}%",
              "sub": f"ATH {R.fmt_price(px[t_ath])} ({R.utc(t_ath, '%d.%m.%Y')}, zamknięcie dnia), {(t_end - t_ath) // DAY} dni temu"
              + (lambda w: f"; najwyższa cena (knot) {R.fmt_price(w[1])} ({R.utc(w[0], '%d.%m.%Y')})" if w else "")(
                  max((p for p in d.pts("1d", "px_btc_hi") if p[0] <= t_end), key=lambda p: p[1], default=None)),
              "zone": None, "note": "Fazy i szczyty cyklu liczymy z zamknięć dziennych; knot = najwyższa cena w trakcie dnia "
                                    "(Binance perp przez Coinalyze, od 2020)."},
             {"label": "Od halvingu", "value": f"{(t_end - h_now) // DAY} dni",
              "sub": f"halving {R.utc(h_now, '%d.%m.%Y')}", "zone": None, "note": ""}]
    if rp:
        items.append({"label": "Cena vs realized price", "value": f"{(v / rp - 1) * 100:+.1f}%",
                      "sub": f"realized price {R.fmt_price(rp)}", "zone": None, "note": ""})
    phs = C.phases(px, manual)
    bad_manual = []
    if manual and phs and phs[-1]["phase"] == "bear":
        bad_manual = list(manual)           # wpis w configu, który nie zadziałał (cena zamknęła się niżej / zła data)
    if phs:
        cur = phs[-1]
        n = (t_end - cur["from"]) // DAY
        if cur["phase"] == "bear":
            after = {t: x for t, x in px.items() if t > cur["from"]}
            t_lo = min(after, key=after.get) if after else None
            sub = (f"od szczytu {R.utc(cur['from'], '%d.%m.%Y')}; najniższe zamknięcie od szczytu "
                   f"{R.fmt_price(after[t_lo])} ({R.utc(t_lo, '%d.%m.%Y')}, {(after[t_lo] / px[cur['from']] - 1) * 100:+.0f}%)"
                   if t_lo else f"od szczytu {R.utc(cur['from'], '%d.%m.%Y')}")
            note = ("Bessa trwa formalnie do potwierdzenia dna cyklu (najniższe zamknięcie między szczytem a następnym "
                    "halvingiem) — reguła pod wykresem faz.")
        elif cur["phase"] == "acc":
            v_bot = px[cur["from"]]
            prev_top = max((p for p in phs if p["phase"] == "bear" and p["to"] == cur["from"]), key=lambda p: p["from"])
            v_top = px[prev_top["from"]]
            sub = (f"od dna {R.utc(cur['from'], '%d.%m.%Y')} ({R.fmt_price(v_bot)}); cena {(v / v_bot - 1) * 100:+.0f}% od dna; "
                   f"do poprzedniego szczytu ({R.fmt_price(v_top)}) brakuje {(v_top / v - 1) * 100:+.0f}%")
            note = ("Akumulacja = od dna cyklu do pierwszego zamknięcia powyżej poprzedniego szczytu."
                    + (" Niepotwierdzona: dno uznane przez nas w config.yaml (cycle.bottoms); pewność daje zamknięcie "
                       "powyżej poprzedniego szczytu albo halving bez niższego zamknięcia." if cur.get("confirmed") is False
                       else ""))
        else:
            sub = f"od {R.utc(cur['from'], '%d.%m.%Y')}"
            note = ""
        past = [(p["to"] - p["from"]) // DAY for p in phs if p["phase"] == cur["phase"] and p["to"] is not None
                and p["from"] >= _ts(datetime(2013, 1, 1))]
        if past:
            sub += f"; poprzednie: {min(past)}–{max(past)} dni"
        items.insert(1, {"label": "Faza cyklu", "value": f"{phase_name(cur).capitalize()} · dzień {n}",
                         "sub": sub, "zone": None, "note": note})
    out.append({"type": "facts", "title": "Stan na zamknięcie miesiąca", "items": items})
    if bad_manual:
        out.append({"type": "text", "title": "Uwaga",
                    "text": f"Dno wpisane w config.yaml (cycle.bottoms: {', '.join(map(str, bad_manual))}) nie obowiązuje — "
                            "po nim cena zamknęła się niżej albo data nie pasuje. Fazy liczone samą regułą."})
    acc_now = bool(phs and phs[-1]["phase"] == "acc" and phs[-1]["to"] is None and manual)
    out.append(price_chart(d, px, t_end, phs, (
        f"Dno bieżącego cyklu ({R.utc(phs[-1]['from'], '%d.%m.%Y')}) uznane przez nas w config.yaml (cycle.bottoms), "
        "dlatego akumulacja jest niepotwierdzona (fioletowa) — pewność daje pierwsze zamknięcie powyżej poprzedniego "
        "szczytu albo halving bez niższego zamknięcia. Jeśli cena zamknie się poniżej dna, wpis przestanie działać "
        "(wróci bessa).") if acc_now else ""))
    tbl = phase_table(px, phs, t_end)
    if tbl:
        out.append(tbl)
    out += projection_block(px, phs, t_end, cc)
    # porównanie z poprzednimi cyklami (te same dni po halvingu i po szczycie)
    tops, bottoms = C.cycle_extremes(px, manual)
    n_h = t_end - h_now
    cur_win = {t: x for t, x in px.items() if t >= h_now}
    t_top_now = max(cur_win, key=cur_win.get) if cur_win else None
    n_top = t_end - t_top_now if t_top_now else None
    rows = []
    for i, h in enumerate(halv[:-1]):
        top = next(((t, x) for t, x in tops if h <= t < h + C.TOP_WINDOW_DAYS * DAY), None)
        if not top:
            continue
        a = close(px_pts, h + n_h)
        b = close(px_pts, top[0] + n_top) if n_top is not None else None
        bot = next(((t, x) for t, x in bottoms if t > top[0] and (i + 1 >= len(halv) or t < halv[i + 1])), None)
        rows.append([f"{R.utc(h, '%Y')}–{R.utc(halv[i + 1], '%Y')}", f"{R.utc(top[0], '%m.%Y')} ({(top[0] - h) // DAY} dni)",
                     f"{(a / top[1] - 1) * 100:+.0f}%" if a else "—", f"{(b / top[1] - 1) * 100:+.0f}%" if b else "—",
                     f"{(bot[1] / top[1] - 1) * 100:+.0f}% po {(bot[0] - top[0]) // DAY} dniach" if bot else "—"])
    if t_top_now:
        bot = next(((t, x) for t, x in bottoms if t > t_top_now), None)
        rows.append([f"{R.utc(h_now, '%Y')}– (obecny)", f"{R.utc(t_top_now, '%m.%Y')} ({(t_top_now - h_now) // DAY} dni)",
                     f"{(v / cur_win[t_top_now] - 1) * 100:+.0f}%", f"{(v / cur_win[t_top_now] - 1) * 100:+.0f}%",
                     f"{(bot[1] / cur_win[t_top_now] - 1) * 100:+.0f}% po {(bot[0] - t_top_now) // DAY} dniach"
                     + (" (uznane)" if manual else "") if bot else "—"])
    if rows:
        out.append({"type": "table", "title": "Obecny cykl na tle poprzednich", "plain": True, "left": [0],
                    "cols": ["Cykl (halving)", "Szczyt (dni po halvingu)", f"Cena {n_h // DAY} dni po halvingu vs szczyt",
                             f"Cena {n_top // DAY if n_top else '—'} dni po szczycie vs szczyt", "Dno cyklu vs szczyt"],
                    "rows": rows,
                    "desc": "Gdzie była cena w poprzednich cyklach w tym samym momencie: tyle samo dni po halvingu i tyle "
                            "samo dni po szczycie cyklu co dziś. Cykl = okres między halvingami.",
                    "note": "Szczyt = najwyższe zamknięcie dnia w 2 latach po halvingu; dno = najniższe między szczytem a "
                            "następnym halvingiem. Liczone z dziennych zamknięć ceny BTC (od 2009)."})
    # wskaźniki cyklu na tle poprzednich szczytów i den (liczone tu z danych i configu — jak meta.ref_lines)
    ref = C.ref_lines_from({sid: dict(d.pts("1d", sid)) for sid in ("px_btc",) + REPORT_CYCLE_SIDS}, cfg or {})
    items = []
    for sid in REPORT_CYCLE_SIDS:
        since = RANGE_FROM["ssr" if sid == "ssr" else "default"]
        pts = [p for p in d.pts("1d", sid) if since <= p[0] <= t_end]
        val = close(pts, t_end)
        if val is None:
            continue
        f = fmt_of(d, sid) or "x"
        marks = [(ln["value"], f"{ln['label']}: {fv(ln['value'], f)}") for ln in ref.get(sid) or []
                 if ln.get("label", "").startswith(("szczyt", "dno"))]
        it = R.range_item(d, d.name(sid), pts, val, f, (d.catalog.get(sid) or {}).get("desc", ""), None, 30,
                          marks=marks, fmt=lambda x, f=f: fv(x, f))
        for m in it.get("marks") or []:
            m["kind"] = "top" if m["label"].startswith("szczyt") else "bottom"
        items.append(it)
    if items:
        out.append({"type": "ranges", "title": "Wskaźniki cyklu na tle trzech ostatnich cykli", "items": items,
                    "desc": "Pasek = zakres wskaźnika od 2017 (SSR od 2020 — wcześniej stablecoinów było za mało). Kropka = "
                            "zamknięcie miesiąca; czerwone znaczniki = wartości przy szczytach poprzednich cykli, zielone = "
                            "przy dnach (wyznaczone z danych).",
                    "note": "MVRV i realized price: Coin Metrics Community; Mayer, cena/200W — z ceny BTC; SSR — TradingView. "
                            "Opis każdego wskaźnika pod paskiem. Pi Cycle (nie przeciął się przy szczytach 11.2021 i "
                            "10.2025) — tylko w zakładce OI & TOTAL."})
    return out


PHASE_COLORS = {"bull": "#4caf7d", "bear": "#e05252", "acc": "#5b9cf6", "unsure": "#b39ddb"}


def phase_name(p):
    return PHASE_NAMES[p["phase"]] + (" niepotwierdzona" if p.get("confirmed") is False else "")


def phase_bands(phs, t_last):
    return [{"from": p["from"], "to": p["to"] or t_last,
             "color": PHASE_COLORS["unsure" if p.get("confirmed") is False else p["phase"]],
             "label": phase_name(p) + (" (trwa)" if p["to"] is None else "")} for p in phs]


def price_chart(d, px, t_end, phs, manual_note=""):
    """Cena BTC (log, świece miesięczne) od 2011 z realized price, średnią 200 tygodni i tłem w kolorach faz cyklu."""
    since = _ts(datetime(2011, 1, 1))
    ts = sorted(px)
    vals = [px[t] for t in ts]
    last_of = {}
    for t in ts:
        last_of[_month_key(t)] = t
    month_end = set(last_of.values())
    keep = lambda t: t >= since and (t in month_end or t == ts[-1])  # noqa: E731 — koniec miesiąca (świece 1M)
    p = [[t, px[t]] for t in ts if keep(t)]
    sma = [[ts[i], sum(vals[i - 1399:i + 1]) / 1400] for i in range(1399, len(vals)) if keep(ts[i])]
    candles = ohlc_groups(d, "px_btc", ts[-1], _month_key, since) if d.pts("1d", "px_btc") else []
    series = [{"name": "Cena BTC — świece miesięczne", "color": "#f7931a", "fmt": "price", "scale": "right", "data": p}]
    if candles and [c[0] for c in candles] == [x[0] for x in p]:
        series[0]["ohlc"] = candles
    rpp = [x for x in d.pts("1d", "rprice_btc") if x[0] <= t_end and keep(x[0])]
    if rpp:
        series.append({"name": "Realized price", "color": "#ffd54f", "fmt": "price", "scale": "right", "data": rpp})
    if sma:
        series.append({"name": "Średnia 200 tygodni", "color": "#4dd0e1", "fmt": "price", "scale": "right", "data": sma})
    return {"type": "chart", "title": "Cena BTC i fazy cyklu — od 2011", "log": True, "series": series,
            "bands": [b for b in phase_bands(phs, ts[-1]) if b["to"] >= since],
            "desc": "Tło: zielone = hossa, czerwone = bessa, niebieskie = akumulacja, fioletowe = akumulacja niepotwierdzona "
                    "(dno uznane przez nas, jeszcze bez pewności — reguła w opisie pod wykresem). "
                    "Skala logarytmiczna, świece miesięczne (knoty: do 2019–2020 indeks TradingView, potem Binance perp). "
                    "Realized price = średnia cena, po której monety ostatnio się ruszały; średnia 200 tygodni = 1400 dni "
                    "(obie linie: wartość z ostatniego dnia miesiąca).",
            "note": "Fazy wyznaczone z dziennych zamknięć ceny BTC: bessa = od szczytu cyklu do dna cyklu; akumulacja = od "
                    "dna do pierwszego zamknięcia powyżej poprzedniego szczytu (cena odrobiła bessę); hossa = od tego "
                    "zamknięcia do kolejnego szczytu. Szczyt = najwyższe zamknięcie w 2 latach po halvingu (liczy się po "
                    "spadku o ≥ 50%), dno = najniższe zamknięcie między szczytem a następnym halvingem (reguła potwierdza "
                    "je dopiero po halvingu)." + (" " + manual_note if manual_note else "")}


def projection_block(px, phs, t_end, cc):
    """Okna kolejnych etapów, gdyby powtórzyły się długości z trzech ostatnich pełnych cykli (od dna 01.2015)."""
    import cycle as C
    if not phs:
        return []
    cur = phs[-1]
    tops = [p["from"] for p in phs if p["phase"] == "bear"]                 # szczyty (początki bess)
    bottoms = [p["from"] for p in phs if p["phase"] == "acc"]               # dna (początki akumulacji)
    since = _ts(datetime(2015, 1, 1))
    rows = []

    def span(vals):
        return f"{min(vals)}–{max(vals)}" if len(set(vals)) > 1 else str(vals[0])

    def window(base, vals):
        a, b = base + min(vals) * DAY, base + max(vals) * DAY
        return f"{R.utc(a, '%m.%Y')} – {R.utc(b, '%m.%Y')}" if R.utc(a, "%m.%Y") != R.utc(b, "%m.%Y") else R.utc(a, "%m.%Y")
    peaks = []
    last_bot = bottoms[-1] if bottoms and cur["phase"] != "bear" else None
    last_top = tops[-1] if tops else None
    # koniec akumulacji (zamknięcie powyżej poprzedniego szczytu)
    accs = [(p["to"] - p["from"]) // DAY for p in phs if p["phase"] == "acc" and p["to"] and p["from"] >= since]
    if cur["phase"] == "acc" and accs:
        rows.append(["Koniec akumulacji (zamknięcie powyżej poprzedniego szczytu)", "dno + długość akumulacji",
                     span(accs), window(cur["from"], accs)])
    # szczyt: dno → szczyt
    b2t = [(t - b) // DAY for b in bottoms for t in tops if b >= since and t > b and
           t == min([x for x in tops if x > b], default=None)]
    if last_bot and b2t:
        rows.append(["Kolejny szczyt cyklu", "dno + (dno → szczyt)", span(b2t), window(last_bot, b2t)])
        peaks.append((last_bot + min(b2t) * DAY, last_bot + max(b2t) * DAY))
    # szczyt: szczyt → szczyt
    t2t = [(b - a) // DAY for a, b in zip(tops, tops[1:]) if a >= _ts(datetime(2013, 1, 1))]
    if last_top and t2t:
        rows.append(["Kolejny szczyt cyklu", "poprzedni szczyt + (szczyt → szczyt)", span(t2t), window(last_top, t2t)])
        peaks.append((last_top + min(t2t) * DAY, last_top + max(t2t) * DAY))
    # szczyt: halving → szczyt
    halv = [C.day_of(h) for h in C.HALVINGS]
    h2t = [(t - h) // DAY for h in halv for t in tops if h >= since and h < t < h + C.TOP_WINDOW_DAYS * DAY]
    try:
        nh = C.day_of(str(cc.get("next_halving_estimate") or ""))
    except ValueError:
        nh = None
    if nh and h2t:
        rows.append(["Kolejny szczyt cyklu", f"halving (szacunek {R.utc(nh, '%m.%Y')}) + (halving → szczyt)",
                     span(h2t), window(nh, h2t)])
        peaks.append((nh + min(h2t) * DAY, nh + max(h2t) * DAY))
    if not rows:
        return []
    desc = ("Szacunek, nie prognoza: kiedy wypadłyby kolejne etapy, gdyby powtórzyły się długości z trzech ostatnich pełnych "
            "cykli (2015–2018, 2018–2022, 2022–2025).")
    if peaks:
        a, b = min(p[0] for p in peaks), max(p[1] for p in peaks)
        desc += f" Łączne okno szczytu ze wszystkich metod: {R.utc(a, '%m.%Y')} – {R.utc(b, '%m.%Y')}."
    return [{"type": "table", "title": "Okno szacunkowe kolejnych etapów cyklu", "plain": True, "left": [0, 1],
             "cols": ["Etap", "Metoda", "W poprzednich cyklach (dni)", "Gdyby się powtórzyło"], "rows": rows, "desc": desc,
             "note": "Długości liczone z dziennych zamknięć ceny BTC; szczyty i dna jak w tabeli faz. Data następnego halvingu "
                     "to szacunek z config.yaml (cycle.next_halving_estimate). Cykl 2011–2013 pominięty (rynek był wtedy zbyt "
                     "mały i krótki, żeby go porównywać)."}]


def phase_table(px, phs, t_end):
    """Tabela faz: wiersz na szczyt cyklu — akumulacja przed nim, hossa, bessa po nim (dni i zmiana ceny)."""
    def cell(p):
        if p is None:
            return "—"
        to = p["to"] or t_end
        a, b = px.get(p["from"]), px.get(to)
        ch = f", {(b / a - 1) * 100:+.0f}%" if a and b else ""
        tail = "trwa" if p["to"] is None else R.utc(to, "%m.%Y")
        mark = ""
        if p.get("confirmed") is False:
            mark = " (niepotwierdzona)"
        elif p["phase"] == "bear" and p["to"] in unsure:
            mark = " (dno niepotwierdzone)"
        return f"{R.utc(p['from'], '%m.%Y')}–{tail}: {(to - p['from']) // DAY} dni{ch}{mark}"
    unsure = {p["from"] for p in phs if p.get("confirmed") is False}
    rows = []
    bears = [p for p in phs if p["phase"] == "bear"]
    for bear in bears:
        bull = next((p for p in phs if p["phase"] == "bull" and p["to"] == bear["from"]), None)
        acc = next((p for p in phs if p["phase"] == "acc" and bull and p["to"] == bull["from"]), None)
        rows.append([R.utc(bear["from"], "%m.%Y"), cell(acc), cell(bull), cell(bear)])
    last = phs[-1] if phs else None
    if last and last["phase"] in ("acc", "bull") and last["to"] is None:     # trwa akumulacja / hossa przed szczytem
        acc = last if last["phase"] == "acc" else next((p for p in phs if p["phase"] == "acc" and p["to"] == last["from"]), None)
        rows.append(["(następny)", cell(acc), cell(last) if last["phase"] == "bull" else "—", "—"])
    if not rows:
        return []
    return {"type": "table", "title": "Fazy kolejnych cykli — czas trwania i zmiana ceny", "plain": True, "left": [0, 1, 2, 3],
            "cols": ["Szczyt cyklu", "Akumulacja przed szczytem", "Hossa", "Bessa po szczycie"], "rows": rows,
            "desc": "Ile trwała każda faza i o ile zmieniła się w niej cena BTC (zamknięcie na końcu fazy ÷ na początku). "
                    "Reguła wyznaczania faz — pod wykresem powyżej.",
            "note": "Pierwszy wiersz: szczyt z 06.2011 (dane od 2010, więc bez akumulacji i hossy przed nim)."}


def month_return(px, y, m):
    """Zwrot BTC w miesiącu (y, m): zamknięcie miesiąca ÷ zamknięcie poprzedniego − 1, w %; None gdy brak danych."""
    while m < 1:
        m, y = m + 12, y - 1
    while m > 12:
        m, y = m - 12, y + 1
    a = _ts(datetime(y, m, 1))
    b = month_start(a + 32 * DAY)
    v0, v1 = close(px, a - DAY), close(px, b - DAY)
    return (v1 / v0 - 1) * 100 if v0 and v1 else None


def seasonality(d, start, end):
    """Zwrot BTC w tym miesiącu oraz w miesiącu poprzednim i następnym — w kolejnych latach od 2011."""
    px = [p for p in d.pts("1d", "px_btc") if p[0] < end]          # bez danych z nowego miesiąca
    y_now, m = _dt(start).year, _dt(start).month
    offs = (-1, 0, 1)
    names = [MONTHS[(m - 1 + k) % 12] for k in offs]
    rows_y = []
    for y in range(2011, y_now + 1):
        rets = [month_return(px, y, m + k) for k in offs]
        if rets[1] is not None:
            rows_y.append((y, rets))
    hist = [r for y, r in rows_y if y != y_now]
    if len(hist) < 3:
        return []

    def col(i):
        return [r[i] for r in hist if r[i] is not None]
    pct = lambda x: "—" if x is None else f"{x:+.1f}%"  # noqa: E731
    med = ["Mediana"] + [pct(statistics.median(col(i))) if col(i) else "—" for i in range(3)]
    ups = ["Lat na plus"] + [f"{sum(1 for x in col(i) if x > 0)} z {len(col(i))}" if col(i) else "—" for i in range(3)]
    rows = [med, ups] + [[str(y)] + [pct(x) for x in r] for y, r in reversed(rows_y)]
    prev_lbl = names[0] + (" (rok wcześniej)" if m == 1 else "")
    next_lbl = names[2] + (" (rok później)" if m == 12 else "")
    return [{"type": "table", "title": f"{names[1].capitalize()} w historii BTC — z miesiącem przed i po",
             "cols": ["Rok", prev_lbl.capitalize(), names[1].capitalize() + " (ten miesiąc)", next_lbl.capitalize()],
             "rows": rows, "left": [0],
             "desc": f"Zwrot BTC w miesiącu „{names[1]}” w kolejnych latach, obok miesiąc przed nim („{names[0]}”) i po nim "
                     f"(„{names[2]}”) — co działo się historycznie wokół tego miesiąca. Dwa pierwsze wiersze: mediana i "
                     f"liczba lat na plus z lat wcześniejszych (bez {y_now}).",
             "note": "Zwrot = zamknięcie miesiąca ÷ zamknięcie poprzedniego − 1. Cena BTC: TradingView INDEX:BTCUSD (do 03.2020) "
                     "i Coinalyze. Statystyka z kilkunastu lat — mała próba."}]


# ── budowa ───────────────────────────────────────────────────
def build(d, ema, kind, now, cfg, macro):
    L = R.layout(cfg)
    start, end = period(kind, now)
    t_end = end - DAY
    plan_from = max(end, int(now) - int(now) % DAY)      # plan makro: od dnia budowy (raport z ręki w środku okresu)
    blocks, warn = [], []
    if d.updated and d.updated < end:
        warn.append(f"dane OI/TOTAL z {R.pl_time(d.updated)} — sprzed zamknięcia okresu")
    if not d.updated:
        warn.append("brak danych z gałęzi data")
    ema_upd = (ema or {}).get("updated") or 0
    if ema and ema.get("daily_at") and ema["daily_at"] < end:
        warn.append("EMA200 i szerokość rynku sprzed zamknięcia okresu")
    if warn:
        blocks.append({"type": "text", "title": "Uwaga", "text": "; ".join(warn) + "."})

    if kind == "weekly":
        hz = [("1 tydzień", t_end - WEEK), ("4 tygodnie", t_end - 4 * WEEK)]
        blocks += [{"type": "section", "title": "Tydzień w liczbach"}]
        blocks += change_table(d, ema, ["px_btc", "px_eth", "total", "total2", "total3es", "btc_d", "ethbtc", "stable_d",
                                        "stable_mcap"], t_end, start, end, hz, "Zamknięcie tygodnia i zmiany",
                               "Zamknięcie świecy tygodniowej (niedziela 24:00 UTC) i zmiana do zamknięcia tydzień i 4 tygodnie "
                               "wcześniej.")
        blocks += btc_weekly_mas(d, t_end)
        blocks += [{"type": "section", "title": "Alty w tygodniu"}]
        blocks += change_table(d, ema, ["oi_others_vs_btc", "alts_vs_btc", "breadth", "fund_others"], t_end, start, end, hz,
                               "Lewar, kapitał i szerokość — zamknięcie tygodnia",
                               "Lewar altów (OI OTHERS / OI BTC), kapitał altów (Alty / BTC), odsetek coinów nad EMA200 i "
                               "funding altów. Oba stosunki rosną razem = kapitał naprawdę płynie w alty.")
        blocks += [{"type": "section", "title": "Derywaty w tygodniu"}]
        rows = oi_rows(d, start, end, float(L["oi_flat_pct"]))
        if rows:
            blocks.append({"type": "table", "title": "Open interest, cena i funding — tydzień",
                           "cols": ["Coin", "Cena", "OI (w coinach)", "OI ($)", "Co to znaczy", "Funding — śr. tygodnia",
                                    "Funding — śr. 12 tyg. wcześniej"], "rows": rows, "left": [4],
                           "desc": "Zmiana w tygodniu: cena ↑ + OI ↑ = nowe longi; cena ↓ + OI ↑ = nowe shorty; cena ↑ + OI ↓ = "
                                   "zamykanie shortów; cena ↓ + OI ↓ = zamykanie longów. Funding w % rocznie (neutralnie ok. 11%).",
                           "note": "OI w coinach = OI w dolarach ÷ cena. Zmiana poniżej 1% = „bez zmian”."})
        blocks += cvd_weekly(d, start, end, cfg)
        mondays = list(range(start - 104 * WEEK, end + 1, WEEK))
        blocks += liq_block(d, "weekly", mondays, lambda a: R.utc(a, "%d.%m"), start, end, end - 104 * WEEK)
        blocks += [{"type": "section", "title": "EMA200 w tygodniu"}]
        blocks += ema_weekly(ema, t_end, cfg)
        blocks += ema_crosses(ema, start, end, float(L["ema_min_volume"]), head=False)
        blocks += macro_blocks(macro, start, end, plan_from, plan_from + WEEK, cfg, 0, "miniony tydzień")
        blocks += change_table(d, ema, [x for x in MACRO_SIDS if x != "m2"], t_end, start, end, hz,
                               "Rynki i płynność — zamknięcie tygodnia",
                               "Dolar, giełda w USA, strach (VIX), obligacje, złoto i płynność Fed. Dane dzienne z TradingView "
                               "(płynność Fed: odczyty tygodniowe; M2 — w raporcie miesięcznym).")
        blocks += [{"type": "section", "title": "Cykl BTC w tygodniu"}]
        blocks += change_table(d, ema, list(REPORT_CYCLE_SIDS), t_end,
                               start, end, hz, "Wskaźniki cyklu — zamknięcie tygodnia",
                               "Skrót; pełne porównanie z poprzednimi cyklami jest w raporcie miesięcznym i w zakładce OI & TOTAL.",
                               rng=False)
    else:
        m1, m3, m12 = month_start(end, 1), month_start(end, 3), month_start(end, 12)
        hz = [("1 mies.", m1 - DAY), ("3 mies.", m3 - DAY), ("12 mies.", m12 - DAY)]
        blocks += [{"type": "section", "title": "Miesiąc w liczbach"}]
        blocks += change_table(d, ema, ["px_btc", "px_eth", "total", "total3es", "btc_d", "ethbtc", "stable_d", "stable_mcap"],
                               t_end, start, end, hz, "Zamknięcie miesiąca i zmiany",
                               "Zamknięcie świecy miesięcznej i zmiana do zamknięcia 1, 3 i 12 miesięcy wcześniej.")
        blocks += seasonality(d, start, end)
        blocks += cycle_blocks(d, t_end, cfg)
        blocks += [{"type": "section", "title": "Struktura rynku"}]
        rows = []
        for sid in ("stable_mcap", "stable_d", "btc_d", "lev_btc", "lev_others", "oi_others_vs_btc", "alts_vs_btc",
                    "binance_share", "breadth", "oi_total"):
            pts = pts_of(d, sid, ema)
            v = close(pts, t_end)
            if v is None:
                continue
            name, f = label_fmt(d, sid)
            rows.append([name, fv(v, f)] + [fv(close(pts, tb), f) for _, tb in hz])
        if rows:
            blocks.append({"type": "table", "title": "Zamknięcia miesięczne — teraz i wcześniej", "plain": True, "left": [0],
                           "cols": ["Wskaźnik", "Koniec miesiąca", "Miesiąc wcześniej", "3 mies. wcześniej", "12 mies. wcześniej"],
                           "rows": rows,
                           "desc": "Wolno zmieniające się wskaźniki struktury rynku: gotówka w stablecoinach, dźwignia, "
                                   "lewar i kapitał altów, udział Binance w OI, szerokość rynku.",
                           "note": "Dźwignia = OI ÷ kapitalizacja (%). Udział Binance = OI BTC z Binance ÷ OI BTC ze wszystkich "
                                   "śledzonych giełd."})
        blocks += [{"type": "section", "title": "Derywaty w miesiącu"}]
        frows = []
        for coin in ("BTC", "ETH"):
            fund = d.pts("1d", f"fund_{coin.lower()}")
            months = {}
            for t, x in fund:
                if t < end:
                    months.setdefault(month_start(t), []).append(x)
            avgs = {m: statistics.mean(xs) for m, xs in months.items() if len(xs) >= 20}
            cur = avgs.get(start)
            if cur is None or len(avgs) < 6:
                continue
            hi, lo = max(avgs, key=avgs.get), min(avgs, key=avgs.get)
            frows.append([coin, f"{cur:+.1f}%", f"{R.percentile_rank(list(avgs.values()), cur):.0f}%",
                          f"{avgs[hi]:+.1f}% ({R.utc(hi, '%m.%Y')})", f"{avgs[lo]:+.1f}% ({R.utc(lo, '%m.%Y')})",
                          f"od {R.utc(min(avgs), '%m.%Y')}"])
        if frows:
            blocks.append({"type": "table", "title": "Funding — średnia miesiąca na tle historii", "plain": True,
                           "cols": ["Coin", "Średnia miesiąca", "Percentyl (0 = najniżej, 100 = najwyżej)", "Najwyższy miesiąc", "Najniższy miesiąc",
                                    "Historia"], "rows": frows,
                           "desc": "Średni funding miesiąca (% rocznie). Wysoko = longi płacą dużo za lewar (przegrzanie), "
                                   "ujemnie = przewaga shortów. Neutralnie ok. 11%.",
                           "note": "Przed 22.09.2022 średnia z wagami stałymi (udziały giełd w OI z pierwszych 30 dni danych OI)."})
        n_months = (_dt(end).year - 2022) * 12 + _dt(end).month - 10      # od 10.2022 (pierwszy pełny miesiąc likwidacji)
        starts = [month_start(end, k) for k in range(max(n_months, 13), -1, -1)]
        blocks += liq_block(d, "monthly", starts, lambda a: R.utc(a, "%m.%Y"), start, end, _ts(datetime(2022, 10, 1)))
        blocks += macro_blocks(macro, start, end, plan_from, max(month_start(plan_from + 32 * DAY), plan_from + WEEK),
                               cfg, 1, "miniony miesiąc")
        blocks += change_table(d, ema, MACRO_SIDS, t_end, start, end, hz, "Rynki i płynność — zamknięcie miesiąca",
                               "Dolar, giełda w USA, strach (VIX), obligacje, złoto, płynność Fed i M2.")

    parts = []
    for sid in ("px_btc", "total", "btc_d"):
        pts = pts_of(d, sid)
        v, f = close(pts, t_end), fmt_of(d, sid)
        if v is not None:
            back = t_end - WEEK if kind == "weekly" else month_start(end, 1) - DAY
            parts.append(f"{d.name(sid)} {fv(v, f)} ({chg(v, close(pts, back), f)})")
    br = close(R.breadth_series(ema), t_end)
    if br is not None:
        parts.append(f"szerokość rynku {br:.0f}%")
    return {"id": R.utc(now, "%Y%m%d-%H%M") + "-" + kind, "kind": kind, "layout": 2, "title": title(kind, start, end),
            "created": int(now), "summary": " · ".join(parts),
            "period": {"start": start, "end": end},
            "sources": {"data_updated": d.updated or None, "ema_updated": ema_upd or None}, "blocks": blocks}


def macro_window(kind):
    """Zakres kalendarza makro dla raportu: (dni wstecz, dni naprzód). Wstecz z zapasem na raport z ręki pod koniec
    okresu (okres raportu zaczyna się wtedy do 13 dni / 62 dni wcześniej)."""
    return (15, 9) if kind == "weekly" else (63, 38)
