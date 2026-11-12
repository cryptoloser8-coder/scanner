"""Minimal TradingView websocket client for CRYPTOCAP index bars.

Unofficial protocol (the same one the TradingView web app uses), no login,
so it may break if TradingView changes it — the collector treats failures
as a soft error and reports them on Telegram.
"""
import json
import logging
import random
import re
import string
import time

log = logging.getLogger("tradingview")

WS_URL = "wss://data.tradingview.com/socket.io/websocket"
_FRAME = re.compile(r"~m~(\d+)~m~")


class TradingViewError(RuntimeError):
    pass


def _rand(prefix):
    return prefix + "".join(random.choice(string.ascii_lowercase) for _ in range(12))


def _frame(func, params):
    msg = json.dumps({"m": func, "p": params}, separators=(",", ":"))
    return f"~m~{len(msg)}~m~{msg}"


def split_frames(raw):
    """Split a websocket payload into individual frames."""
    out, i = [], 0
    while True:
        m = _FRAME.match(raw, i)
        if not m:
            break
        n = int(m.group(1))
        start = m.end()
        out.append(raw[start:start + n])
        i = start + n
    return out


class TradingView:
    def __init__(self, timeout=30, connect=None):
        self.timeout = timeout
        self._connect = connect  # injectable for tests

    def _open(self):
        if self._connect:
            return self._connect()
        from websocket import create_connection
        return create_connection(
            WS_URL, timeout=self.timeout,
            header=["Origin: https://www.tradingview.com"],
        )

    def ohlc_bars(self, symbol, interval="1D", n_bars=20000):
        """[(t, (open, high, low, close))] — knoty (poprawka 56)."""
        return self.bars(symbol, interval, n_bars, ohlc=True)

    def bars(self, symbol, interval="60", n_bars=5000, ohlc=False):
        """Return [(t, close)] — interval '60' = 1h, '1D' = daily; ohlc=True → [(t, (open, high, low, close))]."""
        ws = self._open()
        cs = _rand("cs_")
        try:
            for func, params in (
                ("set_auth_token", ["unauthorized_user_token"]),
                ("chart_create_session", [cs, ""]),
                ("resolve_symbol", [cs, "sym1", "=" + json.dumps(
                    {"symbol": symbol, "adjustment": "splits"})]),
                ("create_series", [cs, "s1", "s1", "sym1", interval, int(n_bars)]),
            ):
                ws.send(_frame(func, params))

            bars = {}
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                raw = ws.recv()
                if not raw:
                    continue
                for fr in split_frames(raw):
                    if fr.startswith("~h~"):  # heartbeat → echo back
                        ws.send(f"~m~{len(fr)}~m~{fr}")
                        continue
                    try:
                        msg = json.loads(fr)
                    except ValueError:
                        continue
                    m = msg.get("m") if isinstance(msg, dict) else None
                    if m in ("timescale_update", "du"):
                        p = msg.get("p", [])
                        s1 = (p[1] if len(p) > 1 else {}).get("s1", {}) or {}
                        for b in s1.get("s", []) or []:
                            v = b.get("v") or []
                            if len(v) >= 5:
                                bars[int(v[0])] = (tuple(float(x) for x in v[1:5]) if ohlc else float(v[4]))
                    elif m in ("symbol_error", "series_error", "critical_error", "protocol_error"):
                        raise TradingViewError(f"{symbol}: {m} {msg.get('p')}")
                    elif m == "series_completed":
                        if not bars:
                            raise TradingViewError(f"{symbol}: brak danych")
                        return sorted(bars.items())
            raise TradingViewError(f"{symbol}: timeout")
        finally:
            try:
                ws.close()
            except Exception:
                pass
