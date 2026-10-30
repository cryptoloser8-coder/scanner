#!/usr/bin/env bash
# Publish the data directory as a single commit on the `data` branch.
# History of the data lives inside the JSON files, so the branch keeps only
# the latest snapshot (force-push) and the repo doesn't grow with every run.
#
#   bash collector/publish.sh DATA_DIR REMOTE_URL
set -euo pipefail
DATA_DIR="$1"
REMOTE="$2"
BRANCH="${DATA_BRANCH:-data}"

cd "$DATA_DIR"
[ -d .git ] || git init -q
git config user.name  "${GIT_AUTHOR_NAME:-oi-monitor-bot}"
git config user.email "${GIT_AUTHOR_EMAIL:-oi-monitor-bot@users.noreply.github.com}"
git checkout -q --orphan "snapshot-$$"
git add -A
git commit -q -m "data: $(date -u +'%Y-%m-%d %H:%M UTC')"
git push -q -f "$REMOTE" "HEAD:refs/heads/$BRANCH"
echo "Opublikowano dane na gałęzi $BRANCH"
