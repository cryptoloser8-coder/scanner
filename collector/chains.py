"""Sieci (poprawka 48): gdzie jest kapitał i ruch — dane DefiLlama, raz na dobę.

Po co: widzieć, na której sieci leżą dolary (stablecoiny) i gdzie się handluje (wolumen DEX), oraz wyłapać
sieć spoza naszej listy, która nagle rośnie. Bez liczby transakcji (łatwo ją napompować — decyzja 12.11.2026).

Co robi (GitHub, workflow „Sieci” — osobno albo równolegle ze skanem przed raportem porannym):
  • nasze sieci (config `chains.list`): pełna historia 4 miar — wolumen DEX, opłaty, stablecoiny, TVL;
    punkt z bieżącej daty UTC jest pomijany (DefiLlama podaje w nim wartości z ostatnich 24 h, nie dzień w toku),
  • sieci spoza listy ze stablecoinami albo TVL ≥ `cand_min` ($20M): historia wolumenu DEX i stablecoinów,
    reguły „rośnie” (progi z sondy 12.11.2026 — na próbę):
      – ruch:    wolumen DEX z 7 dni ÷ średni tydzień z 4 poprzednich ≥ `dex_ratio` (×3) przy 7 dniach ≥ `dex7_min`,
      – kapitał: stablecoiny 30D ≥ `stable30` (+100%) przy stablecoinach ≥ `stable_min`,
      – nowa sieć: pierwsze dane ≤ `new_days` dni temu, a już DEX 7 dni ≥ `new_dex7` albo stablecoiny ≥ `new_stable`,
    epizod = kolejne dni nad progiem (przerwa ≤ `gap_days` go nie kończy) → „nowa” / „dzień N”,
  • sprawdzanie, czy wartość z rana była kompletna: zapisuje wartości ostatniego pełnego dnia, a następnego dnia
    porównuje je z wartościami po korektach DefiLlama (lista `revisions`).

Pliki (gałąź `chains`):
  chains_1d.json    {"updated", "series": {"ch_<slug>_<dex|fees|stable|tvl>": [[t, v], …]}} — nasze sieci,
  chains.json       podsumowanie dla raportu i zakładki (ostatni pełny dzień, zmiany, udziały, „rośnie”, korekty),
  chains_other.json sieci spoza listy: ostatnie `other_days` dni wolumenu DEX i stablecoinów (bez klucza "series"),
  state.json        epizody „rośnie”, wartości poranne do porównania.

    python collector/chains.py --data-dir DIR [--config collector/config.yaml]
"""
import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

log = logging.getLogger("chains")
DAY = 86400
LL = "https://api.llama.fi"
LL_ST = "https://stablecoins.llama.fi"
UA = {"User-Agent": "Mozilla/5.0 (scanner-chains)", "Accept": "application/json"}
METRICS = ("dex", "fees", "stable", "tvl")
FLOW = ("dex", "fees")                 # przepływy (suma z okresu); stable i tvl to stany (poziom)
NAMES = {"dex": "Wolumen DEX", "fees": "Opłaty", "stable": "Stablecoiny", "tvl": "TVL"}

DEFAULTS = {
    "enabled": True,
    "list": [{"name": "Ethereum", "coin": "ETH"}, {"name": "Robinhood Chain"}, {"name": "Solana", "coin": "SOL"},
             {"name": "BSC", "coin": "BNB"}, {"name": "TON", "coin": "TON"}, {"name": "Base"},
             {"name": "Tron", "coin": "TRX"}, {"name": "Hyperliquid L1", "coin": "HYPE"}],
    "cand_min": 20e6,          # sieć spoza listy jest sprawdzana, gdy stablecoiny albo TVL ≥ tyle
    "max_cand": 100,           # najwyżej tyle sieci spoza listy (2 zapytania na sieć)
    "dex_ratio": 3.0,          # ruch: 7 dni ÷ średni tydzień z 4 poprzednich (sonda: p95 ×2,52, p99 ×7,23)
    "dex7_min": 10e6,
    "stable30": 100.0,         # kapitał: stablecoiny 30D w % (sonda: p95 +61%, p99 +409%)
    "stable_min": 20e6,
    "new_days": 35,            # „nowa sieć”: pierwsze dane najwyżej tyle dni temu
    "new_dex7": 10e6,
    "new_stable": 20e6,
    "gap_days": 14,            # przerwa pod progiem krótsza niż tyle dni nie kończy epizodu
    "max_rising": 5,
    "other_days": 120,
    "sleep": 0.4,
}


def cfg_from(full):
    c = dict(DEFAULTS)
    c.update((full or {}).get("chains") or {})
    return c


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return {"robinhood_chain": "robinhood", "hyperliquid_l1": "hyperliquid"}.get(s, s)


def iso(t):
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d")


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _day(t):
    t = int(float(t))
    if t > 1e11:
        t //= 1000
    return t - t % DAY


# ── pobieranie ───────────────────────────────────────────────
class Client:
    def __init__(self, session=None, sleep=time.sleep, pause=0.4):
        self.s = session or requests.Session()
        self.sleep, self.pause, self.calls = sleep, pause, 0

    def get(self, url, params=None):
        for attempt in range(4):
            self.calls += 1
            try:
                r = self.s.get(url, params=params, headers=UA, timeout=120)
            except requests.RequestException as e:
                if attempt == 3:
                    raise RuntimeError(f"{type(e).__name__}: {str(e)[:100]}") from e
                self.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 200:
                self.sleep(self.pause)
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                self.sleep(15 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {r.status_code} {r.text[:120]}")
        raise RuntimeError("zbyt wiele odpowiedzi 429 / 5xx")


def url_for(kind, name):
    q = requests.utils.quote(name)
    return {"dex": (f"{LL}/overview/dexs/{q}", {"excludeTotalDataChartBreakdown": "true"}),
            "fees": (f"{LL}/overview/fees/{q}", {"excludeTotalDataChartBreakdown": "true"}),
            "stable": (f"{LL_ST}/stablecoincharts/{q}", None),
            "tvl": (f"{LL}/v2/historicalChainTvl/{q}", None)}[kind]


def points(data, kind, today):
    """Odpowiedź DefiLlama → posortowana lista [[dzień 00:00 UTC, wartość]] bez punktu z bieżącej daty."""
    out = {}
    if kind in FLOW:
        for p in (data or {}).get("totalDataChart") or [] if isinstance(data, dict) else []:
            if isinstance(p, (list, tuple)) and len(p) >= 2 and _num(p[1]) is not None:
                out[_day(p[0])] = _num(p[1])
    elif kind == "stable":
        for p in data or []:
            usd = p.get("totalCirculatingUSD") or {}
            vals = [_num(v) for v in usd.values()] if isinstance(usd, dict) else [_num(usd)]
            vals = [v for v in vals if v is not None]
            if vals and p.get("date") is not None:
                out[_day(p["date"])] = sum(vals)
    elif kind == "tvl":
        for p in data or []:
            if _num(p.get("tvl")) is not None and p.get("date") is not None:
                out[_day(p["date"])] = _num(p["tvl"])
    return [[t, round(v, 2)] for t, v in sorted(out.items()) if t < today]


# ── liczenie ─────────────────────────────────────────────────
def _sum(d, a, b):
    vals = [d[x] for x in range(a, b + 1, DAY) if x in d]
    return sum(vals) if vals else None


def _at(d, day, back=3):
    for k in range(back + 1):
        if day - k * DAY in d:
            return d[day - k * DAY]
    return None


def _chg(a, b):
    return None if a is None or not b else round((a / b - 1) * 100, 2)


def change(pts, kind, end):
    """Zmiany na dzień `end`. Przepływ: wartość dnia, suma 7 dni, 7D = 7 dni vs poprzednie 7, 30D = 30 vs 30,
    ratio4w = 7 dni ÷ średni tydzień z 4 poprzednich, luki7 = brakujące dni w ostatnich 7. Stan: poziom vs 7 / 30 dni wcześniej."""
    d = dict(map(tuple, pts)) if isinstance(pts, list) else pts
    if kind in FLOW:
        s7, p7 = _sum(d, end - 6 * DAY, end), _sum(d, end - 13 * DAY, end - 7 * DAY)
        s30, p30 = _sum(d, end - 29 * DAY, end), _sum(d, end - 59 * DAY, end - 30 * DAY)
        p28 = _sum(d, end - 34 * DAY, end - 7 * DAY)
        return {"v": d.get(end), "s7": s7, "c7": _chg(s7, p7), "c30": _chg(s30, p30),
                "ratio4w": round(s7 / (p28 / 4), 3) if s7 is not None and p28 else None,
                "gaps7": sum(1 for x in range(end - 6 * DAY, end + DAY, DAY) if x not in d)}
    v = _at(d, end)
    return {"v": v, "c7": _chg(v, _at(d, end - 7 * DAY)), "c30": _chg(v, _at(d, end - 30 * DAY)),
            "c365": _chg(v, _at(d, end - 365 * DAY))}


def hist_rank(pts, kind, end, years=2):
    """Miejsce wartości z dnia `end` w historii ostatnich `years` lat: percentyl 0–100 (przepływy: suma 7 dni)."""
    d = dict(map(tuple, pts))
    start = end - years * 365 * DAY
    if kind in FLOW:
        vals = [_sum(d, x - 6 * DAY, x) for x in range(start, end + DAY, DAY)]
        now = _sum(d, end - 6 * DAY, end)
    else:
        vals = [d[x] for x in range(start, end + DAY, DAY) if x in d]
        now = _at(d, end)
    vals = [v for v in vals if v is not None]
    if now is None or len(vals) < 30:
        return None
    return round(sum(1 for v in vals if v <= now) / len(vals) * 100, 1)


def rising_check(name, dex, stable, end, cfg):
    """→ dict z wynikiem reguł dla sieci spoza listy albo None. dex / stable: listy [[t, v]] (mogą być puste)."""
    first = min([p[0][0] for p in (dex, stable) if p] or [end])
    cd = change(dex, "dex", end) if dex else {}
    cs = change(stable, "stable", end) if stable else {}
    kinds, strength = [], 0.0
    if cd.get("ratio4w") is not None and (cd.get("s7") or 0) >= cfg["dex7_min"] and cd["ratio4w"] >= cfg["dex_ratio"]:
        kinds.append("dex")
        strength = max(strength, cd["ratio4w"] / cfg["dex_ratio"])
    if cs.get("c30") is not None and (cs.get("v") or 0) >= cfg["stable_min"] and cs["c30"] >= cfg["stable30"]:
        kinds.append("stable")
        strength = max(strength, cs["c30"] / cfg["stable30"])
    age = (end - first) // DAY + 1
    if age <= cfg["new_days"] and ((cd.get("s7") or 0) >= cfg["new_dex7"] or (cs.get("v") or 0) >= cfg["new_stable"]):
        kinds.append("new")
        strength = max(strength, 1.0 + max((cd.get("s7") or 0) / cfg["new_dex7"], (cs.get("v") or 0) / cfg["new_stable"]) / 10)
    if not kinds:
        return None
    return {"name": name, "kinds": kinds, "strength": round(strength, 3), "first_data": iso(first), "age_days": age,
            "dex7": cd.get("s7"), "dex_ratio": cd.get("ratio4w"), "stable": cs.get("v"), "stable30": cs.get("c30")}


def episodes(found, state, end, gap_days):
    """Epizody „rośnie”: state = {nazwa: {"first": t, "last": t}} → dopisuje "since", "day_n", "new" do `found`."""
    for r in found:
        e = state.get(r["name"])
        if not e or end - e["last"] > gap_days * DAY:
            e = {"first": end, "last": end}
        e["last"] = end
        state[r["name"]] = e
        r["since"] = iso(e["first"])
        r["day_n"] = (end - e["first"]) // DAY + 1
        r["new"] = e["first"] == end
    for n in [n for n, e in state.items() if end - e["last"] > 60 * DAY]:      # porządek w stanie
        del state[n]
    return found


def revisions(state, series, end, now):
    """Porównanie wartości ostatniego pełnego dnia z poprzedniego przebiegu z wartością po korektach."""
    out = []
    m = state.get("morning") or {}
    day = m.get("day")
    if day and day < end:
        for sid, v0 in (m.get("values") or {}).items():
            v1 = dict(map(tuple, series.get(sid) or [])).get(day)
            if v1 is None or v0 is None:
                continue
            out.append({"day": iso(day), "sid": sid, "saved_at": m.get("at"), "first": v0, "now": v1,
                        "diff_pct": _chg(v1, v0) if v0 else None})
    state["morning"] = {"day": end, "at": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                        "values": {sid: dict(map(tuple, pts)).get(end) for sid, pts in series.items()}}
    return out


# ── przebieg ─────────────────────────────────────────────────
def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def run(data_dir, cfg, client=None, now=None):
    now = now or time.time()
    today = _day(now)
    end = today - DAY
    cl = client or Client(pause=cfg["sleep"])
    os.makedirs(data_dir, exist_ok=True)
    old = _load(os.path.join(data_dir, "chains_1d.json"), {}).get("series") or {}
    state = _load(os.path.join(data_dir, "state.json"), {})
    errors = []

    # 1) listy wszystkich sieci: stablecoiny i TVL teraz (do udziałów i wyboru kandydatów)
    stable_now, tvl_now = {}, {}
    try:
        for c in cl.get(f"{LL_ST}/stablecoinchains") or []:
            usd = c.get("totalCirculatingUSD") or {}
            stable_now[c.get("name")] = sum(_num(v) or 0 for v in usd.values()) if isinstance(usd, dict) else 0
    except Exception as e:  # noqa: BLE001
        errors.append(f"lista stablecoinów: {e}")
    try:
        for c in cl.get(f"{LL}/v2/chains") or []:
            tvl_now[c.get("name")] = _num(c.get("tvl")) or 0
    except Exception as e:  # noqa: BLE001
        errors.append(f"lista TVL: {e}")

    # 2) nasze sieci
    series, ours = {}, []
    ok = 0
    for ch in cfg["list"]:
        name = ch["name"]
        sl = slug(name)
        row = {"name": name, "slug": sl, "coin": ch.get("coin"), "m": {}}
        for kind in METRICS:
            sid = f"ch_{sl}_{kind}"
            url, params = url_for(kind, name)
            try:
                pts = points(cl.get(url, params), kind, today)
                if not pts:
                    raise RuntimeError("pusta historia")
                ok += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name} {kind}: {e}")
                pts = old.get(sid) or []             # błąd → zostaje poprzednia historia
            if not pts:
                continue
            series[sid] = pts
            c = change(pts, kind, end)
            c.update(first=iso(pts[0][0]), last=iso(pts[-1][0]), rank2y=hist_rank(pts, kind, end))
            row["m"][kind] = c
        ours.append(row)
    for sid, pts in old.items():                   # sieć usunięta z listy — historia zostaje do ręcznego usunięcia
        series.setdefault(sid, pts)

    if not ok:
        raise RuntimeError("DefiLlama: żadna seria naszych sieci nie została pobrana — " + "; ".join(errors[:5]))

    tot_stable = sum(stable_now.values())
    share = None
    if tot_stable:
        share = {"total": tot_stable, "rows": sorted(([c["name"], round(stable_now.get(c["name"], 0) / tot_stable * 100, 2)]
                                                      for c in cfg["list"]), key=lambda x: -x[1])}
        share["rest"] = round(100 - sum(x[1] for x in share["rows"]), 2)

    # 3) sieci spoza listy
    mine = {c["name"] for c in cfg["list"]}
    cand = [n for n in set(stable_now) | set(tvl_now) if n and n not in mine
            and max(stable_now.get(n, 0), tvl_now.get(n, 0)) >= cfg["cand_min"]]
    cand.sort(key=lambda n: -max(stable_now.get(n, 0), tvl_now.get(n, 0)))
    cand = cand[:cfg["max_cand"]]
    other, found, fails = {}, [], []
    keep_from = end - cfg["other_days"] * DAY
    for n in cand:
        got = {}
        for kind in ("dex", "stable"):
            url, params = url_for(kind, n)
            try:
                got[kind] = points(cl.get(url, params), kind, today)
            except Exception:  # noqa: BLE001 — nazwa bywa tylko w jednej liście DefiLlama (np. dYdX)
                got[kind] = []
                fails.append(f"{n} ({kind})")
        r = rising_check(n, got["dex"], got["stable"], end, cfg)
        if r:
            found.append(r)
        if got["dex"] or got["stable"]:
            other[n] = {k: [p for p in v if p[0] >= keep_from] for k, v in got.items() if v}
            other[n]["first"] = iso(min(v[0][0] for v in got.values() if v))
    found.sort(key=lambda r: -r["strength"])
    found = episodes(found, state.setdefault("rising", {}), end, cfg["gap_days"])
    shown = found[:cfg["max_rising"]]

    # 4) korekty DefiLlama (wartość z poprzedniego przebiegu vs po korektach)
    rev = revisions(state, {k: v for k, v in series.items() if k.endswith(("_dex", "_fees", "_stable"))}, end, now)
    rev_log = (_load(os.path.join(data_dir, "chains.json"), {}).get("revisions") or []) + rev
    rev_log = rev_log[-8 * len(cfg["list"]) * 3:]       # ok. 8 ostatnich dni

    summary = {
        "updated": int(now), "day": iso(end), "source": "DefiLlama",
        "chains": ours, "share": share,
        "rules": {k: cfg[k] for k in ("cand_min", "dex_ratio", "dex7_min", "stable30", "stable_min", "new_days",
                                      "new_dex7", "new_stable", "gap_days", "max_rising")},
        "candidates": len(cand), "rising": shown, "rising_all": len(found),
        "new_today": [r["name"] for r in shown if r["new"]],
        "revisions": rev_log, "errors": errors + ([f"sieci spoza listy: {len(fails)} nieudanych zapytań"] if fails else []),
        "calls": cl.calls,
    }
    _save(os.path.join(data_dir, "chains_1d.json"), {"updated": int(now), "series": series})
    _save(os.path.join(data_dir, "chains_other.json"), {"updated": int(now), "day": iso(end), "other": other})
    _save(os.path.join(data_dir, "chains.json"), summary)
    _save(os.path.join(data_dir, "state.json"), state)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import yaml
    with open(a.config, encoding="utf-8") as f:
        full = yaml.safe_load(f) or {}
    cfg = cfg_from(full)
    if not cfg.get("enabled", True):
        log.info("chains: wyłączone w config.yaml")
        return 0
    t0 = time.time()
    try:
        s = run(a.data_dir, cfg)
    except Exception as e:  # noqa: BLE001
        log.error("Sieci: %s", e)
        try:
            import alerts
            alerts.Telegram(tg_cfg=full.get("telegram") or {}).post(
                "system", f"⚠️ <b>Sieci (DefiLlama)</b>: przebieg nieudany — {str(e)[:300]}")
        except Exception:  # noqa: BLE001
            pass
        return 1
    mine_err = [e for e in s["errors"] if not e.startswith(("sieci spoza", "lista "))]
    if mine_err:
        try:
            import alerts
            alerts.Telegram(tg_cfg=full.get("telegram") or {}).post(
                "system", "⚠️ <b>Sieci (DefiLlama)</b>: część danych naszych sieci nie została pobrana "
                          "(zostaje poprzednia historia):\n" + "\n".join(mine_err[:8]))
        except Exception:  # noqa: BLE001
            pass
    log.info("Sieci: %d zapytań, %.0f s; kandydaci %d, rośnie %d (pokazane %d), nowe dziś %s; błędy: %s",
             s["calls"], time.time() - t0, s["candidates"], s["rising_all"], len(s["rising"]),
             s["new_today"] or "—", s["errors"] or "—")
    return 0


if __name__ == "__main__":
    sys.exit(main())
