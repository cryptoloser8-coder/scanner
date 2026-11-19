"""Bezpieczne wczytanie config.yaml na Orange Pi (poprawka 115).

config.yaml bywa edytowany ręcznie na GitHubie. Błąd składni zatrzymywał bot.py i ema_monitor.py przy starcie —
bez wiadomości, bez skanów, raportów i alertów, aż zauważył to Watchdog (do ~4 h).

Teraz:
  * poprawny plik → zapisujemy jego kopię (`config.last_good.yaml` w folderze stanu Pi),
  * plik z błędem → Pi pracuje dalej na ostatniej dobrej kopii, a administrator dostaje wiadomość na priv
    (raz na daną wersję pliku, przypomnienie co 12 h, „znowu poprawny” po naprawie).
Nie ma jeszcze dobrej kopii (pierwszy przebieg) → błąd jak dawniej, ale z wiadomością.

    cfg = safe_config.load(path, state_dir)

Skany na GitHubie czytają config.yaml osobno (main.py) — z błędem w pliku nie ruszą; wiadomość o tym mówi.
"""
import hashlib
import html
import json
import logging
import os
import tempfile
import time

import yaml

log = logging.getLogger("safe_config")

GOOD_NAME = "config.last_good.yaml"
STATE_NAME = "config_state.json"
REMIND_S = 12 * 3600
DICT_SECTIONS = ("coinalyze", "telegram", "schedule", "ema", "fib", "reports", "tradingview", "liquidations", "cycle")
LIST_SECTIONS = ("watchlist", "levels", "changes", "liq_alerts", "history_events")


class ConfigError(RuntimeError):
    pass


def parse(text):
    """→ (cfg, None) albo (None, opis problemu po polsku)."""
    try:
        cfg = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" w linii {mark.line + 1} (znak {mark.column + 1})" if mark is not None else ""
        what = getattr(e, "problem", None) or str(e).splitlines()[0]
        return None, f"błąd składni{where}: {what}"
    if cfg is None:
        return None, "plik jest pusty"
    if not isinstance(cfg, dict):
        return None, "plik nie jest listą ustawień (klucz: wartość)"
    for k in DICT_SECTIONS:
        if cfg.get(k) is not None and not isinstance(cfg[k], dict):
            return None, f"sekcja „{k}” powinna mieć ustawienia w postaci klucz: wartość"
    for k in LIST_SECTIONS:
        if cfg.get(k) is not None and not isinstance(cfg[k], list):
            return None, f"sekcja „{k}” powinna być listą"
    return cfg, None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_text(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _notify(text):
    """Wiadomość do administratora (priv). Nigdy nie przerywa wczytywania."""
    try:
        import alerts
        return bool(alerts.Telegram().post("system", text))
    except Exception as e:  # noqa: BLE001
        log.error("config.yaml: nie udało się wysłać wiadomości (%s)", e)
        return False


def _when(ts):
    try:
        import timetable as TT
        return TT.local(ts, TT.load(None), "%d.%m %H:%M")
    except Exception:  # noqa: BLE001
        return time.strftime("%d.%m %H:%M UTC", time.gmtime(ts))


def load(path, state_dir, notify=None, now=None):
    """Wczytuje config.yaml; przy błędzie zwraca ostatnią dobrą wersję i zawiadamia administratora."""
    now = int(now or time.time())
    notify = notify or _notify
    with open(path, encoding="utf-8") as f:
        text = f.read()
    cfg, problem = parse(text)
    spath, gpath = os.path.join(state_dir, STATE_NAME), os.path.join(state_dir, GOOD_NAME)
    st = _read_json(spath)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]

    if problem is None:
        try:
            if st.get("good") != digest or not os.path.exists(gpath):
                _write_text(gpath, text)
            if st.get("bad"):
                notify("✅ <b>config.yaml</b> znowu poprawny — Orange Pi pracuje na bieżącej wersji.")
            if st.get("good") != digest or st.get("bad"):
                _write_text(spath, json.dumps({"good": digest, "good_at": now}))
        except OSError as e:
            log.warning("config.yaml: nie zapisano kopii (%s)", e)
        return cfg

    log.error("config.yaml: %s", problem)
    good_cfg, good_at = None, st.get("good_at")
    try:
        with open(gpath, encoding="utf-8") as f:
            good_cfg, _ = parse(f.read())
    except OSError:
        pass
    bad = st.get("bad") or {}
    if bad.get("hash") != digest or now - int(bad.get("msg_at") or 0) >= REMIND_S:
        again = bad.get("hash") == digest
        if good_cfg is not None:
            tail = ("Orange Pi pracuje na ostatniej dobrej wersji"
                    + (f" (z {_when(good_at)})" if good_at else "") + " — alerty EMA / Fibo i komendy działają.")
        else:
            tail = "Orange Pi nie ma jeszcze zapisanej dobrej wersji — bot i EMA stoją."
        notify(("⚠️ <b>config.yaml nadal ma błąd</b>" if again else "⚠️ <b>config.yaml ma błąd</b>")
               + f" — {html.escape(problem)[:300]}.\n{tail}\n"
               "Skany i raporty na GitHubie nie ruszą, dopóki plik nie zostanie poprawiony (GitHub → collector/config.yaml).")
        bad = {"hash": digest, "msg_at": now, "since": bad.get("since") if again else now}
        try:
            _write_text(spath, json.dumps({**st, "bad": bad}))
        except OSError as e:
            log.warning("config.yaml: nie zapisano stanu (%s)", e)
    if good_cfg is None:
        raise ConfigError(f"config.yaml: {problem} (brak zapisanej dobrej wersji)")
    return good_cfg
