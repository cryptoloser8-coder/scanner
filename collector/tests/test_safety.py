"""Offline tests: bezpiecznik publikacji, pobieranie gałęzi, archiwum na Pi, sonda historii."""
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backup  # noqa: E402
import guard  # noqa: E402
import probe  # noqa: E402

HERE = os.path.join(os.path.dirname(__file__), "..")


def write_series(path, n_points, extra=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    s = {"a": [[i, 1.0] for i in range(n_points)]}
    s.update(extra or {})
    with open(path, "w") as f:
        json.dump({"updated": 1, "series": s}, f)


# ── guard ────────────────────────────────────────────────────
def test_guard_ok_when_growing(tmp_path):
    write_series(str(tmp_path / "old/1d.json"), 100)
    write_series(str(tmp_path / "new/1d.json"), 101)
    assert guard.check(str(tmp_path / "old"), str(tmp_path / "new")) == []


def test_guard_blocks_lost_history(tmp_path):
    write_series(str(tmp_path / "old/1d.json"), 1000)
    write_series(str(tmp_path / "new/1d.json"), 10)
    p = guard.check(str(tmp_path / "old"), str(tmp_path / "new"))
    assert p and "1d.json" in p[0]


def test_guard_blocks_missing_file_and_fewer_reports(tmp_path):
    write_series(str(tmp_path / "old/1h.json"), 10)
    for i in range(3):
        (tmp_path / "old/reports").mkdir(parents=True, exist_ok=True)
        (tmp_path / f"old/reports/{i}.json").write_text("{}")
    (tmp_path / "new/reports").mkdir(parents=True)
    (tmp_path / "new/reports/0.json").write_text("{}")
    p = guard.check(str(tmp_path / "old"), str(tmp_path / "new"))
    assert any("1h.json" in x for x in p) and any("reports/" in x for x in p)


def test_guard_small_series_removal_allowed(tmp_path):
    write_series(str(tmp_path / "old/1d.json"), 1000, {"small": [[1, 1.0]]})
    write_series(str(tmp_path / "new/1d.json"), 1000)
    assert guard.check(str(tmp_path / "old"), str(tmp_path / "new")) == []


def test_guard_allow_shrink_env(tmp_path, monkeypatch):
    write_series(str(tmp_path / "old/1d.json"), 1000)
    write_series(str(tmp_path / "new/1d.json"), 10)
    assert guard.main([str(tmp_path / "old"), str(tmp_path / "new")]) == 1
    monkeypatch.setenv("PUBLISH_ALLOW_SHRINK", "1")
    assert guard.main([str(tmp_path / "old"), str(tmp_path / "new")]) == 0


# ── fetch_branch.sh + publish.sh na lokalnym repo (file://) ──
def _git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def remote(tmp_path):
    if not shutil.which("git"):
        pytest.skip("brak git")
    bare = tmp_path / "remote.git"
    _git("init", "-q", "--bare", str(bare))
    return "file://" + str(bare)


def _sh(script, *args, env=None):
    e = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
             GIT_COMMITTER_EMAIL="t@t", **(env or {}))
    return subprocess.run(["bash", os.path.join(HERE, script), *args], env=e, capture_output=True, text=True)


def test_publish_and_fetch_roundtrip_with_guard(tmp_path, remote):
    d = tmp_path / "d1"
    write_series(str(d / "1d.json"), 500)
    r = _sh("publish.sh", str(d), remote)
    assert r.returncode == 0, r.stderr
    # pobranie istniejącej gałęzi
    r = _sh("fetch_branch.sh", "data", str(tmp_path / "f"), remote)
    assert r.returncode == 0, r.stderr
    assert guard.series_points(str(tmp_path / "f/1d.json")) == 500
    # próba nadpisania „pustą” wersją → zablokowana, gałąź bez zmian
    d2 = tmp_path / "d2"
    write_series(str(d2 / "1d.json"), 3)
    r = _sh("publish.sh", str(d2), remote)
    assert r.returncode != 0 and "Bezpiecznik" in r.stdout + r.stderr
    _sh("fetch_branch.sh", "data", str(tmp_path / "f2"), remote)
    assert guard.series_points(str(tmp_path / "f2/1d.json")) == 500
    # backfill (PUBLISH_ALLOW_SHRINK=1) może celowo przeliczyć historię
    r = _sh("publish.sh", str(d2), remote, env={"PUBLISH_ALLOW_SHRINK": "1"})
    assert r.returncode == 0, r.stderr


def test_fetch_branch_missing_branch_gives_empty_dir(tmp_path, remote):
    r = _sh("fetch_branch.sh", "reports", str(tmp_path / "r"), remote)
    assert r.returncode == 0 and os.path.isdir(tmp_path / "r") and not os.listdir(tmp_path / "r")


def test_fetch_branch_unreachable_remote_fails(tmp_path):
    if not shutil.which("git"):
        pytest.skip("brak git")
    r = subprocess.run(["bash", os.path.join(HERE, "fetch_branch.sh"), "data", str(tmp_path / "x"),
                        "file://" + str(tmp_path / "nie-ma")], capture_output=True, text=True,
                       env=dict(os.environ, FETCH_RETRY_SLEEP="0"), timeout=120)
    assert r.returncode != 0 and not os.path.exists(tmp_path / "x")


# ── backup (Pi) ──────────────────────────────────────────────
def fake_fetch(url, dest):
    for b in backup.BRANCHES:
        write_series(os.path.join(dest, b, "x.json"), 5)


def make_state(tmp_path):
    st = tmp_path / "state"
    (st / "pub").mkdir(parents=True)
    (st / "pub/ema.json").write_text("{}")
    (st / "bot.json").write_text('{"fib_user": []}')
    (st / "candles.json.tmp").write_text("x")
    return str(st)


def test_backup_archive_contents_and_rotation(tmp_path):
    cfg = dict(backup.DEFAULTS, dir=str(tmp_path / "arch"), keep_daily=2)
    st = make_state(tmp_path)
    res = backup.do_backup(cfg, st, now=datetime(2026, 11, 1, 3, tzinfo=timezone.utc), fetch=fake_fetch)
    with tarfile.open(res["file"]) as tar:
        names = tar.getnames()
    assert "data/x.json" in names and "reports/x.json" in names and "pi-state/bot.json" in names
    assert not any(n.startswith("pi-state/pub") for n in names)
    assert not any(n.endswith(".tmp") for n in names)
    for day in ("2026-10-28", "2026-10-29", "2026-10-30"):
        backup.do_backup(cfg, st, now=datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc),
                         fetch=fake_fetch)
    files = sorted(os.listdir(cfg["dir"]))
    # zostają 2 najnowsze dni; 1. dzień miesiąca na zawsze
    assert files == ["scanner-2026-10-30.tar.xz", "scanner-2026-11-01.tar.xz"]
    backup.do_backup(cfg, st, now=datetime(2026, 11, 3, tzinfo=timezone.utc), fetch=fake_fetch)
    backup.do_backup(cfg, st, now=datetime(2026, 11, 4, tzinfo=timezone.utc), fetch=fake_fetch)
    assert "scanner-2026-11-01.tar.xz" in os.listdir(cfg["dir"])


class FakeTG:
    def __init__(self):
        self.sent = []

    def post(self, kind, text):
        self.sent.append((kind, text))


def test_backup_due_failures_and_recovery(tmp_path):
    cfg = dict(backup.DEFAULTS, dir=str(tmp_path / "arch"))
    st = make_state(tmp_path)
    tg = FakeTG()
    early = datetime(2026, 11, 1, 1, tzinfo=timezone.utc)
    assert backup.run_if_due(cfg, st, now=early, backup=lambda *a: 1 / 0, telegram=tg) is None  # przed 02:00

    def boom(*a):
        raise RuntimeError("sieć")
    d1 = datetime(2026, 11, 1, 3, tzinfo=timezone.utc)
    assert backup.run_if_due(cfg, st, now=d1, backup=boom, telegram=tg) is False
    assert backup.run_if_due(cfg, st, now=d1.replace(minute=5), backup=boom, telegram=tg) is None  # ponowienie po 1 h
    assert tg.sent == []                                 # jeden dzień błędu — jeszcze bez alarmu
    d2 = datetime(2026, 11, 2, 3, tzinfo=timezone.utc)
    assert backup.run_if_due(cfg, st, now=d2, backup=boom, telegram=tg) is False
    assert len(tg.sent) == 1 and tg.sent[0][0] == "system" and "2 dni" in tg.sent[0][1]
    d2b = d2.replace(hour=5)
    ok = backup.run_if_due(cfg, st, now=d2b, backup=lambda c, s, n: backup.do_backup(c, s, n, fetch=fake_fetch),
                           telegram=tg)
    assert ok is True and "znowu działa" in tg.sent[-1][1]
    assert backup.run_if_due(cfg, st, now=d2b.replace(hour=9), backup=boom, telegram=tg) is None  # dziś już jest


def test_backup_cfg_from_yaml():
    cfg = backup.load_cfg(os.path.join(HERE, "config.yaml"))
    assert cfg["keep_daily"] == 14 and cfg["repo"] == "cryptoloser8-coder/scanner"


# ── probe ────────────────────────────────────────────────────
class FakeCZ:
    """Coinalyze answering at most 1500 newest points per request (like a capped API)."""
    calls_made = 0

    def __init__(self, first_day):
        self.first = first_day
        self.requests = []

    def history(self, path, syms, interval, frm, to, fields, usd=False):
        self.requests.append((tuple(syms), to))
        days = [t for t in range(self.first, to + 1, 86400)]
        days = days[-1500:]
        return {s: {t: 1.0 for t in days} for s in syms}


def test_probe_history_all_follows_capped_answers():
    first = 1_600_000_000 // 86400 * 86400
    now = first + 4000 * 86400
    cz = FakeCZ(first)
    h = probe.history_all(cz, "/x", ["A", "B"], "c", False, now)
    assert min(h["A"]) == first and len(h["A"]) == 4001
    assert len(cz.requests) >= 3


class FakeResp:
    def __init__(self, status=200, js=None, text="", content=b""):
        self.status_code, self._js, self.text, self.content = status, js, text, content

    def json(self):
        return self._js


class FakeSession:
    def __init__(self, handler):
        self.handler = handler

    def get(self, url, params=None, **kw):
        return self.handler(url, params or {})


def test_probe_vision_listing_paged():
    pages = {
        None: "<ListBucketResult><IsTruncated>true</IsTruncated>"
              "<Contents><Key>data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2021-12-01.zip</Key></Contents>"
              "</ListBucketResult>",
        "data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2021-12-01.zip":
              "<ListBucketResult><IsTruncated>false</IsTruncated>"
              "<Contents><Key>data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-10-31.zip</Key></Contents>"
              "</ListBucketResult>",
    }
    keys, _ = probe.s3_list(FakeSession(lambda url, p: FakeResp(text=pages[p.get("marker")])),
                            "data/futures/um/daily/metrics/BTCUSDT/")
    assert len(keys) == 2 and keys[-1].endswith("2026-10-31.zip")


def test_probe_run_isolates_failing_source_and_markdown(tmp_path):
    def bad():
        raise RuntimeError("nie działa")
    res = probe.run("pi", only=["coinmetrics", "binance"],
                    funcs={"coinmetrics": lambda: [probe.row("coinmetrics", "x", first=1_500_000_000)], "binance": bad})
    assert res["rows"][0]["first"] == "2017-07-14" and res["rows"][1]["status"] == "błąd"
    probe.save(res, str(tmp_path))
    md = (tmp_path / "probe.md").read_text()
    assert "| coinmetrics | x | ok | 2017-07-14 |" in md and "nie działa" in md
