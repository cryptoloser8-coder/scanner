"""Offline: alty według kapitalizacji (poprawka 46) — zapis z CoinGecko, koszyki, indeksy, bloki raportów."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import alts as A  # noqa: E402
import report  # noqa: E402
import today  # noqa: E402
from store import Store  # noqa: E402

DAY, HOUR = 86400, 3600
D0 = 1_794_268_800                      # 10.11.2026 00:00 UTC


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, ""

    def json(self):
        return self._d


def coin(cid, mcap, px, ch24=1.0, vol=1e6, ch7=-5.0, ch30=-20.0):
    return {"id": cid, "symbol": cid[:4], "name": cid.title(), "market_cap": mcap, "current_price": px, "total_volume": vol,
            "price_change_percentage_24h_in_currency": ch24, "price_change_percentage_7d_in_currency": ch7,
            "price_change_percentage_30d_in_currency": ch30}


def market(mult=None, extra=()):
    """600 coinów: BTC, ETH, po kilka w każdym koszyku + ogon; mult = {id: mnożnik ceny} względem zapisu bazowego."""
    mult = mult or {}
    rows = [coin("bitcoin", 1.5e12, 75000.0, 0.5), coin("ethereum", 2.5e11, 2000.0, -0.5)]
    rows += [coin(f"big{i}", 5e9, 10.0, 2.0 + i) for i in range(4)]                   # > $1B: +2, +3, +4, +5
    rows += [coin(f"mid{i}", 3e8, 5.0, -1.0 * i) for i in range(5)]                    # $100M–1B: 0 … −4
    rows += [coin(f"sml{i}", 5e7, 1.0, 3.0) for i in range(6)]                         # $10–100M
    rows += [coin(f"mic{i}", 4e6, 0.1, -2.0, vol=2e5) for i in range(7)]               # $1–10M
    rows += [coin("usdx", 3e9, 1.0002, 0.01, ch7=0.02, ch30=-0.1),                     # stablecoin spoza kategorii
             coin("wrapped", 2e9, 75000.0, 0.5), coin("dead", 5e6, 0.2, 50.0, vol=100.0)]
    rows += [coin(f"tail{i}", 2e6, 0.01, 0.0, vol=10.0) for i in range(573)]           # bez obrotu → poza koszykami
    rows += list(extra)
    for r in rows:
        r["current_price"] *= mult.get(r["id"], 1.0)
    return rows


class FakeCG:
    def __init__(self, coins, metas=None, fail=False):
        self.coins, self.metas, self.fail, self.calls = coins, metas, fail, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if "dexscreener" in url:
            return Resp(self.metas if self.metas is not None else [], 200 if self.metas is not None else 500)
        if self.fail:
            return Resp({"error": "x"}, 401)
        if params.get("category"):
            return Resp([{"id": "wrapped"}] if params["category"] == "wrapped-tokens" else [])
        p = params["page"]
        return Resp(self.coins[(p - 1) * 250:p * 250])


CFG = {"alts": {"enabled": True, "min_volume": 50_000, "movers": 3}}
METAS = [{"name": "AI", "slug": "ai", "marketCap": 1.4e9, "liquidity": 4.7e7, "tokenCount": 59, "volume": 1.2e7,
          "marketCapChange": {"h24": -3.67}},
         {"name": "Stonks", "slug": "s", "marketCap": 4.1e8, "liquidity": 1.7e7, "tokenCount": 12, "volume": {"h24": 5e6},
          "marketCapChange": {"h24": 1.79}}]
NOSLEEP = lambda *_: None  # noqa: E731


def test_due_schedule():
    c = A.settings(CFG)
    assert A.due(c, {}, D0 + 15 * 60) == "close" and A.due(c, {}, D0 + 9 * HOUR) == "now"      # pierwszy zapis w ogóle
    st = {"last_t": D0 - 3 * HOUR}                                                               # wczoraj 21:00 UTC
    assert A.due(c, st, D0 + 75 * 60) == "close"                                                 # pierwszy skan po 00:00 UTC
    assert A.due(c, {"last_t": D0 + 75 * 60}, D0 + 5 * HOUR) is None                             # już zrobiony
    assert A.due(c, {"last_t": D0 + 75 * 60}, D0 + 21 * HOUR + 300) == "now"                     # skan wieczorny
    assert A.due(c, {"last_t": D0 + 21 * HOUR + 300}, D0 + 23 * HOUR) is None
    assert A.due(c, st, D0 + 7 * HOUR) is None                                                   # za późno na zamknięcie dnia
    assert A.due(c, st, D0 + 20 * HOUR + 60) == "now"


def test_bucket_helpers():
    assert [A.bucket_of(x) for x in (2e9, 1e9, 5e8, 5e7, 5e6, 9e5, None)] == ["1b", "1b", "100m", "10m", "1m", None, None]
    assert A.median([3, 1, 2]) == 2 and A.median([1, 2, 3, 4]) == 2.5 and A.median([]) is None
    assert A.is_usd_peg(coin("x", 1e9, 0.9995, 0.1, ch7=-0.2, ch30=0.4)) and not A.is_usd_peg(coin("x", 1e9, 1.0, 3.0))
    assert not A.enabled({}) and A.enabled(CFG)
    assert set(A.catalog()) == {"alt_idx_1b", "alt_idx_100m", "alt_idx_10m", "alt_idx_1m"} and A.catalog()["alt_idx_1m"]["group"] == "idx"


def test_first_close_then_next_day_and_evening(tmp_path):
    d = str(tmp_path)
    store = Store(d)
    s = FakeCG(market(), METAS)
    info = A.collect(store, CFG, D0 + 20 * 60, session=s, sleep=NOSLEEP)
    assert info["snapshot"] == "close" and info["coins"] == 600 and info["buckets"] == {"1b": 4, "100m": 5, "10m": 6, "1m": 7}
    cl = store.extra["alts.json"]["close"]
    assert cl["basis"] == "cg24h" and cl["day"] == D0 - DAY and cl["btc"]["chg"] == 0.5        # pierwszy dzień: 24 h z CoinGecko
    big = cl["rows"][0]
    assert big["name"] == "Alty > $1B" and big["n"] == 4 and big["chg"] == 3.5 and big["up"] == 100.0 and big["beat_btc"] == 100.0
    assert big["top"][0] == ["BIG3", "Big3", 5.0] and big["bottom"][0] == ["BIG0", "Big0", 2.0]
    mid = cl["rows"][1]
    assert mid["chg"] == -2.0 and mid["up"] == 0.0 and mid["beat_btc"] == 0.0 and mid["chg7"] == -5.0
    assert store.series["1d"]["alt_idx_1b"] == {D0 - DAY: 100.0}                                # indeks startuje od 100
    assert store.extra["alts.json"]["metas"]["rows"][0] == {"name": "Stonks", "tokens": 12, "mcap": 4.1e8, "liq": 1.7e7,
                                                            "vol": 5e6, "chg24": 1.79}
    pages = [p for u, p in s.calls if "coingecko" in u and not p.get("category")]
    assert len(pages) == 3                                                                      # 600 coinów = 3 strony
    store.save(D0 + 20 * 60, {})

    # ten sam dzień, skan wieczorny: zmiana od zamknięcia; koszyk według kapitalizacji z zamknięcia
    store = Store(d)
    up = {f"mic{i}": 1.10 for i in range(7)}                                                    # małe +10%
    up.update({"bitcoin": 1.02, "big0": 0.95, "big1": 0.97, "big2": 1.01, "big3": 1.03})
    ev = market(up)
    next(c for c in ev if c["id"] == "mic0")["market_cap"] = 2e7                                # urósł ponad $10M — nadal liczony w $1–10M
    assert A.collect(store, CFG, D0 + 5 * HOUR, session=FakeCG(ev, METAS), sleep=NOSLEEP) == {"snapshot": None}
    info = A.collect(store, CFG, D0 + 21 * HOUR + 300, session=FakeCG(ev, METAS), sleep=NOSLEEP)
    assert info["snapshot"] == "now"
    nw = store.extra["alts.json"]["now"]
    assert nw["basis"] == "own" and nw["since"] == D0 + 20 * 60 and nw["btc"]["chg"] == 2.0
    by = {r["id"]: r for r in nw["rows"]}
    assert by["1m"]["n"] == 7 and by["1m"]["chg"] == 10.0 and by["1m"]["beat_btc"] == 100.0
    assert by["1b"]["chg"] == -1.0 and by["1b"]["up"] == 50.0 and by["1b"]["beat_btc"] == 25.0   # mediana z −5, −3, +1, +3
    assert store.series["1d"]["alt_idx_1m"][D0] == 110.0 and store.series["1d"]["alt_idx_1m"][D0 - DAY] == 100.0
    assert "close" in store.extra["alts.json"]                                                  # tabela poranna zostaje
    store.save(D0 + 21 * HOUR + 300, {})

    # następne zamknięcie dnia (~25 h po poprzednim): doba z własnych zapisów, indeks × (1 + mediana)
    store = Store(d)
    nxt = dict(up)
    nxt.update({f"mic{i}": 1.20 for i in range(7)})
    info = A.collect(store, CFG, D0 + DAY + 75 * 60, session=FakeCG(market(nxt), METAS), sleep=NOSLEEP)
    assert info["snapshot"] == "close"
    alt = store.extra["alts.json"]
    assert "now" not in alt and alt["close"]["basis"] == "own" and alt["close"]["day"] == D0 and alt["close"]["hours"] == 24.9
    by = {r["id"]: r for r in alt["close"]["rows"]}
    assert by["1m"]["chg"] == 20.0 and by["10m"]["chg"] == 0.0
    assert store.series["1d"]["alt_idx_1m"] == {D0 - DAY: 100.0, D0: 120.0}                     # punkt dnia w toku nadpisany
    assert store.series["1d"]["alt_idx_10m"][D0] == 100.0
    assert store.state["alts"]["last_t"] == D0 + DAY + 75 * 60 and len(store.state["alts"]["close"]["px"]) == 600


def test_skip_lists_volume_and_errors(tmp_path):
    store = Store(str(tmp_path))
    A.collect(store, CFG, D0 + 600, session=FakeCG(market(), None), sleep=NOSLEEP)
    assert store.state["alts"]["skip"]["ids"] == ["wrapped"]
    big = store.extra["alts.json"]["close"]["rows"][0]
    assert big["n"] == 4                                             # bez „wrapped” (kategoria) i „usdx” (cena ≈ $1)
    assert store.extra["alts.json"]["close"]["rows"][3]["n"] == 7    # „dead” i ogon bez obrotu odpadają
    assert "metas" not in store.extra["alts.json"]                   # DexScreener nie działa → bez narracji, koszyki są
    store2 = Store(str(tmp_path / "x"))
    try:
        A.collect(store2, CFG, D0 + 600, session=FakeCG(market(), None, fail=True), sleep=NOSLEEP)
        raise AssertionError("powinien być błąd")
    except RuntimeError as e:
        assert "CoinGecko" in str(e)
    assert not store2.state["alts"].get("last_t")                    # nieudany zapis → ponowienie przy następnym skanie


def _data_dir(tmp_path, now, alts):
    d = str(tmp_path / "data")
    os.makedirs(d)
    for fn in ("1h.json", "1d.json"):
        with open(os.path.join(d, fn), "w") as f:
            json.dump({"updated": now, "series": {}}, f)
    with open(os.path.join(d, "alts.json"), "w") as f:
        json.dump(alts, f)
    return d


def _snap(tmp_path):
    store = Store(str(tmp_path / "s"))
    A.collect(store, CFG, D0 + DAY + 20 * 60, session=FakeCG(market(), METAS), sleep=NOSLEEP)
    return store.extra["alts.json"]


def test_morning_report_blocks(tmp_path):
    alts = _snap(tmp_path)                                           # zamknięcie doby 10.11, zapis 11.11 00:20 UTC
    now = D0 + DAY + 6 * HOUR
    d = report.Data(_data_dir(tmp_path, now, alts))
    blocks = report.caps_blocks(d, now)
    (tab,) = blocks                                                  # bez listy najmocniejszych / najsłabszych coinów
    assert tab["title"] == "Alty według kapitalizacji — doba 10.11"
    assert tab["cols"][:3] == ["Koszyk", "Coinów", "Mediana zmiany — doba"]
    assert tab["rows"][0] == ["BTC", "—", "▲+0.5%", "▼-5.0%", "▼-20.0%", "—", "—"]
    assert tab["rows"][2] == ["Alty > $1B", "4", "▲+3.5%", "▼-5.0%", "▼-20.0%", "100%", "100%"]
    assert tab["rows"][5][0] == "Alty $1M – $10M" and "ostatnie 24 h przed zapisem 11.11 00:20 UTC" in tab["note"]
    assert "$50K" in tab["note"]
    md = report.to_markdown({"id": "x", "kind": "morning", "title": "t", "created": now, "blocks": blocks})
    assert "| Alty > $1B | 4 | ▲+3.5% |" in md and "Najmocniejsze" not in md
    meta = report.metas_block(d, now)[0]
    assert meta["rows"][0][:4] == ["Stonks", "12", "$410.0M", "▲+1.8%"] and meta["rows"][1][3] == "▼-3.7%"
    # zapis sprzed dwóch dni → bez bloków (nie pokazujemy nieaktualnej „doby”); stare narracje też znikają
    assert report.caps_blocks(d, now + DAY) == [] and report.metas_block(d, now + 2 * DAY) == []
    assert report.caps_blocks(report.Data(_data_dir(tmp_path / "e", now, {})), now) == []


def test_evening_report_block(tmp_path):
    store = Store(str(tmp_path / "s"))
    A.collect(store, CFG, D0 + 20 * 60, session=FakeCG(market(), METAS), sleep=NOSLEEP)
    A.collect(store, CFG, D0 + 21 * HOUR, session=FakeCG(market({"bitcoin": 0.98, "big0": 0.9}), METAS), sleep=NOSLEEP)
    now = D0 + 21 * HOUR + 45 * 60
    d = report.Data(_data_dir(tmp_path, now, store.extra["alts.json"]))
    b = today.caps_section(d, D0, now)[0]
    assert b["title"] == "Alty według kapitalizacji — od zamknięcia dnia" and b["cols"] == ["Koszyk", "Coinów", "Mediana zmiany", "Na plus", "Lepsze od BTC"]
    assert b["rows"][0] == ["BTC", "—", "▼-2.0%", "—", "—"] and b["rows"][2][:3] == ["Alty > $1B", "4", "•0.0%"]
    assert "10.11 00:20 UTC" in b["note"] and "21:00 UTC" in b["note"]
    assert today.caps_section(d, D0 + DAY, now + DAY) == []          # zapis z poprzedniego dnia → bez bloku


def test_scan_integration(tmp_path):
    """Skan (main.run): zapis koszyków, serie w katalogu, alts.json na dysku, stan źródła w „health”."""
    import alerts
    import main
    import test_collector as TC
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    now = D0 + DAY + 20 * 60
    cfg = TC._cfg(alts={"enabled": True})
    store, _, res = main.run(d, cfg, now=now, coinalyze=TC.FakeCoinalyze(), tv=TC.FakeTV(), telegram=tg, cg_fetch=TC.CG,
                             alts_session=FakeCG(market(), METAS), alts_sleep=NOSLEEP)
    assert res["Alty (CoinGecko)"] is None
    saved = json.load(open(os.path.join(d, "alts.json")))
    assert saved["close"]["day"] == D0 and saved["buckets"][0] == ["1b", "Alty > $1B"] and saved["min_volume"] == 50_000
    meta = json.load(open(os.path.join(d, "meta.json")))
    assert meta["catalog"]["alt_idx_10m"]["group"] == "idx" and meta["info"]["alts"]["snapshot"] == "close"
    assert meta["health"]["Alty (CoinGecko)"] == "ok"
    assert json.load(open(os.path.join(d, "1d.json")))["series"]["alt_idx_1b"] == [[D0, 100.0]]
    # kolejny skan tego samego dnia: bez zapisu, plik zostaje, źródło nadal „ok”
    store, _, res = main.run(d, cfg, now=now + 2 * HOUR, coinalyze=TC.FakeCoinalyze(), tv=TC.FakeTV(), telegram=tg,
                             cg_fetch=TC.CG, alts_session=FakeCG([], None, fail=True), alts_sleep=NOSLEEP)
    assert res["Alty (CoinGecko)"] is None and "alts" not in json.load(open(os.path.join(d, "meta.json")))["info"]
    assert os.path.exists(os.path.join(d, "alts.json"))
    # awaria CoinGecko przy zapisie wieczornym → błąd w „health”, reszta skanu działa
    store, msgs, res = main.run(d, cfg, now=D0 + DAY + 21 * HOUR, coinalyze=TC.FakeCoinalyze(), tv=TC.FakeTV(), telegram=tg,
                                cg_fetch=TC.CG, alts_session=FakeCG([], None, fail=True), alts_sleep=NOSLEEP)
    assert "CoinGecko" in res["Alty (CoinGecko)"] and res["Coinalyze"] is None
    assert any("Alty (CoinGecko)" in m for m in msgs)
    # bez sekcji `alts` w configu moduł jest wyłączony
    store, _, res = main.run(str(tmp_path / "off"), TC._cfg(), now=now, coinalyze=TC.FakeCoinalyze(), tv=TC.FakeTV(),
                             telegram=tg, cg_fetch=TC.CG)
    assert "Alty (CoinGecko)" not in res
