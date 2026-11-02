"""Liquidations, funding and price (Coinalyze) for the liq.html tab.

Universe: BTC, ETH + top N alts by OI (from the OI universe) + watchlist,
markets on the exchanges from config (including Hyperliquid), optionally
without tiny markets (min_market_oi_usd).

Series (hourly in liq_1h.json, daily in liq_1d.json):
  liq_<g>_long / liq_<g>_short   g = btc, eth, others, total, watchlist coins  (USD per candle)
  liq_ex_<exchange>              long + short per exchange                    (USD per candle)
  fund_<g>                       OI-weighted funding, % per year             g = btc, eth, others, watchlist
  px_btc / px_eth                close price
"""
import logging
import statistics
from datetime import datetime, timezone

import series as S

log = logging.getLogger("liquidations")
HOUR, DAY = S.HOUR, S.DAY

LIQ_VERSION = 1              # bump → automatic re-download of the liquidation history
INTRADAY_KEEP_HOURS = 1490
OVERLAP_HOURS = 3
FUND_ABS_CAP = 5000.0        # % per year; anything beyond is a data glitch


def floor(t, step):
    return int(t) - int(t) % step


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def ex_code(symbol):
    return symbol.rsplit(".", 1)[1] if "." in symbol else ""


def canon_names(names, wanted):
    """Coinalyze exchange names → names as written in config (same prefix rule as select_markets)."""
    out = {}
    for code, name in names.items():
        n = _norm(name)
        match = next((w for w in wanted if _norm(w) and n and (n.startswith(_norm(w)) or _norm(w).startswith(n))),
                     None)
        out[code] = match or name
    return out


# ── universe ─────────────────────────────────────────────────
def liq_universe(uni, st, lcfg, watch):
    """→ (sym_base for liq markets, groups {g: set(bases)}, others set, coverage)."""
    top = int(lcfg.get("top_alts", 30))
    min_oi = float(lcfg.get("min_market_oi_usd", 0) or 0)
    ranked = [a for a, _ in (uni.get("assets") or [])]
    alts = [a for a in ranked if a not in ("BTC", "ETH")][:top]
    present = set(uni["symbols"].values())
    others = set(alts) | {w for w in watch if w in present and w not in ("BTC", "ETH")}
    assets = {"BTC", "ETH"} | others
    last_oi = st.get("last_oi") or {}

    def oi_of(sym):
        v = last_oi.get(sym)
        return v[1] if v else None
    sym_base = {}
    for sym, base in uni["symbols"].items():
        if base not in assets:
            continue
        v = oi_of(sym)
        if min_oi and v is not None and v < min_oi:
            continue
        sym_base[sym] = base
    tot = sum((oi_of(s) or 0) for s in uni["symbols"])
    cov = sum((oi_of(s) or 0) for s in sym_base) / tot if tot else None
    return sym_base, others, cov


def group_members(sym_base, others, watch):
    g = {"btc": set(), "eth": set(), "others": set(), "total": set(sym_base)}
    for w in watch:
        g[w.lower()] = set()
    for sym, base in sym_base.items():
        if base == "BTC":
            g["btc"].add(sym)
        elif base == "ETH":
            g["eth"].add(sym)
        if base in others:
            g["others"].add(sym)
        if base.lower() in g and base not in ("BTC", "ETH"):
            g[base.lower()].add(sym)
    return g


# ── aggregation ──────────────────────────────────────────────
def aggregate_liq(hist, groups, timestamps, step):
    """{sym: {t: (l, s)}} → {"liq_<g>_long": {t: v}, ...} dense over timestamps (0 = no liquidations)."""
    out = {}
    for g, syms in groups.items():
        lo = {t: 0.0 for t in timestamps}
        sh = {t: 0.0 for t in timestamps}
        for sym in syms:
            for t, (l, s) in (hist.get(sym) or {}).items():
                t = t - t % step
                if t in lo:
                    lo[t] += l
                    sh[t] += s
        out[f"liq_{g}_long"] = lo
        out[f"liq_{g}_short"] = sh
    return out


def aggregate_liq_by_exchange(hist, sym_base, names, timestamps, step):
    out = {}
    for sym in sym_base:
        name = names.get(ex_code(sym))
        if not name:
            continue
        dst = out.setdefault(S.ex_id(name), {t: 0.0 for t in timestamps})
        for t, (l, s) in (hist.get(sym) or {}).items():
            t = t - t % step
            if t in dst:
                dst[t] += l + s
    return out


def interval_hours(sym, names, lcfg):
    m = {_norm(k): float(v) for k, v in (lcfg.get("funding_interval_hours") or {}).items()}
    return m.get(_norm(names.get(ex_code(sym), "")), m.get("default", 8.0))


def detect_unit(fund_hist, sym_base, names, lcfg):
    """Coinalyze funding: percent (0.01 = 0.01%) or fraction (0.0001)? Median of BTC 8h markets."""
    vals = []
    for sym, base in sym_base.items():
        if base != "BTC" or interval_hours(sym, names, lcfg) != 8:
            continue
        vals += [abs(v) for v in (fund_hist.get(sym) or {}).values() if v]
    if len(vals) < 20:
        return None
    return "fraction" if statistics.median(vals) < 0.001 else "percent"


def annualize(raw, sym, names, lcfg, unit):
    pct = raw * 100 if unit == "fraction" else raw
    v = pct * (24 / interval_hours(sym, names, lcfg)) * 365
    return v if abs(v) <= FUND_ABS_CAP else None


def aggregate_funding(fund_hist, weights, groups, timestamps, step, names, lcfg, unit):
    """OI-weighted average annualised funding per group.

    weights: callable (sym, t) → OI in USD or None.
    """
    ann = {}
    for sym, h in fund_hist.items():
        a = {}
        for t, raw in h.items():
            v = annualize(raw, sym, names, lcfg, unit)
            if v is not None:
                a[t - t % step] = v
        ann[sym] = a
    out = {}
    for g, syms in groups.items():
        if g == "total":
            continue
        s = {}
        for t in timestamps:
            num = den = 0.0
            for sym in syms:
                v = (ann.get(sym) or {}).get(t)
                if v is None:
                    continue
                w = weights(sym, t)
                if not w or w <= 0:
                    continue
                num += v * w
                den += w
            if den > 0:
                s[t] = num / den
        out[f"fund_{g}"] = s
    return out


def oi_weights(oi_hist, fallback, step, ffill_steps):
    """Weight function from per-symbol OI history (ffill a few steps), else latest OI."""
    def w(sym, t):
        h = oi_hist.get(sym) if oi_hist else None
        if h:
            for k in range(ffill_steps + 1):
                v = h.get(t - k * step)
                if v:
                    return v
            return None
        v = fallback.get(sym)
        return v[1] if v else None
    return w


# ── collection ───────────────────────────────────────────────
def price_ohlc(client, symbols, interval, frm, to):
    """{symbol: {t: (high, low, close)}}; klient bez high/low (starsze testy) → (close, close, close)."""
    if hasattr(client, "price_ohlc_history"):
        return client.price_ohlc_history(symbols, interval, frm, to)
    return {s: {t: (v, v, v) for t, v in h.items()} for s, h in client.price_history(symbols, interval, frm, to).items()}


def collect_liq(client, store, cfg, now, backfill=False):
    st = store.state
    lcfg = cfg.get("liquidations") or {}
    watch = [w.upper() for w in cfg.get("watchlist") or []]
    uni = st.get("universe")
    if not uni or not uni.get("symbols"):
        raise RuntimeError("brak listy rynków OI (najpierw musi zadziałać pobieranie OI)")

    # exchange code → name (refreshed together with the OI universe)
    ex = st.get("liq_exchanges") or {}
    if backfill or not ex.get("names") or ex.get("at") != uni.get("at"):
        names = {e.get("code"): e.get("name") for e in client.exchanges()}
        st["liq_exchanges"] = ex = {"at": uni.get("at"), "names": names}
    wanted = (cfg.get("coinalyze") or {}).get("exchanges") or []
    names = canon_names(ex["names"], wanted)
    used = {names.get(ex_code(s)) for s in uni["symbols"]}
    ex_diag = {"coinalyze_exchanges": sorted(n for n in ex["names"].values() if n),
               "configured_without_markets": [w for w in wanted if w not in used]}

    sym_base, others, cov = liq_universe(uni, st, lcfg, watch)
    symbols = sorted(sym_base)
    if not symbols:
        raise RuntimeError("brak rynków do likwidacji")
    groups = group_members(sym_base, others, watch)
    full = backfill or st.get("liq_version") != LIQ_VERSION or store.last_t("1h", "liq_total_long") is None
    calls0, failed0 = client.calls_made, getattr(client, "failed_batches", 0)
    log.info("Likwidacje: %d rynków (%d coinów), pokrycie OI %s%s", len(symbols), len(set(sym_base.values())),
             f"{cov:.1%}" if cov is not None else "?", " — pełne pobranie historii" if full else "")

    # ── hourly ──
    now_h = floor(now, HOUR)
    keep_from = now_h - INTRADAY_KEEP_HOURS * HOUR
    if full:
        start = keep_from
    else:
        anchor = st.get("liq_complete_until") or store.last_t("1h", "liq_total_long")
        start = max(anchor - OVERLAP_HOURS * HOUR, keep_from)
    ts = list(range(start, now_h + 1, HOUR))
    prog = lambda what: (lambda i, n: log.info("  %s paczka %d/%d", what, i, n))  # noqa: E731
    lh = client.liquidation_history(symbols, "1hour", start, now, progress=prog("likwidacje 1h"))
    fh = client.funding_history(symbols, "1hour", start, now, progress=prog("funding 1h"))
    psyms = {sid: sym for sid, sym in (lcfg.get("price_symbols") or {}).items()}
    ph = price_ohlc(client, sorted(set(psyms.values())), "1hour", start, now) if psyms else {}
    oi_h = client.oi_history(symbols, "1hour", start, now, progress=prog("OI 1h (wagi)")) if full else None

    unit = lcfg.get("funding_unit", "auto")
    if unit == "auto":
        unit = st.get("liq_funding_unit") or detect_unit(fh, sym_base, names, lcfg) or "percent"
        st["liq_funding_unit"] = unit

    replace = 0 if full else start
    for sid, pts in aggregate_liq(lh, groups, ts, HOUR).items():
        store.put("1h", sid, pts, replace_from=replace)
    for sid, pts in aggregate_liq_by_exchange(lh, sym_base, names, ts, HOUR).items():
        store.put("1h", sid, pts, replace_from=replace)
    w = oi_weights(oi_h, st.get("last_oi") or {}, HOUR, 6)
    for sid, pts in aggregate_funding(fh, w, groups, ts, HOUR, names, lcfg, unit).items():
        store.put("1h", sid, pts, replace_from=replace)
    for sid, sym in psyms.items():
        for i, suffix in ((2, ""), (0, "_hi"), (1, "_lo")):            # zamknięcie + knoty (high / low)
            store.put("1h", sid + suffix, {t: v[i] for t, v in (ph.get(sym) or {}).items()}, replace_from=replace)
    if full:
        # drop hourly leftovers older than the new window
        for sid in list(store.series["1h"]):
            if sid.startswith(("liq_", "fund_", "px_")):
                s_ = store.series["1h"][sid]
                for t in [t for t in s_ if t < start]:
                    del s_[t]

    # ── daily ──
    if full:
        d0 = int(datetime.strptime(str(cfg.get("coinalyze", {}).get("daily_history_start", "2019-01-01")),
                                   "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        log.info("Likwidacje 1d: %d rynków od %s", len(symbols), _iso(d0))
        days = list(range(floor(d0, DAY), floor(now, DAY) + 1, DAY))
        ld = client.liquidation_history(symbols, "daily", d0, now, progress=prog("likwidacje 1d"))
        fd = client.funding_history(symbols, "daily", d0, now, progress=prog("funding 1d"))
        od = client.oi_history(symbols, "daily", d0, now, progress=prog("OI 1d (wagi)"))
        pd = price_ohlc(client, sorted(set(psyms.values())), "daily", d0, now) if psyms else {}
        daily = aggregate_liq(ld, groups, days, DAY)
        daily.update(aggregate_liq_by_exchange(ld, sym_base, names, days, DAY))
        # first day with real data for both BTC and ETH (earlier = a handful of markets)
        first = min((t for t in days if daily["liq_btc_long"][t] + daily["liq_btc_short"][t] > 0
                     and daily["liq_eth_long"][t] + daily["liq_eth_short"][t] > 0), default=None)
        daily.update(aggregate_funding(fd, oi_weights(od, {}, DAY, 3), groups, days, DAY, names, lcfg, unit))
        for sid, sym in psyms.items():
            for i, suffix in ((2, ""), (0, "_hi"), (1, "_lo")):
                daily[sid + suffix] = {t: v[i] for t, v in (pd.get(sym) or {}).items()}
        for sid, pts in daily.items():
            pts = {t: v for t, v in pts.items() if first is not None and t >= first}
            store.put("1d", sid, pts, replace_from=0)
        if first:
            log.info("Likwidacje 1d: pełne dane od %s", _iso(first))
    # knoty dzienne (high / low ceny) — jednorazowo cała historia, gdy jeszcze ich nie ma (pierwszy skan po poprawce 37)
    if psyms and not full and any(not store.series["1d"].get(sid + "_lo") for sid in psyms):
        d0 = int(datetime.strptime(str(cfg.get("coinalyze", {}).get("daily_history_start", "2019-01-01")),
                                   "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        pd = price_ohlc(client, sorted(set(psyms.values())), "daily", d0, now)
        for sid, sym in psyms.items():
            for i, suffix in ((0, "_hi"), (1, "_lo")):
                store.put("1d", sid + suffix, {t: v[i] for t, v in (pd.get(sym) or {}).items()})
        log.info("Knoty dzienne cen: %s", {sid: len(pd.get(sym) or {}) for sid, sym in psyms.items()})
    # Coinalyze liquidation history before the OI history start (09.2022) covers only a fraction
    # of the market (median ~$1–6M/day vs $100M+ later) → keep daily data from the OI start on.
    # Funding is not cut: fund_btc / fund_eth before that date come from history.py (fixed weights).
    oi_d = store.series["1d"].get("oi_total") or {}
    if oi_d:
        cut = min(oi_d)
        for sid in list(store.series["1d"]):
            if sid.startswith("liq_"):
                s_ = store.series["1d"][sid]
                for t in [t for t in s_ if t < cut]:
                    del s_[t]
    # recent days from the hourly data (sums for liquidations, close for funding/price)
    h_first = min(store.series["1h"].get("liq_total_long") or {now_h: 0})
    first_full_day = h_first if h_first % DAY == 0 else floor(h_first, DAY) + DAY
    day_from = max(floor(start, DAY), first_full_day)
    for sid in list(store.series["1h"]):
        if sid.startswith("liq_"):
            store.put("1d", sid, S.daily_sum_from_hourly(store.get("1h", sid), day_from))
        elif sid.startswith("px_") and sid.endswith(("_hi", "_lo")):
            hh = store.get("1h", sid)                   # knoty: tylko pełne dni w danych godzinowych
            full_from = min(hh) if hh else now_h
            full_from = full_from if full_from % DAY == 0 else floor(full_from, DAY) + DAY
            store.put("1d", sid, S.daily_extreme_from_hourly(hh, max(floor(start, DAY), full_from),
                                                             max if sid.endswith("_hi") else min))
        elif sid.startswith(("fund_", "px_")):
            store.put("1d", sid, S.daily_from_hourly(store.get("1h", sid), floor(start, DAY)))

    failed = getattr(client, "failed_batches", 0) - failed0
    if not failed:
        st["liq_complete_until"] = now_h
    st["liq_version"] = LIQ_VERSION
    info = diagnostics(store, sym_base, names, lh, fh, now_h, unit, cov)
    ranked = [a for a, _ in (uni.get("assets") or [])]
    info.update(ex_diag)
    info.update({"calls": client.calls_made - calls0, "failed_batches": failed, "full": full,
                 "others": [a for a in ranked if a in others],
                 "price_points": {sid: len(ph.get(sym) or {}) for sid, sym in psyms.items()}})
    if failed:
        log.warning("Likwidacje: %d paczek pominiętych po nieudanych próbach", failed)
    return info


def diagnostics(store, sym_base, names, lh, fh, now_h, unit, cov):
    """Per-exchange check (is Hyperliquid there? are funding units consistent?)."""
    t0 = now_h - 24 * HOUR
    per_ex = {}
    for sym, base in sym_base.items():
        name = names.get(ex_code(sym)) or ex_code(sym)
        e = per_ex.setdefault(name, {"markets": 0, "with_liq": 0, "liq_24h": 0.0, "btc_funding_raw": []})
        e["markets"] += 1
        h = lh.get(sym) or {}
        if h:
            e["with_liq"] += 1
        e["liq_24h"] += sum(l + s for t, (l, s) in h.items() if t > t0)
        if base == "BTC":
            f = fh.get(sym) or {}
            if f:
                e["btc_funding_raw"].append(f[max(f)])
    for e in per_ex.values():
        e["liq_24h"] = round(e["liq_24h"])
        e["btc_funding_raw"] = (round(statistics.median(e["btc_funding_raw"]), 6)
                                if e["btc_funding_raw"] else None)
    liq24 = sum(v for t, v in (store.series["1h"].get("liq_total_long") or {}).items() if t > t0) + \
        sum(v for t, v in (store.series["1h"].get("liq_total_short") or {}).items() if t > t0)
    return {"markets": len(sym_base), "assets": len(set(sym_base.values())),
            "oi_coverage": round(cov, 4) if cov is not None else None,
            "funding_unit": unit, "liq_24h": round(liq24), "exchanges": per_ex}
