"""Offline tests: python -m pytest collector/tests -q"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import alerts  # noqa: E402
import main  # noqa: E402
import series as S  # noqa: E402
from coinalyze import RateLimiter, norm_base, select_markets  # noqa: E402
from tradingview import TradingView, split_frames  # noqa: E402

NOW = 1_790_000_000  # fixed "now"
H, D = 3600, 86400


class FakeCoinalyze:
    BASES = {"BTC": 30e9, "ETH": 15e9, "SOL": 5e9, "PEPE": 1e9, "DUST": 1e6, "XAU": 20e9}
    btc_daily_from = None  # simulate exchanges' history starting later

    def __init__(self):
        self.calls_made = 0
        self.markets = []
        for base, oi in self.BASES.items():
            for ex, code in (("Binance", "A"), ("Bybit", "6"), ("Kraken", "K"), ("Hyperliquid", "H")):
                b = "1000PEPE" if base == "PEPE" and code == "A" else base
                self.markets.append({"symbol": f"{b}USDT_PERP.{code}", "exchange": code,
                                     "base_asset": b, "is_perpetual": True, "_oi": oi / 3})
        self.markets.append({"symbol": "BTCUSDT_241227.A", "exchange": "A", "base_asset": "BTC",
                             "is_perpetual": False, "_oi": 1e9})
        self.missing = set()  # symbols that return no data (simulated gaps)

    def exchanges(self):
        return [{"name": "Binance", "code": "A"}, {"name": "Bybit", "code": "6"},
                {"name": "Kraken", "code": "K"}, {"name": "Hyperliquid", "code": "H"}]

    def future_markets(self):
        return self.markets

    def _oi(self, sym, t):
        m = next(m for m in self.markets if m["symbol"] == sym)
        return m["_oi"] * (1 + 0.1 * math.sin(t / 50000))

    def open_interest(self, symbols, progress=None):
        self.calls_made += len(symbols)
        return {s: self._oi(s, NOW) for s in symbols}

    def oi_history(self, symbols, interval, frm, to, progress=None):
        self.calls_made += len(symbols)
        step = H if interval == "1hour" else D
        out = {}
        for s in symbols:
            if s in self.missing:
                out[s] = {}
                continue
            t0 = frm - frm % step
            out[s] = {t: self._oi(s, t) for t in range(t0, int(to) + 1, step) if t >= frm or step == D}
            if step == D and self.btc_daily_from and not s.startswith("SOL"):
                out[s] = {t: v for t, v in out[s].items() if t >= self.btc_daily_from}
        return out


    # ── liquidations / funding / price ──
    def _hist(self, symbols, interval, frm, to, fn):
        self.calls_made += len(symbols)
        step = H if interval == "1hour" else D
        out = {}
        for s in symbols:
            if s in self.missing:
                continue  # failed batch → symbol absent
            t0 = frm - frm % step
            out[s] = {t: fn(s, t) for t in range(t0, int(to) + 1, step) if fn(s, t) is not None}
        return out

    def liquidation_history(self, symbols, interval, frm, to, progress=None):
        def fn(s, t):
            k = t // (H if interval == "1hour" else D)
            if k % 3 == 0:
                return None  # no liquidations in this candle → Coinalyze omits it
            scale = 1.0 if interval == "1hour" else 24.0
            return (1e6 * scale, 5e5 * scale)
        return self._hist(symbols, interval, frm, to, fn)

    def funding_history(self, symbols, interval, frm, to, progress=None):
        # percent per funding interval: 0.01%/8h on CEXes, 0.00125%/1h on Hyperliquid (both ≈ 10.95%/yr)
        return self._hist(symbols, interval, frm, to, lambda s, t: 0.00125 if s.endswith(".H") else 0.01)

    def price_history(self, symbols, interval, frm, to, progress=None):
        return self._hist(symbols, interval, frm, to, lambda s, t: 100000.0 if s.startswith("BTC") else 4000.0)

    def history(self, path, symbols, interval, frm, to, fields, usd=False, progress=None):
        # /ohlcv-history (v, bv, c) — ceny coinów z watchlisty (poprawka 67)
        val = {"v": 1.0, "bv": 0.5, "c": 25.0, "h": 26.0, "l": 24.0}
        f = (fields,) if isinstance(fields, str) else tuple(fields)
        return self._hist(symbols, interval, max(frm, 1_600_000_000), to, lambda s, t: tuple(val[k] for k in f))


class FakeTV:
    def __init__(self, fail=False):
        self.fail = fail
        self.requests = []

    def bars(self, symbol, interval, n):
        self.requests.append((symbol, interval, n))
        if self.fail:
            raise RuntimeError("boom")
        step = H if interval == "60" else D
        end = NOW - NOW % step
        base = {"CRYPTOCAP:TOTAL": 3e12, "CRYPTOCAP:TOTAL2": 1.3e12, "CRYPTOCAP:TOTAL3": 0.9e12,
                "CRYPTOCAP:TOTALES": 2.7e12, "CRYPTOCAP:TOTAL3ES": 0.6e12,
                "CRYPTOCAP:BTC.D": 57.0}.get(symbol, 5.0)
        return [(end - i * step, base * (1 + 0.05 * math.sin((end - i * step) / 90000)))
                for i in range(min(n, 3000))][::-1]


CFG = {
    "coinalyze": {"exchanges": ["binance", "BYBIT"], "max_assets": 3, "universe_refresh_hours": 24,
                  "daily_history_start": "2025-01-01"},
    "watchlist": ["SOL", "PEPE"],
    "tradingview": {"symbols": {"total": "CRYPTOCAP:TOTAL", "total2": "CRYPTOCAP:TOTAL2",
                                "total3": "CRYPTOCAP:TOTAL3", "btc_d": "CRYPTOCAP:BTC.D"}},
    "telegram": {"enabled": True, "daily_report_hour_utc": 0},
    "_cg": ["BTC", "ETH", "SOL", "PEPE", "DUST"],
    "levels": [],
    "changes": [],
}


def CG(top):
    return {"BTC", "ETH", "SOL", "PEPE", "DUST"}


def _cfg(**kw):
    c = json.loads(json.dumps(CFG))
    c.update(kw)
    return c


def test_norm_base():
    assert norm_base("kPEPE") == "PEPE"
    assert norm_base("1000PEPE") == "PEPE"
    assert norm_base("1MBABYDOGE") == "BABYDOGE"
    assert norm_base("XBT") == "BTC"
    assert norm_base("1INCH") == "1INCH"


def test_select_markets_filters_exchange_and_perp():
    f = FakeCoinalyze()
    m = select_markets(f.exchanges(), f.markets, ["binance", "Bybit"])
    assert all(not s.endswith(".K") for s in m)
    assert "BTCUSDT_241227.A" not in m
    assert m["1000PEPEUSDT_PERP.A"] == "PEPE"


def test_rate_limiter_waits():
    t = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        t[0] += s
    rl = RateLimiter(40, clock=lambda: t[0], sleep=sleep)
    rl.acquire(20)
    rl.acquire(20)
    rl.acquire(20)  # must wait ~60s
    assert slept and 59 < sum(slept) < 61


def test_coingecko_retries_network_errors():
    import coingecko
    import requests as rq

    class R:
        status_code = 200

        def json(self):
            return [{"symbol": "btc"}, {"symbol": "eth"}]

    class Sess:
        n = 0

        def get(self, *a, **k):
            Sess.n += 1
            if Sess.n == 1:
                raise rq.ConnectionError("aborted")
            return R()
    out = coingecko.crypto_symbols(250, session=Sess(), sleep=lambda s: None)
    assert out == {"BTC", "ETH"} and Sess.n == 2


def test_two_batches_per_minute_and_skip_failed_batch():
    import coinalyze as C

    class Resp:
        def __init__(self, code, data=None):
            self.status_code, self._d, self.headers, self.text = code, data, {}, ""

        def json(self):
            return self._d

    class Sess:
        def __init__(self):
            self.n = 0

        def get(self, url, params=None, headers=None, timeout=None):
            self.n += 1
            syms = params["symbols"].split(",")
            if syms[0] == "BAD":
                return Resp(400)
            return Resp(200, [{"symbol": s, "value": 1.0, "update": 0} for s in syms])

    t = [0.0]

    def sleep(s):
        t[0] += s
    cl = C.Coinalyze("k", session=Sess(), sleep=sleep)
    cl.limiter.clock = lambda: t[0]
    assert cl.batch == 18
    out = cl.open_interest([f"S{i}" for i in range(36)])
    assert len(out) == 36 and t[0] == 0          # 2 batches, no waiting
    out = cl.open_interest(["BAD"] + [f"X{i}" for i in range(17)] + ["OK1"])
    assert "OK1" in out and cl.failed_batches == 1


def test_aggregate_ffill_bridges_gaps():
    sym_base = {"A": "BTC", "B": "BTC"}
    ts = [0, H, 2 * H, 3 * H]
    hist = {"A": {0: 1, H: 1, 2 * H: 1, 3 * H: 1}, "B": {0: 2, 3 * H: 2}}
    pb, last = S.aggregate(hist, sym_base, ts)
    assert pb["BTC"] == {0: 3, H: 3, 2 * H: 3, 3 * H: 3}
    assert last["B"] == [3 * H, 2]
    # beyond the ffill limit the symbol drops out
    pb2, _ = S.aggregate({"A": {}, "B": {}}, sym_base, [10 * H], {"A": [0, 1], "B": [9 * H, 2]})
    assert pb2["BTC"] == {10 * H: 2}


def test_backfill_then_run(tmp_path):
    d = str(tmp_path)
    cz, tv = FakeCoinalyze(), FakeTV()
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    store, msgs, res = main.run(d, _cfg(), now=NOW, backfill=True, coinalyze=cz, tv=tv, telegram=tg, cg_fetch=CG)
    assert res == {"Coinalyze": None, "Ceny watchlisty": None, "TradingView": None}
    # max_assets=3 → BTC, ETH, SOL (DUST and PEPE dropped), Kraken excluded
    uni = store.state["universe"]["symbols"]
    assert set(uni.values()) == {"BTC", "ETH", "SOL"}
    h = store.series["1h"]
    t = max(h["oi_total"])
    assert t == NOW - NOW % H
    assert math.isclose(h["oi_total"][t], h["oi_btc"][t] + h["oi_alts"][t], rel_tol=1e-5)
    assert math.isclose(h["oi_alts"][t], h["oi_eth"][t] + h["oi_others"][t], rel_tol=1e-5)
    assert math.isclose(h["oi_others"][t], h["oi_sol"][t], rel_tol=1e-5)
    assert "oi_pepe" not in h or not h["oi_pepe"]
    assert len(store.series["1d"]["oi_total"]) > 300
    for sid in ("oi_btc_dom", "oi_alts_vs_btc", "lev_btc", "lev_alts", "lev_others"):
        assert h[sid], sid
    assert 0 < h["oi_btc_dom"][t] < 100
    assert any("Backfill" in m for m in msgs)
    files = sorted(os.listdir(d))
    assert files == ["1d.json", "1h.json", "liq_1d.json", "liq_1h.json", "meta.json", "state.json"]   # liq_* = ceny watchlisty
    meta = json.load(open(os.path.join(d, "meta.json")))
    assert "oi_sol" in meta["catalog"] and meta["health"]["Coinalyze"] == "ok"

    # regular run 2h later: only a small window is fetched
    cz2 = FakeCoinalyze()
    tv2 = FakeTV()
    store2, msgs2, res2 = main.run(d, _cfg(), now=NOW + 2 * H, coinalyze=cz2, tv=tv2, telegram=tg, cg_fetch=CG)
    assert res2 == {"Coinalyze": None, "Ceny watchlisty": None, "TradingView": None}
    assert cz2.calls_made == len(uni) + 1  # universe reused, one history pass + cena SOL (1h)
    assert all(n < 20 for (_, iv, n) in tv2.requests)
    assert max(store2.series["1h"]["oi_total"]) == NOW + 2 * H - (NOW + 2 * H) % H
    assert not any("Dzienny raport" in m for m in msgs2)     # old text report removed (zakładka Raporty)


def test_tradfi_excluded_and_daily_trimmed(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    cz = FakeCoinalyze()
    cz.btc_daily_from = NOW - NOW % D - 200 * D
    store, _, res = main.run(d, _cfg(), now=NOW, backfill=True, coinalyze=cz, tv=FakeTV(),
                             telegram=tg, cg_fetch=CG)
    assert res["Coinalyze"] is None
    assert "XAU" not in set(store.state["universe"]["symbols"].values())
    assert "XAU" in store.state["universe"]["excluded"]
    meta = json.load(open(os.path.join(d, "meta.json")))
    assert meta["crypto_filter"].startswith("CoinGecko")
    assert [a for a, _ in meta["universe_assets"]][:2] == ["BTC", "ETH"]
    s = store.series["1d"]["oi_total"]
    assert min(s) == cz.btc_daily_from          # SOL-only days before BTC/ETH data dropped
    # CoinGecko down + no cache → exclude list still removes XAU
    cfg = _cfg()
    cfg["coinalyze"]["exclude_assets"] = ["XAU"]

    def boom(top):
        raise RuntimeError("cg down")
    store2, _, _ = main.run(str(tmp_path / "b"), cfg, now=NOW, backfill=True, coinalyze=FakeCoinalyze(),
                            tv=FakeTV(), telegram=tg, cg_fetch=boom)
    assert "XAU" not in set(store2.state["universe"]["symbols"].values())


def test_leverage_uses_ex_stable_caps(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    cfg = _cfg()
    cfg["tradingview"]["symbols"].update({"totales": "CRYPTOCAP:TOTALES", "total3es": "CRYPTOCAP:TOTAL3ES"})
    store, _, _ = main.run(d, cfg, now=NOW, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(),
                           telegram=tg, cg_fetch=CG)
    h = store.series["1h"]
    t = max(h["lev_others"])
    assert abs(h["stable_mcap"][t] - (h["total"][t] - h["totales"][t])) < 1e3
    assert abs(h["lev_others"][t] - h["oi_others"][t] / h["total3es"][t] * 100) < 1e-6
    exp = h["oi_alts"][t] / (h["total2"][t] - h["stable_mcap"][t]) * 100
    assert abs(h["lev_alts"][t] - exp) < 1e-6


def test_backfill_replaces_old_hourly_and_cleans_leftovers(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    main.run(d, _cfg(), now=NOW, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    from store import Store
    st = Store(d)
    old = min(st.series["1h"]["oi_total"]) - 5 * H
    st.series["1h"]["oi_total"][old] = 1.0      # stale point older than the backfill window
    st.save(NOW, json.load(open(os.path.join(d, "meta.json"))))
    store, _, _ = main.run(d, _cfg(), now=NOW + H, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    assert old not in store.series["1h"]["oi_total"]
    first = min(store.series["1h"]["oi_total"])
    # a universe refresh days later must NOT trim the growing hourly history
    store, _, _ = main.run(d, _cfg(), now=NOW + 100 * H, coinalyze=FakeCoinalyze(), tv=FakeTV(),
                           telegram=tg, cg_fetch=CG)
    assert min(store.series["1h"]["oi_total"]) == first


def test_gap_in_run_is_bridged(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    main.run(d, _cfg(), now=NOW, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    cz = FakeCoinalyze()
    cz.missing = {"BTCUSDT_PERP.A"}  # one market returns nothing this run
    store, _, _ = main.run(d, _cfg(), now=NOW + H, coinalyze=cz, tv=FakeTV(), telegram=tg, cg_fetch=CG)
    s = store.series["1h"]["oi_btc"]
    t = max(s)
    assert s[t] > 0.9 * s[t - H]  # no sudden dip


def test_level_alerts_near_cross_rearm(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    main.run(d, _cfg(), now=NOW, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    from store import Store
    store = Store(d)
    cat = S.catalog_with_watchlist([])
    v = store.latest("total3")[1]
    st = {}
    lv = [{"series": "total3", "level": v * 1.02, "near_pct": 3, "label": "test"}]
    m1 = alerts.check_levels(store, cat, lv, st)
    assert len(m1) == 1 and "zbliża" in m1[0]
    assert alerts.check_levels(store, cat, lv, st) == []          # no spam
    store.series["1h"]["total3"][max(store.series["1h"]["total3"])] = v * 1.03
    m3 = alerts.check_levels(store, cat, lv, st)
    assert len(m3) == 1 and "przebił" in m3[0] and "górę" in m3[0]
    store.series["1h"]["total3"][max(store.series["1h"]["total3"])] = v * 1.2
    assert alerts.check_levels(store, cat, lv, st) == []          # far → re-armed
    store.series["1h"]["total3"][max(store.series["1h"]["total3"])] = v * 1.04
    m5 = alerts.check_levels(store, cat, lv, st)
    assert len(m5) == 1 and "zbliża" in m5[0] and "od góry" in m5[0]


def test_change_alert_and_cooldown(tmp_path):
    from store import Store
    st_ = Store(str(tmp_path))
    st_.put("1h", "oi_others", {NOW - 24 * H: 100.0, NOW: 115.0})
    cat = S.catalog_with_watchlist([])
    state = {}
    rules = [{"series": "oi_others", "window_hours": 24, "pct": 10, "cooldown_hours": 12}]
    assert len(alerts.check_changes(st_, cat, rules, state, NOW)) == 1
    assert alerts.check_changes(st_, cat, rules, state, NOW + H) == []


def test_health_alerts(tmp_path):
    st = {}
    m = alerts.health_messages(st, {"TradingView": "boom"}, NOW)
    assert len(m) == 1 and "nie działa" in m[0]
    assert alerts.health_messages(st, {"TradingView": "boom"}, NOW + H) == []
    assert len(alerts.health_messages(st, {"TradingView": "boom"}, NOW + 13 * H)) == 1
    m = alerts.health_messages(st, {"TradingView": None}, NOW + 14 * H)
    assert "znowu działa" in m[0]


def test_tv_failure_is_soft(tmp_path):
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    store, msgs, res = main.run(str(tmp_path), _cfg(), now=NOW, backfill=True,
                                coinalyze=FakeCoinalyze(), tv=FakeTV(fail=True), telegram=tg, cg_fetch=CG)
    assert res["Coinalyze"] is None and res["TradingView"]
    assert store.series["1h"]["oi_total"]
    assert any("TradingView" in m for m in msgs)


class FakeWS:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []

    def send(self, m):
        self.sent.append(m)

    def recv(self):
        return self.frames.pop(0)

    def close(self):
        pass


def _f(obj):
    s = obj if isinstance(obj, str) else json.dumps(obj)
    return f"~m~{len(s)}~m~{s}"


def test_tradingview_protocol():
    bars = [{"i": 0, "v": [1000, 1, 2, 0.5, 1.5, 0]}, {"i": 1, "v": [4600, 1.5, 3, 1, 2.5, 0]}]
    frames = [
        _f({"session_id": "x"}),
        _f("~h~1"),
        _f({"m": "timescale_update", "p": ["cs", {"s1": {"s": bars}}]}) + _f({"m": "noop", "p": []}),
        _f({"m": "series_completed", "p": ["cs", "s1"]}),
    ]
    ws = FakeWS(frames)
    out = TradingView(connect=lambda: ws).bars("CRYPTOCAP:TOTAL3", "60", 2)
    assert out == [(1000, 1.5), (4600, 2.5)]
    assert any("~h~1" in s for s in ws.sent)  # heartbeat echoed
    assert any("create_series" in s for s in ws.sent)
    assert split_frames(_f("a") + _f("bc")) == ["a", "bc"]


# ── liquidations ─────────────────────────────────────────────
def _liq_cfg(**kw):
    c = _cfg(**kw)
    c["coinalyze"]["exchanges"] = ["binance", "BYBIT", "Hyperliquid"]
    c["liquidations"] = {"enabled": True, "top_alts": 1, "funding_interval_hours": {"default": 8, "Hyperliquid": 1},
                         "funding_unit": "auto",
                         "price_symbols": {"px_btc": "BTCUSDT_PERP.A", "px_eth": "ETHUSDT_PERP.A"}}
    return c


def test_liquidations_backfill_and_run(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    cfg = _liq_cfg()
    store, msgs, res = main.run(d, cfg, now=NOW, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(),
                                telegram=tg, cg_fetch=CG)
    assert res == {"Coinalyze": None, "Likwidacje": None, "Ceny watchlisty": None, "TradingView": None}
    h, dd = store.series["1h"], store.series["1d"]
    # top_alts=1 → OTHERS = SOL (+ watchlist SOL; PEPE not in OI universe) ; 3 exchanges per coin
    t = NOW - NOW % H
    k = [x for x in range(t - 5 * H, t + 1, H) if (x // H) % 3 != 0][0]
    z = [x for x in range(t - 5 * H, t + 1, H) if (x // H) % 3 == 0][0]
    assert h["liq_btc_long"][k] == 3e6 and h["liq_btc_short"][k] == 1.5e6
    assert h["liq_btc_long"][z] == 0                       # omitted candle = no liquidations, stored as 0
    assert h["liq_others_long"][k] == 3e6 and h["liq_sol_long"][k] == 3e6
    assert h["liq_total_long"][k] == 9e6
    assert h["liq_ex_hyperliquid"][k] == 3 * 1.5e6         # BTC, ETH, SOL on Hyperliquid
    # funding: hourly Hyperliquid and 8h CEX normalise to the same annual rate
    assert abs(h["fund_btc"][t] - 10.95) < 1e-6 and abs(h["fund_others"][t] - 10.95) < 1e-6
    assert h["px_btc"][t] == 100000 and h["px_eth"][t] == 4000
    # daily: Coinalyze daily history + sums from hourly for fully covered days
    assert len(dd["liq_btc_long"]) > 300
    day = t - t % D - D
    exp = sum(v for x, v in h["liq_btc_long"].items() if day <= x < day + D)
    assert dd["liq_btc_long"][day] == exp
    assert abs(dd["fund_btc"][day] - 10.95) < 1e-6
    # separate files, main 1h.json untouched by liquidation series
    files = sorted(os.listdir(d))
    assert files == ["1d.json", "1h.json", "liq_1d.json", "liq_1h.json", "meta.json", "state.json"]
    main_1h = json.load(open(os.path.join(d, "1h.json")))["series"]
    liq_1h = json.load(open(os.path.join(d, "liq_1h.json")))["series"]
    assert "oi_total" in main_1h and not any(s.startswith(("liq_", "fund_", "px_")) for s in main_1h)
    assert "liq_total_long" in liq_1h and "oi_total" not in liq_1h
    meta = json.load(open(os.path.join(d, "meta.json")))
    assert meta["catalog"]["liq_btc_long"]["group"] == "liq" and meta["catalog"]["fund_btc"]["group"] == "fund"
    li = meta["info"]["liquidations"]
    assert li["funding_unit"] == "percent" and li["exchanges"]["Hyperliquid"]["with_liq"] == 3
    assert li["others"] == ["SOL"]
    assert li["configured_without_markets"] == [] and "Kraken" in li["coinalyze_exchanges"]

    # regular run: small window, no re-download of history
    cz = FakeCoinalyze()
    store2, _, res2 = main.run(d, cfg, now=NOW + 2 * H, coinalyze=cz, tv=FakeTV(), telegram=tg, cg_fetch=CG)
    assert res2["Likwidacje"] is None
    n_markets = len(store2.state["universe"]["symbols"])
    assert cz.calls_made <= n_markets * 3 + 5               # OI + liq + funding + 2 ceny 1h + 2 ceny 1d (knoty) + cena SOL
    assert max(store2.series["1h"]["liq_total_long"]) == NOW + 2 * H - (NOW + 2 * H) % H
    assert len(store2.series["1d"]["liq_btc_long"]) == len(dd["liq_btc_long"]) or \
        len(store2.series["1d"]["liq_btc_long"]) == len(dd["liq_btc_long"]) + 1


def test_liquidation_daily_trimmed_to_oi_start(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    cz = FakeCoinalyze()
    cz.btc_daily_from = NOW - NOW % D - 200 * D          # OI history (BTC/ETH) starts later than liquidations
    store, _, _ = main.run(d, _liq_cfg(), now=NOW, backfill=True, coinalyze=cz, tv=FakeTV(), telegram=tg, cg_fetch=CG)
    oi0 = min(store.series["1d"]["oi_total"])
    assert oi0 == cz.btc_daily_from
    assert min(store.series["1d"]["liq_total_long"]) == oi0 and min(store.series["1d"]["fund_btc"]) >= oi0
    assert min(store.series["1d"]["px_btc"]) < oi0       # price keeps its full history


def test_liquidations_first_run_after_upgrade_downloads_history(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    main.run(d, _cfg(), now=NOW, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    assert not [k for k in Store_(d).series["1h"] if k.startswith("liq_")]   # w pliku liq_* tylko ceny watchlisty
    store, _, res = main.run(d, _liq_cfg(), now=NOW + 2 * H, coinalyze=FakeCoinalyze(), tv=FakeTV(),
                             telegram=tg, cg_fetch=CG)
    assert res["Likwidacje"] is None
    assert len(store.series["1h"]["liq_total_long"]) > 1000
    assert len(store.series["1d"]["liq_total_long"]) > 300
    assert store.state["liq_version"] == 1


def test_liquidations_failed_batch_is_refetched_next_run(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    main.run(d, _liq_cfg(), now=NOW, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG)

    class Flaky(FakeCoinalyze):
        def liquidation_history(self, symbols, interval, frm, to, progress=None):
            self.failed_batches = 1
            return {}
    complete = Store_(d).state["liq_complete_until"]
    main.run(d, _liq_cfg(), now=NOW + 10 * H, coinalyze=Flaky(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    assert Store_(d).state["liq_complete_until"] == complete     # not advanced
    store, _, _ = main.run(d, _liq_cfg(), now=NOW + 12 * H, coinalyze=FakeCoinalyze(), tv=FakeTV(),
                           telegram=tg, cg_fetch=CG)
    h = store.series["1h"]["liq_btc_long"]
    gap = [x for x in range(complete + H, NOW + 10 * H, H) if (x // H) % 3 != 0]
    assert all(h[x] > 0 for x in gap)                              # hours lost in the failed run are back


def Store_(d):
    from store import Store
    return Store(d)


def test_funding_unit_detection_and_weights():
    import liquidations as L
    names = {"A": "Binance", "H": "Hyperliquid"}
    lcfg = {"funding_interval_hours": {"default": 8, "Hyperliquid": 1}}
    sb = {"BTCUSDT_PERP.A": "BTC", "BTC.H": "BTC"}
    fh = {"BTCUSDT_PERP.A": {t * H: 0.0001 for t in range(30)}, "BTC.H": {t * H: 0.0000125 for t in range(30)}}
    assert L.detect_unit(fh, sb, names, lcfg) == "fraction"
    assert abs(L.annualize(0.0001, "BTCUSDT_PERP.A", names, lcfg, "fraction") - 10.95) < 1e-9
    # weighting: big market dominates
    groups = {"btc": set(sb)}
    fh2 = {"BTCUSDT_PERP.A": {0: 0.01}, "BTC.H": {0: 0.01}}       # 10.95%/yr and 87.6%/yr
    w = L.oi_weights(None, {"BTCUSDT_PERP.A": [0, 9e9], "BTC.H": [0, 1e9]}, H, 6)
    out = L.aggregate_funding(fh2, w, groups, [0], H, names, lcfg, "percent")
    assert abs(out["fund_btc"][0] - (10.95 * 0.9 + 87.6 * 0.1)) < 1e-6
    # glitch values are dropped
    assert L.annualize(50.0, "BTCUSDT_PERP.A", names, lcfg, "percent") is None


def test_liq_universe_top_and_min_oi():
    import liquidations as L
    uni = {"symbols": {"BTC.A": "BTC", "ETH.A": "ETH", "SOL.A": "SOL", "SOL.X": "SOL", "DOGE.A": "DOGE",
                       "PEPE.A": "PEPE"},
           "assets": [["BTC", 1], ["ETH", 1], ["SOL", 1], ["DOGE", 1], ["PEPE", 1]]}
    st = {"last_oi": {"BTC.A": [0, 5e9], "ETH.A": [0, 3e9], "SOL.A": [0, 1e9], "SOL.X": [0, 1e5],
                      "DOGE.A": [0, 5e8], "PEPE.A": [0, 2e8]}}
    sb, others, cov = L.liq_universe(uni, st, {"top_alts": 1, "min_market_oi_usd": 1e6}, ["PEPE"])
    assert others == {"SOL", "PEPE"}
    assert set(sb) == {"BTC.A", "ETH.A", "SOL.A", "PEPE.A"}       # SOL.X too small, DOGE outside top 1
    assert 0.9 < cov < 1


def test_liq_sum_alerts_and_report(tmp_path):
    from store import Store
    st_ = Store(str(tmp_path))
    t = NOW - NOW % H
    st_.put("1h", "liq_btc_long", {t - k * H: 3e8 for k in range(6)})
    st_.put("1h", "liq_btc_short", {t - k * H: 1e8 for k in range(6)})
    cat = S.catalog_with_watchlist(["SOL"], {"top": 30, "exchanges": ["Binance", "Hyperliquid"]})
    assert "liq_ex_hyperliquid" in cat and "fund_sol" in cat
    state = {}
    rules = [{"series": "liq_btc", "window_hours": 4, "usd": 1.5e9, "cooldown_hours": 12, "label": "kaskada"}]
    m = alerts.check_sums(st_, cat, rules, state, NOW)
    assert len(m) == 1 and "$1.60B" in m[0] and "long $1.20B" in m[0] and "kaskada" in m[0]
    assert alerts.check_sums(st_, cat, rules, state, NOW + H) == []          # cooldown
    assert alerts.check_sums(st_, cat, [dict(rules[0], usd=2e9)], {}, NOW) == []
    assert alerts.check_sums(st_, cat, [{"series": "nope", "usd": 1}], {}, NOW) == []


def test_store_bundles_roundtrip(tmp_path):
    from store import Store
    s = Store(str(tmp_path))
    s.put("1h", "oi_btc", {0: 1.0})
    s.put("1h", "liq_btc_long", {0: 2.0})
    s.put("1d", "fund_btc", {0: 3.0})
    s.save(NOW, {})
    s2 = Store(str(tmp_path))
    assert s2.series["1h"]["oi_btc"] == {0: 1.0} and s2.series["1h"]["liq_btc_long"] == {0: 2.0}
    assert s2.series["1d"]["fund_btc"] == {0: 3.0}


def test_every_configured_tv_series_has_catalog_entry():
    cfg = main.load_config(os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
    cat = main.build_catalog(cfg)
    missing = [sid for sid in cfg["tradingview"]["symbols"] if sid not in cat]
    assert not missing, missing
    assert cat["ethbtc"]["group"] == "pair" and cat["others_d"]["group"] == "pct"
    assert alerts.fmt_value(0.034521, "pair") == "0.03452"


def test_new_tv_series_fetched_in_regular_run(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    main.run(d, _cfg(), now=NOW, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    cfg = _cfg()
    cfg["tradingview"]["symbols"]["ethbtc"] = "BINANCE:ETHBTC"
    tv = FakeTV()
    store, _, res = main.run(d, cfg, now=NOW + 2 * H, coinalyze=FakeCoinalyze(), tv=tv, telegram=tg, cg_fetch=CG)
    assert res["TradingView"] is None
    # a series new to the store gets its full history without a backfill
    assert ("BINANCE:ETHBTC", "1D", 5000) in tv.requests and len(store.series["1d"]["ethbtc"]) > 1000


def test_dominance_breakdown_sums_to_100():
    s = {"total": {0: 3000.0}, "totales": {0: 2700.0}, "total3es": {0: 540.0}}
    S.derived(s)
    assert abs(s["stable_d"][0] - 10.0) < 1e-9 and abs(s["alts_d"][0] - 18.0) < 1e-9
    btc_d, eth_d = 61.0, 11.0                    # BTC + ETH = 2160 of 3000
    assert abs(btc_d + eth_d + s["stable_d"][0] + s["alts_d"][0] - 100) < 1e-9
    cat = S.catalog_with_watchlist([])
    assert cat["stable_d"]["group"] == "pct" and cat["alts_d"]["group"] == "pct"


def test_run_routes_market_alerts_to_group_and_failures_to_admin(tmp_path):
    d = str(tmp_path)
    tgcfg = {"group_chat_id": -100500, "group_thread_id": 7}
    tg = alerts.Telegram(token="", chat_id="111", enabled=False, tg_cfg=tgcfg)
    main.run(d, _cfg(), now=NOW, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(fail=True), telegram=tg, cg_fetch=CG)
    assert [k for k, *_ in tg.sent_to] == ["system", "system"]                 # TV failure + backfill → admin only
    assert all(chat == "111" for _, chat, _, _ in tg.sent_to)
    from store import Store
    v = Store(d).latest("oi_total")[1]
    cfg = _cfg()
    cfg["levels"] = [{"series": "oi_total", "level": v * 1.01, "near_pct": 3, "label": "test A"},
                     {"series": "oi_total", "level": v * 0.99, "near_pct": 3, "label": "test B"}]
    tg2 = alerts.Telegram(token="", chat_id="111", enabled=False, tg_cfg=tgcfg)
    main.run(d, cfg, now=NOW + 2 * H, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg2, cg_fetch=CG)
    market = [x for x in tg2.sent_to if x[0] == "market"]
    assert len(market) == 1 and market[0][1:3] == ("-100500", 7)               # both alerts in ONE message
    assert "test A" in market[0][3] and "test B" in market[0][3] and "Rynek" in market[0][3]


def test_report_lines_in_meta_from_config():
    import main as M
    lines = M.report_lines({"reports": {"lines": {"oi_others_vs_btc": [[0.7, "test"]]}}})
    assert lines["oi_others_vs_btc"] == [{"value": 0.7, "label": "test", "color": "#4caf7d"}]
    assert [ln["value"] for ln in lines["alts_vs_btc"]] == [0.28, 0.38, 0.47]       # default from report.LAYOUT
    assert M.report_lines({})["oi_others_vs_btc"][-1]["label"] == "zrównanie z BTC"


class FakeOHLC(FakeCoinalyze):
    """Coinalyze z high/low: low godzinowy zależy od godziny doby, dzienny low = close − 500."""
    def price_ohlc_history(self, symbols, interval, frm, to, progress=None):
        base = self.price_history(symbols, interval, frm, to)
        if interval == "1hour":
            return {s: {t: (c + 50, c - (t // H % 24) * 10, c) for t, c in h.items()} for s, h in base.items()}
        return {s: {t: (c + 800, c - 500, c) for t, c in h.items()} for s, h in base.items()}


def test_price_wicks_hourly_daily_and_upgrade(tmp_path):
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    store, _, _ = main.run(d, _liq_cfg(), now=NOW, backfill=True, coinalyze=FakeOHLC(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    h, dd = store.series["1h"], store.series["1d"]
    t = NOW - NOW % H
    assert h["px_btc"][t] == 100000 and h["px_btc_lo"][t] == 100000 - (t // H % 24) * 10 and h["px_btc_hi"][t] == 100050
    day = t - t % D - D                                    # pełny dzień w danych godzinowych → min z godzin
    assert dd["px_btc_lo"][day] == 100000 - 230 and dd["px_btc_hi"][day] == 100050
    old = min(dd["px_btc_lo"])                             # starsze dni — z historii dziennej
    assert dd["px_btc_lo"][old] == 100000 - 500 and len(dd["px_btc_lo"]) > 300
    # stan sprzed poprawki: bez knotów dziennych → pierwszy zwykły skan pobiera je raz
    f = os.path.join(d, "liq_1d.json")
    js = json.load(open(f))
    for k in ("px_btc_hi", "px_btc_lo", "px_eth_hi", "px_eth_lo"):
        js["series"].pop(k, None)
    json.dump(js, open(f, "w"))
    store2, _, res = main.run(d, _liq_cfg(), now=NOW + 2 * H, coinalyze=FakeOHLC(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    assert res["Likwidacje"] is None and len(store2.series["1d"]["px_btc_lo"]) > 300
    assert store2.series["1d"]["px_eth_lo"][old] == 4000 - 500


def test_price_wicks_repair_bad_day_and_hourly_backfill(tmp_path):
    """Poprawka 55: knot dzienny zapisany z niepełnej świecy (02.11.2026) → naprawa przy zmianie PX_VERSION;
    knoty godzinowe dociągnięte wstecz tylko tam, gdzie jest zamknięcie 1h; dzień w toku zostaje z danych 1h."""
    import liquidations as LQ
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    main.run(d, _liq_cfg(), now=NOW, backfill=True, coinalyze=FakeOHLC(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    f1d, f1h, fst = (os.path.join(d, n) for n in ("liq_1d.json", "liq_1h.json", "state.json"))
    js = json.load(open(f1d))
    bad = [p for p in js["series"]["px_btc_lo"] if p[0] < NOW - 30 * D][-1][0]
    js["series"]["px_btc_lo"] = [[t, 999999.0 if t == bad else v] for t, v in js["series"]["px_btc_lo"]]
    json.dump(js, open(f1d, "w"))
    jh = json.load(open(f1h))
    cut = NOW - NOW % H - 48 * H
    for k in ("px_btc_hi", "px_btc_lo"):
        jh["series"][k] = [p for p in jh["series"][k] if p[0] >= cut]          # knoty 1h dopiero od 2 dni
    json.dump(jh, open(f1h, "w"))
    st = json.load(open(fst))
    st.pop("px_version", None)                                                  # stan sprzed poprawki 55
    json.dump(st, open(fst, "w"))
    store, _, res = main.run(d, _liq_cfg(), now=NOW + 2 * H, coinalyze=FakeOHLC(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    assert res["Likwidacje"] is None and store.state["px_version"] == LQ.PX_VERSION
    assert store.series["1d"]["px_btc_lo"][bad] == 100000 - 500                 # naprawiony z dziennej świecy
    h = store.series["1h"]
    assert min(h["px_btc_lo"]) < cut - 1000 * H and set(h["px_btc_lo"]) <= set(h["px_btc"])   # wstecz, tylko przy zamknięciach
    today = NOW - NOW % D
    assert store.series["1d"]["px_btc_lo"][today] != 100000 - 500               # dzień w toku: z godzin, nie ze świecy dziennej


# ── poprawka 63: historyczne wydarzenia i kierunek alertu poziomu ──
def test_history_events_from_config():
    cfg = {"history_events": [
        {"date": "2022-11-08", "label": "FTX", "kind": "upadek", "desc": "Upadek FTX"},
        {"date": "2020-03-12", "label": "COVID", "kind": "KRACH"},
        {"date": "zła data", "label": "X"},
        {"date": "2021-01-01", "label": ""},
        {"date": "2024-01-10", "label": "ETF BTC", "kind": "coś innego"},
    ]}
    ev = main.history_events(cfg)
    assert [e["label"] for e in ev] == ["COVID", "FTX", "ETF BTC"]
    assert ev[0]["t"] == 1583971200 and ev[0]["kind"] == "krach" and ev[0]["date"] == "2020-03-12"
    assert ev[1]["desc"] == "Upadek FTX" and ev[2]["kind"] == "inne"
    assert main.history_events({}) == []
    real = main.history_events(main.load_config(os.path.join(os.path.dirname(__file__), "..", "config.yaml")))
    assert len(real) >= 15 and all(e["kind"] in main.HIST_KINDS for e in real)


def test_level_direction_up(tmp_path):
    from store import Store
    st_ = Store(str(tmp_path))
    cat = S.catalog_with_watchlist([])
    sid = "oi_others_vs_btc"
    lv = [{"series": sid, "level": 0.95, "near_pct": 3, "direction": "up", "label": "Lewar altów"}]
    state = {}

    def at(v, k):
        st_.put("1h", sid, {NOW + k * H: v})
        return alerts.check_levels(st_, cat, lv, state)
    assert at(0.80, 0) == []                                   # daleko
    m = at(0.93, 1)
    assert len(m) == 1 and "zbliża" in m[0] and "od dołu" in m[0]
    m = at(0.96, 2)
    assert len(m) == 1 and "przebił" in m[0] and "górę" in m[0]
    assert at(0.97, 3) == []                                   # od góry — bez „zbliża się”
    assert at(0.94, 4) == []                                   # przebicie w dół — pominięte
    assert at(0.70, 5) == []                                   # daleko → strefa uzbrojona na nowo
    assert "zbliża" in at(0.93, 6)[0]
    both = [{"series": sid, "level": 0.95, "near_pct": 3}]
    s2 = {}
    st_.put("1h", sid, {NOW + 7 * H: 0.97})
    alerts.check_levels(st_, cat, both, s2)
    st_.put("1h", sid, {NOW + 8 * H: 0.90})
    assert "w dół" in alerts.check_levels(st_, cat, both, s2)[0]   # bez direction — obie strony jak dawniej
