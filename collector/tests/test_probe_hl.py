import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import probe  # noqa: E402
import probe_hl  # noqa: E402

NOW = 1763424000  # 2025-11-18


class Resp:
    def __init__(self, obj, code=200, headers=None):
        self._o, self.status_code, self.headers = obj, code, headers or {}
        self.text = str(obj)
        self.content = self.text.encode()

    def json(self):
        return self._o


def board():
    rows = []
    for i in range(40):
        good = i < 20
        rows.append({"ethAddress": f"0x{i:040x}", "accountValue": str(2e5 if good else 5e4),
                     "windowPerformances": [["day", {"pnl": "1", "roi": "0", "vlm": "1"}],
                                            ["month", {"pnl": str(1000 - i), "roi": "0", "vlm": "1"}],
                                            ["allTime", {"pnl": str(1e6 - i if good else -1e4), "roi": "0", "vlm": "1"}]]})
    return {"leaderboardRows": rows}


def state(addr):
    good = int(addr, 16) < 20
    pos = [{"position": {"coin": "BTC", "szi": "1" if good else "-1", "positionValue": "100000",
                         "leverage": {"type": "cross", "value": 5}}},
           {"position": {"coin": "PEPE", "szi": "-5" if good else "5", "positionValue": "300000",
                         "leverage": {"type": "cross", "value": 10}}}]
    return {"marginSummary": {"accountValue": "200000" if good else "50000"}, "assetPositions": pos}


class FakeHL:
    def __init__(self):
        self.n429 = 1

    def get(self, url, headers=None, timeout=None):
        assert url == probe_hl.HL_BOARD
        return Resp(board())

    def post(self, url, json=None, headers=None, timeout=None):
        t = json["type"]
        if t == "metaAndAssetCtxs":
            return Resp([{"universe": [{"name": "BTC"}, {"name": "PEPE"}]},
                         [{"markPx": "100000", "openInterest": "10"}, {"markPx": "0.00001", "openInterest": "1e11"}]])
        if t == "clearinghouseState":
            if self.n429:
                self.n429 -= 1
                return Resp({}, 429)
            return Resp(state(json["user"]))
        if t == "portfolio":
            return Resp([["day", {}], ["allTime", {"pnlHistory": [[1700000000000, "0"], [1700086400000, "1"],
                                                                  [1700172800000, "2"]]}]])
        if t == "userFillsByTime":
            return Resp([{"time": 1700000000000}, {"time": 1700100000000}])
        return Resp({}, 400)


def test_hyperliquid_groups_and_costs():
    extra = {}
    rows = probe_hl.check_hyperliquid(session=FakeHL(), sleep=lambda *_: None, extra=extra, group_n=10, now=NOW)
    by = {r["item"]: r for r in rows}
    assert by["ranking (leaderboard)"]["n"] == 40
    g = extra["hyperliquid"]["groups"]
    top, rest = g["najlepsi od zawsze"], g["tracący (losowo)"]
    assert top["n"] == 10 and rest["n"] == 10
    assert round(top["long_pct"]) == 25 and round(rest["long_pct"]) == 75     # BTC long 100k vs PEPE short 300k
    assert round(top["eff_lev"], 1) == 2.0 and round(rest["eff_lev"], 1) == 8.0
    assert round(top["alt_share"]) == 75 and top["alt_long_pct"] == 0
    assert "odpowiedzi 429: 1" in by["pozycje portfeli (clearinghouseState)"]["note"]
    assert any(k.startswith("portfolio") and by[k]["n"] == 3 for k in by)
    assert "OI razem" in by["rynki perp (metaAndAssetCtxs)"]["note"]


class FakeHT:
    def __init__(self, key):
        self.key = key
        self.paths = []

    def get(self, url, params=None, headers=None, timeout=None):
        assert headers["Authorization"] == "Bearer " + self.key
        self.paths.append(url)
        h = {"X-RateLimit-Remaining": "77"}
        if url.endswith("/external-json"):
            return Resp({"paths": {"/segments": {"get": {"summary": "Segments", "parameters": []}}}}, headers=h)
        if url.endswith("/segments"):
            return Resp([{"id": 9, "name": "Smart Money"}], headers=h)
        if "/position-metrics/" in url:
            base = 1735689600 if params["start"].startswith("2024") else NOW - 2 * 86400
            return Resp({"data": [{"timestamp": base + i * 3600, "longNotional": 1} for i in range(5)],
                         "nextCursor": "x"}, headers=h)
        if "/fills" in url:
            return Resp({"error": "Forbidden " + self.key}, 403)
        return Resp({"data": [{"createdAt": "2025-04-01T00:00:00.000Z", "a": 1}]}, headers=h)


def test_hypertracker_depth_budget_and_key_hidden(monkeypatch):
    monkeypatch.setenv("HYPERTRACKER_API_KEY", "SEKRET123")
    s = FakeHT("SEKRET123")
    extra = {}
    rows = probe_hl.check_hypertracker(session=s, sleep=lambda *_: None, extra=extra, now=NOW)
    by = {r["item"]: r for r in rows}
    d = by["metryki BTC — Smart Money (9)"]
    assert d["first"] == "2025-01-01" and "krok ~1.00 h" in d["note"] and "kursor" in d["note"]
    assert "1 Smart Money" not in by["grupy (segments)"]["note"] and "9 Smart Money" in by["grupy (segments)"]["note"]
    assert "GET /segments" in extra["hypertracker"]["spec"]
    # po 403 dalsze zapytania są pomijane, a klucz nie trafia do wyniku
    assert "SEKRET123" not in str(rows) and "SEKRET123" not in str(extra)
    assert by["koszt"]["status"] == "uwaga" and "X-RateLimit-Remaining=77" in by["koszt"]["note"]
    assert by["koszt"]["n"] <= probe_hl.HT_BUDGET and by["koszt"]["n"] == len(s.paths)


def test_no_key(monkeypatch):
    monkeypatch.delenv("HYPERTRACKER_API_KEY", raising=False)
    rows = probe_hl.check_hypertracker(session=object(), extra={})
    assert rows[0]["status"] == "brak"


def test_registered_only_on_demand():
    assert "hyperliquid" in probe.FUNCS and "hypertracker" in probe.FUNCS
    assert "hyperliquid" not in probe.CHECKS["github"]
    assert probe_hl.to_ts("2025-04-01T10:00:00.123Z") == 1743501600 and probe_hl.to_ts(1700000000000) == 1700000000


class FakeHTSpec401(FakeHT):
    def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("/external-json"):
            self.paths.append(url)
            return Resp({"message": "Unauthorized"}, 401)
        return super().get(url, params, headers, timeout)


def test_spec_401_does_not_stop_and_key_cleaned(monkeypatch):
    monkeypatch.setenv("HYPERTRACKER_API_KEY", ' "Bearer SEKRET123"\n')
    s = FakeHTSpec401("SEKRET123")
    rows = probe_hl.check_hypertracker(session=s, sleep=lambda *_: None, extra={}, now=NOW)
    by = {r["item"]: r for r in rows}
    assert by["specyfikacja OpenAPI"]["status"] == "błąd"
    assert by["grupy (segments)"]["status"] == "ok" and by["metryki BTC — Smart Money (9)"]["status"] == "ok"


# ── sonda 86 ──
DAY = 86400


def F(t, coin, side, sz, start, pnl=0.0, fee=0.0, tid=0):
    return {"time": t * 1000, "coin": coin, "side": side, "sz": str(sz), "startPosition": str(start),
            "closedPnl": str(pnl), "fee": str(fee), "tid": tid}


def test_trips_long_short_flip_and_partial_window():
    T = 1760000000
    fills = [
        F(T, "BTC", "A", 1, 2, pnl=5),               # okno zaczyna się w środku longa (2 → 1)
        F(T + 10, "BTC", "A", 1, 1, pnl=5),          # long zamknięty: +10
        F(T + 20, "PEPE", "A", 100, 0),              # short 100
        F(T + 30, "PEPE", "B", 150, -100, pnl=-7, fee=1),   # odwrócenie: short −8 zamknięty, long 50 otwarty
        F(T + 40, "PEPE", "A", 50, 50, pnl=3),       # long +3
        F(T + 50, "xyz:IBM", "B", 1, 0),             # pomijane
        F(T + 60, "SOL", "B", 1, 0),                 # otwarte — nie liczone
    ]
    tr = probe_hl.trips(fills)
    assert [(t["coin"], t["side"], round(t["pnl"], 6)) for t in tr] == [("BTC", "long", 10.0), ("PEPE", "short", -8.0),
                                                                          ("PEPE", "long", 3.0)]
    st = probe_hl.side_stats([t for t in tr if t["side"] == "long"])
    assert st["n"] == 2 and st["win_pct"] == 100 and st["pf"] == float("inf")


def test_months_positive():
    base = 1735689600  # 2025-01-01
    hist = [[(base + d * DAY) * 1000, str(v)] for d, v in ((0, 0), (40, 10), (70, 5), (100, 20), (130, 30))]
    pct, n = probe_hl.months_positive(hist)
    assert n == 4 and pct == 75.0


class Clock:
    def __init__(self):
        self.t = 1763424000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeSito(FakeHL):
    def __init__(self, clock):
        super().__init__()
        self.n429 = 0
        self.clock = clock

    def post(self, url, json=None, headers=None, timeout=None):
        t = json["type"]
        if t == "metaAndAssetCtxs":
            return Resp([{"universe": [{"name": "BTC"}, {"name": "PEPE"}, {"name": "xyz:IBM"}, {"name": "OLD", "isDelisted": True}]},
                         [{"markPx": "100000", "openInterest": "1000"}, {"markPx": "0.00001", "openInterest": "2e12"},
                          {"markPx": "300", "openInterest": "1e6"}, {"markPx": "1", "openInterest": "1e9"}]])
        if t == "portfolio":
            return Resp([["perpAllTime", {"pnlHistory": [[(NOW - 400 * DAY) * 1000, "0"], [(NOW - 10 * DAY) * 1000, "5"]]}]])
        if t == "userFills":
            T = NOW - 20 * DAY
            out = []
            for i in range(40):
                out.append(F(T + i * 100, "PEPE", "B", 1, 0, tid=2 * i))
                out.append(F(T + i * 100 + 50, "PEPE", "A", 1, 1, pnl=(2 if i % 4 else -1), tid=2 * i + 1))
            return Resp(out)
        return super().post(url, json, headers, timeout)


def test_hlsito_end_to_end_and_weights():
    clk = Clock()
    extra = {}
    rows = probe_hl.check_hlsito(session=FakeSito(clk), sleep=clk.sleep, clock=clk, extra=extra, now=NOW,
                                 n_top=5, n_random=5, n_deep=2)
    by = {r["item"]: r for r in rows}
    mk = by["rynki krypto (główna giełda HL)"]
    assert mk["n"] == 2 and "koszyk altów (reszta) $20.0M" in mk["note"]
    assert by["pominięte rynki z „:”"]["n"] == 1
    assert by["profile portfeli (portfolio + userFills)"]["n"] == 10
    w = extra["hlsito"]["wallets"][0]
    assert w["long"]["n"] == 40 and w["long"]["win_pct"] == 75.0 and round(w["age_days"]) == 400
    assert "p50 75.0" in by["skuteczność — longi, ≥ 30 zagrań (% na plus)"]["note"]
    assert any(k.startswith("przykładowe sito: wiek ≥ 365") and by[k]["n"] == 10 for k in by)
    assert "zostaje 10" in by["odrzucone przed rozkładami"]["note"]
    # 21 zapytań po 20 wag + 10 × 80 transakcji / 20 = 460 wag
    assert "wag 460" in by["koszt"]["note"]


def test_weighted_client_waits_for_limit():
    clk = Clock()
    hl = probe_hl.WeightedHL(FakeSito(clk), clk.sleep, clk, per_min=50)
    t0 = clk.t
    for _ in range(3):
        hl.call({"type": "portfolio", "user": "0x1"}, 20)
    assert clk.t - t0 >= 59 and hl.weight == 60


class FakeHTPages(FakeHT):
    def get(self, url, params=None, headers=None, timeout=None):
        if "/coin/BTC/segment/9" in url:
            self.paths.append(url)
            page = 0 if "nextCursor" not in params else int(params["nextCursor"])
            base = NOW - (page + 1) * 20 * DAY
            nxt = str(page + 1) if page < 2 else None
            return Resp({"metrics": [{"createdAt": base + i * 1728} for i in range(1000)], "nextCursor": nxt})
        return super().get(url, params, headers, timeout)


def test_htdepth_pages_to_start(monkeypatch):
    monkeypatch.setenv("HYPERTRACKER_API_KEY", "K")
    s = FakeHTPages("K")
    rows = probe_hl.check_htdepth(session=s, sleep=lambda *_: None, extra={}, now=NOW)
    by = {r["item"]: r for r in rows}
    h = by["historia BTC — Smart Money (9)"]
    assert h["n"] == 3000 and "stron 3" in h["note"] and "pełna historia" in h["note"]
    assert by["koszt"]["n"] == len(s.paths)


def test_trips_skip_spot_and_idle_months():
    T = 1760000000
    fills = [dict(F(T, "@107", "B", 5, 0), dir="Buy"), dict(F(T + 1, "PURR/USDC", "A", 5, 5), dir="Sell"),
             dict(F(T + 2, "ETH", "B", 1, 0), dir="Open Long"), dict(F(T + 3, "ETH", "A", 1, 1, pnl=4), dir="Close Long")]
    tr = probe_hl.trips(fills)
    assert [(t["coin"], t["pnl"]) for t in tr] == [("ETH", 4.0)]
    base = 1735689600
    hist = [[(base + d * DAY) * 1000, str(v)] for d, v in ((0, 0), (40, 10), (70, 10), (100, 10), (130, 30))]
    pct, n = probe_hl.months_positive(hist)
    assert n == 2 and pct == 100.0             # miesiące bez gry pominięte
