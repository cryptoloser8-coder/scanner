"""Independent watchdog on GitHub (workflow „Watchdog”, every ~3 h).

The Orange Pi publishes EMA/Fibo and also starts the OI scans — when it is off, nobody else notices.
This checks the age of ema.json (branch `ema`) and meta.json (branch `data`) and writes to the admin
(private chat) while something is stale. No state: while the problem lasts it repeats every ~3 h.
Poprawka 84: także dane sieci (gałąź `chains`, raz na dobę) i ostatni raport (gałąź `reports`) — stały po cichu
(Sieci 15–17.11.2026). Tych dwóch nie zgłaszamy, gdy pliku nie da się odczytać (brak gałęzi, chwilowy błąd sieci).

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
LIMITS = {"ema": 1 * HOUR, "data": 4 * HOUR,
          "chains": 30 * HOUR,       # raz na dobę, przed raportem porannym (ten sam próg co w sieci.html)
          "reports": 20 * HOUR}      # poranny ~06:00 i wieczorny ~22:50 → najdłuższa zwykła przerwa ok. 17 h


def check(fetch, now, chains=True):
    """fetch(branch, file) → dict | None. → list of problems (Polish text).
    chains=False — sieci wyłączone w config.yaml (chains.enabled), nie sprawdzamy."""
    out = []
    ema = fetch("ema", "ema.json")
    if not ema or not ema.get("updated"):
        out.append("nie da się odczytać danych EMA/Fibo (gałąź ema)")
    elif now - ema["updated"] > LIMITS["ema"]:
        out.append(f"Orange Pi nie publikuje EMA/Fibo od {(now - ema['updated']) / HOUR:.1f} h "
                   "(Pi wyłączone, brak internetu albo błąd — log: ~/Crypto_Loser_analytics_tool/pi/logi/ema-monitor.log)")
    meta = fetch("data", "meta.json")
    if not meta or not meta.get("updated"):
        out.append("nie da się odczytać danych OI/TOTAL (gałąź data)")
    elif now - meta["updated"] > LIMITS["data"]:
        out.append(f"skany OI/TOTAL nie działają od {(now - meta['updated']) / HOUR:.1f} h "
                   "(uruchamia je Orange Pi: ~/Crypto_Loser_analytics_tool/pi/logi/scanner-bot.log; sprawdź też GitHub → Actions)")
    ch = fetch("chains", "chains.json") if chains else None
    if ch and ch.get("updated") and now - ch["updated"] > LIMITS["chains"]:
        out.append(f"dane sieci (DefiLlama) stoją od {(now - ch['updated']) / HOUR:.0f} h "
                   "(GitHub → Actions → Sieci; czerwony przebieg = błąd pobierania albo blokada bezpiecznika)")
    idx = fetch("reports", "index.json")
    last = max((r.get("created") or 0 for r in (idx or {}).get("reports") or []), default=0)
    if last and now - last > LIMITS["reports"]:
        out.append(f"ostatni raport powstał {(now - last) / HOUR:.0f} h temu "
                   "(GitHub → Actions → OI Monitor / Raport)")
    return out


def chains_enabled(path):
    """config.yaml → chains.enabled (domyślnie tak; błąd odczytu = tak)."""
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return bool(((yaml.safe_load(f) or {}).get("chains") or {}).get("enabled", True))
    except Exception:  # noqa: BLE001
        return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"))
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

    problems = check(fetch, time.time(), chains=chains_enabled(a.config))
    if not problems:
        log.info("Wszystko świeże")
        return 0
    text = "🐶 <b>Watchdog</b>\n" + "\n".join(f"❗ {p}" for p in problems)
    log.warning(text)
    alerts.Telegram().post("system", text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
