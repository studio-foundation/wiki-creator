#!/usr/bin/env bash
# Runs pytest on athena instead of this machine. The suite loads torch, fastcoref and GLiNER,
# and several sessions running it at once on the laptop ran it out of memory (2026-11-22).
# Usage: scripts/athena-test.sh [pytest args]   (default: -q)
set -euo pipefail

ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
SLUG=$(git -C "$ROOT" branch --show-current | tr '/' '-')
DIR=wiki-test/runs/${SLUG:-detached}

ssh -n athena "mkdir -p $DIR"
# git's own file list, not rsync's .gitignore filter: some fixtures are tracked under an ignored path.
git -C "$ROOT" ls-files -co --exclude-standard | sed 's|^|/|' |
  rsync -az --delete-excluded --prune-empty-dirs --include-from=- --include='*/' --exclude='*' \
    "$ROOT/" "athena:$DIR/"

[ $# -gt 0 ] || set -- -q
# ssh joins its arguments into one string for the remote shell, so each one is quoted first.
ssh athena "bash -s -- $(printf '%q ' "$DIR" "$@")" <<'EOF'
set -euo pipefail
dir=$HOME/$1; shift
cd ~/wiki-test
# One run at a time on athena, install included, in the same queue as `athena-run`:
# two jobs loading models side by side is the same memory problem moved to another host.
mkdir -p ~/athena-run
exec 9>~/athena-run/lock
flock -n 9 || { echo "Waiting for another session's test run on athena"; flock 9; }
stamp=$(sha256sum "$dir/pyproject.toml" | cut -c1-16)
if [ "$(cat .venv/stamp 2>/dev/null)" != "$stamp" ]; then
  [ -x .venv/bin/python ] || python3 -m venv .venv
  # The CPU torch wheel: athena's GPU is an Intel Arc, so the CUDA build only adds gigabytes.
  # WITH_EXTENSION=0: mwparserfromhell has no 3.14 wheel and athena no Python headers to build one.
  WITH_EXTENSION=0 .venv/bin/pip install -q --extra-index-url https://download.pytorch.org/whl/cpu "$dir[dev,models,coref,gliner]"
  # Dependencies only: each run imports wiki_creator from its own synced tree (STU-569).
  .venv/bin/pip uninstall -q -y wiki-creator
  echo "$stamp" > .venv/stamp
fi
cd "$dir"
# Tests spawn a bare `python`, which athena only has inside the venv. Lowest CPU and disk priority:
# athena's own services must not wait on a test run.
PATH=$HOME/wiki-test/.venv/bin:$PATH PYTHONPATH=$dir exec nice -n 19 ionice -c3 python -m pytest "$@"
EOF
