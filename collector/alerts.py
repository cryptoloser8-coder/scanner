"""Telegram alerts: levels, % changes, daily report, data-source health."""
import html
import logging
import os
from datetime import datetime, timezone

import requests

log = logging.getLogger("alerts")

HOUR = 3600


# ── formatting ───────────────────────────────────────────────
def fmt_value(v, group):
    if v is None:
        return "—"
    if group in ("oi", "mcap"):
        a = abs(v)
        if a >= 1e12:
            return f"${v / 1e12:.3f}T"
        if a >= 1e9:
            return f"${v / 1e9:.2f}B"
        if a >= 1e6:
            return f"${v / 1e6:.1f}M"
        return f"${v:,.0f}"
    if group == "pct":
        return f"{v:.2f}%"
    if group == "ratio":
        return f"{v:.3f}×"
    return f"{v:g}"


def fmt_change(now, before):
    if now is None or before in (None, 0):
        return "—"
    ch = (now / before - 1) * 100
    arrow = "▲" if ch > 0 else ("▼" if ch < 0 else "•")
    return f"{arrow}{ch:+.1f}%"


# ── telegram ─────────────────────────────────────────────────
class Telegram:
    def __init__(self, token=None, chat_id=None, enabled=True, session=None):
        self.token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")
        self.enabled = enabled and bool(self.token and self.chat_id)
        self.session = session or requests.Session()
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        if not self.enabled:
            log.info("[telegram wyłączony] %s", text.replace("\n", " | "))
            return False
        for chunk in _chunks_text(text, 3900):
            try:
                r = self.session.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": chunk, "parse_mode": "HTML",
                          "disable_web_page_preview": True},
                    timeout=30,
                )
                if r.status_code != 200:
                    log.error("Telegram HTTP %s: %s", r.status_code, r.text[:200])
                    return False
            except requests.RequestException as e:
                log.error("Telegram: %s", e)
                return False
        return True


def _chunks_text(text, n):
    lines, buf = text.split("\n"), ""
    for ln in lines:
        if len(buf) + len(ln) + 1 > n and buf:
            yield buf
            buf = ""
        buf += ln + "\n"
    if buf:
        yield buf


# ── rules ────────────────────────────────────────────────────
def check_levels(store, catalog, levels, state, page_url=""):
    """Alert once when entering the `near_pct` zone and once on each cross."""
    msgs = []
    st = state.setdefault("levels", {})
    active_keys = set()
    for lv in levels or []:
        sid, level = lv.get("series"), lv.get("level")
        if sid not in catalog or level in (None, 0):
            log.warning("Poziom pominięty (nieznana seria lub brak level): %s", lv)
            continue
        level = float(level)
        near = float(lv.get("near_pct", 3))
        key = f"{sid}@{level:g}"
        active_keys.add(key)
        latest = store.latest(sid)
        if not latest:
            continue
        _, v = latest
        dist = (v - level) / level * 100
        side = "above" if v >= level else "below"
        s = st.get(key, {})
        meta = catalog[sid]
        label = html.escape(lv.get("label") or f"{meta['name']} {fmt_value(level, meta['group'])}")
        head = f"<b>{html.escape(meta['name'])}</b> {fmt_value(v, meta['group'])}"
        if s.get("side") and s["side"] != side:
            direction = "w górę ⬆️" if side == "above" else "w dół ⬇️"
            msgs.append(f"🚨 {head} przebił poziom {direction}\n{label} ({fmt_value(level, meta['group'])})")
            s["zone"] = "near"
        elif abs(dist) <= near and s.get("zone") != "near":
            where = "od dołu" if side == "below" else "od góry"
            msgs.append(f"⚠️ {head} zbliża się do poziomu {where}: {dist:+.2f}%\n{label} "
                        f"({fmt_value(level, meta['group'])})")
            s["zone"] = "near"
        elif abs(dist) > near * 1.5:
            s["zone"] = "far"
        s["side"] = side
        st[key] = s
    for k in [k for k in st if k not in active_keys]:
        del st[k]
    return msgs


def check_changes(store, catalog, rules, state, now):
    msgs = []
    st = state.setdefault("changes", {})
    for r in rules or []:
        sid = r.get("series")
        if sid not in catalog:
            continue
        win = float(r.get("window_hours", 24))
        pct = float(r.get("pct", 10))
        cooldown = float(r.get("cooldown_hours", 12)) * HOUR
        key = f"{sid}:{win:g}h:{pct:g}"
        latest = store.latest(sid)
        if not latest:
            continue
        t, v = latest
        before = store.value_at(sid, t - win * HOUR, "1h" if win < 72 else "1d",
                                tolerance=2 * HOUR if win < 72 else 2 * 86400)
        if not before:
            continue
        ch = (v / before - 1) * 100
        if abs(ch) >= pct and now - st.get(key, 0) >= cooldown:
            meta = catalog[sid]
            msgs.append(f"📈 <b>{html.escape(meta['name'])}</b> {ch:+.1f}% w {win:g}h "
                        f"({fmt_value(before, meta['group'])} → {fmt_value(v, meta['group'])})")
            st[key] = now
    return msgs


REPORT_IDS = ["total", "total2", "total3", "btc_d", "usdt_d",
              "oi_btc", "oi_alts", "oi_others", "oi_btc_dom", "oi_alts_vs_btc", "lev_others"]


def daily_report(store, catalog, levels, page_url=""):
    lines = ["📊 <b>Dzienny raport OI & TOTAL</b>", ""]
    for sid in REPORT_IDS:
        meta = catalog.get(sid)
        latest = store.latest(sid)
        if not meta or not latest:
            continue
        t, v = latest
        d1 = store.value_at(sid, t - 86400, "1d", tolerance=2 * 86400)
        d7 = store.value_at(sid, t - 7 * 86400, "1d", tolerance=2 * 86400)
        lines.append(f"<b>{html.escape(meta['name'])}</b> {fmt_value(v, meta['group'])}  "
                     f"1D {fmt_change(v, d1)} · 7D {fmt_change(v, d7)}")
    near = []
    for lv in levels or []:
        sid = lv.get("series")
        meta = catalog.get(sid)
        latest = store.latest(sid)
        if not meta or not latest or not lv.get("level"):
            continue
        dist = (latest[1] - float(lv["level"])) / float(lv["level"]) * 100
        near.append((abs(dist), f"{html.escape(lv.get('label') or meta['name'])}: {dist:+.2f}%"))
    if near:
        lines += ["", "<b>Odległość od poziomów:</b>"] + [s for _, s in sorted(near)[:8]]
    if page_url:
        lines += ["", f'<a href="{page_url}">Otwórz wykresy</a>']
    return "\n".join(lines)


def due_daily_report(state, now, hour_utc):
    dt = datetime.fromtimestamp(now, timezone.utc)
    today = dt.strftime("%Y-%m-%d")
    if dt.hour >= int(hour_utc) and state.get("last_report") != today:
        state["last_report"] = today
        return True
    return False


def health_messages(state, results, now, reminder_hours=12):
    """results: {source: error_str or None}. Alert on failure, remind, notify recovery."""
    msgs = []
    st = state.setdefault("health", {})
    for src, err in results.items():
        s = st.get(src, {})
        if err:
            if not s.get("failing"):
                msgs.append(f"❗ Źródło <b>{src}</b> nie działa: {html.escape(str(err))[:300]}")
                s = {"failing": True, "since": now, "last_alert": now}
            elif now - s.get("last_alert", 0) >= reminder_hours * HOUR:
                hrs = (now - s.get("since", now)) / HOUR
                msgs.append(f"❗ <b>{src}</b> nadal nie działa ({hrs:.0f}h): {html.escape(str(err))[:200]}")
                s["last_alert"] = now
            s["error"] = str(err)[:300]
        else:
            if s.get("failing"):
                msgs.append(f"✅ Źródło <b>{src}</b> znowu działa")
            s = {"failing": False, "ok_at": now}
        st[src] = s
    return msgs
