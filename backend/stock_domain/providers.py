from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib.util import find_spec
import logging
import os
import time
import threading
from typing import Any, Protocol

from backend.schemas import PriceSnapshot, now_iso
from backend.stock_domain.catalog import get_stock, normalize_symbol

_log = logging.getLogger("providers")

# Fallback HK stock list (Stock Connect + major indices) used when AKShare HK APIs
# are unreachable (e.g. network restrictions on Chinese financial data endpoints).
_HK_STOCKS_FALLBACK: list[tuple[str, str]] = [
    # ——— 恒生指数成份股 Hang Seng Index Constituents ———
    ("00001", "长和"),
    ("00002", "中电控股"),
    ("00003", "香港中华煤气"),
    ("00005", "汇丰控股"),
    ("00006", "电能实业"),
    ("00011", "恒生银行"),
    ("00012", "恒基地产"),
    ("00016", "新鸿基地产"),
    ("00017", "新世界发展"),
    ("00019", "太古股份公司A"),
    ("00027", "银河娱乐"),
    ("00066", "港铁公司"),
    ("00083", "信和置业"),
    ("00101", "恒隆地产"),
    ("00175", "吉利汽车"),
    ("00241", "阿里健康"),
    ("00267", "中信股份"),
    ("00288", "万洲国际"),
    ("00291", "华润啤酒"),
    ("00316", "东方海外国际"),
    ("00322", "康师傅控股"),
    ("00386", "中国石油化工股份"),
    ("00388", "香港交易所"),
    ("00669", "创科实业"),
    ("00688", "中国海外发展"),
    ("00700", "腾讯控股"),
    ("00762", "中国联通"),
    ("00823", "领展房产基金"),
    ("00857", "中国石油股份"),
    ("00868", "信义玻璃"),
    ("00881", "中升控股"),
    ("00883", "中国海洋石油"),
    ("00939", "中国建设银行"),
    ("00941", "中国移动"),
    ("00960", "龙湖集团"),
    ("00968", "信义光能"),
    ("00981", "中芯国际"),
    ("00992", "联想集团"),
    ("01038", "长江基建集团"),
    ("01044", "恒安国际"),
    ("01088", "中国神华"),
    ("01093", "石药集团"),
    ("01099", "国药控股"),
    ("01109", "华润置地"),
    ("01113", "长实集团"),
    ("01171", "兖矿能源"),
    ("01209", "华润万象生活"),
    ("01211", "比亚迪股份"),
    ("01299", "友邦保险"),
    ("01378", "中国宏桥"),
    ("01398", "工商银行"),
    ("01466", "海丰国际"),
    ("01769", "中国中免"),
    ("01776", "广发证券"),
    ("01810", "小米集团-W"),
    ("01818", "招金矿业"),
    ("01876", "百威亚太"),
    ("01898", "中煤能源"),
    ("01928", "金沙中国有限公司"),
    ("01929", "周大福"),
    ("01997", "九龙仓置业"),
    ("02013", "微盟集团"),
    ("02015", "理想汽车-W"),
    ("02018", "瑞声科技"),
    ("02020", "安踏体育"),
    ("02057", "中通快递-W"),
    ("02269", "药明生物"),
    ("02313", "申洲国际"),
    ("02318", "中国平安"),
    ("02319", "蒙牛乳业"),
    ("02328", "中国财险"),
    ("02331", "李宁"),
    ("02333", "长城汽车"),
    ("02338", "潍柴动力"),
    ("02359", "药明康德"),
    ("02382", "舜宇光学科技"),
    ("02388", "中银香港"),
    ("02518", "汽车之家-S"),
    ("02588", "中银航空租赁"),
    ("02618", "京东物流"),
    ("02628", "中国人寿"),
    ("02688", "新奥能源"),
    ("02822", "南方A50"),
    ("02823", "安硕A50"),
    ("02828", "恒生中国企业"),
    ("02899", "紫金矿业"),
    ("02903", "香港电讯-SS"),
    ("03328", "交通银行"),
    ("03333", "中国恒大"),
    ("03690", "美团-W"),
    ("03800", "协鑫科技"),
    ("03888", "金山软件"),
    ("03968", "招商银行"),
    ("03988", "中国银行"),
    ("06030", "中信证券"),
    ("06098", "碧桂园服务"),
    ("06186", "中国飞鹤"),
    ("06618", "京东健康"),
    ("06690", "海尔智家"),
    ("06862", "海底捞"),
    ("06969", "思摩尔国际"),
    ("09618", "京东集团-SW"),
    ("09626", "哔哩哔哩-W"),
    ("09633", "农夫山泉"),
    ("09660", "新东方-S"),
    ("09668", "阅文集团"),
    ("09688", "百度集团-SW"),
    ("09698", "万国数据-SW"),
    ("09888", "百度集团-SW"),
    ("09899", "云音乐"),
    ("09901", "新东方在线"),
    ("09961", "携程集团-S"),
    ("09988", "阿里巴巴-SW"),
    ("09992", "泡泡玛特"),
    # ——— H股 / 红筹 ———
    ("00168", "青岛啤酒股份"),
    ("00347", "鞍钢股份"),
    ("00548", "深圳高速公路股份"),
    ("00553", "南京熊猫电子股份"),
    ("00564", "郑州煤机"),
    ("00728", "中国电信"),
    ("00753", "中国国航"),
    ("00780", "同程旅行"),
    ("00811", "新华文轩"),
    ("00874", "白云山"),
    ("00902", "华能国际电力股份"),
    ("00914", "海螺水泥"),
    ("00916", "龙源电力"),
    ("00934", "中石化冠德"),
    ("00939", "建设银行"),
    ("00956", "中粮包装"),
    ("00966", "中国太平"),
    ("01030", "新城发展"),
    ("01057", "浙江沪杭甬"),
    ("01066", "威高股份"),
    ("01071", "华电国际电力股份"),
    ("01099", "国药控股"),
    ("01108", "凯盛科技"),
    ("01157", "中联重科"),
    ("01171", "兖矿能源"),
    ("01177", "中国生物制药"),
    ("01186", "中国铁建"),
    ("01288", "农业银行"),
    ("01302", "先声药业"),
    ("01336", "新华保险"),
    ("01339", "中国人保"),
    ("01359", "中国信达"),
    ("01375", "中州证券"),
    ("01385", "上海复旦"),
    ("01398", "工商银行"),
    ("01548", "金斯瑞生物科技"),
    ("01658", "邮储银行"),
    ("01772", "赣锋锂业"),
    ("01787", "山东黄金矿业"),
    ("01797", "新东方在线"),
    ("01833", "平安好医生"),
    ("01898", "中煤能源"),
    ("01951", "锦欣生殖"),
    ("01963", "重庆银行"),
    ("02039", "中集集团"),
    ("02196", "复星医药"),
    ("02202", "万科企业"),
    ("02208", "金风科技"),
    ("02282", "美高梅中国"),
    ("02319", "蒙牛乳业"),
    ("02333", "长城汽车"),
    ("02338", "潍柴动力"),
    ("02357", "中航科工"),
    ("02359", "药明康德"),
    ("02601", "中国太保"),
    ("02607", "上海医药"),
    ("02727", "上海电气"),
    ("02883", "中海油田服务"),
    ("03369", "秦港股份"),
    ("03380", "龙光集团"),
    ("03606", "飞鹤"),
    ("03759", "康龙化成"),
    ("03898", "中车时代电气"),
    ("03993", "洛阳钼业"),
    ("06030", "中信证券"),
    ("06185", "康龙化成"),
    ("06837", "海通证券"),
    ("06881", "中国银河"),
    ("06886", "华泰证券"),
    ("09668", "阅文集团"),
    # ——— 恒生科技指数重点 ———
    ("00020", "商汤-W"),
    ("00268", "金蝶国际"),
    ("00354", "中国软件国际"),
    ("00700", "腾讯控股"),
    ("00772", "阅文集团"),
    ("00780", "同程旅行"),
    ("00909", "明源云"),
    ("01024", "快手-W"),
    ("01347", "华虹半导体"),
    ("01797", "东方甄选"),
    ("01810", "小米集团-W"),
    ("02015", "理想汽车-W"),
    ("02382", "舜宇光学科技"),
    ("02800", "盈富基金"),
    ("03690", "美团-W"),
    ("03888", "金山软件"),
    ("06060", "众安在线"),
    ("06618", "京东健康"),
    ("06682", "第四范式"),
    ("09618", "京东集团-SW"),
    ("09626", "哔哩哔哩-W"),
    ("09688", "百度集团-SW"),
    ("09888", "百度集团-SW"),
    ("09988", "阿里巴巴-SW"),
    ("09999", "网易-S"),
    # ——— 基金 / ETF ———
    ("02800", "盈富基金"),
    ("02801", "安硕中国ETF"),
    ("02822", "南方A50"),
    ("02823", "安硕A50"),
    ("02828", "恒生中国企业"),
    ("03033", "南方恒生科技"),
    ("03067", "安硕恒生科技"),
    ("03088", "华夏恒生科技"),
    ("03188", "华夏沪深300"),
    ("07226", "XL二南方恒科"),
    ("07233", "XL二南方沪深300"),
    ("07552", "XI二南方恒科"),
]

# Fallback US stock list (S&P 500 / Nasdaq major names) for when AKShare
# US stock APIs (East Money / Sina) are unreachable.
_US_STOCKS_FALLBACK: list[tuple[str, str]] = [
    # ——— 大型科技 ———
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("GOOGL", "Alphabet"),
    ("GOOG", "Alphabet C"),
    ("AMZN", "Amazon"),
    ("META", "Meta"),
    ("NVDA", "NVIDIA"),
    ("TSLA", "Tesla"),
    ("INTC", "Intel"),
    ("AMD", "AMD"),
    ("CRM", "Salesforce"),
    ("ADBE", "Adobe"),
    ("ORCL", "Oracle"),
    ("IBM", "IBM"),
    ("CSCO", "Cisco"),
    ("QCOM", "Qualcomm"),
    ("TXN", "Texas Instruments"),
    ("AVGO", "Broadcom"),
    ("MU", "Micron"),
    ("NOW", "ServiceNow"),
    ("UBER", "Uber"),
    ("NFLX", "Netflix"),
    ("PYPL", "PayPal"),
    ("SNAP", "Snap"),
    ("PINS", "Pinterest"),
    ("SPOT", "Spotify"),
    ("ZM", "Zoom"),
    ("SQ", "Block"),
    # ——— 电商 / 消费互联网 ———
    ("BABA", "Alibaba"),
    ("JD", "JD.com"),
    ("PDD", "Pinduoduo"),
    ("NIO", "NIO"),
    ("LI", "Li Auto"),
    ("XPEV", "XPeng"),
    ("SE", "Sea Limited"),
    ("MELI", "MercadoLibre"),
    ("SHOP", "Shopify"),
    ("ETSY", "Etsy"),
    # ——— 传统蓝筹 ———
    ("JPM", "JPMorgan Chase"),
    ("BAC", "Bank of America"),
    ("WFC", "Wells Fargo"),
    ("GS", "Goldman Sachs"),
    ("MS", "Morgan Stanley"),
    ("V", "Visa"),
    ("MA", "Mastercard"),
    ("AXP", "American Express"),
    ("DIS", "Walt Disney"),
    ("NKE", "Nike"),
    ("MCD", "McDonald's"),
    ("SBUX", "Starbucks"),
    ("KO", "Coca-Cola"),
    ("PEP", "PepsiCo"),
    ("WMT", "Walmart"),
    ("COST", "Costco"),
    ("HD", "Home Depot"),
    ("LOW", "Lowe's"),
    ("TGT", "Target"),
    ("UNH", "UnitedHealth"),
    ("JNJ", "Johnson & Johnson"),
    ("PFE", "Pfizer"),
    ("MRK", "Merck"),
    ("ABBV", "AbbVie"),
    ("LLY", "Eli Lilly"),
    ("CVX", "Chevron"),
    ("XOM", "Exxon Mobil"),
    ("COP", "ConocoPhillips"),
    ("BA", "Boeing"),
    ("CAT", "Caterpillar"),
    ("GE", "General Electric"),
    ("MMM", "3M"),
    ("HON", "Honeywell"),
    # ——— 主要 ETF ———
    ("SPY", "SPDR S&P 500 ETF"),
    ("QQQ", "Invesco QQQ Trust"),
    ("DIA", "SPDR Dow Jones ETF"),
    ("IWM", "Russell 2000 ETF"),
    ("VTI", "Vanguard Total Stock Market"),
    ("VOO", "Vanguard S&P 500"),
    ("ARKK", "ARK Innovation ETF"),
    ("BND", "Vanguard Total Bond Market"),
    ("GLD", "SPDR Gold Trust"),
    ("SLV", "iShares Silver Trust"),
    ("TQQQ", "ProShares UltraPro QQQ"),
    # ——— 中概股 ———
    ("BIDU", "Baidu"),
    ("TCOM", "Trip.com"),
    ("NTES", "NetEase"),
    ("BILI", "Bilibili"),
    ("WYNN", "Wynn Resorts"),
    ("YUMC", "Yum China"),
    ("HTHT", "H World Group"),
    ("ZTO", "ZTO Express"),
    ("DADA", "Dada Nexus"),
    ("IQ", "iQiyi"),
]


class ProviderError(RuntimeError):
    pass


class MarketDataProvider(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def get_quote(self, symbol: str) -> PriceSnapshot: ...

    def get_history(self, symbol: str, days: int = 30) -> dict: ...

    def search_intel(self, symbol: str, query: str = "") -> dict: ...

    def get_market_review(self) -> dict: ...

    def get_sectors(self) -> dict: ...

    def get_financial(self, symbol: str) -> dict: ...

    def get_market_timeline(self) -> list[dict]: ...


@dataclass
class DataCapabilityStatus:
    capability: str
    active_provider: str
    degraded: bool = False
    degraded_reason: str | None = None
    coverage: str = "cn_phase1"
    circuit_state: str = "closed"
    circuit_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "active_provider": self.active_provider,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "coverage": self.coverage,
            "circuit_state": self.circuit_state,
            "circuit_failures": self.circuit_failures,
        }


@dataclass(frozen=True)
class ProviderStatus:
    akshare_available: bool
    active_provider: str
    fallback_provider: str
    degraded: bool = False
    degraded_reason: str | None = None
    capabilities: dict[str, DataCapabilityStatus] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "akshare_available": self.akshare_available,
            "active_provider": self.active_provider,
            "fallback_provider": self.fallback_provider,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "capabilities": {
                name: status.to_dict()
                for name, status in (self.capabilities or {}).items()
            },
        }


def _bounded_days(days: int) -> int:
    return max(1, min(days, 90))



class AkShareMarketDataProvider:
    name = "akshare"

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, Any]] = {}
        self._call_lock = threading.RLock()
        self._last_call_time: float = 0.0
        self._min_call_interval: float = 0.1

    def is_available(self) -> bool:
        if (
            os.getenv("PYTEST_CURRENT_TEST")
            and os.getenv("WORKBENCH_TEST_ENABLE_AKSHARE") != "1"
        ):
            return False
        return find_spec("akshare") is not None

    def _ak(self):
        if not self.is_available():
            raise ProviderError("akshare optional dependency is not installed")
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_call_interval:
            time.sleep(self._min_call_interval - elapsed)
        self._last_call_time = time.time()
        import akshare as ak  # type: ignore[import-not-found]

        return ak

    def get_quote(self, symbol: str) -> PriceSnapshot:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        market = str(stock["market"])
        if market == "HK":
            hk_code = normalized.removeprefix("HK")
            # Layer 1: fast hot-rank API (100 stocks, always available)
            try:
                hot_frame = self._cached(
                    ("hk_hot_rank", "all"),
                    ttl_seconds=30,
                    loader=lambda: self._ak().stock_hk_hot_rank_em(),
                )
                row = _find_row(hot_frame, "代码", hk_code)
                return PriceSnapshot(
                    last=_number(row, "最新价"),
                    change_pct=_number(row, "涨跌幅"),
                    updated_at=now_iso(),
                    source=self.name,
                    degraded=False,
                    coverage={
                        "market": "HK",
                        "mode": "real",
                        "source_interface": "stock_hk_hot_rank_em",
                    },
                )
            except Exception:
                pass
            # Layer 2: full HK spot API (covers ~2500+ stocks, broader than hot_rank)
            try:
                hk_spot = self._cached(
                    ("hk_spot", "all"),
                    ttl_seconds=30,
                    loader=lambda: self._ak().stock_hk_spot_em(),
                )
                row = _find_row(hk_spot, "代码", hk_code)
                return PriceSnapshot(
                    last=_number(row, "最新价"),
                    change_pct=_number(row, "涨跌幅"),
                    updated_at=now_iso(),
                    source=self.name,
                    degraded=False,
                    coverage={
                        "market": "HK",
                        "mode": "real",
                        "source_interface": "stock_hk_spot_em",
                    },
                )
            except Exception:
                pass
            # Layer 3: Tencent HK quote (works reliably behind proxies)
            try:
                return self._fetch_hk_quote_tencent(normalized)
            except Exception:
                raise ProviderError(
                    f"HK quote not available for {normalized} "
                    f"via hot_rank, spot_em, or tencent fallback"
                )
        if market == "US":
            # Quick US quote via famous_spot_em if available
            try:
                us_frame = self._cached(
                    ("us_famous_spot", "all"),
                    ttl_seconds=120,
                    loader=lambda: self._ak().stock_us_famous_spot_em(),
                )
                row = _find_row(us_frame, "代码", normalized)
                return PriceSnapshot(
                    last=_number(row, "最新价"),
                    change_pct=_number(row, "涨跌幅"),
                    updated_at=now_iso(),
                    source=self.name,
                    degraded=False,
                    coverage={
                        "market": "US",
                        "mode": "real",
                        "source_interface": "stock_us_famous_spot_em",
                    },
                )
            except Exception:
                pass
            # Fallback: broader US spot API (covers more symbols than famous_spot)
            try:
                us_all_frame = self._cached(
                    ("us_spot_all", "all"),
                    ttl_seconds=120,
                    loader=lambda: self._ak().stock_us_spot_em(),
                )
                row = _find_row(us_all_frame, "代码", normalized)
                return PriceSnapshot(
                    last=_number(row, "最新价"),
                    change_pct=_number(row, "涨跌幅"),
                    updated_at=now_iso(),
                    source=self.name,
                    degraded=False,
                    coverage={
                        "market": "US",
                        "mode": "real",
                        "source_interface": "stock_us_spot_em",
                    },
                )
            except Exception:
                pass
            # Fallback: Tencent US quote (works reliably behind proxies)
            try:
                return self._fetch_us_quote_tencent(normalized)
            except Exception:
                pass
            # Fallback: Twelve Data (optional, requires TWELVEDATA_API_KEY env)
            try:
                return self._fetch_us_quote_twelvedata(normalized)
            except Exception:
                pass
            raise ProviderError(
                f"US quote not available for {normalized} "
                f"via famous_spot, spot_em, tencent, or twelvedata"
            )
        if market != "CN":
            raise ProviderError(f"phase1 real data only covers CN market: {normalized}")
        try:
            row = self._find_cn_quote_row(normalized)
            session = _session_from_mapping(row, volume_unit="lot")
            if not _session_has_ohlc(session):
                session = _merge_session(session, self._tencent_session_fields(normalized))
            return PriceSnapshot(
                last=_number(row, "最新价"),
                change_pct=_number(row, "涨跌幅"),
                updated_at=now_iso(),
                source=self.name,
                degraded=False,
                coverage={
                    "market": "CN",
                    "mode": "real",
                    "source_interface": "stock_zh_a_spot",
                    "session": session,
                },
            )
        except Exception:
            return self._fetch_cn_quote_tencent(normalized)

    def get_history(self, symbol: str, days: int = 30) -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        market = str(stock["market"])
        ak = self._ak()

        if market == "HK":
            hk_code = normalized.removeprefix("HK")
            with self._call_lock:
                frame = ak.stock_hk_daily(symbol=hk_code)
            rows = _frame_tail(frame, _bounded_days(days))
            items = [_history_item(row, idx + 1) for idx, row in enumerate(rows)]
            if not items:
                raise ProviderError(f"empty history for {normalized}")
            return {
                "symbol": normalized,
                "source": self.name,
                "updated_at": now_iso(),
                "degraded": False,
                "degraded_reason": None,
                "coverage": {
                    "market": "HK",
                    "mode": "real",
                    "source_interface": "stock_hk_daily",
                },
                "items": items,
            }

        if market == "US":
            try:
                with self._call_lock:
                    frame = ak.stock_us_daily(symbol=normalized)
                rows = _frame_tail(frame, _bounded_days(days))
                items = [_history_item(row, idx + 1) for idx, row in enumerate(rows)]
                source_interface = "stock_us_daily"
                degraded = False
                degraded_reason = None
            except Exception:
                items = self._fetch_us_history_twelvedata(normalized, days)
                source_interface = "twelvedata_com"
                degraded = True
                degraded_reason = (
                    "akshare stock_us_daily failed, fell back to Twelve Data"
                )
            if not items:
                raise ProviderError(f"empty history for {normalized}")
            return {
                "symbol": normalized,
                "source": self.name,
                "updated_at": now_iso(),
                "degraded": degraded,
                "degraded_reason": degraded_reason,
                "coverage": {
                    "market": "US",
                    "mode": "real",
                    "source_interface": source_interface,
                },
                "items": items,
            }

        if market != "CN":
            raise ProviderError(f"phase1 real data only covers CN market: {normalized}")
        end = datetime.now(timezone.utc).strftime("%Y%m%d")
        start = (
            datetime.now(timezone.utc)
            - timedelta(days=max(_bounded_days(days) * 2, 30))
        ).strftime("%Y%m%d")

        from backend.stock_domain.catalog import is_etf_like

        etf_like = is_etf_like(normalized, stock)
        items: list[dict] = []
        source_interface = "stock_zh_a_hist"
        # ETF/基金优先走东财基金日线，避免 stock_zh_a_hist 对 51xxxx 返回空
        if etf_like:
            try:
                items = self._fetch_cn_etf_history(ak, normalized, days, start, end)
                source_interface = "fund_etf_hist_em"
            except Exception:
                items = []

        if not items:
            try:
                with self._call_lock:
                    frame = ak.stock_zh_a_hist(
                        symbol=normalized,
                        period="daily",
                        start_date=start,
                        end_date=end,
                        adjust="",
                    )
                rows = _frame_tail(frame, _bounded_days(days))
                items = [
                    _history_item(
                        row,
                        idx + 1,
                        date_keys=("日期",),
                        open_keys=("开盘",),
                        high_keys=("最高",),
                        low_keys=("最低",),
                        close_keys=("收盘",),
                    )
                    for idx, row in enumerate(rows)
                ]
                source_interface = "stock_zh_a_hist"
            except Exception:
                fallback_symbol = (
                    f"sh{normalized}" if normalized.startswith(("5", "6")) else f"sz{normalized}"
                )
                with self._call_lock:
                    frame = ak.stock_zh_a_hist_tx(
                        symbol=fallback_symbol, start_date=start, end_date=end, adjust=""
                    )
                rows = _frame_tail(frame, _bounded_days(days))
                items = [
                    _history_item(
                        row,
                        idx + 1,
                        date_keys=("date",),
                        open_keys=("open",),
                        high_keys=("high",),
                        low_keys=("low",),
                        close_keys=("close",),
                    )
                    for idx, row in enumerate(rows)
                ]
                source_interface = "stock_zh_a_hist_tx"

        if not items and etf_like:
            try:
                items = self._fetch_cn_etf_history(ak, normalized, days, start, end)
                source_interface = "fund_etf_hist_em"
            except Exception:
                items = []

        if not items:
            raise ProviderError(f"empty history for {normalized}")
        return {
            "symbol": normalized,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "degraded_reason": None,
            "coverage": {
                "market": "CN",
                "mode": "real",
                "source_interface": source_interface,
            },
            "items": items,
        }

    def search_intel(self, symbol: str, query: str = "") -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")

        if str(stock["market"]) == "HK":
            return self._search_intel_hk(normalized, stock, query)
        if str(stock["market"]) != "CN":
            raise ProviderError(
                f"phase1 real data only covers CN/HK markets: {normalized}"
            )

        missing: list[str] = []
        profile = self._safe_intel_call("profile_cninfo", lambda: self._profile_cninfo(normalized), missing)
        top_holders = self._safe_intel_call(
            "main_holders", lambda: self._main_holders(normalized), missing, default=[]
        )
        fund_holders = self._safe_intel_call(
            "fund_holders", lambda: self._fund_holders(normalized), missing, default=[]
        )
        shareholder_changes = self._safe_intel_call(
            "shareholder_changes", lambda: self._shareholder_changes(normalized), missing, default=[]
        )
        financial = self._safe_intel_call(
            "financial_abstract", lambda: self._financial_abstract(normalized), missing, default=[]
        )
        fund_flow = self._safe_intel_call(
            "fund_flow", lambda: self._fund_flow(normalized), missing, default=[]
        )
        news = self._stock_news(normalized)
        sources = [
            "stock_profile_cninfo",
            "stock_main_stock_holder",
            "stock_fund_stock_holder",
            "stock_shareholder_change_ths",
            "stock_financial_abstract",
            "stock_individual_fund_flow",
        ]
        items = [
            {
                "type": "profile",
                "title": f"{profile.get('公司名称') or stock['name']} | {profile.get('所属行业') or profile.get('主营业务') or '基础资料'}",
                "source": self.name,
                "confidence": "high",
                "updated_at": now_iso(),
            },
            {
                "type": "major_holder",
                "title": self._holder_title(top_holders, normalized, "主要股东"),
                "source": self.name,
                "confidence": "medium",
                "published_at": _safe_iso(top_holders[0].get("公告日期"))
                if top_holders
                else None,
                "updated_at": now_iso(),
            },
            {
                "type": "fund_holder",
                "title": self._holder_title(fund_holders, normalized, "基金持仓"),
                "source": self.name,
                "confidence": "medium",
                "published_at": _safe_iso(fund_holders[0].get("截止日期"))
                if fund_holders
                else None,
                "updated_at": now_iso(),
            },
            {
                "type": "shareholder_change",
                "title": self._shareholder_change_title(
                    shareholder_changes, normalized
                ),
                "source": self.name,
                "confidence": "low",
                "published_at": _safe_iso(shareholder_changes[0].get("公告日期"))
                if shareholder_changes
                else None,
                "updated_at": now_iso(),
            },
            {
                "type": "financial",
                "title": self._financial_title(financial, normalized),
                "source": self.name,
                "confidence": "medium",
                "updated_at": now_iso(),
            },
            {
                "type": "fund_flow",
                "title": self._fund_flow_title(fund_flow, normalized),
                "source": self.name,
                "published_at": _safe_iso(fund_flow[0].get("日期"))
                if fund_flow
                else None,
                "confidence": "medium",
                "updated_at": now_iso(),
            },
        ]
        if news:
            items = news + items
            sources.insert(0, "stock_news_em")
        else:
            missing.append("stock_news_em")
        coverage = {"market": "CN", "sources": sources, "missing": missing}
        return {
            "symbol": normalized,
            "query": query,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "degraded_reason": None,
            "coverage": coverage,
            "items": [item for item in items if item["title"]],
        }

    def _search_intel_hk(self, symbol: str, stock: dict, query: str) -> dict:
        profile = self._hk_company_profile(symbol)
        fin_ind = self._hk_financial_indicator(symbol)
        items: list[dict[str, Any]] = []
        sources: list[str] = []
        if profile:
            items.append(
                {
                    "type": "profile",
                    "title": f"{profile.get('公司名称') or stock['name']} | {profile.get('所属行业') or '港股'}",
                    "source": self.name,
                    "confidence": "high",
                    "updated_at": now_iso(),
                }
            )
            sources.append("stock_hk_company_profile_em")
        else:
            items.append(
                {
                    "type": "profile",
                    "title": f"{stock['name']} | HK Stock",
                    "source": self.name,
                    "confidence": "medium",
                    "updated_at": now_iso(),
                }
            )
        if fin_ind:
            eps = fin_ind.get("基本每股收益(元)")
            roe = fin_ind.get("股东权益回报率(%)")
            pe = fin_ind.get("市盈率")
            pb = fin_ind.get("市净率")
            items.append(
                {
                    "type": "financial",
                    "title": f"EPS: {eps} | ROE: {roe}% | PE: {pe} | PB: {pb}"
                    if eps
                    else f"HK financial indicators ({symbol})",
                    "source": self.name,
                    "confidence": "medium",
                    "updated_at": now_iso(),
                }
            )
            sources.append("stock_hk_financial_indicator_em")
        return {
            "symbol": symbol,
            "query": query,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "degraded_reason": None,
            "coverage": {
                "market": "HK",
                "sources": sources,
                "missing": [
                    "main_holders",
                    "fund_holders",
                    "shareholder_changes",
                    "fund_flow",
                    "news",
                ],
            },
            "items": items,
        }

    def get_market_timeline(self) -> list[dict]:
        """Build market timeline from trade calendar and current index data."""
        today = datetime.now(timezone(timedelta(hours=8)))
        today_str = today.strftime("%Y-%m-%d")
        
        try:
            cal = self._ak().tool_market_trade_date_tc()
            trade_row = cal[cal["trade_date"] == today_str]
            is_trading = len(trade_row) > 0 and bool(trade_row.iloc[0]["is_trading"])
        except Exception:
            is_trading = today.weekday() < 5

        timeline: list[dict] = [
            {
                "date": today_str,
                "type": "trading_day" if is_trading else "non_trading_day",
                "status": "open" if is_trading and 9 <= today.hour < 15 else "closed",
                "title": "A股交易状态",
                "description": "交易日" if is_trading else "非交易日",
                "market": "CN",
            },
        ]

        try:
            indices = self._market_indices()
            for idx in indices[:3]:
                timeline.append(
                    {
                        "date": today_str,
                        "type": "index_performance",
                        "title": str(idx.get("name", idx.get("指数名称", ""))),
                        "market": "CN",
                        "value": float(idx.get("current", idx.get("最新价", 0))),
                        "change_pct": float(
                            idx.get("change_pct", idx.get("涨跌幅", 0))
                        ),
                    }
                )
        except Exception:
            pass

        return timeline

    def get_financial(self, symbol: str) -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        market = str(stock["market"])
        if market == "HK":
            fin_ind = self._hk_financial_indicator(normalized)
            if not fin_ind:
                raise ProviderError(f"empty HK financial indicators for {normalized}")
            revenue = _safe_float(fin_ind.get("营业总收入")) or _safe_float(fin_ind.get("营业收入")) or 0.0
            profit = _safe_float(fin_ind.get("净利润")) or _safe_float(fin_ind.get("归属于母公司股东的净利润")) or 0.0
            total_assets = _safe_float(fin_ind.get("总资产")) or _safe_float(fin_ind.get("资产总计")) or 0.0
            total_liabilities = _safe_float(fin_ind.get("总负债")) or _safe_float(fin_ind.get("负债合计")) or 0.0
            return {
                "symbol": normalized,
                "source": self.name,
                "updated_at": now_iso(),
                "degraded": False,
                "degraded_reason": None,
                "coverage": {
                    "market": "HK",
                    "mode": "real",
                    "source_interface": "stock_hk_financial_indicator_em",
                },
                "items": [{
                    "report_date": str(fin_ind.get("报告期") or now_iso()[:10])[:10],
                    "report_type": "annual",
                    "revenue": revenue or 0.0,
                    "profit": profit or 0.0,
                    "total_assets": total_assets or 0.0,
                    "total_liabilities": total_liabilities or 0.0,
                }],
            }
        if market != "CN":
            raise ProviderError(
                f"akshare financial data only covers CN/HK markets: {normalized}"
            )
        rows = self._financial_abstract(normalized)
        items = _build_financial_items(rows)
        if not items:
            raise ProviderError(f"empty financial data for {normalized}")
        return {
            "symbol": normalized,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "degraded_reason": None,
            "coverage": {
                "market": "CN",
                "mode": "real",
                "source_interface": "stock_financial_abstract",
            },
            "items": items,
        }

    def get_market_review(self) -> dict:
        indices = self._market_indices()
        breadth = self._market_breadth()
        total_turnover = round(
            sum(float(item.get("成交额") or 0.0) for item in breadth), 2
        )
        rising = sum(1 for item in breadth if float(item.get("涨跌幅") or 0.0) > 0)
        falling = sum(1 for item in breadth if float(item.get("涨跌幅") or 0.0) < 0)
        flat = max(len(breadth) - rising - falling, 0)
        lead = indices[0] if indices else {}
        summary = self._market_summary_text(lead, rising, falling, flat)
        return {
            "status": self._market_status(lead, rising, falling),
            "summary": summary,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "degraded_reason": None,
            "coverage": {
                "market": "CN",
                "sources": ["stock_zh_index_spot_sina", "stock_zh_a_spot"],
                "missing": [],
            },
            "indices": indices,
            "breadth": {
                "rising_count": rising,
                "falling_count": falling,
                "flat_count": flat,
                "sample_size": len(breadth),
            },
            "turnover": {"a_share_total": total_turnover},
        }

    def get_sectors(self) -> dict:
        mapping = self._industry_name_map()
        summary_rows = self._industry_summary_rows()
        items: list[dict[str, Any]] = []
        for row in summary_rows[:12]:
            sector_name = str(row.get("板块") or "").strip()
            if not sector_name:
                continue
            code = mapping.get(sector_name)
            leader = str(row.get("领涨股") or "").strip()
            items.append(
                {
                    "sector": sector_name,
                    "code": code,
                    "signal": self._sector_signal(row),
                    "change_pct": _coerce_float(row.get("涨跌幅")),
                    "net_inflow": _coerce_float(row.get("净流入")),
                    "symbols": [leader] if leader else [],
                    "leader_stock": leader or None,
                    "leader_change_pct": _coerce_float(row.get("领涨股-涨跌幅")),
                }
            )
        if not items:
            raise ProviderError("empty sectors snapshot")
        return {
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "degraded_reason": None,
            "coverage": {
                "market": "CN",
                "dimension": "industry",
                "sources": [
                    "stock_board_industry_name_ths",
                    "stock_board_industry_summary_ths",
                ],
                "missing": ["industry_constituents_best_effort"],
            },
            "items": items,
        }

    def capability_status(self, capability: str) -> DataCapabilityStatus:
        return DataCapabilityStatus(
            capability=capability,
            active_provider=self.name,
            degraded=not self.is_available(),
            degraded_reason=None
            if self.is_available()
            else f"{self.name} optional dependency is not installed",
        )

    def _market_indices(self) -> list[dict[str, Any]]:
        frame = self._cached(
            ("market_indices", "cn"),
            ttl_seconds=300,
            loader=lambda: self._ak().stock_zh_index_spot_sina(),
        )
        rows = _frame_tail(frame, 1000)
        picks = {"sh000001", "sz399001", "sz399006"}
        items = []
        for row in rows:
            code = str(row.get("代码") or "").lower()
            if code not in picks:
                continue
            items.append(
                {
                    "code": code,
                    "name": row.get("名称"),
                    "last": _coerce_float(row.get("最新价")),
                    "change_pct": _coerce_float(row.get("涨跌幅")),
                    "turnover": _coerce_float(row.get("成交额")),
                }
            )
        if not items:
            raise ProviderError("empty CN index snapshot")
        return items

    def _market_breadth(self) -> list[dict[str, Any]]:
        frame = self._cached(
            ("cn_spot", "all"), ttl_seconds=300, loader=self._load_cn_spot
        )
        rows = _frame_tail(frame, 6000)
        filtered = [
            row
            for row in rows
            if str(row.get("代码") or "").startswith(("sh", "sz", "bj"))
        ]
        if not filtered:
            raise ProviderError("empty CN spot snapshot")
        return filtered

    def _industry_name_map(self) -> dict[str, str]:
        frame = self._cached(
            ("industry_name_ths", "cn"),
            ttl_seconds=300,
            loader=lambda: self._ak().stock_board_industry_name_ths(),
        )
        rows = _frame_tail(frame, 500)
        return {
            str(row.get("name") or "").strip(): str(row.get("code") or "").strip()
            for row in rows
            if row.get("name")
        }

    def _industry_summary_rows(self) -> list[dict[str, Any]]:
        frame = self._cached(
            ("industry_summary_ths", "cn"),
            ttl_seconds=120,
            loader=lambda: self._ak().stock_board_industry_summary_ths(),
        )
        rows = _frame_tail(frame, 500)
        if not rows:
            raise ProviderError("empty industry summary snapshot")
        rows.sort(key=lambda row: abs(_coerce_float(row.get("涨跌幅"))), reverse=True)
        return rows

    def _safe_intel_call(
        self,
        label: str,
        loader,
        missing: list[str],
        *,
        default: dict | list | None = None,
    ) -> dict | list:
        try:
            return loader()
        except Exception:
            missing.append(label)
            if default is not None:
                return default
            return {} if label == "profile_cninfo" else []

    def fetch_profile_metadata(self, symbol: str) -> dict[str, Any]:
        """从巨潮 profile 提取行业/板块/别名，供 stock_master enrichment。"""
        normalized = normalize_symbol(symbol)
        try:
            profile = self._profile_cninfo(normalized)
        except Exception:
            return {}
        if not profile:
            return {}
        industry = str(profile.get("所属行业") or "").strip()
        main_biz = str(profile.get("主营业务") or "").strip()
        sector = main_biz.split("。")[0].split("；")[0][:64] if main_biz else industry
        aliases: list[str] = []
        for key in ("英文名称", "曾用简称", "A股简称"):
            raw = str(profile.get(key) or "").strip()
            if raw and raw not in aliases:
                aliases.append(raw)
        website = str(profile.get("官方网站") or "").strip()
        if website:
            host = website.replace("https://", "").replace("http://", "").split("/")[0]
            if host.startswith("www."):
                host = host[4:]
            token = host.split(".")[0]
            if token and token not in aliases:
                aliases.append(token)
        return {
            "industry": industry,
            "sector": sector or industry,
            "aliases": aliases,
            "company_name": str(profile.get("公司名称") or "").strip(),
        }

    def _profile_cninfo(self, symbol: str) -> dict[str, Any]:
        frame = self._cached(
            ("profile_cninfo", symbol),
            ttl_seconds=86400,
            loader=lambda: self._ak().stock_profile_cninfo(symbol=symbol),
        )
        rows = _frame_tail(frame, 5)
        return rows[0] if rows else {}

    def _main_holders(self, symbol: str) -> list[dict[str, Any]]:
        frame = self._cached(
            ("main_holders", symbol),
            ttl_seconds=3600,
            loader=lambda: self._ak().stock_main_stock_holder(stock=symbol),
        )
        return _frame_tail(frame, 5)

    def _fund_holders(self, symbol: str) -> list[dict[str, Any]]:
        frame = self._cached(
            ("fund_holders", symbol),
            ttl_seconds=3600,
            loader=lambda: self._ak().stock_fund_stock_holder(symbol=symbol),
        )
        return _frame_tail(frame, 5)

    def _shareholder_changes(self, symbol: str) -> list[dict[str, Any]]:
        frame = self._cached(
            ("shareholder_changes", symbol),
            ttl_seconds=86400,
            loader=lambda: self._ak().stock_shareholder_change_ths(symbol=symbol),
        )
        return _frame_tail(frame, 5)

    def _financial_abstract(self, symbol: str) -> list[dict[str, Any]]:
        frame = self._cached(
            ("financial_abstract", symbol),
            ttl_seconds=86400,
            loader=lambda: self._ak().stock_financial_abstract(symbol=symbol),
        )
        return _frame_tail(frame, 80)  # Need most rows for complete financial data

    def _fund_flow(self, symbol: str) -> list[dict[str, Any]]:
        return self.fetch_fund_flow_rows(symbol, limit=5)

    def fetch_fund_flow_rows(self, symbol: str, limit: int = 12) -> list[dict[str, Any]]:
        market = "sh" if symbol.startswith("6") else "sz"
        frame = self._cached(
            ("fund_flow", symbol),
            ttl_seconds=600,
            loader=lambda: self._ak().stock_individual_fund_flow(
                stock=symbol, market=market
            ),
        )
        rows = _frame_records(frame)
        return rows

    def fetch_chip_cyq(self, symbol: str) -> list[dict[str, Any]]:
        frame = self._cached(
            ("chip_cyq", symbol),
            ttl_seconds=86400,
            loader=lambda: self._ak().stock_cyq_em(symbol=symbol),
        )
        return _frame_records(frame)

    def fetch_session_quote(self, symbol: str) -> dict[str, Any]:
        """Live OHLC/liquidity/valuation already present on the quote row.

        ``stock_individual_info_em`` is a separate, easier-to-drop call. Callers
        should use this first and only ask that endpoint for fields still missing.
        """
        if not self.is_available():
            return {}
        normalized = normalize_symbol(symbol)
        session: dict[str, Any] = {}
        try:
            session = _session_from_mapping(self._find_cn_quote_row(normalized), volume_unit="lot")
        except Exception:
            session = {}
        if not _session_has_ohlc(session) or _session_missing_valuation(session):
            try:
                session = _merge_session(session, self._tencent_session_fields(normalized))
            except Exception:
                pass
        if session.get("last") is None and not _session_has_ohlc(session):
            return {}
        session["as_of"] = datetime.now().strftime("%Y-%m-%d")
        return session

    def _tencent_session_fields(self, symbol: str) -> dict[str, Any]:
        raw = self._tencent_quote_raw(symbol)
        fields = _parse_tencent_fields(raw)
        return _session_from_tencent(fields)

    def _tencent_quote_raw(self, symbol: str) -> str:
        import requests as _req

        if symbol.startswith(("5", "6", "688", "11")):
            tencent_sym = f"sh{symbol}"
        elif symbol.startswith(("0", "1", "3")):
            tencent_sym = f"sz{symbol}"
        else:
            tencent_sym = symbol
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            ),
        }
        resp = _req.get(
            f"https://qt.gtimg.cn/q={tencent_sym}",
            headers=headers,
            timeout=15,
        )
        raw = resp.content.decode("gbk", errors="replace").strip()
        if "=" not in raw:
            raise ProviderError(f"Tencent API unexpected response for {symbol}")
        return raw.split("=", 1)[1].strip().strip('" \n\r')

    def fetch_spot_snapshot(self, symbol: str) -> dict[str, Any]:
        frame = self._cached(
            ("spot_info_em", symbol),
            ttl_seconds=60,
            loader=lambda: self._ak().stock_individual_info_em(symbol=symbol),
        )
        mapping: dict[str, Any] = {}
        for row in _frame_tail(frame, 80):
            key = str(row.get("item") or row.get("指标") or row.get("item_name") or "").strip()
            if not key:
                continue
            mapping[key] = row.get("value") if "value" in row else row.get("值")
        if not mapping:
            return {}
        return {
            "last": _safe_float(mapping.get("最新") or mapping.get("最新价")),
            "turnover_pct": _safe_float(mapping.get("换手率")),
            "amplitude_pct": _safe_float(mapping.get("振幅")),
            "volume_ratio": _safe_float(mapping.get("量比")),
            "pe": _safe_float(mapping.get("市盈率") or mapping.get("市盈率-动态") or mapping.get("市盈率(动)")),
            "pb": _safe_float(mapping.get("市净率")),
            "total_market_cap": _safe_float(mapping.get("总市值")),
            "float_market_cap": _safe_float(mapping.get("流通市值")),
            "industry": str(mapping.get("行业") or "").strip() or None,
        }

    def fetch_hk_spot_snapshot(self, symbol: str) -> dict[str, Any]:
        fin = self._hk_financial_indicator(symbol)
        if not fin:
            return {}
        return {
            "last": _safe_float(fin.get("最新价") or fin.get("收盘价")),
            "pe": _safe_float(fin.get("市盈率")),
            "pb": _safe_float(fin.get("市净率")),
            "turnover_pct": _safe_float(fin.get("换手率")),
            "total_market_cap": _safe_float(fin.get("总市值") or fin.get("市值")),
            "float_market_cap": None,
            "amplitude_pct": None,
            "volume_ratio": None,
            "industry": str(fin.get("所属行业") or "").strip() or None,
        }

    def _stock_news(self, symbol: str) -> list[dict[str, Any]]:
        try:
            frame = self._cached(
                ("news_em", symbol),
                ttl_seconds=600,
                loader=lambda: self._ak().stock_news_em(symbol=symbol),
            )
            rows = _frame_tail(frame, 10)
            return [
                {
                    "type": "news",
                    "title": str(row.get("新闻标题", "")),
                    "source": str(row.get("文章来源", "东方财富")),
                    "confidence": "medium",
                    "published_at": str(row.get("发布时间", "")),
                    "url": str(row.get("新闻链接", "")),
                    "updated_at": now_iso(),
                }
                for row in rows
                if row.get("新闻标题")
            ]
        except Exception:
            return []

    def import_a_share_master(self) -> list[dict[str, Any]]:
        """Fetch all A-share stock codes/names from AKShare and return as list."""
        try:
            frame = self._ak().stock_info_a_code_name()
            rows = _frame_tail(frame, 10000)
            items: list[dict[str, Any]] = []
            for row in rows:
                code = str(row.get("code", ""))
                name = str(row.get("name", ""))
                if not code or not name:
                    continue
                if code.startswith(("6", "688")) or (
                    code.startswith(("0", "3")) and not code.startswith("8")
                ):
                    market = "CN"
                elif code.startswith(("4", "8")):
                    market = "CN"
                else:
                    continue
                items.append({"symbol": code, "name": name, "market": market})
            return items
        except Exception:
            return []

    def fetch_industry_boards(self) -> list[dict[str, Any]]:
        """东财行业板块列表 + 快照（约 86 个行业）。

        列名以 akshare stock_board_industry_em.py 源码为准；未在源码确认的
        列一律不取。
        """
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                frame = self._ak().stock_board_industry_name_em()
                rows = _frame_tail(frame, 500)
                items: list[dict[str, Any]] = []
                for row in rows:
                    name = str(row.get("板块名称") or "")
                    if not name:
                        continue
                    items.append({
                        "industry": name,
                        "board_code": str(row.get("板块代码") or ""),
                        "rank": _safe_float(row.get("排名")),
                        "change_pct": _safe_float(row.get("涨跌幅")),
                        "turnover_pct": _safe_float(row.get("换手率")),
                        "total_market_cap": _safe_float(row.get("总市值")),
                    })
                if items:
                    return items
            except Exception as exc:
                last_err = exc
                time.sleep(0.4 * (attempt + 1))
        if last_err is not None:
            _log.warning("fetch_industry_boards failed: %s", last_err)
        return []

    def fetch_industry_constituents(self, industry: str) -> list[dict[str, Any]]:
        """东财行业板块成分股（含最新价/涨跌幅/换手率/PE/PB）。

        cons_em 没有市值列：用 成交额/(换手率/100) 推算流通市值（cap_est），
        仅用于行业内排序，消费方须标注推算口径。
        """
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                frame = self._ak().stock_board_industry_cons_em(symbol=industry)
                rows = _frame_tail(frame, 2000)
                items: list[dict[str, Any]] = []
                for row in rows:
                    code = str(row.get("代码") or "")
                    if not code:
                        continue
                    turnover_amount = _safe_float(row.get("成交额"))
                    turnover_pct = _safe_float(row.get("换手率"))
                    cap_est = (
                        turnover_amount / (turnover_pct / 100)
                        if turnover_amount and turnover_pct
                        else None
                    )
                    items.append({
                        "symbol": code,
                        "name": str(row.get("名称") or ""),
                        "price": _safe_float(row.get("最新价")),
                        "change_pct": _safe_float(row.get("涨跌幅")),
                        "turnover_pct": turnover_pct,
                        "pe": _safe_float(row.get("市盈率-动态")),
                        "pb": _safe_float(row.get("市净率")),
                        "cap_est": cap_est,
                    })
                if items:
                    return items
            except Exception as exc:
                last_err = exc
                time.sleep(0.4 * (attempt + 1))
        if last_err is not None:
            _log.warning("fetch_industry_constituents(%s) failed: %s", industry, last_err)
        return []

    def import_hk_stock_master(self) -> list[dict[str, Any]]:
        """Fetch HK stock codes/names and return as list.

        Primary source: AKShare stock_hk_hot_rank_em (live hot stocks).
        Fallback: built-in list of major HK stocks (Stock Connect + indices).
        """
        items: list[dict[str, Any]] = []
        try:
            frame = self._ak().stock_hk_hot_rank_em()
            for _, row in frame.iterrows():
                code = str(row.get("代码", "")).strip()
                name = str(row.get("股票名称", "")).strip()
                if code and name:
                    items.append({"symbol": f"HK{code}", "name": name, "market": "HK"})
        except Exception:
            pass

        seen = {i["symbol"] for i in items}
        for code, name in _HK_STOCKS_FALLBACK:
            sym = f"HK{code}"
            if sym not in seen:
                items.append({"symbol": sym, "name": name, "market": "HK"})
                seen.add(sym)

        return items

    def import_us_stock_master(self) -> list[dict[str, Any]]:
        """Fetch US stock codes/names and return as list.

        Primary source: AKShare stock_us_famous_spot_em (live hot stocks) if available.
        Fallback: built-in list of major US stocks (S&P 500 / Nasdaq).
        """
        items: list[dict[str, Any]] = []
        try:
            frame = self._ak().stock_us_famous_spot_em()
            for _, row in frame.iterrows():
                code = str(row.get("代码", "")).strip()
                name = str(row.get("股票名称", "")).strip()
                if code and name:
                    items.append({"symbol": code, "name": name, "market": "US"})
        except Exception:
            pass
        seen = {i["symbol"] for i in items}
        for code, name in _US_STOCKS_FALLBACK:
            if code not in seen:
                items.append({"symbol": code, "name": name, "market": "US"})
                seen.add(code)
        return items

    def _hk_company_profile(self, symbol: str) -> dict[str, Any]:
        hk_code = symbol.removeprefix("HK")
        try:
            frame = self._cached(
                ("hk_profile", symbol),
                ttl_seconds=86400,
                loader=lambda: self._ak().stock_hk_company_profile_em(symbol=hk_code),
            )
            rows = _frame_tail(frame, 1)
            return rows[0] if rows else {}
        except Exception:
            return {}

    def _hk_financial_indicator(self, symbol: str) -> dict[str, Any]:
        hk_code = symbol.removeprefix("HK")
        try:
            frame = self._cached(
                ("hk_fin_indicator", symbol),
                ttl_seconds=86400,
                loader=lambda: self._ak().stock_hk_financial_indicator_em(
                    symbol=hk_code
                ),
            )
            rows = _frame_tail(frame, 1)
            return rows[0] if rows else {}
        except Exception:
            return {}

    def _fetch_cn_spot_http(self) -> Any:
        """Fetch CN spot data via direct HTTP to East Money push2 API.

        Fallback when akshare's stock_zh_a_spot() fails (e.g. behind a
        system proxy that blocks the Sina endpoint).  Returns a DataFrame
        whose column names and SH/SZ code prefixes match the akshare
        layout so callers such as ``_find_row`` and ``_market_breadth``
        work unchanged.
        """
        import pandas as pd
        import requests as _req
        import time as _time

        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1,
            "pz": 10000,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23",
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://quote.eastmoney.com/",
        }

        max_attempts = 3
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                session = _req.Session()
                session.trust_env = False
                session.proxies = {"http": "", "https": ""}
                resp = session.get(url, params=params, headers=headers, timeout=15)
                resp.raise_for_status()
                payload = resp.json()
                items = (payload.get("data") or {}).get("diff") or []
                rows = []
                for item in items:
                    raw_code = str(item.get("f12") or "")
                    if not raw_code:
                        continue
                    if raw_code.startswith(("6", "688")):
                        code = f"sh{raw_code}"
                    elif raw_code.startswith(("0", "3")):
                        code = f"sz{raw_code}"
                    elif raw_code.startswith(("4", "8")):
                        code = f"bj{raw_code}"
                    else:
                        code = raw_code
                    rows.append(
                        {
                            "代码": code,
                            "名称": str(item.get("f14") or ""),
                            "最新价": item.get("f2"),
                            "涨跌额": item.get("f4"),
                            "涨跌幅": item.get("f3"),
                            "成交量": item.get("f5"),
                            "成交额": item.get("f6"),
                            "今开": item.get("f17"),
                            "最高": item.get("f15"),
                            "最低": item.get("f16"),
                            "昨收": item.get("f18"),
                            "换手率": item.get("f8"),
                            "振幅": item.get("f7"),
                            "量比": item.get("f10"),
                            "市盈率-动态": item.get("f9"),
                            "市净率": item.get("f23"),
                            "总市值": item.get("f20"),
                            "流通市值": item.get("f21"),
                        }
                    )
                if not rows:
                    raise ProviderError(
                        "empty CN spot snapshot from East Money fallback"
                    )
                return pd.DataFrame(rows)
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts:
                    _time.sleep(attempt * 1.5)  # 1.5s, 3.0s backoff
        raise ProviderError(
            f"East Money HTTP fallback failed after {max_attempts} attempts: {last_exc}"
        ) from last_exc

    def _fetch_cn_etf_history(
        self,
        ak: Any,
        symbol: str,
        days: int,
        start: str,
        end: str,
    ) -> list[dict]:
        """东财 ETF 日线；A 股 51xxxx/15xxxx 等走股票 hist 常为空。"""
        start_dash = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        end_dash = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
        with self._call_lock:
            frame = None
            last_err: Exception | None = None
            for loader in (
                lambda: ak.fund_etf_hist_em(
                    symbol=symbol, period="daily", start_date=start_dash, end_date=end_dash, adjust=""
                ),
                lambda: ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust=""),
            ):
                try:
                    frame = loader()
                    break
                except Exception as exc:  # noqa: BLE001 — try next API variant
                    last_err = exc
                    frame = None
            if frame is None:
                raise ProviderError(f"fund_etf_hist_em failed for {symbol}: {last_err}")
        rows = _frame_tail(frame, _bounded_days(days))
        items = [
            _history_item(
                row,
                idx + 1,
                date_keys=("日期", "date", "trade_date"),
                open_keys=("开盘", "open"),
                high_keys=("最高", "high"),
                low_keys=("最低", "low"),
                close_keys=("收盘", "close"),
                volume_keys=("成交量", "volume", "vol"),
                amount_keys=("成交额", "amount"),
            )
            for idx, row in enumerate(rows)
        ]
        if not items:
            raise ProviderError(f"empty ETF history for {symbol}")
        return items

    def _fetch_cn_quote_tencent(self, symbol: str) -> PriceSnapshot:
        """Fetch single CN stock quote from Tencent Finance API.

        Tencent's qt.gtimg.cn endpoint does minimal TLS fingerprinting
        and works reliably even when Sina / East Money are blocked by
        a local proxy or anti-scraping rules.
        """
        import requests as _req

        if symbol.startswith(("5", "6", "688", "11")):
            tencent_sym = f"sh{symbol}"
        elif symbol.startswith(("0", "1", "3")):
            tencent_sym = f"sz{symbol}"
        else:
            tencent_sym = symbol

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            ),
        }
        resp = _req.get(
            f"https://qt.gtimg.cn/q={tencent_sym}",
            headers=headers,
            timeout=15,
        )
        raw = resp.content.decode("gbk", errors="replace").strip()
        if "=" not in raw:
            raise ProviderError(f"Tencent API unexpected response for {symbol}")
        value = raw.split("=", 1)[1].strip().strip('" \n\r')
        fields = value.split("~")
        if len(fields) < 5:
            raise ProviderError(
                f"Tencent API insufficient fields for {symbol}: {len(fields)}"
            )
        try:
            last = float(fields[3])
            prev_close = float(fields[4])
            change_pct = (
                round((last - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            )
        except (ValueError, IndexError) as e:
            raise ProviderError(f"Tencent API parse error for {symbol}: {e}") from e

        return PriceSnapshot(
            last=last,
            change_pct=change_pct,
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": "CN",
                "mode": "real",
                "source_interface": "tencent_qt",
                "session": _session_from_tencent(fields),
            },
        )

    def _fetch_hk_quote_tencent(self, symbol: str) -> PriceSnapshot:
        """Fetch HK stock quote from Tencent Finance API (qt.gtimg.cn).

        Tencent supports HK stocks with the 'hk' prefix, e.g. hk00700.
        """
        import requests as _req

        hk_code = symbol.removeprefix("HK")
        tencent_sym = f"hk{hk_code}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            ),
        }
        resp = _req.get(
            f"https://qt.gtimg.cn/q={tencent_sym}",
            headers=headers,
            timeout=15,
        )
        raw = resp.content.decode("gbk", errors="replace").strip()
        if "=" not in raw:
            raise ProviderError(f"Tencent HK API unexpected response for {symbol}")
        value = raw.split("=", 1)[1].strip().strip('" \n\r')
        fields = value.split("~")
        if len(fields) < 5:
            raise ProviderError(
                f"Tencent HK API insufficient fields for {symbol}: {len(fields)}"
            )
        try:
            last = float(fields[3])
            prev_close = float(fields[4])
            change_pct = (
                round((last - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            )
        except (ValueError, IndexError) as e:
            raise ProviderError(f"Tencent HK API parse error for {symbol}: {e}") from e

        return PriceSnapshot(
            last=last,
            change_pct=change_pct,
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": "HK",
                "mode": "real",
                "source_interface": "tencent_qt_hk",
            },
        )

    def _fetch_us_quote_tencent(self, symbol: str) -> PriceSnapshot:
        """Fetch US stock quote from Tencent Finance API (qt.gtimg.cn).

        Tencent supports US stocks with the 'us' prefix, e.g. usAAPL.
        Field layout (tilde-separated): index 3 = last price, 4 = prev close.
        """
        import requests as _req

        us_code = symbol.removeprefix("US")
        tencent_sym = f"us{us_code}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            ),
        }
        resp = _req.get(
            f"https://qt.gtimg.cn/q={tencent_sym}",
            headers=headers,
            timeout=15,
        )
        raw = resp.content.decode("gbk", errors="replace").strip()
        if "=" not in raw:
            raise ProviderError(f"Tencent US API unexpected response for {symbol}")
        value = raw.split("=", 1)[1].strip().strip('" \n\r')
        fields = value.split("~")
        if len(fields) < 5:
            raise ProviderError(
                f"Tencent US API insufficient fields for {symbol}: {len(fields)}"
            )
        try:
            last = float(fields[3])
            prev_close = float(fields[4])
            change_pct = (
                round((last - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            )
        except (ValueError, IndexError) as e:
            raise ProviderError(f"Tencent US API parse error for {symbol}: {e}") from e

        return PriceSnapshot(
            last=last,
            change_pct=change_pct,
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": "US",
                "mode": "real",
                "source_interface": "tencent_qt_us",
            },
        )

    def _fetch_us_quote_twelvedata(self, symbol: str) -> PriceSnapshot:
        api_key = os.getenv("TWELVEDATA_API_KEY")
        if not api_key:
            raise ProviderError("TWELVEDATA_API_KEY not set, skipping")
        import httpx

        us_code = symbol.removeprefix("US.").removeprefix("US")
        transport = httpx.HTTPTransport(proxy=None)
        with httpx.Client(transport=transport) as client:
            resp = client.get(
                "https://api.twelvedata.com/quote",
                params={
                    "symbol": us_code,
                    "apikey": api_key,
                },
                timeout=15,
            )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "error" or not data.get("close"):
            raise ProviderError(
                f"Twelve Data API error for {symbol}: {data.get('message') or data.get('status')}"
            )
        close_today = float(data["close"])
        prev_close = data.get("previous_close")
        if prev_close:
            change_pct = round(
                (close_today - float(prev_close)) / float(prev_close) * 100, 2
            )
        else:
            change_pct = 0.0
        return PriceSnapshot(
            last=close_today,
            change_pct=change_pct,
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": "US",
                "mode": "real",
                "source_interface": "twelvedata_com",
            },
        )

    def _fetch_us_history_twelvedata(self, symbol: str, days: int = 30) -> list[dict]:
        """Fallback US history via Twelve Data time_series API."""
        api_key = os.getenv("TWELVEDATA_API_KEY")
        if not api_key:
            raise ProviderError("TWELVEDATA_API_KEY not set, skipping")
        import httpx

        us_code = symbol.removeprefix("US.").removeprefix("US")
        transport = httpx.HTTPTransport(proxy=None)
        with httpx.Client(transport=transport) as client:
            resp = client.get(
                "https://api.twelvedata.com/time_series",
                params={
                    "symbol": us_code,
                    "interval": "1day",
                    "outputsize": _bounded_days(days),
                    "apikey": api_key,
                },
                timeout=15,
            )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "error" or "values" not in data:
            raise ProviderError(
                f"Twelve Data time_series error for {symbol}: {data.get('message') or data.get('status')}"
            )
        items = []
        for idx, day in enumerate(data["values"]):
            items.append(
                {
                    "day": idx + 1,
                    "date": day.get("datetime", "")[:10],
                    "open": _coerce_float(day.get("open", 0)),
                    "high": _coerce_float(day.get("high", 0)),
                    "low": _coerce_float(day.get("low", 0)),
                    "close": _coerce_float(day.get("close", 0)),
                    "volume": _coerce_float(day.get("volume", 0)),
                }
            )
        if not items:
            raise ProviderError(f"Twelve Data empty history for {symbol}")
        return items

    def _load_cn_spot(self):
        try:
            return self._ak().stock_zh_a_spot()
        except Exception:
            return self._fetch_cn_spot_http()

    def _find_cn_quote_row(self, symbol: str) -> dict[str, Any]:
        frame = self._cached(
            ("cn_spot", "all"), ttl_seconds=60, loader=self._load_cn_spot
        )
        row = _find_row(
            frame,
            "代码",
            f"sh{symbol}"
            if symbol.startswith("6")
            else f"sz{symbol}"
            if symbol.startswith(("0", "3"))
            else symbol,
        )
        return row

    def _holder_title(
        self, rows: list[dict[str, Any]], symbol: str, fallback: str
    ) -> str:
        if not rows:
            return f"{symbol} 暂无可用的 {fallback} 数据"
        row = rows[0]
        holder_name = row.get("股东名称") or row.get("基金名称") or fallback
        ratio = row.get("持股比例") or row.get("占流通股比例")
        return f"{fallback}：{holder_name}，占比 {ratio if ratio not in (None, '') else '未披露'}"

    def _shareholder_change_title(self, rows: list[dict[str, Any]], symbol: str) -> str:
        if not rows:
            return f"{symbol} 暂无近期股东变动信息"
        row = rows[0]
        return f"股东变动：{row.get('变动股东') or symbol} {row.get('变动数量') or '未披露'}"

    def _financial_title(self, rows: list[dict[str, Any]], symbol: str) -> str:
        if not rows:
            return f"{symbol} 暂无财务摘要"
        latest = rows[0]
        report_key = next(
            (key for key in latest if key.isdigit() and len(key) == 8), None
        )
        revenue = latest.get(report_key) if report_key else None
        metric = latest.get("指标") or "财务摘要"
        return f"{metric}：{report_key or 'latest'} {revenue if revenue not in (None, '') else '可用'}"

    def _fund_flow_title(self, rows: list[dict[str, Any]], symbol: str) -> str:
        if not rows:
            return f"{symbol} 暂无资金流向摘要"
        row = rows[0]
        return f"主力净流入：{row.get('主力净流入-净额')}，占比 {row.get('主力净流入-净占比')}%"

    def _market_status(self, lead: dict[str, Any], rising: int, falling: int) -> str:
        lead_change = _coerce_float(lead.get("change_pct"))
        if rising > falling and lead_change >= 0:
            return "上涨居多"
        if falling > rising and lead_change < 0:
            return "下跌居多"
        return "结构分化"

    def _market_summary_text(
        self, lead: dict[str, Any], rising: int, falling: int, flat: int
    ) -> str:
        return (
            f"{lead.get('name', '主要指数')} {lead.get('change_pct', 0):.2f}% ，"
            f"上涨 {rising} 家，下跌 {falling} 家，平盘 {flat} 家；"
            "market/review 已切换到 AKShare A 股真实数据聚合。"
        )

    def _sector_signal(self, row: dict[str, Any]) -> str:
        change_pct = _coerce_float(row.get("涨跌幅"))
        if change_pct >= 2:
            return "强势拉升"
        if change_pct <= -2:
            return "明显走弱"
        return "震荡分化"

    def _cached(self, key: tuple[str, str], *, ttl_seconds: int, loader) -> Any:
        now = time.time()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        with self._call_lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.time():
                return cached[1]
            value = loader()
        self._cache[key] = (now + ttl_seconds, value)
        return value

    _REFRESH_TTL = 86400

    def start_background_refresh(
        self,
        interval_seconds: int = 300,
        interval_getter=None,
    ) -> None:
        """Start a daemon thread that periodically warms expensive API caches.

        ``interval_getter`` is read each cycle so a settings change applies on
        the next sleep without restarting the thread.
        """
        thread = threading.Thread(
            target=self._refresh_loop,
            args=(interval_seconds, interval_getter),
            daemon=True,
        )
        thread.start()

    def _refresh_loop(self, interval: int, interval_getter=None) -> None:
        self._warmup()
        while True:
            sleep_for = interval
            if interval_getter is not None:
                try:
                    sleep_for = int(interval_getter())
                except Exception:
                    sleep_for = interval
            time.sleep(max(30, sleep_for))
            self._warmup()

    def _warmup(self) -> None:
        """Pre-populate ``_cache`` with fresh data for every expensive API.

        Each entry gets a 24-hour TTL so ``_cached()`` never treats it as
        expired during normal use.  The caller (``_refresh_loop``) is
        responsible for calling this method periodically.
        """
        if not self.is_available():
            return
        now = time.time()
        ak = self._ak()
        warmups: list[tuple[str, tuple[str, str], Any]] = [
            ("cn_spot", ("cn_spot", "all"), lambda: self._load_cn_spot()),
            ("hk_spot", ("hk_spot", "all"), lambda: ak.stock_hk_spot()),
            (
                "market_indices",
                ("market_indices", "cn"),
                lambda: ak.stock_zh_index_spot_sina(),
            ),
            (
                "industry_name_ths",
                ("industry_name_ths", "cn"),
                lambda: ak.stock_board_industry_name_ths(),
            ),
            (
                "industry_summary_ths",
                ("industry_summary_ths", "cn"),
                lambda: ak.stock_board_industry_summary_ths(),
            ),
        ]
        for name, key, loader in warmups:
            try:
                self._cache[key] = (now + self._REFRESH_TTL, loader())
            except Exception:
                import logging as _lg

                _lg.getLogger("akshare_refresh").warning(
                    "warmup skipped for %s (transient upstream API issue)", name
                )


def _frame_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            return frame.to_dict("records")
        except Exception:
            return []
    if isinstance(frame, list):
        return [dict(item) for item in frame]
    return []


def _frame_tail(frame: Any, size: int) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "tail") and hasattr(frame, "to_dict"):
        return frame.tail(size).to_dict("records")
    if isinstance(frame, list):
        return [dict(item) for item in frame[-size:]]
    return []


def _find_row(frame: Any, key: str, expected: str) -> dict[str, Any]:
    expected_values = {
        expected,
        expected.upper(),
        expected.lower(),
        expected.removeprefix("HK"),
    }
    for row in _frame_tail(frame, 100000):
        if str(row.get(key, "")).strip() in expected_values:
            return row
    raise ProviderError(f"quote row not found: {expected}")


def _number(row: dict[str, Any], *keys: str, default: float | None = None) -> float:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return float(value)
    if default is not None:
        return default
    raise ProviderError(f"missing numeric column: {keys}")


def _history_item(
    row: dict[str, Any],
    day: int,
    *,
    date_keys: tuple[str, ...] = ("日期", "date"),
    open_keys: tuple[str, ...] = ("开盘", "open"),
    high_keys: tuple[str, ...] = ("最高", "high"),
    low_keys: tuple[str, ...] = ("最低", "low"),
    close_keys: tuple[str, ...] = ("收盘", "close", "最新价"),
    volume_keys: tuple[str, ...] = ("成交量", "volume"),
    amount_keys: tuple[str, ...] = ("成交额", "amount"),
) -> dict[str, Any]:
    close = _number(row, *close_keys)
    volume = _number(row, *volume_keys, default=0.0)
    amount = _number(row, *amount_keys, default=0.0)
    if volume == 0.0 and amount > 0 and close > 0:
        volume = round(amount / close, 0)
    return {
        "day": day,
        "date": _first(row, *date_keys),
        "open": _number(row, *open_keys),
        "high": _number(row, *high_keys),
        "low": _number(row, *low_keys),
        "close": close,
        "volume": volume,
        "amount": amount,
    }


def _build_financial_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 akshare financial_abstract 行转为 JSON 安全的报告列表。"""
    reports: dict[str, dict[str, Any]] = {}
    date_cols: list[str] = []
    if rows:
        for key in rows[0]:
            if isinstance(key, str) and key.isdigit() and len(key) == 8:
                date_cols.append(key)
    for row in rows:
        indicator = str(row.get("指标", ""))
        for dc in date_cols:
            if dc not in reports:
                report_date = f"{dc[:4]}-{dc[4:6]}-{dc[6:8]}"
                reports[dc] = {
                    "report_date": report_date,
                    "report_type": "annual" if dc.endswith("1231") else "quarterly",
                    "revenue": None,
                    "profit": None,
                    "total_assets": None,
                    "total_liabilities": None,
                    "_equity": None,
                    "_debt_ratio_pct": None,
                }
            val = _safe_float(row.get(dc))
            if val is None:
                continue
            if indicator in ("营业总收入", "营业收入"):
                reports[dc]["revenue"] = val
            elif indicator == "归母净利润":
                reports[dc]["profit"] = val
            elif indicator == "净利润" and reports[dc]["profit"] is None:
                reports[dc]["profit"] = val
            elif indicator in ("总资产", "资产总计"):
                reports[dc]["total_assets"] = val
            elif indicator in ("总负债", "负债合计"):
                reports[dc]["total_liabilities"] = val
            elif indicator in ("股东权益合计(净资产)", "净资产", "股东权益"):
                reports[dc]["_equity"] = val
            elif indicator == "资产负债率":
                reports[dc]["_debt_ratio_pct"] = val

    items: list[dict[str, Any]] = []
    for report in sorted(reports.values(), key=lambda x: x["report_date"], reverse=True):
        equity = report.pop("_equity", None)
        debt_ratio = report.pop("_debt_ratio_pct", None)
        if report["total_assets"] is None and equity is not None and debt_ratio is not None:
            ratio = debt_ratio / 100.0
            if 0 <= ratio < 1:
                assets = equity / (1.0 - ratio)
                report["total_assets"] = round(assets, 2)
                report["total_liabilities"] = round(assets - equity, 2)
        for key in ("revenue", "profit", "total_assets", "total_liabilities"):
            if report[key] is None:
                report[key] = 0.0
        if report["revenue"] <= 0 and report["profit"] <= 0:
            continue
        items.append(report)
    return items[:5]


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _coerce_float(value: Any, default: float = 0.0) -> float:
    parsed = _safe_float(value)
    return parsed if parsed is not None else default


_SESSION_FIELD_KEYS = {
    "last": ("最新价", "最新", "last"),
    "open": ("今开", "开盘", "open"),
    "high": ("最高", "high"),
    "low": ("最低", "low"),
    "volume": ("成交量", "volume"),
    "amount": ("成交额", "amount"),
    "turnover_pct": ("换手率", "turnover_pct"),
    "amplitude_pct": ("振幅", "amplitude_pct"),
    "volume_ratio": ("量比", "volume_ratio"),
    "pe": ("市盈率-动态", "市盈率(动)", "市盈率", "pe"),
    "pb": ("市净率", "pb"),
    "total_market_cap": ("总市值", "total_market_cap"),
    "float_market_cap": ("流通市值", "float_market_cap"),
    "prev_close": ("昨收", "prev_close"),
}

# qt.gtimg.cn tilde fields. Amount is 万元, market cap is 亿元, volume is 手.
_TENCENT_INDEX = {
    "last": 3,
    "prev_close": 4,
    "open": 5,
    "volume": 6,
    "high": 33,
    "low": 34,
    "amount_wan": 37,
    "turnover_pct": 38,
    "pe": 39,
    "amplitude_pct": 43,
    "float_market_cap_yi": 44,
    "total_market_cap_yi": 45,
    "pb": 46,
    "volume_ratio": 49,
}


def _coerce_session_number(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.replace("%", "").replace(",", "").strip()
    return _safe_float(value)


def _session_from_mapping(row: dict[str, Any], *, volume_unit: str | None = None) -> dict[str, Any]:
    session: dict[str, Any] = {}
    for name, keys in _SESSION_FIELD_KEYS.items():
        for key in keys:
            if key not in row:
                continue
            parsed = _coerce_session_number(row.get(key))
            if parsed is not None:
                session[name] = parsed
                break
    if volume_unit and session.get("volume") is not None:
        session["volume_unit"] = volume_unit
    return session


def _session_from_tencent(fields: list[str]) -> dict[str, Any]:
    def _at(index: int, scale: float = 1.0) -> float | None:
        if index >= len(fields):
            return None
        parsed = _coerce_session_number(fields[index])
        if parsed is None:
            return None
        return parsed * scale

    session: dict[str, Any] = {}
    for name, index in (
        ("last", _TENCENT_INDEX["last"]),
        ("prev_close", _TENCENT_INDEX["prev_close"]),
        ("open", _TENCENT_INDEX["open"]),
        ("high", _TENCENT_INDEX["high"]),
        ("low", _TENCENT_INDEX["low"]),
        ("volume", _TENCENT_INDEX["volume"]),
        ("turnover_pct", _TENCENT_INDEX["turnover_pct"]),
        ("amplitude_pct", _TENCENT_INDEX["amplitude_pct"]),
        ("volume_ratio", _TENCENT_INDEX["volume_ratio"]),
        ("pe", _TENCENT_INDEX["pe"]),
        ("pb", _TENCENT_INDEX["pb"]),
    ):
        value = _at(index)
        if value is not None:
            session[name] = value
    amount = _at(_TENCENT_INDEX["amount_wan"], 10000.0)
    if amount is not None:
        session["amount"] = amount
    total_cap = _at(_TENCENT_INDEX["total_market_cap_yi"], 100000000.0)
    if total_cap is not None:
        session["total_market_cap"] = total_cap
    float_cap = _at(_TENCENT_INDEX["float_market_cap_yi"], 100000000.0)
    if float_cap is not None:
        session["float_market_cap"] = float_cap
    if session.get("volume") is not None:
        session["volume_unit"] = "lot"
    return session


def _parse_tencent_fields(raw: str) -> list[str]:
    return raw.split("~")


def _session_has_ohlc(session: dict[str, Any]) -> bool:
    return all(isinstance(session.get(key), (int, float)) and session[key] > 0 for key in ("open", "high", "low"))


def _session_missing_valuation(session: dict[str, Any]) -> bool:
    return any(session.get(key) is None for key in ("pe", "pb", "total_market_cap", "turnover_pct"))


def _merge_session(primary: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in extra.items():
        if merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
    return merged


def _safe_float(value: Any) -> float | None:
    """None 保留的 float 转换；NaN/±inf/解析失败 → None（JSON 友好）。"""
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result == float("inf") or result == float("-inf"):
        return None
    return result


def _safe_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if str(value) == "NaT":
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
