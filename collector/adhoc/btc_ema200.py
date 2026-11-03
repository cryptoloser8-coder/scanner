"""Raport specjalny: BTC przy dziennej EMA200 po pierwszym wybiciu nad nią po bessie (zamówiony 03.11.2026).

Pytanie: po dnie cyklu BTC wybił się nad EMA200 i teraz jest blisko powrotu pod nią. Jak to wyglądało w poprzednich
cyklach — ile dni cena była nad EMA200, jak często, jak długo i jak głęboko schodziła pod nią, co działo się potem;
osobno i dokładniej poprzedni cykl (2022–2025, pierwszy z ETF-ami na BTC w USA): każde zejście pod EMA200 w akumulacji
i w hossie („balansowanie na krawędzi”), z knotami, derywatami i szerokością rynku; jakie poziomy są teraz pod ceną;
tło krypto i makro teraz i na początku poprzednich zejść. Wersja 2 (poprawka 42): więcej wykresów do porównań,
opis „Jak czytać”, knoty, poprzedni cykl w szczegółach, tło makro.

Definicje (z zamknięć dziennych UTC, px_btc: INDEX:BTCUSD + Coinalyze; EMA jak ta.ema(200) w TradingView, bieżąca
świeca = cena teraz; knoty px_btc_lo — Binance perp przez Coinalyze, od 09.2019):
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
DROP_DAYS = 120   # wykres „zejście dzień po dniu”
BOTTOM_DAYS = 600  # wykres „cena ÷ dno cyklu”
ETF_START = "2024-01-11"   # pierwszy dzień handlu spotowymi ETF-ami na BTC w USA
COLORS = ["#8e8e8e", "#5b9cf6", "#4caf7d", "#ce93d8", "#4dd0e1", "#ffc107", "#ff8a65", "#90a4ae"]
NOW_COLOR = "#f7931a"
PHASE_COLORS = {"bull": "#4caf7d", "bear": "#e05252", "acc": "#5b9cf6", "unsure": "#b39ddb"}
PHASE_PL = {"bull": "hossa", "bear": "bessa", "acc": "akumulacja"}
BELOW_COLOR = "#e05252"


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
    """Akumulacje po dnach cyklu → [{bottom, first, end, top, ongoing, confirmed, runs, long}] (indeksy dni).
    end = ostatni dzień akumulacji; top = szczyt hossy po niej (None = jeszcze nie było)."""
    idx = {t: i for i, t in enumerate(ts)}
    out = []
    for k, p in enumerate(phs):
        if p["phase"] != "acc" or p["from"] not in idx:
            continue
        b = idx[p["from"]]
        end = idx.get(p["to"], len(ts)) - 1 if p.get("to") else len(ts) - 1
        bull = phs[k + 1] if k + 1 < len(phs) and phs[k + 1]["phase"] == "bull" else None
        top = idx.get(bull["to"]) if bull and bull.get("to") else None
        f = next((i for i in range(b, end + 1) if e[i] is not None and cl[i] > e[i]), None)
        c = {"bottom": b, "first": f, "end": end, "top": top, "ongoing": not p.get("to"),
             "confirmed": p.get("confirmed", True), "runs": [], "long": []}
        if f is not None:
            c["runs"] = runs_below(cl, e, f, end)
            c["long"] = [x for x in clusters(c["runs"]) if x[1] - x[0] + 1 >= LONG]
        out.append(c)
    return out


def drop_stats(ts, cl, e, lo, i0, i1):
    """Liczby jednego zejścia [i0, i1]: ostatnie zamknięcie nad EMA (base), najniższe zamknięcie i knot, odległość
    od EMA w najgorszym dniu (zamknięcie i knot)."""
    seg = range(i0, i1 + 1)
    base = cl[i0 - 1]
    low = min(seg, key=lambda i: cl[i])
    deep = min(seg, key=lambda i: cl[i] / e[i])
    w = [i for i in seg if ts[i] in lo]
    wl = min(w, key=lambda i: lo[ts[i]]) if w else None
    wd = min(w, key=lambda i: lo[ts[i]] / e[i]) if w else None
    return {"base": base, "low_i": low, "low": cl[low], "deep_i": deep, "deep": cl[deep] / e[deep] - 1,
            "drop": cl[low] / base - 1, "wick_i": wl, "wick": lo[ts[wl]] if wl is not None else None,
            "wick_drop": lo[ts[wl]] / base - 1 if wl is not None else None,
            "wick_deep": lo[ts[wd]] / e[wd] - 1 if wd is not None else None}


# ── formatowanie ─────────────────────────────────────────────
def dmy(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%d.%m.%Y")


def my(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%m.%Y")


def pct(x, dec=1):
    return "—" if x is None else f"{x:+.{dec}f}%"


def pctf(x, dec=1):
    """Ułamek (0.12) → „+12.0%”."""
    return "—" if x is None else pct(x * 100, dec)


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


def cycle_label(ts, c):
    return f"po dnie {my(ts[c['bottom']])}"


def phase_at(phs, t):
    for p in phs:
        if p["from"] <= t and (p.get("to") is None or t < p["to"]):
            return p["phase"]
    return None


# ── raport ───────────────────────────────────────────────────
def build(d, ema, cfg, now):
    px = d.pts("1d", "px_btc")
    if len(px) < 400:
        return {"why": "Brak historii ceny BTC w danych (px_btc) — raportu nie da się policzyć.", "summary": "", "blocks": []}
    ts = [int(t) for t, _ in px]
    cl = [v for _, v in px]
    e = ema_list(cl, 200)
    s200 = sma_list(cl, 200)
    lo = {int(t): v for t, v in d.pts("1d", "px_btc_lo")}
    phs = C.phases(dict(zip(ts, cl)), C.ccfg(cfg).get("bottoms") or ())
    cyc = cycles(ts, cl, e, phs)
    hist = [c for c in cyc if not c["ongoing"] and c["first"] is not None]
    cur = cyc[-1] if cyc and cyc[-1]["ongoing"] else None
    prev = hist[-1] if hist else None
    n = len(ts) - 1
    price, ema_now = cl[n], e[n]
    dist = (price / ema_now - 1) * 100
    S = dict(ts=ts, cl=cl, e=e, s200=s200, lo=lo, phs=phs, hist=hist, cur=cur, prev=prev, n=n)

    above = price > ema_now
    k = n
    while k > 0 and e[k - 1] is not None and (cl[k - 1] > e[k - 1]) == above:
        k -= 1
    side_days = n - k + 1
    S.update(above=above, k=k, side_days=side_days)

    blocks = [how_to_read(S)]
    blocks += [{"type": "section", "title": "Teraz"}]
    blocks.append(now_facts(S))
    blocks.append(price_chart(S))
    blocks.append(levels(d, S))

    if prev:
        y0, y1 = dmy(ts[prev["bottom"]])[-4:], dmy(ts[prev["top"]])[-4:] if prev["top"] is not None else "dziś"
        blocks += [{"type": "section", "title": f"Poprzedni cykl ({y0}–{y1}) — pierwszy z ETF-ami"}]
        blocks.append(prev_intro(S))
        blocks.append(prev_chart(S))
        blocks.append(prev_drops_table(S))
        blocks.append(deriv_chart(d, S))
        if ema and ema.get("breadth"):
            blocks.append(breadth_chart(ema, S))

    blocks += [{"type": "section", "title": "Wszystkie cykle: akumulacja po dnie"}]
    blocks.append(cycles_table(S))
    blocks.append(overlay_chart(S))
    blocks.append(bottom_chart(S))
    blocks.append(episodes_table(S))
    blocks.append(drop_path_chart(S))
    blocks.append(lengths_table(S))
    blocks.append(repeat_table(S, ema_now, price))

    blocks += [{"type": "section", "title": "Tło: teraz i na początku poprzednich zejść"}]
    blocks.append(background_table(d, ema, S))
    blocks.append(macro_table(d, S))

    blocks += [{"type": "section", "title": "Na co patrzeć"}]
    blocks.append(watch_block(S))

    bot_t = ts[cur["bottom"]] if cur else None
    side_txt = (f"nad nią od {dmy(ts[k])} ({days_pl(side_days)})" if above else f"pod nią od {dmy(ts[k])} ({days_pl(side_days)})")
    first_txt = ""
    if cur and cur["first"] is not None:
        first_txt = (f"Po dnie cyklu {dmy(bot_t)} ({usd(cl[cur['bottom']])}"
                     f"{', dno uznane, niepotwierdzone' if not cur['confirmed'] else ''}) BTC pierwszy raz zamknął dzień nad "
                     f"EMA200 {dmy(ts[cur['first']])}. ")
    back = sum(1 for c in hist if c["long"])
    why = (first_txt + f"Teraz cena {usd(price)} jest {pct(dist, 2)} od EMA200 ({usd(ema_now)}), {side_txt}. "
           f"W {back} z {len(hist)} poprzednich cykli cena po pierwszym wybiciu nad EMA200 wracała pod nią na dłużej (co "
           f"najmniej {LONG} dni), zanim akumulacja się skończyła. Raport zestawia, jak wyglądały te powroty (jak często, jak długo, "
           "jak głęboko, co działo się potem), osobno i dokładniej poprzedni cykl — pierwszy, w którym działały ETF-y na BTC "
           "(każde zejście pod średnią, także w hossie), jakie poziomy są teraz wokół ceny i jakie było tło rynku. "
           "Same dane z historii; przeliczenia na dzisiejsze ceny to szacunek, nie prognoza.")
    lens = [x[1] - x[0] + 1 for c in hist for x in c["long"]]
    summary = (f"BTC {usd(price)}, EMA200 {usd(ema_now)} ({pct(dist, 2)}), {'nad' if above else 'pod'} od {days_pl(side_days)}"
               + (f" · poprzednie cykle: dłuższe zejścia w akumulacji {min(lens)}–{max(lens)} dni" if lens else ""))
    return {"why": why, "summary": summary, "blocks": blocks}


# ── bloki: wprowadzenie i teraz ──────────────────────────────
def how_to_read(S):
    ts, cl, e, lo, hist = S["ts"], S["cl"], S["e"], S["lo"], S["hist"]
    ex = ""
    c = next((c for c in reversed(hist) if c["long"]), None)
    if c:
        i0, i1, _ = c["long"][0]
        st = drop_stats(ts, cl, e, lo, i0, i1)
        ex = (f" Przykład — zejście {dmy(ts[i0])}–{dmy(ts[i1])}: ostatnie zamknięcie nad EMA200 {usd(st['base'])} "
              f"({dmy(ts[i0 - 1])}); najniższe zamknięcie {usd(st['low'])} ({dmy(ts[st['low_i']])}) → spadek ceny "
              f"{pctf(st['drop'])}; w najgorszym dniu ({dmy(ts[st['deep_i']])}) cena była {pctf(st['deep'])} od EMA200. "
              "Te dwie liczby się różnią, bo średnia też się w tym czasie przesuwa.")
    text = ("EMA200 = średnia z 200 zamknięć dziennych, która mocniej waży ostatnie dni (jak ta.ema(200) w TradingView). "
            "„Zejście” = kolejne dni, w których cena zamknęła się pod EMA200; „dłuższe zejście” = okres co najmniej "
            f"{LONG} dni z zamknięciami pod średnią (krótkie powroty nad nią do {GAP} dni nie przerywają okresu). "
            "Każde zejście opisują dwie miary: „cena vs EMA200 w najgorszym dniu” — jak daleko pod średnią była cena; "
            "„spadek ceny do dołka” — o ile cena spadła od ostatniego zamknięcia nad średnią do najniższego zamknięcia "
            "(to widać na wykresie ceny). Knot = najniższa cena w trakcie dnia (świeca), zwykle o kilka punktów procentowych "
            "niżej niż zamknięcie." + ex +
            " Znaki: „+” = cena nad poziomem, „−” = pod nim. Daty i dni liczone w UTC (zamknięcie dnia o 01:00 PL zimą).")
    return {"type": "text", "title": "Jak czytać ten raport", "text": text}


def now_facts(S):
    ts, cl, e, lo, cur, n, above, k, side_days, hist = (S[x] for x in
                                                        ("ts", "cl", "e", "lo", "cur", "n", "above", "k", "side_days", "hist"))
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
    if ts[n] in lo:
        items.append({"label": "Najniżej dziś (knot)", "value": usd(lo[ts[n]]), "sub": f"{pct((lo[ts[n]] / ema_now - 1) * 100)} od EMA200",
                      "zone": None, "note": "Najniższa cena bieżącej świecy dziennej (Binance perp)."})
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
            h_w = [c for c in hist if c["long"] and lo0 is not None and ts[c["first"]] >= lo0]
            if h_w:
                c = h_w[-1]
                nw = sum(1 for i in range(c["first"], c["long"][0][0]) if ts[i] in lo and lo[ts[i]] < e[i] and cl[i] > e[i])
                ref = f" W cyklu po dnie {my(ts[c['bottom']])}: {nw} takich dni przed pierwszym dłuższym zejściem."
            items.append({"label": "Knoty pod EMA200", "value": str(len(wicks)),
                          "sub": ", ".join(dmy(ts[i])[:5] for i in wicks[-6:]) or "brak",
                          "zone": None, "note": "Dni w obecnym okresie nad średnią, w których cena zeszła w trakcie dnia pod EMA200, "
                                                "ale zamknęła się nad nią (knoty z Binance perp, od 2019)." + ref})
    return {"type": "facts", "title": "BTC i EMA200 teraz", "items": items}


def cross_markers(ts, cl, e, a, b):
    """Strzałki przecięć EMA200 na zamknięciu w [a, b]: ↓ pierwsze zamknięcie pod, ↑ pierwsze zamknięcie nad."""
    out = []
    for i in range(max(a, 1), b + 1):
        if e[i] is None or e[i - 1] is None:
            continue
        was, now = cl[i - 1] > e[i - 1], cl[i] > e[i]
        if was != now:
            out.append({"t": ts[i], "shape": "up" if now else "down", "pos": "below" if now else "above",
                        "color": "#4caf7d" if now else "#e05252"})
    return out


def price_chart(S):
    ts, cl, e, cur = S["ts"], S["cl"], S["e"], S["cur"]
    a = max(0, (cur["bottom"] if cur else len(ts) - 300) - 60)
    return {"type": "chart", "title": "Cena BTC i EMA200 od dna cyklu",
            "desc": "Zamknięcia dzienne. Pomarańczowa linia = cena, szara = EMA200. Strzałki: ↓ pierwsze zamknięcie pod EMA200, "
                    "↑ pierwsze zamknięcie nad nią.",
            "note": "Okres od ok. 2 miesięcy przed dnem cyklu do dziś.",
            "markers": cross_markers(ts, cl, e, a, len(ts) - 1),
            "series": [{"name": "Cena BTC", "color": NOW_COLOR, "fmt": "price", "scale": "right",
                        "data": [[ts[i], cl[i]] for i in range(a, len(ts))]},
                       {"name": "EMA200", "color": "#bbbbbb", "fmt": "price", "scale": "right",
                        "data": [[ts[i], round(e[i], 2)] for i in range(a, len(ts)) if e[i] is not None]}]}


def levels(d, S):
    ts, cl, e, s200, cur, hist, n = (S[x] for x in ("ts", "cl", "e", "s200", "cur", "hist", "n"))
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
    out = [[name, usd(v), pct((price / v - 1) * 100), note] for name, v, note in rows]
    return {"type": "table", "title": "Poziomy wokół ceny teraz", "cols": ["Poziom", "Wartość", "Cena vs poziom", "Co to"],
            "rows": out, "left": [0, 3], "plain": True,
            "desc": "Średnie i poziomy, na które patrzy rynek przy takich testach — od najwyższego do najniższego.",
            "note": "Cena vs poziom: + = cena nad poziomem, − = cena pod nim (jak „cena od średniej” wyżej). "
                    "Średnie tygodniowe z zamknięć tygodni (pon.–nd. UTC); bieżący tydzień = cena teraz, jak na świecy tygodniowej "
                    "w TradingView. Wartości średnich zmieniają się z każdym dniem."}


# ── bloki: poprzedni cykl (ETF) ──────────────────────────────
def prev_range(S):
    """Poprzedni cykl: od 1. zamknięcia nad EMA po dnie do szczytu hossy (albo dziś)."""
    p = S["prev"]
    return p["first"], (p["top"] if p["top"] is not None else S["n"])


def prev_runs(S):
    a, b = prev_range(S)
    return runs_below(S["cl"], S["e"], a, b)


def prev_intro(S):
    ts, cl, e, lo, phs, p = (S[x] for x in ("ts", "cl", "e", "lo", "phs", "prev"))
    runs = prev_runs(S)
    by = {"acc": [r for r in runs if phase_at(phs, ts[r[0]]) == "acc"], "bull": [r for r in runs if phase_at(phs, ts[r[0]]) == "bull"]}
    etf = C.day_of(ETF_START)
    a, b = prev_range(S)
    after_etf = [r for r in runs if ts[r[0]] >= etf]
    longest = max(runs, key=lambda r: r[1] - r[0]) if runs else None
    deepest = min(runs, key=lambda r: drop_stats(ts, cl, e, lo, r[0], r[1])["deep"]) if runs else None
    t = (f"Cykl od dna {dmy(ts[p['bottom']])} ({usd(cl[p['bottom']])}) do szczytu "
         f"{dmy(ts[b]) + ' (' + usd(cl[b]) + ')' if p['top'] is not None else '— trwa'}. Od {dmy(etf)} w USA działają spotowe "
         f"ETF-y na BTC — to pierwszy cykl, w którym część popytu szła przez nie. Od pierwszego zamknięcia nad EMA200 "
         f"({dmy(ts[a])}) do szczytu cena zamykała się pod średnią {len(runs)} razy: {len(by['acc'])} w akumulacji i "
         f"{len(by['bull'])} w hossie; {len(after_etf)} z nich już po starcie ETF-ów. ")
    if longest:
        t += (f"Najdłuższe zejście: {dmy(ts[longest[0]])}–{dmy(ts[longest[1]])} ({days_pl(longest[1] - longest[0] + 1)}); "
              f"najgłębsze pod średnią: {dmy(ts[deepest[0]])}–{dmy(ts[deepest[1]])} "
              f"({pctf(drop_stats(ts, cl, e, lo, deepest[0], deepest[1])['deep'])}). ")
    t += ("W hossie 2024–2025 cena kilka razy „balansowała na krawędzi” EMA200 — schodziła pod nią na kilka dni i wracała. "
          "Wykres i tabela niżej pokazują każde takie zejście.")
    return {"type": "text", "title": "Dlaczego poprzedni cykl osobno", "text": t}


def phase_bands(S, a, b):
    ts, phs = S["ts"], S["phs"]
    out = []
    for p in phs:
        f, t = p["from"], p.get("to") or ts[-1]
        if t < ts[a] or f > ts[b]:
            continue
        key = "unsure" if p["phase"] == "acc" and p.get("confirmed") is False else p["phase"]
        out.append({"from": max(f, ts[a]), "to": min(t, ts[b]), "color": PHASE_COLORS[key],
                    "label": PHASE_PL[p["phase"]] + (" (niepotwierdzona)" if key == "unsure" else "")})
    return out


def prev_chart(S):
    ts, cl, e, p, n = S["ts"], S["cl"], S["e"], S["prev"], S["n"]
    a = max(0, p["bottom"] - 60)
    marks = cross_markers(ts, cl, e, p["first"], n)
    etf = C.day_of(ETF_START)
    if ts[a] <= etf <= ts[n]:
        marks.append({"t": etf, "shape": "circle", "pos": "above", "color": "#ffc107", "text": "ETF"})
    marks.sort(key=lambda m: m["t"])
    return {"type": "chart", "title": "Poprzedni cykl i dziś: cena BTC i EMA200", "log": True,
            "desc": "Od dna 11.2022 do dziś, skala logarytmiczna. Tło = fazy cyklu (niebieskie akumulacja, zielone hossa, czerwone "
                    "bessa, fioletowe akumulacja niepotwierdzona). Strzałki: ↓ zamknięcie pod EMA200, ↑ powrót nad nią; "
                    "żółty punkt = start spotowych ETF-ów w USA.",
            "note": "Zamknięcia dzienne. Każda para strzałek ↓↑ to jedno zejście pod średnią — szczegóły w tabeli niżej.",
            "bands": phase_bands(S, a, n), "markers": marks,
            "series": [{"name": "Cena BTC", "color": NOW_COLOR, "fmt": "price", "scale": "right",
                        "data": [[ts[i], cl[i]] for i in range(a, n + 1)]},
                       {"name": "EMA200", "color": "#bbbbbb", "fmt": "price", "scale": "right",
                        "data": [[ts[i], round(e[i], 2)] for i in range(a, n + 1)]}]}


def prev_drops_table(S):
    ts, cl, e, lo, phs = S["ts"], S["cl"], S["e"], S["lo"], S["phs"]
    rows = []
    for i0, i1 in prev_runs(S):
        st = drop_stats(ts, cl, e, lo, i0, i1)
        back = i1 + 1 if i1 + 1 < len(cl) else None
        after = pct((cl[back + 30] / cl[back] - 1) * 100, 0) if back is not None and back + 30 < len(cl) else "—"
        rows.append([PHASE_PL.get(phase_at(phs, ts[i0]), ""), f"{dmy(ts[i0])}–{dmy(ts[i1])}", str(i1 - i0 + 1),
                     pctf(st["deep"]), pctf(st["wick_deep"]), pctf(st["drop"]), pctf(st["wick_drop"]), after])
    return {"type": "table", "title": "Każde zejście pod EMA200 w poprzednim cyklu",
            "cols": ["Faza", "Dni z zamknięciem pod EMA200", "Ile dni", "Cena vs EMA200 w najgorszym dniu",
                     "Knot vs EMA200 (najniżej)", "Spadek ceny do dołka (zamknięcie)", "Spadek ceny do dołka (knot)",
                     "Cena 30 dni po powrocie nad EMA200"],
            "rows": rows, "left": [0, 1],
            "desc": "Wszystkie zejścia, także jednodniowe — od pierwszego zamknięcia nad EMA200 po dnie 11.2022 do szczytu 10.2025.",
            "note": "Cena vs EMA200 = jak daleko pod średnią zamknęła się cena w najgorszym dniu zejścia (knot: najniższa cena w "
                    "trakcie dnia). Spadek ceny do dołka = od ostatniego zamknięcia nad EMA200 przed zejściem do najniższego "
                    "zamknięcia (albo knota) w zejściu. Cena 30 dni po powrocie = zmiana od pierwszego zamknięcia z powrotem nad "
                    "EMA200. Knoty: Binance perp (Coinalyze)."}


def below_bands(S, a, b, label="BTC pod EMA200"):
    ts = S["ts"]
    cl_ = clusters(runs_below(S["cl"], S["e"], a, b), gap=3)
    return [{"from": ts[i0], "to": ts[i1], "color": BELOW_COLOR, "label": label} for i0, i1, _ in cl_]


def deriv_chart(d, S):
    ts, cl, n = S["ts"], S["cl"], S["n"]
    oi = {int(t): v for t, v in d.pts("1d", "oi_btc")}
    fund = {int(t): v for t, v in d.pts("1d", "fund_btc")}
    idx = {t: i for i, t in enumerate(ts)}
    coins = [[t, round(v / cl[idx[t]] / 1000, 2)] for t, v in sorted(oi.items()) if t in idx]
    if not coins:
        return {"type": "text", "title": "Derywaty BTC", "text": "Brak danych OI BTC."}
    t0 = coins[0][0]
    f7 = [[t, round(avg_back(fund, t, 7), 2)] for t in sorted(fund) if t >= t0 and avg_back(fund, t, 7) is not None]
    a = idx.get(t0, 0)
    return {"type": "chart", "title": "OI BTC w coinach i funding — od 09.2022 do dziś",
            "desc": "Czerwone tło = okresy, gdy BTC zamykał się pod EMA200. OI w coinach rośnie, gdy przybywa otwartych pozycji "
                    "na kontraktach (niezależnie od ceny); funding > ok. 11% rocznie = przewaga longów płacących shortom.",
            "note": "OI w tys. BTC (OI w USD ÷ cena; Binance, Bybit, OKX, Hyperliquid, Deribit). Funding: średnia 7 dni, % w skali "
                    "roku, ważona OI. Krótkie przerwy nad średnią (do 3 dni) połączone w tle.",
            "bands": below_bands(S, a, n),
            "series": [{"name": "OI BTC w coinach (tys.)", "color": NOW_COLOR, "fmt": "num", "scale": "right", "data": coins},
                       {"name": "Funding BTC (7 dni, %/r)", "color": "#5b9cf6", "fmt": "fund", "scale": "left", "data": f7}]}


def breadth_chart(ema, S):
    ts, n = S["ts"], S["n"]
    br = sorted((int(t), v) for t, v, *_ in ema.get("breadth") or [])
    idx = {t: i for i, t in enumerate(ts)}
    br = [(t, v) for t, v in br if t in idx]
    if not br:
        return {"type": "text", "title": "Szerokość rynku", "text": "Brak danych szerokości rynku."}
    a = idx[br[0][0]]
    return {"type": "chart", "title": "Szerokość rynku (alty nad EMA200) i zejścia BTC — od 2019",
            "desc": "Odsetek coinów Binance z ceną nad własną EMA200. Czerwone tło = BTC pod EMA200.",
            "note": "Z wycofanymi coinami (bez błędu przeżywalności). Linia 90% = poziom przy szczytach altów.",
            "bands": below_bands(S, a, n), "lines": [{"value": 90, "label": "90%", "color": "#888"}], "range": [0, 100],
            "series": [{"name": "Szerokość rynku", "color": "#4dd0e1", "fmt": "pct", "scale": "right",
                        "data": [[t, v] for t, v in br]}]}


# ── bloki: wszystkie cykle ───────────────────────────────────
def cycles_table(S):
    ts, cl, e, hist, cur = S["ts"], S["cl"], S["e"], S["hist"], S["cur"]
    rows = []
    for c in hist + ([cur] if cur and cur["first"] is not None else []):
        b, f = c["bottom"], c["first"]
        first_long = c["long"][0] if c["long"] else None
        below_total = sum(i1 - i0 + 1 for i0, i1 in c["runs"])
        span = c["end"] - f + 1
        if c["ongoing"]:
            last, after = "trwa", "—"
        else:
            last = f"{dmy(ts[c['long'][-1][1] + 1])} ({c['long'][-1][1] + 1 - f} dni po 1. przebiciu)" if c["long"] else "—"
            a = (c["long"][-1][1] + 1) if c["long"] else f
            nxt = next((i for i in range(a, len(ts)) if e[i] is not None and cl[i] <= e[i]
                        and all(cl[j] <= e[j] for j in range(i, min(i + LONG, len(ts))))), None)
            after = days_pl((nxt if nxt is not None else len(ts)) - a)
        rows.append([f"{dmy(ts[b])}" + (" (uznane)" if not c["confirmed"] else ""),
                     f"{dmy(ts[f])} ({f - b} dni po dnie)",
                     str(first_long[0] - f) if first_long else ("—" if c["ongoing"] else "brak"),
                     str(len(c["long"])), str(len(c["runs"])),
                     f"{100 * below_total / span:.0f}%",
                     last, after,
                     dmy(ts[c["end"] + 1]) if not c["ongoing"] and c["end"] + 1 < len(ts) else "trwa"])
    if cur and cur["first"] is not None and not cur["long"]:
        rows[-1][2] = f"{len(ts) - cur['first']} i liczymy"
    return {"type": "table", "title": "Akumulacja po dnie cyklu: pierwsze wybicie nad EMA200 i powroty pod nią",
            "cols": ["Dno cyklu", "1. zamknięcie nad EMA200", "Dni nad EMA200 do 1. dłuższego zejścia", "Dłuższych zejść",
                     "Wszystkich zejść", "Dni pod EMA200 (udział)", "Koniec ostatniego dłuższego zejścia",
                     "Potem nad EMA200 bez dłuższej przerwy", "Koniec akumulacji"],
            "rows": rows, "left": [0, 1, 6], "plain": True,
            "desc": "Każdy wiersz to jeden cykl: od pierwszego zamknięcia nad EMA200 po dnie do końca akumulacji (zamknięcie nad "
                    "szczytem poprzedniego cyklu). Ostatni wiersz = obecny cykl.",
            "note": f"Dłuższe zejście = okres z zamknięciami pod EMA200 trwający co najmniej {LONG} dni (przerwy nad średnią do "
                    f"{GAP} dni łączone). Wszystkich zejść = także 1–6-dniowe. Udział = odsetek dni akumulacji (od 1. przebicia) "
                    f"z zamknięciem pod EMA200. „Potem nad EMA200” — do pierwszych {LONG} zamknięć z rzędu pod EMA200 (także w "
                    "hossie lub bessie)."}


def overlay_chart(S):
    ts, cl, e, hist, cur = S["ts"], S["cl"], S["e"], S["hist"], S["cur"]
    series = []
    for j, c in enumerate(hist):
        f = c["first"]
        series.append({"name": cycle_label(ts, c), "color": COLORS[j % len(COLORS)], "fmt": "chg", "scale": "right",
                       "data": [[i - f, round((cl[i] / e[i] - 1) * 100, 2)] for i in range(f, min(f + OVERLAY_DAYS + 1, len(ts)))]})
    if cur and cur["first"] is not None:
        f = cur["first"]
        series.append({"name": cycle_label(ts, cur) + " (teraz)", "color": NOW_COLOR, "fmt": "chg", "scale": "right", "width": 3,
                       "data": [[i - f, round((cl[i] / e[i] - 1) * 100, 2)] for i in range(f, len(ts))]})
    return {"type": "chart", "x": "days", "title": "Odległość od EMA200 w dniach od pierwszego wybicia nad nią",
            "desc": "Wszystkie cykle nałożone: dzień 0 = pierwsze zamknięcie nad EMA200 po dnie. Poniżej 0% = cena pod średnią. "
                    "Gruba pomarańczowa linia = obecny cykl.",
            "note": f"Pierwsze {OVERLAY_DAYS} dni każdego cyklu. Zamknięcia dzienne.",
            "lines": [{"value": 0, "label": "EMA200", "color": "#888"}], "series": series}


def bottom_chart(S):
    ts, cl, hist, cur = S["ts"], S["cl"], S["hist"], S["cur"]
    series = []
    skip = [c for c in hist if max(cl[c["bottom"]:c["bottom"] + BOTTOM_DAYS + 1]) / cl[c["bottom"]] > 15]
    for j, c in enumerate(hist):
        if c in skip:
            continue
        b = c["bottom"]
        series.append({"name": cycle_label(ts, c), "color": COLORS[j % len(COLORS)], "fmt": "x", "scale": "right",
                       "data": [[i - b, round(cl[i] / cl[b], 3)] for i in range(b, min(b + BOTTOM_DAYS + 1, len(ts)))]})
    if cur:
        b = cur["bottom"]
        series.append({"name": cycle_label(ts, cur) + " (teraz)", "color": NOW_COLOR, "fmt": "x", "scale": "right", "width": 3,
                       "data": [[i - b, round(cl[i] / cl[b], 3)] for i in range(b, len(ts))]})
    return {"type": "chart", "x": "days", "log": True, "title": "Cena ÷ dno cyklu w dniach od dna",
            "desc": "Jak szybko cena oddalała się od dna w każdym cyklu: 1,0× = cena dna, 2,0× = dwa razy wyżej. Dzień 0 = dno. "
                    "Skala logarytmiczna.",
            "note": f"Pierwsze {BOTTOM_DAYS} dni po dnie. Zamknięcia dzienne."
                    + (" Pominięty cykl " + ", ".join(cycle_label(ts, c) for c in skip)
                       + " — cena urosła ponad 15× i spłaszczyłaby pozostałe linie." if skip else ""),
            "lines": [{"value": 1, "label": "cena dna", "color": "#888"}], "series": series}


def episodes_table(S):
    ts, cl, e, lo, hist = S["ts"], S["cl"], S["e"], S["lo"], S["hist"]
    rows = []
    for c in hist:
        f, b = c["first"], c["bottom"]
        for i0, i1, nb in c["long"]:
            st = drop_stats(ts, cl, e, lo, i0, i1)
            fw = lambda h: pct((cl[i0 + h] / cl[i0] - 1) * 100, 0) if i0 + h < len(cl) else "—"  # noqa: E731
            rows.append([cycle_label(ts, c), f"{dmy(ts[i0])}–{dmy(ts[i1])}", f"{i1 - i0 + 1} ({nb})", str(i0 - f),
                         pctf(st["deep"]), pctf(st["drop"]), pctf(st["wick_drop"]),
                         pct((st["low"] / cl[b] - 1) * 100, 0), fw(90), fw(180)])
    return {"type": "table", "title": "Dłuższe zejścia pod EMA200 w akumulacji — wszystkie cykle",
            "cols": ["Cykl", "Okres", "Dni (w tym zamknięć pod EMA200)", "Start: dni od 1. wybicia nad EMA200",
                     "Cena vs EMA200 w najgorszym dniu", "Spadek ceny do dołka (zamknięcie)", "Spadek ceny do dołka (knot)",
                     "Najniższe zamknięcie vs dno cyklu", "Cena 90 dni po starcie zejścia", "Cena 180 dni po starcie zejścia"],
            "rows": rows, "left": [0, 1],
            "desc": "Każde dłuższe zejście pod średnią po pierwszym wybiciu, aż do końca akumulacji. Dwie pierwsze liczby mówią "
                    "co innego: jak daleko pod średnią była cena w najgorszym dniu i o ile spadła cena od ostatniego dnia nad średnią.",
            "note": "Spadek ceny do dołka = od ostatniego zamknięcia nad EMA200 przed zejściem do najniższego zamknięcia (albo knota) "
                    "w zejściu. Najniższe zamknięcie vs dno cyklu: + = wyżej niż dno (nowego dna nie było). Knoty od 09.2019 — "
                    "wcześniej „—”. 2020: zejście w czasie krachu covidowego."}


def drop_path_chart(S):
    ts, cl, hist, cur, n = S["ts"], S["cl"], S["hist"], S["cur"], S["n"]
    series, j = [], 0
    for c in hist:
        for i0, i1, _ in c["long"]:
            base = cl[i0 - 1]
            series.append({"name": f"{my(ts[i0])}", "color": COLORS[j % len(COLORS)], "fmt": "chg", "scale": "right",
                           "data": [[i - i0, round((cl[i] / base - 1) * 100, 2)]
                                    for i in range(i0, min(i0 + DROP_DAYS, i1 + 31, len(cl) - 1) + 1)]})
            j += 1
    if cur and not S["above"]:
        i0 = S["k"]
        base = cl[i0 - 1]
        series.append({"name": "teraz", "color": NOW_COLOR, "fmt": "chg", "scale": "right", "width": 3,
                       "data": [[i - i0, round((cl[i] / base - 1) * 100, 2)] for i in range(i0, n + 1)]})
    return {"type": "chart", "x": "days", "title": "Dłuższe zejścia dzień po dniu",
            "desc": "Każda linia = jedno dłuższe zejście z akumulacji. Dzień 0 = pierwsze zamknięcie pod EMA200; wartość = cena "
                    "vs ostatnie zamknięcie nad średnią. Widać, jak głęboko i jak szybko spadała cena i kiedy wracała.",
            "note": f"Każda linia kończy się 30 dni po powrocie nad EMA200 (najwyżej {DROP_DAYS} dni). Gdy BTC zejdzie pod EMA200, obecne zejście dojdzie jako gruba "
                    "pomarańczowa linia (po ponownym zbudowaniu raportu).",
            "lines": [{"value": 0, "label": "ostatnie zamknięcie nad EMA200", "color": "#888"}], "series": series}


def lengths_table(S):
    hist = S["hist"]
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


def repeat_table(S, ema_now, price):
    ts, cl, e, lo, hist = S["ts"], S["cl"], S["e"], S["lo"], S["hist"]
    rows = []
    for c in hist:
        for i0, i1, _ in c["long"]:
            st = drop_stats(ts, cl, e, lo, i0, i1)
            rows.append((st["drop"], st["wick_drop"], cycle_label(ts, c), f"{dmy(ts[i0])}–{dmy(ts[i1])}", i1 - i0 + 1))
    rows.sort(key=lambda r: r[0])
    out = []
    for drop, wdrop, name, per, days in rows:
        out.append([name, per, str(days), pctf(drop), usd(ema_now * (1 + drop)),
                    pctf(wdrop), usd(ema_now * (1 + wdrop)) if wdrop is not None else "—",
                    pct(((ema_now * (1 + drop)) / price - 1) * 100)])
    if rows:
        med = statistics.median(r[0] for r in rows)
        out.append(["Mediana", "", str(int(statistics.median(r[4] for r in rows))), pctf(med), usd(ema_now * (1 + med)),
                    "", "", pct(((ema_now * (1 + med)) / price - 1) * 100)])
    return {"type": "table", "title": "Gdyby powtórzyło się zejście z poprzedniego cyklu — przeliczenie na dziś",
            "cols": ["Cykl", "Okres", "Dni", "Spadek do dołka (zamknięcie)", "Dziś to ok. (zamknięcie)",
                     "Spadek do dołka (knot)", "Dziś to ok. (knot)", "Spadek od ceny teraz"],
            "rows": out, "left": [0, 1],
            "desc": "Spadek z każdego dłuższego zejścia przyłożony do dzisiejszej EMA200 (zejście zaczyna się przy średniej). "
                    "Szacunek z historii, nie prognoza.",
            "note": "Od najgłębszego. „Spadek od ceny teraz” = o ile cena musiałaby spaść od obecnej do poziomu z zamknięcia. "
                    "Knoty od 09.2019."}


# ── bloki: tło ───────────────────────────────────────────────
def starts(S):
    """Początki zejść do tabel tła: dłuższe zejścia ze wszystkich cykli + zejścia ≥ 3 dni w hossie poprzedniego cyklu."""
    ts, hist, phs = S["ts"], S["hist"], S["phs"]
    out = [(cycle_label(ts, c), i0) for c in hist for i0, _, _ in c["long"]]
    if S["prev"]:
        out += [("hossa 2024–25", i0) for i0, i1 in prev_runs(S) if phase_at(phs, ts[i0]) == "bull" and i1 - i0 + 1 >= 3]
    return sorted(out, key=lambda x: x[1])


def background_table(d, ema, S):
    ts, cl, n = S["ts"], S["cl"], S["n"]
    m = {sid: dict(d.pts("1d", sid)) for sid in ("mvrv_btc", "p200w_btc", "lev_btc", "oi_btc")}
    fund = dict(d.pts("1d", "fund_btc"))
    pxm = dict(zip(ts, cl))
    br = {int(t): v for t, v, *_ in ((ema or {}).get("breadth") or [])}

    def row(label, i):
        t = ts[i]
        _, e21 = weekly_levels(ts, cl, i)
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
                pctf(coins, 0) if coins is not None else "—", "—" if lev is None else f"{lev:.2f}%",
                "—" if mv is None else f"{mv:.2f}", "—" if p2 is None else f"{p2:.2f}×",
                pct((cl[i] / e21 - 1) * 100) if e21 else "—"]

    rows = [row(lab, i0) for lab, i0 in starts(S)]
    rows.append(row("teraz", n))
    return {"type": "table", "title": "Tło krypto: początek zejść pod EMA200 i teraz",
            "cols": ["Cykl", "Dzień", "Szerokość rynku", "Funding BTC (śr. 7 dni)", "OI BTC w coinach (30 dni)",
                     "Dźwignia BTC (OI / kapitalizacja)", "MVRV", "Cena / SMA 200W", "Cena vs EMA 21W"],
            "rows": rows, "left": [0, 1], "plain": True,
            "desc": "Te same wskaźniki w pierwszym dniu zejścia pod EMA200 i dziś: dłuższe zejścia z akumulacji i zejścia "
                    "trwające co najmniej 3 dni w hossie 2024–2025.",
            "note": "„—” = brak danych z tamtego okresu: szerokość rynku od 03.2019, funding od 01.2020, OI i dźwignia od "
                    "09.2022. Szerokość = odsetek coinów Binance nad EMA200. Funding w % w skali roku (ok. 11% = neutralnie). "
                    "OI w coinach = zmiana OI w USD podzielonego przez cenę (czy przybywa pozycji, niezależnie od ceny)."}


def macro_table(d, S):
    ts, n = S["ts"], S["n"]
    ser = {sid: dict(d.pts("1d", sid)) for sid in ("spx", "ndx", "dxy", "us10y", "net_liq", "vix")}

    def chg(sid, t, diff=False, tol=4 * DAY):
        a, b = at_or_before(ser[sid], t, tol), at_or_before(ser[sid], t - 30 * DAY, tol)
        if a is None or b is None:
            return "—"
        return f"{a - b:+.2f} pp" if diff else pct((a / b - 1) * 100)

    def row(label, i):
        t = ts[i]
        v = at_or_before(ser["vix"], t, 4 * DAY)
        return [label, dmy(t), chg("spx", t), chg("ndx", t), chg("dxy", t), chg("us10y", t, diff=True), chg("net_liq", t, tol=10 * DAY),
                "—" if v is None else f"{v:.1f}"]

    rows = [row(lab, i0) for lab, i0 in starts(S)]
    rows.append(row("teraz", n))
    return {"type": "table", "title": "Tło makro: 30 dni przed początkiem zejścia i teraz",
            "cols": ["Cykl", "Dzień", "S&P 500 (30 dni)", "Nasdaq 100 (30 dni)", "DXY — dolar (30 dni)", "Rentowność 10L (30 dni)",
                     "Płynność netto Fed (30 dni)", "VIX"],
            "rows": rows, "left": [0, 1], "plain": True,
            "desc": "Czy zejście BTC pod EMA200 szło razem z ruchem na rynkach tradycyjnych: zmiana w 30 dniach przed pierwszym "
                    "dniem zejścia (i 30 dni do dziś).",
            "note": "S&P 500 od 07.2016 (TradingView). DXY: wzrost = mocniejszy dolar. Rentowność obligacji 10-letnich USA — zmiana "
                    "w punktach procentowych. Płynność netto Fed = aktywa Fed − konto Skarbu (TGA) − reverse repo. VIX = zmienność "
                    "S&P 500 (ok. 20 = spokojnie, powyżej 30 = nerwowo)."}


def watch_block(S):
    ts, cl, e, s200, n, hist = S["ts"], S["cl"], S["e"], S["s200"], S["n"], S["hist"]
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
            ["SMA200 (dzienna)", f"≈ {usd(s200[n])}", f"Prosta średnia z 200 dni; cena {pct((cl[n] / s200[n] - 1) * 100)} od niej (+ = nad)."]]
    if longs:
        rows.append(["Długość i głębokość dłuższych zejść w historii",
                     f"{min(x[1] - x[0] + 1 for x in longs)}–{max(x[1] - x[0] + 1 for x in longs)} dni",
                     f"Najniższe zamknięcie w zejściu {min(mins):+.0f}%…{max(mins):+.0f}% nad dnem cyklu — w {len(longs)} "
                     "dłuższych zejściach ani razu pod dnem cyklu."])
    rows.append(["Dźwignia i pozycje", "OI w coinach, funding, likwidacje",
                 "Raport wieczorny (Coiny z listy, Likwidacje dziś) i zakładka OI & TOTAL."])
    rows.append(["Alty", "szerokość rynku, OI OTHERS / OI BTC", "Raport poranny (Alty) i zakładka EMA200."])
    rows.append(["Ten raport", "/raport_specjalny btc_ema200",
                 "Zbudowany ponownie przelicza wszystko od nowa — np. po zejściu pod EMA200 dojdzie ono na wykres „dzień po dniu”."])
    return {"type": "table", "title": "Poziomy i dane do obserwacji", "cols": ["Co", "Poziom teraz", "Gdzie / z historii"],
            "rows": rows, "left": [0, 1, 2], "plain": True,
            "desc": "Lista faktów do śledzenia w najbliższych tygodniach; bez prognozy, co się stanie."}
