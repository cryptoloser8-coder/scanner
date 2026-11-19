"""Offline tests, poprawka 115: bezpieczne wczytanie config.yaml, zapis stanu od razu, dziennik alertów,
polski zapis liczb w alertach Telegrama."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import alert_log as AL  # noqa: E402
import alerts  # noqa: E402
import bot as B  # noqa: E402
import ema_monitor as E  # noqa: E402
import fib as F  # noqa: E402
import lamps as LP  # noqa: E402
import main  # noqa: E402
import safe_config as SC  # noqa: E402
import series as S  # noqa: E402
from store import Store  # noqa: E402
from test_bot import FakeGH, ctx_for, msg  # noqa: E402
from test_ema import NOW as ENOW, FakeBinance, FakeTG, cfg as ema_cfg  # noqa: E402

D, H = 86400, 3600
GOOD = "telegram:\n  enabled: true\nwatchlist: [SOL]\nschedule:\n  scan_every_hours: 2\n"
BAD = "telegram:\n  enabled: true\n watchlist: [SOL\n"


# ── config.yaml: ostatnia dobra wersja ───────────────────────
def test_config_error_falls_back_to_last_good_and_tells_admin_once(tmp_path):
    p, st, sent = tmp_path / "config.yaml", str(tmp_path / "stan"), []
    p.write_text(GOOD, encoding="utf-8")
    assert SC.load(str(p), st, notify=sent.append, now=1000)["watchlist"] == ["SOL"] and sent == []
    assert os.path.exists(os.path.join(st, SC.GOOD_NAME))
    p.write_text(BAD, encoding="utf-8")
    cfg = SC.load(str(p), st, notify=sent.append, now=2000)
    assert cfg["watchlist"] == ["SOL"]                                   # pracuje na ostatniej dobrej wersji
    assert len(sent) == 1 and "config.yaml ma błąd" in sent[0] and "linii" in sent[0] and "ostatniej dobrej wersji" in sent[0]
    SC.load(str(p), st, notify=sent.append, now=2060)                    # bot co minutę — bez powtórek
    assert len(sent) == 1
    SC.load(str(p), st, notify=sent.append, now=2000 + SC.REMIND_S)      # przypomnienie po 12 h
    assert len(sent) == 2 and "nadal ma błąd" in sent[1]
    p.write_text(GOOD.replace("SOL", "SOL, XRP"), encoding="utf-8")
    assert SC.load(str(p), st, notify=sent.append, now=90000)["watchlist"] == ["SOL", "XRP"]
    assert len(sent) == 3 and "znowu poprawny" in sent[2]
    SC.load(str(p), st, notify=sent.append, now=90060)
    assert len(sent) == 3


def test_config_error_without_good_copy_raises_but_notifies(tmp_path):
    p, sent = tmp_path / "config.yaml", []
    p.write_text(BAD, encoding="utf-8")
    with pytest.raises(SC.ConfigError):
        SC.load(str(p), str(tmp_path / "stan"), notify=sent.append, now=1)
    assert len(sent) == 1 and "stoją" in sent[0]


def test_config_wrong_shape_is_an_error():
    assert SC.parse("")[1] and SC.parse("- a\n- b\n")[1]
    assert "telegram" in SC.parse("telegram: [1, 2]\n")[1]
    assert "watchlist" in SC.parse("watchlist: SOL\n")[1]
    assert SC.parse(GOOD)[1] is None


def test_bot_and_ema_use_safe_config(tmp_path):
    p, st = tmp_path / "config.yaml", str(tmp_path / "stan")
    p.write_text(GOOD + "ema:\n  period: 200\n", encoding="utf-8")
    assert B.load_config(str(p), st)["watchlist"] == ["SOL"]
    assert E.load_cfg(str(p), st)["period"] == 200
    p.write_text(BAD, encoding="utf-8")
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)                           # wiadomość nie wychodzi (brak tokenu) — nie szkodzi
    assert B.load_config(str(p), st)["watchlist"] == ["SOL"]
    assert E.load_cfg(str(p), st)["period"] == 200
    with pytest.raises(Exception):
        E.load_cfg(str(p))                                               # bez folderu stanu (testy, GitHub) — jak dawniej


# ── bot: stan na dysk od razu ────────────────────────────────
def test_bot_saves_state_right_after_command_and_scan(tmp_path):
    cfg = {"telegram": {}, "schedule": {"scan_every_hours": 2, "scan_minute": 0}}
    c = ctx_for(tmp_path, updates=[msg("/skan")], cfg=cfg, gh=FakeGH())
    snaps = []

    def boom(branch, name):
        raise RuntimeError("sieć padła po uruchomieniu skanu")
    c.fetch = boom
    with pytest.raises(RuntimeError):
        B.tick(c, lambda: snaps.append(json.loads(json.dumps(c.st))))
    assert snaps and snaps[0]["tg_offset"] > 0                          # komenda zapamiętana zaraz po obsłudze
    assert [w for w, _ in c.gh.calls].count("oi-monitor.yml") >= 1
    # następna minuta ze stanem z dysku: /skan nie rusza drugi raz
    c2 = ctx_for(tmp_path, updates=c.api.updates, cfg=cfg, st=snaps[-1], gh=FakeGH())
    B.poll(c2)
    assert c2.gh.calls == []


def test_bot_tick_without_save_still_works(tmp_path):
    c = ctx_for(tmp_path, updates=[msg("/status")])
    B.tick(c)
    assert c.api.sent and "Status systemu" in c.api.sent[0]["text"]


# ── dziennik alertów: moduł ──────────────────────────────────
def test_alert_log_add_update_missing_prune():
    log = AL.empty("github")
    ev = [AL.event("level", '🚨 <b>TOTAL3</b> $1.05T przebił poziom w górę ⬆️ <a href="x">w</a>', sid="total3", v=1.05e12, key="k"),
          AL.event("liq", "💥 <b>Likwidacje SOL</b>", sid="liq_sol", v=5e8, coin="SOL", px=150.0)]
    assert AL.add(log, ev, 1000, {"btc": 100000, "alt": 50, "eth": None}, fmt=alerts.pl_text) == 2
    a, b = log["alerts"]
    assert a["id"] == "g1000-0" and b["id"] == "g1000-1" and a["text"].startswith("🚨 TOTAL3 $1,05T") and "<" not in a["text"]
    assert a["ref"] == {"btc": 100000.0, "alt": 50.0} and a["out"] == {} and "muted" not in a
    assert AL.due(log, 1000 + 7 * D - 1, [7, 30]) == []
    px = {"total3": 1.26e12, "sol": 120.0}

    def lookup(e, t):
        return {"v": px["total3"] if e["sid"] == "total3" else None, "px": px["sol"] if e.get("coin") else None,
                "ref": {"btc": 110000, "alt": 40, "eth": 3000}}
    assert AL.update(log, 1000 + 7 * D, [7, 30], lookup) == 2
    assert a["out"]["7"]["v_pct"] == 20.0 and a["out"]["7"]["ref_pct"] == {"btc": 10.0, "alt": -20.0}     # eth: brak na starcie
    assert b["out"]["7"]["px_pct"] == -20.0 and "v" not in b["out"]["7"] and "30" not in a["out"]
    assert AL.update(log, 1000 + 8 * D, [7, 30], lookup) == 0                                              # raz
    # brak danych: czekamy 3 dni, potem „missing”
    assert AL.update(log, 1000 + 30 * D, [7, 30], lambda e, t: None) == 0
    assert AL.update(log, 1000 + 33 * D + 1, [7, 30], lambda e, t: None) == 2 and a["out"]["30"] == {"t": 1000 + 30 * D, "missing": True}
    AL.add(log, [AL.event("fib", "x")], 2000, None, muted=True)
    assert log["alerts"][-1]["muted"] is True and "ref" not in log["alerts"][-1]
    AL.prune(log, 1000 + 900 * D, 800, 5000)
    assert log["alerts"] == []
    assert AL.settings({"alert_log": {"horizons_days": [30, "x"]}})["horizons_days"] == [7, 30]
    assert AL.settings({"alert_log": {"horizons_days": [1, 7], "enabled": False}}) == dict(AL.DEFAULTS, horizons_days=[1, 7], enabled=False)
    assert AL.at_day([[0, 1.0], [D, 2.0], [2 * D, 3.0]], D + 5) == 2.0 and AL.at_day([[0, 1.0]], 10 * D) is None


def test_check_functions_report_events(tmp_path):
    st_ = Store(str(tmp_path))
    now = 1_790_000_000
    st_.put("1h", "oi_others", {now - 24 * H: 100.0, now: 115.0})
    st_.put("1h", "total3", {now: 1.0e12})
    t = now - now % H
    st_.put("1h", "liq_btc_long", {t - k * H: 3e8 for k in range(6)})
    st_.put("1h", "liq_btc_short", {t - k * H: 1e8 for k in range(6)})
    cat = S.catalog_with_watchlist([], {"top": 30, "exchanges": ["Binance"]})
    ev = []
    alerts.check_changes(st_, cat, [{"series": "oi_others", "window_hours": 24, "pct": 10}], {}, now, events=ev)
    alerts.check_levels(st_, cat, [{"series": "total3", "level": 1.02e12, "near_pct": 3}], {}, events=ev)
    alerts.check_sums(st_, cat, [{"series": "liq_btc", "window_hours": 4, "usd": 1.5e9}], {}, now, events=ev)
    assert [(e["kind"], e["sid"]) for e in ev] == [("change", "oi_others"), ("level", "total3"), ("liq", "liq_btc")]
    assert ev[0]["v"] == 115.0 and ev[1]["key"].endswith(":near") and ev[2]["v"] == 1.6e9
    # Fibo
    fev, fst = [], {}
    setups = [{"id": "1", "coin": "HYPE", "high": 60, "low": 20, "dir": "long"}]
    F.check(setups, {"HYPE": 30.0}, fst, 2, events=fev)                  # uzbrojenie po cichu
    F.check(setups, {"HYPE": 27.0}, fst, 2, events=fev)
    assert len(fev) == 1 and fev[0]["kind"] == "fib" and fev[0]["coin"] == "HYPE" and fev[0]["px"] == 27.0 and fev[0]["key"] == "1:deep"


def test_lamp_events():
    info = {"on": True, "level": 2, "since": 1_790_000_000, "value": 0.953, "stats": [None, None, None], "episodes": []}
    res = {"lamps": {"leverage": info}}
    st, ev = {"lamps": {}}, []
    m = LP.check(res, {}, st, events=ev)
    assert len(m) == 1 and len(ev) == 1 and ev[0]["kind"] == "lamp" and ev[0]["key"] == "leverage:on" and ev[0]["level"] == 2
    assert ev[0]["text"] == m[0] and ev[0]["v"] == 0.953


# ── dziennik alertów: skan GitHuba ───────────────────────────
def test_scan_journal_writes_prices_and_results(tmp_path):
    d = str(tmp_path)
    now = 1_790_000_000 - 1_790_000_000 % H
    st_ = Store(d)
    for sid, v in (("px_btc", 100000.0), ("px_eth", 3000.0), ("px_sol", 150.0), ("total3", 1.0e12)):
        st_.put("1h", sid, {now: v})
    idx = [[now - now % D - D, 50.0, 300]]
    ev = [{"kind": "liq", "text": "💥 <b>Likwidacje SOL</b>: $512.3M w 4h", "sid": "liq_sol", "v": 5.123e8, "key": "k"},
          {"kind": "level", "text": "🚨 <b>TOTAL3</b> $1.000T przebił", "sid": "total3", "v": 1.0e12, "key": "k2"}]
    lamp = [{"kind": "lamp", "text": "🔴 Lewar altów 0,953× (≥ 0,95)", "key": "leverage:on", "level": 2, "v": 0.953}]
    info = main.alert_journal(st_, {}, now, ev, lamp, False, lambda name: {"d": idx})
    assert info == {"new": 3, "results": 0, "total": 3}
    log = json.load(open(os.path.join(d, AL.FILE), encoding="utf-8"))
    liq, lvl, lam = log["alerts"]
    assert liq["coin"] == "SOL" and liq["px"] == 150.0 and "$512,3M" in liq["text"]
    assert lvl["ref"] == {"btc": 100000.0, "eth": 3000.0, "total3": 1.0e12, "alt": 50.0} and "coin" not in lvl
    assert lam["text"] == "🔴 Lewar altów 0,953× (≥ 0,95)"              # lampki: zapis bez drugiej zamiany
    # nic nowego i nic po terminie → pliku nie ruszamy
    assert main.alert_journal(st_, {}, now + 2 * H, [], [], False, None) is None
    # 7 dni później
    t7 = now + 7 * D
    for sid, v in (("px_btc", 90000.0), ("px_eth", 3300.0), ("px_sol", 120.0), ("total3", 0.8e12)):
        st_.put("1h", sid, {t7: v})
    idx.append([t7 - t7 % D, 40.0, 300])
    info = main.alert_journal(st_, {}, t7 + H, [], [], True, lambda name: {"d": idx})
    assert info == {"new": 0, "results": 3, "total": 3}
    log = json.load(open(os.path.join(d, AL.FILE), encoding="utf-8"))
    liq, lvl, lam = log["alerts"]
    assert liq["out"]["7"]["px_pct"] == -20.0 and "v" not in liq["out"]["7"]
    assert lvl["out"]["7"]["v_pct"] == -20.0 and lvl["out"]["7"]["ref_pct"] == {"btc": -10.0, "eth": 10.0, "total3": -20.0, "alt": -20.0}
    assert lam["out"]["7"]["ref_pct"]["alt"] == -20.0
    assert main.alert_journal(st_, {"alert_log": {"enabled": False}}, t7, ev, [], False, None) is None


def test_scan_journal_never_breaks_the_scan(tmp_path):
    class Broken:
        dir = str(tmp_path)
        series = {"1h": {}, "1d": {}}

        def latest(self, sid):
            raise RuntimeError("x")
    assert main.alert_journal(Broken(), {}, 1, [{"kind": "level", "text": "t", "sid": "total3"}], [], False, None) is None


# ── Orange Pi: alert EMA → dziennik, zapis liczb, stan od razu ──
def _cross(st, tg, now, factor=None):
    fb = FakeBinance(now=now)
    if factor is not None:
        pub = json.load(open(os.path.join(st, "pub", "ema.json")))
        a = next(c for c in pub["coins"] if c["s"] == "AAA")
        fb.live = {"AAAUSDT": a["ec"] * (factor[0] if a["d"] >= 0 else factor[1])}
    return fb


def test_pi_alert_goes_to_journal_in_polish_and_gets_result(tmp_path):
    st, tg = str(tmp_path), FakeTG()
    E.run(ema_cfg(), st, now=ENOW, client=FakeBinance(), telegram=tg, remote=None)
    assert not os.path.exists(os.path.join(st, AL.FILE))                 # bez alertów nie ma pliku
    fb = _cross(st, tg, ENOW + 300, (0.9, 1.1))
    E.run(ema_cfg(), st, now=ENOW + 300, client=fb, telegram=tg, remote=None)
    assert len(tg.sent) == 1 and "przeciął" in tg.sent[0]
    assert "," in tg.sent[0].split("AAA")[1] and "." not in tg.sent[0].split("</b>")[-1].split("EMA200")[0]   # $108,50 (−10,00%
    log = json.load(open(os.path.join(st, AL.FILE), encoding="utf-8"))
    assert log["src"] == "pi" and len(log["alerts"]) == 1
    e = log["alerts"][0]
    assert e["kind"] == "ema_d" and e["coin"] == "AAA" and e["key"].startswith("cross_") and e["px"] == pytest.approx(fb.live["AAAUSDT"], rel=1e-5)
    assert "<" not in e["text"] and e["out"] == {}
    # 7 dni później (Pi działa): wynik z ceny na żywo; kopia idzie do folderu publikacji
    t7 = ENOW + 300 + 7 * D
    fb7 = FakeBinance(now=t7)
    fb7.live = {"AAAUSDT": fb.live["AAAUSDT"] * 1.25}
    E.run(ema_cfg(publish_minutes=0), st, now=t7, client=fb7, telegram=FakeTG(), remote=None)
    log = json.load(open(os.path.join(st, AL.FILE), encoding="utf-8"))
    assert log["alerts"][0]["out"]["7"]["px_pct"] == 25.0
    pub = json.load(open(os.path.join(st, "pub", AL.FILE), encoding="utf-8"))
    assert pub["alerts"][0]["out"]["7"]["px_pct"] == 25.0


def test_pi_state_saved_before_later_failure_no_repeated_alert(tmp_path, monkeypatch):
    st, tg = str(tmp_path), FakeTG()
    E.run(ema_cfg(), st, now=ENOW, client=FakeBinance(), telegram=tg, remote=None)
    fb = _cross(st, tg, ENOW + 300, (0.9, 1.1))
    real = E.rsi_now

    def boom(*a, **k):
        raise RuntimeError("wyjątek po wysłaniu alertów")
    monkeypatch.setattr(E, "rsi_now", boom)
    with pytest.raises(RuntimeError):
        E.run(ema_cfg(), st, now=ENOW + 300, client=fb, telegram=tg, remote=None)
    assert len(tg.sent) == 1
    monkeypatch.setattr(E, "rsi_now", real)
    fb2 = FakeBinance(now=ENOW + 600)
    fb2.live = dict(fb.live)
    E.run(ema_cfg(), st, now=ENOW + 600, client=fb2, telegram=tg, remote=None)
    assert len(tg.sent) == 1                                             # dawniej: ten sam alert drugi raz


def test_muted_alert_is_still_logged(tmp_path):
    st, tg = str(tmp_path), FakeTG()
    E.run(ema_cfg(), st, now=ENOW, client=FakeBinance(), telegram=tg, remote=None)
    with open(os.path.join(st, "bot.json"), "w", encoding="utf-8") as f:
        json.dump({"mute_until": ENOW + D}, f)
    fb = _cross(st, tg, ENOW + 300, (0.9, 1.1))
    E.run(ema_cfg(), st, now=ENOW + 300, client=fb, telegram=tg, remote=None)
    assert tg.sent == []
    log = json.load(open(os.path.join(st, AL.FILE), encoding="utf-8"))
    assert len(log["alerts"]) == 1 and log["alerts"][0]["muted"] is True


# ── zapis liczb w alertach ───────────────────────────────────
def test_pl_text_keeps_links_code_and_fibo_level_names():
    t = alerts.pl_text('🔼 <b>BTC</b> $94,921 (+0.62%) · <a href="https://x.io/ema.html#c=BTC&amp;v=1.5">wykres</a> '
                       '<code>/fib SOL 250.5 120.25</code> ▼-12.0% -5.2% Fibo 0.705–0.786, 0.75 = $1.25')
    assert "$94 921" in t and "+0,62%" in t and "v=1.5" in t and "/fib SOL 250.5 120.25" in t
    assert "▼ 12,0%" in t and "−5,2%" in t and "0.705–0.786, 0.75 = $1,25" in t
