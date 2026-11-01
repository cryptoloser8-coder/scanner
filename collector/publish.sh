#!/usr/bin/env bash
# Publish the data directory as a single commit on the `data` branch.
# History of the data lives inside the JSON files, so the branch keeps only
# the latest snapshot (force-push) and the repo doesn't grow with every run.
# Before the force-push the bezpiecznik (collector/guard.py) compares the new
# snapshot with the one on the branch and refuses to publish a version that lost
# history (PUBLISH_ALLOW_SHRINK=1 — intended recomputation, e.g. backfill).
# Copies of every snapshot: weekly GitHub Release (workflow „Archiwum”) and
# daily archive on the Orange Pi (collector/backup.py).
#
#   bash collector/publish.sh DATA_DIR REMOTE_URL
set -euo pipefail
DATA_DIR="$1"
REMOTE="$2"
BRANCH="${DATA_BRANCH:-data}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── bezpiecznik ──
set +e
git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -eq 0 ]; then
  OLD="$(mktemp -d)"
  trap 'rm -rf "$OLD"' EXIT
  git clone -q --depth 1 --branch "$BRANCH" "$REMOTE" "$OLD/cur"
  python3 "$HERE/guard.py" "$OLD/cur" "$DATA_DIR"
elif [ "$rc" -ne 2 ]; then
  echo "::error::Nie mogę sprawdzić gałęzi $BRANCH przed publikacją (kod $rc) — nie publikuję" >&2
  exit 1
fi

cd "$DATA_DIR"
[ -d .git ] || git init -q
git config user.name  "${GIT_AUTHOR_NAME:-oi-monitor-bot}"
git config user.email "${GIT_AUTHOR_EMAIL:-oi-monitor-bot@users.noreply.github.com}"
git checkout -q --orphan "snapshot-$$"
git add -A
git commit -q -m "data: $(date -u +'%Y-%m-%d %H:%M UTC')"
git push -q -f "$REMOTE" "HEAD:refs/heads/$BRANCH"
echo "Opublikowano dane na gałęzi $BRANCH"
