# AI 效果治理

## Token & 成本观测

### 架构

每次 Copilot run 完成后，系统自动记录以下指标到 `copilot_run_log` 表：

| 字段 | 来源 | 用途 |
|---|---|---|
| `usage_input_tokens` | DeerFlow final event `usage.input_tokens` | 每次请求的输入 token 数 |
| `usage_output_tokens` | DeerFlow final event `usage.output_tokens` / `usage.completion_tokens` | 每次请求的输出 token 数 |
| `cost` | `_estimate_cost()` 根据 model_name 查定价表计算 | 估算费用（USD） |
| `model_name` | 运行时的 `model_name` 配置 | 区分不同模型成本 |
| `latency_ms` | 从 stream 开始到 final event 的实测耗时 | 端到端延迟 |
| `error_category` | stream 异常时的错误分类 | 失败归因 |

### 定价表

定价表定义在 `backend/app_services/copilot_service.py` 的 `ESTIMATED_COST_PER_1K_TOKENS`：

```python
ESTIMATED_COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "gpt-4":        {"input": 0.03,   "output": 0.06},
    "gpt-4-turbo":  {"input": 0.01,   "output": 0.03},
    "gpt-3.5-turbo":{"input": 0.0015, "output": 0.002},
    "gpt-4o":       {"input": 0.005,  "output": 0.015},
    "gpt-4o-mini":  {"input": 0.00015,"output": 0.0006},
    "deepseek-chat":{"input": 0.0005, "output": 0.002},
}
```

新增模型时在此添加对应单价。未匹配的 model_name 默认按 `gpt-4o-mini` 计价。

### API 端点

#### `GET /api/runtime/metrics`

全局汇总（含 `copilot.usage_input_tokens`、`usage_output_tokens`、`total_cost`、`avg_cost`）。

#### `GET /api/runtime/cost-summary`

按天 + 按模型的成本明细：

```json
{
  "days": [
    {
      "date": "2026-06-01",
      "total_cost": 0.123456,
      "total_input_tokens": 50000,
      "total_output_tokens": 12000,
      "run_count": 15,
      "models": {
        "deepseek-chat": {
          "cost": 0.123456,
          "input_tokens": 50000,
          "output_tokens": 12000,
          "run_count": 15
        }
      }
    }
  ],
  "total": {
    "total_cost": 0.123456,
    "total_input_tokens": 50000,
    "total_output_tokens": 12000,
    "total_runs": 15,
    "models": {
      "deepseek-chat": {
        "cost": 0.123456,
        "input_tokens": 50000,
        "output_tokens": 12000,
        "run_count": 15
      }
    }
  }
}
```

#### `GET /api/runtime/copilot-runs/{run_id}`

单次 run 的 tokens/cost/latency 详情。

### 聚合逻辑

`RuntimeObserver.daily_cost_summary()`:

1. 从持久化 `copilot_run_log` 读取最近 2000 条记录
2. 筛选 `status == "completed"` 的 run
3. 按 `created_at` 的日期前缀分组
4. 每组内再按 `model_name` 拆分子组
5. 返回按日期倒序排列的每日明细 + 全局汇总

### 后续可能扩展

- **Token 预算告警**：日成本超出阈值时通过 monitor 规则告警
- **Per-intent/per-skill 成本拆分**：标记每次 run 的 intent/skill 以定位高消耗场景
- **模型 A/B 对比**：同一请求用不同模型跑，对比成本与质量
