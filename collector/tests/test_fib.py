"""Offline tests of manual Fibonacci setups: python -m pytest collector/tests -q"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fib as F  # noqa: E402
import ema_monitor as E  # noqa: E402
from test_ema import NOW, FakeBinance, FakeTG, cfg  # noqa: E402

LONG = {"id": "1", "coin": "SOL", "high": 200.0, "low": 100.0, "dir": "long"}
SHORT = {"id": "2", "coin": "SOL", "high": 200.0, "low": 100.0, "dir": "short"}


def test_levels_long_and_short():
    lv = F.levels(200, 100, "long")
    assert abs(lv[0.705] - 129.5) < 1e-9 and lv[0.75] == 125.0 and abs(lv[0.786] - 121.4) < 1e-9
    s = F.levels(200, 100, "short")
    assert abs(s[0.705] - 170.5) < 1e-9 and s[0.75] == 175.0 and abs(s[0.786] - 178.6) < 1e-9


def test_evaluate_statuses():
    st = lambda p, s=LONG: F.evaluate(s, p, 2)["status"]  # noqa: E731
    assert [st(150), st(131), st(127), st(121.4), st(115), st(99)] == \
        ["above", "near", "zone", "zone", "deep", "invalid"]
    assert [st(p, SHORT) for p in (150, 168, 172, 185, 201)] == ["above", "near", "zone", "deep", "invalid"]
    assert F.evaluate(LONG, None, 2)["status"] is None


def test_alert_sequence_and_rearm():
    st = {}
    run = lambda p: F.check([dict(LONG)], {"SOL": p}, st, 2)  # noqa: E731
    assert run(150) == []                                   # new setup: armed silently
    m = run(131)
    assert len(m) == 1 and "zbliża się" in m[0]
    assert run(130.5) == []                                 # no repeat
    m = run(127)
    assert len(m) == 1 and "w strefie" in m[0] and "0.75 = $125.00" in m[0]
    m = run(118)
    assert len(m) == 1 and "przebiła 0.786" in m[0]
    m = run(99)
    assert len(m) == 1 and "unieważniony" in m[0]
    st.clear()
    run(150)
    run(131)
    run(140)                                                # 140/129.5 = +8% > 3% → re-armed
    assert len(run(131)) == 1


def test_parse_commands():
    k, s = F.parse_command("/fib sol 250 120 long term setup")
    assert k == "add" and s == {"coin": "SOL", "high": 250.0, "low": 120.0, "dir": "long", "label": "term setup"}
    k, s = F.parse_command("/fib@MojBot ETH 2100,5 2600 short")
    assert s["high"] == 2600 and s["low"] == 2100.5 and s["dir"] == "short" and s["label"] == ""
    assert F.parse_command("/fib SOL 250")[0] == "error"
    assert F.parse_command("/usun 3") == ("del", "3")
    assert F.parse_command("/fiby") == ("list", None)
    assert F.parse_command("hello") is None and F.parse_command("/inna") is None


def test_command_helpers_add_list_delete():
    user = []
    s1 = F.add_setup(user, F.parse_command("/fib SOL 200 100 long swing")[1], NOW)
    s2 = F.add_setup(user, F.parse_command("/fib BTC 120000 90000")[1], NOW)
    assert (s1["id"], s2["id"]) == ("1", "2") and s1["src"] == "telegram"
    txt = F.added_text(s1, 127, 2)
    assert "Dodano" in txt and "0.75 = $125.00" in txt and "w strefie" in txt
    assert "brak ceny" in F.added_text(s2, None, 2)
    cfg_setups = [{"id": "c1", "coin": "ETH", "high": 3, "low": 2}]
    lst = F.list_text(cfg_setups + user, {"SOL": 127}, 2)
    assert "Setupy Fibo" in lst and "[c1]" in lst and "brak ceny" in lst
    assert "Usunięto" in F.delete_setup(user, cfg_setups, "1")
    assert "config.yaml" in F.delete_setup(user, cfg_setups, "c1")
    assert "Nie ma" in F.delete_setup(user, cfg_setups, "9")
    assert [s["coin"] for s in user] == ["BTC"]
    assert "Brak setupów" in F.list_text([], {}, 2)


def test_coin_prices_binance_then_hyperliquid():
    p = F.coin_prices({"SOL", "HYPE", "NOPE"}, {"SOLUSDT": 95.0}, hl=lambda: {"HYPE": 40.0, "SOL": 1.0})
    assert p == {"SOL": 95.0, "HYPE": 40.0}

    def boom():
        raise RuntimeError("down")
    assert F.coin_prices({"HYPE"}, {}, hl=boom) == {}


def test_config_setups():
    s = F.from_config([{"coin": "sol", "high": 250, "low": 120, "label": "x"},
                       {"coin": "eth", "high": 1, "low": 2}, {"coin": "btc"}, {"coin": "xrp", "high": 3, "low": 1, "dir": "short"}])
    assert [(x["id"], x["coin"], x["dir"]) for x in s] == [("c1", "SOL", "long"), ("c4", "XRP", "short")]


def test_run_with_fib_from_telegram_and_config(tmp_path):
    st = str(tmp_path)
    c = cfg()
    c["fib"] = {"near_pct": 2, "setups": [{"coin": "AAA", "high": 200, "low": 50, "label": "z configu"}]}
    # setups added in Telegram live in bot.json (written by bot.py)
    with open(os.path.join(st, "bot.json"), "w") as f:
        json.dump({"fib_user": [{"id": "1", "coin": "HYPE", "high": 60, "low": 20, "dir": "long", "label": "hl",
                                 "src": "telegram"}]}, f)
    tg = FakeTG()
    E.run(c, st, now=NOW, client=FakeBinance(), telegram=tg, remote=None, hl=lambda: {"HYPE": 30.0})
    pub = json.load(open(os.path.join(st, "pub", "fib.json")))
    rows = {r["id"]: r for r in pub["setups"]}
    assert set(rows) == {"c1", "1"}
    assert rows["c1"]["chart"] is True and rows["1"]["chart"] is False and rows["1"]["price"] == 30.0
    assert rows["1"]["status"] == "zone"                     # zone of 20→60 long = 28.56–31.8
    assert tg.sent == []                                     # new setups are armed silently
    # next run: HYPE drops through 0.786 → alert to the market channel (group)
    E.run(c, st, now=NOW + 300, client=FakeBinance(now=NOW + 300), telegram=tg, remote=None, hl=lambda: {"HYPE": 27.0})
    assert len(tg.sent) == 1 and "Fibo" in tg.sent[0] and "HYPE" in tg.sent[0] and "0.786" in tg.sent[0]
    assert tg.kinds == ["market"]


def test_run_respects_mute_and_publishes_it(tmp_path):
    st = str(tmp_path)
    c = cfg()
    c["fib"] = {"near_pct": 2, "setups": []}
    with open(os.path.join(st, "bot.json"), "w") as f:
        json.dump({"fib_user": [{"id": "1", "coin": "HYPE", "high": 60, "low": 20, "dir": "long", "label": ""}],
                   "mute_until": NOW + 3600}, f)
    tg = FakeTG()
    E.run(c, st, now=NOW, client=FakeBinance(), telegram=tg, remote=None, hl=lambda: {"HYPE": 30.0})
    E.run(c, st, now=NOW + 300, client=FakeBinance(now=NOW + 300), telegram=tg, remote=None, hl=lambda: {"HYPE": 27.0})
    assert tg.sent == []
    assert json.load(open(os.path.join(st, "pub", "ema.json")))["mute_until"] == NOW + 3600


def test_old_state_setups_used_until_bot_runs(tmp_path):
    st = {"fib_user": [{"id": "1", "coin": "SOL"}]}
    assert E.load_bot_state(str(tmp_path), st)["fib_user"][0]["coin"] == "SOL"


D = 86400
PC = dict(F.PROPOSAL_DEFAULTS)


def _hl(path, start=0):
    """[[t, high, low]] from a list of closes (±1% wicks)."""
    return [[start + i * D, c * 1.01, c * 0.99] for i, c in enumerate(path)]


def test_candidates_long_short_dedupe_and_size_filter():
    up = [100] * 200 + [100 + i for i in range(100)] + [199 - i * 0.5 for i in range(65)]   # rally then pullback
    c = F.candidates("AAA", _hl(up), PC)
    longs = [x for x in c if x["dir"] == "long"]
    assert longs and abs(longs[-1]["low"] - 99) < 1e-9 and abs(longs[-1]["high"] - 199 * 1.01) < 1e-9
    assert all(x["win"] for x in c) and len({(x["high"], x["low"], x["dir"]) for x in c}) == len(c)
    flat = [100 + (i % 3) for i in range(400)]                                             # 2–3% noise only
    assert F.candidates("BBB", _hl(flat), PC) == []
    down = [200 - i * 0.3 for i in range(300)] + [110 + i * 0.4 for i in range(80)]         # fall then bounce
    assert any(x["dir"] == "short" for x in F.candidates("CCC", _hl(down), PC))


def test_proposals_only_near_or_in_zone_sorted_and_command():
    cands = [{"coin": "A", "dir": "long", "high": 200.0, "low": 100.0, "win": "3M"},   # zone 121.4–129.5
             {"coin": "B", "dir": "long", "high": 200.0, "low": 100.0, "win": "1M"},
             {"coin": "C", "dir": "long", "high": 200.0, "low": 100.0, "win": "1R"}]
    out = F.proposals(cands, {"A": 125.0, "B": 133.0, "C": 180.0}, PC)
    assert [(p["coin"], p["status"]) for p in out] == [("A", "zone"), ("B", "near")]
    assert F.command_for(out[0]) == "/fib A 200 100 long auto 3M"
    assert F.parse_command(F.command_for(out[0]))[1]["label"] == "auto 3M"     # command round-trips


def test_run_publishes_proposals_with_high_low(tmp_path):
    st = str(tmp_path)
    E.run(cfg(), st, now=NOW, client=FakeBinance(), remote=None, hl=lambda: {})
    hl = json.load(open(os.path.join(st, "hl.json")))
    assert {"AAAUSDT", "BBBUSDT", "JUPUSDT"} <= set(hl) and 380 <= len(hl["AAAUSDT"]) <= 400
    pub = json.load(open(os.path.join(st, "pub", "fib.json")))
    assert "proposals" in pub and pub["candidates"] >= 1
    for p in pub["proposals"]:
        assert p["status"] in ("zone", "near") and p["cmd"].startswith("/fib ")
