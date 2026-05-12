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

## 3. 你的 SkillRegistry 现状

```python
# 当前 6 个 Skill，纯声明式元数据
DEFAULT_SKILLS = {
    "stock-researcher":  SkillSpec("stock-researcher", "AI 研究员", ["quote", "history", "intel", "report"]),
    "stock-monitor":     SkillSpec("stock-monitor", "AI 盯盘员", ["quote", "intel", "monitor_event"]),
    "risk-officer":      SkillSpec("risk-officer", "AI 风控官", ["portfolio", "risk", "audit", "review_inbox"]),
    "strategy-analyst":  SkillSpec("strategy-analyst", "AI 策略分析师", ["list_strategies", "run_strategy_backtest", ...]),
    "rebalance-planner": SkillSpec("rebalance-planner", "AI 调仓规划师", ["portfolio", "risk", "draft_order"]),
    "report-writer":     SkillSpec("report-writer", "AI 报告员", ["report", "history", "audit"]),
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
    name="stock-researcher",
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
    "stock_research":  {"stock-researcher", "report-writer"},
    "strategy_backtest": {"strategy-analyst", "report-writer"},
    "rebalance_plan":  {"stock-researcher", "risk-officer", "rebalance-planner", "report-writer"},
}

# 传入 DeerFlowClient
client = DeerFlowClient(
    available_skills=INTENT_SKILLS.get(intent_name, {"stock-researcher"}),
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
