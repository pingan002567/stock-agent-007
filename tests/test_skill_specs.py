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



def test_skill_labels_are_capability_names():
    """技能 label 不能是职称。

    用户反馈：设置页技能列表全是「AI 研究员 / AI 风控官」，看不出能做什么。
    这里守住「不出现职称词」这条线，防止以后按旧规范加回去。
    """
    from backend.agent_runtime.skill_specs import WORKBENCH_SKILLS

    titles = ("研究员", "分析师", "风控官", "盯盘员", "报告员", "规划师", "裁判", "执行代理")
    offenders = [
        (name, spec.label)
        for name, spec in WORKBENCH_SKILLS.items()
        if any(word in spec.label for word in titles)
    ]
    assert offenders == [], f"这些 label 还是职称：{offenders}"


def test_profiles_use_capability_names():
    """配置档同样不用职称；旧职称名读取时会被归一。"""
    from backend.config.profiles import DEFAULT_PROFILES, normalize_profile_names

    titles = ("研究员", "分析师", "风控官", "盯盘员", "规划师")
    for profile in DEFAULT_PROFILES:
        assert not any(word in profile["name"] for word in titles), profile["name"]

    migrated = normalize_profile_names([{"name": "AI 风控官", "skills": ["x"]}])
    assert migrated[0]["name"] == "风险审阅档"
    assert migrated[0]["skills"] == ["x"]
    # 幂等：已改过的不再变
    assert normalize_profile_names(migrated) == migrated


def test_tool_labels_cover_all_registered_tools():
    """工具中文名由后端统一下发，必须覆盖全部注册工具。

    实测遗漏过：75 个工具里 Web 缺 24、安卓缺 27，聊天里直接显示英文工具名。
    """
    from backend.config.tool_labels import TOOL_LABELS, tool_label
    from backend.config.tools import DEFAULT_TOOLS

    names = {str(t.get("name")) for t in DEFAULT_TOOLS if t.get("name")}
    missing = sorted(n for n in names if n not in TOOL_LABELS)
    assert missing == [], f"这些工具没有中文名：{missing}"
    assert tool_label("get_crypto_derivatives") == "加密合约"
    # 未登记时不显示「未知」，回退原名
    assert tool_label("not_a_tool") == "not_a_tool"


def test_android_parse_keeps_phase_when_reasoning_arrives_late():
    """安卓端：思维链晚于 tool_call 到达时不能把状态退回 reasoning。

    真实 SSE 顺序是 tool_call → reasoning → tool_result（思维链挂在带 tool_calls
    的分片上）。安卓 applyStreamUpdate 以前无条件 `phase = 'reasoning'`，
    界面上会出现「调用工具…」倒回「思考中…」。
    """
    import re
    from pathlib import Path

    src = Path("mobile-rn/src/api/parse.ts").read_text()
    block = re.search(r"case 'reasoning': \{(.*?)break;", src, re.S)
    assert block, "找不到 reasoning 分支"
    body = block.group(1)
    assert "state.phase !== 'tools'" in body, "reasoning 分支必须避开 tools 状态"
    assert "state.phase !== 'answering'" in body, "reasoning 分支必须避开 answering 状态"


def test_android_steps_interleave_reasoning_and_tools():
    """安卓：steps 要把思考与工具按序保留，且「晚到的思考」插到运行中工具之前。

    后端真实顺序是 tool_call → reasoning → tool_result，若不前插，
    手机上永远是「先工具后思考」，看不出因果。
    """
    import re
    from pathlib import Path

    src = Path("mobile-rn/src/api/parse.ts").read_text()
    # 只看 applyStreamUpdate 里那一段（上面还有个 parseStreamEvent 也有同名分支）
    reducer = src[src.index("export function applyStreamUpdate") :]

    # 工具步在 tool_call 时入列
    tool_call = re.search(r"case 'tool_call': \{(.*?)break;", reducer, re.S)
    assert tool_call and "state.steps.push({ kind: 'tool'" in tool_call.group(1)

    # 思考步：相邻合并 + 运行中工具前插
    # pushReasoningStep 定义在 reducer 之前，要在全文里找
    push = re.search(r"function pushReasoningStep\(.*?\n\}", src, re.S)
    assert push, "找不到 pushReasoningStep"
    body = push.group(0)
    assert "startsWith" in body, "相邻思考要按前缀合并，避免同段重复"
    assert "running" in body and "splice" in body, "晚到的思考要插到运行中的工具之前"

    # 气泡与详情页都要渲染 steps
    bubble = Path("mobile-rn/src/components/AssistantBubble.tsx").read_text()
    assert "assistant.steps ?? []" in bubble
    detail = Path("mobile-rn/src/screens/TurnDetailScreen.tsx").read_text()
    assert "id: 'steps'" in detail
