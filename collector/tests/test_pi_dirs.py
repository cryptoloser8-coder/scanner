import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pi_dirs  # noqa: E402


def test_old_used_until_moved(tmp_path):
    home, pi = tmp_path / "home", tmp_path / "repo" / "pi"
    (home / ".ema-monitor").mkdir(parents=True)
    assert pi_dirs.path("stan", str(pi), str(home)) == str(home / ".ema-monitor")
    (pi / "stan").mkdir(parents=True)
    assert pi_dirs.path("stan", str(pi), str(home)) == str(pi / "stan")


def test_new_when_nothing(tmp_path):
    pi = tmp_path / "pi"
    assert pi_dirs.path("scanner_token", str(pi), str(tmp_path)) == str(pi / "scanner_token")


def test_archive_custom_dir_kept(tmp_path):
    assert pi_dirs.archive_dir(str(tmp_path / "x")) == str(tmp_path / "x")
    assert pi_dirs.archive_dir("~/scanner-archive") == pi_dirs.path("archiwum")
