"""Offline tests, poprawka 116: tabela „Gdzie warto zajrzeć” na Pulpicie (pulse.py)."""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import main  # noqa: E402
import pulse as P  # noqa: E402
from store import Store  # noqa: E402

D, H = 86400, 3600
NOW = 1_790_000_000 - 1_790_000_000 % D + 6 * H
CFG = {"watchlist": ["SOL"]}


def calm(store, sid, base, amp=0.01, days=800, end=NOW):
    """Spokojna seria dzienna: mała fala wokół `base`."""
    t0 = end - end % D
    store.put("1d", sid, {t0 - i * D: base * (1 + amp * math.sin(i / 5)) for i in range(days)})
    store.put("1h", sid, {end - end % H: base * (1 + amp * math.sin(0))})


def test_calm_market_gives_no_rows(tmp_path):
    st = Store(str(tmp_path))
    for sid, b in (("px_btc", 60000), ("px_eth", 2000), ("total", 2e12), ("oi_total", 4e10), ("px_sol", 100)):
        calm(st, sid, b)
    res = P.build(st, CFG, NOW)
    assert res["rows"] == [] and res["updated"] == NOW and st.state["pulse"] == {}


def test_big_move_is_one_row_per_theme_and_new_only_after_first_scan(tmp_path):
    st = Store(str(tmp_path))
    for sid, b in (("px_btc", 60000), ("px_eth", 2000), ("px_sol", 100), ("oi_total", 4e10), ("oi_sol", 2e9)):
        calm(st, sid, b)
    P.build(st, CFG, NOW)                                        # pierwszy skan: pamięć pusta, nic nie jest „nowe”
    t = NOW + 2 * H
    for sid, v in (("px_btc", 51000), ("px_sol", 80), ("oi_sol", 1.5e9)):
        st.put("1h", sid, {t - t % H: v})
    res = P.build(st, CFG, t)
    rows = {r["key"]: r for r in res["rows"]}
    assert set(rows) == {"ceny", "oi"}                           # BTC i SOL w jednym wierszu
    c = rows["ceny"]
    assert c["new"] is True and c["tab"] == "oi" and c["title"].startswith("BTC −1") and c["title"].endswith("w 7 dni") and "SOL −2" in c["detail"]
    assert "też:" in c["detail"] and "Mocniejszy spadek" in c["hist"] and "z 2 lat" in c["hist"]
    assert rows["oi"]["title"].startswith("Open interest SOL −2") and rows["oi"]["href"].startswith("oi.html#s=oi_sol")
    # dobę później: ten sam wiersz już nie jest nowy, data „od kiedy” zostaje
    t2 = t + 25 * H
    for sid, v in (("px_btc", 51000), ("px_sol", 80), ("oi_sol", 1.5e9)):
        st.put("1h", sid, {t2 - t2 % H: v})
        st.put("1d", sid, {t2 - t2 % D - 7 * D: {"px_btc": 60000, "px_sol": 100, "oi_sol": 2e9}[sid]})
    res2 = P.build(st, CFG, t2)
    r2 = {r["key"]: r for r in res2["rows"]}
    assert r2["ceny"]["new"] is False and r2["ceny"]["since"] == t


def test_first_scan_arms_silently_and_memory_expires(tmp_path):
    st = Store(str(tmp_path))
    calm(st, "px_btc", 60000)
    st.put("1h", "px_btc", {NOW - NOW % H: 50000})
    res = P.build(st, CFG, NOW)                                  # pierwszy skan po wgraniu
    assert [r["key"] for r in res["rows"]] == ["ceny"] and res["rows"][0]["new"] is False
    st.put("1h", "px_btc", {NOW + 3 * D: 60000})
    st.put("1d", "px_btc", {NOW - NOW % D + 3 * D - 7 * D: 60000})
    assert P.build(st, CFG, NOW + 3 * D)["rows"] == [] and st.state["pulse"] == {}      # po 48 h pamięć wyczyszczona


def test_liquidations_funding_levels_and_ema(tmp_path):
    st = Store(str(tmp_path))
    t0 = NOW - NOW % D
    st.put("1d", "liq_btc_long", {t0 - i * D: 3e7 for i in range(1, 100)})
    st.put("1d", "liq_btc_short", {t0 - i * D: 1e7 for i in range(1, 100)})
    th = NOW - NOW % H
    st.put("1h", "liq_btc_long", {th - k * H: 4e6 for k in range(24)})        # 96M long + 24M short = 3× zwykłego dnia
    st.put("1h", "liq_btc_short", {th - k * H: 1e6 for k in range(24)})
    st.put("1h", "fund_sol", {th: -31.0})
    st.put("1h", "fund_btc", {th: 5.0})
    st.put("1d", "mvrvz_btc", {t0 - i * D: 1.0 + 0.5 * math.sin(i / 9) for i in range(1, 800)})
    st.put("1d", "mvrvz_btc", {t0: 0.2})
    ema = {"period": 200, "coins": [{"s": "BTC", "p": 59000.0, "e": 60000.0, "d": -1.67, "side": -1, "cross_t": NOW - D},
                                    {"s": "XYZ", "p": 1.0, "e": 2.0, "d": -50.0, "side": -1, "cross_t": NOW - D}]}
    P.build(st, CFG, NOW - 2 * H, ema={"coins": []})
    rows = {r["key"]: r for r in P.build(st, CFG, NOW, ema=ema)["rows"]}
    assert set(rows) == {"likwidacje", "funding", "poziom:mvrvz_btc", "ema"}
    assert rows["likwidacje"]["title"] == "Likwidacje BTC $120,0M w 24 h" and "×3,0 zwykłego dnia" in rows["likwidacje"]["hist"]
    assert "Longi $96,0M (80%) · shorty $24,0M" in rows["likwidacje"]["detail"]
    assert rows["funding"]["title"] == "Funding SOL −31,0% rocznie" and "shorty płacą longom" in rows["funding"]["detail"]
    assert rows["poziom:mvrvz_btc"]["title"] == "MVRV-Z BTC 0,20 — nisko" and "Niżej w mniej niż 1% dni z 2 lat" in rows["poziom:mvrvz_btc"]["hist"]
    assert rows["ema"]["title"] == "BTC przeciął EMA200 w dół" and rows["ema"]["new"] is True and rows["ema"]["href"] == "ema.html#c=BTC"
    assert all("score" not in r and isinstance(r["since"], int) for r in rows.values())


def test_lamp_rows_use_real_dates():
    class S:
        state = {"pulse": {}}
        series = {"1h": {}, "1d": {}}

        def latest(self, sid):
            return None
    lamps = {"lamps": {"selloff": {"name": "Wyprzedaż", "on": True, "level": 1, "since": NOW - 16 * D, "value": -24.7, "mvrvz": 0.37,
                                   "btc_chg": -20.9, "stats": [{"n": 25, "good": 16, "med": -7.8}], "episodes": []},
                       "big_wave": {"name": "Indeks altów", "on": False, "level": 0, "value": 2.8, "stats": [],
                                    "episodes": [[NOW - 60 * D, NOW - 15 * D, 1, -17.4]]}}}
    rows = {r["key"]: r for r in P.build(S(), {}, NOW, lamps_res=lamps)["rows"]}
    a = rows["lampka:selloff"]
    assert a["title"] == "Lampka Wyprzedaż świeci" and a["since"] == NOW - 16 * D and a["new"] is False and a["tab"] == "alt"
    assert "−25%" in a["detail"] and "<" not in a["detail"] and "niżej 16 z 25 razy, mediana −8%" in a["hist"]
    assert rows["lampka-off:big_wave"]["title"] == "Lampka Indeks altów zgasła" and "39" not in rows["lampka-off:big_wave"]["detail"][:8]


def test_scan_writes_pulpit_json(tmp_path):
    from test_collector import CG, FakeCoinalyze, FakeTV, _cfg
    import alerts
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    main.run(d, _cfg(), now=1_790_000_000, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    assert not os.path.exists(os.path.join(d, P.FILE))           # backfill nie liczy Pulpitu
    _, _, _ = main.run(d, _cfg(), now=1_790_000_000 + 2 * H, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    res = json.load(open(os.path.join(d, P.FILE), encoding="utf-8"))
    assert res["updated"] == 1_790_000_000 + 2 * H and isinstance(res["rows"], list) and res["rules"]["liq_x"] == 1.5
    meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
    assert meta["info"]["pulpit"]["rows"] == len(res["rows"])
    _, _, _ = main.run(d, _cfg(pulpit={"enabled": False}), now=1_790_000_000 + 4 * H, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG)
    assert json.load(open(os.path.join(d, P.FILE), encoding="utf-8"))["updated"] == 1_790_000_000 + 2 * H


def test_number_formats():
    assert P.pct(-14.62) == "−14,6%" and P.pct(3.14) == "+3,1%" and P.pct(0) == "0,0%"
    assert P.usd(44.11e9) == "$44,11B" and P.usd(139.6e6) == "$139,6M" and P.price(63179.4) == "$63 179" and P.price(0.0589) == "$0,0589"
    assert P.share(0.4) == "w mniej niż 1% dni" and P.share(6.2) == "tylko w 6% dni"
