"""Series catalogue, OI aggregation and derived indicators."""

HOUR = 3600
DAY = 86400

# group → how the chart treats it: oi/mcap = USD, pct = percent, ratio = multiplier
CATALOG = {
    # ── Open interest ──
    "oi_total": dict(name="OI TOTAL", group="oi", color="#9e9e9e",
                     desc="Łączny open interest (wartość otwartych pozycji) na perpach wszystkich śledzonych coinów, zsumowany z wybranych giełd, w USD."),
    "oi_btc": dict(name="OI BTC", group="oi", color="#f7931a",
                   desc="Open interest wszystkich perpetuali BTC (USDT, USDC i coin-margined) zsumowany z wybranych giełd, w USD."),
    "oi_eth": dict(name="OI ETH", group="oi", color="#8c9eff",
                   desc="Open interest wszystkich perpetuali ETH zsumowany z wybranych giełd, w USD."),
    "oi_btc_binance": dict(name="OI BTC Binance", group="oi", color="#4dd0e1",
                           desc="Open interest perpetuala BTCUSDT (USDT-M) tylko na Binance, w USD — z archiwum "
                                "data.binance.vision, od 09.2020 (dłużej niż suma giełd z Coinalyze, która zaczyna "
                                "się 09.2022). Odczyt z końca dnia (23:55 UTC). Binance to tylko część rynku — "
                                "porównuj kształt, nie poziom z OI BTC."),
    "oi_eth_binance": dict(name="OI ETH Binance", group="oi", color="#9575cd",
                           desc="Open interest perpetuala ETHUSDT (USDT-M) tylko na Binance, w USD — z archiwum "
                                "data.binance.vision, od 12.2021. Odczyt z końca dnia (23:55 UTC)."),
    "oi_alts": dict(name="OI ALTS", group="oi", color="#4caf7d",
                    desc="Open interest wszystkich coinów OPRÓCZ BTC (z ETH). Odpowiednik TOTAL2 po stronie derywatów."),
    "oi_others": dict(name="OI OTHERS", group="oi", color="#ce93d8",
                      desc="Open interest wszystkich coinów OPRÓCZ BTC i ETH. Odpowiednik TOTAL3 po stronie derywatów."),
    # ── Market cap (TradingView CRYPTOCAP) ──
    "total": dict(name="TOTAL", group="mcap", color="#e0e0e0",
                  desc="Kapitalizacja całego rynku krypto (CRYPTOCAP:TOTAL z TradingView)."),
    "total2": dict(name="TOTAL2", group="mcap", color="#26c6da",
                   desc="Kapitalizacja rynku krypto bez BTC (CRYPTOCAP:TOTAL2)."),
    "total3": dict(name="TOTAL3", group="mcap", color="#ffc107",
                   desc="Kapitalizacja rynku krypto bez BTC i ETH (CRYPTOCAP:TOTAL3)."),
    "totales": dict(name="TOTAL bez stable", group="mcap", color="#bdbdbd",
                    desc="Kapitalizacja całego rynku krypto bez stablecoinów (CRYPTOCAP:TOTALES)."),
    "total3es": dict(name="TOTAL3 bez stable", group="mcap", color="#ffe082",
                     desc="Kapitalizacja bez BTC, ETH i stablecoinów (CRYPTOCAP:TOTAL3ES) — „czyste” alty."),
    "others": dict(name="OTHERS (TV)", group="mcap", color="#80cbc4",
                   desc="Kapitalizacja wszystkich coinów OPRÓCZ top 10 (CRYPTOCAP:OTHERS). Małe i średnie alty — "
                        "najbardziej spekulacyjna część rynku. Uwaga: to inna grupa niż nasze OI OTHERS (bez BTC i ETH)."),
    "stable_mcap": dict(name="Stablecoiny", group="mcap", color="#26a69a",
                        desc="Kapitalizacja stablecoinów (TOTAL − TOTALES). Rośnie = do krypto napływa nowy kapitał (suchy proch na zakupy)."),
    # ── Dominance ──
    "btc_d": dict(name="BTC.D", group="pct", color="#ff9800",
                  desc="Dominacja BTC: udział kapitalizacji BTC w TOTAL, w % (CRYPTOCAP:BTC.D)."),
    "eth_d": dict(name="ETH.D", group="pct", color="#7986cb",
                  desc="Dominacja ETH: udział kapitalizacji ETH w TOTAL, w % (CRYPTOCAP:ETH.D)."),
    "usdt_d": dict(name="USDT.D", group="pct", color="#26a69a",
                   desc="Dominacja USDT: udział stablecoina USDT w TOTAL, w %. Rośnie, gdy kapitał ucieka do gotówki (CRYPTOCAP:USDT.D)."),
    "stable_d": dict(name="Stablecoiny.D", group="pct", color="#26a69a",
                     desc="Dominacja WSZYSTKICH stablecoinów: (TOTAL − TOTALES) / TOTAL, w %. Szersze niż USDT.D (obejmuje USDC i resztę). "
                          "Rośnie, gdy kapitał ucieka do gotówki lub gdy rynek spada; spada w hossie. "
                          "BTC.D + ETH.D + Stablecoiny.D + Alty.D = 100%."),
    "alts_d": dict(name="Alty.D", group="pct", color="#ffe082",
                   desc="Dominacja altów bez BTC, ETH i stablecoinów: TOTAL3ES / TOTAL, w %. "
                        "To cała „reszta” rynku (XRP, BNB, SOL i wszystkie mniejsze). "
                        "BTC.D + ETH.D + Stablecoiny.D + Alty.D = 100%. OTHERS.D (poza top 10) to jej część."),
    "others_d": dict(name="OTHERS.D", group="pct", color="#80cbc4",
                     desc="Dominacja OTHERS: udział coinów spoza top 10 w TOTAL, w % (CRYPTOCAP:OTHERS.D). "
                          "Rośnie w fazie „altseason”, gdy kapitał przelewa się w małe alty."),
    "oi_btc_dom": dict(name="OI BTC.D", group="pct", color="#ffb74d",
                       desc="Dominacja BTC w open interest: OI BTC / OI TOTAL, w %. Odpowiednik BTC.D po stronie derywatów. Spadek = lewar przenosi się na alty."),
    # ── Pairs ──
    "ethbtc": dict(name="ETH/BTC", group="pair", color="#9fa8da",
                   desc="Cena ETH wyrażona w BTC (BINANCE:ETHBTC). Rośnie = ETH silniejszy od BTC; "
                        "trwały wzrost ETH/BTC zwykle poprzedza i towarzyszy rotacji kapitału w alty."),
    # ── Leverage & ratios ──
    "oi_alts_vs_btc": dict(name="OI ALTS / OI BTC", group="ratio", color="#64b5f6",
                           desc="Ile razy OI wszystkich altów (z ETH) jest większe od OI BTC. Uwaga: zawiera ETH, więc zwykle jest > 1. Do sygnału „alty zrównują się z BTC” używaj OI OTHERS / OI BTC."),
    "alts_vs_btc": dict(name="Alty / BTC", group="ratio", color="#26c6da",
                        desc="Kapitalizacja altów bez BTC, ETH i stablecoinów (TOTAL3ES) podzielona przez kapitalizację BTC "
                             "(= Alty.D / BTC.D). Odpowiednik OI OTHERS / OI BTC po stronie realnego kapitału (spot). "
                             "Bez stablecoinów, bo te nie spadają w bessie i zawyżałyby wynik (TOTAL3/BTC w 2022 ~1,05). "
                             "Szczyty: 01.2018 ~1,17, 05.2021 ~0,91, 12.2023 i 12.2024 ~0,47–0,48, 09.2025 ~0,38 — każdy cykl niżej."),
    "oi_others_vs_btc": dict(name="OI OTHERS / OI BTC", group="ratio", color="#f06292",
                             desc="OI altów BEZ ETH podzielone przez OI BTC. 1.0 = zrównanie. Historycznie: szczyt altów w grudniu 2024 przy ~1.1–1.27, wrzesień 2025 ~1.05–1.07, tuż przed krachem 10.10.2025 ~0.95, szczyt z marca 2024 ~0.85. Wysoko = lewar ucieka w małe alty."),
    "lev_btc": dict(name="Dźwignia BTC", group="pct", color="#f7931a",
                    desc="OI BTC / kapitalizacja BTC (TOTAL − TOTAL2), w %. Ile otwartych pozycji przypada na kapitalizację BTC."),
    "lev_alts": dict(name="Dźwignia ALTS", group="pct", color="#4caf7d",
                     desc="OI ALTS / kapitalizacja altów bez stablecoinów (TOTAL2 − stablecoiny), w %. Wysokie wartości = wzrosty altów napędzane lewarem, ryzyko kaskady likwidacji."),
    "lev_others": dict(name="Dźwignia OTHERS", group="pct", color="#ce93d8",
                       desc="OI OTHERS / TOTAL3 bez stablecoinów (TOTAL3ES), w %. Lewar na altach bez ETH względem ich kapitalizacji."),
}


def watch_id(sym):
    return f"oi_{sym.lower()}"


PALETTE = ["#5b9cf6", "#e05252", "#ffd54f", "#ba68c8", "#4dd0e1", "#aed581",
           "#ff8a65", "#90a4ae", "#f06292", "#9575cd"]


# ── cykl BTC i makro USA (poprawka 29, collector/cycle.py) — dzienne ─────────────
LINES_NOTE = (" Linie: wartość przy szczytach (czerwone) i dnach (zielone) ceny BTC w poprzednich cyklach "
              "(cykl = okres między halvingami), wyliczone z danych.")
CYCLE_CATALOG = {
    "rprice_btc": dict(name="Realized price BTC", group="price", color="#ffb74d", fmt="usd",
                       desc="Średnia cena, po której monety BTC ostatnio się ruszały (cena ÷ MVRV, Coin Metrics). "
                            "Cena BTC poniżej realized price = przeciętny posiadacz jest na stracie."),
    "mvrv_btc": dict(name="MVRV BTC", group="cycle", color="#ff7043", fmt="x",
                     desc="Kapitalizacja BTC ÷ realized cap (Coin Metrics Community, od 2010). Ile razy rynek jest "
                          "wyceniany powyżej średniej ceny, po której monety ostatnio się ruszały. 1,0 = cena równa "
                          "realized price." + LINES_NOTE),
    "mvrvz_btc": dict(name="MVRV-Z BTC", group="cycle", color="#ec407a", fmt="z", axis="z",
                      desc="(Kapitalizacja − realized cap) ÷ odchylenie standardowe kapitalizacji z całej historii "
                           "(Coin Metrics). Wysoko = rynek daleko nad średnią ceną zakupu, okolice zera i niżej = "
                           "pod nią. Liczone z całej historii, więc dawne wartości lekko się zmieniają z czasem."
                           + LINES_NOTE),
    "mayer_btc": dict(name="Mayer Multiple", group="cycle", color="#ffd54f", fmt="x",
                      desc="Cena BTC ÷ średnia 200-dniowa (cena od 2009: TradingView INDEX:BTCUSD + Coinalyze). "
                           "Miara trendu, nie wyceny: pokazuje, jak daleko cena odjechała od średniej z ostatnich 200 dni "
                           "(powyżej 1 = nad średnią). W danych od 2013 sama wartość prawie nie wiązała się z wynikiem BTC "
                           "w kolejnym roku (inaczej niż MVRV i cena / średnia 200W)." + LINES_NOTE),
    "p200w_btc": dict(name="Cena / średnia 200W", group="cycle", color="#aed581", fmt="x",
                      desc="Cena BTC ÷ średnia z 200 tygodni (1400 dni). 1,0 = cena równa średniej 200-tygodniowej."
                           + LINES_NOTE),
    "picycle_btc": dict(name="Pi Cycle", group="cycle", color="#4fc3f7", fmt="x",
                        desc="Średnia 111-dniowa ÷ (2 × średnia 350-dniowa) ceny BTC. 1,0 = przecięcie tych średnich "
                             "(sygnał Pi Cycle Top). Przecięcia: 04.2013, 12.2013, 12.2017, 04.2021; przy szczytach "
                             "11.2021 i 10.2025 — brak (przy szczycie 11.2021: 0,57; w cyklu 2024–2025 maks. 0,65). "
                             "Wskaźnik ułożony w 2019 pod szczyty 2013 i 2017; w raportach go nie ma." + LINES_NOTE),
    "ssr": dict(name="SSR (BTC ÷ stablecoiny)", group="cycle", color="#26a69a", fmt="x", axis="ssr",
                desc="Kapitalizacja BTC ÷ kapitał w stablecoinach (TradingView). Nisko = dużo stablecoinów względem "
                     "BTC, wysoko = mało. Przed 2020 stablecoinów było niewiele, więc porównuj od 2020 (linie też od "
                     "2020)." + LINES_NOTE),
    "net_liq": dict(name="Płynność netto Fed", group="macro", color="#90caf9", fmt="usd", axis="usd_macro",
                    desc="Aktywa Fed (WALCL) − konto Skarbu USA w Fed (TGA, WTREGEN) − reverse repo (RRPONTSYD), "
                         "w USD (FRED przez TradingView; tygodniowe dane uzupełnione do dziennych). Rośnie = więcej "
                         "pieniądza w systemie finansowym."),
    "m2": dict(name="M2 USA", group="macro", color="#b0bec5", fmt="usd", axis="usd_macro",
               desc="Podaż pieniądza M2 w USA (FRED M2SL, miesięcznie, wyrównana sezonowo), w USD."),
    "dxy": dict(name="Dolar (DXY)", group="macro", color="#a5d6a7", fmt="num",
                desc="Indeks dolara wobec koszyka walut (TradingView TVC:DXY). Rośnie = mocniejszy dolar."),
    "spx": dict(name="S&P 500", group="macro", color="#ce93d8", fmt="num",
                desc="Indeks S&P 500 (TradingView SP:SPX), zamknięcie sesji w USA."),
    "ndx": dict(name="Nasdaq 100", group="macro", color="#9fa8da", fmt="num",
                desc="Indeks Nasdaq 100 (TradingView), spółki technologiczne, zamknięcie sesji w USA."),
    "vix": dict(name="VIX", group="macro", color="#ef9a9a", fmt="num", pane="low",
                desc="Oczekiwana zmienność S&P 500 na 30 dni z opcji (TradingView TVC:VIX). Wysoko = strach na "
                     "giełdzie w USA."),
    "us10y": dict(name="Rentowność 10L USA", group="macro", color="#ffcc80", fmt="yield", axis="yield", pane="low",
                  desc="Rentowność 10-letnich obligacji USA w % (TradingView TVC:US10Y)."),
    "yc_10y2y": dict(name="Krzywa 10L − 2L", group="macro", color="#ffab91", fmt="pp", axis="yield", pane="low",
                     desc="Rentowność 10-letnich minus 2-letnich obligacji USA, w punktach procentowych. Poniżej 0 = "
                          "odwrócona krzywa rentowności."),
    "gold": dict(name="Złoto", group="macro", color="#ffe082", fmt="usd",
                 desc="Cena złota w USD za uncję (TradingView TVC:GOLD)."),
}
CATALOG.update(CYCLE_CATALOG)


def catalog_with_watchlist(watchlist, liq=None, cvd_coins=None):
    """Full catalogue. liq = {"top": N, "exchanges": [names]} adds the liquidation-tab series; cvd_coins — CVD."""
    cat = dict(CATALOG)
    for i, sym in enumerate(watchlist):
        sid = watch_id(sym)
        if sid not in cat:
            cat[sid] = dict(name=f"OI {sym.upper()}", group="oi", color=PALETTE[i % len(PALETTE)],
                            desc=f"Open interest perpetuali {sym.upper()} zsumowany z wybranych giełd, w USD.")
    if liq:
        cat.update(liq_catalog(watchlist, liq.get("top", 30), liq.get("exchanges", [])))
    if cvd_coins:
        cat.update(cvd_catalog(cvd_coins))
    return cat


# ── liquidations / funding / price (zakładka liq.html) ───────
LIQ_GROUPS = ("btc", "eth", "others", "total")
FUND_GROUPS = ("btc", "eth", "others")
# wstępne progi kolorów fundingu (% rocznie) — do skalibrowania na naszych danych (etap 3)
FUND_ZONES = {"yellow": 20, "red": 40}


def ex_id(name):
    return "liq_ex_" + "".join(ch for ch in (name or "").lower() if ch.isalnum())


def liq_catalog(watchlist, top, exchanges):
    others = f"top {top} altów bez BTC i ETH" + (" + watchlista" if watchlist else "")
    who = {"btc": ("BTC", "perpetuali BTC"), "eth": ("ETH", "perpetuali ETH"),
           "others": ("OTHERS", f"altów ({others})"),
           "total": ("TOTAL", f"BTC, ETH i {others}")}
    colors = {"btc": "#f7931a", "eth": "#8c9eff", "others": "#ce93d8", "total": "#9e9e9e"}
    cat = {}
    for g, (nm, what) in who.items():
        cat[f"liq_{g}_long"] = dict(
            name=f"Likwidacje {nm} long", group="liq", color="#e05252", base=f"liq_{g}", side="long",
            desc=f"Zlikwidowane pozycje LONG {what}, suma z Binance, Bybit i OKX, w USD na świecę. "
                 "Dolne oszacowanie: giełdy publikują tylko część likwidacji, a Hyperliquid nie ma ich w Coinalyze. "
                 "Duże likwidacje longów = kaskada w dół, często wypłukanie lewara blisko lokalnych dołków.")
        cat[f"liq_{g}_short"] = dict(
            name=f"Likwidacje {nm} short", group="liq", color="#4caf7d", base=f"liq_{g}", side="short",
            desc=f"Zlikwidowane pozycje SHORT {what}, suma z Binance, Bybit i OKX, w USD na świecę. "
                 "Dolne oszacowanie (jak wyżej). Duże likwidacje shortów = short squeeze, gwałtowny ruch w górę.")
    for i, sym in enumerate(watchlist):
        s = sym.lower()
        for side, col, word in (("long", "#e05252", "LONG"), ("short", "#4caf7d", "SHORT")):
            cat[f"liq_{s}_{side}"] = dict(
                name=f"Likwidacje {sym.upper()} {side}", group="liq", color=col, base=f"liq_{s}", side=side,
                desc=f"Zlikwidowane pozycje {word} na perpach {sym.upper()}, suma z wybranych giełd, w USD.")
    fund_what = {"btc": "BTC", "eth": "ETH", "others": f"altów ({others})"}
    for g in FUND_GROUPS:
        cat[f"fund_{g}"] = dict(
            name=f"Funding {who[g][0]}", group="fund", color=colors[g], zones=FUND_ZONES,
            desc=f"Funding {fund_what[g]} ważony open interest, przeliczony na % rocznie "
                 "(stawka × liczba okresów w roku; Binance/Bybit/OKX zwykle co 8 h, Hyperliquid co 1 h; "
                 "alty, którym giełda skróciła okres do 4 h, mogą wychodzić zaniżone). "
                 "Neutralnie ok. 11% rocznie (0,01% na 8 h). Dodatni = longi płacą shortom; "
                 "utrzymujący się wysoki = przegrzanie longów, ujemny = przewaga shortów (często blisko dołków). "
                 f"Kolory: żółty od {FUND_ZONES['yellow']}%, czerwony od {FUND_ZONES['red']}% (progi wstępne)."
                 + (" Przed 22.09.2022 (Coinalyze nie ma wcześniejszego OI giełd) średnia ma wagi stałe: "
                    "udziały giełd w OI z pierwszych 30 dni danych; Binance od 01.2020, OKX, Bybit i Deribit "
                    "od 03–04.2020." if g in ("btc", "eth") else ""))
    for i, sym in enumerate(watchlist):
        cat[f"fund_{sym.lower()}"] = dict(
            name=f"Funding {sym.upper()}", group="fund", color=PALETTE[i % len(PALETTE)], zones=FUND_ZONES,
            desc=f"Funding perpetuali {sym.upper()} ważony open interest, % rocznie.")
    for i, name in enumerate(exchanges):
        cat[ex_id(name)] = dict(
            name=f"Likwidacje {name}", group="liq", color=PALETTE[i % len(PALETTE)], exchange=name,
            desc=f"Suma likwidacji (long + short) na {name} dla wszystkich śledzonych coinów, w USD. "
                 "Do porównania udziału giełd.")
    cat["px_btc"] = dict(name="Cena BTC", group="price", color="#f7931a",
                         desc="Cena BTC (zamknięcie świecy perpa BTCUSDT na Binance, przez Coinalyze; "
                              "przed 03.2020 — dzienny indeks TradingView INDEX:BTCUSD, od 2009).")
    cat["px_eth"] = dict(name="Cena ETH", group="price", color="#8c9eff",
                         desc="Cena ETH (zamknięcie świecy perpa ETHUSDT na Binance, przez Coinalyze; "
                              "przed 03.2020 — dzienny indeks TradingView INDEX:ETHUSD, od 2015).")
    return cat


def daily_extreme_from_hourly(hourly, day_from, fn=max):
    """Day value = max (fn=max) or min (fn=min) of the hourly values of that UTC day — daily high / low. {t_day: v}."""
    out = {}
    for t, v in hourly.items():
        d = t - t % DAY
        if d >= day_from:
            out[d] = v if d not in out else fn(out[d], v)
    return out


def daily_sum_from_hourly(hourly, day_from):
    """Day value = sum of the hourly values of that UTC day. {t_day: v}."""
    out = {}
    for t, v in hourly.items():
        d = t - t % DAY
        if d >= day_from:
            out[d] = out.get(d, 0.0) + v
    return out


def aggregate(hist, sym_base, timestamps, last_known=None, ffill_steps=6, step=HOUR):
    """Sum per-symbol OI into per-asset OI at each timestamp.

    hist:       {symbol: {t: value}}
    last_known: {symbol: [t, value]} from the previous run — used to bridge
                short gaps (missing candles / failed requests) so sums don't dip.
    Returns ({base: {t: value}}, new_last_known).
    """
    last_known = dict(last_known or {})
    per_base = {}
    new_last = {}
    for sym, base in sym_base.items():
        # align bucket timestamps to the step grid (robust to off-grid timestamps)
        h = {t - t % step: v for t, v in (hist.get(sym) or {}).items() if v is not None}
        prev = last_known.get(sym)
        prev_t, prev_v = (prev if prev else (None, None))
        dst = per_base.setdefault(base, {})
        for t in timestamps:
            v = h.get(t)
            if v is None and prev_t is not None and t > prev_t and (t - prev_t) <= ffill_steps * step:
                v = prev_v
            elif v is not None:
                prev_t, prev_v = t, v
            if v is not None:
                dst[t] = dst.get(t, 0.0) + v
        if prev_t is not None:
            new_last[sym] = [prev_t, prev_v]
    return per_base, new_last


def oi_series(per_base, timestamps, watchlist):
    """Per-asset OI → catalogue series {id: {t: v}}."""
    out = {k: {} for k in ("oi_total", "oi_btc", "oi_eth", "oi_alts", "oi_others")}
    for sym in watchlist:
        out[watch_id(sym)] = {}
    for t in timestamps:
        total = sum(b.get(t, 0.0) for b in per_base.values())
        if total <= 0:
            continue
        btc = per_base.get("BTC", {}).get(t, 0.0)
        eth = per_base.get("ETH", {}).get(t, 0.0)
        out["oi_total"][t] = total
        out["oi_btc"][t] = btc
        out["oi_eth"][t] = eth
        out["oi_alts"][t] = total - btc
        out["oi_others"][t] = total - btc - eth
        for sym in watchlist:
            v = per_base.get(sym.upper(), {}).get(t)
            if v:
                out[watch_id(sym)][t] = v
    return out


def derived(series):
    """Compute derived indicators in place for one resolution."""
    s = series

    def combine(dst, fn, *ids):
        srcs = [s.get(i) or {} for i in ids]
        if not all(srcs):
            return
        common = set(srcs[0]).intersection(*srcs[1:])
        out = {}
        for t in common:
            try:
                v = fn(*(src[t] for src in srcs))
            except ZeroDivisionError:
                continue
            if v is not None:
                out[t] = v
        s[dst] = out

    combine("oi_btc_dom", lambda b, tot: b / tot * 100, "oi_btc", "oi_total")
    combine("oi_alts_vs_btc", lambda a, b: a / b, "oi_alts", "oi_btc")
    combine("oi_others_vs_btc", lambda o, b: o / b, "oi_others", "oi_btc")
    combine("lev_btc", lambda oi, t1, t2: oi / (t1 - t2) * 100, "oi_btc", "total", "total2")
    combine("stable_mcap", lambda t, tes: t - tes, "total", "totales")
    combine("stable_d", lambda t, tes: (t - tes) / t * 100, "total", "totales")
    combine("alts_d", lambda t3es, t: t3es / t * 100, "total3es", "total")
    combine("alts_vs_btc", lambda t3es, t, t2: t3es / (t - t2) if t > t2 else None, "total3es", "total", "total2")
    # leverage vs market cap WITHOUT stablecoins (no perps on stables); fall back if ES missing
    if s.get("stable_mcap"):
        combine("lev_alts", lambda oi, t2, st: oi / (t2 - st) * 100, "oi_alts", "total2", "stable_mcap")
    else:
        combine("lev_alts", lambda oi, t2: oi / t2 * 100, "oi_alts", "total2")
    if s.get("total3es"):
        combine("lev_others", lambda oi, t3: oi / t3 * 100, "oi_others", "total3es")
    else:
        combine("lev_others", lambda oi, t3: oi / t3 * 100, "oi_others", "total3")
    return s


def daily_from_hourly(hourly, day_from):
    """Day value = last hourly value of that UTC day (= daily close). {t_day: v}."""
    out = {}
    last_t = {}
    for t, v in hourly.items():
        d = t - t % DAY
        if d < day_from:
            continue
        if d not in last_t or t > last_t[d]:
            last_t[d] = t
            out[d] = v
    return out


# ── CVD: kupno − sprzedaż na spot i perp (poprawka 44, collector/cvd.py; pliki cvd_1h/1d.json) ──
CVD_COLORS = {"BTC": ("#4fc3f7", "#ffb74d"), "ETH": ("#4db6ac", "#f48fb1"), "SOL": ("#80deea", "#ce93d8"),
              "BNB": ("#fff176", "#ffcc80"), "XRP": ("#b0bec5", "#ef9a9a"), "DOGE": ("#c5e1a5", "#ffab91")}
PX_COLORS = {"SOL": "#9c6ade", "BNB": "#f3ba2f", "XRP": "#b0bec5", "DOGE": "#c2a633"}


def cvd_catalog(coins):
    """Delta (rysowana narastająco od początku zakresu = CVD) i wolumen dla każdego coina; ceny coinów spoza BTC/ETH."""
    cat = {}
    what = {"spot": ("spot", "Binance, Coinbase, Bybit, Kraken, Bitstamp i Bitfinex (OKX spot niedostępny)",
                     "Zakup prawdziwych coinów."),
            "perp": ("perp", "Binance, Bybit, OKX, Hyperliquid i Deribit", "Kontrakty z dźwignią (perpetuale).")}
    for i, coin in enumerate(coins):
        cs = CVD_COLORS.get(coin, (PALETTE[i % len(PALETTE)], PALETTE[(i + 5) % len(PALETTE)]))
        for j, kind in enumerate(("spot", "perp")):
            nm, ex, txt = what[kind]
            cat[f"cvd_{coin.lower()}_{kind}"] = dict(
                name=f"CVD {coin} {nm}", group="cvd", color=cs[j], fmt="flow", cum=True, axis=f"cvd_{kind}",
                desc=f"Kupno − sprzedaż „po rynku” (transakcje kupujących i sprzedających, którzy biorą cenę z arkusza) "
                     f"na rynkach {nm} {coin}, w $. {txt} Na wykresie suma narastająca od początku wybranego zakresu "
                     "(przyciski zakresu) — linia rośnie, gdy przeważają kupujący. Na kafelku: suma z 24 h, 7 i 30 dni. "
                     f"Giełdy: {ex}; liczone pary do USD/USDT/USDC/FDUSD z co najmniej 1% wolumenu coina. "
                     "Wolumen kupujących z Coinalyze od 05.2019 (perp: od startu rynku); skład giełd rośnie z czasem.")
            cat[f"cvd_{coin.lower()}_{kind}_vol"] = dict(
                name=f"Wolumen {coin} {nm}", group="vol", color=cs[j], fmt="usd", axis=f"vol_{kind}",
                desc=f"Wolumen obrotu na rynkach {nm} {coin} w $ na świecę (te same rynki co CVD {coin} {nm}).")
        if coin not in ("BTC", "ETH"):
            cat[f"px_{coin.lower()}"] = dict(
                name=f"Cena {coin}", group="price", color=PX_COLORS.get(coin, PALETTE[i % len(PALETTE)]), fmt="usd",
                desc=f"Cena {coin} (zamknięcie świecy największego perpa {coin}USDT, zwykle Binance, przez Coinalyze).")
    return cat
