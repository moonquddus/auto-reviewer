#!/usr/bin/env bash
set -euo pipefail

label=com.mmt.auto-reviewer
repo="$(cd "$(dirname "$0")/.." && pwd)"
target="$HOME/Library/LaunchAgents/$label.plist"
path="$(dirname "$(command -v claude)"):$(dirname "$(command -v gh)"):$(dirname "$(command -v uv)"):/usr/bin:/bin:/usr/sbin:/sbin"

settings="$(uv run --quiet --project "$repo" python -c '
from auto_reviewer import config
try:
    print(config.load().poll_seconds, config.directory(), sep="\n")
except config.ConfigError as e:
    raise SystemExit(e)
')"
interval="${settings%%$'\n'*}"
config_dir="${settings#*$'\n'}"

sed -e "s|__UV__|$(command -v uv)|" -e "s|__REPO__|$repo|g" -e "s|__PATH__|$path|" -e "s|__HOME__|$HOME|" \
  -e "s|__INTERVAL__|$interval|" -e "s|__CONFIG__|$config_dir|" \
  "$repo/launchd/$label.plist" > "$target"

launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$target"
echo "Loaded $label. Log: ~/Library/Logs/auto-reviewer.log"
