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
wiek konta ≥ 365 dni, < 200 transakcji / dzień; strona oceniana przy ≥ 10 zagraniach, „skuteczny” = zyski ≥ 1,2× strat.
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
SITO = {"min_av": 100e3, "min_age_days": 365, "max_fills_day": 200, "min_trips": 10, "min_pf": 1.2,
        "round_days": 7, "losers": 300, "losers_min_av": 10e3}
WEIGHT_PER_MIN = 1100                 # limit HL 1200 wag / min na IP — zostawiamy zapas
LEV_BUCKETS = ((0, 3, "do ×3"), (3, 10, "×3–10"), (10, 20, "×10–20"), (20, 1e9, "ponad ×20"))
KEEP_EVENTS = 10
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
    sides = []
    ok_base = (p["age_days"] or 0) >= cfg["min_age_days"] and p["fills_per_day"] < cfg["max_fills_day"]
    for side, key in (("L", "long"), ("S", "short")):
        st = p[key]
        if ok_base and st["n"] >= cfg["min_trips"] and (st["pf"] or 0) >= cfg["min_pf"]:
            sides.append(side)
    reason = None
    if not p["trips"]:
        reason = "brak zagrań perpami"
    elif p["fills_per_day"] >= cfg["max_fills_day"]:
        reason = "bot / market maker"
    elif max(p["long"]["n"], p["short"]["n"]) < cfg["min_trips"]:
        reason = "za mało zagrań"
    elif (p["age_days"] or 0) < cfg["min_age_days"]:
        reason = "za młode konto"
    elif not sides:
        reason = "nieskuteczny"

    def side(st):
        return {"n": st["n"], "win": _r(st["win_pct"], 1), "pf": _r(st["pf"]), "pnl": _r(st["pnl"], 0)}
    return {"age": _r(p["age_days"], 0), "mpos": _r(p["months_pos_pct"], 0), "tw": _r(p["trips_per_week"], 1),
            "fpd": _r(p["fills_per_day"], 1), "trips": p["trips"], "L": side(p["long"]), "S": side(p["short"]),
            "p7": _r(period_pnl(per, "perpWeek") or period_pnl(per, "week"), 0),
            "p30": _r(period_pnl(per, "perpMonth") or period_pnl(per, "month"), 0),
            "dd": _r(max_drawdown(at.get("accountValueHistory")), 1), "sides": sides, "why": reason}


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
        st["checked"] = {k: v for k, v in old.items() if v.get("at", 0) >= now - 2 * cfg["round_days"] * DAY}
        st.update({"queue": cand, "losers": los, "round_started": int(now), "round_total": len(cand)})
        log.info("Nowa runda sita: %d kandydatów, %d tracących", len(cand), len(los))
    st.setdefault("checked", {})
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


def value_at(arr, t):
    """Ostatnia wartość nie później niż t (± 30 min)."""
    best = None
    for tt, v in arr:
        if tt <= t + 1800:
            best = v
        else:
            break
    return best


def changes(series, now, top=8):
    out = []
    for win, sec in (("2 h", 2 * 3600), ("24 h", DAY), ("7 dni", 7 * DAY)):
        for g in GROUPS:
            for c in COINS:
                for side in ("long", "short"):
                    arr = series.get(f"{g}_{c}_{side}") or []
                    if len(arr) < 2 or arr[0][0] > now - sec + 1800:
                        continue
                    a, b = value_at(arr, now - sec), arr[-1][1]
                    if a is None or b is None:
                        continue
                    lp = series.get(f"{g}_{c}_lpct") or []
                    out.append({"g": g, "c": c, "win": win, "side": side, "delta": round(b - a), "from": a, "to": b,
                                "lpct_from": value_at(lp, now - sec), "lpct_to": lp[-1][1] if lp else None})
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


def run_positions(data_dir, sito_dir, session=None, sleep=time.sleep, clock=time.time):
    s = session or requests.Session()
    now = clock()
    t0 = now
    sito = _read(os.path.join(sito_dir, "sito.json"), {})
    checked = sito.get("checked") or {}
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
    wallets, fails = [], 0
    for a in list(members) + [x for x in losers if x not in members]:
        try:
            av, pos = parse_state(hl.call({"type": "clearinghouseState", "user": a}, 2))
            orders = parse_orders(hl.call({"type": "frontendOpenOrders", "user": a}, 20)) if pos else []
        except Exception:  # noqa: BLE001
            fails += 1
            continue
        groups = list(members.get(a, [])) + (["R"] if a in losers and a not in members else [])
        info = checked.get(a) or {}
        w = {"addr": a, "g": groups, "av": _r(av, 0), "pos": pos, "ord": orders,
             "prof": {k: info.get(k) for k in ("age", "mpos", "tw", "L", "S", "p7", "p30", "dd")} if info else None}
        w["ev"] = events(prev.get(a), pos, now)
        wallets.append(w)
    groups = {g: group_stats([w for w in wallets if g in w["g"]]) for g in GROUPS}
    gpath = os.path.join(data_dir, "hl_groups.json")
    series = (_read(gpath, {}).get("series") or {})
    t = int(now // 900 * 900)
    append_series(series, t, groups)
    _write(gpath, {"series": series})
    _write(os.path.join(data_dir, "hl_now.json"), {"at": int(now), "groups": groups, "prices": px,
                                                    "changes": changes(series, t)})
    _write(os.path.join(data_dir, "hl_wallets.json"), {"at": int(now), "wallets": [w for w in wallets if w["pos"] or w["ev"]]})
    _write(os.path.join(data_dir, "hl_meta.json"), {
        "at": int(now), "seconds": round(clock() - t0), "fails": fails, "weight": hl.weight,
        "sito": {"round_started": sito.get("round_started"), "total": sito.get("round_total"),
                 "left": len(sito.get("queue") or []), "checked": len(checked), "in_sito": sito.get("in_sito"),
                 "losers": len(losers), "updated": sito.get("updated"), "params": sito.get("params")},
        "groups_n": {g: groups[g]["n"] for g in GROUPS}})
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
