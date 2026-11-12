"""Offline tests for weekly / monthly reports (collector/periodic.py) and their plumbing (poprawka 30)."""
import calendar
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import periodic as P  # noqa: E402
import report  # noqa: E402
import timetable as TT  # noqa: E402

DAY = 86400


def ts(y, m, d, h=0, mi=0):
    return calendar.timegm((y, m, d, h, mi, 0))


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def make_dirs(tmp_path, now):
    """Daily data 2011 → now: BTC price with 4-year cycles, cycle indicators, OI/liq/funding from 09.2022."""
    data, ema = str(tmp_path / "data"), str(tmp_path / "ema")
    start = ts(2011, 1, 1)
    days = list(range(start, now - now % DAY, DAY))
    px = [[t, 1000 * math.exp((t - start) / (365 * DAY) * 0.6) * (1.6 + math.sin((t - ts(2012, 11, 28)) / (1461 * DAY)
                                                                                 * 2 * math.pi + 0.8))]
          for t in days]
    oi_days = [t for t in days if t >= ts(2022, 9, 22)]
    d1 = {"px_btc": px, "total": [[t, 2e12] for t in days], "total2": [[t, 1e12] for t in days],
          "totales": [[t, 1.8e12] for t in days], "total3es": [[t, 3e11] for t in days],
          "btc_d": [[t, 60.0] for t in days], "stable_d": [[t, 10.0] for t in days], "ethbtc": [[t, 0.03] for t in days],
          "oi_others_vs_btc": [[t, 0.7] for t in oi_days], "oi_btc": [[t, 3e10] for t in oi_days],
          "oi_eth": [[t, 1.5e10] for t in oi_days], "oi_btc_binance": [[t, 1e10] for t in oi_days],
          "mayer_btc": [[t, 1.0 + (t % (400 * DAY)) / (400 * DAY)] for t in days],
          "picycle_btc": [[t, 0.5] for t in days],
          "net_liq": [[t, 6e12] for t in days if t >= ts(2020, 1, 1)]}
    liq = {"liq_total_long": [[t, 2e8] for t in oi_days], "liq_total_short": [[t, 1e8] for t in oi_days],
           "fund_btc": [[t, 10.0] for t in days if t >= ts(2020, 1, 21)],
           "fund_eth": [[t, 8.0] for t in days if t >= ts(2020, 1, 21)],
           "fund_others": [[t, 5.0] for t in oi_days], "px_eth": [[t, 2000.0] for t in days]}
    for name, ser in (("1d.json", d1), ("liq_1d.json", liq)):
        _w(os.path.join(data, name), {"updated": now, "series": ser})
    _w(os.path.join(data, "1h.json"), {"updated": now, "series": {}})
    _w(os.path.join(data, "meta.json"), {
        "catalog": {"px_btc": {"name": "Cena BTC", "group": "price"}, "total": {"name": "TOTAL", "group": "mcap"},
                    "btc_d": {"name": "BTC.D", "group": "pct"}, "mayer_btc": {"name": "Mayer Multiple", "group": "cycle",
                                                                                "fmt": "x", "desc": "opis"},
                    "picycle_btc": {"name": "Pi Cycle", "group": "cycle", "fmt": "x"},
                    "net_liq": {"name": "Płynność netto Fed", "group": "macro", "fmt": "usd"},
                    "fund_btc": {"name": "Funding BTC", "group": "fund"}},
        "ref_lines": {"mayer_btc": [{"value": 1.8, "label": "szczyt 12.2017", "color": "#e05252"},
                                    {"value": 0.6, "label": "dno 12.2018", "color": "#4caf7d"}]}})
    _w(os.path.join(ema, "ema.json"), {
        "updated": now, "daily_at": now - now % DAY, "above": 40, "total": 200,
        "breadth": [[t, 20.0, 200] for t in days],
        "coins": [{"s": "SOL", "p": 95, "e": 98, "d": -2.4, "side": -1, "since": 3, "vol": 1.7e8,
                   "cross_t": ts(2026, 10, 28)},
                  {"s": "TINY", "p": 1, "e": 0.9, "d": 5.0, "side": 1, "since": 2, "vol": 1e5, "cross_t": ts(2026, 10, 29)},
                  {"s": "OLD", "p": 1, "e": 0.9, "d": 5.0, "side": 1, "since": 90, "vol": 5e8, "cross_t": ts(2026, 7, 1)}]})
    return data, ema


EVENTS = [
    {"date": "2026-10-29T18:00:00.000Z", "country": "US", "importance": 1, "title": "Fed Interest Rate Decision",
     "actual": 3.75, "forecast": 3.75, "previous": 4.0, "unit": "%"},
    {"date": "2026-10-30T12:30:00.000Z", "country": "US", "importance": 0, "title": "Core PCE MoM",
     "actual": 0.2, "forecast": 0.3, "previous": 0.2, "unit": "%"},
    {"date": "2026-11-06T13:30:00.000Z", "country": "US", "importance": 1, "title": "Non Farm Payrolls",
     "forecast": 50, "previous": 22, "scale": "K"},
    {"date": "2026-11-03T15:00:00.000Z", "country": "US", "importance": 0, "title": "ISM Manufacturing PMI",
     "forecast": 49.5, "previous": 49.1},
    {"date": "2026-11-04T10:00:00.000Z", "country": "EU", "importance": 1, "title": "EU thing"},
]


# ── okres i tytuł ────────────────────────────────────────────
def test_period_weekly_and_monthly():
    now = ts(2026, 11, 2, 0, 50)                      # poniedziałek po zamknięciu tygodnia 26.10–01.11
    assert P.period("weekly", now) == (ts(2026, 10, 26), ts(2026, 11, 2))
    assert P.title("weekly", *P.period("weekly", now)) == "Raport tygodniowy — 26.10–01.11.2026"
    # ręcznie w środku tygodnia → poprzedni pełny tydzień
    assert P.period("weekly", ts(2026, 11, 5, 15)) == (ts(2026, 10, 26), ts(2026, 11, 2))
    assert P.period("monthly", ts(2026, 11, 1, 0, 50)) == (ts(2026, 10, 1), ts(2026, 11, 1))
    assert P.period("monthly", ts(2026, 1, 15)) == (ts(2025, 12, 1), ts(2026, 1, 1))
    assert P.title("monthly", ts(2026, 10, 1), ts(2026, 11, 1)) == "Raport miesięczny — październik 2026"
    assert P.month_start(ts(2026, 3, 10), 3) == ts(2025, 12, 1)


def test_month_return_wraps_year():
    px = [[ts(2020, 11, 30), 100.0], [ts(2020, 12, 31), 110.0], [ts(2021, 1, 31), 99.0]]
    assert round(P.month_return(px, 2021, 0), 6) == 10.0          # grudzień 2020
    assert round(P.month_return(px, 2020, 13), 6) == -10.0        # styczeń 2021
    assert P.month_return(px, 2021, 2) is None


def test_slow_series_compared_with_earlier_reading(tmp_path):
    now = ts(2026, 11, 1, 0, 50)
    data, ema = make_dirs(tmp_path, now)
    d = report.Data(data)
    d.res["1d"]["m2"] = [[ts(2026, m, 1), 2.0e13 + m * 1e11] for m in range(1, 10)]     # odczyty do 09.2026
    d.catalog["m2"] = {"name": "M2 USA", "group": "macro", "fmt": "usd"}
    end = ts(2026, 11, 1)
    rows = P.change_table(d, None, ["m2"], end - DAY, ts(2026, 10, 1), end, [("1 mies.", ts(2026, 9, 30))], "t", "d")[0]["rows"]
    assert rows[0][0] == "M2 USA (odczyt za 09.2026)" and rows[0][2] == "▲+0.5%"       # 09 vs 08, nie 09 vs 09


def test_weekly_mas_and_closes():
    pts = [[ts(2020, 1, 5) + i * DAY, 100.0 + i] for i in range(7 * 210)]
    t_end = pts[-1][0]
    wk = P.weekly_closes(pts, t_end)
    assert all(datetime.fromtimestamp(t, timezone.utc).weekday() == 6 for t, _ in wk) and len(wk) == 210
    assert P.sma_last([1, 2, 3, 4], 2) == 3.5 and P.sma_last([1], 2) is None


# ── całe raporty ─────────────────────────────────────────────
def test_build_weekly(tmp_path):
    now = ts(2026, 11, 2, 0, 50)
    data, ema = make_dirs(tmp_path, now)
    rep = report.build(data, ema, "weekly", now=now, cfg={}, macro={"events": EVENTS, "error": None})
    assert report.layout({})["weekly_ema_coins"] == ["BTC", "ETH", "SOL", "BNB"]
    assert rep["kind"] == "weekly" and rep["id"].endswith("-weekly") and rep["period"]["start"] == ts(2026, 10, 26)
    assert rep["title"] == "Raport tygodniowy — 26.10–01.11.2026"
    secs = [b["title"] for b in rep["blocks"] if b["type"] == "section"]
    assert secs == ["Tydzień w liczbach", "Alty w tygodniu", "Derywaty w tygodniu", "EMA200 w tygodniu",
                    "Makro USA", "Cykl BTC w tygodniu"]
    by = {b.get("title"): b for b in rep["blocks"]}
    first = by["Zamknięcie tygodnia i zmiany"]
    assert first["cols"][:4] == ["Wskaźnik", "Zamknięcie", "1 tydzień", "4 tygodnie"]
    assert first["rows"][0][0] == "Cena BTC"
    assert len(by["BTC na tle średnich tygodniowych"]["rows"]) == 3
    bars = by["Likwidacje — ostatnie 12 tygodni"]
    assert len(bars["rows"]) == 12 and bars["rows"][-1]["current"] and bars["rows"][-1]["label"] == "26.10"
    assert bars["rows"][-1]["long"] == 7 * 2e8
    # EMA: tylko przecięcia z tygodnia; TINY poniżej progu obrotu, OLD poza tygodniem
    ema_tbl = by["EMA200 na świecy dziennej — przecięcia coinów z obrotem ≥ $10.0M dziennie"]
    assert [r[0] for r in ema_tbl["rows"]] == ["SOL"] and "2 coinów" in ema_tbl["desc"]
    # makro: ★★★ z tygodnia, plan ★★/★★★ na kolejny (bez innych krajów)
    res = by["Wyniki publikacji ★★★ — miniony tydzień"]
    assert [r[2] for r in res["rows"]] == ["Fed Interest Rate Decision"]
    plan = [b for b in rep["blocks"] if str(b.get("title", "")).startswith("Plan —")][0]
    assert [r[2] for r in plan["rows"]] == ["ISM Manufacturing PMI", "Non Farm Payrolls"]
    assert by["Rynki i płynność — zamknięcie tygodnia"]["rows"][0][0] == "Płynność netto Fed"
    assert "Cena BTC" in rep["summary"]
    cyc = [r[0] for r in by["Wskaźniki cyklu — zamknięcie tygodnia"]["rows"]]
    assert "Pi Cycle" not in cyc and cyc                       # Pi Cycle tylko w zakładce
    alts = {r[0]: r for r in by["Lewar, kapitał i szerokość — zamknięcie tygodnia"]["rows"]}
    assert alts["Szerokość rynku (% nad EMA200)"][1] == "20%"
    md = report.to_markdown(rep)
    assert "| Tydzień od (UTC) | Suma |" in md and "## Cykl BTC w tygodniu" in md


def test_build_monthly(tmp_path):
    now = ts(2026, 11, 1, 0, 50)
    data, ema = make_dirs(tmp_path, now)
    rep = report.build(data, ema, "monthly", now=now, cfg={}, macro={"events": EVENTS, "error": None})
    assert rep["title"] == "Raport miesięczny — październik 2026"
    secs = [b["title"] for b in rep["blocks"] if b["type"] == "section"]
    assert secs == ["Miesiąc w liczbach", "Gdzie jesteśmy w cyklu BTC", "Struktura rynku", "Derywaty w miesiącu", "Makro USA"]
    by = {b.get("title"): b for b in rep["blocks"]}
    assert by["Zamknięcie miesiąca i zmiany"]["cols"][2:5] == ["1 mies.", "3 mies.", "12 mies."]
    seas = by["Październik w historii BTC — z miesiącem przed i po"]
    assert seas["cols"] == ["Rok", "Wrzesień", "Październik (ten miesiąc)", "Listopad"]
    assert seas["rows"][0][0] == "Mediana" and seas["rows"][1][0] == "Lat na plus"
    assert seas["rows"][1][2].endswith("z 15")
    assert seas["rows"][2][0] == "2026" and seas["rows"][2][3] == "—" and seas["rows"][-1][0] == "2011"
    chart = by["Cena BTC i fazy cyklu — od 2011"]
    assert chart["bands"] and {b["label"].split(" ")[0] for b in chart["bands"]} <= {"hossa", "bessa", "akumulacja"}
    facts = {it["label"]: it for it in by["Stan na zamknięcie miesiąca"]["items"]}
    assert "dzień" in facts["Faza cyklu"]["value"]
    assert "Fazy kolejnych cykli — czas trwania i zmiana ceny" in by
    assert "Tło wykresu (okresy):" in report.to_markdown(rep)
    cyc = by["Obecny cykl na tle poprzednich"]
    assert cyc["rows"][-1][0].startswith("2024") and len(cyc["rows"]) >= 3
    rng = by["Wskaźniki cyklu na tle trzech ostatnich cykli"]["items"]
    mayer = [it for it in rng if it["label"] == "Mayer Multiple"][0]
    assert {m["kind"] for m in mayer["marks"]} == {"top", "bottom"}
    import re
    assert re.match(r"^szczyt \d\d\.\d{4}: \d+\.\d\d×$", mayer["marks"][0]["label"])     # liczone z danych, nie z meta
    liq = by["Likwidacje — ostatnie 12 miesięcy"]
    assert liq["rows"][-1]["label"] == "10.2026" and liq["rows"][-1]["long"] == 31 * 2e8
    fund = by["Funding — średnia miesiąca na tle historii"]["rows"]
    assert fund[0][0] == "BTC" and fund[0][1] == "+10.0%"
    struct = {r[0]: r for r in by["Zamknięcia miesięczne — teraz i wcześniej"]["rows"]}
    assert struct["Udział Binance w OI BTC"][1] == "33.33%"
    res = by["Wyniki publikacji ★★★ — miniony miesiąc"]
    assert [r[2] for r in res["rows"]] == ["Fed Interest Rate Decision"]
    plan = [b for b in rep["blocks"] if str(b.get("title", "")).startswith("Plan —")][0]
    assert [r[2] for r in plan["rows"]] == ["Non Farm Payrolls"]       # miesięczny: tylko ★★★


def test_monthly_accumulation_and_projection(tmp_path):
    now = ts(2026, 11, 1, 0, 50)
    data, ema = make_dirs(tmp_path, now)
    import cycle as C
    from test_cycle import synthetic_px                     # szczyt 10.2025 potwierdzony, dno 2026 jeszcze nie
    px = synthetic_px()
    f1d = os.path.join(data, "1d.json")
    js = json.load(open(f1d))
    js["series"]["px_btc"] = sorted([t, v] for t, v in px.items())
    _w(f1d, js)
    top = [p for p in C.phases(px) if p["phase"] == "bear"][-1]["from"]
    after = {t: v for t, v in px.items() if t > top}
    t_lo = min(after, key=after.get)
    iso = datetime.fromtimestamp(t_lo, timezone.utc).strftime("%Y-%m-%d")
    rep = report.build(data, ema, "monthly", now=now, cfg={"cycle": {"bottoms": [iso]}}, macro=None)
    by = {b.get("title"): b for b in rep["blocks"]}
    facts = {it["label"]: it for it in by["Stan na zamknięcie miesiąca"]["items"]}
    assert facts["Faza cyklu"]["value"].startswith("Akumulacja") and "od dna" in facts["Faza cyklu"]["sub"]
    assert "niepotwierdzona" in facts["Faza cyklu"]["value"]
    bands = by["Cena BTC i fazy cyklu — od 2011"]["bands"]
    assert bands[-1]["label"] == "akumulacja niepotwierdzona (trwa)" and bands[-1]["color"] == "#b39ddb"
    rows = by["Fazy kolejnych cykli — czas trwania i zmiana ceny"]["rows"]
    assert rows[-1][1].endswith("(niepotwierdzona)") and rows[-2][3].endswith("(dno niepotwierdzone)")
    proj = by["Okno szacunkowe kolejnych etapów cyklu"]
    assert proj["rows"][0][0].startswith("Koniec akumulacji") and "Łączne okno szczytu" in proj["desc"]
    # dno z configu, poniżej którego cena później zamknęła się → ostrzeżenie, bessa
    rep2 = report.build(data, ema, "monthly", now=now, cfg={"cycle": {"bottoms": ["2026-02-01"]}}, macro=None)
    assert any("nie obowiązuje" in (b.get("text") or "") for b in rep2["blocks"])


def test_build_without_macro_and_stale_data(tmp_path):
    now = ts(2026, 11, 2, 0, 50)
    data, ema = make_dirs(tmp_path, ts(2026, 11, 1, 12))              # dane sprzed zamknięcia tygodnia
    rep = report.build(data, ema, "weekly", now=now, cfg={}, macro={"events": [], "error": "HTTP 403"})
    assert rep["blocks"][0]["title"] == "Uwaga" and "sprzed zamknięcia" in rep["blocks"][0]["text"]
    assert any("niedostępny (HTTP 403)" in (b.get("text") or "") for b in rep["blocks"])


# ── zapis: osobne przycinanie i latest-<rodzaj> ──────────────
def test_save_groups_and_latest(tmp_path):
    out = str(tmp_path / "rep")

    def rep(i, kind):
        return {"id": f"r{i:03d}-{kind}", "kind": kind, "title": kind, "created": 1000 + i, "summary": "", "blocks": []}
    for i in range(5):
        report.save(out, rep(i, "morning"), keep=3, md=f"daily {i}", keep_periodic=2)
    for i in range(5, 8):
        report.save(out, rep(i, "weekly"), keep=3, md=f"weekly {i}", keep_periodic=2)
    report.save(out, rep(8, "monthly"), keep=3, md="monthly 8", keep_periodic=2)
    idx = json.load(open(os.path.join(out, "index.json")))
    kinds = [r["kind"] for r in idx["reports"]]
    assert kinds.count("morning") == 3 and kinds.count("weekly") == 2 and kinds.count("monthly") == 1
    assert not os.path.exists(os.path.join(out, "reports", "r005-weekly.json"))
    assert os.path.exists(os.path.join(out, "reports", "r004-morning.json"))
    assert open(os.path.join(out, "latest.md")).read() == "daily 4"          # dzienny nie nadpisany przez tygodniowy
    assert open(os.path.join(out, "latest-weekly.md")).read() == "weekly 7"
    assert open(os.path.join(out, "latest-monthly.md")).read() == "monthly 8"
    assert json.load(open(os.path.join(out, "latest-monthly.json")))["id"] == "r008-monthly"


def test_main_make_several_kinds_and_notify(tmp_path, monkeypatch):
    now = ts(2026, 11, 2, 0, 50)
    data, ema = make_dirs(tmp_path, now)
    out, made = str(tmp_path / "rep"), str(tmp_path / "made.json")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("reports:\n  econ:\n    enabled: false\ntelegram:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setattr(report.time, "time", lambda: now)
    args = ["--data", data, "--ema", ema, "--out", out, "--made", made, "--config", str(cfg)]
    assert report.main(["make", "--kind", "weekly,monthly"] + args) == 0
    ids = json.load(open(made))["ids"]
    assert [i.split("-")[-1] for i in ids] == ["weekly", "monthly"]
    assert report.main(["make", "--kind", "decade"] + args) == 2
    sent = []

    class FakeTg:
        enabled = True

        def __init__(self, tg_cfg=None):
            pass

        def post(self, kind, text):
            sent.append((kind, text))
            return True
    monkeypatch.setattr(report.alerts, "Telegram", FakeTg)
    monkeypatch.setattr(report.time, "sleep", lambda s: None)
    assert report.main(["notify"] + args) == 0
    assert [k for k, _ in sent] == ["report", "report"]
    assert "Raport tygodniowy — 26.10–01.11.2026" in sent[0][1] and "Raport miesięczny — październik 2026" in sent[1][1]


def test_macro_window_wider_for_periodic(monkeypatch):
    seen = {}

    def fake_fetch(now_ts, cfg=None, **kw):
        seen["econ"] = (cfg or {}).get("econ")
        return []
    monkeypatch.setattr(report.econ, "fetch", fake_fetch)
    report.macro_for("monthly", {"econ": {"countries": ["US"]}})
    assert seen["econ"]["days_back"] == 63 and seen["econ"]["days_ahead"] == 38 and seen["econ"]["countries"] == ["US"]
    report.macro_for("morning", {"econ": {"days_back": 5}})
    assert seen["econ"] == {"days_back": 5}
    assert report.macro_for("weekly", {"econ": {"enabled": False}}) is None


# ── harmonogram ─────────────────────────────────────────────
SC = TT.load({"reports": [
    {"scan_at": "06:15", "kind": "morning"},
    {"scan_at": "00:05", "timezone": "UTC", "weekday": 1, "kind": "weekly"},
    {"scan_at": "00:05", "timezone": "UTC", "monthday": 1, "kind": "monthly"}]})


def _reports(day):
    return [(e["at"].strftime("%H:%M"), e["kind"]) for e in TT.events_on(SC, day) if e["type"] == "report"]


def test_timetable_weekly_monthly():
    from datetime import date
    assert _reports(date(2026, 11, 2)) == [("01:05", "weekly"), ("06:15", "morning")]       # poniedziałek (zima)
    assert _reports(date(2026, 11, 1)) == [("01:05", "monthly"), ("06:15", "morning")]      # 1. dzień (niedziela)
    assert _reports(date(2026, 11, 3)) == [("06:15", "morning")]
    assert _reports(date(2026, 6, 1)) == [("02:05", "weekly,monthly"), ("06:15", "morning")]  # pon. 1.06 (lato): jeden skan
    ev = [e for e in TT.events_on(SC, date(2026, 11, 2)) if e["type"] == "scan"]
    assert "00:15" not in [e["at"].strftime("%H:%M") for e in ev]                            # zwykły skan pominięty
    due = TT.due(SC, ts(2026, 6, 1, 0, 6), {})
    assert [e["kind"] for e in due] == ["weekly,monthly"]


def test_bot_kind_title():
    import bot
    assert bot._kind_title("weekly,monthly") == "tygodniowy i miesięczny"
    assert bot._kind_title("morning") == "poranny (zamknięcie dnia)"


def test_delete_report_and_latest(tmp_path):
    out = str(tmp_path / "rep")

    def rep(i, kind):
        return {"id": f"2026110{i}-0100-{kind}", "kind": kind, "title": f"{kind} {i}", "created": 1000 + i,
                "summary": "", "blocks": []}
    report.save(out, rep(1, "monthly"), md="monthly 1")
    report.save(out, rep(2, "morning"), md="daily 2")
    report.save(out, rep(3, "monthly"), md="monthly 3")
    assert open(os.path.join(out, "latest-monthly.md")).read() == "monthly 3"
    # usunięcie najnowszego miesięcznego → latest-monthly wraca do poprzedniego, dzienny bez zmian
    args = ["delete", "--out", out, "--config", str(tmp_path / "brak.yaml")]
    assert report.main(args + ["--id", "20261103-0100-monthly"]) == 0
    idx = json.load(open(os.path.join(out, "index.json")))
    assert [r["id"] for r in idx["reports"]] == ["20261102-0100-morning", "20261101-0100-monthly"]
    assert not os.path.exists(os.path.join(out, "reports", "20261103-0100-monthly.json"))
    assert not os.path.exists(os.path.join(out, "reports", "20261103-0100-monthly.md"))
    assert open(os.path.join(out, "latest-monthly.md")).read() == "monthly 1"
    assert json.load(open(os.path.join(out, "latest-monthly.json")))["id"] == "20261101-0100-monthly"
    assert open(os.path.join(out, "latest.md")).read() == "daily 2"
    # ostatni z grupy → stałe pliki grupy znikają; nieznane id → kod 1
    assert report.main(args + ["--id", "20261101-0100-monthly"]) == 0
    assert not os.path.exists(os.path.join(out, "latest-monthly.md"))
    assert report.main(args + ["--id", "nie-ma"]) == 1


def test_formats_z_and_breadth():
    assert P.chg(0.84, 0.91, "z") == "▼-0.07" and P.chg(1.0, 0.83, "z") == "▲+0.17"
    assert P.fv(20.49, "pct0") == "20%" and P.chg(20.49, 25.07, "pct0") == "▼-4.6 pp"


def test_plan_starts_at_build_time(tmp_path):
    # raport z ręki w niedzielę 08.11: okres 26.10–01.11, plan od 08.11 (nie od 02.11, które już minęło)
    now = ts(2026, 11, 8, 15, 0)
    data, ema = make_dirs(tmp_path, now)
    evs = [{"date": "2026-11-03T14:00:00.000Z", "country": "US", "importance": 1, "title": "Past Event"},
           {"date": "2026-11-10T13:30:00.000Z", "country": "US", "importance": 1, "title": "CPI YoY",
            "forecast": 3.0, "previous": 2.9, "unit": "%"},
           {"date": "2026-11-16T13:30:00.000Z", "country": "US", "importance": 1, "title": "Too Far"}]
    rep = report.build(data, ema, "weekly", now=now, cfg={}, macro={"events": evs, "error": None})
    assert rep["period"]["start"] == ts(2026, 10, 26)
    plan = [b for b in rep["blocks"] if str(b.get("title", "")).startswith("Plan —")][0]
    assert plan["title"].endswith("08.11–14.11.2026") and [r[2] for r in plan["rows"]] == ["CPI YoY"]


def test_weekly_ema200_block(tmp_path):
    now = ts(2026, 11, 2, 0, 50)
    data, ema = make_dirs(tmp_path, now)
    t_end = ts(2026, 11, 1)
    e = json.load(open(os.path.join(ema, "ema.json")))
    e["period"] = 200
    e["coins"] += [
        {"s": "BTC", "p": 72000, "e": 76000, "d": -5.0, "side": -1, "since": 9, "weeks": 483, "we": 69800, "wd": 3.2,
         "wc": 74000, "wec": 69700, "wside": 1, "wsince": 11, "wcross_t": ts(2026, 8, 23), "wt": t_end},
        {"s": "ZEC", "p": 300, "e": 200, "d": 50.0, "side": 1, "since": 40, "weeks": 450, "we": 100, "wd": 200.0,
         "wc": 310, "wec": 98, "wside": 1, "wsince": 1, "wcross_t": t_end, "wt": t_end},
        {"s": "ETH", "p": 2000, "e": 2400, "d": -16.0, "side": -1, "since": 30, "weeks": 483, "we": 2450, "wd": -18.0,
         "wc": 2050, "wec": 2460, "wside": -1, "wsince": 1, "wcross_t": t_end, "wt": t_end},
        {"s": "SUI", "p": 1, "e": 1.5, "d": -33.0, "side": -1, "since": 60, "weeks": 185}]
    e["weekly"] = {"min_weeks": 300, "total": 3, "above": 2, "above_close": 2, "t": t_end, "alerts": ["BTC", "ETH"],
                   "breadth": [[t_end - 4 * P.WEEK, 10.0, 3], [t_end - P.WEEK, 33.33, 3], [t_end, 66.67, 3]]}
    json.dump(e, open(os.path.join(ema, "ema.json"), "w"))
    cfg = {"weekly_ema_coins": ["BTC", "ETH", "SUI", "XRP"]}
    rep = report.build(data, ema, "weekly", now=now, cfg=cfg, macro=None)
    by = {b.get("title"): b for b in rep["blocks"]}
    tbl = by["EMA200 na świecy tygodniowej — zamknięcie tygodnia"]
    rows = {r[0]: r for r in tbl["rows"]}
    assert list(rows) == ["BTC", "ETH", "SUI"]                              # XRP nie ma w danych
    assert rows["BTC"][1:7] == ["$74,000", "$69,700", "+6.2%", "nad", "11", "23.08.2026"]
    assert rows["ETH"][4] == "pod (przecięcie w tym tygodniu)"
    assert "za krótka historia (185 z 300 tyg.)" in rows["SUI"][4]
    assert "2 z 3 coinów (67%); tydzień wcześniej 33%, 4 tygodnie wcześniej 10%" in tbl["note"]
    assert "w górę: ZEC; w dół: ETH" in tbl["note"]
    # dane z innego tygodnia (np. Pi jeszcze nie przeliczył) → tylko komunikat
    e["weekly"]["t"] = t_end - P.WEEK
    json.dump(e, open(os.path.join(ema, "ema.json"), "w"))
    rep = report.build(data, ema, "weekly", now=now, cfg=cfg, macro=None)
    blk = [b for b in rep["blocks"] if b.get("title") == "EMA200 na świecy tygodniowej — zamknięcie tygodnia"][0]
    assert blk["type"] == "text" and "25.10.2026" in blk["text"]


def test_report_price_charts_have_candles(tmp_path):
    now = ts(2026, 11, 2, 0, 50)
    data, ema = make_dirs(tmp_path, now)
    f = os.path.join(data, "liq_1d.json")
    js = json.load(open(f))
    px = report.Data(data).pts("1d", "px_btc")
    js["series"]["px_btc_hi"] = [[t, v * 1.03] for t, v in px if t >= ts(2019, 9, 12)]
    js["series"]["px_btc_lo"] = [[t, v * 0.97] for t, v in px if t >= ts(2019, 9, 12)]
    json.dump(js, open(f, "w"))
    rep = report.build(data, ema, "weekly", now=now, cfg={}, macro=None)
    ch = [b for b in rep["blocks"] if b.get("title") == "BTC i średnie tygodniowe — od 2011"][0]
    s0 = ch["series"][0]
    assert s0["ohlc"] and s0["ohlc"][-1][0] == s0["data"][-1][0] and s0["ohlc"][-1][4] == s0["data"][-1][1]
    for t, o, h, l_, c in s0["ohlc"]:
        assert l_ <= min(o, c) <= max(o, c) <= h and P._dt(t).weekday() == 6
    assert s0["ohlc"][1][1] == s0["ohlc"][0][4]                               # open = zamknięcie poprzedniego tygodnia
    rep = report.build(data, ema, "monthly", now=ts(2026, 11, 1, 0, 50), cfg={}, macro=None)
    ch = [b for b in rep["blocks"] if b.get("title") == "Cena BTC i fazy cyklu — od 2011"][0]
    s0 = ch["series"][0]
    assert [c[0] for c in s0["ohlc"]] == [p[0] for p in s0["data"]] and len(s0["ohlc"]) > 150
    assert all(P._dt(c[0]).day >= 28 for c in s0["ohlc"])                   # ostatni dzień miesiąca
    assert "świece" in report.to_markdown(rep) or "Cena BTC" in report.to_markdown(rep)
