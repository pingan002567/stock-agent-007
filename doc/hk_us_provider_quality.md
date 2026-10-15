# HK/US Provider 数据质量 (P4)

> 目标：提高港股和美股市场的数据查询成功率，降低"查不到"的发生频率。
> 状态：设计稿，待实现。

---

## 现状分析

### 港股 (HK) 查询链路

当前 `AkShareMarketDataProvider.get_quote()` HK 段：

```
get_quote("HK00700")
  │
  ├─ Layer 1: stock_hk_hot_rank_em()  ← 仅覆盖 ~100 支热门港股
  │   ├─ 命中 → 返回实时行情
  │   └─ 未命中 → fall through
  │
  └─ Layer 2: _fetch_hk_quote_tencent() ← 腾讯港股接口，无文档
      ├─ 成功 → 返回
      └─ 失败 → raise ProviderError("HK quote not available")
```

**问题**：
- `stock_hk_hot_rank_em` 只覆盖东方财富热度排名前 ~100 的港股，大量有效港股不在其中
- Layer 2 Tencent 接口无稳定文档，可用性不确定
- 没有全量港股实时行情接口作为中间层

### 美股 (US) 查询链路

```
get_quote("AAPL")
  │
  ├─ Layer 1: stock_us_famous_spot_em()  ← 知名美股
  ├─ Layer 2: stock_us_spot_em()         ← 全量美股 (8000+)
  ├─ Layer 3: _fetch_us_quote_tencent()   ← 腾讯美股接口
  ├─ Layer 4: _fetch_us_quote_twelvedata() ← 可选, 需 TWELVEDATA_API_KEY
  └─ 全失败 → raise ProviderError("US quote not available")
```

**问题**：
- 四层 fallback 看似充分，但全走 akshare 内部接口
- yfinance provider 已存在于 `multi_providers.py` 但未被链入 US 回退链
- TwelveData 需要额外 API key，不是默认可用

### ProviderRouter secondary chain 配置

`provider_router.py` `_secondary_providers()` 当前配置：

```python
if market == "US":
    for pid in ["akshare"]:           # ← 只加了 akshare 自身，等于空
        ...
elif market == "HK":
    if primary.name != "akshare":     # ← primary 就是 akshare，不触发
        p = self._get_provider("akshare")
```

**问题**：secondary chain 对 HK/US 市场实质为空，不提供多 provider 回退保障。

---

## 设计方案

### 方案 A：增加 `stock_hk_spot_em` 中间层（HK）

akshare 提供了 `stock_hk_spot_em()` — 全量港股实时行情接口，覆盖约 2500+ 支港股，远好于 hot_rank_em 的 ~100 支。

```python
# providers.py, AkShareMarketDataProvider.get_quote() HK section

if market == "HK":
    hk_code = normalized.removeprefix("HK")

    # Layer 1: hot_rank_em (fast, ~100 stocks)
    try:
        hot_frame = self._cached(("hk_hot_rank", "all"), ttl_seconds=30, ...)
        row = _find_row(hot_frame, "代码", hk_code)
        return PriceSnapshot(...)
    except Exception:
        pass

    # Layer 2 (新增): stock_hk_spot_em — 全量港股实时行情
    try:
        hk_spot = self._cached(("hk_spot", "all"), ttl_seconds=30,
            loader=lambda: self._ak().stock_hk_spot_em())
        row = _find_row(hk_spot, "代码", hk_code)
        return PriceSnapshot(...)
    except Exception:
        pass

    # Layer 3: Tencent fallback (已有)
    try:
        return self._fetch_hk_quote_tencent(normalized)
    except Exception:
        pass

    raise ProviderError(f"HK quote not available for {normalized} ...")
```

**改动量**：~15 行。新增一个 `_cached` 调用 + fallback 层。

### 方案 B：yfinance 链入 US secondary chain

`yfinance` provider 已完整实现，支持 US 市场的 `get_quote`、`get_history`、`get_financial`。只需在 provider_router 的 `_secondary_providers()` 中将其加入 US 回退链：

```python
# provider_router.py _secondary_providers()

if market == "US":
    for pid in ["yfinance", "akshare"]:   # ← 加入 yfinance，排在 akshare 前
        p = self._get_provider(pid)
        if p.name != primary.name and p.is_available():
            chain.append(p)
```

当 akshare US 全部失败时（`_call_with_provider` 中 retry + secondary chain），会依次尝试 yfinance → akshare (self) → mock。

**Fallback 链路完整流程**：

```
akshare US get_quote 失败
  → 重试 0.5s, 1.0s (已有)
  → secondary: yfinance.get_quote("AAPL")  ← 新增，大概率成功
  → secondary: akshare (自引用，无意义)
  → mock_adapter.get_quote("AAPL")         ← 必成功，降级数据
```

**改动量**：~1 行（`["akshare"]` → `["yfinance", "akshare"]`）。

### 方案 C：启动时自动导入 HK/US stock_master

现有 `import_hk_stock_master()` 和 `import_us_stock_master()` 已实现，但未被 bootstrap 自动调用：

```python
# providers.py 已有方法
class AkShareMarketDataProvider:
    def import_hk_stock_master(self) -> list[dict]: ...  # ~250 支
    def import_us_stock_master(self) -> list[dict]: ...  # ~150 支
```

改为启动时自动导入（当 stock_master 表为空时）：

```python
# bootstrap.py

if stock_provider_router.primary.is_available():
    if not repo.list_stock_master(market="CN"):
        result = import_a_share_master()           # 已有

    if not repo.list_stock_master(market="HK"):
        hk_list = provider.import_hk_stock_master()
        for item in hk_list:
            repo.upsert_stock_master(StockMaster(
                symbol=item["symbol"],
                name=item["name"],
                market=item["market"],
                active=True,
            ))

    if not repo.list_stock_master(market="US"):
        us_list = provider.import_us_stock_master()
        # 同理 upsert
```

**收益**：配合 P3 synthetic entry，即使 akshare HK/US 行情接口查不到，P3 也能正确识别 market=HK/US，放行 provider 查询。catalog 覆盖从手动维护的 ~10 只扩展到 ~400 只热门股。

---

## 实施路线

| 步骤 | 文件 | 改动量 | 风险 | 收益 |
|---|---|---|---|---|
| **P4a**：HK `get_quote` 增加 `stock_hk_spot_em` 中间层 | `providers.py` | ~15 行 | 低，新增 fallback 不破坏现有链 | HK 冷门股查询成功率从 ~30% → ~90% |
| **P4b**：yfinance 加入 US secondary chain | `provider_router.py` | ~1 行 | 低，yfinance 已存在且稳定 | US 数据可观测性提升，降低 fallback 到 mock 概率 |
| **P4c**：启动时自动导入 HK/US stock_master | `bootstrap.py`, `repositories.py` | ~50 行 | 低，已有 `import_*_stock_master()` | catalog 覆盖从 10 支 → 400+ 支 |

### 不推荐的做法

| 做法 | 不推荐原因 |
|---|---|
| 全量导入 HK 股票（~2500 支）到 stock_master | 长尾股票极少被查询，P3 synthetic entry 已兜底 |
| 在 akshare provider 内部调用 yfinance | 混入不同 provider 的依赖边界，应统一由 provider_router 编排 |
| 引入第三方行情服务（如 TwelveData 做 primary） | 需要 API key 和费用，当前阶段非必需 |
| 为 HK/US 实现 `get_market_review`/`get_sectors` | AKShare 不支持 HK/US 大盘/板块数据，mock 数据已够用 |

---

## 效果验证

### P4a 验证（HK spot 覆盖）

```python
# 改造前
ak = AkShareMarketDataProvider()
ak.get_quote("HK00005")  # 汇丰 — hot_rank 里有 → OK
ak.get_quote("HK00123")  # 越秀地产 — hot_rank 可能没有 → ProviderError

# 改造后
ak.get_quote("HK00123")  # hot_rank miss → stock_hk_spot_em hit → OK
```

### P4b 验证（US secondary chain）

```python
# 通过 provider_router 查询，akshare US 全部失败
router.get_quote("AAPL")
# 改造前 → _call_with_provider 全部失败 → mock_adapter 降级数据
# 改造后 → secondary yfinance 接管 → 真实数据
```

### P4c 验证（stock_master 覆盖）

```python
# 改造前
repo.list_stock_master(market="HK")  # [] (除非手动 seed)

# 改造后
repo.list_stock_master(market="HK")  # [~250 rows, 含腾讯/阿里/美团...]
```
