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
HALVINGS = ("2012-11-28", "2016-07-09", "2020-05-11", "2024-04-19")
MONTHS = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień",
          "październik", "listopad", "grudzień"]
DAYS_SHORT = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]
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
DIFF_FMTS = ("pct", "yield", "pp", "z", "fund")


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


EXTRA = {"breadth": ("Szerokość rynku (% nad EMA200)", "pct"), "binance_share": ("Udział Binance w OI BTC", "pct"),
         "stable_mcap": ("Kapitał w stablecoinach", "mcap"), "stable_d": ("Udział stablecoinów", "pct"),
         "alts_vs_btc": ("Kapitał: Alty / BTC", "ratio")}


def label_fmt(d, sid):
    if sid in EXTRA and sid not in d.catalog:
        return EXTRA[sid]
    return d.name(sid), fmt_of(d, sid)


def change_table(d, ema, sids, t_end, start, end, horizons, title_, desc, note="", rng=True, labels=None):
    """Wiersze: zamknięcie okresu, zmiany do wcześniejszych zamknięć, zakres okresu z zamknięć dziennych."""
    rows = []
    for sid in sids:
        pts = pts_of(d, sid, ema)
        v = close(pts, t_end, sid)
        if v is None:
            continue
        name, f = label_fmt(d, sid)
        name = (labels or {}).get(sid, name)
        if sid in SLOW:
            last_t = max(p[0] for p in pts if p[0] <= t_end)
            name += f" (odczyt za {R.utc(last_t, '%m.%Y')})"
        row = [name, fv(v, f)] + [chg(v, close(pts, tb, sid), f) for _, tb in horizons]
        if rng:
            w = [x[1] for x in in_period(pts, start, end)]
            row.append(f"{fv(min(w), f)} – {fv(max(w), f)}" if w else "—")
        rows.append(row)
    if not rows:
        return []
    cols = ["Wskaźnik", "Zamknięcie"] + [h for h, _ in horizons] + (["Zakres w okresie"] if rng else [])
    note = note or ("Zmiany do zamknięć wcześniejszych okresów; dla wartości w % (dominacje, rentowności, funding) "
                    "różnica w punktach procentowych." + (" Zakres = najniższe i najwyższe zamknięcie dnia w okresie."
                                                           if rng else ""))
    return [{"type": "table", "title": title_, "cols": cols, "rows": rows, "left": [0], "desc": desc, "note": note}]


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
    series = [{"name": "BTC — zamknięcia tygodni", "color": "#f7931a", "fmt": "price", "scale": "right",
               "data": [p for p in wk if p[0] >= _ts(datetime(2017, 1, 1))]}]
    for n, col in ((20, "#4fc3f7"), (50, "#ffd54f"), (200, "#e05252")):
        ma_pts = [[wk[i][0], sum(vals[i - n + 1:i + 1]) / n] for i in range(n - 1, len(vals))
                  if wk[i][0] >= _ts(datetime(2017, 1, 1))]
        if ma_pts:
            series.append({"name": f"Średnia {n} tyg.", "color": col, "fmt": "price", "scale": "right", "data": ma_pts})
    return [{"type": "table", "title": "BTC na tle średnich tygodniowych", "cols": ["Średnia", "Wartość", "Cena vs średnia",
                                                                              "Strona", "Tygodni po tej stronie"],
             "rows": rows, "left": [0], "plain": True,
             "desc": "Gdzie jest zamknięcie tygodnia BTC względem średnich z 20, 50 i 200 tygodni (zwykłe średnie z "
                     "zamknięć tygodni). Długo nad średnimi = trend wzrostowy, pod = spadkowy.",
             "note": f"Zamknięcie tygodnia: {R.fmt_price(vals[-1])} ({R.utc(wk[-1][0], '%d.%m.%Y')})."},
            {"type": "chart", "title": "BTC i średnie tygodniowe — od 2017", "log": True, "series": series,
             "desc": "Zamknięcia tygodni BTC (skala logarytmiczna) ze średnimi 20, 50 i 200 tygodni."}]


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


# ── EMA200: przecięcia w tygodniu ────────────────────────────
def ema_crosses(ema, start, end, min_vol):
    coins = (ema or {}).get("coins") or []
    hits = [c for c in coins if c.get("cross_t") and start <= c["cross_t"] < end]
    up = sum(1 for c in hits if c.get("side", 0) > 0)
    big = [c for c in hits if (c.get("vol") or 0) >= min_vol]
    big.sort(key=lambda c: -(c.get("vol") or 0))
    rows = [[c["s"], "w górę" if c.get("side", 0) > 0 else "w dół", R.utc(c["cross_t"], "%d.%m"),
             R.fmt_price(c.get("p")), f"{c.get('d', 0):+.1f}%", alerts.fmt_value(c.get("vol"), "liq")] for c in big[:20]]
    head = {"type": "section", "title": "EMA200 — przecięcia w tygodniu"}
    txt = (f"W tygodniu {len(hits)} coinów przecięło EMA200 na zamknięciu dnia: {up} w górę, {len(hits) - up} w dół "
           f"(wszystkie coiny, bez progu obrotu).")
    if not rows:
        return [head, {"type": "text", "title": "", "text": txt + f" Żaden z obrotem ≥ {alerts.fmt_value(min_vol, 'liq')} dziennie."}]
    return [head, {"type": "table", "title": f"Przecięcia coinów z obrotem ≥ {alerts.fmt_value(min_vol, 'liq')} dziennie",
                   "cols": ["Coin", "Kierunek", "Dzień", "Cena dziś", "Odległość od EMA dziś", "Obrót/dzień"],
                   "rows": rows, "plain": True, "desc": txt,
                   "note": "Binance spot */USDT, świeca dzienna. Kierunek i dzień ostatniego przecięcia; jeśli coin przeciął "
                           "średnią kilka razy, liczy się ostatnie."}]


# ── makro ────────────────────────────────────────────────────
def _pl_day(ts):
    from zoneinfo import ZoneInfo
    dt = datetime.fromtimestamp(ts, ZoneInfo("Europe/Warsaw"))
    return f"{DAYS_SHORT[dt.weekday()]} {dt.strftime('%d.%m')}"


def macro_blocks(macro, start, end, plan_end, cfg, plan_min_imp, word):
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
    nxt = econ._sorted([e for e in evs if end <= e["_ts"] < plan_end and (e.get("importance") or 0) >= plan_min_imp])
    stars = "★★ i ★★★" if plan_min_imp <= 0 else "★★★"
    if nxt:
        out.append({"type": "table", "title": f"Plan — {stars}, {R.utc(end, '%d.%m')}–{R.utc(plan_end - DAY, '%d.%m.%Y')}",
                    "cols": ["Dzień", "Godz. PL", "Publikacja", "Ważność", "Prognoza", "Poprzednio"],
                    "rows": [[_pl_day(e["_ts"]), econ.pl_hm(e["_ts"]), econ._name(e), econ.STARS.get(e.get("importance"), ""),
                              econ.fmt_num(e.get("forecast"), e), econ.fmt_num(e.get("previous"), e)] for e in nxt],
                    "plain": True, "left": [2],
                    "desc": "Co i kiedy wyjdzie w nowym okresie (według kalendarza TradingView; terminy i prognozy mogą się zmienić).",
                    "note": "Godziny w czasie polskim."})
    return out


MACRO_SIDS = ["net_liq", "m2", "dxy", "spx", "ndx", "vix", "us10y", "yc_10y2y", "gold"]


# ── cykl BTC (miesięczny) ────────────────────────────────────
def cycle_blocks(d, t_end):
    import cycle as C
    px_pts = d.pts("1d", "px_btc")
    px = {t: v for t, v in px_pts if t <= t_end}
    if not px:
        return []
    out = [{"type": "section", "title": "Gdzie jesteśmy w cyklu BTC"}]
    v = px[max(px)]
    t_ath = max(px, key=px.get)
    halv = [C.day_of(h) for h in HALVINGS]
    h_now = max(h for h in halv if h <= t_end)
    rp = close(d.pts("1d", "rprice_btc"), t_end)
    items = [{"label": "Cena BTC (zamknięcie)", "value": R.fmt_price(v), "sub": R.utc(max(px), "%d.%m.%Y"), "zone": None, "note": ""},
             {"label": "Od szczytu (ATH)", "value": f"{(v / px[t_ath] - 1) * 100:+.1f}%",
              "sub": f"ATH {R.fmt_price(px[t_ath])} ({R.utc(t_ath, '%d.%m.%Y')}), {(t_end - t_ath) // DAY} dni temu",
              "zone": None, "note": ""},
             {"label": "Od halvingu", "value": f"{(t_end - h_now) // DAY} dni",
              "sub": f"halving {R.utc(h_now, '%d.%m.%Y')}", "zone": None, "note": ""}]
    if rp:
        items.append({"label": "Cena vs realized price", "value": f"{(v / rp - 1) * 100:+.1f}%",
                      "sub": f"realized price {R.fmt_price(rp)}", "zone": None, "note": ""})
    out.append({"type": "facts", "title": "Stan na zamknięcie miesiąca", "items": items})
    # porównanie z poprzednimi cyklami (te same dni po halvingu i po szczycie)
    tops, bottoms = C.cycle_extremes(px)
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
        rows.append([f"{R.utc(h_now, '%Y')}– (obecny)", f"{R.utc(t_top_now, '%m.%Y')} ({(t_top_now - h_now) // DAY} dni)",
                     f"{(v / cur_win[t_top_now] - 1) * 100:+.0f}%", f"{(v / cur_win[t_top_now] - 1) * 100:+.0f}%", "—"])
    if rows:
        out.append({"type": "table", "title": "Obecny cykl na tle poprzednich", "plain": True, "left": [0],
                    "cols": ["Cykl (halving)", "Szczyt (dni po halvingu)", f"Cena {n_h // DAY} dni po halvingu vs szczyt",
                             f"Cena {n_top // DAY if n_top else '—'} dni po szczycie vs szczyt", "Dno cyklu vs szczyt"],
                    "rows": rows,
                    "desc": "Gdzie była cena w poprzednich cyklach w tym samym momencie: tyle samo dni po halvingu i tyle "
                            "samo dni po szczycie cyklu co dziś. Cykl = okres między halvingami.",
                    "note": "Szczyt = najwyższe zamknięcie dnia w 2 latach po halvingu; dno = najniższe między szczytem a "
                            "następnym halvingiem. Liczone z dziennych zamknięć ceny BTC (od 2009)."})
    # wskaźniki cyklu na tle poprzednich szczytów i den
    ref = d.meta.get("ref_lines") or {}
    items = []
    for sid in ("mvrv_btc", "mvrvz_btc", "mayer_btc", "p200w_btc", "picycle_btc", "ssr"):
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
                    "note": "MVRV i realized price: Coin Metrics Community; Mayer, cena/200W, Pi Cycle — z ceny BTC; SSR — "
                            "TradingView. Opis każdego wskaźnika pod paskiem."})
    # cena (log) z realized price i średnią 200 tygodni
    since = _ts(datetime(2011, 1, 1))
    ts = sorted(px)
    vals = [px[t] for t in ts]
    keep = lambda t: t >= since and (_dt(t).weekday() == 6 or t == ts[-1])  # noqa: E731 — co tydzień (mniejszy plik)
    p = [[t, px[t]] for t in ts if keep(t)]
    sma = [[ts[i], sum(vals[i - 1399:i + 1]) / 1400] for i in range(1399, len(vals)) if keep(ts[i])]
    series = [{"name": "Cena BTC", "color": "#f7931a", "fmt": "price", "scale": "right", "data": p}]
    rpp = [x for x in d.pts("1d", "rprice_btc") if x[0] <= t_end and keep(x[0])]
    if rpp:
        series.append({"name": "Realized price", "color": "#ffb74d", "fmt": "price", "scale": "right", "data": rpp})
    if sma:
        series.append({"name": "Średnia 200 tygodni", "color": "#e05252", "fmt": "price", "scale": "right", "data": sma})
    out.append({"type": "chart", "title": "Cena BTC, realized price i średnia 200 tygodni — od 2011", "log": True,
                "series": series,
                "desc": "Skala logarytmiczna. Realized price = średnia cena, po której monety ostatnio się ruszały; "
                        "średnia 200 tygodni = 1400 dni."})
    return out


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
        mondays = list(range(start - 104 * WEEK, end + 1, WEEK))
        blocks += liq_block(d, "weekly", mondays, lambda a: R.utc(a, "%d.%m"), start, end, end - 104 * WEEK)
        blocks += ema_crosses(ema, start, end, float(L["ema_min_volume"]))
        blocks += macro_blocks(macro, start, end, end + WEEK, cfg, 0, "miniony tydzień")
        blocks += change_table(d, ema, [x for x in MACRO_SIDS if x != "m2"], t_end, start, end, hz,
                               "Rynki i płynność — zamknięcie tygodnia",
                               "Dolar, giełda w USA, strach (VIX), obligacje, złoto i płynność Fed. Dane dzienne z TradingView "
                               "(płynność Fed: odczyty tygodniowe; M2 — w raporcie miesięcznym).")
        blocks += [{"type": "section", "title": "Cykl BTC w tygodniu"}]
        blocks += change_table(d, ema, ["mvrv_btc", "mvrvz_btc", "mayer_btc", "p200w_btc", "picycle_btc", "ssr"], t_end,
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
        blocks += cycle_blocks(d, t_end)
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
        blocks += macro_blocks(macro, start, end, month_start(end + 32 * DAY), cfg, 1, "miniony miesiąc")
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
    """Zakres kalendarza makro dla raportu: (dni wstecz, dni naprzód)."""
    return (9, 9) if kind == "weekly" else (33, 37)
