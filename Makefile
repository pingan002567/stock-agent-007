# Stock Agent — 构建与运行入口
.DEFAULT_GOAL := help

ROOT        := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PORT        ?= 8686
UV          ?= uv
NPM         ?= npm
CARGO       ?= cargo
export PORT

.PHONY: help install build build-web build-desktop pack run tauri-dev dev-stack dev \
        backend backend-dev test test-web test-e2e lint clean check-venv check-node ensure-web

help: ## 显示可用命令
	@echo ""
	@echo "Stock Agent — Makefile"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "常用（与正式版一致）:"
	@echo "  make install        安装依赖"
	@echo "  make run            打开 Tauri 桌面（后端由引导页 / launchd 启动）"
	@echo "  make build          构建 frontend/dist"
	@echo "  make pack           打包 Tauri 安装包"
	@echo ""
	@echo "开发专用:"
	@echo "  make dev-stack      脚本直连 uvicorn + Tauri（会临时停用 launchd）"
	@echo "  make dev            同 dev-stack，且后端热重载"
	@echo "  make backend-dev    仅 API 热重载（浏览器 / e2e）"
	@echo ""

install: ## 运行 install.sh 安装依赖
	@bash "$(ROOT)/install.sh"

check-venv:
	@test -d "$(ROOT)/.venv" || (echo "未找到 .venv，请先运行: make install" && exit 1)

check-node:
	@test -d "$(ROOT)/frontend/node_modules" || (echo "未找到 frontend/node_modules，请先运行: make install" && exit 1)

ensure-web:
	@if [ ! -f "$(ROOT)/frontend/dist/index.html" ]; then \
		echo "[hint] frontend/dist 缺失，正在构建…"; \
		$(MAKE) build-web; \
	fi

build: build-web ## 构建前端（默认目标）

build-web: check-node ## 构建 SPA 到 frontend/dist
	@echo "[build] frontend/dist ..."
	@cd "$(ROOT)/frontend" && $(NPM) run build
	@echo "[ok] frontend/dist"

build-desktop: build-web check-venv ## 构建 Tauri 桌面 release
	@echo "[build] Tauri desktop ..."
	@cd "$(ROOT)/desktop/src-tauri" && STOCKAGENT_REPO_ROOT="$(ROOT)" $(CARGO) tauri build
	@echo "[ok] 见 desktop/src-tauri/target/release/bundle/"

pack: build-desktop ## 打包桌面客户端（同 build-desktop）

run: ensure-web tauri-dev ## 打开桌面客户端（后端由引导页 / launchd 管理，与正式版一致）

tauri-dev: check-venv check-node ## Tauri 开发壳（首启在引导页 install 注册 launchd 后端）
	@cd "$(ROOT)/desktop/src-tauri" && STOCKAGENT_REPO_ROOT="$(ROOT)" $(CARGO) tauri dev

dev-stack: check-venv ## 开发栈：脚本直连 uvicorn + Tauri（临时停用 launchd）
	@bash "$(ROOT)/scripts/stack.sh" --port $(PORT)

dev: check-venv ## 开发栈 + 后端热重载（临时停用 launchd）
	@bash "$(ROOT)/scripts/stack.sh" --dev --port $(PORT)

backend: check-venv ensure-web ## 仅脚本启动后端（开发调试）
	@bash "$(ROOT)/scripts/stack.sh" --backend-only --port $(PORT)

backend-dev: check-venv ## 仅后端热重载（前台，供 e2e / API 调试）
	@bash -c 'set -a; source "$(ROOT)/scripts/load-env.sh"; set +a; \
		exec $(UV) run uvicorn backend.app:app --host 127.0.0.1 --port $(PORT) --reload --reload-dir backend'

test: check-venv ## 后端 pytest
	@cd "$(ROOT)" && $(UV) run pytest

test-web: check-node ## 前端 vitest
	@cd "$(ROOT)/frontend" && $(NPM) test

test-e2e: check-node ## Playwright e2e
	@cd "$(ROOT)/frontend" && $(NPM) run test:e2e

lint: check-node ## 前端 eslint
	@cd "$(ROOT)/frontend" && $(NPM) run lint

clean: ## 清理构建产物与 Python 缓存
	@rm -rf "$(ROOT)/frontend/dist"
	@find "$(ROOT)" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "[ok] cleaned frontend/dist and __pycache__"
