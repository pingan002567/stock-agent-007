"""用户级 AI 凭证与默认值（跨工作区共享，状态目录 ``credentials.json``）。

分层语义（对齐 TeamClaw/opencode/Claude Code 等的行业惯例——密钥跟人、偏好跟档案）：

    档案 DB 的 runtime 配置（非空字段，档案级覆盖）
      > credentials.json（用户级默认：api_key / base_url / model_name）
      > 进程 env（仓库 .env，纯开发兜底）

plist 自此不再携带 AI 密钥（只留数据目录等非机密项）；切换/新建工作区后
AI 仍可用是**设计使然**（用户级默认），档案想用不同的 Key/模型在设置页
保存即成为档案级覆盖。

注意 ``DeerFlowClientAdapter.from_env`` 的解析是 env 优先，因此分层合成结果
需要回写 ``os.environ`` 才能生效；测试强制 stub（WORKBENCH_DEERFLOW_MODE）
时整体短路，不读不写。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend import paths
from backend.config.runtime import DEFAULT_RUNTIME_CONFIG

# credentials.json 只收敛这三个"跟人走"的键；其余 runtime 项都是档案偏好
CRED_KEYS = ("api_key", "base_url", "model_name")

_PLACEHOLDERS = {"your_api_key_here", "sk-xxx", "xxx", ""}


def credentials_path() -> Path:
    # WORKBENCH_CREDENTIALS_PATH：测试隔离/自定义位置（conftest 指向临时目录，
    # 避免开发机上的真实用户凭证泄入测试进程）
    override = os.getenv("WORKBENCH_CREDENTIALS_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return paths.service_state_dir() / "credentials.json"


def load_credentials() -> dict[str, Any]:
    try:
        data = json.loads(credentials_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_credentials(update: dict[str, Any]) -> dict[str, Any]:
    """合并写入（仅认 CRED_KEYS），文件权限 0600。返回合并后的全量。"""
    current = load_credentials()
    for key in CRED_KEYS:
        value = update.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in _PLACEHOLDERS:
            current[key] = value.strip()
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return current


def ensure_credentials() -> None:
    """首次落盘（幂等）：从进程 env 播种——现网该 env 来自旧 plist/.env，
    等于把历史配置一次性迁移为用户级凭证。"""
    if os.getenv("WORKBENCH_DEERFLOW_MODE") == "stub":
        return
    if credentials_path().exists():
        return
    seed = {
        "api_key": os.getenv("OPENAI_API_KEY"),
        "base_url": os.getenv("OPENAI_BASE_URL"),
        "model_name": os.getenv("WORKBENCH_AI_MODEL"),
    }
    seed = {k: v for k, v in seed.items() if v and v.strip() not in _PLACEHOLDERS}
    if seed:
        save_credentials(seed)


def effective_runtime_config(repo) -> dict[str, Any]:
    """分层合成 runtime 配置，并把关键值注入 env（from_env 是 env 优先）。"""
    raw = repo.get_config("runtime", {})
    workspace = raw.get("config", raw) or {}

    if os.getenv("WORKBENCH_DEERFLOW_MODE") == "stub":
        # 测试/显式桩模式：不读用户凭证、不动 env，保持确定性
        return workspace or dict(DEFAULT_RUNTIME_CONFIG)

    ensure_credentials()
    creds = {k: v for k, v in load_credentials().items() if k in CRED_KEYS and v}
    overrides = {k: v for k, v in workspace.items() if v not in (None, "")}
    merged = {**creds, **overrides}

    env_map = {"api_key": "OPENAI_API_KEY", "base_url": "OPENAI_BASE_URL", "model_name": "WORKBENCH_AI_MODEL"}
    for key, env_name in env_map.items():
        if merged.get(key):
            os.environ[env_name] = str(merged[key])

    return merged or dict(DEFAULT_RUNTIME_CONFIG)
