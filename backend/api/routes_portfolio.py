from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.deps import get_services
from backend.bootstrap import AppServices

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/copilot/followups")
def copilot_followups(services: AppServices = Depends(get_services)):
    """生成 AI 追问建议，基于当前持仓、监控和风险策略上下文。"""
    holdings = services.repo.list_holdings()
    suggestions: list[dict[str, str]] = []

    holding_symbols = [h.symbol for h in holdings]

    if len(holdings) > 0:
        top = holdings[0]
        suggestions.append(
            {
                "label": f"分析 {top.symbol} 风险",
                "prompt": f"分析 {top.symbol} 的持仓风险",
            }
        )
        if len(holdings) > 1:
            suggestions.append(
                {
                    "label": "查看持仓概况",
                    "prompt": "查看我的整体持仓概况",
                }
            )
        suggestions.append(
            {
                "label": "生成调仓草案",
                "prompt": "生成调仓方案",
            }
        )
    else:
        suggestions.append(
            {
                "label": "分析 AAPL",
                "prompt": "分析 AAPL",
            }
        )

    # 检查是否有监控告警
    try:
        events = services.monitor_service.list_events(limit=1)
        if events:
            suggestions.append(
                {
                    "label": "查看监控告警",
                    "prompt": "查看最新的监控告警",
                }
            )
    except Exception:
        pass

    # 检查是否有待办
    try:
        inbox = services.review_inbox_service.list_items()
        pending = [i for i in inbox if i.status == "pending"]
        if pending:
            suggestions.append(
                {
                    "label": f"待办 ({len(pending)})",
                    "prompt": "查看待办事项",
                }
            )
    except Exception:
        pass

    suggestions.append(
        {
            "label": "今日市场动态",
            "prompt": "今天的市场热点是什么",
        }
    )

    return {"items": suggestions}
