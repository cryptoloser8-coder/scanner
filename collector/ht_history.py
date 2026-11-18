"""Pobieranie historii grup HyperTrackera na Orange Pi (poprawka 87).

Jednorazowe ściągnięcie historii metryk grup (zarabiający / tracący) dla coinów krypto Hyperliquid,
porcjami w darmowym limicie HyperTrackera (100 zapytań na dobę), plus raz na dobę stan wszystkich grup
(kafelek „Dla porównania” w zakładce Dźwignia).

    python3 collector/ht_history.py run       # z ema_cron.sh co 5 min: kilka zapytań na przebieg, aż do dziennego limitu
    python3 collector/ht_history.py status    # stan pobierania (nic nie pobiera)

Kolejność: etap 1 — grupy 9 (zarobili $100k–1M) i 14 (stracili $100k–1M), etap 2 — 8 (ponad $1M zysku)
i 15 (ponad $1M straty). Coiny: najpierw BTC, ETH, HYPE, SOL, DOGE, TAO, potem reszta krypto z głównej giełdy HL
wg OI malejąco (OI ≥ $5M; lista ustalana raz, przy pierwszym uruchomieniu). Historia od 19.02.2026 (początek danych HT).

Regulamin HyperTrackera: redystrybucja surowych danych wymaga umowy → surowe dane zostają na Pi
(pi/hypertracker/, poza Gitem). Na gałąź `ht` idą tylko nasze zestawienia (udział longów, kwoty longów i shortów
grup co 4 h, postęp pobierania, ostatni stan grup) z dopiskiem „Powered by HyperTracker”.

Klucz: HYPERTRACKER_API_KEY w pi/scanner_env (jedna linia: HYPERTRACKER_API_KEY=...). Bez klucza — nic nie robi.
Wiadomości do admina (Telegram): koniec etapu, odrzucony klucz, koniec całości.
"""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import pi_dirs as _pd
except ImportError:
    _pd = None

log = logging.getLogger("ht_history")
HT = "https://ht-api.coinmarketman.com/api/external"
HL_INFO = "https://api.hyperliquid.xyz/info"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) scanner-ht"}
START = "2026-01-01T00:00:00Z"        # HT ma dane od 19.02.2026 — wcześniejszy start nic nie kosztuje
SEPARATE = ("BTC", "ETH", "HYPE", "SOL", "DOGE", "TAO")
STAGES = ((9, 14), (8, 15))
SEG_NAME = {8: "zarobili ponad $1M", 9: "zarobili $100k–1M", 14: "stracili $100k–1M", 15: "stracili ponad $1M"}
MIN_OI = 5e6
DAY_BUDGET = 92                       # z 100: 1 na stan grup, reszta zapasu na ponowienia
PER_RUN = 8                           # zapytań na jeden przebieg z crona (co 5 min)
PAGES_GUESS = 23                      # stron na serię (sonda 86: BTC Smart Money 23 strony)
BUCKET = 4 * 3600                     # zestawienia na stronę: co 4 h
PUBLISH_EVERY = 6 * 3600
BRANCH = "ht"                         # HyperTracker osobno; gałąź `hl` = nasze dane z Hyperliquid (GitHub)


def now_ts():
    return time.time()


def day_key(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def iso_ts(s):
    """'2026-11-18T00:16:04.576Z' → sekundy UTC."""
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


def base_dir():
    root = _pd.PI if _pd else os.path.join(os.path.dirname(HERE), "pi")
    return os.path.join(root, "hypertracker")


def load_env():
    if os.environ.get("HYPERTRACKER_API_KEY"):
        return
    path = _pd.env_file() if _pd else os.path.expanduser("~/.scanner_env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


def clean_key(k):
    k = (k or "").strip().strip('"').strip("'").strip()
    return k[7:].strip() if k.lower().startswith("bearer ") else k


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


# ── kolejka ──────────────────────────────────────────────────
def crypto_coins(session, min_oi=MIN_OI):
    """Coiny krypto głównej giełdy HL z OI ≥ min_oi: najpierw 6 osobnych, potem reszta wg OI malejąco."""
    r = session.post(HL_INFO, json={"type": "metaAndAssetCtxs"}, headers=UA, timeout=30)
    r.raise_for_status()
    meta, ctxs = r.json()
    rows = []
    for a, c in zip(meta.get("universe") or [], ctxs or []):
        nm = a.get("name") or ""
        if ":" in nm or a.get("isDelisted"):
            continue
        try:
            oi = float(c.get("openInterest")) * float(c.get("markPx"))
        except (TypeError, ValueError):
            continue
        rows.append((oi, nm))
    rows.sort(reverse=True)
    rest = [nm for oi, nm in rows if oi >= min_oi and nm not in SEPARATE]
    return [c for c in SEPARATE if any(nm == c for _, nm in rows)] + rest, {nm: round(oi) for oi, nm in rows}


def make_queue(coins):
    q = []
    for stage, segs in enumerate(STAGES, 1):
        for c in coins:
            for s in segs:
                q.append({"stage": stage, "seg": s, "coin": c, "cursor": None, "pages": 0, "done": False,
                          "first": None, "last": None, "n": 0})
    return q


# ── HyperTracker ─────────────────────────────────────────────
class Budget(Exception):
    pass


class KeyRejected(Exception):
    pass


def ht_get(session, key, path, params, st, now):
    d = day_key(now)
    used = st.setdefault("calls", {}).get(d, 0)
    if used >= DAY_BUDGET + 1:
        raise Budget(f"limit dzienny ({used} zapytań {d})")
    st["calls"][d] = used + 1
    for k in list(st["calls"]):                    # trzymamy 40 dni liczników
        if k < day_key(now - 40 * 86400):
            del st["calls"][k]
    r = session.get(HT + path, params=params, timeout=60,
                    headers=dict(UA, Authorization=f"Bearer {key}", Accept="application/json"))
    if r.status_code == 200:
        return r.json()
    if r.status_code in (401, 403):
        raise KeyRejected(f"HTTP {r.status_code}")
    if r.status_code == 429:
        st["calls"][d] = DAY_BUDGET + 1            # dziś już nic
        raise Budget("HTTP 429 — limit HyperTrackera")
    raise RuntimeError(f"HTTP {r.status_code} {(r.text or '')[:120]}")


POINT_KEYS = ("positionCount", "positionCountLong", "totalPositionValue", "totalPositionValueLong",
              "totalUnrealizedPnl", "totalFunding")


def merge_points(raw, items):
    """raw: {ts: [count, countLong, value, valueLong, upnl, funding]} ← elementy odpowiedzi HT."""
    added = 0
    for it in items or []:
        try:
            t = iso_ts(it["createdAt"])
        except (KeyError, TypeError, ValueError):
            continue
        k = str(t)
        if k not in raw:
            added += 1
        raw[k] = [it.get(x) for x in POINT_KEYS]
    return added


def step_task(session, key, task, st, now, ddir):
    """Jedna strona historii jednej serii (grupa × coin). Zwraca True, gdy seria skończona."""
    params = {"start": START, "limit": 1000}
    if task["cursor"]:
        params["nextCursor"] = task["cursor"]
    obj = ht_get(session, key, f"/position-metrics/coin/{task['coin']}/segment/{task['seg']}", params, st, now)
    items = (obj or {}).get("metrics") or []
    path = os.path.join(ddir, "raw", f"{task['seg']}_{task['coin']}.json")
    raw = _read(path, {})
    task["n"] += merge_points(raw, items)
    _write(path, raw)
    task["pages"] += 1
    ts = sorted(int(k) for k in raw)
    if ts:
        task["first"], task["last"] = ts[0], ts[-1]
    task["cursor"] = (obj or {}).get("nextCursor")
    if not task["cursor"] or not items:
        task["done"] = True
        task["cursor"] = None
    return task["done"]


# ── zestawienia na stronę (gałąź ht) ─────────────────────────
def bucketize(raw, bucket=BUCKET):
    """{ts: punkt} → [[t_kubełka, %long, longi $, shorty $, portfele, portfele long]] — ostatni punkt w kubełku."""
    out = {}
    for k in sorted(raw, key=int):
        p = raw[k]
        tot, lv = p[2], p[3]
        if tot is None or lv is None:
            continue
        b = int(k) // bucket * bucket
        out[b] = [b, round(lv / tot * 100, 2) if tot else None, round(lv), round(tot - lv), p[0], p[1]]
    return [out[b] for b in sorted(out)]


def build_public(st, ddir, now):
    """Zestawienia: postęp + serie 6 coinów osobno + koszyk altów (gdy pobrane wszystkie jego coiny) + stan grup."""
    coins = st.get("coins") or []
    basket = [c for c in coins if c not in SEPARATE]
    q = st.get("queue") or []
    done = {(t["seg"], t["coin"]) for t in q if t["done"]}
    series = {}
    for seg in sorted({t["seg"] for t in q}):
        for c in SEPARATE:
            if (seg, c) in done:
                raw = _read(os.path.join(ddir, "raw", f"{seg}_{c}.json"), {})
                b = bucketize(raw)
                series[f"ht{seg}_{c}_lpct"] = [[x[0], x[1]] for x in b]
                series[f"ht{seg}_{c}_long"] = [[x[0], x[2]] for x in b]
                series[f"ht{seg}_{c}_short"] = [[x[0], x[3]] for x in b]
        if basket and all((seg, c) in done for c in basket):
            agg = {}
            for c in basket:
                for x in bucketize(_read(os.path.join(ddir, "raw", f"{seg}_{c}.json"), {})):
                    a = agg.setdefault(x[0], [0, 0])
                    a[0] += x[2]
                    a[1] += x[3]
            ks = sorted(agg)
            series[f"ht{seg}_ALT_lpct"] = [[k, round(agg[k][0] / (agg[k][0] + agg[k][1]) * 100, 2)
                                            if agg[k][0] + agg[k][1] else None] for k in ks]
            series[f"ht{seg}_ALT_long"] = [[k, agg[k][0]] for k in ks]
            series[f"ht{seg}_ALT_short"] = [[k, agg[k][1]] for k in ks]
    return {"series": series}, progress(st, now)


def progress(st, now):
    q = st.get("queue") or []
    coins = st.get("coins") or []
    pages_done = sum(t["pages"] for t in q)
    done_tasks = [t for t in q if t["done"]]
    avg_pages = (sum(t["pages"] for t in done_tasks) / len(done_tasks)) if done_tasks else PAGES_GUESS
    left = sum(max(0, round(avg_pages) - t["pages"]) if not t["done"] else 0 for t in q)
    days = [v for k, v in (st.get("calls") or {}).items() if k < day_key(now)]
    per_day = (sum(days[-7:]) / len(days[-7:])) if days else DAY_BUDGET
    per_day = max(1, per_day - 1)                  # 1 dziennie na stan grup
    eta = now + left / per_day * 86400 if left else now
    cur = next((t for t in q if not t["done"]), None)

    def stage_info(stage):
        tasks = [t for t in q if t["stage"] == stage]
        full = [c for c in coins if all(t["done"] for t in tasks if t["coin"] == c)]
        return {"segs": list(STAGES[stage - 1]), "coins_done": full, "coins_total": len(coins),
                "done": bool(tasks) and all(t["done"] for t in tasks)}
    return {"updated": int(now), "start_hist": "2026-02-19", "coins": coins,
            "stage": cur["stage"] if cur else None, "current": {"coin": cur["coin"], "seg": cur["seg"]} if cur else None,
            "pages_done": pages_done, "pages_est": pages_done + left, "pct": round(pages_done / max(1, pages_done + left) * 100, 1),
            "eta": day_key(eta) if left else None, "per_day": round(per_day, 1),
            "stages": {str(s): stage_info(s) for s in (1, 2)}, "complete": cur is None and bool(q),
            "seg_names": {str(k): v for k, v in SEG_NAME.items()}, "attribution": "Powered by HyperTracker",
            "last_page_at": st.get("last_page_at")}


def publish(ddir, st, now, remote=None, runner=subprocess.run):
    series, prog = build_public(st, ddir, now)
    pub = os.path.join(ddir, "pub")
    _write(os.path.join(pub, "ht_groups.json"), series)
    _write(os.path.join(pub, "ht_progress.json"), prog)
    summ = _read(os.path.join(ddir, "summary_latest.json"), None)
    if summ:
        _write(os.path.join(pub, "ht_summary.json"), summ)
    if remote is None:
        tok_file = _pd.token_file() if _pd else os.path.expanduser("~/.scanner_token")
        with open(tok_file, encoding="utf-8") as f:
            tok = f.read().strip()
        remote = f"https://x-access-token:{tok}@github.com/cryptoloser8-coder/scanner.git"
    env = dict(os.environ, DATA_BRANCH=BRANCH, GIT_AUTHOR_NAME="ht-history-pi", GIT_AUTHOR_EMAIL="ht-history@users.noreply.github.com")
    tmp = tempfile.mkdtemp(prefix="hl-pub-")                # publish.sh robi git init w katalogu — kopia bez .git
    for fn in os.listdir(pub):
        if fn.endswith(".json"):
            with open(os.path.join(pub, fn), "rb") as a, open(os.path.join(tmp, fn), "wb") as b:
                b.write(a.read())
    r = runner(["bash", os.path.join(HERE, "publish.sh"), tmp, remote], env=env, capture_output=True, text=True)
    shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        raise RuntimeError(((r.stderr or r.stdout) or "")[-300:].replace(remote, "<remote>"))
    st["published_at"] = int(now)
    st["summary_published"] = st.get("summary_day")


def summarize_state(obj, now):
    """/state/summary → zwięzły stan grup na kafelek (udział longów, kwoty, liczba kont)."""
    out = {"at": int(now), "attribution": "Powered by HyperTracker", "groups": []}
    for g in (obj or {}).get("segments") or []:
        seg = g.get("segment") or {}
        lv, sv = g.get("positionLongValue"), g.get("positionShortValue")
        out["groups"].append({"id": g.get("segmentId"), "name": seg.get("name"), "category": seg.get("category"),
                              "criteria": seg.get("criteria"), "long": lv, "short": sv,
                              "lpct": round(lv / (lv + sv) * 100, 1) if lv is not None and sv and lv + sv else None,
                              "traders": g.get("countTraders"), "in_position": g.get("countTradersInPosition"),
                              "lev": g.get("exposureRatio")})
    out["traders"] = (obj or {}).get("countTraders")
    out["active"] = (obj or {}).get("countActiveTraders")
    return out


# ── przebieg ─────────────────────────────────────────────────
def notify(text, telegram=None):
    try:
        if telegram is None:
            import alerts
            telegram = alerts.Telegram()
        telegram.post("system", text)
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram: %s", e)


def run(session=None, now=None, ddir=None, telegram=None, per_run=PER_RUN, publish_fn=publish):
    load_env()
    key = clean_key(os.environ.get("HYPERTRACKER_API_KEY", ""))
    if not key:
        return "brak klucza HYPERTRACKER_API_KEY w pi/scanner_env — nic nie robię"
    s = session or requests.Session()
    now = now or now_ts()
    ddir = ddir or base_dir()
    os.makedirs(ddir, exist_ok=True)
    spath = os.path.join(ddir, "state.json")
    st = _read(spath, {})
    if st.get("key_rejected") == key[-6:]:
        return "klucz odrzucony wcześniej — czekam na nowy klucz"
    msgs = []
    if not st.get("queue"):
        try:
            coins, oi = crypto_coins(s)
        except Exception as e:  # noqa: BLE001
            return f"nie mogę pobrać listy coinów z Hyperliquid: {e}"
        st.update({"coins": coins, "oi_at_start": oi, "queue": make_queue(coins), "started": int(now)})
        msgs.append(f"🛰 HyperTracker: start pobierania historii — {len(coins)} coinów, {len(st['queue'])} serii.")
    calls0 = sum((st.get("calls") or {}).values())
    try:
        # 1) raz na dobę: stan wszystkich grup
        if st.get("summary_day") != day_key(now):
            obj = ht_get(s, key, "/state/summary", None, st, now)
            summ = summarize_state(obj, now)
            _write(os.path.join(ddir, "summary_latest.json"), summ)
            _write(os.path.join(ddir, "summary", day_key(now) + ".json"), obj)
            st["summary_day"] = day_key(now)
        # 2) porcja historii
        n = 0
        while n < per_run:
            task = next((t for t in st["queue"] if not t["done"]), None)
            if task is None:
                break
            stage_before = task["stage"]
            step_task(s, key, task, st, now, ddir)
            st["last_page_at"] = int(now)
            n += 1
            nxt = next((t for t in st["queue"] if not t["done"]), None)
            if task["done"] and (nxt is None or nxt["stage"] != stage_before):
                segs = " i ".join(SEG_NAME[x] for x in STAGES[stage_before - 1])
                msgs.append(f"✅ HyperTracker: etap {stage_before} gotowy — historia grup „{segs}” dla "
                            f"{len(st['coins'])} coinów." + ("" if nxt else " Całość pobrana."))
    except Budget as e:
        log.info("Stop: %s", e)
    except KeyRejected as e:
        st["key_rejected"] = key[-6:]
        msgs.append(f"⛔ HyperTracker odrzucił klucz ({e}). Pobieranie historii wstrzymane — wygeneruj nowy klucz "
                    "i wpisz go w pi/scanner_env (HYPERTRACKER_API_KEY=...).")
    except Exception as e:  # noqa: BLE001
        log.warning("Błąd: %s", e)
        st.setdefault("errors", []).append([int(now), str(e)[:200]])
        st["errors"] = st["errors"][-20:]
    _write(spath, st)
    for m in msgs:
        notify(m, telegram)
    used = sum((st.get("calls") or {}).values()) - calls0
    complete = all(t["done"] for t in st["queue"])
    pending = (st.get("last_page_at") or 0) > (st.get("published_at") or 0) or \
        (st.get("summary_day") and st.get("summary_published") != st.get("summary_day"))
    # 87c: publikuj też po wyczerpaniu dziennego limitu, jeśli są nieopublikowane porcje (wcześniej tylko przy nowych zapytaniach)
    if (used or pending) and (now - st.get("published_at", 0) >= PUBLISH_EVERY or complete or msgs):
        try:
            publish_fn(ddir, st, now)
            _write(spath, st)
        except Exception as e:  # noqa: BLE001
            log.warning("Publikacja: %s", e)
    p = progress(st, now)
    return f"zapytań teraz {used}; postęp {p['pct']}% ({p['pages_done']}/{p['pages_est']} stron), koniec ok. {p['eta']}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("run", "status"))
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.cmd == "status":
        st = _read(os.path.join(base_dir(), "state.json"), {})
        print(json.dumps(progress(st, now_ts()), ensure_ascii=False, indent=1))
        return 0
    print(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
