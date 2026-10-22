"""P3-G：阈值残留检测 —— 判据必须下沉到工具，skill 里不得再硬编码具体阈值。

这是一个"软约束"变成可执行检查的例子：模型会背错阈值、会自由发挥，
而阈值只在工具代码里出现一次。这里断言的是"历史上已经下沉过"的那批阈值
不再回流进提示词（防止重构时被顺手写回去）。
"""

from __future__ import annotations

import re

import pytest

from backend.agent_runtime import skill_specs
from backend.agent_runtime.skill_specs import WORKBENCH_SKILLS, _read_skill_md

# 已经下沉到工具返回值的判据 —— skill 正文里出现这些字符串即视为回流。
# 每条都在 doc/SKILL_REFACTOR_PLAN.md §3.A 有对应记录。
DOWN_SHIFTED_THRESHOLDS = [
    "net_rate < 5%",
    "净买额占成交额 <",
    "float_ratio ≥ 5%",
    "float_ratio≥5%",
    "且 ≤ 30 天",
    "≤30 天",
    "broken.rate > 0.4",
    "获利比例高 + 现价贴近成本密集上沿",
    "套牢比例高 + 现价在 90% 成本下方",
    "集中度低（带宽大）",
    "阶段纪律（硬性",
]


@pytest.mark.parametrize("name", sorted(n for n, s in WORKBENCH_SKILLS.items() if s.is_subagent))
def test_no_down_shifted_threshold_in_skill_body(name: str) -> None:
    _, _, body = _read_skill_md(name)
    hits = [t for t in DOWN_SHIFTED_THRESHOLDS if t in body]
    assert not hits, (
        f"{name}: 判据已经下沉到工具，提示词里不该再出现阈值/规则文本 {hits}；"
        "若确需解释，引用工具返回的结构化字段（如 significance / risk_level / pressure）"
    )
