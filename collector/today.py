"""Raport wieczorny „Krypto dziś” (poprawka 35) — co zmieniło się od zamknięcia dziennej świecy (00:00 UTC).

Raport poranny pokazuje stan po zamknięciu dnia (tło z 2 lat, alty, derywaty, EMA200). Wieczorny tylko to, co
ruszyło się od tego czasu (ok. 21 z 24 godzin doby krypto), bez powtórzeń:
  Rynek od 00:00 UTC (zmiana + zakres dnia, szerokość rynku teraz vs na zamknięciu) →
  Coiny z listy (cena, OI w coinach i w $, co to znaczy, funding, likwidacje dziś) →
  Likwidacje dziś (bloki 3-godzinne) → Ruchy coinów (najmocniejsze, najsłabsze, przecięcia EMA200 na żywo) →
  Makro z USA dziś (tylko gdy były publikacje ★★★; reakcja BTC na świecach 1 h).
Ceny coinów spoza BTC/ETH: Binance spot z gałęzi ema (Orange Pi, co ~5–15 min); BTC/ETH, OI, funding, likwidacje,
TOTAL: świece 1 h z gałęzi data (skan przed raportem). Bez interpretacji — tylko liczby.
"""
import statistics

import alerts
import econ
import periodic as P
import report as R

HOUR, DAY = 3600, 86400
DEFAULT_COINS = ["BTC", "ETH", "SOL", "BNB", "DOGE", "HYPE"]
MARKET = ["px_btc", "px_eth", "total", "total2", "total3es", "btc_d", "ethbtc", "stable_d", "oi_total", "oi_others_vs_btc"]
MOVERS = 8                       # ile najmocniejszych / najsłabszych coinów
LIQ_BLOCK_H = 3                  # likwidacje dziś: bloki 3-godzinne
PX_FROM_DATA = ("BTC", "ETH")    # te ceny z danych 1 h (px_*), reszta z ema.json


def coins_cfg(cfg):
    lst = ((cfg or {}).get("today") or {}).get("coins") or DEFAULT_COINS
    return [str(c).upper() for c in lst]


def day_start(t):
    return int(t) - int(t) % DAY


def base_at(d, sid, t0):
    """Wartość na zamknięciu doby (00:00 UTC): świeca 1 h 23:00–00:00 albo dzienna z poprzedniego dnia."""
    v = R.at(d.pts("1h", sid), t0 - HOUR, HOUR)
    if v is None:
        v = R.at(d.pts("1d", sid), t0 - DAY, DAY)
    return v


def now_at(d, sid):
    p = d.pts("1h", sid)
    return p[-1] if p else None


def pl(t):
    return R.pl_time(t, "%H:%M")


def usd(v):
    """Kwoty likwidacji krótko: $409K, $8.3M, $1.2B."""
    return f"${v / 1e3:.0f}K" if abs(v) < 1e6 else alerts.fmt_value(v, "liq")


# ── sekcje ───────────────────────────────────────────────────
def market_section(d, ema, t0):
    rows = []
    for sid in MARKET:
        last = now_at(d, sid)
        base = base_at(d, sid, t0)
        if not last or base is None:
            continue
        name, f = P.label_fmt(d, sid)
        f = f or "num"
        day = [v for t, v in d.pts("1h", sid) if t >= t0] + [base]
        rows.append([name, P.fv(last[1], f), P.chg(last[1], base, f), f"{P.fv(min(day), f)} – {P.fv(max(day), f)}"])
    bn = R.breadth_now(ema)
    b0 = R.at(R.breadth_series(ema), t0 - DAY, DAY)                 # szerokość na zamknięciu doby (świeca z wczoraj)
    if bn is not None:
        rows.append(["Szerokość rynku (% nad EMA200)", P.fv(bn, "pct0"), P.chg(bn, b0, "pct0") if b0 is not None else "—", "—"])
    if not rows:
        return []
    last_t = max((now_at(d, s) or [0])[0] for s in MARKET)
    return [{"type": "section", "title": "Rynek od zamknięcia dnia"},
            {"type": "table", "title": f"Od 00:00 UTC ({pl(t0)} PL) do teraz", "left": [0],
             "cols": ["Wskaźnik", "Teraz", "Od 00:00 UTC", "Zakres dziś"], "rows": rows,
             "desc": "Co zmieniło się od zamknięcia dziennej świecy. Pełne tło (2 lata, szczyty, cykl) jest w raporcie porannym.",
             "note": f"Świece 1 h (ostatnia od {pl(last_t)} PL, niedokończona). Zakres = najniższe i najwyższe zamknięcie godziny "
                     "dziś. Dla wartości w % różnica w punktach procentowych. Szerokość rynku: coiny Binance z ceną nad EMA200 "
                     "teraz vs na zamknięciu dnia."}]


def coin_rows(d, ema, coins, t0, now, flat):
    by = {c["s"]: c for c in (ema or {}).get("coins") or []}
    rows, notes = [], []
    for coin in coins:
        lc = coin.lower()
        oi_last, oi0 = now_at(d, f"oi_{lc}"), base_at(d, f"oi_{lc}", t0)
        if coin in PX_FROM_DATA:
            pl_, p0 = now_at(d, f"px_{lc}"), base_at(d, f"px_{lc}", t0)
            p1 = pl_[1] if pl_ else None
        else:
            c = by.get(coin) or {}
            p1, p0 = c.get("p"), c.get("c")
            if not c:
                notes.append(f"{coin}: brak pary Binance spot — bez ceny")
        px_ch = R.pct_change(p1, p0) if p1 and p0 else None
        oi_usd = R.pct_change(oi_last[1], oi0) if oi_last and oi0 else None
        oi_coin = ((oi_last[1] / p1) / (oi0 / p0) - 1) * 100 if oi_last and oi0 and p1 and p0 else None
        case = R.oi_case(px_ch, oi_coin, flat) if px_ch is not None and oi_coin is not None else "—"
        fund = d.pts("1h", f"fund_{lc}")
        f_now = fund[-1][1] if fund else None
        f7 = [v for t, v in fund if fund and t > fund[-1][0] - 7 * DAY]
        lg = sum(v for t, v in d.pts("1h", f"liq_{lc}_long") if t >= t0)
        sh = sum(v for t, v in d.pts("1h", f"liq_{lc}_short") if t >= t0)
        liq = (f"{usd(lg + sh)} · {100 * lg / (lg + sh):.0f}% long" if lg + sh
               else ("$0" if d.pts("1h", f"liq_{lc}_long") else "—"))
        if oi_last is None and p1 is None:
            continue
        rows.append([coin, R.fmt_price(p1) if p1 else "—", R.fmt_chg(px_ch), R.fmt_chg(oi_coin), R.fmt_chg(oi_usd), case,
                     f"{f_now:+.1f}%" if f_now is not None else "—",
                     f"{statistics.mean(f7):+.1f}%" if f7 else "—", liq])
    return rows, notes


def coins_section(d, ema, coins, t0, now, L):
    flat = float(L["oi_flat_pct"])
    rows, notes = coin_rows(d, ema, coins, t0, now, flat)
    if not rows:
        return []
    return [{"type": "section", "title": "Coiny z listy"},
            {"type": "table", "title": "Cena, lewar, funding i likwidacje — od 00:00 UTC", "left": [0, 5],
             "cols": ["Coin", "Cena", "Cena od 00:00", "OI (w coinach)", "OI ($)", "Co to znaczy", "Funding teraz",
                      "Funding śr. 7 dni", "Likwidacje dziś"], "rows": rows,
             "desc": "Kto dziś napędza ruch. Cena ↑ + OI ↑ = nowe longi; cena ↓ + OI ↑ = nowe shorty; cena ↑ + OI ↓ = "
                     "zamykanie shortów; cena ↓ + OI ↓ = zamykanie longów. Funding w % rocznie (neutralnie ok. 11%).",
             "note": "OI, funding i likwidacje: Coinalyze, świece 1 h (likwidacje tylko Binance, Bybit, OKX — dolne oszacowanie). "
                     "Ceny BTC i ETH z tych samych danych; pozostałe z Binance spot (gałąź ema, co ~5–15 min), więc OI w coinach "
                     f"jest dla nich przybliżone. Zmiana poniżej {flat:g}% = „bez zmian”."
                     + (" " + "; ".join(notes) + "." if notes else "")}]


def liq_section(d, t0, now):
    hl, hs = d.pts("1h", "liq_total_long"), dict(d.pts("1h", "liq_total_short"))
    if not hl:
        return []
    step = LIQ_BLOCK_H * HOUR
    last_t = hl[-1][0]
    rows = []
    for a in range(t0, last_t + 1, step):
        lv = sum(v for t, v in hl if a <= t < a + step)
        sv = sum(v for t, v in hs.items() if a <= t < a + step)
        tot = lv + sv
        rows.append({"label": f"{pl(a)[:2]}–{pl(a + step)[:2]}", "long": lv, "short": sv, "current": a + step > last_t + HOUR,
                     "text": f"{usd(tot)} · {100 * lv / tot:.0f}% long" if tot else "$0"})
    # typowy blok 3 h: percentyl 90 z ostatnich 60 dni (pełne bloki przed dziś)
    hist = []
    for a in range(t0 - 60 * DAY, t0, step):
        hist.append(sum(v for t, v in hl if a <= t < a + step) + sum(v for t, v in hs.items() if a <= t < a + step))
    hist = [x for x in hist if x > 0] if any(hist) else []
    big = sorted(hist)[min(len(hist) - 1, int(len(hist) * 0.9))] if len(hist) >= 20 else None
    lg_day = sum(v for t, v in hl if t >= t0)
    sh_day = sum(v for t, v in hs.items() if t >= t0)
    tot_day = lg_day + sh_day
    top = max(((t, v + hs.get(t, 0.0)) for t, v in hl if t >= t0), key=lambda x: x[1], default=None)
    days = [(t, v + dict(d.pts("1d", "liq_total_short")).get(t, 0.0)) for t, v in d.pts("1d", "liq_total_long")
            if t0 - 730 * DAY <= t < t0]
    med = statistics.median([v for _, v in days]) if days else None
    note = (f"Dziś do teraz: {alerts.fmt_value(tot_day, 'liq')}"
            + (f" ({100 * lg_day / tot_day:.0f}% long)" if tot_day else "")
            + (f"; mediana całej doby z 2 lat: {alerts.fmt_value(med, 'liq')}" if med else "")
            + (f"; największa godzina: {pl(top[0])}–{pl(top[0] + HOUR)} PL, {alerts.fmt_value(top[1], 'liq')}" if top and top[1] else "")
            + ". Suma z Binance, Bybit i OKX (bez Hyperliquid) — dolne oszacowanie.")
    return [{"type": "section", "title": "Likwidacje dziś"},
            {"type": "bars", "title": "Likwidacje od 00:00 UTC — bloki 3-godzinne (czas polski)", "rows": rows,
             "label_col": "Godziny (PL)",
             "parts": [{"key": "long", "name": "longi", "color": "#e05252"}, {"key": "short", "name": "shorty", "color": "#4caf7d"}],
             "line": {"value": big, "label": f"duży blok: {alerts.fmt_value(big, 'liq')} (więcej tylko w 10% bloków z 60 dni)"}
             if big else None,
             "desc": "Kiedy dziś czyszczony był lewar. Duże likwidacje longów = zjazd w dół, shortów = short squeeze.",
             "note": note}]


def movers_section(ema, t0, L):
    coins = [c for c in (ema or {}).get("coins") or [] if c.get("p") and c.get("c")]
    if not coins:
        return []
    min_vol = float(L["ema_min_volume"])
    vol_txt = alerts.fmt_value(min_vol, "liq")
    for c in coins:
        c["_ch"] = (c["p"] / c["c"] - 1) * 100
    up_all = sum(1 for c in coins if c["_ch"] > 0)
    big = [c for c in coins if (c.get("vol") or 0) >= min_vol]
    big.sort(key=lambda c: -c["_ch"])

    def row(c):
        return [c["s"], R.fmt_price(c["p"]), R.fmt_chg(c["_ch"]), f"{c.get('d', 0):+.1f}%", alerts.fmt_value(c.get("vol"), "liq")]
    cols = ["Coin", "Cena", "Od 00:00 UTC", "Od EMA200", "Obrót/dzień"]
    out = [{"type": "section", "title": "Ruchy coinów dziś"}]
    out.append({"type": "table", "title": f"Najmocniejsze i najsłabsze — obrót ≥ {vol_txt} dziennie", "cols": cols,
                "rows": [row(c) for c in big[:MOVERS]] + [["…", "", "", "", ""]] + [row(c) for c in big[-MOVERS:]]
                if len(big) > 2 * MOVERS else [row(c) for c in big],
                "desc": f"Na plus od 00:00 UTC: {up_all} z {len(coins)} coinów Binance (wszystkie, bez progu obrotu). "
                        f"Tabela: {MOVERS} najmocniejszych i {MOVERS} najsłabszych z {len(big)} coinów z obrotem ≥ {vol_txt}.",
                "note": "Binance spot */USDT; zmiana od zamknięcia dziennej świecy. „Od EMA200” = odległość ceny od średniej teraz."})
    cross = [c for c in coins if c.get("e") and (1 if c["p"] >= c["e"] else -1) != (c.get("side") or 0)]
    up = sum(1 for c in cross if c["p"] >= c["e"])
    txt = (f"Dziś {len(cross)} coinów jest po drugiej stronie EMA200 niż na wczorajszym zamknięciu: {up} wybiło w górę, "
           f"{len(cross) - up} spadło pod średnią (wszystkie coiny). Potwierdzenie dopiero na zamknięciu dnia.")
    cb = sorted([c for c in cross if (c.get("vol") or 0) >= min_vol], key=lambda c: -(c.get("vol") or 0))
    if cb:
        out.append({"type": "table", "title": f"Przecięcia EMA200 dziś (na żywo) — obrót ≥ {vol_txt}", "plain": True,
                    "cols": ["Coin", "Kierunek", "Cena", "EMA200", "Odległość", "Obrót/dzień"],
                    "rows": [[c["s"], "w górę" if c["p"] >= c["e"] else "w dół", R.fmt_price(c["p"]), R.fmt_price(c["e"]),
                              f"{c.get('d', 0):+.2f}%", alerts.fmt_value(c.get("vol"), "liq")] for c in cb[:15]],
                    "desc": txt,
                    "note": "Binance spot */USDT, cena teraz vs EMA200; dzień przecięcia liczy się dopiero po zamknięciu świecy "
                            "(wtedy trafi do raportu porannego i zakładki EMA200)."})
    else:
        out.append({"type": "text", "title": "Przecięcia EMA200 dziś (na żywo)",
                    "text": txt + f" Żaden z obrotem ≥ {vol_txt} dziennie."})
    return out


def macro_section(d, macro, t0, now, cfg):
    """Publikacje ★★★ z USA od 00:00 UTC i zmiana BTC wokół nich. Brak publikacji (np. weekend) → sekcji nie ma."""
    if macro is None:
        return []
    if macro.get("error"):
        return [{"type": "section", "title": "Makro z USA dziś"},
                {"type": "text", "title": "", "text": f"Kalendarz ekonomiczny niedostępny ({macro['error']})."}]
    countries = [c.upper() for c in econ.settings(cfg)["countries"] or []]
    evs = []
    for e in macro.get("events") or []:
        try:
            ts = econ._ts(e)
        except (ValueError, TypeError):
            continue
        if (e.get("importance") or 0) >= 1 and t0 <= ts <= now and \
                (not countries or str(e.get("country") or "").upper() in countries):
            evs.append(dict(e, _ts=ts))
    if not evs:
        return []
    px = d.pts("1h", "px_btc")
    rows = []
    for e in econ._sorted(evs):
        h = e["_ts"] - e["_ts"] % HOUR
        a, b = R.at(px, h - HOUR, HOUR), R.at(px, h + HOUR, HOUR)          # zamknięcie o pełnej godzinie → +2 h
        if b is not None and (not px or px[-1][0] < h + HOUR):
            b = None
        rows.append([econ.pl_hm(e["_ts"]), econ._name(e), econ.fmt_num(e.get("actual"), e), econ.fmt_num(e.get("forecast"), e),
                     econ.diff_text(e), R.fmt_chg(R.pct_change(b, a)) if a and b else "—"])
    return [{"type": "section", "title": "Makro z USA dziś"},
            {"type": "table", "title": "Publikacje ★★★ i zmiana BTC", "left": [1],
             "cols": ["Godz. PL", "Publikacja", "Wynik", "Prognoza", "Wynik − prognoza", "BTC (2 h)"], "rows": rows,
             "desc": "Najważniejsze dane z USA z dziś i jak w tym czasie zmieniła się cena BTC.",
             "note": "BTC (2 h) = zmiana ceny od pełnej godziny przed publikacją do zamknięcia drugiej godziny (świece 1 h; "
                     "inne wydarzenia w tym czasie też się liczą). Kalendarz: TradingView, wysoka ważność. Godziny w czasie polskim."}]


def build(d, ema, now, cfg, macro, L, head_blocks, ema_upd):
    t0 = day_start(now)
    blocks = list(head_blocks)
    blocks += market_section(d, ema, t0)
    blocks += coins_section(d, ema, coins_cfg(cfg), t0, now, L)
    blocks += liq_section(d, t0, now)
    blocks += movers_section(ema, t0, L)
    blocks += macro_section(d, macro, t0, now, cfg)
    parts = []
    for sid in ("px_btc", "total"):
        last, base = now_at(d, sid), base_at(d, sid, t0)
        if last:
            name, f = P.label_fmt(d, sid)
            parts.append(f"{name} {P.fv(last[1], f or 'num')}" + (f" ({P.chg(last[1], base, f or 'num')} od 00:00 UTC)" if base else ""))
    hl, hs = d.pts("1h", "liq_total_long"), d.pts("1h", "liq_total_short")
    if hl:
        parts.append("likwidacje dziś " + alerts.fmt_value(sum(v for t, v in hl if t >= t0) + sum(v for t, v in hs if t >= t0), "liq"))
    bn = R.breadth_now(ema)
    if bn is not None:
        parts.append(f"szerokość rynku {bn:.0f}%")
    return {"id": R.utc(now, "%Y%m%d-%H%M") + "-evening", "kind": "evening", "layout": 2,
            "title": R.KIND_TITLES["evening"], "created": now, "summary": " · ".join(parts),
            "period": {"start": t0, "end": now},
            "sources": {"data_updated": d.updated or None, "ema_updated": ema_upd or None}, "blocks": blocks}
