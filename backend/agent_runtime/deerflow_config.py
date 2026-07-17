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
    }
    if api_key:
        model_cfg["openai_api_key"] = api_key
    if base_url:
        model_cfg["openai_api_base"] = base_url
    return model_cfg


A2_TOOLS = [
    "get_stock_context", "get_daily_history", "search_stock_intel",
    "get_industry_context",
    "add_watchlist_item", "remove_watchlist_item",
    "get_monitor_events", "get_monitor_rules", "evaluate_monitor_rules",
    "list_strategies", "get_backtest_result",
    "list_report_templates", "generate_report", "get_report_quality",
]

A3_TOOLS = [
    "get_portfolio_snapshot", "upsert_holding",
    "analyze_portfolio_risk", "get_active_risk_policy",
    "list_risk_policies", "evaluate_policy_risk",
    "upsert_monitor_rule", "delete_monitor_rule",
    "run_strategy_backtest", "list_pre_trade_reviews", "list_paper_orders",
    "get_paper_portfolio", "analyze_paper_performance", "create_paper_portfolio_snapshot",
    "list_decision_journal", "get_decision_journal_entry", "summarize_decision_outcomes",
    "list_review_inbox", "summarize_review_inbox",
    "dismiss_inbox_item", "snooze_inbox_item", "mark_inbox_item_done",
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


def _sandbox_mode() -> str:
    """沙箱执行模式:docker(aio 容器隔离) / host(Local 受控 host bash) / readonly。

    默认自动:Docker 守护进程可达 → docker;否则 host——单用户本地工作台的信任
    模型等同于用户自己在本机跑 agent 工具(SandboxAudit 审计 + 命令/路径安全层
    仍然生效)。``WORKBENCH_SANDBOX_MODE`` 可强制三者之一;readonly 恢复旧行为
    (仅只读文件工具,无 bash/写盘)。
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


def _sandbox_section(mode: str) -> dict[str, Any]:
    if mode == "docker":
        return {"use": "deerflow.community.aio_sandbox.aio_sandbox_provider:AioSandboxProvider"}
    return {
        "use": "deerflow.sandbox.local:LocalSandboxProvider",
        "allow_host_bash": mode == "host",
    }


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
    # per turn; upload_files converts PDF/Word/Excel/PPT to Markdown). Write
    # tools (write_file/str_replace/bash) are intentionally NOT registered.
    for _file_tool in ("ls", "glob", "grep", "read_file"):
        configs.append({
            "name": _file_tool, "group": "files",
            "use": f"deerflow.sandbox.tools:{_file_tool}_tool",
        })
    # 沙箱代码执行(P0,doc/DEERFLOW_21_RESEARCH.md):bash/写盘让 AI 能"写代码算"
    # ——自定义指标/归因/压力测试/画图;产物经 present_files 呈现。readonly 模式不注册。
    if _sandbox_mode() != "readonly":
        _exec_set = tuple(
            t.strip() for t in os.getenv(
                "WORKBENCH_SANDBOX_EXEC_TOOLS", "bash,write_file,str_replace"
            ).split(",") if t.strip()
        )
        for _exec_tool in _exec_set:
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
            {"name": "sandbox-exec"},
        ],
        "skills": {
            "path": "skills",
            "container_path": "/mnt/skills",
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
            "keep": {"type": "messages", "value": 10},
            "preserve_recent_skill_count": 5,
            "preserve_recent_skill_tokens": 25000,
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
        # run 级 token 硬预算(意图预算管"能拉谁",这里管"最多烧多少")
        "token_budget": {
            "enabled": True,
            "max_tokens": int(os.getenv("WORKBENCH_RUN_TOKEN_BUDGET", "300000")),
            "warn_threshold": 0.8,
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

    return str(config_path.resolve())
