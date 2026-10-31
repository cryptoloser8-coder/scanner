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
  {"type": "table", "title", "note", "cols": [...], "rows": [[...], ...]}
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
KIND_TITLES = {"test": "Raport testowy", "daily": "Raport dzienny", "manual": "Raport na żądanie"}
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


def ema_blocks(ema, fib):
    blocks = []
    if not ema:
        return [{"type": "text", "title": "EMA200 i szerokość rynku", "text": "Brak danych z gałęzi ema."}]
    breadth = ema.get("breadth") or []
    total = ema.get("total") or 0
    above = ema.get("above") or 0
    now_pct = 100 * above / total if total else None
    items = [{"label": "Szerokość rynku", "value": f"{now_pct:.1f}%" if now_pct is not None else "—",
              "sub": f"{above} z {total} coinów nad EMA200", "zone": None,
              "note": "Odsetek coinów Binance */USDT (z co najmniej 300 dniami historii) z ceną nad EMA200 na świecy dziennej."}]
    if breadth:
        last_t = breadth[-1][0]
        yr = [b for b in breadth if b[0] >= last_t - 365 * DAY]
        mx = max(yr, key=lambda b: b[1])
        mn = min(yr, key=lambda b: b[1])
        items[0]["sub"] += f" · 12 mies.: maks. {mx[1]:.0f}% ({utc(mx[0], '%d.%m.%Y')}), min. {mn[1]:.0f}% ({utc(mn[0], '%d.%m.%Y')})"
    coins = {c.get("s"): c for c in ema.get("coins") or []}
    for sym in ("BTC", "ETH"):
        c = coins.get(sym)
        if c:
            side = "nad" if c.get("side", 0) > 0 else "pod"
            items.append({"label": f"{sym} vs EMA200", "value": f"{c['d']:+.2f}%",
                          "sub": f"cena {fmt_price(c['p'])} · EMA {fmt_price(c['e'])} · {side} od {c.get('since', '?')} dni",
                          "zone": None, "note": "Odległość aktualnej ceny od EMA200 (świeca dzienna)."})
    blocks.append({"type": "facts", "title": "EMA200 i szerokość rynku (Binance)", "items": items})

    if breadth:
        last_t = breadth[-1][0]
        blocks.append({"type": "chart", "title": "Szerokość rynku — % coinów nad EMA200, 2 lata", "log": False,
                       "range": [0, 100],
                       "note": breadth_peaks_note(breadth),
                       "series": [{"name": "% nad EMA200", "color": "#ffc107", "fmt": "pct", "scale": "right",
                                   "data": [[b[0], b[1]] for b in breadth if b[0] >= last_t - 730 * DAY]}]})

    rule_coins = []
    for r in ema.get("rules") or []:
        rule_coins += [c for c in r.get("coins") or [] if c not in rule_coins]
    rows = []
    for sym in rule_coins:
        c = coins.get(sym)
        if not c:
            continue
        rows.append([sym, fmt_price(c["p"]), fmt_price(c["e"]),
                     f"{c['d']:+.2f}%", ("nad" if c.get("side", 0) > 0 else "pod") + f" {c.get('since', '?')} dni"])
    rows.sort(key=lambda r: abs(float(r[3].rstrip("%"))))
    if rows:
        blocks.append({"type": "table", "title": "Coiny z alertami EMA200 — od najbliższego przecięcia",
                       "note": "Coiny bez pary na Binance spot (np. HYPE) nie mają tu EMA200.",
                       "cols": ["Coin", "Cena", "EMA200", "Odległość", "Strona"], "rows": rows})

    if fib:
        setups = fib.get("setups") or []
        props = fib.get("proposals") or []
        by = {}
        for s in setups:
            by[s.get("status", "?")] = by.get(s.get("status", "?"), 0) + 1
        in_zone = sum(1 for p in props if p.get("status") == "zone")
        txt = (f"Twoje setupy: {len(setups)}" + (" (" + ", ".join(f"{k}: {v}" for k, v in sorted(by.items())) + ")" if by else "")
               + f". Propozycje automatu: {len(props)} (w strefie 0.705–0.786: {in_zone}), "
               f"wybrane z {fib.get('candidates', '?')} ruchów.")
        blocks.append({"type": "text", "title": "Fibo", "text": txt})
    return blocks


def build(data_dir, ema_dir, kind="test", now=None):
    now = int(now or time.time())
    d = Data(data_dir)
    ema = _read(os.path.join(ema_dir, "ema.json")) if ema_dir else None
    fib = _read(os.path.join(ema_dir, "fib.json")) if ema_dir else None

    blocks = []
    warn = []
    if not d.updated:
        warn.append("brak danych z gałęzi data (OI, TOTAL, likwidacje)")
    elif now - d.updated > 4 * HOUR:
        warn.append(f"dane OI/TOTAL sprzed {(now - d.updated) / HOUR:.0f} h")
    ema_upd = (ema or {}).get("updated") or 0
    if not ema_upd:
        warn.append("brak danych z gałęzi ema (EMA200, Fibo)")
    elif now - ema_upd > 2 * HOUR:
        warn.append(f"dane EMA sprzed {(now - ema_upd) / HOUR:.0f} h")

    if kind == "test":
        blocks.append({"type": "text", "title": "O tym raporcie",
                       "text": "To raport testowy: sprawdza drogę od danych do strony, pobierania PDF i powiadomienia na Telegramie. "
                               "Liczby policzył kod z aktualnych danych. Treść i układ raportu ustalimy później; "
                               "komentarz AI pojawi się w tym miejscu."})
    if warn:
        blocks.append({"type": "text", "title": "Uwaga", "text": "Nieświeże dane: " + "; ".join(warn) + "."})

    blocks.append({"type": "facts", "title": "Rynek — kapitalizacja i dominacje (TradingView)",
                   "items": [fact_series(d, s) for s in ("total", "total2", "total3", "btc_d", "eth_d", "stable_d", "alts_d", "ethbtc")]})
    der = [fact_series(d, "oi_total"), fact_series(d, "oi_btc"), fact_history(d, "oi_others_vs_btc"),
           fact_series(d, "fund_btc"), fact_series(d, "fund_others")]
    lq = liq_24h(d)
    if lq:
        der.append(lq)
    blocks.append({"type": "facts", "title": "Derywaty — open interest, funding, likwidacje (Coinalyze)", "items": der})
    blocks.append(chart_block(d, "TOTAL3 i BTC.D — 12 miesięcy", ["total3", "btc_d"], days=365,
                              colors={"total3": "#26c6da"},
                              note="TOTAL3 (prawa oś) = kapitalizacja bez BTC i ETH; BTC.D (lewa oś) w %."))
    blocks.append(chart_block(d, "OI OTHERS / OI BTC — cała historia", ["oi_others_vs_btc"],
                              note=history_note(d, "oi_others_vs_btc")))
    blocks += ema_blocks(ema, fib)

    # one-line summary (index + Telegram)
    parts = []
    for sid in ("total", "btc_d"):
        last = d.latest(sid)
        if last:
            parts.append(f"{d.name(sid)} {fmt_val(last[1], d.group(sid))}")
    if ema and ema.get("total"):
        parts.append(f"szerokość rynku {100 * ema['above'] / ema['total']:.0f}%")
    summary = " · ".join(parts)

    return {"id": utc(now, "%Y%m%d-%H%M") + "-" + kind, "kind": kind,
            "title": KIND_TITLES.get(kind, "Raport"), "created": now, "summary": summary,
            "sources": {"data_updated": d.updated or None, "ema_updated": ema_upd or None},
            "blocks": blocks}


def save(out_dir, rep, keep=120):
    """Write reports/<id>.json and update index.json (newest first, at most `keep`)."""
    idx = _read(os.path.join(out_dir, "index.json"), {}) or {}
    items = [r for r in idx.get("reports") or [] if r.get("id") != rep["id"]]
    items.insert(0, {k: rep[k] for k in ("id", "kind", "title", "created", "summary")})
    items.sort(key=lambda r: r.get("created") or 0, reverse=True)
    for old in items[keep:]:
        try:
            os.remove(os.path.join(out_dir, "reports", f"{old['id']}.json"))
        except FileNotFoundError:
            pass
    items = items[:keep]
    _write(os.path.join(out_dir, "reports", f"{rep['id']}.json"), rep)
    _write(os.path.join(out_dir, "index.json"), {"updated": rep["created"], "reports": items})
    return items


def notify_text(entry, page_url):
    link = f"{page_url}?id={entry['id']}"
    lines = [f"📊 <b>Nowy raport: {entry['title']}</b>", utc(entry["created"])]
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
    cfg["telegram_enabled"] = (full.get("telegram") or {}).get("enabled", True)
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
        rep = build(a.data, a.ema, a.kind)
        save(a.out, rep, keep=int(cfg["keep"]))
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
    tg = alerts.Telegram()
    if not tg.enabled:
        log.error("Brak TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return 1
    ok = tg.send(notify_text(idx["reports"][0], a.page or cfg["page_url"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
