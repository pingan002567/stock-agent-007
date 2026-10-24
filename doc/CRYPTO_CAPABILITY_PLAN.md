# 币圈（Crypto）能力支持规划

> 状态：规划稿（未动代码）
> 目标：在现有 A 股 / 港股 / 美股 工作台上，增加**币圈行情与分析**能力。
> 边界：**只研究，永不下单**。交易所 API key 一律不落库、不索要。

---

## 0. 实测结论（2026-10-24，中国大陆 ECS + 本地各测一遍）

**主流交易所与聚合站基本全被墙，但 Gate.io 全线可用** —— 选型必须据此来，不能照抄"Binance 优先"的通用方案。

| 数据源 | ECS | 结论 |
|---|---|---|
| api.binance.com / api1 / api-gcp / data-api.binance.vision | ❌ 全超时 | 不可用 |
| www.okx.com | ❌ | 不可用 |
| api.coingecko.com | ❌ | 不可用 |
| api.coinbase.com / kraken / bybit / bitget / mexc | ❌ | 不可用 |
| api.coinpaprika.com | ❌ | 不可用 |
| rest.coincap.io | 401（需 key） | 不可用 |
| **api.gateio.ws** | ✅ 0.35s | **主源** |
| **api.coinlore.net** | ✅ 0.74s | 聚合/市值兜底 |
| **api.llama.fi**（DefiLlama） | ✅ 1.4s | 链上 TVL |
| **api.alternative.me** | ✅ 1.4s | 恐贪指数 |

实测拿到的真实字段（BTC，2026-10-24）：

```
现货 ticker   last 80895.7 · high_24h 82054.2 · low_24h 80515.7
              change_percentage -0.93 · quote_volume 6.06 亿 USDT
K 线          [时间戳, 计价量, 开, 高, 低, 收, 基础量, 是否收盘] ✅
永续合约       funding_rate_indicative 0.000048 · funding_interval 28800(8h)
              maintenance_rate 0.003 · index_price / mark_price ✅
合约统计       open_interest 5.53 亿 USDT · lsr_taker 0.97 · lsr_account 1.94
              top_lsr_size 0.77（大户偏空）· long_liq_usd 45 万 / short_liq_usd 4.5 万 ✅
交易对         6100 个 USDT 现货对
```

**含义**：现货、K 线、资金费率、持仓量、多空比、**清算数据** 全部拿得到 —— 币圈的核心分析面不缺料。
不需要任何 API key，也不碰用户密钥。

⚠️ 若以后要接 Binance/OKX（深度更好、币种更全），必须先解决网络（代理/境外节点），
否则代码写了也连不上。**方案默认不依赖它们。**

---

## 1. 现状盘点：现有架构的假设 vs 币圈

| 维度 | 现在（A/H/US） | 币圈 | 冲突程度 |
|---|---|---|---|
| 交易时段 | 有开收盘、有交易日历（`trading_calendar.py`） | **7×24 连续**，无休市 | 🔴 高 |
| 标的模型 | `StockMaster(symbol, name, market, industry, sector)` | 币种 + 交易对 + 交易所，同一币多个市场 | 🔴 高 |
| 涨跌停 / T+1 | 有（sentiment 涨停池、`手数`限制） | **没有**，但有杠杆与强平 | 🔴 高 |
| 估值 | PE/PB/财报（`get_stock_financial`） | **无财报**，看供应量、解锁、TVL、费用收入 | 🔴 高 |
| 筹码 / 龙虎榜 / 两融 / 解禁 | A 股专用（`extra` 块） | 不适用；换成资金费率/持仓量/清算/链上 | 🟡 中 |
| 情绪 | 涨停池、连板、炸板率 | BTC 主导率、稳定币净流入、恐贪指数、合约多空比 | 🟡 中 |
| 币种 | 单一（人民币计价） | USDT/USD 计价，涉及汇率 | 🟡 中 |
| 涨跌颜色 | 绿涨红跌（国际惯例） | 绿涨红跌 ✅ 一致 | 🟢 无 |
| 数据源 | akshare / tushare / yfinance / longbridge | 交易所 REST + 聚合站 | 🟡 中 |

**结论**：不能靠"加一个 market 值"糊过去，但也不用推倒重来 —— 分层改造即可。

---

## 2. 关键设计决策（先定这 6 个）

### D1. 标的用「币种」还是「交易对」

**建议：canonical symbol = 币种代码（`BTC` / `ETH` / `SOL`），交易对由 provider 拼。**

- 理由：持仓/自选是**资产**语义（我持 0.5 个 BTC），不是"我在 Binance 的 BTCUSDT 交易对"。
- 派生：
  - 现货报价 → 默认 `{SYM}USDT`（可配 `WORKBENCH_CRYPTO_QUOTE_CURRENCY`）
  - 永续 → `BTC-PERP`（后缀区分，和现货同币不同风险）
- `market` 字段新增值：**`CRYPTO`**

### D2. 交易时段怎么处理

`_MARKET_TZ["CRYPTO"] = "UTC"`，并且：
- `is_trading_day("CRYPTO")` → **恒 True**
- `session_has_closed("CRYPTO")` → **恒 True**（永远有"最新已收盘 K 线"= 上一根日线）
- `expected_bar_date("CRYPTO")` → **UTC 当日**（日线以 UTC 00:00 切）

不做特殊分支的话，`market_structure` 里的 `stale / provisional` 判断会全错 —— 这是必改点。

### D3. 数据源选型（按实测，不按名气）

| 用途 | 主源 | 兜底 | 备注 |
|---|---|---|---|
| 现货行情 / K 线 / 交易对 | **Gate.io** `/api/v4/spot/*` | Coinlore（只有现价/市值） | 6100 个 USDT 对，无需 key |
| 永续：资金费率 / 持仓量 / 多空比 / 清算 | **Gate.io** `/api/v4/futures/usdt/*` | — | 一份数据把 P2 全解决 |
| 市值 / 主导率 / 全球概览 | **Coinlore** | DefiLlama | 无需 key |
| 链上 TVL / 稳定币 | **DefiLlama** | — | 无需 key |
| 恐贪指数 | **alternative.me** | — | 无需 key |

**不引入**：Binance / OKX / Coinbase / CoinGecko（实测全不通）。
**不要求**：任何 API key（含交易所私有接口）—— 与"永不索取用户密钥"的底线一致。

限频与缓存：Gate 公共接口按 IP 限频，实测 RTT 0.3–0.5s。建议
`quote` 缓存 5s、`kline` 60s、`global` 300s、`fear_greed` 3600s。

### D4. 新增能力清单（capability）

沿用现有 `CapabilitySpec` 模式，新增：

| capability | 返回 | 说明 |
|---|---|---|
| `crypto_quote` | 现价、24h 涨跌、成交量、市值 | 替代 `quote` |
| `crypto_kline` | OHLCV 多周期（1h/4h/1d） | 替代 `history` |
| `crypto_derivatives` | 资金费率、持仓量、多空比、近 24h 清算 | **币圈特有** |
| `crypto_global` | 总市值、BTC 主导率、24h 量 | 市场层面 |
| `crypto_onchain` | 稳定币净流入、链上 TVL 变化 | 资金面 |
| `crypto_fear_greed` | 恐贪指数 + 分位 | 情绪 |

**A 股专用能力对 CRYPTO 一律 `degraded` + `reason="仅 A 股"`**：`cyq / northbound_hold / margin_detail / lhb / share_float / industry_*`。

### D5. Skill：新增还是改造

**建议新增 `crypto-dive`（A2），不改 `stock-deep-dive`。**

理由：`stock-deep-dive` 里 70% 是 A 股语义（筹码、龙虎榜、解禁、涨跌停、两融），改造成"按 market 分流"会让提示词翻倍、且污染 A 股判断。

`crypto-dive` 的骨架（四段输出，与定时任务契约一致）：

```
1. 结论：做/不做/观望（一句话）
2. 依据：价格结构（关键位/趋势）+ 资金面（资金费率/持仓量/稳定币流入）+ 事件（解锁/升级/监管）
3. 动作：档位（分批建仓/减仓/止损位）+ 触发条件
4. 数据健康：缺哪个源、哪条判断作废
```

`valuation-check` 对币圈**不启用**（无 PE/PB）；币圈"估值"是 tokenomics：
流通量 / 总供应 / FDV / 解锁曲线 —— 放进 `crypto-dive` 的"依据"里。

### D6. 风控差异

| 项 | A 股现状 | 币圈需要 |
|---|---|---|
| 单标的权重上限 | ✅ 可复用 | ✅ 复用，但**按波动率归一**（BTC 10% ≠ 小币 10%） |
| 行业集中 | 有（申万行业） | 换成 **赛道**（L1/DeFi/Meme/AI） |
| 隔夜风险 | 有（T+1 无法当日卖） | **无休市**，但 24/7 意味着"随时可能爆"，风险更高 |
| 杠杆 | 无 | **默认 0**；启用需显式 `WORKBENCH_CRYPTO_LEVERAGE=1` |
| 强平 | 无 | 逐仓/全仓、维持保证金率 → 只在 P3 讨论 |

---

## 3. 代码改造清单（按模块）

| 模块 | 改动 | 量级 |
|---|---|---|
| `stock_domain/catalog.py` | `normalize_symbol` 识别 `BTC`/`BTCUSDT` → canonical `BTC`；`StockMaster.market="CRYPTO"`、`instrument_type="crypto"`；种子入 30–50 个主流币 | 0.5 天 |
| `stock_domain/provider_router.py` | `_provider_for_market("CRYPTO")` → 新 `CryptoProvider`；行情缓存 TTL（quote 5s / kline 60s） | 0.5 天 |
| `stock_domain/crypto_providers.py`（新） | Binance/OKX/CoinGecko/DefiLlama 客户端 + 降级链 + 限频 | 1.5 天 |
| `stock_domain/capability_registry.py` | 新增 6 个 capability；A 股专用能力标 market 限制 | 0.5 天 |
| `stock_domain/trading_calendar.py` | `CRYPTO` 恒开市 + UTC 日线切分 | 0.5 天 |
| `stock_domain/market_structure.py` | `extra` 块对 CRYPTO 返回 `applicable=False`；新增 `derivatives` 块；`stale/provisional` 判断适配 24/7 | 1 天 |
| `stock_domain/sentiment_tools.py` | 按 market 分流：A 股走涨停池，CRYPTO 走主导率/稳定币/恐贪 | 1 天 |
| `skills/custom/crypto-dive/` | 新 skill（四段契约） | 0.5 天 |
| `backend/agent_runtime/skill_specs.py` | 注册 `crypto-dive`（A2，18 轮） | 10 分钟 |
| `frontend` | 24/7 时间轴、USDT 计价显示、`CRYPTO` 图标/标签 | 1 天 |
| `scheduler_service.py` | 币圈值班任务的锚点（见 §5） | 0.5 天 |

**合计 ≈ 8 天**（含自测，不含真实交易）。

---

## 4. 分阶段路线

### P0 · 只读行情（1.5 天）
- `CryptoProvider`：Gate.io 现货 quote + kline（Coinlore 兜底现价/市值）
- `normalize_symbol` 支持 BTC/ETH/…
- `get_stock_context` 对 CRYPTO 返回价格/24h 涨跌/市值（其余标 `degraded`）
- **验收**：问"BTC 现在多少"，能给出价格 + 24h 涨跌 + 来源时间戳

### P1 · 分析能力（2.5 天）
- 新增 `crypto-dive` skill + `get_market_structure` 的 crypto 分支（趋势/关键位/波动率）
- 情绪分流（主导率 + 恐贪 + 稳定币流入）
- **验收**：问"ETH 现在能买吗"，输出四段（结论/依据/动作/数据健康），且明确没有抄 A 股筹码

### P2 · 衍生品与链上（2 天）
- `crypto_derivatives`（资金费率/持仓量/多空比/清算）+ `crypto_onchain`
- 加入 `crypto-dive` 的"资金面"段
- **验收**：能回答"现在合约是不是太挤了"，给出资金费率分位 + 持仓量变化

### P3 · 组合与定时（2 天）
- 持仓支持 `CRYPTO`（权重/成本/盈亏），USDT↔CNY 折算
- 定时任务锚点 + 盯盘规则（价格阈值 / 资金费率异常）
- **验收**：币圈持仓能进组合体检；能配一条"BTC 跌破 X 提醒"

---

## 5. 定时任务的锚点（24/7 特有）

A 股靠 08:30 / 11:45 / 15:15 锚定；币圈没有自然收盘，建议：

| 时点（UTC） | 用途 | 逻辑 |
|---|---|---|
| 00:00 | 日线收盘复盘 | 币圈日线以 UTC 切，最有意义 |
| 08:00 | 亚洲时段前瞻 | 对应 A 股开盘前 |
| 16:00 | 美洲时段前瞻 | 对应美股开盘前 |

资金费率结算（每 8h：00/08/16 UTC）是天然的"体检点"——可以做成事件触发而非定时。

---

## 6. 风险与取舍（要提前认的）

1. **数据源可用性（已实测，且比预想严重）**：Binance / OKX / Coinbase / CoinGecko **全部不可达**，
   只有 Gate.io + Coinlore + DefiLlama + alternative.me 可用。Fallback 链只能是
   `Gate.io → Coinlore`（只有现价与市值），一旦 Gate 挂了，K 线/合约数据就没了 ——
   必须把降级写进 `coverage.missing` 并让 skill 明确说"这段判断作废"。
2. **操纵与噪音**：小市值币拉盘砸盘、刷量严重。`crypto-dive` 必须带"流动性门槛"（24h 成交额 < 阈值直接说"做不成"）。
3. **汇率**：USDT 不是 1:1 人民币，组合里要显式写用哪个汇率、什么时候取的。
4. **合规**：境内对虚拟货币交易有明确限制。**本系统只做研究，不接任何交易 API**；这一点要在提示词与 UI 双重声明。
5. **别把币圈硬塞进 A 股 skill**：宁可多一个 skill，也不要让 `stock-deep-dive` 里出现"BTC 的筹码分布"这种胡话。

---

## 7. 验收标准（每阶段 DoD）

| 阶段 | DoD |
|---|---|
| P0 | 3 个主流币的 quote/kline 可取；断网时 `degraded=true` 且有 reason；不泄露任何 key |
| P1 | `crypto-dive` 通过 skill 规范 5 条校验；输出四段；明确拒绝 A 股概念 |
| P2 | 资金费率/持仓量有分位口径；数据缺失时不编 |
| P3 | 币圈持仓进组合体检；定时任务按时触发且能跳过（数据源全挂时） |

---

## 8. 建议的下一步

先做 **P0（1.5 天）**：只读行情打通，验证"数据源可用性 + 24/7 日历改造"这两个最硬的假设。
P0 跑通再决定要不要继续 —— 如果 Binance/OKX 在你的网络环境里都不稳定，后面全是空中楼阁。
