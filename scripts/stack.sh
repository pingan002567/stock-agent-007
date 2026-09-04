#!/usr/bin/env bash
# 开发栈：脚本直连 uvicorn + Tauri（由 make dev-stack / make dev 调用；正式入口 make run 只开客户端）

if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKEND_PORT="${PORT:-8686}"
DESKTOP_MODE=true
BACKEND_ONLY=false
DEV_MODE=false

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
ok() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; }

show_help() {
  cat <<EOF

Stock Agent 开发栈（正式使用请 make run，仅开 Tauri 客户端）

  make run            打开 Tauri（后端由引导页 / launchd 管理）
  make dev-stack      脚本直连 uvicorn + Tauri
  make dev            同 dev-stack，且后端热重载
  make backend        仅脚本启动后端
  make backend-dev    仅后端热重载（前台）

本脚本供 Makefile 调用，也可直接：

  ./scripts/stack.sh [--dev] [--backend-only] [--port PORT]

EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --desktop) DESKTOP_MODE=true; shift;;
    --backend-only) BACKEND_ONLY=true; DESKTOP_MODE=false; shift;;
    --dev) DEV_MODE=true; shift;;
    --port) BACKEND_PORT="$2"; shift 2;;
    --help|-h) show_help; exit 0;;
    *) err "未知参数: $1"; show_help; exit 1;;
  esac
done

# shellcheck disable=SC1091
source "$ROOT/scripts/load-env.sh"
BACKEND_PORT="${SERVICE_CFG_PORT:-$BACKEND_PORT}"

check_env() {
  [ -f .env ] || warn ".env 不存在（请在设置页连接 LLM 提供商）"
  if [ ! -d ".venv" ]; then err "未找到 .venv，请先运行 make install"; exit 1; fi
  if [ "$DESKTOP_MODE" = true ]; then
    command -v cargo >/dev/null 2>&1 || { err "未找到 cargo，请安装 Rust: https://rustup.rs"; exit 1; }
    cargo tauri --version >/dev/null 2>&1 || {
      err "未找到 tauri-cli: cargo install tauri-cli --version \"^2.0\" --locked"; exit 1;
    }
    [ -d "frontend/node_modules" ] || { err "前端依赖未安装，请运行 make install"; exit 1; }
  fi
}

cleanup() {
  echo ""; log "正在停止服务..."
  [ -n "${TAURI_PID:-}" ] && kill "$TAURI_PID" 2>/dev/null || true
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  ok "服务已停止"; exit 0
}

launchd_backend_ready() {
  if [ "$(uname -s)" != "Darwin" ]; then return 1; fi
  if ! uv run python -m backend.service_cli status 2>/dev/null | grep -q '"service_loaded": true'; then
    return 1
  fi
  curl -sf "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null 2>&1
}

stop_launchd_backend() {
  if [ "$(uname -s)" != "Darwin" ]; then return 0; fi
  if uv run python -m backend.service_cli status 2>/dev/null | grep -q '"service_loaded": true'; then
    warn "检测到 launchd 后端，停止以避免与开发实例冲突..."
    uv run python -m backend.service_cli uninstall >/dev/null 2>&1 || true
    sleep 1
  fi
}

kill_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti "tcp:${port}" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    warn "端口 ${port} 已被占用，终止旧进程..."
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

ensure_frontend_dist() {
  make -C "$ROOT" build-web
}

start_backend() {
  if [ "$DEV_MODE" != true ] && launchd_backend_ready; then
    ensure_frontend_dist
    ok "复用 launchd 后端 (端口: $BACKEND_PORT, 数据: $WORKBENCH_DATA_DIR)"
    return 0
  fi

  stop_launchd_backend
  kill_port "$BACKEND_PORT"
  ensure_frontend_dist
  log "启动后端 (端口: $BACKEND_PORT, 数据: $WORKBENCH_DATA_DIR)..."
  local reload=()
  [ "$DEV_MODE" = true ] && reload=(--reload --reload-dir backend)
  uv run uvicorn backend.app:app --host 127.0.0.1 --port "$BACKEND_PORT" "${reload[@]}" &
  BACKEND_PID=$!
  log "等待后端就绪..."
  for _ in {1..60}; do
    if curl -sf "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
      ok "后端已就绪"; return 0
    fi
    sleep 1
  done
  warn "后端启动超时，请检查日志"; return 1
}

start_desktop() {
  log "启动 Tauri 桌面客户端..."
  (
    cd desktop/src-tauri
    export STOCKAGENT_REPO_ROOT="$ROOT"
    cargo tauri dev
  ) &
  TAURI_PID=$!
  ok "Tauri 桌面壳已启动"
}

show_status() {
  cat <<EOF

==========================================
  🖥️  客户端:  Tauri 桌面应用
  🔧 后端:    http://127.0.0.1:$BACKEND_PORT
  📁 数据:    $WORKBENCH_DATA_DIR
  📚 API文档: http://127.0.0.1:$BACKEND_PORT/docs
  按 Ctrl+C 停止服务
==========================================

EOF
}

main() {
  echo ""; log "Stock Agent 启动中..."
  check_env
  trap cleanup INT TERM
  start_backend || exit 1
  if [ "$DESKTOP_MODE" = true ]; then
    start_desktop
  fi
  show_status
  wait
}

main
