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
    # Full-open: every authority sees research + risk + planner groups.
    for groups in (a2, a3, a4):
        assert "a2-research" in groups
        assert "a3-risk" in groups
        assert "a4-planner" in groups
        assert "files" in groups and "search" in groups
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

    from deerflow.config.paths import get_paths
    from deerflow.runtime.user_context import DEFAULT_USER_ID

    user_dir = get_paths().user_agent_dir(DEFAULT_USER_ID, "workbench-a2")
    assert (user_dir / "config.yaml").is_file()
    soul = (user_dir / "SOUL.md").read_text(encoding="utf-8")
    assert "update_agent" in soul


def test_product_skills_are_seeded_into_deerflow_user_custom_dir(tmp_path, monkeypatch):
    import deerflow.config.paths as paths_mod
    from deerflow.runtime.user_context import DEFAULT_USER_ID
    from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
    from backend.agent_runtime.deerflow_config import ensure_user_custom_skills
    from backend.agent_runtime.skill_specs import skill_md_path
    from backend.paths import REPO_ROOT

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(paths_mod, "_paths", None)
    ensure_user_custom_skills()

    dest = paths_mod.get_paths().user_custom_skills_dir(DEFAULT_USER_ID)
    assert (dest / "stock-researcher" / "SKILL.md").is_file()
    assert skill_md_path("stock-researcher") == dest / "stock-researcher" / "SKILL.md"

    # Product skills re-sync from seed when content drifts (allowed-tools updates).
    edited = dest / "stock-researcher" / "SKILL.md"
    seed_text = (REPO_ROOT / "skills" / "custom" / "stock-researcher" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    edited.write_text(seed_text + "\n<!-- user edit -->\n", encoding="utf-8")
    ensure_user_custom_skills()
    assert "user edit" not in edited.read_text(encoding="utf-8")
    assert "create_risk_policy" in (dest / "risk-officer" / "SKILL.md").read_text(encoding="utf-8")

    storage = UserScopedSkillStorage(DEFAULT_USER_ID, host_path=str(REPO_ROOT / "skills"))
    storage.ensure_custom_skill_is_editable("stock-researcher")
    (dest / "notes-only").mkdir()
    (dest / "notes-only" / "SKILL.md").write_text(
        "---\nname: notes-only\ndescription: scratch\n---\nbody\n",
        encoding="utf-8",
    )
    ensure_user_custom_skills()
    assert "scratch" in (dest / "notes-only" / "SKILL.md").read_text(encoding="utf-8")
    names = {skill.name for skill in storage.load_skills()}
    assert "stock-researcher" in names
    assert "notes-only" in names
    assert "sector-rotation-report" in names


def test_patch_skill_policy_builtins_keeps_task_and_web_search():
    from deerflow.skills import tool_policy
    from backend.agent_runtime.deerflow_config import patch_skill_policy_builtins

    before = set(tool_policy.ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)
    patch_skill_policy_builtins()
    after = set(tool_policy.ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)
    assert "task" in after
    assert "web_search" in after
    assert before <= after

def test_get_available_tools_honors_authority_tool_groups(tmp_path):
    """Native DeerFlow filter: full-open schema includes planner tools; A5 stays out."""
    from deerflow.config.app_config import reload_app_config
    from deerflow.tools import get_available_tools
    from backend.agent_runtime.deerflow_config import tool_groups_for_authority

    path = __import__("backend.agent_runtime.deerflow_config", fromlist=["generate_config"]).generate_config(tmp_path)
    app = reload_app_config(path)
    a2 = {t.name for t in get_available_tools(groups=tool_groups_for_authority("A2"), app_config=app)}
    a4 = {t.name for t in get_available_tools(groups=tool_groups_for_authority("A4"), app_config=app)}

    assert "generate_draft_order" in a2
    assert "generate_draft_order" in a4
    assert "place_real_order" not in a2
    assert "place_real_order" not in a4
    # Builtins stay outside group filter.
    assert "ask_clarification" in a2
    assert "get_daily_history" in a2
    assert "analyze_portfolio_risk" in a2
    assert "analyze_portfolio_risk" in a4
    assert "bash" in a2
    assert "write_file" in a2
    assert "skill_manage" in a2


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


def test_local_sandbox_defaults_to_host_bash_on(monkeypatch, tmp_path):
    monkeypatch.delenv("WORKBENCH_SANDBOX_MODE", raising=False)
    monkeypatch.delenv("WORKBENCH_SANDBOX_ALLOW_HOST_BASH", raising=False)
    monkeypatch.delenv("WORKBENCH_SANDBOX_WRITE", raising=False)
    monkeypatch.setattr(
        "backend.agent_runtime.deerflow_config._sandbox_mode",
        lambda: "host",
    )
    from backend.agent_runtime import deerflow_config as cfg

    section = cfg._sandbox_section("host")
    assert section["allow_host_bash"] is True
    assert cfg._sandbox_bash_enabled() is True
    assert cfg._sandbox_write_tools_enabled() is True
    assert cfg._sandbox_exec_enabled() is True

    monkeypatch.setenv("WORKBENCH_SANDBOX_ALLOW_HOST_BASH", "0")
    assert cfg._sandbox_section("host")["allow_host_bash"] is False
    assert cfg._sandbox_bash_enabled() is False


def test_authority_tool_groups_include_sandbox_exec_when_write_on(monkeypatch):
    monkeypatch.delenv("WORKBENCH_SANDBOX_ALLOW_HOST_BASH", raising=False)
    monkeypatch.delenv("WORKBENCH_SANDBOX_WRITE", raising=False)
    monkeypatch.setattr(
        "backend.agent_runtime.deerflow_config._sandbox_mode",
        lambda: "host",
    )
    from backend.agent_runtime.deerflow_config import tool_groups_for_authority

    assert "sandbox-exec" in tool_groups_for_authority("A2")

    monkeypatch.setenv("WORKBENCH_SANDBOX_WRITE", "0")
    monkeypatch.setenv("WORKBENCH_SANDBOX_ALLOW_HOST_BASH", "0")
    assert "sandbox-exec" not in tool_groups_for_authority("A2")


def test_generated_config_enables_skill_evolution_and_write_file(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBENCH_AI_SKILL_EVOLUTION", raising=False)
    monkeypatch.delenv("WORKBENCH_SANDBOX_WRITE", raising=False)
    monkeypatch.delenv("WORKBENCH_SANDBOX_ALLOW_HOST_BASH", raising=False)
    monkeypatch.setattr(
        "backend.agent_runtime.deerflow_config._sandbox_mode",
        lambda: "host",
    )
    config = _generate(tmp_path)
    assert config["skill_evolution"]["enabled"] is True
    assert config["sandbox"]["allow_host_bash"] is True
    tool_names = {t["name"] for t in config["tools"]}
    assert "write_file" in tool_names
    assert "str_replace" in tool_names
    assert "bash" in tool_names

    monkeypatch.setenv("WORKBENCH_AI_SKILL_EVOLUTION", "0")
    config_off = _generate(tmp_path)
    assert config_off["skill_evolution"]["enabled"] is False
