# daily_stock_analysis 能力迁移设计

## 目标

daily_stock_analysis 是股票分析能力的重要参考，但本项目不应复制它的源码再改名。正确策略是：

```text
吸收能力模型 -> 设计稳定接口 -> 自研 adapter -> 必要时合规引入上游
```

## 已吸收或已规划的能力

| 能力 | 当前 Workbench 映射 |
| --- | --- |
| 行情与报价 | `stock_domain/quote_tools.py` |
| 历史行情 | `stock_domain/history_tools.py` |
| 股票情报 | `stock_domain/intel_tools.py` |
| 组合/持仓 | `stock_domain/portfolio_tools.py` |
| 风险分析 | `stock_domain/risk_tools.py` |
| 回测 | `stock_domain/backtest_tools.py` |
| 报告生成 | `stock_domain/report_tools.py` |
| 盯盘事件 | `monitor_event` + `AI 盯盘员` |

## 仍值得迁移的基础能力

相比直接上复杂 AI，先吸收基础能力更合理。建议优先补齐：

1. 股票基础数据目录
   - 股票代码、名称、市场、行业、板块、拼音别名。
   - 供搜索、个股页、自选和持仓使用。

2. 数据源适配与降级
   - 每个工具输出数据源、更新时间、数据质量。
   - 主数据源失败时返回降级状态。

3. 历史行情缓存
   - 短周期用内存缓存。
   - 后续可用 DuckDB 保存历史行情和回测数据。

4. 事件与通知降噪
   - 盯盘不能把所有消息都推给用户。
   - 需要规则、优先级、频率控制、重复事件合并。

5. 报告模板
   - 单股深研。
   - 市场复盘。
   - 风险扫描。
   - 调仓规划。

6. 策略和回测结果摘要
   - 不需要先做专业量化平台。
   - 先提供策略说明、适用范围、历史表现、风险暴露。

7. 配置与环境检查
   - 数据源可用性。
   - API key 是否配置。
   - 模型 provider 是否可用。

## 不建议迁移的内容

暂不迁移：

- 上游项目的 UI。
- 上游完整调度系统。
- 与本项目对象模型冲突的配置方式。
- 与 DeerFlow 重叠的 agent 编排。
- 任何逐文件复制后轻微改名的实现。

## Adapter 边界

对外暴露稳定接口：

```text
get_realtime_quote(symbol)
get_daily_history(symbol, days)
search_stock_intel(symbol, query)
summarize_portfolio(holdings)
analyze_portfolio_risk(holdings)
get_backtest_summary(strategy_id)
generate_stock_dashboard(context)
```

内部可以先使用 provider-router + mock fallback，实现稳定接口；若安装 optional AKShare extra，再把 `quote/history/intel` 升级为真实数据通道。

## 版权策略

必须遵守：

- 不做“复制源码再改变量名”的迁移。
- 如果直接 vendoring 上游代码，保留上游许可证、来源 URL、commit hash。
- 如果以 adapter 方式调用上游包，文档中标明依赖来源。
- 本项目自有接口、对象模型、业务流程、权限与审计逻辑独立实现。

## 分阶段计划

### Phase 1：基础能力

- 股票搜索目录。
- provider-router + mock fallback，optional AKShare 负责 `quote/history/intel`。
- 持仓风险。
- 报告模板。
- 数据源状态。

### Phase 2：AI 任务化

- DeerFlow runtime 接入。
- 工具事件标准化。
- SSE 流式输出。
- 结构化结果校验。

### Phase 3：长期运行

- 盯盘规则。
- 事件降噪。
- 通知策略。
- 任务重试。

### Phase 4：策略和回测

- 策略库。
- 回测摘要。
- 风险对比。
- 与持仓调仓联动。
