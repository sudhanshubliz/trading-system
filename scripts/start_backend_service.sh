#!/bin/zsh
set -euo pipefail

REPO_DIR="/Users/sudhanshu_thakur/Documents/workspace/binance/trading-system"
EXPECTED_CWD="$REPO_DIR"
DEFAULT_HOST="127.0.0.1"
DEFAULT_PORT="3030"

cd "$REPO_DIR"

if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

HOST="${BACKEND_HOST:-$DEFAULT_HOST}"
PORT="${BACKEND_PORT:-$DEFAULT_PORT}"
PID_FILE="$REPO_DIR/logs/backend_${PORT}.pid"

mkdir -p "$REPO_DIR/logs"

existing_pid="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN -n -P 2>/dev/null | head -n 1 || true)"
if [[ -n "$existing_pid" ]]; then
  existing_cwd="$(lsof -a -p "$existing_pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)"
  if [[ "$existing_cwd" == "$EXPECTED_CWD" ]]; then
    echo "trading-system backend already listening on $HOST:$PORT (pid=$existing_pid)"
    echo "$existing_pid" > "$PID_FILE"
    exit 0
  fi

  echo "refusing to start trading-system backend on $HOST:$PORT" >&2
  echo "port is already occupied by pid=$existing_pid cwd=$existing_cwd" >&2
  echo "expected cwd=$EXPECTED_CWD" >&2
  exit 1
fi

echo "$$" > "$PID_FILE"
trap 'rm -f "$PID_FILE"' EXIT

exec "$REPO_DIR/.venv/bin/python3" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
