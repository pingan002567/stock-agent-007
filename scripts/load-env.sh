#!/usr/bin/env bash
# 加载 Stock Agent 运行环境（由 Makefile / scripts/stack.sh 调用）

if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${DATA_DIR:-$ROOT/data}"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export NO_PROXY="${NO_PROXY:-eastmoney.com,push2.eastmoney.com,finance.sina.com.cn}"
export no_proxy="${no_proxy:-$NO_PROXY}"

SERVICE_CFG_PORT=""
SERVICE_CFG_DATA_DIR=""
if [ "$(uname -s)" = "Darwin" ]; then
  cfg="$HOME/Library/Application Support/StockAgent/service.json"
  if [ -f "$cfg" ]; then
    # shellcheck disable=SC2046
    eval "$(cd "$ROOT" && uv run python - <<'PY'
import json, shlex
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
  fi
fi

export WORKBENCH_DATA_DIR="${WORKBENCH_DATA_DIR:-${SERVICE_CFG_DATA_DIR:-$DATA_DIR}}"
mkdir -p "$WORKBENCH_DATA_DIR"
export WORKBENCH_AI_MODE="${WORKBENCH_AI_MODE:-direct}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com/v1}"
export WORKBENCH_AI_MODEL="${WORKBENCH_AI_MODEL:-deepseek-v4-flash}"

export BACKEND_PORT="${SERVICE_CFG_PORT:-${BACKEND_PORT:-8686}}"
