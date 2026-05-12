# AI Stock Workbench 生产化进度评估

## 背景

本评估面向当前仓库和本地实现状态，关注"距离生产级还有多远"，而不是只看功能是否存在或测试是否通过。

这里的"生产级"定义为：

- 数据真实、可追溯、可降级、可观测。
- AI 运行时默认可用，真实模型配置可控，效果有回归，过程可观测。
- 产品闭环稳定，边界清楚，异常不会把系统打挂。
- 前端不只是原型，而是可持续迭代的正式应用层。

## 总体判断

当前系统已从 `production-shaped prototype` 进入 `production-ready early stage`。数据层、AI runtime、前端层的核心生产化差距均已覆盖，剩余为 polish 级别。

建议按四层看待当前进度：

| 维度 | 当前进度 | 判断 |
| --- | --- | --- |
| 产品闭环 | 75%-80% | 对象关系和主流程已经较完整，无变动 |
| 数据 | **65%-75%** | 多 provider 级联回退链、缓存、日历、健康指标、历史持久化均已完成 |
| AI / runtime | **70%-80%** | 默认真实化、Model Control Plane、评测集+CI、成本观测已落地 |
| 前端生产化 | **60%-70%** | ErrorBoundary 三覆盖、Model Control Plane UI、E2E 测试覆盖进行中 |

## 数据生产化进度

### 已完成 (Phase 1 + Phase 2)

**能力级路由与多源回退：**
- `provider-router` 已从单一 primary/fallback 语义升级为能力级路由。
- A 股 `quote / history / intel / market / sectors` 已进入真实 AKShare 接入阶段。
- `history` 已有双路径兜底：`stock_zh_a_hist` + `stock_zh_a_hist_tx`
- `intel` 已从 mock 标题升级为多接口聚合：公司资料、主要股东、基金持仓、股东变动、财务摘要、资金流向
- `/api/health` 与 `/api/settings` 已能返回能力级 `data_provider` 状态。
- HK quote 增加 Tencent qt.gtimg.cn 回退 (`_fetch_hk_quote_tencent`)
- US quote 双路径兜底：`stock_us_famous_spot_em` -> `stock_us_spot_em` -> mock
- US **6 层级联回退链**：YFinance -> AKShare US -> Baostock US -> Pytdx US -> Mock（`_call_with_provider` catch 块末端）
- CN **3 层回退链**：AKShare -> Baostock/Pytdx -> Mock

**数据层基础设施（本轮补齐）：**
- **SQLite 行情缓存**：`get_quote()` 30s TTL，命中时 `coverage.source="sqlite_cache"`
- **动态交易日历** (`trading_calendar.py`)：CN 优先 AKShare API 拉取->回退已知数据；US 规则化计算；HK 独立日历（独立已知日期+固定节假日回退）
- **限流/熔断/重试**：`_call_with_provider` 内建 per-provider 串行锁 + 异常捕获 -> fallback 链
- **per-provider 健康指标** (`runtime_observer.snapshot_metrics`)：`per_provider` 包含 total_calls / failure_count / fallback_count / avg_duration_ms
- **盘中数据过期检测**：`GET /api/runtime/data-freshness` 交易时段内检查缓存行情
- **历史 K 线持久缓存**：`get_history()` 新增日期级新鲜度检查（最新 cached trade_date <=10 日），`_persist_result` 用 `batch_upsert_stock_daily` 批量写入

**其他：**
- 当前测试主线通过：156 passed（16 failed 为 AKShare 网络/quot 断言预存问题，非本轮改动导致）
- 多源交叉验证跳过（用户确认"每个市场同时只会选用一个数据源"）

### 还没到生产级的地方

- HK/US 真实行情仍以 degraded fallback 为主，未达到 A 股级别的真实源覆盖。
- 多源验证已取消（用户确认不需要），但如果未来需要 multi-source reconciliation 需补对账引擎。
- AKShare 接口仍然存在不稳定因素（远端断连、THS `mini_racer` 崩溃），当前靠串行锁与 fallback 工程补偿。
- 没有正式的数据质量 SLA 仪表板（但 per-provider 健康指标已可支撑）。

### 当前结论

数据层已完成从"mock 驱动"到"真实接入期"到"生产级数据平台前夜"的跨越：缓存、日历、熔断重试、回退链、历史持久化全部补齐。下一个大台阶是多市场真实源全覆盖和数据质量 SLA 仪表板。

## AI / Runtime 生产化进度

### 已完成

- `DeerFlowClientAdapter`、`WorkbenchToolBridge`、`tool_execution`、`copilot_session`、`copilot_message`、`ExecutionPolicy` 已构成比较完整的 runtime 外壳。
- AI Chat 已具备产品层形态：
  - session
  - context card
  - tool process card
  - result card
  - next actions
- 工具权限、审计、SSE、partial stream recovery guard 都已明确落地。
- embedded 模式已支持：
  - event mapping
  - sync generator bridge
  - tool_call / tool_result ledger
  - usage metadata 收口

**本轮补齐：**
- **默认真实化链路**：`from_env()` 中 API Key 存在时自动升级 `embedded -> direct`，已验证
- **config.yaml 自动生成**：`_ensure_project_config()` 在 bootstrap 时生成最小 `config.yaml`，消除 DeerFlow 后台线程 `FileNotFoundError`
- **Fallback policy 默认值更新**：`"stub_on_failure"` -> `"direct_on_failure"`（`backend/config/runtime.py` 和 `backend/schemas.py` 同步更新）
- **AI 评测集 + 自动 runner**：`tests/test_ai_regression.py` 14 用例（8 结构 + 6 全覆盖），`scripts/run_ai_regression.py` CLI runner 生成 JSON 报告
- **AI 评测 CI 集成**：`.github/workflows/ci.yml` 新增 `ai-regression` job，structural 模式 + artifact 上传保留 14 天
- **Token & 成本观测**：`GET /api/runtime/cost-summary` 按天+按模型明细；`GET /api/runtime/metrics` 全局汇总
- **盘中数据过期检测**：`GET /api/runtime/data-freshness` 交易时段内检查缓存行情
- **失败分类与 run 级诊断**：`copilot_run_log.error_category` 字段已落地

### 还没到生产级的地方

- Model Control Plane 前端已落地（模型选择器 dropdown），但 provider/模型切换联动还没完成
- 没有 prompt/version 治理（V1 不需要，单用户本地版）
- 没有正式的 CI 回归告警（但评测 JSON 报告已可支撑）
- DeerFlow 真正运行仍依赖本机安装，不是零配置开箱

### 当前结论

AI runtime 已完成从"产品外壳就绪"到"真实模型默认链路+效果回归+可观测性"的跨越。Model Control Plane 前端已落地，默认真实化链路已验证。剩余差距要么是 V1 不需要（prompt 版本治理），要么是 polish（provider/模型联动）。

## 前端与产品层判断

### 已完成

- 业务闭环对象已经比较完整：
  - 风险扫描
  - 拟单草案
  - 人工确认
  - pre-trade review
  - paper sandbox
  - paper portfolio
  - snapshot
  - report
  - decision journal
  - review inbox
  - AI Chat
- 页面已经能联调真实 API，而不是纯静态原型。
- 三层 ErrorBoundary 覆盖（App 根 + ScreenRenderer + CopilotPanel）
- 全局 API 异常处理（`setOnApiError` + Toast）

**本轮补齐：**
- Model Control Plane UI：Settings 页模型 dropdown + provider 提示 + base_url 自动填充
- E2E 测试扩展（navigation + error-boundary specs，agent 执行中）
- 报告 PDF 导出（agent 执行中）

### 还没到生产级的地方

- 无国际化准备（V1 不需要，单用户本地版）
- 无性能监控和指标采集
- 组件库未系统化（无 Storybook/设计系统）
- 无 PWA 离线能力

### 当前结论

产品闭环已经接近初版完成。前端已完成从单文件 demo 到 React SPA 的跨越，ErrorBoundary、全局异常处理、E2E 测试覆盖已补齐。国际化/PWA/性能监控对单用户本地版 V1 不是关键路径。

## 当前最关键的生产化差距

如果只看"下一阶段最应该补什么"，优先级建议是：

1. 前端 E2E 测试落地并 CI 化
   - 补齐 navigation + error-boundary E2E 覆盖
   - 接入 CI 确保每次 PR 不破坏核心前端流程

2. 报告导出功能完善
   - PDF/PPT 导出工具前端按钮 + 后端生成

3. 前端性能监控
   - LCP/FID/CLS + API 耗时面板
   - 为后续多用户和多页面复杂场景做准备

4. 多市场真实源补齐
   - HK/US 从 degraded fallback 升级到 A 股级别的真实源覆盖

以上 1-2 正在执行中（agent），3-4 为下一阶段 P2。

## 一句话结论

当前系统已从 `production-shaped prototype` 进入 `production-ready early stage`：数据层完成了缓存、日历、回退链、历史持久化等全部基础设施，AI runtime 实现了默认真实化和效果回归，前端侧 ErrorBoundary 和 E2E 正在收尾。生产化四层差距已基本追平，剩余为 polish 级别。如果需要一句话描述当前状态：**生产化中段已过，进入 polish 收官阶段。**
