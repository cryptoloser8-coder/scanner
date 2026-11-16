#!/usr/bin/env bash
# Poprawka 83 — jednorazowe porządki na Orange Pi: wszystkie pliki apki w jednym folderze
# ~/Crypto_Loser_analytics_tool (dawniej ~/scanner; repo na GitHubie nadal nazywa się `scanner`).
#   bash ~/scanner/collector/porzadki_pi.sh
# Przenosi (jeśli są):
#   ~/.ema-monitor        → pi/stan/
#   ~/scanner-archive     → pi/archiwum/
#   ~/.scanner_env        → pi/scanner_env
#   ~/.scanner_token      → pi/scanner_token
#   ~/ema-monitor.log, ~/scanner-bot.log → pi/logi/
# Zmienia nazwę ~/scanner → ~/Crypto_Loser_analytics_tool.
# W crontabie poprawia tylko nasze dwie linie (ścieżki do kodu i logów); kopia crontaba: pi/crontab-przed-83.txt.
# Usuwa stary ~/trigger-oi-monitor.sh i .log (od 31.10 nieużywane), jeśli crontab ich nie wywołuje.
# Inne foldery (crypto-tracker, krypto-radar itd.) — nie rusza.
# Na czas porządków blokuje cron EMA i bota (te same blokady flock), więc nic nie uruchomi się w połowie.
# Można uruchomić drugi raz — zrobione pomija.
set -eu
R="$(cd "$(dirname "$0")/.." && pwd)"
NEW="$HOME/Crypto_Loser_analytics_tool"
P="$R/pi"

if [ ! -f "$R/collector/pi_dirs.py" ] || ! grep -q "pi_dirs" "$R/collector/ema_monitor.py" \
   || ! grep -q "pi_dirs" "$R/collector/bot.py" || ! grep -q "pi_dirs" "$R/collector/backup.py"; then
  echo "❌ Na Pi nie ma jeszcze nowego kodu (poprawka 83). Wgraj całą paczkę na GitHuba, odczekaj 5 min"
  echo "   (Pi samo robi git pull) albo wykonaj: git -C $R pull --ff-only — i uruchom ponownie."
  exit 1
fi

echo "⏳ Czekam, aż skończy się bieżący przebieg EMA i bota (maks. 5 min)…"
exec 8>/tmp/ema-monitor.lock
flock -w 300 8 || { echo "❌ EMA nadal działa — spróbuj za chwilę"; exit 1; }
exec 9>/tmp/scanner-bot.lock
flock -w 120 9 || { echo "❌ Bot nadal działa — spróbuj za chwilę"; exit 1; }

mkdir -p "$P/logi"
chmod 700 "$P"

move() {  # move SRC DST — tylko gdy SRC jest, a DST jeszcze nie
  if [ -e "$1" ] && [ ! -e "$2" ]; then
    mv "$1" "$2" && echo "✅ $1 → $2"
  elif [ -e "$1" ]; then
    echo "⚠️  $1 zostaje: w $2 już coś jest (sprawdź ręcznie)"
  fi
}

move "$HOME/.ema-monitor"     "$P/stan"
move "$HOME/scanner-archive"  "$P/archiwum"
move "$HOME/.scanner_env"     "$P/scanner_env"
move "$HOME/.scanner_token"   "$P/scanner_token"
move "$HOME/ema-monitor.log"  "$P/logi/ema-monitor.log"
move "$HOME/scanner-bot.log"  "$P/logi/scanner-bot.log"
mkdir -p "$P/stan" "$P/archiwum"
chmod 600 "$P/scanner_env" "$P/scanner_token" 2>/dev/null || true

# zmiana nazwy folderu ~/scanner → ~/Crypto_Loser_analytics_tool
RENAMED=0
if [ "$R" != "$NEW" ]; then
  if [ -e "$NEW" ]; then
    echo "⚠️  $NEW już istnieje — nazwy $R nie zmieniam (sprawdź ręcznie)"
  else
    mv "$R" "$NEW" && RENAMED=1 && echo "✅ $R → $NEW"
    R="$NEW"; P="$R/pi"
  fi
fi

# crontab: tylko nasze dwie linie (folder kodu i logi)
if crontab -l >/dev/null 2>&1; then
  [ -e "$P/crontab-przed-83.txt" ] || crontab -l > "$P/crontab-przed-83.txt"
  NEWTAB=$(crontab -l | sed -E \
    -e 's#(\$HOME|~|/home/[^/ ]+)/ema-monitor\.log#\1/Crypto_Loser_analytics_tool/pi/logi/ema-monitor.log#g' \
    -e 's#(\$HOME|~|/home/[^/ ]+)/scanner-bot\.log#\1/Crypto_Loser_analytics_tool/pi/logi/scanner-bot.log#g')
  if [ "$R" = "$NEW" ]; then
    NEWTAB=$(printf '%s\n' "$NEWTAB" | sed -E 's#(\$HOME|~|/home/[^/ ]+)/scanner/#\1/Crypto_Loser_analytics_tool/#g')
  fi
  if [ "$NEWTAB" != "$(crontab -l)" ]; then
    if printf '%s\n' "$NEWTAB" | crontab -; then
      echo "✅ crontab poprawiony (kopia: $P/crontab-przed-83.txt)"
    else
      echo "❌ Nie udało się zapisać crontaba — cofam zmianę nazwy folderu"
      [ "$RENAMED" = 1 ] && mv "$NEW" "$HOME/scanner"
      exit 1
    fi
  else
    echo "ℹ️  crontab bez zmian"
  fi
  if crontab -l | grep -qE '(\$HOME|~|/home/[^/ ]+)/scanner/'; then
    echo "⚠️  W crontabie zostało odwołanie do ~/scanner/ — pokaż mi je:"
    crontab -l | grep -E '(\$HOME|~|/home/[^/ ]+)/scanner/'
  fi
fi

# stary uruchamiacz skanów (zastąpiony przez bot.py 31.10)
if ! crontab -l 2>/dev/null | grep -q "trigger-oi-monitor"; then
  for f in "$HOME/trigger-oi-monitor.sh" "$HOME/trigger-oi-monitor.log"; do
    [ -e "$f" ] && rm -f "$f" && echo "🗑  usunięty $f"
  done
else
  echo "⚠️  crontab nadal wywołuje trigger-oi-monitor.sh — zostawiam (do sprawdzenia)"
fi

echo
echo "Gotowe. Jeśli terminal był w starym folderze, wpisz: cd ~"
echo "Zawartość $P:"
ls -la "$P"
echo
echo "Crontab teraz:"
crontab -l 2>/dev/null || true
