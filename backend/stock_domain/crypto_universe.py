"""加密货币标的表（canonical = 币种代码，不是交易对）。

为什么用币种而不是交易对：
    持仓的语义是"我持有 0.08 个 BTC"，不是"我在 Gate 的 BTC_USDT 交易对上有一笔仓位"。
    交易对是报价方式，由 provider 按需拼（默认 USDT 计价）。

这个表只放**主流、Gate.io 有 USDT 现货对**的币，不追求全（6100 个交易对里
绝大多数是流动性极差的，放进来只会让搜索变成噪音）。
"""

from __future__ import annotations

from typing import Any

# 计价货币（报价币）；canonical symbol 不带计价
QUOTE_CURRENCIES: tuple[str, ...] = ("USDT", "USDC", "USD", "BTC", "ETH")

#: symbol -> {name, aliases, sector}
CRYPTO_UNIVERSE: dict[str, dict[str, Any]] = {
    "BTC": {"name": "Bitcoin", "aliases": ["比特币", "bitcoin"], "sector": "L1 / 支付"},
    "ETH": {"name": "Ethereum", "aliases": ["以太坊", "ethereum", "ether"], "sector": "L1 / 智能合约"},
    "SOL": {"name": "Solana", "aliases": ["solana"], "sector": "L1 / 高性能"},
    "BNB": {"name": "BNB", "aliases": ["binance coin", "币安币"], "sector": "L1 / 交易所"},
    "XRP": {"name": "XRP", "aliases": ["ripple", "瑞波"], "sector": "支付"},
    "DOGE": {"name": "Dogecoin", "aliases": ["狗狗币", "dogecoin"], "sector": "Meme"},
    "ADA": {"name": "Cardano", "aliases": ["cardano"], "sector": "L1 / 智能合约"},
    "TRX": {"name": "TRON", "aliases": ["tron", "波场"], "sector": "L1 / 公链"},
    "AVAX": {"name": "Avalanche", "aliases": ["avalanche"], "sector": "L1 / 高性能"},
    "TON": {"name": "Toncoin", "aliases": ["toncoin", "ton"], "sector": "L1 / 生态"},
    "LINK": {"name": "Chainlink", "aliases": ["chainlink"], "sector": "预言机"},
    "DOT": {"name": "Polkadot", "aliases": ["polkadot", "波卡"], "sector": "跨链"},
    "LTC": {"name": "Litecoin", "aliases": ["litecoin", "莱特币"], "sector": "支付"},
    "BCH": {"name": "Bitcoin Cash", "aliases": ["bitcoin cash", "比特现金"], "sector": "支付"},
    "SHIB": {"name": "Shiba Inu", "aliases": ["shiba", "柴犬币"], "sector": "Meme"},
    "PEPE": {"name": "Pepe", "aliases": ["pepe"], "sector": "Meme"},
    "UNI": {"name": "Uniswap", "aliases": ["uniswap"], "sector": "DeFi / DEX"},
    "AAVE": {"name": "Aave", "aliases": ["aave"], "sector": "DeFi / 借贷"},
    "MKR": {"name": "Maker", "aliases": ["maker", "makerdao"], "sector": "DeFi / 稳定币"},
    "CRV": {"name": "Curve DAO", "aliases": ["curve"], "sector": "DeFi / DEX"},
    "ATOM": {"name": "Cosmos Hub", "aliases": ["cosmos"], "sector": "跨链"},
    "NEAR": {"name": "NEAR Protocol", "aliases": ["near"], "sector": "L1 / 智能合约"},
    "APT": {"name": "Aptos", "aliases": ["aptos"], "sector": "L1 / 高性能"},
    "SUI": {"name": "Sui", "aliases": ["sui"], "sector": "L1 / 高性能"},
    "ARB": {"name": "Arbitrum", "aliases": ["arbitrum"], "sector": "L2"},
    "OP": {"name": "Optimism", "aliases": ["optimism"], "sector": "L2"},
    "INJ": {"name": "Injective", "aliases": ["injective"], "sector": "DeFi / 衍生品"},
    "SEI": {"name": "Sei", "aliases": ["sei"], "sector": "L1 / 高性能"},
    "TIA": {"name": "Celestia", "aliases": ["celestia"], "sector": "模块化 / DA"},
    "FIL": {"name": "Filecoin", "aliases": ["filecoin"], "sector": "存储"},
    "ETC": {"name": "Ethereum Classic", "aliases": ["ethereum classic"], "sector": "L1 / 支付"},
    "XLM": {"name": "Stellar", "aliases": ["stellar"], "sector": "支付"},
    "HBAR": {"name": "Hedera", "aliases": ["hedera"], "sector": "L1 / 企业链"},
    "ICP": {"name": "Internet Computer", "aliases": ["internet computer"], "sector": "L1 / 计算"},
    "WLD": {"name": "Worldcoin", "aliases": ["worldcoin"], "sector": "身份 / AI"},
    "FET": {"name": "Artificial Superintelligence", "aliases": ["fetch.ai", "asi"], "sector": "AI"},
    "RENDER": {"name": "Render", "aliases": ["render network", "rndr"], "sector": "AI / 算力"},
    "GRT": {"name": "The Graph", "aliases": ["the graph"], "sector": "基础设施 / 索引"},
    "ALGO": {"name": "Algorand", "aliases": ["algorand"], "sector": "L1 / 智能合约"},
    "VET": {"name": "VeChain", "aliases": ["vechain"], "sector": "供应链"},
    "STX": {"name": "Stacks", "aliases": ["stacks"], "sector": "L2 / BTC 生态"},
    "JUP": {"name": "Jupiter", "aliases": ["jupiter"], "sector": "DeFi / 聚合器"},
    "WIF": {"name": "dogwifhat", "aliases": ["dogwifhat"], "sector": "Meme"},
    "BONK": {"name": "Bonk", "aliases": ["bonk"], "sector": "Meme"},
    "ORDI": {"name": "ORDI", "aliases": ["ordinals"], "sector": "BTC 生态"},
}

#: 计价货币也当币种看（USDT/USDC 可以持有、也可以当报价币）
STABLECOINS: tuple[str, ...] = ("USDT", "USDC")


def is_crypto_symbol(symbol: str) -> bool:
    return str(symbol or "").strip().upper() in CRYPTO_UNIVERSE


def crypto_meta(symbol: str) -> dict[str, Any] | None:
    return CRYPTO_UNIVERSE.get(str(symbol or "").strip().upper())


def gate_pair(symbol: str, quote: str = "USDT") -> str:
    """canonical symbol → Gate.io 交易对（BTC → BTC_USDT）。"""
    return f"{str(symbol).strip().upper()}_{quote.upper()}"


def crypto_master_payload(symbol: str) -> dict[str, Any] | None:
    """给 stock_master 用的种子字段。"""
    meta = crypto_meta(symbol)
    if meta is None:
        return None
    sym = symbol.upper()
    return {
        "symbol": sym,
        "name": str(meta["name"]),
        "market": "CRYPTO",
        "industry": "加密货币",
        "sector": str(meta.get("sector") or ""),
        "aliases": [sym, str(meta["name"]), *[str(a) for a in meta.get("aliases") or []]],
        "instrument_type": "crypto",
    }
