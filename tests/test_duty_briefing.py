"""定时值班任务「统一四段」契约的测试（离线）。

覆盖：
1. submit_duty_briefing 的归一化与校验（结论必填、条目截断、别名兼容）
2. 从 tool_execution 账本提取最后一次成功提交
3. 落盘报告固定四段，结论取自 briefing 而不是正文首行
4. 没有 briefing 时回退：仍然四段，且「结论」不再被标题行污染
"""

from __future__ import annotations

from backend.app_services.duty_briefing import (
    extract_briefing,
    normalize_briefing,
)
from backend.app_services.report_service import _ops_briefing_one_liner
from backend.schemas import ReportGenerateRequest, ToolExecution


def _exec(tool: str, arguments: dict, status: str = "succeeded") -> ToolExecution:
    return ToolExecution(
        execution_id=f"ex_{tool}_{status}",
        tool=tool,
        domain="ops",
        status=status,
        authority_level="A2",
        arguments=arguments,
    )


# ── 1. 归一化 ──────────────────────────────────────────────
def test_normalize_requires_conclusion() -> None:
    try:
        normalize_briefing({"evidence": ["x"]})
    except ValueError as exc:
        assert "conclusion" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("空结论必须报错")


def test_normalize_strips_markdown_and_caps() -> None:
    b = normalize_briefing(
        {
            "conclusion": "**今天别追高**",
            "evidence": ["# 涨停 50 家", "", "  ", "炸板率 27%"],
            "actions": [{"text": "`002467` 减半", "symbol": "002467"}],
            "data_health": ["北向快照滞后"],
        }
    )
    assert b["conclusion"] == "今天别追高"
    assert b["evidence"] == ["涨停 50 家", "炸板率 27%"]  # 去空、去 #，保持顺序
    assert b["actions"] == ["002467 减半"]  # dict 取 text
    assert b["data_health"] == ["北向快照滞后"]


def test_normalize_accepts_aliases() -> None:
    b = normalize_briefing({"summary": "不动", "reasons": ["a"], "next_actions": ["b"]})
    assert b["conclusion"] == "不动"
    assert b["evidence"] == ["a"]
    assert b["actions"] == ["b"]


def test_normalize_caps_items() -> None:
    b = normalize_briefing({"conclusion": "ok", "evidence": [f"e{i}" for i in range(20)]})
    assert len(b["evidence"]) == 8


# ── 2. 从账本提取 ──────────────────────────────────────────
def test_extract_takes_last_successful() -> None:
    executions = [
        _exec("get_stock_context", {"symbol": "002467"}),
        _exec("submit_duty_briefing", {"conclusion": "先写个草稿"}),
        _exec("submit_duty_briefing", {"conclusion": "最终结论", "actions": ["减半"]}),
        _exec("submit_duty_briefing", {"conclusion": "失败的"}, status="failed"),
    ]
    briefing = extract_briefing(executions)
    assert briefing is not None
    assert briefing["conclusion"] == "最终结论"
    assert briefing["actions"] == ["减半"]


def test_extract_returns_none_without_submission() -> None:
    assert extract_briefing([_exec("get_stock_context", {"symbol": "X"})]) is None
    assert extract_briefing([]) is None


# ── 3. 结论不再被标题行污染 ────────────────────────────────
def test_one_liner_skips_headings_and_titles() -> None:
    assert _ops_briefing_one_liner("1. 市场环境（截至 10-22 收盘）**\n今天别追高。") == "今天别追高。"
    assert _ops_briefing_one_liner("收盘体检 10-23 15:15**\n今天没动") == "今天没动"
    assert _ops_briefing_one_liner("今日盘前简报 · 10-23（A股交易日 08:30）\n别加仓") == "别加仓"
    assert _ops_briefing_one_liner("本周复盘（10/12–10/16）\n本周做对了一件事") == "本周做对了一件事"
    # 直接是结论时原样返回
    assert _ops_briefing_one_liner("今天别追高。") == "今天别追高。"


def _ops_report(tmp_path, options: dict):
    from backend.bootstrap import create_services
    from backend.schemas import ReportGenerateRequest

    services = create_services(db_path=tmp_path / "ops.sqlite3", files_root=tmp_path / "files")
    result = services.report_service.generate(
        ReportGenerateRequest(
            report_type="ops_briefing",
            source_type="scheduled_task",
            source_id="sched_close",
            title="收盘值班简报 · 收盘体检",
            options=options,
        )
    )
    return result if hasattr(result, "content") else result["report"]


def test_report_uses_briefing_for_four_sections(tmp_path) -> None:
    report = _ops_report(
        tmp_path,
        {
            "session": "close",
            "narrative": "收盘体检 10-23 15:15**\n随便写点原文",
            "briefing": {
                "conclusion": "今天不动，明天等低开",
                "evidence": ["组合 +0.8%，白酒贡献最大"],
                "actions": ["002467 减半，跌破 4.6 执行"],
                "data_health": ["北向快照滞后 → 资金判断作废"],
            },
        },
    )
    content = report.content
    # 固定四段，顺序稳定
    for title in ("## 依据", "## 动作", "## 数据健康", "## 执行约束"):
        assert title in content
    assert content.index("## 依据") < content.index("## 动作") < content.index("## 数据健康")
    # 结论取 briefing，不是正文首行（正文首行是「收盘体检 10-23 15:15」）
    assert "今天不动，明天等低开" in content
    assert "> **结论**" in content
    assert "随便写点原文" not in content  # 有结构化提交时不再塞原文
    # 结构化字段落到 report payload
    assert report.payload["briefing"]["conclusion"] == "今天不动，明天等低开"


def test_report_falls_back_without_briefing(tmp_path) -> None:
    report = _ops_report(
        tmp_path,
        {
            "session": "intraday",
            "narrative": "盘中报告 · 10-23 11:45\n下午不加仓，等尾盘再看",
            "briefing": None,
        },
    )
    content = report.content
    # 仍然四段
    for title in ("## 依据", "## 动作", "## 数据健康"):
        assert title in content
    # 结论不再是标题行
    assert "盘中报告 · 10-23 11:45" not in content.split("## 依据")[0]
    assert "下午不加仓" in content
    assert "未提交结构化值班结论" in content
