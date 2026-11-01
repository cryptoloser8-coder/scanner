"""Szerokość rynku bez błędu przeżywalności: dzienne zamknięcia par */USDT wycofanych z Binance.

Jednorazowo na Orange Pi (ok. 15–30 min, EMA i alerty działają w tym czasie normalnie):
    python3 ~/scanner/collector/delisted.py

Pobiera z archiwum data.binance.vision (miesięczne + ostatnie dzienne pliki świec 1d) wszystkie pary
*/USDT, których dziś nie ma na liście ema_monitor (wycofane z giełdy), z tymi samymi filtrami
(bez stablecoinów, fiat, złota, tokenów z dźwignią i opakowanych kopii), i zapisuje je do
~/.ema-monitor/delisted.json. ema_monitor.py przy najbliższym przebiegu przelicza szerokość rynku
z nimi (coin liczy się w dniach, w których był notowany i miał już ≥ min_days historii).
Pary wycofane w przyszłości ema_monitor sam przenosi do delisted.json (nie kasuje ich historii).

Ograniczenie: symbol użyty ponownie dla innego coina (np. LUNAUSDT po 05.2022) — liczy się tylko
obecny coin (stara historia pod tym samym symbolem nie jest dołączana).
"""
import argparse
import csv
import fcntl
import io
import json
import logging
import os
import re
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ema_monitor as E  # noqa: E402

log = logging.getLogger("delisted")
DAY = 86400
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL = "https://data.binance.vision/"
KEY_RE = re.compile(r"<Key>([^<]+)</Key>")
PREFIX_RE = re.compile(r"<Prefix>([^<]+)</Prefix>")
TRUNC_RE = re.compile(r"<IsTruncated>true</IsTruncated>")
NEXT_RE = re.compile(r"<NextMarker>([^<]+)</NextMarker>")
LOCK = "/tmp/ema-monitor.lock"


def s3_list(session, prefix, delimiter=None, max_pages=50):
    keys, prefixes, marker = [], [], None
    for _ in range(max_pages):
        params = {"prefix": prefix}
        if delimiter:
            params["delimiter"] = delimiter
        if marker:
            params["marker"] = marker
        r = session.get(S3, params=params, timeout=60)
        r.raise_for_status()
        k = KEY_RE.findall(r.text)
        p = [x for x in PREFIX_RE.findall(r.text) if x != prefix]
        keys += k
        prefixes += p
        if not TRUNC_RE.search(r.text):
            break
        nm = NEXT_RE.search(r.text)
        marker = nm.group(1) if nm else ((k or p or [None])[-1])
        if not marker:
            break
    return keys, prefixes


def archive_symbols(session):
    _, pref = s3_list(session, "data/spot/monthly/klines/", delimiter="/")
    return sorted({p.rstrip("/").rsplit("/", 1)[-1] for p in pref})


def candidates(all_symbols, current, cfg):
    """Archive symbols → {symbol: base} for */quote pairs not trading today, after the EMA filters."""
    quote = cfg["quote"]
    excl = E.ALWAYS_EXCLUDE | {e.upper() for e in cfg.get("exclude") or []}
    bases = {s[:-len(quote)] for s in all_symbols if s.endswith(quote)}
    out = {}
    for s in all_symbols:
        if not s.endswith(quote) or s in current:
            continue
        b = s[:-len(quote)]
        if not b or b in excl:
            continue
        if any(b.endswith(x) and b[:-len(x)] in bases for x in E.LEVERAGED):
            continue
        out[s] = b
    return out


def _t_seconds(v):
    t = int(float(v))
    if t > 10 ** 14:          # od 2025 archiwum spot podaje czas w mikrosekundach
        t //= 1000
    return t // 1000


def parse_klines(content):
    """Kline ZIP (CSV, without header) → {day_t: close}."""
    z = zipfile.ZipFile(io.BytesIO(content))
    out = {}
    with z.open(z.namelist()[0]) as f:
        for row in csv.reader(io.TextIOWrapper(f, "utf-8")):
            if not row or not row[0].strip().lstrip("-").isdigit():
                continue                                   # nagłówek (część plików go ma)
            t = _t_seconds(row[0])
            out[t - t % DAY] = float(row[4])
    return out


def symbol_closes(session, sym):
    """All daily closes of one symbol: monthly files + daily files after the last full month."""
    keys, _ = s3_list(session, f"data/spot/monthly/klines/{sym}/1d/")
    monthly = sorted(k for k in keys if k.endswith(".zip"))
    closes = {}
    for k in monthly:
        r = session.get(DL + k, timeout=60)
        r.raise_for_status()
        closes.update(parse_klines(r.content))
    dkeys, _ = s3_list(session, f"data/spot/daily/klines/{sym}/1d/")
    last_m = monthly[-1][-11:-4] if monthly else ""          # "YYYY-MM"
    for k in sorted(x for x in dkeys if x.endswith(".zip")):
        if k[-14:-7] > last_m:                               # "YYYY-MM" z "…-YYYY-MM-DD.zip"
            r = session.get(DL + k, timeout=60)
            r.raise_for_status()
            closes.update(parse_klines(r.content))
    return [[t, c] for t, c in sorted(closes.items())]


def merge_into(path, new, lock=LOCK):
    """Merge {symbol: {"b": base, "c": [[t, close]...]}} into delisted.json under the cron lock (short)."""
    with open(lock, "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            cur = E._read(path, {})
            for sym, rec in new.items():
                old = cur.get(sym) or {}
                d = {t: c for t, c in old.get("c") or []}
                d.update({t: c for t, c in rec["c"]})
                cur[sym] = {"b": rec["b"], "c": [[t, c] for t, c in sorted(d.items())],
                            "src": old.get("src") or rec.get("src")}
            d = os.path.dirname(path) or "."
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cur, f, separators=(",", ":"))
            os.replace(tmp, path)
            return cur
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def run(state_dir, cfg, session=None, workers=6, lock=LOCK):
    s = session or requests.Session()
    st = E._read(os.path.join(state_dir, "state.json"), {})
    current = set(st.get("symbols") or {})
    if not current:
        raise RuntimeError("brak listy par w ~/.ema-monitor/state.json — najpierw musi zadziałać ema_monitor")
    t0 = time.time()
    syms = archive_symbols(s)
    cand = candidates(syms, current, cfg)
    log.info("Archiwum: %d par, wycofane */%s po filtrach: %d", len(syms), cfg["quote"], len(cand))
    new, failed = {}, []

    def one(sym):
        try:
            return sym, symbol_closes(s, sym), None
        except Exception as e:  # noqa: BLE001
            return sym, None, f"{type(e).__name__}: {e}"
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (sym, closes, err) in enumerate(ex.map(one, sorted(cand)), 1):
            if err:
                failed.append(f"{sym}: {err}"[:200])
            elif closes:
                new[sym] = {"b": cand[sym], "c": closes, "src": "archiwum"}
            if i % 25 == 0:
                log.info("  %d/%d par", i, len(cand))
    path = os.path.join(state_dir, "delisted.json")
    allrec = merge_into(path, new, lock=lock)
    min_days = int(cfg["min_days"])
    usable = sum(1 for r in allrec.values() if len(r.get("c") or []) >= min_days)
    return {"archive_symbols": len(syms), "candidates": len(cand), "downloaded": len(new),
            "failed": failed, "total": len(allrec), "usable_min_days": usable,
            "minutes": round((time.time() - t0) / 60, 1)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--state", default=os.path.expanduser("~/.ema-monitor"))
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    res = run(a.state, E.load_cfg(a.config), workers=a.workers)
    print(f"Gotowe w {res['minutes']} min: w archiwum {res['archive_symbols']} par, wycofanych po filtrach "
          f"{res['candidates']}, pobrano {res['downloaded']}, nieudane {len(res['failed'])}.")
    print(f"W delisted.json: {res['total']} par, z co najmniej {E.load_cfg(a.config)['min_days']} dniami "
          f"historii (liczą się do szerokości): {res['usable_min_days']}.")
    for f in res["failed"][:20]:
        print("  nieudane:", f)
    print("Szerokość rynku przeliczy się przy najbliższym przebiegu ema_monitor (do 5 min).")
    return 0 if not res["failed"] or res["downloaded"] else 1


if __name__ == "__main__":
    sys.exit(main())
