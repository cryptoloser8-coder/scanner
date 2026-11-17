"""Gdzie na Orange Pi leżą pliki apki (poprawka 83).

Od poprawki 83 wszystko jest w jednym folderze apki (kopia repo `scanner`, dawniej ~/scanner),
w podfolderze `pi/` (nie trafia do Gita — .gitignore):
    ~/Crypto_Loser_analytics_tool/                 kod (git pull co 5 min)
    ~/Crypto_Loser_analytics_tool/pi/stan/         stan bota i EMA (dawniej ~/.ema-monitor)
    ~/Crypto_Loser_analytics_tool/pi/archiwum/     codzienne kopie danych (dawniej ~/scanner-archive)
    ~/Crypto_Loser_analytics_tool/pi/logi/         ema-monitor.log, scanner-bot.log (dawniej w ~)
    ~/Crypto_Loser_analytics_tool/pi/scanner_env   dane Telegrama (dawniej ~/.scanner_env)
    ~/Crypto_Loser_analytics_tool/pi/scanner_token token GitHub (dawniej ~/.scanner_token)
Przeniesienie wykonane 16.11.2026 jednorazowym skryptem porzadki_pi.sh (usunięty z repo w poprawce 84).
Dopóki nie przeniesione — używane są stare miejsca, więc nic się nie psuje w trakcie.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PI = os.path.join(REPO, "pi")
OLD = {
    "stan": "~/.ema-monitor",
    "archiwum": "~/scanner-archive",
    "scanner_env": "~/.scanner_env",
    "scanner_token": "~/.scanner_token",
}


def path(name, pi_dir=None, home=None):
    """Nowe miejsce, jeśli istnieje albo starego brak; inaczej stare (przed przeniesieniem)."""
    new = os.path.join(pi_dir or PI, name)
    old = OLD[name]
    old = os.path.join(home, old[2:]) if home else os.path.expanduser(old)
    if os.path.exists(new) or not os.path.exists(old):
        return new
    return old


def state_dir():
    return path("stan")


def env_file():
    return path("scanner_env")


def token_file():
    return path("scanner_token")


def archive_dir(configured=None):
    """Folder archiwum; stara wartość z configu (~/scanner-archive) wskazuje nowe miejsce po przeniesieniu."""
    if configured and configured.rstrip("/") not in (OLD["archiwum"], os.path.expanduser(OLD["archiwum"])):
        return os.path.expanduser(configured)
    return path("archiwum")
