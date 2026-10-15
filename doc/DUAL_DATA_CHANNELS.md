# 双通道数据契约（Mode A / Mode B）

> 状态：已落地（Agent Mode A 工具 + 系统 Mode B 缓存路径）  
> 核心：**共用一份 `data_sources` 配置，Agent 与系统仪表各自独立取数完成功能。**

## 共用配置

| 项 | 说明 |
|----|------|
| 配置键 | `data_sources`（SQLite `repo.get_config`） |
| 谁写 | Settings REST（桌面 / iOS）：启停、按市场主源、凭证 |
| 谁读 | Mode B `provider_router`；Mode A `capability_invoke._data_sources_config` |
| 可用性 | 两边均经 `is_provider_usable`（启用 + 凭证完整） |
| 密钥 | 只在服务端 `provider_credentials.resolve`；工具/API 列表不回显明文 |

没有第二套「Agent 专用源配置」。

## Mode A — Agent 自主查询

| 工具 | 作用 |
|------|------|
| `list_data_sources` | 源目录：能力、鉴权方式说明、是否已配置凭证、健康态（**无密钥**） |
| `describe_data_capability` | 参数 schema / 返回摘要 / 局限 |
| `invoke_data_capability` | 指定 `provider` + `capability` + `params`；服务端注入凭证 |

实现：`backend/stock_domain/capability_registry.py`、`capability_invoke.py`。

### Mode A 能力一览（节选）

| capability | 典型 provider | 说明 |
|------------|---------------|------|
| `quote` / `history` / `financial` | 多源 | 行情 / K 线 / 财报 |
| `industry_boards` / `industry_constituents` | eastmoney / tonghuashun / … | 行业 |
| `cyq` / `moneyflow` | eastmoney / akshare / tushare | 筹码 / 资金流 |
| `northbound_hold` / `margin_detail` / `lhb` / `share_float` | **tushare** | 北向持股 / 两融 / 龙虎榜 / 解禁 |

### 写回策略

- 仅 **非 degraded 的 `quote`** 经 `provider_router.ingest_quote` 写入与 Mode B **相同** 的 mem key（`quote:{SYMBOL}`）及 SQLite 行情表。
- TTL：内存约 60s（与 `_CACHE_TTL["quote"]` 一致）；失败不阻塞 Agent。
- `history` / `financial` / 结构类能力 **不写回**，避免污染仪表盘 TTL 语义。

## Mode B — 系统仪表盘供给

```
SPA / REST /api/*
  → app_services
  → provider_router（选源 + SQLite/内存 TTL）
  → 自选 / 持仓 / 盯盘 / 市场页
```

- **不依赖** Agent 在线；失败用缓存 + `degraded`，不把选源甩给前端。
- 缓存实现以 `provider_router` 代码为准；概述见 [`data_cache_strategy.md`](./data_cache_strategy.md)。
- 典型 REST：watchlist、holdings、monitor、quotes — 只读系统通道。

## 快捷工具 vs Mode A

| 路径 | 含义 |
|------|------|
| `get_stock_context` / `get_market_structure` / `get_daily_history` 等 | **快捷路径**：系统编排，内部仍读同一 `data_sources` + router |
| Mode A `invoke_data_capability` | Agent **显式选 provider**（换源、跨源、快捷 degraded 后兜底） |

简单事实题优先快捷工具；需换源或复杂研究再 Mode A（`list` → `describe` → `invoke`）。

`get_industry_context` 在 `degraded=true` 时会附带结构化 `mode_a_recovery.steps`（优先 `tonghuashun`）。Lead / 研究类 skill **必须**跟随该步骤，禁止跳过编造。

## Mode B 仪表盘降级展示

- 自选 `/api/watchlist`、持仓 `/api/holdings`：报价走 `provider_router.get_quote`（mem/SQLite 优先），失败时返回 `quote.degraded` / `quotes_degraded_count`，前端展示琥珀提示而非空白表。
- 后台预热（`warmup_hot_stocks` / app 启动 market+sectors）受 `should_run_market_warmup` 约束：仅 CN 交易日 08:30–15:30。

## 何时用哪条

| 场景 | 通道 |
|------|------|
| 自选/持仓页刷新 | Mode B |
| 问「茅台现价」 | 快捷 `get_stock_context` |
| 行业接口 degraded / 要换同花顺或 Tushare | Mode A |
| 指定 Tushare 拉北向/两融/龙虎榜/解禁 | Mode A 对应 capability |
| 全网新闻补洞 | `web_search`（最后兜底） |

## 明确不做

- 两套独立的 `data_sources` 配置
- 密钥进入模型上下文 / transcript
- 仪表盘页直接调 Agent 工具
- Agent 为刷仪表盘反复打源
- 任意 URL 裸 HTTP（第二期再议白名单）
