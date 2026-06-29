#!/usr/bin/env bash
# 已收敛到唯一入口 ./start.sh。本文件保留为薄转发，等价于 `./start.sh --dev`。
exec "$(cd "$(dirname "$0")/.." && pwd)/start.sh" --dev "$@"
