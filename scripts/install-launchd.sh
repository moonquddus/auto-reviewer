#!/usr/bin/env bash
set -euo pipefail

label=com.moonquddus.auto-reviewer
repo="$(cd "$(dirname "$0")/.." && pwd)"
target="$HOME/Library/LaunchAgents/$label.plist"
path="$(dirname "$(command -v claude)"):$(dirname "$(command -v gh)"):$(dirname "$(command -v uv)"):/usr/bin:/bin:/usr/sbin:/sbin"

[[ -f "$repo/config.yaml" ]] || { echo "Missing $repo/config.yaml. Copy config.example.yaml first." >&2; exit 1; }

sed -e "s|__UV__|$(command -v uv)|" -e "s|__REPO__|$repo|g" -e "s|__PATH__|$path|" -e "s|__HOME__|$HOME|" \
  "$repo/launchd/$label.plist" > "$target"

launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$target"
echo "Loaded $label. Log: ~/Library/Logs/auto-reviewer.log"
