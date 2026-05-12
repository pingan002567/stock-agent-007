#!/bin/bash

# ===========================
# Stock Agent 启动脚本 (Mac/Linux)
# ===========================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

BACKEND_PORT=${BACKEND_PORT:-6666}
FRONTEND_PORT=${FRONTEND_PORT:-5173}

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
ok() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; }

pause_and_exit() {
    local code=${1:-0}
    echo ""
    echo -e "${BLUE}按 Enter 键退出...${NC}"
    read -r
    exit $code
}

show_help() {
    echo ""
    echo "Stock Agent 启动脚本 (Mac/Linux)"
    echo ""
    echo "用法: ./start.sh [选项]"
    echo ""
    echo "选项:"
    echo "  --backend-only    仅启动后端"
    echo "  --frontend-only   仅启动前端"
    echo "  --dev             开发模式 (带热重载)"
    echo "  --port PORT       设置后端端口 (默认: 6666)"
    echo "  --help            显示此帮助信息"
    echo ""
}

BACKEND_ONLY=false
FRONTEND_ONLY=false
DEV_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --backend-only) BACKEND_ONLY=true; shift;;
        --frontend-only) FRONTEND_ONLY=true; shift;;
        --dev) DEV_MODE=true; shift;;
        --port) BACKEND_PORT="$2"; shift 2;;
        --help|-h) show_help; pause_and_exit 0;;
        *) err "未知参数: $1"; show_help; pause_and_exit 1;;
    esac
done

check_env() {
    if [ ! -f .env ]; then
        err "未找到 .env 文件"
        echo "  请先运行 ./install.sh 安装依赖"
        echo "  或手动复制 .env.example 为 .env 并配置 API Key"
        pause_and_exit 1
    fi
    
    if [ ! -d ".venv" ]; then
        err "未找到虚拟环境"
        echo "  请先运行 ./install.sh 安装依赖"
        pause_and_exit 1
    fi
    
    if [ ! -d "frontend/node_modules" ]; then
        err "前端依赖未安装"
        echo "  请先运行 ./install.sh 安装依赖"
        pause_and_exit 1
    fi
}

cleanup() {
    echo ""
    log "正在停止服务..."
    
    [ -n "$BACKEND_PID" ] && kill $BACKEND_PID 2>/dev/null && wait $BACKEND_PID 2>/dev/null
    [ -n "$FRONTEND_PID" ] && kill $FRONTEND_PID 2>/dev/null && wait $FRONTEND_PID 2>/dev/null
    
    ok "服务已停止"
    pause_and_exit 0
}

start_backend() {
    log "启动后端服务 (端口: $BACKEND_PORT)..."
    
    source .venv/bin/activate
    
    if [ "$DEV_MODE" = true ]; then
        uv run uvicorn backend.app:app --host 0.0.0.0 --port $BACKEND_PORT --reload --reload-dir backend &
    else
        uv run uvicorn backend.app:app --host 0.0.0.0 --port $BACKEND_PORT &
    fi
    
    BACKEND_PID=$!
    
    log "等待后端启动..."
    for i in {1..30}; do
        if curl -s http://localhost:$BACKEND_PORT/health > /dev/null 2>&1; then
            ok "后端服务已启动"
            return 0
        fi
        sleep 1
    done
    
    warn "后端启动超时，请检查日志: tail -f log/info.log"
    return 1
}

start_frontend() {
    log "启动前端服务 (端口: $FRONTEND_PORT)..."
    
    cd frontend
    
    if [ "$DEV_MODE" = true ]; then
        npm run dev -- --port $FRONTEND_PORT &
    else
        npm run dev -- --port $FRONTEND_PORT &
    fi
    
    FRONTEND_PID=$!
    cd ..
    
    ok "前端服务已启动"
}

show_status() {
    echo ""
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║                    Stock Agent 已启动                     ║"
    echo "╠═══════════════════════════════════════════════════════════╣"
    printf "║  📱 前端:     http://localhost:%-25s║\n" "$FRONTEND_PORT"
    printf "║  🔧 后端:     http://localhost:%-25s║\n" "$BACKEND_PORT"
    printf "║  📚 API文档:  http://localhost:%-25s║\n" "$BACKEND_PORT/docs"
    echo "╠═══════════════════════════════════════════════════════════╣"
    echo "║  按 Ctrl+C 停止服务                                      ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo ""
}

main() {
    echo ""
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║             Stock Agent 启动中... (Mac/Linux)            ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo ""
    
    check_env
    trap cleanup INT TERM
    
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
