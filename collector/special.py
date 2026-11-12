"""Raporty rzadkie (poprawka 36): roczny (kind "yearly") i po halvingu BTC (kind "halving").

Roczny  — „jaki był rok”: rok w liczbach, BTC rok po roku (rok w cyklu), miesiące roku, derywaty, alty, coiny roku,
          cykl i makro r/r. Budowany 1 stycznia po zamknięciu świecy rocznej.
Halving — „cykl się zamknął, co dalej”: halving w liczbach, zakończony cykl, co było po poprzednich halvingach, stan
          rynku vs poprzednie halvingi, okno szacunkowe szczytu, lista „co sprawdzić” (system + rynek). Dane do dnia
          halvingu (as-of) + weryfikacja poprzedniego halvingu (co się stało, czy okno z tamtego raportu trafiło).
          Budowany ręcznie (/raport_teraz halving) po dopisaniu daty do config.yaml cycle.halvings; bot przypomina
          przed cycle.next_halving_estimate. preview=True (podgląd wstecz) — dodatkowo „co stało się potem”.
Liczby liczy kod, bez interpretacji; szacunki z historii = „szacunek, nie prognoza”.
"""
import json
import os
import statistics
from datetime import datetime, timezone

import alerts
import cycle as C
import periodic as P
import report as R

DAY = 86400
BLOCKS_PER_HALVING = 210000


def halvings():
    """[(dzień UTC, blok)] — z cycle.HALVINGS (kod + config.yaml cycle.halvings)."""
    return [(h, BLOCKS_PER_HALVING * (i + 1)) for i, h in enumerate(C.HALVINGS)]
CYCLE_YEAR = {0: "rok halvingu", 1: "rok po halvingu", 2: "2 lata po halvingu", 3: "rok przed halvingiem"}


def ts(y, m=1, d=1):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


def fmt_pct(x, sign=True):
    return "—" if x is None else (f"{x:+.0f}%" if abs(x) >= 100 else f"{x:+.1f}%") if sign else f"{x:.0f}%"


def upto(pts, t):
    return [p for p in pts if p[0] <= t]


def max_dd(vals):
    """Największy spadek od szczytu (w %) w ciągu serii wartości."""
    peak, dd = None, 0.0
    for v in vals:
        peak = v if peak is None or v > peak else peak
        dd = min(dd, (v / peak - 1) * 100)
    return dd


# ══ ROCZNY ═══════════════════════════════════════════════════
def year_numbers(d, ema, y):
    a, b = ts(y), ts(y + 1)
    rows = []
    for sid in ("px_btc", "px_eth", "total", "total3es", "btc_d", "ethbtc", "stable_d", "stable_mcap"):
        pts = P.pts_of(d, sid, ema)
        name, f = P.label_fmt(d, sid)
        v, v0 = P.close(pts, b - DAY), P.close(pts, a - DAY)
        yr = [p for p in pts if a <= p[0] < b]
        if v is None or not yr:
            continue
        hi, lo = max(yr, key=lambda p: p[1]), min(yr, key=lambda p: p[1])
        if sid in P.WICKS:                                # ceny: knoty (najwyższa / najniższa cena w trakcie dnia)
            wl = [p for p in d.pts("1d", P.WICKS[sid][0]) if a <= p[0] < b]
            wh = [p for p in d.pts("1d", P.WICKS[sid][1]) if a <= p[0] < b]
            if wl and wh:
                lo, hi = min(wl + [lo], key=lambda p: p[1]), max(wh + [hi], key=lambda p: p[1])
        dd = f"{max_dd([v0] + [p[1] for p in yr] if v0 else [p[1] for p in yr]):.0f}%" \
            if f not in ("pct", "pct0") else "—"
        rows.append([name, P.fv(v, f), P.fv(v0, f), P.chg(v, v0, f),
                     f"{P.fv(hi[1], f)} ({R.utc(hi[0], '%d.%m')})", f"{P.fv(lo[1], f)} ({R.utc(lo[0], '%d.%m')})", dd])
    return [{"type": "section", "title": f"Rok {y} w liczbach"},
            {"type": "table", "title": "Zamknięcie roku i zmiana rok do roku", "left": [0],
             "cols": ["Wskaźnik", "Koniec roku", "Rok wcześniej", "Zmiana r/r", "Najwyżej w roku", "Najniżej w roku",
                      "Największy spadek od szczytu w roku"], "rows": rows,
             "desc": "Zamknięcie świecy rocznej (31.12, 24:00 UTC) i zmiana do zamknięcia poprzedniego roku.",
             "note": "Najwyżej / najniżej = zamknięcia dzienne; dla cen BTC i ETH — najwyższa i najniższa cena w trakcie dnia "
                     "(knoty, Binance perp przez Coinalyze). Największy spadek liczony z zamknięć dziennych. Dla wartości w % "
                     "zmiana w punktach procentowych."}]


def btc_years(d, y):
    px = d.pts("1d", "px_btc")
    rows, by_kind = [], {}
    for yy in range(2011, y + 1):
        v0, v1 = P.close(px, ts(yy) - DAY), P.close(px, ts(yy + 1) - DAY)
        if not v0 or not v1:
            continue
        r = (v1 / v0 - 1) * 100
        kind = CYCLE_YEAR[(yy - 2012) % 4]
        dd = max_dd([v0] + [v for t, v in px if ts(yy) <= t < ts(yy + 1)])
        rows.append([str(yy), kind, fmt_pct(r), f"{dd:.0f}%"])
        if yy != y:
            by_kind.setdefault(kind, []).append((yy, r))
    summ = [[k, f"{statistics.median([r for _, r in v]):+.0f}%", f"{sum(1 for _, r in v if r > 0)} z {len(v)}",
             ", ".join(f"{yy} {fmt_pct(r)}" for yy, r in v)] for k, v in
            sorted(by_kind.items(), key=lambda kv: list(CYCLE_YEAR.values()).index(kv[0]))]
    return [{"type": "section", "title": "BTC rok po roku"},
            {"type": "table", "title": "Zwrot BTC w kolejnych latach", "plain": True, "left": [0, 1],
             "cols": ["Rok", "Rok w cyklu", "Zwrot", "Największy spadek w roku"], "rows": list(reversed(rows)),
             "desc": "Zwrot BTC w każdym roku kalendarzowym od 2011 i miejsce roku w cyklu halvingów "
                     "(halvingi: 2012, 2016, 2020, 2024; następny szacunkowo 2028).",
             "note": "Zwrot = zamknięcie roku ÷ zamknięcie poprzedniego − 1. Cena: TradingView INDEX:BTCUSD (do 03.2020) i Coinalyze."},
            {"type": "table", "title": "Lata według miejsca w cyklu", "plain": True, "left": [0, 3],
             "cols": ["Rok w cyklu", "Mediana zwrotu", "Lata na plus", "Lata"], "rows": summ,
             "desc": f"Te same lata pogrupowane według miejsca w cyklu (bez {y}). Mała próba — 3–4 lata w grupie."}]


def month_bounds(y, m):
    a = ts(y, m)
    return a, P.month_start(a + 32 * DAY)


def month_chg(pts, y, m):
    a, b = month_bounds(y, m)
    v0, v1 = P.close(pts, a - DAY), P.close(pts, b - DAY)
    return (v1 / v0 - 1) * 100 if v0 and v1 else None


def month_sum(pts, y, m):
    a, b = month_bounds(y, m)
    vals = [v for t, v in pts if a <= t < b]
    return sum(vals) if vals else None


def month_mean(pts, y, m):
    a, b = month_bounds(y, m)
    vals = [v for t, v in pts if a <= t < b]
    return statistics.mean(vals) if len(vals) >= 20 else None


def months_of_year(d, ema, y):
    px = d.pts("1d", "px_btc")
    rows = []
    for m in range(1, 13):
        a, b = month_bounds(y, m)
        hist = [r for yy in range(2011, y) if (r := P.month_return(px, yy, m)) is not None]
        rows.append([P.MONTHS[m - 1], R.fmt_price(P.close(px, b - DAY)), fmt_pct(P.month_return(px, y, m)),
                     fmt_pct(P.month_return(px, y - 1, m)), f"{statistics.median(hist):+.1f}%" if hist else "—",
                     f"{sum(1 for r in hist if r > 0)} z {len(hist)}" if hist else "—"])
    out = [{"type": "section", "title": f"Miesiące {y}"},
           {"type": "table", "title": f"BTC miesiąc po miesiącu — {y} i {y - 1}", "left": [0],
            "cols": ["Miesiąc", "Zamknięcie", f"Zwrot {y}", f"Zwrot {y - 1}", f"Mediana 2011–{y - 1}", "Lat na plus"],
            "rows": rows,
            "desc": f"Jak wyglądał każdy miesiąc {y}: zamknięcie i zwrot BTC obok tego samego miesiąca rok wcześniej "
                    "i mediany z wcześniejszych lat."}]
    t3 = P.pts_of(d, "total3es", ema)
    bd = d.pts("1d", "btc_d")
    lg, sh = d.pts("1d", "liq_total_long"), d.pts("1d", "liq_total_short")
    fb = d.pts("1d", "fund_btc")
    rows2 = []
    for m in range(1, 13):
        def liq(yy):
            a_, b_ = month_sum(lg, yy, m), month_sum(sh, yy, m)
            return alerts.fmt_value(a_ + b_, "liq") if a_ is not None and b_ is not None else "—"

        def bdd(yy):
            a_, b_ = month_bounds(yy, m)
            v0, v1 = P.close(bd, a_ - DAY), P.close(bd, b_ - DAY)
            return P.chg(v1, v0, "pct") if v0 is not None and v1 is not None else "—"

        def fund(yy):
            v = month_mean(fb, yy, m)
            return f"{v:+.1f}%" if v is not None else "—"
        rows2.append([P.MONTHS[m - 1], fmt_pct(month_chg(t3, y, m)), fmt_pct(month_chg(t3, y - 1, m)), bdd(y), bdd(y - 1),
                      liq(y), liq(y - 1), fund(y), fund(y - 1)])
    out.append({"type": "table", "title": f"Rynek miesiąc po miesiącu — {y} i {y - 1}", "left": [0],
                "cols": ["Miesiąc", f"TOTAL3ES {y}", f"TOTAL3ES {y - 1}", f"BTC.D {y}", f"BTC.D {y - 1}",
                         f"Likwidacje {y}", f"Likwidacje {y - 1}", f"Funding BTC {y}", f"Funding BTC {y - 1}"],
                "rows": rows2,
                "desc": "Alty bez stablecoinów (zmiana w miesiącu), udział BTC (zmiana w pp), suma likwidacji i średni funding BTC "
                        "(% rocznie) — każdy miesiąc obok tego samego miesiąca rok wcześniej.",
                "note": "Likwidacje: Binance, Bybit, OKX (dolne oszacowanie), od 09.2022. Funding przed 22.09.2022 z wagami stałymi."})
    return out


def phase_compare(px, phs, t_end):
    """Bieżąca faza na tle tej samej fazy w poprzednich cyklach (od 2013): długość, zmiana, ten sam dzień fazy, szczyt fazy."""
    if not phs:
        return []
    cur = phs[-1]
    pxl = sorted((t, v) for t, v in px.items() if t <= t_end)
    n = (t_end - cur["from"]) // DAY
    v_start, v_now = px[cur["from"]], P.close(pxl, t_end)
    inside = [(t, v) for t, v in pxl if t >= cur["from"]]
    t_hi, v_hi = max(inside, key=lambda x: x[1])
    t_lo, v_lo = min(inside, key=lambda x: x[1])
    name = P.phase_name(cur)
    facts = [{"label": "Faza cyklu", "value": f"{name.capitalize()} · dzień {n}",
              "sub": f"od {R.utc(cur['from'], '%d.%m.%Y')} ({R.fmt_price(v_start)}); zmiana {fmt_pct((v_now / v_start - 1) * 100)}",
              "zone": None, "note": ""},
             {"label": "Najwyższe zamknięcie w fazie", "value": R.fmt_price(v_hi),
              "sub": f"{R.utc(t_hi, '%d.%m.%Y')} — {(t_end - t_hi) // DAY} dni temu; teraz {fmt_pct((v_now / v_hi - 1) * 100)}",
              "zone": None, "note": ""},
             {"label": "Najniższe zamknięcie w fazie", "value": R.fmt_price(v_lo),
              "sub": f"{R.utc(t_lo, '%d.%m.%Y')} — teraz {fmt_pct((v_now / v_lo - 1) * 100)}", "zone": None, "note": ""}]
    rows = []
    for p in phs[:-1]:
        if p["phase"] != cur["phase"] or p["to"] is None or p["from"] < ts(2013):
            continue
        seg = [(t, v) for t, v in pxl if p["from"] <= t <= p["to"]]
        if not seg:
            continue
        a = px[p["from"]]
        same = P.close(pxl, p["from"] + n * DAY) if p["from"] + n * DAY <= p["to"] else None
        hi = max(seg, key=lambda x: x[1])
        rows.append([f"{R.utc(p['from'], '%m.%Y')}–{R.utc(p['to'], '%m.%Y')}", f"{(p['to'] - p['from']) // DAY} dni",
                     fmt_pct((px[p['to']] / a - 1) * 100), fmt_pct((same / a - 1) * 100) if same else "(faza krótsza)",
                     f"{fmt_pct((hi[1] / a - 1) * 100)} po {(hi[0] - p['from']) // DAY} dniach"])
    rows.append([f"{R.utc(cur['from'], '%m.%Y')}– (obecna)", f"{n} dni (trwa)", fmt_pct((v_now / v_start - 1) * 100),
                 fmt_pct((v_now / v_start - 1) * 100), f"{fmt_pct((v_hi / v_start - 1) * 100)} po {(t_hi - cur['from']) // DAY} dniach"])
    return [{"type": "facts", "title": f"Faza cyklu na {R.utc(t_end, '%d.%m.%Y')}", "items": facts},
            {"type": "table", "title": f"Obecna {name} na tle poprzednich", "plain": True, "left": [0],
             "cols": ["Faza", "Długość", "Zmiana w całej fazie", f"Zmiana po {n} dniach", "Najwyżej w fazie"], "rows": rows,
             "desc": "Ta sama faza w poprzednich cyklach: ile trwała, o ile zmieniła się cena, gdzie była cena w tym samym dniu "
                     "fazy co dziś i kiedy był jej szczyt.",
             "note": "Fazy z dziennych zamknięć BTC: bessa = szczyt → dno; akumulacja = dno → zamknięcie nad poprzednim szczytem; "
                     "hossa = stamtąd → kolejny szczyt (szczyt liczy się dopiero po spadku o ≥ 50%, dlatego hossa może „trwać” "
                     "mimo spadku od szczytu — patrz „Najwyższe zamknięcie w fazie”)."}]


def derivatives_year(d, y):
    a, b = ts(y), ts(y + 1)
    out = [{"type": "section", "title": "Derywaty w roku"}]
    rows = []
    for coin in ("BTC", "ETH"):
        oi = d.pts("1d", f"oi_{coin.lower()}")
        yr = [p for p in oi if a <= p[0] < b]
        if not yr:
            continue
        v0, v1 = P.close(oi, a - DAY) or yr[0][1], P.close(oi, b - DAY)
        hi = max(yr, key=lambda p: p[1])
        fund = [v for t, v in d.pts("1d", f"fund_{coin.lower()}") if a <= t < b]
        rows.append([coin, alerts.fmt_value(v0, "oi"), alerts.fmt_value(v1, "oi"), R.fmt_chg(R.pct_change(v1, v0)),
                     f"{alerts.fmt_value(hi[1], 'oi')} ({R.utc(hi[0], '%d.%m')})",
                     f"{statistics.mean(fund):+.1f}%" if fund else "—"])
    if rows:
        out.append({"type": "table", "title": "Open interest i funding w roku", "left": [0],
                    "cols": ["Coin", "OI na początek", "OI na koniec", "Zmiana", "Maks. OI (dzień)", "Funding — śr. roku"],
                    "rows": rows, "desc": "OI w dolarach (rośnie także razem z ceną). Funding w % rocznie, neutralnie ok. 11%."})
    frows = []
    for yy in range(2020, y + 1):
        cells = [str(yy)]
        for coin in ("btc", "eth"):
            f = [v for t, v in d.pts("1d", f"fund_{coin}") if ts(yy) <= t < ts(yy + 1)]
            cells.append(f"{statistics.mean(f):+.1f}%" if len(f) > 200 else "—")
        frows.append(cells)
    out.append({"type": "table", "title": "Funding — średnia roku od 2020", "plain": True,
                "cols": ["Rok", "BTC", "ETH"], "rows": list(reversed(frows)),
                "desc": "Wysoki średni funding = rok, w którym longi płaciły dużo za dźwignię.",
                "note": "Przed 22.09.2022 średnia z wagami stałymi (udziały giełd w OI z pierwszych 30 dni danych OI)."})
    lg, sh = d.pts("1d", "liq_total_long"), dict(d.pts("1d", "liq_total_short"))
    lrows = []
    for yy in range(2023, y + 1):
        days = [(t, v, sh.get(t, 0.0)) for t, v in lg if ts(yy) <= t < ts(yy + 1)]
        if len(days) < 300:
            continue
        tot = sum(v + s for _, v, s in days)
        big = max(days, key=lambda x: x[1] + x[2])
        lrows.append([str(yy), alerts.fmt_value(tot, "liq"), f"{100 * sum(v for _, v, _ in days) / tot:.0f}%",
                      f"{R.utc(big[0], '%d.%m')}: {alerts.fmt_value(big[1] + big[2], 'liq')}"])
    if lrows:
        out.append({"type": "table", "title": "Likwidacje — suma roku", "plain": True,
                    "cols": ["Rok", "Suma", "Udział longów", "Największy dzień"], "rows": list(reversed(lrows)),
                    "note": "Binance, Bybit, OKX — dolne oszacowanie; pełne lata od 2023."})
    top = sorted([(t, v + sh.get(t, 0.0), v) for t, v in lg if a <= t < b], key=lambda x: -x[1])[:5]
    if top:
        out.append({"type": "table", "title": f"5 największych dni likwidacji w {y}", "plain": True,
                    "cols": ["Dzień", "Suma", "Udział longów"],
                    "rows": [[R.utc(t, "%d.%m.%Y"), alerts.fmt_value(s, "liq"), f"{100 * lv / s:.0f}%"] for t, s, lv in top]})
    return out


def alts_year(d, ema, y, hist_dir):
    a, b = ts(y), ts(y + 1)
    out = [{"type": "section", "title": "Alty i coiny w roku"}]
    rows = []
    for sid, extra in (("oi_others_vs_btc", None), ("alts_vs_btc", None), ("breadth", 90), ("fund_others", None)):
        pts = P.pts_of(d, sid, ema)
        name, f = P.label_fmt(d, sid)
        yr = [p[:2] for p in pts if a <= p[0] < b]
        if not yr:
            continue
        hi, lo = max(yr, key=lambda p: p[1]), min(yr, key=lambda p: p[1])
        rows.append([name, P.fv(P.close(pts, b - DAY), f), f"{P.fv(hi[1], f)} ({R.utc(hi[0], '%d.%m')})",
                     f"{P.fv(lo[1], f)} ({R.utc(lo[0], '%d.%m')})",
                     f"{sum(1 for _, v in yr if v >= extra)} dni ≥ {extra}%" if extra else ""])
    btc = _hist(hist_dir, "BTC")
    if btc:
        days = [(t, c, e) for t, c, e in btc if a <= t < b and e]
        if days:
            above = sum(1 for _, c, e in days if c > e)
            rows.append(["BTC nad EMA200", f"{above} z {len(days)} dni", "", "", ""])
    out.append({"type": "table", "title": "Lewar, kapitał i szerokość w roku", "left": [0],
                "cols": ["Wskaźnik", "Koniec roku", "Maks. (dzień)", "Min. (dzień)", ""], "rows": rows,
                "desc": "Gdzie w roku były wskaźniki altów. W altseasonie 12.2024 szerokość rynku przekraczała 90%."})
    rets = []
    for fn in sorted(os.listdir(hist_dir)) if hist_dir and os.path.isdir(hist_dir) else []:
        h = _hist(hist_dir, fn[:-5])
        c0 = P.close([[t, c] for t, c, _ in h], a - DAY) if h else None
        c1 = P.close([[t, c] for t, c, _ in h], b - DAY) if h else None
        if c0 and c1 and h[0][0] <= a - DAY:
            rets.append((fn[:-5], (c1 / c0 - 1) * 100))
    if rets:
        rets.sort(key=lambda x: -x[1])
        up = sum(1 for _, r in rets if r > 0)
        rows2 = [[s, fmt_pct(r)] for s, r in rets[:10]] + [["…", ""]] + [[s, fmt_pct(r)] for s, r in rets[-10:]]
        out.append({"type": "table", "title": f"Coiny roku — 10 najmocniejszych i 10 najsłabszych ({len(rets)} coinów)",
                    "cols": ["Coin", f"Zwrot {y}"], "rows": rows2,
                    "desc": f"Na plus w {y}: {up} z {len(rets)} coinów Binance */USDT notowanych przez cały rok.",
                    "note": "Tylko coiny notowane dziś (coiny wycofane w trakcie roku pominięte — wynik zawyżony). Bez filtra obrotu."})
    return out


def _hist(hist_dir, sym):
    try:
        with open(os.path.join(hist_dir, f"{sym}.json"), encoding="utf-8") as f:
            return [p[:3] for p in json.load(f).get("d") or [] if len(p) >= 3]     # [t, close, ema] (+ knoty od poprawki 55)
    except (OSError, ValueError):
        return []


def cycle_macro_year(d, ema, y, cfg):
    a, b = ts(y), ts(y + 1)
    out = []
    px = {t: v for t, v in d.pts("1d", "px_btc") if t < b}
    phs = C.phases(px, C.ccfg(cfg).get("bottoms") or ())
    out += phase_compare(px, phs, b - DAY)
    out += P.change_table(d, ema, list(P.REPORT_CYCLE_SIDS), b - DAY, a, b, [("Rok wcześniej", a - DAY)],
                          "Wskaźniki cyklu — koniec roku i rok wcześniej", "Skrót; szczegóły w raporcie miesięcznym.", rng=False)
    out = [{"type": "section", "title": "Cykl BTC i makro w roku"}] + out
    out += P.change_table(d, ema, P.MACRO_SIDS, b - DAY, a, b, [("Rok wcześniej", a - DAY)],
                          "Rynki i płynność — zmiana r/r", "Dolar, giełda w USA, VIX, obligacje, złoto, płynność Fed i M2.")
    return out


def build_yearly(d, ema, y, cfg, hist_dir, now, head_blocks=()):
    blocks = list(head_blocks)
    blocks += year_numbers(d, ema, y)
    blocks += btc_years(d, y)
    blocks += months_of_year(d, ema, y)
    blocks += derivatives_year(d, y)
    blocks += alts_year(d, ema, y, hist_dir)
    blocks += cycle_macro_year(d, ema, y, cfg)
    px = d.pts("1d", "px_btc")
    v0, v1 = P.close(px, ts(y) - DAY), P.close(px, ts(y + 1) - DAY)
    return {"id": R.utc(now, "%Y%m%d-%H%M") + "-yearly", "kind": "yearly", "layout": 2, "title": f"Raport roczny — {y}",
            "created": int(now), "summary": f"Cena BTC {R.fmt_price(v1)} ({fmt_pct((v1 / v0 - 1) * 100)} r/r)",
            "period": {"start": ts(y), "end": ts(y + 1)}, "sources": {"data_updated": d.updated}, "blocks": blocks}


# ══ HALVING ══════════════════════════════════════════════════
def latest_halving_idx(now):
    days = [C.day_of(h) for h, _ in halvings()]
    past = [i for i, t in enumerate(days) if t <= now]
    return past[-1] if past else None


def build_halving(d, ema, cfg, now, idx=None, preview=False, head_blocks=()):
    """idx = numer halvingu na liście (0 = 2012; domyślnie ostatni do `now`). Dane do dnia halvingu (as-of).
    preview → dodatkowo „co stało się potem” (tylko w podglądzie wstecz)."""
    if idx is None:
        idx = latest_halving_idx(now)
    iso, block = halvings()[idx]
    t_h = C.day_of(iso)
    n = idx + 1
    reward_before, reward_after = 50 / 2 ** (n - 1), 50 / 2 ** n
    px_all = {t: v for t, v in d.pts("1d", "px_btc")}
    px = {t: v for t, v in px_all.items() if t <= t_h}
    pxl = sorted(px.items())
    v = px[max(px)]
    t_ath = max(px, key=px.get)
    prev = C.day_of(halvings()[idx - 1][0]) if idx else None
    blocks = list(head_blocks)
    if preview:
        blocks.append({"type": "text", "title": "Podgląd",
                       "text": f"Zbudowany wstecz z danych do {R.utc(t_h, '%d.%m.%Y')} (tak, jakby powstał w dniu halvingu). "
                               "Blok „Co stało się potem” na końcu jest tylko w podglądzie."})
    items = [{"label": "Halving", "value": f"nr {n} · blok {block:,}".replace(",", " "), "sub": R.utc(t_h, "%d.%m.%Y"),
              "zone": None, "note": ""},
             {"label": "Nagroda za blok", "value": f"{reward_before:g} → {reward_after:g} BTC",
              "sub": f"emisja ok. {reward_before * 144:g} → {reward_after * 144:g} BTC dziennie", "zone": None, "note": ""},
             {"label": "Cena BTC", "value": R.fmt_price(v), "sub": f"{(v / px[t_ath] - 1) * 100:+.0f}% od ATH "
              f"({R.fmt_price(px[t_ath])}, {R.utc(t_ath, '%d.%m.%Y')})", "zone": None, "note": ""}]
    if prev:
        items.append({"label": "Od poprzedniego halvingu", "value": f"{(t_h - prev) // DAY} dni",
                      "sub": f"cena {fmt_pct((v / P.close(pxl, prev) - 1) * 100)}", "zone": None, "note": ""})
    blocks += [{"type": "section", "title": "Halving w liczbach"}, {"type": "facts", "title": "", "items": items}]
    blocks += ended_cycles(px, pxl, idx, t_h, cfg)
    blocks += after_halvings(px_all, idx, t_h)
    blocks += state_vs_previous(d, idx, t_h)
    blocks += peak_window(px, idx, t_h)
    blocks += previous_check(px, idx, t_h)
    blocks += checklist(px, idx, t_h, cfg)
    if preview:
        blocks += verification(px_all, idx, t_h)
    return {"id": R.utc(now, "%Y%m%d-%H%M") + "-halving", "kind": "halving", "layout": 2,
            "title": f"Raport po halvingu — {R.utc(t_h, '%d.%m.%Y')}", "created": int(now),
            "summary": f"Halving nr {n} (blok {block}) · nagroda {reward_before:g} → {reward_after:g} BTC · cena BTC {R.fmt_price(v)}",
            "period": {"start": t_h, "end": t_h + DAY}, "sources": {"data_updated": d.updated}, "blocks": blocks}


def ended_cycles(px, pxl, idx, t_h, cfg):
    tops, bottoms = C.cycle_extremes(px, ())
    rows = []
    hs = [C.day_of(h) for h, _ in halvings()[:idx + 1]]
    for a, b in zip(hs, hs[1:]):
        pa, pb = P.close(pxl, a), P.close(pxl, b)
        top = next(((t, x) for t, x in tops if a <= t < b), None)
        bot = next(((t, x) for t, x in bottoms if top and top[0] < t <= b), None)
        rows.append([f"{R.utc(a, '%m.%Y')} → {R.utc(b, '%m.%Y')}", R.fmt_price(pa), R.fmt_price(pb),
                     fmt_pct((pb / pa - 1) * 100) if pa and pb else "—",
                     f"{R.utc(top[0], '%m.%Y')} · {(top[0] - a) // DAY} dni · {fmt_pct((top[1] / pa - 1) * 100)}" if top and pa else "—",
                     f"{R.utc(bot[0], '%m.%Y')} · {fmt_pct((bot[1] / top[1] - 1) * 100)}" if bot and top else "—"])
    out = [{"type": "section", "title": "Cykl, który się zakończył"},
           {"type": "table", "title": "Cykle od halvingu do halvingu", "plain": True, "left": [0],
            "cols": ["Cykl", "Cena przy halvingu", "Cena przy następnym", "Zmiana", "Szczyt (dni od halvingu, wzrost)",
                     "Dno (spadek od szczytu)"], "rows": list(reversed(rows)),
            "desc": "Ostatni wiersz u góry = cykl, który właśnie się zakończył. Po halvingu reguła potwierdza dno tego cyklu.",
            "note": "Szczyt = najwyższe zamknięcie w 2 latach po halvingu; dno = najniższe między szczytem a następnym halvingiem."}]
    phs = C.phases(px, ())
    tbl = P.phase_table(px, phs, t_h)
    if tbl:
        tbl["desc"] = ("Ile trwała każda faza i o ile zmieniła się w niej cena BTC. Bessa = szczyt → dno; akumulacja = dno → "
                       "pierwsze zamknięcie powyżej poprzedniego szczytu; hossa = stamtąd → kolejny szczyt.")
        out.append(tbl)
    return out


AFTER = (90, 180, 365, 525)


def after_halvings(px_all, idx, t_h):
    pxl = sorted(px_all.items())
    rows, cols_vals = [], {k: [] for k in AFTER}
    tops, _ = C.cycle_extremes({t: v for t, v in px_all.items() if t <= t_h}, ())
    for iso, _ in halvings()[:idx]:
        h = C.day_of(iso)
        p0 = P.close(pxl, h)
        cells = [R.utc(h, "%m.%Y"), R.fmt_price(p0)]
        for k in AFTER:
            pk = P.close(pxl, h + k * DAY)
            r = (pk / p0 - 1) * 100 if pk and p0 else None
            cols_vals[k].append(r)
            cells.append(fmt_pct(r))
        top = next(((t, x) for t, x in tops if h <= t < h + C.TOP_WINDOW_DAYS * DAY), None)
        dd = max_dd([v for t, v in pxl if h <= t <= h + 365 * DAY])
        cells += [f"{(top[0] - h) // DAY} dni, {fmt_pct((top[1] / p0 - 1) * 100)}" if top else "—", f"{dd:.0f}%"]
        rows.append(cells)
    med = ["Mediana", ""] + [fmt_pct(statistics.median([x for x in cols_vals[k] if x is not None]))
                             if any(x is not None for x in cols_vals[k]) else "—" for k in AFTER] + ["", ""]
    return [{"type": "section", "title": "Co było po poprzednich halvingach"},
            {"type": "table", "title": "Cena BTC po poprzednich halvingach", "left": [0],
             "cols": ["Halving", "Cena"] + [f"+{k} dni" for k in AFTER] + ["Szczyt cyklu (dni, wzrost)",
                                                                           "Największy spadek w roku po"],
             "rows": rows + [med],
             "desc": "Zmiana ceny od dnia halvingu. Wzrost do szczytu malał z cyklu na cykl.",
             "note": "Trzy poprzednie cykle — mała próba. Szacunek z historii, nie prognoza."}]


STATE = [("mvrv_btc", "MVRV"), ("mvrvz_btc", "MVRV-Z"), ("mayer_btc", "Mayer Multiple"), ("p200w_btc", "Cena / 200W"),
         ("ssr", "SSR"), ("fund_btc", "Funding BTC (śr. 30 dni)"), ("oi_others_vs_btc", "OI OTHERS / OI BTC"),
         ("btc_d", "BTC.D")]


def state_vs_previous(d, idx, t_h):
    hs = [C.day_of(h) for h, _ in halvings()[:idx + 1]][::-1]
    pxl = d.pts("1d", "px_btc")
    rows = []
    ath_row = ["Cena vs ATH"]
    for h in hs:
        upto_h = [v for t, v in pxl if t <= h]
        p = P.close(pxl, h)
        ath_row.append(fmt_pct((p / max(upto_h) - 1) * 100) if upto_h and p else "—")
    rows.append(ath_row)
    for sid, name in STATE:
        pts = d.pts("1d", sid)
        cells = [name]
        for h in hs:
            if sid == "fund_btc":
                vals = [v for t, v in pts if h - 30 * DAY < t <= h]
                cells.append(f"{statistics.mean(vals):+.1f}%" if vals else "—")
            elif sid == "ssr" and h < ts(2020):
                cells.append("—")
            else:
                x = P.close(pts, h)
                f = P.fmt_of(d, sid) or "x"
                cells.append(P.fv(x, f) if x is not None else "—")
        rows.append(cells)
    return [{"type": "section", "title": "Stan rynku przy halvingu"},
            {"type": "table", "title": "Ten halving i poprzednie — te same wskaźniki", "left": [0], "plain": True,
             "cols": ["Wskaźnik"] + [R.utc(h, "%m.%Y") + (" (ten)" if i == 0 else "") for i, h in enumerate(hs)],
             "rows": rows,
             "desc": "Gdzie był rynek w dniu tego halvingu i w dniach poprzednich. Brak danych = wskaźnika wtedy jeszcze nie było "
                     "(OI od 2022, funding od 2020, SSR od 2020).",
             "note": "Wartości z zamknięcia dnia halvingu."}]


def peak_window(px, idx, t_h):
    tops, _ = C.cycle_extremes(px, ())
    h2t = []
    for iso, _ in halvings()[:idx]:
        h = C.day_of(iso)
        top = next((t for t, _ in tops if h <= t < h + C.TOP_WINDOW_DAYS * DAY), None)
        if top:
            h2t.append(((top - h) // DAY, R.utc(h, "%Y")))
    if not h2t:
        return []
    rows = [[f"Halving {y}", f"{n} dni", R.utc(t_h + n * DAY, "%d.%m.%Y")] for n, y in h2t]
    last2 = [n for n, _ in h2t[-2:]]
    rows.append(["Dwa ostatnie cykle (zakres)", f"{min(last2)}–{max(last2)} dni",
                 f"{R.utc(t_h + min(last2) * DAY, '%d.%m.%Y')} – {R.utc(t_h + max(last2) * DAY, '%d.%m.%Y')}"])
    return [{"type": "section", "title": "Okno szacunkowe szczytu"},
            {"type": "table", "title": "Gdyby powtórzył się czas od halvingu do szczytu", "plain": True, "left": [0],
             "cols": ["Na podstawie", "Halving → szczyt", "Szczyt wypadłby"], "rows": rows,
             "desc": "Szacunek, nie prognoza: data szczytu, gdyby powtórzyła się liczba dni od halvingu do szczytu z poprzednich cykli.",
             "note": "Cykl 2012–2013 był krótszy (rynek mały i młody). Szczyt = najwyższe zamknięcie dnia."}]


def halving_tops(px, idx):
    """[(rok halvingu, dni do szczytu, wzrost od halvingu %)] dla poprzednich halvingów (z danych do dnia tego halvingu)."""
    tops, _ = C.cycle_extremes(px, ())
    pxl = sorted(px.items())
    out = []
    for iso, _ in halvings()[:idx]:
        h = C.day_of(iso)
        top = next(((t, x) for t, x in tops if h <= t < h + C.TOP_WINDOW_DAYS * DAY), None)
        p0 = P.close(pxl, h)
        if top and p0:
            out.append((R.utc(h, "%Y"), (top[0] - h) // DAY, (top[1] / p0 - 1) * 100))
    return out


def previous_check(px, idx, t_h):
    """Co stało się po poprzednim halvingu (dane do dnia tego halvingu) i czy okno z tamtego raportu trafiło w szczyt."""
    if idx < 1:
        return []
    pxl = sorted(px.items())
    hp = C.day_of(halvings()[idx - 1][0])
    p0 = P.close(pxl, hp)
    rows = []
    for k in AFTER:
        pk = P.close(pxl, hp + k * DAY)
        rows.append([f"+{k} dni ({R.utc(hp + k * DAY, '%d.%m.%Y')})", fmt_pct((pk / p0 - 1) * 100) if pk and p0 else "—"])
    tops, bottoms = C.cycle_extremes(px, ())
    top = next(((t, x) for t, x in tops if hp <= t < hp + C.TOP_WINDOW_DAYS * DAY), None)
    if top:
        rows.append(["Szczyt cyklu", f"{R.fmt_price(top[1])} — {R.utc(top[0], '%d.%m.%Y')}, {(top[0] - hp) // DAY} dni po halvingu, "
                     f"{fmt_pct((top[1] / p0 - 1) * 100)}"])
        bot = next(((t, x) for t, x in bottoms if t > top[0]), None)
        if bot:
            rows.append(["Dno cyklu", f"{R.fmt_price(bot[1])} — {R.utc(bot[0], '%d.%m.%Y')}, {fmt_pct((bot[1] / top[1] - 1) * 100)} od szczytu, "
                         f"{(bot[0] - top[0]) // DAY} dni po nim"])
        ht = halving_tops({t: v for t, v in px.items() if t <= hp}, idx - 1)[-2:]
        if ht:
            lo, hi = min(n for _, n, _ in ht), max(n for _, n, _ in ht)
            a, b = hp + lo * DAY, hp + hi * DAY
            where = ("w oknie" if a <= top[0] <= b else
                     f"{(a - top[0]) // DAY} dni przed oknem" if top[0] < a else f"{(top[0] - b) // DAY} dni po oknie")
            rows.append(["Okno szczytu z tamtego raportu",
                         f"{R.utc(a, '%d.%m.%Y')} – {R.utc(b, '%d.%m.%Y')} ({lo}–{hi} dni, dwa wcześniejsze cykle) → szczyt {where}"])
    return [{"type": "section", "title": f"Poprzedni halving ({R.utc(hp, '%m.%Y')}) — co się wydarzyło"},
            {"type": "table", "title": "Cena BTC po poprzednim halvingu i trafność okna szczytu", "plain": True, "left": [0, 1],
             "cols": ["Co", "Wynik"], "rows": rows,
             "desc": "Sprawdzenie poprzedniego raportu: jak zachowała się cena po tamtym halvingu i czy szczyt wypadł w oknie "
                     "szacunkowym, które wtedy pokazaliśmy (te same reguły co w oknie wyżej)."}]


def checklist(px, idx, t_h, cfg):
    nxt_block = halvings()[idx][1] + 210000
    nxt_est = R.utc(t_h + 1458 * DAY, "%m.%Y")
    tops, bottoms = C.cycle_extremes(px, ())
    last_bot = bottoms[-1] if bottoms else None
    manual = [m for m in C.ccfg(cfg).get("bottoms") or () if C.day_of(str(m)) <= t_h]   # tylko dna sprzed halvingu
    sys_rows = [
        ["Data tego halvingu", f"Porównaj dzień w config.yaml → cycle.halvings ({R.utc(t_h, '%Y-%m-%d')}) z eksploratorem bloków "
                               f"(blok {halvings()[idx][1]:,}, dzień UTC)".replace(",", " ") + " — od tej daty liczą się cykle, "
                               "fazy, okna szacunkowe i znaczniki w OI & TOTAL."],
        ["Następny halving", f"Ustaw cycle.next_halving_estimate w config.yaml: blok {nxt_block:,}".replace(",", " ")
         + f", ok. {nxt_est} (4 lata × ~1460 dni; sprawdź tempo bloków). Bot przypomni o nim przed tą datą."],
        ["Dno zakończonego cyklu", (f"Reguła wyznacza teraz dno {R.utc(last_bot[0], '%d.%m.%Y')} ({R.fmt_price(last_bot[1])}). "
                                    if last_bot else "") + (f"W config.yaml jest dno uznane ręcznie ({', '.join(manual)}) — jeśli "
                                    "to ten sam dzień, usuń wpis; jeśli inny, zdecyduj, które obowiązuje." if manual else
                                    "Sprawdź, czy zgadza się z dnem, które uznawaliśmy wcześniej.")],
        ["Źródła danych", "Czy działają i mają pełną historię: Coinalyze (OI, funding, likwidacje), TradingView (TOTAL, ceny, "
                          "makro), Coin Metrics (MVRV), Binance (EMA200). Stan: meta.json → health, zakładka OI & TOTAL."],
        ["Raport miesięczny i OI & TOTAL", "Czy fazy cyklu, tabela cykli, okno szacunkowe i linie poziomów cyklu uwzględniają "
                                           "zakończony cykl (ref_tops / ref_bottoms w config.yaml)."],
        ["Porównanie z poprzednim raportem", "Otwórz raport po poprzednim halvingu (zakładka Raporty) i sprawdź, co się zmieniło "
                                             "w aplikacji i w danych od tamtej pory."],
    ]
    ht = halving_tops(px, idx)
    days = [n for _, n, _ in ht]
    mkt_rows = [
        ["Czas do szczytu", (f"W poprzednich cyklach szczyt wypadał {min(days)}–{max(days)} dni po halvingu ("
                             + ", ".join(f"{y}: {n}" for y, n, _ in ht) + ") — okno wyżej.") if ht else "—"],
        ["Malejące wzrosty", ("Wzrost od halvingu do szczytu: " + ", ".join(f"{y} {fmt_pct(g)}" for y, _, g in ht)
                             + " — sprawdzaj, czy wzorzec się utrzymuje.") if ht else "—"],
        ["Wskaźniki przy szczytach", "MVRV, Mayer, cena/200W i Alty/BTC przy każdym szczycie były niżej niż w poprzednim — "
                                     "porównuj z poprzednimi cyklami, nie ze stałymi progami."],
        ["ATH przed halvingiem", "Czy cena przebiła poprzedni ATH przed halvingiem (wiersz „Cena vs ATH” w tabeli stanu rynku)."],
        ["Pierwsze miesiące", "Zmiany po +90 i +180 dniach w poprzednich cyklach — tabela „Cena BTC po poprzednich halvingach”."],
    ]
    return [{"type": "section", "title": "Co sprawdzić i na co zwrócić uwagę"},
            {"type": "table", "title": "System — do zrobienia po halvingu", "plain": True, "left": [0, 1],
             "cols": ["Co", "Jak"], "rows": sys_rows,
             "desc": "Raport powstaje raz na ~4 lata — do tego czasu aplikacja i źródła danych mogą się zmienić. Ta lista przypomina, "
                     "co trzeba sprawdzić i zaktualizować, żeby kolejny cykl liczył się poprawnie."},
            {"type": "table", "title": "Rynek — na co patrzeć w kolejnych miesiącach (fakty z poprzednich cykli)", "plain": True,
             "left": [0, 1], "cols": ["Temat", "Co mówi historia"], "rows": mkt_rows,
             "desc": "Bez prognoz — tylko to, co powtarzało się po poprzednich halvingach, do obserwacji."}]


def verification(px_all, idx, t_h):
    pxl = sorted(px_all.items())
    p0 = P.close(pxl, t_h)
    rows = []
    for k in AFTER:
        pk = P.close(pxl, t_h + k * DAY)
        rows.append([f"+{k} dni ({R.utc(t_h + k * DAY, '%d.%m.%Y')})", fmt_pct((pk / p0 - 1) * 100) if pk else "jeszcze nie"])
    after = [(t, v) for t, v in pxl if t_h <= t < t_h + C.TOP_WINDOW_DAYS * DAY]
    if after:
        t, v = max(after, key=lambda x: x[1])
        rows.append(["Najwyższe zamknięcie w 2 lata po", f"{R.fmt_price(v)} — {R.utc(t, '%d.%m.%Y')}, {(t - t_h) // DAY} dni po halvingu, "
                     f"{fmt_pct((v / p0 - 1) * 100)}"])
    return [{"type": "section", "title": "Co stało się potem (tylko w podglądzie)"},
            {"type": "table", "title": "Co stało się po tym halvingu", "plain": True, "left": [0, 1],
             "cols": ["Kiedy", "Cena BTC vs dzień halvingu"], "rows": rows,
             "desc": "Tego w prawdziwym raporcie nie będzie (powstaje w dniu halvingu). Tu — żeby ocenić, czy tabele wyżej były pomocne."}]
