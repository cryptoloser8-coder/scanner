"""Scan and report schedule (config.yaml → `schedule`), checked every minute on the Orange Pi by bot.py.

Times are wall-clock times in `timezone` (default Europe/Warsaw); summer/winter time is handled by zoneinfo.
  regular scans:  every `scan_every_hours` hours at minute `scan_minute`  (00:15, 02:15, …)
  report scans:   reports: [{scan_at: "06:15", kind: morning}, …] — the OI scan runs (~40 min),
                  then the same GitHub run builds the report and posts the link.
                  An entry may have its own `timezone` (e.g. {scan_at: "16:05", timezone: America/New_York}
                  = always 5 min after the US close, whatever the summer/winter time in Poland and the US).
                  `weekday` (1 = Monday … 7 = Sunday), `monthday` (1–31) and `month` (1–12; e.g. monthday 1 +
                  month 1 = 1 January, the yearly report) limit an entry to those days — checked
                  in the entry's own timezone, e.g. {scan_at: "00:05", timezone: UTC, weekday: 1, kind: weekly}
                  = right after the weekly candle closes. Report entries at the same moment are merged into one
                  scan with kinds joined by a comma ("weekly,monthly").
A regular scan closer than `skip_regular_minutes` to a report scan is skipped (the report scan replaces it).
An event is started once, at most `grace_minutes` late (report scans: `report_grace_minutes`),
e.g. after the Pi was switched off for a while.
"""
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover  (Python < 3.9)
    ZoneInfo = None

DEFAULTS = {
    "timezone": "Europe/Warsaw",
    "scan_every_hours": 2,
    "scan_minute": 15,
    "reports": [{"scan_at": "06:15", "kind": "morning"}, {"scan_at": "22:05", "kind": "evening"}],
    "skip_regular_minutes": 60,
    "grace_minutes": 10,
    "report_grace_minutes": 90,
}


def load(section):
    sc = dict(DEFAULTS)
    sc.update(section or {})
    sc["reports"] = list(sc.get("reports") or [])
    return sc


def tz(sc):
    return ZoneInfo(sc.get("timezone") or "Europe/Warsaw")


def _hm(v):
    h, m = str(v).strip().split(":")
    return int(h), int(m)


def events_on(sc, day):
    """All events of one local calendar day → [{"at": aware datetime, "type": scan|report, "kind", "key"}]."""
    z = tz(sc)
    reports = []
    for r in sc["reports"]:
        h, m = _hm(r["scan_at"])
        rz = ZoneInfo(r["timezone"]) if r.get("timezone") else z
        wd, md, mo = r.get("weekday"), r.get("monthday"), r.get("month")
        for d in (day - timedelta(days=1), day, day + timedelta(days=1)):
            if wd is not None and d.isoweekday() != int(wd):
                continue
            if md is not None and d.day != int(md):
                continue
            if mo is not None and d.month != int(mo):
                continue
            at = datetime(d.year, d.month, d.day, h, m, tzinfo=rz).astimezone(z)
            if at.date() == day:                       # the event of this local (Polish) day
                kind = str(r.get("kind") or "daily")
                same = next((x for x in reports if x["at"].timestamp() == at.timestamp()), None)
                if same is None:
                    reports.append({"at": at, "type": "report", "kind": kind})
                elif kind not in same["kind"].split(","):
                    same["kind"] += "," + kind
    skip = float(sc.get("skip_regular_minutes") or 0) * 60
    regular = []
    every = int(sc.get("scan_every_hours") or 0)
    if every > 0:
        for h in range(0, 24, every):
            at = datetime(day.year, day.month, day.day, h, int(sc.get("scan_minute") or 0), tzinfo=z)
            if any(abs(at.timestamp() - r["at"].timestamp()) < skip for r in reports):
                continue
            regular.append({"at": at, "type": "scan", "kind": None})
    out = sorted(reports + regular, key=lambda e: e["at"].timestamp())
    for e in out:
        e["key"] = e["at"].strftime("%Y-%m-%d %H:%M ") + e["type"]
    return out


def _days_around(sc, now_ts, before=1, after=1):
    today = datetime.fromtimestamp(now_ts, tz(sc)).date()
    return [today + timedelta(days=d) for d in range(-before, after + 1)]


def due(sc, now_ts, done):
    """Events that should start now (not started yet, at most grace minutes late)."""
    out = []
    for day in _days_around(sc, now_ts, 1, 0):
        for e in events_on(sc, day):
            age = now_ts - e["at"].timestamp()
            grace = float(sc["report_grace_minutes"] if e["type"] == "report" else sc["grace_minutes"]) * 60
            if 0 <= age <= grace and e["key"] not in done:
                out.append(e)
    return out


def upcoming(sc, now_ts, n=3, only=None):
    out = []
    for day in _days_around(sc, now_ts, 0, 2):
        for e in events_on(sc, day):
            if e["at"].timestamp() > now_ts and (only is None or e["type"] == only):
                out.append(e)
    return out[:n]


def prune(done, now_ts, keep_days=3):
    for k in [k for k, v in done.items() if now_ts - (v.get("at") or 0) > keep_days * 86400]:
        del done[k]


def local(ts, sc, fmt="%H:%M"):
    return datetime.fromtimestamp(ts, tz(sc)).strftime(fmt)
