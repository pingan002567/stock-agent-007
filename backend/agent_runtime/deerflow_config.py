"""Runtime generation of a minimal DeerFlow config.yaml.

Generated once at bootstrap and written to a known path.  The config
registers our Workbench tools via ``use:`` reflection so that
``DeerFlowClient`` discovers them as native tools.

Model configuration is derived from runtime environment variables
(OPENAI_API_KEY / OPENAI_BASE_URL / WORKBENCH_AI_MODEL).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from backend import paths
from backend.agent_runtime.tools import get_all_workbench_tools

DEFAULT_MODEL = os.getenv("WORKBENCH_AI_MODEL") or "gpt-4o"
DEFAULT_FILENAME = "deerflow_generated_config.yaml"


def _resolve_env(val: str) -> str:
    """Resolve ``$VAR`` placeholders in *val*."""
    if val.startswith("$"):
        return os.getenv(val[1:], "")
    return val


# 常见多模态模型名特征：命中即默认开 vision（view_image 工具随之可用）。
# WORKBENCH_AI_VISION=1/0 可显式覆盖。
_VISION_MODEL_HINTS = (
    "gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4",
    "claude", "gemini", "qwen-vl", "qwen2-vl", "qvq", "glm-4v", "vision",
)


def _model_supports_vision(model_name: str) -> bool:
    env = os.getenv("WORKBENCH_AI_VISION", "").strip().lower()
    if env in {"1", "true", "on"}:
        return True
    if env in {"0", "false", "off"}:
        return False
    name = model_name.lower()
    return any(hint in name for hint in _VISION_MODEL_HINTS)


CONTEXT_WINDOW_TOKENS = 300_000


def _context_window() -> int:
    raw = os.getenv("WORKBENCH_AI_CONTEXT_WINDOW", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return CONTEXT_WINDOW_TOKENS


def _build_model_config() -> dict[str, Any]:
    """Build the ``models`` section from env vars."""
    # 运行时（reconnect）env 可能已被设置页更新，这里逐次现读，不用 import
    # 时快照的 DEFAULT_MODEL。名字必须与 adapter.stream 传的 model_name 一致，
    # 否则 get_model_config 查不到 → vision 等按模型的能力判定全部失效。
    model_name = (
        os.getenv("WORKBENCH_DEERFLOW_MODEL_NAME")
        or os.getenv("WORKBENCH_AI_MODEL")
        or DEFAULT_MODEL
    )
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("WORKBENCH_AI_API_KEY") or ""
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("WORKBENCH_AI_BASE_URL") or ""

    model_cfg: dict[str, Any] = {
        "name": model_name,
        "display_name": model_name,
        "use": "langchain_openai:ChatOpenAI",
        "model": model_name,
        "supports_thinking": False,
        "supports_vision": _model_supports_vision(model_name),
        # 声明上下文窗口。summarization 的 fraction 触发器与 keep 策略都读
        # model.profile["max_input_tokens"]，缺了就只能退回固定 token 阈值。
        "profile": {"max_input_tokens": _context_window()},
    }
    if api_key:
        model_cfg["openai_api_key"] = api_key
    if base_url:
        model_cfg["openai_api_base"] = base_url
    return model_cfg


A2_TOOLS = [
    "get_stock_context", "get_daily_history", "search_stock_intel",
    "get_industry_context", "get_market_structure", "refresh_market_data",
    "add_watchlist_item", "list_watchlist", "remove_watchlist_item",
    "get_monitor_events", "get_monitor_rules", "evaluate_monitor_rules",
    "list_strategies", "get_backtest_result",
    "list_report_templates", "generate_report", "get_report_quality",
    "list_skills", "list_mcp_servers",
]

A3_TOOLS = [
    "get_portfolio_snapshot", "upsert_holding", "remove_holding",
    "analyze_portfolio_risk", "get_active_risk_policy",
    "list_risk_policies", "evaluate_policy_risk",
    "update_risk_policy", "create_risk_policy", "activate_risk_policy",
    "upsert_monitor_rule", "delete_monitor_rule",
    "run_strategy_backtest", "list_pre_trade_reviews", "list_paper_orders",
    "get_paper_portfolio", "analyze_paper_performance", "create_paper_portfolio_snapshot",
    "list_decision_journal", "get_decision_journal_entry", "summarize_decision_outcomes",
    "list_review_inbox", "summarize_review_inbox",
    "dismiss_inbox_item", "snooze_inbox_item", "mark_inbox_item_done",
    "update_skill", "upsert_mcp_server", "remove_mcp_server",
]

A4_TOOLS = [
    "generate_draft_order", "list_rebalance_drafts", "get_rebalance_draft",
    "confirm_rebalance_draft", "reject_rebalance_draft", "create_pre_trade_review",
]

A5_BLOCKED = ["place_real_order"]

TOOL_GROUP_MAP: dict[str, str] = {}
for t in A2_TOOLS:
    TOOL_GROUP_MAP[t] = "a2-research"
for t in A3_TOOLS:
    TOOL_GROUP_MAP[t] = "a3-risk"
for t in A4_TOOLS:
    TOOL_GROUP_MAP[t] = "a4-planner"
for t in A5_BLOCKED:
    TOOL_GROUP_MAP[t] = "a5-blocked"

# DeerFlow AgentConfig.tool_groups：按会话 authority 选 lead 可见工具组。
# files/search/sandbox-exec 是沙箱与检索组；a5-blocked 永不进入 schema。
# Builtin（task / ask_clarification / present_files）由 get_available_tools
# 在 groups 过滤之外始终注入，无需写进 AgentConfig。
_AUTHORITY_AGENT_NAMES = {
    "A2": "workbench-a2",
    "A3": "workbench-a3",
    "A4": "workbench-a4",
}


def tool_groups_for_authority(level: str | None) -> list[str]:
    """Map request authority → DeerFlow tool_groups (native get_available_tools filter).

    Single-user local workbench: expose the full research/risk/planner surface on
    every session. ``a5-blocked`` (``place_real_order``) stays out of the schema.
    ``level`` is retained for agent_name / audit, not for tool clipping.
    """
    del level  # authority still selects agent_name; tools are intentionally full-open
    groups = ["a2-research", "a3-risk", "a4-planner", "files", "search"]
    if _sandbox_write_tools_enabled() or _sandbox_bash_enabled():
        groups.append("sandbox-exec")
    return groups


def agent_name_for_authority(level: str | None) -> str:
    normalized = str(level or "A2").strip().upper() or "A2"
    if normalized in {"A4", "A5"}:
        return _AUTHORITY_AGENT_NAMES["A4"]
    if normalized == "A3":
        return _AUTHORITY_AGENT_NAMES["A3"]
    return _AUTHORITY_AGENT_NAMES["A2"]


def ensure_user_custom_skills() -> None:
    """Copy repo skill packages into DeerFlow's per-user custom directory once.

    ``skill_manage`` only writes ``users/<id>/skills/custom``. Repo
    ``skills/custom`` is the seed. Once that user directory contains any
    skill, DeerFlow stops loading the repo copies, so every product skill
    must be seeded or it disappears. An existing ``SKILL.md`` is left alone
    so later ``skill_manage`` edits survive restart.
    """
    import shutil

    from deerflow.config.paths import get_paths
    from deerflow.runtime.user_context import DEFAULT_USER_ID

    from backend.paths import REPO_ROOT

    seed_root = REPO_ROOT / "skills" / "custom"
    if not seed_root.is_dir():
        return
    dest_root = get_paths().user_custom_skills_dir(DEFAULT_USER_ID)
    dest_root.mkdir(parents=True, exist_ok=True)
    for skill_dir in sorted(p for p in seed_root.iterdir() if p.is_dir()):
        if skill_dir.name.startswith(".") or not (skill_dir / "SKILL.md").is_file():
            continue
        dest = dest_root / skill_dir.name
        if (dest / "SKILL.md").is_file():
            continue
        for src in skill_dir.rglob("*"):
            rel = src.relative_to(skill_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue
            target = dest / rel
            if src.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)


def _repo_soul_text() -> str:
    from backend.paths import REPO_ROOT

    path = REPO_ROOT / "skills" / "SOUL.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def ensure_authority_agents() -> None:
    """Write DeerFlow AgentConfig YAMLs so tool_groups are loadable by agent_name.

    DeerFlow 原生合同：``load_agent_config(name).tool_groups`` →
    ``get_available_tools(groups=...)``. Embedded ``DeerFlowClient`` 默认忽略
    该字段；适配层把它接到 ``_get_tools``，不另造 allowlist。

    ``update_agent`` only persists SOUL for a per-user agent. A config that
    exists only under the legacy shared ``agents/`` dir is rejected, so the
    same YAML is also written to ``users/<id>/agents/<name>/``. SOUL.md is
    seeded from ``skills/SOUL.md`` once and never overwritten, so later
    ``update_agent`` edits survive restart.
    """
    import yaml
    from deerflow.config.paths import get_paths
    from deerflow.runtime.user_context import DEFAULT_USER_ID

    paths = get_paths()
    agents_dir = paths.agents_dir
    agents_dir.mkdir(parents=True, exist_ok=True)
    seed_soul = _repo_soul_text()
    for level, name in _AUTHORITY_AGENT_NAMES.items():
        payload = {
            "name": name,
            "description": f"Workbench lead agent (authority {level})",
            "tool_groups": tool_groups_for_authority(level),
            # skills 省略（None）：prompt 仍加载全部启用 skill；工具裁剪只靠 tool_groups。
            # 这样不会走 skill allowed-tools 并集把 task/bash/read_file 滤掉。
        }
        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        agent_dir = agents_dir / name
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "config.yaml").write_text(text, encoding="utf-8")
        user_dir = paths.user_agent_dir(DEFAULT_USER_ID, name)
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / "config.yaml").write_text(text, encoding="utf-8")
        soul_path = user_dir / "SOUL.md"
        if seed_soul and not soul_path.is_file():
            soul_path.write_text(seed_soul, encoding="utf-8")


def _sandbox_mode() -> str:
    """沙箱执行模式:docker(aio 容器隔离) / host(Local 本机文件) / readonly。

    默认自动:Docker 守护进程可达 → docker;否则 host。``WORKBENCH_SANDBOX_MODE``
    可强制三者之一;readonly 仅只读文件工具。

    注意:LocalSandboxProvider 在 ``allow_host_bash: true`` 时无法做 per-Agent
    skill 文件系统隔离(DeerFlow 会抛 SandboxRuntimeError)。host 模式下默认
    **关闭** host bash;需要真本机 bash 时显式设
    ``WORKBENCH_SANDBOX_ALLOW_HOST_BASH=1``(并接受技能隔离不可用)。
    """
    forced = os.getenv("WORKBENCH_SANDBOX_MODE", "").strip().lower()
    if forced in {"docker", "host", "readonly"}:
        return forced
    import subprocess
    try:
        probe = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, timeout=3,
        )
        # 某些 docker shim 在守护进程宕机时仍 exit 0:必须校验版本输出非空
        if probe.returncode == 0 and probe.stdout.strip():
            return "docker"
    except Exception:
        pass
    return "host"


def _host_bash_explicitly_allowed() -> bool:
    """Host bash for LocalSandbox (default on for this single-user desktop app).

    Set WORKBENCH_SANDBOX_ALLOW_HOST_BASH=0 to disable. Enabling host bash means
    LocalSandboxProvider cannot enforce per-Agent skill filesystem isolation —
    skill-scoped subagent sandboxes may fail; prefer skill_manage / shared skills.
    """
    return _env_flag("WORKBENCH_SANDBOX_ALLOW_HOST_BASH", default=True)


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _skill_evolution_enabled() -> bool:
    """Agent may create/patch SKILL.md via DeerFlow ``skill_manage`` (default on)."""
    return _env_flag("WORKBENCH_AI_SKILL_EVOLUTION", default=True)


def _sandbox_section(mode: str) -> dict[str, Any]:
    if mode == "docker":
        return {"use": "deerflow.community.aio_sandbox.aio_sandbox_provider:AioSandboxProvider"}
    # Single-user local: host bash defaults on so bash/write_file work without Docker.
    allow_bash = mode == "host" and _host_bash_explicitly_allowed()
    return {
        "use": "deerflow.sandbox.local:LocalSandboxProvider",
        "allow_host_bash": allow_bash,
    }


def _sandbox_write_tools_enabled() -> bool:
    """Register write_file/str_replace (not bash).

    Default on for docker + host so reports/artifacts can land in the sandbox.
    Set WORKBENCH_SANDBOX_WRITE=0 to force read-only file tools.
    """
    mode = _sandbox_mode()
    if mode == "readonly":
        return False
    if mode == "docker":
        return _env_flag("WORKBENCH_SANDBOX_WRITE", default=True)
    if mode == "host":
        return _env_flag("WORKBENCH_SANDBOX_WRITE", default=True)
    return False


def _sandbox_bash_enabled() -> bool:
    mode = _sandbox_mode()
    if mode == "docker":
        return True
    if mode == "host":
        return _host_bash_explicitly_allowed()
    return False


def _sandbox_exec_enabled() -> bool:
    """Any sandbox-exec group tool (write and/or bash)."""
    return _sandbox_write_tools_enabled() or _sandbox_bash_enabled()


def _build_tool_configs() -> list[dict[str, Any]]:
    """Build the ``tools`` section from module-level tool instances."""
    configs: list[dict[str, Any]] = []
    for tool in get_all_workbench_tools():
        configs.append({
            "name": tool.name,
            "group": TOOL_GROUP_MAP.get(tool.name, "a2-research"),
            "use": f"backend.agent_runtime.tools:{tool.name}",
        })
    # Sandbox file tools (read-only set): let the agent read uploaded research
    # docs under /mnt/user-data/uploads (UploadsMiddleware injects the file list
    # per turn; upload_files converts PDF/Word/Excel/PPT to Markdown).
    for _file_tool in ("ls", "glob", "grep", "read_file"):
        configs.append({
            "name": _file_tool, "group": "files",
            "use": f"deerflow.sandbox.tools:{_file_tool}_tool",
        })
    # Write tools: host defaults include bash when allow_host_bash is on.
    # Note: host bash disables DeerFlow per-Agent skill FS isolation.
    exec_tools: list[str] = []
    if _sandbox_write_tools_enabled():
        exec_tools.extend(["write_file", "str_replace"])
    if _sandbox_bash_enabled():
        exec_tools.append("bash")
    # Optional override list, e.g. WORKBENCH_SANDBOX_EXEC_TOOLS=write_file
    override = os.getenv("WORKBENCH_SANDBOX_EXEC_TOOLS", "").strip()
    if override:
        exec_tools = [t.strip() for t in override.split(",") if t.strip()]
    for _exec_tool in exec_tools:
        configs.append({
            "name": _exec_tool, "group": "sandbox-exec",
            "use": f"deerflow.sandbox.tools:{_exec_tool}_tool",
        })
    # present_files 由 harness 内建自动注册,勿重复(会被去重告警跳过)
    # Web search: a single "web_search" tool backed by the best-configured provider.
    # Tavily / Serper register the same tool name, so we pick one (not all). Tavily and
    # Serper need an API key; DuckDuckGo is the keyless default fallback.
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        configs.append({
            "name": "web_search", "group": "search",
            "use": "deerflow.community.tavily.tools:web_search_tool",
            "api_key": tavily_key,
        })
        # Tavily also exposes a URL-content fetcher.
        configs.append({
            "name": "web_fetch", "group": "search",
            "use": "deerflow.community.tavily.tools:web_fetch_tool",
            "api_key": tavily_key,
        })
    elif os.getenv("SERPER_API_KEY"):
        configs.append({
            "name": "web_search", "group": "search",
            "use": "deerflow.community.serper.tools:web_search_tool",
        })
    else:
        configs.append({
            "name": "web_search", "group": "search",
            "use": "deerflow.community.ddg_search.tools:web_search_tool",
        })
    return configs


def _has_enabled_mcp_server() -> bool:
    """extensions_config.json 里是否有启用的 MCP server（直接读文件，不 import DeerFlow）。"""
    import json

    # 兜底与 bootstrap.ensure_workspace_files 一致：MCP 配置在工作目录
    path = os.getenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH") or str(paths.extensions_config_path())
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return False
    servers = data.get("mcpServers") or {}
    return any(
        isinstance(server, dict) and server.get("enabled", True)
        for server in servers.values()
    )


def _build_subagent_configs() -> dict[str, dict]:
    """Build the ``subagents.custom_agents`` section.

    Single source of truth: generated from SKILL.md frontmatter (description +
    allowed-tools) plus the runtime spec table in ``skill_specs``.
    """
    from backend.agent_runtime import skill_specs

    return skill_specs.subagent_config_dicts()


def _ensure_project_config() -> str:
    """Write a minimal project-root ``config.yaml`` that DeerFlow can find.

    DeerFlow's ``AppConfig`` searches for ``config.yaml`` in the project
    root at startup.  Without this file the ``DeerFlowClient`` constructor
    succeeds but a background skill-loading thread fails, which clutters
    logs and may interfere with downstream features.

    We write a minimal viable snippet here so DeerFlow's internal
    ``AppConfig.from_file()`` resolves cleanly.
    """
    # deerflow_config.py is at backend/agent_runtime/deerflow_config.py;
    # parents[2] = project root
    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "config.yaml"
    if config_path.exists():
        return str(config_path)

    minimal: dict[str, Any] = {
        "log_level": "warning",
        "sandbox": {
            "use": "deerflow.sandbox.local:LocalSandboxProvider",
            "allow_host_bash": False,
        },
    }
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(minimal, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return str(config_path)


def generate_config(target_dir: str | Path = "data") -> str:
    """Generate a minimal DeerFlow instance config and return its absolute path.

    Also ensures the project-root ``config.yaml`` exists (via
    ``_ensure_project_config``) so DeerFlow background threads don't
    fail.

    Args:
        target_dir: Directory to write the config file into.

    Returns:
        Absolute path to the generated config file.
    """
    _ensure_project_config()
    # Seed before custom_agents are generated so task() prompts follow
    # skill_manage edits, not the stale repo copy.
    ensure_user_custom_skills()

    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    config_path = target / DEFAULT_FILENAME

    model_cfg = _build_model_config()

    config: dict[str, Any] = {
        "models": [model_cfg],
        "sandbox": _sandbox_section(_sandbox_mode()),
        "tools": _build_tool_configs(),
        "tool_groups": [
            {"name": "a2-research"},
            {"name": "a3-risk"},
            {"name": "a4-planner"},
            {"name": "a5-blocked"},
            {"name": "files"},
            {"name": "search"},
            {"name": "sandbox-exec"},
        ],
        "skills": {
            "path": "skills",
            "container_path": "/mnt/skills",
        },
        # DeerFlow builtin ``skill_manage``: create/patch/edit custom SKILL.md.
        # Off with WORKBENCH_AI_SKILL_EVOLUTION=0. New skills are progressive skills;
        # task() subagents still need a skill_specs.WORKBENCH_SKILLS row.
        "skill_evolution": {
            "enabled": _skill_evolution_enabled(),
            "security_fail_closed": True,
        },
        "title": {
            "enabled": True,
            "max_words": 8,
            "max_chars": 40,
        },
        "tool_search": {
            # harness 的 tool_search 只延迟 MCP 工具（本地 config 工具不受影响）：
            # 配置了启用的 MCP server 时自动打开，省 prompt token。
            "enabled": _has_enabled_mcp_server(),
        },
        "subagents": {
            "timeout_seconds": 900,
            "custom_agents": _build_subagent_configs(),
        },
        "summarization": {
            "enabled": True,
            "trigger": [{"type": "tokens", "value": 32000}],
            "keep": {"type": "tokens", "value": 12000},
            # 关键：摘要前会先 trim_messages(max_tokens=..., start_on="human")。
            # 默认 4000 太小——agent 轮次里一个 user 消息后面跟着一长串 tool 结果,
            # 4000 token 的窗口里找不到 human 边界就返回空,摘要退化成
            # "Previous conversation was too long to summarize.",而 RemoveMessage
            # 照样把整段历史删光。给足预算才能真正产出摘要。
            # 注意：设 null 不等于关闭——DeerFlow 只在非 None 时才透传该参数,
            # null 会落回 LangChain 自己的默认值 4000。
            "trim_tokens_to_summarize": 16000,
            "preserve_recent_skill_count": 3,
            "preserve_recent_skill_tokens": 8000,
        },
        "loop_detection": {
            "enabled": True,
            "warn_threshold": 3,
            "hard_limit": 5,
        },
        "circuit_breaker": {
            "failure_threshold": 5,
            "recovery_timeout_sec": 60,
        },
        "token_usage": {"enabled": True},
        # run 级 token 硬预算。注意语义：这里比的是**本轮所有模型调用的
        # input+output 累加和**,而每次调用都要重发整个上下文,所以它约等于
        # 「模型调用次数 × 单次上下文」,不是「上下文有多大」。拿它当上下文
        # 窗口用会让长任务在第 6~7 步就被硬停。按 300k 窗口 + 压缩后 ≤32k
        # 的单次上下文估算,一轮 30 步左右才到上限。
        "token_budget": {
            "enabled": True,
            "max_tokens": int(os.getenv("WORKBENCH_RUN_TOKEN_BUDGET", "1000000")),
            "warn_threshold": 0.8,
        },
        # 单条工具结果的上限。超过 externalize_min_chars 就落盘成文件 + 预览,
        # 模型要全文得自己 read_file,避免一条结果永久占住每一次后续调用的上下文。
        # DeerFlow 默认 12000 太松:我们的行情类工具单条 8~9.5k 字符,正好钻过去。
        "tool_output": {
            "enabled": True,
            "externalize_min_chars": 4000,
            "tool_overrides": {
                "get_daily_history": 2000,
                "search_stock_intel": 3000,
                "list_rebalance_drafts": 3000,
                "get_market_structure": 3000,
                "refresh_market_data": 2000,
                "analyze_portfolio_risk": 3000,
            },
        },
        "memory": {
            "enabled": True,
            "storage_path": str(paths.data_dir() / "deerflow_memory.json"),
            "debounce_seconds": 30,
            "model_name": None,
            "max_facts": 50,
            "fact_confidence_threshold": 0.7,
            "injection_enabled": True,
            "max_injection_tokens": 1000,
        },
        "guardrails": {
            "enabled": True,
            "provider": {
                "use": "deerflow.guardrails.builtin:AllowlistProvider",
                "config": {
                    "denied_tools": [
                        "place_real_order",
                        "confirm_rebalance_draft",
                    ],
                },
            },
        },
    }

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # DeerFlow AgentConfig（按 authority 的 tool_groups）与主 config 一并落地。
    ensure_authority_agents()

    return str(config_path.resolve())
