"""Coinalyze REST client + futures-universe selection."""
import logging
import re
import time
from collections import deque

import requests

log = logging.getLogger("coinalyze")

BASE_URL = "https://api.coinalyze.net/v1"
MAX_SYMBOLS_PER_REQUEST = 20


class CoinalyzeError(RuntimeError):
    pass


class RateLimiter:
    """Coinalyze counts every symbol in a request as one call (40 calls / minute / key)."""

    def __init__(self, calls_per_minute=38, clock=time.monotonic, sleep=time.sleep):
        self.limit = calls_per_minute
        self.calls = deque()  # (timestamp, cost)
        self.clock = clock
        self.sleep = sleep

    def acquire(self, cost):
        while True:
            now = self.clock()
            while self.calls and now - self.calls[0][0] >= 60:
                self.calls.popleft()
            used = sum(c for _, c in self.calls)
            if used + cost <= self.limit:
                self.calls.append((now, cost))
                return
            wait = 60 - (now - self.calls[0][0]) + 0.05
            self.sleep(max(wait, 0.05))


class Coinalyze:
    def __init__(self, api_key, calls_per_minute=38, session=None, sleep=time.sleep):
        if not api_key:
            raise CoinalyzeError("Brak COINALYZE_API_KEY")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.sleep = sleep
        self.limiter = RateLimiter(calls_per_minute, sleep=sleep)
        self.calls_made = 0

    def _get(self, path, params=None, cost=1):
        params = dict(params or {})
        for attempt in range(6):
            self.limiter.acquire(cost)
            try:
                r = self.session.get(
                    f"{BASE_URL}{path}", params=params,
                    headers={"api_key": self.api_key}, timeout=60,
                )
            except requests.RequestException as e:
                log.warning("%s: błąd sieci (%s), ponawiam", path, e)
                self.sleep(min(2 ** attempt * 2, 60))
                continue
            self.calls_made += cost
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", "10") or 10)
                log.warning("429 rate limit, czekam %.0fs", wait)
                self.sleep(wait + 0.5)
                continue
            if r.status_code == 401:
                raise CoinalyzeError("Nieprawidłowy klucz Coinalyze (401)")
            if r.status_code >= 500:
                log.warning("%s: %s, ponawiam", path, r.status_code)
                self.sleep(min(2 ** attempt * 3, 60))
                continue
            raise CoinalyzeError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
        raise CoinalyzeError(f"{path}: zbyt wiele nieudanych prób")

    # ── endpoints ────────────────────────────────────────────
    def exchanges(self):
        return self._get("/exchanges")

    def future_markets(self):
        return self._get("/future-markets")

    def open_interest(self, symbols):
        """Current OI in USD → {symbol: value}."""
        out = {}
        for batch in _chunks(symbols, MAX_SYMBOLS_PER_REQUEST):
            data = self._get("/open-interest", {
                "symbols": ",".join(batch), "convert_to_usd": "true",
            }, cost=len(batch))
            for row in data or []:
                if row.get("value") is not None:
                    out[row["symbol"]] = float(row["value"])
        return out

    def oi_history(self, symbols, interval, frm, to, progress=None):
        """OI history in USD → {symbol: {t: close}}."""
        out = {}
        batches = list(_chunks(symbols, MAX_SYMBOLS_PER_REQUEST))
        for i, batch in enumerate(batches):
            data = self._get("/open-interest-history", {
                "symbols": ",".join(batch), "interval": interval,
                "from": int(frm), "to": int(to), "convert_to_usd": "true",
            }, cost=len(batch))
            for row in data or []:
                hist = {}
                for p in row.get("history") or []:
                    c = p.get("c")
                    if c is not None:
                        hist[int(p["t"])] = float(c)
                out[row["symbol"]] = hist
            if progress and (i % 10 == 0 or i == len(batches) - 1):
                progress(i + 1, len(batches))
        return out


def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ── universe ─────────────────────────────────────────────────
_PREFIX = re.compile(r"^(1000000|100000|10000|1000|1M)(?=[A-Z])")


def norm_base(asset):
    """Normalise contract base assets: kPEPE/1000PEPE → PEPE, XBT → BTC."""
    a = (asset or "").strip()
    if len(a) > 1 and a[0] == "k" and a[1:].isupper():
        a = a[1:]
    a = a.upper()
    a = _PREFIX.sub("", a)
    return {"XBT": "BTC"}.get(a, a)


def _norm_name(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def select_markets(exchanges, markets, wanted_exchanges):
    """Perpetual markets on the wanted exchanges → {symbol: base}."""
    wanted = [_norm_name(w) for w in wanted_exchanges]
    codes = set()
    for ex in exchanges:
        n = _norm_name(ex.get("name"))
        if any(n.startswith(w) or w.startswith(n) for w in wanted if w and n):
            codes.add(ex.get("code"))
    out = {}
    for m in markets:
        if not m.get("is_perpetual"):
            continue
        if m.get("exchange") not in codes:
            continue
        base = norm_base(m.get("base_asset"))
        if base:
            out[m["symbol"]] = base
    return out


def build_universe(client, cfg, log_fn=log.info):
    """Pick markets to track. With max_assets > 0 we rank assets by current OI."""
    exchanges = client.exchanges()
    markets = client.future_markets()
    sym_base = select_markets(exchanges, markets, cfg["exchanges"])
    log_fn(f"Coinalyze: {len(sym_base)} rynków perp na wybranych giełdach")
    max_assets = int(cfg.get("max_assets") or 0)
    ranking = {}
    if max_assets > 0 and sym_base:
        current = client.open_interest(list(sym_base))
        for sym, v in current.items():
            ranking[sym_base[sym]] = ranking.get(sym_base[sym], 0.0) + v
        top = sorted(ranking, key=ranking.get, reverse=True)[:max_assets]
        keep = set(top) | {"BTC", "ETH"}
        coverage = sum(ranking[a] for a in keep if a in ranking) / max(sum(ranking.values()), 1)
        sym_base = {s: b for s, b in sym_base.items() if b in keep}
        log_fn(f"Coinalyze: top {max_assets} coinów → {len(sym_base)} rynków, "
               f"pokrycie OI {coverage:.1%}")
    return {"symbols": sym_base, "ranking": ranking}
