"""判据下沉后的纯函数测试：阈值只在代码里出现一次，skill 只引用结论。"""

from __future__ import annotations

from backend.stock_domain.multi_providers import (
    _consecutive_days,
    _lhb_significance,
    _unlock_risk_level,
)


def test_lhb_significance_thresholds() -> None:
    assert _lhb_significance(0.02) == "noise"
    assert _lhb_significance(-0.02) == "noise"   # 净卖出同样是噪音
    assert _lhb_significance(0.06) == "notable"
    assert _lhb_significance(0.15) == "strong"
    assert _lhb_significance(None) == "noise"


def test_unlock_risk_level() -> None:
    assert _unlock_risk_level(0.12, 10) == "critical"
    assert _unlock_risk_level(0.06, 20) == "high"
    assert _unlock_risk_level(0.04, 60) == "medium"
    assert _unlock_risk_level(0.02, 400) == "low"
    assert _unlock_risk_level(None, 10) == "low"


def test_consecutive_days_handles_weekend_gap() -> None:
    # 周五/周一相差 3 天（跨周末）仍算连续
    items = [
        {"trade_date": "2026-10-23"},
        {"trade_date": "2026-10-22"},
        {"trade_date": "2026-10-19"},  # 周一，与前一条周五差 3 天
        {"trade_date": "2026-10-10"},
    ]
    assert _consecutive_days(items) == 3
    assert _consecutive_days([]) == 0
