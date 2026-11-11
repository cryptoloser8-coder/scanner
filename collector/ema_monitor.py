"""EMA200 monitor — runs on the Orange Pi (Binance blocks GitHub's US servers).

  python collector/ema_monitor.py run    # cron, every 5 min: prices, alerts, publish
  python collector/ema_monitor.py check  # one-off diagnostics, sends nothing, publishes nothing
  python collector/ema_monitor.py check --test-telegram   # + test message on Telegram

Data: Binance spot, all */USDT pairs that are trading, without stablecoins / fiat /
leveraged tokens, with at least `min_days` closed daily candles.

Once per UTC day (first run after 00:00 UTC): exchangeInfo + daily candles (new coins: up to
1000 days; known coins: only the missing days) + 24h volume, EMA recomputed, market breadth,
per-coin history files. Every run: one request for all prices → EMA "live" (today's candle
counted with the current price, like on TradingView), distance, alerts.

State:   ~/.ema-monitor/ (candles.json, state.json, pub/ = local clone of branch `ema`)
Env:     ~/.scanner_env  (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID), token ~/.scanner_token
         (GitHub fine-grained token with Contents: Read and write) for publishing.
Config:  section `ema:` in collector/config.yaml.
"""
import argparse
import html
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alerts  # noqa: E402
import fib as F  # noqa: E402

log = logging.getLogger("ema")
DAY = 86400
HOUR = 3600

DEFAULTS = {
    "period": 200,
    "quote": "USDT",
    "min_days": 300,
    "min_volume_usd": 0,
    "keep_days": 0,                 # 0 = keep the whole history (from the Binance listing)
    "breadth_days": 0,              # 0 = whole history
    "history_pages_per_run": 100,   # older-candle requests per run while the full history is being filled in
    "breadth_min_coins": 10,
    "chart_days": 0,                # 0 = whole history in the chart files
    "publish_minutes": 15,
    "cross_buffer_pct": 0.5,
    "cooldown_hours": 12,
    "near_rearm": 1.5,
    "near_cooldown_hours": 24,      # "approaching" alert for the same coin at most once per N hours
    "exclude": [],
    "alerts": [],
    "repo": "cryptoloser8-coder/scanner",
    "branch": "ema",
    "page_url": "https://cryptoloser8-coder.github.io/scanner/ema.html",
    # RSI on 3-day and weekly candles (built from the daily closes): per coin + share of coins oversold / overbought
    "rsi_period": 14,
    "rsi_low": 30,
    "rsi_high": 70,
    "rsi_min_bars": 30,             # a coin counts once it has this many closed 3D / 1W candles
    "rsi_min_coins": 30,            # history points with fewer coins are skipped
    "rsi_d3_shift": 0,              # 0–2: which day starts a 3-day candle (0 = like Binance `3d` klines)
}
# stablecoins, fiat and gold tokens — never part of the EMA universe
ALWAYS_EXCLUDE = {
    "USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USDE", "PYUSD", "USD1", "RLUSD", "BFUSD",
    "XUSD", "USDS", "U", "AEUR", "EURI", "EUR", "GBP", "AUD", "BRL", "TRY", "JPY", "PLN", "RON", "ZAR", "UAH",
    "ARS", "MXN", "COP", "CZK", "KGST", "PAXG", "XAUT",
    # wrapped / staked copies of other coins (would double-count BTC, ETH, SOL…)
    "WBTC", "WBETH", "BETH", "BNSOL", "STETH", "WSTETH", "CBBTC",
    # stablecoins / fiat seen only among pairs delisted from Binance (archive, delisted.py)
    "PAX", "USDSB", "SUSD", "UST", "USTC", "BKRW", "BIDR", "IDRT", "NGN", "RUB", "BVND", "VAI", "GYEN",
}
LEVERAGED = ("UP", "DOWN", "BULL", "BEAR")
HIST_VERSION = 2          # bump → chart files are rewritten on the next run (not only after 00:00 UTC)


def fmt_price(v):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1000:
        return f"${v:,.0f}"
    if a >= 1:
        return f"${v:,.2f}"
    if a == 0:
        return "$0"
    decimals = 3 - math.floor(math.log10(a))       # 4 significant digits, no scientific notation
    return f"${v:.{decimals}f}"


# ── Binance ──────────────────────────────────────────────────
class Binance:
    BASES = ("https://api.binance.com", "https://data-api.binance.vision")

    def __init__(self, session=None, sleep=time.sleep, pause=0.05):
        self.s = session or requests.Session()
        self.sleep = sleep
        self.pause = pause
        self.calls = 0

    def _get(self, path, params=None):
        last = None
        for attempt in range(5):
            for base in self.BASES:
                try:
                    r = self.s.get(base + path, params=params, timeout=30)
                except requests.RequestException as e:
                    last = e
                    continue
                self.calls += 1
                if r.status_code == 200:
                    if self.pause:
                        self.sleep(self.pause)
                    return r.json()
                if r.status_code in (418, 429):
                    wait = float(r.headers.get("Retry-After", "30") or 30)
                    log.warning("Binance limit (%s), czekam %.0fs", r.status_code, wait)
                    self.sleep(wait + 1)
                    last = RuntimeError(f"HTTP {r.status_code}")
                    break
                last = RuntimeError(f"{path}: HTTP {r.status_code} {r.text[:150]}")
                if r.status_code < 500 and r.status_code != 403:
                    raise last
            self.sleep(min(2 ** attempt, 30))
        raise RuntimeError(f"Binance {path}: {last}")

    def exchange_info(self):
        return self._get("/api/v3/exchangeInfo")

    def klines(self, symbol, limit, end_ms=None):
        params = {"symbol": symbol, "interval": "1d", "limit": int(limit)}
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        return self._get("/api/v3/klines", params)

    def prices(self):
        return {r["symbol"]: float(r["price"]) for r in self._get("/api/v3/ticker/price")}

    def volumes(self):
        return {r["symbol"]: float(r.get("quoteVolume") or 0)
                for r in self._get("/api/v3/ticker/24hr", {"type": "MINI"})}


# ── universe and candles ─────────────────────────────────────
def universe(info, cfg):
    """exchangeInfo → {symbol: base} for trading spot */quote pairs without stables/leveraged tokens."""
    quote = cfg["quote"]
    excl = ALWAYS_EXCLUDE | {e.upper() for e in cfg.get("exclude") or []}
    rows = [s for s in info.get("symbols", [])
            if s.get("status") == "TRADING" and s.get("quoteAsset") == quote
            and s.get("isSpotTradingAllowed", True)]
    bases = {s["baseAsset"] for s in rows}
    out = {}
    for s in rows:
        b = s["baseAsset"]
        if b in excl:
            continue
        lev = next((x for x in LEVERAGED if b.endswith(x) and b[:-len(x)] in bases), None)
        if lev:
            continue
        out[s["symbol"]] = b
    return out


def closed_candles(rows, now):
    """Binance klines → [[t_open_s, close], ...] without the still-open candle."""
    out = []
    for k in rows or []:
        if int(k[6]) < now * 1000:
            out.append([int(k[0]) // 1000, float(k[4])])
    return out


def closed_hl(rows, now):
    """Binance klines → [[t_open_s, high, low], ...] (closed candles only)."""
    return [[int(k[0]) // 1000, float(k[2]), float(k[3])] for k in rows or [] if int(k[6]) < now * 1000]


def merge(old, new, keep):
    d = {t: c for t, c in old or []}
    d.update({t: c for t, c in new})
    out = sorted(d.items())
    return out[-keep:] if keep else out


def _merge_hl(old, new, keep):
    d = {t: (h, l_) for t, h, l_ in old or []}
    d.update({t: (h, l_) for t, h, l_ in new})
    return [[t, h, l_] for t, (h, l_) in sorted(d.items())][-keep:]


def ema_series(closes, period):
    """EMA like TradingView ta.ema: seeded with the first close. → list of values (same length)."""
    a = 2 / (period + 1)
    out, e = [], None
    for c in closes:
        e = c if e is None else a * c + (1 - a) * e
        out.append(e)
    return out


def streak(closes, emas):
    """Days on the current side of the EMA (closed candles) → (side, days, index where the streak started)."""
    if not closes:
        return 0, 0, None
    side = 1 if closes[-1] >= emas[-1] else -1
    n, i = 0, len(closes) - 1
    while i >= 0 and (1 if closes[i] >= emas[i] else -1) == side:
        n += 1
        i -= 1
    return side, n, (i + 1 if i >= 0 else None)


# ── RSI on 3-day / weekly candles ────────────────────────────
RSI_KINDS = ("d3", "w")


def bar_key(t, kind, shift=0):
    """Number of the 3-day / weekly candle a daily candle (open time t, UTC) belongs to.
    Weekly = Monday–Sunday UTC (as on Binance and TradingView); 3-day = counted from 1970-01-01 + shift days."""
    d = int(t) // DAY
    return (d + 3) // 7 if kind == "w" else (d + int(shift)) // 3


def bar_end(key, kind, shift=0):
    """Open time (UTC midnight) of the last day of a 3-day / weekly candle."""
    return ((key * 7 - 3 + 6) if kind == "w" else (key * 3 - int(shift) + 2)) * DAY


def resample(times, closes, kind, shift=0):
    """Daily closes → (keys, closes) of 3-day / weekly candles (close = last daily close in the candle)."""
    keys, out = [], []
    for t, c in zip(times, closes):
        k = bar_key(t, kind, shift)
        if keys and keys[-1] == k:
            out[-1] = c
        else:
            keys.append(k)
            out.append(c)
    return keys, out


def rsi_series(closes, period=14):
    """Wilder's RSI like TradingView ta.rsi → list (None for the first `period` values)."""
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    gain = loss = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gain += max(d, 0.0)
        loss += max(-d, 0.0)
    gain /= period
    loss /= period
    out[period] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        gain = (gain * (period - 1) + max(d, 0.0)) / period
        loss = (loss * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def rsi_live(times, closes, price, now, kind, cfg):
    """RSI of the candle that is open now (counted with the current price, like on TradingView).
    None while the coin has fewer than rsi_min_bars closed candles."""
    shift = cfg.get("rsi_d3_shift", 0)
    keys, bars = resample(times, closes, kind, shift)
    if not keys:
        return None
    cur = bar_key(now, kind, shift)
    if keys[-1] == cur:
        bars[-1] = price
    else:
        keys.append(cur)
        bars.append(price)
    if len(bars) - 1 < int(cfg.get("rsi_min_bars", 30)):
        return None
    return rsi_series(bars, int(cfg.get("rsi_period", 14)))[-1]


def rsi_extremes(series, cfg, now, kind, extra=None):
    """Share of coins with RSI below rsi_low / above rsi_high on each CLOSED 3-day / weekly candle
    → [[t_last_day, pct_oversold, pct_overbought, coins], ...]. extra = delisted pairs (as in breadth)."""
    period, lo, hi = int(cfg.get("rsi_period", 14)), float(cfg.get("rsi_low", 30)), float(cfg.get("rsi_high", 70))
    min_bars, shift = int(cfg.get("rsi_min_bars", 30)), cfg.get("rsi_d3_shift", 0)
    cur = bar_key(now, kind, shift)
    cnt, n_lo, n_hi = {}, {}, {}
    for times, closes, _ in list(series.values()) + list((extra or {}).values()):
        keys, bars = resample(times, closes, kind, shift)
        vals = rsi_series(bars, period)
        for j in range(min_bars, len(keys)):
            k, v = keys[j], vals[j]
            if k >= cur or v is None:
                continue
            cnt[k] = cnt.get(k, 0) + 1
            if v < lo:
                n_lo[k] = n_lo.get(k, 0) + 1
            elif v > hi:
                n_hi[k] = n_hi.get(k, 0) + 1
    min_n = int(cfg.get("rsi_min_coins", 30))
    return [[bar_end(k, kind, shift), round(n_lo.get(k, 0) / n * 100, 2), round(n_hi.get(k, 0) / n * 100, 2), n]
            for k, n in sorted(cnt.items()) if n >= min_n]


def rsi_now(rows, cfg):
    """Live share of oversold / overbought coins (coins trading today) → {"d3": [pct_lo, pct_hi, n], "w": [...]}."""
    lo, hi = float(cfg.get("rsi_low", 30)), float(cfg.get("rsi_high", 70))
    out = {}
    for kind, field in (("d3", "r3"), ("w", "rw")):
        vals = [r[field] for r in rows if r.get(field) is not None]
        n = len(vals)
        out[kind] = ([round(sum(1 for v in vals if v < lo) / n * 100, 2),
                      round(sum(1 for v in vals if v > hi) / n * 100, 2), n] if n else None)
    return out


def rsi_sig(cfg):
    return [cfg.get(k) for k in ("rsi_period", "rsi_low", "rsi_high", "rsi_min_bars", "rsi_min_coins", "rsi_d3_shift")]


# ── rules / alerts ───────────────────────────────────────────
def rule_for(coin, rules):
    """Merged settings of all rules matching a coin → {"cross": bool, "near_pct": x|None, ...} or None."""
    out = None
    for r in rules or []:
        coins = r.get("coins", [])
        if not (coins == "all" or (isinstance(coins, list) and coin in [c.upper() for c in coins])):
            continue
        out = out or {"cross": False, "near_pct": None, "confirm": "live", "direction": "both"}
        if r.get("cross"):
            out["cross"] = True
            out["confirm"] = r.get("confirm", out["confirm"])
            out["direction"] = r.get("direction", out["direction"])
        if r.get("near_pct") is not None:
            np_ = float(r["near_pct"])
            out["near_pct"] = np_ if out["near_pct"] is None else max(out["near_pct"], np_)
    return out


def check_alerts(rows, rules, st, cfg, now, daily_done, arm_only=False):
    """rows: computed coins. st: state["alerts"] (mutated). → list of message lines."""
    msgs = []
    buf = float(cfg["cross_buffer_pct"])
    cool = float(cfg["cooldown_hours"]) * HOUR
    rearm = float(cfg["near_rearm"])
    near_cool = float(cfg.get("near_cooldown_hours") or 0) * HOUR
    page = cfg.get("page_url", "")
    for r in rows:
        coin = r["s"]
        rule = rule_for(coin, rules)
        s = st.setdefault(coin, {})
        new_coin = "side" not in s
        d = r["d"]
        # live side with hysteresis
        side = s.get("side")
        if side is None:
            side = 1 if d >= 0 else -1
        elif side < 0 and d > buf:
            side = 1
        elif side > 0 and d < -buf:
            side = -1
        prev_side = s.get("side")
        s["side"] = side
        link = f' · <a href="{page}#c={coin}">wykres</a>' if page else ""
        if not rule or arm_only or new_coin:
            s["zone"] = "near" if rule and rule["near_pct"] is not None and abs(d) <= rule["near_pct"] else "far"
            s["close_side"] = r["side"]
            continue
        head = f"<b>{html.escape(coin)}</b> {fmt_price(r['p'])}"
        ema_txt = f"EMA{cfg['period']} {fmt_price(r['e'])}"
        # crossing (live, during the day)
        if rule["cross"] and rule["confirm"] == "live" and prev_side is not None and side != prev_side:
            up = side > 0
            if rule["direction"] in ("both", "up" if up else "down") and now - s.get("cross_at", 0) >= cool:
                arrow = "🔼 przeciął w górę" if up else "🔽 przeciął w dół"
                msgs.append(f"{arrow} EMA{cfg['period']}: {head} ({d:+.2f}%, {ema_txt}){link}")
                s["cross_at"] = now
        # crossing confirmed by the daily close
        if rule["cross"] and rule["confirm"] == "close" and daily_done:
            if s.get("close_side") is not None and r["side"] != s["close_side"]:
                up = r["side"] > 0
                if rule["direction"] in ("both", "up" if up else "down"):
                    word = "nad" if up else "pod"
                    msgs.append(f"{'✅' if up else '❌'} zamknął dzień {word} EMA{cfg['period']}: {head} "
                                f"(zamknięcie {fmt_price(r['c'])}, {ema_txt}){link}")
        if daily_done:
            s["close_side"] = r["side"]
        # approaching
        np_ = rule["near_pct"]
        if np_ is not None:
            if abs(d) <= np_ and s.get("zone") != "near":
                if now - s.get("near_at", 0) >= near_cool:
                    where = "od dołu" if d < 0 else "od góry"
                    msgs.append(f"⚠️ zbliża się do EMA{cfg['period']} {where}: {head} ({d:+.2f}%, {ema_txt}){link}")
                    s["near_at"] = now
                s["zone"] = "near"
            elif abs(d) > np_ * rearm:
                s["zone"] = "far"
    return msgs


# ── computations ─────────────────────────────────────────────
def compute(candles, sym_base, prices, vols, cfg, rules):
    """→ (rows, excluded, per-coin series {base: (times, closes, emas)})."""
    period, min_days = int(cfg["period"]), int(cfg["min_days"])
    min_vol = float(cfg.get("min_volume_usd") or 0)
    rows, excluded, series = [], [], {}
    a = 2 / (period + 1)
    excl = ALWAYS_EXCLUDE | {e.upper() for e in cfg.get("exclude") or []}
    for sym, base in sym_base.items():
        if base in excl:
            continue
        cs = candles.get(sym) or []
        if len(cs) < min_days:
            excluded.append([base, len(cs)])
            continue
        vol = vols.get(sym)
        if min_vol and vol is not None and vol < min_vol:
            continue
        times = [t for t, _ in cs]
        closes = [c for _, c in cs]
        emas = ema_series(closes, period)
        side, since, idx = streak(closes, emas)
        p = prices.get(sym) or closes[-1]
        e_live = a * p + (1 - a) * emas[-1]          # today's candle counted with the current price
        rule = rule_for(base, rules)
        rows.append({
            "s": base, "sym": sym, "p": p, "e": e_live, "d": (p / e_live - 1) * 100,
            "c": closes[-1], "ec": emas[-1], "side": side, "since": since,
            "cross_t": times[idx] if idx is not None else None,
            "vol": vol, "days": len(cs),
            "alert": ({"cross": rule["cross"], "near": rule["near_pct"]} if rule else None),
        })
        series[base] = (times, closes, emas)
    rows.sort(key=lambda r: abs(r["d"]))
    excluded.sort(key=lambda x: -x[1])
    return rows, excluded, series


def delisted_series(delisted, cfg):
    """delisted.json {symbol: {"b": base, "c": [[t, close]...]}} → {"D:<symbol>": (times, closes, emas)}
    for pairs no longer on Binance (only those with ≥ min_days, after the same exclusions)."""
    period, min_days = int(cfg["period"]), int(cfg["min_days"])
    excl = ALWAYS_EXCLUDE | {e.upper() for e in cfg.get("exclude") or []}
    out = {}
    for sym, rec in (delisted or {}).items():
        cs = rec.get("c") or []
        if rec.get("b") in excl or len(cs) < min_days:
            continue
        times = [t for t, _ in cs]
        closes = [c for _, c in cs]
        out["D:" + sym] = (times, closes, ema_series(closes, period))
    return out


def breadth(series, cfg, now, extra=None):
    """% of coins (with ≥ min_days of history at that day) closing above their EMA, per day.
    extra = series of delisted pairs (counted on the days they were trading)."""
    min_days = int(cfg["min_days"])
    start = now - now % DAY - int(cfg["breadth_days"]) * DAY if int(cfg.get("breadth_days") or 0) else 0
    cnt, above = {}, {}
    for times, closes, emas in list(series.values()) + list((extra or {}).values()):
        for i in range(min_days - 1, len(times)):
            t = times[i]
            if t < start:
                continue
            cnt[t] = cnt.get(t, 0) + 1
            if closes[i] >= emas[i]:
                above[t] = above.get(t, 0) + 1
    min_n = int(cfg.get("breadth_min_coins", 10))
    return [[t, round(above.get(t, 0) / n * 100, 2), n] for t, n in sorted(cnt.items()) if n >= min_n]


# ── publishing (branch `ema`) ────────────────────────────────
def _round(v, sig=6):
    return None if v is None else float(f"{v:.{sig}g}")


def write_outputs(pub_dir, payload, series, cfg, write_hist):
    os.makedirs(pub_dir, exist_ok=True)
    _write(os.path.join(pub_dir, "ema.json"), payload)
    if write_hist:
        hdir = os.path.join(pub_dir, "hist")
        os.makedirs(hdir, exist_ok=True)
        keep = int(cfg.get("chart_days") or 0)
        names = set()
        for base, (times, closes, emas) in series.items():
            fn = f"{base}.json"
            names.add(fn)
            if keep:
                times, closes, emas = times[-keep:], closes[-keep:], emas[-keep:]
            pts = [[t, _round(c), _round(e)] for t, c, e in zip(times, closes, emas)]
            _write(os.path.join(hdir, fn), {"s": base, "p": int(cfg["period"]), "d": pts})
        for fn in os.listdir(hdir):
            if fn.endswith(".json") and fn not in names:
                os.remove(os.path.join(hdir, fn))


def _write(path, obj):
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


def git_publish(pub_dir, remote, branch, run=subprocess.run):
    """One root commit (amended every time) force-pushed to `branch` — the branch never grows."""
    def g(*args, check=True):
        return run(["git", "-C", pub_dir, *args], check=check, capture_output=True, text=True)
    if not os.path.isdir(os.path.join(pub_dir, ".git")):
        g("init", "-q")
        g("config", "user.name", "ema-monitor-pi")
        g("config", "user.email", "ema-monitor@users.noreply.github.com")
    g("add", "-A")
    has_head = g("rev-parse", "--verify", "HEAD", check=False).returncode == 0
    msg = "ema: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if has_head:
        g("commit", "-q", "--amend", "-m", msg)
    else:
        g("commit", "-q", "-m", msg)
    r = run(["git", "-C", pub_dir, "push", "-q", "-f", remote, f"HEAD:refs/heads/{branch}"],
            capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("git push: " + (r.stderr or r.stdout).strip().replace(remote, "<remote>")[:300])


def cleanup_git(pub_dir, run=subprocess.run):
    for args in (["reflog", "expire", "--expire=now", "--all"], ["gc", "-q", "--prune=now"]):
        run(["git", "-C", pub_dir, *args], capture_output=True, text=True)


# ── main run ─────────────────────────────────────────────────
def load_cfg(path):
    with open(path, encoding="utf-8") as f:
        full = yaml.safe_load(f) or {}
    cfg = dict(DEFAULTS)
    cfg.update(full.get("ema") or {})
    cfg["alerts"] = cfg.get("alerts") or []
    fcfg = full.get("fib") or {}
    pcfg = dict(F.PROPOSAL_DEFAULTS)
    pcfg.update(fcfg.get("proposals") or {})
    cfg["fib"] = {"near_pct": float(fcfg.get("near_pct", 2) or 2), "setups": fcfg.get("setups") or [],
                  "proposals": pcfg}
    cfg["telegram"] = full.get("telegram") or {}
    return cfg


def load_env(path):
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def load_bot_state(state_dir, st=None):
    """bot.json (written by bot.py): Telegram setups, mute. Before the bot's first run: old state.json keys."""
    b = _read(os.path.join(state_dir, "bot.json"), None)
    if b is None:
        b = {"fib_user": (st or {}).get("fib_user") or []}
    return b


def run(cfg, state_dir, now=None, client=None, telegram=None, publish=True, remote=None,
        git=subprocess.run, check_only=False, hl=F.hyperliquid_mids):
    now = int(now or time.time())
    os.makedirs(state_dir, exist_ok=True)
    cpath, spath = os.path.join(state_dir, "candles.json"), os.path.join(state_dir, "state.json")
    candles = _read(cpath, {})
    st = _read(spath, {})
    hlpath = os.path.join(state_dir, "hl.json")
    hld = _read(hlpath, {})
    hl_days = int((cfg.get("fib") or {}).get("proposals", F.PROPOSAL_DEFAULTS).get("hl_days", 400))
    hl_changed = False
    cl = client or Binance()
    today = now - now % DAY
    info = {}

    # once per UTC day: universe, candles, volumes
    daily_due = st.get("daily_day") != today or not st.get("symbols")
    dpath = os.path.join(state_dir, "delisted.json")
    delisted = _read(dpath, {})
    delisted_changed = False
    if daily_due:
        sym_base = universe(cl.exchange_info(), cfg)
        old_base = st.get("symbols") or {}
        st["symbols"] = sym_base
        excl = ALWAYS_EXCLUDE | {e.upper() for e in cfg.get("exclude") or []}
        for k in [k for k in candles if k not in sym_base]:
            # pair gone from Binance → keep its history for market breadth (no survivorship bias)
            b = old_base.get(k) or (k[:-len(cfg["quote"])] if k.endswith(cfg["quote"]) else None)
            if b and b not in excl and candles[k]:
                d = {t: c for t, c in (delisted.get(k) or {}).get("c") or []}
                d.update({t: c for t, c in candles[k]})
                delisted[k] = {"b": b, "c": [[t, c] for t, c in sorted(d.items())], "src": "ema_monitor",
                               "gone": today}
                delisted_changed = True
            del candles[k]
        for k in [k for k in delisted if k in sym_base]:     # pair is back on the exchange
            del delisted[k]
            delisted_changed = True
        for k in [k for k in hld if k not in sym_base]:
            del hld[k]
            hl_changed = True
        fetched = 0
        log.info("Pobieram świece dzienne dla %d par (pierwszy raz trwa kilka minut)…", len(sym_base))
        for n_sym, sym in enumerate(sorted(sym_base), 1):
            if n_sym % 50 == 0:
                log.info("  %d/%d par", n_sym, len(sym_base))
            old = candles.get(sym) or []
            if old:
                missing = (today - old[-1][0]) // DAY       # days after the last stored closed candle
                if missing <= 1:
                    continue
                limit = min(1000, missing + 2)
            else:
                limit = 1000
            try:
                rows_k = cl.klines(sym, limit)
            except Exception as e:  # noqa: BLE001
                log.warning("%s: %s", sym, e)
                continue
            new = closed_candles(rows_k, now)
            candles[sym] = merge(old, new, int(cfg["keep_days"]))
            if sym in hld or not old:            # known coin (or brand-new one): extend high/low too
                hld[sym] = _merge_hl(hld.get(sym), closed_hl(rows_k, now), hl_days)
                hl_changed = True
            fetched += 1
        try:
            st["volumes"] = cl.volumes()
        except Exception as e:  # noqa: BLE001
            log.warning("wolumen 24h: %s", e)
        st["daily_day"] = today
        info["fetched"] = fetched
        log.info("Dzienne odświeżenie: %d par, pobrano świece dla %d", len(sym_base), fetched)
    sym_base = st["symbols"]

    # fill in older candles (back to the Binance listing), a limited number of requests per run
    backfilled = 0
    if not check_only and int(cfg.get("history_pages_per_run") or 0) > 0:
        full = set(st.get("full_hist") or [])
        todo = [s for s in sorted(sym_base) if s not in full and candles.get(s)]
        if todo:
            log.info("Starsza historia: zostało %d par, w tym uruchomieniu do %d paczek",
                     len(todo), int(cfg["history_pages_per_run"]))
        for sym in todo[:int(cfg["history_pages_per_run"])]:
            first = candles[sym][0][0]
            try:
                rows = cl.klines(sym, 1000, end_ms=first * 1000 - 1)
            except Exception as e:  # noqa: BLE001
                log.warning("%s (starsza historia): %s", sym, e)
                continue
            older = closed_candles(rows, now)
            if older:
                candles[sym] = merge(older, candles[sym], int(cfg["keep_days"]))
                backfilled += 1
            if len(rows) < 1000:
                full.add(sym)          # reached the listing date
        st["full_hist"] = sorted(full & set(sym_base))
        info["history_done"] = f"{len(st['full_hist'])}/{len(sym_base)}"
        if backfilled:
            log.info("Starsza historia: dopisano %d paczek, kompletne %s", backfilled, info["history_done"])

    # high/low of the last ~hl_days days for Fibo proposals (one request per coin, capped per run)
    if not check_only:
        need = [s for s in sorted(sym_base) if candles.get(s) and len(candles[s]) >= int(cfg["min_days"])
                and len(hld.get(s) or []) < min(hl_days, len(candles[s])) - 2]
        for sym in need[:int(cfg.get("history_pages_per_run") or 100)]:
            try:
                hld[sym] = _merge_hl(hld.get(sym), closed_hl(cl.klines(sym, min(1000, hl_days + 2)), now), hl_days)
                hl_changed = True
            except Exception as e:  # noqa: BLE001
                log.warning("%s (high/low): %s", sym, e)
        if need:
            info["hl_missing"] = max(0, len(need) - int(cfg.get("history_pages_per_run") or 100))

    prices = cl.prices()
    rows, excluded, series = compute(candles, sym_base, prices, st.get("volumes") or {}, cfg, cfg["alerts"])
    for r in rows:                       # RSI on the open 3-day / weekly candle, with the current price
        times_r, closes_r, _ = series[r["s"]]
        r["r3"] = rsi_live(times_r, closes_r, r["p"], now, "d3", cfg)
        r["rw"] = rsi_live(times_r, closes_r, r["p"], now, "w", cfg)

    # alerts (first run ever: arm silently)
    ast = st.setdefault("alerts", {})
    first = not st.get("armed")
    msgs = check_alerts(rows, cfg["alerts"], ast, cfg, now, daily_done=daily_due, arm_only=first or check_only)
    st["armed"] = True

    # Fibonacci setups: config + Telegram (/fib is handled by bot.py, stored in bot.json)
    bst = load_bot_state(state_dir, st)
    fcfg = cfg.get("fib") or {"near_pct": 2, "setups": []}
    cfg_setups = F.from_config(fcfg["setups"])
    user_setups = bst.get("fib_user") or []
    fib_coins = {x["coin"] for x in cfg_setups + user_setups}
    fprices = F.coin_prices(fib_coins, prices, cfg["quote"], hl=hl)
    setups = cfg_setups + user_setups
    fmsgs = F.check(setups, fprices, st.setdefault("fib_state", {}), fcfg["near_pct"], arm_only=check_only)
    mute_until = bst.get("mute_until")

    # automatic Fibo proposals: raw candidates once a day (or when high/low data changed), live status every run
    pcfg = fcfg.get("proposals") or F.PROPOSAL_DEFAULTS
    listed = {r["s"]: r["sym"] for r in rows}
    if daily_due or hl_changed or "fib_cands" not in st:
        cands = []
        for base, sym in listed.items():
            cands += F.candidates(base, hld.get(sym) or [], pcfg)
        st["fib_cands"] = cands
    props = F.proposals(st.get("fib_cands") or [], {r["s"]: r["p"] for r in rows}, pcfg)
    for pr in props:
        pr["cmd"] = F.command_for(pr)
        pr["chart"] = pr["coin"] in series

    if (msgs or fmsgs) and not check_only:
        if alerts.is_muted(mute_until, now):
            log.info("Alerty wyciszone (/cisza) — pomijam %d", len(msgs) + len(fmsgs))
            info["muted_alerts"] = len(msgs) + len(fmsgs)
        else:
            tg = telegram or alerts.Telegram(tg_cfg=cfg.get("telegram") or {})
            if msgs:
                header = f"📈 <b>EMA{cfg['period']}</b> (Binance, świeca dzienna)"
                for i in range(0, len(msgs), 25):
                    tg.post("market", "\n".join([header, ""] + msgs[i:i + 25]))
            if fmsgs:
                tg.post("market", "\n".join(["🎯 <b>Fibo</b>", ""] + fmsgs))

    above = sum(1 for r in rows if r["d"] >= 0)
    try:
        d_mtime = int(os.path.getmtime(dpath))
    except OSError:
        d_mtime = None
    d_new = delisted_changed or d_mtime != st.get("delisted_mtime")      # e.g. after delisted.py
    rsi_stale = (st.get("rsi") or {}).get("sig") != rsi_sig(cfg)
    if daily_due or backfilled or d_new or not st.get("breadth") or rsi_stale:
        dser = delisted_series(delisted, cfg)
        br = breadth(series, cfg, now, extra=dser)
        st["breadth_delisted"] = len(dser)
        st["rsi"] = {"sig": rsi_sig(cfg), "d3": rsi_extremes(series, cfg, now, "d3", extra=dser),
                     "w": rsi_extremes(series, cfg, now, "w", extra=dser)}
    else:
        br = st["breadth"]
    st["breadth"] = br
    payload = {
        "updated": now, "daily_at": st.get("daily_day"), "period": int(cfg["period"]),
        "min_days": int(cfg["min_days"]), "source": f"Binance spot */{cfg['quote']}",
        "above": above, "total": len(rows),
        "coins": [{k: (_round(v) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
        "excluded": excluded, "breadth": br,
        "rules": cfg["alerts"], "near_default": None,
        "mute_until": mute_until if alerts.is_muted(mute_until, now) else None,
        "history_full": len(st.get("full_hist") or []), "pairs": len(sym_base),
        # pairs delisted from Binance counted in the breadth history (0 = only coins trading today)
        "breadth_delisted": int(st.get("breadth_delisted") or 0),
        # RSI on 3-day / weekly candles: history = closed candles (with delisted pairs), now = live (coins trading today)
        "rsi": {"period": int(cfg["rsi_period"]), "low": cfg["rsi_low"], "high": cfg["rsi_high"],
                "min_bars": int(cfg["rsi_min_bars"]), "d3_shift": int(cfg["rsi_d3_shift"]),
                "d3": st["rsi"]["d3"], "w": st["rsi"]["w"], "now": rsi_now(rows, cfg)},
    }
    fib_payload = {"updated": now, "near_pct": fcfg["near_pct"], "zone": list(F.ZONE),
                   "setups": F.publish_rows(setups, set(series)),
                   "proposals": [{k: (_round(v) if isinstance(v, float) else v) for k, v in pr.items()} for pr in props],
                   "proposal_cfg": pcfg, "candidates": len(st.get("fib_cands") or [])}
    info.update({"pairs": len(sym_base), "coins": len(rows), "excluded": len(excluded), "above": above,
                 "alerts_sent": 0 if check_only else len(msgs) + len(fmsgs), "calls": cl.calls,
                 "fib_setups": len(setups)})

    if not check_only:
        if daily_due or backfilled:      # candles change only once a day (or while filling in history)
            _write(cpath, candles)
        if hl_changed:
            _write(hlpath, hld)
        if delisted_changed:
            _write(dpath, delisted)
        try:
            st["delisted_mtime"] = int(os.path.getmtime(dpath))
        except OSError:
            st["delisted_mtime"] = None
        due = daily_due or now - st.get("published_at", 0) >= float(cfg["publish_minutes"]) * 60 - 30
        if backfilled:
            st["hist_dirty"] = True              # EMA changed (longer warm-up) → rewrite chart files
        if publish and due:
            pub = os.path.join(state_dir, "pub")
            write_hist = (daily_due or st.get("hist_dirty") or st.get("hist_version") != HIST_VERSION
                          or not os.path.isdir(os.path.join(pub, "hist")))
            write_outputs(pub, payload, series, cfg, write_hist=write_hist)
            _write(os.path.join(pub, "fib.json"), fib_payload)
            st["hist_dirty"] = False
            if write_hist:
                st["hist_version"] = HIST_VERSION
            if remote:
                try:
                    git_publish(pub, remote, cfg["branch"], run=git)
                    st["published_at"] = now
                    if daily_due:
                        cleanup_git(pub, run=git)
                    info["published"] = True
                except Exception as e:  # noqa: BLE001
                    log.error("Publikacja: %s", e)
                    info["publish_error"] = str(e)
        _write(spath, st)
    info["fib"] = fib_payload["setups"]
    return info, rows, excluded, msgs + fmsgs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "check"])
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--config", default=os.path.join(here, "config.yaml"))
    ap.add_argument("--state", default=os.path.expanduser("~/.ema-monitor"))
    ap.add_argument("--env-file", default="~/.scanner_env")
    ap.add_argument("--token-file", default="~/.scanner_token")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--test-telegram", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_env(a.env_file)
    cfg = load_cfg(a.config)
    remote = None
    try:
        with open(os.path.expanduser(a.token_file), encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            remote = f"https://x-access-token:{tok}@github.com/{cfg['repo']}.git"
    except FileNotFoundError:
        log.warning("Brak tokenu GitHub (%s) — bez publikacji na stronę", a.token_file)

    if a.mode == "check":
        # check uses a temporary copy of the state so it never disturbs the cron job
        import shutil
        tmp = tempfile.mkdtemp(prefix="ema-check-")
        for fn in ("candles.json", "state.json", "delisted.json"):
            src = os.path.join(a.state, fn)
            if os.path.exists(src):
                shutil.copy(src, tmp)
        info, rows, excluded, _ = run(cfg, tmp, check_only=True)
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"\nPary {cfg['quote']} na Binance (po odfiltrowaniu stabli/fiat): {info['pairs']}")
        print(f"Coiny z EMA{cfg['period']} (≥ {cfg['min_days']} dni historii): {info['coins']}, "
              f"pominięte (za krótka historia): {info['excluded']}")
        print(f"Nad EMA: {info['above']} z {info['coins']}  ·  zapytań do Binance: {info['calls']}")
        print("\nNajbliżej przecięcia:")
        for r in rows[:12]:
            print(f"  {r['s']:<8} cena {fmt_price(r['p']):>12}  EMA {fmt_price(r['e']):>12}  {r['d']:+6.2f}%  "
                  f"{'nad' if r['d'] >= 0 else 'pod'} od {r['since']} {'dnia' if r['since'] == 1 else 'dni'}")
        names = {r["s"] for r in rows}
        for rl in cfg["alerts"]:
            if isinstance(rl.get("coins"), list):
                miss = [c for c in rl["coins"] if c.upper() not in names]
                if miss:
                    print(f"\nUwaga: z reguły alertów nie ma na liście: {', '.join(miss)} "
                          "(brak pary USDT na Binance albo za krótka historia)")
        if info.get("fib"):
            print("\nSetupy Fibo:")
            for r in info["fib"]:
                stt = F.STATUS_PL.get(r["status"], "brak ceny")
                print(f"  [{r['id']}] {r['coin']} {r['dir']}  0.75 = {F.fmt(r['l75'])}  cena {F.fmt(r['price'])}  {stt}")
        print(f"\nTelegram: {'skonfigurowany' if os.environ.get('TELEGRAM_BOT_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID') else 'BRAK danych w ~/.scanner_env'}")
        print(f"GitHub (publikacja): {'token jest' if remote else 'BRAK tokenu'}")
        if a.test_telegram:
            tg = alerts.Telegram(tg_cfg=cfg["telegram"])
            ok = tg.post("system", "✅ Test z Orange Pi — wiadomości do Ciebie (priv) działają.")
            print("Wiadomość testowa na priv:", "wysłana" if ok else "NIE wysłana (sprawdź token i chat id)")
            if tg.target("market")[0] != tg.chat_id:
                ok = tg.post("market", "✅ Test z Orange Pi — alerty i raporty trafiają do tego wątku.")
                print("Wiadomość testowa do grupy:", "wysłana" if ok else
                      "NIE wysłana (sprawdź group_chat_id / group_thread_id i czy bot jest w grupie)")
            else:
                print("Grupa: nieustawiona (telegram.group_chat_id) — alerty idą na priv")
        return 0
    results = {"Obliczenia EMA na Orange Pi (Binance)": None, "Publikacja EMA/Fibo na stronę": None}
    msgs = []
    try:
        info, _, _, msgs = run(cfg, a.state, publish=not a.no_publish, remote=remote)
        results["Publikacja EMA/Fibo na stronę"] = info.get("publish_error")
        if msgs or info.get("publish_error") or info.get("fetched") is not None:
            log.info("%s", info)
    except Exception as e:  # noqa: BLE001
        log.exception("EMA run")
        results["Obliczenia EMA na Orange Pi (Binance)"] = f"{type(e).__name__}: {e}"
    report_health(a.state, results, cfg)
    return 0


def report_health(state_dir, results, cfg, now=None, telegram=None):
    """Failures of the Pi itself → admin (private): first failure, reminder, recovery."""
    now = int(now or time.time())
    path = os.path.join(state_dir, "health.json")
    hst = _read(path, {})
    hrs = float((cfg.get("telegram") or {}).get("health_reminder_hours", 12) or 12)
    # report a failure only after 3 runs in a row (~15 min) — single network blips are normal
    streak = hst.setdefault("_streak", {})
    effective = {}
    for src, err in results.items():
        streak[src] = streak.get(src, 0) + 1 if err else 0
        failing = ((hst.get("health") or {}).get(src) or {}).get("failing")
        effective[src] = err if (err and (failing or streak[src] >= 3)) else None
    msgs = alerts.health_messages(hst, effective, now, hrs)
    if msgs:
        tg = telegram or alerts.Telegram(tg_cfg=cfg.get("telegram") or {})
        for m in msgs:
            tg.post("system", m)
    os.makedirs(state_dir, exist_ok=True)
    _write(path, hst)
    return msgs


if __name__ == "__main__":
    sys.exit(main())
