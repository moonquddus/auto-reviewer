#!/usr/bin/env bash
set -euo pipefail

label=com.moonquddus.auto-reviewer
logs=("$HOME/Library/Logs/auto-reviewer.log" "$HOME/Library/Logs/auto-reviewer.launchd.log")

touch "${logs[@]}"
"$(dirname "$0")/install-launchd.sh"
echo "Press q to stop."

tail -n 0 -F "${logs[@]}" &
tail_pid=$!

stop() {
  kill "$tail_pid" 2>/dev/null || true
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  echo "Stopped $label."
}
trap stop EXIT

while IFS= read -rsn1 key; do
  [[ $key == q ]] && break
done
