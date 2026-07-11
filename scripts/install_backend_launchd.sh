#!/bin/zsh
set -euo pipefail

REPO_DIR="/Users/sudhanshu_thakur/Documents/workspace/binance/trading-system"
PLIST_NAME="com.sudhanshu.trading-system.backend"
PLIST_SOURCE="$REPO_DIR/ops/launchd/${PLIST_NAME}.plist"
PLIST_TARGET="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$REPO_DIR/logs"

cp "$PLIST_SOURCE" "$PLIST_TARGET"
launchctl unload "$PLIST_TARGET" >/dev/null 2>&1 || true
launchctl load "$PLIST_TARGET"

echo "Installed backend launchd job:"
echo "  $PLIST_TARGET"
echo
echo "Check status with:"
echo "  launchctl print gui/$(id -u)/${PLIST_NAME}"
echo
echo "Start immediately with:"
echo "  launchctl kickstart -k gui/$(id -u)/${PLIST_NAME}"
