"""Dziennik alertów z wynikiem (poprawka 115) — na razie samo zbieranie, bez strony.

Każdy alert rynkowy (poziomy, zmiany %, likwidacje, lampki Altsezonu — skan GitHuba; EMA200 1D / 1W, Fibo — Orange Pi)
trafia do pliku `alerts_log.json` na gałęzi swojego wydawcy (`data` albo `ema`) razem z cenami z chwili alertu.
Po 7 i 30 dniach (ustawienie `alert_log.horizons_days`) dopisywany jest wynik: te same ceny i zmiana w %.
Po kilku miesiącach widać, które alerty były coś warte, a które tylko hałasują.

Wpis:
  {"id": "g1763500000-0", "t": czas alertu, "src": "github" | "pi", "kind": level | change | liq | lamp | ema_d | ema_w | fib,
   "text": treść bez znaczników, "muted": true gdy /cisza wstrzymała wysyłkę (alert i tak zapisany),
   "coin": "SOL", "px": cena coina, "sid": id serii, "v": wartość serii, "key": klucz reguły / setupu,
   "ref": {"btc": …, "eth": …, "alt": indeks altów, "total3": …},
   "out": {"7": {"t": termin, "px": …, "px_pct": …, "v": …, "v_pct": …, "ref": {…}, "ref_pct": {…}}, "30": {…}}}
Wynik bez danych po 3 dniach od terminu → {"t": termin, "missing": true} (więcej nie próbujemy).

Ustawienia (config.yaml, wszystkie opcjonalne): alert_log: {enabled: true, horizons_days: [7, 30], keep_days: 800}.
Moduł nie pobiera niczego sam — ceny podaje wywołujący (lookup).
"""
import html
import json
import os
import re
import tempfile

DAY = 86400
FILE = "alerts_log.json"
DEFAULTS = {"enabled": True, "horizons_days": [7, 30], "keep_days": 800, "max_entries": 5000}
GIVE_UP_DAYS = 3


def settings(cfg):
    s = dict(DEFAULTS)
    s.update({k: v for k, v in ((cfg or {}).get("alert_log") or {}).items() if v is not None})
    try:
        s["horizons_days"] = sorted({int(h) for h in s["horizons_days"] if int(h) > 0}) or list(DEFAULTS["horizons_days"])
    except (TypeError, ValueError):
        s["horizons_days"] = list(DEFAULTS["horizons_days"])
    return s


def plain(text):
    """Treść wiadomości Telegrama bez znaczników HTML (linki znikają, tekst zostaje)."""
    t = re.sub(r"<[^>]+>", "", str(text or ""))
    return re.sub(r"[ \t]+", " ", html.unescape(t)).strip()


def event(kind, text, **fields):
    """Jeden alert do zapisania; pola None pomijane."""
    e = {"kind": kind, "text": text}
    e.update({k: v for k, v in fields.items() if v is not None})
    return e


def _num(v):
    try:
        return None if v is None else float(f"{float(v):.6g}")
    except (TypeError, ValueError):
        return None


def _pct(new, old):
    if new is None or not old:
        return None
    return round((new / old - 1) * 100, 2)


def _clean_ref(ref):
    return {k: _num(v) for k, v in (ref or {}).items() if _num(v) is not None}


def empty(src):
    return {"updated": 0, "src": src, "alerts": []}


def load(path, src):
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return empty(src)
    if not isinstance(obj, dict) or not isinstance(obj.get("alerts"), list):
        return empty(src)
    obj["src"] = src
    return obj


def save(path, log, now):
    log["updated"] = int(now)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(log, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


def add(log, events, now, ref=None, muted=False, fmt=None):
    """Dopisuje alerty z jednego przebiegu. ref = ceny tła z tej chwili ({"btc": …}); fmt = zamiana zapisu liczb w treści.
    → liczba dopisanych."""
    now = int(now)
    ref = _clean_ref(ref)
    used = {e.get("id") for e in log["alerts"]}
    n = 0
    for ev in events or []:
        i = 0
        while f"{log['src'][0]}{now}-{i}" in used:
            i += 1
        text = plain(ev.get("text"))
        if fmt:
            try:
                text = fmt(text)
            except Exception:  # noqa: BLE001 — zapis liczb to ozdoba
                pass
        e = {"id": f"{log['src'][0]}{now}-{i}", "t": now, "src": log["src"], "kind": ev.get("kind") or "other", "text": text}
        for k in ("coin", "sid", "key", "level"):
            if ev.get(k) is not None:
                e[k] = ev[k]
        for k in ("px", "v"):
            if _num(ev.get(k)) is not None:
                e[k] = _num(ev[k])
        if muted:
            e["muted"] = True
        if ref:
            e["ref"] = dict(ref)
        e["out"] = {}
        used.add(e["id"])
        log["alerts"].append(e)
        n += 1
    return n


def due(log, now, horizons):
    """→ [(wpis, liczba dni, termin)] — wyniki do dopisania w tym przebiegu."""
    out = []
    for e in log["alerts"]:
        for h in horizons:
            t_due = e["t"] + h * DAY
            if str(h) not in (e.get("out") or {}) and now >= t_due:
                out.append((e, h, t_due))
    return out


def update(log, now, horizons, lookup):
    """Dopisuje wyniki po terminie. lookup(wpis, termin) → {"px": …, "v": …, "ref": {…}} (to, co zna) albo None.
    → liczba dopisanych wyników."""
    n = 0
    for e, h, t_due in due(log, now, horizons):
        try:
            got = lookup(e, t_due) or {}
        except Exception:  # noqa: BLE001 — brak ceny nie może zatrzymać skanu
            got = {}
        res = {"t": t_due}
        px, v, ref = _num(got.get("px")), _num(got.get("v")), _clean_ref(got.get("ref"))
        if px is not None and e.get("px"):
            res["px"], res["px_pct"] = px, _pct(px, e["px"])
        if v is not None and e.get("v") is not None:
            res["v"] = v
            if e["v"] > 0 and v > 0:
                res["v_pct"] = _pct(v, e["v"])
        ref = {k: x for k, x in ref.items() if (e.get("ref") or {}).get(k)}
        if ref:
            res["ref"] = ref
            res["ref_pct"] = {k: _pct(x, e["ref"][k]) for k, x in ref.items()}
        if len(res) == 1:
            if now < t_due + GIVE_UP_DAYS * DAY:
                continue                      # danych jeszcze nie ma — spróbujemy w następnym przebiegu
            res["missing"] = True
        e.setdefault("out", {})[str(h)] = res
        n += 1
    return n


def prune(log, now, keep_days, max_entries):
    keep = [e for e in log["alerts"] if now - e.get("t", 0) <= keep_days * DAY]
    log["alerts"] = keep[-int(max_entries):]
    return log


def at_day(points, t, tolerance_days=3):
    """Wartość z serii dziennej [[t, v, …], …] dla doby, w której wypada t (albo ostatniej wcześniejszej w tolerancji)."""
    best = None
    for p in points or []:
        if p[0] <= t and t - p[0] <= (tolerance_days + 1) * DAY and (best is None or p[0] > best[0]):
            best = p
    return best[1] if best else None
