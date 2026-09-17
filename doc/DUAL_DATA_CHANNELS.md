# 双通道数据契约（Mode A / Mode B）

> 状态：已落地（Agent Mode A 工具 + 系统 Mode B 缓存路径）

## Mode A — Agent 自主查询

| 工具 | 作用 |
|------|------|
| `list_data_sources` | 源目录：能力、鉴权方式说明、是否已配置凭证、健康态（**无密钥**） |
| `describe_data_capability` | 参数 schema / 返回摘要 / 局限 |
| `invoke_data_capability` | 指定 `provider` + `capability` + `params`；服务端注入凭证 |

实现：`backend/stock_domain/capability_registry.py`、`capability_invoke.py`。

凭证只存在于 Settings `provider_credentials` / 环境变量，经 `provider_credentials.resolve` 注入 Provider；工具返回会 scrub 常见密钥字段。

成功的 `quote` 可选写回 `provider_router` 内存缓存，供仪表盘间接受益；不阻塞 Agent。

## Mode B — 系统仪表盘供给

路径不变：

```
SPA / REST /api/*
  → app_services
  → provider_router（选源 + SQLite/内存 TTL）
  → 自选 / 持仓 / 盯盘 / 市场页
```

- **不依赖** Agent 在线；失败用缓存 + `degraded`，不把选源甩给前端。
- 缓存策略见 [`data_cache_strategy.md`](./data_cache_strategy.md)。
- 典型 REST：watchlist、holdings、monitor、quotes — 只读系统通道。

## 何时用哪条

| 场景 | 通道 |
|------|------|
| 自选/持仓页刷新 | Mode B |
| 问「茅台现价」 | 快捷 `get_stock_context`（内部可走 router） |
| 行业接口 degraded / 要换同花顺或 Tushare | Mode A `invoke_data_capability` |
| 全网新闻补洞 | `web_search`（最后兜底） |

## 明确不做

- 密钥进入模型上下文 / transcript
- 仪表盘页直接调 Agent 工具
- 任意 URL 裸 HTTP（第二期再议白名单）
