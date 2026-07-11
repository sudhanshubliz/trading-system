#!/bin/zsh
set -euo pipefail

PLIST_NAME="com.sudhanshu.trading-system.backend"
PLIST_TARGET="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

launchctl unload "$PLIST_TARGET" >/dev/null 2>&1 || true
rm -f "$PLIST_TARGET"

echo "Removed backend launchd job:"
echo "  $PLIST_TARGET"
