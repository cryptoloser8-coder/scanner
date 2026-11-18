"""Sonda Hyperliquid i HyperTracker (poprawka 85) — pozycje najlepszych portfeli vs reszta.

Uruchamiana tylko na życzenie: Actions → Sonda → only: „hypertracker hyperliquid”.
Nic nie zbiera na stałe — sprawdza, co i jak głęboko da się pobrać, ile to kosztuje (zapytania, czas, limity).

  hyperliquid  — darmowe API giełdy (bez klucza):
                 ranking (stats-data…/leaderboard): ile kont, jakie pola, ile waży,
                 pozycje (clearinghouseState) dla ~450 portfeli w 3 grupach: najlepsi od zawsze, najlepsi z 30 dni,
                 tracący (losowa próbka) → czas na portfel, odpowiedzi 429, pierwszy podgląd „najlepsi vs reszta”,
                 portfolio (historia PnL konta) — czy da się ustalić, kto był „najlepszy” w przeszłości (bez patrzenia w przyszłość),
                 userFillsByTime — jak daleko wstecz sięgają transakcje portfela.
  hypertracker — API HyperTracker (sekret HYPERTRACKER_API_KEY; darmowy plan ~100 zapytań na dobę, sonda zużywa ≤ 30):
                 specyfikacja OpenAPI (lista endpointów), grupy (segments), głębokość historii metryk grup dla BTC i HYPE,
                 pozycji, nastawienia (bias), ranking, ryzyko likwidacji, portfele, transakcje; nagłówki limitów.

Wynik: wiersze w probe.md + szczegóły (próbki odpowiedzi, specyfikacja, liczby grup) w probe.json → "extra".
Klucz nigdy nie trafia do wyniku.
"""
import os
import random
import time
from datetime import datetime, timezone

import requests

HL_INFO = "https://api.hyperliquid.xyz/info"
HL_BOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
HT_ROOT = "https://ht-api.coinmarketman.com/api"
HT = HT_ROOT + "/external"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) scanner-probe"}

GROUP_N = 150              # portfeli na grupę
TOP_MIN_AV = 100e3         # „najlepsi”: konto ≥ $100k
REST_MIN_AV = 10e3         # „tracący”: konto ≥ $10k i PnL od zawsze < 0
HT_BUDGET = 30             # najwyżej tyle zapytań do HyperTrackera w jednej sondzie
MAJORS = ("BTC", "ETH")


# ── narzędzia ────────────────────────────────────────────────
def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def usd(x):
    if x is None:
        return "—"
    a = abs(x)
    for lim, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if a >= lim:
            return f"${x / lim:.1f}{suf}"
    return f"${x:.0f}"


def to_ts(v):
    """Liczba (s / ms) albo tekst ISO → sekundy UTC; None, gdy to nie data."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        if 1.2e9 < v < 4e9:
            return int(v)
        if 1.2e12 < v < 4e12:
            return int(v / 1000)
        return None
    if isinstance(v, str) and len(v) >= 10 and v[4:5] == "-" and v[7:8] == "-":
        s = v[:19].replace(" ", "T")
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return int(datetime.strptime(s if "T" in fmt else s[:10], fmt).replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                continue
    return None


TIME_KEYS = ("timestamp", "time", "t", "snapshotTime", "bucket", "date", "ts", "createdAt", "openedAt", "updatedAt")


def item_ts(it):
    if not isinstance(it, dict):
        return None
    for k in TIME_KEYS:
        if k in it and to_ts(it[k]) is not None:
            return to_ts(it[k])
    for k, v in it.items():
        if any(w in k.lower() for w in ("time", "date", "at")) and to_ts(v) is not None:
            return to_ts(v)
    return None


def items_of(obj):
    """Lista rekordów z odpowiedzi (lista albo słownik z listą w data / items / results / …)."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in ("data", "items", "results", "rows", "positions", "metrics", "segments", "leaderboard", "wallets", "fills"):
            if isinstance(obj.get(k), list):
                return obj[k]
        for v in obj.values():
            if isinstance(v, list):
                return v
    return []


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M") if t else None


def _short(obj, depth=0):
    """Skrócona próbka do probe.json (bez długich list i tekstów)."""
    if isinstance(obj, dict):
        return {k: _short(v, depth + 1) for k, v in list(obj.items())[:40]}
    if isinstance(obj, list):
        out = [_short(v, depth + 1) for v in obj[:2 if depth else 3]]
        return out + ([f"… razem {len(obj)}"] if len(obj) > len(out) else [])
    if isinstance(obj, str) and len(obj) > 300:
        return obj[:300] + "…"
    return obj


# ── Hyperliquid ──────────────────────────────────────────────
class HLClient:
    def __init__(self, session=None, sleep=time.sleep, pause=0.12):
        self.s = session or requests.Session()
        self.sleep = sleep
        self.pause = pause
        self.calls = 0
        self.r429 = 0
        self.errors = 0

    def info(self, body):
        for attempt in range(4):
            self.calls += 1
            try:
                r = self.s.post(HL_INFO, json=body, headers=UA, timeout=30)
            except requests.RequestException:
                self.errors += 1
                self.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 200:
                self.sleep(self.pause)
                return r.json()
            if r.status_code == 429:
                self.r429 += 1
                self.sleep(10 * (attempt + 1))
                continue
            self.errors += 1
            if r.status_code >= 500:
                self.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {r.status_code} {r.text[:120]}")
        raise RuntimeError("zbyt wiele odpowiedzi 429 / 5xx / błędów sieci")


def board_rows(obj):
    """Ranking → [{addr, av, pnl: {day, week, month, allTime}, roi: {...}, vlm: {...}}]."""
    out = []
    for r in (obj.get("leaderboardRows") if isinstance(obj, dict) else obj) or []:
        perf = {}
        for w in r.get("windowPerformances") or []:
            if isinstance(w, (list, tuple)) and len(w) == 2 and isinstance(w[1], dict):
                perf[w[0]] = w[1]
        out.append({"addr": r.get("ethAddress"), "av": _f(r.get("accountValue")),
                    "pnl": {k: _f(v.get("pnl")) for k, v in perf.items()},
                    "roi": {k: _f(v.get("roi")) for k, v in perf.items()},
                    "vlm": {k: _f(v.get("vlm")) for k, v in perf.items()}})
    return out


def pick_groups(rows, n=GROUP_N, seed=17):
    big = [r for r in rows if r["addr"] and (r["av"] or 0) >= TOP_MIN_AV]
    top_all = sorted(big, key=lambda r: -(r["pnl"].get("allTime") or 0))[:n]
    top_30 = sorted(big, key=lambda r: -(r["pnl"].get("month") or 0))[:n]
    losers = [r for r in rows if r["addr"] and (r["av"] or 0) >= REST_MIN_AV and (r["pnl"].get("allTime") or 0) < 0]
    rest = random.Random(seed).sample(losers, min(n, len(losers)))
    return {"najlepsi od zawsze": top_all, "najlepsi 30 dni": top_30, "tracący (losowo)": rest}


def account_positions(state):
    """clearinghouseState → (wartość konta, [(coin, wartość pozycji ze znakiem, dźwignia)])."""
    ms = state.get("marginSummary") or {}
    av = _f(ms.get("accountValue"))
    pos = []
    for ap in state.get("assetPositions") or []:
        p = ap.get("position") or {}
        szi, val = _f(p.get("szi")), _f(p.get("positionValue"))
        if not szi or val is None:
            continue
        lev = p.get("leverage") or {}
        pos.append((p.get("coin"), abs(val) if szi > 0 else -abs(val), _f(lev.get("value"))))
    return av, pos


def group_stats(states):
    """Lista (av, pozycje) → liczby grupy: ile kont w pozycjach, long / short, dźwignia, udział altów, top coiny."""
    n = len(states)
    with_pos = [(av, pos) for av, pos in states if pos]
    long_ = sum(v for _, pos in with_pos for _, v, _ in pos if v > 0)
    short = -sum(v for _, pos in with_pos for _, v, _ in pos if v < 0)
    gross = long_ + short
    av_sum = sum(av or 0 for av, _ in with_pos)
    eff = [sum(abs(v) for _, v, _ in pos) / av for av, pos in with_pos if av and av > 0]
    set_lev = [lv for _, pos in with_pos for _, _, lv in pos if lv]
    per = {}
    for _, pos in with_pos:
        for c, v, _ in pos:
            d = per.setdefault(c, [0.0, 0.0])
            d[0 if v > 0 else 1] += abs(v)
    alts = sum(a + b for c, (a, b) in per.items() if c not in MAJORS)
    alt_long = sum(a for c, (a, b) in per.items() if c not in MAJORS)
    top = sorted(per.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:8]
    return {"n": n, "with_pos": len(with_pos), "long": long_, "short": short,
            "long_pct": long_ / gross * 100 if gross else None,
            "eff_lev": gross / av_sum if av_sum else None, "eff_lev_median": _median(eff),
            "set_lev_median": _median(set_lev), "alt_share": alts / gross * 100 if gross else None,
            "alt_long_pct": alt_long / alts * 100 if alts else None, "coins": len(per),
            "top": [{"coin": c, "ntl": a + b, "long_pct": a / (a + b) * 100 if a + b else None} for c, (a, b) in top]}


def _pct(x):
    return "—" if x is None else f"{x:.0f}%"


def _x(x):
    return "—" if x is None else f"×{x:.1f}"


def check_hyperliquid(session=None, sleep=time.sleep, extra=None, group_n=GROUP_N, now=None, **_):
    from probe import row, err_row
    extra = extra if extra is not None else {}
    ex = extra.setdefault("hyperliquid", {})
    s = session or requests.Session()
    hl = HLClient(s, sleep)
    rows = []
    now = now or time.time()

    # 1) rynki
    try:
        meta, ctxs = hl.info({"type": "metaAndAssetCtxs"})
        uni = meta.get("universe") or []
        oi = []
        for a, c in zip(uni, ctxs):
            px, o = _f(c.get("markPx")), _f(c.get("openInterest"))
            if px and o and not a.get("isDelisted"):
                oi.append((o * px, a.get("name")))
        oi.sort(reverse=True)
        tot = sum(v for v, _ in oi)
        alt = sum(v for v, nm in oi if nm not in MAJORS)
        rows.append(row("hyperliquid", "rynki perp (metaAndAssetCtxs)", "ok", n=len(oi),
                        note=f"OI razem {usd(tot)}, w altach {alt / tot * 100:.0f}%; największe: "
                             + ", ".join(f"{nm} {usd(v)}" for v, nm in oi[:8]) if tot else "brak OI"))
        ex["markets_oi_top"] = [{"coin": nm, "oi_usd": v} for v, nm in oi[:30]]
    except Exception as e:  # noqa: BLE001
        rows.append(err_row("hyperliquid", "rynki perp", e))

    # 2) ranking
    t = time.time()
    try:
        r = s.get(HL_BOARD, headers=UA, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} {r.text[:120]}")
        raw = r.json()
        board = board_rows(raw)
        mb = len(r.content) / 1e6
        first = (raw.get("leaderboardRows") or [{}])[0] if isinstance(raw, dict) else {}
        ex["leaderboard_sample"] = _short(first)
        n10 = sum(1 for b in board if (b["av"] or 0) >= 10e3)
        n100 = sum(1 for b in board if (b["av"] or 0) >= 100e3)
        n1m = sum(1 for b in board if (b["av"] or 0) >= 1e6)
        rows.append(row("hyperliquid", "ranking (leaderboard)", "ok" if board else "brak", n=len(board),
                        note=f"{mb:.1f} MB, {time.time() - t:.1f} s; kont ≥ $10k: {n10}, ≥ $100k: {n100}, ≥ $1M: {n1m}; "
                             f"okna: {', '.join(sorted(board[0]['pnl'])) if board else '—'}; pola: "
                             + ", ".join(sorted(first.keys()))))
    except Exception as e:  # noqa: BLE001
        rows.append(err_row("hyperliquid", "ranking (leaderboard)", e))
        return rows

    # 3) pozycje portfeli w 3 grupach
    groups = pick_groups(board, group_n)
    cache, t0, fail = {}, time.time(), 0
    calls0 = hl.calls
    for g in groups.values():
        for b in g:
            if b["addr"] in cache:
                continue
            try:
                cache[b["addr"]] = account_positions(hl.info({"type": "clearinghouseState", "user": b["addr"]}))
            except Exception:  # noqa: BLE001
                fail += 1
    dt = time.time() - t0
    per_addr = dt / max(1, len(cache) + fail)
    rows.append(row("hyperliquid", "pozycje portfeli (clearinghouseState)", "ok" if cache else "błąd", n=len(cache),
                    note=f"{dt:.0f} s, {per_addr:.2f} s na portfel, zapytań {hl.calls - calls0}, odpowiedzi 429: {hl.r429}, "
                         f"nieudane: {fail}; limit giełdy ok. 1200 „wag” na minutę na IP (ten typ = 2) → teoretycznie "
                         f"~600 portfeli na minutę; przy naszym tempie 1000 portfeli ≈ {per_addr * 1000 / 60:.0f} min"))
    stats = {}
    for name, g in groups.items():
        st = group_stats([cache[b["addr"]] for b in g if b["addr"] in cache])
        stats[name] = st
        pnl = _median([b["pnl"].get("allTime") for b in g])
        av = _median([b["av"] for b in g])
        top = "; ".join(f"{c['coin']} {usd(c['ntl'])} long {_pct(c['long_pct'])}" for c in st["top"][:6])
        rows.append(row("hyperliquid", f"teraz — {name}", "ok", n=st["n"],
                        note=f"konto mediana {usd(av)}, PnL od zawsze mediana {usd(pnl)}; w pozycjach {st['with_pos']}; "
                             f"long {usd(st['long'])} / short {usd(st['short'])} ({_pct(st['long_pct'])} long); "
                             f"dźwignia efektywna (pozycje ÷ konta) {_x(st['eff_lev'])}, mediana konta {_x(st['eff_lev_median'])}, "
                             f"ustawiona mediana {_x(st['set_lev_median'])}; alty {_pct(st['alt_share'])} pozycji, "
                             f"w altach long {_pct(st['alt_long_pct'])}; coinów {st['coins']}; największe: {top}"))
    ex["groups"] = stats

    # 4) portfolio: historia PnL konta (czy da się ustalić „najlepszych” w przeszłości)
    probe_addrs = [g[0]["addr"] for g in groups.values() if g][:3]
    for a in probe_addrs:
        try:
            pf = hl.info({"type": "portfolio", "user": a})
            per = {k: v for k, v in pf} if isinstance(pf, list) else {}
            at = per.get("allTime") or per.get("perpAllTime") or {}
            ph = at.get("pnlHistory") or []
            ts = [to_ts(p[0]) for p in ph if p]
            ts = [x for x in ts if x]
            step = _median([b - a_ for a_, b in zip(ts, ts[1:])]) if len(ts) > 2 else None
            rows.append(row("hyperliquid", f"portfolio {a[:8]}… (historia PnL)", "ok" if ph else "brak",
                            min(ts) if ts else None, max(ts) if ts else None, len(ph),
                            note=f"okresy: {', '.join(per)}; punkty allTime co ~{step / 86400:.1f} dnia" if step else
                                 f"okresy: {', '.join(per)}"))
            ex.setdefault("portfolio_sample", {})[a] = _short(pf)
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("hyperliquid", f"portfolio {a[:8]}…", e))

    # 5) transakcje portfela: jak daleko wstecz
    if probe_addrs:
        a = probe_addrs[0]
        try:
            fills = hl.info({"type": "userFillsByTime", "user": a, "startTime": 1672531200000,
                             "endTime": int(now * 1000)})
            ts = [to_ts(f.get("time")) for f in fills or []]
            ts = [x for x in ts if x]
            rows.append(row("hyperliquid", f"transakcje {a[:8]}… (userFillsByTime od 2023)", "ok" if ts else "brak",
                            min(ts) if ts else None, max(ts) if ts else None, len(ts),
                            note="jedno zapytanie zwraca najwyżej ok. 2000, a giełda trzyma ok. 10 000 ostatnich transakcji "
                                 "portfela — historii pozycji wstecz z darmowego API nie odtworzymy"))
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("hyperliquid", f"transakcje {a[:8]}…", e))
    rows.append(row("hyperliquid", "koszt", "ok", n=hl.calls,
                    note=f"zapytań do /info: {hl.calls}, odpowiedzi 429: {hl.r429}, błędów: {hl.errors}; bez klucza"))
    return rows


# ── HyperTracker ─────────────────────────────────────────────
class HTClient:
    def __init__(self, key, session=None, sleep=time.sleep, budget=HT_BUDGET):
        self.s = session or requests.Session()
        self.key = key
        self.sleep = sleep
        self.budget = budget
        self.calls = 0
        self.limit_headers = {}
        self.stopped = None

    def get(self, path, params=None, root=HT, fatal=True):
        if self.stopped:
            raise RuntimeError(f"pominięte: {self.stopped}")
        if self.calls >= self.budget:
            self.stopped = f"wykorzystany budżet sondy ({self.budget} zapytań)"
            raise RuntimeError(self.stopped)
        self.calls += 1
        h = dict(UA, Authorization=f"Bearer {self.key}", Accept="application/json")
        r = self.s.get(root + path, params=params, headers=h, timeout=60)
        for k, v in (r.headers or {}).items():
            if "limit" in k.lower() or "remaining" in k.lower() or "quota" in k.lower() or k.lower() == "retry-after":
                self.limit_headers[k] = v
        self.sleep(1.0)
        if r.status_code == 200:
            return r.json()
        txt = (r.text or "")[:160].replace(self.key, "<klucz>") if self.key else (r.text or "")[:160]
        if r.status_code in (401, 403) and fatal:
            self.stopped = f"HTTP {r.status_code} — klucz odrzucony albo brak dostępu w planie"
            raise RuntimeError(f"HTTP {r.status_code} {txt}")
        if r.status_code == 429:
            self.stopped = "HTTP 429 — limit zapytań wyczerpany"
            raise RuntimeError(f"HTTP 429 {txt}")
        raise RuntimeError(f"HTTP {r.status_code} {txt}")


def clean_key(k):
    """Klucz wklejony z „Bearer ”, w cudzysłowie albo ze spacjami / nową linią → sam token."""
    k = (k or "").strip().strip('"').strip("'").strip()
    if k.lower().startswith("bearer "):
        k = k[7:].strip()
    return k


def spec_summary(spec):
    """OpenAPI → {ścieżka: {params, opis}}."""
    out = {}
    for path, ops in (spec.get("paths") or {}).items():
        for meth, op in (ops or {}).items():
            if not isinstance(op, dict):
                continue
            params = [p.get("name") for p in op.get("parameters") or [] if isinstance(p, dict)]
            desc = " ".join(str(op.get(k) or "") for k in ("summary", "description")).strip()
            out[f"{meth.upper()} {path}"] = {"params": params, "opis": desc[:600]}
    return out


def depth_rows(source, label, first_obj, last_obj, now):
    """Dwie odpowiedzi (od najdawniej / ostatnie dni) → wiersz: od kiedy, krok, ile punktów na stronę."""
    from probe import row
    a, b = items_of(first_obj), items_of(last_obj) if last_obj is not None else []
    ts_a = sorted(x for x in (item_ts(i) for i in a) if x)
    ts_b = sorted(x for x in (item_ts(i) for i in b) if x)
    allts = ts_a + ts_b
    if not allts:
        return row(source, label, "brak" if not a else "ok", n=len(a),
                   note="brak rozpoznanego pola czasu" if a else "pusta odpowiedź")
    step = _median([y - x for x, y in zip(ts_b, ts_b[1:]) if y > x]) or _median([y - x for x, y in zip(ts_a, ts_a[1:]) if y > x])
    order = ""
    ta = [item_ts(i) for i in a if item_ts(i)]
    if len(ta) > 1:
        order = "rosnąco" if ta[0] < ta[-1] else "malejąco"
    cur = isinstance(first_obj, dict) and any(k for k in first_obj if "cursor" in k.lower() or "next" in k.lower())
    pages = None
    if step and ts_a and len(a) > 1:
        pages = int((now - ts_a[0]) / step / len(a)) + 1
    return row(source, label, "ok", min(allts), max(allts), len(a),
               note=(f"krok ~{step / 3600:.2f} h; " if step else "")
               + (f"kolejność {order}; " if order else "")
               + ("jest kursor stron; " if cur else "")
               + (f"cała historia ≈ {pages} zapytań przy tej wielkości strony" if pages else ""))


def check_hypertracker(session=None, sleep=time.sleep, extra=None, now=None, budget=HT_BUDGET, **_):
    from probe import row, err_row
    extra = extra if extra is not None else {}
    ex = extra.setdefault("hypertracker", {"samples": {}})
    key = clean_key(os.environ.get("HYPERTRACKER_API_KEY", ""))
    if not key:
        return [row("hypertracker", "klucz API", "brak",
                    note="dodaj sekret HYPERTRACKER_API_KEY (GitHub → Settings → Secrets and variables → Actions)")]
    ht = HTClient(key, session, sleep, budget)
    now = now or time.time()
    rows = [row("hypertracker", "klucz API", "ok", note="sekret HYPERTRACKER_API_KEY")]
    day = 86400
    early = "2024-01-01T00:00:00Z"
    recent = datetime.fromtimestamp(now - 2 * day, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    yday = datetime.fromtimestamp(now - day, timezone.utc).strftime("%Y-%m-%d")

    def call(label, path, params=None, root=HT, fatal=True):
        try:
            obj = ht.get(path, params, root, fatal)
            ex["samples"][label] = _short(obj)
            return obj
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("hypertracker", label, e))
            return None

    # 1) specyfikacja OpenAPI
    # (85b: 401 na specyfikacji nie zatrzymuje sondy — prawdziwy test klucza to /segments)
    spec = call("specyfikacja OpenAPI", "/external-json", root=HT_ROOT, fatal=False)
    if isinstance(spec, dict) and spec.get("paths"):
        ex["samples"].pop("specyfikacja OpenAPI", None)
        ex["spec"] = spec_summary(spec)
        rows.append(row("hypertracker", "specyfikacja OpenAPI", "ok", n=len(ex["spec"]),
                        note="lista endpointów z opisami w probe.json → extra.hypertracker.spec"))

    # 2) grupy
    seg = call("grupy (segments)", "/segments")
    if seg is not None:
        it = items_of(seg)
        names = []
        for s_ in it:
            if isinstance(s_, dict):
                names.append(f"{s_.get('id', s_.get('segmentId', '?'))} {s_.get('name', s_.get('label', ''))}".strip())
        rows.append(row("hypertracker", "grupy (segments)", "ok", n=len(it), note="; ".join(names[:20])))

    # 3) głębokość historii: od 2024 (pierwsza strona) i ostatnie 2 dni
    series = (("metryki BTC — Smart Money (9)", "/position-metrics/coin/BTC/segment/9"),
              ("metryki HYPE — Smart Money (9)", "/position-metrics/coin/HYPE/segment/9"),
              ("metryki BTC — Giga-Rekt (15)", "/position-metrics/coin/BTC/segment/15"),
              ("metryki BTC — wielkość Leviathan (7)", "/position-metrics/coin/BTC/position-size-segment/7"),
              ("metryki BTC — cały rynek", "/position-metrics/coin/BTC"),
              ("metryki giełdy (general)", "/position-metrics/general"))
    for label, path in series:
        a = call(label + " od 2024", path, {"start": early, "limit": 1000})
        b = call(label + " ostatnie 2 dni", path, {"start": recent, "limit": 1000}) if a is not None else None
        if a is not None:
            rows.append(depth_rows("hypertracker", label, a, b, now))

    # 4) pozostałe endpointy: czy działają na darmowym planie, jakie pola
    for label, path, params in (
            ("pozycje (positions) od 2024", "/positions", {"start": early, "coin": "BTC", "segmentId": 9, "limit": 5}),
            ("nastawienie grupy 9 (bias-history) od 2024", "/segments/9/bias-history", {"start": early, "limit": 50}),
            ("podsumowanie grupy 9", "/segments/9/summary", None),
            ("ranking 30 dni", "/leaderboards/perp-pnl", {"rankBy": "pnlMonth", "limit": 25}),
            ("ryzyko likwidacji — grupa 9", "/9/assets/liquidation-risk", {"limit": 10}),
            ("portfele grupy 9", "/wallets", {"segmentIds": 9, "limit": 5}),
            ("transakcje BTC wczoraj", "/fills", {"start": yday, "end": yday, "coin[]": "BTC", "limit": 5}),
            ("stan giełdy (state/summary)", "/state/summary", None)):
        obj = call(label, path, params)
        if obj is None:
            continue
        it = items_of(obj)
        ts = sorted(x for x in (item_ts(i) for i in it) if x)
        keys = sorted(it[0].keys()) if it and isinstance(it[0], dict) else sorted(obj.keys()) if isinstance(obj, dict) else []
        rows.append(row("hypertracker", label, "ok", ts[0] if ts else None, ts[-1] if ts else None, len(it),
                        note="pola: " + ", ".join(keys[:30])))

    rows.append(row("hypertracker", "koszt", "ok" if not ht.stopped else "uwaga", n=ht.calls,
                    note=f"zapytań w tej sondzie: {ht.calls} (darmowy plan ok. 100 na dobę); nagłówki limitów: "
                         + (", ".join(f"{k}={v}" for k, v in ht.limit_headers.items()) or "brak")
                         + (f"; zatrzymano: {ht.stopped}" if ht.stopped else "")))
    ex["limit_headers"] = ht.limit_headers
    return rows


# ═══ Sonda 86: sito portfeli (Hyperliquid) i głębokość historii HyperTrackera ═══
# hlsito  — lista rynków krypto wg OI (bez rynków z dodatkowych giełd „xyz:…”), a dla ~250 kandydatów z rankingu
#           (konto ≥ $100k, PnL od zawsze > 0): wiek konta, % miesięcy na plusie, zagrania (pozycja otwarta → zamknięta)
#           z ostatnich ≤ 2000 transakcji: skuteczność i stosunek zysków do strat osobno dla longów i shortów, częstotliwość;
#           dla 15 portfeli przewijanie transakcji wstecz → jak daleko sięga historia (limit giełdy ok. 10 000).
# htdepth — przewijanie historii metryk grupy Smart Money dla BTC do samego początku (≤ 25 zapytań) + próbka małego alta.
SEPARATE = ("BTC", "ETH", "HYPE", "SOL", "DOGE", "TAO")
SITO_TOP = 50             # najlepsi od zawsze
SITO_RANDOM = 300         # losowo z reszty kandydatów
SITO_DEEP = 0             # tyle portfeli: transakcje przewijane wstecz
DEEP_PAGES = 6
WEIGHT_PER_MIN = 900      # limit giełdy 1200 „wag” na minutę na IP — zostawiamy zapas
OI_LEVELS = (5e6, 10e6, 25e6, 100e6)
EPS = 1e-9


class WeightedHL(HLClient):
    """HLClient pilnujący „wag” zapytań (limit Hyperliquid na minutę)."""
    def __init__(self, session=None, sleep=time.sleep, clock=time.time, per_min=WEIGHT_PER_MIN):
        super().__init__(session, sleep, pause=0)
        self.clock = clock
        self.per_min = per_min
        self.log = []          # (czas, waga)
        self.weight = 0

    def _wait(self, w):
        while True:
            now = self.clock()
            self.log = [(t, x) for t, x in self.log if now - t < 60]
            if sum(x for _, x in self.log) + w <= self.per_min or not self.log:
                break
            self.sleep(max(0.5, 60 - (now - self.log[0][0])))

    def call(self, body, weight=20):
        self._wait(weight)
        out = self.info(body)
        extra = len(out) // 20 if isinstance(out, list) and body.get("type", "").startswith("userFills") else 0
        self.log.append((self.clock(), weight + extra))
        self.weight += weight + extra
        return out


def crypto_markets(meta, ctxs):
    """metaAndAssetCtxs → [(OI $, nazwa)] malejąco; tylko główna giełda (bez „dex:coin”), bez wycofanych."""
    out = []
    for a, c in zip(meta.get("universe") or [], ctxs or []):
        nm = a.get("name") or ""
        if ":" in nm or a.get("isDelisted"):
            continue
        px, o = _f(c.get("markPx")), _f(c.get("openInterest"))
        if px and o:
            out.append((o * px, nm))
    out.sort(reverse=True)
    return out


def trips(fills):
    """Transakcje portfela → zagrania: [{coin, side, pnl (po opłatach), open, close}].

    Zagranie = od otwarcia pozycji (z zera) do powrotu do zera albo odwrócenia strony. Pierwsza transakcja w oknie może
    zaczynać się w środku pozycji — wtedy zagranie liczymy od niej (strona = znak pozycji przed transakcją)."""
    out, cur = [], {}
    for f in sorted(fills or [], key=lambda x: (x.get("time") or 0, x.get("tid") or 0)):
        c = f.get("coin")
        if not c or ":" in c or c.startswith("@") or "/" in c:
            continue
        d = f.get("dir") or ""
        if d and "Long" not in d and "Short" not in d:     # 86b: tylko perpy (spot: „Buy” / „Sell”)
            continue
        sz, start = _f(f.get("sz")), _f(f.get("startPosition"))
        if sz is None or start is None:
            continue
        delta = sz if f.get("side") == "B" else -sz
        after = start + delta
        pnl = (_f(f.get("closedPnl")) or 0.0) - (_f(f.get("fee")) or 0.0)
        t = to_ts(f.get("time"))
        tr = cur.get(c)
        if tr is None:
            side = start if abs(start) > EPS else delta
            tr = cur[c] = {"coin": c, "side": "long" if side > 0 else "short", "pnl": 0.0, "open": t, "close": None}
        tr["pnl"] += pnl
        if abs(after) <= EPS * max(1.0, abs(start)) or (start * after < 0):
            tr["close"] = t
            out.append(tr)
            cur.pop(c)
            if start * after < 0:          # odwrócenie: nowa pozycja w drugą stronę
                cur[c] = {"coin": c, "side": "long" if after > 0 else "short", "pnl": 0.0, "open": t, "close": None}
    return out


def side_stats(tr):
    wins = [t["pnl"] for t in tr if t["pnl"] > 0]
    loss = [-t["pnl"] for t in tr if t["pnl"] < 0]
    return {"n": len(tr), "win_pct": len(wins) / len(tr) * 100 if tr else None,
            "pf": sum(wins) / sum(loss) if loss else (None if not wins else float("inf")),
            "pnl": sum(t["pnl"] for t in tr)}


def months_positive(pnl_hist):
    """Historia PnL od zawsze ([[ms, pnl], …], co ~tydzień) → (% miesięcy na plusie, liczba miesięcy)."""
    pts = sorted((to_ts(p[0]), _f(p[1])) for p in pnl_hist or [] if p and to_ts(p[0]) and _f(p[1]) is not None)
    if len(pts) < 2:
        return None, 0
    month_end = {}
    for t, v in pts:
        month_end[datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m")] = v
    ks = sorted(month_end)
    prev = pts[0][1]
    ch = []
    for k in ks:
        ch.append(month_end[k] - prev)
        prev = month_end[k]
    ch = ch[1:] if len(ch) > 1 else ch           # pierwszy miesiąc niepełny
    ch = [x for x in ch if abs(x) >= 1]          # 86b: tylko miesiące, w których konto grało (zmiana PnL ≥ $1)
    return (sum(1 for x in ch if x > 0) / len(ch) * 100 if ch else None), len(ch)


def wallet_profile(pf, fills, now):
    per = {k: v for k, v in pf} if isinstance(pf, list) else {}
    at = per.get("perpAllTime") or per.get("allTime") or {}
    ts = [to_ts(p[0]) for p in at.get("pnlHistory") or [] if p]
    ts = [x for x in ts if x]
    age = (now - min(ts)) / 86400 if ts else None
    mpos, nm = months_positive(at.get("pnlHistory"))
    tr = trips(fills)
    ft = [to_ts(f.get("time")) for f in fills or []]
    ft = [x for x in ft if x]
    span = (max(ft) - min(ft)) / 86400 if len(ft) > 1 else None
    weeks = max(span or 0, 7) / 7
    long_ = side_stats([t for t in tr if t["side"] == "long"])
    short = side_stats([t for t in tr if t["side"] == "short"])
    alts = [t for t in tr if t["coin"] not in SEPARATE]
    return {"age_days": age, "months_pos_pct": mpos, "months": nm, "fills": len(ft), "fills_capped": len(ft) >= 2000,
            "fills_span_days": span, "fills_first": min(ft) if ft else None,
            "trips": len(tr), "trips_per_week": len(tr) / weeks, "fills_per_day": len(ft) / max(span or 0, 1),
            "all": side_stats(tr), "long": long_, "short": short, "alt_trips_pct": len(alts) / len(tr) * 100 if tr else None}


def _pcts(xs, ps=(10, 25, 50, 75, 90)):
    xs = sorted(x for x in xs if x is not None and x != float("inf"))
    if not xs:
        return "—"
    return ", ".join(f"p{p} {xs[min(len(xs) - 1, int(p / 100 * len(xs)))]:.{0 if abs(xs[-1]) >= 100 else 1}f}" for p in ps) \
        + f" (n={len(xs)})"


def check_hlsito(session=None, sleep=time.sleep, clock=time.time, extra=None, now=None,
                 n_top=SITO_TOP, n_random=SITO_RANDOM, n_deep=SITO_DEEP, **_):
    from probe import row, err_row
    extra = extra if extra is not None else {}
    ex = extra.setdefault("hlsito", {})
    s = session or requests.Session()
    hl = WeightedHL(s, sleep, clock)
    now = now or clock()
    rows = []

    # 1) rynki krypto wg OI
    try:
        meta, ctxs = hl.call({"type": "metaAndAssetCtxs"}, 20)
        mk = crypto_markets(meta, ctxs)
        tot = sum(v for v, _ in mk)
        basket = [(v, n) for v, n in mk if n not in SEPARATE]
        ex["markets"] = [{"coin": n, "oi_usd": round(v)} for v, n in mk]
        levels = "; ".join(f"OI ≥ {usd(lv)}: {sum(1 for v, _ in mk if v >= lv)} (koszyk altów {sum(1 for v, _ in basket if v >= lv)})"
                           for lv in OI_LEVELS)
        rows.append(row("hlsito", "rynki krypto (główna giełda HL)", "ok", n=len(mk),
                        note=f"OI razem {usd(tot)}; osobno {', '.join(SEPARATE)}: "
                             + ", ".join(f"{n} {usd(v)}" for v, n in mk if n in SEPARATE)
                             + f"; koszyk altów (reszta) {usd(sum(v for v, _ in basket))}; {levels}; "
                             f"pierwsze w koszyku: " + ", ".join(f"{n} {usd(v)}" for v, n in basket[:15])))
        others = sum(1 for a in meta.get("universe") or [] if ":" in (a.get("name") or ""))
        if others:
            rows.append(row("hlsito", "pominięte rynki z „:”", "ok", n=others, note="dodatkowe giełdy (akcje, surowce…)"))
    except Exception as e:  # noqa: BLE001
        rows.append(err_row("hlsito", "rynki krypto", e))

    # 2) kandydaci
    try:
        r = s.get(HL_BOARD, headers=UA, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        board = board_rows(r.json())
    except Exception as e:  # noqa: BLE001
        return rows + [err_row("hlsito", "ranking", e)]
    pool = [b for b in board if b["addr"] and (b["av"] or 0) >= TOP_MIN_AV and (b["pnl"].get("allTime") or 0) > 0]
    pool.sort(key=lambda b: -(b["pnl"].get("allTime") or 0))
    top = pool[:n_top]
    rest = random.Random(86).sample(pool[n_top:], min(n_random, max(0, len(pool) - n_top)))
    cands = [(b, "najlepsi od zawsze") for b in top] + [(b, "losowo z kandydatów") for b in rest]
    rows.append(row("hlsito", "kandydaci", "ok", n=len(cands),
                    note=f"z rankingu: konto ≥ {usd(TOP_MIN_AV)} i PnL od zawsze > 0 → {len(pool)} kont; "
                         f"sprawdzane: {len(top)} najlepszych + {len(rest)} losowo"))

    # 3) profile
    prof, fails, t0 = [], 0, time.time()
    for i, (b, grp) in enumerate(cands):
        try:
            pf = hl.call({"type": "portfolio", "user": b["addr"]}, 20)
            fills = hl.call({"type": "userFills", "user": b["addr"]}, 20)
            p = wallet_profile(pf, fills, now)
            p.update({"addr": b["addr"], "group": grp, "av": b["av"], "pnl_all": b["pnl"].get("allTime"),
                      "pnl_month": b["pnl"].get("month")})
            if i < n_deep:                       # przewijanie wstecz
                allf = list(fills or [])
                pages = 1
                while len(allf) >= 2000 * pages and pages < DEEP_PAGES:
                    first = min(f.get("time") for f in allf)
                    more = hl.call({"type": "userFillsByTime", "user": b["addr"], "startTime": 0, "endTime": first - 1}, 20)
                    if not more:
                        break
                    seen = {(f.get("tid"), f.get("time")) for f in allf}
                    new = [f for f in more if (f.get("tid"), f.get("time")) not in seen]
                    if not new:
                        break
                    allf += new
                    pages += 1
                ts = [to_ts(f.get("time")) for f in allf]
                ts = [x for x in ts if x]
                p["deep"] = {"fills": len(allf), "pages": pages, "first": _iso(min(ts)) if ts else None,
                             "days": (max(ts) - min(ts)) / 86400 if len(ts) > 1 else None}
            prof.append(p)
        except Exception:  # noqa: BLE001
            fails += 1
    rows.append(row("hlsito", "profile portfeli (portfolio + userFills)", "ok" if prof else "błąd", n=len(prof),
                    note=f"{time.time() - t0:.0f} s; nieudane {fails}; wagi razem {hl.weight}, odpowiedzi 429: {hl.r429}; "
                         f"limit {WEIGHT_PER_MIN} wag/min"))
    ex["wallets"] = [{k: (round(v, 3) if isinstance(v, float) and v != float("inf") else v) for k, v in p.items()
                      if k not in ("long", "short", "all")}
                     | {k: {kk: (round(vv, 3) if isinstance(vv, float) and vv != float("inf") else vv)
                            for kk, vv in p[k].items()} for k in ("all", "long", "short")}
                     for p in prof]
    if not prof:
        return rows

    # 4) rozkłady — 86b: tylko konta, które grały perpami w oknie transakcji, bez botów (≥ 200 transakcji/dzień)
    idle = [p for p in prof if p["trips"] == 0]
    bots = [p for p in prof if p["trips"] and p["fills_per_day"] >= 200]
    rows.append(row("hlsito", "odrzucone przed rozkładami", "ok", n=len(idle) + len(bots),
                    note=f"bez zagrań perpami w oknie (nie grają / tylko spot / skarbce): {len(idle)}; boty / market makerzy "
                         f"(≥ 200 transakcji/dzień): {len(bots)}; zostaje {len(prof) - len(idle) - len(bots)}"))
    prof = [p for p in prof if p["trips"] and p["fills_per_day"] < 200]
    if not prof:
        return rows

    def dist(label, xs, note=""):
        rows.append(row("hlsito", label, "ok", n=sum(1 for x in xs if x is not None), note=_pcts(xs) + note))
    dist("wiek konta (dni)", [p["age_days"] for p in prof])
    dist("wartość konta ($k)", [(p["av"] or 0) / 1e3 for p in prof])
    dist("% miesięcy na plusie", [p["months_pos_pct"] for p in prof if p["months"] >= 3], " — miesiące, w których konto grało; konta z ≥ 3 takimi")
    dist("transakcje w oknie (max 2000)", [p["fills"] for p in prof],
         f"; okno pełne (2000) u {sum(1 for p in prof if p['fills_capped'])} kont")
    dist("okno transakcji (dni wstecz)", [p["fills_span_days"] for p in prof])
    dist("zagrania (w oknie)", [p["trips"] for p in prof])
    dist("zagrania na tydzień", [p["trips_per_week"] for p in prof])
    dist("transakcje na dzień", [p["fills_per_day"] for p in prof], " — bardzo dużo = bot / market maker")
    for side in ("all", "long", "short"):
        nm = {"all": "wszystkie", "long": "longi", "short": "shorty"}[side]
        for nmin in (10, 30):
            ok = [p for p in prof if p[side]["n"] >= nmin]
            dist(f"skuteczność — {nm}, ≥ {nmin} zagrań (% na plus)", [p[side]["win_pct"] for p in ok], "")
            dist(f"zyski ÷ straty — {nm}, ≥ {nmin} zagrań", [p[side]["pf"] for p in ok], "")
    dist("% zagrań na altach (bez 6 osobnych)", [p["alt_trips_pct"] for p in prof])
    both = [p for p in prof if p["long"]["n"] >= 30 and p["short"]["n"] >= 30]
    lb = sum(1 for p in both if (p["long"]["pf"] or 0) > (p["short"]["pf"] or 0))
    rows.append(row("hlsito", "longi vs shorty w jednym portfelu", "ok", n=len(both),
                    note=f"konta z ≥ 30 zagraniami w obie strony; lepsze w longach (zyski÷straty): {lb}, w shortach: {len(both) - lb}"))
    # przykładowe sito
    for age_min in (180, 365):
        for nmin in (10, 30):
            ok = [p for p in prof if (p["age_days"] or 0) >= age_min and p["trips"] >= nmin
                  and p["fills_per_day"] < 200 and (p["all"]["pf"] or 0) > 1.2]
            rows.append(row("hlsito", f"przykładowe sito: wiek ≥ {age_min} dni, ≥ {nmin} zagrań, < 200 transakcji/dzień, "
                                      "zyski÷straty > 1,2", "ok", n=len(ok),
                            note=f"z {len(prof)} grających; longi dobre (≥ {nmin}, z÷s > 1,2): "
                                 f"{sum(1 for p in ok if p['long']['n'] >= nmin and (p['long']['pf'] or 0) > 1.2)}, shorty dobre: "
                                 f"{sum(1 for p in ok if p['short']['n'] >= nmin and (p['short']['pf'] or 0) > 1.2)}"))
    deep = [p["deep"] for p in prof if p.get("deep")]
    if deep:
        rows.append(row("hlsito", "transakcje przewijane wstecz", "ok", n=len(deep),
                        note="; ".join(f"{d['fills']} tr. / {d['pages']} str. od {d['first']} ({(d['days'] or 0):.0f} dni)"
                                       for d in deep)))
    per_wallet = hl.weight / max(1, len(prof) + fails)
    rows.append(row("hlsito", "koszt", "ok", n=hl.calls,
                    note=f"zapytań {hl.calls}, wag {hl.weight} (~{per_wallet:.0f} na portfel) → przy {WEIGHT_PER_MIN} wag/min "
                         f"sito dla 1000 portfeli ≈ {per_wallet * 1000 / WEIGHT_PER_MIN:.0f} min (raz w tygodniu)"))
    return rows


def check_htdepth(session=None, sleep=time.sleep, extra=None, now=None, budget=40, max_pages=25, **_):
    from probe import row, err_row
    extra = extra if extra is not None else {}
    ex = extra.setdefault("htdepth", {})
    key = clean_key(os.environ.get("HYPERTRACKER_API_KEY", ""))
    if not key:
        return [row("htdepth", "klucz API", "brak", note="sekret HYPERTRACKER_API_KEY")]
    ht = HTClient(key, session, sleep, budget)
    rows = []
    early = "2023-01-01T00:00:00Z"
    path = "/position-metrics/coin/BTC/segment/9"
    params = {"start": early, "limit": 1000}
    first = last = None
    pts = 0
    pages = 0
    try:
        while pages < max_pages:
            obj = ht.get(path, params)
            pages += 1
            it = items_of(obj)
            ts = [item_ts(i) for i in it]
            ts = [x for x in ts if x]
            if ts:
                first = min(ts) if first is None else min(first, min(ts))
                last = max(ts) if last is None else max(last, max(ts))
            pts += len(it)
            cur = obj.get("nextCursor") if isinstance(obj, dict) else None
            if not cur or not it:
                break
            params = {"start": early, "limit": 1000, "nextCursor": cur}
        done = pages < max_pages
        rows.append(row("htdepth", "historia BTC — Smart Money (9)", "ok", first, last, pts,
                        note=f"stron {pages}{'' if done else ' (przerwane — jest dalej)'}; "
                             f"{'pełna historia' if done else 'początek wcześniej niż ' + (_iso(first) or '?')}"))
        ex["btc_seg9"] = {"first": _iso(first), "last": _iso(last), "points": pts, "pages": pages, "complete": done}
    except Exception as e:  # noqa: BLE001
        rows.append(err_row("htdepth", f"historia BTC — Smart Money (9) po {pages} str.", e))
    # małe alty: czy są metryki grup i od kiedy (1 zapytanie na coin)
    for coin in ("FARTCOIN", "VVV", "kPEPE"):
        try:
            obj = ht.get(f"/position-metrics/coin/{coin}/segment/9", {"start": early, "limit": 1000})
            it = items_of(obj)
            ts = sorted(x for x in (item_ts(i) for i in it) if x)
            rows.append(row("htdepth", f"{coin} — Smart Money (9), 1. strona", "ok" if it else "brak",
                            ts[0] if ts else None, ts[-1] if ts else None, len(it),
                            note="pola: " + ", ".join(sorted(it[0].keys())) if it else "pusto"))
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("htdepth", f"{coin} — Smart Money (9)", e))
    rows.append(row("htdepth", "koszt", "ok" if not ht.stopped else "uwaga", n=ht.calls,
                    note=f"zapytań {ht.calls}" + (f"; zatrzymano: {ht.stopped}" if ht.stopped else "")))
    return rows


# ═══ Sonda 90: czy HyperTracker ma historię pozycji portfeli z naszego sita ═══
# htwallets — bierze portfele z gałęzi hl-sito (skuteczni L / S, największe konta + tracący), pyta /positions
#             (pozycje od 04.2025, filtr address[]) paczkami po 10 adresów; ≤ 10 zapytań z limitu 100 / dobę.
#             Wynik: ile portfeli ma historię, od kiedy, ile pozycji, jakie pola (czy jest wynik pozycji), próbki.
SITO_URL = "https://raw.githubusercontent.com/{repo}/hl-sito/sito.json"


def pick_sito_wallets(sito, n_good=20, n_bad=10):
    ch = sito.get("checked") or {}
    good = sorted((a for a, v in ch.items() if v.get("sides")), key=lambda a: -((ch[a].get("av") or 0)))
    return good[:n_good], (sito.get("losers") or [])[:n_bad]


def check_htwallets(session=None, sleep=time.sleep, extra=None, now=None, budget=10, sito=None, **_):
    from probe import row, err_row
    extra = extra if extra is not None else {}
    ex = extra.setdefault("htwallets", {"samples": {}})
    key = clean_key(os.environ.get("HYPERTRACKER_API_KEY", ""))
    if not key:
        return [row("htwallets", "klucz API", "brak", note="sekret HYPERTRACKER_API_KEY")]
    s = session or requests.Session()
    rows = []
    if sito is None:
        repo = os.environ.get("GITHUB_REPOSITORY", "cryptoloser8-coder/scanner")
        try:
            r = s.get(SITO_URL.format(repo=repo), headers=UA, timeout=60)
            r.raise_for_status()
            sito = r.json()
        except Exception as e:  # noqa: BLE001
            return [err_row("htwallets", "sito.json z gałęzi hl-sito", e)]
    good, bad = pick_sito_wallets(sito)
    rows.append(row("htwallets", "portfele do sprawdzenia", "ok", n=len(good) + len(bad),
                    note=f"z sita: {len(good)} skutecznych (największe konta) + {len(bad)} tracących"))
    ht = HTClient(key, s, sleep, budget)
    per_addr = {}
    keys_seen = set()

    def ask(label, addrs, pages=1):
        cursor, got = None, 0
        for pg in range(pages):
            params = {"start": "2025-04-01T00:00:00Z", "limit": 1000, "address[]": addrs}
            if cursor:
                params["nextCursor"] = cursor
            try:
                obj = ht.get("/positions", params)
            except Exception as e:  # noqa: BLE001
                rows.append(err_row("htwallets", f"{label} — strona {pg + 1}", e))
                return
            it = items_of(obj)
            got += len(it)
            if pg == 0:
                ex["samples"][label] = _short(obj)
            for p in it:
                if not isinstance(p, dict):
                    continue
                keys_seen.update(p.keys())
                a = (p.get("address") or p.get("user") or p.get("wallet") or "").lower()
                d = per_addr.setdefault(a, {"n": 0, "open": 0, "first": None, "last": None, "coins": set()})
                d["n"] += 1
                d["coins"].add(p.get("coin"))
                if p.get("closeTime") in (None, "") and p.get("closedAt") in (None, ""):
                    d["open"] += 1
                t = to_ts(p.get("openTime") or p.get("openedAt") or p.get("createdAt"))
                if t:
                    d["first"] = t if d["first"] is None else min(d["first"], t)
                    d["last"] = t if d["last"] is None else max(d["last"], t)
            cursor = obj.get("nextCursor") if isinstance(obj, dict) else None
            if not cursor:
                break
        rows.append(row("htwallets", label, "ok", n=got, note=("jest kolejna strona" if cursor else "całość w odpowiedzi")))

    ask("skuteczni 1–10", [a.lower() for a in good[:10]], pages=3)
    ask("skuteczni 11–20", [a.lower() for a in good[10:20]])
    ask("tracący 1–10", [a.lower() for a in bad[:10]])
    if good:
        ask("jeden portfel (kontrola filtra)", [good[0].lower()])

    def summ(addrs, label):
        have = [a for a in addrs if per_addr.get(a.lower(), {}).get("n")]
        firsts = [per_addr[a.lower()]["first"] for a in have if per_addr[a.lower()]["first"]]
        ns = [per_addr[a.lower()]["n"] for a in have]
        rows.append(row("htwallets", f"{label}: z historią w HT", "ok" if have else "brak", min(firsts) if firsts else None,
                        max(firsts) if firsts else None, len(have),
                        note=f"z {len(addrs)}; pozycji na portfel: mediana {_median(ns) or 0:.0f}, max {max(ns) if ns else 0}; "
                             f"najwcześniejsze otwarcie: {_iso(min(firsts)) if firsts else '—'}"))
    summ(good[:20], "skuteczni")
    summ(bad[:10], "tracący")
    other = [a for a in per_addr if a not in {x.lower() for x in good + bad}]
    rows.append(row("htwallets", "pola pozycji", "ok", n=len(keys_seen),
                    note=", ".join(sorted(keys_seen))[:900] + (f"; UWAGA: {len(other)} adresów spoza zapytania — filtr nie działa?" if other else "")))
    ex["per_addr"] = {a: {**v, "coins": sorted(c for c in v["coins"] if c)} for a, v in per_addr.items()}
    rows.append(row("htwallets", "koszt", "ok" if not ht.stopped else "uwaga", n=ht.calls,
                    note=f"zapytań {ht.calls} z dziennego limitu 100 (Pi tego dnia pobierze o tyle mniej historii)"
                         + (f"; zatrzymano: {ht.stopped}" if ht.stopped else "")))
    return rows
