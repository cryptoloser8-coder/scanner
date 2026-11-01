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
  bitmex      — funding XBTUSD/ETHUSD (od 2016?),
  binance     — funding perpetuali BTCUSDT/ETHUSDT (od 2019?), tylko z Pi,
  vision      — archiwum data.binance.vision: dzienne metryki futures (OI, long/short) i lista par spot
                (także zdelistowanych — szerokość rynku bez błędu przeżywalności).
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
CHECKS = {
    "github": ("coinalyze", "tradingview", "coinmetrics", "bitmex", "binance", "vision"),
    "pi": ("binance", "vision", "bitmex", "coinmetrics"),
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


# ── BitMEX ───────────────────────────────────────────────────
def check_bitmex(session=None, **_):
    s = session or requests.Session()
    rows = []
    for sym in ("XBTUSD", "ETHUSD"):
        try:
            first = _get(s, "https://www.bitmex.com/api/v1/funding",
                         params={"symbol": sym, "count": 1, "reverse": "false"}).json()
            last = _get(s, "https://www.bitmex.com/api/v1/funding",
                        params={"symbol": sym, "count": 1, "reverse": "true"}).json()
            if not first:
                rows.append(row("bitmex", f"funding {sym}", "brak"))
                continue
            rows.append(row("bitmex", f"funding {sym}", "ok", first[0]["timestamp"],
                            last[0]["timestamp"] if last else None,
                            note=f"okres {first[0].get('fundingInterval', '?')}; pierwsza stawka {first[0].get('fundingRate')}"))
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("bitmex", f"funding {sym}", e))
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


FUNCS = {"coinalyze": check_coinalyze, "tradingview": check_tradingview, "coinmetrics": check_coinmetrics,
         "bitmex": check_bitmex, "binance": check_binance, "vision": check_vision}


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
