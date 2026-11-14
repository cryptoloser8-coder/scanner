"""Sonda historii: od kiedy źródła mają dane, którymi da się wydłużyć nasze serie.

Nic nie zmienia w danych ani w produkcji — tylko pyta źródła i zapisuje tabelę wyników.

    python collector/probe.py github --out DIR          # na GitHub Actions (workflow „Sonda”)
    python3 ~/scanner/collector/probe.py pi --publish   # na Orange Pi (Binance działa tylko stąd)

Wynik: DIR/probe.json + DIR/probe.md; z --publish także gałąź probe-<github|pi>
(raw.githubusercontent.com/<repo>/probe-pi/probe.md).

Sprawdzane (dla serii, które już mamy):
  coinalyze   — dzienne OI, funding, likwidacje, cena: od kiedy dla każdego rynku BTC/ETH i kilku altów,
  tradingview — dzienne ceny BTC/ETH z różnych giełd i indeksów (Bitstamp od 2011?),
  coinmetrics — Coin Metrics Community: cena, kapitalizacja, realized cap BTC/ETH (od 2010?),
  binance     — funding perpetuali BTCUSDT/ETHUSDT (od 2019?), tylko z Pi,
  vision      — archiwum data.binance.vision: dzienne metryki futures (OI, long/short) i lista par spot
                (także zdelistowanych — szerokość rynku bez błędu przeżywalności),
  cvd         — wolumen kupujących (bv) w Coinalyze dla BTC, ETH, SOL, BNB, XRP, DOGE: spot i perp, od kiedy,
                historia 1h, zgodność z „taker buy volume” w archiwum Binance (do CVD spot vs perp).

Nowe źródła do sekcji Alty (poprawka 45) — uruchamiane tylko na życzenie (--only coingecko dexscreener):
  coingecko   — ile coinów wpada do koszyków kapitalizacji ($1–10M, $10–100M, $100M–1B, > $1B), jakie mają obroty,
                czy odpowiedź zawiera zmiany 24h/7D/30D, jak głęboka jest historia na darmowym kluczu i ile to zapytań,
  dexscreener — trendujące narracje („metas”): czy API odpowiada z GitHuba i jakie pola zwraca.

Sieci (poprawka 47) — tylko na życzenie (--only defillama):
  defillama   — wolumen DEX, opłaty, stablecoiny i TVL dla 8 sieci (Ethereum, Robinhood Chain, Solana, BSC, TON, Base,
                Tron, Hyperliquid L1): od kiedy, czy ostatni dzień jest pełny, udział w stablecoinach; kandydaci spoza
                listy i percentyle z 2 lat do reguły „sieć nagle rośnie”.
"""
import argparse
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

log = logging.getLogger("probe")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) scanner-probe"}
START_2010 = int(datetime(2010, 1, 1, tzinfo=timezone.utc).timestamp())
CHECKS = {       # domyślny zestaw; coingecko, dexscreener i defillama tylko przez --only (nowe źródła, osobne pytanie)
    "github": ("coinalyze", "tradingview", "coinmetrics", "binance", "vision", "cvd"),
    "pi": ("binance", "vision", "coinmetrics"),
}


def iso(t):
    if t is None:
        return None
    if isinstance(t, str):
        return t[:10]
    if t > 1e11:            # ms
        t = t / 1000
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d")


def row(source, item, status="ok", first=None, last=None, n=None, note=""):
    return {"source": source, "item": item, "status": status, "first": iso(first), "last": iso(last),
            "n": n, "note": note}


def err_row(source, item, e):
    return row(source, item, "błąd", note=f"{type(e).__name__}: {str(e)[:160]}")


def _get(session, url, **kw):
    kw.setdefault("timeout", 60)
    kw.setdefault("headers", UA)
    r = session.get(url, **kw)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:120]}")
    return r


# ── Coinalyze ────────────────────────────────────────────────
CZ_ALL_EXCHANGES = ("BTC", "ETH")          # te coiny: wszystkie giełdy
CZ_BINANCE_ONLY = ("SOL", "XRP", "DOGE")   # te: tylko Binance (próbka altów)
CZ_ENDPOINTS = (
    ("OI", "/open-interest-history", "c", True),
    ("funding", "/funding-rate-history", "c", False),
    ("likwidacje", "/liquidation-history", ("l", "s"), True),
    ("cena", "/ohlcv-history", "c", False),
)


def coinalyze_markets(client):
    names = {e["code"]: e["name"] for e in client.exchanges()}
    out = []
    for m in client.future_markets():
        if not m.get("is_perpetual"):
            continue
        base = str(m.get("base_asset", "")).upper()
        ex = names.get(m.get("exchange"), m.get("exchange"))
        if base in CZ_ALL_EXCHANGES or (base in CZ_BINANCE_ONLY and ex == "Binance"):
            out.append((base, ex, m["symbol"]))
    return sorted(out)


CZ_CAP = 1500        # odpowiedź z tyloma punktami może być obcięta → dopytujemy o wcześniejsze dni


def history_all(client, path, syms, fields, usd, now, max_rounds=6):
    """Daily history from 2010 → {symbol: {t: v}}; if a symbol's answer looks capped
    (≥ CZ_CAP points), ask again for the days before its first point."""
    out = {s: {} for s in syms}
    todo = list(syms)
    ends = {s: now for s in syms}
    for _ in range(max_rounds):
        if not todo:
            break
        groups = {}
        for s in todo:
            groups.setdefault(ends[s], []).append(s)
        nxt = []
        for end, group in sorted(groups.items()):
            hist = client.history(path, group, "daily", START_2010, end, fields, usd=usd)
            for s in group:
                h = hist.get(s) or {}
                new = {t: v for t, v in h.items() if t not in out[s]}
                out[s].update(new)
                if len(h) >= CZ_CAP and new:
                    ends[s] = min(h) - 86400
                    nxt.append(s)
        todo = nxt
    return out


def check_coinalyze(session=None, client=None, now=None):
    from coinalyze import Coinalyze
    now = int(now or time.time())
    client = client or Coinalyze(os.environ.get("COINALYZE_API_KEY", ""), session=session)
    rows = []
    mk = coinalyze_markets(client)
    syms = [s for _, _, s in mk]
    for label, path, fields, usd in CZ_ENDPOINTS:
        try:
            hist = history_all(client, path, syms, fields, usd, now)
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("coinalyze", label, e))
            continue
        for base, ex, sym in mk:
            h = hist.get(sym) or {}
            if not h:
                rows.append(row("coinalyze", f"{label} {base} {ex} ({sym})", "brak"))
                continue
            ts = sorted(h)
            vals = [h[t] for t in ts]
            nz = [t for t, v in zip(ts, vals) if (sum(v) if isinstance(v, tuple) else v)]
            note = f"pierwszy niezerowy {iso(nz[0])}" if nz and nz[0] != ts[0] else ""
            rows.append(row("coinalyze", f"{label} {base} {ex} ({sym})", "ok", ts[0], ts[-1], len(ts), note))
    rows.append(row("coinalyze", "zużyte zapytania", note=str(client.calls_made)))
    return rows


# ── TradingView ──────────────────────────────────────────────
TV_SYMBOLS = ("BITSTAMP:BTCUSD", "BITSTAMP:ETHUSD", "COINBASE:BTCUSD", "COINBASE:ETHUSD",
              "BITFINEX:BTCUSD", "BITFINEX:ETHUSD", "INDEX:BTCUSD", "INDEX:ETHUSD",
              "CRYPTOCAP:BTC", "CRYPTOCAP:ETH", "CRYPTOCAP:TOTAL", "BINANCE:BTCUSDT")


def check_tradingview(tv=None, **_):
    from tradingview import TradingView
    tv = tv or TradingView(timeout=40)
    rows = []
    for sym in TV_SYMBOLS:
        bars, note = None, ""
        for n in (20000, 5000):
            try:
                bars = tv.bars(sym, "1D", n)
                note = f"n_bars={n}"
                break
            except Exception as e:  # noqa: BLE001
                note = f"{type(e).__name__}: {str(e)[:120]}"
        if not bars:
            rows.append(row("tradingview", sym, "błąd", note=note))
            continue
        rows.append(row("tradingview", sym, "ok", bars[0][0], bars[-1][0], len(bars),
                        f"{note}; pierwsza cena {bars[0][1]:g}"))
    return rows


# ── Coin Metrics Community ───────────────────────────────────
CM_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
CM_METRICS = {"btc": ("PriceUSD", "CapMrktCurUSD", "CapRealUSD", "CapMVRVCur", "SplyCur"),
              "eth": ("PriceUSD", "CapMrktCurUSD", "CapRealUSD")}


def check_coinmetrics(session=None, sleep=time.sleep, **_):
    s = session or requests.Session()
    rows = []
    for asset, metrics in CM_METRICS.items():
        for m in metrics:
            try:
                ends = {}
                for side in ("start", "end"):
                    r = _get(s, CM_URL, params={"assets": asset, "metrics": m, "frequency": "1d",
                                                "page_size": 1, "paging_from": side})
                    data = r.json().get("data") or []
                    ends[side] = data[0] if data else None
                    sleep(0.7)               # limit: 10 zapytań / 6 s
                if not ends["start"]:
                    rows.append(row("coinmetrics", f"{asset} {m}", "brak"))
                    continue
                rows.append(row("coinmetrics", f"{asset} {m}", "ok", ends["start"]["time"],
                                (ends["end"] or {}).get("time"),
                                note=f"pierwsza wartość {ends['start'].get(m)}"))
            except Exception as e:  # noqa: BLE001
                rows.append(err_row("coinmetrics", f"{asset} {m}", e))
    return rows


# ── Binance futures (tylko Pi — GitHub zablokowany) ──────────
def check_binance(session=None, **_):
    s = session or requests.Session()
    rows = []
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        try:
            first = _get(s, url, params={"symbol": sym, "startTime": 0, "limit": 1}).json()
            last = _get(s, url, params={"symbol": sym, "limit": 1}).json()
            if not first:
                rows.append(row("binance", f"funding {sym}", "brak"))
                continue
            rows.append(row("binance", f"funding {sym}", "ok", first[0]["fundingTime"],
                            last[-1]["fundingTime"] if last else None,
                            note=f"pierwsza stawka {first[0].get('fundingRate')}"))
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("binance", f"funding {sym}", e))
    return rows


# ── data.binance.vision (archiwum Binance) ───────────────────
VISION_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
VISION_DL = "https://data.binance.vision/"
KEY_RE = re.compile(r"<Key>([^<]+)</Key>")
PREFIX_RE = re.compile(r"<Prefix>([^<]+)</Prefix>")
TRUNC_RE = re.compile(r"<IsTruncated>true</IsTruncated>")
NEXT_RE = re.compile(r"<NextMarker>([^<]+)</NextMarker>")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def s3_list(session, prefix, delimiter=None, max_pages=20):
    """→ (keys, common_prefixes) for an S3 prefix (paged by marker)."""
    keys, prefixes, marker = [], [], None
    for _ in range(max_pages):
        params = {"prefix": prefix}
        if delimiter:
            params["delimiter"] = delimiter
        if marker:
            params["marker"] = marker
        xml = _get(session, VISION_S3, params=params).text
        k = KEY_RE.findall(xml)
        p = [x for x in PREFIX_RE.findall(xml) if x != prefix]
        keys += k
        prefixes += p
        if not TRUNC_RE.search(xml):
            break
        nm = NEXT_RE.search(xml)
        marker = nm.group(1) if nm else ((k or p or [None])[-1])
        if not marker:
            break
    return keys, prefixes


def check_vision(session=None, **_):
    s = session or requests.Session()
    rows = []
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        item = f"futures UM metrics {sym}"
        try:
            keys, _ = s3_list(s, f"data/futures/um/daily/metrics/{sym}/")
            zips = sorted(k for k in keys if k.endswith(".zip"))
            if not zips:
                rows.append(row("vision", item, "brak"))
                continue
            d0, d1 = DATE_RE.search(zips[0]).group(1), DATE_RE.search(zips[-1]).group(1)
            note = ""
            if sym == "BTCUSDT":     # nagłówek i pierwszy wiersz najstarszego pliku
                z = zipfile.ZipFile(io.BytesIO(_get(s, VISION_DL + zips[0]).content))
                with z.open(z.namelist()[0]) as f:
                    lines = f.read().decode("utf-8", "replace").splitlines()
                note = "kolumny: " + (lines[0] if lines else "?")[:200]
                if len(lines) > 1:
                    note += " | 1. wiersz: " + lines[1][:160]
            rows.append(row("vision", item, "ok", d0, d1, len(zips), note))
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("vision", item, e))
    try:
        _, pref = s3_list(s, "data/spot/monthly/klines/", delimiter="/")
        syms = [p.rstrip("/").rsplit("/", 1)[-1] for p in pref]
        usdt = [x for x in syms if x.endswith("USDT")]
        rows.append(row("vision", "spot — pary w archiwum (także zdelistowane)", "ok", n=len(syms),
                        note=f"w tym */USDT: {len(usdt)}"))
    except Exception as e:  # noqa: BLE001
        rows.append(err_row("vision", "spot — pary w archiwum", e))
    try:
        keys, _ = s3_list(s, "data/spot/monthly/klines/LUNAUSDT/1d/")
        zips = sorted(k for k in keys if k.endswith(".zip"))
        rows.append(row("vision", "spot LUNAUSDT 1d (zdelistowana w 05.2022)", "ok" if zips else "brak",
                        DATE_RE.search(zips[0]).group(1) if zips else None,
                        DATE_RE.search(zips[-1]).group(1) if zips else None, len(zips)))
    except Exception as e:  # noqa: BLE001
        rows.append(err_row("vision", "spot LUNAUSDT 1d", e))
    return rows


# ── CVD (wolumen kupujących / sprzedających) — spot vs perp ──
# Coinalyze /ohlcv-history ma pola v (wolumen), bv (wolumen kupujących — agresorów), tx, btx (transakcje).
# Delta = kupno − sprzedaż = 2·bv − v; CVD = suma narastająca delty. Sonda sprawdza, dla których rynków
# są te pola, od kiedy, jak głęboka jest historia 1h i czy bv zgadza się z „taker buy volume” Binance
# (archiwum data.binance.vision) — czyli czy naprawdę znaczy to, co myślimy.
CVD_COINS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE")
CVD_PERP_EXCHANGES = ("Binance", "Bybit", "OKX", "Hyperliquid", "Deribit")   # jak OI (config)
CVD_SPOT_EXCHANGES = ("Binance", "Coinbase", "Bybit", "OKX", "Kraken", "Bitstamp", "Bitfinex")
CVD_QUOTES = ("USDT", "USD", "USDC", "FDUSD")
CVD_1H_DAYS = 120
DAY = 86400


def _ex_codes(exchanges, wanted):
    from coinalyze import _norm_name
    wn = [_norm_name(w) for w in wanted]
    out = {}
    for ex in exchanges:
        n = _norm_name(ex.get("name"))
        if any(n and w and (n.startswith(w) or w.startswith(n)) for w in wn):
            out[ex.get("code")] = ex.get("name")
    return out


def cvd_markets(exchanges, futures, spots, coins=CVD_COINS):
    """→ list of market dicts {kind spot|perp, base, ex, sym, soe, quote, unit base|quote, bs (has_buy_sell_data)}."""
    from coinalyze import norm_base
    perp_ex = _ex_codes(exchanges, CVD_PERP_EXCHANGES)
    spot_ex = _ex_codes(exchanges, CVD_SPOT_EXCHANGES)
    out = []
    for m in futures or []:
        base = norm_base(m.get("base_asset"))
        quote = str(m.get("quote_asset") or "").upper()
        if not m.get("is_perpetual") or m.get("exchange") not in perp_ex or base not in coins:
            continue
        if quote not in CVD_QUOTES:
            continue
        unit = "quote" if "QUOTE" in str(m.get("oi_lq_vol_denominated_in") or "").upper() else "base"
        out.append({"kind": "perp", "base": base, "ex": perp_ex[m["exchange"]], "sym": m["symbol"],
                    "soe": m.get("symbol_on_exchange") or "", "quote": quote, "unit": unit,
                    "margined": m.get("margined"), "bs": m.get("has_buy_sell_data")})
    for m in spots or []:
        base = norm_base(m.get("base_asset"))
        quote = str(m.get("quote_asset") or "").upper()
        if m.get("exchange") not in spot_ex or base not in coins or quote not in CVD_QUOTES:
            continue
        out.append({"kind": "spot", "base": base, "ex": spot_ex[m["exchange"]], "sym": m["symbol"],
                    "soe": m.get("symbol_on_exchange") or "", "quote": quote, "unit": "base",
                    "margined": None, "bs": m.get("has_buy_sell_data")})
    return sorted(out, key=lambda x: (CVD_COINS.index(x["base"]) if x["base"] in CVD_COINS else 99,
                                      x["kind"] != "spot", x["ex"], x["sym"]))


def ohlcv_raw(client, syms, interval, frm, to, step, max_rounds=6, cap=CZ_CAP):
    """Raw /ohlcv-history points → {symbol: {t: point dict}}; capped answers are followed backwards."""
    out = {s: {} for s in syms}
    ends = {s: int(to) for s in syms}
    todo = list(syms)
    for _ in range(max_rounds):
        if not todo:
            break
        groups = {}
        for s in todo:
            groups.setdefault(ends[s], []).append(s)
        nxt = []
        for end, group in sorted(groups.items()):
            for batch in _chunks_local(group, getattr(client, "batch", 18)):
                data = client._batch_get("/ohlcv-history", {"interval": interval, "from": int(frm),
                                                            "to": int(end)}, batch)
                for r in data or []:
                    s = r.get("symbol")
                    if s not in out:
                        continue
                    pts = [p for p in (r.get("history") or []) if p.get("t") is not None]
                    new = {int(p["t"]): p for p in pts if int(p["t"]) not in out[s]}
                    out[s].update(new)
                    if len(pts) >= cap and new:
                        ends[s] = min(new) - step
                        nxt.append(s)
        todo = nxt
    return out


def _chunks_local(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), max(1, int(n))):
        yield seq[i:i + max(1, int(n))]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    k = len(xs) // 2
    return xs[k] if len(xs) % 2 else (xs[k - 1] + xs[k]) / 2


def _usd(p, unit):
    v, c = _num(p.get("v")), _num(p.get("c"))
    if v is None:
        return None
    return v if unit == "quote" else (v * c if c is not None else None)


def _delta_usd(p, unit):
    v, bv, c = _num(p.get("v")), _num(p.get("bv")), _num(p.get("c"))
    if v is None or bv is None:
        return None
    d = 2 * bv - v
    return d if unit == "quote" else (d * c if c is not None else None)


def cvd_stats(pts, now, unit="base"):
    """Summary of one market's daily points: dates, fields, bv quality, last day and CVD 30 / 365 days (USD)."""
    full = {t: p for t, p in pts.items() if t + DAY <= now}
    ts = sorted(full)
    res = {"n": len(ts), "first": ts[0] if ts else None, "last": ts[-1] if ts else None, "fields": [],
           "bv_first": None, "bv_share": None, "ratio_med": None, "ratio_min": None, "ratio_max": None,
           "half_share": None, "last_usd": None, "last_delta_usd": None, "cvd30": None, "cvd365": None,
           "tx": False}
    if not ts:
        return res
    fields = set()
    for p in full.values():
        fields.update(k for k, v in p.items() if v is not None)
    res["fields"] = sorted(fields - {"t"})
    res["tx"] = "tx" in fields and "btx" in fields
    traded = [t for t in ts if (_num(full[t].get("v")) or 0) > 0]
    with_bv = [t for t in traded if (_num(full[t].get("bv")) or 0) > 0]
    res["bv_first"] = with_bv[0] if with_bv else None
    if traded:
        since = res["bv_first"] or traded[0]
        span = [t for t in traded if t >= since]
        res["bv_share"] = sum(1 for t in span if _num(full[t].get("bv")) is not None) / len(span)
    year = [t for t in with_bv if t >= ts[-1] - 364 * DAY]
    ratios = [_num(full[t]["bv"]) / _num(full[t]["v"]) for t in year]
    if ratios:
        res["ratio_med"], res["ratio_min"], res["ratio_max"] = _median(ratios), min(ratios), max(ratios)
        res["half_share"] = sum(1 for r in ratios if abs(r - 0.5) < 1e-6) / len(ratios)
    last = full[ts[-1]]
    res["last_usd"] = _usd(last, unit)
    res["last_delta_usd"] = _delta_usd(last, unit)

    def cvd(days):
        d = [_delta_usd(full[t], unit) for t in ts if t > ts[-1] - days * DAY]
        d = [x for x in d if x is not None]
        return sum(d) if d else None
    res["cvd30"], res["cvd365"] = cvd(30), cvd(365)
    return res


def fmt_usd(x):
    if x is None:
        return "—"
    a = abs(x)
    s = "−" if x < 0 else ""
    if a >= 1e9:
        return f"{s}${a / 1e9:.2f} mld"
    if a >= 1e6:
        return f"{s}${a / 1e6:.1f} mln"
    if a >= 1e3:
        return f"{s}${a / 1e3:.0f} tys."
    return f"{s}${a:.0f}"


def _fmt_ratio(x, nd=3):
    return "—" if x is None else f"{x:.{nd}f}"


# data.binance.vision: miesięczne świece 1d. Kolumny: 0 open_time, 4 close, 5 volume, 7 quote/base volume,
# 8 count, 9 taker buy (base albo kontrakty), 10 taker buy quote/base.
VISION_KLINES = {"spot": "data/spot/monthly/klines/{s}/1d/{s}-1d-{m}.zip",
                 "um": "data/futures/um/monthly/klines/{s}/1d/{s}-1d-{m}.zip",
                 "cm": "data/futures/cm/monthly/klines/{s}/1d/{s}-1d-{m}.zip"}


def parse_vision_klines(text):
    """CSV (with or without header; spot open_time in ms or µs) → {day_t_seconds: [floats]}."""
    out = {}
    for line in text.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 11:
            continue
        t = _num(parts[0])
        if t is None:
            continue                     # nagłówek
        if t > 1e14:                     # µs (spot od 2025)
            t /= 1e6
        elif t > 1e11:                   # ms
            t /= 1e3
        out[int(t) // DAY * DAY] = [_num(x) for x in parts[:11]]
    return out


def _months_back(now, n):
    d = datetime.fromtimestamp(now, timezone.utc)
    y, m = d.year, d.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
    return out


def vision_market(mk):
    """Coinalyze Binance market → (archive kind, Binance symbol) or None."""
    soe = (mk.get("soe") or "").upper()
    if not soe or mk.get("ex", "").lower() != "binance":
        return None
    if mk["kind"] == "spot":
        return "spot", soe
    if soe.endswith("_PERP") or str(mk.get("margined") or "").upper().startswith("COIN"):
        return "cm", soe
    return "um", soe


def vision_compare(session, mk, pts, now):
    """Compare Coinalyze v / bv / tx with the Binance archive for the last available month."""
    vm = vision_market(mk)
    if not vm:
        return None
    kind, s = vm
    item = f"{mk['base']} {mk['kind']} Binance {mk['sym']} ↔ archiwum Binance {kind}/{s}"
    try:
        rows = None
        for month in _months_back(now, 2):
            url = VISION_DL + VISION_KLINES[kind].format(s=s, m=month)
            r = session.get(url, timeout=60, headers=UA)
            if r.status_code == 200:
                z = zipfile.ZipFile(io.BytesIO(r.content))
                with z.open(z.namelist()[0]) as f:
                    rows = parse_vision_klines(f.read().decode("utf-8", "replace"))
                break
        if not rows:
            return row("cvd", item, "brak", note="brak pliku w archiwum za 2 ostatnie miesiące")
        days = sorted(t for t in rows if t in pts)
        if not days:
            return row("cvd", item, "brak", note="brak wspólnych dni")

        def med(field, col):
            rs = []
            for t in days:
                a, b = _num(pts[t].get(field)), rows[t][col]
                if a is not None and b:
                    rs.append(a / b)
            return _median(rs)
        # v: kolumna 5 (spot/um: coiny; cm: kontrakty) albo 7 (spot/um: quote; cm: coiny)
        # bv: kolumna 9 (spot/um: coiny; cm: kontrakty) albo 10 (spot/um: quote; cm: coiny)
        names = {"spot": ("coiny", "quote"), "um": ("coiny", "quote"), "cm": ("kontrakty", "coiny")}[kind]
        parts = [f"v ÷ volume({names[0]}) {_fmt_ratio(med('v', 5))}",
                 f"v ÷ volume({names[1]}) {_fmt_ratio(med('v', 7))}",
                 f"bv ÷ taker_buy({names[0]}) {_fmt_ratio(med('bv', 9))}",
                 f"bv ÷ taker_buy({names[1]}) {_fmt_ratio(med('bv', 10))}",
                 f"tx ÷ count {_fmt_ratio(med('tx', 8))}"]
        return row("cvd", item, "ok", days[0], days[-1], len(days),
                   "mediana Coinalyze ÷ Binance (1,000 = zgodne): " + "; ".join(parts))
    except Exception as e:  # noqa: BLE001
        return err_row("cvd", item, e)


def check_cvd(session=None, client=None, now=None):
    from coinalyze import Coinalyze
    now = int(now or time.time())
    s = session or requests.Session()
    client = client or Coinalyze(os.environ.get("COINALYZE_API_KEY", ""), session=session)
    rows = []
    mk = cvd_markets(client.exchanges(), client.future_markets(), client._get("/spot-markets"))
    with_bs = [m for m in mk if m["bs"] is not False]
    for m in mk:
        if m["bs"] is False:
            rows.append(row("cvd", f"{m['base']} {m['kind']} {m['ex']} ({m['sym']})", "brak",
                            note="has_buy_sell_data = false (bez zapytania)"))
    syms = [m["sym"] for m in with_bs]
    daily = ohlcv_raw(client, syms, "daily", START_2010, now, DAY) if syms else {}
    hourly = ohlcv_raw(client, syms, "1hour", now - CVD_1H_DAYS * DAY, now, 3600, max_rounds=1) if syms else {}
    stats = {}
    for m in with_bs:
        st = stats[m["sym"]] = cvd_stats(daily.get(m["sym"]) or {}, now, m["unit"])
        h = hourly.get(m["sym"]) or {}
        hb = [t for t, p in h.items() if _num(p.get("bv")) is not None]
        item = f"{m['base']} {m['kind']} {m['ex']} ({m['sym']}, {m['quote']})"
        if not st["n"]:
            rows.append(row("cvd", item, "brak", note="brak świec dziennych"))
            continue
        note = [f"pola: {','.join(st['fields'])}",
                f"bv od {iso(st['bv_first']) or '—'}",
                f"bv w {st['bv_share'] * 100:.0f}% dni" if st["bv_share"] is not None else "bv: brak",
                f"bv÷v rok: mediana {_fmt_ratio(st['ratio_med'])}, {_fmt_ratio(st['ratio_min'])}–"
                f"{_fmt_ratio(st['ratio_max'])}" + (f", dokładnie 0,5: {st['half_share'] * 100:.0f}% dni"
                                                    if st["half_share"] else ""),
                f"wolumen dnia {fmt_usd(st['last_usd'])} (jedn. {m['unit']})",
                f"delta dnia {fmt_usd(st['last_delta_usd'])}",
                f"CVD 30 dni {fmt_usd(st['cvd30'])}, 365 dni {fmt_usd(st['cvd365'])}",
                f"1h: {len(h)} świec" + (f" od {datetime.fromtimestamp(min(h), timezone.utc):%Y-%m-%d %H:%M}"
                                         if h else "") + (f", bv w {len(hb)}" if h else "")]
        status = "ok" if st["bv_first"] else "brak bv"
        rows.append(row("cvd", item, status, st["first"], st["last"], st["n"], "; ".join(note)))
    # porównanie z archiwum Binance (co znaczy bv, w jakich jednostkach jest v)
    for m in with_bs:
        r = vision_compare(s, m, daily.get(m["sym"]) or {}, now)
        if r:
            rows.append(r)
    # podsumowanie na coin: spot vs perp
    for coin in CVD_COINS:
        part = {}
        for kind in ("spot", "perp"):
            ms = [m for m in with_bs if m["base"] == coin and m["kind"] == kind and stats.get(m["sym"], {}).get("bv_first")]
            vol = [stats[m["sym"]]["last_usd"] for m in ms if stats[m["sym"]]["last_usd"] is not None]
            c30 = [stats[m["sym"]]["cvd30"] for m in ms if stats[m["sym"]]["cvd30"] is not None]
            top = sorted(ms, key=lambda m: -(stats[m["sym"]]["last_usd"] or 0))[:3]
            part[kind] = (len(ms), sum(vol) if vol else None, sum(c30) if c30 else None,
                          ", ".join(f"{m['ex']} {m['sym']}" for m in top))
        n_all = sum(1 for m in mk if m["base"] == coin)
        note = (f"rynków: {n_all}; spot z bv {part['spot'][0]}: wolumen dnia {fmt_usd(part['spot'][1])}, "
                f"CVD 30 dni {fmt_usd(part['spot'][2])} (największe: {part['spot'][3] or '—'}); "
                f"perp z bv {part['perp'][0]}: wolumen dnia {fmt_usd(part['perp'][1])}, "
                f"CVD 30 dni {fmt_usd(part['perp'][2])} (największe: {part['perp'][3] or '—'})")
        rows.append(row("cvd-podsumowanie", coin, "ok" if part["spot"][0] and part["perp"][0] else "niepełne",
                        note=note))
    rows.append(row("cvd", "zużyte zapytania Coinalyze", note=str(client.calls_made)))
    return rows


FUNCS = {"coinalyze": check_coinalyze, "tradingview": check_tradingview, "coinmetrics": check_coinmetrics,
         "binance": check_binance, "vision": check_vision, "cvd": check_cvd}


# ── CoinGecko: koszyki kapitalizacji altów ───────────────────
CG = "https://api.coingecko.com/api/v3"
CG_BUCKETS = (("> $1B", 1e9, float("inf")), ("$100M – $1B", 1e8, 1e9), ("$10M – $100M", 1e7, 1e8), ("$1M – $10M", 1e6, 1e7))
CG_SKIP_CATEGORIES = ("stablecoins", "wrapped-tokens", "liquid-staking-tokens")
CG_MAX_PAGES = 40                      # 40 × 250 = 10 000 coinów
CG_VOL_LEVELS = (50e3, 250e3, 1e6)     # progi dziennego obrotu do filtra koszyków


def _cg_get(session, path, params, sleep, calls):
    key = os.environ.get("COINGECKO_API_KEY", "")
    headers = dict(UA, **({"x-cg-demo-api-key": key} if key else {}))
    for attempt in range(5):
        calls[0] += 1
        r = session.get(CG + path, params=params, headers=headers, timeout=60)
        if r.status_code == 200:
            sleep(2.5)                 # limit darmowego klucza: ok. 30 zapytań na minutę
            return r.json()
        if r.status_code == 429 or r.status_code >= 500:
            sleep(min(20 * (attempt + 1), 65))
            continue
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:120]}")
    raise RuntimeError("zbyt wiele odpowiedzi 429 / 5xx")


def cg_bucket_stats(coins, skip_ids=()):
    """Lista z /coins/markets → statystyki koszyków (bez BTC, ETH i podanych id: stablecoiny, tokeny opakowane)."""
    out = []
    for name, lo, hi in CG_BUCKETS:
        b = [c for c in coins if c.get("id") not in skip_ids and c.get("id") not in ("bitcoin", "ethereum")
             and lo <= (c.get("market_cap") or 0) < hi]
        vols = sorted((c.get("total_volume") or 0) for c in b)
        ch = [c.get("price_change_percentage_24h_in_currency") for c in b]
        ch = sorted(x for x in ch if x is not None)
        out.append({"bucket": name, "n": len(b), "vol_median": _median(vols) if vols else None,
                    "vol_ok": {lvl: sum(1 for v in vols if v >= lvl) for lvl in CG_VOL_LEVELS},
                    "chg24_median": _median(ch) if ch else None,
                    "with_7d": sum(1 for c in b if c.get("price_change_percentage_7d_in_currency") is not None),
                    "with_30d": sum(1 for c in b if c.get("price_change_percentage_30d_in_currency") is not None),
                    "sample": [c.get("id") for c in b[:1] + b[len(b) // 2:len(b) // 2 + 1]]})
    return out


def check_coingecko(session=None, sleep=time.sleep, max_pages=CG_MAX_PAGES, **_):
    s = session or requests.Session()
    calls = [0]
    rows = [row("coingecko", "klucz API", "ok" if os.environ.get("COINGECKO_API_KEY") else "brak",
                note="sekret COINGECKO_API_KEY (darmowy klucz demo)" if os.environ.get("COINGECKO_API_KEY")
                else "bez klucza — niższe limity; dodaj COINGECKO_API_KEY do kroku sondy")]
    coins, last_page = [], 0
    try:
        for page in range(1, max_pages + 1):
            got = _cg_get(s, "/coins/markets", {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250,
                                                "page": page, "price_change_percentage": "24h,7d,30d"}, sleep, calls)
            if not got:
                break
            coins += got
            last_page = page
            if (got[-1].get("market_cap") or 0) < CG_BUCKETS[-1][1]:       # cała reszta poniżej $1M
                break
    except Exception as e:  # noqa: BLE001
        rows.append(err_row("coingecko", f"lista coinów (po {last_page} stronach)", e))
    if not coins:
        return rows
    skip = set()
    for cat in CG_SKIP_CATEGORIES:
        try:
            got = _cg_get(s, "/coins/markets", {"vs_currency": "usd", "category": cat, "order": "market_cap_desc",
                                                "per_page": 250, "page": 1}, sleep, calls)
            skip |= {c["id"] for c in got or []}
            rows.append(row("coingecko", f"kategoria {cat}", "ok", n=len(got or []), note="pomijane w koszykach (pierwsze 250)"))
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("coingecko", f"kategoria {cat}", e))
    below = next((i for i, c in enumerate(coins) if (c.get("market_cap") or 0) < CG_BUCKETS[-1][1]), None)
    rows.append(row("coingecko", "lista coinów", "ok", n=len(coins),
                    note=f"{last_page} stron po 250; kapitalizacja spada poniżej $1M na pozycji "
                         f"{below + 1 if below is not None else '> ' + str(len(coins))}; pola zmian 24h/7D/30D w odpowiedzi: "
                         f"{'tak' if 'price_change_percentage_7d_in_currency' in coins[0] else 'NIE'}"))
    stats = cg_bucket_stats(coins, skip)
    for st in stats:
        vo = ", ".join(f"≥ {fmt_usd(lvl)}: {n}" for lvl, n in st["vol_ok"].items())
        rows.append(row("coingecko", f"koszyk {st['bucket']}", "ok" if st["n"] else "brak", n=st["n"],
                        note=f"obrót 24h mediana {fmt_usd(st['vol_median']) if st['vol_median'] is not None else '—'}; coinów z obrotem {vo}; "
                             f"mediana zmiany 24h {st['chg24_median']:+.1f}%; ze zmianą 7D {st['with_7d']}, 30D {st['with_30d']}"
                        if st["n"] and st["chg24_median"] is not None else "brak coinów"))
    # głębokość historii na darmowym kluczu: po 2 coiny z każdego koszyka (pierwszy i środkowy)
    for st in stats:
        for cid in st["sample"]:
            for days in ("max", "365"):
                try:
                    h = _cg_get(s, f"/coins/{cid}/market_chart", {"vs_currency": "usd", "days": days, "interval": "daily"},
                                sleep, calls)
                    pr, mc = h.get("prices") or [], h.get("market_caps") or []
                    rows.append(row("coingecko", f"historia {cid} ({st['bucket']}, days={days})", "ok" if pr else "brak",
                                    pr[0][0] if pr else None, pr[-1][0] if pr else None, len(pr),
                                    note=f"kapitalizacja w historii: {'tak' if any(x[1] for x in mc) else 'NIE'}"))
                    break
                except Exception as e:  # noqa: BLE001
                    rows.append(err_row("coingecko", f"historia {cid} (days={days})", e))
    pages = last_page
    rows.append(row("coingecko", "koszt w zapytaniach", "ok", n=calls[0],
                    note=f"ta sonda: {calls[0]} zapytań. Zapis listy raz na dobę = {pages} zapytań/dzień ≈ {pages * 30}/miesiąc; "
                         f"co 2 h = {pages * 12}/dzień ≈ {pages * 360}/miesiąc (darmowy klucz: 10 000/miesiąc — sprawdź w panelu CoinGecko)"))
    return rows


# ── DexScreener: narracje („metas”) ──────────────────────────
DS = "https://api.dexscreener.com"


def check_dexscreener(session=None, **_):
    s = session or requests.Session()
    rows = []
    try:
        metas = _get(s, DS + "/metas/trending/v1").json()
        metas = metas if isinstance(metas, list) else (metas.get("metas") or metas.get("data") or [])
    except Exception as e:  # noqa: BLE001
        return [err_row("dexscreener", "trendujące narracje", e)]
    if not metas:
        return [row("dexscreener", "trendujące narracje", "brak")]
    keys = sorted(metas[0].keys())
    rows.append(row("dexscreener", "trendujące narracje", "ok", n=len(metas), note="pola: " + ", ".join(keys)))

    def chg(m):
        c = m.get("marketCapChange")
        return c.get("h24") if isinstance(c, dict) else None
    for m in metas[:8]:
        c24 = chg(m)
        rows.append(row("dexscreener", f"narracja: {str(m.get('name'))[:40]}", "ok", n=m.get("tokenCount"),
                        note=f"kapitalizacja {fmt_usd(_num(m.get('marketCap')))}; płynność {fmt_usd(_num(m.get('liquidity')))}; "
                             f"zmiana kapitalizacji 24h {c24 if c24 is not None else '—'}; obrót {str(m.get('volume'))[:60]}"))
    slug = metas[0].get("slug")
    if slug:
        try:
            one = _get(s, f"{DS}/metas/meta/v1/{slug}").json()
            pairs = one.get("pairs") or []
            rows.append(row("dexscreener", f"skład narracji {slug}", "ok" if pairs else "brak", n=len(pairs),
                            note="pola pary: " + ", ".join(sorted(pairs[0].keys())[:25]) if pairs else "brak par w odpowiedzi"))
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("dexscreener", f"skład narracji {slug}", e))
    return rows


FUNCS.update({"coingecko": check_coingecko, "dexscreener": check_dexscreener})


# ── DefiLlama: sieci (poprawka 47) — tylko przez --only defillama ─────────
# Pytania: czy endpointy odpowiadają z GitHuba, jak długa jest historia dla naszych 8 sieci, czy ostatni dzień
# jest pełny, ile sieci trzeba przejrzeć do reguły „sieć spoza listy nagle rośnie” i jakie progi wychodzą z historii.
LL = "https://api.llama.fi"
LL_ST = "https://stablecoins.llama.fi"
LL_CHAINS = ("Ethereum", "Robinhood Chain", "Solana", "BSC", "TON", "Base", "Tron", "Hyperliquid L1")
LL_CAND_MIN = 20e6        # kandydat do reguły „rośnie”: stablecoiny albo TVL ≥ $20M, albo wolumen DEX 24 h ≥ $1M
LL_CAND_DEX24 = 1e6
LL_MAX_CAND = 80          # najwyżej tyle sieci spoza listy (2 zapytania na sieć)
LL_DEX7_MIN = 10e6        # do rankingu i percentyli: wolumen DEX z 7 dni ≥ $10M
LL_HIST_DAYS = 730        # percentyle z ostatnich 2 lat


def _ll_get(session, url, params, sleep, calls):
    for attempt in range(4):
        calls[0] += 1
        try:
            r = session.get(url, params=params, headers=UA, timeout=90)
        except requests.RequestException as e:
            if attempt == 3:
                raise RuntimeError(f"{type(e).__name__}: {str(e)[:100]}") from e
            sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            sleep(0.4)
            return r.json()
        if r.status_code == 429 or r.status_code >= 500:
            sleep(15 * (attempt + 1))
            continue
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:120]}")
    raise RuntimeError("zbyt wiele odpowiedzi 429 / 5xx")


def _day(t):
    t = int(float(t))
    if t > 1e11:
        t //= 1000
    return t - t % DAY


def ll_points(data, kind):
    """Odpowiedź DefiLlama → {dzień 00:00 UTC: wartość}. kind: dex / fees (totalDataChart), stable, tvl."""
    out = {}
    if kind in ("dex", "fees"):
        for p in (data or {}).get("totalDataChart") or []:
            if isinstance(p, (list, tuple)) and len(p) >= 2 and _num(p[1]) is not None:
                out[_day(p[0])] = _num(p[1])
    elif kind == "stable":
        for p in data or []:
            usd = p.get("totalCirculatingUSD") or {}
            vals = [_num(v) for v in usd.values()] if isinstance(usd, dict) else [_num(usd)]
            vals = [v for v in vals if v is not None]
            if vals and p.get("date") is not None:
                out[_day(p["date"])] = sum(vals)
    elif kind == "tvl":
        for p in data or []:
            if _num(p.get("tvl")) is not None and p.get("date") is not None:
                out[_day(p["date"])] = _num(p["tvl"])
    return out


FLOW = ("dex", "fees")          # przepływy: sumy z okresów; reszta (stable, tvl) to stany: poziom vs poziom


def _sum(pts, a, b):
    """Suma z dni a..b włącznie (brak dnia = 0); None, gdy w oknie nie ma żadnego punktu."""
    vals = [pts[d] for d in range(a, b + 1, DAY) if d in pts]
    return sum(vals) if vals else None


def _at(pts, d, back=3):
    for k in range(back + 1):
        if d - k * DAY in pts:
            return pts[d - k * DAY]
    return None


def _chg(a, b):
    return None if a is None or not b else (a / b - 1) * 100


def ll_change(pts, kind, end):
    """Zmiany na dzień `end`: przepływ — 7 dni vs poprzednie 7 i 30 dni vs poprzednie 30; stan — vs 7 i 30 dni wcześniej.
    Dodatkowo `ratio4w`: przepływ = 7 dni ÷ średni tydzień z poprzednich 4; stan = jak 7D."""
    if kind in FLOW:
        s7, p7 = _sum(pts, end - 6 * DAY, end), _sum(pts, end - 13 * DAY, end - 7 * DAY)
        s30, p30 = _sum(pts, end - 29 * DAY, end), _sum(pts, end - 59 * DAY, end - 30 * DAY)
        p28 = _sum(pts, end - 34 * DAY, end - 7 * DAY)
        return {"v": pts.get(end), "s7": s7, "c7": _chg(s7, p7), "c30": _chg(s30, p30),
                "ratio4w": (s7 / (p28 / 4)) if s7 is not None and p28 else None}
    v = _at(pts, end)
    return {"v": v, "s7": None, "c7": _chg(v, _at(pts, end - 7 * DAY)), "c30": _chg(v, _at(pts, end - 30 * DAY)),
            "ratio4w": None}


def ll_tail(pts, today, n=3):
    """Ostatnie n dni: wartość ÷ mediana 7 dni przed nimi — czy ostatni dzień jest pełny (≈ 1) czy w toku (≪ 1)."""
    days = sorted(pts)[-n:]
    out = []
    for d in days:
        prev = [pts[x] for x in range(d - 7 * DAY, d, DAY) if x in pts]
        med = _median(prev)
        out.append((d, pts[d], (pts[d] / med) if med else None, d >= today))
    return out


def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = min(len(xs) - 1, max(0, int(round(q / 100 * (len(xs) - 1)))))
    return xs[k]


def _fmt_pct(x):
    return "—" if x is None else f"{x:+.1f}%"


def _ll_sum_nested(x):
    if isinstance(x, dict):
        return sum(_ll_sum_nested(v) for v in x.values())
    return _num(x) or 0.0


def ll_breakdown(data):
    """breakdown24h z /overview/dexs: {sieć: {protokół: wartość}} albo {sieć: wartość} → {sieć: suma}."""
    b = (data or {}).get("breakdown24h")
    if not isinstance(b, dict):
        return {}
    return {k: _ll_sum_nested(v) for k, v in b.items()}


def check_defillama(session=None, sleep=time.sleep, now=None, chains=LL_CHAINS, max_cand=LL_MAX_CAND, **_):
    s = session or requests.Session()
    calls = [0]
    now = now or time.time()
    today = _day(now)
    end = today - DAY                     # ostatni pełny dzień UTC
    rows = []
    q = requests.utils.quote

    # 1) listy wszystkich sieci (jedno zapytanie na źródło)
    lists = {}
    for key, url, params in (
            ("dex", LL + "/overview/dexs", {"excludeTotalDataChart": "true", "excludeTotalDataChartBreakdown": "true"}),
            ("fees", LL + "/overview/fees", {"excludeTotalDataChart": "true", "excludeTotalDataChartBreakdown": "true"}),
            ("stable", LL_ST + "/stablecoinchains", None),
            ("tvl", LL + "/v2/chains", None)):
        try:
            lists[key] = _ll_get(s, url, params, sleep, calls)
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("defillama", f"lista sieci: {key}", e))
    names = {}
    if "dex" in lists:
        names["dex"] = set(lists["dex"].get("allChains") or [])
    if "fees" in lists:
        names["fees"] = set(lists["fees"].get("allChains") or [])
    if "stable" in lists:
        names["stable"] = {c.get("name") for c in lists["stable"] or []}
    if "tvl" in lists:
        names["tvl"] = {c.get("name") for c in lists["tvl"] or []}
    dex24 = ll_breakdown(lists.get("dex"))
    for key, ns in names.items():
        miss = [c for c in chains if c not in ns]
        extra = f"; breakdown24h: {len(dex24)} sieci w jednym zapytaniu" if key == "dex" and dex24 else (
            "; breakdown24h: BRAK — wolumen 24 h sieci tylko z zapytań per sieć" if key == "dex" else "")
        rows.append(row("defillama", f"lista sieci: {key}", "ok", n=len(ns),
                        note=("wszystkie nasze sieci są" if not miss else "brak nazw: " + ", ".join(miss)) + extra))
    stable_now = {c.get("name"): _ll_sum_nested(c.get("totalCirculatingUSD") or {}) for c in lists.get("stable") or []}
    tvl_now = {c.get("name"): _num(c.get("tvl")) or 0.0 for c in lists.get("tvl") or []}

    # 2) nasze sieci: pełna historia 4 miar
    ours = {}
    for ch in chains:
        for kind, url, params in (
                ("dex", f"{LL}/overview/dexs/{q(ch)}", {"excludeTotalDataChartBreakdown": "true"}),
                ("fees", f"{LL}/overview/fees/{q(ch)}", {"excludeTotalDataChartBreakdown": "true"}),
                ("stable", f"{LL_ST}/stablecoincharts/{q(ch)}", None),
                ("tvl", f"{LL}/v2/historicalChainTvl/{q(ch)}", None)):
            item = f"{ch}: {kind}"
            try:
                data = _ll_get(s, url, params, sleep, calls)
            except Exception as e:  # noqa: BLE001
                rows.append(err_row("defillama", item, e))
                continue
            pts = ll_points(data, kind)
            if not pts:
                rows.append(row("defillama", item, "brak", note="pusta historia"))
                continue
            ours[(ch, kind)] = pts
            c = ll_change(pts, kind, end)
            tail = "; ".join(f"{iso(d)[5:]} {fmt_usd(v)}" + (f" (×{r:.2f} mediany 7 dni)" if r is not None else "")
                             + (" — dzień w toku" if live else "") for d, v, r, live in ll_tail(pts, today))
            gaps = sum(1 for d in range(min(pts), max(pts), DAY) if d not in pts)
            lfd = f"; totalLastFullDay {fmt_usd(_num(data.get('totalLastFullDay')))}" if (
                kind in FLOW and isinstance(data, dict) and data.get("totalLastFullDay") is not None) else ""
            what = "7 dni vs poprzednie 7" if kind in FLOW else "vs 7 dni wcześniej"
            rows.append(row("defillama", item, "ok", min(pts), max(pts), len(pts),
                            note=f"{iso(end)[5:]}: {fmt_usd(c['v'])}; {what} {_fmt_pct(c['c7'])}; 30D {_fmt_pct(c['c30'])}"
                                 f"{lfd}; luki {gaps} dni; ostatnie dni: {tail}"))

    # 3) udział naszych sieci w stablecoinach (stan teraz)
    tot = sum(stable_now.values())
    if tot:
        sh = sorted(((stable_now.get(ch, 0.0), ch) for ch in chains), reverse=True)
        rest = tot - sum(v for v, _ in sh)
        rows.append(row("defillama", "udział w stablecoinach (teraz)", "ok", n=len(stable_now),
                        note=", ".join(f"{ch} {v / tot * 100:.1f}%" for v, ch in sh)
                             + f", reszta {rest / tot * 100:.1f}% (razem {fmt_usd(tot)})"))

    # 4) kandydaci do reguły „rośnie”: sieci spoza listy z kapitałem albo ruchem
    every = set(stable_now) | set(tvl_now) | set(dex24)
    cand = [c for c in every if c and c not in chains and (
        stable_now.get(c, 0) >= LL_CAND_MIN or tvl_now.get(c, 0) >= LL_CAND_MIN or dex24.get(c, 0) >= LL_CAND_DEX24)]
    cand.sort(key=lambda c: -max(stable_now.get(c, 0), tvl_now.get(c, 0), dex24.get(c, 0) * 30))
    rows.append(row("defillama", "kandydaci do reguły „rośnie”", "ok", n=len(cand),
                    note=f"sieci spoza listy ze stablecoinami albo TVL ≥ {fmt_usd(LL_CAND_MIN)} albo DEX 24 h ≥ "
                         f"{fmt_usd(LL_CAND_DEX24)} (z {len(every)} wszystkich); sprawdzane w sondzie: {min(len(cand), max_cand)}"))
    hist = {"dex": [], "stable": []}
    now_rank = {"dex": [], "stable": []}
    fails = []
    pool = [(ch, True) for ch in chains] + [(c, False) for c in cand[:max_cand]]
    for ch, mine in pool:
        for kind in ("dex", "stable"):
            pts = ours.get((ch, kind))
            if pts is None and not mine:
                url = (f"{LL}/overview/dexs/{q(ch)}" if kind == "dex" else f"{LL_ST}/stablecoincharts/{q(ch)}")
                try:
                    pts = ll_points(_ll_get(s, url, {"excludeTotalDataChartBreakdown": "true"} if kind == "dex" else None,
                                            sleep, calls), kind)
                except Exception:  # noqa: BLE001
                    fails.append(f"{ch} ({kind})")
                    continue
            if not pts:
                continue
            # historia: każdy dzień z ostatnich 2 lat, gdy sieć była dość duża
            for d in range(end - LL_HIST_DAYS * DAY, end + DAY, DAY):
                if kind == "dex":
                    c = ll_change(pts, "dex", d)
                    if c["s7"] is not None and c["s7"] >= LL_DEX7_MIN and c["ratio4w"] is not None:
                        hist["dex"].append(c["ratio4w"])
                elif d in pts and pts[d] >= LL_CAND_MIN:
                    c = ll_change(pts, "stable", d)
                    if c["c30"] is not None:
                        hist["stable"].append(c["c30"])
            c = ll_change(pts, kind, end)
            if kind == "dex" and c["s7"] is not None and c["s7"] >= LL_DEX7_MIN and c["ratio4w"] is not None:
                now_rank["dex"].append((c["ratio4w"], ch, mine, c["s7"]))
            if kind == "stable" and c["v"] is not None and c["v"] >= LL_CAND_MIN and c["c30"] is not None:
                now_rank["stable"].append((c["c30"], ch, mine, c["v"]))
    if fails:
        rows.append(row("defillama", "kandydaci: nieudane zapytania", "błąd", n=len(fails), note=", ".join(fails[:25])))
    if hist["dex"]:
        h = hist["dex"]
        rows.append(row("defillama", "historia: DEX 7 dni ÷ średni tydzień z 4 poprzednich", "ok", n=len(h),
                        note=f"dni-sieci z wolumenem 7 dni ≥ {fmt_usd(LL_DEX7_MIN)}, ostatnie {LL_HIST_DAYS} dni: "
                             + ", ".join(f"p{p} ×{_pct(h, p):.2f}" for p in (50, 90, 95, 99))))
    if hist["stable"]:
        h = hist["stable"]
        rows.append(row("defillama", "historia: stablecoiny 30D", "ok", n=len(h),
                        note=f"dni-sieci ze stablecoinami ≥ {fmt_usd(LL_CAND_MIN)}, ostatnie {LL_HIST_DAYS} dni: "
                             + ", ".join(f"p{p} {_pct(h, p):+.1f}%" for p in (50, 90, 95, 99))))
    for r_, ch, mine, size in sorted(now_rank["dex"], reverse=True)[:12]:
        rows.append(row("defillama", f"teraz DEX rośnie: {ch}{' (nasza)' if mine else ''}", "ok",
                        note=f"7 dni {fmt_usd(size)}; ×{r_:.2f} średniego tygodnia z 4 poprzednich"))
    for c30, ch, mine, size in sorted(now_rank["stable"], reverse=True)[:12]:
        rows.append(row("defillama", f"teraz stablecoiny rosną: {ch}{' (nasza)' if mine else ''}", "ok",
                        note=f"{fmt_usd(size)}; 30D {_fmt_pct(c30)}"))
    rows.append(row("defillama", "koszt w zapytaniach", "ok", n=calls[0],
                    note=f"ta sonda: {calls[0]} zapytań; w produkcji raz na dobę: 4 listy + 4 × {len(chains)} naszych sieci "
                         f"+ 2 × kandydaci (bez klucza)"))
    return rows


FUNCS.update({"defillama": check_defillama})


def run(where, only=None, funcs=None, now=None):
    funcs = funcs or FUNCS
    rows = []
    t0 = time.time()
    for name in (only or CHECKS[where]):
        log.info("Sprawdzam: %s", name)
        t = time.time()
        try:
            got = funcs[name]()
        except Exception as e:  # noqa: BLE001
            got = [err_row(name, "całe źródło", e)]
        log.info("  %s: %d wierszy, %.0f s", name, len(got), time.time() - t)
        rows += got
    return {"where": where, "at": datetime.fromtimestamp(now or time.time(), timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"), "seconds": round(time.time() - t0), "rows": rows}


def to_markdown(res):
    out = [f"# Sonda historii — {res['where']} — {res['at']}", "",
           f"Czas: {res['seconds']} s. „Od” / „do” = pierwszy i ostatni dzień danych w źródle.", "",
           "| Źródło | Co | Stan | Od | Do | Punkty | Uwagi |", "|---|---|---|---|---|---|---|"]
    for r in res["rows"]:
        out.append("| " + " | ".join(str(x if x is not None else "") .replace("|", "/") for x in (
            r["source"], r["item"], r["status"], r["first"], r["last"], r["n"], r["note"])) + " |")
    return "\n".join(out) + "\n"


def save(res, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "probe.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "probe.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(res))


def publish(out_dir, where, token_file="~/.scanner_token", repo="cryptoloser8-coder/scanner"):
    with open(os.path.expanduser(token_file), encoding="utf-8") as f:
        tok = f.read().strip()
    remote = f"https://x-access-token:{tok}@github.com/{repo}.git"
    env = dict(os.environ, DATA_BRANCH=f"probe-{where}", GIT_AUTHOR_NAME="probe-bot",
               GIT_AUTHOR_EMAIL="probe-bot@users.noreply.github.com")
    r = subprocess.run(["bash", os.path.join(HERE, "publish.sh"), out_dir, remote], env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).replace(tok, "<token>")[-400:])
    return f"https://raw.githubusercontent.com/{repo}/probe-{where}/probe.md"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("where", choices=sorted(CHECKS))
    ap.add_argument("--only", nargs="*", choices=sorted(FUNCS))
    ap.add_argument("--out", default=None)
    ap.add_argument("--publish", action="store_true", help="opublikuj wynik na gałęzi probe-<where> (Pi)")
    ap.add_argument("--token-file", default="~/.scanner_token")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    res = run(a.where, a.only)
    out = a.out or tempfile.mkdtemp(prefix="probe-")
    save(res, out)
    print(to_markdown(res))
    if a.publish:
        print("Opublikowano:", publish(out, a.where, a.token_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
