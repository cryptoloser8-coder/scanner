"""Telegram alerts: levels, % changes, daily report, data-source health."""
import html
import logging
import os
import time

import requests

log = logging.getLogger("alerts")

HOUR = 3600


# ── formatting ───────────────────────────────────────────────
def fmt_value(v, group):
    if v is None:
        return "—"
    if group == "fund":
        return f"{v:+.1f}%/r"
    if group == "price":
        return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"
    if group in ("oi", "mcap", "liq"):
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
    if group == "pair":
        return f"{v:.5f}" if abs(v) < 1 else f"{v:.4g}"
    return f"{v:g}"


def fmt_change(now, before):
    if now is None or before in (None, 0):
        return "—"
    ch = (now / before - 1) * 100
    arrow = "▲" if ch > 0 else ("▼" if ch < 0 else "•")
    return f"{arrow}{ch:+.1f}%"


# ── telegram ─────────────────────────────────────────────────
class Telegram:
    """Sends messages. Routing (config `telegram`): market alerts and reports go to the group thread
    (group_chat_id / group_thread_id) when it is configured, system messages always to the admin
    (TELEGRAM_CHAT_ID, private chat)."""

    def __init__(self, token=None, chat_id=None, enabled=True, session=None, tg_cfg=None):
        self.token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")
        self.cfg = tg_cfg or {}
        self.enabled = enabled and bool(self.token and self.chat_id)
        self.session = session or requests.Session()
        self.sent = []          # texts (all targets) — used by tests and logs
        self.sent_to = []       # (kind, chat_id, thread_id, text)

    def target(self, kind="system"):
        """→ (chat_id, thread_id) for a message kind: system | market | report."""
        gid = self.cfg.get("group_chat_id")
        if kind in ("market", "report") and gid not in (None, "", 0):
            tid = self.cfg.get("group_thread_id")
            return str(gid), (int(tid) if tid not in (None, "", 0) else None)
        return self.chat_id, None

    def post(self, kind, text):
        chat, thread = self.target(kind)
        return self.send(text, chat_id=chat, thread_id=thread, kind=kind)

    def send(self, text, chat_id=None, thread_id=None, kind="system"):
        chat = chat_id or self.chat_id
        self.sent.append(text)
        self.sent_to.append((kind, chat, thread_id, text))
        if not self.enabled:
            log.info("[telegram wyłączony] %s", text.replace("\n", " | "))
            return False
        for chunk in _chunks_text(text, 3900):
            body = {"chat_id": chat, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}
            if thread_id:
                body["message_thread_id"] = int(thread_id)
            try:
                r = self.session.post(f"https://api.telegram.org/bot{self.token}/sendMessage", json=body, timeout=30)
                if r.status_code != 200:
                    log.error("Telegram HTTP %s: %s", r.status_code, r.text[:200])
                    return False
            except requests.RequestException as e:
                log.error("Telegram: %s", e)
                return False
        return True


def is_muted(mute_until, now):
    try:
        return bool(mute_until) and float(mute_until) > now
    except (TypeError, ValueError):
        return False


def fetch_mute(url, session=None, timeout=15):
    """mute_until (unix ts) published by the Orange Pi in ema.json (/cisza); None when unknown."""
    if not url:
        return None
    try:
        r = (session or requests).get(url, params={"t": int(time.time())}, timeout=timeout)
        r.raise_for_status()
        return r.json().get("mute_until")
    except Exception as e:  # noqa: BLE001
        log.warning("Stan wyciszenia (%s): %s", url, e)
        return None


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
    """Alert once when entering the `near_pct` zone and once on each cross.
    direction (optional): up = only crosses upward and approaching from below; down = the opposite; default both."""
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
        want = str(lv.get("direction") or "both").lower()
        ok_side = want not in ("up", "down") or (want == "up") == (side == "above")   # przebicie w tę stronę się liczy
        ok_near = want not in ("up", "down") or (want == "up") == (side == "below")   # zbliżanie z tej strony
        if s.get("side") and s["side"] != side:
            if ok_side:
                direction = "w górę ⬆️" if side == "above" else "w dół ⬇️"
                msgs.append(f"🚨 {head} przebił poziom {direction}\n{label} ({fmt_value(level, meta['group'])})")
            s["zone"] = "near"
        elif abs(dist) <= near and s.get("zone") != "near" and ok_near:
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


def window_sum(store, sid, hours):
    """Sum of the last `hours` hourly candles of a series → (sum, last_t) or (None, None)."""
    s = store.series["1h"].get(sid) or {}
    if not s:
        return None, None
    t_last = max(s)
    return sum(v for t, v in s.items() if t > t_last - hours * HOUR), t_last


def liq_parts(store, catalog, sid, hours):
    """liq_btc → long + short; liq_btc_long / liq_ex_x → itself. → (total, long, short, name)."""
    if f"{sid}_long" in catalog:
        lo, _ = window_sum(store, f"{sid}_long", hours)
        sh, _ = window_sum(store, f"{sid}_short", hours)
        if lo is None or sh is None:
            return None
        return lo + sh, lo, sh, catalog[f"{sid}_long"]["name"].rsplit(" ", 1)[0]
    if sid in catalog:
        v, _ = window_sum(store, sid, hours)
        return None if v is None else (v, None, None, catalog[sid]["name"])
    return None


def check_sums(store, catalog, rules, state, now):
    """Alert when the sum of a liquidation series over the window ≥ usd (with cooldown).

    rule: {series: liq_btc | liq_total | liq_btc_long | liq_ex_hyperliquid…, window_hours, usd, cooldown_hours}
    """
    msgs = []
    st = state.setdefault("sums", {})
    for r in rules or []:
        sid = r.get("series")
        win = float(r.get("window_hours", 4))
        usd = float(r.get("usd") or 0)
        if not sid or usd <= 0:
            continue
        parts = liq_parts(store, catalog, sid, win)
        if not parts:
            log.warning("Alert sumy pominięty (nieznana seria lub brak danych): %s", r)
            continue
        total, lo, sh, name = parts
        key = f"{sid}:{win:g}h:{usd:g}"
        cooldown = float(r.get("cooldown_hours", 12)) * HOUR
        if total >= usd and now - st.get(key, 0) >= cooldown:
            split = f"\nlong {fmt_value(lo, 'liq')} · short {fmt_value(sh, 'liq')}" if lo is not None else ""
            label = f"\n{html.escape(r['label'])}" if r.get("label") else ""
            msgs.append(f"💥 <b>{html.escape(name)}</b>: {fmt_value(total, 'liq')} w {win:g}h "
                        f"(próg {fmt_value(usd, 'liq')}){split}{label}")
            st[key] = now
    return msgs


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
