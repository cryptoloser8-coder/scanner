import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hl_wallets as W  # noqa: E402

DAY = 86400
NOW = 1795000000.0


class Resp:
    def __init__(self, obj, code=200):
        self._o, self.status_code, self.text = obj, code, str(obj)
        self.content = self.text.encode()

    def json(self):
        return self._o

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(self.status_code)


def addr(i):
    return f"0x{i:040x}"


def F(t, coin, side, sz, start, pnl=0.0, d="Close Long"):
    return {"time": int(t * 1000), "coin": coin, "side": side, "sz": str(sz), "startPosition": str(start),
            "closedPnl": str(pnl), "fee": "0", "tid": int(t), "dir": d}


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Fake:
    """Konta 0–9: zarabiające ≥ $100k (0–3 dobre w longach, 4–5 dobre w shortach, 6 młode, 7 bot, 8–9 słabe);
    10–14: tracące; 15: bez obrotów."""
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        rows = []
        for i in range(16):
            win = i < 10
            rows.append({"ethAddress": addr(i), "accountValue": str(2e6 - i * 1e5 if win else 5e4),
                         "windowPerformances": [["month", {"pnl": "1", "roi": "0", "vlm": "0" if i == 15 else "1000"}],
                                                ["allTime", {"pnl": "100000" if win else "-5000", "roi": "0", "vlm": "1"}]]})
        return Resp({"leaderboardRows": rows})

    def post(self, url, json=None, headers=None, timeout=None):
        t, u = json["type"], json.get("user")
        self.calls.append(t)
        i = int(u, 16) if u else None
        if t == "metaAndAssetCtxs":
            return Resp([{"universe": [{"name": n} for n in ("BTC", "ETH", "PEPE")]},
                         [{"markPx": "100", "prevDayPx": "90"}, {"markPx": "10", "prevDayPx": "10"}, {"markPx": "1", "prevDayPx": "1"}]])
        if t == "portfolio":
            age = 100 if i == 6 else 500
            return Resp([["perpAllTime", {"pnlHistory": [[(NOW - age * DAY) * 1000, "0"], [NOW * 1000, "10"]],
                                          "accountValueHistory": [[(NOW - age * DAY) * 1000, "100"], [(NOW - 50 * DAY) * 1000, "200"],
                                                                  [NOW * 1000, "150"]]}],
                         ["perpMonth", {"pnlHistory": [[0, "0"], [1, "500"]]}]])
        if t == "userFills":
            out, T = [], NOW - 30 * DAY
            good_long, good_short = i in (0, 1, 2, 3), i in (4, 5)
            n = 400 if i == 7 else 12
            for k in range(n):
                tt = T + k * (60 if i == 7 else 3600)
                if i == 7 or good_long or i in (6, 8, 9):
                    pnl = 5 if (good_long or i == 6) else (-5 if k % 2 else 3)
                    out += [F(tt, "BTC", "B", 1, 0, 0, "Open Long"), F(tt + 10, "BTC", "A", 1, 1, pnl, "Close Long")]
                if good_short:
                    out += [F(tt, "PEPE", "A", 10, 0, 0, "Open Short"), F(tt + 10, "PEPE", "B", 10, -10, 4, "Close Short")]
            return Resp(out)
        if t == "clearinghouseState":
            if i in (8, 9):
                return Resp({"marginSummary": {"accountValue": "1000"}, "assetPositions": []})
            L = i in (0, 1, 2, 3, 10, 11, 12)
            return Resp({"marginSummary": {"accountValue": "100000"}, "assetPositions": [
                {"position": {"coin": "BTC" if i % 2 else "PEPE", "szi": "1" if L else "-1", "entryPx": "90", "positionValue": "100000",
                              "unrealizedPnl": "500", "liquidationPx": "60", "leverage": {"type": "cross", "value": 5 if i < 10 else 25},
                              "marginUsed": "20000", "cumFunding": {"sinceOpen": "12"}}},
                {"position": {"coin": "xyz:IBM", "szi": "1", "positionValue": "5"}}]})
        if t == "frontendOpenOrders":
            return Resp([{"coin": "BTC", "side": "A", "limitPx": "80", "triggerPx": "85", "isTrigger": True, "orderType": "Stop Market",
                          "sz": "1", "reduceOnly": True}, {"coin": "@107", "side": "B", "limitPx": "1", "orderType": "Limit"}])
        return Resp({}, 400)


def test_sito_and_positions(tmp_path):
    clk, s = Clock(), Fake()
    sd, dd = str(tmp_path / "sito"), str(tmp_path / "hl")
    n, st = W.run_sito(sd, minutes=600, session=s, sleep=clk.sleep, clock=clk)
    assert n == 10 and st["round_total"] == 10                  # konta 10–15 nie są kandydatami (strata / brak obrotów)
    ch = st["checked"]
    assert ch[addr(0)]["sides"] == ["L"] and ch[addr(4)]["sides"] == ["S"]
    assert ch[addr(6)]["why"] == "za młode konto" and ch[addr(7)]["why"] == "bot / market maker"
    assert ch[addr(8)]["sides"] == [] and ch[addr(0)]["dd"] == -25.0 and ch[addr(0)]["p30"] == 500
    assert st["in_sito"] == {"L": 4, "S": 2} and len(st["losers"]) == 5
    # druga runda dopiero po 7 dniach
    n2, _ = W.run_sito(sd, minutes=600, session=s, sleep=clk.sleep, clock=clk)
    assert n2 == 0

    g = W.run_positions(dd, sd, session=s, sleep=clk.sleep, clock=clk)
    assert g["L"]["n"] == 4 and g["S"]["n"] == 2 and g["R"]["n"] == 5
    L = g["L"]
    assert L["long"] == 400000 and L["short"] == 0 and L["lpct"] == 100.0 and L["only_long"] == 4
    assert L["coins"]["BTC"]["long"] == 200000 and L["coins"]["ALT"]["long"] == 200000 and L["coins"]["ALT"]["nL"] == 2
    assert L["lev_buckets"][1] == ["×3–10", 4, 0] and L["eff_lev"] == 1.0
    assert g["R"]["lev_buckets"][3][1] + g["R"]["lev_buckets"][3][2] == 5      # tracący na ×25
    wal = W._read(os.path.join(dd, "hl_wallets.json"), {})["wallets"]
    w0 = next(w for w in wal if w["addr"] == addr(1))
    p = w0["pos"][0]
    assert len(w0["pos"]) == 1 and p["c"] == "BTC" and p["L"] and p["mark"] == 100000.0 and p["fund"] == -12
    assert w0["ord"] == [{"c": "BTC", "kind": "sl", "buy": False, "px": 85.0, "sz": 1.0, "reduce": True}]
    assert w0["prof"]["L"]["n"] == 12 and w0["ev"] == []
    ser = W._read(os.path.join(dd, "hl_groups.json"), {})["series"]
    assert ser["L_all_lpct"][-1][1] == 100.0 and ser["S_ALT_short"][-1][1] == 100000
    now = W._read(os.path.join(dd, "hl_now.json"), {})
    assert now["prices"]["BTC"]["ch24"] == 11.11
    meta = W._read(os.path.join(dd, "hl_meta.json"), {})
    assert meta["sito"]["checked"] == 10 and meta["sito"]["left"] == 0 and meta["groups_n"] == {"L": 4, "S": 2, "R": 5}


def test_events_and_changes():
    prev = {"pos": [{"c": "BTC", "L": True, "size": 1000000, "mark": 1}, {"c": "ETH", "L": False, "size": 50000}], "ev": []}
    cur = [{"c": "BTC", "L": True, "size": 1500000, "entry": 1, "mark": 1}, {"c": "SOL", "L": True, "size": 20000, "entry": 2, "mark": 2}]
    ev = W.events(prev, cur, NOW)
    kinds = sorted(e[1] for e in ev)
    assert kinds == ["dokupił", "otworzył", "zamknął"] and W.events(None, cur, NOW) == []
    t = int(NOW)
    series = {"L_ALT_flowL": [[t - 8 * DAY, 9e6], [t - 3 * DAY, 1e6], [t - 2 * 3600, 2e6], [t, 3e6]],
              "S_BTC_flowS": [[t - 3600, -4e5]], "L_ALT_long": [[t - DAY, 1e9]]}
    ch = W.changes(series, t)
    assert (ch[0]["g"], ch[0]["c"], ch[0]["side"], ch[0]["delta"], ch[0]["win"]) == ("L", "ALT", "long", 6e6, "7 dni")
    assert "since" not in ch[0] and ch[1]["delta"] == -4e5 and ch[1]["since"] == t - 3600 and len(ch) == 2


def test_flows_same_wallets_only():
    """93: przepływ = zmiana ilości × cena u portfeli obecnych przed i po; nowi / odchodzący osobno; ruch ceny się nie liczy."""
    P = lambda c, L, size, mark: {"c": c, "L": L, "size": size, "mark": mark}
    prev = {"groups": {"L": ["a", "b", "x"], "S": [], "R": []},
            "pos": {"a": [["BTC", True, 10, 100]], "b": [["SOL", False, 5, 10]], "x": [["ETH", True, 2, 50]]}}
    wallets = [{"addr": "a", "g": ["L"], "pos": [P("BTC", True, 1320, 110)]},     # 10 → 12 BTC po 110: +220 (cena +10% nie liczy się)
               {"addr": "b", "g": ["L"], "pos": []},                               # zamknął short SOL: −5 × 10 = −50
               {"addr": "n", "g": ["L"], "pos": [P("ETH", True, 500, 50)]}]        # nowy w grupie — nie przepływ
    f, comp = W.group_flows(prev, wallets)
    assert round(f["L"]["BTC"]["long"]) == 220 and f["L"]["SOL"]["short"] == -50 and round(f["L"]["all"]["long"]) == 220
    assert f["L"]["ETH"]["long"] == 0
    assert comp["L"] == {"in": 1, "out": 1, "n": 3, "long_in": 500, "short_in": 0, "long_out": 100, "short_out": 0}
    f2, comp2 = W.group_flows(prev, wallets[:2] + wallets[2:], failed=["x"])     # nieudane pobranie ≠ wyjście z grupy
    assert comp2["L"]["out"] == 0
    m = W.members_doc(wallets, prev, ["x"], NOW)
    assert "x" in m["groups"]["L"] and m["pos"]["x"] == [["ETH", True, 2, 50]] and "b" not in m["pos"]
    series = {}
    W.append_flows(series, 900, f, {"L": {"n": 3}})
    W.append_flows(series, 900, f, {"L": {"n": 3}})                             # ten sam kwadrans — sumuje
    assert series["L_BTC_flowL"] == [[900, 440]] and series["L_n"] == [[900, 3]]


def test_hopeless_wallet_skips_portfolio(tmp_path):
    class Few(Fake):
        def post(self, url, json=None, headers=None, timeout=None):
            if json["type"] == "userFills":
                T = NOW - DAY
                return Resp([F(T, "BTC", "B", 1, 0, 0, "Open Long"), F(T + 10, "BTC", "A", 1, 1, 5, "Close Long")])
            return super().post(url, json, headers, timeout)
    clk, s = Clock(), Few()
    _, st = W.run_sito(str(tmp_path), minutes=600, session=s, sleep=clk.sleep, clock=clk)
    assert "portfolio" not in s.calls and st["checked"][addr(0)]["why"] == "za mało zagrań"


def test_daily_results_and_round_snapshot(tmp_path):
    clk, s = Clock(), Fake()
    sd, dd = str(tmp_path / "sito"), str(tmp_path / "hl")
    W.run_sito(sd, minutes=600, session=s, sleep=clk.sleep, clock=clk)
    rounds = os.listdir(os.path.join(sd, "rounds"))
    snap = W._read(os.path.join(sd, "rounds", rounds[0]), {})
    assert len(rounds) == 1 and snap["members"][addr(0)][0] == "L" and len(snap["losers"]) == 5
    W.run_positions(dd, sd, session=s, sleep=clk.sleep, clock=clk)
    month = W.time.strftime("%Y-%m", W.time.gmtime(clk.t))
    doc = W._read(os.path.join(dd, "daily", month + ".json"), {})
    day = W.time.strftime("%Y-%m-%d", W.time.gmtime(clk.t))
    rows = doc["days"][day]
    assert len(rows) == 6 + 5 and doc["cols"][0] == "id"                      # 4 L + 2 S + 5 tracących
    r0 = next(r for r in rows if doc["ids"][r[0]] == addr(0))
    assert r0[1] == "L" and r0[3] == 100000 and r0[4] == 2000000
    assert any(r[1] == "R" and r[3] == -5000 for r in rows)
    n_get = s.calls.count("leaderboard")
    W.run_positions(dd, sd, session=s, sleep=clk.sleep, clock=clk)          # ten sam dzień — bez drugiego zapisu
    assert len(W._read(os.path.join(dd, "daily", month + ".json"), {})["days"]) == 1 and n_get == 0
    assert W._read(os.path.join(dd, "hl_meta.json"), {})["daily_saved"] is False


def test_verdict_from_saved_numbers_and_young_split():
    """92: werdykt z zapisanych liczb (nowe progi bez pobierania) + młodsze / starsze osobno."""
    base = {"trips": 30, "fpd": 5, "L": {"n": 15, "win": 60, "pf": 2.0, "pnl": 100}, "S": {"n": 15, "win": 100, "pf": None, "pnl": 50}}
    old = dict(base, age=500)
    young = dict(base, age=200)
    baby = dict(base, age=100)
    assert W.verdict(old) == (["L", "S"], None)               # brak z÷s przy zysku = same zyskowne zagrania
    assert W.verdict(young) == (["L", "S"], None)
    assert W.verdict(baby) == ([], "za młode konto")
    assert W.verdict(young, dict(W.SITO, min_age_days=365)) == ([], "za młode konto")
    assert W.verdict(dict(base, age=500, S={"n": 15, "win": 0, "pf": None, "pnl": -5}))[0] == ["L"]
    ch = {"a": dict(young, sides=[], why="za młode konto"), "b": dict(old, sides=["L", "S"], why=None), "c": {"why": "x", "sides": []}}
    assert W.reverdict(ch) == 1 and ch["a"]["sides"] == ["L", "S"] and ch["c"]["sides"] == []
    pos = [{"c": "BTC", "L": True, "size": 1000, "lev": 5}]
    wallets = [{"addr": "a", "g": ["L", "S"], "av": 500, "pos": pos}, {"addr": "b", "g": ["L", "S"], "av": 1000, "pos": []}]
    sp = W.age_split(wallets, ch)
    L = sp["groups"]["L"]
    assert sp["young_days"] == 365 and sp["min_age_days"] == 180
    assert L["mlode"]["members"] == 1 and L["mlode"]["in_pos"] == 1 and L["mlode"]["long"] == 1000 and L["mlode"]["eff_lev"] == 2.0
    assert L["starsze"]["members"] == 1 and L["starsze"]["in_pos"] == 0 and L["starsze"]["age_med"] == 500
    series = {}
    W.append_split(series, 100, sp)
    W.append_split(series, 100, sp)
    assert series["Ly_all_long"] == [[100, 1000]] and "Lo_all_eff_lev" not in series and series["So_all_long"] == [[100, 0]]


def test_best_lists():
    """92: najlepsi osobno w longach i shortach: ≥ 20 zagrań, z÷s ≥ 1,5 (brak strat przy zysku też), sort wg zysku."""
    def v(sides, L, S):
        return {"sides": sides, "age": 400, "av": 1e5, "L": L, "S": S}
    ch = {"a": v(["L"], {"n": 25, "win": 60, "pf": 2.0, "pnl": 500}, {"n": 0}),
          "b": v(["L"], {"n": 25, "win": 100, "pf": None, "pnl": 900}, {"n": 0}),
          "c": v(["L"], {"n": 12, "win": 90, "pf": 9.0, "pnl": 5000}, {"n": 0}),        # za mało zagrań
          "d": v(["L"], {"n": 40, "win": 50, "pf": 1.3, "pnl": 8000}, {"n": 0}),        # z÷s < 1,5
          "e": v(["S"], {"n": 0}, {"n": 30, "win": 70, "pf": 3.0, "pnl": 100})}
    wallets = [{"addr": "a", "av": 2e5, "pos": [{"c": "BTC", "L": True, "size": 1000, "lev": 5, "pnl": -50},
                                                 {"c": "ETH", "L": False, "size": 400, "lev": 3, "pnl": 20}]}]
    b = W.best_lists(ch, wallets)
    L, S = b["groups"]["L"], b["groups"]["S"]
    assert [x["addr"] for x in L] == ["b", "a"] and [x["addr"] for x in S] == ["e"]
    a = L[1]
    assert a["av"] == 2e5 and a["long"] == 1000 and a["short"] == 400 and a["upnl"] == -30 and a["npos"] == 2
    assert L[0]["upnl"] is None and L[0]["pos"] == [] and L[0]["av"] == 1e5


def test_positions_twice_writes_flows(tmp_path):
    clk, s = Clock(), Fake()
    sd, dd = str(tmp_path / "sito"), str(tmp_path / "hl")
    W.run_sito(sd, minutes=600, session=s, sleep=clk.sleep, clock=clk)
    W.run_positions(dd, sd, session=s, sleep=clk.sleep, clock=clk)
    g1 = W._read(os.path.join(dd, "hl_groups.json"), {})
    assert g1["comp"] == W.FLOW_SEED and "L_all_flowL" not in g1["series"] and g1["series"]["L_n"]
    assert W._read(os.path.join(dd, "hl_members.json"), {})["groups"]["L"]
    clk.t += 7200
    W.run_positions(dd, sd, session=s, sleep=clk.sleep, clock=clk)
    g2 = W._read(os.path.join(dd, "hl_groups.json"), {})
    assert g2["series"]["L_all_flowL"][-1][1] == 0 and len(g2["comp"]) == 1      # te same pozycje, ten sam skład
