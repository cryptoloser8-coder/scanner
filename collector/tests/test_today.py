"""Raport wieczorny „Krypto dziś” (today.py) i poranny „Zamknięcie dnia” — dane udawane, bez sieci."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import report  # noqa: E402
import today  # noqa: E402

H, DAY = 3600, 86400


def ts(*a):
    return int(datetime(*a, tzinfo=timezone.utc).timestamp())


T0 = ts(2026, 11, 2)                 # poniedziałek 00:00 UTC
NOW = T0 + 21 * H + 50 * 60          # 22:50 PL


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def make_dirs(tmp_path):
    data, ema = str(tmp_path / "data"), str(tmp_path / "ema")
    hours = [T0 - 62 * DAY + i * H for i in range(62 * 24 + 22)]          # do 21:00 UTC dziś
    days = [T0 - 800 * DAY + i * DAY for i in range(801)]

    def h(v_before, v_now):                                               # stała do 00:00, potem stała „teraz”
        return [[t, v_before if t < T0 else v_now] for t in hours]
    h1 = {"total": h(2.5e12, 2.55e12), "total2": h(1.0e12, 1.0e12), "total3es": h(4.8e11, 4.7e11),
          "btc_d": h(60.0, 60.4), "ethbtc": h(0.029, 0.029), "stable_d": h(10.5, 10.4),
          "oi_total": h(6e10, 6.3e10), "oi_others_vs_btc": h(0.74, 0.70),
          "oi_btc": h(2.4e10, 2.52e10), "oi_eth": h(1.4e10, 1.33e10), "oi_sol": h(3e9, 3.3e9), "oi_hype": h(2.7e9, 2.6e9)}
    liq1h = {"px_btc": h(77000.0, 77770.0), "px_eth": h(2300.0, 2208.0),
             "fund_btc": h(10.0, 12.0), "fund_sol": h(5.0, -3.0), "fund_hype": h(10.0, 10.0),
             "liq_total_long": [[t, 2e7 if t == T0 + 14 * H else 1e6] for t in hours],
             "liq_total_short": [[t, 5e5] for t in hours],
             "liq_btc_long": [[t, 1e5] for t in hours], "liq_btc_short": [[t, 1e5] for t in hours]}
    liq1d = {"liq_total_long": [[t, 1e8] for t in days], "liq_total_short": [[t, 5e7] for t in days]}
    d1 = {"total": [[t, 2.5e12] for t in days]}
    for f, s in (("1h", h1), ("liq_1h", liq1h), ("liq_1d", liq1d), ("1d", d1)):
        _w(os.path.join(data, f + ".json"), {"updated": NOW - 40 * 60, "series": s})
    _w(os.path.join(data, "meta.json"), {"catalog": {
        "px_btc": {"name": "Cena BTC", "group": "price", "fmt": "price"},
        "px_eth": {"name": "Cena ETH", "group": "price", "fmt": "price"},
        "total": {"name": "TOTAL", "group": "mcap"}, "total2": {"name": "TOTAL2", "group": "mcap"},
        "total3es": {"name": "TOTAL3 bez stable", "group": "mcap"}, "btc_d": {"name": "BTC.D", "group": "pct"},
        "ethbtc": {"name": "ETH/BTC", "group": "pair"}, "stable_d": {"name": "Stablecoiny.D", "group": "pct"},
        "oi_total": {"name": "OI TOTAL", "group": "oi"}, "oi_others_vs_btc": {"name": "OI OTHERS / OI BTC", "group": "ratio"}}})
    coins = [{"s": "BTC", "p": 77800, "c": 77000, "e": 76000, "d": 2.4, "side": 1, "vol": 9e8},
             {"s": "SOL", "p": 99.0, "c": 95.0, "e": 98.0, "d": 1.0, "side": -1, "vol": 1.7e8},       # wybił EMA w górę
             {"s": "BNB", "p": 700.0, "c": 710.0, "e": 690.0, "d": 1.4, "side": 1, "vol": 5e7},
             {"s": "DOGE", "p": 0.07, "c": 0.075, "e": 0.09, "d": -22.0, "side": -1, "vol": 5e8},
             {"s": "TINY", "p": 2.0, "c": 1.0, "e": 1.5, "d": 33.0, "side": -1, "vol": 4e5}]          # poniżej progu obrotu
    coins += [{"s": f"C{i}", "p": 1.0 + i / 100, "c": 1.0, "e": 0.5, "d": 50.0, "side": 1, "vol": 2e7} for i in range(20)]
    _w(os.path.join(ema, "ema.json"), {"updated": NOW - 300, "above": 40, "total": 200, "coins": coins,
                                        "breadth": [[T0 - DAY, 18.0, 200]], "breadth_delisted": 0})
    return data, ema


EVENTS = [{"title": "ISM Manufacturing PMI", "country": "US", "date": "2026-11-02T15:00:00.000Z", "importance": 1,
           "actual": 48.0, "forecast": 49.5, "previous": 49.1, "period": "Oct"},
          {"title": "Construction Spending MoM", "country": "US", "date": "2026-11-02T15:00:00.000Z", "importance": 0,
           "actual": 0.1, "forecast": 0.2, "previous": 0.0, "unit": "%"},
          {"title": "JOLTs Job Openings", "country": "US", "date": "2026-11-03T15:00:00.000Z", "importance": 1,
           "forecast": 7.2, "previous": 7.1, "scale": "M"}]


def by_title(rep):
    return {b.get("title"): b for b in rep["blocks"]}


def test_evening_crypto_today(tmp_path):
    data, ema = make_dirs(tmp_path)
    rep = report.build(data, ema, "evening", now=NOW, cfg={}, macro={"events": EVENTS, "error": None})
    assert rep["id"].endswith("-evening") and rep["title"] == "Raport wieczorny — krypto dziś"
    secs = [b["title"] for b in rep["blocks"] if b["type"] == "section"]
    assert secs == ["Rynek od zamknięcia dnia", "Coiny z listy", "Likwidacje dziś", "Ruchy coinów dziś", "Makro z USA dziś"]
    by = by_title(rep)
    mk = {r[0]: r for r in by["Od 00:00 UTC (01:00 PL) do teraz"]["rows"]}
    assert mk["Cena BTC"][2] == "▲+1.0%" and mk["BTC.D"][2] == "▲+0.40 pp" and mk["OI OTHERS / OI BTC"][2] == "▼-5.4%"
    assert mk["Szerokość rynku (% nad EMA200)"][1:3] == ["20%", "▲+2.0 pp"]
    coins = {r[0]: r for r in by["Cena, lewar, funding i likwidacje — od 00:00 UTC"]["rows"]}
    assert list(coins) == ["BTC", "ETH", "SOL", "BNB", "DOGE", "HYPE"]
    assert coins["BTC"][2] == "▲+1.0%" and coins["BTC"][5].startswith("nowe longi")         # OI w coinach +4%
    assert coins["ETH"][5].startswith("zamykanie longów")                                    # cena −4%, OI −5% → w coinach −1%
    assert coins["SOL"][2] == "▲+4.2%" and coins["SOL"][6] == "-3.0%"
    assert coins["HYPE"][1] == "—" and coins["HYPE"][4] == "▼-3.7%" and coins["HYPE"][5] == "—"
    assert "HYPE: brak pary Binance spot" in by["Cena, lewar, funding i likwidacje — od 00:00 UTC"]["note"]
    bars = by["Likwidacje od 00:00 UTC — bloki 3-godzinne (czas polski)"]
    assert [r["label"] for r in bars["rows"]][:2] == ["01–04", "04–07"] and len(bars["rows"]) == 8
    assert bars["rows"][-1]["current"] and not bars["rows"][0]["current"] and bars["line"]
    assert "największa godzina: 15:00–16:00 PL" in bars["note"]
    mv = by["Najmocniejsze i najsłabsze — obrót ≥ $10.0M dziennie"]
    assert "Na plus od 00:00 UTC: 22 z 25" in mv["desc"] and mv["rows"][-1][0] == "DOGE"
    cross = by["Przecięcia EMA200 dziś (na żywo) — obrót ≥ $10.0M"]
    assert [r[:2] for r in cross["rows"]] == [["SOL", "w górę"]]
    macro = by["Publikacje ★★★ i zmiana BTC"]
    assert [r[1] for r in macro["rows"]] == ["ISM Manufacturing PMI (Oct)"]                # tylko ★★★ z dziś
    assert macro["rows"][0][5] == "•+0.0%"                                                   # stała cena w tych godzinach
    assert "od 00:00 UTC" in rep["summary"] and "likwidacje dziś" in rep["summary"]
    md = report.to_markdown(rep)
    assert "## Coiny z listy" in md and "| HYPE |" in md


def test_evening_weekend_and_coins_from_config(tmp_path):
    data, ema = make_dirs(tmp_path)
    rep = report.build(data, ema, "evening", now=NOW, cfg={"today": {"coins": ["btc", "sol"]}},
                       macro={"events": [], "error": None})
    assert "Makro z USA dziś" not in [b.get("title") for b in rep["blocks"]]                # brak publikacji → bez sekcji
    rows = by_title(rep)["Cena, lewar, funding i likwidacje — od 00:00 UTC"]["rows"]
    assert [r[0] for r in rows] == ["BTC", "SOL"]
    rep2 = report.build(str(tmp_path / "x"), str(tmp_path / "y"), "evening", now=NOW, cfg={}, macro=None)
    assert rep2["kind"] == "evening" and any(b.get("title") == "Uwaga" for b in rep2["blocks"])


def test_morning_only_plan_high(tmp_path):
    morning = [b for b in report.econ.block(EVENTS, ts(2026, 11, 2, 6, 0), {}, results=False, plan_importance="high")]
    titles = [b.get("title") for b in morning]
    assert not any(str(t).startswith("Publikacje z USA") for t in titles)
    assert morning[1]["title"] == "Zaplanowane — dziś, 02.11.2026"
    assert [r[1] for r in morning[1]["rows"]] == ["ISM Manufacturing PMI (Oct)"] and "★★★" in morning[1]["desc"]
    assert today.coins_cfg({}) == ["BTC", "ETH", "SOL", "BNB", "DOGE", "HYPE"]
