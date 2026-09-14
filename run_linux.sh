#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_MAIN="$BASE_DIR/backend/app/main.py"
APP_URL="http://127.0.0.1:8000/"

if [[ ! -f "$BACKEND_MAIN" ]]; then
  echo "Missing backend entry: $BACKEND_MAIN" >&2
  exit 1
fi

pick_python() {
  local candidates=(
    "$BASE_DIR/.venv/bin/python"
    "python3"
    "python"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ "$candidate" == */* ]]; then
      if [[ -x "$candidate" ]]; then
        echo "$candidate"
        return 0
      fi
    elif command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done

  return 1
}

server_ready() {
  "$PYTHON_BIN" -c "import urllib.request; urllib.request.urlopen('$APP_URL', timeout=1).read(1)" >/dev/null 2>&1
}

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$APP_URL" >/dev/null 2>&1 || true
  fi
}

PYTHON_BIN="$(pick_python || true)"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo "No usable Python interpreter found. Expected .venv/bin/python, python3, or python." >&2
  exit 1
fi

if server_ready; then
  echo "Server already running at $APP_URL"
  open_browser
  exit 0
fi

echo "Using Python: $PYTHON_BIN"
"$PYTHON_BIN" "$BACKEND_MAIN" &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup INT TERM

for _ in {1..60}; do
  if server_ready; then
    echo "Prompt tool demo running at $APP_URL"
    open_browser
    wait "$SERVER_PID"
    exit $?
  fi
  sleep 0.5
done

echo "Server did not become ready within 30 seconds." >&2
cleanup
wait "$SERVER_PID" || true
exit 1
