"""Offline tests: dłuższa historia (history.py), pary zdelistowane w szerokości rynku (delisted.py, ema_monitor)."""
import csv
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import delisted as DL  # noqa: E402
import ema_monitor as E  # noqa: E402
import history as H  # noqa: E402
import report  # noqa: E402
from store import Store  # noqa: E402

D = 86400
NOW = 1_790_000_000 - 1_790_000_000 % D + 6 * 3600
CUT = NOW - NOW % D - 100 * D            # „pierwszy dzień OI” w testach


def zip_bytes(name, text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


class Resp:
    def __init__(self, status=200, text="", content=b""):
        self.status_code, self.text, self.content = status, text, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# ── 1. cena ──────────────────────────────────────────────────
class FakeTV:
    def __init__(self, first_day):
        self.first, self.calls = first_day, 0

    def bars(self, symbol, interval, n):
        self.calls += 1
        today = NOW - NOW % D
        return [(t + 3600, 1000.0 + i) for i, t in enumerate(range(self.first, today + D, D))]  # TV: znacznik nie o 00:00


def test_prices_prepended_once_and_healed_after_wipe(tmp_path):
    store = Store(str(tmp_path))
    coin_first = NOW - NOW % D - 50 * D
    store.put("1d", "px_btc", {t: 5.0 for t in range(coin_first, NOW, D)})
    tv = FakeTV(coin_first - 300 * D)
    cfg = {"history": {"price_symbols": {"px_btc": "INDEX:BTCUSD"}}}
    info = H.extend_prices(store, tv, cfg, NOW)
    px = store.series["1d"]["px_btc"]
    assert min(px) == coin_first - 300 * D and "+300 dni" in info["px_btc"]
    assert px[coin_first] == 5.0                         # istniejące dane Coinalyze nietknięte
    H.extend_prices(store, tv, cfg, NOW + 3600)
    assert tv.calls == 1                                 # drugi raz nic nie pobiera
    for t in [t for t in px if t < coin_first]:          # pełne przeliczenie skasowało wydłużenie…
        del px[t]
    H.extend_prices(store, tv, cfg, NOW + 7200)
    assert tv.calls == 2 and min(px) == coin_first - 300 * D   # …więc wraca od razu, bez czekania 20 h


# ── 2. funding ───────────────────────────────────────────────
class FakeCZ:
    """Funding (percent per 8 h): Binance 0.01 from CUT-400d, OKX 0.03 from CUT-200d; OI shares 3:1."""
    calls_made = 0

    def __init__(self):
        self.funding = {"BTCUSDT_PERP.A": (CUT - 400 * D, 0.01), "BTCUSDT_PERP.3": (CUT - 200 * D, 0.03),
                        "ETHUSDT_PERP.A": (CUT - 300 * D, 0.02)}
        self.oi = {"BTCUSDT_PERP.A": 3e9, "BTCUSDT_PERP.3": 1e9, "ETHUSDT_PERP.A": 2e9}

    def history(self, path, syms, interval, frm, to, fields, usd=False):
        assert path == "/funding-rate-history"
        out = {}
        for s in syms:
            start, v = self.funding.get(s, (None, None))
            if start is not None:
                out[s] = {t: v for t in range(max(start, frm - frm % D), to + 1, D)}
        return out

    def oi_history(self, syms, interval, frm, to):
        return {s: {t: self.oi[s] for t in range(frm, to + 1, D)} for s in syms if s in self.oi}


def funding_store(tmp_path):
    store = Store(str(tmp_path))
    store.put("1d", "oi_total", {t: 1e10 for t in range(CUT, NOW, D)})
    store.put("1d", "fund_btc", {t: 9.0 for t in range(CUT, NOW, D)})
    store.put("1d", "fund_eth", {t: 9.0 for t in range(CUT, NOW, D)})
    store.state.update({
        "universe": {"at": 1, "symbols": {"BTCUSDT_PERP.A": "BTC", "BTCUSDT_PERP.3": "BTC", "ETHUSDT_PERP.A": "ETH"},
                     "assets": [["BTC", 4000], ["ETH", 2000]]},
        "last_oi": {}, "liq_funding_unit": "percent",
        "liq_exchanges": {"at": 1, "names": {"A": "Binance", "3": "OKX"}},
    })
    return store


def test_funding_before_oi_start_with_fixed_weights(tmp_path):
    store = funding_store(tmp_path)
    cfg = {"history": {}, "coinalyze": {"exchanges": ["Binance", "OKX"]},
           "liquidations": {"funding_interval_hours": {"default": 8}}}
    info = H.extend_funding(FakeCZ(), store, cfg, NOW)
    fb = store.series["1d"]["fund_btc"]
    ann = lambda pct: pct * 3 * 365                       # noqa: E731  (% na 8 h → % rocznie)
    assert abs(fb[CUT - 300 * D] - ann(0.01)) < 1e-6     # tylko Binance
    assert abs(fb[CUT - 10 * D] - ann(0.75 * 0.01 + 0.25 * 0.03)) < 1e-4   # wagi stałe 3:1
    assert fb[CUT] == 9.0                                # od pierwszego dnia OI bez zmian
    assert min(store.series["1d"]["fund_eth"]) == CUT - 300 * D
    w = store.state["history"]["funding"]["btc"]["weights_pct"]
    assert w == {"Binance": 75.0, "OKX": 25.0} and "fund_btc" in info
    assert H.extend_funding(FakeCZ(), store, cfg, NOW + 3600) == {}      # już gotowe


def test_liquidation_cut_keeps_extended_funding(tmp_path):
    """liquidations.collect_liq cuts liq_ series before the OI start, but no longer fund_."""
    import liquidations as L
    src = open(L.__file__, encoding="utf-8").read()
    assert 'if sid.startswith("liq_"):\n                s_ = store.series["1d"][sid]' in src


# ── 3. archiwum Binance (OI) ─────────────────────────────────
def metrics_csv(day_iso, oi_usd):
    rows = [["create_time", "symbol", "sum_open_interest", "sum_open_interest_value"]]
    rows += [[f"{day_iso} 00:00:00", "BTCUSDT", "1", str(oi_usd / 2)],
             [f"{day_iso} 23:55:00", "BTCUSDT", "1", str(oi_usd)],
             [f"{day_iso} 12:00:00", "BTCUSDT", "1", str(oi_usd / 3)]]
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue()


class VisionSession:
    def __init__(self, days, missing=()):
        self.days, self.missing, self.downloads = list(days), set(missing), 0

    def get(self, url, params=None, timeout=None):
        if url == H.VISION_S3:
            keys = "".join(f"<Contents><Key>data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{H.iso(t)}.zip"
                           f"</Key></Contents>" for t in self.days)
            return Resp(text=f"<ListBucketResult><IsTruncated>false</IsTruncated>{keys}</ListBucketResult>")
        self.downloads += 1
        d = url.rsplit("-metrics-", 1)[1][:10]
        t = H.day_of(d)
        if t in self.missing or t not in self.days:
            return Resp(404)
        return Resp(content=zip_bytes(f"BTCUSDT-metrics-{d}.csv", metrics_csv(d, 1e9 + (t // D % 100) * 1e7)))


def test_vision_oi_first_fill_then_incremental(tmp_path):
    store = Store(str(tmp_path))
    today = NOW - NOW % D
    days = list(range(today - 20 * D, today, D))
    sess = VisionSession(days, missing={days[3]})
    cfg = {"history": {"vision_oi": {"oi_btc_binance": "BTCUSDT"}, "vision_workers": 2}}
    H.collect_vision(store, cfg, NOW, session=sess)
    s = store.series["1d"]["oi_btc_binance"]
    assert len(s) == 19 and s[days[0]] == 1e9 + (days[0] // D % 100) * 1e7          # ostatni odczyt dnia (23:55)
    assert store.state["history"]["vision"]["BTCUSDT"]["missing"] == [days[3]]
    n = sess.downloads
    H.collect_vision(store, cfg, NOW + 7200, session=sess)                # ten sam dzień — nic nowego
    assert sess.downloads == n
    sess.days.append(today)                                               # następnego dnia nowy plik
    H.collect_vision(store, cfg, NOW + D, session=sess)
    assert today in s and sess.downloads == n + 1


def test_parse_metrics_skips_bad_rows():
    content = zip_bytes("x.csv", "create_time,symbol,sum_open_interest,sum_open_interest_value\n"
                                 "2020-09-01 23:55:00,BTCUSDT,1,\n2020-09-01 23:50:00,BTCUSDT,1,5\n")
    assert H.parse_metrics(content) == ("2020-09-01 23:50:00", 5.0)


# ── 4. pary zdelistowane ─────────────────────────────────────
def ecfg(**kw):
    c = dict(E.DEFAULTS)
    c.update({"min_days": 3, "breadth_min_coins": 1, "alerts": [], "page_url": ""})
    c.update(kw)
    return c


def test_delisted_candidates_filters():
    syms = ["BTCUSDT", "LUNAUSDT", "BTCUPUSDT", "BUSDUSDT", "USTUSDT", "FTTBTC", "XYZUSDT", "JUPUSDT"]
    c = DL.candidates(syms, current={"BTCUSDT", "JUPUSDT"}, cfg=ecfg(exclude=["xyz"]))
    assert c == {"LUNAUSDT": "LUNA"}             # bez: obecnych, dźwigni, stablecoinów, innej waluty, wykluczonych


def test_parse_klines_ms_and_microseconds_with_header():
    t1, t2 = 1_600_000_000, 1_740_000_000
    text = ("open_time,open,high,low,close\n"
            f"{t1 * 1000},1,1,1,2.5,0\n{t2 * 1_000_000},1,1,1,3.5,0\n")
    out = DL.parse_klines(zip_bytes("k.csv", text))
    assert out == {t1 - t1 % D: 2.5, t2 - t2 % D: 3.5}


def test_delisted_series_and_breadth_include_dead_coins():
    t = [NOW - NOW % D - i * D for i in range(6)][::-1]
    live = {"AAA": (t, [1, 2, 3, 4, 5, 6], [1, 1.5, 2, 2.5, 3, 3.5])}
    dead = {"OLDUSDT": {"b": "OLD", "c": [[x, 1.0] for x in t[:4]]},             # notowany 4 dni, spadał pod EMA
            "USDCUSDT": {"b": "USDC", "c": [[x, 1.0] for x in t]},              # stablecoin — pomijany
            "TINYUSDT": {"b": "TINY", "c": [[t[0], 1.0]]}}                       # za krótka historia
    ds = E.delisted_series(dead, ecfg())
    assert set(ds) == {"D:OLDUSDT"}
    br = {x[0]: (x[1], x[2]) for x in E.breadth(live, ecfg(), NOW, extra=ds)}
    assert br[t[3]][1] == 2 and br[t[5]][1] == 1     # coin zdelistowany liczy się tylko, gdy był notowany


class FB:
    """Minimal Binance: AAA always, GONE only on the first day."""
    def __init__(self, now, gone=True):
        self.now, self.gone, self.calls = now, gone, 0

    def exchange_info(self):
        mk = lambda s, b: {"symbol": s, "baseAsset": b, "quoteAsset": "USDT", "status": "TRADING"}  # noqa: E731
        return {"symbols": [mk("AAAUSDT", "AAA")] + ([mk("GONEUSDT", "GONE")] if self.gone else [])}

    def klines(self, symbol, limit, end_ms=None):
        today = self.now - self.now % D
        last = today if end_ms is None else (end_ms // 1000) - (end_ms // 1000) % D
        days = [last - i * D for i in range(min(limit, 10))][::-1]
        return [[x * 1000, "0", "1", "1", "1", "0", (x + D) * 1000 - 1] for x in days]

    def prices(self):
        return {"AAAUSDT": 1.0, "GONEUSDT": 1.0}

    def volumes(self):
        return {}


def test_ema_monitor_moves_delisted_pair_and_publishes_count(tmp_path):
    st = str(tmp_path)
    E.run(ecfg(history_pages_per_run=0), st, now=NOW, client=FB(NOW), remote=None)
    assert "GONEUSDT" in json.load(open(os.path.join(st, "candles.json")))
    E.run(ecfg(history_pages_per_run=0), st, now=NOW + D, client=FB(NOW + D, gone=False), remote=None)
    dl = json.load(open(os.path.join(st, "delisted.json")))
    assert dl["GONEUSDT"]["b"] == "GONE" and len(dl["GONEUSDT"]["c"]) >= 9
    assert "GONEUSDT" not in json.load(open(os.path.join(st, "candles.json")))
    pub = json.load(open(os.path.join(st, "pub", "ema.json")))
    assert pub["breadth_delisted"] == 1
    E.run(ecfg(history_pages_per_run=0), st, now=NOW + 2 * D, client=FB(NOW + 2 * D, gone=True), remote=None)
    assert "GONEUSDT" not in json.load(open(os.path.join(st, "delisted.json")))   # wróciła na giełdę


def test_breadth_recomputed_after_delisted_import(tmp_path):
    st = str(tmp_path)
    c = ecfg(history_pages_per_run=0)
    E.run(c, st, now=NOW, client=FB(NOW, gone=False), remote=None)
    t = [NOW - NOW % D - i * D for i in range(30, 10, -1)]
    lock = str(tmp_path / "lock")
    DL.merge_into(os.path.join(st, "delisted.json"), {"OLDUSDT": {"b": "OLD", "c": [[x, 1.0] for x in t]}},
                  lock=lock)
    E.run(c, st, now=NOW + 300, client=FB(NOW + 300, gone=False), remote=None)      # ten sam dzień
    pub = json.load(open(os.path.join(st, "pub", "ema.json")))
    assert pub["breadth_delisted"] == 1 and pub["breadth"][0][0] == t[2]         # od 3. dnia OLD (min_days 3)


def test_report_breadth_note_mentions_delisted():
    br = [[NOW - i * D, 50.0, 10] for i in range(5)][::-1]
    assert "wycofanych" in report.breadth_peaks_note(br, delisted=120)
    assert "zawyżone" in report.breadth_peaks_note(br)
