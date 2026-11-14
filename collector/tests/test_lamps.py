"""Lampki zakładki Altsezon (lamps.py, poprawka 70)."""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import alerts  # noqa: E402
import lamps as LP  # noqa: E402
import series as S  # noqa: E402

D = 86400
T0 = 1_700_006_400 // D * D          # początek siatki (pełna doba UTC)


def days(n):
    return [T0 + i * D for i in range(n)]


def flat_idx(n, v=100.0):
    return [[t, v, 100] for t in days(n)]


def test_leverage_lamp_lights_levels_and_goes_off():
    n = 120
    lev = {t: 0.6 for t in days(n)}
    idx = flat_idx(n + 60)
    st = {}
    now = T0 + (n - 1) * D
    r = LP.build({}, now, idx=idx[:n], lev=lev)
    assert r["lamps"]["leverage"]["on"] is False
    assert LP.check(r, {}, st) == []                       # pierwszy przebieg: uzbrojenie po cichu
    lev[now + D] = 0.91
    r = LP.build({}, now + D, idx=idx[:n + 1], lev=lev)
    m = LP.check(r, {}, st)
    assert len(m) == 1 and "Lewar altów" in m[0] and "0,910×" in m[0] and "Zapaliła się" in m[0] and "uwaga" in m[0]
    assert LP.check(r, {}, st) == []                       # bez powtórek
    lev[now + 2 * D] = 0.96
    r = LP.build({}, now + 2 * D, idx=idx[:n + 2], lev=lev)
    m = LP.check(r, {}, st, "https://a.github.io/scanner/oi.html")
    assert "Wyższy poziom" in m[0] and "0,95" in m[0] and m[-1].endswith('alt.html">Altsezon — wszystkie lampki</a>')
    # przygasa na 5 dni i wraca — ten sam epizod, bez nowej wiadomości
    for k in range(3, 8):
        lev[now + k * D] = 0.80
    r = LP.build({}, now + 7 * D, idx=idx[:n + 8], lev=lev)
    assert r["lamps"]["leverage"]["on"] is False and r["lamps"]["leverage"]["since"] == now + D
    assert LP.check(r, {}, st) == []
    lev[now + 8 * D] = 0.92
    r = LP.build({}, now + 8 * D, idx=idx[:n + 9], lev=lev)
    assert LP.check(r, {}, st) == []                       # poziom 1 < już zgłoszony 2
    # gaśnie na dobre po gap_days (14) bez warunku
    for k in range(9, 30):
        lev[now + k * D] = 0.70
    r = LP.build({}, now + 29 * D, idx=idx[:n + 30], lev=lev)
    m = LP.check(r, {}, st)
    assert len(m) == 1 and "zgasła" in m[0] and "Świeciła" in m[0]
    assert LP.check(r, {}, st) == []
    ep = r["lamps"]["leverage"]["episodes"][-1]
    assert ep[0] == now + D and ep[1] == now + 8 * D and ep[2] == 2


def test_stats_after_30_days():
    n = 200
    lev = {t: 0.6 for t in days(n)}
    for k in range(40, 45):
        lev[T0 + k * D] = 0.97
    # indeks spada o 20% w 30 dni po zapaleniu
    idx = [[t, 100.0 if i <= 40 else 80.0, 100] for i, t in enumerate(days(n))]
    r = LP.build({}, T0 + (n - 1) * D, idx=idx, lev=lev)
    s = r["lamps"]["leverage"]["stats"]
    assert s[0]["n"] == 1 and s[0]["good"] == 1 and math.isclose(s[0]["med"], -20.0)
    assert s[1]["n"] == 1 and s[2]["n"] == 0
    txt = LP._stat_txt("leverage", s[1])
    assert "niżej 1 z 1" in txt and "nie prognoza" in txt


def test_big_wave_and_selloff():
    n = 200
    vals = []
    for i in range(n):
        if i < 50:
            v = 100.0
        elif i < 80:
            v = 100.0 * (1.5 ** ((i - 50) / 30))          # +50% w 30 dni
        elif i < 110:
            v = 150.0 * (0.5 ** ((i - 80) / 30))          # potem −50%
        else:
            v = 75.0
        vals.append(v)
    idx = [[t, v, 100] for t, v in zip(days(n), vals)]
    btc = {t: 50_000.0 for t in days(n)}
    r = LP.build({}, T0 + (n - 1) * D, idx=idx, btc=btc, mvrvz={t: 0.3 for t in days(n)})
    bw = r["lamps"]["big_wave"]
    assert len(bw["episodes"]) == 1
    s, e, _, _ = bw["episodes"][0]
    conf = T0 + next(i for i in range(50, 80) if vals[i] >= 140 - 1e-9) * D
    assert s == conf                                       # od dnia +40% nad dołkiem
    assert e < T0 + 110 * D                                # do potwierdzenia końca (−28,6% od szczytu)
    assert bw["on"] is False
    assert bw["fresh"] is True and abs(bw["value"]) < 1e-6 and bw["low_t"] >= T0 + 110 * D   # bez fali: % nad obecnym dołkiem
    so = r["lamps"]["selloff"]
    assert so["episodes"] and so["episodes"][0][0] > T0 + 80 * D   # −20% w 30 dni + BTC tani (MVRV-Z 0,3)
    assert so["on"] is False                               # na końcu płasko
    # BTC drogi i bez zjazdu → brak wyprzedaży
    r2 = LP.build({}, T0 + (n - 1) * D, idx=idx, btc=btc, mvrvz={t: 2.0 for t in days(n)})
    assert r2["lamps"]["selloff"]["episodes"] == []


def test_rally_and_rsi_min_coins():
    n = 60
    br = [[t, 85.0 if i >= 50 else 40.0, 300] for i, t in enumerate(days(n))]
    rsi = [[t, 0.0, 35.0, 300] for t in days(n)[::3]]
    r = LP.build({}, T0 + (n - 1) * D, idx=flat_idx(n), breadth=br, rsi_d3=rsi)
    ra = r["lamps"]["rally"]
    assert ra["on"] and ra["level"] == 1 and ra["since"] == T0 + 50 * D
    assert "Rajd trwa" in LP.describe("rally", ra, LP.config({}), 1)
    assert r["lamps"]["rsi3d"]["on"]
    few = [[t, 95.0, 10] for t in days(n)]                 # za mało coinów
    r2 = LP.build({}, T0 + (n - 1) * D, idx=flat_idx(n), breadth=few)
    assert "rally" not in r2["lamps"]


def test_stale_data_means_off():
    n = 60
    lev = {t: 0.97 for t in days(n - 10)}                  # lewar ostatnio 10 dni temu
    r = LP.build({}, T0 + (n - 1) * D, idx=flat_idx(n), lev=lev)
    assert r["lamps"]["leverage"]["on"] is False and r["lamps"]["leverage"]["fresh"] is False


def test_config_override_and_no_index():
    c = LP.config({"alt_lamps": {"leverage": {"levels": [0.8]}, "gap_days": 3}})
    assert c["leverage"]["levels"] == [0.8] and c["gap_days"] == 3 and c["rally"]["levels"] == [80, 90]
    assert LP.build({}, T0, idx=[]) is None
    assert LP.check(None, {}, {}) == []


def test_level_alert_false_is_line_only(tmp_path):
    from store import Store
    st_ = Store(str(tmp_path))
    cat = S.catalog_with_watchlist([])
    lv = [{"series": "oi_others_vs_btc", "level": 0.95, "alert": False}]
    state = {}
    st_.put("1h", "oi_others_vs_btc", {T0: 0.5})
    assert alerts.check_levels(st_, cat, lv, state) == []
    st_.put("1h", "oi_others_vs_btc", {T0 + 3600: 1.2})
    assert alerts.check_levels(st_, cat, lv, state) == [] and state["levels"] == {}


def test_main_run_publishes_lamps(tmp_path):
    import main
    from test_collector import CG, NOW, FakeCoinalyze, FakeTV, _cfg
    n = 400
    t0 = NOW // D * D - (n - 1) * D
    idx = {"d": [[t0 + i * D, 100.0, 100] for i in range(n)]}
    ema = {"breadth": [[t0 + i * D, 50.0, 300] for i in range(n)], "rsi": {"d3": []}}
    got = []

    def fetch(name):
        got.append(name)
        return {"altindex.json": idx, "ema.json": ema}.get(name)
    d = str(tmp_path)
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    main.run(d, _cfg(), now=NOW, backfill=True, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG,
             ema_fetch=fetch)
    meta = json.load(open(os.path.join(d, "meta.json")))
    lamps = meta["alt_lamps"]["lamps"]
    assert set(got) == {"altindex.json", "ema.json"}
    assert lamps["rally"]["on"] is False and lamps["rally"]["value"] == 50.0
    assert "leverage" in lamps and meta["alt_lamps"]["cfg"]["leverage"]["levels"] == [0.9, 0.95, 1.0]
    st = json.load(open(os.path.join(d, "state.json")))
    assert "lamps" in st                                   # uzbrojone przy backfillu
    # szerokość skacze na 92% → przy zwykłym przebiegu alert „Szeroki rajd” w osobnej wiadomości
    ema["breadth"].append([NOW // D * D + D, 92.0, 300])
    _, msgs, _ = main.run(d, _cfg(), now=NOW + D, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG,
                          ema_fetch=fetch)
    assert any("Szeroki rajd" in m for m in msgs)
    assert any(t.startswith("💡 <b>Altsezon — lampki</b>") for t in tg.sent)
    # brak gałęzi ema → skan działa, lampek nie ma
    main.run(d, _cfg(), now=NOW + D + 3600, coinalyze=FakeCoinalyze(), tv=FakeTV(), telegram=tg, cg_fetch=CG,
             ema_fetch=lambda name: None)
    assert json.load(open(os.path.join(d, "meta.json")))["alt_lamps"] is None
