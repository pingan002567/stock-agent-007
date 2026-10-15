# 可运行 Web Demo 实施计划

## 目标

把后端骨架推进到“本地可启动、可浏览器操作”的 demo：使用 `uv` 创建 Python 3.12 环境，启动 FastAPI 后端，并由后端直接托管一个轻量 Web 操作台。

运行方式：

```bash
uv sync --extra test
uv run pytest -q
uv run uvicorn backend.app:app --reload --port 8000
```

浏览器访问：

```text
http://127.0.0.1:8000/demo
```

## Demo 关系

当前项目有两类 demo：

- `prototype/stock-workbench-demo.html`：完整产品原型，用于评审视觉、交互和信息架构。
- `demo/index.html`：后端托管的轻量可运行 demo，用于验证 API、SSE、SQLite、本地报告和 adapter 边界。
- `doc/prototypes/v0.5-skill-trace-demo/stock-workbench-demo.html`：当前 `demo/index.html` 的 v0.5 归档快照，用于追溯 Skill Trace 联调状态。

两者关系：

```text
完整产品原型 -> 指导最终 UI
轻量 Web demo -> 验证后端服务链路
```

后续可把轻量 Web demo 按完整原型一比一复刻，但不应丢失当前 API 验证能力。

## Web Demo 必须支持

### 股票搜索

- 输入 `AAPL`、`腾讯`、`maotai`。
- 展示搜索结果。
- 点击结果后调用 `/api/stocks/{symbol}/context`。
- 展示 `StockContext`。

### 个股深研

- 在个股上下文中点击“生成深研报告”。
- 调用 `POST /api/stocks/{symbol}/research`。
- 页面展示任务 ID、报告 ID、报告结论和内容摘要。

### 持仓风控

- 点击“持仓风险扫描”。
- 调用 `/api/holdings/risk`。
- 展示 AAPL 集中度风险。

### 市场与板块

- 调用 `/api/market/review` 和 `/api/market/sectors`。
- 展示白酒、港股互联网、大型科技板块及关联标的。

### Copilot

- 输入“分析 AAPL 风险”。
- 调用 `POST /api/copilot/chat` 获取 `run_id`。
- 再连接 `/api/copilot/stream/{run_id}`。
- 把 SSE 事件逐条追加到右侧消息流。
- SSE 必须支持声明式 `skill_trace` 事件，用于展示本次请求涉及的 Skills、handoff、权限等级和阻断状态。
- `skill_trace` 不是产品运行时 Team Run，不新增 Team Run 模式或 `/api/team-runs`。
- 调仓类 final payload 必须展示 `execution_guard.auto_trade=false` 和真实交易关闭状态。

## 后端联调增强

- `GET /api/health` 用于启动自检。
- 在 `backend.app:create_app()` 中挂载静态 demo 页面。
- HTTP 端到端测试覆盖：
  - `/api/overview`
  - `/api/stocks/search`
  - `/api/stocks/{symbol}/context`
  - `/api/stocks/{symbol}/research`
  - `/api/holdings/risk`
  - `/api/copilot/chat`
- SSE 测试覆盖 `/api/copilot/stream/{run_id}`。
- Skill Trace 测试覆盖：
  - `POST /api/copilot/chat` 返回 `skills`。
  - `GET /api/tasks` 中对应任务保存 `skill_trace`。
  - `/api/copilot/stream/{run_id}` 输出 `skill_trace` 事件和 final payload。
  - `/api/team-runs` 和 `/api/teamrun` 保持 `404`。
  - 真实下单类请求返回 `403`。

## 版权与迁移边界

- `stock_domain` 保持为本项目自有 adapter。
- 不复制 `daily_stock_analysis` 源码。
- Demo 使用 mock adapter。
- 后续接 DSA 时只替换 adapter 内部实现，并保留上游许可证与来源声明。
- DeerFlow 真实接入时只替换 `DeerFlowClientAdapter` 内部实现，不绕开 Copilot + SkillRegistry + SSE + Task/Report/Audit 边界。

## 手工验收

- `uv run pytest -q` 通过。
- `uv run uvicorn backend.app:app --reload --port 8000` 可启动。
- 浏览器打开 `/demo` 能完成搜索、深研、风控、市场板块、Copilot 流式输出。
- 右侧 AI Copilot 能显示 `skill_trace`。
- 任务页能显示 Skill Trace 面板。
- 输入“把 AAPL 降到 15% 并生成调仓方案”后，输出中能看到 `execution-agent-disabled` blocked 和 `auto_trade=false`。
- 访问 `/api/team-runs` 返回 `404`。
- `prototype/stock-workbench-demo.html` 可直接通过 `file://` 打开，用于产品评审。
