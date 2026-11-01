"""Wydłużenie historii serii, które już mamy (poprawka 28). Uruchamiane w każdym skanie (main.run),
ale pobiera tylko to, czego brakuje — po pierwszym razie to kilka sekund.

1. Cena BTC/ETH (px_btc, px_eth w liq_1d.json) przed startem Coinalyze (03.2020):
   dzienne zamknięcia indeksu TradingView (INDEX:BTCUSD od 2009, INDEX:ETHUSD od 2015).
2. Funding BTC/ETH (fund_btc, fund_eth) przed startem OI w Coinalyze (22.09.2022):
   dzienny funding z Coinalyze (Binance od 01.2020, OKX/Bybit/Deribit od 03–04.2020),
   średnia z wagami STAŁYMI = udziały rynków w OI z pierwszych 30 dni danych OI
   (wcześniej nie ma dziennego OI giełd, więc nie da się ważyć jak dziś).
3. OI Binance (oi_btc_binance, oi_eth_binance w 1d.json): archiwum data.binance.vision —
   dzienne pliki metryk perpetuali USDT-M (BTCUSDT od 09.2020, ETHUSDT od 12.2021), wartość
   z ostatniego odczytu dnia (23:55 UTC), w USD. Osobne serie — nie mieszamy z sumą wszystkich giełd.
   Pierwsze pobranie ~4000 małych plików (~60 MB, kilkanaście minut), potem 1 plik dziennie na parę.

Ustawienia: config.yaml → `history:`. Stan: state.json → `history`.
"""
import csv
import io
import logging
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

import liquidations as L
import series as S

log = logging.getLogger("history")
DAY = S.DAY
RETRY_HOURS = 20                 # nieudana / niepełna próba → ponownie najwcześniej po tylu godzinach

DEFAULTS = {
    "enabled": True,
    "price_symbols": {"px_btc": "INDEX:BTCUSD", "px_eth": "INDEX:ETHUSD"},
    "funding_groups": ["btc", "eth"],
    "funding_start": "2019-01-01",
    "funding_weight_days": 30,
    "vision_oi": {"oi_btc_binance": "BTCUSDT", "oi_eth_binance": "ETHUSDT"},
    "vision_workers": 8,
    "vision_max_minutes": 25,
}
VISION_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
VISION_DL = "https://data.binance.vision/"
KEY_RE = re.compile(r"<Key>([^<]+)</Key>")
TRUNC_RE = re.compile(r"<IsTruncated>true</IsTruncated>")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.zip$")


def floor(t, step):
    return int(t) - int(t) % step


def day_of(iso):
    return int(datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def iso(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d")


def hcfg(cfg):
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (cfg.get("history") or {}).items() if v is not None})
    return out


def _due(hst, key, now):
    last = (hst.get(key) or {}).get("tried", 0)
    return now - last >= RETRY_HOURS * 3600


# ── 1. cena ──────────────────────────────────────────────────
def extend_prices(store, tv, cfg, now):
    """Prepend daily closes from TradingView before the first stored point (never overwrites)."""
    hst = store.state.setdefault("history", {})
    info = {}
    for sid, symbol in (hcfg(cfg)["price_symbols"] or {}).items():
        key = f"price:{sid}"
        cur = store.series["1d"].get(sid) or {}
        if not cur:
            continue                                    # brak danych z Coinalyze — nie mamy do czego doklejać
        first = min(cur)
        rec = hst.get(key) or {}
        done = rec.get("src_first") is not None
        if done and first <= rec["src_first"]:
            continue                                    # już wydłużone
        if not done and not _due(hst, key, now):
            continue                                    # nieudana próba niedawno — spróbujemy później
        # done i first > src_first = wydłużenie zniknęło (np. pełne przeliczenie) → od razu ponownie
        rec["tried"] = now
        hst[key] = rec
        bars = tv.bars(symbol, "1D", 20000)
        pts = {floor(t, DAY): v for t, v in bars if floor(t, DAY) < first}
        store.put("1d", sid, pts)
        rec["src_first"] = min(pts) if pts else first
        rec["symbol"] = symbol
        info[sid] = f"+{len(pts)} dni od {iso(rec['src_first'])} ({symbol})"
        log.info("Historia %s: %s", sid, info[sid])
    return info


# ── 2. funding ───────────────────────────────────────────────
def fixed_weights(oi_hist, start, days):
    """Mean daily OI (USD) per symbol over [start, start + days) → {symbol: weight}."""
    end = start + days * DAY
    out = {}
    for sym, h in (oi_hist or {}).items():
        vals = [v for t, v in h.items() if start <= t < end and v]
        if vals:
            out[sym] = sum(vals) / len(vals)
    return out


def extend_funding(client, store, cfg, now):
    """fund_btc / fund_eth before the first daily OI day, OI-share weights fixed from the first month."""
    h = hcfg(cfg)
    st = store.state
    hst = st.setdefault("history", {})
    oi_d = store.series["1d"].get("oi_total") or {}
    uni = st.get("universe")
    unit = st.get("liq_funding_unit")
    if not oi_d or not uni or not uni.get("symbols") or not unit:
        return {}
    cut = min(oi_d)
    groups_wanted = [g for g in h["funding_groups"] if g in ("btc", "eth")]
    todo = [g for g in groups_wanted
            if min(store.series["1d"].get(f"fund_{g}") or {cut: 0}) >= cut]
    done_before = any(((hst.get("funding") or {}).get(g) or {}).get("from") for g in todo)
    if not todo or (not done_before and not _due(hst, "funding", now)):
        return {}                                       # gotowe albo nieudana próba niedawno
    hst["funding"] = rec = dict(hst.get("funding") or {}, tried=now)

    lcfg = cfg.get("liquidations") or {}
    watch = [w.upper() for w in cfg.get("watchlist") or []]
    sym_base, others, _ = L.liq_universe(uni, st, lcfg, watch)
    groups = {g: syms for g, syms in L.group_members(sym_base, others, watch).items() if g in todo}
    symbols = sorted(set().union(*groups.values())) if groups else []
    if not symbols:
        return {}
    wanted = (cfg.get("coinalyze") or {}).get("exchanges") or []
    names = L.canon_names((st.get("liq_exchanges") or {}).get("names") or {}, wanted)

    d0 = day_of(str(h["funding_start"]))
    wdays = int(h["funding_weight_days"])
    from probe import history_all                       # odporne na obcięte odpowiedzi (≥ 1500 punktów)
    fd = {sym: {t: v for t, v in hh.items() if d0 <= t < cut}
          for sym, hh in history_all(client, "/funding-rate-history", symbols, "c", False, cut - 1).items()}
    od = client.oi_history(symbols, "daily", cut, cut + wdays * DAY)
    w = fixed_weights(od, cut, wdays)
    days = list(range(floor(d0, DAY), cut, DAY))
    agg = L.aggregate_funding(fd, lambda sym, t: w.get(sym), groups, days, DAY, names, lcfg, unit)
    info = {}
    for g in todo:
        pts = {t: v for t, v in (agg.get(f"fund_{g}") or {}).items() if t < cut}
        store.put("1d", f"fund_{g}", pts)
        tot = sum(w.get(s, 0) for s in groups[g]) or 1
        shares = {}
        for s in groups[g]:
            if w.get(s):
                ex = names.get(L.ex_code(s), L.ex_code(s))
                shares[ex] = shares.get(ex, 0) + w[s] / tot * 100
        rec[g] = {"from": iso(min(pts)) if pts else None, "until": iso(cut), "days": len(pts),
                  "weights_pct": {k: round(v, 1) for k, v in sorted(shares.items(), key=lambda x: -x[1])}}
        info[f"fund_{g}"] = f"+{len(pts)} dni" + (f" od {rec[g]['from']}" if pts else "")
        log.info("Historia fund_%s: %s, wagi stałe %s", g, info[f"fund_{g}"], rec[g]["weights_pct"])
    return info


# ── 3. OI Binance z archiwum data.binance.vision ─────────────
def vision_days(session, symbol, max_pages=20):
    """→ sorted list of day timestamps that have a metrics file in the archive."""
    prefix = f"data/futures/um/daily/metrics/{symbol}/"
    keys, marker = [], None
    for _ in range(max_pages):
        params = {"prefix": prefix}
        if marker:
            params["marker"] = marker
        r = session.get(VISION_S3, params=params, timeout=60)
        r.raise_for_status()
        k = KEY_RE.findall(r.text)
        keys += k
        if not TRUNC_RE.search(r.text) or not k:
            break
        marker = k[-1]
    out = set()
    for k in keys:
        m = DATE_RE.search(k)
        if m:
            out.add(day_of(m.group(1)))
    return sorted(out)


def parse_metrics(content):
    """Daily metrics ZIP → (last create_time, sum_open_interest_value in USD) or None."""
    z = zipfile.ZipFile(io.BytesIO(content))
    with z.open(z.namelist()[0]) as f:
        rows = list(csv.DictReader(io.TextIOWrapper(f, "utf-8")))
    best = None
    for r in rows:
        try:
            v = float(r["sum_open_interest_value"])
        except (KeyError, TypeError, ValueError):
            continue
        ct = r.get("create_time") or ""
        if v > 0 and (best is None or ct >= best[0]):
            best = (ct, v)
    return best


def fetch_metrics_day(session, symbol, t):
    d = iso(t)
    url = f"{VISION_DL}data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{d}.zip"
    r = session.get(url, timeout=60)
    if r.status_code == 404:
        return t, None, "404"
    r.raise_for_status()
    got = parse_metrics(r.content)
    return t, (got[1] if got else None), None


def collect_vision(store, cfg, now, session=None, clock=time.time):
    """Fill oi_<coin>_binance daily series from the archive (only missing days)."""
    h = hcfg(cfg)
    s = session or requests.Session()
    hst = store.state.setdefault("history", {})
    vst = hst.setdefault("vision", {})
    today = floor(now, DAY)
    deadline = clock() + float(h["vision_max_minutes"]) * 60
    info = {}
    for sid, symbol in (h["vision_oi"] or {}).items():
        rec = vst.setdefault(symbol, {})
        have = store.series["1d"].get(sid) or {}
        bad = set(rec.get("missing") or [])
        # lista plików archiwum: raz na dobę (nowy plik dochodzi raz dziennie)
        if not rec.get("days_at") or now - rec["days_at"] >= 20 * 3600 or not rec.get("first"):
            avail = vision_days(s, symbol)
            rec["days_at"] = now
            rec["first"] = avail[0] if avail else None
            rec["last"] = avail[-1] if avail else None
            todo = [t for t in avail if t not in have and t not in bad and t < today]
        else:
            last = max(have) if have else ((rec.get("first") or today) - DAY)
            todo = [t for t in range(last + DAY, today, DAY) if t not in bad]
        if not todo:
            info[sid] = f"{len(have)} dni, bez braków"
            continue
        got, errors = 0, 0
        with ThreadPoolExecutor(max_workers=int(h["vision_workers"])) as ex:
            for i in range(0, len(todo), 200):
                if clock() > deadline:
                    break
                chunk = todo[i:i + 200]
                for t, v, err in ex.map(lambda t: _safe_fetch(s, symbol, t), chunk):
                    if v is not None:
                        store.put("1d", sid, {t: v})
                        got += 1
                    elif err == "404" and t < today - 3 * DAY:
                        bad.add(t)                      # dziura w archiwum — nie pytamy co skan
                    elif err and err != "404":
                        errors += 1
        rec["missing"] = sorted(bad)[-400:]
        n = len(store.series["1d"].get(sid) or {})
        info[sid] = f"+{got} dni (razem {n})" + (f", błędy {errors}" if errors else "") + \
            (" — przerwane limitem czasu, dokończy następny skan" if clock() > deadline else "")
        log.info("Archiwum Binance %s (%s): %s", sid, symbol, info[sid])
        if errors and not got:
            raise RuntimeError(f"{symbol}: {errors} nieudanych pobrań z data.binance.vision")
    return info


def _safe_fetch(session, symbol, t):
    try:
        return fetch_metrics_day(session, symbol, t)
    except Exception as e:  # noqa: BLE001
        return t, None, f"{type(e).__name__}: {e}"


# ── całość ───────────────────────────────────────────────────
def extend_all(store, cfg, now, client=None, tv=None, session=None):
    """→ (info, errors). Każda część osobno — awaria jednej nie blokuje pozostałych."""
    h = hcfg(cfg)
    if not h.get("enabled", True):
        return {}, {}
    info, errors = {}, {}
    if tv is not None:
        try:
            info.update(extend_prices(store, tv, cfg, now))
        except Exception as e:  # noqa: BLE001
            log.exception("Historia cen")
            errors["ceny (TradingView INDEX)"] = str(e)
    if client is not None:
        try:
            info.update(extend_funding(client, store, cfg, now))
        except Exception as e:  # noqa: BLE001
            log.exception("Historia fundingu")
            errors["funding przed 09.2022"] = str(e)
    if h.get("vision_oi"):
        try:
            info.update(collect_vision(store, cfg, now, session))
        except Exception as e:  # noqa: BLE001
            log.exception("Archiwum Binance")
            errors["archiwum Binance"] = str(e)
    return info, errors
