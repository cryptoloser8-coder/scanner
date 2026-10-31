"""Offline tests of the EMA200 monitor: python -m pytest collector/tests -q"""
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ema_monitor as E  # noqa: E402

D = 86400
NOW = 1_790_000_000 - 1_790_000_000 % D + 6 * 3600     # 06:00 UTC


def cfg(**kw):
    c = dict(E.DEFAULTS)
    c.update({"min_days": 300, "breadth_min_coins": 1, "alerts": [{"coins": ["AAA", "BBB"], "cross": True, "confirm": "live",
                                           "near_pct": 2}], "page_url": ""})
    c.update(kw)
    return c


class FakeBinance:
    """Prices: AAA rises above its EMA, BBB falls below, CCC is young (excluded), plus junk pairs."""

    def __init__(self, now=NOW, live=None):
        self.now = now
        self.calls = 0
        self.kl_requests = []
        self.live = live or {}
        self.ages = {}

    def exchange_info(self):
        self.calls += 1
        mk = lambda s, b, q="USDT", st="TRADING": {"symbol": s, "baseAsset": b, "quoteAsset": q,  # noqa: E731
                                                   "status": st, "isSpotTradingAllowed": True}
        return {"symbols": [mk("AAAUSDT", "AAA"), mk("BBBUSDT", "BBB"), mk("CCCUSDT", "CCC"),
                            mk("USDCUSDT", "USDC"), mk("AAAUPUSDT", "AAAUP"), mk("AAABTC", "AAA", "BTC"),
                            mk("DEADUSDT", "DEAD", st="BREAK"), mk("JUPUSDT", "JUP")]}

    def _close(self, sym, day):
        x = day / D
        if sym == "AAAUSDT":
            return 100 + 20 * math.sin(x / 60)
        if sym == "BBBUSDT":
            return 50 - 10 * math.sin(x / 45)
        if sym == "JUPUSDT":
            return 1 + 0.2 * math.sin(x / 30)
        return 5.0

    def klines(self, symbol, limit, end_ms=None):
        self.calls += 1
        self.kl_requests.append((symbol, limit) if end_ms is None else (symbol, limit, "old"))
        today = self.now - self.now % D
        age = 120 if symbol == "CCCUSDT" else self.ages.get(symbol, 2000)
        listing = today - (age - 1) * D
        last = today if end_ms is None else (end_ms // 1000) - (end_ms // 1000) % D
        days = [last - i * D for i in range(limit) if last - i * D >= listing][::-1]
        return [[t * 1000, "0", str(self._close(symbol, t) * 1.02), str(self._close(symbol, t) * 0.98),
                 str(self._close(symbol, t)), "0", (t + D) * 1000 - 1, "0", 0, "0", "0", "0"] for t in days]

    def prices(self):
        self.calls += 1
        today = self.now - self.now % D
        return {s: self.live.get(s, self._close(s, today)) for s in ("AAAUSDT", "BBBUSDT", "CCCUSDT", "JUPUSDT")}

    def volumes(self):
        self.calls += 1
        return {"AAAUSDT": 5e7, "BBBUSDT": 2e6, "CCCUSDT": 1e5, "JUPUSDT": 9e6}


class FakeTG:
    def __init__(self):
        self.sent = []
        self.kinds = []

    def send(self, text):
        self.sent.append(text)
        return True

    def post(self, kind, text):
        self.kinds.append(kind)
        return self.send(text)


def test_universe_filters_stables_leveraged_and_other_quotes():
    u = E.universe(FakeBinance().exchange_info(), cfg())
    assert set(u) == {"AAAUSDT", "BBBUSDT", "CCCUSDT", "JUPUSDT"}     # JUP kept although it ends with "UP"
    assert "JUPUSDT" not in E.universe(FakeBinance().exchange_info(), cfg(exclude=["jup"]))


def test_ema_matches_definition_and_streak():
    closes = [10, 11, 12, 13, 12, 11, 10, 9]
    e = E.ema_series(closes, 3)
    exp = [10]
    for c in closes[1:]:
        exp.append(0.5 * c + 0.5 * exp[-1])
    assert all(abs(x - y) < 1e-12 for x, y in zip(e, exp))
    side, n, idx = E.streak(closes, e)
    assert side == -1 and n == 4 and idx == 4   # 12 < EMA 12.06 already


def test_closed_candles_drop_the_open_one():
    rows = FakeBinance().klines("AAAUSDT", 5)
    rows.append([NOW // D * D * 1000, "0", "0", "0", "1", "0", (NOW // D * D + D) * 1000 - 1])
    assert len(E.closed_candles(rows, NOW)) == 4     # fake klines (like Binance) include today's open candle


def test_first_run_check_and_publish(tmp_path):
    st = str(tmp_path / "st")
    fb, tg = FakeBinance(), FakeTG()
    info, rows, excl, msgs = E.run(cfg(), st, now=NOW, client=fb, telegram=tg, publish=True, remote=None)
    assert {r["s"] for r in rows} == {"AAA", "BBB", "JUP"} and excl == [["CCC", 119]]
    assert msgs == [] and tg.sent == []                        # first run only arms the alerts
    pub = json.load(open(tmp_path / "st" / "pub" / "ema.json"))
    assert pub["total"] == 3 and pub["coins"][0]["s"] in ("AAA", "BBB", "JUP")
    assert abs(pub["coins"][0]["d"]) <= abs(pub["coins"][-1]["d"])        # sorted by distance
    a = next(c for c in pub["coins"] if c["s"] == "AAA")
    assert a["alert"] == {"cross": True, "near": 2.0} and a["days"] == 1999   # older history filled in already
    assert next(c for c in pub["coins"] if c["s"] == "JUP")["alert"] is None
    assert pub["breadth"] and 0 <= pub["breadth"][-1][1] <= 100
    hist = json.load(open(tmp_path / "st" / "pub" / "hist" / "AAA.json"))
    assert len(hist["d"]) == 1999 and len(hist["d"][0]) == 3   # whole history in the chart file
    # same day again: no candle requests, only prices
    fb2 = FakeBinance(now=NOW + 300)
    E.run(cfg(), st, now=NOW + 300, client=fb2, telegram=tg, remote=None)
    assert [r for r in fb2.kl_requests if len(r) == 2] == []          # no new-candle requests on the same day
    # next day: only the missing candles are fetched
    fb3 = FakeBinance(now=NOW + D)
    E.run(cfg(), st, now=NOW + D, client=fb3, telegram=tg, remote=None)
    new = [r for r in fb3.kl_requests if len(r) == 2]
    assert new and all(r[1] <= 4 for r in new)   # missing days + margin, not 1000


def _rows(d, side=None, p=100.0):
    e = p / (1 + d / 100)
    return [{"s": "AAA", "p": p, "e": e, "d": d, "c": p, "side": side if side is not None else (1 if d >= 0 else -1)}]


def test_alerts_near_cross_hysteresis_cooldown():
    c = cfg(alerts=[{"coins": ["AAA"], "cross": True, "confirm": "live", "near_pct": 2}], near_cooldown_hours=0)
    st, t = {}, NOW
    assert E.check_alerts(_rows(-5), c["alerts"], st, c, t, False) == []         # new coin: armed silently
    m = E.check_alerts(_rows(-1.5), c["alerts"], st, c, t + 300, False)
    assert len(m) == 1 and "zbliża się" in m[0] and "od dołu" in m[0]
    assert E.check_alerts(_rows(-1.0), c["alerts"], st, c, t + 600, False) == []  # still near: no repeat
    assert E.check_alerts(_rows(0.3), c["alerts"], st, c, t + 900, False) == []   # inside buffer: no cross yet
    m = E.check_alerts(_rows(0.8), c["alerts"], st, c, t + 1200, False)
    assert len(m) == 1 and "przeciął w górę" in m[0]
    assert E.check_alerts(_rows(-0.8), c["alerts"], st, c, t + 1500, False) == []  # cooldown blocks a flip
    E.check_alerts(_rows(-6), c["alerts"], st, c, t + 2000, False)                 # far → near re-armed
    m = E.check_alerts(_rows(-1.9), c["alerts"], st, c, t + 2300, False)
    assert len(m) == 1 and "zbliża się" in m[0]


def test_alerts_close_mode_and_direction():
    c = cfg(alerts=[{"coins": ["AAA"], "cross": True, "confirm": "close", "direction": "up"}])
    st = {}
    E.check_alerts(_rows(-3, side=-1), c["alerts"], st, c, NOW, True)
    assert E.check_alerts(_rows(1, side=-1), c["alerts"], st, c, NOW + 300, False) == []   # live cross ignored
    m = E.check_alerts(_rows(1, side=1), c["alerts"], st, c, NOW + D, True)
    assert len(m) == 1 and "zamknął dzień nad" in m[0]
    assert E.check_alerts(_rows(-2, side=-1), c["alerts"], st, c, NOW + 2 * D, True) == []  # down filtered


def test_rule_merging_and_all():
    rules = [{"coins": "all", "cross": True, "confirm": "close"}, {"coins": ["sol"], "near_pct": 3}]
    r = E.rule_for("SOL", rules)
    assert r["cross"] and r["confirm"] == "close" and r["near_pct"] == 3.0
    assert E.rule_for("XYZ", rules)["near_pct"] is None
    assert E.rule_for("XYZ", rules[1:]) is None


def test_alert_sent_on_live_cross_through_run(tmp_path):
    st = str(tmp_path)
    tg = FakeTG()
    E.run(cfg(), st, now=NOW, client=FakeBinance(), telegram=tg, remote=None)
    fb = FakeBinance(now=NOW + 300)
    a_ema = None
    # find AAA's EMA from the published file and push the live price 10% above / below it
    pub = json.load(open(os.path.join(st, "pub", "ema.json")))
    a = next(c for c in pub["coins"] if c["s"] == "AAA")
    a_ema = a["ec"]
    target = a_ema * (0.9 if a["d"] >= 0 else 1.1)
    fb.live = {"AAAUSDT": target}
    E.run(cfg(), st, now=NOW + 300, client=fb, telegram=tg, remote=None)
    assert len(tg.sent) == 1 and "AAA" in tg.sent[0] and "przeciął" in tg.sent[0]


def test_git_publish_to_local_bare_repo(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    pub = tmp_path / "pub"
    E.write_outputs(str(pub), {"x": 1}, {"AAA": ([0, D], [1.0, 2.0], [1.0, 1.5])}, cfg(), True)
    E.git_publish(str(pub), str(bare), "ema")
    E.write_outputs(str(pub), {"x": 2}, {}, cfg(), False)
    E.git_publish(str(pub), str(bare), "ema")
    out = subprocess.run(["git", "-C", str(bare), "show", "ema:ema.json"], capture_output=True, text=True).stdout
    assert json.loads(out) == {"x": 2}
    n = subprocess.run(["git", "-C", str(bare), "rev-list", "--count", "ema"], capture_output=True, text=True).stdout
    assert n.strip() == "1"                                    # branch never grows
    E.cleanup_git(str(pub))


def test_breadth_counts_only_coins_with_enough_history():
    c = cfg(min_days=3, breadth_days=10)
    t = [NOW - NOW % D - i * D for i in range(5)][::-1]
    series = {f"C{i}": (t, [1, 2, 3, 4, 5], [1, 1.5, 2, 2.5, 3]) for i in range(10)}
    br = E.breadth(series, c, NOW)
    assert br[0][0] == t[2] and br[-1][1] == 100.0 and br[-1][2] == 10


def test_fmt_price_small_values():
    assert E.fmt_price(0.00002191) == "$0.00002191"
    assert E.fmt_price(0.9147) == "$0.9147" and E.fmt_price(124.2) == "$124.20" and E.fmt_price(95957) == "$95,957"


def test_wrapped_and_pegged_tokens_excluded_even_before_daily_refresh():
    info = {"symbols": [{"symbol": f"{b}USDT", "baseAsset": b, "quoteAsset": "USDT", "status": "TRADING"}
                        for b in ("BTC", "WBTC", "BNSOL", "KGST")]}
    assert set(E.universe(info, cfg())) == {"BTCUSDT"}
    candles = {f"{b}USDT": [[i * D, 1.0] for i in range(400)] for b in ("BTC", "WBTC")}
    rows, _, _ = E.compute(candles, {"BTCUSDT": "BTC", "WBTCUSDT": "WBTC"}, {}, {}, cfg(), [])
    assert [r["s"] for r in rows] == ["BTC"]


def test_older_history_is_filled_in_pages_up_to_the_listing(tmp_path):
    st = str(tmp_path)
    c = cfg(history_pages_per_run=3)
    fb = FakeBinance()
    fb.ages = {"AAAUSDT": 2600, "BBBUSDT": 900, "JUPUSDT": 1500}
    E.run(c, st, now=NOW, client=fb, remote=None)
    cand = json.load(open(os.path.join(st, "candles.json")))
    # first run: 999 recent days for all + 3 older pages (AAA, BBB, CCC… sorted: AAA, BBB, CCC)
    assert len(cand["BBBUSDT"]) == 899                          # young coin: complete at once (899 closed days)
    for i in range(1, 6):
        fbn = FakeBinance(now=NOW + i * 300)
        fbn.ages = fb.ages
        E.run(c, st, now=NOW + i * 300, client=fbn, remote=None)
    cand = json.load(open(os.path.join(st, "candles.json")))
    stt = json.load(open(os.path.join(st, "state.json")))
    assert len(cand["AAAUSDT"]) == 2599 and len(cand["JUPUSDT"]) == 1499   # back to the listing
    assert set(stt["full_hist"]) == {"AAAUSDT", "BBBUSDT", "CCCUSDT", "JUPUSDT"}
    pub = json.load(open(os.path.join(st, "pub", "ema.json")))
    assert pub["history_full"] == 4 and pub["breadth"][0][0] < NOW - 2000 * D   # breadth covers the long history
    # nothing left to do → no more "old" requests
    fbx = FakeBinance(now=NOW + 3600)
    fbx.ages = fb.ages
    E.run(c, st, now=NOW + 3600, client=fbx, remote=None)
    assert not [r for r in fbx.kl_requests if len(r) == 3]


def test_chart_files_rewritten_after_version_bump(tmp_path):
    st = str(tmp_path)
    E.run(cfg(), st, now=NOW, client=FakeBinance(), remote=None)
    f = os.path.join(st, "pub", "hist", "AAA.json")
    os.remove(f)
    E.run(cfg(), st, now=NOW + 1000, client=FakeBinance(now=NOW + 1000), remote=None)
    assert not os.path.exists(f)                             # same day, same version → not rewritten
    s = json.load(open(os.path.join(st, "state.json")))
    s["hist_version"] = 1                                    # state from an older version (like the Pi now)
    json.dump(s, open(os.path.join(st, "state.json"), "w"))
    E.run(cfg(), st, now=NOW + 2000, client=FakeBinance(now=NOW + 2000), remote=None)
    assert os.path.exists(f)
