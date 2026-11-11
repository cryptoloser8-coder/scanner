"""CVD spot vs perp (poprawka 44): zbieranie (cvd.collect), bloki raportów, wersja dla AI — offline."""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import cvd  # noqa: E402
import report  # noqa: E402
import series as S  # noqa: E402
from store import Store  # noqa: E402

DAY, HOUR = 86400, 3600
T0 = 1_700_006_400 // DAY * DAY
EXCHANGES = [{"code": "A", "name": "Binance"}, {"code": "6", "name": "Bybit"}, {"code": "C", "name": "Coinbase"},
             {"code": "3", "name": "OKX"}, {"code": "Y", "name": "Gate.io"}]
FUTURES = [
    {"symbol": "BTCUSDT_PERP.A", "exchange": "A", "base_asset": "BTC", "quote_asset": "USDT", "is_perpetual": True,
     "oi_lq_vol_denominated_in": "BASE_ASSET", "has_buy_sell_data": True},
    {"symbol": "BTCUSD_PERP.A", "exchange": "A", "base_asset": "BTC", "quote_asset": "USD", "is_perpetual": True,
     "oi_lq_vol_denominated_in": "QUOTE_ASSET", "has_buy_sell_data": True},
    {"symbol": "BTCUSDT_PERP.3", "exchange": "3", "base_asset": "BTC", "quote_asset": "USDT", "is_perpetual": True,
     "oi_lq_vol_denominated_in": "BASE_ASSET"},
    {"symbol": "BTCTINY.6", "exchange": "6", "base_asset": "BTC", "quote_asset": "USDT", "is_perpetual": True},
    {"symbol": "SOLUSDT_PERP.A", "exchange": "A", "base_asset": "SOL", "quote_asset": "USDT", "is_perpetual": True},
    {"symbol": "ETHBTC_PERP.A", "exchange": "A", "base_asset": "ETH", "quote_asset": "BTC", "is_perpetual": True},
    {"symbol": "BTC_USDT.Y", "exchange": "Y", "base_asset": "BTC", "quote_asset": "USDT", "is_perpetual": True},
    {"symbol": "BTCQ.A", "exchange": "A", "base_asset": "BTC", "quote_asset": "USDT", "is_perpetual": False},
    {"symbol": "ETHUSDT.6", "exchange": "6", "base_asset": "ETH", "quote_asset": "USDT", "is_perpetual": True,
     "has_buy_sell_data": False},
]
SPOTS = [
    {"symbol": "BTCUSD.A", "exchange": "A", "base_asset": "BTC", "quote_asset": "USDT", "has_buy_sell_data": True},
    {"symbol": "BTCUSD.C", "exchange": "C", "base_asset": "BTC", "quote_asset": "USD", "has_buy_sell_data": True},
    {"symbol": "BTCEUR.C", "exchange": "C", "base_asset": "BTC", "quote_asset": "EUR", "has_buy_sell_data": True},
    {"symbol": "SOLUSD.A", "exchange": "A", "base_asset": "SOL", "quote_asset": "USDT", "has_buy_sell_data": True},
]
# wolumen na świecę (w jednostkach rynku), udział kupna, cena
VOL = {"BTCUSDT_PERP.A": 100.0, "BTCUSD_PERP.A": 2_000_000.0, "BTCUSDT_PERP.3": 50.0, "BTCTINY.6": 0.1,
       "SOLUSDT_PERP.A": 1000.0, "BTCUSD.A": 10.0, "BTCUSD.C": 5.0, "SOLUSD.A": 300.0}
BUY = {"perp": 0.45, "spot": 0.6}
PRICE = {"BTC": 40_000.0, "SOL": 100.0}
CFG = {"cvd": {"enabled": True, "coins": ["BTC", "SOL"], "spot_exchanges": ["Binance", "Coinbase"],
               "quotes": ["USDT", "USD"], "min_share": 0.01, "share_days": 30, "history_start": "2023-11-15"},
       "coinalyze": {"exchanges": ["Binance", "Bybit", "OKX"]}}


def kind_of(sym):
    return "spot" if sym in ("BTCUSD.A", "BTCUSD.C", "SOLUSD.A") else "perp"


class FakeCZ:
    """Coinalyze: najwyżej `cap` najnowszych punktów na rynek (jak prawdziwe API), dane od T0."""
    batch = 18

    def __init__(self, cap=1500, fail_daily=False):
        self.cap, self.calls_made, self.failed_batches, self.requests = cap, 0, 0, []
        self.fail_daily = fail_daily

    def exchanges(self):
        return EXCHANGES

    def future_markets(self):
        return FUTURES

    def spot_markets(self):
        return SPOTS

    def history(self, path, syms, interval, frm, to, fields, usd=False, progress=None):
        assert path == "/ohlcv-history" and tuple(fields) == ("v", "bv", "c")
        self.requests.append((interval, tuple(syms), frm, to))
        self.calls_made += len(syms)
        if interval == "daily" and self.fail_daily:
            self.failed_batches += 1
            return {}
        step = DAY if interval == "daily" else HOUR
        k = 1.0 if interval == "daily" else 1 / 24
        out = {}
        for s in syms:
            coin = "SOL" if s.startswith("SOL") else "BTC"
            start = max(frm, T0)
            start = -(-start // step) * step
            ts = list(range(start, to + 1, step))[-self.cap:]
            v = VOL[s] * k
            out[s] = {t: (v, v * BUY[kind_of(s)], PRICE[coin]) for t in ts}
        return out


def test_candidates_filters():
    mk = cvd.candidates(EXCHANGES, FUTURES, SPOTS, cvd.settings(CFG))
    assert set(mk) == {"BTCUSDT_PERP.A", "BTCUSD_PERP.A", "BTCUSDT_PERP.3", "BTCTINY.6", "SOLUSDT_PERP.A",
                       "BTCUSD.A", "BTCUSD.C", "SOLUSD.A"}
    assert mk["BTCUSD_PERP.A"]["unit"] == "quote" and mk["BTCUSDT_PERP.A"]["unit"] == "base"
    assert mk["BTCUSD.C"]["kind"] == "spot" and mk["BTCUSD.C"]["ex"] == "Coinbase"


def test_usd_units():
    assert cvd.usd((10, 6, 100), "base") == (1000.0, 200.0)
    assert cvd.usd((1000, 400, 50_000), "quote") == (1000.0, -200.0)
    assert cvd.usd((None, 1, 1), "base") is None and cvd.usd((-1, 1, 1), "base") is None


def test_collect_full_then_incremental(tmp_path):
    now = T0 + 400 * DAY + 5 * HOUR + 600
    store = Store(str(tmp_path))
    cz = FakeCZ()
    info = cvd.collect(cz, store, CFG, now)
    st = store.state["cvd"]
    assert info["full"] and info["daily"] and "BTCTINY.6" not in st["selected"]     # < 1% wolumenu BTC perp
    assert len(st["selected"]) == 7 and st["px"] == {"SOL": "SOLUSDT_PERP.A"}
    today = now - now % DAY
    d1 = store.series["1d"]
    # perp BTC: USDT-M 100 BTC + OKX 50 BTC (× $40k) + odwrotny $2M (już w $) — delta = (2·0.45 − 1) × wolumen
    vol = 150 * 40_000 + 2_000_000
    assert abs(d1["cvd_btc_perp_vol"][today - DAY] - vol) < 1e-6 * vol
    assert abs(d1["cvd_btc_perp"][today - DAY] - (-0.1 * vol)) < 1e-6 * vol
    assert abs(d1["cvd_btc_spot"][today - DAY] / d1["cvd_btc_spot_vol"][today - DAY] - 0.2) < 1e-9
    assert min(d1["cvd_btc_spot"]) == cvd._day_ts("2023-11-15")       # historia od history_start
    assert today in d1["cvd_btc_spot"]                                 # bieżąca doba z godzin
    assert d1["px_sol"][today - DAY] == 100.0 and store.series["1h"]["px_sol"]
    h = store.series["1h"]["cvd_btc_spot"]
    assert len(h) > 1000 and abs(sum(v for t, v in h.items() if today - DAY <= t < today)
                                 - d1["cvd_btc_spot"][today - DAY]) < 1e-3
    # ten sam dzień: bez świec dziennych, tylko godziny od ostatniej − 3 h
    n_req = len(cz.requests)
    info2 = cvd.collect(cz, store, CFG, now + 2 * HOUR)
    assert not info2["daily"] and all(r[0] == "1hour" for r in cz.requests[n_req:])
    assert cz.requests[-1][2] == now - now % HOUR - 3 * HOUR
    # następna doba: świece dzienne kandydatów za 40 dni
    info3 = cvd.collect(cz, store, CFG, now + DAY)
    assert info3["daily"] and not info3["full"]
    daily_req = [r for r in cz.requests if r[0] == "daily"][-1]
    assert daily_req[2] == today + DAY - 40 * DAY and len(daily_req[1]) == 8


def test_collect_failed_daily_keeps_old_series(tmp_path):
    now = T0 + 100 * DAY + 3 * HOUR
    store = Store(str(tmp_path))
    cvd.collect(FakeCZ(), store, CFG, now)
    before = dict(store.series["1d"]["cvd_btc_perp"])
    info = cvd.collect(FakeCZ(fail_daily=True), store, CFG, now + DAY)
    assert info["failed_batches"] >= 1 and store.state["cvd"]["daily_day"] == now - now % DAY
    assert all(store.series["1d"]["cvd_btc_perp"][t] == v for t, v in before.items() if t < now - now % DAY)


def _data_dir(tmp_path, now, days=800):
    """Dane jak na gałęzi data: cvd_1d/1h + ceny w liq_*; doba przed `now` ma przewagę kupna na spot."""
    data = tmp_path / "data"
    data.mkdir()
    today = now - now % DAY
    ds = [today - (days - i) * DAY for i in range(days)]
    d1, h1 = {}, {}
    for coin, base in (("btc", 1e9), ("eth", 4e8), ("sol", 1e8), ("bnb", 2e7), ("xrp", 5e7), ("doge", 1e7)):
        for kind, mult in (("spot", 1), ("perp", 10)):
            vol = base * mult
            imb = [((i * 37) % 21 - 10) / 100 * (0.5 if kind == "perp" else 1) for i in range(days)]   # −10…+10%
            if coin == "btc" and kind == "spot":
                imb[-1] = 0.25                                       # nietypowa doba: +25% wolumenu
            d1[f"cvd_{coin}_{kind}_vol"] = [[t, vol] for t in ds]
            d1[f"cvd_{coin}_{kind}"] = [[t, vol * x] for t, x in zip(ds, imb)]
    hours = list(range(today - 8 * DAY, today + 5 * HOUR, HOUR))
    h1["cvd_btc_spot"] = [[t, 1e6] for t in hours]
    h1["cvd_btc_perp"] = [[t, -2e6] for t in hours]
    px = {"px_btc": [[t, 50_000.0 * (1.02 if t == ds[-1] else 1)] for t in ds],
          "px_eth": [[t, 2000.0] for t in ds], "px_sol": [[t, 100.0] for t in ds]}
    for name, obj in (("cvd_1d.json", d1), ("cvd_1h.json", h1), ("liq_1d.json", px),
                      ("liq_1h.json", {"px_btc": [[t, 50_000.0] for t in hours]}), ("1d.json", {}), ("1h.json", {})):
        (data / name).write_text(json.dumps({"updated": now, "series": obj}))
    (data / "meta.json").write_text(json.dumps({"catalog": {}}))
    return str(data)


def test_morning_blocks(tmp_path):
    now = T0 + 900 * DAY + 6 * HOUR
    d = report.Data(_data_dir(tmp_path, now))
    cfg = {"cvd": {"enabled": True}}
    bl = cvd.morning_blocks(d, now, cfg)
    by = {b.get("title"): b for b in bl}
    tab = by["Kupno vs sprzedaż — spot i perp"]
    day = report.utc(now - now % DAY - DAY, "%d.%m")
    btc = tab["rows"][0]
    assert btc[:3] == ["BTC", f"doba {day}", "▲+2.0%"]
    assert btc[3] == "+$250M (+25.0%)" and btc[4] == "+$300M (+3.0%)" and btc[5] == "kupują spot i perp"
    assert tab["rows"][1][:2] == ["BTC", "7 dni"] and tab["rows"][1][5] == "przewaga kupna tylko na spot"
    assert [r[0] for r in tab["rows"]].count("DOGE") == 2 and "Przykład: BTC w dobie" in tab["desc"]
    bars = by[f"Przewaga kupujących w dobie {day} — % wolumenu"]
    b0 = bars["rows"][0]
    assert b0["label"] == "BTC" and b0["spot"] == 25.0 and b0["spot_band"][1] < 25        # poza zwykłym zakresem
    assert -10 <= b0["spot_band"][0] < 0 < b0["spot_band"][1] <= 10
    ch = by["BTC — CVD spot i perp, ostatnie 7 dni (co godzinę)"]
    s, p = ch["series"][0]["data"], ch["series"][1]["data"]
    assert len(s) == 7 * 24 and s[-1][1] == 168e6 and p[-1][1] == -336e6
    assert ch["series"][2]["scale"] == "hidden"


def test_weekly_blocks(tmp_path):
    now = T0 + 900 * DAY + 6 * HOUR
    d = report.Data(_data_dir(tmp_path, now))
    end = now - now % DAY - ((now // DAY + 3) % 7) * DAY          # poniedziałek 00:00 UTC
    bl = cvd.weekly_blocks(d, end - 7 * DAY, end, {"cvd": {"enabled": True}})
    titles = [b["title"] for b in bl]
    assert titles == ["Kupno vs sprzedaż — spot i perp w tygodniu",
                      "BTC — przewaga kupujących tydzień po tygodniu (12 tygodni)",
                      "ETH — przewaga kupujących tydzień po tygodniu (12 tygodni)"]
    w = bl[1]
    assert len(w["rows"]) == 12 and w["rows"][-1]["label"] == report.utc(end - 7 * DAY, "%d.%m")
    assert w["rows"][0]["spot_band"] and "spot_text" in w["rows"][0]


def test_report_morning_has_cvd_and_markdown(tmp_path):
    now = T0 + 900 * DAY + 6 * HOUR
    data = _data_dir(tmp_path, now)
    rep = report.build(data, None, "morning", now=now, cfg={"cvd": {"enabled": True}})
    secs = [b["title"] for b in rep["blocks"] if b["type"] == "section"]
    assert "CVD — kto kupował: spot i perp" in secs
    md = report.to_markdown(rep)
    assert "spot — przewaga kupujących (% wolumenu · $)" in md and "+25.0% · +$250M" in md
    assert "**CVD spot**" in md and "+$168M" in md
    # wyłączone w configu → bez sekcji
    rep2 = report.build(data, None, "morning", now=now, cfg={})
    assert "CVD — kto kupował: spot i perp" not in [b.get("title") for b in rep2["blocks"]]


def test_catalog_and_store_bundle():
    cat = S.catalog_with_watchlist([], None, ["BTC", "SOL"])
    assert cat["cvd_btc_spot"]["cum"] and cat["cvd_btc_spot"]["fmt"] == "flow"
    assert cat["cvd_sol_perp_vol"]["group"] == "vol" and cat["px_sol"]["group"] == "price" and "px_btc" not in cat
    from store import bundle_of
    assert bundle_of("cvd_btc_spot_vol") == "cvd_" and bundle_of("px_sol") == "liq_"


def test_who_and_formats():
    assert cvd.who(3.0, -2.0, 1.0) == "spot kupuje, perp sprzedaje"
    assert cvd.who(0.5, 0.2, 1.0) == "bez wyraźnej przewagi"
    assert cvd.fmt_usd(-1.4e9) == "-$1.40B" and cvd.fmt_usd(359e6) == "+$359M" and cvd.fmt_usd(0.0) == "$0"
    assert report.fmt_val(-2.7e7, "flow") == "-$27M"


def test_store_saves_cvd_in_own_files(tmp_path):
    now = T0 + 60 * DAY + 3 * HOUR
    store = Store(str(tmp_path))
    cvd.collect(FakeCZ(), store, CFG, now)
    store.save(now, {})
    files = sorted(os.listdir(tmp_path))
    assert "cvd_1d.json" in files and "cvd_1h.json" in files and "liq_1d.json" in files     # px_sol → liq_
    main1d = json.load(open(tmp_path / "1d.json"))["series"]
    assert not any(k.startswith("cvd_") for k in main1d)
    again = Store(str(tmp_path))
    assert again.series["1d"]["cvd_btc_spot"] == store.series["1d"]["cvd_btc_spot"]


def test_main_run_cvd_failure_is_isolated(tmp_path):
    import alerts
    import main
    import test_collector as TC
    cfg = TC._cfg()
    cfg["cvd"] = {"enabled": True, "coins": ["BTC"]}
    tg = alerts.Telegram(token="", chat_id="", enabled=False)
    _, _, res = main.run(str(tmp_path), cfg, now=TC.NOW, backfill=True, coinalyze=TC.FakeCoinalyze(), tv=TC.FakeTV(),
                         telegram=tg, cg_fetch=TC.CG)
    assert res["Coinalyze"] is None and res["TradingView"] is None and res["CVD"]       # błąd CVD nie psuje reszty
    meta = json.load(open(tmp_path / "meta.json"))
    assert meta["health"]["CVD"] != "ok" and "cvd_btc_spot" in meta["catalog"]


def test_report_cfg_reads_cvd_section():
    cfg = report.load_cfg(os.path.join(HERE, "config.yaml"))
    assert cvd.enabled(cfg) and cvd.coins_of(cfg) == ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]


def test_morning_merged_oi_cvd_table(tmp_path):
    """Poprawka 45: jedna tabela cena + OI + CVD w sekcji Derywaty; sekcja CVD bez własnej tabeli."""
    now = T0 + 900 * DAY + 6 * HOUR
    data = _data_dir(tmp_path, now)
    today = now - now % DAY
    ds = [today - (800 - i) * DAY for i in range(800)]
    oi = {"oi_btc": [[t, 2e10 * (1.05 if t == ds[-1] else 1)] for t in ds],        # doba: OI $ +5%, cena +2% → w coinach +2.9%
          "oi_eth": [[t, 1e10] for t in ds]}
    with open(os.path.join(data, "1d.json"), "w") as f:
        json.dump({"updated": now, "series": oi}, f)
    rep = report.build(data, None, "morning", now=now, cfg={"cvd": {"enabled": True}})
    by = {b.get("title"): b for b in rep["blocks"]}
    assert "Kupno vs sprzedaż — spot i perp" not in by and "Open interest i cena — BTC i ETH" not in by
    tab = by["Cena, open interest i CVD — kto napędzał ruch"]
    assert tab["cols"] == ["Coin", "Okres", "Cena", "OI (w coinach)", "CVD perp", "CVD spot", "Typowe odczytanie"]
    btc = tab["rows"][0]
    assert btc[:4] == ["BTC", "doba " + report.utc(today - DAY, "%d.%m"), "▲+2.0%", "▲+2.9%"]
    assert btc[4] == "+$300M (+3.0%)" and btc[5] == "+$250M (+25.0%)"
    assert btc[6][0] == "Cena rośnie, przybywa pozycji"
    assert btc[6][1] == {"t": "CVD perp: przewaga kupna → potwierdza: nowe longi", "tone": "ok"}
    assert btc[6][2] == {"t": "Spot i perp: kupują spot i perp", "tone": "mute"}
    sol = next(r for r in tab["rows"] if r[0] == "SOL")
    assert sol[3] == "—" and sol[6][0] == "Cena stoi (brak danych OI)"                 # coin bez serii OI
    assert "potwierdzone: BTC, doba" in tab["desc"]
    secs = [b["title"] for b in rep["blocks"] if b["type"] == "section"]
    assert secs.index("Derywaty") < secs.index("CVD — kto kupował: spot i perp")
    assert f"Przewaga kupujących w dobie {report.utc(today - DAY, '%d.%m')} — % wolumenu" in by
    md = report.to_markdown(rep)
    assert "Cena rośnie, przybywa pozycji · CVD perp: przewaga kupna → potwierdza: nowe longi · Spot i perp: kupują spot i perp" in md
