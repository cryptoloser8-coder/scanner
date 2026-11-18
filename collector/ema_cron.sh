#!/usr/bin/env bash
# Uruchamiane z crona na Orange Pi co 5 minut:
#   */5 * * * * flock -n /tmp/ema-monitor.lock bash $HOME/Crypto_Loser_analytics_tool/collector/ema_cron.sh >> $HOME/Crypto_Loser_analytics_tool/pi/logi/ema-monitor.log 2>&1
# Najpierw pobiera najnowszą wersję repo (kod i config.yaml), potem raz na dobę robi
# archiwum danych (collector/backup.py — tylko gdy dziś jeszcze go nie ma), na końcu liczy EMA i wysyła alerty.
# Bot Telegram i harmonogram skanów to osobna linia crona (co minutę): collector/bot.py.
set -u
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"   # folder apki (od poprawki 83: ~/Crypto_Loser_analytics_tool)
git -C "$REPO_DIR" pull -q --ff-only 2>&1 | tail -2
python3 "$REPO_DIR/collector/backup.py" --if-due 2>&1 | tail -3
# poprawka 87: historia grup HyperTrackera porcjami (kilka zapytań na przebieg, do dziennego limitu; bez klucza nic nie robi)
[ -f "$REPO_DIR/collector/ht_history.py" ] && timeout 300 python3 "$REPO_DIR/collector/ht_history.py" run 2>&1 | tail -2
exec python3 "$REPO_DIR/collector/ema_monitor.py" run "$@"
