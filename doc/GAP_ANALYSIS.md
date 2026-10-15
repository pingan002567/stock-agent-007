# 当前项目 vs 目标架构 —— 差距分析

> 项目: stock-agent-001 | 日期: 2026-06-06

---

## 总览

| 维度 | 当前 | 目标 | 差距 |
|------|------|------|------|
| 工具执行 | 双写 ledger（adapter 拦截） | DeerFlow 内部单写 | 🔴 大 |
| Skill 系统 | 自建 SkillRegistry | DeerFlow 原生 SKILL.md | 🟡 中（SKILL.md 已创建，未接入） |
| 多 Agent | subagent_enabled=False | 按 intent 动态启用 | 🟡 中 |
| 多轮对话 | thread_id=run_id（每次新建） | thread_id=session_id | 🟡 中 |
| 工具分组 | 1 组 "workbench" | 4 组 A2/A3/A4/A5 | 🟡 中 |
| extensions_config.json | 不存在 | MCP + skill 状态管理 | 🟡 中 |
| DeerFlow 特性 | 基本全关 | 摘要/循环检测/熔断/Skills | 🟢 小（纯配置） |
| MCP | 无 | 预留接口 | 🟢 小（暂不需要） |

---

## 1. 🔴 工具双写（gap 最大）

### 现状
```
tools.py L205:  _bridge.execute(name, kwargs, authority)    ← 执行 1
adapter L546:  _map_and_execute_tools → bridge.execute()    ← 执行 2（重复）
```

### 目标
```
tools.py:  _tool() 内置全流程 → 执行 1 次 → adapter 纯透传
```

### 需要改动
| 文件 | 行号 | 改动 |
|------|------|------|
| `tools.py` L194-219 | 重写 `_tool` 工厂 | Pydantic→策略→权限→业务→ledger 全内聚 |
| `tools.py` L27 | `_bridge: Any = None` → `ContextVar` | 线程安全注入 |
| `deerflow_client.py` L546-554 | 删 `_map_and_execute_tools` 调用 | 替换为纯事件映射 |
| `deerflow_client.py` L724-799 | 删整个方法 (75行) | - |
| `tool_bridge.py` L570-673 | 精简 `execute()` | 去 DeerFlow 模式的重复逻辑 |

**改动量**: ~80 行净增（删 75 + 重写 100 + 精简 50 + 新增 40）

---

## 2. 🟡 Skill 系统（SKILL.md 已创建，未接入）

### 现状
```
✅ skills/custom/ 下 6 个 SKILL.md 已创建（符合 DeerFlow 标准）
❌ extensions_config.json 不存在 → skills 启/禁状态无法管理
❌ deerflow_config.py 未设置 skills.path
❌ available_skills 未传递给 DeerFlowClient
❌ SkillRegistry 仍在用（Python 代码）
```

### 目标
```
DeerFlow 扫描 skills/custom/ → 6 个 Skill 对象
extensions_config.json 管理 enabled 状态
available_skills 按 intent 动态过滤工具
SkillRegistry 精简为 label 映射
```

### 需要改动
| 文件 | 改动 |
|------|------|
| `extensions_config.json` | 新建: `{"mcpServers":{}, "skills":{"stock-researcher":{"enabled":true},...}}` |
| `deerflow_config.py` L114-124 | 加入 `"skills": {"path": "skills", "container_path": "/mnt/skills"}` |
| `deerflow_client.py` | `DeerFlowClient(available_skills=INTENT_SKILLS[intent])` |
| `skill_registry.py` | 精简为 SKILL_LABELS 映射表 |
| `bootstrap.py` | 注册 extensions_config 路径 |

**改动量**: ~30 行

---

## 3. 🟡 多 Agent（subagent_enabled=False）

### 现状
```
deerflow_client.py L526: subagent_enabled=False  ← 硬编码关闭
copilot_service.py: skill_trace 是声明式标签，非真正多 Agent
```

### 目标
```
简单 intent: Lead Agent 单打（保持 subagent_enabled=False）
复杂 intent: Lead + Subagents 并行（subagent_enabled=True）
SubagentConfig 定义每个 Subagent 的 system_prompt + tool 白名单
```

### 需要改动
| 文件 | 改动 |
|------|------|
| `deerflow_client.py` | `subagent_enabled` 改为参数化 |
| `copilot_service.py` | 按 intent 决定是否启用 subagent |
| `subagent_configs.py` | 新建: 6 个 SubagentConfig |
| `deerflow_config.py` | 加入 `subagents` 配置段 |

**改动量**: ~50 行

---

## 4. 🟡 多轮对话（thread_id 传错）

### 现状
```
copilot_service.py L506: session_id=None       ← 传 None
deerflow_client.py L523: thread_id=session_id or run_id  ← 实际用 run_id
结果: 每次调用都是新 thread，前一轮上下文丢失
```

### 目标
```
copilot_service.py: session_id=state.session_id
deerflow_client.py: thread_id=session_id  ← 复用同一 thread
```

### 需要改动
```
copilot_service.py L506: session_id=None → session_id=state.session_id
```

**改动量**: 1 行

---

## 5. 🟡 工具分组（1 组 vs 4 组）

### 现状
```yaml
# deerflow_config.py L121-123
tool_groups:
  - name: workbench    # 全部 38 个工具在 1 个组
```

### 目标
```yaml
tool_groups:
  - name: a2-research   # A2: 研究工具 (13个)
  - name: a3-risk       # A3: 风险/策略工具 (20个)
  - name: a4-planner    # A4: 调仓工具 (6个)
  - name: a5-blocked    # A5: 阻断 (1个)
```

### 需要改动
| 文件 | 改动 |
|------|------|
| `deerflow_config.py` | TOOL_GROUP_MAP + 按组注册 |
| `deerflow_client.py` | `get_available_tools(groups=AUTHORITY_GROUPS[level])` |

**改动量**: ~30 行

---

## 6. 🟡 extensions_config.json（不存在）

### 现状
```
❌ 文件不存在
→ skills 启/禁状态无法持久化
→ MCP 服务器无法配置
→ DeerFlow 的 SkillStorage 无法管理 enabled 状态
```

### 目标
```json
{"mcpServers": {}, "skills": {"stock-researcher": {"enabled": true}, ...}}
```

### 需要改动
```
新建 extensions_config.json + 设置 DEER_FLOW_EXTENSIONS_CONFIG_PATH
```

**改动量**: 新建 1 个文件

---

## 7. 🟢 DeerFlow 特性（纯配置，随时可开）

| 特性 | 当前 | 目标 | 改动 |
|------|------|------|------|
| Summarization | 未配置 | 32K token 自动压缩 | config 加 1 段 |
| LoopDetection | 未配置 | 防死循环 | config 加 1 段 |
| Circuit Breaker | 未配置 | 连续 5 次失败熔断 | config 加 1 段 |
| Token Usage | 未配置 | 完整追踪 | config 加 1 段 |
| TitleMiddleware | 未配置 | 自动标题 | config 加 1 段 |
| Memory | 未配置 | 跨会话记忆 | config 加 1 段 |
| Guardrails | 未配置 | 工具预授权 | config 加 1 段 |

**改动量**: 纯 YAML 配置，~15 行

---

## 8. 🟢 MCP（预留接口，暂不需要）

### 现状
```
❌ 无 MCP 服务器
✅ extensions_config.json 的 mcpServers 段预留
```

### 未来接入
```
extensions_config.json → mcpServers → DeerFlow 自动加载
无需改代码，只需配置 JSON
```

---

## 实施优先级

```
🔴 P0 (本周) —— 修复 bug + 核心架构
  ├── 工具双写 → TOOL_IN_DEERFLOW.md 方案
  └── 多轮对话 → 改 1 行 thread_id

🟡 P1 (下周) —— Skill + 工具分组 + extensions_config
  ├── extensions_config.json 新建
  ├── deerflow_config.py 加 skills.path + tool_groups 分级
  ├── SkillRegistry 精简
  └── available_skills 接入

🟡 P2 (两周内) —— 多 Agent + 特性配置
  ├── SubagentConfig + 按 intent 动态启用
  └── Summarization / LoopDetection / Circuit Breaker 配置

🟢 P3 (按需) —— Memory / Guardrails / MCP
  └── 纯 YAML 配置，随时可以加
```

## 改动量汇总

| 优先级 | 文件改动数 | 代码行数 |
|--------|----------|---------|
| P0 | 4 文件 | ~80 行 |
| P1 | 4 文件 + 1 新建 | ~60 行 |
| P2 | 3 文件 | ~50 行 |
| P3 | 0 代码 | ~15 行配置 |
| **合计** | **~11 文件** | **~205 行** |
