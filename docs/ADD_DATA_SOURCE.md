# 添加新的付费数据源指南

## 1. 创建 Provider 类

在 `backend/stock_domain/multi_providers.py` 中添加新的 Provider 类：

```python
class NewDataProvider:
    """新数据源描述"""
    
    name = "new_provider"  # 唯一标识符
    
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, Any]] = {}
        self._call_lock = threading.RLock()
    
    @property
    def _api_key(self) -> str | None:
        return os.getenv("NEW_PROVIDER_API_KEY") or None
    
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        if (
            os.getenv("PYTEST_CURRENT_TEST")
            and os.getenv("WORKBENCH_TEST_ENABLE_NEW_PROVIDER") != "1"
        ):
            return False
        # 检查依赖包和 API Key
        return find_spec("new_provider_sdk") is not None and self._api_key is not None
    
    def get_quote(self, symbol: str) -> PriceSnapshot:
        """获取实时报价"""
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        
        # 调用 API 获取数据
        # ...
        
        return PriceSnapshot(
            last=price,
            change_pct=change_pct,
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": str(stock["market"]),
                "mode": "real",
                "source_interface": "new_provider.quote",
            },
        )
    
    def get_history(self, symbol: str, days: int = 30) -> dict:
        """获取历史K线"""
        # 实现历史数据获取
        pass
    
    def search_intel(self, symbol: str, query: str = "") -> dict:
        """搜索情报"""
        raise ProviderError("new_provider: intel/search not supported")
    
    def get_market_review(self) -> dict:
        """获取市场综述"""
        raise ProviderError("new_provider: market review not supported")
    
    def get_sectors(self) -> dict:
        """获取板块数据"""
        raise ProviderError("new_provider: sectors not supported")
    
    def get_financial(self, symbol: str) -> dict:
        """获取财务数据"""
        raise ProviderError("new_provider: financial not supported")
```

## 2. 注册 Provider

在 `multi_providers.py` 的 `PROVIDER_CLASSES` 字典中添加：

```python
PROVIDER_CLASSES: dict[str, type] = {
    "akshare": None,
    "tickflow": TickFlowMarketDataProvider,
    "tushare": TushareMarketDataProvider,
    "pytdx": PytdxMarketDataProvider,
    "baostock": BaostockMarketDataProvider,
    "yfinance": YFinanceMarketDataProvider,
    "longbridge": LongbridgeMarketDataProvider,
    "new_provider": NewDataProvider,  # 添加新数据源
    "mock": MockMarketDataProvider,
}
```

## 3. 添加配置

在 `backend/config/data_sources.py` 中添加：

```python
AVAILABLE_PROVIDERS = [
    # ... 现有数据源
    {
        "id": "new_provider",
        "name": "新数据源",
        "markets": ["CN"],  # 支持的市场
        "description": "数据源描述",
        "requirements": "pip install new-provider-sdk && set NEW_PROVIDER_API_KEY",
    },
]
```

## 4. 添加环境变量

在 `.env.example` 中添加：

```env
# New Provider (可选)
# 获取地址: https://newprovider.com
# NEW_PROVIDER_API_KEY=xxxxx
```

## 5. 安装依赖

```bash
pip install new-provider-sdk
```

## 示例：添加聚宽 (JoinQuant) 数据源

```python
class JoinQuantMarketDataProvider:
    """聚宽量化数据接口"""
    
    name = "joinquant"
    
    @property
    def _api_key(self) -> str | None:
        return os.getenv("JOINQUANT_API_KEY") or None
    
    def is_available(self) -> bool:
        return find_spec("jqdatasdk") is not None and self._api_key is not None
    
    def _api(self):
        import jqdatasdk as jq
        jq.auth(self._api_key, os.getenv("JOINQUANT_PASSWORD", ""))
        return jq
    
    def get_quote(self, symbol: str) -> PriceSnapshot:
        jq = self._api()
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        
        # 聚宽代码格式: 000001.XSHE / 600000.XSHG
        jq_code = f"{normalized}.XSHG" if normalized.startswith("6") else f"{normalized}.XSHE"
        
        df = jq.get_price(jq_code, count=1, fields=["close", "pre_close"])
        if df.empty:
            raise ProviderError(f"joinquant empty quote for {normalized}")
        
        last = float(df.iloc[-1]["close"])
        pre_close = float(df.iloc[-1]["pre_close"])
        change_pct = round((last - pre_close) / pre_close * 100, 2) if pre_close else 0
        
        return PriceSnapshot(
            last=last,
            change_pct=change_pct,
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={"market": "CN", "mode": "real"},
        )
```

## 常见付费数据源

| 数据源 | 市场 | 特点 | 价格 |
|--------|------|------|------|
| Tushare Pro | CN/HK | 数据全面，社区活跃 | 免费/付费 |
| 聚宽 JoinQuant | CN | 量化数据，历史丰富 | 付费 |
| 米筐 RiceQuant | CN | 量化数据，API 稳定 | 付费 |
| 恒有数 HSNData | CN | 实时行情，低延迟 | 付费 |
| 通达信 Pytdx | CN | 免费，实时行情 | 免费 |
| 长桥 Longbridge | CN/HK/US | 多市场，API 完善 | 免费/付费 |
| Twelve Data | US | 美股数据，API 稳定 | 免费/付费 |
| Alpha Vantage | US | 美股数据，免费额度 | 免费/付费 |
