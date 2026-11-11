"""Alty według kapitalizacji (poprawka 46): koszyki z CoinGecko + narracje z DexScreenera.

Po co: TOTAL3, OI OTHERS i „Alty / BTC” są ważone kapitałem — pokazują głównie kilka największych altów.
Tu każdy coin liczy się tak samo: w każdym przedziale kapitalizacji bierzemy medianę zmiany ceny („typowy coin”).

Co robi przy skanie (GitHub; CoinGecko nie jest dostępny z Orange Pi ani potrzebny tam):
  • zapis (snapshot) listy coinów z kapitalizacją ≥ $1M — 12 stron /coins/markets, darmowy klucz demo,
    najwyżej dwa razy na dobę (config `alts.snapshot_hours_utc`, domyślnie pierwszy skan po 00:00 i po 20:00 UTC):
      – „close”  (po 00:00 UTC): zamknięcie dnia → tabela w raporcie porannym + punkt dzienny indeksów,
      – „now”    (po 20:00 UTC): zmiana od zamknięcia dnia → wiersze w raporcie wieczornym,
  • koszyki: > $1B, $100M–1B, $10–100M, $1–10M (bez BTC, ETH, stablecoinów, tokenów opakowanych i LST),
    tylko coiny z obrotem 24 h ≥ `alts.min_volume` ($50 tys.),
  • przydział do koszyka według kapitalizacji z POPRZEDNIEGO zapisu (coin, który dziś urósł z $8M do $15M,
    liczy się dziś do $1–10M) — bez tego małe koszyki wyglądałyby gorzej, a duże lepiej, niż było naprawdę,
  • serie dzienne `alt_idx_*` (1d.json): indeks = 100 w dniu startu, potem × (1 + mediana zmiany koszyka);
    do nakładania w oi.html. Historii wstecz nie ma — budujemy własną od dnia uruchomienia,
  • narracje DexScreenera (/metas/trending/v1) — grupy tokenów ze zmianą kapitalizacji z 24 h.

Pliki: `alts.json` w katalogu danych (tabele dla raportów), stan w state.json → "alts"
(ceny i kapitalizacje z ostatniego zamknięcia, wartości indeksów, lista pomijanych id).
"""
import logging
import os
import time

import requests

log = logging.getLogger("alts")
HOUR, DAY = 3600, 86400
CG = "https://api.coingecko.com/api/v3"
DS = "https://api.dexscreener.com"
UA = {"User-Agent": "Mozilla/5.0 (oi-monitor)", "Accept": "application/json"}

# (id, nazwa, od, do) — od największych; id jest też końcówką id serii: alt_idx_<id>
BUCKETS = (("1b", "Alty > $1B", 1e9, None), ("100m", "Alty $100M – $1B", 1e8, 1e9),
           ("10m", "Alty $10M – $100M", 1e7, 1e8), ("1m", "Alty $1M – $10M", 1e6, 1e7))
MAJORS = ("bitcoin", "ethereum")
DEFAULTS = {
    "enabled": False,                  # włączane w config.yaml (alts: enabled: true), jak CVD
    "min_volume": 50_000,              # minimalny obrót 24 h coina ($), żeby liczył się do koszyka
    "snapshot_hours_utc": [0, 20],     # pierwszy skan po tych godzinach UTC robi zapis; 0 = zamknięcie dnia
    "close_max_delay_hours": 6,        # zapis później niż tyle godzin po 00:00 UTC nie jest już „zamknięciem dnia”
    "max_pages": 16,                   # 250 coinów na stronę; kapitalizacja spada poniżej $1M ok. 12. strony
    "skip_categories": ["stablecoins", "wrapped-tokens", "liquid-staking-tokens"],
    "skip_ids": [],                    # dodatkowe id CoinGecko do pominięcia
    "movers": 0,                       # ile najmocniejszych / najsłabszych coinów na koszyk zapisać w alts.json (0 = wcale;
                                       # raport ich nie pokazuje — decyzja 11.11)
    "metas": True,                     # narracje z DexScreenera
    "metas_top": 12,
}
SERIES = {b[0]: f"alt_idx_{b[0]}" for b in BUCKETS}


def settings(cfg):
    out = dict(DEFAULTS)
    out.update((cfg or {}).get("alts") or {})
    return out


def enabled(cfg):
    return bool(settings(cfg)["enabled"])


def catalog():
    """Serie do oi.html (grupa „idx”): indeks typowego coina w koszyku."""
    colors = {"1b": "#e0e0e0", "100m": "#4caf7d", "10m": "#ce93d8", "1m": "#e57373"}
    return {SERIES[bid]: dict(
        name=name, group="idx", fmt="num", color=colors[bid],
        desc=f"Indeks typowego coina w przedziale kapitalizacji „{name.replace('Alty ', '')}”: 100 w dniu startu zapisu, "
             "potem każdego dnia × (1 + mediana zmiany ceny coinów w koszyku). Każdy coin liczy się tak samo "
             "(TOTAL3 i OI OTHERS są ważone kapitałem, czyli pokazują głównie największe alty). Koszyk = kapitalizacja "
             "z poprzedniego dnia; tylko coiny z obrotem powyżej progu, bez stablecoinów i tokenów opakowanych. "
             "Źródło: CoinGecko. Bez historii wstecz — linia rośnie od dnia uruchomienia. "
             "Porównuj w trybie Index 100 albo % zmiana z pozostałymi koszykami, BTC i ETH.")
        for bid, name, _, _ in BUCKETS}


# ── pobieranie ───────────────────────────────────────────────
def _cg(session, path, params, sleep, calls):
    key = os.environ.get("COINGECKO_API_KEY", "")
    headers = dict(UA, **({"x-cg-demo-api-key": key} if key else {}))
    last = "?"
    for attempt in range(6):
        calls[0] += 1
        try:
            r = session.get(CG + path, params=params, headers=headers, timeout=60)
        except requests.RequestException as e:
            last = str(e)
            sleep(min(10 * (attempt + 1), 60))
            continue
        if r.status_code == 200:
            sleep(2.5)                     # darmowy klucz: ok. 30 zapytań na minutę
            return r.json()
        last = f"HTTP {r.status_code}"
        if r.status_code == 429 or r.status_code >= 500:
            sleep(min(20 * (attempt + 1), 65))
            continue
        raise RuntimeError(f"CoinGecko HTTP {r.status_code}: {r.text[:160]}")
    raise RuntimeError(f"CoinGecko: zbyt wiele nieudanych prób ({last})")


def fetch_coins(session, c, sleep, calls):
    """Wszystkie coiny z kapitalizacją ≥ najniższego progu koszyków, od największych."""
    floor = BUCKETS[-1][2]
    out = []
    for page in range(1, int(c["max_pages"]) + 1):
        got = _cg(session, "/coins/markets", {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250,
                                              "page": page, "price_change_percentage": "24h,7d,30d"}, sleep, calls)
        if not got:
            break
        out += got
        if len(got) < 250 or (got[-1].get("market_cap") or 0) < floor:
            break
    return out


def fetch_skip_ids(session, c, sleep, calls):
    """Id coinów z kategorii pomijanych w koszykach (stablecoiny: 2 strony, reszta: 1)."""
    ids = set()
    for cat in c["skip_categories"] or []:
        for page in range(1, 3 if cat == "stablecoins" else 2):
            got = _cg(session, "/coins/markets", {"vs_currency": "usd", "category": cat, "order": "market_cap_desc",
                                                  "per_page": 250, "page": page}, sleep, calls)
            ids |= {x["id"] for x in got or [] if x.get("id")}
            if len(got or []) < 250:
                break
    return ids


def fetch_metas(session, top):
    """Trendujące narracje DexScreenera → [{name, tokens, mcap, liq, vol, chg24}], od największego wzrostu."""
    r = session.get(DS + "/metas/trending/v1", headers=UA, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"DexScreener HTTP {r.status_code}")
    data = r.json()
    data = data if isinstance(data, list) else (data.get("metas") or data.get("data") or [])

    def num(x, key=None):
        if isinstance(x, dict):
            x = x.get(key) if key else None
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    rows = []
    for m in data:
        ch = num(m.get("marketCapChange"), "h24")
        if not m.get("name") or ch is None:
            continue
        vol = m.get("volume")
        rows.append({"name": str(m["name"])[:40], "tokens": m.get("tokenCount"), "mcap": num(m.get("marketCap")),
                     "liq": num(m.get("liquidity")), "vol": num(vol, "h24") if isinstance(vol, dict) else num(vol),
                     "chg24": round(ch, 2)})
    rows.sort(key=lambda x: -x["chg24"])
    return rows[:int(top)]


# ── liczenie ─────────────────────────────────────────────────
def median(vals):
    v = sorted(vals)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def bucket_of(mcap):
    for bid, _, lo, hi in BUCKETS:
        if mcap is not None and mcap >= lo and (hi is None or mcap < hi):
            return bid
    return None


def is_usd_peg(coin):
    """Stablecoin dolarowy spoza listy kategorii: cena ≈ $1 i brak ruchu w 24 h / 7 dni / 30 dni."""
    p = coin.get("current_price")
    ch = [coin.get(f"price_change_percentage_{k}_in_currency") for k in ("24h", "7d", "30d")]
    return (p is not None and abs(p - 1) < 0.02 and all(x is not None for x in ch)
            and abs(ch[0]) < 0.5 and abs(ch[1]) < 1.0 and abs(ch[2]) < 1.5)


def _f(x, nd=2):
    return None if x is None else round(x, nd)


def bucket_rows(coins, skip, c, prev=None, own=False):
    """Statystyki koszyków z jednego zapisu.

    prev = {id: [cena, kapitalizacja]} z poprzedniego zapisu. Gdy jest: koszyk według TAMTEJ kapitalizacji,
    a `own` (zmiana ceny od tamtego zapisu) trafia do „own” — z niej liczony jest indeks.
    Kolumna „chg” (doba) = own, jeśli own=True (zapis ~24 h temu), inaczej pole 24 h z CoinGecko.
    → (wiersze koszyków, {"bitcoin": {...}, "ethereum": {...}})
    """
    min_vol, k = float(c["min_volume"]), int(c["movers"])
    members = {b[0]: [] for b in BUCKETS}
    majors = {}
    for coin in coins:
        cid, px = coin.get("id"), coin.get("current_price")
        if not cid or not px:
            continue
        ch24 = coin.get("price_change_percentage_24h_in_currency")
        p = (prev or {}).get(cid)
        own_ch = (px / p[0] - 1) * 100 if p and p[0] else None
        row = {"id": cid, "sym": str(coin.get("symbol") or "").upper()[:12], "name": str(coin.get("name") or "")[:24],
               "own": own_ch, "chg": own_ch if own else ch24,
               "chg7": coin.get("price_change_percentage_7d_in_currency"),
               "chg30": coin.get("price_change_percentage_30d_in_currency")}
        if cid in MAJORS:
            majors[cid] = row
            continue
        if cid in skip or is_usd_peg(coin) or (coin.get("total_volume") or 0) < min_vol:
            continue
        bid = bucket_of(p[1] if p else coin.get("market_cap"))
        if bid:
            members[bid].append(row)
    btc = majors.get("bitcoin") or {}
    rows = []
    for bid, name, _, _ in BUCKETS:
        m = [r for r in members[bid] if r["chg"] is not None]
        ch = [r["chg"] for r in m]
        beat = [r for r in m if btc.get("chg") is not None and r["chg"] > btc["chg"]]
        srt = sorted(m, key=lambda r: -r["chg"])
        mv = lambda rs: [[r["sym"], r["name"], _f(r["chg"], 1)] for r in rs]  # noqa: E731
        own_vals = [r["own"] for r in members[bid] if r["own"] is not None]
        rows.append({
            "id": bid, "name": name, "n": len(m),
            "chg": _f(median(ch)), "own": _f(median(own_vals), 3), "own_n": len(own_vals),
            "chg7": _f(median([r["chg7"] for r in members[bid] if r["chg7"] is not None])),
            "chg30": _f(median([r["chg30"] for r in members[bid] if r["chg30"] is not None])),
            "up": _f(100 * sum(1 for x in ch if x > 0) / len(ch), 1) if ch else None,
            "beat_btc": _f(100 * len(beat) / len(m), 1) if m and btc.get("chg") is not None else None,
            "top": mv(srt[:k]), "bottom": mv(srt[::-1][:k]) if len(srt) > k else []})
    maj = {cid: {x: _f(majors[cid].get(x)) for x in ("chg", "own", "chg7", "chg30")} for cid in majors}
    return rows, maj


def due(c, st, now):
    """Czy ten skan robi zapis i jaki: "close" (zamknięcie dnia), "now" (w ciągu dnia) albo None."""
    last = int(st.get("last_t") or 0)
    day0 = int(now) - int(now) % DAY
    if not last:
        return "close" if now - day0 <= float(c["close_max_delay_hours"]) * HOUR else "now"
    for h in sorted({int(x) for x in c["snapshot_hours_utc"]}, reverse=True):
        mark = day0 + h * HOUR
        if now >= mark and last < mark:
            if h == 0:
                return "close" if now - day0 <= float(c["close_max_delay_hours"]) * HOUR else None
            return "now"
    return None


def collect(store, cfg, now, session=None, sleep=time.sleep):
    """Jeden przebieg: w razie potrzeby zapis z CoinGecko, serie indeksów, alts.json. → info (dict)."""
    c = settings(cfg)
    st = store.state.setdefault("alts", {})
    kind = due(c, st, now)
    if not kind:
        return {"snapshot": None}
    s = session or requests.Session()
    calls = [0]
    day0 = int(now) - int(now) % DAY
    # lista pomijanych id: raz na dobę (przy zamknięciu dnia) albo gdy jej jeszcze nie ma
    skip_st = st.get("skip") or {}
    if kind == "close" or not skip_st.get("ids"):
        try:
            skip_st = {"t": int(now), "ids": sorted(fetch_skip_ids(s, c, sleep, calls))}
            st["skip"] = skip_st
        except Exception as e:  # noqa: BLE001 — bez świeżej listy zostaje poprzednia (i filtr „cena ≈ $1”)
            log.warning("CoinGecko, kategorie do pominięcia: %s", e)
    skip = set(skip_st.get("ids") or []) | {str(x) for x in c["skip_ids"] or []}
    coins = fetch_coins(s, c, sleep, calls)
    if len(coins) < 500:
        raise RuntimeError(f"CoinGecko zwrócił tylko {len(coins)} coinów")

    out = store.extra.setdefault("alts.json", {})
    out.update({"min_volume": c["min_volume"], "buckets": [[b[0], b[1]] for b in BUCKETS]})
    close = st.get("close") or {}
    prev, prev_t = close.get("px"), int(close.get("t") or 0)
    hours = (now - prev_t) / HOUR if prev_t else None
    idx = st.setdefault("idx", {})

    if kind == "close":
        own = bool(prev) and 20 <= hours <= 30                 # zmiana od poprzedniego zamknięcia = „doba”
        rows, maj = bucket_rows(coins, skip, c, prev, own)
        day = day0 - DAY                                       # zamknięta doba UTC
        for r in rows:
            sid = SERIES[r["id"]]
            if r["own"] is not None and idx.get(r["id"]):
                idx[r["id"]] = idx[r["id"]] * (1 + r["own"] / 100)
            elif not idx.get(r["id"]):
                idx[r["id"]] = 100.0
            store.put("1d", sid, {day: idx[r["id"]]}, replace_from=day)
        out["close"] = {"t": int(now), "day": day, "prev_t": prev_t or None, "hours": _f(hours, 1),
                        "basis": "own" if own else "cg24h", "rows": rows, "btc": maj.get("bitcoin"),
                        "eth": maj.get("ethereum"), "coins": len(coins)}
        out.pop("now", None)                                   # wiersze „od zamknięcia” z poprzedniego dnia są nieaktualne
        st["close"] = {"t": int(now), "px": {x["id"]: [x["current_price"], x.get("market_cap")]
                                             for x in coins if x.get("id") and x.get("current_price")}}
    else:
        rows, maj = bucket_rows(coins, skip, c, prev, own=bool(prev))
        if prev:
            for r in rows:                                     # punkt dnia w toku (nadpisze go zamknięcie dnia)
                if r["own"] is not None and idx.get(r["id"]):
                    store.put("1d", SERIES[r["id"]], {day0: idx[r["id"]] * (1 + r["own"] / 100)}, replace_from=day0)
        out["now"] = {"t": int(now), "since": prev_t or None, "hours": _f(hours, 1),
                      "basis": "own" if prev else "cg24h", "rows": rows, "btc": maj.get("bitcoin"),
                      "eth": maj.get("ethereum"), "coins": len(coins)}
    info = {"snapshot": kind, "coins": len(coins), "calls": calls[0],
            "buckets": {r["id"]: r["n"] for r in rows}}
    if c["metas"]:
        try:
            out["metas"] = {"t": int(now), "rows": fetch_metas(s, c["metas_top"])}
            info["metas"] = len(out["metas"]["rows"])
        except Exception as e:  # noqa: BLE001 — narracje są dodatkiem, nie blokują koszyków
            log.warning("DexScreener: %s", e)
            info["metas_error"] = str(e)[:120]
    out["updated"] = int(now)
    st["last_t"] = int(now)
    log.info("Alty: zapis „%s”, %d coinów, %d zapytań, koszyki %s", kind, len(coins), calls[0], info["buckets"])
    return info
