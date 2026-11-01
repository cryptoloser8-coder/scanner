"""Cykl BTC i makro USA (poprawka 29) — serie dzienne do nakładania w zakładce OI & TOTAL.

Cykl BTC (wszystkie dzienne, liczone w każdym skanie od nowa):
  mvrv_btc      MVRV = kapitalizacja / realized cap (Coin Metrics Community, od 2010)
  rprice_btc    realized price = cena / MVRV (średnia cena, po której monety ostatnio się ruszały)
  mvrvz_btc     MVRV-Z = (kapitalizacja − realized cap) / odchylenie standardowe kapitalizacji z całej historii
  mayer_btc     Mayer Multiple = cena / średnia 200-dniowa
  p200w_btc     cena / średnia 200-tygodniowa (1400 dni)
  picycle_btc   Pi Cycle: średnia 111-dniowa / (2 × średnia 350-dniowa); ≥ 1 = przecięcie
  ssr           SSR = kapitalizacja BTC / kapitał w stablecoinach (TradingView)
Makro USA (TradingView, dzienne; config tradingview.daily_symbols):
  dxy, spx, ndx, vix, us10y, gold — wprost; yc_10y2y = us10y − us02y (pp);
  net_liq = aktywa Fed (WALCL) − konto Skarbu (WTREGEN) − reverse repo (RRPONTSYD), w USD;
  m2 = podaż pieniądza M2 (M2SL), w USD.
Linie poziomów (meta.ref_lines) dla wskaźników cyklu liczy kod z danych: wartości przy szczytach
i dnach ceny BTC w poprzednich cyklach (cykl = okres między halvingami).
"""
import logging
import math
from datetime import datetime, timezone

import requests

log = logging.getLogger("cycle")
DAY = 86400
CM_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
CM_METRICS = {"cm_mvrv_btc": "CapMVRVCur", "cm_mcap_btc": "CapMrktCurUSD"}
HALVINGS = ("2012-11-28", "2016-07-09", "2020-05-11", "2024-04-19")
DEFAULTS = {
    "enabled": True,
    "coinmetrics": True,
    # jednostki serii FRED w TradingView → USD (WALCL i WTREGEN w mln, RRPONTSYD i M2SL w mld)
    "units": {"fed_assets": 1e6, "fed_tga": 1e6, "fed_rrp": 1e9, "fred_m2": 1e9},
    "ref_tops": 3,      # linie: tyle ostatnich zakończonych szczytów…
    "ref_bottoms": 2,   # …i den
}
TOP_COLOR, BOTTOM_COLOR = "#e05252", "#4caf7d"


def ccfg(cfg):
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (cfg.get("cycle") or {}).items() if v is not None})
    return out


def day_of(iso):
    return int(datetime.strptime(iso[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def mmyy(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%m.%Y")


# ── Coin Metrics ─────────────────────────────────────────────
def fetch_coinmetrics(store, now, session=None, max_pages=10):
    """Dopisuje cm_mvrv_btc i cm_mcap_btc (od ostatniego punktu − 10 dni; pierwszy raz od 2010)."""
    s = session or requests.Session()
    have = store.series["1d"].get("cm_mvrv_btc") or {}
    start = (max(have) - 10 * DAY) if have else day_of("2010-01-01")
    params = {"assets": "btc", "metrics": ",".join(CM_METRICS.values()), "frequency": "1d",
              "start_time": datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d"),
              "page_size": 10000}
    url, got = CM_URL, 0
    for _ in range(max_pages):
        r = s.get(url, params=params, timeout=60, headers={"User-Agent": "scanner"})
        if r.status_code != 200:
            raise RuntimeError(f"Coin Metrics HTTP {r.status_code}: {r.text[:150]}")
        js = r.json()
        for row in js.get("data") or []:
            t = day_of(row["time"])
            for sid, m in CM_METRICS.items():
                v = row.get(m)
                if v not in (None, ""):
                    store.put("1d", sid, {t: float(v)})
            got += 1
        url, params = js.get("next_page_url"), None
        if not url:
            break
    return got


# ── pomocnicze ───────────────────────────────────────────────
def daily(series, ffill_days=0):
    """{t: v} → sorted list [(t, v)] on a contiguous daily grid (gaps forward-filled up to ffill_days)."""
    if not series:
        return []
    ts = sorted(series)
    out, last_v, last_t = [], None, None
    for t in range(ts[0] - ts[0] % DAY, ts[-1] + 1, DAY):
        v = series.get(t)
        if v is not None:
            last_v, last_t = v, t
        elif last_v is not None and t - last_t <= ffill_days * DAY:
            v = last_v
        if v is not None:
            out.append((t, v))
    return out


def sma(pairs, n):
    """[(t, v)] → {t: mean of the last n values} (contiguous input)."""
    out, acc = {}, 0.0
    vals = [v for _, v in pairs]
    for i, (t, v) in enumerate(pairs):
        acc += v
        if i >= n:
            acc -= vals[i - n]
        if i >= n - 1:
            out[t] = acc / n
    return out


def ratio(a, b):
    return {t: a[t] / b[t] for t in a if t in b and b[t]}


# ── cykle z ceny ─────────────────────────────────────────────
TOP_WINDOW_DAYS = 730        # szczyt cyklu szukamy w 2 latach po halvingu (przed 1. halvingiem: od początku danych)


def cycle_extremes(px):
    """Szczyty i dna ceny BTC w cyklach wyznaczonych halvingami → (tops, bottoms) [(t, price)].
    Szczyt = maksimum w 2 latach po halvingu (pierwszy: przed 1. halvingiem). Dno = minimum między szczytem
    a następnym halvingiem. Szczyt bieżącego cyklu liczy się dopiero po spadku o ≥ 50%, a dno dopiero
    po następnym halvingu (wcześniej nie wiadomo, czy już było)."""
    if not px:
        return [], []
    first, last = min(px), max(px)
    halv = [day_of(h) for h in HALVINGS]
    windows = [(first, halv[0], halv[0])] + [
        (h, h + TOP_WINDOW_DAYS * DAY, nxt) for h, nxt in zip(halv, halv[1:] + [None])]
    tops, bottoms = [], []
    for a, b, next_halving in windows:
        w = {t: v for t, v in px.items() if a <= t < b}
        if not w:
            continue
        t_top = max(w, key=w.get)
        after = [v for t, v in px.items() if t > t_top and (next_halving is None or t < next_halving)]
        if next_halving is None and (not after or min(after) > w[t_top] * 0.5):
            continue                   # bieżący cykl: szczyt jeszcze niepotwierdzony
        tops.append((t_top, w[t_top]))
        if next_halving is not None and next_halving <= last:
            wb = {t: v for t, v in px.items() if t_top < t < next_halving}
            if wb:
                t_bot = min(wb, key=wb.get)
                bottoms.append((t_bot, wb[t_bot]))
    return tops, bottoms


def ref_lines(store, cfg):
    """{sid: [{"value", "label", "color"}]} — wartości wskaźników przy poprzednich szczytach i dnach."""
    c = ccfg(cfg)
    s = store.series["1d"]
    tops, bottoms = cycle_extremes(s.get("px_btc") or {})
    tops, bottoms = tops[-int(c["ref_tops"]):], bottoms[-int(c["ref_bottoms"]):]
    out = {}
    for sid in ("mvrv_btc", "mvrvz_btc", "mayer_btc", "p200w_btc", "picycle_btc", "ssr"):
        ser = s.get(sid) or {}
        lines = []
        for pts, word, col in ((tops, "szczyt", TOP_COLOR), (bottoms, "dno", BOTTOM_COLOR)):
            for t, _ in pts:
                if sid == "ssr" and t < day_of("2020-01-01"):
                    continue           # wcześniej stablecoinów było za mało, żeby SSR był porównywalny
                v = ser.get(t)
                if v is not None:
                    lines.append({"value": round(v, 3), "label": f"{word} {mmyy(t)}", "color": col})
        if sid == "picycle_btc":
            lines.append({"value": 1.0, "label": "przecięcie średnich", "color": "#ffc107"})
        if sid == "mvrv_btc":
            lines.append({"value": 1.0, "label": "cena = realized price", "color": "#ffc107"})
        if lines:
            out[sid] = lines
    yc = s.get("yc_10y2y") or {}
    if yc:
        out["yc_10y2y"] = [{"value": 0.0, "label": "odwrócenie krzywej", "color": "#ffc107"}]
    return out


# ── obliczenia ───────────────────────────────────────────────
class _Out(dict):
    """Writes through store.put (rounded like the rest of the data, replaces the whole series)."""
    def __init__(self, store):
        super().__init__(store.series["1d"])
        self.store = store

    def __setitem__(self, sid, pts):
        self.store.put("1d", sid, pts, replace_from=0)
        super().__setitem__(sid, self.store.series["1d"][sid])

    def pop(self, sid, default=None):
        self.store.series["1d"].pop(sid, None)
        return super().pop(sid, default)


def compute(store, cfg):
    """Wylicza serie cyklu i makro w store.series['1d'] (po S.derived). → info."""
    c = ccfg(cfg)
    s = _Out(store)
    info = {}
    px = s.get("px_btc") or {}
    if px:
        p = daily(px, ffill_days=3)
        pd = dict(p)
        s["mayer_btc"] = ratio(pd, sma(p, 200))
        s["p200w_btc"] = ratio(pd, sma(p, 1400))
        s111, s350 = sma(p, 111), sma(p, 350)
        s["picycle_btc"] = {t: s111[t] / (2 * s350[t]) for t in s350 if t in s111 and s350[t]}
    mv, mc = s.get("cm_mvrv_btc") or {}, s.get("cm_mcap_btc") or {}
    if mv:
        s["mvrv_btc"] = dict(mv)
        if px:
            s["rprice_btc"] = {t: px[t] / mv[t] for t in mv if t in px and mv[t] > 0}
        if mc:
            common = sorted(t for t in mv if t in mc and mv[t] > 0)
            caps = [mc[t] for t in common]
            if len(caps) > 30:
                mean = sum(caps) / len(caps)
                sd = math.sqrt(sum((x - mean) ** 2 for x in caps) / len(caps))
                if sd > 0:
                    s["mvrvz_btc"] = {t: (mc[t] - mc[t] / mv[t]) / sd for t in common}
    tot, t2, st = s.get("total") or {}, s.get("total2") or {}, s.get("stable_mcap") or {}
    if tot and t2 and st:
        s["ssr"] = {t: (tot[t] - t2[t]) / st[t] for t in st if t in tot and t in t2 and st[t] > 0}
    # makro
    u10, u2 = s.get("us10y") or {}, s.get("us02y") or {}
    if u10 and u2:
        s["yc_10y2y"] = {t: u10[t] - u2[t] for t in u10 if t in u2}
    units = c["units"]
    fa, tga, rrp = (s.get(k) or {} for k in ("fed_assets", "fed_tga", "fed_rrp"))
    if fa and tga and rrp:
        start = max(min(fa), min(tga), min(rrp))
        A, T, R = (dict(daily(x, ffill_days=14)) for x in (fa, tga, rrp))
        nl = {t: A[t] * units["fed_assets"] - T[t] * units["fed_tga"] - R[t] * units["fed_rrp"]
              for t in A if t >= start and t in T and t in R}
        last = nl[max(nl)] if nl else None
        if last is not None and 1e12 < last < 3e13:          # sanity: kilka bln USD
            s["net_liq"] = nl
        else:
            info["net_liq"] = f"pominięta — podejrzana wartość {last!r} (sprawdź jednostki cycle.units)"
            s.pop("net_liq", None)
    m2 = s.get("fred_m2") or {}
    if m2:
        s["m2"] = {t: v * units["fred_m2"] for t, v in m2.items()}
    info["series"] = sorted(k for k in ("mvrv_btc", "rprice_btc", "mvrvz_btc", "mayer_btc", "p200w_btc",
                                        "picycle_btc", "ssr", "yc_10y2y", "net_liq", "m2") if s.get(k))
    return info


def run(store, cfg, now, session=None):
    """→ (info, error or None)."""
    c = ccfg(cfg)
    info, err = {}, None
    if c.get("coinmetrics"):
        try:
            info["coinmetrics_rows"] = fetch_coinmetrics(store, now, session)
        except Exception as e:  # noqa: BLE001
            log.exception("Coin Metrics")
            err = str(e)
    info.update(compute(store, cfg))
    return info, err
