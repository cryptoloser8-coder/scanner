"""Offline: sieci z DefiLlama (poprawka 48) — pobieranie, zmiany, reguły „rośnie”, epizody, korekty, pliki."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import chains  # noqa: E402

DAY = 86400
NOW = int(datetime(2026, 11, 12, 5, 30, tzinfo=timezone.utc).timestamp())
TODAY = NOW - NOW % DAY
END = TODAY - DAY
START = TODAY - 800 * DAY


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, str(data)[:100]

    def json(self):
        return self._d


def flow(base, boom_from=None, boom=1.0, start=START, skip=()):
    return {"totalDataChart": [[d, base * (boom if boom_from and d >= boom_from else 1.0)]
                               for d in range(start, TODAY + DAY, DAY) if d not in skip]}   # z punktem „dziś”


def stable(level, from_=None, mult=1.0, start=START):
    return [{"date": str(d), "totalCirculatingUSD": {"peggedUSD": level * (mult if from_ and d >= from_ else 1.0)}}
            for d in range(start, TODAY + DAY, DAY)]


class Fake:
    """Nasze: Ethereum, Solana. Inne: Boom (DEX ×5 od 7 dni), Cash (stablecoiny ×2,5 od 20 dni),
    Fresh (nowa: dane od 10 dni, $50M stablecoinów), Calm (bez zmian), Tiny (za mała)."""
    def __init__(self, fail=()):
        self.urls, self.fail = [], set(fail)

    def get(self, url, params=None, headers=None, timeout=None):
        u = chains.requests.utils.unquote(url)
        self.urls.append(u)
        name = u.rsplit("/", 1)[1]
        if any(f in u for f in self.fail):
            return Resp("err", 500 if "500" in str(self.fail) else 404)
        if u.endswith("/overview/dexs"):                               # cały rynek: płasko
            return Resp(flow(3e9))
        if u.endswith("/stablecoinchains"):
            return Resp([{"name": n, "totalCirculatingUSD": {"peggedUSD": v}} for n, v in
                         (("Ethereum", 1.3e11), ("Solana", 1.4e10), ("Boom", 3e7), ("Cash", 5e8), ("Fresh", 5e7),
                          ("Calm", 1e8), ("Tiny", 1e5))])
        if u.endswith("/v2/chains"):
            return Resp([{"name": "Ethereum", "tvl": 4e10}, {"name": "Boom", "tvl": 2.5e7}])
        if "/overview/dexs/" in u or "/overview/fees/" in u:
            if name == "Boom":
                return Resp(flow(2e6, TODAY - 7 * DAY, 5.0))
            if name == "Fresh":
                return Resp(flow(1e5, start=TODAY - 10 * DAY))
            if name in ("Cash", "Calm"):
                return Resp(flow(1e6))
            return Resp(flow(1e9 if name == "Ethereum" else 5e8, skip={END - 3 * DAY} if name == "Solana" else ()))
        if "/stablecoincharts/" in u:
            if name == "Cash":
                return Resp(stable(2e8, TODAY - 20 * DAY, 2.5))
            if name == "Fresh":
                return Resp(stable(5e7, start=TODAY - 10 * DAY))
            return Resp(stable({"Ethereum": 1.3e11, "Solana": 1.4e10}.get(name, 1e8)))
        if "/historicalChainTvl/" in u:
            return Resp([{"date": d, "tvl": 1e9} for d in range(START, TODAY + DAY, DAY)])
        return Resp({}, 404)


CFG = dict(chains.DEFAULTS, list=[{"name": "Ethereum", "coin": "ETH"}, {"name": "Solana", "coin": "SOL"}], sleep=0)


def run(tmp_path, fake=None, now=NOW):
    cl = chains.Client(session=fake or Fake(), sleep=lambda *_: None, pause=0)
    return chains.run(str(tmp_path), CFG, client=cl, now=now), cl


def test_points_drop_today_and_parse_kinds():
    assert chains.points({"totalDataChart": [[END, 5], [TODAY, 7]]}, "dex", TODAY) == [[END, 5.0]]
    st = [{"date": str(END), "totalCirculatingUSD": {"peggedUSD": 2, "peggedEUR": 1}}, {"date": str(TODAY)}]
    assert chains.points(st, "stable", TODAY) == [[END, 3.0]]
    assert chains.points([{"date": END * 1000, "tvl": 7}], "tvl", TODAY) == [[END, 7.0]]
    assert chains.points("bad", "dex", TODAY) == [] and chains.slug("Hyperliquid L1") == "hyperliquid"


def test_change_flow_gaps_and_stock():
    pts = [[END - k * DAY, 2.0 if k < 7 else 1.0] for k in range(0, 70) if k != 2]
    c = chains.change(pts, "dex", END)
    assert c["s7"] == 12 and c["gaps7"] == 1 and c["ratio4w"] == round(12 / 7, 3)
    st = [[END - k * DAY, 200.0 if k < 10 else 100.0] for k in range(0, 400)]
    c = chains.change(st, "stable", END)
    assert c["v"] == 200 and c["c7"] == 0 and c["c30"] == 100 and c["c365"] == 100


def test_run_files_ours_and_share(tmp_path):
    s, cl = run(tmp_path)
    files = sorted(os.listdir(tmp_path))
    assert files == ["chains.json", "chains_1d.json", "chains_other.json", "state.json"]
    ser = json.load(open(tmp_path / "chains_1d.json"))["series"]
    assert set(ser) == {f"ch_{c}_{m}" for c in ("ethereum", "solana") for m in chains.METRICS} | {"ch_all_dex", "ch_all_stable"}
    assert s["market"]["dex"]["ratio4w"] == 1.0
    assert ser["ch_ethereum_dex"][-1][0] == END                       # bez punktu z bieżącej daty
    eth = s["chains"][0]
    assert eth["slug"] == "ethereum" and eth["m"]["dex"]["v"] == 1e9 and eth["m"]["dex"]["c7"] == 0
    assert eth["m"]["stable"]["first"] == chains.iso(START) and eth["m"]["dex"]["rank2y"] == 100.0
    assert s["chains"][1]["m"]["dex"]["gaps7"] == 1                   # luka u Solany
    assert s["share"]["rows"][0][0] == "Ethereum" and s["share"]["rest"] > 0 and s["day"] == chains.iso(END)


def test_rising_rules_and_episode_from_history(tmp_path):
    s, _ = run(tmp_path)
    by = {r["name"]: r for r in s["rising"]}
    assert set(by) == {"Boom", "Cash", "Fresh"}                       # Calm bez zmian, Tiny za mała
    assert by["Boom"]["kinds"] == ["dex"] and by["Boom"]["dex_ratio"] == 5.0 and by["Boom"]["dex_rel"] == 5.0
    assert by["Cash"]["kinds"] == ["stable"] and by["Cash"]["stable30"] == 150.0
    assert by["Fresh"]["kinds"] == ["new"] and by["Fresh"]["age_days"] == 10
    # epizod liczony z historii, nie od pierwszego przebiegu: Boom ≥ ×3 od 4 dni (≥ 4 dni „boomu” w oknie 7 dni),
    # Cash od 20 dni (stablecoiny ×2,5), Fresh od pierwszego dnia danych
    assert {n: r["day_n"] for n, r in by.items()} == {"Boom": 4, "Cash": 20, "Fresh": 10}
    assert by["Boom"]["since"] == chains.iso(END - 3 * DAY) and s["new_today"] == []
    assert s["candidates"] == 4 and s["rising"][0]["name"] == "Boom"   # siła: ×5 ÷ ×3 = 1,67 > +150% ÷ +100% = 1,5
    other = json.load(open(tmp_path / "chains_other.json"))["other"]
    assert "Boom" in other and len(other["Boom"]["dex"]) <= CFG["other_days"] + 1


def test_dex_rule_is_relative_to_market():
    dex = [[END - k * DAY, 2e6 * (5 if k < 7 else 1)] for k in range(60, -1, -1)]
    assert chains.rising_check("X", dex, [], END, CFG)["dex_rel"] == 5.0          # bez rynku: ×5
    market = {END - k * DAY: 1e9 * (2 if k < 7 else 1) for k in range(60, -1, -1)}  # cały rynek ×2
    assert chains.rising_check("X", dex, [], END, CFG, market) is None             # ×5 ÷ ×2 = 2,5 < 3


def test_episode_start_gap_and_new():
    cfg = dict(CFG)
    base = [[END - k * DAY, 1e8] for k in range(200, -1, -1)]
    # stablecoiny ×3 od 5 dni → epizod od 5 dni; dziś pierwszy dzień → new
    st = [[t, v * (3 if t >= END - 4 * DAY else 1)] for t, v in base]
    assert chains.episode_start("X", [], st, END, cfg) == END - 4 * DAY
    st1 = [[t, v * (3 if t >= END else 1)] for t, v in base]
    r = chains.episodes([{"name": "X"}], {"X": ([], st1)}, END, cfg)[0]
    assert r["new"] and r["day_n"] == 1


def test_second_day_revisions_and_day_n(tmp_path):
    run(tmp_path)
    s, _ = run(tmp_path, now=NOW + DAY)
    rev = s["revisions"]
    assert rev and all(r["day"] == chains.iso(END) for r in rev)
    assert {r["sid"] for r in rev} >= {"ch_ethereum_dex", "ch_solana_stable"} and all(r["diff_pct"] == 0 for r in rev)
    days = {r["name"]: r["day_n"] for r in s["rising"]}
    assert days == {"Boom": 5, "Cash": 21, "Fresh": 11} and s["new_today"] == []


def test_failure_keeps_old_history(tmp_path):
    run(tmp_path)
    s, _ = run(tmp_path, fake=Fake(fail=("/overview/fees/Solana",)), now=NOW + DAY)
    ser = json.load(open(tmp_path / "chains_1d.json"))["series"]
    assert ser["ch_solana_fees"][-1][0] == END                        # stara historia, nie pusta
    assert any(e.startswith("Solana fees") for e in s["errors"])


def test_total_failure_raises(tmp_path):
    class Dead:
        def get(self, *a, **k):
            return Resp("x", 403)
    try:
        run(tmp_path, fake=Dead())
        raise AssertionError("powinien być błąd")
    except RuntimeError as e:
        assert "żadna seria" in str(e)
    assert not os.path.exists(tmp_path / "chains.json")
