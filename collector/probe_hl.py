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

    def get(self, path, params=None, root=HT):
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
        if r.status_code in (401, 403):
            self.stopped = f"HTTP {r.status_code} — klucz odrzucony albo brak dostępu w planie"
            raise RuntimeError(f"HTTP {r.status_code} {txt}")
        if r.status_code == 429:
            self.stopped = "HTTP 429 — limit zapytań wyczerpany"
            raise RuntimeError(f"HTTP 429 {txt}")
        raise RuntimeError(f"HTTP {r.status_code} {txt}")


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
    key = os.environ.get("HYPERTRACKER_API_KEY", "").strip()
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

    def call(label, path, params=None, root=HT):
        try:
            obj = ht.get(path, params, root)
            ex["samples"][label] = _short(obj)
            return obj
        except Exception as e:  # noqa: BLE001
            rows.append(err_row("hypertracker", label, e))
            return None

    # 1) specyfikacja OpenAPI
    spec = call("specyfikacja OpenAPI", "/external-json", root=HT_ROOT)
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
