"""Sonda CVD (probe.py check_cvd) — offline, na udawanych odpowiedziach Coinalyze i archiwum Binance."""
import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import probe  # noqa: E402

DAY = 86400
NOW = 1_793_000_000 // DAY * DAY + 3600          # 1 h po północy UTC
EXCHANGES = [{"code": "A", "name": "Binance"}, {"code": "6", "name": "Bybit"}, {"code": "C", "name": "Coinbase"},
             {"code": "Y", "name": "Gate.io"}]
FUTURES = [
    {"symbol": "BTCUSDT_PERP.A", "exchange": "A", "symbol_on_exchange": "BTCUSDT", "base_asset": "BTC",
     "quote_asset": "USDT", "is_perpetual": True, "margined": "STABLE", "oi_lq_vol_denominated_in": "BASE_ASSET",
     "has_buy_sell_data": True},
    {"symbol": "BTCUSD_PERP.A", "exchange": "A", "symbol_on_exchange": "BTCUSD_PERP", "base_asset": "BTC",
     "quote_asset": "USD", "is_perpetual": True, "margined": "COIN", "oi_lq_vol_denominated_in": "QUOTE_ASSET",
     "has_buy_sell_data": True},
    {"symbol": "ETHBTC_PERP.A", "exchange": "A", "base_asset": "ETH", "quote_asset": "BTC", "is_perpetual": True},
    {"symbol": "BTC_USDT.Y", "exchange": "Y", "base_asset": "BTC", "quote_asset": "USDT", "is_perpetual": True},
    {"symbol": "1000PEPEUSDT.6", "exchange": "6", "base_asset": "1000PEPE", "quote_asset": "USDT",
     "is_perpetual": True},
    {"symbol": "SOLUSDT.6", "exchange": "6", "symbol_on_exchange": "SOLUSDT", "base_asset": "SOL",
     "quote_asset": "USDT", "is_perpetual": True, "has_buy_sell_data": False},
]
SPOTS = [
    {"symbol": "BTCUSDT.A", "exchange": "A", "symbol_on_exchange": "BTCUSDT", "base_asset": "BTC",
     "quote_asset": "USDT", "has_buy_sell_data": True},
    {"symbol": "BTCUSD.C", "exchange": "C", "symbol_on_exchange": "BTC-USD", "base_asset": "BTC",
     "quote_asset": "USD", "has_buy_sell_data": True},
    {"symbol": "BTCEUR.C", "exchange": "C", "base_asset": "BTC", "quote_asset": "EUR", "has_buy_sell_data": True},
]


def point(t, v=100.0, bv=55.0, c=80_000.0):
    return {"t": t, "o": c, "h": c, "l": c, "c": c, "v": v, "bv": bv, "tx": 1000, "btx": 560}


class FakeCZ:
    """Coinalyze: at most `cap` newest points per symbol per request."""
    batch = 18

    def __init__(self, first_days, cap=1500):
        self.first = first_days            # {symbol: first day t}
        self.cap = cap
        self.calls_made = 0
        self.requests = []

    def exchanges(self):
        return EXCHANGES

    def future_markets(self):
        return FUTURES

    def _get(self, path, params=None):
        assert path == "/spot-markets"
        return SPOTS

    def _batch_get(self, path, params, batch):
        self.requests.append((params["interval"], tuple(batch), params["to"]))
        self.calls_made += len(batch)
        step = DAY if params["interval"] == "daily" else 3600
        out = []
        for s in batch:
            start = max(self.first.get(s, params["from"]), params["from"])
            start = -(-start // step) * step
            ts = list(range(start, params["to"] + 1, step))[-self.cap:]
            out.append({"symbol": s, "history": [point(t, bv=(55.0 if t >= self.first[s] + 30 * DAY else None))
                                                 for t in ts]})
        return out


def test_cvd_markets_filters_exchanges_quotes_and_coins():
    mk = probe.cvd_markets(EXCHANGES, FUTURES, SPOTS)
    syms = [m["sym"] for m in mk]
    assert syms == ["BTCUSDT.A", "BTCUSD.C", "BTCUSDT_PERP.A", "BTCUSD_PERP.A", "SOLUSDT.6"]
    by = {m["sym"]: m for m in mk}
    assert by["BTCUSD_PERP.A"]["unit"] == "quote" and by["BTCUSDT_PERP.A"]["unit"] == "base"
    assert by["BTCUSD.C"]["ex"] == "Coinbase" and by["SOLUSDT.6"]["bs"] is False


def test_ohlcv_raw_follows_capped_answers():
    first = NOW // DAY * DAY - 3000 * DAY
    cz = FakeCZ({"A": first, "B": first + 2000 * DAY})
    h = probe.ohlcv_raw(cz, ["A", "B"], "daily", probe.START_2010, NOW, DAY)
    assert min(h["A"]) == first and len(h["A"]) == 3001
    assert min(h["B"]) == first + 2000 * DAY
    assert len(cz.requests) >= 3


def test_cvd_stats_delta_ratio_and_units():
    today = NOW // DAY * DAY
    pts = {t: point(t) for t in range(today - 400 * DAY, today + 1, DAY)}      # dziś = niepełny dzień
    pts[today - 400 * DAY]["bv"] = None
    st = probe.cvd_stats(pts, NOW, "base")
    assert st["last"] == today - DAY and st["n"] == 400
    assert st["bv_first"] == today - 399 * DAY and st["bv_share"] == 1.0
    assert abs(st["ratio_med"] - 0.55) < 1e-9 and st["half_share"] == 0
    assert st["last_usd"] == 100 * 80_000 and st["last_delta_usd"] == 10 * 80_000
    assert st["cvd30"] == 30 * 10 * 80_000 and st["cvd365"] == 365 * 10 * 80_000
    assert st["tx"] and "bv" in st["fields"]
    q = probe.cvd_stats(pts, NOW, "quote")              # wolumen już w USD (kontrakty odwrotne)
    assert q["last_usd"] == 100 and q["cvd30"] == 300


def test_cvd_stats_flags_fake_half_split():
    today = NOW // DAY * DAY
    pts = {t: point(t, bv=50.0) for t in range(today - 50 * DAY, today, DAY)}
    st = probe.cvd_stats(pts, NOW)
    assert st["half_share"] == 1.0 and st["cvd30"] == 0


def test_parse_vision_klines_header_and_microseconds():
    t = 1_790_000_000 // DAY * DAY
    text = ("open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
            "taker_buy_quote_volume,ignore\n"
            f"{t * 1000},1,2,0.5,1.5,100,0,150,1000,55,82,0\n"
            f"{(t + DAY) * 1_000_000},1,2,0.5,1.5,200,0,300,2000,90,135,0\n")
    rows = probe.parse_vision_klines(text)
    assert sorted(rows) == [t, t + DAY] and rows[t + DAY][9] == 90


def _zip(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", text)
    return buf.getvalue()


class Resp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


class VisionSession:
    def __init__(self, files):
        self.files = files           # {url suffix: csv text}
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        for k, text in self.files.items():
            if url.endswith(k):
                return Resp(200, _zip(text))
        return Resp(404)


def test_check_cvd_end_to_end():
    today = NOW // DAY * DAY
    first = today - 800 * DAY
    cz = FakeCZ({"BTCUSDT.A": first, "BTCUSD.C": first, "BTCUSDT_PERP.A": first, "BTCUSD_PERP.A": first})
    month = probe._months_back(NOW, 1)[0]
    lines = "\n".join(f"{t * 1000},1,1,1,80000,100,0,8000000,1000,55,4400000,0"
                      for t in range(today - 40 * DAY, today, DAY))
    sess = VisionSession({f"spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-{month}.zip": lines})
    rows = probe.check_cvd(session=sess, client=cz, now=NOW)
    items = {r["item"]: r for r in rows}
    sol = [r for r in rows if "SOLUSDT.6" in r["item"]][0]
    assert sol["status"] == "brak" and "has_buy_sell_data" in sol["note"]
    btc = [r for r in rows if r["item"].startswith("BTC spot Binance (BTCUSDT.A")][0]
    assert btc["status"] == "ok" and btc["first"] is not None and "1h:" in btc["note"]
    assert "bv od" in btc["note"] and "CVD 30 dni" in btc["note"]
    cmp_ = [r for r in rows if "archiwum Binance spot/BTCUSDT" in r["item"]][0]
    assert cmp_["status"] == "ok" and "bv ÷ taker_buy(coiny) 1.000" in cmp_["note"]
    assert "v ÷ volume(coiny) 1.000" in cmp_["note"]
    um = [r for r in rows if "archiwum Binance um/BTCUSDT" in r["item"]][0]
    assert um["status"] == "brak"
    cm = [r for r in rows if "archiwum Binance cm/BTCUSD_PERP" in r["item"]]
    assert cm and cm[0]["status"] == "brak"
    summ = items["BTC"]
    assert summ["source"] == "cvd-podsumowanie" and summ["status"] == "ok" and "spot z bv 2" in summ["note"]
    assert items["SOL"]["status"] == "niepełne"
    assert any(r["item"] == "zużyte zapytania Coinalyze" for r in rows)
    md = probe.to_markdown({"where": "github", "at": "x", "seconds": 1, "rows": rows})
    assert "| cvd-podsumowanie | BTC | ok |" in md


def test_probe_cvd_in_github_checks():
    assert "cvd" in probe.CHECKS["github"] and "cvd" in probe.FUNCS and "cvd" not in probe.CHECKS["pi"]
