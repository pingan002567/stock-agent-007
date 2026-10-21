"""Skill 规范的硬性校验（放在 pytest 里，`make test` / CI 都会跑到）。

这些断言不是风格偏好，每条都对应一个真实踩过的坑：

1. **frontmatter name 必须等于目录名** —— DeerFlow 按 name 找
   `<user>/skills/custom/<name>/SKILL.md`，不一致就静默取不到。
2. **allowed-tools 必须是真实存在的工具** —— 写错名字时子代理的工具 schema 里
   没有它，模型只能瞎猜（`get_stock_financial` 曾经不在任何 authority group，
   Lead 完全看不见）。
3. **allowed-tools 的权限不能超过该 skill 的 authority** —— 否则运行时被
   `permission_guard.require` 拒绝（`watch-rule-monitor` 声明 A3 工具却是 A2，
   「帮我盯住某只票」直接失效）。
4. **正文反引号里提到的工具必须在 allowed-tools 内** —— 否则技能在教模型用
   它没有的工具（`sector-rotation-digest` 曾承诺 write_file/bash/generate_report）。
"""

from __future__ import annotations

import re

import pytest

from backend.agent_runtime import skill_specs
from backend.agent_runtime.skill_specs import WORKBENCH_SKILLS, _read_skill_md

# 沙箱/内置工具：不在 tool_bridge 里，但也可能被正文提到
BUILTIN_TOOLS = {"web_search", "read_file", "write_file", "bash", "list_files", "grep", "task"}


def _subagent_names() -> list[str]:
    return sorted(n for n, s in WORKBENCH_SKILLS.items() if s.is_subagent)


def _bridge_tools() -> dict[str, str]:
    """工具名 -> required_authority（A1..A5）。

    直接解析 tool_bridge.py 里的 ToolSpec 表：构造 WorkbenchToolBridge 需要 repo 等
    真实依赖，测试里没必要。
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "backend/agent_runtime/tool_bridge.py"
    text = src.read_text(encoding="utf-8")
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r'"([a-z_]+)": ToolSpec\([^)]*?AuthorityLevel\.(A\d)', text)
    }


@pytest.fixture(scope="module")
def bridge_tools() -> dict[str, str]:
    return _bridge_tools()


@pytest.mark.parametrize("name", _subagent_names())
def test_name_matches_directory(name: str) -> None:
    """frontmatter name 必须等于目录名。"""
    path = skill_specs.skill_md_path(name)
    assert path.is_file(), f"{name}: SKILL.md 不存在"
    assert path.parent.name == name, f"{name}: 目录名 {path.parent.name} 与 name 不一致"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^name:\s*(\S+)", text, re.M)
    assert m, f"{name}: frontmatter 缺 name"
    assert m.group(1) == name, f"{name}: frontmatter name={m.group(1)} 与目录名不一致"


@pytest.mark.parametrize("name", _subagent_names())
def test_allowed_tools_exist(name: str, bridge_tools: dict[str, str]) -> None:
    """allowed-tools 必须都是真实工具（或已知的内置工具）。"""
    _, allowed, _ = _read_skill_md(name)
    assert allowed, f"{name}: allowed-tools 为空"
    unknown = [t for t in allowed if t not in bridge_tools and t not in BUILTIN_TOOLS]
    assert not unknown, f"{name}: 不存在的工具 {unknown}"


@pytest.mark.parametrize("name", _subagent_names())
def test_tool_authority_within_skill(name: str, bridge_tools: dict[str, str]) -> None:
    """allowed-tools 里的工具权限不能超过该 skill 的 authority。"""
    spec = WORKBENCH_SKILLS[name]
    _, allowed, _ = _read_skill_md(name)
    over = [
        (t, bridge_tools[t])
        for t in allowed
        if t in bridge_tools and bridge_tools[t] > spec.authority
    ]
    assert not over, f"{name}(authority={spec.authority}) 声明了更高权限的工具: {over}"


@pytest.mark.parametrize("name", _subagent_names())
def test_body_mentions_only_allowed_tools(name: str, bridge_tools: dict[str, str]) -> None:
    """正文反引号里的工具名必须在 allowed-tools 内。

    只挑「看起来像工具名」的标识符（snake_case 且不是字段名），
    字段名（as_of / degraded / reason…）不在 tool_bridge 里，直接跳过。
    """
    _, allowed, body = _read_skill_md(name)
    allowed_set = set(allowed) | BUILTIN_TOOLS
    mentioned = set(re.findall(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`", body))
    known = set(bridge_tools) | BUILTIN_TOOLS
    offending = sorted(t for t in mentioned if t in known and t not in allowed_set)
    assert not offending, f"{name}: 正文提到了未授权的工具 {offending}（要么加进 allowed-tools，要么改正文）"


@pytest.mark.parametrize("name", _subagent_names())
def test_installed_copy_matches_seed(name: str) -> None:
    """运行时副本若已存在，必须与仓库 seed 一致（防止改了仓库却不生效）。

    `.deer-flow/users/.../skills/custom/<name>` 是 DeerFlow 的用户副本；
    `deerflow_config.ensure_user_custom_skills()` 会在启动时用 seed 覆盖漂移的产品技能。
    全新 checkout 没有副本 → skip。
    """
    installed = skill_specs._installed_skill_md(name)
    if installed is None or not installed.is_file():
        pytest.skip("无运行时副本")
    seed = skill_specs._SKILLS_DIR / name / "SKILL.md"
    assert installed.read_text(encoding="utf-8") == seed.read_text(encoding="utf-8"), (
        f"{name}: 运行时副本与仓库 seed 不一致 —— 重启应用或调用 "
        "ensure_user_custom_skills() 同步"
    )

