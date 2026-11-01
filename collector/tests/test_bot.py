"""Offline tests: Telegram bot, commands, schedule (Polish time), watch, routing, health."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from zoneinfo import ZoneInfo  # noqa: E402

import alerts  # noqa: E402
import bot as B  # noqa: E402
import ema_monitor as E  # noqa: E402
import report  # noqa: E402
import timetable as TT  # noqa: E402
import watchdog  # noqa: E402

PL = ZoneInfo("Europe/Warsaw")
ADMIN = "111"
GROUP = "-100500"


def pl(y, mo, d, h, mi):
    return int(datetime(y, mo, d, h, mi, tzinfo=PL).timestamp())


NOW = pl(2026, 11, 2, 12, 0)          # Monday, winter time (UTC+1)


class FakeApi:
    def __init__(self, updates=()):
        self.updates = list(updates)
        self.sent, self.menus = [], []

    def get_updates(self, offset):
        return [u for u in self.updates if u["update_id"] >= offset]

    def get_me(self):
        return {"username": "ScannerBot"}

    def set_commands(self, commands, scope):
        self.menus.append((scope["type"], [c["command"] for c in commands]))

    def send(self, chat_id, text, thread_id=None, reply_to=None):
        self.sent.append({"chat": str(chat_id), "text": text, "thread": thread_id, "reply_to": reply_to})


class FakeGH:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def dispatch(self, workflow, inputs):
        self.calls.append((workflow, dict(inputs)))
        return (True, None) if self.ok else (False, "HTTP 401 (token wygasł albo nie ma uprawnienia Actions)")


def ctx_for(tmp_path, updates=(), cfg=None, st=None, now=NOW, gh=None, data=None, prices=None):
    cfg = cfg or {"telegram": {"group_chat_id": int(GROUP), "group_thread_id": 7},
                  "fib": {"near_pct": 2, "setups": [{"coin": "ETH", "high": 3000, "low": 2000}]},
                  "reports": {"page_url": "https://x.io/raporty.html"}}
    data = data if data is not None else {
        ("data", "meta.json"): {"updated": now - 1800, "health": {"Coinalyze": "ok", "TradingView": "ok"}},
        ("reports", "index.json"): {"reports": [{"id": "r1", "title": "Raport poranny", "created": now - 3600,
                                                  "summary": "TOTAL $2.5T"}]}}
    tg = alerts.Telegram(token="", chat_id=ADMIN, enabled=False, tg_cfg=cfg.get("telegram"))
    return B.Ctx(cfg, st if st is not None else {}, now, ADMIN, FakeApi(updates), gh or FakeGH(),
                 lambda b, n: data.get((b, n)), lambda coins: dict((prices or {"SOL": 127.0}), **{}),
                 str(tmp_path), tg)


_uid = [1000]


def msg(text, user=ADMIN, chat=None, ctype="private", date=NOW, thread=None):
    _uid[0] += 1
    chat = chat or (user if ctype == "private" else GROUP)
    m = {"message_id": _uid[0], "from": {"id": int(user)}, "chat": {"id": int(chat), "type": ctype, "title": "Krypto"},
         "date": date, "text": text}
    if thread:
        m.update(message_thread_id=thread, is_topic_message=True)
    return {"update_id": _uid[0], "message": m}


# ── commands ─────────────────────────────────────────────────
def test_help_admin_vs_group_member_and_menu(tmp_path):
    c = ctx_for(tmp_path, [msg("/pomoc"), msg("/pomoc", user="222", ctype="supergroup", thread=7)])
    B.tick(c)
    admin_help, member_help = c.api.sent[0]["text"], c.api.sent[1]["text"]
    assert "/skan" in admin_help and "Administrator" in admin_help and "/status" in admin_help
    assert "/skan" not in member_help and "/status" in member_help and "/fiby" in member_help
    assert c.api.sent[1]["thread"] == 7 and c.api.sent[1]["chat"] == GROUP          # reply in the same thread
    scopes = dict(c.api.menus)
    assert "skan" in scopes["chat"] and "skan" not in scopes["all_group_chats"] and "status" in scopes["default"]
    assert c.st["tg_offset"] == _uid[0] + 1 and c.st["me"]["username"] == "ScannerBot"
    n = len(c.api.menus)
    B.sync_commands(c)
    assert len(c.api.menus) == n                                                     # menu set once (hash)


def test_permissions_and_ignored_messages(tmp_path):
    ups = [msg("/skan", user="222", ctype="supergroup"),            # member → admin command refused
           msg("/status", user="333"),                                # stranger in private → silent
           msg("/status", user="222", ctype="supergroup", chat="-999"),  # other group → silent
           msg("/status@InnyBot", user="222", ctype="supergroup"),    # command for another bot → silent
           msg("/status", date=NOW - 3 * 3600),                       # stale → silent
           msg("hej"),                                                # not a command
           msg("/cokolwiek")]                                         # unknown, admin private → hint
    c = ctx_for(tmp_path, ups)
    c.me = "ScannerBot"
    B.poll(c)
    texts = [s["text"] for s in c.api.sent]
    assert len(texts) == 2 and "tylko dla administratora" in texts[0] and "Nie znam komendy" in texts[1]
    assert c.gh.calls == []


def test_watek_works_in_unconfigured_group(tmp_path):
    cfg = {"telegram": {}}
    c = ctx_for(tmp_path, [msg("/watek@ScannerBot", ctype="supergroup", chat="-100777", thread=42),
                           msg("/status", user="222", ctype="supergroup", chat="-100777")], cfg=cfg)
    c.me = "ScannerBot"
    B.poll(c)
    assert len(c.api.sent) == 1
    t = c.api.sent[0]["text"]
    assert "-100777" in t and "<code>42</code>" in t and "config.yaml" in t


def test_status_raport_fiby(tmp_path):
    c = ctx_for(tmp_path, [msg("/status"), msg("/raport", user="222", ctype="supergroup"), msg("/fiby")])
    B.poll(c)
    st_txt, rep_txt, fib_txt = (s["text"] for s in c.api.sent)
    assert "Skany OI/TOTAL" in st_txt and "30 min temu" in st_txt and "Coinalyze ok" in st_txt
    assert "Następny skan: 12:15" in st_txt and "Następny raport: wieczorny" in st_txt and "22:05" in st_txt
    assert "raport ok. 22:50" in st_txt and "Alerty rynkowe włączone" in st_txt
    assert 'href="https://x.io/raporty.html?id=r1"' in rep_txt and "TOTAL $2.5T" in rep_txt
    assert "[c1]" in fib_txt


def test_admin_actions(tmp_path):
    ups = [msg("/fib SOL 200 100 long swing"), msg("/fiby", user="222", ctype="supergroup"), msg("/usun 1"),
           msg("/skan"), msg("/raport_teraz"), msg("/raport_teraz skan"),
           msg("/cisza 2h"), msg("/status"), msg("/cisza off"), msg("/cisza xyz")]
    c = ctx_for(tmp_path, ups)
    B.poll(c)
    t = [s["text"] for s in c.api.sent]
    assert "Dodano" in t[0] and "0.75 = $125.00" in t[0] and "SOL" in t[1] and "Usunięto" in t[2]
    assert c.gh.calls == [("oi-monitor.yml", {"mode": "run", "report": "none"}),
                          ("report.yml", {"kind": "manual"}),
                          ("oi-monitor.yml", {"mode": "run", "report": "manual"})]
    assert "wyciszone do 02.11 14:00" in t[6] and "wyciszone do" in t[7]
    assert "włączone" in t[8] and c.st["mute_until"] is None and "Składnia" in t[9]


def test_raport_teraz_weekly_monthly(tmp_path):
    c = ctx_for(tmp_path, [msg("/raport_teraz tydzień"), msg("/raport_teraz miesiac")])
    B.poll(c)
    assert c.gh.calls == [("report.yml", {"kind": "weekly"}), ("report.yml", {"kind": "monthly"})]
    assert "tygodniowy" in c.api.sent[0]["text"] and "miesięczny" in c.api.sent[1]["text"]


def test_usun_raport(tmp_path):
    c = ctx_for(tmp_path, [msg("/usun_raport https://x.io/raporty.html?id=r1"), msg("/usun_raport xyz"),
                           msg("/usun_raport 20261101-1600-monthly"), msg("/usun_raport 20261101-1600-monthly", user="222")])
    c.fetch = lambda branch, name: {"reports": [{"id": "20261101-1600-monthly", "title": "Raport miesięczny — październik 2026",
                                                 "created": 1793548800, "kind": "monthly"}]}
    B.poll(c)
    t = [x["text"] for x in c.api.sent]
    assert "Podaj ID" in t[0] and "Podaj ID" in t[1]
    assert "Usuwam z historii: Raport miesięczny — październik 2026" in t[2]
    assert c.gh.calls == [("report.yml", {"kind": "manual", "delete": "20261101-1600-monthly"})]   # nie-admin: bez akcji


def test_dispatch_failure_is_reported(tmp_path):
    c = ctx_for(tmp_path, [msg("/skan")], gh=FakeGH(ok=False))
    B.poll(c)
    assert "Nie udało się" in c.api.sent[0]["text"] and "token" in c.api.sent[0]["text"]


# ── schedule ─────────────────────────────────────────────────
def test_timetable_polish_time_skip_and_dst():
    sc = TT.load({"reports": [{"scan_at": "06:15", "kind": "morning"}, {"scan_at": "22:05", "kind": "evening"}]})
    day = datetime(2026, 11, 2).date()
    ev = TT.events_on(sc, day)
    keys = [e["key"][11:] for e in ev]
    assert "06:15 report" in keys and "22:05 report" in keys
    assert "06:15 scan" not in keys and "22:15 scan" not in keys and "20:15 scan" in keys and "00:15 scan" in keys
    morning = next(e for e in ev if e["kind"] == "morning")
    assert datetime.fromtimestamp(morning["at"].timestamp(), timezone.utc).hour == 5          # winter: 06:15 PL = 05:15 UTC
    summer = next(e for e in TT.events_on(sc, datetime(2026, 7, 1).date()) if e["kind"] == "morning")
    assert datetime.fromtimestamp(summer["at"].timestamp(), timezone.utc).hour == 4           # summer: 04:15 UTC
    done = {}
    assert TT.due(sc, pl(2026, 11, 2, 6, 14), done) == []
    d = TT.due(sc, pl(2026, 11, 2, 6, 16), done)
    assert [(e["type"], e["kind"]) for e in d] == [("report", "morning")]
    done[d[0]["key"]] = {"at": 0}
    assert TT.due(sc, pl(2026, 11, 2, 6, 17), done) == []
    assert [e["key"][11:] for e in TT.due(sc, pl(2026, 11, 2, 8, 20), {})] == ["08:15 scan"]
    late = TT.due(sc, pl(2026, 11, 2, 7, 30), {})                                  # Pi was off: report up to 90 min late
    assert [e["kind"] for e in late] == ["morning"]
    assert TT.due(sc, pl(2026, 11, 2, 7, 50), {}) == []
    assert TT.due(sc, pl(2026, 11, 2, 8, 30), {}) == []                            # regular 08:15 only 10 min grace
    nxt = TT.upcoming(sc, pl(2026, 11, 2, 23, 0), 2)
    assert [e["key"][11:] for e in nxt] == ["00:15 scan", "02:15 scan"]


def test_timetable_evening_in_new_york_time():
    sc = TT.load({"reports": [{"scan_at": "06:15", "kind": "morning"},
                              {"scan_at": "16:05", "timezone": "America/New_York", "kind": "evening"}]})
    def evening(y, m, d):
        e = [x for x in TT.events_on(sc, datetime(y, m, d).date()) if x["kind"] == "evening"]
        assert len(e) == 1
        return e[0]["key"][11:16]
    assert evening(2026, 11, 2) == "22:05"          # both on winter time
    assert evening(2026, 7, 1) == "22:05"           # both on summer time
    assert evening(2026, 10, 31) == "21:05"         # Poland already on winter time, US still on summer time
    assert evening(2027, 3, 16) == "21:05"          # US already on summer time, Poland not yet
    keys = [e["key"][11:] for e in TT.events_on(sc, datetime(2026, 10, 31).date())]
    assert "20:15 scan" not in keys and "22:15 scan" in keys      # regular scan near 21:05 skipped, 22:15 kept
    assert [e["kind"] for e in TT.due(sc, pl(2026, 10, 31, 21, 6), {})] == ["evening"]


def test_schedule_tick_dispatch_retry_and_pending(tmp_path):
    c = ctx_for(tmp_path, now=pl(2026, 11, 2, 6, 16), gh=FakeGH(ok=False))
    assert B.schedule_tick(c) == []
    msgs = B.report_health(c)
    assert msgs and "Uruchamianie skanów" in msgs[0]
    c2 = ctx_for(tmp_path, now=pl(2026, 11, 2, 6, 17), st=c.st)                     # next minute: retry works
    assert len(B.schedule_tick(c2)) == 1
    assert c2.gh.calls == [("oi-monitor.yml", {"mode": "run", "report": "morning"})]
    assert c2.st["pending_reports"][0]["kind"] == "morning"
    assert "znowu działa" in B.report_health(c2)[0]
    c3 = ctx_for(tmp_path, now=pl(2026, 11, 2, 6, 18), st=c2.st)
    assert B.schedule_tick(c3) == [] and c3.gh.calls == []                          # started once


def test_watch_stale_data_and_missing_report(tmp_path):
    t0 = pl(2026, 11, 2, 6, 17)
    st = {"pending_reports": [{"key": "k", "kind": "morning", "at": t0}]}
    data = {("data", "meta.json"): {"updated": t0 - 5 * 3600}, ("reports", "index.json"): {"reports": []}}
    c = ctx_for(tmp_path, st=st, now=t0 + 30 * 60, data=data)
    assert B.watch_tick(c) == [] and len(c.st["pending_reports"]) == 1
    assert "Skany OI/TOTAL" in B.report_health(c)[0]
    c2 = ctx_for(tmp_path, st=c.st, now=t0 + 80 * 60, data=data)
    out = B.watch_tick(c2)
    assert out and "nie powstał" in out[0] and c2.st["pending_reports"] == []
    # report present → pending cleared silently
    st3 = {"pending_reports": [{"key": "k", "kind": "evening", "at": t0}]}
    data3 = {("data", "meta.json"): {"updated": t0}, ("reports", "index.json"): {"reports": [{"created": t0 + 2500}]}}
    c3 = ctx_for(tmp_path, st=st3, now=t0 + 50 * 60, data=data3)
    assert B.watch_tick(c3) == [] and c3.st["pending_reports"] == []


def test_migrate_from_old_state(tmp_path):
    with open(tmp_path / "state.json", "w") as f:
        json.dump({"fib_user": [{"id": "1", "coin": "SOL"}], "tg_offset": 55, "other": 1}, f)
    assert B.migrate(str(tmp_path)) == {"fib_user": [{"id": "1", "coin": "SOL"}], "tg_offset": 55}


# ── routing, mute, health ────────────────────────────────────
def test_telegram_routing():
    tg = alerts.Telegram(token="", chat_id=ADMIN, enabled=False, tg_cfg={"group_chat_id": -100500, "group_thread_id": 7})
    assert tg.target("market") == ("-100500", 7) and tg.target("report") == ("-100500", 7)
    assert tg.target("system") == (ADMIN, None)
    tg.post("market", "x")
    assert tg.sent_to[0][:3] == ("market", "-100500", 7)
    solo = alerts.Telegram(token="", chat_id=ADMIN, enabled=False, tg_cfg={"group_chat_id": None})
    assert solo.target("market") == (ADMIN, None)
    assert alerts.is_muted(NOW + 10, NOW) and not alerts.is_muted(NOW - 10, NOW) and not alerts.is_muted(None, NOW)


def test_ema_near_alert_cooldown():
    c = dict(E.DEFAULTS)
    c.update({"alerts": [{"coins": ["AAA"], "cross": False, "near_pct": 2}], "page_url": "", "near_cooldown_hours": 24})
    rows = lambda d: [{"s": "AAA", "d": d, "p": 1.0, "e": 1.0, "c": 1.0, "side": 1 if d >= 0 else -1}]  # noqa: E731
    st = {}
    E.check_alerts(rows(-5), c["alerts"], st, c, NOW, False)
    assert len(E.check_alerts(rows(-1.5), c["alerts"], st, c, NOW + 300, False)) == 1
    E.check_alerts(rows(-4), c["alerts"], st, c, NOW + 600, False)                   # moved away (re-armed)
    assert E.check_alerts(rows(-1.8), c["alerts"], st, c, NOW + 900, False) == []   # but within 24 h: silent
    E.check_alerts(rows(-4), c["alerts"], st, c, NOW + 25 * 3600, False)
    assert len(E.check_alerts(rows(-1.8), c["alerts"], st, c, NOW + 25 * 3600 + 300, False)) == 1


class _TG:
    def __init__(self):
        self.out = []

    def post(self, kind, text):
        self.out.append((kind, text))


def test_pi_health_after_three_failures_and_recovery(tmp_path):
    cfg, tg, src = {"telegram": {}}, _TG(), "Binance (Orange Pi)"
    for i in range(2):
        assert E.report_health(str(tmp_path), {src: "timeout"}, cfg, now=NOW + i * 300, telegram=tg) == []
    m = E.report_health(str(tmp_path), {src: "timeout"}, cfg, now=NOW + 600, telegram=tg)
    assert len(m) == 1 and "nie działa" in m[0] and tg.out[0][0] == "system"
    assert E.report_health(str(tmp_path), {src: "timeout"}, cfg, now=NOW + 900, telegram=tg) == []
    m = E.report_health(str(tmp_path), {src: None}, cfg, now=NOW + 1200, telegram=tg)
    assert "znowu działa" in m[0]


def test_watchdog():
    now = NOW
    fresh = {("ema", "ema.json"): {"updated": now - 600}, ("data", "meta.json"): {"updated": now - 3600}}
    assert watchdog.check(lambda b, n: fresh.get((b, n)), now) == []
    stale = {("ema", "ema.json"): {"updated": now - 3 * 3600}, ("data", "meta.json"): {"updated": now - 6 * 3600}}
    out = watchdog.check(lambda b, n: stale.get((b, n)), now)
    assert len(out) == 2 and "Orange Pi" in out[0] and "skany OI" in out[1]
    assert len(watchdog.check(lambda b, n: None, now)) == 2


def test_report_kinds():
    assert "zamknięcie dnia" in report.KIND_TITLES["morning"] and "krypto dziś" in report.KIND_TITLES["evening"]
    rep = report.build("/nonexistent", "/nonexistent", "evening", now=NOW)
    assert rep["id"].endswith("-evening") and not any(b["title"] == "O tym raporcie" for b in rep["blocks"])


def test_registry_names_are_valid_telegram_commands():
    import re
    names = [c.name for c in B.COMMANDS]
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"[a-z0-9_]{1,32}", n) for n in names)
    assert all(1 <= len(c.desc) <= 256 for c in B.COMMANDS)
