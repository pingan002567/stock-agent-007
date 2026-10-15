# AI Stock Workbench 可行性分析

## 结论

基于 DeerFlow 作为内嵌 Python agent runtime、daily_stock_analysis 作为股票领域能力参考，建设一个 AI 驱动股票工作台是可行的。更稳妥的方式不是把两个项目直接揉成一个系统，而是使用明确的边界：

```text
AI Stock Workbench
  -> Workbench API / UI
  -> DeerFlow Embedded Agent Runtime
  -> Stock Domain Tools
  -> daily_stock_analysis Adapter / 自研基础能力
  -> Local Persistence / Reports / Audit
```

其中：

- DeerFlow 负责 agent 编排、推理流、工具调用、任务流。
- daily_stock_analysis 负责提供可迁移的股票分析能力参考，包括行情、研报、组合、回测、报告等。
- Stock Workbench 自己负责产品对象、权限、审计、报告沉淀、用户交互和风险边界。

## 为什么适合用 DeerFlow

DeerFlow 的价值在于把 AI 工作拆成可编排、可流式输出、可追踪的 agent 任务，而股票工作台天然有这些需求：

- 用户提出自然语言请求：例如“分析 AAPL 风险”“帮我看腾讯是不是该减仓”。
- 系统需要自动选择能力：深研、盯盘、风控、调仓规划、报告生成。
- 每个任务会调用多个工具：行情、历史走势、新闻、持仓、风险、行业、回测。
- 输出需要过程可见：工具调用、证据、推理片段、最终结论、报告。
- 高风险任务需要权限控制：研究允许，拟单允许，真实交易禁止或强确认。

因此 DeerFlow 不应被页面直接调用，而应被封装为 `DeerFlowClient` / `AgentOrchestrator`。

## 为什么 daily_stock_analysis 不应整体复制

daily_stock_analysis 的价值在于领域能力，而不是产品架构本身。直接复制源码会带来几个问题：

- 版权与来源声明风险。
- 与本项目的对象模型、任务流、审计流不一致。
- 可能把上游的 UI、调度、配置、工具风格一起带进来，导致边界混乱。
- 后续升级上游困难。

推荐策略：

- 先吸收能力，不复制实现。
- 建立 `stock_domain` adapter 层。
- 对外暴露稳定工具接口。
- 后续如果需要 vendoring 或 submodule，引入上游许可、commit hash 和来源说明。

## 推荐内部模块

```text
backend/
  api/
  app_services/
  agent_runtime/
  stock_domain/
  persistence/
  config/
```

职责：

- `api`：HTTP/SSE 输入输出。
- `app_services`：业务流程组合。
- `agent_runtime`：DeerFlow 嵌入边界。
- `stock_domain`：股票工具稳定接口。
- `persistence`：SQLite 与本地文件。
- `config`：Provider、Model、Skill、Tool 配置。

## V1 能力边界

V1 适合实现：

- 股票搜索。
- 个股上下文。
- 自选管理。
- 持仓导入与风险扫描。
- 市场与板块复盘。
- AI 盯盘事件。
- AI 深研报告。
- AI 调仓规划草案。
- Copilot SSE 流式输出。
- 任务、报告、审计沉淀。

V1 不应实现：

- 多用户 SaaS。
- 多租户权限。
- 真实交易自动下单。
- 复杂分布式队列。
- Redis/Kafka/Celery 等重型基础设施。

## 集成路线

1. 建立本项目自有对象模型和 mock adapter。
2. 用 mock adapter 打通 API、SSE、报告、任务、审计。
3. 将 daily_stock_analysis 的基础能力逐步映射到 `stock_domain`。
4. 将 DeerFlow 替换当前 stub runtime，保留统一事件格式。
5. 强化权限、配置、审计和结构化输出校验。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| AI 输出不稳定 | 使用 schema、normalizer、repair/fail 状态 |
| 数据源失败 | 工具输出带数据源、更新时间和降级状态 |
| 投资建议风险 | 输出包含证据、反对理由、有效期、免责声明 |
| 自动交易风险 | V1 禁止真实下单，执行代理关闭 |
| 上游代码版权 | 不复制源码，adapter 重写，必要时保留许可 |
