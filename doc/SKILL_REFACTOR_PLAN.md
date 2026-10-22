# Skill 体系重构方案：把「判据」从提示词下沉到代码

> 状态：方案（本轮已落地 A1 样例，其余待实施）
> 动机：大模型能力足够强，skill 不该教它「怎么想」，只该告诉它「数据是什么、边界在哪、必须答哪几块」。

## 0. 原则（一句话）

> **凡是「模型不知道自己不知道」的，写下来（并尽量下沉到代码）；凡是「模型知道但可能选不同做法」的，放开。**

区分两种"自由"：

| 自由 | 该不该给 | 原因 |
|---|---|---|
| 自由**推理**（怎么归因、怎么给概率、怎么讲风险） | ✅ 给 | 这是模型强项 |
| 自由**造数**（补一个获利比例、编一个"连涨 6 日"） | ❌ 堵死 | 用户拿去下单，不可审计 = 不可用 |

**提示词是建议，代码是保证。** 每一条禁令都是一次"模型可能不听话"的赌注；
每一条代码约束都是确定性。

## 1. 现状诊断

```
11 个 skill + SOUL 共 571 行
stock-deep-dive 116 行，其中 27 行含「禁止/不得/不要/严禁」（23% 是禁令）
```

三类问题：

1. **判据写在提示词里** —— 阈值（5%/10%/30 天）散落在 skill 里，模型要背、会背错、会自由发挥。
2. **过 claim 补丁** —— 名字起错导致的"不要委派"式负向声明（改名后部分可删）。
3. **判断被压死** —— 输出框架细到"每块怎么写"，所有回答长一个样。

## 2. 三层职责（各归各）

| 层 | 该给什么 | 谁负责 |
|---|---|---|
| **事实层**（数据语义） | 单位、交易日、缓存新鲜度、`degraded/missing` 含义、字段什么时候不可信 | **代码**（工具返回值里的结构化字段） |
| **约束层**（合规/可审计） | 引用格式、禁止编造、权限边界、不构成投资建议 | **skill**（不可下沉） |
| **判断层**（怎么做结论） | 怎么归因、三情景怎么切、仓位怎么给 | **模型**（放开） |

**下沉判据**：把"`net_rate < 5%` 是噪音"变成工具返回 `significance: "noise"`，
把"`float_ratio ≥ 5% 且 ≤30 天` 是抛压"变成 `risk_level: "high"`。
阈值只在代码里出现一次，skill 只引用结论。

## 3. 改造清单

### A. 判据下沉到工具（核心，收益最大）

| # | 工具 | 下沉字段 | 取代的提示词规则 | 状态 |
|---|---|---|---|---|
| A1 | `get_market_structure.extra.lhb` | `significance`(noise/notable/strong) + `summary.consecutive_days` + `net_buy` | "net_rate<5% 是噪音" / "连续多日才谈接力" | ✅ 已做 |
| A2 | `get_market_structure.extra.unlock` | `risk_level`(low/medium/high/critical) + `days_to_float` + `summary.max_risk_30d` | "float_ratio≥5% 且≤30天" | ✅ 已做 |
| A3 | `get_market_structure.chip` | `pressure`(sell/hold/buy) + `position`(高于/低于成本密集区) | "获利比例高+贴近密集上沿→抛压" | ⏳ |
| A4 | `get_market_sentiment` | `phase` + `divergence`（已下沉）| 阶段纪律表 | ✅ 已做 |
| A5 | `get_stock_context` | `stance`/`confidence` 结构化 | "AI 评分是评分，不是事实" | ⏳ |
| A6 | `get_daily_history` | `trend`(up/down/side) + `volatility` | "均线多头/空头" | ⏳（有争议，倾向留给模型）|

### B. 约束层：保留在 skill，不可下沉

引用格式 / 禁止编造数字 / 权限边界 / 不构成投资建议 / 非交易日语义 / `degraded/missing` 处理。
—— 这三类**不动**，且要写得更短、更准。

### C. 判断层放开

- 输出框架从"每块怎么写"降到"**必须包含哪几块**"。
- 三情景、仓位建议、归因逻辑、风险叙事 → 模型自由。
- 效果：回答不再千篇一律，模型能根据用户风险偏好、问题深度自适应。

### D. 数据历史：从「今天」到「周期位置」（单独一期）

情绪温度落库（每天收盘一条 `market_sentiment_daily` 表），
`get_market_sentiment` 返回 `phase_day`（升温第几天 / 退潮第几天），
并支持画情绪曲线。这是"知道今天"到"知道处在周期哪个位置"的跨越。

### E. 可审计性强化

引用从纯文本规范化为可选结构化字段 `citations: [{tool, as_of, key}]`，
前端可渲染成可点击的「来源」链 —— 用户能核对每个数字。

### F. skill 瘦身

| 目标 | 现在 | 目标 |
|---|---|---|
| 单 skill 行数 | 33~116 | ≤ 80 |
| 禁令占比 | stock-deep-dive 23% | ≤ 15% |
| 判断性段落 | 大量 | 0（交给模型）|

### G. 验证 / CI

- 保留 `tests/test_skill_specs.py` 的 50 条规范断言。
- 新增：**阈值残留检测** —— skill 正文出现 ≥2 个具体百分数阈值（如 "5%"、"30 天"）时告警，
  提示"该判据是否该下沉到工具？"（软告警，不阻断）。
- 新增：`tests/test_market_structure_annotations.py` 这类纯函数单测（阈值逻辑必须测）。

## 4. 分阶段实施

| 阶段 | 内容 | 预估 |
|---|---|---|
| **P0** | A1/A2（已做）+ A3 筹码压力 + A5 stance/confidence | 0.5 天 |
| **P1** | C 判断层放开 + F skill 瘦身（逐个过一遍，删判断、留事实/约束）| 0.5 天 |
| **P2** | D 情绪历史表 + phase_day + 情绪曲线 | 1 天 |
| **P3** | E 结构化 citations + G 阈值残留 lint | 0.5 天 |

## 5. 本轮已交付（样例）

- `multi_providers.fetch_lhb` 每条加 `significance` / `net_buy`，顶层加
  `summary{latest_significance, consecutive_days, net_buy_days, net_buy_total}`。
- `multi_providers.fetch_share_float` 每条加 `days_to_float` / `risk_level`，
  顶层加 `summary{next_unlock, next_risk_level, max_risk_30d}`。
- 纯函数 `_lhb_significance` / `_unlock_risk_level` / `_consecutive_days`
  + `tests/test_market_structure_annotations.py`（3 例）。
- `stock-deep-dive` 的龙虎榜/解禁两节改为**引用结论字段**，阈值不再出现在提示词里。

关键设计细节（踩坑记录）：

- 连续上榜只算**最近一段**（第一次断档即停），跨周末的 3 天缺口算连续。
- 解禁无比例信息（ratio=None）一律 `low` —— 不因"快解禁了"就凭空升级。
- 阈值在代码里只出现一次，skill 只写字段名，改了代码不用改 9 个 skill。
