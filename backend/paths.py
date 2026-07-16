"""统一路径解析：桌面化改造的 cwd 陷阱修复（doc/DESKTOP_APP_PLAN.md §2 改造清单 1）。

三类路径，职责分离（§3.1.3）：
- 数据目录（可选）：SQLite/生成文件。开发态默认仓库内 ``data/``（与历史行为一致），
  桌面态经 launchd plist 下发 ``WORKBENCH_DATA_DIR`` 指到
  ``~/Library/Application Support/StockAgent``。
- 服务状态目录（固定不可选）：plist 引用的 service.json（端口/数据目录）与服务日志。
  固定路径是为了壳在后端启动前就能找到它。
- 前端产物：锚定仓库根，不再依赖进程 cwd。
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

APP_NAME = "StockAgent"


def data_dir() -> Path:
    """数据目录：WORKBENCH_DATA_DIR 优先；缺省保持历史行为（cwd 下 data/）。"""
    env = os.getenv("WORKBENCH_DATA_DIR", "").strip()
    return Path(env).expanduser() if env else Path("data")


def default_db_path() -> Path:
    return data_dir() / "workbench.sqlite3"


def default_files_root() -> Path:
    return data_dir() / "files"


def frontend_dist() -> Path:
    """SPA 构建产物：WORKBENCH_FRONTEND_DIST 优先，缺省锚定仓库根。"""
    env = os.getenv("WORKBENCH_FRONTEND_DIST", "").strip()
    return Path(env).expanduser() if env else REPO_ROOT / "frontend" / "dist"


def extensions_config_path() -> Path:
    """MCP 服务器配置：用户配置属于工作目录（随档案迁移/备份）。
    历史位置在仓库根，由 bootstrap.ensure_workspace_files() 做一次性迁移。"""
    return data_dir() / "extensions_config.json"


def workspace_meta_path() -> Path:
    """档案元信息（名称/创建时间/schema 版本），多工作区切换器的显示与迁移依据。"""
    return data_dir() / "workspace.json"


def service_state_dir() -> Path:
    """服务状态目录（固定）：service.json + 日志。macOS 约定位置。"""
    return Path.home() / "Library" / "Application Support" / APP_NAME


def default_desktop_data_dir() -> Path:
    """桌面态数据目录默认值（约定优于配置，可在首启引导中另选）。"""
    return service_state_dir() / "data"
