"""US economic calendar for the reports (TradingView economic calendar, unofficial public endpoint).

  GET https://economic-calendar.tradingview.com/events?from=…Z&to=…Z&countries=US
  → {"status": "ok", "result": [{"title", "country", "date" (UTC ISO), "importance" (-1 low, 0 medium, 1 high),
                                  "actual", "forecast", "previous", "unit", "scale", "period", "source", …}]}

Only medium and high importance (≈ 2 and 3 stars). A report shows the releases of the last US day that had any
(evening report: today's results; morning report: the same results again as a reminder; Monday morning: Friday)
and the plan of the next US day with scheduled releases (evening: tomorrow; morning: today; Friday evening: Monday).
All numbers come from the calendar; nothing is interpreted.
"""
import logging
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

log = logging.getLogger("econ")

URL = "https://economic-calendar.tradingview.com/events"
HEADERS = {"Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/",
           "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
STARS = {0: "★★", 1: "★★★"}
IMPORTANCE = {"low": -1, "medium": 0, "high": 1}
DEFAULTS = {"enabled": True, "countries": ["US"], "min_importance": "medium", "days_back": 5, "days_ahead": 5}
NY = "America/New_York"
WEEKDAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]


def settings(cfg):
    out = dict(DEFAULTS)
    out.update((cfg or {}).get("econ") or {})
    return out


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch(now_ts, cfg=None, session=None, timeout=20):
    """Raw events from the last `days_back` days up to now (list of dicts). Raises on HTTP / format errors."""
    import requests
    st = settings(cfg)
    now = datetime.fromtimestamp(now_ts, timezone.utc)
    params = {"from": _iso(now - timedelta(days=int(st["days_back"]))), "to": _iso(now + timedelta(days=int(st["days_ahead"]))),
              "countries": ",".join(c.upper() for c in st["countries"])}
    r = (session or requests).get(URL, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok":
        raise ValueError(f"status {data.get('status')}: {data.get('errmsg') or data.get('message') or ''}")
    return data.get("result") or []


def _ts(ev):
    """'2026-10-30T12:30:00.000Z' → unix time (works on Python 3.9: no 'Z' in fromisoformat)."""
    d = str(ev.get("date") or "").strip()
    if d.endswith("Z"):
        d = d[:-1] + "+00:00"
    dt = datetime.fromisoformat(d)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _by_day(events, cfg):
    """{New York date: [events]} for the configured countries and importance."""
    st = settings(cfg)
    lvl = IMPORTANCE.get(str(st["min_importance"]).lower(), 0)
    countries = [c.upper() for c in st["countries"] or []]
    ny = ZoneInfo(NY)
    days = {}
    for ev in events:
        try:
            ts = _ts(ev)
        except (ValueError, TypeError):
            continue
        imp = ev.get("importance")
        if imp is None or imp < lvl:
            continue
        if countries and str(ev.get("country") or "").upper() not in countries:
            continue
        days.setdefault(datetime.fromtimestamp(ts, ny).date(), []).append(dict(ev, _ts=ts))
    return days


def _sorted(evs):
    return sorted(evs, key=lambda e: (e["_ts"], -(e.get("importance") or 0), e.get("title") or ""))


def last_day(events, now_ts, cfg=None):
    """(US date, [events]) — releases of the latest New York calendar day (≤ now) with medium/high events."""
    days = {d: [e for e in evs if e["_ts"] <= now_ts] for d, evs in _by_day(events, cfg).items()}
    days = {d: evs for d, evs in days.items() if evs}
    if not days:
        return None, []
    day = max(days)
    return day, _sorted(days[day])


def next_day(events, now_ts, cfg=None):
    """(US date, [events]) — scheduled releases of the next New York calendar day (> now) that has any."""
    days = {d: [e for e in evs if e["_ts"] > now_ts] for d, evs in _by_day(events, cfg).items()}
    days = {d: evs for d, evs in days.items() if evs}
    if not days:
        return None, []
    day = min(days)
    return day, _sorted(days[day])


def fmt_num(v, ev, sign=False):
    if v is None:
        return "—"
    unit, scale = (ev.get("unit") or "").strip(), (ev.get("scale") or "").strip()
    s = f"{v:+.6g}" if sign else f"{v:.6g}"
    return s + scale + ("%" if unit == "%" else "")


def diff_text(ev):
    a, f = ev.get("actual"), ev.get("forecast")
    if a is None or f is None:
        return "—"
    d = round(a - f, 6)
    if (ev.get("unit") or "").strip() == "%":
        return f"{d:+.6g} pp"
    return fmt_num(d, ev, sign=True)


def short_error(e):
    """A readable reason for the report instead of a long technical message."""
    code = getattr(getattr(e, "response", None), "status_code", None)
    if code:
        return f"HTTP {code}"
    name = type(e).__name__
    if "Timeout" in name:
        return "przekroczony czas odpowiedzi"
    if "Connection" in name or "Proxy" in str(e):
        return "brak połączenia"
    return str(e)[:80] or name


def pl_hm(ts):
    return datetime.fromtimestamp(ts, ZoneInfo("Europe/Warsaw")).strftime("%H:%M")


def _when(day, now_ts):
    ny_today = datetime.fromtimestamp(now_ts, ZoneInfo(NY)).date()
    if day == ny_today:
        return "dziś"
    if day == ny_today - timedelta(days=1):
        return "wczoraj"
    if day == ny_today + timedelta(days=1):
        return "jutro"
    return WEEKDAYS[day.weekday()]


def _name(ev):
    return f"{ev.get('title', '')}" + (f" ({ev['period']})" if ev.get("period") else "")


def block(events, now_ts, cfg=None, error=None, results=True, plan_importance=None):
    """Report blocks for the 'Dane makro z USA' section: last day's results + next day's plan.
    results=False → only the plan (morning report); plan_importance="high" → plan only with ★★★."""
    head = {"type": "section", "title": "Dane makro z USA"}
    if error:
        return [head, {"type": "text", "title": "", "text": f"Kalendarz ekonomiczny niedostępny ({error}). Reszta raportu bez zmian."}]
    st = settings(cfg)
    out = [head]
    day, evs = last_day(events or [], now_ts, cfg) if results else (None, [])
    if evs:
        rows = [[pl_hm(ev["_ts"]), _name(ev), STARS.get(ev.get("importance"), ""), fmt_num(ev.get("actual"), ev),
                 fmt_num(ev.get("forecast"), ev), fmt_num(ev.get("previous"), ev), diff_text(ev)] for ev in evs]
        out.append({"type": "table", "title": f"Publikacje z USA — {_when(day, now_ts)}, {day.strftime('%d.%m.%Y')}",
                    "cols": ["Godz. PL", "Publikacja", "Ważność", "Wynik", "Prognoza", "Poprzednio", "Wynik − prognoza"],
                    "rows": rows, "plain": True, "left": [1],
                    "desc": "Dane makro z USA o średniej (★★) i wysokiej (★★★) ważności z ostatniego dnia publikacji. "
                            "Wieczorem — wyniki z dzisiaj; rano — te same wyniki jako przypomnienie.",
                    "note": "Źródło: kalendarz ekonomiczny TradingView (ważność według TradingView: średnia = ★★, wysoka = ★★★). "
                            "Prognoza = oczekiwanie rynku przed publikacją. Godziny w czasie polskim. "
                            "Wystąpienia (np. przemówienia z Fed) nie mają liczb."})
    elif results:
        out.append({"type": "text", "title": "", "text": "Brak publikacji o średniej i wysokiej ważności w ostatnich dniach."})
    pcfg = cfg
    if plan_importance:
        pcfg = dict(cfg or {}, econ=dict((cfg or {}).get("econ") or {}, min_importance=plan_importance))
    stars = "★★★" if plan_importance == "high" else "★★ i ★★★"
    nday, nevs = next_day(events or [], now_ts, pcfg)
    if nevs:
        rows = [[pl_hm(ev["_ts"]), _name(ev), STARS.get(ev.get("importance"), ""),
                 fmt_num(ev.get("forecast"), ev), fmt_num(ev.get("previous"), ev)] for ev in nevs]
        out.append({"type": "table", "title": f"Zaplanowane — {_when(nday, now_ts)}, {nday.strftime('%d.%m.%Y')}",
                    "cols": ["Godz. PL", "Publikacja", "Ważność", "Prognoza", "Poprzednio"],
                    "rows": rows, "plain": True, "left": [1],
                    "desc": f"Co i o której wyjdzie w najbliższym dniu z publikacjami {stars} "
                            + ("— najważniejsze dane z USA, zwykle ruszają też krypto. Wyniki z wczoraj były w raporcie "
                               "wieczornym." if plan_importance == "high" else
                               "(wieczorem — jutro, rano — dziś, w piątek wieczorem — poniedziałek)."),
                    "note": "Godziny w czasie polskim, według kalendarza TradingView; terminy i prognozy mogą się jeszcze zmienić."})
    else:
        out.append({"type": "text", "title": "Zaplanowane",
                    "text": f"Brak zaplanowanych publikacji {stars} w najbliższych {st['days_ahead']} dniach."})
    return out
