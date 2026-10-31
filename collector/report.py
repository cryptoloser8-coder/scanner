"""Reports: build a report from the `data` and `ema` branches, publish it on the `reports` branch.

  python collector/report.py make   --data DIR --ema DIR --out DIR [--kind test]
  python collector/report.py notify --out DIR [--page URL]

All numbers are computed here (code); the page only renders them. A future AI comment
goes into a "text" block and only interprets the facts that are already in the file.

reports branch:
  index.json          {"updated": ts, "reports": [{id, kind, title, created, summary}, ...]}  newest first
  reports/<id>.json   {id, kind, title, created, summary, sources, blocks: [...]}

Blocks (generic, rendered by raporty.html — the report layout lives only in this file):
  {"type": "text",  "title", "text"}
  {"type": "facts", "title", "items": [{"label", "value", "sub", "zone", "note"}]}   zone: green|yellow|red|None
  {"type": "chart", "title", "note", "log", "range" (optional [min, max]), "series": [{"name", "color", "fmt", "scale", "data": [[t, v], ...]}]}
  {"type": "table", "title", "note", "cols": [...], "rows": [[...], ...], "plain" (optional: no +/− colours)}
  {"type": "section", "title"}                                       — section heading
  any block: optional "desc" — plain-language explanation shown above the content (bigger font than "note")
  {"type": "ranges", "title", "note", "items": [{"label", "value", "sub", "pos" 0–100, "min", "max",
                                                 "marks": [{"pos", "label", "kind"}], "note"}]}  — range bars
  {"type": "bars", "title", "note", "rows": [{"label", "long", "short", "text", "current"}],
                   "parts": [{"key", "name", "color"}], "line": {"value", "label"}}         — horizontal stacked bars
  chart: optional "lines": [{"value", "label", "color"}] — horizontal levels

Layout v2 (31.10.2026): Rynek (range bars) → Alty (table vs past peaks, OI OTHERS/OI BTC and Alty/BTC with levels,
OI OTHERS + OI BTC, market breadth) → Derywaty (OI vs price, funding bars) → Likwidacje (7 days) → EMA200 (coins near it).
Thresholds and levels: config.yaml → reports: (see LAYOUT).
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alerts  # noqa: E402  (fmt_value, Telegram)
from store import _write  # noqa: E402

log = logging.getLogger("report")

HOUR = 3600
DAY = 86400
KIND_TITLES = {"test": "Raport testowy", "morning": "Raport poranny", "evening": "Raport wieczorny (po sesji w USA)",
               "daily": "Raport dzienny", "manual": "Raport na żądanie"}
DEFAULTS = {"notify": True, "keep": 120,
            "page_url": "https://cryptoloser8-coder.github.io/scanner/raporty.html"}


# ── helpers ──────────────────────────────────────────────────
def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def utc(ts, fmt="%d.%m.%Y %H:%M UTC"):
    return datetime.fromtimestamp(ts, timezone.utc).strftime(fmt)


def pl_time(ts, fmt="%d.%m.%Y %H:%M"):
    """Polish local time (like the schedule and the bot)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, ZoneInfo("Europe/Warsaw")).strftime(fmt)
    except Exception:  # noqa: BLE001
        return utc(ts, fmt + " UTC")


def at(pts, t, tolerance):
    """Value of the last point at/before t, if it is not older than tolerance."""
    best = None
    for pt in pts:
        if pt[0] <= t:
            best = pt
        else:
            break
    if best is None or t - best[0] > tolerance:
        return None
    return best[1]


def pct_change(now, before):
    if now is None or before in (None, 0):
        return None
    return (now / before - 1) * 100


def fmt_chg(ch, unit="%"):
    if ch is None:
        return "—"
    arrow = "▲" if ch > 0 else ("▼" if ch < 0 else "•")
    return f"{arrow}{ch:+.2f}{unit}" if unit.strip() == "pp" else f"{arrow}{ch:+.1f}{unit}"


def fmt_price(v):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 100:
        return f"${v:,.0f}"
    if a >= 1:
        return f"${v:,.2f}"
    return "$" + f"{v:.4g}"


def fmt_val(v, group):
    return fmt_price(v) if group == "price" else alerts.fmt_value(v, group)


def percentile_rank(values, v):
    """Share of values ≤ v, in % (0–100)."""
    if not values or v is None:
        return None
    return 100.0 * sum(1 for x in values if x <= v) / len(values)


def zone_of(v, zones):
    if v is None or not zones:
        return None
    return "red" if v >= zones["red"] else ("yellow" if v >= zones["yellow"] else "green")


class Data:
    """Series from the data branch: 1h + 1d (main and liq_ files), sorted [[t, v], ...]."""

    def __init__(self, data_dir):
        self.meta = _read(os.path.join(data_dir, "meta.json"), {}) or {}
        self.catalog = self.meta.get("catalog", {})
        self.res = {"1h": {}, "1d": {}}
        self.updated = 0
        for res in self.res:
            for prefix in ("", "liq_"):
                d = _read(os.path.join(data_dir, f"{prefix}{res}.json"), {}) or {}
                self.updated = max(self.updated, d.get("updated") or 0)
                for sid, pts in (d.get("series") or {}).items():
                    self.res[res][sid] = sorted(pts)

    def pts(self, res, sid):
        return self.res[res].get(sid) or []

    def latest(self, sid):
        for res in ("1h", "1d"):
            p = self.pts(res, sid)
            if p:
                return p[-1]
        return None

    def ago(self, sid, now_t, seconds):
        """Value `seconds` before now_t: hourly data if it reaches that far, else daily."""
        v = at(self.pts("1h", sid), now_t - seconds, 3 * HOUR)
        if v is None:
            v = at(self.pts("1d", sid), now_t - seconds, 2 * DAY)
        return v

    def group(self, sid):
        return (self.catalog.get(sid) or {}).get("group", "")

    def name(self, sid):
        return (self.catalog.get(sid) or {}).get("name", sid)

    def color(self, sid, default="#888"):
        return (self.catalog.get(sid) or {}).get("color", default)


# ── blocks ───────────────────────────────────────────────────
def fact_series(d, sid, label=None, extra_note=""):
    """Value + 24h / 7d change of one series from the catalogue."""
    last = d.latest(sid)
    if not last:
        return {"label": label or d.name(sid), "value": "—", "sub": "brak danych", "zone": None, "note": ""}
    t, v = last
    g = d.group(sid)
    diff = g in ("pct", "fund")          # percentages: change in percentage points
    unit = " pp" if diff else "%"

    def chg(seconds):
        before = d.ago(sid, t, seconds)
        if before is None:
            return None
        return (v - before) if diff else pct_change(v, before)

    return {"label": label or d.name(sid), "value": fmt_val(v, g),
            "sub": f"24h {fmt_chg(chg(DAY), unit)} · 7D {fmt_chg(chg(7 * DAY), unit)}",
            "zone": zone_of(v, (d.catalog.get(sid) or {}).get("zones")),
            "note": extra_note or (d.catalog.get(sid) or {}).get("desc", "")}


def fact_history(d, sid, years=2):
    """Value + where it sits in its own history (max, percentile of the last N years)."""
    f = fact_series(d, sid)
    daily = d.pts("1d", sid)
    last = d.latest(sid)
    if not daily or not last:
        return f
    t_max, v_max = max(daily, key=lambda p: p[1])
    recent = [p[1] for p in daily if p[0] >= last[0] - years * 365 * DAY]
    pr = percentile_rank(recent, last[1])
    f["sub"] += f" · maks. {fmt_val(v_max, d.group(sid))} ({utc(t_max, '%m.%Y')})"
    if pr is not None:
        f["sub"] += f" · wyżej niż {pr:.0f}% dni z {years} lat"
    return f


def liq_24h(d):
    hourly = bool(d.pts("1h", "liq_total_long"))
    res = "1h" if hourly else "1d"
    p = d.pts(res, "liq_total_long")
    if not p:
        return None
    t_now = p[-1][0]

    def s(sid):   # last 24 hourly candles, or the last daily candle
        pts = d.pts(res, sid)
        return sum(v for t, v in pts if t > t_now - DAY) if hourly else sum(v for t, v in pts if t == t_now)

    long_, short_ = s("liq_total_long"), s("liq_total_short")
    tot = long_ + short_
    share = (100 * long_ / tot) if tot else 0
    return {"label": "Likwidacje 24h (TOTAL)", "value": alerts.fmt_value(tot, "liq"),
            "sub": f"long {alerts.fmt_value(long_, 'liq')} ({share:.0f}%) · short {alerts.fmt_value(short_, 'liq')}",
            "zone": None,
            "note": "Suma z Binance, Bybit i OKX (bez Hyperliquid) — dolne oszacowanie."}


def chart_block(d, title, sids, days=None, note="", log_scale=False, res="1d", colors=None):
    series = []
    for i, sid in enumerate(sids):
        p = d.pts(res, sid)
        if days and p:
            p = [x for x in p if x[0] >= p[-1][0] - days * DAY]
        if not p:
            continue
        series.append({"name": d.name(sid), "color": (colors or {}).get(sid) or d.color(sid), "fmt": d.group(sid),
                       "scale": "right" if i == 0 else "left", "data": p})
    return {"type": "chart", "title": title, "note": note, "log": log_scale, "series": series}


def breadth_peaks_note(breadth, level=90, days=730):
    """Months with breadth ≥ level inside the chart window + years with such readings in the whole history."""
    last_t = breadth[-1][0]
    months, years = {}, set()
    for t, v, *_ in breadth:
        if v >= level:
            years.add(utc(t, "%Y"))
            if t >= last_t - days * DAY:
                m = utc(t, "%m.%Y")
                months[m] = max(months.get(m, 0), v)
    keys = sorted(months, key=lambda m: (m[3:], m[:2]))
    win = (", ".join(f"{m} (maks. {months[m]:.1f}%)" for m in keys) if keys else "brak")
    hist = ", ".join(sorted(years)) if years else "brak"
    return (f"Odczyty ≥ {level}% na wykresie: {win}. Lata z takim odczytem w całej historii "
            f"(od {utc(breadth[0][0], '%m.%Y')}): {hist}. "
            "Liczone tylko z coinów notowanych dziś, więc starsze lata są zawyżone.")


def history_note(d, sid):
    daily = d.pts("1d", sid)
    if not daily:
        return ""
    t_max, v_max = max(daily, key=lambda p: p[1])
    t_min, v_min = min(daily, key=lambda p: p[1])
    g = d.group(sid)
    return (f"Dane od {utc(daily[0][0], '%d.%m.%Y')}. Maks. {fmt_val(v_max, g)} ({utc(t_max, '%d.%m.%Y')}), "
            f"min. {fmt_val(v_min, g)} ({utc(t_min, '%d.%m.%Y')}).")


# ── layout settings (config.yaml → reports:) ────────────────
LAYOUT = {
    "range_years": 2,              # pasek zakresu w sekcji Rynek i przy fundingu
    "ema_near_pct": 3.0,           # EMA200: tylko coiny bliżej niż X% od średniej
    "ema_min_volume": 10e6,        # … z obrotem ≥ $ dziennie
    "ema_max_rows": 15,
    "oi_flat_pct": 1.0,            # OI i cena: zmiana poniżej X% = „bez zmian”
    "liq_days": 7,                 # likwidacje: ostatnie N pełnych dni
    "liq_big_pct": 90,             # linia „duży dzień” = percentyl z 2 lat
    "alts_ref_level": 1.0,         # kolumny tabeli altów: szczyty OI OTHERS/OI BTC ≥ poziom …
    "alts_ref_count": 3,           # … ostatnie N
    "alts_chart_from": "2020-01-01",
    "lines": {
        "oi_others_vs_btc": [[0.60, "strefa dołków"], [0.85, "górne 10% dni"],
                             [0.95, "szczyty 03.2024 i 07.2025"], [1.00, "zrównanie z BTC"]],
        "alts_vs_btc": [[0.28, "dołki 2025–2026"], [0.38, "szczyt 09.2025"], [0.47, "szczyty 12.2023 i 12.2024"]],
    },
}
NEUTRAL_FUNDING = 10.95        # 0,01% na 8 h w skali roku
LINE_COLORS = ["#4caf7d", "#ffc107", "#ff9800", "#e05252"]


def layout(cfg):
    out = dict(LAYOUT)
    out.update({k: v for k, v in (cfg or {}).items() if k in LAYOUT and v is not None})
    lines = dict(LAYOUT["lines"])
    lines.update((cfg or {}).get("lines") or {})
    out["lines"] = lines
    return out


# ── helpers for the sections ─────────────────────────────────
def daily_at(pts, t, tolerance=3 * DAY):
    return at(pts, t, tolerance)


def avg_days(pts, t, days):
    vals = [v for tt, v in pts if t - days * DAY < tt <= t]
    return sum(vals) / len(vals) if vals else None


def ratio_pts(d, sid, fn, *ids):
    """Daily series from the data branch, or computed from its parts (older data without the derived series)."""
    p = d.pts("1d", sid)
    if p:
        return p
    srcs = [dict(d.pts("1d", i)) for i in ids]
    out = []
    for t in sorted(set(srcs[0]).intersection(*srcs[1:])) if srcs and all(srcs) else []:
        try:
            v = fn(*(src[t] for src in srcs))
        except ZeroDivisionError:
            v = None
        if v is not None:
            out.append([t, v])
    return out


def alts_btc_pts(d):
    return ratio_pts(d, "alts_vs_btc", lambda a, t, t2: a / (t - t2) if t > t2 else None, "total3es", "total", "total2")


def local_peaks(pts, level, window_days=45):
    """Days that are the highest point within ±window and ≥ level."""
    out = []
    w = window_days * DAY
    for i, (t, v) in enumerate(pts):
        if v < level:
            continue
        lo = i
        while lo > 0 and pts[lo - 1][0] >= t - w:
            lo -= 1
        hi = i
        while hi + 1 < len(pts) and pts[hi + 1][0] <= t + w:
            hi += 1
        win = pts[lo:hi + 1]
        if v >= max(x[1] for x in win) and not any(x[1] == v and x[0] < t for x in win):
            out.append((t, v))
    return out


def breadth_series(ema):
    return [[b[0], b[1]] for b in (ema or {}).get("breadth") or []]


def breadth_now(ema):
    if ema and ema.get("total"):
        return 100 * ema["above"] / ema["total"]
    return None


def alts_refs(d, ema, L, now):
    """Reference moments for the alt table — all found in the data:
    the last N peaks of OI OTHERS/OI BTC ≥ level + the lowest point of the last 12 months.
    A peak with market breadth ≥ 90% that day is marked as an altseason."""
    oi = d.pts("1d", "oi_others_vs_btc")
    br = breadth_series(ema)
    if not oi:
        return [], None
    peaks = local_peaks(oi, float(L["alts_ref_level"]))
    alt_t = None
    for t, _ in peaks:
        b = daily_at(br, t)
        if b is not None and b >= 90:
            alt_t = t
    refs = []
    for t, _ in peaks[-int(L["alts_ref_count"]):]:
        b = daily_at(br, t)
        refs.append((t, f"szczyt {utc(t, '%d.%m.%Y')}" + (" (altseason)" if b is not None and b >= 90 else "")))
    if alt_t and all(t != alt_t for t, _ in refs):
        refs.insert(0, (alt_t, f"altseason {utc(alt_t, '%d.%m.%Y')}"))
    year = [p for p in oi if p[0] >= oi[-1][0] - 365 * DAY]
    if year:
        t_min = min(year, key=lambda p: p[1])[0]
        if all(t != t_min for t, _ in refs):
            refs.append((t_min, f"dno 12 mies. {utc(t_min, '%d.%m.%Y')}"))
    refs.sort()
    return refs, alt_t


def range_item(d, label, pts, v, group, desc, alt_t, years, sub="", marks=None, fmt=None):
    """One bar: where today's value sits between the min and max of the last `years` years."""
    fmt = fmt or (lambda x: fmt_val(x, group))
    if v is None or not pts:
        return {"label": label, "value": "—", "sub": "brak danych", "pos": None, "note": desc}
    t_end = pts[-1][0]
    win = [p for p in pts if p[0] >= t_end - years * 365 * DAY]
    lo = min(win, key=lambda p: p[1])
    hi = max(win, key=lambda p: p[1])
    vmin, vmax = min(lo[1], v), max(hi[1], v)
    span = (vmax - vmin) or 1

    def pos(x):
        return round(max(0.0, min(100.0, (x - vmin) / span * 100)), 1)
    mk = []
    for x, txt in (marks or []):
        if x is not None:
            mk.append({"pos": pos(x), "label": txt})
    if alt_t and alt_t >= win[0][0]:
        av = daily_at(pts, alt_t)
        if av is not None:
            mk.append({"pos": pos(av), "label": f"altseason {utc(alt_t, '%m.%Y')}: {fmt(av)}", "kind": "ref"})
    return {"label": label, "value": fmt(v), "sub": sub, "pos": pos(v), "marks": mk,
            "min": f"min. {fmt(lo[1])} ({utc(lo[0], '%m.%Y')})", "max": f"maks. {fmt(hi[1])} ({utc(hi[0], '%m.%Y')})",
            "note": desc}


def chg_text(v, before, diff=False):
    if v is None or before is None:
        return ""
    return fmt_chg((v - before) if diff else pct_change(v, before), " pp" if diff else "%")


# ── sections ─────────────────────────────────────────────────
MARKET = [
    ("total", "Cały rynek (TOTAL)", "Wielkość całego rynku krypto. Pokazuje, jak daleko jesteśmy od szczytu."),
    ("btc_d", "Udział BTC (BTC.D)", "Jaka część rynku to BTC. Rośnie = kapitał ucieka z altów do BTC, spada = płynie w alty."),
    ("stable_d", "Udział stablecoinów", "Ile rynku czeka w gotówce. Wysoko = strach i czekanie, nisko = wszyscy w ryzyku."),
    ("stable_mcap", "Kapitał w stablecoinach", "Pieniądze gotowe do zakupów. Rośnie = na rynek wchodzi nowy kapitał."),
]


def market_section(d, L, alt_t):
    items = []
    years = int(L["range_years"])
    for sid, label, desc in MARKET:
        last = d.latest(sid)
        daily = ratio_pts(d, sid, lambda t, tes: t - tes, "total", "totales") if sid == "stable_mcap" else d.pts("1d", sid)
        if sid == "stable_d" and not daily:
            daily = ratio_pts(d, sid, lambda t, tes: (t - tes) / t * 100, "total", "totales")
        v = last[1] if last else (daily[-1][1] if daily else None)
        g = d.group(sid) or ("pct" if sid.endswith("_d") else "mcap")
        sub = ""
        if v is not None and daily:
            sub = "7D " + chg_text(v, daily_at(daily, daily[-1][0] - 7 * DAY), diff=(g == "pct"))
            if sid == "total":
                ath = max(daily, key=lambda p: p[1])
                sub = f"{pct_change(v, ath[1]):+.0f}% od szczytu ({utc(ath[0], '%m.%Y')}) · " + sub
        items.append(range_item(d, label, daily, v, g, desc, alt_t, years, sub=sub))
    return [{"type": "section", "title": "Rynek"},
            {"type": "ranges", "title": "Gdzie jest rynek na tle ostatnich 2 lat", "items": items,
             "note": f"Pasek = zakres z ostatnich {years} lat (od minimum do maksimum). Kropka = dziś, "
                     "znacznik = dzień ostatniego altseasonu (wyznaczony z danych: szczyt OI OTHERS/OI BTC przy szerokości rynku ≥ 90%)."}]


def lines_for(L, sid):
    out = []
    for i, (v, label) in enumerate(L["lines"].get(sid) or []):
        out.append({"value": float(v), "label": str(label), "color": LINE_COLORS[i % len(LINE_COLORS)]})
    return out


def alts_section(d, ema, L, refs, now):
    blocks = [{"type": "section", "title": "Alty"}]
    oi = d.pts("1d", "oi_others_vs_btc")
    ab = alts_btc_pts(d)
    br = breadth_series(ema)
    fund = d.pts("1d", "fund_others")
    eb = d.pts("1d", "ethbtc")
    last_oi = d.latest("oi_others_vs_btc")
    last_eb = d.latest("ethbtc")
    rows_def = [
        ("Lewar: OI OTHERS / OI BTC", lambda t: daily_at(oi, t), last_oi[1] if last_oi else None, lambda x: f"{x:.3f}"),
        ("Kapitał: Alty / BTC", lambda t: daily_at(ab, t), ab[-1][1] if ab else None, lambda x: f"{x:.3f}"),
        ("Szerokość rynku (% nad EMA200)", lambda t: daily_at(br, t), breadth_now(ema), lambda x: f"{x:.0f}%"),
        ("Funding OTHERS (śr. 7 dni, rocznie)", lambda t: avg_days(fund, t, 7),
         avg_days(fund, fund[-1][0], 7) if fund else None, lambda x: f"{x:+.1f}%"),
        ("ETH / BTC", lambda t: daily_at(eb, t), last_eb[1] if last_eb else None, lambda x: f"{x:.4f}"),
    ]
    rows = []
    for name, at_t, today, f in rows_def:
        cells = [name, f(today) if today is not None else "—"]
        for t, _ in refs:
            x = at_t(t)
            cells.append(f(x) if x is not None else "—")
        rows.append(cells)
    if refs:
        blocks.append({"type": "table", "title": "Stan altów na tle poprzednich szczytów",
                       "cols": ["Wskaźnik", "Dziś"] + [lbl for _, lbl in refs], "rows": rows, "plain": True,
                       "desc": "Dzisiejsze wartości obok tych z ważnych momentów. W prawdziwym altseasonie wysoko jest wszystko naraz; "
                               "gdy wysoko jest tylko lewar, to raczej ostrzeżenie.",
                       "note": f"Kolumny wyznacza kod z danych: ostatnie szczyty OI OTHERS/OI BTC powyżej {L['alts_ref_level']:.2f} "
                               "i najniższy punkt z 12 miesięcy; „altseason” = szerokość rynku ≥ 90% tego dnia."})
    blocks.append(chart_block(d, "Lewar: OI OTHERS / OI BTC — cała historia", ["oi_others_vs_btc"],
                              note=history_note(d, "oi_others_vs_btc")))
    blocks[-1]["lines"] = lines_for(L, "oi_others_vs_btc")
    blocks[-1]["desc"] = ("Ile pozycji z dźwignią jest na altach (bez ETH) w porównaniu z BTC. Rośnie = lewar przenosi się na alty. "
                          "Czytaj razem z wykresem kapitału niżej: oba rosną = kapitał naprawdę płynie w alty; "
                          "rośnie tylko lewar = ruch na dźwigni, łatwo o kaskadę likwidacji (tak było we wrześniu 2025 i 2026).")
    since = int(datetime.strptime(str(L["alts_chart_from"]), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    abw = [p for p in ab if p[0] >= since]
    if abw:
        hi = max(ab, key=lambda p: p[1] if p[0] >= since else -1)
        blocks.append({"type": "chart", "title": f"Kapitał: Alty / BTC — od {utc(since, '%Y')}", "log": False,
                       "lines": lines_for(L, "alts_vs_btc"),
                       "desc": "Ile są warte alty (bez BTC, ETH i stablecoinów) w porównaniu z BTC — realne pieniądze, bez dźwigni. "
                               "Rośnie razem z lewarem wyżej = mocny sygnał; rośnie sam, bez lewara = spokojny napływ bez przegrzania.",
                       "note": f"Maks. na wykresie {hi[1]:.3f} ({utc(hi[0], '%d.%m.%Y')}). Każdy cykl kończył się niżej, "
                               "więc linie są z ostatnich lat.",
                       "series": [{"name": "Alty / BTC", "color": d.color("alts_vs_btc", "#26c6da"), "fmt": "ratio",
                                   "scale": "right", "data": abw}]})
    cb = chart_block(d, "OI OTHERS i OI BTC — w dolarach", ["oi_others", "oi_btc"])
    cb["desc"] = ("Te same dane co stosunek wyżej, ale osobno: widać, czy stosunek rośnie, bo alty dokładają pozycji, "
                  "czy dlatego, że z BTC pozycje schodzą.")
    for s in cb["series"]:
        s["scale"] = "right"
    blocks.append(cb)
    if br:
        last_t = br[-1][0]
        blocks.append({"type": "chart", "title": "Szerokość rynku — % coinów nad EMA200, 2 lata", "log": False,
                       "range": [0, 100], "lines": [{"value": 90, "label": "rozgrzanie altów", "color": "#e05252"}],
                       "desc": "Jaki odsetek coinów jest w trendzie wzrostowym (cena nad EMA200). Powyżej 90% = rynek altów rozgrzany, "
                               "tak było przy szczytach altów; blisko 0% = dno.",
                       "note": "Coiny Binance */USDT z co najmniej 300 dniami historii. " + breadth_peaks_note(ema["breadth"]),
                       "series": [{"name": "% nad EMA200", "color": "#ffc107", "fmt": "pct", "scale": "right",
                                   "data": [p for p in br if p[0] >= last_t - 730 * DAY]}]})
    return blocks


OI_CASES = {
    (1, 1): "nowe longi — wzrost wspierany lewarem",
    (-1, 1): "nowe shorty — gra na spadek",
    (0, 1): "lewar rośnie, cena stoi — budowanie pozycji",
    (1, -1): "zamykanie shortów — wzrost bez nowych kupujących",
    (-1, -1): "zamykanie longów — wypłukiwanie lewara",
    (0, -1): "lewar maleje, cena stoi",
    (1, 0): "cena rośnie bez zmiany lewara",
    (-1, 0): "cena spada bez zmiany lewara",
    (0, 0): "bez wyraźnych zmian",
}


def oi_case(px_ch, oi_coin_ch, flat):
    def sgn(x):
        return 0 if x is None or abs(x) < flat else (1 if x > 0 else -1)
    return OI_CASES[(sgn(px_ch), sgn(oi_coin_ch))]


def oi_price_rows(d, coin, flat):
    rows = []
    oi_sid, px_sid = f"oi_{coin.lower()}", f"px_{coin.lower()}"
    for label, res, sec in (("24 h", "1h", DAY), ("7 dni", "1d", 7 * DAY)):
        oi, px = d.pts(res, oi_sid), d.pts(res, px_sid)
        if not oi or not px:
            continue
        t = min(oi[-1][0], px[-1][0])
        tol = 3 * HOUR if res == "1h" else 2 * DAY
        o1, p1, o0, p0 = at(oi, t, tol), at(px, t, tol), at(oi, t - sec, tol), at(px, t - sec, tol)
        if None in (o1, p1, o0, p0) or not (o0 and p0 and p1):
            continue
        px_ch = pct_change(p1, p0)
        oi_usd = pct_change(o1, o0)
        oi_coin = ((o1 / p1) / (o0 / p0) - 1) * 100
        rows.append([coin, label, fmt_chg(px_ch), fmt_chg(oi_coin), fmt_chg(oi_usd), oi_case(px_ch, oi_coin, flat)])
    return rows


def derivatives_section(d, L, alt_t):
    flat = float(L["oi_flat_pct"])
    rows = oi_price_rows(d, "BTC", flat) + oi_price_rows(d, "ETH", flat)
    blocks = [{"type": "section", "title": "Derywaty"}]
    if rows:
        blocks.append({"type": "table", "title": "Open interest i cena — BTC i ETH",
                       "cols": ["Coin", "Okres", "Cena", "OI (w coinach)", "OI ($)", "Co to znaczy"], "rows": rows,
                       "desc": "Kto napędza ruch ceny. Cena ↑ + OI ↑ = nowe longi; cena ↓ + OI ↑ = nowe shorty; "
                               "cena ↑ + OI ↓ = zamykanie shortów; cena ↓ + OI ↓ = zamykanie longów.",
                       "note": "OI w coinach = OI w dolarach podzielone przez cenę — bez tego OI rósłby i spadał razem z ceną. "
                               f"Zmiana poniżej {flat:g}% = „bez zmian”."})
    years = int(L["range_years"])
    items = []
    for coin in ("BTC", "ETH"):
        sid = f"fund_{coin.lower()}"
        pts, last = d.pts("1d", sid), d.latest(sid)
        a7 = avg_days(pts, pts[-1][0], 7) if pts else None
        items.append(range_item(
            d, f"Funding {coin}", pts, last[1] if last else None, "fund",
            "Opłata między longami a shortami, w % rocznie. Dodatni = longi płacą shortom (przewaga longów), "
            "ujemny = shorty płacą longom (przewaga shortów, często blisko dołków). Neutralnie ok. 11%.",
            alt_t, years, sub=f"śr. 7 dni {a7:+.1f}%" if a7 is not None else "",
            marks=[(NEUTRAL_FUNDING, "neutralnie ~11%")], fmt=lambda x: f"{x:+.1f}%"))
    for it in items[1:]:
        it["note"] = ""                                  # one description for both coins
    blocks.append({"type": "ranges", "title": "Funding na tle ostatnich 2 lat", "items": items,
                   "note": "Pasek = zakres dziennych odczytów z ostatnich 2 lat. Szary znacznik = poziom neutralny."})
    return blocks


def liq_section(d, L):
    lg, sh = d.pts("1d", "liq_total_long"), dict(d.pts("1d", "liq_total_short"))
    if not lg:
        return []
    days = [(t, v, sh.get(t, 0.0)) for t, v in lg][:-1]          # last day is not finished
    since = days[-1][0] - 730 * DAY if days else 0
    tot2 = [lv + sv for t, lv, sv in days if t >= since]
    big = sorted(tot2)[min(len(tot2) - 1, int(len(tot2) * float(L["liq_big_pct"]) / 100))] if tot2 else None
    med = sorted(tot2)[len(tot2) // 2] if tot2 else None
    rows = []
    for t, lv, sv in days[-int(L["liq_days"]):]:
        rows.append({"label": utc(t, "%d.%m"), "long": lv, "short": sv})
    hl, hs = d.pts("1h", "liq_total_long"), d.pts("1h", "liq_total_short")
    if hl:
        t_now = hl[-1][0]
        rows.append({"label": "24 h", "long": sum(v for t, v in hl if t > t_now - DAY),
                     "short": sum(v for t, v in hs if t > t_now - DAY), "current": True})
    for r in rows:
        tot = r["long"] + r["short"]
        r["text"] = f"{alerts.fmt_value(tot, 'liq')} · {100 * r['long'] / tot:.0f}% long" if tot else "$0"
    return [{"type": "section", "title": "Likwidacje"},
            {"type": "bars", "title": f"Likwidacje — ostatnie {L['liq_days']} dni (doba UTC)", "rows": rows,
             "parts": [{"key": "long", "name": "longi", "color": "#e05252"}, {"key": "short", "name": "shorty", "color": "#4caf7d"}],
             "line": {"value": big, "label": f"duży dzień: {alerts.fmt_value(big, 'liq')} (więcej tylko w {100 - L['liq_big_pct']:.0f}% dni z 2 lat)"} if big else None,
             "desc": "Duże likwidacje longów = kaskada w dół, wypłukanie lewara (często blisko lokalnych dołków); "
                     "duże likwidacje shortów = short squeeze.",
             "note": f"Mediana dnia z 2 lat: {alerts.fmt_value(med, 'liq')}. "
                     "Suma z Binance, Bybit i OKX (bez Hyperliquid) — dolne oszacowanie."}]


def ema_near_section(ema, L):
    near_pct, min_vol = float(L["ema_near_pct"]), float(L["ema_min_volume"])
    blocks = [{"type": "section", "title": "EMA200 — coiny blisko średniej"}]
    if not ema:
        return blocks + [{"type": "text", "title": "", "text": "Brak danych z gałęzi ema."}]
    coins = [c for c in ema.get("coins") or [] if abs(c.get("d", 99)) <= near_pct and (c.get("vol") or 0) >= min_vol]
    coins.sort(key=lambda c: abs(c["d"]))
    vol_txt = alerts.fmt_value(min_vol, "liq")
    if not coins:
        return blocks + [{"type": "text", "title": "",
                          "text": f"Żaden coin z obrotem ≥ {vol_txt} dziennie nie jest bliżej niż {near_pct:g}% od EMA200."}]
    rows = []
    for c in coins[:int(L["ema_max_rows"])]:
        side = "nad" if c.get("side", 0) > 0 else "pod"
        rows.append([c["s"], fmt_price(c["p"]), fmt_price(c["e"]), f"{c['d']:+.2f}%", side,
                     str(c.get("since", "?")), alerts.fmt_value(c.get("vol"), "liq")])
    more = len(coins) - len(rows)
    return blocks + [{"type": "table", "title": f"Bliżej niż {near_pct:g}% od EMA200, obrót ≥ {vol_txt} dziennie",
                      "cols": ["Coin", "Cena", "EMA200", "Odległość", "Strona", "Dni po tej stronie", "Obrót/dzień"],
                      "rows": rows,
                      "desc": "Coiny, przy których cena jest tuż przy EMA200 — tu decyduje się, czy trend się odwraca. "
                              "Coiny daleko od średniej pomijamy.",
                      "note": "Binance spot */USDT, świeca dzienna; odległość z aktualnej ceny. „Dni po tej stronie” = od ostatniego "
                              "przecięcia na zamknięciu dnia (1–2 = świeże przecięcie). Obrót = średni dzienny w USDT."
                              + (f" I jeszcze {more} — zakładka EMA200." if more > 0 else "")}]


def build(data_dir, ema_dir, kind="test", now=None, cfg=None):
    now = int(now or time.time())
    L = layout(cfg)
    d = Data(data_dir)
    ema = _read(os.path.join(ema_dir, "ema.json")) if ema_dir else None

    blocks = []
    warn = []
    if not d.updated:
        warn.append("brak danych z gałęzi data (OI, TOTAL, likwidacje)")
    elif now - d.updated > 4 * HOUR:
        warn.append(f"dane OI/TOTAL sprzed {(now - d.updated) / HOUR:.0f} h")
    ema_upd = (ema or {}).get("updated") or 0
    if not ema_upd:
        warn.append("brak danych z gałęzi ema (EMA200)")
    elif now - ema_upd > 2 * HOUR:
        warn.append(f"dane EMA sprzed {(now - ema_upd) / HOUR:.0f} h")

    if kind == "test":
        blocks.append({"type": "text", "title": "O tym raporcie",
                       "text": "Raport testowy. Liczby i oceny liczy kod z aktualnych danych; układ dopracowujemy stopniowo. "
                               "Komentarz AI pojawi się później."})
    if warn:
        blocks.append({"type": "text", "title": "Uwaga", "text": "Nieświeże dane: " + "; ".join(warn) + "."})

    refs, alt_t = alts_refs(d, ema, L, now)
    if d.updated:
        blocks += market_section(d, L, alt_t)
        blocks += alts_section(d, ema, L, refs, now)
        blocks += derivatives_section(d, L, alt_t)
        blocks += liq_section(d, L)
    blocks += ema_near_section(ema, L)

    parts = []
    for sid in ("total", "btc_d", "oi_others_vs_btc"):
        last = d.latest(sid)
        if last:
            parts.append(f"{d.name(sid)} {fmt_val(last[1], d.group(sid))}")
    bn = breadth_now(ema)
    if bn is not None:
        parts.append(f"szerokość rynku {bn:.0f}%")
    summary = " · ".join(parts)

    return {"id": utc(now, "%Y%m%d-%H%M") + "-" + kind, "kind": kind, "layout": 2,
            "title": KIND_TITLES.get(kind, "Raport"), "created": now, "summary": summary,
            "sources": {"data_updated": d.updated or None, "ema_updated": ema_upd or None},
            "blocks": blocks}


# ── text version for AI agents (markdown) ───────────────────
SOURCES_MD = """## Źródła danych i metody
- Kapitalizacja i dominacje (TOTAL, TOTAL2, TOTAL3ES — alty bez BTC, ETH i stablecoinów, BTC.D, stablecoiny = TOTAL − TOTALES): indeksy CRYPTOCAP z TradingView (https://www.tradingview.com/symbols/CRYPTOCAP-TOTAL/), świece dzienne.
- ETH/BTC: para ETHBTC z Binance przez TradingView.
- Open interest, funding, likwidacje, ceny perpetuali BTC i ETH: Coinalyze (https://coinalyze.net) — suma z Binance, Bybit, OKX, Hyperliquid i Deribit; likwidacje tylko z Binance, Bybit i OKX (dolne oszacowanie). OI w USD; „OI w coinach” = OI w USD / cena.
- OTHERS w open interest = wszystkie śledzone coiny bez BTC i ETH (top coiny według OI).
- Funding: stawka ważona open interest, przeliczona na % w skali roku; ok. 11% rocznie = poziom neutralny (0,01% na 8 h).
- EMA200 i szerokość rynku: Binance spot (https://www.binance.com), pary */USDT, świece dzienne; EMA liczona jak ta.ema(200) w TradingView; szerokość rynku = odsetek coinów (z co najmniej 300 dniami historii, bez stablecoinów i tokenów opakowanych) z ceną nad EMA200. Historia szerokości liczona tylko z coinów notowanych dziś, więc starsze lata są zawyżone.
- Daty bez godziny = dzień UTC. Wszystkie liczby policzył program; raport nie zawiera interpretacji ani rekomendacji.
"""


def _md_cell(v):
    return str(v if v is not None else "—").replace("|", "/").replace("\n", " ")


def _md_table(cols, rows):
    out = ["| " + " | ".join(_md_cell(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(_md_cell(c) for c in r) + " |" for r in rows]
    return out


def _md_series(s, lines):
    """A chart series as numbers: today, earlier values, extremes, position vs the drawn levels."""
    pts = s.get("data") or []
    if not pts:
        return []
    g = s.get("fmt", "")
    t, v = pts[-1]
    f = lambda x: fmt_val(x, g)  # noqa: E731
    ago = []
    for days, label in ((7, "7 dni temu"), (30, "30 dni temu"), (90, "90 dni temu"), (365, "rok temu")):
        x = at(pts, t - days * DAY, 3 * DAY)
        if x is not None:
            ago.append(f"{label} {f(x)}")
    hi = max(pts, key=lambda p: p[1])
    lo = min(pts, key=lambda p: p[1])
    out = [f"- **{s.get('name')}**: dziś {f(v)} ({utc(t, '%d.%m.%Y')})" + (f"; {', '.join(ago)}" if ago else "") + ".",
           f"  Na wykresie (od {utc(pts[0][0], '%m.%Y')}): maks. {f(hi[1])} ({utc(hi[0], '%d.%m.%Y')}), "
           f"min. {f(lo[1])} ({utc(lo[0], '%d.%m.%Y')})."]
    if lines:
        below = [ln for ln in lines if v < ln["value"]]
        above = [ln for ln in lines if v >= ln["value"]]
        pos = []
        if above:
            pos.append(f"nad {f(max(above, key=lambda x: x['value'])['value'])}")
        if below:
            pos.append(f"pod {f(min(below, key=lambda x: x['value'])['value'])}")
        out.append("  Linie poziomów: " + "; ".join(f"{f(ln['value'])} = {ln['label']}" for ln in lines)
                   + (f". Dziś: {' i '.join(pos)}." if pos else "."))
    return out


def to_markdown(rep, page_url=""):
    """The whole report as plain markdown — to paste into any AI agent (charts turned into numbers)."""
    src = rep.get("sources") or {}
    L = [f"# {rep['title']} — {pl_time(rep['created'])} czasu polskiego ({utc(rep['created'])})", "",
         "Raport rynku kryptowalut z projektu Crypto Scanner. Same dane: wszystkie liczby policzył program z danych źródłowych "
         "(lista na końcu), bez interpretacji i rekomendacji. Opisy przy wskaźnikach mówią tylko, co wskaźnik mierzy i jak się go "
         "zwykle czyta. Zapis liczb: kropka dziesiętna, $ = USD, M = mln, B = mld, T = bln, pp = punkty procentowe, "
         "× = krotność, %/r = procent w skali roku.",
         f"Dane: OI/TOTAL/likwidacje z {pl_time(src['data_updated']) if src.get('data_updated') else 'brak'}, "
         f"EMA200 z {pl_time(src['ema_updated']) if src.get('ema_updated') else 'brak'} (czas polski)."]
    if page_url:
        L.append(f"Wersja z wykresami: {page_url}?id={rep['id']}")
    for b in rep.get("blocks") or []:
        t, title = b.get("type"), b.get("title") or ""
        if t == "section":
            L += ["", f"## {title}"]
            continue
        if t == "text" and title == "O tym raporcie":
            continue
        L += ["", f"### {title}"] if title else [""]
        if b.get("desc"):
            L.append(b["desc"])
        if t == "text":
            L.append(b.get("text", ""))
        elif t == "facts":
            for it in b.get("items") or []:
                L.append(f"- **{it.get('label')}**: {it.get('value')} ({it.get('sub', '')})")
        elif t == "ranges":
            for it in b.get("items") or []:
                line = f"- **{it.get('label')}**: {it.get('value')}" + (f" ({it['sub']})" if it.get("sub") else "")
                if it.get("pos") is not None:
                    line += (f". Zakres: {it.get('min')} – {it.get('max')}; dziś na {it['pos']:.0f}% zakresu "
                             "(0% = minimum, 100% = maksimum)")
                    refs = [m["label"] for m in it.get("marks") or []]
                    if refs:
                        line += "; punkty odniesienia: " + ", ".join(refs)
                L.append(line + ".")
                if it.get("note"):
                    L.append(f"  {it['note']}")
        elif t == "table":
            L += _md_table(b.get("cols") or [], b.get("rows") or [])
        elif t == "chart":
            for i, s_ in enumerate(b.get("series") or []):
                L += _md_series(s_, b.get("lines") if i == 0 else None)
        elif t == "bars":
            rows = []
            for r in b.get("rows") or []:
                tot = (r.get("long") or 0) + (r.get("short") or 0)
                rows.append([r.get("label"), alerts.fmt_value(tot, "liq"), alerts.fmt_value(r.get("long"), "liq"),
                             alerts.fmt_value(r.get("short"), "liq"), f"{100 * r['long'] / tot:.0f}%" if tot else "—"])
            L += _md_table(["Dzień (UTC)", "Suma", "Longi", "Shorty", "Udział longów"], rows)
            if b.get("line"):
                L.append(f"Próg — {b['line']['label']}.")
        if b.get("note"):
            L.append(f"_{b['note']}_")
    L += ["", SOURCES_MD]
    return "\n".join(L)


def save(out_dir, rep, keep=120, md=None):
    """Write reports/<id>.json (+ .md for AI), update index.json (newest first, at most `keep`) and latest.md/.json."""
    idx = _read(os.path.join(out_dir, "index.json"), {}) or {}
    items = [r for r in idx.get("reports") or [] if r.get("id") != rep["id"]]
    items.insert(0, {k: rep[k] for k in ("id", "kind", "title", "created", "summary")})
    items.sort(key=lambda r: r.get("created") or 0, reverse=True)
    for old in items[keep:]:
        for ext in ("json", "md"):
            try:
                os.remove(os.path.join(out_dir, "reports", f"{old['id']}.{ext}"))
            except FileNotFoundError:
                pass
    items = items[:keep]
    _write(os.path.join(out_dir, "reports", f"{rep['id']}.json"), rep)
    _write(os.path.join(out_dir, "index.json"), {"updated": rep["created"], "reports": items})
    if md is not None and items and items[0]["id"] == rep["id"]:
        for path in (os.path.join(out_dir, "reports", f"{rep['id']}.md"), os.path.join(out_dir, "latest.md")):
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
        _write(os.path.join(out_dir, "latest.json"), rep)
    elif md is not None:
        with open(os.path.join(out_dir, "reports", f"{rep['id']}.md"), "w", encoding="utf-8") as f:
            f.write(md)
    return items


def notify_text(entry, page_url):
    link = f"{page_url}?id={entry['id']}"
    lines = [f"📊 <b>Nowy raport: {entry['title']}</b>", pl_time(entry["created"])]
    if entry.get("summary"):
        lines.append(entry["summary"])
    lines += ["", f'<a href="{link}">Otwórz raport</a>']
    return "\n".join(lines)


def load_cfg(path):
    try:
        with open(path, encoding="utf-8") as f:
            full = yaml.safe_load(f) or {}
    except FileNotFoundError:
        full = {}
    cfg = dict(DEFAULTS)
    cfg.update(full.get("reports") or {})
    cfg["telegram"] = full.get("telegram") or {}
    cfg["telegram_enabled"] = cfg["telegram"].get("enabled", True)
    return cfg


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Raporty: zbuduj i opublikuj / powiadom.")
    ap.add_argument("cmd", choices=["make", "notify"])
    ap.add_argument("--data", default="data-branch", help="katalog z gałęzią data")
    ap.add_argument("--ema", default="ema-branch", help="katalog z gałęzią ema")
    ap.add_argument("--out", default="reports-branch", help="katalog z gałęzią reports")
    ap.add_argument("--kind", default="test", choices=sorted(KIND_TITLES))
    ap.add_argument("--config", default=os.path.join(here, "config.yaml"))
    ap.add_argument("--page", default=os.environ.get("REPORT_PAGE_URL", ""), help="adres raporty.html")
    a = ap.parse_args(argv)
    cfg = load_cfg(a.config)

    if a.cmd == "make":
        rep = build(a.data, a.ema, a.kind, cfg=cfg)
        save(a.out, rep, keep=int(cfg["keep"]), md=to_markdown(rep, a.page or cfg["page_url"]))
        n = sum(len(b.get("items") or b.get("rows") or b.get("series") or [1]) for b in rep["blocks"])
        log.info("Raport %s: %d bloków, %d pozycji", rep["id"], len(rep["blocks"]), n)
        return 0

    idx = _read(os.path.join(a.out, "index.json"), {}) or {}
    if not idx.get("reports"):
        log.error("Brak raportów w %s", a.out)
        return 1
    if not (cfg["notify"] and cfg["telegram_enabled"]):
        log.info("Powiadomienia o raportach wyłączone w configu")
        return 0
    tg = alerts.Telegram(tg_cfg=cfg["telegram"])
    if not tg.enabled:
        log.error("Brak TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return 1
    ok = tg.post("report", notify_text(idx["reports"][0], a.page or cfg["page_url"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
