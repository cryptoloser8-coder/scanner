"""CVD — kupno vs sprzedaż na spot i perp (poprawka 44). Bot GitHuba (main.py) + bloki raportów.

Źródło: Coinalyze /ohlcv-history — v (wolumen) i bv (wolumen kupujących „po rynku”, czyli agresorów),
sprawdzone sondą 05.11.2026 (probe.py, źródło `cvd`): dla Binance v i bv = volume i taker_buy_volume
z archiwum data.binance.vision (stosunek 1,000). Kontrakty odwrotne (oi_lq_vol_denominated_in = QUOTE_ASSET,
np. BTCUSD_PERP) mają wolumen już w $ (kontrakty × wartość kontraktu), pozostałe — w coinach (× cena świecy).

Serie (cvd_1h.json / cvd_1d.json, osobne pliki):
  cvd_<coin>_<spot|perp>       delta = kupno − sprzedaż w $ na świecę (CVD = suma narastająca — liczy strona)
  cvd_<coin>_<spot|perp>_vol   wolumen w $ na świecę
oraz ceny coinów spoza BTC/ETH: px_<coin> (zamknięcie największego perpa USDT; pliki liq_*, jak px_btc).

Rynki: pary do kwotowań z config `cvd.quotes` na giełdach spot (`cvd.spot_exchanges`) i perp (coinalyze.exchanges),
z danymi kupna/sprzedaży; do sumy wchodzą te z ≥ min_share wolumenu coina (osobno spot i perp) z ostatnich share_days
dni. Wybór raz na dobę UTC, razem z pobraniem świec dziennych wszystkich kandydatów (~150 zapytań). Co skan: świece 1h
wybranych rynków (~90 zapytań). Pierwszy raz: cała historia dzienna od `history_start`.
"""
import logging
from datetime import datetime, timezone

import series as S

log = logging.getLogger("cvd")
HOUR, DAY = S.HOUR, S.DAY
CVD_VERSION = 1              # zmiana → ponowne pobranie całej historii
INTRADAY_KEEP_HOURS = 1490
OVERLAP_HOURS = 3
DAILY_REFRESH_DAYS = 40      # codzienne pobranie świec dziennych: tyle dni wstecz (wybór rynków + korekty)
KINDS = ("spot", "perp")
FIELDS = ("v", "bv", "c")
DEFAULTS = {"enabled": True, "coins": ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"],
            "spot_exchanges": ["Binance", "Coinbase", "Bybit", "Kraken", "Bitstamp", "Bitfinex"],
            "perp_exchanges": None, "quotes": ["USDT", "USD", "USDC", "FDUSD"],
            "min_share": 0.01, "share_days": 30, "history_start": "2019-05-01", "flat_pct": 1.0}
NAMES = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "BNB": "BNB", "XRP": "XRP", "DOGE": "DOGE"}


def settings(cfg):
    c = dict(DEFAULTS)
    c.update({k: v for k, v in ((cfg or {}).get("cvd") or {}).items() if v is not None})
    if not c.get("perp_exchanges"):
        c["perp_exchanges"] = ((cfg or {}).get("coinalyze") or {}).get("exchanges") or ["Binance", "Bybit", "OKX"]
    c["coins"] = [x.upper() for x in c["coins"]]
    c["quotes"] = [x.upper() for x in c["quotes"]]
    return c


def enabled(cfg):
    return bool(((cfg or {}).get("cvd") or {}).get("enabled"))


def sid(coin, kind, vol=False):
    return f"cvd_{coin.lower()}_{kind}" + ("_vol" if vol else "")


def px_sid(coin):
    return f"px_{coin.lower()}"


def floor(t, step):
    return int(t) - int(t) % step


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _day_ts(s):
    return int(datetime.strptime(str(s), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


# ── rynki ────────────────────────────────────────────────────
def _codes(exchanges, wanted):
    from coinalyze import _norm_name
    wn = [_norm_name(w) for w in wanted]
    out = {}
    for ex in exchanges or []:
        n = _norm_name(ex.get("name"))
        if any(n and w and (n.startswith(w) or w.startswith(n)) for w in wn):
            out[ex.get("code")] = ex.get("name")
    return out


def candidates(exchanges, futures, spots, c):
    """→ {symbol: {"coin", "kind", "ex", "quote", "unit": base|quote}} — rynki z danymi kupna/sprzedaży."""
    from coinalyze import norm_base
    perp_ex, spot_ex = _codes(exchanges, c["perp_exchanges"]), _codes(exchanges, c["spot_exchanges"])
    coins, quotes = set(c["coins"]), set(c["quotes"])
    out = {}
    for m in futures or []:
        base, quote = norm_base(m.get("base_asset")), str(m.get("quote_asset") or "").upper()
        if (not m.get("is_perpetual") or m.get("exchange") not in perp_ex or base not in coins or quote not in quotes
                or m.get("has_buy_sell_data") is False or m.get("has_ohlcv_data") is False):
            continue
        unit = "quote" if "QUOTE" in str(m.get("oi_lq_vol_denominated_in") or "").upper() else "base"
        out[m["symbol"]] = {"coin": base, "kind": "perp", "ex": perp_ex[m["exchange"]], "quote": quote, "unit": unit}
    for m in spots or []:
        base, quote = norm_base(m.get("base_asset")), str(m.get("quote_asset") or "").upper()
        if m.get("exchange") not in spot_ex or base not in coins or quote not in quotes or m.get("has_buy_sell_data") is False:
            continue
        out[m["symbol"]] = {"coin": base, "kind": "spot", "ex": spot_ex[m["exchange"]], "quote": quote, "unit": "base"}
    return out


def usd(point, unit):
    """(v, bv, c) → (wolumen $, delta $) albo None."""
    try:
        v, bv, c = (float(x) for x in point)
    except (TypeError, ValueError):
        return None
    if v < 0 or bv < 0:
        return None
    d = 2 * bv - v
    if unit == "quote":
        return v, d
    return v * c, d * c


def select(daily, cands, now, share, days):
    """Rynki z ≥ share wolumenu coina (osobno spot / perp) z ostatnich `days` pełnych dni → (set, {coin:kind: pokrycie})."""
    today = floor(now, DAY)
    vol = {}
    for sym, m in cands.items():
        v = 0.0
        for t, p in (daily.get(sym) or {}).items():
            if today - days * DAY <= t < today:
                u = usd(p, m["unit"])
                if u:
                    v += u[0]
        vol[sym] = v
    keep, cover = set(), {}
    groups = {}
    for sym, m in cands.items():
        groups.setdefault((m["coin"], m["kind"]), []).append(sym)
    for (coin, kind), syms in groups.items():
        tot = sum(vol[s] for s in syms)
        if tot <= 0:
            continue
        sel = [s for s in syms if vol[s] >= share * tot]
        keep.update(sel)
        cover[f"{coin}:{kind}"] = round(sum(vol[s] for s in sel) / tot, 4)
    return keep, cover


def price_symbols(cands, selected, daily, now, days=30):
    """Coin (bez BTC/ETH) → największy wybrany perp USDT (preferencja Binance) — źródło ceny px_<coin>."""
    today = floor(now, DAY)
    best = {}
    for sym in selected:
        m = cands[sym]
        if m["kind"] != "perp" or m["quote"] != "USDT" or m["coin"] in ("BTC", "ETH"):
            continue
        v = sum((usd(p, m["unit"]) or (0, 0))[0] for t, p in (daily.get(sym) or {}).items() if t >= today - days * DAY)
        score = (m["ex"].lower().startswith("binance"), v)
        if m["coin"] not in best or score > best[m["coin"]][0]:
            best[m["coin"]] = (score, sym)
    return {coin: sym for coin, (_, sym) in best.items()}


def aggregate(hist, cands, selected, step, t_from=None, t_to=None):
    """{sym: {t: (v, bv, c)}} → {sid: {t: $}} (delta i wolumen na coin i rodzaj; tylko świece z danymi)."""
    out = {}
    for sym in selected:
        m = cands.get(sym)
        if not m:
            continue
        ds, vs = out.setdefault(sid(m["coin"], m["kind"]), {}), out.setdefault(sid(m["coin"], m["kind"], True), {})
        for t, p in (hist.get(sym) or {}).items():
            t = t - t % step
            if (t_from is not None and t < t_from) or (t_to is not None and t >= t_to):
                continue
            u = usd(p, m["unit"])
            if not u:
                continue
            vs[t] = vs.get(t, 0.0) + u[0]
            ds[t] = ds.get(t, 0.0) + u[1]
    return out


def _history(client, syms, interval, frm, to):
    return client.history("/ohlcv-history", syms, interval, frm, to, FIELDS) if syms else {}


def _daily_full(client, syms, now):
    """Cała historia dzienna (odpowiedzi obcięte do ~1500 dni są dopytywane wstecz)."""
    from probe import history_all
    return history_all(client, "/ohlcv-history", syms, FIELDS, False, now) if syms else {}


def spot_markets(client):
    f = getattr(client, "spot_markets", None)
    return f() if f else client._get("/spot-markets")


# ── zbieranie (main.py, co skan) ─────────────────────────────
def collect(client, store, cfg, now, backfill=False):
    c = settings(cfg)
    st = store.state.setdefault("cvd", {})
    now = int(now)
    now_h, today = floor(now, HOUR), floor(now, DAY)
    calls0, failed0 = client.calls_made, getattr(client, "failed_batches", 0)
    full = backfill or st.get("version") != CVD_VERSION or not store.series["1d"].get(sid("BTC", "spot"))
    cfg_key = [c["coins"], c["spot_exchanges"], c["perp_exchanges"], c["quotes"]]

    # lista rynków — raz na dobę (razem ze świecami dziennymi)
    need_daily = full or st.get("daily_day") != today or st.get("cfg") != cfg_key or not st.get("cands")
    if need_daily:
        st["cands"] = candidates(client.exchanges(), client.future_markets(), spot_markets(client), c)
        st["cfg"] = cfg_key
    cands = st["cands"]
    if not cands:
        raise RuntimeError("brak rynków z danymi kupna/sprzedaży")
    all_syms = sorted(cands)

    # świece dzienne wszystkich kandydatów → wybór rynków, serie dzienne (pełne dni)
    if need_daily:
        f0 = getattr(client, "failed_batches", 0)
        if full:
            log.info("CVD 1d: %d rynków — pełna historia od %s", len(all_syms), c["history_start"])
            daily = _daily_full(client, all_syms, now)
        else:
            daily = _history(client, all_syms, "daily", today - DAILY_REFRESH_DAYS * DAY, now)
        ok = getattr(client, "failed_batches", 0) == f0
        sel, cover = select(daily, cands, now, float(c["min_share"]), int(c["share_days"]))
        if sel and (ok or not st.get("selected")):
            st["selected"], st["cover"] = sorted(sel), cover
            st["px"] = price_symbols(cands, sel, daily, now)
        selected = set(st.get("selected") or [])
        if ok:
            d0 = _day_ts(c["history_start"]) if full else today - DAILY_REFRESH_DAYS * DAY
            series_d = aggregate(daily, cands, selected, DAY, t_from=d0, t_to=today)
            for k, pts in series_d.items():
                store.put("1d", k, pts, replace_from=0 if full else d0)
            for coin, sym in (st.get("px") or {}).items():
                pts = {t - t % DAY: p[2] for t, p in (daily.get(sym) or {}).items() if t < today}
                store.put("1d", px_sid(coin), pts, replace_from=None)
            st["daily_day"] = today
            st["version"] = CVD_VERSION
        else:
            log.warning("CVD 1d: część paczek nieudana — serie dzienne bez zmian, ponowię przy następnym skanie")
    selected = set(st.get("selected") or [])
    if not selected:
        raise RuntimeError("brak wybranych rynków CVD")

    # świece godzinowe wybranych rynków
    keep_from = now_h - INTRADAY_KEEP_HOURS * HOUR
    h_full = full or not store.series["1h"].get(sid("BTC", "spot")) or st.get("h_version") != CVD_VERSION
    anchor = st.get("complete_until") or store.last_t("1h", sid("BTC", "spot"))
    start = keep_from if (h_full or not anchor) else max(anchor - OVERLAP_HOURS * HOUR, keep_from)
    f0 = getattr(client, "failed_batches", 0)
    syms_h = sorted(selected | set((st.get("px") or {}).values()))
    hourly = _history(client, syms_h, "1hour", start, now)
    ok_h = getattr(client, "failed_batches", 0) == f0
    series_h = aggregate(hourly, cands, selected, HOUR, t_from=start)
    for k, pts in series_h.items():
        store.put("1h", k, pts, replace_from=0 if h_full else start)
    for coin, sym in (st.get("px") or {}).items():
        store.put("1h", px_sid(coin), {t - t % HOUR: p[2] for t, p in (hourly.get(sym) or {}).items()})
        # bieżący (niepełny) dzień ceny z ostatniej świecy godzinowej
        h = store.series["1h"].get(px_sid(coin)) or {}
        if h:
            store.put("1d", px_sid(coin), S.daily_from_hourly(h, today))
    # bieżący dzień CVD z godzin (pełne dni nadpisuje codzienne pobranie świec dziennych)
    for k in series_h:
        store.put("1d", k, S.daily_sum_from_hourly(store.get("1h", k), today), replace_from=today)
    if ok_h:
        st["complete_until"] = now_h
        st["h_version"] = CVD_VERSION
    failed = getattr(client, "failed_batches", 0) - failed0
    info = {"candidates": len(cands), "selected": len(selected), "cover": st.get("cover"),
            "price_markets": st.get("px"), "calls": client.calls_made - calls0, "failed_batches": failed,
            "full": full, "daily": need_daily, "hourly_from": _iso(start)}
    log.info("CVD: %s", info)
    return info


# ── raporty (report.py / periodic.py) ────────────────────────
def window(d, coin, kind, t0, t1):
    """Suma wolumenu i delty ($) z dni [t0, t1) → (vol, delta) albo None."""
    vs = dict(d.pts("1d", sid(coin, kind, True)))
    ds = dict(d.pts("1d", sid(coin, kind)))
    days = [t for t in vs if t0 <= t < t1 and t in ds]
    if not days:
        return None
    return sum(vs[t] for t in days), sum(ds[t] for t in days)


def imbalance(w):
    return None if not w or not w[0] else 100.0 * w[1] / w[0]


def band(d, coin, kind, t_end, years=2, step_days=1, lo=10, hi=90):
    """Zwykły zakres przewagi (% wolumenu): percentyle lo–hi z okresów długości step_days z ostatnich `years` lat."""
    vs = dict(d.pts("1d", sid(coin, kind, True)))
    ds = dict(d.pts("1d", sid(coin, kind)))
    vals = []
    t = t_end - step_days * DAY
    t_min = t_end - years * 365 * DAY
    while t >= t_min:
        days = [x for x in range(t, t + step_days * DAY, DAY) if x in vs and x in ds]
        if len(days) == step_days:
            v = sum(vs[x] for x in days)
            if v > 0:
                vals.append(100.0 * sum(ds[x] for x in days) / v)
        t -= step_days * DAY
    if len(vals) < 20:
        return None
    vals.sort()

    def q(p):
        return vals[min(len(vals) - 1, max(0, int(round(p / 100 * (len(vals) - 1)))))]
    return [round(q(lo), 2), round(q(hi), 2)]


WHO = {(1, 1): "kupują spot i perp", (1, -1): "spot kupuje, perp sprzedaje", (-1, 1): "spot sprzedaje, perp kupuje",
       (-1, -1): "sprzedają spot i perp", (0, 1): "przewaga kupna tylko na perp",
       (0, -1): "przewaga sprzedaży tylko na perp", (1, 0): "przewaga kupna tylko na spot",
       (-1, 0): "przewaga sprzedaży tylko na spot", (0, 0): "bez wyraźnej przewagi"}


def who(sp, pp, flat):
    def sg(x):
        return 0 if x is None or abs(x) < flat else (1 if x > 0 else -1)
    return WHO[(sg(sp), sg(pp))]


def fmt_usd(v):
    if v is None:
        return "—"
    if abs(v) < 0.5:
        return "$0"
    a = abs(v)
    t = f"{a / 1e9:.2f}B" if a >= 1e9 else f"{a / 1e6:.0f}M" if a >= 1e6 else f"{a / 1e3:.0f}K" if a >= 1e3 else f"{a:.0f}"
    return ("-" if v < 0 else "+") + "$" + t


def fmt_pct(v):
    return "—" if v is None else f"{v:+.1f}%"


def cell(w):
    return "—" if not w else f"{fmt_usd(w[1])} ({fmt_pct(imbalance(w))})"


def price_change(d, coin, t_now, t_before):
    """Zmiana zamknięcia dziennego ceny coina (px_<coin>) w % albo None."""
    from report import at, pct_change
    pts = d.pts("1d", px_sid(coin))
    return pct_change(at(pts, t_now, 2 * DAY), at(pts, t_before, 2 * DAY))


def coins_of(cfg):
    return settings(cfg)["coins"]


def has_data(d):
    return bool(d.pts("1d", sid("BTC", "spot")))


DESC_TABLE = ("CVD = kupno − sprzedaż: różnica między transakcjami kupujących i sprzedających „po rynku” (ten, kto się "
              "spieszy i bierze cenę z arkusza). W nawiasie ta sama różnica jako % całego wolumenu — pozwala porównać coiny "
              "i dni. Spot = zakup prawdziwych coinów, perp = kontrakty z dźwignią.")
NOTE_MARKETS = ("Spot: Binance, Coinbase, Bybit, Kraken, Bitstamp, Bitfinex (OKX spot niedostępny w Coinalyze). Perp: Binance, "
                "Bybit, OKX, Hyperliquid, Deribit. Liczone są rynki z co najmniej 1% wolumenu danego coina. ")


def _example(rows_src):
    """„Jak czytać” z pierwszego wiersza (BTC, doba) — liczby z danych."""
    coin, label, w_s, w_p = rows_src
    if not w_s:
        return ""
    side = "kupujący" if w_s[1] >= 0 else "sprzedający"
    return (f" Przykład: {coin} w dobie {label} — na spot przeważali {side} o {fmt_usd(abs(w_s[1]))[1:]} "
            f"({abs(imbalance(w_s)):.1f}% wolumenu).")


def morning_blocks(d, now, cfg, table=True):
    """Raport poranny: tabela doba / 7 dni, słupki doby na tle 2 lat, wykres BTC 7 dni co godzinę.
    table=False (poprawka 45): tabela jest już w sekcji Derywaty, połączona z OI — tu tylko słupki i wykres."""
    if not has_data(d):
        return []
    from report import fmt_chg, utc
    c = settings(cfg)
    flat = float(c["flat_pct"])
    today = floor(now, DAY)
    day = today - DAY                          # ostatnia pełna doba UTC
    label = utc(day, "%d.%m")
    rows, drows, first = [], [], None
    for coin in c["coins"]:
        for lab, t0, tb in ((f"doba {label}", day, day - DAY), ("7 dni", day - 6 * DAY, day - 7 * DAY)):
            ws, wp = window(d, coin, "spot", t0, today), window(d, coin, "perp", t0, today)
            if not ws and not wp:
                continue
            rows.append([coin, lab, fmt_chg(price_change(d, coin, day, tb)), cell(ws), cell(wp),
                         who(imbalance(ws), imbalance(wp), flat)])
            if first is None:
                first = (coin, label, ws, wp)
        r = {"label": coin}
        for kind in KINDS:
            w = window(d, coin, kind, day, today)
            if w:
                r[kind] = round(imbalance(w), 2)
                r[kind + "_text"] = f"{fmt_pct(imbalance(w))} · {fmt_usd(w[1])}"
                b = band(d, coin, kind, day)
                if b:
                    r[kind + "_band"] = b
        if any(k in r for k in KINDS):
            drows.append(r)
    if not rows:
        return []
    blocks = [{"type": "section", "title": "CVD — kto kupował: spot i perp"},
              {"type": "table", "title": "Kupno vs sprzedaż — spot i perp",
               "cols": ["Coin", "Okres", "Cena", "CVD spot", "CVD perp", "Kto przeważał"], "rows": rows, "left": [0, 5],
               "desc": DESC_TABLE + (_example(first) if first else ""),
               "note": NOTE_MARKETS + f"Doba = dzień UTC (zamknięcie dnia), 7 dni = 7 pełnych dni do {label}. "
                                      f"Przewaga poniżej {flat:g}% wolumenu = „bez wyraźnej przewagi”."}]
    if not table:
        blocks = blocks[:1] if (drows or btc_hour_chart(d, today)) else []
    if drows:
        blocks.append({"type": "dbars", "title": f"Przewaga kupujących w dobie {label} — % wolumenu", "rows": drows,
                       "parts": [{"key": "spot", "name": "spot"}, {"key": "perp", "name": "perp"}],
                       "band_label": "zwykły zakres: 80% dni z ostatnich 2 lat",
                       "desc": ("" if table else "CVD = kupno − sprzedaż „po rynku”, tu jako % całego wolumenu doby. ") +
                               "Słupek w prawo = więcej kupna, w lewo = więcej sprzedaży. Szary pas = zwykły zakres (bez 10% "
                               "najmocniejszych dni kupna i 10% sprzedaży z 2 lat) — słupek poza pasem = dzień nietypowy. "
                               "Skala osobna dla spot i perp (na perp przewagi są zwykle mniejsze, bo wolumen jest ogromny).",
                       "note": "Pas liczony z dziennych odczytów tej samej sumy rynków."})
    ch = btc_hour_chart(d, today)
    if ch:
        blocks.append(ch)
    return blocks


def btc_hour_chart(d, t_end, days=7):
    hs, hp = d.pts("1h", sid("BTC", "spot")), d.pts("1h", sid("BTC", "perp"))
    px = [p for p in d.pts("1h", "px_btc") if t_end - days * DAY <= p[0] < t_end]
    if not hs or not hp:
        return None

    def cum(pts):
        out, run = [], 0.0
        for t, v in pts:
            if t_end - days * DAY <= t < t_end:
                run += v
                out.append([t, round(run)])
        return out
    s, p = cum(hs), cum(hp)
    if len(s) < 24 or len(p) < 24:
        return None
    series = [{"name": "CVD spot", "color": "#4fc3f7", "fmt": "flow", "scale": "left", "data": s},
              {"name": "CVD perp", "color": "#ffb74d", "fmt": "flow", "scale": "right", "data": p}]
    if px:
        series.append({"name": "Cena BTC", "color": "#9e9e9e", "fmt": "price", "scale": "hidden", "width": 1, "data": px})
    from report import utc
    return {"type": "chart", "title": f"BTC — CVD spot i perp, ostatnie {days} dni (co godzinę)", "log": False,
            "series": series,
            "desc": "CVD = suma narastająca (kupno − sprzedaż) od początku wykresu. Linia rośnie = przeważali kupujący, "
                    "spada = sprzedający. Spot i perp na osobnych osiach (na perp obraca się wielokrotnie więcej), więc "
                    "ważny jest kształt i kierunek, nie wysokość linii. Szara linia = cena BTC (bez osi).",
            "note": f"Świece godzinowe do {utc(t_end, '%d.%m %H:%M UTC')}."}


def weekly_blocks(d, start, end, cfg, weeks=12, chart_coins=("BTC", "ETH")):
    """Raport tygodniowy: tabela tydzień / 4 tygodnie dla coinów + przewaga tydzień po tygodniu (12 tygodni)."""
    if not has_data(d):
        return []
    from report import fmt_chg, utc
    c = settings(cfg)
    flat = float(c["flat_pct"])
    W = 7 * DAY
    rows = []
    for coin in c["coins"]:
        for lab, t0 in (("tydzień", start), ("4 tygodnie", end - 4 * W)):
            ws, wp = window(d, coin, "spot", t0, end), window(d, coin, "perp", t0, end)
            if not ws and not wp:
                continue
            rows.append([coin, lab, fmt_chg(price_change(d, coin, end - DAY, t0 - DAY)), cell(ws), cell(wp),
                         who(imbalance(ws), imbalance(wp), flat)])
    if not rows:
        return []
    blocks = [{"type": "table", "title": "Kupno vs sprzedaż — spot i perp w tygodniu",
               "cols": ["Coin", "Okres", "Cena", "CVD spot", "CVD perp", "Kto przeważał"], "rows": rows, "left": [0, 5],
               "desc": DESC_TABLE,
               "note": NOTE_MARKETS + f"Tydzień = pon.–nd. UTC, 4 tygodnie = ostatnie 4 pełne tygodnie. Przewaga poniżej "
                                      f"{flat:g}% wolumenu = „bez wyraźnej przewagi”."}]
    for i, coin in enumerate(chart_coins):
        rr = []
        bands = {kind: band(d, coin, kind, end, step_days=7) for kind in KINDS}
        for k in range(weeks - 1, -1, -1):
            w0 = end - (k + 1) * W
            r = {"label": utc(w0, "%d.%m")}
            for kind in KINDS:
                w = window(d, coin, kind, w0, w0 + W)
                if w:
                    r[kind] = round(imbalance(w), 2)
                    r[kind + "_text"] = f"{fmt_pct(imbalance(w))} · {fmt_usd(w[1])}"
                    if bands[kind]:
                        r[kind + "_band"] = bands[kind]
            if any(x in r for x in KINDS):
                rr.append(r)
        if not rr:
            continue
        blocks.append({"type": "dbars", "title": f"{coin} — przewaga kupujących tydzień po tygodniu ({weeks} tygodni)",
                       "rows": rr, "parts": [{"key": "spot", "name": "spot"}, {"key": "perp", "name": "perp"}],
                       "label_col": "Tydzień od", "band_label": "zwykły zakres: 80% tygodni z ostatnich 2 lat",
                       "desc": ("Każdy wiersz = tydzień (data poniedziałku). Słupek w prawo = więcej kupna, w lewo = więcej "
                                "sprzedaży, % wolumenu tygodnia. Szary pas = zwykły zakres tygodni z 2 lat. Skala osobna dla "
                                "spot i perp.") if i == 0 else ""})
    return blocks
