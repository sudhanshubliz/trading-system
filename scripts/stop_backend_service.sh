#!/bin/zsh
set -euo pipefail

REPO_DIR="/Users/sudhanshu_thakur/Documents/workspace/binance/trading-system"
DEFAULT_PORT="3030"

cd "$REPO_DIR"

if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

PORT="${BACKEND_PORT:-$DEFAULT_PORT}"
pid="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN -n -P 2>/dev/null | head -n 1 || true)"

if [[ -z "$pid" ]]; then
  echo "no listening backend found on port $PORT"
  exit 0
fi

cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)"
if [[ "$cwd" != "$REPO_DIR" ]]; then
  echo "refusing to stop pid=$pid on port $PORT because cwd=$cwd" >&2
  echo "expected cwd=$REPO_DIR" >&2
  exit 1
fi

kill "$pid"
echo "stopped trading-system backend on port $PORT (pid=$pid)"
