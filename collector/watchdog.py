"""Independent watchdog on GitHub (workflow „Watchdog”, every ~3 h).

The Orange Pi publishes EMA/Fibo and also starts the OI scans — when it is off, nobody else notices.
This checks the age of ema.json (branch `ema`) and meta.json (branch `data`) and writes to the admin
(private chat) while something is stale. No state: while the problem lasts it repeats every ~3 h.

  python collector/watchdog.py --repo owner/name
"""
import argparse
import logging
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alerts  # noqa: E402

log = logging.getLogger("watchdog")
HOUR = 3600
LIMITS = {"ema": 1 * HOUR, "data": 4 * HOUR}


def check(fetch, now):
    """fetch(branch, file) → dict | None. → list of problems (Polish text)."""
    out = []
    ema = fetch("ema", "ema.json")
    if not ema or not ema.get("updated"):
        out.append("nie da się odczytać danych EMA/Fibo (gałąź ema)")
    elif now - ema["updated"] > LIMITS["ema"]:
        out.append(f"Orange Pi nie publikuje EMA/Fibo od {(now - ema['updated']) / HOUR:.1f} h "
                   "(Pi wyłączone, brak internetu albo błąd — log: ~/ema-monitor.log)")
    meta = fetch("data", "meta.json")
    if not meta or not meta.get("updated"):
        out.append("nie da się odczytać danych OI/TOTAL (gałąź data)")
    elif now - meta["updated"] > LIMITS["data"]:
        out.append(f"skany OI/TOTAL nie działają od {(now - meta['updated']) / HOUR:.1f} h "
                   "(uruchamia je Orange Pi: ~/scanner-bot.log; sprawdź też GitHub → Actions)")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = requests.Session()

    def fetch(branch, name):
        try:
            r = s.get(f"https://raw.githubusercontent.com/{a.repo}/{branch}/{name}",
                      params={"t": int(time.time())}, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("%s/%s: %s", branch, name, e)
            return None

    problems = check(fetch, time.time())
    if not problems:
        log.info("Wszystko świeże")
        return 0
    text = "🐶 <b>Watchdog</b>\n" + "\n".join(f"❗ {p}" for p in problems)
    log.warning(text)
    alerts.Telegram().post("system", text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
