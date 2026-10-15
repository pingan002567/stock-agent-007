# AI Runtime 设置设计

## 背景

AI 工作台需要在设置页管理 Provider、Model、Skill、Tool 和 Profile。用户不应该只看到一个 API key 输入框，而应该能理解系统当前使用哪类模型、哪些技能开启、哪些工具可被调用、哪些动作被禁止。

设计参考 DeerFlow 的 agent runtime 思路：运行时由模型、工具、任务流和上下文共同决定，但在产品层需要被包装成可理解的设置对象。

## 设置对象

```text
Settings
  ├─ Providers
  ├─ Models
  ├─ Profiles
  ├─ Skills
  ├─ Tools
  └─ Guards / Audit
```

## Provider

Provider 表示模型服务商或模型接入通道。

字段建议：

```yaml
ProviderConfig:
  id
  name
  type
  base_url
  api_key_ref
  enabled
  health_status
  last_checked_at
```

页面能力：

- 新增 Provider。
- 测试连接。
- 设置默认 provider。
- 显示健康状态。
- 隐藏密钥明文。

## Model

Model 表示可被 agent runtime 调用的模型。

字段建议：

```yaml
ModelConfig:
  id
  provider_id
  model_name
  purpose
  context_window
  supports_streaming
  supports_tool_calling
  cost_tier
  enabled
```

用途分类：

- `reasoning`：深研、复杂规划。
- `fast`：搜索、摘要、意图识别。
- `coding/tool`：工具调用和结构化修复。
- `fallback`：主模型失败时降级。

## Profile

Profile 是运行配置组合，用于把场景和模型绑定：

```yaml
RuntimeProfile:
  id
  name
  default_model
  fast_model
  reasoning_model
  max_tool_calls
  max_runtime_seconds
  output_schema_mode
  evidence_required
```

示例：

- 日常盯盘：低延迟、少 token、强降噪。
- 深度研究：高推理、更多工具、更长上下文。
- 风控复核：强 schema、强审计、证据必填。

## Skill

Skill 是 AI 能力单元。它不是页面 tab，而是根据语境被调用的能力。

字段建议：

```yaml
SkillConfig:
  id
  name
  description
  enabled
  locked
  default_profile
  allowed_tools
  authority_level
  output_schema
  audit_required
```

默认 Skills：

| Skill | 权限 | 工具 |
| --- | --- | --- |
| AI 研究员 | A2 | quote, history, intel, report |
| AI 盯盘员 | A3 | quote, intel, monitor_event |
| AI 风控官 | A3 | portfolio, risk, audit |
| AI 调仓规划师 | A4 | portfolio, risk, draft_order |
| AI 报告员 | A2 | report, history, audit |
| AI 执行代理 | A5 | V1 locked/disabled |

## Tool

Tool 是最小权限边界。Skill 只能调用允许范围内的工具。

字段建议：

```yaml
ToolConfig:
  id
  name
  category
  enabled
  risk_level
  requires_confirmation
  data_source
  timeout_seconds
```

工具风险：

- L1：只读查询。
- L2：生成报告或任务。
- L3：修改本地状态，例如自选、盯盘规则。
- L4：生成拟单草案。
- L5：真实交易，V1 禁止。

## Permission Guard

权限规则：

- AI 可以研究。
- AI 可以生成调仓建议。
- AI 可以生成拟单草案。
- AI 不能在 V1 真实下单。

## AI Chat 会话与动作边界

v0.20 后右侧 AI Chat 是产品统一入口，但它仍受运行时边界约束：

```yaml
CopilotSession:
  session_id
  title
  current_page
  anchor_symbol
  authority_level
  last_message_at

CopilotMessage:
  message_id
  session_id
  role
  kind
  text
  run_id
  task_id
  payload_summary
```

动作分级：

- 自动允许：只读查询、风险扫描、策略回测、报告生成、盯盘规则评估、paper portfolio snapshot。
- 需要页面显式动作：草案确认/驳回、paper order 创建/取消、decision journal close、review inbox done/dismiss/snooze。
- 永远阻断：真实交易、`place_real_order`、TeamRun。

UI 呈现约束：

- 右侧 Chat 默认展示会话列表、当前对话、上下文卡、工具过程卡、结果卡和 next actions。
- Chat 不直接暴露 TeamRun 控制项，也不在设置页提供真实交易开关。

会话保存原则：

- 保存消息摘要、工具过程摘要、关联对象 ID 和 final answer。
- 不保存 API key、环境变量、完整持仓、完整历史行情、完整报告 Markdown 或完整工具参数。
- 高风险动作必须进入 AuditService。

## 设置页信息架构

建议设置页分为：

1. Providers：模型服务商。
2. Models：模型列表和用途。
3. Profiles：运行 profile。
4. Skills：AI 角色开关、权限和输出 schema。
5. Tools：工具权限和风险级别。
6. Risk Policy：当前 active/default 风险策略、仓位上限、预警线、板块上限、monitor cooldown、draft 有效期。
7. Runtime：流式输出、重试、超时、审计策略。

Risk Policy 设置约束：

- 风险偏好是独立业务对象，不放进 `app_config`；设置页只展示 `/api/settings.risk_policy` 摘要和 `/api/risk-policies` 列表。
- active policy 会回填 monitor 默认 threshold/cooldown、strategy backtest 默认参数、rebalance draft 默认有效期。
- 风险偏好只影响研究、提醒、回测、拟单草案，不影响真实交易，因为 `place_real_order` 继续 blocked。

## 与 DeerFlow 的关系

Workbench 不直接暴露 DeerFlow 内部配置给用户，而是把设置翻译成运行时参数：

```text
Settings UI
  -> provider/model/profile/skill/tool config
  -> AgentOrchestrator
  -> DeerFlowClient.stream()
  -> unified SSE events
```

这样后续替换 DeerFlow 接入方式时，前端和业务对象不需要改变。
