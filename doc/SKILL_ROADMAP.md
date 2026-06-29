# Skill 演进路线图

> 依据：业务特性（个人投研台、research-only A1–A5、多市场 A/HK/US）+ 专业框架（FinRobot/TradingAgents/AlphaAgents/CFI 11 维）+ 数据可行性（现有 provider 仅 quote/history/intel）。
> 分层：**A 类**=现有数据就能做；**B 类**=需先接数据源；**C 类**=结构性。

## 现状（7 个 skill）
| skill | 升级状态 |
|---|---|
| stock-researcher | ✅ 已升级（论点+三情景+引用纪律+反方） |
| report-writer | ✅ 已升级（引用纪律+论点结构+质量门禁） |
| risk-officer / rebalance-planner / stock-monitor / strategy-analyst | ⏳ P0 待升级 |
| worldcup-predictor | 玩具，禁用，不动 |

## P0 — A 类（现有数据，最高性价比）
1. **引用纪律全推**：逐条溯源 `[来源:tool·时间]` + 禁编造 + 降级降置信度 → 推广到 risk/rebalance/monitor/strategy。
2. **risk-officer**：＋仓位建议区间（引用阈值）＋距硬限预警＋轻量压力测试（板块/单票冲击）；保持不出调仓。
3. **rebalance-planner**：＋多方案（保守/中性/激进）＋调仓后影响预估（权重/集中度变化）＋每项引用触发的 risk rule。
4. **stock-monitor**：＋优先级 Top3（severity×标的聚合）＋异动↔intel 根因关联＋跨 skill 跳转建议。
5. **strategy-analyst**：＋稳健性（参数敏感性/样本内外）＋基准对比（买入持有）＋过拟合/小样本警示。

## P1 — C 类（结构性，提质）
6. **RTO 输出 schema 下发 envelope**：把各 skill 的 output_format 注入 prompt 信封，稳定结构化产出（多数 turn 不注入 SKILL.md 正文，见 prompt 分析）。
7. ✅ **单一真相源（已落地）**：新增 `skill_specs.py`——SKILL.md frontmatter(description+allowed-tools) 为单一来源，运行时字段(label/system_prompt/params/intents)集中在一张 `WORKBENCH_SKILLS` 表；`subagent_configs`/`skill_registry`/`SKILL_LABELS`/`INTENT_SKILLS` 全部**生成**，删除 `subagent_configs.py`。加 skill = 写 SKILL.md + 一行表。
8. **多代理对抗**：researcher(看多) ↔ risk-officer(看空) → synthesis（TradingAgents 范式）；扩大 subagent 启用范围（现仅 strategy_backtest/rebalance_plan）。
9. **intent↔skill 映射对齐**：`INTENT_SKILLS`(已由 skill_specs 生成) / `_build_skill_trace` / `INTENT_TO_CONTEXT_SECTIONS` 三处校验一致（#7 已统一前者）。

## P2 — B 类（需数据源）
10. ✅ **valuation-analyst（已落地）**——发现财务数据其实已在 provider 层（`get_financial`/`StockFinancial`），只是没暴露成 agent 工具。已暴露 `get_stock_financial` 工具 + 新增 valuation-analyst skill（盈利/偿债/倍数/多期趋势，research-only），并让 researcher 也用上财报。
    - 受限于现有财报字段（营收/净利/资产/负债），**暂不做完整 DCF**（需现金流/股本数据）——skill 内已显式声明。
11. **结构化公告/财报日历** → 新增 **catalyst-tracker**（带时点催化剂）/ **management-credibility**（guidance vs 实际）。待接源。
12. **（美股专有，最低优先级）** 期权流 / 内部人 Form4。

## 贯穿约束
research-only（不出买卖/精确目标价；risk 给仓位区间而非指令）· 多市场口径分支 · token/隐私走摘要 · 每个建议挂 `evidence_refs`。

## 落地记录
- 2026-06：stock-researcher / report-writer 完成 A 类升级（commit `ed37e9c`）。
- 2026-06：P0 其余 4 个 skill（risk/rebalance/monitor/strategy）升级（commit `40638d5`）。
- 2026-06：P2 valuation-analyst 落地（暴露 get_stock_financial 工具 + 新 skill + researcher 用上财报）。
- 2026-06：P1 #7 单一真相源落地（skill_specs.py 生成 subagent/registry，删 subagent_configs.py）。
