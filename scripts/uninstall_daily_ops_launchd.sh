#!/bin/zsh
set -euo pipefail

PLIST_NAMES=(
  "com.sudhanshu.trading-system.daily-ops-check"
  "com.sudhanshu.trading-system.evening-ops-check"
  "com.sudhanshu.trading-system.weekend-deep-check"
)

for plist_name in "${PLIST_NAMES[@]}"; do
  plist_target="$HOME/Library/LaunchAgents/${plist_name}.plist"
  launchctl unload "$plist_target" >/dev/null 2>&1 || true
  rm -f "$plist_target"
done

echo "Removed launchd jobs:"
for plist_name in "${PLIST_NAMES[@]}"; do
  echo "  $HOME/Library/LaunchAgents/${plist_name}.plist"
done
