"""工具结果投影：让调用方用入参决定要哪些字段、要多少条。

行情类工具的原始返回（90 根 K 线约 9KB）一旦进了 agent 线程，之后每一次模型
调用都要重发一遍，还会把摘要中间件的裁剪窗口撑爆。这里提供统一的字段投影 +
条数截断，并在截断时留一句「怎么拿全量」的提示，模仿 read_file 的续读约定。
"""

from __future__ import annotations

from typing import Any, Iterable

DetailLevel = str

# 三档：summary（默认，只回统计 + 少量近端样本）、指定字段投影、full（原样）
DETAIL_SUMMARY = "summary"
DETAIL_FULL = "full"

BACKTEST_SUMMARY_FIELDS = (
    "run_id",
    "strategy_id",
    "strategy_name",
    "strategy_type",
    "period",
    "universe",
    "metrics",
    "risk_summary",
    "evidence_refs",
    "execution_guard",
    "created_at",
)

DRAFT_LIST_FIELDS = (
    "draft_id",
    "symbol",
    "status",
    "target_weight_pct",
    "created_at",
    "valid_until",
)

MONITOR_EVENT_FIELDS = (
    "event_id",
    "symbol",
    "title",
    "severity",
    "trigger_rule",
    "created_at",
)

REPORT_SUMMARY_FIELDS = (
    "report_id",
    "report_type",
    "title",
    "conclusion",
    "source_type",
    "source_id",
    "template_id",
    "quality_status",
    "created_at",
    "markdown_path",
    "evidence_refs",
    "disclaimer",
)


def project_items(
    items: list[dict[str, Any]],
    fields: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """按 *fields* 投影、按 *limit* 截断（items 已是 newest-first）。"""
    rows = items[:limit] if limit and limit > 0 else list(items)
    if not fields:
        return [dict(row) for row in rows]
    keep = list(fields)
    return [{key: row[key] for key in keep if key in row} for row in rows]


def project_mapping(
    data: dict[str, Any],
    fields: Iterable[str] | None = None,
) -> dict[str, Any]:
    """按 *fields* 投影单个 dict；fields 为空则原样浅拷贝。"""
    if not fields:
        return dict(data)
    keep = list(fields)
    return {key: data[key] for key in keep if key in data}


def truncation_note(
    *,
    returned: int,
    total: int,
    tool: str,
    hint: str,
) -> dict[str, Any] | None:
    """截断说明。未截断时返回 None，避免给上下文添无用字段。"""
    if returned >= total:
        return None
    return {
        "returned": returned,
        "total": total,
        "hint": f"仅返回 {returned}/{total} 条。{hint}",
        "tool": tool,
    }
