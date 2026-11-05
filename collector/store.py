"""JSON storage on the `data` branch.

Files:
  1h.json / 1d.json          {"updated": ts, "series": {id: [[t, v], ...]}}  — read by oi.html
  liq_1h.json / liq_1d.json  same format, liquidations / funding / price  — read by liq.html
  cvd_1h.json / cvd_1d.json  same format, CVD (kupno − sprzedaż) i wolumen spot / perp — read by oi.html (cvd.py)
  meta.json                  catalogue, levels, health — read by every tab
  state.json                 collector internals (universe, gap-fill values, alert state)
"""
import json
import os
import tempfile

RESOLUTIONS = ("1h", "1d")
# file prefix per series-id prefix (anything else goes to the main 1h/1d files)
BUNDLES = {"liq_": "liq_", "fund_": "liq_", "px_": "liq_", "cvd_": "cvd_"}
FILE_PREFIXES = ("", "liq_", "cvd_")


def bundle_of(sid):
    for p, f in BUNDLES.items():
        if sid.startswith(p):
            return f
    return ""


def _round(v):
    return float(f"{v:.6g}")


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def _write(path, obj):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


class Store:
    def __init__(self, data_dir):
        self.dir = data_dir
        self.series = {}
        for res in RESOLUTIONS:
            self.series[res] = {}
            for fp in FILE_PREFIXES:
                raw = _read(os.path.join(data_dir, f"{fp}{res}.json"), {}).get("series", {})
                for sid, pts in raw.items():
                    if bundle_of(sid) == fp:
                        self.series[res][sid] = {int(t): v for t, v in pts}
        self.state = _read(os.path.join(data_dir, "state.json"), {})

    def get(self, res, sid):
        return self.series[res].setdefault(sid, {})

    def last_t(self, res, sid):
        s = self.series[res].get(sid)
        return max(s) if s else None

    def put(self, res, sid, points, replace_from=None):
        """Merge points; with replace_from, drop stored points ≥ replace_from first."""
        dst = self.get(res, sid)
        if replace_from is not None:
            for t in [t for t in dst if t >= replace_from]:
                del dst[t]
        for t, v in points.items():
            if v is not None:
                dst[int(t)] = _round(v)

    def latest(self, sid):
        """Most recent (t, v) preferring hourly data."""
        for res in RESOLUTIONS:
            s = self.series[res].get(sid)
            if s:
                t = max(s)
                return t, s[t]
        return None

    def value_at(self, sid, t, res="1h", tolerance=2 * 3600):
        """Value at/just before t (within tolerance)."""
        s = self.series[res].get(sid) or {}
        best = None
        for ts in s:
            if ts <= t and t - ts <= tolerance and (best is None or ts > best):
                best = ts
        return s[best] if best is not None else None

    def save(self, now, meta):
        for res in RESOLUTIONS:
            for fp in FILE_PREFIXES:
                out = {sid: sorted([t, v] for t, v in pts.items())
                       for sid, pts in sorted(self.series[res].items()) if pts and bundle_of(sid) == fp}
                if fp and not out and not os.path.exists(os.path.join(self.dir, f"{fp}{res}.json")):
                    continue  # don't create empty extra files
                _write(os.path.join(self.dir, f"{fp}{res}.json"), {"updated": now, "series": out})
        _write(os.path.join(self.dir, "meta.json"), meta)
        _write(os.path.join(self.dir, "state.json"), self.state)
