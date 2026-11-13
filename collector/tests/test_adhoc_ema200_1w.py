"""Raport specjalny btc_ema200_1w (poprawka 62): świece tygodniowe, epizody „przy średniej”, podział po dnie / w bessie."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import adhoc  # noqa: E402
import report  # noqa: E402
from adhoc import btc_ema200_1w as E  # noqa: E402
from test_adhoc import CFG, wavy_dirs  # noqa: E402
from test_special import ts  # noqa: E402

DAY = 86400


def wk(c, lo, e):
    return {"c": c, "l": lo, "h": c, "e": e, "t0": 0, "t": 0}


def test_catalog_has_title():
    assert adhoc.catalog()["btc_ema200_1w"] == E.TITLE


def test_weeks_mon_sun_with_wicks():
    t0 = ts(2026, 11, 2)                                                   # poniedziałek
    tss = [t0 + i * DAY for i in range(10)]                               # pon.–nd. + pon.–śr.
    cl = [100.0 + i for i in range(10)]
    lo = {tss[3]: 90.0}
    W = E.weeks(tss, cl, {}, lo)
    assert len(W) == 2 and W[0]["t0"] == t0 and W[0]["t"] == tss[6] and W[0]["days"] == 7
    assert W[0]["l"] == 90.0 and W[0]["c"] == 106.0
    assert W[1]["o"] == 106.0 and W[1]["c"] == 109.0 and W[1]["days"] == 3


def test_episodes_end_on_close_below_or_move_away():
    e = 100.0
    W = [wk(120, 110, e), wk(120, 110, e),
         wk(105, 99, e), wk(104, 102, e), wk(110, 106, e), wk(103, 98, e),   # przy średniej (przerwa 1 tydz.)
         wk(130, 120, e), wk(130, 120, e), wk(130, 120, e),                  # odejście w górę
         wk(108, 101, e), wk(95, 90, e),                                     # zamknięcie pod → koniec
         wk(120, 110, e)]
    eps = E.find_episodes(W)
    assert eps == [(2, 5, False), (9, 10, True)]


def test_build_btc_ema200_1w(tmp_path):
    data, ema = wavy_dirs(tmp_path)
    rep = report.build(data, ema, "adhoc:btc_ema200_1w", now=ts(2026, 10, 31, 9), cfg=CFG)
    assert rep["kind"] == "adhoc" and rep["topic"] == "btc_ema200_1w"
    assert rep["title"] == "Raport specjalny: " + E.TITLE and rep["summary"].startswith("BTC $")
    assert rep["blocks"][0]["title"] == "Dlaczego ten raport" and "EMA200" in rep["blocks"][0]["text"]
    secs = [b["title"] for b in rep["blocks"] if b["type"] == "section"]
    assert secs[0] == "Teraz" and secs[-1] == "Na co patrzeć"
    assert not any(b.get("title") == "Jak czytać ten raport" for b in rep["blocks"])
    for b in rep["blocks"]:
        if b["type"] == "table":
            assert all(len(r) == len(b["cols"]) for r in b["rows"]), b["title"]
        if b["type"] == "chart":
            ts_ = [m["t"] for m in b.get("markers") or []]
            assert ts_ == sorted(ts_)
            for s in b["series"]:
                xs = [p[0] for p in s["data"]]
                assert xs == sorted(xs) and len(xs) == len(set(xs)), (b["title"], s["name"])
    wkc = next(b for b in rep["blocks"] if b["title"].startswith("BTC — świece tygodniowe"))
    c = wkc["series"][0]["ohlc"]
    assert c and all(x[2] >= max(x[1], x[4]) and x[3] <= min(x[1], x[4]) for x in c)
    a = next(b for b in rep["blocks"] if b["title"].startswith("Kiedy cena po dnie bessy"))
    b_ = next(b for b in rep["blocks"] if b["title"].startswith("Ciekawostka"))
    assert "nie analogia" in b_["title"] and a["rows"]
    rep_md = report.to_markdown(rep, "https://example.org/raporty.html")
    assert "Przeliczenie na dziś — szacunek, nie prognoza" in rep_md
