"""extensions_config.json 的读写存取（技能启停的单一属主）。

TeamClaw 单一属主模式：配置只有一个持有者（工作目录的 extensions_config.json，
DeerFlow 的 ``is_skill_enabled`` 直接消费它），设置页是无状态视图——读走这里、
写走这里（原子写），写后由调用方触发 runtime 重建。DB 里历史的 ``skills``
config 键无任何运行时消费者，已废弃。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from backend import paths
from backend.agent_runtime import skill_specs


def _config_path() -> Path:
    override = os.getenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", "").strip()
    return Path(override) if override else paths.extensions_config_path()


def read_extensions() -> dict[str, Any]:
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_extensions(data: dict[str, Any]) -> None:
    """原子写：tmp + rename，DeerFlow 侧按 mtime 失效缓存。"""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_skill_enabled(name: str, enabled: bool) -> None:
    spec = skill_specs.WORKBENCH_SKILLS.get(name)
    if spec is None:
        raise ValueError(f"unknown skill: {name}")
    if spec.locked or not spec.is_subagent:
        raise ValueError(f"skill is locked: {name}")
    data = read_extensions()
    skills = data.setdefault("skills", {})
    entry = skills.setdefault(name, {})
    entry["enabled"] = bool(enabled)
    _write_extensions(data)


def skills_view() -> list[dict[str, Any]]:
    """设置页视图：spec（label/权限/描述）× extensions（enabled）合成。"""
    states = read_extensions().get("skills", {})
    out: list[dict[str, Any]] = []
    for name, spec in skill_specs.WORKBENCH_SKILLS.items():
        if spec.is_subagent:
            description, _tools, _body = skill_specs._read_skill_md(name)
        else:
            # 合成技能（如锁定禁用的执行代理守卫）无 SKILL.md，仍需在视图中可见
            description = spec.synthetic_description
        state = states.get(name, {})
        locked = spec.locked or not spec.is_subagent
        out.append({
            "name": name,
            "label": spec.label,
            "description": description,
            "authority": spec.authority,
            "enabled": bool(spec.enabled) if locked else bool(state.get("enabled", spec.enabled)),
            "locked": locked,
        })
    return out
