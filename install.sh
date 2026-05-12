#!/bin/bash
set -e

# ===========================
# Stock Agent 安装脚本 (Mac/Linux)
# ===========================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

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

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║     Stock Agent 安装程序 (Mac/Linux)          ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""

# ===========================
# 1. 检测操作系统
# ===========================
detect_os() {
    OS="$(uname -s)"
    case "$OS" in
        Linux*)     
            if [ -f /etc/debian_version ]; then
                PLATFORM="debian"
                PKG_MANAGER="apt"
            elif [ -f /etc/redhat-release ]; then
                PLATFORM="redhat"
                PKG_MANAGER="yum"
            else
                PLATFORM="linux"
                PKG_MANAGER="unknown"
            fi
            ;;
        Darwin*)    PLATFORM="macos"; PKG_MANAGER="brew";;
        *)          
            err "不支持的操作系统: $OS"
            err "Windows 用户请运行 install.bat"
            pause_and_exit 1
            ;;
    esac
    log "检测到操作系统: $PLATFORM"
}

# ===========================
# 2. 安装系统依赖
# ===========================
install_system_deps() {
    log "检查系统依赖..."
    
    # 检查并安装 Python
    if ! command -v python3 &> /dev/null; then
        log "安装 Python3..."
        case $PLATFORM in
            macos)   brew install python@3.12;;
            debian)  sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip;;
            redhat)  sudo yum install -y python3.12;;
            *)       err "请手动安装 Python 3.12+"; pause_and_exit 1;;
        esac
    fi
    
    # 检查 Python 版本
    PYTHON_VER=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
    PYTHON_MAJOR=$(echo $PYTHON_VER | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VER | cut -d. -f2)
    
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 12 ]); then
        err "需要 Python 3.12+，当前版本 $PYTHON_VER"
        case $PLATFORM in
            macos)   brew install python@3.12;;
            debian)  sudo apt install -y python3.12;;
            *)       err "请手动升级 Python";;
        esac
        pause_and_exit 1
    fi
    ok "Python $(python3 --version 2>&1 | awk '{print $2}')"
    
    # 检查并安装 Node.js
    if ! command -v node &> /dev/null; then
        log "安装 Node.js..."
        case $PLATFORM in
            macos)   brew install node@18;;
            debian)  curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - && sudo apt install -y nodejs;;
            redhat)  curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash - && sudo yum install -y nodejs;;
            *)       err "请手动安装 Node.js 18+"; pause_and_exit 1;;
        esac
    fi
    ok "Node.js $(node --version)"
    
    # 检查并安装 Git
    if ! command -v git &> /dev/null; then
        log "安装 Git..."
        case $PLATFORM in
            macos)   brew install git;;
            debian)  sudo apt install -y git;;
            redhat)  sudo yum install -y git;;
            *)       err "请手动安装 Git"; pause_and_exit 1;;
        esac
    fi
    ok "Git $(git --version | awk '{print $3}')"
}

# ===========================
# 3. 配置环境变量
# ===========================
setup_env() {
    log "配置环境变量..."
    
    if [ ! -f .env ]; then
        if [ -f .env.example ]; then
            cp .env.example .env
            warn "已创建 .env 文件"
            echo ""
            echo "请编辑 .env 文件，填入你的 API Key:"
            echo "  OPENAI_API_KEY=your_api_key_here"
            echo ""
            read -p "是否现在编辑? (y/n): " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                ${EDITOR:-vi} .env
            fi
        fi
    else
        ok ".env 文件已存在"
    fi
}

# ===========================
# 4. 安装 Python 依赖
# ===========================
install_python_deps() {
    log "安装 Python 依赖..."
    
    # 创建虚拟环境
    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
        ok "虚拟环境已创建"
    fi
    
    source .venv/bin/activate
    
    # 安装 uv
    if ! command -v uv &> /dev/null; then
        pip install uv
    fi
    
    # 安装项目依赖
    log "安装项目依赖（可能需要几分钟）..."
    uv pip install -e ".[akshare,yfinance]"
    ok "Python 依赖已安装"
}

# ===========================
# 5. 安装 Node.js 依赖
# ===========================
install_node_deps() {
    log "安装前端依赖..."
    
    cd frontend
    npm install
    cd ..
    
    ok "前端依赖已安装"
}

# ===========================
# 6. 初始化数据库
# ===========================
init_database() {
    log "初始化数据库..."
    
    mkdir -p data log
    
    source .venv/bin/activate
    
    # 启动临时后端
    log "启动临时后端服务..."
    uv run uvicorn backend.app:app --host 127.0.0.1 --port 16666 &
    TEMP_PID=$!
    sleep 5
    
    # 导入数据
    log "导入股票数据..."
    curl -s -X POST http://127.0.0.1:16666/api/stocks/import-a-share-master > /dev/null 2>&1 && ok "A股数据已导入"
    curl -s -X POST http://127.0.0.1:16666/api/stocks/import-hk-master > /dev/null 2>&1 && ok "港股数据已导入"
    curl -s -X POST http://127.0.0.1:16666/api/stocks/import-us-master > /dev/null 2>&1 && ok "美股数据已导入"
    
    # 停止临时后端
    kill $TEMP_PID 2>/dev/null
    wait $TEMP_PID 2>/dev/null
    
    ok "数据库初始化完成"
}

# ===========================
# 主流程
# ===========================
main() {
    detect_os
    install_system_deps
    setup_env
    install_python_deps
    install_node_deps
    init_database
    
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║           安装完成!                           ║"
    echo "╠═══════════════════════════════════════════════╣"
    echo "║                                               ║"
    echo "║  启动命令: ./start.sh                         ║"
    echo "║                                               ║"
    echo "║  或手动启动:                                  ║"
    echo "║    终端1: source .venv/bin/activate           ║"
    echo "║            uv run uvicorn backend.app:app     ║"
    echo "║              --host 0.0.0.0 --port 6666      ║"
    echo "║    终端2: cd frontend && npm run dev          ║"
    echo "║                                               ║"
    echo "╚═══════════════════════════════════════════════╝"
    echo ""
    
    pause_and_exit 0
}

main
