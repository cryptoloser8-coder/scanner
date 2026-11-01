"""Codzienne archiwum danych na Orange Pi (druga kopia obok wydań „Archiwum” na GitHubie).

Raz na dobę (po `backup.hour_utc`, domyślnie 02:00 UTC) pakuje do jednego pliku .tar.xz:
  - gałęzie data, ema i reports z GitHuba (cała historia danych i raporty),
  - stan Pi: ~/.ema-monitor (świece Binance, setupy Fibo z Telegrama, stan bota) — bez katalogu pub/.
Pliki: ~/scanner-archive/scanner-RRRR-MM-DD.tar.xz. Zostaje ostatnie `keep_daily` dni (domyślnie 14)
oraz na zawsze plik z 1. dnia każdego miesiąca.

Uruchamiane z collector/ema_cron.sh (cron co 5 min, bez zmian w crontabie):
    python3 collector/backup.py --if-due     # robi kopię tylko, gdy dziś jej jeszcze nie ma
Ręcznie:
    python3 ~/scanner/collector/backup.py now     # kopia teraz
    python3 ~/scanner/collector/backup.py list    # lista kopii
Awaria dwa dni z rzędu → wiadomość do admina na Telegramie (raz), po naprawie „znowu działa”.
"""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

log = logging.getLogger("backup")
BRANCHES = ("data", "ema", "reports")
DEFAULTS = {"dir": "~/scanner-archive", "keep_daily": 14, "hour_utc": 2,
            "repo": "cryptoloser8-coder/scanner"}
SKIP_STATE = ("pub",)               # katalog roboczy publikacji (kopia gałęzi ema)
SKIP_SUFFIX = (".tmp", ".lock")


def load_cfg(path):
    cfg = dict(DEFAULTS)
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            full = yaml.safe_load(f) or {}
        cfg.update({k: v for k, v in (full.get("backup") or {}).items() if v is not None})
        cfg["telegram"] = full.get("telegram") or {}
        repo = (full.get("ema") or {}).get("repo")
        if repo and not (full.get("backup") or {}).get("repo"):
            cfg["repo"] = repo
    except FileNotFoundError:
        cfg["telegram"] = {}
    return cfg


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, obj):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def fetch_branches(repo_url, dest, run=subprocess.run):
    """Shallow clone of every data branch into dest/<branch> (without .git). Raises on failure."""
    for b in BRANCHES:
        target = os.path.join(dest, b)
        r = run(["git", "clone", "-q", "--depth", "1", "--branch", b, repo_url, target],
                capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"git clone {b}: {(r.stderr or r.stdout).strip()[:200]}")
        shutil.rmtree(os.path.join(target, ".git"), ignore_errors=True)


def _state_filter(ti):
    parts = ti.name.split("/")
    if len(parts) > 1 and parts[1] in SKIP_STATE:
        return None
    if ti.name.endswith(SKIP_SUFFIX):
        return None
    return ti


def make_archive(out_path, branches_dir, state_dir):
    """Write out_path (.tar.xz) atomically: <branch>/… + pi-state/…; → number of files."""
    tmp = out_path + ".part"
    with tarfile.open(tmp, "w:xz") as tar:
        for b in BRANCHES:
            p = os.path.join(branches_dir, b)
            if os.path.isdir(p):
                tar.add(p, arcname=b)
        if state_dir and os.path.isdir(state_dir):
            tar.add(state_dir, arcname="pi-state", filter=_state_filter)
    with tarfile.open(tmp, "r:xz") as tar:      # sprawdzenie: archiwum da się przeczytać
        members = tar.getmembers()
    n = sum(1 for m in members if m.isfile())
    names = {m.name.split("/")[0] for m in members}
    missing = [b for b in BRANCHES if b not in names]
    if missing:
        os.remove(tmp)
        raise RuntimeError("archiwum bez gałęzi: " + ", ".join(missing))
    os.replace(tmp, out_path)
    return n


def archive_name(day):
    return f"scanner-{day}.tar.xz"


def rotate(archive_dir, keep_daily, today):
    """Keep the newest `keep_daily` daily files + every file from the 1st of a month. → removed names."""
    files = sorted(f for f in os.listdir(archive_dir) if f.startswith("scanner-") and f.endswith(".tar.xz"))
    days = [f[len("scanner-"):-len(".tar.xz")] for f in files]
    recent = set(sorted(days)[-int(keep_daily):]) if keep_daily > 0 else set()
    removed = []
    for f, d in zip(files, days):
        if d in recent or d.endswith("-01"):
            continue
        os.remove(os.path.join(archive_dir, f))
        removed.append(f)
    return removed


def do_backup(cfg, state_dir, now=None, fetch=fetch_branches):
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    adir = os.path.expanduser(cfg["dir"])
    os.makedirs(adir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="scanner-backup-")
    try:
        fetch(f"https://github.com/{cfg['repo']}.git", work)
        out = os.path.join(adir, archive_name(day))
        n = make_archive(out, work, state_dir)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    removed = rotate(adir, int(cfg.get("keep_daily", 14)), day)
    size = os.path.getsize(out)
    return {"file": out, "files": n, "bytes": size, "removed": removed, "day": day}


def due(st, now, hour_utc):
    day = now.strftime("%Y-%m-%d")
    if st.get("last_ok_day") == day or now.hour < int(hour_utc):
        return False
    last_try = st.get("last_try_ts") or 0
    return now.timestamp() - last_try >= 3600          # po błędzie ponawiamy co godzinę, nie co 5 min


def notify(text, cfg, telegram=None):
    try:
        if telegram is None:
            import alerts
            from ema_monitor import load_env
            load_env("~/.scanner_env")
            telegram = alerts.Telegram(tg_cfg=cfg.get("telegram"))
        telegram.post("system", text)
    except Exception as e:  # noqa: BLE001 — powiadomienie nie może przerwać crona
        log.warning("Telegram: %s", e)


def run_if_due(cfg, state_dir, now=None, backup=do_backup, telegram=None, force=False):
    now = now or datetime.now(timezone.utc)
    spath = os.path.join(state_dir, "backup.json")
    st = _read(spath, {})
    if not force and not due(st, now, cfg.get("hour_utc", 2)):
        return None
    st["last_try_ts"] = int(now.timestamp())
    try:
        res = backup(cfg, state_dir, now)
    except Exception as e:  # noqa: BLE001
        days = st.setdefault("failed_days", [])
        d = now.strftime("%Y-%m-%d")
        if d not in days:
            days.append(d)
        st["failed_days"] = days[-5:]
        st["last_error"] = str(e)[:300]
        log.error("Kopia danych nie powiodła się: %s", e)
        if len(st["failed_days"]) >= 2 and not st.get("notified"):
            notify("⚠️ Archiwum na Orange Pi: kopia danych nie powiodła się "
                   f"{len(st['failed_days'])} dni z rzędu.\nBłąd: {st['last_error']}\n"
                   "Sprawdź: python3 ~/scanner/collector/backup.py now", cfg, telegram)
            st["notified"] = True
        _write(spath, st)
        return False
    if st.get("notified"):
        notify("✅ Archiwum na Orange Pi znowu działa: " + os.path.basename(res["file"]), cfg, telegram)
    st.update({"last_ok_day": res["day"], "last_ok_file": res["file"], "last_ok_bytes": res["bytes"],
               "failed_days": [], "notified": False, "last_error": None})
    _write(spath, st)
    log.info("Kopia danych: %s (%.1f MB, %d plików)%s", os.path.basename(res["file"]), res["bytes"] / 1e6,
             res["files"], f"; usunięte stare: {', '.join(res['removed'])}" if res["removed"] else "")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", nargs="?", choices=["now", "list"], default=None)
    ap.add_argument("--if-due", action="store_true")
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--state", default=os.path.expanduser("~/.ema-monitor"))
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_cfg(a.config)
    if a.mode == "list":
        adir = os.path.expanduser(cfg["dir"])
        files = sorted(os.listdir(adir)) if os.path.isdir(adir) else []
        for f in files:
            print(f"{f}  {os.path.getsize(os.path.join(adir, f)) / 1e6:.1f} MB")
        print(f"{len(files)} plików w {adir}")
        return 0
    if a.mode == "now":
        return 0 if run_if_due(cfg, a.state, force=True) else 1
    if a.if_due:
        run_if_due(cfg, a.state)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
