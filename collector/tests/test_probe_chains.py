"""Offline: sonda DefiLlama — sieci (wolumen DEX, opłaty, stablecoiny, TVL; kandydaci do reguły „rośnie”)."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import probe  # noqa: E402

DAY = 86400
NOW = int(datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc).timestamp())
TODAY = NOW - NOW % DAY
START = TODAY - 800 * DAY


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, str(data)[:100]

    def json(self):
        return self._d


def dex_chart(base, boom_from=None, boom=1.0, today_part=0.1):
    pts = []
    for d in range(START, TODAY, DAY):
        pts.append([d, base * (boom if boom_from is not None and d >= boom_from else 1.0)])
    pts.append([TODAY, base * today_part])            # dzień w toku
    return pts


def stable_chart(level, growth_from=None, growth=1.0):
    return [{"date": str(d), "totalCirculatingUSD": {"peggedUSD": level * (growth if growth_from and d >= growth_from else 1.0),
                                                    "peggedEUR": 0}} for d in range(START, TODAY + DAY, DAY)]


class FakeLL:
    """Nasze 2 sieci + 3 inne: NewChain (DEX ×5 od tygodnia), Stable (stablecoiny ×2 od 20 dni), Tiny (za mała)."""
    def __init__(self):
        self.urls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        u = probe.requests.utils.unquote(url)
        if u.endswith("/overview/dexs"):
            return Resp({"allChains": ["Ethereum", "Solana", "NewChain", "Tiny"],
                         "breakdown24h": {"Ethereum": {"uni": 1e9}, "Solana": {"ray": 5e8}, "NewChain": {"x": 2e6},
                                          "Tiny": {"y": 1e3}}})
        if u.endswith("/overview/fees"):
            return Resp({"allChains": ["Ethereum", "Solana"]})
        if u.endswith("/stablecoinchains"):
            return Resp([{"name": "Ethereum", "totalCirculatingUSD": {"peggedUSD": 1.3e11}},
                         {"name": "Solana", "totalCirculatingUSD": {"peggedUSD": 1.4e10}},
                         {"name": "Stable", "totalCirculatingUSD": {"peggedUSD": 1e8}},
                         {"name": "Tiny", "totalCirculatingUSD": {"peggedUSD": 1e5}}])
        if u.endswith("/v2/chains"):
            return Resp([{"name": "Ethereum", "tvl": 6e10}, {"name": "Solana", "tvl": 9e9}])
        if "/overview/dexs/" in u:
            ch = u.rsplit("/", 1)[1]
            if ch == "NewChain":
                return Resp({"totalDataChart": dex_chart(1e6, TODAY - 7 * DAY, 5.0)})
            if ch == "Stable":
                return Resp({}, 404)
            return Resp({"totalDataChart": dex_chart(1e9 if ch == "Ethereum" else 5e8), "totalLastFullDay": 1e9})
        if "/overview/fees/" in u:
            return Resp({"totalDataChart": dex_chart(3e6)})
        if "/stablecoincharts/" in u:
            ch = u.rsplit("/", 1)[1]
            if ch == "Stable":
                return Resp(stable_chart(5e7, TODAY - 20 * DAY, 2.0))
            if ch == "NewChain":
                return Resp([])
            return Resp(stable_chart(1.3e11 if ch == "Ethereum" else 1.4e10))
        if "/historicalChainTvl/" in u:
            return Resp([{"date": d, "tvl": 1e9} for d in range(START, TODAY + DAY, DAY)])
        return Resp({}, 404)


def run():
    s = FakeLL()
    rows = probe.check_defillama(session=s, sleep=lambda *_: None, now=NOW, chains=("Ethereum", "Solana"))
    return s, rows, {r["item"]: r for r in rows}


def test_points_parsers():
    assert probe.ll_points({"totalDataChart": [[TODAY, 5], [TODAY + DAY, None]]}, "dex") == {TODAY: 5.0}
    assert probe.ll_points([{"date": str(TODAY), "totalCirculatingUSD": {"peggedUSD": 2, "peggedEUR": 1}}], "stable") == {TODAY: 3.0}
    assert probe.ll_points([{"date": TODAY * 1000 + 5, "tvl": 7}], "tvl") == {TODAY: 7.0}
    assert probe.ll_breakdown({"breakdown24h": {"A": {"p": 1, "q": {"r": 2}}, "B": 3}}) == {"A": 3.0, "B": 3.0}


def test_change_flow_and_stock():
    pts = {TODAY - k * DAY: (2.0 if k < 8 else 1.0) for k in range(1, 70)}
    c = probe.ll_change(pts, "dex", TODAY - DAY)
    assert c["s7"] == 14 and round(c["c7"]) == 100 and round(c["ratio4w"], 2) == 2.0
    st = {TODAY - k * DAY: 100.0 + (100 if k < 10 else 0) for k in range(1, 60)}
    c = probe.ll_change(st, "stable", TODAY - DAY)
    assert c["v"] == 200 and c["c7"] == 0 and round(c["c30"]) == 100


def test_our_chains_rows():
    _, rows, by = run()
    assert "wszystkie nasze sieci są" in by["lista sieci: dex"]["note"] and "breakdown24h: 4 sieci" in by["lista sieci: dex"]["note"]
    eth = by["Ethereum: dex"]
    assert eth["status"] == "ok" and eth["last"] == "2026-11-12" and "dzień w toku" in eth["note"]
    assert "11-11: $1.00 mld" in eth["note"] and "totalLastFullDay" in eth["note"] and "luki 0 dni" in eth["note"]
    assert "×0.10 mediany 7 dni) — dzień w toku" in eth["note"]
    assert by["Solana: stable"]["status"] == "ok" and "vs 7 dni wcześniej +0.0%" in by["Solana: stable"]["note"]
    share = by["udział w stablecoinach (teraz)"]["note"]
    assert share.startswith("Ethereum 90.2%") and "reszta 0.1%" in share


def test_candidates_and_rising():
    s, rows, by = run()
    cand = by["kandydaci do reguły „rośnie”"]
    assert cand["n"] == 2                            # NewChain (DEX 24 h ≥ $1M), Stable (stablecoiny ≥ $20M); Tiny za mała
    assert "teraz DEX rośnie: NewChain" in by and "×5.00" in by["teraz DEX rośnie: NewChain"]["note"]
    assert "teraz stablecoiny rosną: Stable" in by and "+100.0%" in by["teraz stablecoiny rosną: Stable"]["note"]
    assert "teraz DEX rośnie: Ethereum (nasza)" in by
    assert "Stable (dex)" in by["kandydaci: nieudane zapytania"]["note"]
    h = by["historia: DEX 7 dni ÷ średni tydzień z 4 poprzednich"]
    assert "p50 ×1.00" in h["note"] and h["n"] > 1000                 # 2 lata × 2 sieci + kilka dni NewChain
    assert by["koszt w zapytaniach"]["n"] == len(s.urls)
    assert "defillama" not in probe.CHECKS["github"] and "defillama" in probe.FUNCS


def test_list_error_is_reported():
    class Bad(FakeLL):
        def get(self, url, **kw):
            if url.endswith("/v2/chains"):
                return Resp("nope", 403)
            return super().get(url, **kw)
    rows = probe.check_defillama(session=Bad(), sleep=lambda *_: None, now=NOW, chains=("Ethereum",))
    by = {r["item"]: r for r in rows}
    assert by["lista sieci: tvl"]["status"] == "błąd" and "HTTP 403" in by["lista sieci: tvl"]["note"]
