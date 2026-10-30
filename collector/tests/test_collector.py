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
            for ex, code in (("Binance", "A"), ("Bybit", "6"), ("Kraken", "K")):
                b = "1000PEPE" if base == "PEPE" and code == "A" else base
                self.markets.append({"symbol": f"{b}USDT_PERP.{code}", "exchange": code,
                                     "base_asset": b, "is_perpetual": True, "_oi": oi / 3})
        self.markets.append({"symbol": "BTCUSDT_241227.A", "exchange": "A", "base_asset": "BTC",
                             "is_perpetual": False, "_oi": 1e9})
        self.missing = set()  # symbols that return no data (simulated gaps)

    def exchanges(self):
        return [{"name": "Binance", "code": "A"}, {"name": "Bybit", "code": "6"},
                {"name": "Kraken", "code": "K"}]

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
    assert cl.batch == 19
    out = cl.open_interest([f"S{i}" for i in range(38)])
    assert len(out) == 38 and t[0] == 0          # 2 batches, no waiting
    out = cl.open_interest(["BAD"] + [f"X{i}" for i in range(18)] + ["OK1"])
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
    assert res == {"Coinalyze": None, "TradingView": None}
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
    assert files == ["1d.json", "1h.json", "meta.json", "state.json"]
    meta = json.load(open(os.path.join(d, "meta.json")))
    assert "oi_sol" in meta["catalog"] and meta["health"]["Coinalyze"] == "ok"

    # regular run 2h later: only a small window is fetched
    cz2 = FakeCoinalyze()
    tv2 = FakeTV()
    store2, msgs2, res2 = main.run(d, _cfg(), now=NOW + 2 * H, coinalyze=cz2, tv=tv2, telegram=tg, cg_fetch=CG)
    assert res2 == {"Coinalyze": None, "TradingView": None}
    assert cz2.calls_made == len(uni)  # universe reused, one history pass
    assert all(n < 20 for (_, iv, n) in tv2.requests)
    assert max(store2.series["1h"]["oi_total"]) == NOW + 2 * H - (NOW + 2 * H) % H
    assert any("Dzienny raport" in m for m in msgs2)


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
