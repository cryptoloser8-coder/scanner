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
import cvd as V  # noqa: E402
import cycle as C  # noqa: E402
import history as H  # noqa: E402
import liquidations as L  # noqa: E402
import series as S  # noqa: E402
from coinalyze import Coinalyze, build_universe  # noqa: E402
from store import Store  # noqa: E402
from tradingview import TradingView  # noqa: E402

log = logging.getLogger("collector")
HOUR, DAY = S.HOUR, S.DAY

INTRADAY_KEEP_HOURS = 1490   # Coinalyze keeps 1500–2000 intraday points
OVERLAP_HOURS = 3            # re-fetch recent hours (late / partial candles)


def report_lines(cfg):
    """{series id: [{"value", "label", "color"}]} — the level lines of the report charts (config reports.lines)."""
    try:
        import report
        lay = report.layout(cfg.get("reports") or {})
        return {sid: report.lines_for(lay, sid) for sid in lay.get("lines") or {}}
    except Exception as e:  # noqa: BLE001 — lines are optional decoration
        log.warning("Linie poziomów z raportu: %s", e)
        return {}


HIST_KINDS = ("krach", "upadek", "hack", "prawo", "etf", "polityka", "inne")


def history_events(cfg):
    """config history_events → [{"t", "date", "label", "desc", "kind"}] posortowane po dacie (poprawka 63).
    Historyczne wydarzenia rysowane w oi/liq/ema i na wykresach BTC od 2011 w raportach. Błędne wpisy pomijane."""
    out = []
    for e in cfg.get("history_events") or []:
        try:
            d = datetime.strptime(str(e.get("date"))[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            label = str(e.get("label") or "").strip()
            if not label:
                raise ValueError("brak label")
        except Exception as ex:  # noqa: BLE001
            log.warning("Historyczne wydarzenie pominięte (%s): %s", ex, e)
            continue
        kind = str(e.get("kind") or "inne").strip().lower()
        out.append({"t": int(d.timestamp()), "date": d.strftime("%Y-%m-%d"), "label": label,
                    "desc": str(e.get("desc") or "").strip(), "kind": kind if kind in HIST_KINDS else "inne"})
    return sorted(out, key=lambda x: x["t"])


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


try:                                   # alty według kapitalizacji (poprawka 46) — brak modułu nie zatrzymuje skanu
    import alts as A  # noqa: E402
except Exception:  # noqa: BLE001
    A = None


def build_catalog(cfg):
    watch = [w.upper() for w in cfg["watchlist"]]
    liq = None
    if liq_enabled(cfg):
        liq = {"top": int(cfg["liquidations"].get("top_alts", 30)), "exchanges": cfg["coinalyze"]["exchanges"]}
    cat = S.catalog_with_watchlist(watch, liq, V.settings(cfg)["coins"] if V.enabled(cfg) else None, V.watch_close_coins(cfg))
    if A is not None and A.enabled(cfg):
        cat.update(A.catalog())
    return cat


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
    # tylko dzienne (makro USA, poprawka 29): pierwszy raz pełna historia
    daily_syms = cfg["tradingview"].get("daily_symbols") or {}
    for sid, symbol in daily_syms.items():
        try:
            last_d = store.last_t("1d", sid)
            nd = 20000 if (backfill or last_d is None) else min(5000, (now - last_d) // DAY + 5)
            bars_d = tv.bars(symbol, "1D", nd)
            store.put("1d", sid, {t - t % DAY: v for t, v in bars_d})
            log.info("TV %s: %d×1D", symbol, len(bars_d))
        except Exception as e:  # noqa: BLE001
            log.error("TV %s: %s", symbol, e)
            errors.append(f"{symbol}: {e}")
    if errors and len(errors) == len(cfg["tradingview"]["symbols"]) + len(daily_syms):
        raise RuntimeError("; ".join(errors[:3]))
    return errors


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── main run ─────────────────────────────────────────────────
def alt_lamps(store, cfg, now, ema_fetch):
    """Lampki zakładki Altsezon (lamps.py, poprawka 70) → wynik do meta.json albo None. Nigdy nie przerywa skanu.
    ema_fetch(name) → dict z gałęzi `ema` (altindex.json, ema.json — liczy Orange Pi)."""
    try:
        import lamps as LP   # import w funkcji: przy wgrywaniu kilkoma uploadami brak pliku nie psuje skanu
    except ImportError:
        log.warning("Lampki: brak lamps.py — pomijam")
        return None, None
    if not LP.config(cfg).get("enabled", True) or ema_fetch is None:
        return LP, None
    try:
        idx, ema = ema_fetch("altindex.json") or {}, ema_fetch("ema.json") or {}
        d1 = store.series["1d"]
        res = LP.build(cfg, now, idx=idx.get("d"), breadth=ema.get("breadth"), rsi_d3=(ema.get("rsi") or {}).get("d3"),
                       lev=d1.get("oi_others_vs_btc"), lev_now=store.latest("oi_others_vs_btc"),
                       mvrvz=d1.get("mvrvz_btc"), btc=d1.get("px_btc"))
        return LP, res
    except Exception:  # noqa: BLE001
        log.exception("Lampki")
        return LP, None


def raw_fetcher(repo, branch, session=None, timeout=20):
    """name → dict z raw.githubusercontent.com/<repo>/<branch>/<name> (None przy błędzie)."""
    import requests

    def get(name):
        try:
            r = (session or requests).get(f"https://raw.githubusercontent.com/{repo}/{branch}/{name}",
                                          params={"t": int(time.time())}, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("Gałąź %s, %s: %s", branch, name, e)
            return None
    return get


def run(data_dir, cfg, now=None, backfill=False, coinalyze=None, tv=None, telegram=None, cg_fetch=None,
        vision_session=None, cm_session=None, alts_session=None, alts_sleep=time.sleep, ema_fetch=None):
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

    # CVD spot vs perp (poprawka 44): kupno − sprzedaż z wolumenu Coinalyze
    if V.enabled(cfg):
        try:
            if client is None:
                raise RuntimeError("brak klienta Coinalyze")
            info["cvd"] = V.collect(client, store, cfg, now, backfill)
            results["CVD"] = None
        except Exception as e:  # noqa: BLE001
            log.exception("CVD")
            results["CVD"] = str(e)

    # ceny i knoty coinów z watchlisty (poprawki 67–68): jeden perp na coin, historia dzienna od startu rynku
    if V.watch_coins(cfg):
        try:
            if client is None:
                raise RuntimeError("brak klienta Coinalyze")
            info["watch_px"] = V.watch_prices(client, store, cfg, now)
            results["Ceny watchlisty"] = None
        except Exception as e:  # noqa: BLE001
            log.exception("Ceny watchlisty")
            results["Ceny watchlisty"] = str(e)

    tv = tv or TradingView()
    try:
        tv_err = collect_tv(tv, store, cfg, now, backfill)
        results["TradingView"] = None
        if tv_err:
            info["tradingview_partial"] = tv_err
    except Exception as e:  # noqa: BLE001
        log.exception("TradingView")
        results["TradingView"] = str(e)

    # dłuższa historia istniejących serii (poprawka 28): cena i funding BTC/ETH sprzed startu Coinalyze,
    # OI Binance z archiwum data.binance.vision — pobiera tylko braki (config `history`)
    if (cfg.get("history") or {}).get("enabled"):
        h_info, h_err = H.extend_all(store, cfg, now,
                                     client=client if results.get("Coinalyze") is None else None,
                                     tv=tv if results.get("TradingView") is None else None,
                                     session=vision_session)
        if h_info:
            info["history"] = h_info
        if (cfg["history"].get("vision_oi") or H.DEFAULTS["vision_oi"]):
            results["Archiwum Binance"] = h_err.pop("archiwum Binance", None)
        if h_err:
            info["history_errors"] = h_err

    # alty według kapitalizacji (poprawka 46): koszyki z CoinGecko + narracje DexScreenera, najwyżej 2 zapisy na dobę
    if A is not None and A.enabled(cfg) and not backfill:
        ast = st.setdefault("alts", {})
        try:
            a_info = A.collect(store, cfg, now, session=alts_session, sleep=alts_sleep)
            if a_info.get("snapshot"):
                info["alts"] = a_info
                ast["error"] = None
        except Exception as e:  # noqa: BLE001
            log.exception("Alty (CoinGecko)")
            ast["error"] = str(e)
        results["Alty (CoinGecko)"] = ast.get("error")      # stan z ostatniej próby zapisu (nie każdy skan ją robi)

    for res in ("1h", "1d"):
        S.derived(store.series[res])

    # cykl BTC (Coin Metrics + wskaźniki z ceny) i makro USA (poprawka 29) — po serii pochodnych (SSR)
    cyc_lines, cyc_marks = {}, {}
    if (cfg.get("cycle") or {}).get("enabled"):
        c_info, c_err = C.run(store, cfg, now, session=cm_session)
        info["cycle"] = c_info
        if (cfg["cycle"].get("coinmetrics", True)):
            results["Coin Metrics"] = c_err
        cyc_lines = C.ref_lines(store, cfg)
        cyc_marks = C.cycle_marks(store.series["1d"].get("px_btc") or {}, cfg)   # tło faz cyklu w oi.html

    # lampki Altsezonu (poprawka 70): indeks altów, szerokość, RSI z gałęzi `ema` + lewar, MVRV-Z, BTC z tego skanu
    if ema_fetch is None and repo:
        ema_fetch = raw_fetcher(repo, "ema")
    LP, lamps_res = alt_lamps(store, cfg, now, ema_fetch)

    # system messages → admin (private); market alerts → group thread (one message per run, unless muted)
    system = alerts.health_messages(st, results, now, cfg["telegram"].get("health_reminder_hours", 12))
    market, lamp_msgs = [], []
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
        if LP and lamps_res:
            LP.check(lamps_res, cfg, st, arm_only=True)
    else:
        market += alerts.check_levels(store, catalog, cfg["levels"], st, page_url)
        market += alerts.check_changes(store, catalog, cfg["changes"], st, now)
        market += alerts.check_sums(store, catalog, cfg.get("liq_alerts"), st, now)
        if LP and lamps_res:
            lamp_msgs = LP.check(lamps_res, cfg, st, page_url)
    for m in system:
        tg.post("system", m)
    if market or lamp_msgs:
        mute_until = alerts.fetch_mute(mute_url) if mute_url else None
        if alerts.is_muted(mute_until, now):
            log.info("Alerty wyciszone (/cisza) — pomijam %d", len(market) + len(lamp_msgs))
            info["muted_alerts"] = len(market) + len(lamp_msgs)
        else:
            if market:
                tg.post("market", "\n\n".join(["📊 <b>Rynek</b> (OI, TOTAL, likwidacje)"] + market))
            if lamp_msgs:
                tg.post("market", "\n\n".join(["💡 <b>Altsezon — lampki</b>"] + lamp_msgs))
    msgs = system + market + lamp_msgs

    meta = {
        "updated": now,
        "catalog": catalog,
        "levels": cfg["levels"],
        # reference lines from the report (config reports.lines) — drawn in oi.html too, one source for both
        "ref_lines": {**cyc_lines, **report_lines(cfg)},
        "cycle_marks": cyc_marks,
        "history_events": history_events(cfg),
        "alt_lamps": lamps_res,             # lampki Altsezonu (lamps.py) — alt.html tylko je wyświetla
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
