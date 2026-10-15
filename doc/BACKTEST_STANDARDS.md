# 策略回测标准产出规范

> 项目: stock-agent-001 | 日期: 2026-06-09

---

## 1. 收益指标

| 指标 | 说明 | 公式 | 参考值 |
|------|------|------|--------|
| **总收益率** | 回测期间总回报 | (期末净值 - 期初净值) / 期初净值 | > 0 |
| **年化收益率** | 年化后的收益率 | (1 + 总收益率) ^ (365 / 天数) - 1 | > 10% |
| **基准收益率** | 对标指数收益 | 沪深300 / 标普500 | - |
| **超额收益** | 相对基准的超额 | 策略收益 - 基准收益 | > 0 |
| **Alpha** | 超额收益（CAPM） | Rp - [Rf + β(Rm - Rf)] | > 0 |
| **Beta** | 市场敏感度 | Cov(Rp, Rm) / Var(Rm) | 0.5-1.5 |

---

## 2. 风险指标

| 指标 | 说明 | 参考值 |
|------|------|--------|
| **最大回撤** | 最大峰值到谷值的跌幅 | < 20% |
| **波动率** | 收益率标准差（年化） | < 25% |
| **下行波动率** | 只计算负收益的波动 | < 15% |
| **VaR (95%)** | 95%置信度下的最大损失 | - |
| **CVaR (95%)** | 超过VaR的平均损失 | - |
| **回撤持续时间** | 从回撤到恢复的时间 | < 6个月 |

---

## 3. 风险调整收益

| 指标 | 说明 | 公式 | 参考值 |
|------|------|------|--------|
| **夏普比率** | 单位风险的超额收益 | (Rp - Rf) / σp | > 1.0 |
| **索提诺比率** | 只考虑下行风险 | (Rp - Rf) / σd | > 1.5 |
| **卡玛比率** | 收益与最大回撤比 | 年化收益 / 最大回撤 | > 1.0 |
| **信息比率** | 超额收益与跟踪误差比 | Alpha / TE | > 0.5 |
| **Calmar比率** | 收益/最大回撤 | 年化收益 / 最大回撤 | > 0.5 |

---

## 4. 交易统计

| 指标 | 说明 | 参考值 |
|------|------|--------|
| **总交易次数** | 回测期间的交易数量 | - |
| **胜率** | 盈利交易占比 | > 50% |
| **盈亏比** | 平均盈利 / 平均亏损 | > 1.5 |
| **平均持仓天数** | 每笔交易平均持有时间 | - |
| **最大连续亏损** | 连续亏损的最大次数 | < 5次 |
| **单笔最大亏损** | 单笔交易的最大亏损 | < 5% |

---

## 5. 持仓分析

| 指标 | 说明 |
|------|------|
| **持仓集中度** | 前5大持仓占比 |
| **行业分布** | 各行业持仓占比 |
| **换手率** | 交易频率 |
| **持仓周期分布** | 短/中/长期持仓占比 |
| **仓位利用率** | 平均仓位占比 |

---

## 6. 时间维度分析

| 分析 | 说明 |
|------|------|
| **月度收益** | 每月收益率 |
| **年度收益** | 每年收益率 |
| **滚动收益** | 1年/3年滚动收益 |
| **回撤分析** | 各次回撤的时间和幅度 |
| **恢复时间** | 从回撤到恢复的时间 |

---

## 7. 归因分析

| 分析 | 说明 |
|------|------|
| **资产配置归因** | 不同资产类别的贡献 |
| **选股归因** | 个股选择的贡献 |
| **择时归因** | 择时操作的贡献 |
| **交互效应** | 配置与选股的交互影响 |

---

## 8. 压力测试

| 测试 | 说明 |
|------|------|
| **极端市场** | 2008金融危机、2020疫情 |
| **利率冲击** | 利率大幅上升/下降 |
| **流动性危机** | 市场流动性枯竭 |
| **黑天鹅事件** | 极端事件影响 |

---

## 9. 当前系统状态

| 内容 | 当前系统 | 标准回测 |
|------|---------|---------|
| 总收益率 | ❌ | ✅ |
| 年化收益率 | ❌ | ✅ |
| 最大回撤 | ❌ | ✅ |
| 夏普比率 | ❌ | ✅ |
| 胜率 | ❌ | ✅ |
| 月度收益 | ❌ | ✅ |
| 基准对比 | ❌ | ✅ |
| 归因分析 | ❌ | ✅ |
| 信号分析 | ✅ | ✅ |
| 风险摘要 | ✅ | ✅ |
| 候选动作 | ✅ | ✅ |

---

## 10. 实施建议

### P0 - 核心指标（必须）

- 总收益率、年化收益率
- 最大回撤
- 夏普比率
- 胜率

### P1 - 进阶指标（推荐）

- 月度/年度收益表
- 回撤分析
- 基准对比

### P2 - 高级功能（可选）

- 归因分析
- 压力测试
- 滚动收益分析

---

## 11. 数据结构设计

### BacktestMetrics

```python
class BacktestMetrics(BaseModel):
    # 收益指标
    total_return_pct: float
    annualized_return_pct: float
    benchmark_return_pct: float | None
    alpha: float | None
    beta: float | None
    
    # 风险指标
    max_drawdown_pct: float
    volatility_pct: float
    downside_volatility_pct: float
    var_95: float | None
    cvar_95: float | None
    
    # 风险调整收益
    sharpe_ratio: float
    sortino_ratio: float | None
    calmar_ratio: float | None
    information_ratio: float | None
    
    # 交易统计
    total_trades: int
    win_rate: float
    profit_loss_ratio: float
    avg_holding_days: float | None
    max_consecutive_losses: int | None
    max_single_loss_pct: float | None
    
    # 持仓分析
    top5_concentration_pct: float | None
    sector_distribution: dict[str, float] | None
    turnover_rate: float | None
```

### BacktestRun（增强版）

```python
class BacktestRun(BaseModel):
    run_id: str
    strategy_id: str
    strategy_name: str
    strategy_type: str
    
    # 回测配置
    strategy_snapshot: dict
    period: dict
    universe: list[str]
    parameters: dict
    
    # 结果
    metrics: BacktestMetrics
    signals: list[dict]
    risk_summary: dict
    candidate_actions: list[dict]
    
    # 时间维度
    monthly_returns: list[dict] | None
    drawdown_analysis: list[dict] | None
    
    # 元数据
    evidence_refs: list[str]
    risk_policy_ref: dict
    execution_guard: dict
    degraded: bool
    degraded_reason: str | None
    created_at: str
```
