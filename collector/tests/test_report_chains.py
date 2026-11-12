"""Offline: sekcja „Sieci” w raporcie porannym i linia w powiadomieniu (poprawka 49)."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import report  # noqa: E402

DAY = 86400
NOW = int(datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc).timestamp())


def chains_json(day="2026-11-11", rising=None, new_today=None, revisions=None):
    m = lambda v, extra=None: dict({"v": v, "s7": v * 7, "c7": -5.0, "c30": 10.0, "rank2y": 40.0,  # noqa: E731
                                    "min2y": ["2025-04-01", v], "max2y": ["2025-01-10", v * 20], "first": "2018-11-01"},
                                   **(extra or {}))
    return {"updated": NOW - 1800, "day": day, "candidates": 66,
            "chains": [{"name": "Solana", "slug": "solana", "coin": "SOL",
                        "m": {"stable": m(14e9), "dex": m(1.3e9, {"rank2y": 0.0}), "fees": m(8e6), "tvl": m(5e9)}},
                       {"name": "Ethereum", "slug": "ethereum", "coin": "ETH",
                        "m": {"stable": m(134e9), "dex": m(1.5e9), "fees": m(9e6), "tvl": m(40e9)}},
                       {"name": "Robinhood Chain", "slug": "robinhood",
                        "m": {"stable": m(1e9), "dex": m(6e8, {"first": "2026-06-10"})}}],
            "share": {"total": 290e9, "rows": [["Ethereum", 46.2], ["Solana", 4.8], ["Robinhood Chain", 0.4]], "rest": 48.6},
            "market": {"dex": {"s7": 48e9, "c7": -20.0}, "stable": {"v": 291e9, "c30": -4.0}},
            "rules": dict({"cand_min": 2e7, "dex_ratio": 3.0, "dex7_min": 1e7, "stable30": 100,
                                           "stable_min": 2e7, "new_days": 35, "new_dex7": 1e7, "new_stable": 2e7}),
            "rising": rising or [], "rising_all": len(rising or []), "new_today": new_today or [],
            "revisions": revisions or []}


DAY0 = NOW - NOW % DAY - DAY


def dex_series():
    flat = lambda base, n, last=None: [[DAY0 - k * DAY, (last if last is not None and k < 7 else base)]  # noqa: E731
                                       for k in range(n, -1, -1)]
    return {"ch_solana_dex": flat(5e8, 900, 1e8),                  # ostatni tydzień najniżej
            "ch_ethereum_dex": [[DAY0 - k * DAY, 1e9 + ((k + 25) % 50) * 1e7] for k in range(900, -1, -1)],
            "ch_robinhood_dex": flat(6e8, 154)}                    # dane od 10.06.2026


class D:
    def __init__(self, ch, series=None):
        self.chains = ch
        self.chains_series = dex_series() if series is None else series
        self.meta = {"cycle_marks": {"events": [{"t": 1759708800, "kind": "top"}, {"t": 1782777600, "kind": "bottom"}]}}


ARC = {"name": "Arc", "kinds": ["stable"], "strength": 1.5, "first_data": "2026-07-02", "age_days": 133, "dex7": 1.2e8,
       "dex_ratio": 0.8, "dex_rel": 0.85, "market_ratio": 0.94, "stable": 1.32e9, "stable30": 155.8,
       "since": "2026-10-27", "day_n": 16, "new": False}
THOR = {"name": "THORChain", "kinds": ["dex"], "strength": 1.3, "first_data": "2021-04-01", "age_days": 2000,
        "dex7": 1.63e9, "dex_ratio": 3.73, "dex_rel": 3.97, "market_ratio": 0.94, "stable": None, "stable30": None,
        "since": "2026-11-11", "day_n": 1, "new": True}


def test_section_table_ranges_and_rising():
    b = report.chains_section(D(chains_json(rising=[ARC, THOR], new_today=["THORChain"])), NOW)
    assert [x["type"] for x in b] == ["section", "table", "ranges", "table"]
    t = b[1]
    assert t["title"].startswith("Sieci — doba 11.11") and t["rows"][0][0] == "Wszystkie sieci"
    assert t["rows"][0][1] == report.fmt_usd_short(290e9)                    # ta sama suma co „Udział”
    assert [r[0] for r in t["rows"][1:]] == ["Ethereum", "Solana", "Robinhood Chain"]   # wg stablecoinów
    assert t["rows"][1][3] == "46.2%" and t["rows"][3][6] == report.fmt_usd_short(None)  # brak opłat → —
    rg = {i["label"]: i for i in b[2]["items"]}
    assert rg["Solana"]["sub"] == "najniżej w 2 latach" and rg["Ethereum"]["sub"].startswith("wyżej niż w")
    assert rg["Robinhood Chain"]["note"].startswith("Dane od 10.06.2026") and rg["Ethereum"]["note"] == ""
    kinds = {k: [m.get("kind") for m in v["marks"]] for k, v in rg.items()}
    assert kinds["Ethereum"] == ["best", "worst", None, "top", "bottom"]
    assert kinds["Robinhood Chain"] == ["best", "worst", None]        # dno BTC przed startem sieci → bez kreski
    assert [x["type"] for x in report.chains_section(D(chains_json(), series={}), NOW)] == ["section", "table", "text"]
    rows = {r[0]: r for r in b[3]["rows"]}
    assert rows["Arc"][4] == "dzień 16 (od 27.10)" and "stablecoiny ▲+155.8%" in rows["Arc"][2]
    assert rows["THORChain"][4] == "nowa (od 11.11)" and "×3.7 zwykłego tygodnia; cały rynek ×0.94" in rows["THORChain"][2]
    assert "Sprawdzamy 66 sieci" in b[3]["note"]


def test_no_rising_and_stale_and_empty():
    b = report.chains_section(D(chains_json()), NOW)
    assert b[-1]["type"] == "text" and b[-1]["text"].startswith("Dziś żadna sieć")
    stale = report.chains_section(D(chains_json(day="2026-11-08")), NOW)
    assert len(stale) == 2 and "nieświeże" in stale[1]["text"] and "08.11" in stale[1]["text"]
    assert report.chains_section(D({}), NOW) == [] and report.chains_section(object(), NOW) == []


def test_revisions_note():
    rev = [{"day": "2026-11-10", "sid": "ch_ton_fees", "diff_pct": -12.5}, {"day": "2026-11-10", "sid": "ch_eth_dex", "diff_pct": 0.4},
           {"day": "2026-11-09", "sid": "ch_eth_dex", "diff_pct": 50.0}]
    b = report.chains_section(D(chains_json(revisions=rev)), NOW)
    assert "(10.11) DefiLlama poprawiła potem najwyżej o: DEX 0.4%, opłaty 12.5%." in b[1]["note"]


def test_alert_line_only_for_new_and_fresh(tmp_path):
    assert report.chains_alert(D(chains_json(new_today=["THORChain"])), NOW) == "Nowa sieć rośnie: THORChain"
    assert report.chains_alert(D(chains_json(new_today=["A", "B"])), NOW) == "Nowe sieci rosną: A, B"
    assert report.chains_alert(D(chains_json(new_today=["A"], day="2026-11-01")), NOW) == ""
    assert report.chains_alert(D(chains_json()), NOW) == ""
    entry = {"id": "x", "kind": "morning", "title": "Zamknięcie dnia", "created": NOW, "summary": "s", "alert": "Nowa sieć rośnie: X"}
    assert "🆕 Nowa sieć rośnie: X" in report.notify_text(entry, "https://p/raporty.html")
    assert "🆕" not in report.notify_text(dict(entry, alert=""), "https://p/raporty.html")
    rep = {"id": "20261112-0700-morning", "kind": "morning", "title": "T", "created": NOW, "summary": "s",
           "alert": "Nowa sieć rośnie: X", "blocks": []}
    report.save(str(tmp_path), rep)
    idx = report._read(str(tmp_path / "index.json"), {})
    assert idx["reports"][0]["alert"] == "Nowa sieć rośnie: X"
    rep.pop("alert")
    rep["id"] = "20261113-0700-morning"
    report.save(str(tmp_path), rep)
    assert "alert" not in report._read(str(tmp_path / "index.json"), {})["reports"][0]


def test_markdown_has_section():
    rep = {"id": "x", "kind": "morning", "title": "T", "created": NOW, "summary": "",
           "blocks": report.chains_section(D(chains_json(rising=[ARC])), NOW)}
    md = report.to_markdown(rep, "")
    assert "## Sieci — gdzie jest kapitał i ruch" in md and "| Ethereum |" in md and "**Solana**" in md and "| Arc |" in md


def test_dex_weeks_and_marks():
    day = NOW - NOW % DAY - DAY
    pts = [[day - k * DAY, (1e8 if k > 100 else 3e8) * (5 if 400 <= k < 407 else 1)] for k in range(800, -1, -1)]
    wk = report.dex_weeks(pts, day)
    assert wk[0][0] == day - 730 * DAY and wk[-1] == (day, 21e8)
    short = report.dex_weeks(pts[-60:], day)                      # krótka historia: pierwsze 30 dni pominięte
    assert short[0][0] == day - 59 * DAY + 30 * DAY
    lo, hi = min(w for _, w in wk), max(w for _, w in wk)
    top, bottom = day - 200 * DAY, day - 50 * DAY
    ev = [{"t": top + 3600, "kind": "top"}, {"t": bottom, "kind": "bottom"}, {"t": day - 900 * DAY, "kind": "top"}]
    m = report.dex_marks(wk, day, ev, report.log_pos(lo, hi))
    kinds = [x.get("kind") for x in m]
    assert kinds == ["best", "worst", None, "top", "bottom"]       # zdarzenie sprzed okna pominięte
    assert m[0]["pos"] == 100.0 and m[0]["label"].endswith(": $3.50B") and m[1]["pos"] == 0.0
    assert m[3]["label"].startswith("szczyt BTC") and m[4]["label"].endswith(": $2.10B")
    assert report.dex_marks(short[:10], day, ev, report.log_pos(1, 2)) == []
    p = report.log_pos(10, 1000)
    assert (p(10), p(100), p(1000), p(5), p(5000)) == (0.0, 50.0, 100.0, 0.0, 100.0)
    assert report.log_pos(0, 10)(5) == 50.0                     # zero w danych → skala liniowa


def test_all_time_note():
    day = NOW - NOW % DAY - DAY
    pts = [[day - k * DAY, 9e8 if 1000 <= k < 1007 else 1e8] for k in range(1200, -1, -1)]
    note = report.all_time_note(pts, day, 7e8)
    assert note.startswith("Najlepszy tydzień w całej historii") and "9.0× więcej" in note
    assert report.all_time_note(pts, day, 7e9) == ""
