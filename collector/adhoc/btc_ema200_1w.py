"""Raport specjalny: BTC przy EMA200 na świecy tygodniowej (zamówiony 13.11.2026).

Pytanie: BTC po 12 tygodniach nad EMA200 1W zszedł knotem pod nią (tydzień jeszcze się nie zamknął). Jak cena zachowywała
się w historii, gdy po tygodniach nad średnią knoty schodziły w jej okolice albo pod nią, ale tygodnie zamykały się nad
nią (jak w 2023, gdy BTC odbijał się od średniej przez 7 tygodni) — ile to trwało, jak głęboko, czym się kończyło, co
działo się potem z BTC i altami. Okresy w bessie przed dnem cyklu pokazane osobno — to inna sytuacja, nie analogia
(teraz jesteśmy po dnie). Do tego: tło na początku podobnych okresów, cena między EMA200 1D a 1W, lewar w trakcie,
okresy pod średnią po zamknięciu tygodnia pod nią, pierwsze wybicie po dnie, przeliczenie na dziś, poziomy.

Definicje (zamknięcia dzienne UTC px_btc: INDEX:BTCUSD + Coinalyze; knoty px_btc_lo / _hi: do 2019–2020 indeks TradingView,
potem Binance perp; tydzień = pon.–nd. UTC; EMA200 1W = ta.ema(200) z zamknięć tygodni, bieżący tydzień = cena teraz):
  tydzień przy średniej — najniższa cena tygodnia (knot) najwyżej ZONE nad EMA200 1W albo pod nią;
  epizod               — po tygodniu nad średnią (zamknięcie nad, knot wyżej niż strefa) kolejne tygodnie przy średniej
                         (przerwy do GAP tygodni); koniec = zamknięcie tygodnia pod EMA200 1W albo odejście ceny w górę;
  grupa A / B          — epizod po dnie bessy (faza akumulacji, jak teraz) / w trakcie bessy przed dnem (fazy z cycle.phases).
Kwoty w $ z różnych lat są nieporównywalne (rynek futures wielokrotnie urósł) — likwidacje jako % OI, CVD jako % wolumenu,
OI jako zmiana %.
"""
import bisect
from datetime import datetime, timezone

import cycle as C
import report as R

TITLE = "BTC przy EMA200 na świecy tygodniowej"
DAY = 86400
WEEK = 7 * DAY
ZONE = 0.03        # tydzień „przy średniej”: knot ≤ 3% nad EMA200 1W (albo pod nią)
GAP = 2            # przerwy do 2 tygodni nie kończą epizodu
ALPHA = 2 / 201
NOW_COLOR = "#f7931a"
COLORS = ["#8e8e8e", "#5b9cf6", "#4caf7d", "#ce93d8", "#4dd0e1", "#ff8a65", "#90a4ae"]   # kolejne okresy grupy A
PHASE_COLORS = {"bull": "#4caf7d", "bear": "#e05252", "acc": "#5b9cf6", "unsure": "#b39ddb"}
PHASE_PL = {"bull": "hossa", "bear": "bessa", "acc": "akumulacja"}
EMA_W_COLOR = "#ce93d8"
EMA_D_COLOR = "#bbbbbb"
NOTES = {   # przypisy do wyjątkowych tygodni (poniedziałek tygodnia) → (tekst, szok: True = zawyża głębokość spadku)
    "2015-08-17": ("flash crash 18.08.2015 — knot $162 (indeks TradingView) poniżej dna bessy; zamknięcia dzienne nie zeszły "
                   "pod dno", True),
    "2020-03-09": ("covid — krach jednocześnie na wszystkich rynkach", True),
    "2023-06-05": ("pozwy SEC przeciw Binance i Coinbase (06.2023) — mocny spadek altów", False),
}


# ── liczenie ─────────────────────────────────────────────────
def ema_list(vals, n):
    out = [None] * len(vals)
    if len(vals) < n:
        return out
    a = 2 / (n + 1)
    out[n - 1] = sum(vals[:n]) / n
    for i in range(n, len(vals)):
        out[i] = a * vals[i] + (1 - a) * out[i - 1]
    return out


def sma_list(vals, n):
    out, s = [None] * len(vals), 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def week_of(t):
    return (int(t) // DAY + 3) // 7          # tydzień pon.–nd. UTC (1970-01-01 = czwartek)


def monday(w):
    return (w * 7 - 3) * DAY


def weeks(ts, cl, hi, lo):
    """Świece tygodniowe z dziennych → [{w, t0 (poniedziałek), t (ostatni dzień), o, h, l, c, days}]."""
    out = []
    for t, c in zip(ts, cl):
        w = week_of(t)
        h, l_ = max(hi.get(t, c), c), min(lo.get(t, c), c)
        if out and out[-1]["w"] == w:
            x = out[-1]
            x.update(t=t, c=c, h=max(x["h"], h), l=min(x["l"], l_), days=x["days"] + 1)
        else:
            o = out[-1]["c"] if out else c
            out.append({"w": w, "t0": monday(w), "t": t, "o": o, "h": max(h, o), "l": min(l_, o), "c": c, "days": 1})
    return out


def in_zone(x):
    return x["e"] is not None and x["l"] <= x["e"] * (1 + ZONE)


def find_episodes(W):
    """Epizody „przy średniej” → [(i0, i1, down)]; down = koniec zamknięciem tygodnia pod EMA200 1W."""
    out, i = [], 1
    while i < len(W):
        x, p = W[i], W[i - 1]
        if p["e"] is not None and in_zone(x) and p["c"] > p["e"] and not in_zone(p):
            last, j, down = i, i, x["c"] < x["e"]
            while not down and j + 1 < len(W):
                j += 1
                if W[j]["c"] < W[j]["e"]:
                    last, down = j, True
                elif in_zone(W[j]):
                    last = j
                elif j - last > GAP:
                    break
            out.append((i, last, down))
            i = last + 1
        else:
            i += 1
    return out


def runs_below_w(W, a=0):
    """Okresy z zamknięciami tygodni pod EMA200 1W → [(i0, i1)]."""
    out, st = [], None
    for i in range(a, len(W)):
        below = W[i]["e"] is not None and W[i]["c"] < W[i]["e"]
        if below and st is None:
            st = i
        if not below and st is not None:
            out.append((st, i - 1))
            st = None
    if st is not None:
        out.append((st, len(W) - 1))
    return out


def phase_at(phs, t):
    for p in phs:
        if p["from"] <= t and (p.get("to") is None or t < p["to"]):
            return "unsure" if p["phase"] == "acc" and p.get("confirmed") is False else p["phase"]
    return None


def at(pts, t, tol=10 * DAY):
    """Wartość serii [[t, v]] w dniu t albo ostatnia wcześniejsza (do tol)."""
    if not pts:
        return None
    i = bisect.bisect_right(pts[0], t) - 1
    return pts[1][i] if i >= 0 and t - pts[0][i] <= tol else None


def ser(d, sid):
    p = d.pts("1d", sid)
    return ([int(t) for t, _ in p], [v for _, v in p])


def chg(a, b):
    return None if not a or b is None else b / a - 1


# ── formatowanie ─────────────────────────────────────────────
def dmy(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%d.%m.%Y")


def dm(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%d.%m")


def iso(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d")


def pctf(x, dec=1):
    return "—" if x is None else f"{x * 100:+.{dec}f}%".replace(".", ",")


def usd(v):
    return "—" if v is None else R.fmt_price(v)


def weeks_pl(n):
    return f"{n} tydz." if n != 1 else "1 tydz."


def span(a, b):
    """Zakres dat: 03–23.08.2015, 16.03–05.04.2015, 29.12.2014–18.01.2015."""
    A, B = dmy(a), dmy(b)
    if A[-4:] != B[-4:]:
        return f"{A}–{B}"
    if A[3:5] != B[3:5]:
        return f"{A[:5]}–{B}"
    return f"{A[:2]}–{B}"


# ── raport ───────────────────────────────────────────────────
def build(d, ema, cfg, now):
    px = d.pts("1d", "px_btc")
    if len(px) < 1500:
        return {"why": "Brak historii ceny BTC w danych (px_btc) — raportu nie da się policzyć.", "summary": "", "blocks": []}
    ts = [int(t) for t, _ in px]
    cl = [v for _, v in px]
    hi = {int(t): v for t, v in d.pts("1d", "px_btc_hi")}
    lo = {int(t): v for t, v in d.pts("1d", "px_btc_lo")}
    W = weeks(ts, cl, hi, lo)
    for x, e in zip(W, ema_list([x["c"] for x in W], 200)):
        x["e"] = e
    widx = {x["w"]: i for i, x in enumerate(W)}
    e1d = ema_list(cl, 200)
    di = {t: i for i, t in enumerate(ts)}

    def ew_live(t):
        """EMA200 1W w dniu t tak, jak na świecy tygodniowej w trakcie tygodnia (bieżący tydzień = zamknięcie dnia t)."""
        i = widx[week_of(t)]
        pe = W[i - 1]["e"] if i > 0 else None
        return None if pe is None else ALPHA * cl[di[t]] + (1 - ALPHA) * pe

    phs = C.phases(dict(zip(ts, cl)), C.ccfg(cfg).get("bottoms") or ())
    bottoms = [p["from"] for p in phs if p["phase"] == "acc"]
    partial = datetime.fromtimestamp(ts[-1], timezone.utc).weekday() != 6
    eps = find_episodes(W)
    S = dict(d=d, ema=ema, ts=ts, cl=cl, hi=hi, lo=lo, W=W, e1d=e1d, di=di, ew=ew_live, phs=phs, bottoms=bottoms,
             partial=partial, now=now, eps=[ep_info(W, ts, cl, ew_live, phs, bottoms, partial, *ep) for ep in eps])
    A = [x for x in S["eps"] if x["group"] == "A"]
    B = [x for x in S["eps"] if x["group"] == "B"]
    S["A"], S["B"] = A, B
    for k, ep in enumerate(A):
        ep["color"] = NOW_COLOR if ep["ongoing"] else COLORS[k % len(COLORS)]
    cur = A[-1] if A and A[-1]["ongoing"] else None
    S["cur"] = cur

    n = len(W) - 1
    x = W[n]
    blocks = [{"type": "section", "title": "Teraz"}, now_facts(S), weekly_chart(S)]
    blocks += [{"type": "section", "title": "Cena przy EMA200 1W po dnie bessy — jak teraz"},
               table_a(S), overlay_chart(S), weeks_table(S),
               daily_chart(S, "2023-04-17", "2023-11-19", "Rok 2023: cena przy EMA200 1W dzień po dniu"),
               daily_chart(S, iso(W[max(0, n - 20)]["t0"]), iso(ts[-1]), "Teraz: cena przy EMA200 1W dzień po dniu"),
               table_b(S)]
    blocks += [{"type": "section", "title": "Teraz na tle podobnych okresów"}, compare_table(S)]
    blocks += [{"type": "section", "title": "Cena między EMA200 1D a EMA200 1W"}, between_table(S)]
    blocks += [{"type": "section", "title": "Lewar i przewaga kupujących w trakcie"}, leverage_table(S), oi_chart(S)]
    blocks += [{"type": "section", "title": "Alty, gdy BTC testuje średnią"}, alts_table(S), alts_chart(S)]
    blocks += [{"type": "section", "title": "Gdy tydzień zamknął się pod średnią"}, below_table(S)]
    blocks += [{"type": "section", "title": "Pierwsze wybicie nad EMA200 1W po dnie"}, breakout_table(S)]
    blocks += [{"type": "section", "title": "Przeliczenie na dziś i poziomy"}, repeat_table(S), levels_table(S)]
    blocks += [{"type": "section", "title": "Na co patrzeć"}, watch_block(S)]

    dist = x["c"] / x["e"] - 1
    wk_txt = "tydzień jeszcze trwa" if partial else "tydzień zamknięty"
    why = (f"W tygodniu {span(x['t0'], x['t0'] + 6 * DAY)} BTC zszedł pod EMA200 na świecy tygodniowej: najniżej "
           f"{usd(x['l'])} ({pctf(x['l'] / x['e'] - 1)} od średniej {usd(x['e'])}), teraz {usd(x['c'])} ({pctf(dist)}); "
           f"{wk_txt}. Wcześniej cena była nad tą średnią przez {cur['above_before'] if cur else '—'} tygodni. "
           "Raport sprawdza, jak BTC zachowywał się w historii, gdy po okresie nad średnią knoty schodziły w jej okolice albo pod "
           "nią — ile to trwało, jak głęboko, czym się kończyło i co działo się potem z BTC i altami. Główne porównanie: "
           "takie okresy po dnie bessy (jak teraz). Okresy w trakcie bessy przed dnem są osobno, jako ciekawostka — to inna "
           "sytuacja. Same dane z historii; przeliczenia na dzisiejsze ceny to szacunek, nie prognoza.")
    odb = [a for a in A if not a["ongoing"] and not a["down"]]
    summary = (f"BTC {usd(x['c'])}, EMA200 1W {usd(x['e'])} ({pctf(dist)}), knot tygodnia {pctf(x['l'] / x['e'] - 1)} · "
               f"po dnie bessy: {len(odb)} z {len([a for a in A if not a['ongoing']])} takich okresów skończyło się odbiciem bez "
               "zamknięcia tygodnia pod średnią")
    return {"why": why, "summary": summary, "blocks": blocks}


def ep_info(W, ts, cl, ew, phs, bottoms, partial, i0, i1, down):
    di = {t: i for i, t in enumerate(ts)}
    seg = W[i0:i1 + 1]
    ph = phase_at(phs, W[i0]["t0"])
    ongoing = i1 == len(W) - 1 and (partial or not down)
    k = i0 - 1
    while k > 0 and W[k - 1]["e"] is not None and W[k - 1]["c"] > W[k - 1]["e"]:
        k -= 1
    deep = min(seg, key=lambda x: x["l"] / x["e"])
    prev_b = max([b for b in bottoms if b <= W[i0]["t0"]], default=None)
    next_b = min([b for b in bottoms if b >= W[i0]["t0"] - 6 * DAY], default=None)
    note, shock = "", False
    for x in seg:
        if iso(x["t0"]) in NOTES:
            note, shock = NOTES[iso(x["t0"])]
    days = [t for t in ts if W[i0]["t0"] <= t <= W[i1]["t"]]
    below = [t for t in days if ew(t) is not None and cl[di[t]] < ew(t)]
    return {"i0": i0, "i1": i1, "down": down and not (ongoing and partial), "ongoing": ongoing, "phase": ph,
            "group": "A" if ph in ("acc", "unsure") else "B", "t0": W[i0]["t0"], "t1": W[i1]["t"], "weeks": len(seg),
            "wick_under": sum(1 for x in seg if x["l"] < x["e"]), "deep": deep["l"] / deep["e"] - 1, "deep_t": deep["t0"],
            "low": deep["l"], "close_min": min(x["c"] / x["e"] - 1 for x in seg), "above_before": i0 - k,
            "prev_bottom": prev_b, "next_bottom": next_b if ph == "bear" else None, "note": note, "shock": shock,
            "days": len(days), "days_below": len(below)}


def fwd(S, ep, wk):
    """Zmiana zamknięcia od ostatniego tygodnia epizodu po wk tygodniach."""
    W = S["W"]
    j = ep["i1"] + wk
    return None if ep["ongoing"] or j >= len(W) or (j == len(W) - 1 and S["partial"]) else W[j]["c"] / W[ep["i1"]]["c"] - 1


def end_txt(ep):
    if ep["ongoing"]:
        return "trwa"
    return "tydzień zamknięty pod średnią" if ep["down"] else "odbicie — żaden tydzień nie zamknął się pod średnią"


# ── bloki: teraz ─────────────────────────────────────────────
def now_facts(S):
    W, cl, ts, e1d, cur, partial = S["W"], S["cl"], S["ts"], S["e1d"], S["cur"], S["partial"]
    x = W[-1]
    close_t = x["t0"] + 7 * DAY
    left_h = max(0, (close_t - S["now"]) / 3600)
    items = [
        {"label": "Cena BTC", "value": usd(x["c"]), "sub": f"{dmy(ts[-1])}" + (" — tydzień w trakcie" if partial else ""),
         "zone": None, "note": "Ostatnia cena z danych (skan co ~2 h)."},
        {"label": "EMA200 1W", "value": usd(x["e"]), "sub": f"cena {pctf(x['c'] / x['e'] - 1)} od średniej",
         "zone": "yellow" if abs(x["c"] / x["e"] - 1) <= ZONE else None,
         "note": "Średnia z zamknięć 200 tygodni (ok. 4 lata), nowsze tygodnie ważą więcej (jak ta.ema(200) w TradingView). "
                 "W trakcie tygodnia liczona z ceny teraz — zmienia się z ceną."},
        {"label": "Najniżej w tym tygodniu (knot)", "value": usd(x["l"]), "sub": f"{pctf(x['l'] / x['e'] - 1)} od średniej",
         "zone": None, "note": "Najniższa cena tygodnia (pon.–nd. UTC); knoty z Binance perp."},
        {"label": "Zamknięcie tygodnia", "value": R.utc(close_t - 60, "%d.%m %H:%M UTC"),
         "sub": (f"za ok. {left_h:.0f} h · w Polsce {R.pl_time(close_t - 60, '%d.%m %H:%M')}" if partial else "tydzień zamknięty"),
         "zone": None, "note": "O tym, czy cena jest pod średnią na świecy tygodniowej, decyduje zamknięcie tygodnia, nie knot."},
        {"label": "Wcześniej nad EMA200 1W", "value": f"{cur['above_before'] if cur else '—'} tyg.",
         "sub": f"od {dmy(W[cur['i0'] - cur['above_before']]['t0'])}" if cur else "", "zone": None,
         "note": "Kolejne tygodnie zamknięte nad średnią przed obecnym tygodniem."},
        {"label": "EMA200 1D", "value": usd(e1d[-1]), "sub": f"cena {pctf(cl[-1] / e1d[-1] - 1)} od dziennej średniej",
         "zone": None, "note": "Średnia z 200 zamknięć dziennych — porównanie w sekcji „Cena między EMA200 1D a EMA200 1W”."},
    ]
    if S["bottoms"]:
        b = S["bottoms"][-1]
        items.append({"label": "Od dna bessy", "value": f"{(ts[-1] - b) // WEEK} tyg.", "sub": f"dno {dmy(b)}, {usd(cl[S['di'][b]])}",
                      "zone": None, "note": "Dno cyklu (zamknięcie dnia) — fazy jak w raporcie miesięcznym."})
    return {"type": "facts", "title": "BTC i EMA200 1W teraz", "items": items}


def weekly_chart(S):
    W, phs = S["W"], S["phs"]
    a = next(i for i, x in enumerate(W) if x["e"] is not None)
    cand = [[x["t"], x["o"], x["h"], x["l"], x["c"]] for x in W[a:]]
    marks = []
    for i in range(a + 1, len(W)):
        was, now_ = W[i - 1]["c"] > W[i - 1]["e"], W[i]["c"] > W[i]["e"]
        if was != now_:
            marks.append({"t": W[i]["t"], "shape": "up" if now_ else "down", "pos": "below" if now_ else "above",
                          "color": "#4caf7d" if now_ else "#e05252"})
    t_first, t_last = W[a]["t"], W[-1]["t"]
    bands = []
    for p in phs:
        f, t = p["from"], p.get("to") or t_last
        if t < t_first:
            continue
        key = "unsure" if p["phase"] == "acc" and p.get("confirmed") is False else p["phase"]
        bands.append({"from": max(f, t_first), "to": min(t, t_last), "color": PHASE_COLORS[key],
                      "label": PHASE_PL[p["phase"]] + (" (niepotwierdzona)" if key == "unsure" else "")})
    return {"type": "chart", "title": "BTC — świece tygodniowe i EMA200 1W od 2013", "log": True, "view": 1095,
            "desc": "Każda świeca to tydzień (pon.–nd. UTC), skala logarytmiczna. Fioletowa linia = EMA200 1W, przerywana = 3% nad "
                    "nią (górna granica strefy „przy średniej”). Strzałki: ↓ pierwsze zamknięcie tygodnia pod średnią, ↑ pierwsze "
                    "nad nią. Tło = fazy cyklu.",
            "note": "Średnia liczy się od 09.2013 (potrzebuje 200 tygodni danych od 2009). Knoty: do 2019–2020 indeks TradingView, "
                    "potem Binance perp. Ostatnia świeca: tydzień w trakcie." if S["partial"] else "",
            "bands": bands, "markers": marks,
            "series": [{"name": "BTC — świece tygodniowe", "color": NOW_COLOR, "fmt": "price", "scale": "right",
                        "data": [[x["t"], x["c"]] for x in W[a:]], "ohlc": cand},
                       {"name": "EMA200 1W", "color": EMA_W_COLOR, "fmt": "price", "scale": "right",
                        "data": [[x["t"], round(x["e"], 2)] for x in W[a:]]},
                       {"name": "EMA200 1W + 3%", "color": EMA_W_COLOR, "fmt": "price", "scale": "right", "dash": True, "width": 1,
                        "data": [[x["t"], round(x["e"] * (1 + ZONE), 2)] for x in W[a:]]}]}


# ── bloki: epizody ───────────────────────────────────────────
def ep_when(ep):
    return f"od {dmy(ep['t0'])}" if ep["ongoing"] else span(ep["t0"], ep["t1"])


def table_a(S):
    rows, notes = [], []
    for ep in S["A"]:
        mark = ""
        if ep["note"]:
            notes.append(ep["note"])
            mark = " " + "¹²³⁴"[len(notes) - 1]
        after = " / ".join(pctf(fwd(S, ep, k), 0) for k in (4, 13, 26))
        rows.append([ep_when(ep) + (" (teraz)" if ep["ongoing"] else ""),
                     f"{(ep['t0'] - ep['prev_bottom']) // WEEK} tyg." if ep["prev_bottom"] else "—",
                     str(ep["weeks"]) + (" (trwa)" if ep["ongoing"] else ""), str(ep["wick_under"]),
                     pctf(ep["deep"]) + mark, end_txt(ep), "—" if ep["ongoing"] else after])
    return {"type": "table", "title": "Kiedy cena po dnie bessy wracała do EMA200 1W",
            "cols": ["Kiedy", "Ile po dnie bessy", "Tygodni przy średniej", "W tym tygodni z knotem pod średnią",
                     "Najniżej pod średnią (knot)", "Czym się skończyło", "Cena 1 / 3 / 6 mies. później"],
            "rows": rows, "left": [0, 5], "plain": True,
            "desc": "Okresy po dnie bessy (ta sama faza cyklu co teraz), w których po tygodniach nad EMA200 1W najniższa cena tygodnia "
                    f"zeszła do {ZONE * 100:.0f}% nad średnią albo pod nią. „Tydzień przy średniej” = taki tydzień; okres trwa, dopóki "
                    f"takie tygodnie się powtarzają (przerwy do {GAP} tyg.). Kończy się zamknięciem tygodnia pod średnią albo "
                    "odejściem ceny w górę. Ostatni wiersz = teraz.",
            "note": " ".join(f"{'¹²³⁴'[k]} {t}." for k, t in enumerate(notes)) +
                    " Cena później = zmiana od zamknięcia ostatniego tygodnia okresu (po 4, 13 i 26 tygodniach). Najniżej pod "
                    "średnią: + = knot nad średnią, − = pod nią. Tydzień = pon.–nd. UTC."}


def table_b(S):
    rows = []
    for ep in S["B"]:
        nb = ep["next_bottom"]
        if nb is None:
            when = "—"
        elif nb <= ep["t1"]:
            when = f"w trakcie ({dmy(nb)})"
        else:
            when = f"{(nb - ep['t0']) // WEEK} tyg. później"
        after = " / ".join(pctf(fwd(S, ep, k), 0) for k in (4, 13, 26))
        rows.append([ep_when(ep), PHASE_PL.get(ep["phase"], "—"), when, str(ep["weeks"]), str(ep["wick_under"]),
                     pctf(ep["deep"]), end_txt(ep), after])
    return {"type": "table", "title": "Ciekawostka: to samo w trakcie bessy, przed dnem — inna sytuacja, nie analogia",
            "cols": ["Kiedy", "Faza", "Kiedy przyszło dno bessy", "Tygodni przy średniej", "W tym tygodni z knotem pod średnią",
                     "Najniżej pod średnią (knot)", "Czym się skończyło", "Cena 1 / 3 / 6 mies. później"],
            "rows": rows, "left": [0, 1, 2, 6], "plain": True,
            "desc": "Te same okresy, ale w bessie — cena spadała od szczytu cyklu, a dno było jeszcze przed nią. Teraz jesteśmy po "
                    "dnie, więc tych okresów nie należy brać jako porównania. Liczone tak samo jak tabela wyżej.",
            "note": "Cena później = zmiana od zamknięcia ostatniego tygodnia okresu (po 4, 13 i 26 tygodniach)."}


def overlay_chart(S):
    cl, ew, di = S["cl"], S["ew"], S["di"]
    series = []
    for ep in S["A"]:
        t0 = ep["t0"]
        pts = []
        for k in range(-14, 92):
            t = t0 + k * DAY
            if t in di and ew(t):
                pts.append([k, round((cl[di[t]] / ew(t) - 1) * 100, 2)])
        if not pts:
            continue
        if ep["ongoing"]:
            series.append({"name": "teraz", "color": NOW_COLOR, "fmt": "chg", "scale": "right", "width": 3, "data": pts})
        else:
            series.append({"name": ep_when(ep), "color": ep["color"], "fmt": "chg", "scale": "right", "data": pts})
    series.sort(key=lambda s: s["name"] == "teraz")
    return {"type": "chart", "x": "days", "title": "Cena vs EMA200 1W dzień po dniu — okresy po dnie bessy nałożone",
            "desc": "Dzień 0 = poniedziałek pierwszego tygodnia przy średniej. Linia = zamknięcie dnia vs EMA200 1W (tak jak średnia "
                    "wyglądała na świecy tygodniowej tego dnia). Poniżej 0% = cena pod średnią. Gruba pomarańczowa = teraz.",
            "note": "Od 2 tygodni przed do ok. 13 tygodni po początku okresu. Zamknięcia dzienne, bez knotów. Oś ucięta na −25% i "
                    "+30% (covid 2020 i flash crash 2015 wychodzą poza nią).", "range": [-25, 30],
            "lines": [{"value": 0, "label": "EMA200 1W", "color": "#888"},
                      {"value": ZONE * 100, "label": f"{ZONE * 100:.0f}% nad średnią", "color": "#555"}], "series": series}


def weeks_table(S):
    W, rows = S["W"], []
    for ep in S["A"]:
        seg = W[ep["i0"]:ep["i1"] + 1]
        cells_l, cells_c = [], []
        for x in seg:
            dl, dc = x["l"] / x["e"] - 1, x["c"] / x["e"] - 1
            cells_l.append({"t": f"{dm(x['t0'])}: {pctf(dl)}", "tone": "neg" if dl < 0 else None})
            cells_c.append({"t": f"{dm(x['t0'])}: {pctf(dc)}" + (" (trwa)" if x is W[-1] and S["partial"] else ""),
                            "tone": "neg" if dc < 0 else None})
        rows.append([ep_when(ep), cells_l, cells_c, f"{ep['days_below']} z {ep['days']}"])
    return {"type": "table", "title": "Tydzień po tygodniu: knot i zamknięcie vs EMA200 1W",
            "cols": ["Okres", "Najniżej w tygodniu (knot) vs średnia", "Zamknięcie tygodnia vs średnia",
                     "Dni zamknięte pod średnią"],
            "rows": rows, "left": [0, 1, 2], "plain": True, "even": True,
            "desc": "Każdy tydzień okresów z tabeli wyżej (data = poniedziałek). Czerwone = pod średnią.",
            "note": "Dni zamknięte pod średnią = zamknięcia dzienne pod EMA200 1W liczoną tak, jak na świecy tygodniowej w danym "
                    "dniu."}


def daily_ohlc(S, a, b):
    ts, cl, hi, lo = S["ts"], S["cl"], S["hi"], S["lo"]
    out = []
    for i, t in enumerate(ts):
        if a <= t <= b:
            o = cl[i - 1] if i else cl[i]
            out.append([t, o, max(hi.get(t, cl[i]), cl[i], o), min(lo.get(t, cl[i]), cl[i], o), cl[i]])
    return out


def daily_chart(S, a_iso, b_iso, title):
    a, b = C.day_of(a_iso), C.day_of(b_iso)
    ts, cl, e1d, ew, di = S["ts"], S["cl"], S["e1d"], S["ew"], S["di"]
    rng = [t for t in ts if a <= t <= b]
    ew_pts = [[t, round(ew(t), 2)] for t in rng if ew(t)]
    return {"type": "chart", "title": title,
            "desc": "Świece dzienne. Fioletowa = EMA200 1W (wartość z danego dnia, tak jak na świecy tygodniowej), przerywana = "
                    "3% nad nią, szara = EMA200 1D (średnia z 200 dni).",
            "note": "Knoty: Binance perp (Coinalyze).",
            "series": [{"name": "BTC — świece dzienne", "color": NOW_COLOR, "fmt": "price", "scale": "right",
                        "data": [[t, cl[di[t]]] for t in rng], "ohlc": daily_ohlc(S, a, b)},
                       {"name": "EMA200 1W", "color": EMA_W_COLOR, "fmt": "price", "scale": "right", "data": ew_pts},
                       {"name": "EMA200 1W + 3%", "color": EMA_W_COLOR, "fmt": "price", "scale": "right", "dash": True, "width": 1,
                        "data": [[t, round(v * (1 + ZONE), 2)] for t, v in ew_pts]},
                       {"name": "EMA200 1D", "color": EMA_D_COLOR, "fmt": "price", "scale": "right",
                        "data": [[t, round(e1d[di[t]], 2)] for t in rng]}]}


# ── bloki: tło ───────────────────────────────────────────────
def comp_eps(S):
    """Okresy do porównań: grupa A od 2019 (wcześniej brak danych o altach, derywatach i CVD) + teraz."""
    return [ep for ep in S["A"] if ep["t0"] >= C.day_of("2019-06-01")]


def col_name(ep):
    return "teraz" if ep["ongoing"] else datetime.fromtimestamp(ep["t0"], timezone.utc).strftime("%m.%Y")


def compare_table(S):
    d, ts, cl, e1d, di = S["d"], S["ts"], S["cl"], S["e1d"], S["di"]
    eps = comp_eps(S)
    sr = {k: ser(d, k) for k in ("rprice_btc", "oi_btc", "fund_btc", "oi_others_vs_btc", "ndx", "us10y", "vix", "dxy")}
    W = S["W"]

    def row(label, f):
        return [label] + [f(ep) for ep in eps]

    def t_(ep):
        return ep["t0"] - DAY

    def px(t):
        return at((ts, cl), t)

    def sma200w(t):
        wk = [x["c"] for x in W if x["t"] <= t and datetime.fromtimestamp(x["t"], timezone.utc).weekday() == 6][-200:]
        return sum(wk) / 200 if len(wk) == 200 else None

    def oi_coins(t):
        o, p = at(sr["oi_btc"], t), px(t)
        return o / p if o and p else None

    rows = [
        row("Cena ÷ realized price (MVRV)", lambda ep: f"{px(t_(ep)) / at(sr['rprice_btc'], t_(ep)):.2f}".replace(".", ",")
            if at(sr["rprice_btc"], t_(ep)) else "—"),
        row("Cena ÷ średnia 200 tygodni", lambda ep: f"{px(t_(ep)) / sma200w(t_(ep)):.2f}".replace(".", ",")
            if sma200w(t_(ep)) else "—"),
        row("EMA200 1D vs EMA200 1W", lambda ep: pctf(e1d[di[t_(ep)]] / W[ep["i0"] - 1]["e"] - 1, 0)),
        row("OI BTC w coinach — zmiana 30 dni przed", lambda ep: pctf(chg(oi_coins(t_(ep) - 30 * DAY), oi_coins(t_(ep))), 0)),
        row("Funding BTC (% rocznie, śr. 7 dni)", lambda ep: avg_fmt(sr["fund_btc"], t_(ep), 7)),
        row("Lewar altów (OI OTHERS ÷ OI BTC)", lambda ep: f"{at(sr['oi_others_vs_btc'], t_(ep)):.2f}".replace(".", ",")
            if at(sr["oi_others_vs_btc"], t_(ep)) else "—"),
        row("Nasdaq 100 — zmiana 30 dni przed", lambda ep: pctf(chg(at(sr["ndx"], t_(ep) - 30 * DAY), at(sr["ndx"], t_(ep))), 0)),
        row("Rentowność 10-letnich obligacji USA (30 dni przed → start)",
            lambda ep: (f"{at(sr['us10y'], t_(ep) - 30 * DAY):.2f} → {at(sr['us10y'], t_(ep)):.2f}%".replace(".", ",")
                        if at(sr["us10y"], t_(ep)) else "—")),
        row("VIX (strach na giełdzie USA)", lambda ep: f"{at(sr['vix'], t_(ep)):.0f}" if at(sr["vix"], t_(ep)) else "—"),
    ]
    return {"type": "table", "title": "Tło na początku okresu: teraz i po dnie bessy wcześniej",
            "cols": ["Miara"] + [col_name(ep) for ep in eps], "rows": rows, "left": [0], "plain": True,
            "desc": "Stan rynku dzień przed pierwszym tygodniem przy średniej. Kolumny = okresy po dnie bessy z tabeli wyżej (od 2019 — "
                    "wcześniej nie ma danych o derywatach) i teraz.",
            "note": "Rynek futures wielokrotnie urósł, więc kwoty w $ z różnych lat są nieporównywalne — tu tylko stosunki i zmiany "
                    "%. MVRV = cena ÷ średnia cena, po której BTC ostatnio się przemieścił (Coin Metrics). OI w coinach = OI w $ ÷ "
                    "cena (od 09.2022). Funding > ok. 11% rocznie = longi płacą shortom więcej niż zwykle."}


def avg_fmt(s, t, n):
    vals = [v for tt, v in zip(*s) if t - (n - 1) * DAY <= tt <= t] if s[0] else []
    return f"{sum(vals) / len(vals):.1f}%".replace(".", ",") if vals else "—"


def between_table(S):
    ts, cl, e1d, ew, phs = S["ts"], S["cl"], S["e1d"], S["ew"], S["phs"]
    rows, st, prev = [], None, None
    days = [t for i, t in enumerate(ts) if e1d[i] is not None and ew(t) is not None]
    di = S["di"]
    for t in days + [None]:
        ok = t is not None and cl[di[t]] < e1d[di[t]] and cl[di[t]] > ew(t) and phase_at(phs, t) in ("acc", "unsure")
        if ok and st is None:
            st = t
        if not ok and st is not None:
            n = (prev - st) // DAY + 1
            if n >= 5:
                if t is None:
                    how, after = "trwa", "—"
                else:
                    how = ("cena wróciła nad EMA200 1D" if cl[di[t]] >= e1d[di[t]] else
                           "dzień zamknięty pod EMA200 1W" if phase_at(phs, t) in ("acc", "unsure") else "koniec fazy")
                    j = di[prev] + 30
                    after = pctf(cl[j] / cl[di[prev]] - 1, 0) if j < len(cl) else "—"
                rows.append([span(st, prev), str(n), how, after])
            st = None
        prev = t
    # obecny stan, gdy dziś cena jest już pod obiema średnimi
    t = ts[-1]
    now_txt = ("pod EMA200 1D i nad EMA200 1W" if e1d[-1] > cl[-1] > ew(t) else
               "pod obiema średnimi" if cl[-1] < min(e1d[-1], ew(t)) else
               "nad obiema średnimi" if cl[-1] > max(e1d[-1], ew(t)) else "nad EMA200 1D, pod EMA200 1W")
    n_up = sum(1 for r in rows if r[2].startswith("cena wróciła"))
    n_dn = sum(1 for r in rows if r[2].startswith("dzień zamknięty"))
    return {"type": "table", "title": "Okresy, gdy cena była pod EMA200 1D, ale nad EMA200 1W (po dnie bessy)",
            "cols": ["Kiedy", "Ile dni", "Czym się skończyło", "Cena 30 dni po końcu"], "rows": rows, "left": [0, 2], "plain": True,
            "desc": f"Dzienna EMA200 (200 dni) i tygodniowa (200 tygodni) jako dwie podłogi: cena spadła pod dzienną, ale trzymała "
                    f"się nad tygodniową. Okresy co najmniej 5 dni, tylko po dnie bessy. Z zakończonych: {n_up} razy cena wróciła "
                    f"nad EMA200 1D, {n_dn} razy dzień zamknął się pod EMA200 1W. Teraz cena jest {now_txt}.",
            "note": "Zamknięcia dzienne; EMA200 1W liczona tak, jak na świecy tygodniowej w danym dniu. „Dzień zamknięty pod EMA200 "
                    "1W” to zamknięcie dnia, nie tygodnia."}


def leverage_table(S):
    d, ts, cl = S["d"], S["ts"], S["cl"]
    oi, fund = ser(d, "oi_btc"), ser(d, "fund_btc")
    liq = dict((int(t), v) for t, v in d.pts("1d", "liq_btc_long"))
    cvd = {k: dict((int(t), v) for t, v in d.pts("1d", k)) for k in
           ("cvd_btc_spot", "cvd_btc_spot_vol", "cvd_btc_perp", "cvd_btc_perp_vol")}
    eps = comp_eps(S)

    def px(t):
        return at((ts, cl), t)

    def coins(t):
        o, p = at(oi, t), px(t)
        return o / p if o and p else None

    def rng(ep):
        return [t for t in ts if ep["t0"] <= t <= ep["t1"]]

    def liq_pct(ep):
        r = [liq[t] / at(oi, t) for t in rng(ep) if t in liq and at(oi, t)]
        if not r:
            return "—", "—", "—"
        hist = sorted(liq[t] / at(oi, t) for t in liq if ep["t0"] - 365 * DAY <= t < ep["t0"] and at(oi, t))
        p90 = hist[int(0.9 * len(hist))] if hist else None
        mx = max(r)
        pc = sum(1 for h in hist if h < mx) / len(hist) if hist else None
        return (f"{sum(r) / len(r) * 100:.2f}%".replace(".", ","),
                f"{mx * 100:.2f}%".replace(".", ",") + (f" ({pc * 100:.0f}. percentyl)" if pc is not None else ""),
                f"{sum(1 for x in r if p90 and x > p90)} z {len(r)}")

    def cvd_pct(ep, k):
        t = rng(ep)
        s, v = sum(cvd[k].get(x, 0) for x in t), sum(cvd[k + "_vol"].get(x, 0) for x in t)
        return pctf(s / v) if v else "—"

    def fund_avg(a, b):
        vals = [v for t, v in zip(*fund) if a <= t <= b]
        return f"{sum(vals) / len(vals):.1f}%".replace(".", ",") if vals else None

    rows = [[ "OI BTC w coinach: tydzień przed → koniec okresu"] +
            [pctf(chg(coins(ep["t0"] - 7 * DAY), coins(ep["t1"])), 0) for ep in eps],
            ["Funding BTC: 2 tyg. przed → w trakcie (% rocznie)"] +
            [(f"{fund_avg(ep['t0'] - 14 * DAY, ep['t0'] - DAY)} → {fund_avg(ep['t0'], ep['t1'])}"
              if fund_avg(ep["t0"], ep["t1"]) else "—") for ep in eps]]
    lq = [liq_pct(ep) for ep in eps]
    rows += [["Likwidacje longów BTC — średnio dziennie (% OI)"] + [x[0] for x in lq],
             ["Najgorszy dzień likwidacji (% OI; miejsce na tle roku przed)"] + [x[1] for x in lq],
             ["Dni z likwidacjami większymi niż 90% dni roku przed"] + [x[2] for x in lq],
             ["CVD spot w trakcie (% wolumenu)"] + [cvd_pct(ep, "cvd_btc_spot") for ep in eps],
             ["CVD perp w trakcie (% wolumenu)"] + [cvd_pct(ep, "cvd_btc_perp") for ep in eps]]
    return {"type": "table", "title": "Lewar i przewaga kupujących w trakcie okresu przy średniej",
            "cols": ["Miara"] + [col_name(ep) + (" (do dziś)" if ep["ongoing"] else "") for ep in eps], "rows": rows,
            "left": [0], "plain": True,
            "desc": "Co działo się na kontraktach i na spocie, gdy cena była przy średniej. Spadek OI w coinach = pozycje z dźwignią "
                    "się zamykają (lewar się czyści); CVD ujemne = więcej sprzedaży „po rynku” niż kupna.",
            "note": "Rynek futures wielokrotnie urósł, więc kwot w $ z różnych lat nie porównujemy: likwidacje jako % OI na dzień i na "
                    "tle roku przed okresem, CVD jako % wolumenu. OI i likwidacje od 09.2022 (Binance, Bybit, OKX); CVD = suma "
                    "kwotowań na największych giełdach (Coinalyze)."}


def oi_chart(S):
    d, cl = S["d"], S["cl"]
    oi = dict((int(t), v) for t, v in d.pts("1d", "oi_btc"))
    di = S["di"]
    series = []
    for ep in comp_eps(S):
        base_t = ep["t0"] - DAY
        if base_t not in oi:
            continue
        base = oi[base_t] / cl[di[base_t]]
        pts = [[k, round(oi[t] / cl[di[t]] / base * 100, 2)] for k in range(-28, 92)
               for t in [ep["t0"] + k * DAY] if t in oi and t in di]
        if ep["ongoing"]:
            series.append({"name": "teraz", "color": NOW_COLOR, "fmt": "num", "scale": "right", "width": 3, "data": pts})
        else:
            series.append({"name": ep_when(ep), "color": ep["color"], "fmt": "num", "scale": "right",
                           "data": pts})
    series.sort(key=lambda s: s["name"] == "teraz")
    return {"type": "chart", "x": "days", "title": "OI BTC w coinach (100 = dzień przed okresem)",
            "desc": "Dzień 0 = poniedziałek pierwszego tygodnia przy średniej. Powyżej 100 = więcej otwartych pozycji na kontraktach "
                    "niż przed okresem, poniżej = pozycje się zamykały.",
            "note": "OI w $ ÷ cena BTC, czyli liczba BTC w otwartych pozycjach — niezależna od ceny. Dane od 09.2022.",
            "lines": [{"value": 100, "label": "dzień przed okresem", "color": "#888"}], "series": series}


def alts_table(S):
    d, ema = S["d"], S["ema"]
    sr = {k: ser(d, k) for k in ("px_btc", "total3es", "ethbtc")}
    br = sorted((int(t), v) for t, v, *_ in ((ema or {}).get("breadth") or []))
    brs = ([t for t, _ in br], [v for _, v in br])
    now = S["ts"][-1]
    rows = []
    for ep in comp_eps(S):
        t0, t1 = ep["t0"] - 7 * DAY, min(ep["t1"], now)
        row = [ep_when(ep) + (" (teraz)" if ep["ongoing"] else ""),
               f"{pctf(chg(at(sr['px_btc'], t0), at(sr['px_btc'], t1)), 0)} / {pctf(chg(at(sr['total3es'], t0), at(sr['total3es'], t1)), 0)}",
               pctf(chg(at(sr["ethbtc"], t0), at(sr["ethbtc"], t1)), 0),
               (f"{at(brs, t0):.0f}% → {at(brs, t1):.0f}%" if at(brs, t0) is not None and at(brs, t1) is not None else "—")]
        for k in (30, 91, 182):
            t2 = ep["t1"] + k * DAY
            row.append("—" if ep["ongoing"] or t2 > now else
                       f"{pctf(chg(at(sr['px_btc'], ep['t1']), at(sr['px_btc'], t2)), 0)} / "
                       f"{pctf(chg(at(sr['total3es'], ep['t1']), at(sr['total3es'], t2)), 0)}")
        t3 = ep["t1"] + 91 * DAY
        row.append("—" if ep["ongoing"] or t3 > now or at(brs, t3) is None else f"{at(brs, t3):.0f}%")
        rows.append(row)
    return {"type": "table", "title": "BTC i alty w trakcie i po okresie przy średniej",
            "cols": ["Okres", "W trakcie: BTC / alty", "W trakcie: ETH/BTC", "W trakcie: szerokość rynku",
                     "1 mies. później: BTC / alty", "3 mies. później: BTC / alty", "6 mies. później: BTC / alty",
                     "Szerokość rynku 3 mies. później"],
            "rows": rows, "left": [0], "plain": True,
            "desc": "Alty = kapitalizacja bez BTC, ETH i stablecoinów (TOTAL3ES). „W trakcie” = od tygodnia przed okresem do jego końca; "
                    "„później” = od końca okresu. Szerokość rynku = odsetek coinów Binance z ceną nad własną EMA200 1D.",
            "note": "Tylko okresy od 2019 (wcześniejsze dane o altach w TradingView są niepełne). Indeks OTHERS z TradingView pominięty "
                    "— skacze przy zmianach składu (np. 08.2023: OTHERS +14%, alty jako całość −1%). Szerokość rynku z wycofanymi "
                    "coinami (bez błędu przeżywalności)."}


def alts_chart(S):
    d = S["d"]
    s = dict((int(t), v) for t, v in d.pts("1d", "alts_vs_btc"))
    series = []
    for ep in comp_eps(S):
        base_t = ep["t0"] - DAY
        if base_t not in s:
            continue
        pts = [[k, round(s[t] / s[base_t] * 100, 2)] for k in range(-28, 183) for t in [ep["t0"] + k * DAY] if t in s]
        if ep["ongoing"]:
            series.append({"name": "teraz", "color": NOW_COLOR, "fmt": "num", "scale": "right", "width": 3, "data": pts})
        else:
            series.append({"name": ep_when(ep), "color": ep["color"], "fmt": "num", "scale": "right",
                           "data": pts})
    series.sort(key=lambda s_: s_["name"] == "teraz")
    return {"type": "chart", "x": "days", "title": "Alty ÷ BTC (100 = dzień przed okresem)",
            "desc": "Dzień 0 = poniedziałek pierwszego tygodnia przy średniej. Powyżej 100 = alty (bez ETH i stablecoinów) radziły "
                    "sobie lepiej niż BTC, poniżej = gorzej.",
            "note": "TOTAL3ES ÷ kapitalizacja BTC (TradingView). Do 6 miesięcy po początku okresu.",
            "lines": [{"value": 100, "label": "dzień przed okresem", "color": "#888"}], "series": series}


# ── bloki: pod średnią, wybicia, przeliczenie, poziomy ───────
def below_table(S):
    W, phs, partial = S["W"], S["phs"], S["partial"]
    a = next(i for i, x in enumerate(W) if x["e"] is not None)
    rows_a, rows_b = [], []
    for i0, i1 in runs_below_w(W, a):
        ongoing = i1 == len(W) - 1
        seg = W[i0:i1 + 1]
        base = W[i0 - 1]["c"]
        deep_c = min(x["c"] / x["e"] - 1 for x in seg)
        lw = min(seg, key=lambda x: x["l"])
        ph = phase_at(phs, W[i0]["t0"])
        after = []
        for k in (13, 26):
            j = i1 + 1 + k
            after.append("—" if ongoing or j >= len(W) else pctf(W[j]["c"] / W[i1 + 1]["c"] - 1, 0))
        row = [(f"od {dmy(W[i0]['t0'])}" if ongoing else span(W[i0]["t0"], W[i1]["t"])),
               str(len(seg)) + (" (tydzień trwa)" if ongoing and partial else " (trwa)" if ongoing else ""),
               pctf(deep_c), pctf(lw["l"] / lw["e"] - 1), pctf(lw["l"] / base - 1), " / ".join(after)]
        (rows_a if ph in ("acc", "unsure") else rows_b).append(["po dnie bessy" if ph in ("acc", "unsure")
                                                                else "bessa — inna sytuacja"] + row)
    rows = rows_a + rows_b
    return {"type": "table", "title": "Okresy z zamknięciem tygodnia pod EMA200 1W",
            "cols": ["Faza", "Kiedy", "Tygodni pod średnią", "Najgłębsze zamknięcie tygodnia vs średnia",
                     "Najniżej (knot) vs średnia", "Spadek ceny do najniższego knota", "Cena 3 / 6 mies. po powrocie nad"],
            "rows": rows, "left": [0, 1], "plain": True,
            "desc": "Co działo się, gdy tydzień jednak zamknął się pod średnią: ile tygodni cena była pod nią i jak głęboko. "
                    "Najpierw okresy po dnie bessy (jak teraz), potem w trakcie bessy (inna sytuacja).",
            "note": "Spadek ceny do najniższego knota = od zamknięcia ostatniego tygodnia nad średnią. Cena po powrocie = zmiana od "
                    "pierwszego tygodnia zamkniętego z powrotem nad średnią. 2015: wartość średniej niepewna o ok. ±2,5% (mało danych "
                    "przed 2013). Knot 18.08.2015 ($162) = flash crash."}


def breakout_table(S):
    W, bottoms, partial = S["W"], S["bottoms"], S["partial"]
    rows = []
    for k, b in enumerate(bottoms):
        nb = bottoms[k + 1] if k + 1 < len(bottoms) else None
        i_b = next((i for i, x in enumerate(W) if x["t"] >= b), None)
        if i_b is None or W[i_b]["e"] is None:
            continue
        lines, i = [], i_b
        while i < len(W):
            if W[i]["c"] > W[i]["e"] and (W[i - 1]["c"] <= W[i - 1]["e"] or i == i_b):
                j = i
                while j + 1 < len(W) and W[j + 1]["c"] > W[j + 1]["e"]:
                    j += 1
                n_ = j - i + 1
                if j + 1 == len(W) - 1 and partial and W[-1]["c"] <= W[-1]["e"]:
                    txt = f"{dmy(W[i]['t0'])}: {n_} tyg. nad — w tym tygodniu cena pod średnią (tydzień trwa)"
                elif j == len(W) - 1:
                    txt = f"{dmy(W[i]['t0'])}: {n_} tyg. nad (trwa)"
                else:
                    txt = f"{dmy(W[i]['t0'])}: {n_} tyg. nad, potem tydzień zamknięty pod"
                lines.append({"t": txt, "tone": None})
                if n_ >= 26 or (nb and W[i]["t0"] > nb):
                    break
                i = j + 1
            else:
                i += 1
            if nb and i < len(W) and W[i]["t0"] >= nb:
                break
        if not lines:
            continue
        rows.append([f"{dmy(b)} ({usd(S['cl'][S['di'][b]])})", str(len(lines)), lines])
    return {"type": "table", "title": "Wybicia nad EMA200 1W po dnie bessy",
            "cols": ["Dno bessy", "Ile wybić do trwałego (≥ 26 tyg. nad)", "Kolejne wybicia: ile tygodni nad średnią"],
            "rows": rows, "left": [0, 2], "plain": True, "even": True,
            "desc": "Wybicie = pierwszy tydzień zamknięty nad EMA200 1W po tygodniu pod nią. Dla każdego dna: kolejne wybicia, aż "
                    "cena utrzymała się nad średnią co najmniej 26 tygodni.",
            "note": "Data = poniedziałek tygodnia wybicia. Cykl 2011–2013 poza zakresem (średnia liczy się od 09.2013)."}


def repeat_table(S):
    W = S["W"]
    x = W[-1]
    e = x["e"]
    rows = []
    for ep in S["A"]:
        if ep["ongoing"]:
            continue
        note = ep["note"].split(" — ")[0] + " — zawyża głębokość" if ep["shock"] else ""
        items = [("najniższy knot w okresie przy średniej", ep["deep"])]
        if ep["down"]:
            nxt = next(((i0, i1) for i0, i1 in runs_below_w(W) if i0 == ep["i1"]), None)
            if nxt:
                seg = W[nxt[0]:nxt[1] + 1]
                items += [("najniższe zamknięcie tygodnia w okresie pod średnią", min(y["c"] / y["e"] - 1 for y in seg)),
                          ("najniższy knot w okresie pod średnią", min(y["l"] / y["e"] - 1 for y in seg))]
        seen = set()
        for lab, v in items:
            if round(v, 4) in seen:
                continue
            seen.add(round(v, 4))
            lv = e * (1 + v)
            rows.append([ep_when(ep), lab, pctf(v), usd(lv), pctf(lv / x["c"] - 1), note])
    return {"type": "table", "title": "Przeliczenie na dziś — szacunek, nie prognoza",
            "cols": ["Okres po dnie bessy", "Co przeliczamy", "Odległość od średniej wtedy",
                     "Ta sama odległość od dzisiejszej średniej", "Od ceny teraz", "Uwagi"],
            "rows": rows, "left": [0, 1, 5], "plain": True,
            "desc": f"Gdyby cena zeszła pod dzisiejszą EMA200 1W ({usd(e)}) tak samo jak w okresach po dnie bessy. Dla okresów "
                    "zakończonych zamknięciem tygodnia pod średnią — także najgłębszy punkt całego pobytu pod nią.",
            "note": "Średnia przesuwa się z ceną, więc to tylko orientacja."}


def levels_table(S):
    d, W, cl, e1d, ts = S["d"], S["W"], S["cl"], S["e1d"], S["ts"]
    price = cl[-1]
    wk = [x["c"] for x in W if datetime.fromtimestamp(x["t"], timezone.utc).weekday() == 6]
    if S["partial"]:
        wk.append(W[-1]["c"])
    rp = d.latest("rprice_btc")
    rows = [("EMA200 1D", e1d[-1], "średnia z 200 zamknięć dziennych"),
            ("EMA200 1W + 3%", W[-1]["e"] * (1 + ZONE), "górna granica strefy „przy średniej”"),
            ("EMA200 1W", W[-1]["e"], "średnia z 200 tygodni — temat raportu"),
            ("SMA 200 tygodni", sum(wk[-200:]) / 200 if len(wk) >= 200 else None,
             "zwykła średnia z ok. 4 lat; przy dnach cykli cena schodziła w jej okolice"),
            ("Realized price", rp[1] if rp else None, "średnia cena, po której BTC ostatnio się przemieścił (Coin Metrics)")]
    if S["bottoms"]:
        b = S["bottoms"][-1]
        rows.append(("Dno bessy", cl[S["di"][b]], dmy(b)))
    rows = sorted([r for r in rows if r[1]], key=lambda r: -r[1])
    return {"type": "table", "title": "Poziomy wokół ceny teraz", "cols": ["Poziom", "Wartość", "Cena vs poziom", "Co to"],
            "rows": [[n, usd(v), pctf(price / v - 1), t] for n, v, t in rows], "left": [0, 3], "plain": True,
            "desc": f"Od najwyższego do najniższego; cena teraz {usd(price)} ({dmy(ts[-1])}).",
            "note": "Cena vs poziom: + = cena nad poziomem, − = pod nim. Średnie tygodniowe z zamknięć tygodni (pon.–nd. UTC), "
                    "bieżący tydzień = cena teraz."}


def watch_block(S):
    W, A = S["W"], S["A"]
    x = W[-1]
    done = [a for a in A if not a["ongoing"]]
    odb = [a for a in done if not a["down"]]
    dn = [a for a in done if a["down"]]
    parts = [f"Zamknięcie tygodnia {dmy(x['t0'] + 6 * DAY)} o 23:59 UTC względem EMA200 1W (teraz {usd(x['e'])}; średnia "
             "przesunie się nieco z ceną zamknięcia)."]
    if odb:
        parts.append(f"Po dnie bessy {len(odb)} z {len(done)} okresów przy średniej skończyło się odbiciem bez zamknięcia tygodnia "
                     f"pod nią: trwały {min(a['weeks'] for a in odb)}–{max(a['weeks'] for a in odb)} tyg., knoty sięgały "
                     f"{pctf(max(a['deep'] for a in odb))} … {pctf(min(a['deep'] for a in odb))} od średniej.")
    if dn:
        parts.append(f"{len(dn)} skończyło się zamknięciem tygodnia pod średnią (" +
                     ", ".join(ep_when(a) + (" — " + a["note"].split(" — ")[0] if a["shock"] else "") for a in dn) + ").")
    parts.append(f"Teraz: knot {pctf(x['l'] / x['e'] - 1)}, cena {pctf(x['c'] / x['e'] - 1)} od średniej. Lewar, alty i tło — "
                 "w tabelach wyżej.")
    return {"type": "text", "title": "Na co patrzeć", "text": " ".join(parts)}
