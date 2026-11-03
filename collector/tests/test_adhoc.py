"""Raporty specjalne (collector/adhoc/, poprawka 39): lista, budowa, zapis bez przycinania, wersja dla AI, bot."""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import adhoc  # noqa: E402
import bot as B  # noqa: E402
import report  # noqa: E402
from adhoc import btc_ema200 as E  # noqa: E402
from test_bot import ctx_for, msg  # noqa: E402
from test_cycle import synthetic_px  # noqa: E402
from test_special import _w, make_dirs, ts  # noqa: E402

DAY = 86400
CFG = {"cycle": {"bottoms": ["2026-06-30"]}}


def wavy_dirs(tmp_path):
    """Dane jak w test_special, ale cena faluje (±25%, okres 150 dni) → zejścia pod EMA200 w akumulacji."""
    data, ema = make_dirs(tmp_path)
    px = sorted(synthetic_px().items())
    wav = [[t, v * (1 + 0.25 * math.sin(2 * math.pi * t / (150 * DAY)))] for t, v in px]
    with open(os.path.join(data, "liq_1d.json"), encoding="utf-8") as f:
        liq = json.load(f)
    liq["series"]["px_btc"] = wav
    liq["series"]["px_btc_lo"] = [[t, v * 0.97] for t, v in wav if t >= ts(2019, 9, 12)]
    _w(os.path.join(data, "liq_1d.json"), liq)
    return data, ema


def test_catalog_reads_title_without_import():
    cat = adhoc.catalog()
    assert cat["btc_ema200"] == E.TITLE
    assert all(adhoc.NAME_RE.match(k) for k in cat)


def test_runs_and_clusters():
    cl = [10, 9, 9, 11, 9, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 9, 9]
    e = [10] * len(cl)
    runs = E.runs_below(cl, e, 0, len(cl) - 1)
    assert runs == [(0, 2), (4, 4), (16, 17)]
    assert E.clusters(runs, gap=1) == [(0, 4, 4), (16, 17, 2)]          # przerwa 1 dzień nad = jeden okres
    assert E.clusters(runs, gap=0) == [(0, 2, 3), (4, 4, 1), (16, 17, 2)]


def test_weekly_levels_use_forming_week():
    t0 = ts(2026, 1, 5)                                                  # poniedziałek
    tss = [t0 + i * DAY for i in range(7 * 25 + 3)]
    cl = [100.0] * (7 * 25) + [200.0, 200.0, 300.0]                       # bieżący tydzień: zamknięcie = 300
    s20, e21 = E.weekly_levels(tss, cl, len(tss) - 1)
    assert s20 == (19 * 100 + 300) / 20 and e21 > 100


def test_build_btc_ema200(tmp_path):
    data, ema = wavy_dirs(tmp_path)
    now = ts(2026, 10, 31, 9)
    rep = report.build(data, ema, "adhoc:btc_ema200", now=now, cfg=CFG)
    assert rep["kind"] == "adhoc" and rep["topic"] == "btc_ema200" and rep["id"].endswith("-adhoc-btc_ema200")
    assert rep["title"].startswith("Raport specjalny: ") and rep["summary"].startswith("BTC $")
    assert rep["blocks"][0]["title"] == "Dlaczego ten raport" and "EMA200" in rep["blocks"][0]["text"]
    assert rep["blocks"][1]["title"] == "Jak czytać ten raport"
    secs = [b["title"] for b in rep["blocks"] if b["type"] == "section"]
    assert secs[0] == "Teraz" and secs[-1] == "Na co patrzeć" and any(x.startswith("Poprzedni cykl") for x in secs)
    days = [b for b in rep["blocks"] if b.get("x") == "days"]
    assert len(days) == 3 and all(s["data"][0][0] == 0 for b in days for s in b["series"])
    charts = [b for b in rep["blocks"] if b["type"] == "chart"]
    assert any(b.get("markers") for b in charts) and any(b.get("bands") for b in charts)
    for b in charts:                                          # znaczniki posortowane (wymóg Lightweight Charts)
        ts_ = [m["t"] for m in b.get("markers") or []]
        assert ts_ == sorted(ts_)
    prev = next(b for b in rep["blocks"] if b["title"] == "Każde zejście pod EMA200 w poprzednim cyklu")
    assert prev["rows"] and all(len(r) == len(prev["cols"]) for r in prev["rows"])
    macro = next(b for b in rep["blocks"] if b["title"].startswith("Tło makro"))
    assert macro["rows"][-1][0] == "teraz"
    ep = next(b for b in rep["blocks"] if b["title"].startswith("Dłuższe zejścia"))
    assert ep["rows"] and all(len(r) == len(ep["cols"]) for r in ep["rows"])
    cyc = next(b for b in rep["blocks"] if b["title"].startswith("Akumulacja po dnie"))
    assert len(cyc["rows"]) >= 3 and all(len(r) == len(cyc["cols"]) for r in cyc["rows"])
    md = report.to_markdown(rep)
    assert "dzień 0:" in md and "Dlaczego ten raport" in md and "Znaczniki na wykresie" in md
    json.dumps(rep)                                                                   # da się zapisać
    data2, ema2 = make_dirs(tmp_path / "plain")                                       # gładka cena: obecny cykl nad EMA
    rep2 = report.build(data2, ema2, "adhoc:btc_ema200", now=now, cfg=CFG)
    cyc2 = next(b for b in rep2["blocks"] if b["title"].startswith("Akumulacja po dnie"))
    assert "(uznane)" in cyc2["rows"][-1][0] and "liczymy" in cyc2["rows"][-1][2]


def test_adhoc_saved_never_pruned_and_macro_off(tmp_path):
    out = str(tmp_path / "out")
    rep = {"id": "20261103-0900-adhoc-btc_ema200", "kind": "adhoc", "title": "Raport specjalny: X", "created": 100,
           "summary": "", "blocks": []}
    report.save(out, rep, keep=1, md="# x")
    for i in range(3):
        report.save(out, {"id": f"2026110{i}-0700-morning", "kind": "morning", "title": "R", "created": 200 + i,
                          "summary": "", "blocks": []}, keep=1, md="# r")
    with open(os.path.join(out, "index.json"), encoding="utf-8") as f:
        ids = [r["id"] for r in json.load(f)["reports"]]
    assert "20261103-0900-adhoc-btc_ema200" in ids and len(ids) == 2
    assert os.path.exists(os.path.join(out, "latest-adhoc.md"))
    assert report.group_of("adhoc") == "adhoc"
    assert report.macro_for("adhoc:btc_ema200", {}) is None
    assert "🔎" in report.notify_text({"id": rep["id"], "kind": "adhoc", "title": rep["title"], "created": 100}, "https://x/r.html")


def test_make_rejects_unknown_special(tmp_path):
    data, ema = make_dirs(tmp_path)
    out = str(tmp_path / "out")
    assert report.main(["make", "--kind", "adhoc:nie_ma", "--data", data, "--ema", ema, "--out", out,
                        "--made", str(tmp_path / "m.json")]) == 2


def test_bot_raport_specjalny(tmp_path):
    c = ctx_for(tmp_path, [msg("/raport_specjalny"), msg("/raport_specjalny btc_ema200"), msg("/raport_specjalny xyz"),
                           msg("/raport_specjalny btc_ema200", user="222")])
    B.poll(c)
    t = [x["text"] for x in c.api.sent]
    assert "btc_ema200" in t[0] and E.TITLE in t[0]
    assert c.gh.calls == [("report.yml", {"special": "btc_ema200"})]
    assert "w przygotowaniu" in t[1] and "Nie ma raportu specjalnego" in t[2]
    assert B.REPORT_ID.match("20261103-0900-adhoc-btc_ema200")
