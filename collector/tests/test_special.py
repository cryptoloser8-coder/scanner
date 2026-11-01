"""Raporty roczny i po halvingu (special.py), halvingi z configu, harmonogram 1 stycznia, przypomnienia bota."""
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bot as B  # noqa: E402
import cycle as C  # noqa: E402
import report  # noqa: E402
import special as S  # noqa: E402
import timetable as TT  # noqa: E402
from test_bot import ctx_for, msg  # noqa: E402
from test_cycle import synthetic_px  # noqa: E402

DAY = 86400


def ts(*a):
    return int(datetime(*a, tzinfo=timezone.utc).timestamp())


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def make_dirs(tmp_path):
    data, ema = str(tmp_path / "data"), str(tmp_path / "ema")
    px = sorted(synthetic_px().items())                                   # 2010 → 31.10.2026
    days = [t for t, _ in px if t >= ts(2022, 10, 1)]
    d1 = {"total": [[t, v * 3e7] for t, v in px if t >= ts(2017, 1, 1)],
          "total3es": [[t, v * 6e6] for t, v in px if t >= ts(2017, 1, 1)],
          "btc_d": [[t, 55.0 + (t % 7)] for t, _ in px if t >= ts(2017, 1, 1)],
          "oi_btc": [[t, 2e10] for t in days], "oi_eth": [[t, 1e10] for t in days],
          "oi_others_vs_btc": [[t, 0.7] for t in days], "mvrv_btc": [[t, 1.5] for t, _ in px]}
    liq = {"px_btc": [[t, v] for t, v in px], "liq_total_long": [[t, 1e8] for t in days],
           "liq_total_short": [[t, 5e7] for t in days], "fund_btc": [[t, 10.0] for t, _ in px if t >= ts(2020, 1, 1)],
           "fund_eth": [[t, 8.0] for t, _ in px if t >= ts(2020, 1, 1)]}
    for f, s in (("1d", d1), ("liq_1d", liq)):
        _w(os.path.join(data, f + ".json"), {"updated": ts(2026, 11, 1), "series": s})
    _w(os.path.join(data, "meta.json"), {"catalog": {
        "px_btc": {"name": "Cena BTC", "group": "price", "fmt": "price"}, "total": {"name": "TOTAL", "group": "mcap"},
        "total3es": {"name": "TOTAL3 bez stable", "group": "mcap"}, "btc_d": {"name": "BTC.D", "group": "pct"},
        "mvrv_btc": {"name": "MVRV BTC", "group": "cycle", "fmt": "x"}}})
    _w(os.path.join(ema, "ema.json"), {"updated": ts(2026, 11, 1), "coins": [], "breadth": [[t, 40.0, 300] for t in days]})
    for sym, k in (("BTC", 1.0), ("AAA", 2.0), ("BBB", 0.5)):
        _w(os.path.join(ema, "hist", f"{sym}.json"),
           {"s": sym, "p": 200, "d": [[t, v * k if t >= ts(2025, 6, 1) else v, v * 0.9] for t, v in px if t >= ts(2023, 1, 1)]})
    return data, ema


def test_yearly_report(tmp_path):
    data, ema = make_dirs(tmp_path)
    rep = report.build(data, ema, "yearly", now=ts(2026, 1, 1, 0, 50), cfg={})
    assert rep["kind"] == "yearly" and rep["title"] == "Raport roczny — 2025" and rep["id"].endswith("-yearly")
    secs = [b["title"] for b in rep["blocks"] if b["type"] == "section"]
    assert secs == ["Rok 2025 w liczbach", "BTC rok po roku", "Miesiące 2025", "Derywaty w roku", "Alty i coiny w roku",
                    "Cykl BTC i makro w roku"]
    by = {b.get("title"): b for b in rep["blocks"]}
    btc = by["BTC miesiąc po miesiącu — 2025 i 2024"]
    assert len(btc["rows"]) == 12 and btc["cols"][2:4] == ["Zwrot 2025", "Zwrot 2024"]
    mk = by["Rynek miesiąc po miesiącu — 2025 i 2024"]
    assert mk["rows"][0][5] != "—" and mk["rows"][0][0] == "styczeń"                    # likwidacje 2025
    years = by["Zwrot BTC w kolejnych latach"]["rows"]
    assert years[0][:2] == ["2025", "rok po halvingu"] and years[-1][0] == "2011"
    phase = by["Faza cyklu na 31.12.2025"]["items"]
    assert phase[0]["label"] == "Faza cyklu" and phase[1]["label"] == "Najwyższe zamknięcie w fazie"
    coins = [b for b in rep["blocks"] if str(b.get("title", "")).startswith("Coiny roku")][0]
    assert coins["rows"][0][0] == "AAA" and "3 coinów" in coins["title"]


def test_halving_report_and_previous_check(tmp_path):
    data, ema = make_dirs(tmp_path)
    rep = report.build(data, ema, "halving", now=ts(2026, 11, 1), cfg={})
    assert rep["kind"] == "halving" and rep["title"] == "Raport po halvingu — 20.04.2024"
    by = {b.get("title"): b for b in rep["blocks"]}
    facts = {it["label"]: it for it in by[""]["items"]}
    assert facts["Halving"]["value"] == "nr 4 · blok 840 000" and facts["Nagroda za blok"]["value"] == "6.25 → 3.125 BTC"
    prev = dict((r[0], r[1]) for r in by["Cena BTC po poprzednim halvingu i trafność okna szczytu"]["rows"])
    assert "Szczyt cyklu" in prev and "Okno szczytu z tamtego raportu" in prev
    sysrows = dict(by["System — do zrobienia po halvingu"]["rows"])
    assert "2024-04-20" in sysrows["Data tego halvingu"] and "1 050 000" in sysrows["Następny halving"]
    assert "Podgląd" not in by and not any("tylko w podglądzie" in str(b.get("title")) for b in rep["blocks"])
    prv = S.build_halving(report.Data(data), None, {}, ts(2026, 11, 1), idx=3, preview=True)
    assert any(b.get("title") == "Co stało się potem (tylko w podglądzie)" for b in prv["blocks"])


def test_halvings_from_config_and_save_groups(tmp_path):
    try:
        assert C.configure({"cycle": {"halvings": ["2028-04-17", "zła"]}})[-1] == "2028-04-17"
        assert S.halvings()[-1] == ("2028-04-17", 1050000)
        assert S.latest_halving_idx(ts(2028, 5, 1)) == 4 and S.latest_halving_idx(ts(2026, 5, 1)) == 3
    finally:
        C.configure({})
    assert C.HALVINGS[-1] == "2024-04-20"
    out = str(tmp_path / "rep")
    for i in range(3):
        report.save(out, {"id": f"y{i}-yearly", "kind": "yearly", "title": "r", "created": i, "summary": "", "blocks": []},
                    keep=1, md=f"y{i}", keep_periodic=1)
    idx = json.load(open(os.path.join(out, "index.json")))
    assert len(idx["reports"]) == 3                                       # roczne bez przycinania
    assert open(os.path.join(out, "latest-yearly.md")).read() == "y2"


def test_schedule_yearly_on_january_first():
    sc = TT.load({"reports": [{"scan_at": "00:05", "timezone": "UTC", "monthday": 1, "kind": "monthly"},
                              {"scan_at": "00:05", "timezone": "UTC", "monthday": 1, "month": 1, "kind": "yearly"}]})
    kinds = lambda d: [e["kind"] for e in TT.events_on(sc, d) if e["type"] == "report"]  # noqa: E731
    assert kinds(date(2027, 1, 1)) == ["monthly,yearly"] and kinds(date(2027, 2, 1)) == ["monthly"]


def test_bot_halving_command_and_reminders(tmp_path):
    c = ctx_for(tmp_path, [msg("/raport_teraz halving"), msg("/raport_teraz rok")])
    B.poll(c)
    assert c.gh.calls == [("report.yml", {"kind": "halving"}), ("report.yml", {"kind": "yearly"})]
    assert "po halvingu" in c.api.sent[0]["text"] and "roczny" in c.api.sent[1]["text"]
    cfg = {"cycle": {"next_halving_estimate": "2028-04-15"}}
    c = ctx_for(tmp_path, cfg=dict(cfg), now=ts(2028, 3, 20, 12))
    m = B.halving_tick(c)
    assert len(m) == 1 and "za ok. 26 dni" in m[0] and "1 050 000" in m[0] and "cycle.halvings" in m[0]
    assert B.halving_tick(c) == []                                        # raz na próg
    c.now = ts(2028, 4, 8, 12)
    assert "za ok. 7 dni" in B.halving_tick(c)[0]
    c.cfg = {"cycle": {"next_halving_estimate": "2028-04-15", "halvings": ["2028-04-17"]}}
    c.now = ts(2028, 4, 15, 12)
    assert B.halving_tick(c) == []                                        # halving już dopisany → cisza
    C.configure({})
    assert B.halving_tick(ctx_for(tmp_path, now=ts(2026, 11, 1))) == []
