"""Manual Fibonacci setups with alerts (runs on the Orange Pi inside ema_monitor).

A setup = coin + swing high + swing low + direction (+ optional label). You pick the swing
yourself (any interval, long or short term); the Pi watches the price every 5 minutes.

  long  (pullback after a rise):  level(r) = high − r × (high − low)   → zone below the high
  short (bounce after a fall):    level(r) = low  + r × (high − low)   → zone above the low

Zone = 0.705–0.786 with the 0.75 line. Status: far → near → zone → deep (past 0.786) → invalid
(beyond the swing low/high). Alerts: near (once, re-armed after moving away), entering the zone,
breaking through 0.786, invalidation.

Setups come from config.yaml (`fib:`) and from Telegram commands (stored on the Pi):
  /fib SOL 250 120 [long|short] [opis]   /fiby   /usun ID   /pomoc
"""
import html
import logging
import math
import re
import time

import requests

log = logging.getLogger("fib")

ZONE = (0.705, 0.75, 0.786)
STATUS_PL = {"above": "przed strefą", "near": "blisko strefy", "zone": "w strefie",
             "deep": "za 0.786", "invalid": "unieważniony"}


def fmt(v):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1000:
        return f"${v:,.0f}"
    if a >= 1:
        return f"${v:,.2f}"
    if a == 0:
        return "$0"
    return f"${v:.{3 - math.floor(math.log10(a))}f}"


def levels(high, low, direction):
    r = high - low
    if direction == "short":
        return {z: low + z * r for z in ZONE}
    return {z: high - z * r for z in ZONE}


def evaluate(setup, price, near_pct):
    """→ dict with levels, status and distance (%) to the zone edge (0 inside the zone)."""
    h, l_, d = float(setup["high"]), float(setup["low"]), setup.get("dir", "long")
    lv = levels(h, l_, d)
    z_in, z_mid, z_out = lv[ZONE[0]], lv[ZONE[1]], lv[ZONE[2]]
    out = {"l705": z_in, "l75": z_mid, "l786": z_out, "price": price}
    if price is None:
        out.update(status=None, dist=None)
        return out
    if d == "long":
        if price <= l_:
            st, dist = "invalid", (price / z_out - 1) * 100
        elif price < z_out:
            st, dist = "deep", (price / z_out - 1) * 100
        elif price <= z_in:
            st, dist = "zone", 0.0
        else:
            dist = (price / z_in - 1) * 100
            st = "near" if dist <= near_pct else "above"
    else:
        if price >= h:
            st, dist = "invalid", (price / z_out - 1) * 100
        elif price > z_out:
            st, dist = "deep", (price / z_out - 1) * 100
        elif price >= z_in:
            st, dist = "zone", 0.0
        else:
            dist = (price / z_in - 1) * 100
            st = "near" if -dist <= near_pct else "above"
    out.update(status=st, dist=dist)
    return out


def describe(setup):
    lab = f" — {html.escape(setup['label'])}" if setup.get("label") else ""
    return f"<b>{html.escape(setup['coin'])}</b> {setup.get('dir', 'long')} [{setup['id']}]{lab}"


def check(setups, prices, st, near_pct, rearm=1.5, arm_only=False):
    """st: {setup_id: {"status":…, "near_armed":…}} (mutated) → list of message lines."""
    msgs = []
    for s in setups:
        ev = evaluate(s, prices.get(s["coin"]), near_pct)
        s["_ev"] = ev
        if ev["status"] is None:
            continue
        prev = st.get(s["id"], {})
        new = {"status": ev["status"], "near_sent": prev.get("near_sent", False)}
        head = describe(s)
        zone_txt = f"strefa {fmt(ev['l705'])}–{fmt(ev['l786'])}, 0.75 = {fmt(ev['l75'])}"
        if not prev or arm_only:
            new["near_sent"] = ev["status"] in ("near", "zone", "deep")
            st[s["id"]] = new
            continue
        p, cur = prev.get("status"), ev["status"]
        if cur == "near" and not prev.get("near_sent"):
            msgs.append(f"⚠️ {head}: zbliża się do strefy Fibo ({ev['dist']:+.2f}%, cena {fmt(ev['price'])}; {zone_txt})")
            new["near_sent"] = True
        if cur == "zone" and p != "zone":
            msgs.append(f"🎯 {head}: cena w strefie Fibo 0.705–0.786 ({fmt(ev['price'])}; {zone_txt})")
            new["near_sent"] = True
        if cur == "deep" and p in ("zone", "near", "above"):
            msgs.append(f"⬇️ {head}: cena przebiła 0.786 ({fmt(ev['price'])}, 0.786 = {fmt(ev['l786'])})")
        if cur == "invalid" and p != "invalid":
            ext = "dołek" if s.get("dir", "long") == "long" else "szczyt"
            msgs.append(f"❌ {head}: setup unieważniony — cena przebiła {ext} ruchu ({fmt(ev['price'])})")
        # re-arm the "near" alert once the price has moved clearly away from the zone
        if cur == "above" and abs(ev["dist"]) > near_pct * rearm:
            new["near_sent"] = False
        st[s["id"]] = new
    for k in [k for k in st if k not in {s["id"] for s in setups}]:
        del st[k]
    return msgs


# ── setups: config + Telegram ────────────────────────────────
def from_config(items):
    out = []
    for i, it in enumerate(items or []):
        try:
            h, l_ = float(it["high"]), float(it["low"])
        except (KeyError, TypeError, ValueError):
            log.warning("Fibo z configu pominięte (brak high/low): %s", it)
            continue
        if h <= l_:
            log.warning("Fibo z configu pominięte (high ≤ low): %s", it)
            continue
        d = str(it.get("dir") or it.get("kierunek") or "long").lower()
        out.append({"id": f"c{i + 1}", "coin": str(it["coin"]).upper(), "high": h, "low": l_,
                    "dir": "short" if d.startswith("s") else "long", "label": it.get("label") or "",
                    "src": "config"})
    return out


_NUM = r"[0-9]+(?:[.,][0-9]+)?"
HELP = ("<b>Fibo — komendy</b>\n"
        "/fib COIN SZCZYT DOŁEK [long|short] [opis] — dodaj setup\n"
        "   np. <code>/fib SOL 250 120 long term</code>\n"
        "   long = cofnięcie po wzroście (strefa pod szczytem), short = odbicie po spadku\n"
        "/fiby — lista setupów ze statusem\n"
        "/usun ID — usuń setup (np. /usun 3)\n"
        "Setupy z config.yaml (id c1, c2…) usuwasz w configu.")


def parse_command(text):
    """→ ("add", setup) | ("list", None) | ("del", id) | ("help", None) | ("error", msg) | None."""
    t = (text or "").strip()
    if not t.startswith("/"):
        return None
    cmd, _, rest = t.partition(" ")
    cmd = cmd.split("@")[0].lower()
    if cmd in ("/pomoc", "/help", "/start"):
        return "help", None
    if cmd in ("/fiby", "/lista"):
        return "list", None
    if cmd in ("/usun", "/usuń", "/del"):
        m = re.match(r"\s*(\w+)", rest)
        return ("del", m.group(1)) if m else ("error", "Podaj id, np. /usun 3")
    if cmd == "/fib":
        m = re.match(rf"\s*([A-Za-z0-9]+)\s+({_NUM})\s+({_NUM})\s*(.*)$", rest)
        if not m:
            return "error", "Składnia: /fib COIN SZCZYT DOŁEK [long|short] [opis], np. /fib SOL 250 120 long term"
        coin, a, b, tail = m.group(1).upper(), float(m.group(2).replace(",", ".")), \
            float(m.group(3).replace(",", ".")), m.group(4).strip()
        if a == b:
            return "error", "Szczyt i dołek muszą być różne"
        h, l_ = max(a, b), min(a, b)
        d = "long"
        first = tail.split(" ", 1)[0].lower() if tail else ""
        if first in ("long", "short", "l", "s"):
            d = "short" if first.startswith("s") else "long"
            tail = tail[len(first):].strip()
        return "add", {"coin": coin, "high": h, "low": l_, "dir": d, "label": tail[:80]}
    return None


class Bot:
    """Minimal Telegram polling (getUpdates, no webhook). Only messages from `chat_id` are handled."""

    def __init__(self, token, chat_id, session=None):
        self.token, self.chat_id = token, str(chat_id)
        self.s = session or requests.Session()

    def updates(self, offset):
        r = self.s.get(f"https://api.telegram.org/bot{self.token}/getUpdates",
                       params={"offset": offset, "timeout": 0, "allowed_updates": '["message"]'}, timeout=30)
        r.raise_for_status()
        return r.json().get("result", [])

    def reply(self, text):
        self.s.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": True}, timeout=30)


def handle_commands(bot, st, config_setups, prices, near_pct, now=None):
    """Process pending Telegram commands. st["fib_user"] = user setups, st["tg_offset"] = last update."""
    now = int(now or time.time())
    user = st.setdefault("fib_user", [])
    try:
        ups = bot.updates(st.get("tg_offset", 0))
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram getUpdates: %s", e)
        return 0
    handled = 0
    for u in ups:
        st["tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != bot.chat_id:
            continue
        if msg.get("date") and now - int(msg["date"]) > 86400:
            continue                     # ignore stale messages (e.g. sent before the bot was set up)
        parsed = parse_command(msg.get("text"))
        if not parsed:
            continue
        handled += 1
        kind, arg = parsed
        if kind == "help":
            bot.reply(HELP)
        elif kind == "error":
            bot.reply("❓ " + html.escape(arg))
        elif kind == "add":
            nid = str(max([int(s["id"]) for s in user if str(s["id"]).isdigit()] + [0]) + 1)
            setup = dict(arg, id=nid, src="telegram", added=now)
            user.append(setup)
            ev = evaluate(setup, prices.get(setup["coin"]), near_pct)
            if ev["price"] is None:
                price_txt = "⚠️ brak ceny dla tego coina na Binance i Hyperliquid"
            else:
                dist_txt = "" if ev["dist"] in (None, 0) else " ({:+.2f}%)".format(ev["dist"])
                price_txt = "cena {} — {}{}".format(fmt(ev["price"]), STATUS_PL.get(ev["status"], ""), dist_txt)
            bot.reply(f"✅ Dodano {describe(setup)}\nszczyt {fmt(setup['high'])}, dołek {fmt(setup['low'])}\n"
                      f"0.705 = {fmt(ev['l705'])} · <b>0.75 = {fmt(ev['l75'])}</b> · 0.786 = {fmt(ev['l786'])}\n{price_txt}")
        elif kind == "del":
            before = len(user)
            user[:] = [s for s in user if str(s["id"]) != str(arg)]
            if len(user) < before:
                bot.reply(f"🗑 Usunięto setup {html.escape(str(arg))}")
            elif any(s["id"] == arg for s in config_setups):
                bot.reply(f"Setup {html.escape(arg)} jest w config.yaml — usuń go tam.")
            else:
                bot.reply(f"Nie ma setupu o id {html.escape(str(arg))}. Lista: /fiby")
        elif kind == "list":
            allset = config_setups + user
            if not allset:
                bot.reply("Brak setupów. Dodaj: /fib COIN SZCZYT DOŁEK [long|short] [opis]")
            else:
                lines = ["<b>Setupy Fibo</b>"]
                for s in allset:
                    ev = evaluate(s, prices.get(s["coin"]), near_pct)
                    stt = STATUS_PL.get(ev["status"], "brak ceny")
                    dist = "" if ev["dist"] in (None, 0) else f" {ev['dist']:+.1f}%"
                    lines.append(f"{describe(s)}: {stt}{dist} · 0.75 = {fmt(ev['l75'])}")
                bot.reply("\n".join(lines))
    return handled


def hyperliquid_mids(session=None):
    s = session or requests.Session()
    r = s.post("https://api.hyperliquid.xyz/info", json={"type": "allMids"}, timeout=30)
    r.raise_for_status()
    return {k.upper(): float(v) for k, v in r.json().items() if not k.startswith("@")}


def coin_prices(coins, binance_prices, quote="USDT", hl=hyperliquid_mids):
    """Binance */USDT price for each coin, Hyperliquid mid for the missing ones."""
    out, missing = {}, []
    for c in coins:
        p = binance_prices.get(f"{c}{quote}")
        if p:
            out[c] = p
        else:
            missing.append(c)
    if missing and hl:
        try:
            mids = hl()
            for c in missing:
                if c in mids:
                    out[c] = mids[c]
        except Exception as e:  # noqa: BLE001
            log.warning("Hyperliquid allMids: %s", e)
    return out


def publish_rows(setups, hist_coins):
    rows = []
    for s in setups:
        ev = s.get("_ev") or {}
        rows.append({"id": s["id"], "coin": s["coin"], "dir": s.get("dir", "long"), "label": s.get("label", ""),
                     "high": s["high"], "low": s["low"], "src": s.get("src"), "added": s.get("added"),
                     "l705": ev.get("l705"), "l75": ev.get("l75"), "l786": ev.get("l786"),
                     "price": ev.get("price"), "status": ev.get("status"), "dist": ev.get("dist"),
                     "chart": s["coin"] in hist_coins})
    return rows


# ── automatic proposals (shown on the page only) ─────────────
PROPOSAL_DEFAULTS = {"windows": [30, 90, 365], "min_move_pct": 8.0, "vol_mult": 4.0,
                     "near_pct": 5.0, "max": 60, "hl_days": 400}
WINDOW_NAME = {30: "1M", 90: "3M", 365: "1R"}


def daily_vol_pct(hl, n=30):
    """Median daily range (high−low)/low in % over the last n days."""
    xs = sorted((h - l_) / l_ * 100 for _, h, l_ in hl[-n:] if l_ > 0)
    return xs[len(xs) // 2] if xs else None


def candidates(coin, hl, pcfg):
    """Main move in each window → list of raw candidates (status computed later with the live price).

    hl: [[t, high, low], ...] closed daily candles, oldest first.
    """
    out = []
    if len(hl) < 20:
        return out
    dvol = daily_vol_pct(hl)
    if not dvol:
        return out
    need = max(float(pcfg["min_move_pct"]), float(pcfg["vol_mult"]) * dvol)
    seen = {}
    for w in pcfg["windows"]:
        win = hl[-int(w):]
        if len(win) < min(int(w), 20):
            continue
        i_hi = max(range(len(win)), key=lambda i: win[i][1])
        i_lo = min(range(len(win)), key=lambda i: win[i][2])
        hi, lo = win[i_hi][1], win[i_lo][2]
        if lo <= 0 or i_hi == i_lo:
            continue
        move = (hi / lo - 1) * 100
        if move < need:
            continue
        d = "long" if i_lo < i_hi else "short"
        key = (round(hi, 12), round(lo, 12), d)
        name = WINDOW_NAME.get(int(w), f"{int(w)}d")
        if key in seen:
            seen[key]["win"] += "/" + name
            continue
        c = {"coin": coin, "dir": d, "high": hi, "low": lo, "t_high": win[i_hi][0], "t_low": win[i_lo][0],
             "win": name, "move": move, "dvol": dvol}
        seen[key] = c
        out.append(c)
    return out


def proposals(cands, prices, pcfg):
    """Live status for raw candidates → only those in the zone or approaching it (≤ near_pct), sorted."""
    near = float(pcfg["near_pct"])
    out = []
    for c in cands:
        p = prices.get(c["coin"])
        if p is None:
            continue
        ev = evaluate(c, p, near)
        if ev["status"] not in ("zone", "near"):
            continue
        out.append(dict(c, **{k: ev[k] for k in ("l705", "l75", "l786", "price", "status", "dist")}))
    out.sort(key=lambda r: (0 if r["status"] == "zone" else 1, abs(r["dist"] or 0)))
    return out[:int(pcfg["max"])]


def command_for(p):
    def num(v):
        return f"{v:.6g}"
    return f"/fib {p['coin']} {num(p['high'])} {num(p['low'])} {p['dir']} auto {p['win']}"
