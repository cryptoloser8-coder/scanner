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
4. Knoty dzienne ceny (px_*_hi / _lo) dla dni z zamknięciem z TradingView INDEX (poprawka 56): high / low
   z tego samego źródła co zamknięcie (BTC od 2010, ETH od 2015); dni z zamknięciem z Coinalyze bez zmian.
5. Świece 1h BTC/ETH od 08.2017 (poprawka 56): archiwum Binance spot (data.binance.vision, klines 1h —
   pliki miesięczne, potem dzienne) → osobne pliki px_1h_<coin>.json (zamknięcie, high, low co godzinę),
   ładowane przez strony tylko na wykresie 1H/4H. Pierwsze pobranie ~110 plików na parę, potem 1 dziennie.

Ustawienia: config.yaml → `history:`. Stan: state.json → `history`.
"""
import csv
import io
import json
import logging
import os
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
    "spot_1h": {"px_btc": "BTCUSDT", "px_eth": "ETHUSDT"},
    "spot_1h_start": "2017-08-01",
    "spot_1h_max_minutes": 10,
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


# ── 1b. knoty dzienne z TradingView INDEX ────────────────────
WICK_TOL = 0.0005            # zamknięcie w danych = zamknięcie INDEX (± 0,05%) → dzień z TradingView


def extend_wicks(store, tv, cfg, now):
    """High / low dla dni, których zamknięcie pochodzi z TradingView INDEX (wydłużona historia ceny).
    Raz; ponownie, gdy wydłużenie zniknie (np. pełne przeliczenie likwidacji) albo po nieudanej próbie."""
    if not hasattr(tv, "ohlc_bars"):
        return {}
    hst = store.state.setdefault("history", {})
    info = {}
    for sid, symbol in (hcfg(cfg)["price_symbols"] or {}).items():
        close = store.series["1d"].get(sid) or {}
        hi_now = store.series["1d"].get(sid + "_hi") or {}
        if not close:
            continue
        key = f"wick:{sid}"
        rec = hst.get(key) or {}
        if rec.get("first") is not None and hi_now and min(hi_now) <= rec["first"]:
            continue                                    # już zrobione
        if not _due(hst, key, now):
            continue
        rec["tried"] = now
        hst[key] = rec
        his, los = {}, {}
        for t, bar in tv.ohlc_bars(symbol, "1D", 20000):
            d = floor(t, DAY)
            c_have = close.get(d)
            _, h, l_, c = bar
            if c_have is None or not c or abs(c_have / c - 1) > WICK_TOL:
                continue                                # dzień z zamknięciem z innego źródła (Coinalyze) — bez zmian
            his[d], los[d] = max(h, c_have), min(l_, c_have)
        store.put("1d", sid + "_hi", his)
        store.put("1d", sid + "_lo", los)
        rec["first"] = min(his) if his else None
        info[sid + "_knoty"] = f"{len(his)} dni z {symbol}" + (f" od {iso(min(his))}" if his else "")
        log.info("Knoty %s: %s", sid, info[sid + "_knoty"])
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


# ── 5. świece 1h z archiwum Binance spot ─────────────────────
HOUR = 3600
KLINE_URL = VISION_DL + "data/spot/{per}/klines/{sym}/1h/{sym}-1h-{date}.zip"


def parse_klines(content):
    """ZIP z klines Binance → {t_open_s: (high, low, close)}; czas w ms, a od 2025 w µs."""
    z = zipfile.ZipFile(io.BytesIO(content))
    out = {}
    with z.open(z.namelist()[0]) as f:
        for row in csv.reader(io.TextIOWrapper(f, "utf-8")):
            try:
                ot = int(row[0])
                h, l_, c = float(row[2]), float(row[3]), float(row[4])
            except (ValueError, IndexError):
                continue                                # nagłówek albo pusty wiersz
            out[ot // 1_000_000 if ot > 10 ** 14 else ot // 1000] = (h, l_, c)
    return out


def px1h_path(data_dir, sid):
    return os.path.join(data_dir, f"px_1h_{sid[3:]}.json")


def load_px1h(path):
    """→ ({t: (high, low, close)}, missing_days)."""
    try:
        with open(path, encoding="utf-8") as f:
            o = json.load(f)
    except (OSError, ValueError):
        return {}, []
    t0, step = int(o.get("t0") or 0), int(o.get("step") or HOUR)
    out = {}
    for i, (h, l_, c) in enumerate(zip(o.get("h") or [], o.get("l") or [], o.get("c") or [])):
        if c is not None:
            out[t0 + i * step] = (h, l_, c)
    return out, list(o.get("missing") or [])


def save_px1h(path, bars, symbol, now, missing):
    r8 = lambda v: float(f"{v:.8g}")                    # noqa: E731
    ts = sorted(bars)
    t0, n = ts[0], (ts[-1] - ts[0]) // HOUR + 1
    cols = {"h": [None] * n, "l": [None] * n, "c": [None] * n}
    for t in ts:
        i = (t - t0) // HOUR
        cols["h"][i], cols["l"][i], cols["c"][i] = (r8(x) for x in bars[t])
    obj = {"updated": now, "symbol": symbol, "source": "Binance spot (data.binance.vision), klines 1h",
           "step": HOUR, "t0": t0, "last": ts[-1], "missing": missing[-200:], **cols}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def _month_start(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return int(datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp())


def _next_month(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())


def _fetch_kline(session, symbol, per, date):
    try:
        r = session.get(KLINE_URL.format(per=per, sym=symbol, date=date), timeout=60)
        if r.status_code == 404:
            return per, date, None, "404"
        r.raise_for_status()
        return per, date, parse_klines(r.content), None
    except Exception as e:  # noqa: BLE001
        return per, date, None, f"{type(e).__name__}: {e}"


def collect_spot_1h(data_dir, cfg, now, session=None, clock=time.time):
    """Dopisuje brakujące świece 1h (pełne dni do wczoraj) do px_1h_<coin>.json."""
    h = hcfg(cfg)
    s = session or requests.Session()
    today = floor(now, DAY)
    cur_month = _month_start(today)
    deadline = clock() + float(h["spot_1h_max_minutes"]) * 60
    info = {}
    for sid, symbol in (h.get("spot_1h") or {}).items():
        path = px1h_path(data_dir, sid)
        bars, missing = load_px1h(path)
        miss = set(missing)
        d = floor(max(bars) + HOUR, DAY) if bars else day_of(h["spot_1h_start"])
        months, days = [], []
        while d < today:
            if d == _month_start(d) and _next_month(d) <= cur_month:
                months.append(d)
                d = _next_month(d)
            else:
                if d not in miss:
                    days.append(d)
                d += DAY
        got, errors, n0 = 0, 0, len(bars)
        with ThreadPoolExecutor(max_workers=int(h["vision_workers"])) as ex:
            jobs = [("monthly", datetime.fromtimestamp(m, timezone.utc).strftime("%Y-%m")) for m in months]
            later = [("daily", iso(t)) for t in days]
            while (jobs or later) and clock() < deadline:
                if not jobs:
                    jobs, later = later, []
                more = []
                for per, date, rows, err in ex.map(lambda j: _fetch_kline(s, symbol, *j), jobs):
                    if rows:
                        bars.update({t: v for t, v in rows.items() if t < today})
                        got += 1
                    elif err == "404" and per == "monthly":       # miesiąc jeszcze nie spakowany → pliki dzienne
                        m = day_of(date + "-01")
                        more += [("daily", iso(t)) for t in range(m, min(_next_month(m), today), DAY) if t not in miss]
                    elif err == "404":
                        if day_of(date) < today - 3 * DAY:
                            miss.add(day_of(date))                  # dziura w archiwum — nie pytamy co skan
                    else:
                        errors += 1
                jobs = more
        if len(bars) != n0 or sorted(miss) != sorted(missing):
            if bars:
                save_px1h(path, bars, symbol, now, sorted(miss))
        info[sid + "_1h"] = (f"+{len(bars) - n0} h (razem {len(bars)}" + (f", od {iso(min(bars))}" if bars else "") + ")"
                             + (f", błędy {errors}" if errors else "")
                             + (" — przerwane limitem czasu" if clock() >= deadline else ""))
        log.info("Świece 1h %s (%s): %s", sid, symbol, info[sid + "_1h"])
        if errors and not got:
            raise RuntimeError(f"{symbol} 1h: {errors} nieudanych pobrań z data.binance.vision")
    return info


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
        try:
            info.update(extend_wicks(store, tv, cfg, now))
        except Exception as e:  # noqa: BLE001
            log.exception("Knoty z TradingView")
            errors["knoty (TradingView INDEX)"] = str(e)
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
    if h.get("spot_1h") and getattr(store, "dir", None):
        try:
            info.update(collect_spot_1h(store.dir, cfg, now, session))
        except Exception as e:  # noqa: BLE001
            log.exception("Świece 1h (archiwum Binance)")
            errors["archiwum Binance"] = "; ".join(x for x in (errors.get("archiwum Binance"), f"świece 1h: {e}") if x)
    return info, errors
