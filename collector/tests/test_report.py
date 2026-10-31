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
    days = [T0 + i * DAY for i in range(800)]
    hours = [days[-1] + h * 3600 for h in range(-48, 1)]
    peak = {300: 1.3, 600: 1.05}                                    # OI OTHERS/BTC peaks (300 = altseason)
    d1 = {"total": [[t, 2e12 + i * 1e9] for i, t in enumerate(days)],
          "total2": [[t, 1e12] for t in days],
          "totales": [[t, 1.8e12 + i * 1e9] for i, t in enumerate(days)],
          "total3es": [[t, 3e11 + (2e11 if i == 300 else 0)] for i, t in enumerate(days)],
          "btc_d": [[t, 60 + i * 0.001] for i, t in enumerate(days)],
          "stable_d": [[t, 10.0] for t in days],
          "ethbtc": [[t, 0.03] for t in days],
          "oi_others_vs_btc": [[t, peak.get(i, 0.6 + (0.1 if i == 700 else 0) - (0.05 if i == 650 else 0))]
                               for i, t in enumerate(days)],
          "oi_others": [[t, 1.8e10] for t in days], "oi_btc": [[t, 2.4e10] for t in days],
          "oi_eth": [[t, 1.4e10] for t in days]}
    h1 = {"total": [[t, 2.4e12] for t in hours], "btc_d": [[t, 60.5] for t in hours],
          "oi_btc": [[t, 2.4e10 * (1.05 if t == hours[-1] else 1)] for t in hours]}
    liq1d = {"liq_total_long": [[t, 6e8 if i == 795 else 1e8] for i, t in enumerate(days)],
             "liq_total_short": [[t, 5e7] for t in days],
             "fund_btc": [[t, 10.0] for t in days], "fund_eth": [[t, -5.0] for t in days],
             "fund_others": [[t, 40.0 if i == 300 else 8.0] for i, t in enumerate(days)],
             "px_btc": [[t, 77000.0] for t in days], "px_eth": [[t, 2200.0] for t in days]}
    liq1h = {"liq_total_long": [[t, 1e6] for t in hours], "liq_total_short": [[t, 5e5] for t in hours],
             "fund_btc": [[t, 25.0] for t in hours],
             "px_btc": [[t, 77000.0 * (0.98 if t == hours[-1] else 1)] for t in hours]}
    _w(os.path.join(data, "1d.json"), {"updated": now, "series": d1})
    _w(os.path.join(data, "1h.json"), {"updated": now, "series": h1})
    _w(os.path.join(data, "liq_1d.json"), {"updated": now, "series": liq1d})
    _w(os.path.join(data, "liq_1h.json"), {"updated": now, "series": liq1h})
    _w(os.path.join(data, "meta.json"), {"catalog": {
        "total": {"name": "TOTAL", "group": "mcap"}, "btc_d": {"name": "BTC.D", "group": "pct"},
        "stable_d": {"name": "Stablecoiny.D", "group": "pct"}, "stable_mcap": {"name": "Stablecoiny", "group": "mcap"},
        "oi_others_vs_btc": {"name": "OI OTHERS / OI BTC", "group": "ratio"},
        "oi_others": {"name": "OI OTHERS", "group": "oi"}, "oi_btc": {"name": "OI BTC", "group": "oi"},
        "fund_btc": {"name": "Funding BTC", "group": "fund", "zones": {"yellow": 20, "red": 40}}}})
    _w(os.path.join(ema, "ema.json"), {
        "updated": now, "above": 37, "total": 370,
        "breadth": [[t, 95.0 if i == 300 else 20.0, 370] for i, t in enumerate(days)],
        "coins": [{"s": "BTC", "p": 77000, "e": 76000, "d": 1.3, "side": 1, "since": 70, "vol": 9e8},
                  {"s": "SOL", "p": 95, "e": 98, "d": -2.4, "side": -1, "since": 2, "vol": 1.7e8},
                  {"s": "TINY", "p": 1, "e": 1.01, "d": -1.0, "side": -1, "since": 3, "vol": 4e5},
                  {"s": "DOGE", "p": 0.0754, "e": 0.0905, "d": -16.7, "side": -1, "since": 24, "vol": 5e8}],
        "rules": [{"coins": ["BTC", "DOGE", "HYPE"]}]})
    return data, ema


def blocks_by_title(rep):
    return {b.get("title"): b for b in rep["blocks"]}


def test_build_layout_v2(tmp_path):
    now = T0 + 800 * DAY
    data, ema = make_dirs(tmp_path, now)
    rep = report.build(data, ema, "test", now=now)
    assert rep["id"].endswith("-test") and rep["title"] == "Raport testowy" and rep["layout"] == 2
    sections = [b["title"] for b in rep["blocks"] if b["type"] == "section"]
    assert sections == ["Rynek", "Alty", "Derywaty", "Likwidacje", "EMA200 — coiny blisko średniej"]
    by = blocks_by_title(rep)
    # Rynek: 4 range bars, altseason mark from the data (day 300: OI peak with breadth 95%)
    rng = by["Gdzie jest rynek na tle ostatnich 2 lat"]["items"]
    assert [it["label"] for it in rng][:2] == ["Cały rynek (TOTAL)", "Udział BTC (BTC.D)"]
    assert rng[0]["value"] == "$2.400T" and "od szczytu" in rng[0]["sub"]
    assert all(0 <= it["pos"] <= 100 for it in rng)
    alt_day = report.utc(T0 + 300 * DAY, "%m.%Y")
    assert [m["label"].split(":")[0] for m in rng[0]["marks"] if m.get("kind") == "ref"] == [f"altseason {alt_day}"]
    # Alty table: columns = peaks ≥ 1.0 + lowest point of 12 months, found in the data
    tab = by["Stan altów na tle poprzednich szczytów"]
    assert tab["cols"][0:2] == ["Wskaźnik", "Dziś"]
    assert any("(altseason)" in c for c in tab["cols"]) and any(c.startswith("dno 12 mies.") for c in tab["cols"])
    assert len(tab["cols"]) == 5                                     # 2 peaks + dno
    alt_row = tab["rows"][1]
    assert alt_row[0].startswith("Kapitał") and alt_row[2] == "0.385"  # (3e11 + 2e11) / (2.3e12 − 1e12) on day 300
    oi_chart = by["Lewar: OI OTHERS / OI BTC — cała historia"]
    assert [l["value"] for l in oi_chart["lines"]] == [0.60, 0.85, 0.95, 1.00]
    assert by["Kapitał: Alty / BTC — od 2020"]["lines"]
    # Derywaty: OI in coins, not dollars (24h: OI $ +5%, price −2% → OI in coins +7.1%)
    oi_rows = by["Open interest i cena — BTC i ETH"]["rows"]
    btc24 = next(r for r in oi_rows if r[0] == "BTC" and r[1] == "24 h")
    assert btc24[2] == "▼-2.0%" and btc24[3] == "▲+7.1%" and btc24[5].startswith("nowe shorty")
    # Likwidacje: 7 full days + last 24 h, "big day" line from 2-year percentile
    bars = by["Likwidacje — ostatnie 7 dni (doba UTC)"]
    assert len(bars["rows"]) == 8 and bars["rows"][-1]["label"] == "24 h"
    assert bars["line"]["value"] == 1.5e8
    # EMA200: only coins near the average with enough volume
    ema_tab = next(b for b in rep["blocks"] if b["type"] == "table" and b["title"].startswith("Bliżej niż 3%"))
    assert [r[0] for r in ema_tab["rows"]] == ["BTC", "SOL"]        # TINY: low volume, DOGE: too far
    assert "Uwaga" not in by
    assert "TOTAL $2.400T" in rep["summary"]


def test_layout_from_config(tmp_path):
    now = T0 + 800 * DAY
    data, ema = make_dirs(tmp_path, now)
    cfg = {"ema_near_pct": 20, "ema_min_volume": 1e5, "liq_days": 3,
           "lines": {"oi_others_vs_btc": [[0.7, "test"]]}}
    by = blocks_by_title(report.build(data, ema, "manual", now=now, cfg=cfg))
    assert len(by["Likwidacje — ostatnie 3 dni (doba UTC)"]["rows"]) == 4
    assert [l["label"] for l in by["Lewar: OI OTHERS / OI BTC — cała historia"]["lines"]] == ["test"]
    ema_tab = next(b for t, b in by.items() if t and t.startswith("Bliżej niż 20%"))
    assert [r[0] for r in ema_tab["rows"]] == ["TINY", "BTC", "SOL", "DOGE"]


def test_oi_case_and_peaks():
    assert report.oi_case(2.0, 3.0, 1.0).startswith("nowe longi")
    assert report.oi_case(-2.0, 3.0, 1.0).startswith("nowe shorty")
    assert report.oi_case(2.0, -3.0, 1.0).startswith("zamykanie shortów")
    assert report.oi_case(-2.0, -3.0, 1.0).startswith("zamykanie longów")
    assert report.oi_case(0.5, -0.5, 1.0) == "bez wyraźnych zmian"
    pts = [[i * DAY, v] for i, v in enumerate([0.5] * 50 + [1.2] + [0.5] * 100 + [1.1, 1.1] + [0.5] * 50)]
    assert [round(v, 1) for _, v in report.local_peaks(pts, 1.0)] == [1.2, 1.1]   # plateau counted once


def test_stale_data_warning(tmp_path):
    now = T0 + 800 * DAY
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


def test_markdown_for_ai(tmp_path):
    now = T0 + 800 * DAY
    data, ema = make_dirs(tmp_path, now)
    rep = report.build(data, ema, "manual", now=now)
    md = report.to_markdown(rep, "https://x.github.io/scanner/raporty.html")
    assert md.startswith("# Raport na żądanie")
    assert f"raporty.html?id={rep['id']}" in md
    for sec in ("## Rynek", "## Alty", "## Derywaty", "## Likwidacje", "## EMA200", "## Źródła danych i metody"):
        assert sec in md
    assert "dziś na " in md and "% zakresu" in md                     # range bars as numbers
    assert "Linie poziomów: 0.600× = strefa dołków" in md             # chart levels as numbers
    assert "| Dzień (UTC) | Suma | Longi | Shorty | Udział longów |" in md
    assert "<" not in md.replace("<=", "")                            # plain text, no HTML
    out = str(tmp_path / "out")
    report.save(out, rep, md=md)
    assert open(os.path.join(out, "latest.md"), encoding="utf-8").read() == md
    assert os.path.exists(os.path.join(out, "reports", f"{rep['id']}.md"))
    assert json.load(open(os.path.join(out, "latest.json")))["id"] == rep["id"]


def test_backfill_md_for_older_reports(tmp_path):
    now = T0 + 800 * DAY
    data, ema = make_dirs(tmp_path, now)
    out = str(tmp_path / "out")
    old = report.build(data, ema, "test", now=now - 3600)
    report.save(out, old)                                            # made before the AI text existed: no .md
    assert not os.path.exists(os.path.join(out, "reports", f"{old['id']}.md"))
    new = report.build(data, ema, "manual", now=now)
    report.save(out, new, md=report.to_markdown(new), page_url="https://x/raporty.html")
    text = open(os.path.join(out, "reports", f"{old['id']}.md"), encoding="utf-8").read()
    assert text.startswith("# Raport testowy") and f"raporty.html?id={old['id']}" in text
    assert open(os.path.join(out, "latest.md"), encoding="utf-8").read().startswith("# Raport na żądanie")
