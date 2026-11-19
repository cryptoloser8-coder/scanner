"""Pulpit — tabela „Gdzie warto zajrzeć” (poprawka 116).

Liczone w każdym skanie (main.py) i zapisywane do `pulpit.json` na gałęzi data; index.html tylko to wyświetla.
Do tabeli trafia to, co dziś odbiega od zwykłego zakresu albo zmieniło stan. Reguły (ustalone 19.11.2026, sprawdzone
na ostatnim roku: zwykle ok. 4 wierszy dziennie, w 9 dniach na 10 najwyżej 7):

  1. ruch w 7 dni — cena albo OI (BTC, ETH, TOTAL, watchlista) zmieniły się mocniej niż w 90% tygodni z 2 lat;
     stablecoiny: zmiana w 30 dni,
  2. skrajny poziom tła — MVRV-Z, Mayer, lewar altów, dominacja BTC, Alty/BTC, dolar, USA 10Y, szerokość rynku
     w dolnych albo górnych 10% zakresu z 2 lat,
  3. likwidacje z 24 h co najmniej 1,5× większe od zwykłego dnia (mediana z 90 dni),
  4. funding ponad 20% rocznie w którąkolwiek stronę,
  5. zmiana stanu — lampka Altsezonu świeci albo właśnie zgasła; BTC, ETH lub coin z watchlisty przeciął EMA200.

Jeden wiersz na temat: gdy spada cały rynek, ceny wszystkich coinów są w jednym wierszu („BTC −14,6% w 7 dni”
+ pozostałe w opisie), tak samo OI, likwidacje i funding. Zmiana znaku fundingu świadomie pominięta (przy zerze
przeskakuje co chwilę). To, co jest w zwykłym zakresie, nie jest pokazywane.

„Nowe” = wiersza nie było w tabeli 24 h temu. Pamięć w state.json → pulse: {klucz: {"since", "last"}}; wiersz, który
zniknął na krócej niż 48 h i wrócił, zachowuje datę „od kiedy” (bez migania przy progu). Pierwszy skan po wgraniu
zapamiętuje stan po cichu (nic nie jest „nowe”).

Ustawienia (config.yaml, wszystkie opcjonalne):
  pulpit: {enabled: true, move_pct: [10, 90], level_pct: [10, 90], liq_x: 1.5, fund_abs: 20, new_hours: 24}
"""
import logging
import re
import statistics

log = logging.getLogger("pulse")

HOUR, DAY = 3600, 86400
FILE = "pulpit.json"
DEFAULTS = {"enabled": True, "move_pct": [10, 90], "level_pct": [10, 90], "liq_x": 1.5, "fund_abs": 20, "new_hours": 24,
            "history_days": 730, "min_points": 300, "keep_hours": 48, "ema_cross_days": 2, "lamp_off_days": 3}
NB = " "

# poziomy tła: seria → (krótka nazwa, zakładka, liczba miejsc po przecinku, przyrostek, serie do linku w oi.html)
LEVELS = [
    ("mvrvz_btc", "MVRV-Z BTC", "oi", 2, "", "px_btc,mvrvz_btc"),
    ("mayer_btc", "Mayer BTC", "oi", 2, "", "px_btc,mayer_btc"),
    ("oi_others_vs_btc", "Lewar altów", "alt", 3, "×", None),
    ("btc_d", "Dominacja BTC", "oi", 1, "%", "btc_d"),
    ("alts_vs_btc", "Alty/BTC", "alt", 3, "", None),
    ("dxy", "Dolar (DXY)", "oi", 1, "", "dxy"),
    ("us10y", "USA 10Y", "oi", 2, "%", "us10y"),
]


def settings(cfg):
    s = dict(DEFAULTS)
    s.update({k: v for k, v in ((cfg or {}).get("pulpit") or {}).items() if v is not None})
    return s


# ── zapis liczb (po polsku, jak na stronach) ──
def num(v, d=1):
    s = f"{abs(v):,.{d}f}".replace(",", NB).replace(".", ",")
    return ("−" if v < 0 else "") + s


def pct(v, d=1):
    return ("+" if v > 0 else "−" if v < 0 else "") + num(abs(v), d) + "%"


def usd(v):
    a = abs(v)
    s = "−" if v < 0 else ""
    if a >= 1e12:
        return f"{s}${num(a / 1e12, 2)}T"
    if a >= 1e9:
        return f"{s}${num(a / 1e9, 2)}B"
    if a >= 1e6:
        return f"{s}${num(a / 1e6, 1)}M"
    if a >= 1e3:
        return f"{s}${num(a / 1e3, 0)}K"
    return f"{s}${num(a, 0)}"


def price(v):
    a = abs(v)
    if a >= 100:
        return "$" + num(v, 0)
    if a >= 1:
        return "$" + num(v, 2)
    return "$" + f"{v:.4g}".replace(".", ",")


def dm(t):
    import time as _t
    return _t.strftime("%d.%m", _t.gmtime(t))


def share(p):
    """„tylko w 6% dni” / „w mniej niż 1% dni” — nigdy 0%."""
    return "w mniej niż 1% dni" if p < 1 else f"tylko w {p:.0f}% dni"


def minus(text):
    """Zwykły minus przed liczbą → prawdziwy (teksty lampek z lamps.py)."""
    return re.sub(r"(?<![\w,.])-(?=\d)", "−", text)


# ── dane ──
def daily(store, sid):
    return store.series["1d"].get(sid) or {}


def now_and_before(store, sid, days):
    """→ (t, wartość teraz, wartość sprzed `days` dni) albo None."""
    last = store.latest(sid)
    if not last:
        return None
    t, v = last
    before = store.value_at(sid, t - days * DAY, "1h", tolerance=3 * HOUR)
    if before is None:
        before = store.value_at(sid, t - days * DAY, "1d", tolerance=2 * DAY)
    return (t, v, before) if before else None


def change_rank(series, days, t_end, hist_days, min_points, value):
    """Ile % zmian `days`-dniowych z ostatnich `hist_days` dni było mniejszych lub równych `value` (None = za mało danych)."""
    vals = []
    for t, v in series.items():
        if t_end - hist_days * DAY <= t < t_end - t_end % DAY:
            b = series.get(t - days * DAY)
            if b:
                vals.append((v / b - 1) * 100)
    if len(vals) < min_points:
        return None
    return sum(1 for x in vals if x <= value) / len(vals) * 100


def level_rank(series, t_end, hist_days, min_points, value):
    vals = [v for t, v in series.items() if t_end - hist_days * DAY <= t < t_end - t_end % DAY]
    if len(vals) < min_points:
        return None
    return sum(1 for x in vals if x <= value) / len(vals) * 100, min(vals), max(vals)


def coin_of(sid):
    return sid.split("_", 1)[1].upper() if "_" in sid else sid.upper()


# ── reguły ──
def moves(store, s, sids, kind):
    """Nietypowy ruch w 7 dni → [(odległość od środka, sid, zmiana %, ranga, wartość teraz)]."""
    lo, hi = s["move_pct"]
    out = []
    for sid in sids:
        nb = now_and_before(store, sid, 7)
        if not nb:
            continue
        t, v, before = nb
        ch = (v / before - 1) * 100
        r = change_rank(daily(store, sid), 7, t, s["history_days"], s["min_points"], ch)
        if r is not None and (r <= lo or r >= hi):
            out.append((abs(r - 50), sid, ch, r, v))
    return sorted(out, key=lambda x: (-round(x[0]), sids.index(x[1])))      # przy remisie kolejność listy: BTC, ETH, …


def rank_txt(r, what="tydzień"):
    if r <= 50:
        return f"Mocniejszy spadek {share(r)} z 2 lat"
    return f"Mocniejszy wzrost {share(100 - r)} z 2 lat"


def row_prices(store, s, watch):
    sids = ["px_btc", "px_eth", "total"] + [f"px_{w.lower()}" for w in watch]
    m = moves(store, s, sids, "px")
    if not m:
        return None
    name = lambda sid: "TOTAL" if sid == "total" else coin_of(sid)      # noqa: E731
    val = lambda sid, v: usd(v) if sid == "total" else price(v)         # noqa: E731
    _, sid, ch, r, v = m[0]
    rest = " · ".join(f"{name(x[1])} {pct(x[2])}" for x in m[1:])
    return {"key": "ceny", "tab": "oi", "href": f"oi.html#s={sid}&m=val&r=1d&z=365",
            "title": f"{name(sid)} {pct(ch)} w 7 dni", "detail": f"{val(sid, v)}" + (f" · też: {rest}" if rest else ""),
            "hist": rank_txt(r), "score": m[0][0]}


def row_oi(store, s, watch):
    sids = ["oi_total", "oi_btc", "oi_eth", "oi_others"] + [f"oi_{w.lower()}" for w in watch]
    m = moves(store, s, sids, "oi")
    if not m:
        return None
    m.sort(key=lambda x: (x[1] != "oi_total", -x[0]))             # OI łącznie na czele, jeśli jest
    name = lambda sid: "łącznie" if sid == "oi_total" else coin_of(sid)      # noqa: E731
    _, sid, ch, r, v = m[0]
    rest = " · ".join(f"{name(x[1])} {pct(x[2])}" for x in m[1:])
    title = f"Open interest {pct(ch)} w 7 dni" if sid == "oi_total" else f"Open interest {coin_of(sid)} {pct(ch)} w 7 dni"
    return {"key": "oi", "tab": "oi", "href": f"oi.html#s={sid}&m=val&r=1d&z=365", "title": title,
            "detail": usd(v) + (f" · też: {rest}" if rest else ""), "hist": rank_txt(r), "score": m[0][0]}


def row_stable(store, s):
    nb = now_and_before(store, "stable_mcap", 30)
    if not nb:
        return None
    t, v, before = nb
    ch = (v / before - 1) * 100
    r = change_rank(daily(store, "stable_mcap"), 30, t, s["history_days"], s["min_points"], ch)
    lo, hi = s["move_pct"]
    if r is None or lo < r < hi:
        return None
    return {"key": "stable", "tab": "oi", "href": "oi.html#s=stable_mcap&m=val&r=1d&z=365",
            "title": f"Stablecoiny {pct(ch)} w 30 dni", "detail": f"{usd(v)} · 30 dni temu {usd(before)}",
            "hist": rank_txt(r).replace("Mocniejszy", "Większy"), "score": abs(r - 50)}


def rows_levels(store, s, breadth=None):
    lo, hi = s["level_pct"]
    out = []
    items = [(sid, nm, tab, d, suf, link, daily(store, sid)) for sid, nm, tab, d, suf, link in LEVELS]
    if breadth:
        items.append(("breadth", "Szerokość rynku", "ema", 0, "% coinów nad EMA200", None, {int(x[0]): x[1] for x in breadth}))
    for sid, nm, tab, d, suf, link, ser in items:
        if not ser:
            continue
        t = max(ser)
        v = ser[t]
        if sid != "breadth":
            last = store.latest(sid)
            if last and last[0] >= t:
                t, v = last
        got = level_rank(ser, t, s["history_days"], s["min_points"], v)
        if not got:
            continue
        r, mn, mx = got
        if lo < r < hi:
            continue
        f = lambda x: num(x, d) + suf                                   # noqa: E731
        before = None
        for back in range(30, 36):
            before = ser.get(t - t % DAY - back * DAY)
            if before is not None:
                break
        low = r <= 50
        hist = (f"Niżej {share(r)} z 2 lat (najniżej {num(mn, d)})" if low
                else f"Wyżej {share(100 - r)} z 2 lat (najwyżej {num(mx, d)})")
        href = {"alt": "alt.html", "ema": "ema.html"}.get(tab) or f"oi.html#s={link}&m=val&r=1d&z=1095"
        out.append({"key": f"poziom:{sid}", "tab": tab, "href": href, "title": f"{nm} {f(v)} — {'nisko' if low else 'wysoko'}",
                    "detail": f"30 dni temu {f(before)}" if before is not None else "", "hist": hist, "score": abs(r - 50)})
    return out


def row_liq(store, s, watch):
    import alerts
    best = []
    for g in ["total", "btc", "eth", "others"] + [w.lower() for w in watch]:
        lo, _ = alerts.window_sum(store, f"liq_{g}_long", 24)
        sh, _ = alerts.window_sum(store, f"liq_{g}_short", 24)
        if lo is None or sh is None or lo + sh <= 0:
            continue
        dl, ds = daily(store, f"liq_{g}_long"), daily(store, f"liq_{g}_short")
        t = max(dl) if dl else 0
        hist = [dl[u] + ds.get(u, 0) for u in dl if t - 90 * DAY <= u < t]
        if len(hist) < 60:
            continue
        med = statistics.median(hist)
        if med > 0 and (lo + sh) / med >= float(s["liq_x"]):
            best.append(((lo + sh) / med, g, lo, sh))
    if not best:
        return None
    best.sort(key=lambda x: (x[1] != "total", -x[0]))
    x, g, lo, sh = best[0]
    rest = " · ".join(f"{b[1].upper()} ×{num(b[0], 1)}" for b in best[1:])
    nm = "łącznie" if g == "total" else g.upper()
    return {"key": "likwidacje", "tab": "liq", "href": f"liq.html#a={g}&i=1h&z=1w",
            "title": f"Likwidacje {nm} {usd(lo + sh)} w 24 h",
            "detail": f"Longi {usd(lo)} ({lo / (lo + sh) * 100:.0f}%) · shorty {usd(sh)}" + (f" · też: {rest}" if rest else ""),
            "hist": f"×{num(x, 1)} zwykłego dnia (mediana z 90 dni)", "score": min(50, 30 + x * 5)}


def row_funding(store, s, watch):
    hot = []
    for g in ["btc", "eth", "others"] + [w.lower() for w in watch]:
        last = store.latest(f"fund_{g}")
        if last and abs(last[1]) >= float(s["fund_abs"]):
            hot.append((abs(last[1]), g, last[1]))
    if not hot:
        return None
    hot.sort(reverse=True)
    nm = lambda g: "altów" if g == "others" else g.upper()               # noqa: E731
    _, g, v = hot[0]
    rest = " · ".join(f"{nm(h[1])} {pct(h[2])}" for h in hot[1:])
    who = "longi płacą shortom" if v > 0 else "shorty płacą longom"
    return {"key": "funding", "tab": "liq", "href": f"liq.html#a={g}&i=1h&z=1w&f=1&fs=fund_{g}",
            "title": f"Funding {nm(g)} {pct(v)} rocznie", "detail": who + (f" · też: {rest}" if rest else ""),
            "hist": f"Próg: {num(float(s['fund_abs']), 0)}% rocznie w którąkolwiek stronę", "score": min(50, 25 + hot[0][0] / 4)}


def rows_lamps(lamps_res, cfg, s, now):
    """Lampki: świeci → wiersz z prawdziwą datą zapalenia; zgasła w ostatnich dniach → wiersz „zgasła”."""
    out = []
    if not lamps_res or not lamps_res.get("lamps"):
        return out
    try:
        import lamps as LP
        c = LP.config(cfg)
    except Exception:  # noqa: BLE001
        return out
    for k in LP.LAMPS:
        info = lamps_res["lamps"].get(k)
        if not info:
            continue
        name = info.get("name") or LP.NAME.get(k, k)
        if info.get("on"):
            lvl = info.get("level") or 1
            txt = re.sub(r"<[^>]+>", "", LP.describe(k, info, c, lvl))
            txt = re.sub(r"^\W+\s*", "", txt)                           # bez ikony z przodu
            txt = txt.split(": ", 1)[1] if ": " in txt and txt.split(": ", 1)[0].lower().startswith(name.lower()[:6]) else txt
            st = (info.get("stats") or [])
            stat = LP._stat_txt(k, st[lvl - 1] if lvl - 1 < len(st) else None).strip()
            out.append({"key": f"lampka:{k}", "tab": "alt", "href": "alt.html", "title": f"Lampka {name} świeci",
                        "detail": minus(txt[:1].upper() + txt[1:]),
                        "hist": minus(stat.replace("Historycznie 30 dni po zapaleniu alty", "Po zapaleniu alty 30 dni później")
                                      .replace(" (historia, nie prognoza).", "")),
                        "score": 60, "since": info.get("since"), "lamp": True})
        elif info.get("since") is None:
            ep = (info.get("episodes") or [])[-1:] or None
            if ep and now - ep[0][1] <= (c.get("gap_days", 7) + int(s["lamp_off_days"])) * DAY:
                out.append({"key": f"lampka-off:{k}", "tab": "alt", "href": "alt.html", "title": f"Lampka {name} zgasła",
                            "detail": f"Świeciła {dm(ep[0][0])}–{dm(ep[0][1])} ({(ep[0][1] - ep[0][0]) // DAY + 1} dni)",
                            "hist": "", "score": 55, "since": ep[0][1] + c.get("gap_days", 7) * DAY, "lamp": True})
    return out


def row_ema(ema, s, watch, now):
    """BTC, ETH i watchlista: przecięcie EMA200 na zamknięciu dnia w ostatnich dniach."""
    if not ema or not ema.get("coins"):
        return None
    want = ["BTC", "ETH"] + [w.upper() for w in watch]
    hits = []
    for c in ema["coins"]:
        if c.get("s") in want and c.get("cross_t") and now - c["cross_t"] <= (int(s["ema_cross_days"]) + 1) * DAY:
            hits.append((want.index(c["s"]), c))
    if not hits:
        return None
    hits.sort(key=lambda x: x[0])
    c = hits[0][1]
    word = lambda x: "w górę" if (x.get("side") or 0) > 0 else "w dół"   # noqa: E731
    rest = " · ".join(f"{h[1]['s']} {word(h[1])}" for h in hits[1:])
    period = ema.get("period", 200)
    return {"key": "ema", "tab": "ema", "href": f"ema.html#c={c['s']}",
            "title": f"{c['s']} przeciął EMA{period} {word(c)}",
            "detail": f"Cena {price(c['p'])} · EMA{period} {price(c['e'])} ({pct(c['d'], 1)})" + (f" · też: {rest}" if rest else ""),
            "hist": f"Zamknięcie dnia {dm(c['cross_t'])} po drugiej stronie średniej", "score": 58}


# ── całość ──
def build(store, cfg, now, lamps_res=None, ema=None):
    """→ {"updated", "rows": [...]}; aktualizuje pamięć w store.state["pulse"]."""
    s = settings(cfg)
    watch = [str(w) for w in (cfg or {}).get("watchlist") or []]
    rows = []
    for fn, args in ((row_prices, (store, s, watch)), (row_oi, (store, s, watch)), (row_stable, (store, s)),
                     (row_liq, (store, s, watch)), (row_funding, (store, s, watch)), (row_ema, (ema, s, watch, now))):
        try:
            r = fn(*args)
            if r:
                rows.append(r)
        except Exception:  # noqa: BLE001 — jeden temat nie może zepsuć reszty
            log.exception("Pulpit: %s", fn.__name__)
    for fn, args in ((rows_levels, (store, s, (ema or {}).get("breadth"))), (rows_lamps, (lamps_res, cfg, s, now))):
        try:
            rows += fn(*args)
        except Exception:  # noqa: BLE001
            log.exception("Pulpit: %s", fn.__name__)

    first = "pulse" not in store.state
    mem = store.state.setdefault("pulse", {})
    new_s, keep_s = float(s["new_hours"]) * HOUR, float(s["keep_hours"]) * HOUR
    for r in rows:
        m = mem.get(r["key"])
        if not m:
            m = {"since": now, "armed": True} if first else {"since": now}
        m["last"] = now
        mem[r["key"]] = m
        lamp_since = r.pop("since", None)
        r["since"] = int(lamp_since or m["since"])
        r["new"] = (not m.get("armed")) and now - (lamp_since or m["since"]) < new_s
        r.pop("lamp", None)
    for k in [k for k, m in mem.items() if now - m.get("last", 0) > keep_s]:
        del mem[k]
    rows.sort(key=lambda r: (not r["new"], -r.pop("score", 0)))
    return {"updated": int(now), "rules": {k: s[k] for k in ("move_pct", "level_pct", "liq_x", "fund_abs", "new_hours")}, "rows": rows}
