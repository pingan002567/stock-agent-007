# Skill 完全依赖 DeerFlow 原生系统 —— 实施指南（已验证）

> 项目: stock-agent-001 | 日期: 2026-06-06
> 验证依据: DeerFlow v2.0 skills/ 模块源码

---

## 1. DeerFlow Skill 系统标准（源码验证）

### 1.1 文件命名

```
SKILL_MD_FILE = "SKILL.md"     ← types.py L5，大小写敏感
```

文件名必须严格为 `SKILL.md`（大写 SKILL，小写 md）。

### 1.2 目录结构

```
skills/                         ← 项目根目录（config.skills.path 或默认）
├── public/                     ← SkillCategory.PUBLIC，只读
│   └── <name>/SKILL.md
└── custom/                     ← SkillCategory.CUSTOM，可读写
    └── <name>/SKILL.md
```

DeerFlow 通过 `os.walk()` 递归扫描 `skills/{public,custom}/`，查找包含 `SKILL.md` 的子目录。跳过以 `.` 开头的隐藏目录。

### 1.3 YAML Frontmatter 规范

```yaml
---
name: stock-researcher           # ★ 必需: hyphen-case, ^[a-z0-9-]+$, ≤64 chars
description: 分析个股...          # ★ 必需: ≤1024 chars, 不能含 < >
license: MIT                     # 可选
allowed-tools:                   # 可选: 字符串列表
  - get_stock_context
  - get_daily_history
version: "1.0"                   # 可选（.skill 包安装时）
author: "team"                   # 可选（.skill 包安装时）
compatibility: ">=2.0"           # 可选（.skill 包安装时）
metadata: {}                     # 可选
---
```

**允许的 frontmatter key**（validation.py L15）：`name`, `description`, `license`, `allowed-tools`, `metadata`, `compatibility`, `version`, `author`

**name 规范**（validation.py L70-75）：
- 正则: `^[a-z0-9-]+$`（小写字母、数字、连字符）
- 不能以 `-` 开头或结尾
- 不能有连续 `--`
- 最大 64 字符

### 1.4 发现机制

```
LocalSkillStorage._iter_skill_files()
  └── os.walk(skills/public/)  → 扫描所有 SKILL.md
  └── os.walk(skills/custom/) → 扫描所有 SKILL.md
      └── parser.parse_skill_file()  → 解析 YAML frontmatter
      └── 缓存到 _enabled_skills_cache（后台线程）
```

### 1.5 工具过滤机制

```python
# tool_policy.py — 取所有已加载 skill 的 allowed-tools 的并集
filter_tools_by_skill_allowed_tools(tools, skills)
  → if no skill declares allowed-tools: return all tools (legacy)
  → else: return tools ∩ union(allowed-tools from all skills)
```

**关键**：一旦任何 skill 声明了 `allowed-tools`，未声明 `allowed-tools` 的 skill 不会贡献工具（fail-closed）。

### 1.6 系统提示词注入

```
apply_prompt_template() → get_skills_prompt_section(available_skills)
  └── 注入 <skills> 段: 每个 skill 的 name + description + 文件路径
  └── Agent 看到: "Skill files are at /mnt/skills/custom/<name>/SKILL.md"
  └── Agent 可通过 read_file 按需加载完整内容
```

### 1.7 摘要保护

```
SummarizationMiddleware._partition_with_skill_rescue()
  └── 识别 AIMessage + ToolMessage 对 中 read_file("/mnt/skills/...") 的调用
  └── 按预算 (5个/25K token) 保留最近加载的 skill 文件
  └── 被 rescue 的 skill 文件不会被摘要压缩
```

---

## 2. 当前项目状态

### 2.1 目录结构 ✅

```
skills/
├── public/                                    ← 空（DeerFlow 要求存在，可以为空）
└── custom/
    ├── stock-researcher/SKILL.md     ✅ name 匹配
    ├── risk-officer/SKILL.md         ✅ name 匹配
    ├── strategy-analyst/SKILL.md     ✅ name 匹配
    ├── rebalance-planner/SKILL.md    ✅ name 匹配
    ├── stock-monitor/SKILL.md        ✅ name 匹配
    └── report-writer/SKILL.md        ✅ name 匹配
```

### 2.2 命名校验 ✅

```
stock-researcher      → ^[a-z0-9-]+$ ✅  ≤64 ✅  无首尾- ✅
risk-officer          → ^[a-z0-9-]+$ ✅  ≤64 ✅  无首尾- ✅
strategy-analyst      → ^[a-z0-9-]+$ ✅  ≤64 ✅  无首尾- ✅
rebalance-planner     → ^[a-z0-9-]+$ ✅  ≤64 ✅  无首尾- ✅
stock-monitor         → ^[a-z0-9-]+$ ✅  ≤64 ✅  无首尾- ✅
report-writer         → ^[a-z0-9-]+$ ✅  ≤64 ✅  无首尾- ✅
```

### 2.3 allowed-tools 校验 ✅

所有 `allowed-tools` 使用实际工具名（如 `get_stock_context`），不是人类可读标签（如 `"quote"`）。

### 2.4 description 校验 ✅

所有 description 不含 `< >` 角括号，不超过 1024 字符。

---

## 3. 需改动的代码

### 3.1 `deerflow_config.py` — 显式设置 skills.path

```python
# backend/agent_runtime/deerflow_config.py

def generate_config(target_dir="data"):
    config = {
        "models": [...],
        "tools": [...],
        "tool_groups": [{"name": "workbench"}],
        "sandbox": {...},
        # ★ 新增: 显式指定 skills 路径
        "skills": {
            "path": "skills",              # 相对于项目根目录
            "container_path": "/mnt/skills",
        },
        # ★ 新增: 摘要保护已加载的 skill
        "summarization": {
            "enabled": True,
            "trigger": [{"type": "tokens", "value": 32000}],
            "keep": {"type": "messages", "value": 10},
            "preserve_recent_skill_count": 5,
            "preserve_recent_skill_tokens": 25000,
            "skill_file_read_tool_names": ["read_file", "read", "view", "cat"],
        },
    }
    ...
```

### 3.2 `extensions_config.json` — 启用 skills

```json
{
  "mcpServers": {},
  "skills": {
    "stock-researcher":    {"enabled": true},
    "risk-officer":        {"enabled": true},
    "strategy-analyst":    {"enabled": true},
    "rebalance-planner":   {"enabled": true},
    "stock-monitor":       {"enabled": true},
    "report-writer":       {"enabled": true}
  }
}
```

或运行时 API：

```python
client.update_skill("stock-researcher", enabled=True)
```

### 3.3 `deerflow_client.py` — 按 intent 传 available_skills

```python
INTENT_SKILLS = {
    "stock_research":    {"stock-researcher", "report-writer"},
    "strategy_backtest": {"strategy-analyst", "report-writer"},
    "rebalance_plan":    {"stock-researcher", "risk-officer", "rebalance-planner", "report-writer"},
    "risk_review":       {"risk-officer", "report-writer"},
    "monitor_event":     {"stock-monitor", "report-writer"},
}

# adapter.stream() 中
client = DeerFlowClient(available_skills=INTENT_SKILLS.get(intent, {"stock-researcher"}))
```

### 3.4 `skill_registry.py` — 精简

```python
# 保留 intent_router 需要的 skill→label 映射即可
# 实际 skill 数据和工具过滤由 DeerFlow 管理
SKILL_LABELS = {
    "stock-researcher": "AI 研究员",
    "risk-officer": "AI 风控官",
    "strategy-analyst": "AI 策略分析师",
    "rebalance-planner": "AI 调仓规划师",
    "stock-monitor": "AI 盯盘员",
    "report-writer": "AI 报告员",
}
```

### 3.5 `SubagentConfig` — 去掉手写工具白名单

```python
# DeerFlow 的 allowed-tools 已经过滤工具，SubagentConfig.tools 设置 None
STOCK_RESEARCHER = SubagentConfig(
    name="stock-researcher",
    tools=None,  # ← 让 DeerFlow 根据 SKILL.md allowed-tools 自动过滤
)
```

---

## 4. 工作流全景

```
1. DeerFlow 启动
   skills/custom/ 下扫描 → 6 个 SKILL.md
   parser.parse_skill_file() → 解析 name/description/allowed-tools
   → 6 个 Skill 对象（enabled 状态来自 extensions_config.json）

2. Agent 创建（每次 stream）
   available_skills = {"stock-researcher", "report-writer"}
   ↓
   _load_enabled_skills_for_tool_policy()
   → 加载所有 enabled skills → 按 available_skills 过滤 → [stock-researcher, report-writer]
   ↓
   filter_tools_by_skill_allowed_tools(38 tools, [stock-researcher, report-writer])
   → union(allowed-tools) = {get_stock_context, get_daily_history, search_stock_intel,
                              list_report_templates, generate_report, get_report_quality}
   → Agent 只看到这 6 个工具！其余 32 个不可见
   ↓
   apply_prompt_template()
   → <skills> 段注入:
       - stock-researcher: 分析个股基本面、技术面和情报...
         (/mnt/skills/custom/stock-researcher/SKILL.md)
       - report-writer: 生成结构化分析报告...
         (/mnt/skills/custom/report-writer/SKILL.md)

3. Agent 运行时
   需要详细了解研究员工作流 → read_file("/mnt/skills/custom/stock-researcher/SKILL.md")
   → 获得完整指引

4. 长对话摘要时
   SummarizationMiddleware 识别到 read_file("/mnt/skills/...") 的调用
   → 保留最近 5 个 skill 文件（≤25000 token）
   → 不参与摘要压缩
```

---

## 5. 验证清单

```bash
# 1. 文件结构
find skills -name "SKILL.md" -type f
# 预期: 6 个文件

# 2. 命名校验
python -c "
import re
for name in ['stock-researcher','risk-officer','strategy-analyst','rebalance-planner','stock-monitor','report-writer']:
    ok = bool(re.match(r'^[a-z0-9-]+$', name)) and len(name) <= 64
    print(f'{name}: {\"PASS\" if ok else \"FAIL\"}')"

# 3. DeerFlow 加载
python -c "
from deerflow.skills.storage import get_or_new_skill_storage
skills = get_or_new_skill_storage().load_skills()
print(f'Loaded {len(skills)} skills:')
for s in skills:
    print(f'  {s.name}: tools={s.allowed_tools}')"

# 4. 工具过滤
python -c "
from deerflow.skills.tool_policy import filter_tools_by_skill_allowed_tools
# 模拟工具列表...
# 验证只返回 allowed-tools 中的工具

# 5. 端到端
# 发送 "分析 AAPL" → Agent 只调用 get_stock_context/get_daily_history/search_stock_intel
# 不调用其他 32 个工具
```
