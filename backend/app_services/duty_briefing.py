"""定时值班任务的统一输出契约。

背景：五个定时任务此前各自写自由文本，落盘时用一个「取正文第一行当结论」的
启发式硬套进统一模板 —— 结果每份报告的"结论"其实是各自的标题行，章节数也从
4 到 6 不等，任务之间没法比较、前端也没法稳定渲染。

现在统一成固定四段：**结论 / 依据 / 动作 / 数据健康**。
- 结论：一句话（≤200 字），说清今天该做什么或不用动
- 依据：≤8 条，每条带数字或来源
- 动作：≤8 条，标的 + 做什么 + 触发条件
- 数据健康：≤8 条，只写会影响本场结论的缺口

模型通过 ``submit_duty_briefing`` 工具提交结构化内容（工具调用天然是类型化的，
比在正文里解析 JSON 稳）；调度器再从 ``tool_execution`` 账本里取最后一次提交，
喂给报告落盘。正文仍要写同样四段，供对话里直接阅读。
"""

from __future__ import annotations

from typing import Any, Iterable

DUTY_BRIEFING_TOOL = "submit_duty_briefing"

# 报告正文的固定章节（任务差异只体现在"依据/动作"里写什么）
SECTION_TITLES: tuple[str, ...] = ("结论", "依据", "动作", "数据健康")

MAX_CONCLUSION_CHARS = 200
MAX_ITEMS = 8
MAX_ITEM_CHARS = 200

_FIELD_ALIASES = {
    "conclusion": ("conclusion", "summary", "verdict", "结论"),
    "evidence": ("evidence", "reasons", "basis", "依据"),
    "actions": ("actions", "next_actions", "todos", "动作"),
    "data_health": ("data_health", "data_issues", "gaps", "数据健康"),
}


def _pick(data: dict[str, Any], field: str) -> Any:
    for key in _FIELD_ALIASES[field]:
        if key in data and data[key] not in (None, "", [], {}):
            return data[key]
    return None


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    # 去掉模型习惯性加的 markdown 标记，结论不该以「#」「-」「**」开头
    text = text.lstrip("#*-→· ").strip()
    text = text.replace("**", "").replace("`", "").strip()
    text = text.strip("\"'“”").strip()
    return text[:limit]


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, Iterable):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            raw = (
                item.get("text")
                or item.get("action")
                or item.get("item")
                or item.get("message")
                or ""
            )
        else:
            raw = item
        text = _clean_text(raw, MAX_ITEM_CHARS)
        if text:
            out.append(text)
        if len(out) >= MAX_ITEMS:
            break
    return out


def normalize_briefing(raw: Any) -> dict[str, Any]:
    """把模型提交的内容规整成固定结构；结论为空即视为无效提交。"""
    data = raw if isinstance(raw, dict) else {}
    conclusion = _clean_text(_pick(data, "conclusion"), MAX_CONCLUSION_CHARS)
    if not conclusion:
        raise ValueError(
            "conclusion 不能为空：用一句话说清今天的结论（该做什么 / 不用动）"
        )
    return {
        "conclusion": conclusion,
        "evidence": _clean_list(_pick(data, "evidence")),
        "actions": _clean_list(_pick(data, "actions")),
        "data_health": _clean_list(_pick(data, "data_health")),
    }


def extract_briefing(executions: Iterable[Any]) -> dict[str, Any] | None:
    """从 tool_execution 账本里取最后一次成功的 submit_duty_briefing。

    取最后一条（模型可能先交个草稿再改），失败的提交跳过。
    """
    found: dict[str, Any] | None = None
    for item in executions or []:
        if getattr(item, "tool", None) != DUTY_BRIEFING_TOOL:
            continue
        if str(getattr(item, "status", "") or "") != "succeeded":
            continue
        try:
            found = normalize_briefing(getattr(item, "arguments", None) or {})
        except ValueError:
            continue
    return found


def briefing_missing_note(briefing: dict[str, Any] | None) -> str | None:
    """给报告用的一句话体检：结构化提交缺了什么。"""
    if not briefing:
        return "本轮未提交结构化值班结论（模型未调用 submit_duty_briefing），以下为系统快照与原文。"
    missing = [name for name in ("依据", "动作", "数据健康") if not briefing.get(
        {"依据": "evidence", "动作": "actions", "数据健康": "data_health"}[name]
    )]
    if not missing:
        return None
    return f"结构化提交缺少：{'、'.join(missing)}。"
