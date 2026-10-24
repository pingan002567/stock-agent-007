"""定时任务:按日程自动发起 Copilot run(盘前简报/周度复盘等)。

DeerFlow harness 无 scheduler(Gateway 专属,见 doc/DEERFLOW_21_RESEARCH.md P1),
自建轻量 cron:任务存 repo config(单用户,量小),asyncio 循环沿用
monitor_service 模式,到点即 create_run 并 drain 流至收口。

日程表达(刻意不引 croniter,三种够用):
  ``daily@HH:MM``      每天,本机时区
  ``weekly@N@HH:MM``   每周,N=1..7(ISO,1=周一 7=周日)
  ``every@Nm``         每 N 分钟(N>=5)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from uuid import uuid4

from backend.schemas import AuthorityLevel, CopilotRequest, ReportGenerateRequest, now_iso

logger = logging.getLogger("scheduler")

CONFIG_KEY = "scheduled_tasks"
CHECK_INTERVAL_SECONDS = 30
RUN_TIMEOUT_SECONDS = 900

_DATA_DISCIPLINE = (
    "取数：优先本地缓存；遇 degraded / stale / 缺字段先 list_data_sources 再换可用 provider"
    "（行业优先同花顺）；仍失败写「未获取+原因」，禁止编造。不索要完整持仓明细、不回显密钥、不做真实下单。"
)

_DATA_HEALTH_RULE = (
    "数据健康：只写会影响本场结论的缺口，每项一行「缺什么 → 哪条判断作废」；"
    "不写熔断次数、provider 名、内部字段名；与本场结论无关的标的不写；"
    "官方日K在收盘前落后一交易日不算故障，收盘后仍缺当日开高低量才写。"
)

# 统一四段输出契约：所有定时任务共用，任务差异只体现在「依据/动作」里写什么。
DUTY_OUTPUT_CONTRACT = (
    "【输出】固定四段，只写这四段，不要另加章节或改变顺序：\n"
    "1. 结论：一句话（≤40 字），说清今天该做什么，或明确「今天不用动」。\n"
    "2. 依据：≤5 条，每条一句话且带数字或来源。\n"
    "3. 动作：≤5 条，每条写「标的 + 做什么 + 触发条件/价位」；没有动作就写「无需操作」。\n"
    "4. 数据健康：≤5 条，只写会影响本场结论的缺口，每项一行「缺什么 → 哪条判断作废」；"
    "不写熔断次数、provider 名、内部字段名；与本场结论无关的标的不写；"
    "官方日K在收盘前落后一交易日不算故障，收盘后仍缺当日开高低量才写。\n"
    "收口前必须调用 submit_duty_briefing，把同样的结论/依据/动作/数据健康提交成结构化字段。\n"
    "正文与工具提交必须一致；表格合计 ≤8 行。"
)

DUTY_PREAMBLE = (
    "你是值班研究员。禁止自动交易。\n"
    f"{_DATA_DISCIPLINE}\n"
    "必须调用：get_portfolio_snapshot、get_monitor_events、summarize_review_inbox。\n"
    "持仓+自选合计超过 15 只时，只深拉权重最高与今日异动 Top 8，其余一行涨跌，禁止逐只深研。\n"
    "A 股讨论抛压/套牢时必须 get_market_structure；港美股禁止写获利/套牢比例。\n"
    f"{DUTY_OUTPUT_CONTRACT}\n"
    "不要调用 generate_report，系统会在运行结束后自动落盘值班简报。"
)

DISCOVERY_PREAMBLE = (
    "你是盘前机会发现员。禁止自动交易。\n"
    "范围：全市场，**不得只看自选与持仓**（自选/持仓仅作重叠对照，不可当作唯一宇宙）。\n"
    f"{_DATA_DISCIPLINE}\n"
    "必须先拉市场面：invoke_data_capability 或快捷工具获取 market_review、sectors、"
    "industry_boards（必要时 Mode A 换源）；再按**上方已注入**的风险画像筛选候选。\n"
    f"{DUTY_OUTPUT_CONTRACT}\n"
    "不要调用 generate_report，系统会在运行结束后自动落盘机会发现报告。"
)

# 仍等于这些旧默认文案的已落库任务，会在 list_tasks 时升级到 DEFAULT_TASKS 新 prompt。
# 四段契约改造前的旧文案都带「【输出】≤N 字」且不含「固定四段」；
# 用它做升级判定，比维护精确文案集合更省事，也不会误伤已迁移的任务。
_LEGACY_PROMPT_MARKERS = ("【输出】≤600 字", "【输出】≤900 字")
_NEW_PROMPT_MARKER = "固定四段"

_LEGACY_DEFAULT_PROMPTS: dict[str, frozenset[str]] = {
    "sched_premarket_discovery": frozenset(
        {
            "扫描全市场（大盘、板块轮动、行业），找出与用户风险画像匹配的今日机会，"
            "不局限于自选与持仓；列出 3～5 个值得跟进的标的及回避方向。",
            (
                "【任务】盘前机会发现（A股交易日 08:20）。范围＝全市场，不限于自选/持仓。\n"
                "【取数】按已注入的风险画像筛选；大盘/板块走市场复盘与行业能力（行业优先同花顺）；"
                "逐个候选排查与现有持仓是否重叠；失败须标注「精度有限」。\n"
                "【输出】≤600 字\n"
                "1. 市场环境：1 段，指数与板块强弱（缺失则说明）。\n"
                "2. 机会清单：3–5 个；每条含代码/名称、行业、触发逻辑、参考入场区间、止损位、"
                "仓位上限（不超风险策略单票上限）、与持仓是否重叠。\n"
                "3. 回避清单：2–3 个方向及理由。\n"
                "4. 数据健康：降级/缺失项。\n"
                "【约束】只写市场环境+全市场机会，不写自选/持仓隔夜简报（留给 08:30）。"
            ),
            (
                "【任务】盘前机会发现（A股交易日 08:20）。范围＝全市场，不限于自选/持仓。\n"
                "【取数】按已注入的风险画像筛选；大盘/板块走市场复盘与行业能力（行业优先同花顺）；"
                "逐个候选排查与现有持仓是否重叠；失败须标注「精度有限」。\n"
                "【输出】≤600 字\n"
                "1. 市场环境：1 段，指数与板块强弱（缺失则说明）。\n"
                "2. 机会清单：3–5 个；每条含代码/名称、行业、触发逻辑、参考入场区间、止损位、"
                "仓位上限（不超风险策略单票上限）、与持仓是否重叠。\n"
                "3. 回避清单：2–3 个方向及理由。\n"
                f"4. {_DATA_HEALTH_RULE}\n"
                "【约束】只写市场环境+全市场机会，不写自选/持仓隔夜简报（留给 08:30）。"
            ),
        }
    ),
    "sched_premarket": frozenset(
        {
            "汇总自选与持仓相关的隔夜要闻与情报，列出今天需要重点关注的标的和风险点。",
            (
                "【任务】今日盘前简报（A股交易日 08:30，集合竞价前）。只做自选/持仓+隔夜要闻，"
                "不重复 08:20 机会发现已述的全市场机会清单。\n"
                "【取数】自选/持仓/盯盘优先本地缓存；隔夜要闻与情报窗口＝上一交易日收盘后至今。\n"
                "【输出】≤600 字\n"
                "1. 隔夜要闻：≤5 条；每条含来源与对自选/持仓影响（利好/利空/中性）。\n"
                "2. 今日重点标的：≤5 个；关注理由与关键价位；此刻无开盘价，不得编造。\n"
                "3. 风险与日历：今日解禁/财报/停复牌、公司或监管公告、昨日已触发的盯盘规则。\n"
                "4. 数据健康：本次降级/缺失字段。\n"
                "【约束】只写例外与动作，不复述行情流水账。"
            ),
        }
    ),
    "sched_close": frozenset(
        {
            "复盘今日持仓与自选涨跌、盯盘未处理事件、数据源是否降级、风控距硬限。"
            "列出例外，不要编造未拉到的数字。",
            (
                "【任务】收盘体检（A股交易日 15:15）。\n"
                "【取数】持仓/自选/盯盘优先本地缓存；结论依赖当日现价时，同一标的最多 refresh 一次。\n"
                "【输出】≤600 字\n"
                "1. 组合表现：整体涨跌；正/负贡献最大各 ≤3 只（含权重与当日涨跌）。\n"
                "2. 盯盘事件：未处理事件按严重度排序 + 建议动作。\n"
                "3. 距硬限：逐项「当前值/阈值/剩余空间」；阈值以风险策略为准，无则用 5 个百分点；"
                "剩余空间 <5 个百分点即预警。\n"
                "4. 例外清单：明确今日「无需处理」与「必须处理」。\n"
                "5. 数据健康：降级/缺失字段与原因。"
            ),
        }
    ),
    "sched_weekly_review": frozenset(
        {
            "本周持仓表现、盯盘事件回顾、风险状况变化与下周关注点。",
            (
                "【任务】本周周度复盘（周日 17:00）。\n"
                "【取数】持仓/自选走本地缓存；归因用决策日志与结果汇总；板块/行业走行业能力。\n"
                "【输出】≤900 字\n"
                "1. 周度表现：组合收益 vs 基准（基准不可得则说明），最大回撤。\n"
                "2. 归因：前 3 大正/负贡献标的及原因（事件/情绪/基本面）。\n"
                "3. 决策复盘：本周建议与实际走势是否一致，偏差在哪。\n"
                "4. 风险变化：集中度、单票超限、行业集中、距硬限的环比变化。\n"
                "5. 下周关注：3–5 条，含催化剂时点与回避方向。\n"
                "6. 数据健康：降级/缺失项。\n"
                "【约束】只写结论与动作，不复述每日简报。"
            ),
        }
    ),
}

DEFAULT_TASKS: list[dict[str, Any]] = [
    {
        "task_id": "sched_premarket_discovery",
        "name": "盘前机会发现",
        "prompt": "【任务】盘前机会发现（每日 08:20，含周末与节假日）。范围＝全市场，不限于自选/持仓。休市日照常输出，机会对应下一开市日，并注明今日休市。\n【取数】按已注入的风险画像筛选；大盘/板块走市场复盘与行业能力（行业优先同花顺）；逐个候选排查与现有持仓是否重叠；失败须标注「精度有限」。\n【输出】固定四段（见 preamble 的四段契约）：\n1. 结论：今天做不做、做哪个方向，一句话。\n2. 依据：≤5 条，覆盖市场环境（指数与板块强弱）与 3–5 个机会的核心逻辑（代码/名称、行业、触发逻辑、与持仓是否重叠）。\n3. 动作：≤5 条，每条含参考入场区间、止损位、仓位上限（不超风险策略单票上限）；另给 2–3 个回避方向。\n4. 数据健康：降级/缺失项及被作废的判断。\n【约束】只写市场环境+全市场机会，不写自选/持仓隔夜简报（留给 08:30）。",
        "page": "chat",
        "authority_level": "A3",
        "schedule": "daily@08:20",
        "enabled": True,
    },
    {
        "task_id": "sched_premarket",
        "name": "盘前简报",
        "prompt": "【任务】今日盘前简报（A股交易日 08:30，集合竞价前）。只做自选/持仓+隔夜要闻，不重复 08:20 机会发现已述的全市场机会清单。\n【取数】自选/持仓/盯盘优先本地缓存；隔夜要闻与情报窗口＝上一交易日收盘后至今。\n【输出】固定四段（见 preamble 的四段契约）：\n1. 结论：今天该做什么或不用动，一句话。\n2. 依据：≤5 条，覆盖隔夜要闻（含来源与利好/利空/中性）、今日重点标的与关键价位（此刻无开盘价，不得编造）。\n3. 动作：≤5 条，标的+做什么+触发条件；无动作写「无需操作」。\n4. 数据健康：只写会影响本场结论的缺口。\n【约束】只写例外与动作，不复述行情流水账。",
        "page": "chat",
        "authority_level": "A3",
        "schedule": "daily@08:30",
        "enabled": True,
        "calendar": "CN",
    },
    {
        "task_id": "sched_intraday",
        "name": "盘中报告",
        "prompt": "【任务】盘中报告（A股交易日 11:45，上午收盘后／下午开盘前）。目标＝上午盘总结 + 下午开盘操作预案；不重复盘前简报的隔夜要闻流水账，也不替代 15:15 收盘体检。\n【取数】持仓/自选/盯盘优先本地缓存；结论依赖现价时，同一标的最多 refresh 一次；板块强弱走市场复盘/行业能力。\n【输出】固定四段（见 preamble 的四段契约）：\n1. 结论：下午做不做、做哪个方向，一句话。\n2. 依据：≤5 条，覆盖上午指数与主线强弱、持仓/自选正负贡献各 ≤3 只（含当日涨跌）、已触发盯盘与异动。\n3. 动作：≤5 条可执行动作（继续持有/加仓/减仓/观望），每条含标的、理由、参考价位或触发条件、仓位上限；另给 1–3 条回避方向。\n4. 数据健康：只写会影响本场结论的缺口。\n【约束】只写结论与动作；禁止真实下单。",
        "page": "chat",
        "authority_level": "A3",
        "schedule": "daily@11:45",
        "enabled": True,
        "calendar": "CN",
    },
    {
        "task_id": "sched_close",
        "name": "收盘体检",
        "prompt": "【任务】收盘体检（A股交易日 15:15）。\n【取数】持仓/自选/盯盘优先本地缓存；结论依赖当日现价时，同一标的最多 refresh 一次。\n【输出】固定四段（见 preamble 的四段契约）：\n1. 结论：今天要不要动、明天要准备什么，一句话。\n2. 依据：≤5 条，覆盖组合整体涨跌与正/负贡献最大各 ≤3 只（含权重与当日涨跌）、未处理盯盘事件按严重度排序、距硬限「当前值/阈值/剩余空间」（阈值以风险策略为准，无则用 5 个百分点，剩余空间 <5 个百分点即预警）。\n3. 动作：≤5 条，明确今日「必须处理」与明日「需要准备」；无需处理写「无需操作」。\n4. 数据健康：只写会影响本场结论的缺口。\n【约束】只写结论与动作，不复述行情流水账。",
        "page": "chat",
        "authority_level": "A3",
        "schedule": "daily@15:15",
        "enabled": True,
        "calendar": "CN",
    },
    {
        "task_id": "sched_weekly_review",
        "name": "周度复盘",
        "prompt": "【任务】本周周度复盘（周日 17:00）。\n【取数】持仓/自选走本地缓存；归因用决策日志与结果汇总；板块/行业走行业能力。\n【输出】固定四段（见 preamble 的四段契约）：\n1. 结论：本周做对/做错了什么、下周怎么打，一句话。\n2. 依据：≤5 条，覆盖组合收益 vs 基准（不可得则说明）与最大回撤、前 3 大正/负贡献标的及原因、决策建议与实际走势是否一致及偏差、风险变化（集中度/单票超限/行业集中/距硬限环比）。\n3. 动作：≤5 条，下周关注方向与回避方向，含催化剂时点。\n4. 数据健康：只写会影响本场结论的缺口。\n【约束】只写结论与动作，不复述每日简报。",
        "page": "chat",
        "authority_level": "A3",
        "schedule": "weekly@7@17:00",
        "enabled": False,
    },
]


def is_discovery_task(task: dict[str, Any]) -> bool:
    task_id = str(task.get("task_id") or "")
    name = str(task.get("name") or "")
    return task_id == "sched_premarket_discovery" or "机会发现" in name


def infer_ops_session(task: dict[str, Any]) -> str:
    task_id = str(task.get("task_id") or "")
    name = str(task.get("name") or "")
    if is_discovery_task(task):
        return "discovery"
    if task_id == "sched_weekly_review" or "周" in name:
        return "weekly"
    if (
        task_id == "sched_intraday"
        or "盘中" in name
        or "午间" in name
        or task_id.endswith("_intraday")
        or "intraday" in task_id
    ):
        return "intraday"
    if "收盘" in name or task_id.endswith("_close") or "close" in task_id:
        return "close"
    return "premarket"


def uses_cn_session_calendar(task: dict[str, Any]) -> bool:
    # 机会发现看的是下一开市日，周末和节假日也要出清单。
    if is_discovery_task(task):
        return False
    calendar = str(task.get("calendar") or "").upper()
    if calendar == "CN":
        return True
    if calendar:
        return False
    return str(task.get("task_id") or "") in {
        "sched_premarket",
        "sched_intraday",
        "sched_close",
    }


def next_duty_run(task: dict[str, Any], after: datetime) -> Optional[datetime]:
    schedule = str(task.get("schedule") or "")
    nxt = compute_next_run(schedule, after)
    if nxt is None or not uses_cn_session_calendar(task):
        return nxt
    from backend.stock_domain.trading_calendar import is_trading_day

    for _ in range(400):
        if is_trading_day("CN", nxt.date()):
            return nxt
        nxt = compute_next_run(schedule, nxt)
        if nxt is None:
            return None
    return nxt


def skip_reason_for(task: dict[str, Any], now: datetime | None = None) -> str | None:
    if not uses_cn_session_calendar(task):
        return None
    from backend.stock_domain.trading_calendar import is_trading_day

    day = (now or datetime.now()).date()
    if not is_trading_day("CN", day):
        return "休市"
    return None


def cap_duty_authority(raw: str | None) -> AuthorityLevel:
    """定时值班固定 A3：要读持仓/待办，且不超过自动交易门槛。"""
    _ = raw
    return AuthorityLevel.A3


def compute_next_run(schedule: str, after: datetime) -> Optional[datetime]:
    """日程 → after 之后最近一次触发时刻;非法日程返回 None。"""
    try:
        kind, _, rest = schedule.partition("@")
        if kind == "daily":
            hh, mm = (int(x) for x in rest.split(":"))
            candidate = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if candidate <= after:
                candidate += timedelta(days=1)
            return candidate
        if kind == "weekly":
            day_s, _, time_s = rest.partition("@")
            day = int(day_s)  # ISO 1..7
            hh, mm = (int(x) for x in time_s.split(":"))
            if not 1 <= day <= 7:
                return None
            candidate = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
            delta_days = (day - candidate.isoweekday()) % 7
            candidate += timedelta(days=delta_days)
            if candidate <= after:
                candidate += timedelta(days=7)
            return candidate
        if kind == "every":
            minutes = int(rest.rstrip("m"))
            if minutes < 5:
                return None
            return after + timedelta(minutes=minutes)
    except (ValueError, AttributeError):
        return None
    return None


class SchedulerService:
    def __init__(self, *, repo, copilot_service, audit_service, report_service=None, alert_sink: Callable[[str, str], None] | None = None) -> None:
        self.repo = repo
        self.copilot_service = copilot_service
        self.audit_service = audit_service
        self.report_service = report_service
        self.alert_sink = alert_sink
        self._loop_task: asyncio.Task | None = None

    # ── 存取(repo config 单键,属主唯一) ──

    def list_tasks(self) -> list[dict[str, Any]]:
        data = self.repo.get_config(CONFIG_KEY, {"items": []})
        items = list(data.get("items") or [])
        if not items:
            items = [dict(item) for item in DEFAULT_TASKS]
            self._save(items)
        else:
            known = {item.get("task_id") for item in items}
            dirty = False
            for seed in DEFAULT_TASKS:
                if seed["task_id"] not in known and seed["task_id"] in {
                    "sched_close",
                    "sched_premarket_discovery",
                    "sched_intraday",
                }:
                    items.append(dict(seed))
                    dirty = True
            seed_by_id = {seed["task_id"]: seed for seed in DEFAULT_TASKS}
            for item in items:
                tid = str(item.get("task_id") or "")
                seed = seed_by_id.get(tid)
                if seed is None:
                    continue
                legacy = _LEGACY_DEFAULT_PROMPTS.get(tid) or frozenset()
                prompt_text = str(item.get("prompt") or "")
                is_legacy = prompt_text in legacy or (
                    not prompt_text.strip()
                    or (
                        any(m in prompt_text for m in _LEGACY_PROMPT_MARKERS)
                        and _NEW_PROMPT_MARKER not in prompt_text
                    )
                )
                if is_legacy and seed.get("prompt"):
                    item["prompt"] = seed["prompt"]
                    dirty = True
                if is_discovery_task(item) and item.get("calendar"):
                    item.pop("calendar", None)
                    dirty = True
            if dirty:
                self._save(items)
        now = datetime.now()
        for item in items:
            nxt = next_duty_run(item, now)
            item["next_run_at"] = nxt.isoformat(timespec="minutes") if (nxt and item.get("enabled")) else None
            item["skip_reason"] = skip_reason_for(item, now) if item.get("enabled") else None
        return items

    def _save(self, items: list[dict[str, Any]]) -> None:
        persistable: list[dict[str, Any]] = []
        for item in items:
            row = dict(item)
            row.pop("next_run_at", None)
            row.pop("skip_reason", None)
            persistable.append(row)
        self.repo.set_config(CONFIG_KEY, {"items": persistable})

    def upsert_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = self.list_tasks()
        task_id = str(payload.get("task_id") or "").strip() or f"sched_{uuid4().hex[:8]}"
        existing = next((t for t in items if t["task_id"] == task_id), None)

        if "schedule" in payload and payload.get("schedule") is not None:
            schedule = str(payload.get("schedule") or "")
        elif existing:
            schedule = str(existing.get("schedule") or "")
        else:
            schedule = str(payload.get("schedule") or "")
        if compute_next_run(schedule, datetime.now()) is None:
            raise ValueError(f"invalid schedule: {schedule!r} (daily@HH:MM / weekly@N@HH:MM / every@Nm)")

        def _merge(key: str, default: Any = None) -> Any:
            if key in payload and payload[key] is not None:
                return payload[key]
            if existing is not None and key in existing:
                return existing[key]
            return default

        if "enabled" in payload and payload.get("enabled") is not None:
            enabled = bool(payload["enabled"])
        elif existing is not None:
            enabled = bool(existing.get("enabled", True))
        else:
            enabled = True

        record = {
            "task_id": task_id,
            "name": str(_merge("name", "未命名任务")),
            "prompt": str(_merge("prompt", "")),
            "page": str(_merge("page", "chat")),
            "authority_level": str(_merge("authority_level", "A2")),
            "schedule": schedule,
            "enabled": enabled,
            "last_run_at": (existing or {}).get("last_run_at"),
            "last_status": (existing or {}).get("last_status"),
            "last_run_id": (existing or {}).get("last_run_id"),
            "last_error": (existing or {}).get("last_error"),
            "last_report_id": (existing or {}).get("last_report_id"),
            "calendar": payload.get("calendar") if payload.get("calendar") is not None else (existing or {}).get("calendar"),
        }
        if existing:
            items[items.index(existing)] = record
        else:
            items.append(record)
        self._save(items)
        self.audit_service.record("scheduled task upserted", f"{task_id} {schedule}")
        return record

    def set_enabled(self, task_id: str, enabled: bool) -> dict[str, Any]:
        items = self.list_tasks()
        task = next((t for t in items if t["task_id"] == task_id), None)
        if task is None:
            raise KeyError(task_id)
        task["enabled"] = bool(enabled)
        self._save(items)
        return task

    def delete_task(self, task_id: str) -> None:
        items = [t for t in self.list_tasks() if t["task_id"] != task_id]
        self._save(items)

    # ── 执行 ──

    async def run_task_now(self, task_id: str) -> dict[str, Any]:
        items = self.list_tasks()
        task = next((t for t in items if t["task_id"] == task_id), None)
        if task is None:
            raise KeyError(task_id)
        return await self._execute(task, honor_calendar=False)

    async def _execute(self, task: dict[str, Any], *, honor_calendar: bool = False) -> dict[str, Any]:
        if honor_calendar:
            reason = skip_reason_for(task)
            if reason:
                outcome = {
                    "run_id": None,
                    "status": "skipped",
                    "error": f"已跳过：{reason}",
                    "report_id": None,
                }
                self._write_run_trace(task, outcome)
                return outcome
        stamp = datetime.now().strftime("%m-%d %H:%M")
        discovery = is_discovery_task(task)
        preamble = DISCOVERY_PREAMBLE if discovery else DUTY_PREAMBLE
        profile_block = ""
        if discovery:
            from backend.config.investor_profile import (
                format_profile_for_prompt,
                load_investor_profile,
            )

            profile_block = format_profile_for_prompt(load_investor_profile(self.repo)) + "\n\n"
        request = CopilotRequest(
            message=(
                f"[定时任务·{task['name']} {stamp}]\n{preamble}\n\n"
                f"{profile_block}"
                f"用户任务：{task.get('prompt') or ''}"
            ),
            page=task.get("page") or "chat",
            authority_level=cap_duty_authority(str(task.get("authority_level") or "A2")),
        )
        outcome: dict[str, Any] = {
            "run_id": None,
            "status": "failed",
            "error": None,
            "report_id": None,
            "session_id": None,
        }
        try:
            run = self.copilot_service.create_run(request)
            outcome["run_id"] = run.run_id
            outcome["session_id"] = getattr(run, "session_id", None)

            async def _drain() -> None:
                async for event in self.copilot_service.stream_run(run.run_id, run.task_id):
                    if event.type == "error":
                        outcome["error"] = str(event.payload.get("error") or "run error")

            await asyncio.wait_for(_drain(), timeout=RUN_TIMEOUT_SECONDS)
            outcome["status"] = "completed" if not outcome["error"] else "failed"
        except asyncio.TimeoutError:
            outcome["error"] = f"timeout after {RUN_TIMEOUT_SECONDS}s"
        except Exception as exc:  # 单任务失败不拖垮循环
            outcome["error"] = str(exc)[:200]
        self._persist_ops_briefing(task, outcome)
        self._write_run_trace(task, outcome)
        self._notify_duty_outcome(task, outcome)
        return outcome

    def _write_run_trace(self, task: dict[str, Any], outcome: dict[str, Any]) -> None:
        items = self.list_tasks()
        task_rec = next((t for t in items if t["task_id"] == task["task_id"]), None)
        if task_rec is not None:
            task_rec["last_run_at"] = now_iso()
            task_rec["last_status"] = outcome["status"]
            task_rec["last_run_id"] = outcome["run_id"]
            task_rec["last_error"] = outcome["error"]
            task_rec["last_report_id"] = outcome.get("report_id")
            self._save(items)
        self.audit_service.record(
            "scheduled task executed",
            f"{task['task_id']} -> {outcome['status']}"
            + (f" ({outcome['error']})" if outcome["error"] else ""),
        )

    def _notify_duty_outcome(self, task: dict[str, Any], outcome: dict[str, Any]) -> None:
        if self.alert_sink is None:
            return
        status = str(outcome.get("status") or "")
        if status == "skipped":
            return

        from backend.config.notification_prefs import load_notification_prefs

        prefs = load_notification_prefs(self.repo)
        name = str(task.get("name") or task.get("task_id") or "值班任务")
        task_id = str(task.get("task_id") or "")
        session_id = outcome.get("session_id")
        report_id = outcome.get("report_id")
        deep = {
            "kind": "scheduled_task",
            "task_id": task_id or None,
            "session_id": str(session_id) if session_id else None,
            "report_id": str(report_id) if report_id else None,
        }

        if status == "failed":
            detail = str(outcome.get("error") or "定时任务未收口")
            title = f"值班失败 · {name}"
            body = detail[:400]
        elif status == "completed":
            if not prefs.get("duty_completion_push", True):
                return
            narrative = self._copilot_narrative(outcome.get("run_id")).strip()
            title = f"值班完成 · {name}"
            body = (narrative[:280] if narrative else "任务已完成，可在对话或研究报告中查看。")
        else:
            return

        try:
            self.alert_sink(title, body, **deep)
        except Exception:
            logger.exception("duty alert push failed")

    def _copilot_narrative(self, run_id: str | None) -> str:
        if not run_id:
            return ""
        try:
            messages = self.repo.list_copilot_run_messages(run_id)
        except Exception:
            return ""
        finals = [item.text.strip() for item in messages if item.kind == "final_answer" and item.text.strip()]
        return finals[-1] if finals else ""

    def _read_duty_briefing(self, run_id: str | None) -> dict[str, Any] | None:
        """从 tool_execution 账本取本轮 submit_duty_briefing 的结构化结果。"""
        if not run_id:
            return None
        try:
            from backend.app_services.duty_briefing import extract_briefing

            executions = self.repo.list_tool_executions(run_id=run_id, limit=400)
        except Exception:
            logger.exception("read duty briefing failed for %s", run_id)
            return None
        return extract_briefing(executions)

    def _persist_ops_briefing(self, task: dict[str, Any], outcome: dict[str, Any]) -> None:
        if self.report_service is None:
            return
        session = infer_ops_session(task)
        title_map = {
            "premarket": "盘前值班简报",
            "discovery": "盘前机会发现",
            "intraday": "盘中值班报告",
            "close": "收盘值班简报",
            "weekly": "周度值班复盘",
        }
        try:
            report = self.report_service.generate(
                ReportGenerateRequest(
                    report_type="ops_briefing",
                    source_type="scheduled_task",
                    source_id=str(task["task_id"]),
                    title=f"{title_map.get(session, '值班简报')} · {task.get('name') or task['task_id']}",
                    options={
                        "session": session,
                        "run_id": outcome.get("run_id"),
                        "run_status": outcome.get("status"),
                        "run_error": outcome.get("error"),
                        "narrative": self._copilot_narrative(outcome.get("run_id")),
                        "task_name": task.get("name"),
                        # 四段契约的结构化提交（缺省时报告层回退到原文解析）
                        "briefing": self._read_duty_briefing(outcome.get("run_id")),
                    },
                )
            )
            outcome["report_id"] = report.report_id
        except Exception as exc:
            logger.exception("ops_briefing persist failed for %s", task.get("task_id"))
            outcome["report_error"] = str(exc)[:200]

    # ── 循环(monitor_service 同款生命周期) ──

    async def startup(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._run_loop(), name="workbench-scheduler-loop")

    async def shutdown(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def _run_loop(self) -> None:
        # due 判定用「上次检查时刻 < 触发点 <= 现在」窗口,重启错过的触发不补跑
        last_check = datetime.now()
        while True:
            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                now = datetime.now()
                for task in self.list_tasks():
                    if not task.get("enabled"):
                        continue
                    nxt = next_duty_run(task, last_check)
                    if nxt and last_check < nxt <= now:
                        logger.info("scheduled task due: %s", task["task_id"])
                        await self._execute(task, honor_calendar=True)
                last_check = now
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler loop iteration failed")
                last_check = datetime.now()
