#!/bin/zsh
set -euo pipefail

REPO_DIR="/Users/sudhanshu_thakur/Documents/workspace/binance/trading-system"
PLIST_NAMES=(
  "com.sudhanshu.trading-system.daily-ops-check"
  "com.sudhanshu.trading-system.evening-ops-check"
  "com.sudhanshu.trading-system.weekend-deep-check"
)

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$REPO_DIR/logs" "$REPO_DIR/daily-checks"

for plist_name in "${PLIST_NAMES[@]}"; do
  plist_source="$REPO_DIR/ops/launchd/${plist_name}.plist"
  plist_target="$HOME/Library/LaunchAgents/${plist_name}.plist"

  cp "$plist_source" "$plist_target"
  launchctl unload "$plist_target" >/dev/null 2>&1 || true
  launchctl load "$plist_target"
done

echo "Installed launchd jobs:"
for plist_name in "${PLIST_NAMES[@]}"; do
  echo "  $HOME/Library/LaunchAgents/${plist_name}.plist"
done
echo
echo "Check status with:"
echo "  launchctl list | rg 'trading-system.(daily|evening|weekend)'"
echo
echo "Run the morning check immediately with:"
echo "  launchctl start com.sudhanshu.trading-system.daily-ops-check"
