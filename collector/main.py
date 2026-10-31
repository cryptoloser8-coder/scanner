"""OI & TOTAL Monitor — collector.

  python collector/main.py run      --data-dir DIR   # regular run (cron)
  python collector/main.py backfill --data-dir DIR   # one-time full history download

Env: COINALYZE_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAGE_URL (optional)
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alerts  # noqa: E402
import coingecko  # noqa: E402
import liquidations as L  # noqa: E402
import series as S  # noqa: E402
from coinalyze import Coinalyze, build_universe  # noqa: E402
from store import Store  # noqa: E402
from tradingview import TradingView  # noqa: E402

log = logging.getLogger("collector")
HOUR, DAY = S.HOUR, S.DAY

INTRADAY_KEEP_HOURS = 1490   # Coinalyze keeps 1500–2000 intraday points
OVERLAP_HOURS = 3            # re-fetch recent hours (late / partial candles)


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("coinalyze", {})
    cfg["coinalyze"].setdefault("exchanges", ["Binance", "Bybit", "OKX"])
    cfg.setdefault("watchlist", [])
    cfg.setdefault("tradingview", {}).setdefault("symbols", {})
    cfg.setdefault("telegram", {})
    cfg["levels"] = cfg.get("levels") or []
    cfg["changes"] = cfg.get("changes") or []
    cfg["liq_alerts"] = cfg.get("liq_alerts") or []
    if cfg.get("liquidations") is not None:
        lq = cfg["liquidations"]
        lq.setdefault("enabled", True)
        lq.setdefault("top_alts", 30)
        lq.setdefault("funding_interval_hours", {"default": 8, "Hyperliquid": 1})
        lq.setdefault("price_symbols", {"px_btc": "BTCUSDT_PERP.A", "px_eth": "ETHUSDT_PERP.A"})
    return cfg


def liq_enabled(cfg):
    return bool((cfg.get("liquidations") or {}).get("enabled"))


def build_catalog(cfg):
    watch = [w.upper() for w in cfg["watchlist"]]
    liq = None
    if liq_enabled(cfg):
        liq = {"top": int(cfg["liquidations"].get("top_alts", 30)), "exchanges": cfg["coinalyze"]["exchanges"]}
    return S.catalog_with_watchlist(watch, liq)


def floor(t, step):
    return int(t) - int(t) % step


# ── Coinalyze OI ─────────────────────────────────────────────
def make_crypto_filter(cfg, st, now, fetch=None):
    """Keep crypto assets only: CoinGecko top-N symbols + config overrides."""
    ccfg = cfg["coinalyze"]
    excl = {a.upper() for a in ccfg.get("exclude_assets") or []}
    incl = {a.upper() for a in ccfg.get("include_assets") or []}
    top = int(ccfg.get("crypto_whitelist_top", 1500) or 0)
    wl = None
    st["crypto_filter"] = "exclude_assets"
    if top > 0:
        try:
            wl = set((fetch or coingecko.crypto_symbols)(top))
            st["crypto_whitelist"] = {"at": now, "symbols": sorted(wl)}
            st["crypto_filter"] = f"CoinGecko top {top}"
        except Exception as e:  # noqa: BLE001
            cached = (st.get("crypto_whitelist") or {}).get("symbols")
            log.warning("CoinGecko niedostępne (%s) — %s", e,
                        "używam zapisanej listy" if cached else "filtruję tylko listą exclude_assets")
            wl = set(cached) if cached else None
            if cached:
                st["crypto_filter"] = "CoinGecko (zapisana lista)"

    def is_crypto(base):
        if base in incl:
            return True
        if base in excl:
            return False
        return True if wl is None else base in wl
    return is_crypto


def collect_oi(client, store, cfg, now, backfill, cg_fetch=None):
    st = store.state
    ccfg = cfg["coinalyze"]
    watch = [w.upper() for w in cfg["watchlist"]]

    uni = st.get("universe")
    # start of the hourly OI history from the last backfill (one-time migration for older state)
    if not backfill and "oi_1h_from" not in st and uni:
        st["oi_1h_from"] = floor(uni.get("at", now), HOUR) - INTRADAY_KEEP_HOURS * HOUR
    refresh_h = float(ccfg.get("universe_refresh_hours", 24))
    if backfill or not uni or now - uni.get("at", 0) >= refresh_h * HOUR:
        u = build_universe(client, ccfg, is_crypto=make_crypto_filter(cfg, st, now, cg_fetch))
        ranked = sorted(u["ranking"], key=u["ranking"].get, reverse=True)
        uni = {"at": now, "symbols": u["symbols"], "excluded": u["excluded"], "top": ranked[:30],
               "filter": st.get("crypto_filter"),
               "assets": [[a, round(u["ranking"][a] / 1e6, 1)] for a in ranked
                          if a in set(u["symbols"].values())]}
        st["universe"] = uni
    sym_base = uni["symbols"]
    symbols = sorted(sym_base)
    if not symbols:
        raise RuntimeError("Brak rynków — sprawdź listę giełd w config.yaml")

    # Hourly
    now_h = floor(now, HOUR)
    last = store.last_t("1h", "oi_total")
    if backfill or last is None:
        start = now_h - INTRADAY_KEEP_HOURS * HOUR
    else:
        start = max(last - OVERLAP_HOURS * HOUR, now_h - INTRADAY_KEEP_HOURS * HOUR)
    log.info("OI 1h: %d rynków od %s", len(symbols), _iso(start))
    hist = client.oi_history(symbols, "1hour", start, now,
                             progress=lambda i, n: log.info("  OI 1h paczka %d/%d", i, n))
    ts = list(range(start, now_h + 1, HOUR))
    prev = {} if backfill else st.get("last_oi", {})
    per_base, new_last = S.aggregate(hist, sym_base, ts, prev, ffill_steps=6, step=HOUR)
    hourly = S.oi_series(per_base, ts, watch)
    for sid, pts in hourly.items():
        store.put("1h", sid, pts, replace_from=0 if backfill else start)
    st["last_oi"] = {**st.get("last_oi", {}), **new_last}
    # drop symbols no longer tracked
    st["last_oi"] = {k: v for k, v in st["last_oi"].items() if k in sym_base}

    # Daily
    if backfill:
        d0 = int(datetime.strptime(str(ccfg.get("daily_history_start", "2019-01-01")),
                                   "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        log.info("OI 1d: %d rynków od %s", len(symbols), _iso(d0))
        dh = client.oi_history(symbols, "daily", d0, now,
                               progress=lambda i, n: log.info("  OI 1d paczka %d/%d", i, n))
        days = list(range(floor(d0, DAY), floor(now, DAY) + 1, DAY))
        pb, _ = S.aggregate(dh, sym_base, days, None, ffill_steps=3, step=DAY)
        daily = S.oi_series(pb, days, watch)
        # Coinalyze history starts at different dates per exchange; keep only days
        # where both BTC and ETH are present (earlier days = a handful of markets)
        first = min((t for t in days if daily["oi_btc"].get(t, 0) > 0 and daily["oi_eth"].get(t, 0) > 0),
                    default=None)
        for sid, pts in daily.items():
            pts = {t: v for t, v in pts.items() if first is not None and t >= first}
            store.put("1d", sid, pts, replace_from=0)
        if first:
            log.info("OI 1d: pełne dane od %s", _iso(first))
    # drop hourly OI points older than the last backfill window (leftovers with stale composition)
    if backfill:
        st["oi_1h_from"] = start
    oldest_ok = st.get("oi_1h_from", 0)
    for sid in hourly:
        s_ = store.series["1h"].get(sid) or {}
        for t in [t for t in s_ if t < oldest_ok]:
            del s_[t]

    # Daily close from hourly for the days touched by this run
    day_from = floor(start, DAY)
    for sid in hourly:
        store.put("1d", sid, S.daily_from_hourly(store.get("1h", sid), day_from))
    failed = getattr(client, "failed_batches", 0)
    if failed:
        log.warning("Coinalyze: %d paczek pominiętych po nieudanych próbach", failed)
    return {"markets": len(symbols), "calls": client.calls_made, "failed_batches": failed}


# ── TradingView CRYPTOCAP ────────────────────────────────────
def collect_tv(tv, store, cfg, now, backfill):
    errors = []
    now_h = floor(now, HOUR)
    for sid, symbol in cfg["tradingview"]["symbols"].items():
        try:
            last = store.last_t("1h", sid)
            n = 5000 if (backfill or last is None) else min(5000, (now_h - last) // HOUR + 4)
            bars = tv.bars(symbol, "60", n)
            store.put("1h", sid, dict(bars))
            last_d = store.last_t("1d", sid)
            nd = 5000 if (backfill or last_d is None) else min(5000, (now - last_d) // DAY + 3)
            bars_d = tv.bars(symbol, "1D", nd)
            store.put("1d", sid, dict(bars_d))
            log.info("TV %s: %d×1h, %d×1D", symbol, len(bars), len(bars_d))
        except Exception as e:  # noqa: BLE001
            log.error("TV %s: %s", symbol, e)
            errors.append(f"{symbol}: {e}")
    if errors and len(errors) == len(cfg["tradingview"]["symbols"]):
        raise RuntimeError("; ".join(errors[:3]))
    return errors


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── main run ─────────────────────────────────────────────────
def run(data_dir, cfg, now=None, backfill=False, coinalyze=None, tv=None, telegram=None, cg_fetch=None):
    now = int(now or time.time())
    store = Store(data_dir)
    st = store.state
    catalog = build_catalog(cfg)
    tg = telegram or alerts.Telegram(enabled=cfg["telegram"].get("enabled", True), tg_cfg=cfg["telegram"])
    page_url = os.environ.get("PAGE_URL", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    mute_url = f"https://raw.githubusercontent.com/{repo}/ema/ema.json" if repo else ""
    results, info = {}, {}

    client = None
    try:
        client = coinalyze or Coinalyze(os.environ.get("COINALYZE_API_KEY", ""))
        info["coinalyze"] = collect_oi(client, store, cfg, now, backfill, cg_fetch)
        results["Coinalyze"] = None
    except Exception as e:  # noqa: BLE001
        log.exception("Coinalyze")
        results["Coinalyze"] = str(e)

    if liq_enabled(cfg):
        try:
            if client is None:
                raise RuntimeError("brak klienta Coinalyze")
            info["liquidations"] = L.collect_liq(client, store, cfg, now, backfill)
            results["Likwidacje"] = None
        except Exception as e:  # noqa: BLE001
            log.exception("Likwidacje")
            results["Likwidacje"] = str(e)

    try:
        tv_err = collect_tv(tv or TradingView(), store, cfg, now, backfill)
        results["TradingView"] = None
        if tv_err:
            info["tradingview_partial"] = tv_err
    except Exception as e:  # noqa: BLE001
        log.exception("TradingView")
        results["TradingView"] = str(e)

    for res in ("1h", "1d"):
        S.derived(store.series[res])

    # system messages → admin (private); market alerts → group thread (one message per run, unless muted)
    system = alerts.health_messages(st, results, now, cfg["telegram"].get("health_reminder_hours", 12))
    market = []
    if backfill:
        n1h = len(store.series["1h"].get("oi_total", {}))
        n1d = len(store.series["1d"].get("oi_total", {}))
        t1d = len(store.series["1d"].get("total", {}))
        extra = ""
        if liq_enabled(cfg):
            extra = f" Likwidacje {len(store.series['1d'].get('liq_total_long', {}))} dni."
        system.append(f"✅ Backfill zakończony: OI {n1d} dni + {n1h} godzin, TOTAL {t1d} dni.{extra}")
        # arm level state silently so the first regular run doesn't fire stale crosses
        alerts.check_levels(store, catalog, cfg["levels"], st)
        alerts.check_sums(store, catalog, cfg.get("liq_alerts"), st, now)
    else:
        market += alerts.check_levels(store, catalog, cfg["levels"], st, page_url)
        market += alerts.check_changes(store, catalog, cfg["changes"], st, now)
        market += alerts.check_sums(store, catalog, cfg.get("liq_alerts"), st, now)
    for m in system:
        tg.post("system", m)
    if market:
        mute_until = alerts.fetch_mute(mute_url) if mute_url else None
        if alerts.is_muted(mute_until, now):
            log.info("Alerty wyciszone (/cisza) — pomijam %d", len(market))
            info["muted_alerts"] = len(market)
        else:
            tg.post("market", "\n\n".join(["📊 <b>Rynek</b> (OI, TOTAL, likwidacje)"] + market))
    msgs = system + market

    meta = {
        "updated": now,
        "catalog": catalog,
        "levels": cfg["levels"],
        "watchlist": [w.upper() for w in cfg["watchlist"]],
        "exchanges": cfg["coinalyze"]["exchanges"],
        "health": {k: (v or "ok") for k, v in results.items()},
        "info": info,
        "top_oi_assets": (st.get("universe") or {}).get("top", []),
        "excluded_assets": (st.get("universe") or {}).get("excluded", []),
        "crypto_filter": (st.get("universe") or {}).get("filter"),
        # tracked assets with current OI in $M at universe refresh — to audit what's counted
        "universe_assets": (st.get("universe") or {}).get("assets", []),
    }
    if liq_enabled(cfg):
        lq = cfg["liquidations"]
        meta["liquidations"] = {
            "top_alts": int(lq.get("top_alts", 30)),
            "liq_alerts": cfg.get("liq_alerts") or [],
            "updated_until": st.get("liq_complete_until"),
        }
    store.save(now, meta)
    log.info("Gotowe. Wiadomości: %d. %s", len(msgs), info)
    return store, msgs, results


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "backfill"])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"))
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(a.config)
    _, _, results = run(a.data_dir, cfg, backfill=(a.mode == "backfill"))
    # fail the job only when every source is down (so GitHub e-mails you)
    return 1 if results and all(results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
