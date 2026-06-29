#!/usr/bin/env bash
# ===========================
# Stock Agent 单一启动入口 (Mac/Linux)
# ===========================
# 同时支持 `./start.sh` 与 `sh start.sh`（下方会自动用 bash 重新执行）。

# 若不是用 bash 运行（例如 `sh start.sh`），用 bash 重新执行，避免 [[ ]]/数组等语法报错。
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

BACKEND_PORT=${BACKEND_PORT:-6666}
FRONTEND_PORT=${FRONTEND_PORT:-8888}   # 与 frontend/vite.config.ts 一致

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
ok() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; }

show_help() {
    cat <<EOF

Stock Agent 启动脚本 (Mac/Linux) — 唯一入口

用法: ./start.sh [选项]

选项:
  --backend-only    仅启动后端
  --frontend-only   仅启动前端
  --dev             后端开启热重载 (--reload)
  --port PORT       设置后端端口 (默认: 6666)
  --help            显示此帮助信息

EOF
}

BACKEND_ONLY=false; FRONTEND_ONLY=false; DEV_MODE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --backend-only) BACKEND_ONLY=true; shift;;
        --frontend-only) FRONTEND_ONLY=true; shift;;
        --dev) DEV_MODE=true; shift;;
        --port) BACKEND_PORT="$2"; shift 2;;
        --help|-h) show_help; exit 0;;
        *) err "未知参数: $1"; show_help; exit 1;;
    esac
done

check_env() {
    [ -f .env ] || warn ".env 不存在（direct 模式需要 OPENAI_API_KEY；缺失会回退到 stub）"
    if [ ! -d ".venv" ]; then err "未找到 .venv，请先运行 ./install.sh"; exit 1; fi
    if [ "$BACKEND_ONLY" != true ] && [ ! -d "frontend/node_modules" ]; then
        err "前端依赖未安装，请先运行 ./install.sh（或 cd frontend && npm install）"; exit 1
    fi
}

cleanup() {
    echo ""; log "正在停止服务..."
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
    wait 2>/dev/null
    ok "服务已停止"; exit 0
}

load_env() {
    # 载入 .env 并设置 AI / 数据源默认值（原 scripts/dev.sh 的行为）
    [ -f .env ] && set -a && source .env && set +a
    export NO_PROXY="${NO_PROXY:-eastmoney.com,push2.eastmoney.com,finance.sina.com.cn}"
    export no_proxy="${no_proxy:-$NO_PROXY}"
    # direct 模式按需即时生成 DeerFlow 配置（需 OPENAI_API_KEY）；回退 direct->embedded->stub
    export WORKBENCH_AI_MODE="${WORKBENCH_AI_MODE:-direct}"
    export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com/v1}"
    export WORKBENCH_AI_MODEL="${WORKBENCH_AI_MODEL:-deepseek-chat}"
}

start_backend() {
    log "启动后端 (端口: $BACKEND_PORT)..."
    local reload=""
    [ "$DEV_MODE" = true ] && reload="--reload --reload-dir backend"
    uv run uvicorn backend.app:app --host 0.0.0.0 --port "$BACKEND_PORT" $reload &
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

start_frontend() {
    log "启动前端 (端口: $FRONTEND_PORT)..."
    ( cd frontend && npm run dev -- --port "$FRONTEND_PORT" ) &
    FRONTEND_PID=$!
    ok "前端已启动"
}

show_status() {
    cat <<EOF

==========================================
  📱 前端:    http://localhost:$FRONTEND_PORT
  🔧 后端:    http://localhost:$BACKEND_PORT
  📚 API文档: http://localhost:$BACKEND_PORT/docs
  按 Ctrl+C 停止服务
==========================================

EOF
}

main() {
    echo ""; log "Stock Agent 启动中..."
    check_env
    trap cleanup INT TERM
    load_env
    if [ "$FRONTEND_ONLY" = true ]; then
        start_frontend
    elif [ "$BACKEND_ONLY" = true ]; then
        start_backend
    else
        start_backend
        start_frontend
    fi
    show_status
    wait
}

main
