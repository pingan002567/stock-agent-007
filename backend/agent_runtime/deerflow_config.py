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

from backend.agent_runtime.tools import get_all_workbench_tools

DEFAULT_MODEL = os.getenv("WORKBENCH_AI_MODEL") or "gpt-4o"
DEFAULT_FILENAME = "deerflow_generated_config.yaml"


def _resolve_env(val: str) -> str:
    """Resolve ``$VAR`` placeholders in *val*."""
    if val.startswith("$"):
        return os.getenv(val[1:], "")
    return val


def _build_model_config() -> dict[str, Any]:
    """Build the ``models`` section from env vars."""
    model_name = os.getenv("WORKBENCH_DEERFLOW_MODEL_NAME") or DEFAULT_MODEL
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("WORKBENCH_AI_API_KEY") or ""
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("WORKBENCH_AI_BASE_URL") or ""

    model_cfg: dict[str, Any] = {
        "name": model_name,
        "display_name": model_name,
        "use": "langchain_openai:ChatOpenAI",
        "model": model_name,
        "supports_thinking": False,
        "supports_vision": False,
    }
    if api_key:
        model_cfg["openai_api_key"] = api_key
    if base_url:
        model_cfg["openai_api_base"] = base_url
    return model_cfg


A2_TOOLS = [
    "get_stock_context", "get_daily_history", "search_stock_intel",
    "add_watchlist_item", "remove_watchlist_item",
    "get_monitor_events", "get_monitor_rules", "evaluate_monitor_rules",
    "list_strategies", "get_backtest_result",
    "list_report_templates", "generate_report", "get_report_quality",
]

A3_TOOLS = [
    "get_portfolio_snapshot", "upsert_holding",
    "analyze_portfolio_risk", "get_active_risk_policy",
    "list_risk_policies", "evaluate_policy_risk",
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


def _build_tool_configs() -> list[dict[str, Any]]:
    """Build the ``tools`` section from module-level tool instances."""
    configs: list[dict[str, Any]] = []
    for tool in get_all_workbench_tools():
        configs.append({
            "name": tool.name,
            "group": TOOL_GROUP_MAP.get(tool.name, "a2-research"),
            "use": f"backend.agent_runtime.tools:{tool.name}",
        })
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


def _build_subagent_configs() -> dict[str, dict]:
    """Build the ``subagents.custom_agents`` section from SubagentConfig definitions."""
    from backend.agent_runtime.subagent_configs import (
        STOCK_RESEARCHER, RISK_OFFICER, STRATEGY_ANALYST,
        REBALANCE_PLANNER, STOCK_MONITOR, REPORT_WRITER, VALUATION_ANALYST,
    )
    result = {}
    for cfg in [STOCK_RESEARCHER, RISK_OFFICER, STRATEGY_ANALYST,
                REBALANCE_PLANNER, STOCK_MONITOR, REPORT_WRITER, VALUATION_ANALYST]:
        result[cfg.name] = {
            "description": cfg.description,
            "system_prompt": cfg.system_prompt,
            "tools": cfg.tools,
            "disallowed_tools": cfg.disallowed_tools,
            "max_turns": cfg.max_turns,
            "timeout_seconds": cfg.timeout_seconds,
        }
    return result


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
        "sandbox": {
            "use": "deerflow.sandbox.local:LocalSandboxProvider",
            "allow_host_bash": False,
        },
        "tools": _build_tool_configs(),
        "tool_groups": [
            {"name": "a2-research"},
            {"name": "a3-risk"},
            {"name": "a4-planner"},
            {"name": "a5-blocked"},
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
            "enabled": False,
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
        "memory": {
            "enabled": True,
            "storage_path": "data/deerflow_memory.json",
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
