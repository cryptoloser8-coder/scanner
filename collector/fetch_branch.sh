#!/usr/bin/env bash
# Pobiera gałąź danych (data / ema / reports) do katalogu — bezpiecznie:
#   - gałąź istnieje       → git clone (błąd klonowania = błąd kroku, NIE pusty katalog),
#   - gałęzi nie ma (kod 2) → pusty katalog (pierwsze uruchomienie),
#   - nie da się sprawdzić  → błąd kroku.
# Dawniej `git clone … || mkdir` przy chwilowej awarii sieci zaczynał od pustego katalogu,
# a publikacja (force-push) nadpisywała całą historię.
#
#   bash collector/fetch_branch.sh BRANCH DIR REMOTE_URL
set -uo pipefail
BRANCH="$1"
DIR="$2"
REMOTE="$3"

for attempt in 1 2 3; do
  git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    rm -rf "$DIR"
    if git clone -q --depth 1 --branch "$BRANCH" "$REMOTE" "$DIR" 2>/dev/null; then
      echo "Pobrano gałąź $BRANCH"
      exit 0
    fi
    echo "Klonowanie gałęzi $BRANCH nie powiodło się (próba $attempt)" >&2
  elif [ "$rc" -eq 2 ]; then
    mkdir -p "$DIR"
    echo "Gałęzi $BRANCH jeszcze nie ma — zaczynam od pustego katalogu"
    exit 0
  else
    echo "Nie mogę sprawdzić gałęzi $BRANCH (git ls-remote, kod $rc, próba $attempt)" >&2
  fi
  sleep $((attempt * ${FETCH_RETRY_SLEEP:-10}))
done
echo "::error::Nie udało się pobrać gałęzi $BRANCH — przerywam, żeby nie nadpisać historii" >&2
exit 1
