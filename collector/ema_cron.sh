#!/usr/bin/env bash
# Uruchamiane z crona na Orange Pi co 5 minut:
#   */5 * * * * flock -n /tmp/ema-monitor.lock bash $HOME/scanner/collector/ema_cron.sh >> $HOME/ema-monitor.log 2>&1
# Najpierw pobiera najnowszą wersję repo (kod i config.yaml), potem liczy EMA i wysyła alerty.
# Bot Telegram i harmonogram skanów to osobna linia crona (co minutę): collector/bot.py.
set -u
REPO_DIR="${REPO_DIR:-$HOME/scanner}"
git -C "$REPO_DIR" pull -q --ff-only 2>&1 | tail -2
exec python3 "$REPO_DIR/collector/ema_monitor.py" run "$@"
