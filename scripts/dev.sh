#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "Shutting down..."
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && echo "Stopped frontend (PID $FRONTEND_PID)"
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null && echo "Stopped backend (PID $BACKEND_PID)"
  wait 2>/dev/null
  echo "All services stopped."
  exit 0
}

trap cleanup SIGINT SIGTERM

# Load .env if present
[ -f "$ROOT/.env" ] && set -a && source "$ROOT/.env" && set +a

# Start backend
echo "Starting backend (port 6666)..."
cd "$ROOT"
NO_PROXY="${NO_PROXY:-eastmoney.com,push2.eastmoney.com,finance.sina.com.cn}" \
no_proxy="${no_proxy:-$NO_PROXY}" \
# AI mode: "direct" auto-generates DeerFlow config (requires OPENAI_API_KEY in env).
# Falls back: direct -> embedded -> stub. This is the most robust default because
# direct mode generates config on the fly and doesn't need pre-existing config files.
WORKBENCH_AI_MODE="${WORKBENCH_AI_MODE:-direct}" \
OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com/v1}" \
WORKBENCH_AI_MODEL="${WORKBENCH_AI_MODEL:-deepseek-chat}" \
WORKBENCH_DEERFLOW_MODE="${WORKBENCH_DEERFLOW_MODE:-}" \
WORKBENCH_DEERFLOW_CONFIG_PATH="${WORKBENCH_DEERFLOW_CONFIG_PATH:-}" \
WORKBENCH_DEERFLOW_MODEL_NAME="${WORKBENCH_DEERFLOW_MODEL_NAME:-}" \
uv run uvicorn backend.app:app --host 0.0.0.0 --port 6666 &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in {1..60}; do
  if curl -s http://127.0.0.1:6666/api/health >/dev/null 2>&1; then
    echo "Backend ready."
    break
  fi
  if [ $i -eq 60 ]; then
    echo "Backend failed to start."
    cleanup
  fi
  sleep 1
done

# Start frontend
echo "Starting frontend (port 8888)..."
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "=========================================="
echo "  Backend:  http://127.0.0.1:6666"
echo "  Frontend: http://127.0.0.1:8888"
echo "  App:      http://127.0.0.1:8888  (dev)"
echo "            http://127.0.0.1:6666/app  (built app if dist exists)"
echo "  Press Ctrl+C to stop all services"
echo "=========================================="
echo ""

wait
