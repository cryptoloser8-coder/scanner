"""Offline tests for collector/econ.py (fake TradingView calendar)."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import econ  # noqa: E402
import report  # noqa: E402


def ts(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


EVENTS = [  # Friday 30.10.2026 (US on summer time: 8:30 ET = 12:30 UTC = 13:30 PL)
    {"title": "Core PCE Price Index MoM", "country": "US", "date": "2026-10-30T12:30:00.000Z", "importance": 1,
     "actual": 0.3, "forecast": 0.2, "previous": 0.2, "unit": "%", "period": "Sep"},
    {"title": "Personal Income MoM", "country": "US", "date": "2026-10-30T12:30:00.000Z", "importance": 0,
     "actual": 0.4, "forecast": 0.4, "previous": 0.3, "unit": "%"},
    {"title": "Chicago PMI", "country": "US", "date": "2026-10-30T13:45:00.000Z", "importance": 0,
     "actual": 45.2, "forecast": 46.0, "previous": 46.6, "unit": ""},
    {"title": "Baker Hughes Oil Rig Count", "country": "US", "date": "2026-10-30T17:00:00.000Z", "importance": -1,
     "actual": 480, "forecast": None, "previous": 482},
    {"title": "Non Farm Payrolls", "country": "US", "date": "2026-10-02T12:30:00.000Z", "importance": 1,
     "actual": 254, "forecast": 150, "previous": 159, "scale": "K"},
    {"title": "Fed Chair Speech", "country": "US", "date": "2026-10-29T18:30:00Z", "importance": 1},
    {"title": "ECB Rate Decision", "country": "EU", "date": "2026-10-30T12:15:00.000Z", "importance": 1, "actual": 2.0},
    {"title": "ISM Manufacturing PMI", "country": "US", "date": "2026-11-02T15:00:00.000Z", "importance": 1,
     "forecast": 49.5, "previous": 49.1, "period": "Oct"},
    {"title": "Construction Spending MoM", "country": "US", "date": "2026-11-02T15:00:00.000Z", "importance": 0,
     "forecast": 0.1, "previous": -0.2, "unit": "%"},
    {"title": "JOLTs Job Openings", "country": "US", "date": "2026-11-03T15:00:00.000Z", "importance": 1,
     "forecast": 7.2, "previous": 7.1, "scale": "M"},
]


def test_last_day_evening_morning_monday():
    day, evs = econ.last_day(EVENTS, ts(2026, 10, 30, 21, 45))            # evening report Friday
    assert str(day) == "2026-10-30"
    assert [e["title"] for e in evs] == ["Core PCE Price Index MoM", "Personal Income MoM", "Chicago PMI"]  # no low, no EU
    day2, evs2 = econ.last_day(EVENTS, ts(2026, 10, 31, 6, 0))              # Saturday morning: reminder of Friday
    assert str(day2) == "2026-10-30" and len(evs2) == 3
    day3, _ = econ.last_day(EVENTS, ts(2026, 11, 2, 6, 0))                  # Monday morning: Friday, not the future ISM
    assert str(day3) == "2026-10-30"
    day4, evs4 = econ.last_day(EVENTS, ts(2026, 10, 30, 6, 0))              # Friday morning: Thursday (speech)
    assert str(day4) == "2026-10-29" and evs4[0]["title"] == "Fed Chair Speech"
    _, only_high = econ.last_day(EVENTS, ts(2026, 10, 30, 21, 45), {"econ": {"min_importance": "high"}})
    assert [e["title"] for e in only_high] == ["Core PCE Price Index MoM"]


def test_block_rows_and_formats():
    blocks = econ.block(EVENTS, ts(2026, 10, 30, 21, 45))
    assert blocks[0] == {"type": "section", "title": "Dane makro z USA"}
    tab = blocks[1]
    assert tab["title"] == "Publikacje z USA — dziś, 30.10.2026"
    assert tab["rows"][0] == ["13:30", "Core PCE Price Index MoM (Sep)", "★★★", "0.3%", "0.2%", "0.2%", "+0.1 pp"]
    assert tab["rows"][2][3:] == ["45.2", "46", "46.6", "-0.8"]
    morning = econ.block(EVENTS, ts(2026, 10, 31, 6, 0))[1]
    assert morning["title"] == "Publikacje z USA — wczoraj, 30.10.2026"
    monday = econ.block(EVENTS, ts(2026, 11, 2, 6, 0))[1]
    assert monday["title"] == "Publikacje z USA — piątek, 30.10.2026"
    assert econ.fmt_num(254, {"scale": "K"}) == "254K" and econ.fmt_num(None, {}) == "—"
    assert econ.diff_text({"actual": 254, "forecast": 150, "scale": "K"}) == "+104K"


def test_block_error_and_empty():
    err = econ.block([], ts(2026, 10, 30, 21, 45), error="HTTP 403")
    assert err[1]["type"] == "text" and "HTTP 403" in err[1]["text"]
    empty = econ.block([], ts(2026, 10, 30, 21, 45))
    assert "Brak publikacji" in empty[1]["text"]


class FakeResp:
    def __init__(self, data, code=200):
        self.data, self.code = data, code

    def raise_for_status(self):
        if self.code >= 400:
            raise RuntimeError(f"HTTP {self.code}")

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return self.resp


def test_fetch_params_headers_and_errors():
    s = FakeSession(FakeResp({"status": "ok", "result": EVENTS}))
    assert econ.fetch(ts(2026, 10, 30, 21, 45), session=s) == EVENTS
    url, params, headers = s.calls[0]
    assert url == econ.URL and params["countries"] == "US" and params["from"] == "2026-10-25T21:45:00.000Z"
    assert params["to"] == "2026-11-04T21:45:00.000Z"
    assert headers["Origin"] == "https://www.tradingview.com"
    for bad in (FakeResp({"status": "error", "errmsg": "x"}), FakeResp({}, 403)):
        try:
            econ.fetch(ts(2026, 10, 30, 21, 45), session=FakeSession(bad))
            assert False, "should raise"
        except Exception:  # noqa: BLE001
            pass


def test_report_with_macro_section(tmp_path):
    rep = report.build(str(tmp_path / "nic"), str(tmp_path / "nic2"), "manual", now=int(ts(2026, 10, 30, 21, 45)),
                       macro={"events": EVENTS, "error": None})
    titles = [b.get("title") for b in rep["blocks"]]
    assert "Dane makro z USA" in titles
    md = report.to_markdown(rep)
    assert "| 13:30 | Core PCE Price Index MoM (Sep) | ★★★ | 0.3% | 0.2% | 0.2% | +0.1 pp |" in md
    assert "kalendarz ekonomiczny TradingView" in md


def test_short_error():
    class R:
        status_code = 403
    class E(Exception):
        response = R()
    assert econ.short_error(E("x")) == "HTTP 403"
    assert econ.short_error(ConnectionError("Tunnel connection failed")) == "brak połączenia"
    assert econ.short_error(ValueError("status error")) == "status error"


def test_next_day_plan():
    day, evs = econ.next_day(EVENTS, ts(2026, 10, 30, 21, 45))              # Friday evening → Monday
    assert str(day) == "2026-11-02" and [e["title"] for e in evs] == ["ISM Manufacturing PMI", "Construction Spending MoM"]
    plan = econ.block(EVENTS, ts(2026, 10, 30, 21, 45))[2]
    assert plan["title"] == "Zaplanowane — poniedziałek, 02.11.2026"
    assert plan["rows"][0] == ["16:00", "ISM Manufacturing PMI (Oct)", "★★★", "49.5", "49.1"]
    morning = econ.block(EVENTS, ts(2026, 11, 2, 6, 0))                     # Monday morning: Friday + today
    assert morning[1]["title"].startswith("Publikacje z USA — piątek") and morning[2]["title"] == "Zaplanowane — dziś, 02.11.2026"
    evening = econ.block(EVENTS, ts(2026, 11, 2, 21, 45))                   # Monday evening: today + tomorrow
    assert evening[1]["title"] == "Publikacje z USA — dziś, 02.11.2026"
    assert evening[2]["title"] == "Zaplanowane — jutro, 03.11.2026" and evening[2]["rows"][0][3] == "7.2M"
    none = econ.block(EVENTS, ts(2026, 11, 3, 21, 45))
    assert none[2]["type"] == "text" and "Brak zaplanowanych" in none[2]["text"]
