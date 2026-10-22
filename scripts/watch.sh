#!/usr/bin/env bash
set -euo pipefail

label=com.mmt.auto-reviewer
repo="$(cd "$(dirname "$0")/.." && pwd)"
logs=("$HOME/Library/Logs/auto-reviewer.log" "$HOME/Library/Logs/auto-reviewer.launchd.log")

touch "${logs[@]}"
"$repo/scripts/install-launchd.sh" >/dev/null

stop() {
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  echo "Stopped $label."
}
trap stop EXIT

uv run --quiet --project "$repo" python -m auto_reviewer.watch "${logs[@]}"
