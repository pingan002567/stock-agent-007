#!/usr/bin/env bash
# ===========================
# Stock Agent 启动脚本 (Mac/Linux) — 后端 + Tauri 桌面
# ===========================
# 同时支持 `./start.sh` 与 `sh start.sh`（下方会自动用 bash 重新执行）。

if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

BACKEND_PORT=${BACKEND_PORT:-8686}
DATA_DIR="$PROJECT_DIR/data"

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
ok() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; }

show_help() {
    cat <<EOF

Stock Agent 启动脚本 (Mac/Linux) — Tauri 桌面客户端

用法: ./start.sh [选项]

选项:
  --desktop         启动后端并打开 Tauri 开发壳（默认行为）
  --backend-only    仅启动后端（不打开桌面壳）
  --dev             后端开启热重载 (--reload)；会停止 launchd 并直连 uvicorn
  --port PORT       设置后端端口 (默认: 8686)
  --help            显示此帮助信息

示例:
  ./start.sh                  # 后端 + Tauri 桌面
  ./start.sh --dev            # 后端热重载 + Tauri 桌面
  ./start.sh --backend-only   # 仅后端（已安装 .app 时）

EOF
}

DESKTOP_MODE=true
BACKEND_ONLY=false
DEV_MODE=false
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

check_env() {
    [ -f .env ] || warn ".env 不存在（direct 模式需要 OPENAI_API_KEY；缺失会回退到 stub）"
    if [ ! -d ".venv" ]; then err "未找到 .venv，请先运行 ./install.sh"; exit 1; fi
    if [ "$DESKTOP_MODE" = true ]; then
        if ! command -v cargo >/dev/null 2>&1; then
            err "未找到 cargo，请先安装 Rust: https://rustup.rs"
            exit 1
        fi
        if ! cargo tauri --version >/dev/null 2>&1; then
            err "未找到 tauri-cli，请运行: cargo install tauri-cli --version \"^2.0\" --locked"
            exit 1
        fi
        if [ ! -d "frontend/node_modules" ]; then
            err "前端依赖未安装，请先运行 ./install.sh"
            exit 1
        fi
    fi
}

cleanup() {
    echo ""; log "正在停止服务..."
    [ -n "$TAURI_PID" ] && kill "$TAURI_PID" 2>/dev/null
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
    wait 2>/dev/null
    ok "服务已停止"; exit 0
}

load_env() {
    [ -f .env ] && set -a && source .env && set +a
    export NO_PROXY="${NO_PROXY:-eastmoney.com,push2.eastmoney.com,finance.sina.com.cn}"
    export no_proxy="${no_proxy:-$NO_PROXY}"
    read_service_config
    export WORKBENCH_DATA_DIR="${WORKBENCH_DATA_DIR:-${SERVICE_CFG_DATA_DIR:-$DATA_DIR}}"
    mkdir -p "$WORKBENCH_DATA_DIR"
    export WORKBENCH_AI_MODE="${WORKBENCH_AI_MODE:-direct}"
    export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com/v1}"
    export WORKBENCH_AI_MODEL="${WORKBENCH_AI_MODEL:-deepseek-chat}"
}

read_service_config() {
    SERVICE_CFG_PORT=""
    SERVICE_CFG_DATA_DIR=""
    if [ "$(uname -s)" != "Darwin" ]; then return 0; fi
    local cfg="$HOME/Library/Application Support/StockAgent/service.json"
    [ -f "$cfg" ] || return 0
    # shellcheck disable=SC2046
    eval "$(uv run python - <<'PY'
import json, os, shlex
from pathlib import Path
p = Path.home() / "Library/Application Support/StockAgent/service.json"
try:
    c = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
port = c.get("port")
data = c.get("data_dir")
if port:
    print(f"SERVICE_CFG_PORT={port}")
if data:
    print(f"SERVICE_CFG_DATA_DIR={shlex.quote(str(data))}")
PY
)"
}

launchd_backend_ready() {
    if [ "$(uname -s)" != "Darwin" ]; then return 1; fi
    if ! uv run python -m backend.service_cli status 2>/dev/null | grep -q '"service_loaded": true'; then
        return 1
    fi
    local port="${SERVICE_CFG_PORT:-$BACKEND_PORT}"
    curl -sf "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1
}

stop_launchd_backend() {
    if [ "$(uname -s)" != "Darwin" ]; then return 0; fi
    if uv run python -m backend.service_cli status 2>/dev/null | grep -q '"service_loaded": true'; then
        warn "检测到 launchd 后端，停止以避免与开发实例分歧..."
        uv run python -m backend.service_cli uninstall >/dev/null 2>&1 || true
        sleep 1
    fi
}

kill_port() {
    local port="$1"
    local pids
    pids=$(lsof -ti "tcp:${port}" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        warn "端口 ${port} 已被占用，终止旧后端..."
        # shellcheck disable=SC2086
        kill $pids 2>/dev/null || true
        sleep 1
    fi
}

ensure_frontend_dist() {
    local dist_index="frontend/dist/index.html"
    local src_css="frontend/src/index.css"
    if [ ! -f "$dist_index" ]; then
        warn "frontend/dist 不存在，正在构建..."
    elif [ "$src_css" -nt "$dist_index" ]; then
        warn "检测到前端样式有更新，正在重新构建 frontend/dist..."
    else
        return 0
    fi
    ( cd frontend && npm run build ) || { err "前端构建失败"; exit 1; }
    ok "前端构建完成"
}

start_backend() {
    read_service_config
    BACKEND_PORT="${SERVICE_CFG_PORT:-$BACKEND_PORT}"

    if [ "$DEV_MODE" != true ] && launchd_backend_ready; then
        ensure_frontend_dist
        ok "复用 launchd 后端 (端口: $BACKEND_PORT, 数据: ${SERVICE_CFG_DATA_DIR:-$WORKBENCH_DATA_DIR})"
        return 0
    fi

    stop_launchd_backend
    kill_port "$BACKEND_PORT"
    ensure_frontend_dist
    log "启动后端 (端口: $BACKEND_PORT, 数据: $WORKBENCH_DATA_DIR)..."
    local reload=""
    [ "$DEV_MODE" = true ] && reload="--reload --reload-dir backend"
    uv run uvicorn backend.app:app --host 127.0.0.1 --port "$BACKEND_PORT" $reload &
    BACKEND_PID=$!
    log "等待后端就绪..."
    for i in {1..60}; do
        if curl -s "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
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
        export STOCKAGENT_REPO_ROOT="$PROJECT_DIR"
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
    echo ""; log "Stock Agent 启动中（Tauri 桌面）..."
    check_env
    trap cleanup INT TERM
    load_env
    start_backend || exit 1
    if [ "$DESKTOP_MODE" = true ]; then
        start_desktop
    fi
    show_status
    wait
}

main
