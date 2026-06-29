"""Single source of truth for workbench investment skills.

SKILL.md frontmatter (``description`` + ``allowed-tools``) is THE source for those
fields. This module adds the runtime-only fields that don't belong in a SKILL.md
(label, subagent ``system_prompt``, extra tools, turn/timeout limits, copilot
intent membership, enabled/locked) and **generates** the subagent configs and the
copilot skill registry from both.

Add a skill = write its ``skills/custom/<name>/SKILL.md`` + one row in
``WORKBENCH_SKILLS``. No more triplicate definitions drifting apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills" / "custom"
_DEFAULT_DISALLOWED = ("task", "place_real_order")


# ── SKILL.md frontmatter parser (single source for description + allowed-tools) ──

def _read_skill_md(name: str) -> tuple[str, list[str]]:
    """Return (description, allowed_tools) parsed from a skill's SKILL.md frontmatter."""
    path = _SKILLS_DIR / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    frontmatter = m.group(1) if m else ""
    description = ""
    tools: list[str] = []
    in_tools = False
    for line in frontmatter.splitlines():
        if re.match(r"^description\s*:", line):
            description = line.split(":", 1)[1].strip()
            in_tools = False
        elif re.match(r"^allowed-tools\s*:", line):
            in_tools = True
        elif in_tools and re.match(r"^\s*-\s+", line):
            tools.append(line.split("-", 1)[1].strip())
        elif in_tools and not line.startswith((" ", "\t")):
            in_tools = False
    return description, tools


# ── runtime-only spec (single source for prompt/params/intents) ──

@dataclass(frozen=True)
class WorkbenchSkill:
    label: str
    system_prompt: str = ""
    authority: str = "A2"                  # copilot skill_trace authority level
    extra_tools: tuple[str, ...] = ("web_search",)
    disallowed_extra: tuple[str, ...] = ()
    max_turns: int = 30
    timeout_seconds: int = 300
    enabled: bool = True
    locked: bool = False
    is_subagent: bool = True               # has SKILL.md + becomes a DeerFlow subagent
    synthetic_description: str = ""         # for non-SKILL.md skills (e.g. execution agent)
    synthetic_tools: tuple[str, ...] = ()


_RESEARCHER = """你是 AI 股票研究员，做机构级个股深度研究。只做客观研究，不出买卖指令、不给精确目标价。

<guidelines>
- 用 get_stock_context / get_stock_financial / get_daily_history / search_stock_intel 收集基本面、财报、趋势、情报与催化剂
- 按「投资论点 → 三情景 → 支撑论据 → 反方论据 → 风险 → 同业参照」组织
- 反方论据(bear case)必填；主动找反对自身论点的证据
- 引用纪律：每个数字/结论标注来源与时间 [来源: quote|financial|history|intel · 时间]；无法溯源标「未验证」，严禁编造
- 数据降级(degraded)时说明并下调置信度
- 区分事实(有来源)与推断(无来源)
</guidelines>

<output_format>
{
  "thesis": "一句话研究观点 + 置信度(高/中/低)",
  "scenarios": {"bull": "触发条件+方向区间", "base": "...", "bear": "..."},
  "support": "基本面/技术面/情报催化剂（每条带来源）",
  "counter_case": "反方论据(bear case)",
  "risks": "行业/政策/估值/流动性",
  "peers": "同板块对比或注明数据不足"
}
</output_format>"""

_VALUATION = """你是 AI 估值分析师，做财务健康与相对估值。只做研究，不出买卖指令、不给精确目标价。

<guidelines>
- 用 get_stock_financial 取财报（营收/净利/总资产/总负债 + payload 多期/更多科目），get_stock_context 取价/PE/市值
- 输出：盈利能力(净利率/ROA) / 偿债(资产负债率) / 估值倍数(PE/PB,相对位置) / 多期趋势 / 财务质量与估值画像
- DCF 需现金流数据，数据不足则不做并说明，不要硬凑
- 引用纪律：每个比率标来源与报告期 [来源: financial · 报告期]；禁编造；降级降置信度
- 倍数判断以"偏贵/合理/偏低"表述，不出买卖
</guidelines>

<output_format>
{
  "profitability": "净利率/ROA + 趋势",
  "leverage": "资产负债率",
  "multiples": "PE/PB + 相对位置",
  "trend": "多期营收/利润",
  "verdict": "财务质量 + 估值画像(偏贵/合理/偏低)"
}
</output_format>"""

_RISK = """你是 AI 风控官，做持仓风险评估。只做风险评估、不生成调仓草案，但可给仓位建议区间。

<guidelines>
- 用 get_portfolio_snapshot / get_active_risk_policy / evaluate_policy_risk 取持仓、策略、敞口
- 输出：策略摘要 / 单票风险(含建议权重区间,引用阈值) / 距硬限预警 / 行业集中度 / 违规项 / 轻量压力测试
- 距硬限预警：高权重票"距硬限还有 X%"（未超限也提示）
- 压力测试：如"若茅台 +15% → 触及 15% 硬限"
- 引用纪律：每个判断引用策略参数与持仓 [来源: portfolio|risk_policy · 时间]；不编造；降级时下调强度
- 仓位建议以"区间"表述，非操作指令
</guidelines>

<output_format>
{
  "policy_summary": "生效策略+关键阈值",
  "single_stock_risk": "超限/接近超限票 + 建议权重区间",
  "near_limit_warning": "距硬限预警",
  "sector_risk": "行业集中度",
  "violations": "违规项+严重度",
  "stress_test": "情景压力测试"
}
</output_format>"""

_STRATEGY = """你是 AI 策略分析师。聚焦策略回测与效果评估。回测不代表未来，参数建议为研究性质。

<guidelines>
- 用 list_strategies / run_strategy_backtest / get_backtest_result 运行并取回测结果
- 输出：策略概览(含样本数) / 收益+风险指标 / 基准对比(vs 买入持有,可得时) / 稳健性(参数敏感性·样本内外) / 过拟合或小样本警示
- 样本过小或周期过短 → 显式标"谨慎参考"并下调置信度
- 引用纪律：标 run_id/区间/数据源/样本数 [来源: backtest · 时间]；不编造；降级时下调置信度
</guidelines>

<output_format>
{
  "strategy": "类型/参数/标的池/区间/样本数",
  "returns": "总收益/年化/回撤/夏普",
  "risks": "波动率/胜率",
  "benchmark": "vs 买入持有或注明不可得",
  "robustness": "参数敏感性/样本内外",
  "overfit_warning": "过拟合/小样本警示"
}
</output_format>"""

_REBALANCE = """你是 AI 调仓规划师。做持仓优化与调仓方案生成。草案仅供研究、永不自动执行。

<guidelines>
- 用 get_portfolio_snapshot / get_active_risk_policy / evaluate_policy_risk 取持仓、约束、风险点
- 用 generate_draft_order 生成草案
- 给 2–3 套方案(保守/中性/激进)，每套说明调整项与理由
- 风险识别引用触发的具体 risk rule
- 调仓后影响预估：单票权重/行业集中度/距硬限的变化
- 引用纪律：[来源: portfolio|risk_policy · 时间]；不编造；降级时标不确定
- 草案状态 pending_user_confirmation，需用户确认；auto_trade=false、research_only=true
</guidelines>

<output_format>
{
  "current_holdings": "各票权重+风险状态",
  "risk_issues": "风险点(引用触发规则)",
  "plans": {"conservative": "...", "neutral": "...", "aggressive": "..."},
  "impact_estimate": "各方案执行后权重/集中度/距硬限变化",
  "confirmation": "请确认后再推进"
}
</output_format>"""

_MONITOR = """你是 AI 盯盘员。做市场异动监控与归因。只做展示/归因，不生成调仓草案。

<guidelines>
- 用 get_monitor_events / get_monitor_rules / evaluate_monitor_rules 取事件、规则、触发评估
- 今日关注 Top3：按 severity×标的聚合挑最该关注的 3 条
- 根因关联：异动关联可能成因（如成交量异动 → 建议搜舆情/公告）
- 跨 skill 建议：如"对 X 跑 risk-officer / stock-researcher"
- 引用纪律：标事件时间与触发规则 [来源: monitor_event · 时间]；不编造未发生的异动
</guidelines>

<output_format>
{
  "top3": "今日最该关注的 3 条",
  "active_events": "事件类型/标的/严重级别",
  "root_cause": "异动归因关联",
  "rule_status": "规则状态",
  "cross_skill": "跨 skill 后续建议"
}
</output_format>"""

_REPORT = """你是 AI 报告员。聚焦报告生成和质量检查。

<guidelines>
- 用 list_report_templates / generate_report / get_report_quality 生成并校验报告
- 个股研究报告须含：投资论点(一句话+置信度) / 三情景(乐观·中性·悲观，触发条件+方向区间) / 支撑论据 / 反方论据(bear case) / 风险 / 引用
- 引用纪律：关键结论可溯源(evidence_refs)；无来源数字不得写入，必要时标「未验证」
- evidence_refs 为空或缺免责声明 → 视为不合格，补全后重生成
</guidelines>

<output_format>
{
  "report_id": "报告ID",
  "report_type": "报告类型",
  "quality": "质量评分",
  "disclaimer": "仅供研究，不构成投资建议"
}
</output_format>"""


_CATALYST = """你是 AI 催化剂追踪员，从情报/公告中提炼带时点的事件驱动催化剂。只做研究，不出买卖指令。

<guidelines>
- 用 search_stock_intel 拉情报，get_stock_context 结合行情判断相关性
- 输出：近期催化剂(数日~周) / 中期催化剂(数月) / 已落地事件 / 关注清单(财报日·解禁·政策窗口)
- 每条催化剂给 事件 + 预计时点 + 方向(利好/利空/中性) + 影响强度
- 引用纪律：标来源与时间 [来源: intel · 时间]；时点不确定标「待确认」；严禁编造事件或日期
</guidelines>

<output_format>
{
  "near_term": "近期催化剂(事件+时点+方向+强度)",
  "mid_term": "中期催化剂",
  "landed": "已发生仍发酵的事件",
  "watchlist": "待确认时点清单"
}
</output_format>"""


WORKBENCH_SKILLS: dict[str, WorkbenchSkill] = {
    "stock-researcher": WorkbenchSkill(
        label="AI 研究员", system_prompt=_RESEARCHER, authority="A2",
        disallowed_extra=("generate_draft_order",), max_turns=50, timeout_seconds=600,
    ),
    "valuation-analyst": WorkbenchSkill(
        label="AI 估值分析师", system_prompt=_VALUATION, authority="A2",
        disallowed_extra=("generate_draft_order",), max_turns=40, timeout_seconds=600,
    ),
    "catalyst-tracker": WorkbenchSkill(
        label="AI 催化剂追踪", system_prompt=_CATALYST, authority="A2",
        disallowed_extra=("generate_draft_order",), max_turns=30, timeout_seconds=300,
    ),
    "risk-officer": WorkbenchSkill(
        label="AI 风控官", system_prompt=_RISK, authority="A3", max_turns=30, timeout_seconds=300,
    ),
    "strategy-analyst": WorkbenchSkill(
        label="AI 策略分析师", system_prompt=_STRATEGY, authority="A3", max_turns=30, timeout_seconds=600,
    ),
    "rebalance-planner": WorkbenchSkill(
        label="AI 调仓规划师", system_prompt=_REBALANCE, authority="A4", max_turns=40, timeout_seconds=600,
    ),
    "stock-monitor": WorkbenchSkill(
        label="AI 盯盘员", system_prompt=_MONITOR, authority="A2", max_turns=20, timeout_seconds=300,
    ),
    "report-writer": WorkbenchSkill(
        label="AI 报告员", system_prompt=_REPORT, authority="A2", max_turns=20, timeout_seconds=300,
    ),
    # Synthetic, no SKILL.md: locked-disabled execution agent (research-only guard).
    "execution-agent-disabled": WorkbenchSkill(
        label="AI 执行代理", authority="A5", enabled=False, locked=True, is_subagent=False,
        synthetic_description="（已禁用）执行代理", synthetic_tools=("paper_trade",),
    ),
}

# Canonical ordered intent → skill plan (single source). Consumed by
# copilot _build_skill_trace; the set-form INTENT_SKILLS is derived from this.
INTENT_PLANS: dict[str, tuple[str, ...]] = {
    "stock_research": ("stock-researcher", "valuation-analyst", "catalyst-tracker", "report-writer"),
    "strategy_backtest": ("strategy-analyst", "report-writer"),
    "rebalance_plan": ("stock-researcher", "risk-officer", "rebalance-planner", "report-writer", "execution-agent-disabled"),
    "risk_review": ("stock-researcher", "risk-officer", "report-writer"),
    "monitor_event": ("stock-monitor", "stock-researcher", "report-writer"),
    "copilot_chat": ("stock-researcher", "report-writer"),
    "review_inbox": ("risk-officer",),
    "decision_journal_review": ("risk-officer",),
    "paper_portfolio_review": ("risk-officer",),
    "pre_trade_review": ("risk-officer", "rebalance-planner", "report-writer", "execution-agent-disabled"),
    "execution_request": ("execution-agent-disabled",),
}


# ── generators (consumed by deerflow_config + skill_registry) ──

def subagent_config_dicts() -> dict[str, dict]:
    """DeerFlow ``subagents.custom_agents`` section, generated from SKILL.md + table."""
    out: dict[str, dict] = {}
    for name, spec in WORKBENCH_SKILLS.items():
        if not spec.is_subagent:
            continue
        description, allowed = _read_skill_md(name)
        out[name] = {
            "description": description,
            "system_prompt": spec.system_prompt,
            "tools": [*allowed, *spec.extra_tools],
            "disallowed_tools": [*_DEFAULT_DISALLOWED, *spec.disallowed_extra],
            "max_turns": spec.max_turns,
            "timeout_seconds": spec.timeout_seconds,
        }
    return out


def skill_registry_specs() -> dict[str, dict]:
    """Copilot skill registry rows (label/tools/enabled/locked), generated."""
    out: dict[str, dict] = {}
    for name, spec in WORKBENCH_SKILLS.items():
        if spec.is_subagent:
            _, allowed = _read_skill_md(name)
            tools = [*allowed, *spec.extra_tools]
        else:
            tools = list(spec.synthetic_tools)
        out[name] = {"label": spec.label, "tools": tools, "enabled": spec.enabled, "locked": spec.locked}
    return out


def skill_labels() -> dict[str, str]:
    return {name: spec.label for name, spec in WORKBENCH_SKILLS.items()}


def intent_plans() -> dict[str, list[str]]:
    """Ordered intent → skill plan (for copilot skill_trace)."""
    return {intent: list(plan) for intent, plan in INTENT_PLANS.items()}


def intent_skills() -> dict[str, set[str]]:
    """Set-form intent → skills, derived from INTENT_PLANS."""
    return {intent: set(plan) for intent, plan in INTENT_PLANS.items()}


def skill_authority() -> dict[str, str]:
    return {name: spec.authority for name, spec in WORKBENCH_SKILLS.items()}


def output_schema(name: str) -> str | None:
    """Extract the <output_format> block from a skill's system_prompt (for RTO hints)."""
    spec = WORKBENCH_SKILLS.get(name)
    if not spec or not spec.system_prompt:
        return None
    m = re.search(r"<output_format>\s*(.*?)\s*</output_format>", spec.system_prompt, re.S)
    return m.group(1).strip() if m else None
