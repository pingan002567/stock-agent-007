# Skill 系统：DeerFlow vs Workbench

> 项目: stock-agent-001 | 日期: 2026-06-06

---

## 1. 两套 Skill 系统并存

项目中有两套完全不同的 "Skill" 概念：

| 维度 | DeerFlow Skill | Workbench SkillRegistry |
|------|---------------|------------------------|
| 定义方式 | SKILL.md 文件（YAML frontmatter + Markdown） | Python dataclass `SkillSpec` |
| 存储位置 | `skills/public/`, `skills/custom/` | `backend/agent_runtime/skill_registry.py` |
| 加载方式 | 文件系统扫描 + 后台线程缓存 | 代码写死 |
| 注入方式 | 系统提示词注入名称+描述 | Prompt Envelope JSON 中的 skill_trace |
| 完整内容 | Agent 通过 `read_file` 按需加载 SKILL.md | 无完整内容，只有元数据 |
| 工具策略 | `allowed-tools` 字段过滤工具 | `tools` 列表（声明式，不实际过滤） |
| 启用控制 | extensions_config.json `skills.{name}.enabled` | `SkillSpec.enabled` / `locked` |
| 数量 | 21 个内置技能（通用领域） | 6 个（股票领域） |

---

## 2. DeerFlow Skill 工作流

```
1. 系统启动
   skills/public/ 和 skills/custom/ 下扫描 SKILL.md
   └── 解析 YAML frontmatter → Skill(name, description, allowed-tools, category)

2. Agent 创建（每次 stream 调用）
   get_skills_prompt_section(available_skills=...)
   └── 注入到系统提示词:
       <skills>
       Available skills:
       - **deep-research**: 多源深度研究
       - **report-generation**: 格式化报告生成
       ...
       Skill files are at /mnt/skills/public/<name>/SKILL.md
       </skills>

3. Agent 运行时
   认为需要某个 skill
   └── read_file("/mnt/skills/public/deep-research/SKILL.md")
       └── 获得完整工作流指引

4. 摘要压缩时
   SummarizationMiddleware._partition_with_skill_rescue()
   └── 最近加载的 skill 文件被 rescued（不被压缩）

5. 安全
   SecurityScanner 扫描 SKILL.md 内容
   tool_policy 根据 allowed-tools 过滤可用工具
```

### Skill 文件格式

```markdown
---
name: deep-research
description: 多源深度研究，生成综合报告
license: MIT
allowed-tools:
  - web_search
  - web_fetch
  - read_file
  - write_file
  - bash
---

# Deep Research Skill

## Workflow
1. 收集信息源
2. 交叉验证
3. 综合分析
4. 生成报告
...
```

---

## 2.5 命名规范：id 功能化，职业名留给 label

`name`（目录名 / frontmatter / `subagent_type`）**必须是功能 id**；
职业称谓只出现在 `label`（UI）和 SKILL.md 正文的「角色」段落里。

理由：

- **`name` 是路由键**：Lead 选 `task(subagent_type=…)`，问的是"这件事该干什么"，
  功能名自带触发信号（`valuation-check` vs `valuation-analyst`）。
- **职业名必然过 claim**：旧名 `stock-researcher` 听起来"任何股票研究都归我"，
  逼得 description 里要写"单指标/现价/PE 查询不要委派"这种补丁；
  `report-writer` 与板块轮动报告重叠，也要写"不要本技能硬套模板"。
- **人格不会丢**：每个 SKILL.md 的「角色」段落 + `label` 都是职业称谓，
  改名不动人设。

| 旧名（职业） | 新名（功能） | label（职业，不变） |
|---|---|---|
| stock-researcher | `stock-deep-dive` | AI 研究员 |
| valuation-analyst | `valuation-check` | AI 估值分析师 |
| catalyst-tracker | `catalyst-scan` | AI 催化剂追踪 |
| risk-officer | `portfolio-risk-audit` | AI 风控官 |
| strategy-analyst | `strategy-backtest` | AI 策略分析师 |
| rebalance-planner | `rebalance-plan` | AI 调仓规划师 |
| stock-monitor | `watch-rule-monitor` | AI 盯盘员 |
| report-writer | `report-render` | AI 报告员 |
| sector-rotation-report | `sector-rotation-digest` | AI 板块轮动报告 |

新增技能时按此约定：`name` 用「对象-动作」，`label` 用职业称谓。

---

## 2.6 规范校验（tests/test_skill_specs.py）

四条硬约束写在测试里，`make test` / CI 都会跑到：

| 断言 | 防的是什么 |
|---|---|
| frontmatter `name` == 目录名 | DeerFlow 按 name 找 `<user>/skills/custom/<name>/SKILL.md`，不一致会静默取不到 |
| `allowed-tools` 都是真实工具 | 写错名字时子代理 schema 里没有它，模型只能猜 |
| 工具的 required_authority ≤ 该 skill 的 authority | 否则运行时被 `permission_guard.require` 拒（`watch-rule-monitor` 曾声明 A3 工具却是 A2） |
| 正文反引号里的工具 ⊆ allowed-tools | 否则技能在教模型用没授权的工具（`sector-rotation-digest` 曾承诺 write_file/bash） |
| 运行时副本 == 仓库 seed（存在时） | 改了仓库却不生效 |

修过的三个真实问题：

1. `watch-rule-monitor`：A2 → **A3**（它要 `upsert_monitor_rule` / `delete_monitor_rule`）
2. `sector-rotation-digest`：正文去掉 `write_file`/`bash` 承诺，补 `generate_report` 授权
3. `get_stock_financial` 不在任何 authority group → 补进 `A2_TOOLS`（否则 Lead 完全看不见）

---

## 2.7 A 股情绪能力（get_market_sentiment + market-sentiment 技能）

此前 skill 里几乎没有 A 股"人性"层面的判断：只有 3 条筹码规则，
涨跌停家数 / 连板高度 / 炸板率 / 赚钱效应这些**情绪温度计**一个都没有，
`lhb` / `margin` / `share_float` 也只作为数据源存在、没有解读规则。

### 工具 `get_market_sentiment`（A2，只读）

数据源全是 akshare / 东财（无需 token）：

| 块 | 来源 | 用途 |
|---|---|---|
| 涨停池 | `stock_zt_pool_em` | 涨停家数、连板数、封板资金、所属行业 |
| 炸板池 | `stock_zt_pool_zbgc_em` | 炸板率 = 炸板 /(涨停+炸板) |
| 昨日涨停池 | `stock_zt_pool_previous_em` | 今日红盘率 = 赚钱效应 |
| 跌停池 | `stock_zt_pool_dtgc_em` | 跌停家数 |
| 涨跌家数/成交额 | `provider_router.get_market_review()` | 广度（已有缓存） |

返回：`temperature`(0-100) / `phase` / `phase_hint` / `divergence` /
`limit_up{ladder,max_streak,sealed_amount_top,hot_sectors}` / `broken{count,rate}` /
`previous_limit_up{red_ratio}` / `breadth` / `score_parts` / `formula` / `coverage`。

**温度分权重**（合计 100，`formula` 字段会一并返回，便于解释）：

```
涨停家数 min(25, 涨停/50*25)    连板高度 min(20, 最高板/6*20)
涨跌比   0.2→0 / 0.8→25          炸板率  20%→15 / 60%→0
昨日涨停红盘率 0.2→0 / 0.8→15
```

**背离守卫（关键）**：A 股常见"涨停不少、全市场普跌"。
只看涨停与赚钱效应会把这种日子判成"升温"，误导成可以普涨参与 ——
所以 `上涨家数占比 < 30% 且涨停 ≥ 30` 时，温度**封顶 55**、阶段改为 **分化**，
并在 `divergence` 里写明"结构性分化，不是普涨"。实测同一交易日：
原始分 88.6（高潮）→ 守卫后 55.0（分化）。

### 技能 `market-sentiment`（A2，16 轮以内）

回答"今天该不该做"，不回答"买什么"。六段输出：
一句话结论（能做/试仓/防守/空仓）→ 温度与阶段 → 温度计三件套 →
资金去向（涨停板块集中度）→ 纪律建议 → 数据健康。

内置阶段纪律表（高潮不加仓 / 冰点不抄底…）与**一致性陷阱**：
"满屏涨停 + 涨跌家数背离"是风险信号而非买入信号。

### 个股维度：资金与筹码行为（stock-deep-dive 新增一节）

`get_market_structure` 的 `extra` 块给了四类 A 股行为数据，但此前**只有数据、没有解读规则**。
现在 `stock-deep-dive` 里写清了判据与禁止项：

| 数据 | 可用字段 | 判据 | 明令禁止 |
|---|---|---|---|
| 龙虎榜 `extra.lhb` | `on_list` / `net_amount` / `net_rate` / `reason` / `institutions` | `|net_rate|<5%` 视为噪音；连续多日上榜才谈接力 | 断言"主力吸筹"；没上榜还反推意图 |
| 两融 `extra.margin` | `rzye` / `rqye` / `rzmre` / `rzche` | **融资净买入 = rzmre − rzche** 是唯一方向信号 | 只有当期值却说"连续 N 日上升"；把低融券余额读成"没人看空" |
| 解禁 `extra.unlock` | `float_ratio` / `float_date` / `holder_name` | ≥5% 且 ≤30 天 → 明确抛压；≥10% 升级为主要风险 | 据此断定近期下跌原因 |
| 北向 `extra.northbound` | 持股快照 `as_of` | 只能描述持仓，不能当资金流 | 写"今日北向净买入" |

并强调三者是**不同的钱**（成本分布 / 席位买卖 / 杠杆资金），禁止互相替代。

### 测试

- `tests/test_market_sentiment.py`：全部离线（monkeypatch 两个取数函数），
  覆盖梯队统计、炸板率、红盘率、温度区间、**背离守卫**、全池失败时的降级（温度必须是 null 而不是 0）
- `tests/test_skill_specs.py`：新技能自动纳入 5 条规范校验

---

## 3. 你的 SkillRegistry 现状

```python
# 当前 6 个 Skill，纯声明式元数据
DEFAULT_SKILLS = {
    "stock-deep-dive":  SkillSpec("stock-deep-dive", "AI 研究员", ["quote", "history", "intel", "report"]),
    "watch-rule-monitor":     SkillSpec("watch-rule-monitor", "AI 盯盘员", ["quote", "intel", "monitor_event"]),
    "portfolio-risk-audit":      SkillSpec("portfolio-risk-audit", "AI 风控官", ["portfolio", "risk", "audit", "review_inbox"]),
    "strategy-backtest":  SkillSpec("strategy-backtest", "AI 策略分析师", ["list_strategies", "run_strategy_backtest", ...]),
    "rebalance-plan": SkillSpec("rebalance-plan", "AI 调仓规划师", ["portfolio", "risk", "draft_order"]),
    "report-render":     SkillSpec("report-render", "AI 报告员", ["report", "history", "audit"]),
}
```

用途：
- `intent_router` → 根据 intent 名字映射到 skill plan
- `copilot_service._build_skill_trace()` → 生成声明式 skill_trace JSON
- prompt_envelope → 把 skill_trace 注入到上下文中

局限：
- `tools` 列表是**人类可读标签**（如 `"quote"`），不是实际工具名（如 `"get_stock_context"`）
- 不实际过滤工具——Agent 看到全部 38 个工具
- 不被 DeerFlow 感知

---

## 4. 推荐方案：三层 Skill 体系

### 4.1 SkillRegistry → 意图路由（保留）

```python
# 保持不变：用于 intent 路由 + skill_trace 生成
SkillRegistry  →  intent_router  →  skill_plan
```

### 4.2 SubagentConfig → 工具白名单 + 角色提示词（新增）

```python
# 当 subagent_enabled=True 时使用
# 每个 skill 对应一个 SubagentConfig，含:
#   - system_prompt（角色指引，替代 SKILL.md）
#   - tools（实际工具名白名单，强制过滤）
#   - disallowed_tools（禁止的工具）

STOCK_RESEARCHER = SubagentConfig(
    name="stock-deep-dive",
    description="分析个股基本面、技术面和情报",
    system_prompt="""你是 AI 股票研究员...""",
    tools=["get_stock_context", "get_daily_history", "search_stock_intel"],
    disallowed_tools=["task", "place_real_order", "generate_draft_order"],
)
```

### 4.3 DeerFlow available_skills → 上下文控制

```python
# 按 intent 决定可见的 skill 范围
# 简单 intent: 只开放对应 skill
INTENT_SKILLS = {
    "stock_research":  {"stock-deep-dive", "report-render"},
    "strategy_backtest": {"strategy-backtest", "report-render"},
    "rebalance_plan":  {"stock-deep-dive", "portfolio-risk-audit", "rebalance-plan", "report-render"},
}

# 传入 DeerFlowClient
client = DeerFlowClient(
    available_skills=INTENT_SKILLS.get(intent_name, {"stock-deep-dive"}),
)
```

### 4.4 要不要创建 SKILL.md 文件？

**不需要。** DeerFlow SKILL.md 是为通用 Agent（需要 `read_file` 加载技能文件）设计的。你的 Agent 已经有：
- `prompt_envelope` 注入上下文
- `SubagentConfig.system_prompt` 注入角色指引
- `available_skills` 控制可见范围

再加 SKILL.md 文件只会增加一个不必要的间接层。

### 4.5 可以用 DeerFlow Skill 的什么？

| 特性 | 要不要用 | 理由 |
|------|---------|------|
| SKILL.md 文件 | ❌ 不需要 | prompt_envelope 已做上下文注入 |
| `available_skills` 白名单 | ✅ 用 | 控制 Agent 看到的 skill 范围 |
| `allowed-tools` 过滤 | ❌ 不需要 | SubagentConfig.tools 白名单更精确 |
| Skill rescue（摘要时） | ❌ 不需要 | 没有 read_file 加载的 skill 文件 |
| SecurityScanner | ❌ 不需要 | 没有外部 skill 文件需要扫描 |
| Skill evolution | ❌ 不需要 | 股票分析 skill 不应该让 Agent 自改 |
| `extensions_config.json` | ✅ 可选 | 通过 API 动态启/禁 skill |

---

## 5. 总结

```
Skill 三层体系:

  SkillRegistry        →  intent 路由 + skill_trace（声明式元数据）
  SubagentConfig       →  工具白名单 + 角色提示词（强制执行）
  available_skills     →  上下文范围控制（DeerFlow 感知）
```

不需要创建 SKILL.md 文件——你的 Agent 通过 `SubagentConfig.system_prompt` 注入角色指引，比文件加载更直接。`available_skills` 白名单用于在 DeerFlow 层面控制 Agent 能看到的 skill 范围。
