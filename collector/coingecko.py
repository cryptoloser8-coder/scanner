"""CoinGecko: list of crypto symbols (top N by market cap) used to filter out
TradFi perps (gold, oil, stocks) that crypto exchanges now list."""
import logging
import os
import time

import requests

log = logging.getLogger("coingecko")
URL = "https://api.coingecko.com/api/v3/coins/markets"


def crypto_symbols(top_n=1500, session=None, sleep=time.sleep):
    """Upper-case symbols of the top_n coins by market cap. Raises on failure."""
    s = session or requests.Session()
    key = os.environ.get("COINGECKO_API_KEY", "")
    headers = {"x-cg-demo-api-key": key} if key else {}
    out = set()
    pages = max(1, (int(top_n) + 249) // 250)
    for page in range(1, pages + 1):
        for attempt in range(6):
            try:
                r = s.get(URL, params={"vs_currency": "usd", "order": "market_cap_desc",
                                       "per_page": 250, "page": page}, headers=headers, timeout=30)
            except requests.RequestException as e:  # flaky connections from CI runners
                log.warning("CoinGecko strona %d: błąd sieci (%s), ponawiam", page, e)
                sleep(min(10 * (attempt + 1), 60))
                continue
            if r.status_code == 200:
                break
            if r.status_code == 429 or r.status_code >= 500:
                sleep(min(15 * (attempt + 1), 60))
                continue
            raise RuntimeError(f"CoinGecko HTTP {r.status_code}: {r.text[:200]}")
        else:
            raise RuntimeError("CoinGecko: zbyt wiele nieudanych prób")
        for c in r.json() or []:
            if c.get("symbol"):
                out.add(c["symbol"].upper())
        sleep(3)  # be gentle with the keyless API
    log.info("CoinGecko: %d symboli krypto (top %d)", len(out), top_n)
    return out
