"""Telegram bot + scan scheduler on the Orange Pi — runs every minute from cron:

  * * * * * flock -n /tmp/scanner-bot.lock python3 $HOME/scanner/collector/bot.py >> $HOME/scanner-bot.log 2>&1

Every run:
  1. answers commands (Telegram getUpdates; the only program reading this bot's messages),
  2. starts scheduled OI scans and report scans (GitHub workflow_dispatch, config `schedule`, Polish time),
  3. every 15 min checks that the GitHub scans deliver fresh data and that scheduled reports appeared.
Problems go to the admin only (private chat). Code and config update themselves (ema_cron.sh does git pull).

State: ~/.ema-monitor/bot.json (Telegram Fibo setups, mute, offset, schedule) — never in the public repo.
Env:   ~/.scanner_env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID = admin), ~/.scanner_token (GitHub token).

Commands are defined once in COMMANDS below: /pomoc and the Telegram command menu are generated from it.
"""
import argparse
import hashlib
import html
import json
import logging
import os
import re
import sys
import time

import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alerts  # noqa: E402
import fib as F  # noqa: E402
import timetable as TT  # noqa: E402
from ema_monitor import _read, _write, load_env  # noqa: E402

log = logging.getLogger("bot")
HOUR = 3600
STALE_COMMAND_S = 1800          # ignore commands older than 30 min (e.g. after the Pi was off)
WATCH_EVERY_S = 900             # freshness checks every 15 min
REPORT_LATE_S = 75 * 60         # a scheduled report should exist ~45 min after its scan started


# ── command registry ─────────────────────────────────────────
class Cmd:
    def __init__(self, name, desc, handler, admin=False, usage="", aliases=()):
        self.name, self.desc, self.handler, self.admin = name, desc, handler, admin
        self.usage, self.aliases = usage, tuple(aliases)


def _registry():
    return [
        Cmd("pomoc", "Lista komend", h_pomoc, aliases=("help", "start")),
        Cmd("status", "Stan systemu: świeżość danych, następny skan i raport", h_status),
        Cmd("raport", "Linki do ostatnich raportów: dziennego, tygodniowego i miesięcznego", h_raport),
        Cmd("fiby", "Setupy Fibo ze statusem", h_fiby, aliases=("lista",)),
        Cmd("skan", "Uruchom skan OI/TOTAL teraz (~40 min)", h_skan, admin=True),
        Cmd("raport_teraz", "Zbuduj raport z obecnych danych (skan: najpierw skan, ~45 min; tydzień / miesiąc: "
            "raport tygodniowy / miesięczny za ostatni pełny okres)", h_raport_teraz, admin=True,
            usage="[skan|tydzień|miesiąc]"),
        Cmd("usun_raport", "Usuń raport z historii (ID z adresu raportu: ?id=…; kilka po przecinku)", h_usun_raport,
            admin=True, usage="ID"),
        Cmd("cisza", "Wycisz alerty rynkowe (domyślnie 8h; off = włącz)", h_cisza, admin=True, usage="[8h|30m|2d|off]"),
        Cmd("fib", "Dodaj setup Fibo", h_fib, admin=True, usage="COIN SZCZYT DOŁEK [long|short] [opis]"),
        Cmd("usun", "Usuń setup Fibo", h_usun, admin=True, usage="ID", aliases=("usuń", "del")),
        Cmd("watek", "Pokaż id czatu i wątku (do config.yaml)", h_watek, admin=True),
    ]


def find(name):
    name = name.lower()
    for c in COMMANDS:
        if name == c.name or name in c.aliases:
            return c
    return None


def menu(admin):
    return [{"command": c.name, "description": c.desc[:256]} for c in COMMANDS if admin or not c.admin]


# ── Telegram / GitHub / raw data ─────────────────────────────
class TgApi:
    def __init__(self, token, session=None):
        self.token = token
        self.s = session or requests.Session()

    def call(self, method, **params):
        r = self.s.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params, timeout=40)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: HTTP {r.status_code} {data.get('description', r.text[:200])}")
        return data.get("result")

    def get_updates(self, offset):
        return self.call("getUpdates", offset=offset, timeout=0, allowed_updates=["message"]) or []

    def get_me(self):
        return self.call("getMe")

    def set_commands(self, commands, scope):
        return self.call("setMyCommands", commands=commands, scope=scope)

    def send(self, chat_id, text, thread_id=None, reply_to=None):
        body = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if thread_id:
            body["message_thread_id"] = int(thread_id)
        if reply_to:
            body["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
        return self.call("sendMessage", **body)


class GitHub:
    def __init__(self, token, repo, session=None):
        self.token, self.repo = token, repo
        self.s = session or requests.Session()

    def dispatch(self, workflow, inputs):
        """→ (ok, error text). Starts .github/workflows/<workflow> on main."""
        if not self.token:
            return False, "brak tokenu GitHub (~/.scanner_token)"
        try:
            r = self.s.post(f"https://api.github.com/repos/{self.repo}/actions/workflows/{workflow}/dispatches",
                            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                                     "X-GitHub-Api-Version": "2022-11-28"},
                            json={"ref": "main", "inputs": inputs}, timeout=30)
        except requests.RequestException as e:
            return False, f"sieć: {e}"
        if r.status_code == 204:
            return True, None
        hint = " (token wygasł albo nie ma uprawnienia Actions)" if r.status_code in (401, 403) else ""
        return False, f"HTTP {r.status_code}{hint}: {r.text[:150]}"


def raw_fetcher(repo, session=None):
    s = session or requests.Session()

    def fetch(branch, name):
        try:
            r = s.get(f"https://raw.githubusercontent.com/{repo}/{branch}/{name}", params={"t": int(time.time())}, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("raw %s/%s: %s", branch, name, e)
            return None
    return fetch


def price_lookup(state_dir, session=None):
    """Prices for /fib and /fiby: last EMA run (pub/ema.json), then Binance ticker, then Hyperliquid."""
    s = session or requests.Session()

    def prices(coins):
        coins = {c.upper() for c in coins}
        e = _read(os.path.join(state_dir, "pub", "ema.json"), {}) or {}
        known = {c.get("s"): c.get("p") for c in e.get("coins") or []}
        out = {c: known[c] for c in coins if known.get(c)}
        for c in [c for c in coins if c not in out]:
            try:
                r = s.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": f"{c}USDT"}, timeout=15)
                if r.status_code == 200:
                    out[c] = float(r.json()["price"])
            except Exception:  # noqa: BLE001
                pass
        missing = [c for c in coins if c not in out]
        if missing:
            out.update(F.coin_prices(missing, {}, hl=F.hyperliquid_mids))
        return out
    return prices


# ── context ──────────────────────────────────────────────────
class Ctx:
    def __init__(self, cfg, st, now, admin, api, gh, fetch, prices, state_dir, tg):
        self.cfg, self.st, self.now, self.admin = cfg, st, int(now), str(admin)
        self.api, self.gh, self.fetch, self.prices, self.state_dir, self.tg = api, gh, fetch, prices, state_dir, tg
        self.sc = TT.load(cfg.get("schedule"))
        self.health = {}          # source → error or None (only sources checked in this run)
        self.me = (st.get("me") or {}).get("username", "")

    @property
    def tgcfg(self):
        return self.cfg.get("telegram") or {}

    @property
    def group_id(self):
        g = self.tgcfg.get("group_chat_id")
        return str(g) if g not in (None, "", 0) else ""

    def t(self, ts, fmt="%H:%M"):
        return TT.local(ts, self.sc, fmt)

    def fib_cfg(self):
        f = self.cfg.get("fib") or {}
        return float(f.get("near_pct", 2) or 2), F.from_config(f.get("setups") or [])


def ago(sec):
    sec = max(0, int(sec))
    if sec < 3600:
        return f"{sec // 60} min temu"
    h, m = divmod(sec // 60, 60)
    return f"{h} h {m} min temu" if h < 48 else f"{h // 24} dni temu"


# ── handlers: general ────────────────────────────────────────
def h_pomoc(ctx, msg, args):
    admin = _is_admin(ctx, msg)
    lines = ["<b>Komendy</b>"]
    for c in COMMANDS:
        if not c.admin:
            lines.append(f"/{c.name}{' ' + html.escape(c.usage) if c.usage else ''} — {html.escape(c.desc)}")
    if admin:
        lines += ["", "<b>Administrator</b>"]
        for c in COMMANDS:
            if c.admin:
                lines.append(f"/{c.name}{' ' + html.escape(c.usage) if c.usage else ''} — {html.escape(c.desc)}")
        lines += ["", "Przykład: <code>/fib SOL 250 120 long term</code> (long = cofnięcie po wzroście, "
                      "short = odbicie po spadku). Ustawienia (alerty, harmonogram, grupa): config.yaml na GitHubie."]
    return "\n".join(lines)


def h_status(ctx, msg, args):
    return status_text(ctx)


def status_text(ctx):
    now = ctx.now
    lines = ["📡 <b>Status systemu</b> (czas PL)"]
    meta = ctx.fetch("data", "meta.json")
    if meta and meta.get("updated"):
        age = now - meta["updated"]
        limit = (int(ctx.sc.get("scan_every_hours") or 2) + 1.5) * HOUR
        icon = "✅" if age <= limit else "❗"
        lines.append(f"{icon} Skany OI/TOTAL (GitHub): ostatni start {ctx.t(meta['updated'])}, {ago(age)}")
        hl = meta.get("health") or {}
        if hl:
            lines.append("    źródła: " + " · ".join(f"{html.escape(k)} {'ok' if v == 'ok' else '❗'}" for k, v in hl.items()))
    else:
        lines.append("❔ Skany OI/TOTAL: brak odpowiedzi z GitHuba")
    est = _read(os.path.join(ctx.state_dir, "state.json"), {}) or {}
    pa = est.get("published_at")
    if pa:
        icon = "✅" if now - pa <= HOUR else "❗"
        lines.append(f"{icon} EMA200/Fibo (Orange Pi): opublikowane {ctx.t(pa)}, {ago(now - pa)}")
    idx = ctx.fetch("reports", "index.json")
    reps = (idx or {}).get("reports") or []
    if reps:
        r = reps[0]
        lines.append(f"📊 Ostatni raport: <a href=\"{_report_url(ctx, r['id'])}\">{html.escape(r['title'])}</a>, "
                     f"{ctx.t(r['created'], '%d.%m %H:%M')}")
    nxt = TT.upcoming(ctx.sc, now, 1)
    nrep = TT.upcoming(ctx.sc, now, 1, only="report")
    if nxt:
        lines.append(f"⏭ Następny skan: {nxt[0]['at'].strftime('%H:%M')}")
    if nrep:
        e = nrep[0]
        lines.append(f"⏭ Następny raport: {_kind_title(e['kind'])} — skan {e['at'].strftime('%d.%m %H:%M')}, "
                     f"raport ok. {ctx.t(e['at'].timestamp() + 45 * 60)}")
    mu = ctx.st.get("mute_until")
    lines.append(f"🔕 Alerty rynkowe wyciszone do {ctx.t(mu, '%d.%m %H:%M')}" if alerts.is_muted(mu, now)
                 else "🔔 Alerty rynkowe włączone")
    return "\n".join(lines)


def h_raport(ctx, msg, args):
    idx = ctx.fetch("reports", "index.json")
    reps = (idx or {}).get("reports") or []
    if not reps:
        return "Nie ma jeszcze raportów."
    periodic = ("weekly", "monthly")
    r = next((x for x in reps if x.get("kind") not in periodic), reps[0])
    lines = [f"📊 <b>{html.escape(r['title'])}</b>, {ctx.t(r['created'], '%d.%m.%Y %H:%M')}"]
    if r.get("summary"):
        lines.append(html.escape(r["summary"]))
    lines.append(f"<a href=\"{_report_url(ctx, r['id'])}\">Otwórz raport</a>")
    for kind in periodic:
        x = next((x for x in reps if x.get("kind") == kind), None)
        if x and x is not r:
            lines.append(f"🗓 <a href=\"{_report_url(ctx, x['id'])}\">{html.escape(x['title'])}</a>")
    return "\n".join(lines)


def h_fiby(ctx, msg, args):
    near, cfg_setups = ctx.fib_cfg()
    setups = cfg_setups + (ctx.st.get("fib_user") or [])
    prices = ctx.prices({s["coin"] for s in setups}) if setups else {}
    return F.list_text(setups, prices, near)


# ── handlers: admin ──────────────────────────────────────────
def h_skan(ctx, msg, args):
    ok, err = ctx.gh.dispatch("oi-monitor.yml", {"mode": "run", "report": "none"})
    return "🔄 Skan uruchomiony — nowe dane za ok. 40 min (/status)." if ok else f"⚠️ Nie udało się: {html.escape(err)}"


PERIOD_ARGS = {"tydzien": "weekly", "tydzień": "weekly", "tyg": "weekly", "weekly": "weekly",
               "miesiac": "monthly", "miesiąc": "monthly", "mies": "monthly", "monthly": "monthly"}


def h_raport_teraz(ctx, msg, args):
    kind = PERIOD_ARGS.get(args.strip().lower())
    if kind:
        ok, err = ctx.gh.dispatch("report.yml", {"kind": kind})
        okt = f"📊 Raport {_kind_title(kind)} (ostatni pełny okres) w przygotowaniu — link za 1–2 min."
    elif args.strip().lower().startswith("skan"):
        ok, err = ctx.gh.dispatch("oi-monitor.yml", {"mode": "run", "report": "manual"})
        okt = "🔄 Skan + raport uruchomione — link przyjdzie za ok. 45 min."
    else:
        ok, err = ctx.gh.dispatch("report.yml", {"kind": "manual"})
        okt = "📊 Raport z obecnych danych w przygotowaniu — link za 1–2 min."
    return okt if ok else f"⚠️ Nie udało się: {html.escape(err)}"


def h_cisza(ctx, msg, args):
    a = args.strip().lower()
    if a in ("off", "0", "wył", "wyl", "stop", "koniec"):
        ctx.st["mute_until"] = None
        return "🔔 Alerty rynkowe włączone."
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s*([mhd]?)$", a or "8h")
    if not m:
        return "❓ Składnia: /cisza 8h | 30m | 2d | off"
    n, unit = float(m.group(1).replace(",", ".")), m.group(2) or "h"
    sec = n * {"m": 60, "h": HOUR, "d": 86400}[unit]
    if sec <= 0 or sec > 14 * 86400:
        return "❓ Wyciszenie od 1 min do 14 dni."
    ctx.st["mute_until"] = ctx.now + int(sec)
    return (f"🔕 Alerty rynkowe (EMA, Fibo, poziomy, likwidacje) wyciszone do {ctx.t(ctx.st['mute_until'], '%d.%m %H:%M')}. "
            "Raporty i komunikaty o awariach dalej przychodzą. Włączenie: /cisza off")


def h_fib(ctx, msg, args):
    parsed = F.parse_command("/fib " + args)
    if not parsed or parsed[0] == "error":
        return "❓ " + html.escape(parsed[1] if parsed else "Składnia: /fib COIN SZCZYT DOŁEK [long|short] [opis]")
    near, _ = ctx.fib_cfg()
    user = ctx.st.setdefault("fib_user", [])
    setup = F.add_setup(user, parsed[1], ctx.now)
    price = ctx.prices({setup["coin"]}).get(setup["coin"])
    return F.added_text(setup, price, near)


def h_usun(ctx, msg, args):
    m = re.match(r"\s*(\w+)", args)
    if not m:
        return "❓ Podaj id, np. /usun 3 (lista: /fiby)"
    _, cfg_setups = ctx.fib_cfg()
    return F.delete_setup(ctx.st.setdefault("fib_user", []), cfg_setups, m.group(1))


REPORT_ID = re.compile(r"^\d{8}-\d{4}-[a-z,]+$")


def h_usun_raport(ctx, msg, args):
    ids = [x for x in re.split(r"[\s,]+", args.strip()) if x]
    ids = [x.split("id=")[-1] for x in ids]                       # można wkleić cały link
    if not ids or not all(REPORT_ID.match(x) for x in ids):
        return "❓ Podaj ID raportu z jego adresu (…raporty.html?id=<b>20261101-1600-monthly</b>), np. /usun_raport 20261101-1600-monthly"
    idx = ctx.fetch("reports", "index.json")
    known = {r.get("id"): r for r in (idx or {}).get("reports") or []}
    if idx is not None:
        missing = [x for x in ids if x not in known]
        if missing:
            return "❓ Nie ma takiego raportu: " + ", ".join(html.escape(x) for x in missing)
    ok, err = ctx.gh.dispatch("report.yml", {"kind": "manual", "delete": ",".join(ids)})
    if not ok:
        return f"⚠️ Nie udało się: {html.escape(err)}"
    names = [html.escape(known[x]["title"]) + f" ({ctx.t(known[x]['created'], '%d.%m %H:%M')})" if x in known else x
             for x in ids]
    return "🗑 Usuwam z historii: " + "; ".join(names) + ". Zniknie ze strony za 1–2 min."


def h_watek(ctx, msg, args):
    chat = msg.get("chat") or {}
    tid = msg.get("message_thread_id") if msg.get("is_topic_message") else None
    lines = [f"Czat: <b>{html.escape(chat.get('title') or chat.get('type', ''))}</b>",
             f"group_chat_id: <code>{chat.get('id')}</code>",
             f"group_thread_id: <code>{tid if tid else 'null'}</code>"]
    if chat.get("type") == "private":
        lines.append("To czat prywatny — wyślij /watek w wątku grupy.")
    else:
        lines += ["", "Wpisz te wartości w config.yaml (sekcja telegram) i zapisz na GitHubie.",
                  "Sprawdzenie: <code>python3 ~/scanner/collector/ema_monitor.py check --test-telegram</code>"]
        if not tid:
            lines.append("(brak numeru wątku = wątek „Ogólny” albo grupa bez tematów)")
    return "\n".join(lines)


# ── helpers ──────────────────────────────────────────────────
def _is_admin(ctx, msg):
    return str((msg.get("from") or {}).get("id")) == ctx.admin


def _report_url(ctx, rid):
    page = (ctx.cfg.get("reports") or {}).get("page_url") or "https://cryptoloser8-coder.github.io/scanner/raporty.html"
    return f"{page}?id={rid}"


def _kind_title(kind):
    names = {"morning": "poranny (zamknięcie dnia)", "evening": "wieczorny (krypto dziś)", "manual": "na żądanie",
             "test": "testowy", "daily": "dzienny", "weekly": "tygodniowy", "monthly": "miesięczny"}
    return " i ".join(names.get(k, k) for k in str(kind or "").split(",") if k)


def reply(ctx, msg, text):
    chat = (msg.get("chat") or {}).get("id")
    tid = msg.get("message_thread_id") if msg.get("is_topic_message") else None
    try:
        ctx.api.send(chat, text, thread_id=tid, reply_to=msg.get("message_id"))
    except Exception as e:  # noqa: BLE001
        log.error("Odpowiedź: %s", e)


def handle_message(ctx, msg):
    text = (msg.get("text") or "").strip()
    if not text.startswith("/") or ctx.now - int(msg.get("date") or 0) > STALE_COMMAND_S:
        return None
    head, _, rest = text.partition(" ")
    name, _, at = head[1:].partition("@")
    if at and ctx.me and at.lower() != ctx.me.lower():
        return None                                   # command for another bot
    cmd = find(name)
    chat = msg.get("chat") or {}
    admin = _is_admin(ctx, msg)
    private_admin = chat.get("type") == "private" and admin
    in_group = bool(ctx.group_id) and str(chat.get("id")) == ctx.group_id
    if not (private_admin or in_group or (admin and cmd is not None and cmd.name == "watek")):
        return None                                   # other chats / strangers: silent
    if cmd is None:
        if private_admin:
            reply(ctx, msg, f"❓ Nie znam komendy /{html.escape(name)}. Lista: /pomoc")
        return None
    if cmd.admin and not admin:
        reply(ctx, msg, "🔒 Ta komenda jest tylko dla administratora. Lista: /pomoc")
        return cmd.name
    try:
        out = cmd.handler(ctx, msg, rest.strip())
    except Exception as e:  # noqa: BLE001
        log.exception("/%s", cmd.name)
        out = f"⚠️ Błąd: {html.escape(str(e))[:200]}"
    reply(ctx, msg, out)
    return cmd.name


def poll(ctx):
    try:
        ups = ctx.api.get_updates(ctx.st.get("tg_offset", 0))
    except Exception as e:  # noqa: BLE001
        log.warning("getUpdates: %s", e)
        return []
    done = []
    for u in ups:
        ctx.st["tg_offset"] = u["update_id"] + 1
        if u.get("message"):
            name = handle_message(ctx, u["message"])
            if name:
                done.append(name)
    return done


def sync_commands(ctx):
    """Telegram menu (after typing "/"): general commands everywhere, all commands in the admin's chat."""
    h = hashlib.sha1(json.dumps([menu(False), menu(True), ctx.admin], sort_keys=True).encode()).hexdigest()[:12]
    if ctx.st.get("cmd_hash") == h:
        return False
    try:
        if not ctx.st.get("me"):
            ctx.st["me"] = {"username": (ctx.api.get_me() or {}).get("username", "")}
            ctx.me = ctx.st["me"]["username"]
        ctx.api.set_commands(menu(False), {"type": "default"})
        ctx.api.set_commands(menu(False), {"type": "all_group_chats"})
        ctx.api.set_commands(menu(True), {"type": "chat", "chat_id": int(ctx.admin)})
        ctx.st["cmd_hash"] = h
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("setMyCommands: %s", e)
        return False


# ── schedule & watch ─────────────────────────────────────────
def schedule_tick(ctx):
    done = ctx.st.setdefault("sched_done", {})
    started = []
    for e in TT.due(ctx.sc, ctx.now, done):
        report = e["kind"] if e["type"] == "report" else "none"
        ok, err = ctx.gh.dispatch("oi-monitor.yml", {"mode": "run", "report": report})
        ctx.health["Uruchamianie skanów (token GitHub)"] = None if ok else err
        if not ok:
            log.error("Skan %s: %s", e["key"], err)
            continue                                  # retried next minute (within the grace period)
        done[e["key"]] = {"at": ctx.now}
        started.append(e["key"])
        log.info("Uruchomiono %s (raport: %s)", e["key"], report)
        if e["type"] == "report":
            ctx.st.setdefault("pending_reports", []).append({"key": e["key"], "kind": e["kind"], "at": ctx.now})
    TT.prune(done, ctx.now)
    return started


def watch_tick(ctx):
    if ctx.now - ctx.st.get("watch_at", 0) < WATCH_EVERY_S:
        return []
    ctx.st["watch_at"] = ctx.now
    out = []
    meta = ctx.fetch("data", "meta.json")
    if meta and meta.get("updated"):
        age = ctx.now - meta["updated"]
        limit = (int(ctx.sc.get("scan_every_hours") or 2) + 1.5) * HOUR
        ctx.health["Skany OI/TOTAL na GitHubie"] = None if age <= limit else (
            f"ostatni skan wystartował {ctx.t(meta['updated'], '%d.%m %H:%M')} ({ago(age)}) — sprawdź GitHub → Actions")
    pend = ctx.st.get("pending_reports") or []
    if pend:
        idx = ctx.fetch("reports", "index.json")
        if idx is not None:
            keep = []
            for p in pend:
                if any((r.get("created") or 0) >= p["at"] for r in idx.get("reports") or []):
                    continue
                if ctx.now - p["at"] > REPORT_LATE_S:
                    out.append(f"❗ Raport {_kind_title(p['kind'])} nie powstał (skan uruchomiony {ctx.t(p['at'])}). "
                               "Sprawdź GitHub → Actions → OI Monitor.")
                else:
                    keep.append(p)
            ctx.st["pending_reports"] = keep
    return out


def report_health(ctx):
    hst = ctx.st.setdefault("health_state", {})
    hrs = float(ctx.tgcfg.get("health_reminder_hours", 12) or 12)
    return alerts.health_messages(hst, ctx.health, ctx.now, hrs) if ctx.health else []


def migrate(state_dir):
    """First run: take Telegram setups and the update offset from the old EMA state."""
    old = _read(os.path.join(state_dir, "state.json"), {}) or {}
    return {"fib_user": old.get("fib_user") or [], "tg_offset": old.get("tg_offset") or 0}


def tick(ctx):
    """One bot run (every minute) → messages sent to the admin."""
    sync_commands(ctx)
    poll(ctx)
    schedule_tick(ctx)
    sysmsgs = watch_tick(ctx) + report_health(ctx)
    for m in sysmsgs:
        ctx.tg.post("system", m)
    return sysmsgs


COMMANDS = _registry()


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Bot Telegram + harmonogram skanów (Orange Pi, co minutę)")
    ap.add_argument("--config", default=os.path.join(here, "config.yaml"))
    ap.add_argument("--state", default=os.path.expanduser("~/.ema-monitor"))
    ap.add_argument("--env-file", default="~/.scanner_env")
    ap.add_argument("--token-file", default="~/.scanner_token")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_env(a.env_file)
    token, admin = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not admin:
        log.error("Brak TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID w %s", a.env_file)
        return 1
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    try:
        with open(os.path.expanduser(a.token_file), encoding="utf-8") as f:
            gh_token = f.read().strip()
    except FileNotFoundError:
        gh_token = ""
    repo = (cfg.get("ema") or {}).get("repo") or "cryptoloser8-coder/scanner"
    path = os.path.join(a.state, "bot.json")
    st = _read(path, None)
    if st is None:
        st = migrate(a.state)
    ctx = Ctx(cfg, st, time.time(), admin, TgApi(token), GitHub(gh_token, repo), raw_fetcher(repo),
              price_lookup(a.state), a.state, alerts.Telegram(tg_cfg=cfg.get("telegram") or {}))
    tick(ctx)
    os.makedirs(a.state, exist_ok=True)
    _write(path, ctx.st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
