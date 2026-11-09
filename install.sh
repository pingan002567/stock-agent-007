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
    
    # 找一个 >= 3.12 的解释器：
    #   1) 本机已有的 python3.13 / python3.12 / python3
    #   2) uv 的受管 Python（uv python install，不依赖 Homebrew）
    #   3) 包管理器兜底（macOS 新版上 brew 可能装不上，所以放最后）
    # 这样在 Homebrew 不支持的系统版本（如 macOS 27 预发布）也能装。
    PYTHON_BIN=""
    for cand in python3.13 python3.12 python3; do
        command -v "$cand" >/dev/null 2>&1 || continue
        ver=$("$cand" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null) || continue
        vmajor=${ver%%.*}; vminor=${ver#*.}; vminor=${vminor%%.*}
        if [ "$vmajor" -gt 3 ] || { [ "$vmajor" -eq 3 ] && [ "$vminor" -ge 12 ]; }; then
            PYTHON_BIN=$(command -v "$cand")
            PYTHON_VERSION="$ver"
            break
        fi
    done

    if [ -z "$PYTHON_BIN" ] && command -v uv >/dev/null 2>&1; then
        log "本机没有 Python 3.12+，改用 uv 的受管 Python（不依赖 Homebrew）..."
        uv python install 3.12 >/dev/null 2>&1 || true
        PYTHON_BIN=$(uv python find 3.12 2>/dev/null || true)
        if [ -n "$PYTHON_BIN" ] && [ -x "$PYTHON_BIN" ]; then
            PYTHON_VERSION=$("$PYTHON_BIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
        else
            PYTHON_BIN=""
        fi
    fi

    if [ -z "$PYTHON_BIN" ]; then
        err "需要 Python 3.12+，本机没有可用解释器"
        echo "  建议安装 uv 后重试（uv 会自带受管 Python）："
        echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
        case $PLATFORM in
            debian)  sudo apt install -y python3.12 python3.12-venv;;
            redhat)  sudo yum install -y python3.12;;
            macos)   echo "    brew install python@3.12  # 若系统版本过新，brew 可能不支持";;
        esac
        pause_and_exit 1
    fi
    ok "Python $( "$PYTHON_BIN" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' )（$PYTHON_BIN）"
    
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
# 某些机器上全局 http.proxy 对 curl 有效、对 git 无效（LibreSSL SSL_ERROR_SYSCALL）。
# 这里探测一次：直连能通而默认走代理不通，就**仅本次安装**绕过代理。
prepare_git_network() {
    local probe="https://github.com/bytedance/deer-flow.git"
    local try i
    # 网络可能间歇性抖动：每条约 2 次机会
    for try in 1 2; do
        if git ls-remote --heads "$probe" >/dev/null 2>&1; then
            return 0
        fi
        if git -c http.proxy= -c https.proxy= ls-remote --heads "$probe" >/dev/null 2>&1; then
            warn "git 走全局代理失败，本次安装临时改为直连（不改你的 git 配置）"
            export GIT_CONFIG_COUNT=2
            export GIT_CONFIG_KEY_0=http.proxy
            export GIT_CONFIG_VALUE_0=
            export GIT_CONFIG_KEY_1=https.proxy
            export GIT_CONFIG_VALUE_1=
            return 0
        fi
        for i in 1 2 3; do sleep 1; done
    done
    # 两条路都不通：仍然绕过代理（代理坏的时候直连成功率更高），并让后续重试兜底
    export GIT_CONFIG_COUNT=2
    export GIT_CONFIG_KEY_0=http.proxy
    export GIT_CONFIG_VALUE_0=
    export GIT_CONFIG_KEY_1=https.proxy
    export GIT_CONFIG_VALUE_1=
    warn "暂时连不上 GitHub，安装将重试（也可能是网络抖动）"
}

install_python_deps() {
    log "安装 Python 依赖..."
    prepare_git_network
    
    # 创建虚拟环境（用上面解析出的 3.12+ 解释器）
    if [ ! -d ".venv" ]; then
        if ! "$PYTHON_BIN" -m venv .venv 2>/dev/null; then
            warn "标准 venv 失败，改用 uv venv"
            uv venv --python "$PYTHON_BIN" .venv
        fi
        ok "虚拟环境已创建（$(.venv/bin/python -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')）"
    fi

    source .venv/bin/activate

    # 安装 uv（优先用已装的）
    if ! command -v uv &> /dev/null; then
        if command -v curl &> /dev/null && curl -LsSf https://astral.sh/uv/install.sh | sh; then
            export PATH="$HOME/.local/bin:$PATH"
        else
            pip install uv
        fi
    fi

    # 安装项目依赖（显式指向 .venv，避免 uv 另建环境）
    # 源选择：用户显式指定的优先；默认源失败再回退国内镜像
    # （有些网络能 curl pypi.org 但 uv 的 TLS 握手会 EOF，此时换源即可）
    log "安装项目依赖（可能需要几分钟）..."
    local indexes=()
    [ -n "$UV_INDEX_URL" ] && indexes+=("$UV_INDEX_URL")
    [ -n "$PIP_INDEX_URL" ] && indexes+=("$PIP_INDEX_URL")
    indexes+=("" "https://pypi.tuna.tsinghua.edu.cn/simple" "https://mirrors.aliyun.com/pypi/simple")

    local installed=0 attempt
    export UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT:-120}
    for attempt in 1 2; do
        for idx in "${indexes[@]}"; do
            prepare_git_network
            if [ -n "$idx" ]; then
                if uv pip install --python .venv/bin/python --index-url "$idx" -e ".[akshare,test]"; then
                    [ "$idx" != "" ] && warn "使用镜像源: $idx"
                    installed=1; break 2
                fi
            else
                if uv pip install --python .venv/bin/python -e ".[akshare,test]"; then
                    installed=1; break 2
                fi
            fi
            warn "该源安装失败，换下一个源重试..."
        done
        [ "$attempt" -eq 1 ] && warn "第 1 轮全部失败，等待 3 秒后重试..."
        for i in 1 2 3; do sleep 1; done
    done

    if [ "$installed" -ne 1 ]; then
        err "Python 依赖安装失败"
        echo "  可手动指定源后重试，例如："
        echo "    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple make install"
        pause_and_exit 1
    fi
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
    
    cleanup_temp_backend() { kill ${TEMP_PID:-0} 2>/dev/null || true; }
    trap cleanup_temp_backend EXIT
    # 启动临时后端
    log "启动临时后端服务..."
    .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 16666 &
    TEMP_PID=$!
    sleep 5
    
    # 导入数据
    log "导入股票数据..."
    curl -s -X POST http://127.0.0.1:16666/api/stocks/import-a-share-master > /dev/null 2>&1 && ok "A股数据已导入"
    curl -s -X POST http://127.0.0.1:16666/api/stocks/import-hk-master > /dev/null 2>&1 && ok "港股数据已导入"
    curl -s -X POST http://127.0.0.1:16666/api/stocks/import-us-master > /dev/null 2>&1 && ok "美股数据已导入"
    
    # 停止临时后端
    kill $TEMP_PID 2>/dev/null || true
    wait $TEMP_PID 2>/dev/null || true
    
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
    echo "║  启动命令: make run（桌面客户端）              ║"
    echo "║  开发热重载: make dev                         ║"
    echo "║                                               ║"
    echo "║  或手动调试:                                  ║"
    echo "║    终端1: make backend-dev                    ║"
    echo "║    终端2: make tauri-dev                      ║"
    echo "║                                               ║"
    echo "╚═══════════════════════════════════════════════╝"
    echo ""
    
    pause_and_exit 0
}

main
