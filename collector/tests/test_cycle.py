"""Offline tests: cykl BTC i makro (cycle.py), dzienne symbole TradingView (main.collect_tv)."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cycle as C  # noqa: E402
import main  # noqa: E402
from store import Store  # noqa: E402

D = 86400


def t_of(iso):
    return C.day_of(iso)


def synthetic_px():
    """Price with clear peaks after each halving and lows in between (2010 → 2026-10-31)."""
    peaks = {"2011-06-08": 30, "2013-12-04": 1200, "2017-12-16": 19000, "2021-11-08": 67000, "2025-10-06": 125000}
    lows = {"2010-07-20": 0.1, "2011-11-18": 2, "2012-11-27": 12, "2015-01-14": 180, "2018-12-15": 3200, "2022-11-21": 15800,
            "2026-06-30": 58000, "2026-10-31": 77000}
    knots = sorted([(t_of(k), v) for k, v in {**peaks, **lows}.items()])
    px = {}
    for (t1, v1), (t2, v2) in zip(knots, knots[1:]):
        for t in range(t1, t2, D):           # interpolacja w skali log
            f = (t - t1) / (t2 - t1)
            px[t] = math.exp(math.log(v1) + f * (math.log(v2) - math.log(v1)))
    px[knots[-1][0]] = knots[-1][1]
    return px


def test_cycle_extremes_use_halvings_and_confirmation():
    tops, bottoms = C.cycle_extremes(synthetic_px())
    assert [C.mmyy(t) for t, _ in tops] == ["06.2011", "12.2013", "12.2017", "11.2021", "10.2025"]
    assert [C.mmyy(t) for t, _ in bottoms] == ["11.2011", "01.2015", "12.2018", "11.2022"]   # dno 2026 niepewne
    px = synthetic_px()
    for t in [t for t in px if t > t_of("2025-10-06")]:
        px[t] = 100000                       # bez spadku o 50% → szczyt 10.2025 niepotwierdzony
    tops2, _ = C.cycle_extremes(px)
    assert [C.mmyy(t) for t, _ in tops2][-1] == "11.2021"


def test_compute_indicators_and_ref_lines(tmp_path):
    st = Store(str(tmp_path))
    px = synthetic_px()
    st.put("1d", "px_btc", px)
    st.put("1d", "cm_mvrv_btc", {t: 2.0 for t in px if t >= t_of("2010-07-18")})
    st.put("1d", "cm_mcap_btc", {t: v * 19e6 for t, v in px.items() if t >= t_of("2010-07-18")})
    days = [t for t in px if t >= t_of("2014-04-01")]
    st.put("1d", "total", {t: 3e12 for t in days})
    st.put("1d", "total2", {t: 1e12 for t in days})
    st.put("1d", "stable_mcap", {t: 2e11 for t in days})
    st.put("1d", "us10y", {t: 4.0 for t in days})
    st.put("1d", "us02y", {t: 4.5 for t in days})
    info = C.compute(st, {})
    s = st.series["1d"]
    t = t_of("2026-10-31")
    assert abs(s["rprice_btc"][t] - 77000 / 2) < 1
    assert abs(s["ssr"][t] - 10) < 1e-6 and abs(s["yc_10y2y"][t] + 0.5) < 1e-9
    assert min(s["mayer_btc"]) == min(px) + 199 * D and min(s["p200w_btc"]) == min(px) + 1399 * D
    assert "mvrvz_btc" in info["series"] and "net_liq" not in info["series"]
    lines = C.ref_lines(st, {})
    labels = [x["label"] for x in lines["mayer_btc"]]
    assert labels == ["szczyt 12.2017", "szczyt 11.2021", "szczyt 10.2025", "dno 12.2018", "dno 11.2022"]
    assert [x["label"] for x in lines["ssr"]] == ["szczyt 11.2021", "szczyt 10.2025", "dno 11.2022"]   # od 2020
    assert any(x["value"] == 1.0 for x in lines["picycle_btc"]) and lines["yc_10y2y"][0]["value"] == 0.0


def test_net_liquidity_units_and_sanity(tmp_path):
    st = Store(str(tmp_path))
    weeks = [t_of("2026-01-07") + i * 7 * D for i in range(20)]
    st.put("1d", "fed_assets", {t: 6.6e6 for t in weeks})           # mln USD
    st.put("1d", "fed_tga", {t: 8.5e5 for t in weeks})              # mln USD
    st.put("1d", "fed_rrp", {t: 50.0 for t in range(weeks[0], weeks[-1] + 1, D)})   # mld USD, dziennie
    st.put("1d", "fred_m2", {t_of("2026-09-01"): 22000.0})
    info = C.compute(st, {})
    nl = st.series["1d"]["net_liq"]
    assert abs(nl[weeks[0] + 3 * D] - (6.6e12 - 8.5e11 - 5e10)) < 1e6     # dni między tygodniami uzupełnione
    assert st.series["1d"]["m2"][t_of("2026-09-01")] == 2.2e13
    bad = Store(str(tmp_path / "b"))
    bad.put("1d", "fed_assets", {t: 6.6e6 for t in weeks})
    bad.put("1d", "fed_tga", {t: 8.5e5 for t in weeks})
    bad.put("1d", "fed_rrp", {t: 50.0 for t in weeks})
    info = C.compute(bad, {"cycle": {"units": {"fed_assets": 1.0, "fed_tga": 1.0, "fed_rrp": 1.0, "fred_m2": 1.0}}})
    assert "net_liq" not in bad.series["1d"] and "podejrzana" in info["net_liq"]


def test_fred_already_in_usd(tmp_path):
    """TradingView podaje serie FRED już w USD (01.11.2026: WALCL 6,75e12) — bez mnożenia przez jednostki."""
    st = Store(str(tmp_path))
    weeks = [t_of("2026-01-07") + i * 7 * D for i in range(20)]
    st.put("1d", "fed_assets", {t: 6.7456e12 for t in weeks})
    st.put("1d", "fed_tga", {t: 9.997e11 for t in weeks})
    st.put("1d", "fed_rrp", {t: 4.375e9 for t in range(weeks[0], weeks[-1] + 1, D)})
    st.put("1d", "fred_m2", {t_of("2026-09-01"): 2.34139e13})
    info = C.compute(st, {})
    nl = st.series["1d"]["net_liq"]
    assert abs(nl[weeks[-1]] - (6.7456e12 - 9.997e11 - 4.375e9)) < 1e7 and "net_liq" not in info
    assert abs(st.series["1d"]["m2"][t_of("2026-09-01")] - 2.34139e13) < 1e8


def test_mvrv_z_expanding_std():
    """Odchylenie liczone od początku do danego dnia: dawny szczyt nie jest zaniżany przez późniejsze kapitalizacje."""
    days = [t_of("2015-01-01") + i * D for i in range(400)]
    mc = {t: 1e9 * (1 + i / 100) for i, t in enumerate(days)}
    mc[days[100]] = 5e9                                                 # wczesny szczyt
    mc.update({t: 1e11 for t in days[300:]})                            # później dużo większy rynek
    mv = {t: 2.0 for t in days}
    z = C.zscore_expanding(mc, mv)
    assert days[10] not in z and z[days[100]] > 5                       # z odchyleniem z całej historii byłoby < 0,1
    import statistics
    first = days[31]
    caps = [mc[t] for t in days[:32]]
    assert abs(z[first] - (mc[first] / 2) / statistics.pstdev(caps)) < 1e-6


class Resp:
    def __init__(self, js, status=200):
        self.status_code, self._js, self.text = status, js, ""

    def json(self):
        return self._js


class CMSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, params))
        if params is not None:
            rows = [{"asset": "btc", "time": "2010-07-18T00:00:00.000000000Z", "CapMVRVCur": "146.0",
                     "CapMrktCurUSD": "295959.1"}]
            return Resp({"data": rows, "next_page_url": "https://next"})
        return Resp({"data": [{"asset": "btc", "time": "2010-07-19T00:00:00.000000000Z", "CapMVRVCur": "120.5",
                               "CapMrktCurUSD": ""}]})


def test_fetch_coinmetrics_pages_and_increments(tmp_path):
    st = Store(str(tmp_path))
    sess = CMSession()
    n = C.fetch_coinmetrics(st, 0, session=sess)
    assert n == 2 and st.series["1d"]["cm_mvrv_btc"][t_of("2010-07-19")] == 120.5
    assert t_of("2010-07-19") not in st.series["1d"]["cm_mcap_btc"]        # pusta wartość pominięta
    assert sess.calls[0][1]["start_time"] == "2010-01-01" and sess.calls[1] == ("https://next", None)
    sess2 = CMSession()
    C.fetch_coinmetrics(st, 0, session=sess2)
    assert sess2.calls[0][1]["start_time"] == "2010-07-09"                  # od ostatniego punktu − 10 dni
    err = C.run(st, {"cycle": {}}, 0, session=type("S", (), {"get": lambda *a, **k: Resp({}, 500)})())[1]
    assert "HTTP 500" in err


class DailyTV:
    def __init__(self):
        self.req = []

    def bars(self, symbol, interval, n):
        self.req.append((symbol, interval, n))
        if symbol == "BAD:X":
            raise RuntimeError("symbol_error")
        return [(t_of("2026-10-29") + 14 * 3600 + i * D, 100.0 + i) for i in range(3)]


def test_collect_tv_daily_symbols(tmp_path):
    st = Store(str(tmp_path))
    tv = DailyTV()
    cfg = {"tradingview": {"symbols": {}, "daily_symbols": {"spx": "SP:SPX", "bad": "BAD:X"}}}
    errs = main.collect_tv(tv, st, cfg, t_of("2026-11-01"), False)
    assert sorted(st.series["1d"]["spx"]) == [t_of("2026-10-29"), t_of("2026-10-30"), t_of("2026-10-31")]
    assert ("SP:SPX", "1D", 20000) in tv.req and len(errs) == 1 and "spx" not in st.series["1h"]
    main.collect_tv(tv, st, cfg, t_of("2026-11-01"), False)
    assert tv.req[-2][2] == 5 + 1                                              # potem tylko ostatnie dni
