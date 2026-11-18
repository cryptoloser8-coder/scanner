"""Dźwignia — zarabiający vs reszta (Hyperliquid): sito portfeli i ich pozycje (poprawka 88).

    python collector/hl_wallets.py sito --sito-dir hl-sito --minutes 270
        Raz na dobę (workflow „Dźwignia — sito”): porcja kandydatów z rankingu Hyperliquid → wiek konta,
        skuteczność osobno w longach i w shortach, częstotliwość. Pełny przegląd co ~7 dni.
        Wynik: gałąź `hl-sito` (sito.json).
    python collector/hl_wallets.py positions --data-dir hl-branch --sito-dir hl-sito
        Po każdym skanie (workflow „Dźwignia — pozycje”, co ~2 h): pozycje i zlecenia portfeli z sita
        + próbki tracących → sumy longów i shortów grup na coinach (historia), kafelki, największe zmiany,
        stan portfeli do okna na stronie. Wynik: gałąź `hl` (hl_groups.json, hl_now.json, hl_wallets.json, hl_meta.json).

Grupy: L = skuteczni w longach, S = skuteczni w shortach (portfel może być w obu), R = tracący (losowa próbka).
Sito (start 18.11.2026, do przeglądu): konto ≥ $100k, zysk od zawsze > 0, wolumen 30 dni > 0 (wstępnie z rankingu),
wiek konta ≥ 180 dni (od poprawki 92; wcześniej 365), < 200 transakcji / dzień; strona oceniana przy ≥ 10 zagraniach, „skuteczny” = zyski ≥ 1,2× strat.
Poprawka 92: „młodsze” konta (180–365 dni) liczone też osobno (hl_now → age_split, serie Ly/Lo/Sy/So),
żeby na przeglądzie zdecydować: śledzić dalej, zrezygnować czy zejść do 90 dni.
Tylko krypto z głównej giełdy HL (bez rynków „dex:coin”), tylko perpy. Wszystko z darmowego API, bez klucza.
"""
import argparse
import json
import logging
import os
import random
import sys
import tempfile
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import probe_hl as P  # noqa: E402  (trips, side_stats, months_positive, board_rows, WeightedHL)

log = logging.getLogger("hl_wallets")
SEPARATE = ("BTC", "ETH", "HYPE", "SOL", "DOGE", "TAO")
COINS = SEPARATE + ("ALT",)
GROUPS = ("L", "S", "R")
SITO = {"min_av": 100e3, "min_age_days": 180, "young_days": 365, "max_fills_day": 200, "min_trips": 10, "min_pf": 1.2,
        "round_days": 7, "losers": 300, "losers_min_av": 10e3}
WEIGHT_PER_MIN = 1100                 # limit HL 1200 wag / min na IP — zostawiamy zapas
LEV_BUCKETS = ((0, 3, "do ×3"), (3, 10, "×3–10"), (10, 20, "×10–20"), (20, 1e9, "ponad ×20"))
KEEP_EVENTS = 10
BEST = {"top": 10, "min_trips": 20, "min_pf": 1.5}   # 92: „najlepsze konta” — ≥ 20 zagrań w stronie, z÷s ≥ 1,5, sort wg zysku
DAY = 86400


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def _write(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _r(x, nd=2):
    return None if x is None or x != x or x in (float("inf"), float("-inf")) else round(x, nd)


def fetch_board(session):
    r = session.get(P.HL_BOARD, headers=P.UA, timeout=120)
    r.raise_for_status()
    return P.board_rows(r.json())


# ── sito ─────────────────────────────────────────────────────
def candidates(board, cfg=SITO):
    """Ranking → kandydaci do sita (największe konta pierwsze) i próbka tracących."""
    c = [b for b in board if b["addr"] and (b["av"] or 0) >= cfg["min_av"] and (b["pnl"].get("allTime") or 0) > 0
         and (b["vlm"].get("month") or 0) > 0]
    c.sort(key=lambda b: -(b["av"] or 0))
    los = [b for b in board if b["addr"] and (b["av"] or 0) >= cfg["losers_min_av"] and (b["pnl"].get("allTime") or 0) < 0
           and (b["vlm"].get("month") or 0) > 0]
    los = random.Random(int(time.time() // (7 * DAY))).sample(los, min(cfg["losers"], len(los)))
    return [b["addr"] for b in c], [b["addr"] for b in los]


def max_drawdown(av_hist):
    vals = [_f(p[1]) for p in av_hist or [] if p and _f(p[1]) is not None]
    peak, dd = None, 0.0
    for v in vals:
        peak = v if peak is None or v > peak else peak
        if peak and peak > 0:
            dd = min(dd, v / peak - 1)
    return dd * 100 if vals else None


def period_pnl(per, name):
    h = (per.get(name) or {}).get("pnlHistory") or []
    v = [_f(p[1]) for p in h if p and _f(p[1]) is not None]
    return v[-1] - v[0] if len(v) > 1 else None


def evaluate(pf, fills, now, cfg=SITO):
    """portfolio + userFills → profil portfela i werdykt (które strony skuteczne)."""
    per = {k: v for k, v in pf} if isinstance(pf, list) else {}
    p = P.wallet_profile(pf, fills, now)
    at = per.get("perpAllTime") or per.get("allTime") or {}

    def side(st):
        return {"n": st["n"], "win": _r(st["win_pct"], 1), "pf": _r(st["pf"]), "pnl": _r(st["pnl"], 0)}
    res = {"age": _r(p["age_days"], 0), "mpos": _r(p["months_pos_pct"], 0), "tw": _r(p["trips_per_week"], 1),
           "fpd": _r(p["fills_per_day"], 1), "trips": p["trips"], "L": side(p["long"]), "S": side(p["short"]),
           "p7": _r(period_pnl(per, "perpWeek") or period_pnl(per, "week"), 0),
           "p30": _r(period_pnl(per, "perpMonth") or period_pnl(per, "month"), 0),
           "dd": _r(max_drawdown(at.get("accountValueHistory")), 1)}
    res["sides"], res["why"] = verdict(res, cfg)      # 92: ten sam werdykt co przy przeliczaniu z zapisanych liczb
    return res


def _pf_ok(st, cfg):
    """z÷s ≥ progu; brak z÷s przy zysku = same zyskowne zagrania (zapis JSON nie trzyma nieskończoności)."""
    pf = st.get("pf")
    return pf >= cfg["min_pf"] if pf is not None else (st.get("pnl") or 0) > 0


def verdict(v, cfg=SITO):
    """Werdykt z zapisanych liczb portfela (bez ponownego pobierania) — po zmianie progów działa od razu."""
    L, S_ = v.get("L") or {}, v.get("S") or {}
    age, fpd = v.get("age") or 0, v.get("fpd") or 0
    ok_base = age >= cfg["min_age_days"] and fpd < cfg["max_fills_day"]
    sides = [k for k, st in (("L", L), ("S", S_))
             if ok_base and (st.get("n") or 0) >= cfg["min_trips"] and _pf_ok(st, cfg)]
    if not v.get("trips"):
        why = "brak zagrań perpami"
    elif fpd >= cfg["max_fills_day"]:
        why = "bot / market maker"
    elif max(L.get("n") or 0, S_.get("n") or 0) < cfg["min_trips"]:
        why = "za mało zagrań"
    elif age < cfg["min_age_days"]:
        why = "za młode konto"
    elif not sides:
        why = "nieskuteczny"
    else:
        why = None
    return sides, why


def reverdict(checked, cfg=SITO):
    n = 0
    for v in (checked or {}).values():
        if "trips" not in v:
            continue
        sides, why = verdict(v, cfg)
        n += sides != v.get("sides")
        v["sides"], v["why"] = sides, why
    return n


def is_young(info, cfg=SITO):
    return (info or {}).get("age") is not None and info["age"] < cfg.get("young_days", 365)


def round_snapshot(st):
    """Kto był w sicie w tej rundzie: {addr: [strony, wiek, L: n / % / z÷s, S: n / % / z÷s, konto]} + tracący."""
    mem = {}
    for a, v in (st.get("checked") or {}).items():
        if v.get("sides"):
            L, S_ = v.get("L") or {}, v.get("S") or {}
            mem[a] = ["".join(v["sides"]), v.get("age"), L.get("n"), L.get("win"), L.get("pf"),
                      S_.get("n"), S_.get("win"), S_.get("pf"), v.get("av")]
    return {"round_started": st.get("round_started"), "total": st.get("round_total"), "params": st.get("params"),
            "cols": ["strony", "wiek", "L_n", "L_win", "L_pf", "S_n", "S_win", "S_pf", "konto"],
            "members": mem, "losers": st.get("losers") or []}


def save_round(sito_dir, st, now):
    if not st.get("round_started"):
        return
    d = time.strftime("%Y-%m-%d", time.gmtime(st["round_started"]))
    _write(os.path.join(sito_dir, "rounds", d + ".json"), round_snapshot(st))


def run_sito(sito_dir, minutes=270, session=None, sleep=time.sleep, clock=time.time, cfg=SITO):
    s = session or requests.Session()
    path = os.path.join(sito_dir, "sito.json")
    st = _read(path, {})
    now = clock()
    hl = P.WeightedHL(s, sleep, clock, per_min=WEIGHT_PER_MIN)
    board = None
    if not st.get("queue") and now - st.get("round_started", 0) >= cfg["round_days"] * DAY:
        board = fetch_board(s)
        cand, los = candidates(board, cfg)
        old = st.get("checked") or {}
        save_round(sito_dir, st, now)                 # 91: zdjęcie kończącej się rundy (kto był w sicie) — na zawsze
        st["checked"] = {k: v for k, v in old.items() if v.get("at", 0) >= now - 2 * cfg["round_days"] * DAY}
        st.update({"queue": cand, "losers": los, "round_started": int(now), "round_total": len(cand)})
        log.info("Nowa runda sita: %d kandydatów, %d tracących", len(cand), len(los))
    st.setdefault("checked", {})
    ch = reverdict(st["checked"], cfg)               # 92: nowe progi działają od razu na już sprawdzonych
    if ch:
        log.info("Nowe progi: zmiana werdyktu u %d portfeli", ch)
    st["params"] = cfg
    t_end = clock() + minutes * 60
    done = 0
    av = {}
    if board is None and st.get("queue"):
        try:
            av = {b["addr"]: b["av"] for b in fetch_board(s)}
        except Exception as e:  # noqa: BLE001
            log.warning("Ranking: %s", e)
    else:
        av = {b["addr"]: b["av"] for b in board or []}
    while st.get("queue") and clock() < t_end:
        a = st["queue"][0]
        try:
            # 88b: najpierw transakcje; historię PnL (portfolio) tylko, gdy portfel ma szansę przejść sito
            fills = hl.call({"type": "userFills", "user": a}, 20)
            pre = P.wallet_profile([], fills, clock())
            hopeless = (not pre["trips"] or pre["fills_per_day"] >= cfg["max_fills_day"]
                        or max(pre["long"]["n"], pre["short"]["n"]) < cfg["min_trips"])
            pf = [] if hopeless else hl.call({"type": "portfolio", "user": a}, 20)
            ev = evaluate(pf, fills, clock(), cfg)
            ev.update({"at": int(clock()), "av": _r(av.get(a), 0)})
            st["checked"][a] = ev
        except Exception as e:  # noqa: BLE001
            log.warning("%s: %s", a[:10], e)
            st.setdefault("failed", {})[a] = int(clock())
        st["queue"].pop(0)
        done += 1
        if done % 100 == 0:
            _write(path, st)
    # zostają tylko kandydaci z bieżącej rundy (konto mogło wypaść z rankingu)
    st["updated"] = int(clock())
    st["in_sito"] = {k: sum(1 for v in st["checked"].values() if k in v.get("sides", [])) for k in ("L", "S")}
    save_round(sito_dir, st, now)
    _write(path, st)
    return done, st


# ── pozycje ──────────────────────────────────────────────────
def parse_state(state):
    ms = state.get("marginSummary") or {}
    out = []
    for ap in state.get("assetPositions") or []:
        p = ap.get("position") or {}
        c = p.get("coin") or ""
        szi = _f(p.get("szi"))
        if not szi or ":" in c:
            continue
        val = abs(_f(p.get("positionValue")) or 0)
        entry = _f(p.get("entryPx"))
        mark = val / abs(szi) if szi else None
        lev = p.get("leverage") or {}
        liq = _f(p.get("liquidationPx"))
        cf = (p.get("cumFunding") or {}).get("sinceOpen")
        out.append({"c": c, "L": szi > 0, "size": _r(val, 0), "entry": entry, "mark": _r(mark, 6),
                    "pnl": _r(_f(p.get("unrealizedPnl")), 0),
                    "pnlPct": _r((mark / entry - 1) * (100 if szi > 0 else -100), 2) if entry and mark else None,
                    "liq": liq, "liqDist": _r((liq / mark - 1) * 100, 2) if liq and mark else None,
                    "lev": _f(lev.get("value")), "mode": lev.get("type"), "margin": _r(_f(p.get("marginUsed")), 0),
                    "fund": _r(-_f(cf), 0) if _f(cf) is not None else None})
    return _f(ms.get("accountValue")), out


def parse_orders(orders):
    out = []
    for o in orders or []:
        c = o.get("coin") or ""
        if ":" in c or c.startswith("@"):
            continue
        ot = (o.get("orderType") or "").lower()
        kind = "sl" if "stop" in ot else "tp" if "take profit" in ot else "limit"
        px = _f(o.get("triggerPx")) if o.get("isTrigger") else _f(o.get("limitPx"))
        out.append({"c": c, "kind": kind, "buy": o.get("side") == "B", "px": px, "sz": _f(o.get("sz")),
                    "reduce": bool(o.get("reduceOnly"))})
    return out


def coin_key(c):
    return c if c in SEPARATE else "ALT"


def lev_bucket(x):
    for i, (lo, hi, _) in enumerate(LEV_BUCKETS):
        if lo <= (x or 0) < hi:
            return i
    return len(LEV_BUCKETS) - 1


def group_stats(wallets):
    """[{av, pos}] → kafelek grupy + tabela coinów."""
    tot_l = tot_s = av_sum = 0.0
    only_l = only_s = both = 0
    levb = [[0, 0] for _ in LEV_BUCKETS]
    coins = {k: {"long": 0.0, "short": 0.0, "nL": 0, "nS": 0} for k in COINS}
    in_pos = 0
    for w in wallets:
        pos = w["pos"]
        if not pos:
            continue
        in_pos += 1
        av_sum += w["av"] or 0
        ls = [p for p in pos if p["L"]]
        ss = [p for p in pos if not p["L"]]
        only_l += bool(ls and not ss)
        only_s += bool(ss and not ls)
        both += bool(ls and ss)
        for i, grp in ((0, ls), (1, ss)):
            if grp:
                big = max(grp, key=lambda p: p["size"] or 0)
                levb[lev_bucket(big["lev"])][i] += 1
        seen = set()
        for p in pos:
            k = coin_key(p["c"])
            side = "long" if p["L"] else "short"
            coins[k][side] += p["size"] or 0
            if (k, side) not in seen:
                coins[k]["nL" if p["L"] else "nS"] += 1
                seen.add((k, side))
            if p["L"]:
                tot_l += p["size"] or 0
            else:
                tot_s += p["size"] or 0
    for k in coins:
        a = coins[k]
        a["lpct"] = _r(a["long"] / (a["long"] + a["short"]) * 100, 1) if a["long"] + a["short"] else None
        a["long"], a["short"] = round(a["long"]), round(a["short"])
    return {"n": len(wallets), "in_pos": in_pos, "long": round(tot_l), "short": round(tot_s),
            "lpct": _r(tot_l / (tot_l + tot_s) * 100, 1) if tot_l + tot_s else None,
            "only_long": only_l, "only_short": only_s, "both": both,
            "eff_lev": _r((tot_l + tot_s) / av_sum, 2) if av_sum else None,
            "lev_buckets": [[LEV_BUCKETS[i][2]] + levb[i] for i in range(len(LEV_BUCKETS))], "coins": coins}


def append_series(series, t, groups):
    def add(k, v):
        if v is None:
            return
        arr = series.setdefault(k, [])
        if arr and arr[-1][0] == t:
            arr[-1] = [t, v]
        else:
            arr.append([t, v])
    for g, st in groups.items():
        add(f"{g}_all_long", st["long"])
        add(f"{g}_all_short", st["short"])
        add(f"{g}_all_lpct", st["lpct"])
        for c, a in st["coins"].items():
            add(f"{g}_{c}_long", a["long"])
            add(f"{g}_{c}_short", a["short"])
            add(f"{g}_{c}_lpct", a["lpct"])


def changes(series, now, top=8):
    """93: największe zmiany z przepływów — tylko portfele obecne w grupie przed i po (bez wpływu zmian składu sita
    i ruchu ceny). Gdy przepływy liczone krócej niż okno — „since” (od kiedy)."""
    out = []
    for win, sec in (("2 h", 2 * 3600), ("24 h", DAY), ("7 dni", 7 * DAY)):
        start = now - sec + 900
        for g in GROUPS:
            for c in COINS:
                for side, tag in (("long", "flowL"), ("short", "flowS")):
                    arr = series.get(f"{g}_{c}_{tag}") or []
                    vals = [v for t, v in arr if t >= start]
                    if not vals:
                        continue
                    x = {"g": g, "c": c, "win": win, "side": side, "delta": round(sum(vals))}
                    if arr[0][0] > start + 1800:
                        x["since"] = arr[0][0]
                    out.append(x)
    out.sort(key=lambda x: -abs(x["delta"]))
    res, seen = [], set()
    for x in out:
        k = (x["g"], x["c"], x["side"])
        if k in seen or abs(x["delta"]) < 1e5:
            continue
        seen.add(k)
        res.append(x)
        if len(res) >= top:
            break
    return res


# ── 93: przepływy na tych samych portfelach ─────────────────
FLOW_SEED = [{"t": 1795015800, "g": "*", "note": "Sito: pełna runda i konta od 180 dni — skuteczni w longach 153 → 529, "
              "w shortach 114 → 390 portfeli (kwoty i udziały skoczyły przez zmianę składu, nie przez rynek)"}]
KEEP_COMP = 300


def compact_pos(pos):
    """[[coin, long?, ilość, cena]] — do przepływów w następnym przebiegu."""
    return [[p["c"], p["L"], _r(p["size"] / p["mark"], 8), p["mark"]] for p in pos or [] if p.get("size") and p.get("mark")]


def wallet_flow(prev, cur):
    """Zmiana ilości × cena na każdej (coin, strona): + otworzył / dokupił, − zmniejszył / zamknął. Ruch ceny się nie liczy."""
    a = {(c, L): (q, m) for c, L, q, m in prev or []}
    b = {(c, L): (q, m) for c, L, q, m in cur or []}
    out = {}
    for k in set(a) | set(b):
        qa, ma = a.get(k, (0, None))
        qb, mb = b.get(k, (0, None))
        d = ((qb or 0) - (qa or 0)) * (mb or ma or 0)
        if abs(d) >= 1:
            out[k] = d
    return out


def group_flows(prev, wallets, failed=()):
    """prev = {"groups": {g: [adresy]}, "pos": {adres: compact}} z poprzedniego przebiegu.
    → (przepływy {g: {coin|all: {long, short}}}, zmiany składu {g: {in, out, long_in, short_in, long_out, short_out}})."""
    cur = {w["addr"]: compact_pos(w["pos"]) for w in wallets}
    ppos = prev.get("pos") or {}
    flows, comp = {}, {}
    for g in GROUPS:
        pg = set((prev.get("groups") or {}).get(g) or []) - set(failed)
        cg = {w["addr"] for w in wallets if g in w["g"]}
        f = {k: {"long": 0.0, "short": 0.0} for k in COINS + ("all",)}
        for a in cg & pg:
            for (c, L), d in wallet_flow(ppos.get(a), cur[a]).items():
                side = "long" if L else "short"
                f[coin_key(c)][side] += d
                f["all"][side] += d
        flows[g] = f

        def tot(addrs, src):
            ls = [0.0, 0.0]
            for a in addrs:
                for c, L, q, m in src.get(a) or []:
                    ls[0 if L else 1] += (q or 0) * (m or 0)
            return [round(x) for x in ls]
        new, gone = cg - pg, pg - cg
        li, si = tot(new, cur)
        lo, so = tot(gone, ppos)
        comp[g] = {"in": len(new), "out": len(gone), "n": len(cg), "long_in": li, "short_in": si, "long_out": lo, "short_out": so}
    return flows, comp


def members_doc(wallets, prev, failed, now):
    """Członkowie grup i pozycje (skrót) do następnego przebiegu; portfel, którego nie udało się pobrać, zostaje z poprzednim stanem."""
    groups = {g: [w["addr"] for w in wallets if g in w["g"]] for g in GROUPS}
    pos = {w["addr"]: compact_pos(w["pos"]) for w in wallets if w["pos"]}
    for a in failed:
        for g in GROUPS:
            if a in ((prev.get("groups") or {}).get(g) or []):
                groups[g].append(a)
        if a in (prev.get("pos") or {}):
            pos[a] = prev["pos"][a]
    return {"at": int(now), "groups": groups, "pos": pos}


def append_flows(series, t, flows, groups):
    """Przepływy dodawane (dwa przebiegi w tym samym kwadransie się sumują) + liczba portfeli grupy."""
    def add(k, v, plus):
        arr = series.setdefault(k, [])
        if arr and arr[-1][0] == t:
            arr[-1] = [t, round(arr[-1][1] + v) if plus else v]
        else:
            arr.append([t, round(v) if plus else v])
    for g, f in flows.items():
        for c, a in f.items():
            add(f"{g}_{c}_flowL", a["long"], True)
            add(f"{g}_{c}_flowS", a["short"], True)
    for g, st in groups.items():
        add(f"{g}_n", st["n"], False)


def events(prev, cur, now):
    """Porównanie z poprzednim stanem portfela → ostatnie ruchy (otworzył / dokupił / zmniejszył / zamknął)."""
    if prev is None:                       # pierwszy raz w zapisie — bez „otworzył” dla wszystkiego naraz
        return []
    ev = list(prev.get("ev") or [])
    pp = {(p["c"], p["L"]): p for p in (prev or {}).get("pos") or []}
    cp = {(p["c"], p["L"]): p for p in cur}
    for k, p in cp.items():
        q = pp.get(k)
        if q is None:
            ev.append([int(now), "otworzył", p["c"], p["L"], p["size"], p["entry"]])
        elif q["size"] and p["size"] and abs(p["size"] / q["size"] - 1) > 0.1 and abs(p["size"] - q["size"]) > 1000:
            ev.append([int(now), "dokupił" if p["size"] > q["size"] else "zmniejszył", p["c"], p["L"],
                       round(abs(p["size"] - q["size"])), p["mark"]])
    for k, q in pp.items():
        if k not in cp:
            ev.append([int(now), "zamknął", q["c"], q["L"], q["size"], q.get("mark")])
    return ev[-KEEP_EVENTS:]


def _med(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def age_split(wallets, checked, cfg=SITO):
    """92: grupy L i S osobno dla młodszych (wiek < young_days) i starszych kont — pozycje teraz + skuteczność z sita."""
    out = {}
    for g in ("L", "S"):
        out[g] = {}
        for k, young in (("mlode", True), ("starsze", False)):
            ws = [w for w in wallets if g in w["g"] and is_young(checked.get(w["addr"]), cfg) == young]
            st = group_stats(ws)
            info = [checked.get(a) or {} for a, v in checked.items()
                    if g in (v.get("sides") or []) and is_young(v, cfg) == young]
            sd = [i.get(g) or {} for i in info]
            out[g][k] = {x: st[x] for x in ("n", "in_pos", "long", "short", "lpct", "only_long", "only_short", "both",
                                             "eff_lev", "lev_buckets")}
            out[g][k].update({"members": len(info), "age_med": _r(_med([i.get("age") for i in info]), 0),
                              "win_med": _r(_med([x.get("win") for x in sd]), 1),
                              "pf_med": _r(_med([x.get("pf") for x in sd]), 2),
                              "n_med": _r(_med([x.get("n") for x in sd]), 0),
                              "av_med": _r(_med([i.get("av") for i in info]), 0)})
    return {"young_days": cfg.get("young_days", 365), "min_age_days": cfg["min_age_days"], "groups": out}


def best_lists(checked, wallets, cfg=BEST):
    """92: najlepsze konta osobno w longach i w shortach — spośród portfeli sita z ≥ min_trips zagraniami w tej stronie
    i z÷s ≥ min_pf, sortowane wg zrealizowanego zysku z tej strony (ostatnie transakcje). + co trzymają teraz."""
    by = {w["addr"]: w for w in wallets}
    out = {}
    for g in ("L", "S"):
        rows = []
        for a, v in checked.items():
            st = v.get(g) or {}
            pf = st.get("pf")
            if g not in (v.get("sides") or []) or (st.get("n") or 0) < cfg["min_trips"]:
                continue
            if not (pf >= cfg["min_pf"] if pf is not None else (st.get("pnl") or 0) > 0):
                continue
            rows.append((st.get("pnl") or 0, a, v))
        rows.sort(key=lambda x: -x[0])
        lst = []
        for _, a, v in rows[:cfg["top"]]:
            w = by.get(a) or {}
            pos = w.get("pos") or []
            lst.append({"addr": a, "age": v.get("age"), "av": w.get("av") if w.get("av") is not None else v.get("av"),
                        "side": v.get(g), "other": v.get("S" if g == "L" else "L"), "sides": v.get("sides"),
                        "tw": v.get("tw"), "p30": v.get("p30"),
                        "long": round(sum(p["size"] or 0 for p in pos if p["L"])),
                        "short": round(sum(p["size"] or 0 for p in pos if not p["L"])),
                        "upnl": round(sum(p["pnl"] or 0 for p in pos)) if pos else None,
                        "pos": [{k: p.get(k) for k in ("c", "L", "size", "lev", "pnl")}
                                for p in sorted(pos, key=lambda p: -(p["size"] or 0))[:8]], "npos": len(pos)})
        out[g] = lst
    return {"params": cfg, "groups": out}


def append_split(series, t, split):
    """Serie Ly / Lo / Sy / So (młodsze / starsze): longi, shorty, % long, dźwignia rzeczywista — do przeglądu."""
    for g, d in (split.get("groups") or {}).items():
        for k, tag in (("mlode", "y"), ("starsze", "o")):
            st = d.get(k) or {}
            for f in ("long", "short", "lpct", "eff_lev"):
                if st.get(f) is None:
                    continue
                arr = series.setdefault(f"{g}{tag}_all_{f}", [])
                if arr and arr[-1][0] == t:
                    arr[-1] = [t, st[f]]
                else:
                    arr.append([t, st[f]])


DAILY_COLS = ["id", "grupa", "wynik_dzien", "wynik_od_poczatku", "konto"]


def daily_due(data_dir, now):
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    doc = _read(os.path.join(data_dir, "daily", day[:7] + ".json"), {})
    return day not in (doc.get("days") or {})


def save_daily(data_dir, board, members, losers, now):
    """91: raz na dobę (UTC) wynik każdego śledzonego portfela z rankingu HL — „zyskowny czy stratny” dzień po dniu.
    daily/RRRR-MM.json: {"cols", "ids": [adresy], "days": {"RRRR-MM-DD": [[id, grupa, wynik dnia, wynik od początku, konto]]}}"""
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    path = os.path.join(data_dir, "daily", day[:7] + ".json")
    doc = _read(path, {"cols": DAILY_COLS, "ids": [], "days": {}})
    if day in doc["days"]:
        return False
    idx = {a: i for i, a in enumerate(doc["ids"])}
    by = {b["addr"]: b for b in board if b["addr"]}
    rows = []
    for a in list(members) + [x for x in losers if x not in members]:
        b = by.get(a)
        if not b:
            continue
        if a not in idx:
            idx[a] = len(doc["ids"])
            doc["ids"].append(a)
        g = "".join(members.get(a) or []) or "R"
        rows.append([idx[a], g, _r(b["pnl"].get("day"), 0), _r(b["pnl"].get("allTime"), 0), _r(b["av"], 0)])
    doc["days"][day] = rows
    _write(path, doc)
    return True


def run_positions(data_dir, sito_dir, session=None, sleep=time.sleep, clock=time.time):
    s = session or requests.Session()
    now = clock()
    t0 = now
    sito = _read(os.path.join(sito_dir, "sito.json"), {})
    checked = sito.get("checked") or {}
    reverdict(checked)                                # 92: progi z kodu, nawet jeśli sito jeszcze nie przeliczyło
    members = {a: v["sides"] for a, v in checked.items() if v.get("sides")}
    losers = sito.get("losers") or []
    hl = P.WeightedHL(s, sleep, clock, per_min=WEIGHT_PER_MIN)
    prev = {w["addr"]: w for w in (_read(os.path.join(data_dir, "hl_wallets.json"), {}).get("wallets") or [])}
    meta, ctxs = hl.call({"type": "metaAndAssetCtxs"}, 20)
    px = {}
    for a, c in zip(meta.get("universe") or [], ctxs or []):
        nm = a.get("name") or ""
        if nm in SEPARATE:
            mk, pd = _f(c.get("markPx")), _f(c.get("prevDayPx"))
            px[nm] = {"px": mk, "ch24": _r((mk / pd - 1) * 100, 2) if mk and pd else None}
    wallets, fails, failed = [], 0, []
    for a in list(members) + [x for x in losers if x not in members]:
        try:
            av, pos = parse_state(hl.call({"type": "clearinghouseState", "user": a}, 2))
            orders = parse_orders(hl.call({"type": "frontendOpenOrders", "user": a}, 20)) if pos else []
        except Exception:  # noqa: BLE001
            fails += 1
            failed.append(a)
            continue
        groups = list(members.get(a, [])) + (["R"] if a in losers and a not in members else [])
        info = checked.get(a) or {}
        w = {"addr": a, "g": groups, "av": _r(av, 0), "pos": pos, "ord": orders,
             "prof": {k: info.get(k) for k in ("age", "mpos", "tw", "L", "S", "p7", "p30", "dd")} if info else None}
        w["ev"] = events(prev.get(a), pos, now)
        wallets.append(w)
    daily_saved = False
    if daily_due(data_dir, now):
        try:
            daily_saved = save_daily(data_dir, fetch_board(s), members, losers, now)
        except Exception as e:  # noqa: BLE001
            log.warning("Dzienny zapis wyników: %s", e)
    groups = {g: group_stats([w for w in wallets if g in w["g"]]) for g in GROUPS}
    split = age_split(wallets, checked)
    best = best_lists(checked, wallets)
    best_ids = {x["addr"] for lst in best["groups"].values() for x in lst}
    gpath = os.path.join(data_dir, "hl_groups.json")
    gdoc = _read(gpath, {})
    series = gdoc.get("series") or {}
    comp_ev = gdoc.get("comp") if "comp" in gdoc else list(FLOW_SEED)
    t = int(now // 900 * 900)
    append_series(series, t, groups)
    append_split(series, t, split)
    mpath = os.path.join(data_dir, "hl_members.json")
    prev_m = _read(mpath, None)
    if prev_m:                                        # 93: przepływy od drugiego przebiegu z tym plikiem
        flows, comp = group_flows(prev_m, wallets, failed)
        append_flows(series, t, flows, groups)
        for g, c in comp.items():
            if c["in"] or c["out"]:
                comp_ev.append(dict(c, t=t, g=g))
    else:
        append_flows(series, t, {}, groups)
    comp_ev = comp_ev[-KEEP_COMP:]
    _write(mpath, members_doc(wallets, prev_m or {}, failed, now))
    _write(gpath, {"series": series, "comp": comp_ev})
    _write(os.path.join(data_dir, "hl_now.json"), {"at": int(now), "groups": groups, "prices": px,
                                                    "changes": changes(series, t),
                                                    "age_split": split, "best": best})
    _write(os.path.join(data_dir, "hl_wallets.json"), {"at": int(now), "wallets": [w for w in wallets if w["pos"] or w["ev"] or w["addr"] in best_ids]})
    _write(os.path.join(data_dir, "hl_meta.json"), {
        "at": int(now), "seconds": round(clock() - t0), "fails": fails, "weight": hl.weight,
        "sito": {"round_started": sito.get("round_started"), "total": sito.get("round_total"),
                 "left": len(sito.get("queue") or []), "checked": len(checked), "in_sito": sito.get("in_sito"),
                 "losers": len(losers), "updated": sito.get("updated"), "params": sito.get("params")},
        "groups_n": {g: groups[g]["n"] for g in GROUPS}, "daily_saved": daily_saved})
    return groups


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("sito", "positions"))
    ap.add_argument("--sito-dir", required=True)
    ap.add_argument("--data-dir")
    ap.add_argument("--minutes", type=float, default=270)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.cmd == "sito":
        n, st = run_sito(a.sito_dir, a.minutes)
        print(f"Sprawdzono {n} portfeli; w kolejce {len(st.get('queue') or [])}; w sicie: {st.get('in_sito')}")
    else:
        g = run_positions(a.data_dir, a.sito_dir)
        print("Grupy:", {k: (v["n"], v["in_pos"], v["lpct"]) for k, v in g.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
