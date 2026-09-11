from __future__ import annotations

import yaml

from backend.agent_runtime.deerflow_config import CONTEXT_WINDOW_TOKENS, generate_config


def _generate(tmp_path) -> dict:
    return yaml.safe_load(open(generate_config(tmp_path), encoding="utf-8"))


def test_model_declares_the_context_window_so_fraction_triggers_work(tmp_path):
    """summarization's fraction trigger/keep read model.profile['max_input_tokens'];
    without it LangChain refuses to build the middleware."""
    config = _generate(tmp_path)

    assert CONTEXT_WINDOW_TOKENS == 300_000
    assert config["models"][0]["profile"]["max_input_tokens"] == 300_000


def test_authority_tool_groups_never_include_blocked_and_scale_with_level():
    from backend.agent_runtime.deerflow_config import (
        agent_name_for_authority,
        tool_groups_for_authority,
    )

    a2 = tool_groups_for_authority("A2")
    a3 = tool_groups_for_authority("A3")
    a4 = tool_groups_for_authority("A4")

    assert "a5-blocked" not in a2 + a3 + a4
    assert "a2-research" in a2 and "a4-planner" not in a2 and "a3-risk" not in a2
    assert "a3-risk" in a3 and "a4-planner" not in a3
    assert "a4-planner" in a4
    assert "files" in a2 and "search" in a2
    assert agent_name_for_authority("A2") == "workbench-a2"
    assert agent_name_for_authority("A4") == "workbench-a4"


def test_generate_config_writes_deerflow_agent_configs_with_tool_groups(tmp_path):
    from deerflow.config.agents_config import load_agent_config
    from backend.agent_runtime.deerflow_config import (
        ensure_authority_agents,
        tool_groups_for_authority,
    )

    _generate(tmp_path)
    ensure_authority_agents()

    for level, name in (("A2", "workbench-a2"), ("A3", "workbench-a3"), ("A4", "workbench-a4")):
        agent = load_agent_config(name)
        assert agent is not None
        assert agent.tool_groups == tool_groups_for_authority(level)


def test_get_available_tools_honors_authority_tool_groups(tmp_path):
    """Native DeerFlow filter: A2 schema must not list generate_draft_order."""
    from deerflow.config.app_config import reload_app_config
    from deerflow.tools import get_available_tools
    from backend.agent_runtime.deerflow_config import tool_groups_for_authority

    path = __import__("backend.agent_runtime.deerflow_config", fromlist=["generate_config"]).generate_config(tmp_path)
    app = reload_app_config(path)
    a2 = {t.name for t in get_available_tools(groups=tool_groups_for_authority("A2"), app_config=app)}
    a4 = {t.name for t in get_available_tools(groups=tool_groups_for_authority("A4"), app_config=app)}

    assert "generate_draft_order" not in a2
    assert "generate_draft_order" in a4
    assert "place_real_order" not in a2
    assert "place_real_order" not in a4
    # Builtins stay outside group filter.
    assert "ask_clarification" in a2
    assert "get_daily_history" in a2
    assert "analyze_portfolio_risk" not in a2
    assert "analyze_portfolio_risk" in a4


def test_context_window_is_env_overridable(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_AI_CONTEXT_WINDOW", "128000")
    assert _generate(tmp_path)["models"][0]["profile"]["max_input_tokens"] == 128_000

    monkeypatch.setenv("WORKBENCH_AI_CONTEXT_WINDOW", "not-a-number")
    assert _generate(tmp_path)["models"][0]["profile"]["max_input_tokens"] == 300_000


def test_summarization_gets_a_trim_budget_large_enough_to_produce_a_summary(tmp_path):
    """Leaving trim_tokens_to_summarize unset falls back to LangChain's 4000, which
    returns an empty slice for tool-heavy turns — the summary degrades to a
    placeholder while RemoveMessage still wipes the history."""
    summarization = _generate(tmp_path)["summarization"]

    assert summarization["enabled"] is True
    assert summarization["trim_tokens_to_summarize"] == 16_000
    assert summarization["trim_tokens_to_summarize"] > summarization["keep"]["value"]


def test_tool_output_externalizes_earlier_than_the_deerflow_default(tmp_path):
    """DeerFlow defaults to 12000 chars; our market-data results land just under it
    and would otherwise sit in the thread forever."""
    tool_output = _generate(tmp_path)["tool_output"]

    assert tool_output["enabled"] is True
    assert tool_output["externalize_min_chars"] < 12_000
    assert tool_output["tool_overrides"]["get_daily_history"] < tool_output["externalize_min_chars"]


def test_token_budget_exceeds_the_context_window_because_it_sums_across_calls(tmp_path):
    """The budget is cumulative input+output over every model call in a run, so
    sizing it at one context window hard-stops legitimate multi-step turns."""
    config = _generate(tmp_path)

    assert config["token_budget"]["max_tokens"] > config["models"][0]["profile"]["max_input_tokens"]


def test_generated_config_is_accepted_by_the_deerflow_schema(tmp_path):
    from deerflow.config.app_config import AppConfig

    config = AppConfig.model_validate(_generate(tmp_path))

    assert config.summarization.trim_tokens_to_summarize == 16_000
    assert config.tool_output.externalize_min_chars == 4_000
    assert config.models[0].profile["max_input_tokens"] == 300_000
