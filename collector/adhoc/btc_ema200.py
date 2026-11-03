"""Raport specjalny: BTC przy dziennej EMA200 po pierwszym wybiciu nad nią po bessie (zamówiony 03.11.2026).

Pytanie: po dnie cyklu BTC wybił się nad EMA200 i teraz jest blisko powrotu pod nią. Jak to wyglądało w poprzednich
cyklach — ile dni cena była nad EMA200, jak często, jak długo i jak głęboko schodziła pod nią w akumulacji (dno →
zamknięcie nad poprzednim szczytem), co działo się potem; jakie poziomy są teraz pod ceną; tło (szerokość rynku,
funding, OI, MVRV) teraz i na początku poprzednich zejść.

Definicje (z zamknięć dziennych UTC, px_btc: INDEX:BTCUSD + Coinalyze; EMA jak ta.ema(200) w TradingView, bieżąca
świeca = cena teraz):
  zejście          — kolejne zamknięcia dnia pod EMA200;
  dłuższe zejście  — okres z zamknięciami pod EMA200 trwający ≥ LONG dni; przerwy nad średnią ≤ GAP dni łączone;
  fazy cyklu       — cycle.phases (te same co w raporcie miesięcznym i oi.html), dna z config cycle.bottoms.
"""
import statistics
from datetime import datetime, timezone

import cycle as C
import report as R

TITLE = "BTC przy EMA200 po pierwszym wybiciu po bessie"
DAY = 86400
GAP = 10          # przerwy nad EMA200 do 10 dni łączą zejścia w jeden okres
LONG = 7          # okres pod EMA200 od 7 dni = „dłuższe zejście”
OVERLAY_DAYS = 365
COLORS = ["#8e8e8e", "#5b9cf6", "#4caf7d", "#ce93d8", "#4dd0e1", "#ffc107"]
NOW_COLOR = "#f7931a"


# ── liczenie ─────────────────────────────────────────────────
def ema_list(vals, n):
    a = 2 / (n + 1)
    out = [None] * len(vals)
    if len(vals) < n:
        return out
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


def weekly_levels(ts, cl, i):
    """SMA 20 i EMA 21 tygodni na dzień i: zamknięcia pełnych tygodni + bieżący tydzień = zamknięcie dnia i
    (jak świeca tygodniowa w TradingView w trakcie tygodnia)."""
    closes, cur = [], None
    for j in range(i + 1):
        w = week_of(ts[j])
        if w != cur:
            closes.append(cl[j])
            cur = w
        else:
            closes[-1] = cl[j]
    s20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    e21 = ema_list(closes, 21)[-1] if len(closes) >= 21 else None
    return s20, e21


def runs_below(cl, e, a, b):
    """Kolejne zamknięcia pod EMA w [a, b] → [(i0, i1)]."""
    out, start = [], None
    for i in range(a, b + 1):
        below = e[i] is not None and cl[i] <= e[i]
        if below and start is None:
            start = i
        if not below and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, b))
    return out


def clusters(runs, gap=GAP):
    """Zejścia oddzielone ≤ gap dniami nad średnią → jeden okres [(i0, i1, dni pod)]."""
    out = []
    for i0, i1 in runs:
        if out and i0 - out[-1][1] - 1 <= gap:
            out[-1] = (out[-1][0], i1, out[-1][2] + i1 - i0 + 1)
        else:
            out.append((i0, i1, i1 - i0 + 1))
    return out


def cycles(ts, cl, e, phs):
    """Akumulacje po dnach cyklu → [{bottom, first, end, ongoing, confirmed, runs, long}] (indeksy dni)."""
    idx = {t: i for i, t in enumerate(ts)}
    out = []
    for p in phs:
        if p["phase"] != "acc" or p["from"] not in idx:
            continue
        b = idx[p["from"]]
        end = idx.get(p["to"], len(ts)) - 1 if p.get("to") else len(ts) - 1
        f = next((i for i in range(b, end + 1) if e[i] is not None and cl[i] > e[i]), None)
        c = {"bottom": b, "first": f, "end": end, "ongoing": not p.get("to"), "confirmed": p.get("confirmed", True),
             "runs": [], "long": []}
        if f is not None:
            c["runs"] = runs_below(cl, e, f, end)
            c["long"] = [x for x in clusters(c["runs"]) if x[1] - x[0] + 1 >= LONG]
        out.append(c)
    return out


# ── formatowanie ─────────────────────────────────────────────
def dmy(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%d.%m.%Y")


def my(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%m.%Y")


def pct(x, dec=1):
    return "—" if x is None else f"{x:+.{dec}f}%"


def usd(v):
    return R.fmt_price(v)


def days_pl(n):
    return f"{n} {'dzień' if n == 1 else 'dni'}"


def at_or_before(m, t, tol=3 * DAY):
    for k in range(int(tol // DAY) + 1):
        v = m.get(t - k * DAY)
        if v is not None:
            return v
    return None


def avg_back(m, t, n):
    vals = [m.get(t - k * DAY) for k in range(n)]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


# ── raport ───────────────────────────────────────────────────
def build(d, ema, cfg, now):
    px = d.pts("1d", "px_btc")
    if len(px) < 400:
        return {"why": "Brak historii ceny BTC w danych (px_btc) — raportu nie da się policzyć.", "summary": "", "blocks": []}
    ts = [int(t) for t, _ in px]
    cl = [v for _, v in px]
    e = ema_list(cl, 200)
    s200 = sma_list(cl, 200)
    lo = dict(d.pts("1d", "px_btc_lo"))
    phs = C.phases(dict(zip(ts, cl)), C.ccfg(cfg).get("bottoms") or ())
    cyc = cycles(ts, cl, e, phs)
    hist = [c for c in cyc if not c["ongoing"] and c["first"] is not None]
    cur = cyc[-1] if cyc and cyc[-1]["ongoing"] else None
    n = len(ts) - 1
    price, ema_now = cl[n], e[n]
    dist = (price / ema_now - 1) * 100

    # strona EMA teraz: od ostatniego przecięcia na zamknięciu
    above = price > ema_now
    k = n
    while k > 0 and e[k - 1] is not None and (cl[k - 1] > e[k - 1]) == above:
        k -= 1
    side_days = n - k + 1

    blocks = []
    blocks += [{"type": "section", "title": "Teraz"}]
    blocks.append(now_facts(ts, cl, e, lo, cur, n, above, k, side_days, hist))
    blocks.append(price_chart(ts, cl, e, cur))
    lv = levels(d, ts, cl, e, s200, cur, hist, n)
    blocks.append(lv)

    blocks += [{"type": "section", "title": "Jak było w poprzednich cyklach"}]
    blocks.append(cycles_table(ts, cl, e, hist, cur))
    blocks.append(overlay_chart(ts, cl, e, hist, cur))
    blocks.append(episodes_table(ts, cl, e, hist))
    blocks.append(lengths_table(ts, hist))
    blocks.append(repeat_table(ts, cl, e, hist, ema_now, price))

    blocks += [{"type": "section", "title": "Tło: teraz i na początku poprzednich zejść"}]
    blocks.append(background_table(d, ema, ts, cl, e, hist, n))

    blocks += [{"type": "section", "title": "Na co patrzeć"}]
    blocks.append(watch_block(ts, cl, e, s200, n, hist))

    # opis sytuacji
    bot_t = ts[cur["bottom"]] if cur else None
    side_txt = (f"nad nią od {dmy(ts[k])} ({days_pl(side_days)})" if above else f"pod nią od {dmy(ts[k])} ({days_pl(side_days)})")
    if cur and cur["first"] is not None:
        first_txt = (f"Po dnie cyklu {dmy(bot_t)} ({usd(cl[cur['bottom']])}"
                     f"{', dno uznane, niepotwierdzone' if not cur['confirmed'] else ''}) BTC pierwszy raz zamknął dzień nad "
                     f"EMA200 {dmy(ts[cur['first']])}. ")
    else:
        first_txt = ""
    back = sum(1 for c in hist if c["long"])
    why = (first_txt + f"Teraz cena {usd(price)} jest {pct(dist, 2)} od EMA200 ({usd(ema_now)}), {side_txt}. "
           f"W {back} z {len(hist)} poprzednich cykli cena po pierwszym wybiciu nad EMA200 wracała pod nią na dłużej (co "
           f"najmniej {LONG} dni), zanim akumulacja się skończyła. Raport zestawia, jak wyglądały te powroty (jak często, jak długo, "
           "jak głęboko, co działo się potem), jakie poziomy są teraz wokół ceny i jakie było tło rynku. Same dane z historii; "
           "przeliczenia na dzisiejsze ceny to szacunek, nie prognoza.")
    lens = [x[1] - x[0] + 1 for c in hist for x in c["long"]]
    summary = (f"BTC {usd(price)}, EMA200 {usd(ema_now)} ({pct(dist, 2)}), {'nad' if above else 'pod'} od {days_pl(side_days)}"
               + (f" · poprzednie cykle: dłuższe zejścia w akumulacji {min(lens)}–{max(lens)} dni" if lens else ""))
    return {"why": why, "summary": summary, "blocks": blocks}


def now_facts(ts, cl, e, lo, cur, n, above, k, side_days, hist):
    price, ema_now = cl[n], e[n]
    items = [
        {"label": "Cena BTC", "value": usd(price), "sub": f"zamknięcie bieżącego dnia ({dmy(ts[n])}, w trakcie)", "zone": None,
         "note": "Ostatnia cena z danych (skan co ~2 h)."},
        {"label": "EMA200 (dzienna)", "value": usd(ema_now), "sub": f"cena {pct((price / ema_now - 1) * 100, 2)} od średniej",
         "zone": "yellow" if abs(price / ema_now - 1) <= 0.02 else None,
         "note": "Wykładnicza średnia z 200 zamknięć dziennych (jak ta.ema(200) w TradingView)."},
        {"label": "Po której stronie", "value": f"{'nad' if above else 'pod'} EMA200", "sub": f"od {dmy(ts[k])} — {days_pl(side_days)}",
         "zone": None, "note": "Liczone z zamknięć dziennych."},
    ]
    if cur:
        b = cur["bottom"]
        items.append({"label": "Od dna cyklu", "value": days_pl(n - b), "sub": f"dno {dmy(ts[b])}, {usd(cl[b])}"
                      + (" (uznane, niepotwierdzone)" if not cur["confirmed"] else ""), "zone": None,
                      "note": "Faza: akumulacja (dno → zamknięcie nad poprzednim szczytem)."})
        if cur["first"] is not None and above:
            seg = range(cur["first"], n + 1)
            mx = max(seg, key=lambda i: cl[i] / e[i])
            wicks = [i for i in range(k, n + 1) if ts[i] in lo and lo[ts[i]] < e[i]]
            items.append({"label": "Najwyżej nad EMA200", "value": pct((cl[mx] / e[mx] - 1) * 100),
                          "sub": f"{dmy(ts[mx])}", "zone": None, "note": "Od pierwszego zamknięcia nad EMA200 po dnie."})
            ref = ""
            lo0 = min(lo) if lo else None
            h_w = [c for c in hist if c["long"] and lo0 is not None and ts[c["first"]] >= lo0]   # cykle z danymi o knotach
            if h_w:
                c = h_w[-1]
                nw = sum(1 for i in range(c["first"], c["long"][0][0]) if ts[i] in lo and lo[ts[i]] < e[i] and cl[i] > e[i])
                ref = f" W cyklu po dnie {my(ts[c['bottom']])}: {nw} takich dni przed pierwszym dłuższym zejściem."
            items.append({"label": "Knoty pod EMA200", "value": str(len(wicks)),
                          "sub": ", ".join(dmy(ts[i])[:5] for i in wicks[-6:]) or "brak",
                          "zone": None, "note": "Dni w obecnym okresie nad średnią, w których cena zeszła w trakcie dnia pod EMA200, "
                                                "ale zamknęła się nad nią (knoty z Binance perp, od 2019)." + ref})
    return {"type": "facts", "title": "BTC i EMA200 teraz", "items": items}


def price_chart(ts, cl, e, cur):
    a = max(0, (cur["bottom"] if cur else len(ts) - 300) - 60)
    data = [[ts[i], cl[i]] for i in range(a, len(ts))]
    emad = [[ts[i], round(e[i], 2)] for i in range(a, len(ts)) if e[i] is not None]
    return {"type": "chart", "title": "Cena BTC i EMA200 od dna cyklu",
            "desc": "Zamknięcia dzienne. Pomarańczowa linia = cena, szara = EMA200.",
            "note": "Okres od ok. 2 miesięcy przed dnem cyklu do dziś.",
            "series": [{"name": "Cena BTC", "color": NOW_COLOR, "fmt": "price", "scale": "right", "data": data},
                       {"name": "EMA200", "color": "#bbbbbb", "fmt": "price", "scale": "right", "data": emad}]}


def levels(d, ts, cl, e, s200, cur, hist, n):
    price = cl[n]
    s20, e21 = weekly_levels(ts, cl, n)
    s1400 = sma_list(cl, 1400)[n]
    rp = d.latest("rprice_btc")
    rows = [("EMA200 (dzienna)", e[n], "średnia, wokół której toczy się ten raport"),
            ("SMA200 (dzienna)", s200[n], "prosta średnia z 200 dni"),
            ("EMA 21 tygodni", e21, "z SMA 20 tygodni tworzy tzw. pasmo wsparcia hossy (bull market support band)"),
            ("SMA 20 tygodni", s20, "druga linia pasma"),
            ("SMA 200 tygodni", s1400, "średnia z ok. 4 lat; przy dnach cykli cena schodziła w jej okolice"),
            ("Realized price", rp[1] if rp else None, "średnia cena, po której BTC ostatnio się przemieścił (Coin Metrics, ~1 dzień opóźnienia)")]
    if cur:
        b = cl[cur["bottom"]]
        rows.append(("Dno cyklu", b, f"{dmy(ts[cur['bottom']])}"))
        mins = [(min(cl[x[0]:x[1] + 1]) / cl[c["bottom"]] - 1) for c in hist for x in c["long"]]
        if mins:
            m = min(mins)
            rows.append((f"Dno + {m * 100:.0f}%", b * (1 + m),
                         "najniższe zamknięcie w dłuższym zejściu z poprzednich cykli było o tyle nad dnem (najbliżej dna)"))
    rows = [r for r in rows if r[1]]
    rows.sort(key=lambda r: -r[1])
    out = [[name, usd(v), pct((v / price - 1) * 100), note] for name, v, note in rows]
    return {"type": "table", "title": "Poziomy wokół ceny teraz", "cols": ["Poziom", "Wartość", "Od ceny", "Co to"],
            "rows": out, "left": [0, 3], "plain": True,
            "desc": "Średnie i poziomy, na które patrzy rynek przy takich testach — od najwyższego do najniższego.",
            "note": "Średnie tygodniowe z zamknięć tygodni (pon.–nd. UTC); bieżący tydzień = cena teraz, jak na świecy tygodniowej "
                    "w TradingView. Wartości średnich zmieniają się z każdym dniem."}


def cycles_table(ts, cl, e, hist, cur):
    rows = []
    for c in hist + ([cur] if cur and cur["first"] is not None else []):
        b, f = c["bottom"], c["first"]
        first_long = c["long"][0] if c["long"] else None
        below_total = sum(i1 - i0 + 1 for i0, i1 in c["runs"])
        span = c["end"] - f + 1
        if c["ongoing"]:
            last = "trwa"
            after = "—"
        else:
            last = f"{dmy(ts[c['long'][-1][1] + 1])} ({c['long'][-1][1] + 1 - f} dni po 1. przebiciu)" if c["long"] else "—"
            # nad EMA po ostatnim dłuższym zejściu: do pierwszych LONG zamknięć z rzędu pod EMA (także w hossie / bessie)
            a = (c["long"][-1][1] + 1) if c["long"] else f
            nxt = next((i for i in range(a, len(ts)) if e[i] is not None and cl[i] <= e[i]
                        and all(cl[j] <= e[j] for j in range(i, min(i + LONG, len(ts))))), None)
            after = days_pl((nxt if nxt is not None else len(ts)) - a)
        rows.append([f"{dmy(ts[b])}" + (" (uznane)" if not c["confirmed"] else ""),
                     f"{dmy(ts[f])} ({f - b} dni po dnie)",
                     str(first_long[0] - f) if first_long else ("—" if c["ongoing"] else "brak"),
                     str(len(c["long"])),
                     f"{100 * below_total / span:.0f}%",
                     last, after,
                     dmy(ts[c["end"] + 1]) if not c["ongoing"] and c["end"] + 1 < len(ts) else "trwa"])
    if cur and cur["first"] is not None and not cur["long"]:
        rows[-1][2] = f"{len(ts) - cur['first']} i liczymy"
    return {"type": "table", "title": "Akumulacja po dnie cyklu: pierwsze wybicie nad EMA200 i powroty pod nią",
            "cols": ["Dno cyklu", "1. zamknięcie nad EMA200", "Dni nad do 1. dłuższego zejścia", "Dłuższych zejść",
                     "Dni pod EMA (udział)", "Koniec ostatniego dłuższego zejścia", "Potem nad EMA200 bez dłuższej przerwy",
                     "Koniec akumulacji"],
            "rows": rows, "left": [0, 1, 5], "plain": True,
            "desc": "Każdy wiersz to jeden cykl: od pierwszego zamknięcia nad EMA200 po dnie do końca akumulacji (zamknięcie nad "
                    "szczytem poprzedniego cyklu). Ostatni wiersz = obecny cykl.",
            "note": f"Dłuższe zejście = okres z zamknięciami pod EMA200 trwający co najmniej {LONG} dni (przerwy nad średnią do "
                    f"{GAP} dni łączone). Udział = odsetek dni akumulacji (od 1. przebicia) z zamknięciem pod EMA200. "
                    f"„Potem nad EMA200” — do pierwszych {LONG} zamknięć z rzędu pod EMA200 (także w hossie lub bessie)."}


def overlay_chart(ts, cl, e, hist, cur):
    series = []
    for j, c in enumerate(hist):
        f = c["first"]
        data = [[i - f, round((cl[i] / e[i] - 1) * 100, 2)] for i in range(f, min(f + OVERLAY_DAYS + 1, len(ts)))]
        series.append({"name": f"po dnie {my(ts[c['bottom']])}", "color": COLORS[j % len(COLORS)], "fmt": "chg",
                       "scale": "right", "data": data})
    if cur and cur["first"] is not None:
        f = cur["first"]
        series.append({"name": f"po dnie {my(ts[cur['bottom']])} (teraz)", "color": NOW_COLOR, "fmt": "chg", "scale": "right",
                       "width": 3, "data": [[i - f, round((cl[i] / e[i] - 1) * 100, 2)] for i in range(f, len(ts))]})
    return {"type": "chart", "x": "days", "title": "Odległość od EMA200 w dniach od pierwszego wybicia nad nią",
            "desc": "Wszystkie cykle nałożone: dzień 0 = pierwsze zamknięcie nad EMA200 po dnie. Poniżej 0% = cena pod średnią.",
            "note": f"Pierwsze {OVERLAY_DAYS} dni każdego cyklu. Zamknięcia dzienne.",
            "lines": [{"value": 0, "label": "EMA200", "color": "#888"}], "series": series}


def episodes_table(ts, cl, e, hist):
    rows = []
    for c in hist:
        f, b = c["first"], c["bottom"]
        for i0, i1, nb in c["long"]:
            seg = range(i0, i1 + 1)
            deep = min(seg, key=lambda i: cl[i] / e[i])
            low = min(seg, key=lambda i: cl[i])
            base = cl[i0 - 1]                                   # ostatnie zamknięcie nad EMA przed zejściem
            fw = lambda h: pct((cl[i0 + h] / cl[i0] - 1) * 100, 0) if i0 + h < len(cl) else "—"  # noqa: E731
            rows.append([f"po dnie {my(ts[b])}", f"{dmy(ts[i0])}–{dmy(ts[i1])}", f"{i1 - i0 + 1} ({nb})",
                         str(i0 - f), pct((cl[deep] / e[deep] - 1) * 100), pct((cl[low] / base - 1) * 100),
                         pct((cl[low] / cl[b] - 1) * 100, 0), fw(90), fw(180)])
    return {"type": "table", "title": "Dłuższe zejścia pod EMA200 w akumulacji",
            "cols": ["Cykl", "Okres", "Dni (zamknięć pod)", "Start: dni od 1. przebicia", "Najgłębiej pod EMA200",
                     "Spadek do dołka", "Dołek vs dno cyklu", "Cena po 90 dniach", "Cena po 180 dniach"],
            "rows": rows, "left": [0, 1],
            "desc": "Każde dłuższe zejście pod średnią po pierwszym wybiciu, aż do końca akumulacji.",
            "note": "Spadek do dołka = od ostatniego zamknięcia nad EMA200 przed zejściem do najniższego zamknięcia w zejściu. "
                    "Dołek vs dno cyklu: dodatni = dołek wyżej niż dno cyklu (nowego dna nie było). Cena po 90 / 180 dniach — "
                    "liczone od pierwszego zamknięcia pod EMA200 w tym zejściu. 2020: zejście w czasie krachu covidowego."}


def lengths_table(ts, hist):
    lens = [i1 - i0 + 1 for c in hist for i0, i1 in c["runs"]]
    buckets = [("1 dzień", 1, 1), ("2–4 dni", 2, 4), ("5–14 dni", 5, 14), ("15–28 dni", 15, 28), ("29 dni i więcej", 29, 10 ** 6)]
    rows = []
    for label, a, b in buckets:
        k = sum(1 for x in lens if a <= x <= b)
        rows.append([label, str(k), f"{100 * k / len(lens):.0f}%" if lens else "—"])
    med = statistics.median(lens) if lens else None
    return {"type": "table", "title": "Jak długo trwały zejścia pod EMA200 (wszystkie, w akumulacji)",
            "cols": ["Długość zejścia", "Ile razy", "Udział"], "rows": rows, "left": [0], "plain": True,
            "desc": "Każde zejście = kolejne zamknięcia dnia pod EMA200, bez łączenia krótkich przerw.",
            "note": f"{len(lens)} zejść w {len(hist)} cyklach (od 1. przebicia po dnie do końca akumulacji); mediana "
                    f"{med:.0f} dni." if lens else "Brak danych."}


def repeat_table(ts, cl, e, hist, ema_now, price):
    rows = []
    for c in hist:
        for i0, i1, _ in c["long"]:
            low = min(cl[i0:i1 + 1])
            drop = low / cl[i0 - 1] - 1
            rows.append((drop, f"po dnie {my(ts[c['bottom']])}", f"{dmy(ts[i0])}–{dmy(ts[i1])}", i1 - i0 + 1))
    rows.sort()
    out = [[name, per, str(days), pct(drop * 100), usd(ema_now * (1 + drop)), pct(((ema_now * (1 + drop)) / price - 1) * 100)]
           for drop, name, per, days in rows]
    if rows:
        med = statistics.median(r[0] for r in rows)
        out.append(["Mediana", "", str(int(statistics.median(r[3] for r in rows))), pct(med * 100), usd(ema_now * (1 + med)),
                    pct(((ema_now * (1 + med)) / price - 1) * 100)])
    return {"type": "table", "title": "Gdyby powtórzyło się zejście z poprzedniego cyklu — przeliczenie na dziś",
            "cols": ["Cykl", "Okres", "Dni", "Spadek do dołka", "Dziś to ok.", "Od ceny teraz"], "rows": out, "left": [0, 1],
            "desc": "Spadek z każdego dłuższego zejścia przyłożony do dzisiejszej EMA200 (zejście zaczyna się przy średniej). "
                    "Szacunek z historii, nie prognoza.",
            "note": "Od najgłębszego. Liczone z zamknięć dziennych — knoty w trakcie dnia schodziły niżej."}


def background_table(d, ema, ts, cl, e, hist, n):
    m = {sid: dict(d.pts("1d", sid)) for sid in ("mvrv_btc", "p200w_btc", "lev_btc", "oi_btc")}
    fund = dict(d.pts("1d", "fund_btc"))
    pxm = dict(zip(ts, cl))
    br = {int(t): v for t, v, *_ in ((ema or {}).get("breadth") or [])}

    def row(label, i):
        t = ts[i]
        s20, e21 = weekly_levels(ts, cl, i)
        oi_now, oi_30 = at_or_before(m["oi_btc"], t), at_or_before(m["oi_btc"], t - 30 * DAY)
        coins = None
        if oi_now and oi_30 and pxm.get(t - 30 * DAY):
            coins = (oi_now / cl[i]) / (oi_30 / pxm[t - 30 * DAY]) - 1
        lev = at_or_before(m["lev_btc"], t)
        mv = at_or_before(m["mvrv_btc"], t)
        p2 = at_or_before(m["p200w_btc"], t)
        b = at_or_before(br, t)
        fu = avg_back(fund, t, 7)
        return [label, dmy(t), "—" if b is None else f"{b:.0f}%", "—" if fu is None else f"{fu:+.1f}%",
                pct(coins * 100, 0) if coins is not None else "—", "—" if lev is None else f"{lev:.2f}%",
                "—" if mv is None else f"{mv:.2f}", "—" if p2 is None else f"{p2:.2f}×",
                pct((cl[i] / e21 - 1) * 100) if e21 else "—"]

    rows = [row(f"po dnie {my(ts[c['bottom']])}", i0) for c in hist for i0, _, _ in c["long"]]
    rows.append(row("teraz", n))
    return {"type": "table", "title": "Tło rynku: początek każdego dłuższego zejścia i teraz",
            "cols": ["Cykl", "Dzień", "Szerokość rynku", "Funding BTC (śr. 7 dni)", "OI BTC w coinach (30 dni)",
                     "Dźwignia BTC (OI / kapitalizacja)", "MVRV", "Cena / SMA 200W", "Cena vs EMA 21W"],
            "rows": rows, "left": [0, 1], "plain": True,
            "desc": "Te same wskaźniki w pierwszym dniu każdego dłuższego zejścia pod EMA200 i dziś.",
            "note": "„—” = brak danych z tamtego okresu: szerokość rynku od 03.2019, funding od 01.2020, OI i dźwignia od "
                    "09.2022. Szerokość = odsetek coinów Binance nad EMA200. Funding w % w skali roku (ok. 11% = neutralnie). "
                    "OI w coinach = zmiana OI w USD podzielonego przez cenę (czy przybywa pozycji, niezależnie od ceny)."}


def watch_block(ts, cl, e, s200, n, hist):
    s20, e21 = weekly_levels(ts, cl, n)
    lens = [i1 - i0 + 1 for c in hist for i0, i1 in c["runs"]]
    short = sum(1 for x in lens if x <= 4)
    longs = [x for c in hist for x in c["long"]]
    mins = [(min(cl[x[0]:x[1] + 1]) / cl[c["bottom"]] - 1) * 100 for c in hist for x in c["long"]]
    rows = [["Zamknięcie dnia (00:00 UTC = 01:00 PL zimą, 02:00 latem)", f"EMA200 ≈ {usd(e[n])}",
             f"Z historii: {short} z {len(lens)} zejść pod EMA200 w akumulacji trwało najwyżej 4 dni. Alert EMA200 dla BTC "
             "przychodzi na Telegram przy przecięciu (bufor 0,5%)."],
            ["Zamknięcie tygodnia (niedziela 24:00 UTC)",
             f"EMA 21W ≈ {usd(e21)}, SMA 20W ≈ {usd(s20)}", "Raport tygodniowy w poniedziałek pokazuje BTC vs średnie tygodniowe."],
            ["SMA200 (dzienna)", f"≈ {usd(s200[n])}", f"Prosta średnia z 200 dni: {pct((s200[n] / cl[n] - 1) * 100)} od ceny, "
             f"{pct((s200[n] / e[n] - 1) * 100)} od EMA200."]]
    if longs:
        rows.append(["Długość i głębokość dłuższych zejść w historii",
                     f"{min(x[1] - x[0] + 1 for x in longs)}–{max(x[1] - x[0] + 1 for x in longs)} dni",
                     f"Dołek w zejściu {min(mins):+.0f}%…{max(mins):+.0f}% nad dnem cyklu — w {len(longs)} dłuższych zejściach "
                     "ani razu pod dnem cyklu."])
    rows.append(["Dźwignia i pozycje", "OI w coinach, funding, likwidacje",
                 "Raport wieczorny (Coiny z listy, Likwidacje dziś) i zakładka OI & TOTAL."])
    rows.append(["Alty", "szerokość rynku, OI OTHERS / OI BTC", "Raport poranny (Alty) i zakładka EMA200."])
    return {"type": "table", "title": "Poziomy i dane do obserwacji", "cols": ["Co", "Poziom teraz", "Gdzie / z historii"],
            "rows": rows, "left": [0, 1, 2], "plain": True,
            "desc": "Lista faktów do śledzenia w najbliższych tygodniach; bez prognozy, co się stanie."}
