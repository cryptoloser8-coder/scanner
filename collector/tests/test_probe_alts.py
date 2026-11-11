"""Offline: sonda nowych źródeł do sekcji Alty (CoinGecko — koszyki kapitalizacji, DexScreener — narracje)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import probe  # noqa: E402


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, str(data)[:100]

    def json(self):
        return self._d


def coin(i, mcap, vol=1e5):
    return {"id": f"c{i}", "symbol": f"c{i}", "market_cap": mcap, "total_volume": vol,
            "price_change_percentage_24h_in_currency": 1.0 + i % 3, "price_change_percentage_7d_in_currency": -2.0,
            "price_change_percentage_30d_in_currency": None if i % 2 else 5.0}


class FakeCG:
    def __init__(self):
        self.urls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append((url, dict(params or {})))
        if url.endswith("/coins/markets") and params.get("category"):
            return Resp([{"id": "c3"}] if params["category"] == "stablecoins" else [])
        if url.endswith("/coins/markets"):
            if params["page"] == 1:        # BTC, ETH + 4 duże + 3 średnie
                rows = [dict(coin(0, 1.5e12), id="bitcoin"), dict(coin(1, 3e11), id="ethereum")]
                rows += [coin(i, 5e9) for i in range(2, 6)] + [coin(i, 3e8) for i in range(6, 9)]
                return Resp(rows)
            if params["page"] == 2:        # małe i ogon poniżej $1M → koniec stronicowania
                return Resp([coin(i, 5e7, 2e6) for i in range(9, 14)] + [coin(i, 4e6, 2e4) for i in range(14, 20)]
                            + [coin(20, 5e5)])
            return Resp([])
        if "/market_chart" in url:
            if params["days"] == "max":
                return Resp({"error": "exceeds the allowed time range"}, 401)
            return Resp({"prices": [[1_760_000_000_000 + i * 86_400_000, 1.0] for i in range(365)],
                         "market_caps": [[1_760_000_000_000, 1e7]]})
        return Resp({}, 404)


def test_coingecko_buckets_and_history():
    s = FakeCG()
    rows = probe.check_coingecko(session=s, sleep=lambda *_: None)
    by = {r["item"]: r for r in rows}
    assert by["lista coinów"]["n"] == 21 and "2 stron" in by["lista coinów"]["note"] and "pozycji 21" in by["lista coinów"]["note"]
    assert "24h/7D/30D w odpowiedzi: tak" in by["lista coinów"]["note"]
    assert by["koszyk > $1B"]["n"] == 3                         # 4 duże − stablecoin c3; BTC i ETH osobno
    assert by["koszyk $100M – $1B"]["n"] == 3 and by["koszyk $10M – $100M"]["n"] == 5 and by["koszyk $1M – $10M"]["n"] == 6
    assert "≥ $50 tys.: 0" in by["koszyk $1M – $10M"]["note"] and "≥ $1.0 mln: 5" in by["koszyk $10M – $100M"]["note"]
    hist = [r for r in rows if r["item"].startswith("historia ")]
    assert any(r["status"] == "błąd" and "days=max" in r["item"] for r in hist)       # darmowy klucz: bez pełnej historii
    ok = [r for r in hist if r["status"] == "ok"]
    assert ok and ok[0]["n"] == 365 and "kapitalizacja w historii: tak" in ok[0]["note"]
    cost = by["koszt w zapytaniach"]
    assert "raz na dobę = 2 zapytań/dzień" in cost["note"] and cost["n"] == len(s.urls)


def test_dexscreener_metas():
    class S:
        def get(self, url, **kw):
            if url.endswith("/metas/trending/v1"):
                return Resp([{"name": "AI", "slug": "ai", "marketCap": 1.8e9, "liquidity": 9e7, "tokenCount": 46,
                              "volume": {"h24": 3e8}, "marketCapChange": {"h24": 12.6}}])
            return Resp({"pairs": [{"chainId": "solana", "priceUsd": "1", "liquidity": {"usd": 1}}]})
    rows = probe.check_dexscreener(session=S())
    assert rows[0]["n"] == 1 and "marketCapChange" in rows[0]["note"]
    assert rows[1]["item"] == "narracja: AI" and rows[1]["n"] == 46 and "12.6" in rows[1]["note"]
    assert rows[2]["item"] == "skład narracji ai" and rows[2]["n"] == 1
    assert "coingecko" not in probe.CHECKS["github"] and {"coingecko", "dexscreener"} <= set(probe.FUNCS)
