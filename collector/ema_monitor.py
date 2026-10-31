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

log = logging.getLogger("ema")
DAY = 86400
HOUR = 3600

DEFAULTS = {
    "period": 200,
    "quote": "USDT",
    "min_days": 300,
    "min_volume_usd": 0,
    "keep_days": 1500,
    "breadth_days": 1095,
    "breadth_min_coins": 10,
    "chart_days": 1000,
    "publish_minutes": 15,
    "cross_buffer_pct": 0.5,
    "cooldown_hours": 12,
    "near_rearm": 1.5,
    "exclude": [],
    "alerts": [],
    "repo": "cryptoloser8-coder/scanner",
    "branch": "ema",
    "page_url": "https://cryptoloser8-coder.github.io/scanner/ema.html",
}
# stablecoins, fiat and gold tokens — never part of the EMA universe
ALWAYS_EXCLUDE = {
    "USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USDE", "PYUSD", "USD1", "RLUSD", "BFUSD",
    "XUSD", "USDS", "AEUR", "EURI", "EUR", "GBP", "AUD", "BRL", "TRY", "JPY", "PLN", "RON", "ZAR", "UAH",
    "ARS", "MXN", "COP", "CZK", "PAXG", "XAUT",
}
LEVERAGED = ("UP", "DOWN", "BULL", "BEAR")


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

    def klines(self, symbol, limit):
        return self._get("/api/v3/klines", {"symbol": symbol, "interval": "1d", "limit": int(limit)})

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


def merge(old, new, keep):
    d = {t: c for t, c in old or []}
    d.update({t: c for t, c in new})
    return sorted(d.items())[-keep:]


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
                where = "od dołu" if d < 0 else "od góry"
                msgs.append(f"⚠️ zbliża się do EMA{cfg['period']} {where}: {head} ({d:+.2f}%, {ema_txt}){link}")
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
    for sym, base in sym_base.items():
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


def breadth(series, cfg, now):
    """% of coins (with ≥ min_days of history at that day) closing above their EMA, per day."""
    min_days = int(cfg["min_days"])
    start = now - now % DAY - int(cfg["breadth_days"]) * DAY
    cnt, above = {}, {}
    for times, closes, emas in series.values():
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
        keep = int(cfg["chart_days"])
        names = set()
        for base, (times, closes, emas) in series.items():
            fn = f"{base}.json"
            names.add(fn)
            pts = [[t, _round(c), _round(e)] for t, c, e in zip(times[-keep:], closes[-keep:], emas[-keep:])]
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


def run(cfg, state_dir, now=None, client=None, telegram=None, publish=True, remote=None,
        git=subprocess.run, check_only=False):
    now = int(now or time.time())
    os.makedirs(state_dir, exist_ok=True)
    cpath, spath = os.path.join(state_dir, "candles.json"), os.path.join(state_dir, "state.json")
    candles = _read(cpath, {})
    st = _read(spath, {})
    cl = client or Binance()
    today = now - now % DAY
    info = {}

    # once per UTC day: universe, candles, volumes
    daily_due = st.get("daily_day") != today or not st.get("symbols")
    if daily_due:
        sym_base = universe(cl.exchange_info(), cfg)
        st["symbols"] = sym_base
        for k in [k for k in candles if k not in sym_base]:
            del candles[k]
        fetched = 0
        for sym in sorted(sym_base):
            old = candles.get(sym) or []
            if old:
                missing = (today - old[-1][0]) // DAY       # days after the last stored closed candle
                if missing <= 1:
                    continue
                limit = min(1000, missing + 2)
            else:
                limit = 1000
            try:
                new = closed_candles(cl.klines(sym, limit), now)
            except Exception as e:  # noqa: BLE001
                log.warning("%s: %s", sym, e)
                continue
            candles[sym] = merge(old, new, int(cfg["keep_days"]))
            fetched += 1
        try:
            st["volumes"] = cl.volumes()
        except Exception as e:  # noqa: BLE001
            log.warning("wolumen 24h: %s", e)
        st["daily_day"] = today
        info["fetched"] = fetched
        log.info("Dzienne odświeżenie: %d par, pobrano świece dla %d", len(sym_base), fetched)
    sym_base = st["symbols"]

    prices = cl.prices()
    rows, excluded, series = compute(candles, sym_base, prices, st.get("volumes") or {}, cfg, cfg["alerts"])

    # alerts (first run ever: arm silently)
    ast = st.setdefault("alerts", {})
    first = not st.get("armed")
    msgs = check_alerts(rows, cfg["alerts"], ast, cfg, now, daily_done=daily_due, arm_only=first or check_only)
    st["armed"] = True
    if msgs and not check_only:
        tg = telegram or alerts.Telegram()
        header = f"📈 <b>EMA{cfg['period']}</b> (Binance, świeca dzienna)"
        for i in range(0, len(msgs), 25):
            tg.send("\n".join([header, ""] + msgs[i:i + 25]))

    above = sum(1 for r in rows if r["d"] >= 0)
    br = breadth(series, cfg, now) if daily_due or not st.get("breadth") else st["breadth"]
    st["breadth"] = br
    payload = {
        "updated": now, "daily_at": st.get("daily_day"), "period": int(cfg["period"]),
        "min_days": int(cfg["min_days"]), "source": f"Binance spot */{cfg['quote']}",
        "above": above, "total": len(rows),
        "coins": [{k: (_round(v) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
        "excluded": excluded, "breadth": br,
        "rules": cfg["alerts"], "near_default": None,
    }
    info.update({"pairs": len(sym_base), "coins": len(rows), "excluded": len(excluded), "above": above,
                 "alerts_sent": 0 if check_only else len(msgs), "calls": cl.calls})

    if not check_only:
        _write(cpath, candles)
        due = daily_due or now - st.get("published_at", 0) >= float(cfg["publish_minutes"]) * 60 - 30
        if publish and due:
            pub = os.path.join(state_dir, "pub")
            write_outputs(pub, payload, series, cfg, write_hist=daily_due or not os.path.isdir(os.path.join(pub, "hist")))
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
    return info, rows, excluded, msgs


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
        for fn in ("candles.json", "state.json"):
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
        print(f"\nTelegram: {'skonfigurowany' if os.environ.get('TELEGRAM_BOT_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID') else 'BRAK danych w ~/.scanner_env'}")
        print(f"GitHub (publikacja): {'token jest' if remote else 'BRAK tokenu'}")
        if a.test_telegram:
            ok = alerts.Telegram().send("✅ Test EMA200 z Orange Pi — powiadomienia działają.")
            print("Wiadomość testowa:", "wysłana" if ok else "NIE wysłana (sprawdź token i chat id)")
        return 0
    info, _, _, msgs = run(cfg, a.state, publish=not a.no_publish, remote=remote)
    if msgs or info.get("publish_error") or info.get("fetched") is not None:
        log.info("%s", info)
    return 0


if __name__ == "__main__":
    sys.exit(main())
