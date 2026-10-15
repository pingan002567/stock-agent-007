# 个股分析·行业维度能力拆分（待审核）

> 起草：2026-07-05 · 状态：**待审核，未开工**
>
> 背景：现有 stock_research 链（researcher → valuation → catalyst → report）对行业维度覆盖很浅——
> `get_stock_context` 只有 sector/industry 标签，同业参照是"可得才做"，行业排名/市占率/壁垒/上下游完全没有数据支撑。
> 目标：让个股研究报告的「竞争格局」一节有真数据、有引用、可验收。

## 现状盘点

| 已有 | 缺失 |
|---|---|
| akshare 东财行业板块接口齐全：`stock_board_industry_name_em`（行业列表+涨跌/资金）、`_cons_em`（成分股）、`_spot_em`（实时）、`_hist_em`（历史） | ❗**股票主表 `industry`/`sector` 字段是空串**（`catalog_tools.py` 三处 `industry=""`）——"个股属于哪个行业"这个最基础的映射不存在 |
| `provider_router.get_sectors()` 已有板块行情能力 | 没有任何行业级领域工具（无法查行业排名/行业内分位） |
| `web_search`（DDG 兜底/Tavily 升级）已接线 | 市占率/壁垒/上下游无结构化数据源（本质是研报文本信息） |
| 研报上传 RAG 已接线（PDF→MD，read_file/grep） | skill 提示词未要求竞争格局分析，未规定 web 来源可信度分级 |

## 能力拆分

### P0-A 个股→行业映射回填（前置依赖，其余全部依赖它）

- **交付物**：股票主表 `industry` 字段有值（A 股先行；港/美股标注 best-effort）
- **数据源**：`stock_board_industry_name_em` × `stock_board_industry_cons_em` 反向索引（行业→成分股 → 建 symbol→industry 映射）
- **改动面**：`catalog_tools.py`（导入时回填）+ `bootstrap._seed_market_data`（播种阶段构建，缓存进 SQLite，`WORKBENCH_SKIP_SEED=1` 跳过）+ 增量刷新策略（行业成分月度变动，缓存 TTL 7 天）
- **验收**：随机抽 10 只 A 股，`industry` 非空且与东财一致；离线启动不被阻塞
- **工作量**：小-中（半天）

### P0-B `get_industry_context` 领域工具（行业排名的硬数据）

- **交付物**：新 agent 工具，输入 symbol 或行业名，输出：
  - 行业快照：涨跌幅（日/月）、资金净流入、行业内公司数
  - 该股行业内分位：市值排名、PE/PB 相对行业中位数、涨幅分位
  - 行业 Top10 成分股对比表（市值/PE/涨幅）
- **改动面**（按项目三处协同约定）：
  1. `stock_domain/industry_tools.py`（新模块，走 provider_router 缓存）
  2. `tool_bridge.py`：注册 handler + ToolSpec（A2 / domain=industry / 只读）
  3. `agent_runtime/tools.py`：`IndustryContextInput` + `_tool` 定义
  4. `skill_specs`/SKILL.md：stock-researcher、valuation-analyst 的 allowed-tools 加入
  5. 前端 TOOL_LABELS：`get_industry_context: "行业格局"`
- **验收**：bridge 单测（含降级：行业查不到时返回明确 degraded 标记）；真实模型问"茅台在白酒行业什么位置"能调用并引用数字
- **工作量**：中（1 天）
- **依赖**：P0-A

### P0-C stock-researcher 提示词升级（竞争格局一节）

- **交付物**：SKILL.md 输出框架新增第 5 节「竞争格局」：
  - 行业地位（调 `get_industry_context`，硬数据）
  - 壁垒/护城河（web_search / 已上传研报，**必须标注来源与可信度**）
  - 上下游依赖（同上；查不到就明确写"数据不足"，禁止凭训练知识编造现状）
- **引用纪律扩展**：web 来源标 `[来源: web · 域名 · 日期]`，训练知识推断必须标「推断·未验证」
- **改动面**：仅 `skills/custom/stock-researcher/SKILL.md`（+valuation-analyst 顺带）
- **验收**：AI 回归标记用例：报告含竞争格局节且每条有来源标注或「数据不足」声明
- **工作量**：小（2 小时）
- **依赖**：P0-B（无工具时该节只能全靠 web，质量差）

### P1-D valuation-analyst 行业相对估值

- **交付物**：估值结论从绝对倍数升级为"相对行业分位"（如 PE 处于行业 35 分位）
- **改动面**：SKILL.md 工作流引用 `get_industry_context` 的行业中位数数据
- **工作量**：小 · **依赖**：P0-B

### P1-E report-writer 模板加行业节

- **交付物**：报告模板含「行业与竞争格局」章节，质量检查项加"行业数据是否有来源"
- **改动面**：report 模板注册表 + 质量检查规则
- **工作量**：小-中

### P2-F 市占率/壁垒/上下游深化（文本路线）

- 研报 RAG 工作流指引：SKILL.md 明确"会话有已上传行业研报时优先 grep 研报"
- web 来源分级：官方公告/券商研报 > 财经媒体 > 论坛（提示词层约定）
- Wind/Choice MCP 接入后的产业链数据（通道已备好，等数据源）
- **工作量**：提示词部分小；MCP 数据源部分取决于外部条件

## 实施顺序与批次建议

```
批次1（P0-A + P0-B + P0-C）≈ 2 天：行业排名硬数据 + 竞争格局输出 → 可独立验收
批次2（P1-D + P1-E）≈ 半天-1 天：估值与报告联动
批次3（P2-F）：提示词部分随批次1顺带；MCP 数据源另议
```

## 风险与边界

- **akshare 行业接口限 A 股**（东财板块）：港/美股行业排名 P0 阶段明确降级为"标签+web 搜索"，不硬凑
- **接口稳定性**：东财接口偶发变动，走 provider_router 降级链（失败→缓存→明确 degraded），不让行业节拖垮整份报告
- **不做**：自建因子库、自算市占率（无权威数据就标注数据不足，宁缺毋假）
