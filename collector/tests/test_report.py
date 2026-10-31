"""Offline tests for collector/report.py (fake data, no network)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import report  # noqa: E402

DAY = 86400
T0 = 1790000000 - 1790000000 % DAY


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def make_dirs(tmp_path, now):
    data, ema = str(tmp_path / "data"), str(tmp_path / "ema")
    days = [T0 + i * DAY for i in range(400)]
    hours = [days[-1] + h * 3600 for h in range(-48, 1)]
    d1 = {"total": [[t, 2e12 + i * 1e9] for i, t in enumerate(days)],
          "btc_d": [[t, 60 + i * 0.001] for i, t in enumerate(days)],
          "total3": [[t, 7e11] for t in days],
          "oi_others_vs_btc": [[t, 0.5 + (0.7 if i == 100 else 0) + i * 0.0005] for i, t in enumerate(days)]}
    h1 = {"total": [[t, 2.4e12] for t in hours], "btc_d": [[t, 60.5] for t in hours]}
    liq1h = {"liq_total_long": [[t, 1e6] for t in hours], "liq_total_short": [[t, 5e5] for t in hours],
             "fund_btc": [[t, 25.0] for t in hours]}
    _w(os.path.join(data, "1d.json"), {"updated": now, "series": d1})
    _w(os.path.join(data, "1h.json"), {"updated": now, "series": h1})
    _w(os.path.join(data, "liq_1h.json"), {"updated": now, "series": liq1h})
    _w(os.path.join(data, "meta.json"), {"catalog": {
        "total": {"name": "TOTAL", "group": "mcap"}, "btc_d": {"name": "BTC.D", "group": "pct"},
        "total3": {"name": "TOTAL3", "group": "mcap"},
        "oi_others_vs_btc": {"name": "OI OTHERS / OI BTC", "group": "ratio"},
        "fund_btc": {"name": "Funding BTC", "group": "fund", "zones": {"yellow": 20, "red": 40}}}})
    _w(os.path.join(ema, "ema.json"), {
        "updated": now, "above": 37, "total": 370,
        "breadth": [[t, 95.0 if i == 300 else 20.0, 370] for i, t in enumerate(days)],
        "coins": [{"s": "BTC", "p": 77000, "e": 76000, "d": 1.3, "side": 1, "since": 70},
                  {"s": "DOGE", "p": 0.0754, "e": 0.0905, "d": -16.7, "side": -1, "since": 24}],
        "rules": [{"coins": ["BTC", "DOGE", "HYPE"]}]})
    _w(os.path.join(ema, "fib.json"), {"setups": [{"status": "zone"}], "proposals": [{"status": "zone"}] * 3,
                                       "candidates": 50})
    return data, ema


def test_build_facts_and_blocks(tmp_path):
    now = T0 + 400 * DAY
    data, ema = make_dirs(tmp_path, now)
    rep = report.build(data, ema, "test", now=now)
    assert rep["id"].endswith("-test") and rep["title"] == "Raport testowy"
    types = [b["type"] for b in rep["blocks"]]
    assert {"text", "facts", "chart", "table"} <= set(types)
    facts = {it["label"]: it for b in rep["blocks"] if b["type"] == "facts" for it in b["items"]}
    assert facts["TOTAL"]["value"] == "$2.400T"
    assert facts["Funding BTC"]["zone"] == "yellow"                 # zones from the catalogue
    assert "pp" in facts["BTC.D"]["sub"]                            # % series: change in percentage points
    assert facts["Likwidacje 24h (TOTAL)"]["value"] == "$36.0M"     # 24 hourly candles × $1.5M
    assert "maks." in facts["OI OTHERS / OI BTC"]["sub"]
    assert facts["Szerokość rynku"]["value"] == "10.0%"
    table = next(b for b in rep["blocks"] if b["type"] == "table")
    assert [r[0] for r in table["rows"]] == ["BTC", "DOGE"]         # HYPE has no EMA → skipped
    assert table["rows"][1][1] == "$0.0754"
    assert "Uwaga" not in [b["title"] for b in rep["blocks"]]       # fresh data → no warning
    assert "TOTAL $2.400T" in rep["summary"]


def test_stale_data_warning(tmp_path):
    now = T0 + 400 * DAY
    data, ema = make_dirs(tmp_path, now - 10 * 3600)
    rep = report.build(data, ema, "test", now=now)
    warn = [b for b in rep["blocks"] if b["title"] == "Uwaga"]
    assert warn and "sprzed 10 h" in warn[0]["text"]


def test_missing_branches(tmp_path):
    rep = report.build(str(tmp_path / "nic"), str(tmp_path / "nic2"), "test", now=T0)
    assert any(b["title"] == "Uwaga" for b in rep["blocks"])


def test_breadth_note_from_data():
    days = [T0 + i * DAY for i in range(800)]
    br = [[t, 99.6 if i == 700 else 30.0, 300] for i, t in enumerate(days)]
    note = report.breadth_peaks_note(br)
    assert "99.6%" in note and report.utc(days[700], "%m.%Y") in note


def test_save_index_and_prune(tmp_path):
    out = str(tmp_path / "out")
    for i in range(5):
        rep = {"id": f"r{i}", "kind": "test", "title": "T", "created": T0 + i, "summary": "", "blocks": []}
        items = report.save(out, rep, keep=3)
    assert [r["id"] for r in items] == ["r4", "r3", "r2"]
    assert sorted(os.listdir(os.path.join(out, "reports"))) == ["r2.json", "r3.json", "r4.json"]
    idx = json.load(open(os.path.join(out, "index.json")))
    assert idx["reports"][0]["id"] == "r4"


def test_notify_text_has_link():
    txt = report.notify_text({"id": "20261031-1200-test", "title": "Raport testowy", "created": T0, "summary": "TOTAL $2T"},
                             "https://x.github.io/scanner/raporty.html")
    assert 'href="https://x.github.io/scanner/raporty.html?id=20261031-1200-test"' in txt
    assert "Raport testowy" in txt and "TOTAL $2T" in txt


def test_notify_disabled_in_config(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("reports:\n  notify: false\n", encoding="utf-8")
    out = tmp_path / "out"
    report.save(str(out), {"id": "a", "kind": "test", "title": "T", "created": T0, "summary": "", "blocks": []})
    assert report.main(["notify", "--out", str(out), "--config", str(cfg)]) == 0
