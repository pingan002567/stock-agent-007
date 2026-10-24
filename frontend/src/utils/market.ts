/** Infer market from stock symbol.
 *  - HKxxxxx / xxxxx (5-digit) → "HK"
 *  - Pure alpha (AAPL, MSFT) → "US"
 *  - Numeric (600519, 000001) → "CN"
 */
/** 已知加密货币代码（后端 stock_master 有 market=CRYPTO 时应优先用后端值，
 *  这里只作兜底：纯字母 1-5 位会被下面判成美股，BTC/ETH 必须拦下来）。 */
const CRYPTO_CODES = new Set([
  "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "TRX", "AVAX", "TON", "LINK", "DOT",
  "LTC", "BCH", "SHIB", "PEPE", "UNI", "AAVE", "MKR", "CRV", "ATOM", "NEAR", "APT", "SUI",
  "ARB", "OP", "INJ", "SEI", "TIA", "FIL", "ETC", "XLM", "HBAR", "ICP", "WLD", "FET",
  "RENDER", "GRT", "ALGO", "VET", "STX", "JUP", "WIF", "BONK", "ORDI", "USDT", "USDC",
]);

export function inferMarket(symbol?: string, market?: string): string {
  // 后端给了 market 就以它为准（crypto 不在 CN/HK/US 三分类里）
  if (market) return market;
  if (!symbol) return "CN";
  const s = symbol.toUpperCase();
  if (CRYPTO_CODES.has(s)) return "CRYPTO";
  if (s.startsWith("HK")) return "HK";
  // 5 or 6 digit numeric → CN (A-share)
  if (/^\d{5,6}$/.test(s)) return "CN";
  // Pure alphabetic → US
  if (/^[A-Z]{1,5}$/.test(s)) return "US";
  return "CN";
}

/** market → 原币币种 */
export function marketCurrency(market?: string): string {
  if (market === "HK") return "HKD";
  if (market === "US") return "USD";
  if (market === "CRYPTO") return "USDT";
  return "CNY";
}

/** 币种符号。USDT 用 ₮（不要用 $，那是美元）。 */
export function currencySign(currency?: string): string {
  switch ((currency || "CNY").toUpperCase()) {
    case "USD": return "$";
    case "HKD": return "HK$";
    case "USDT": return "₮";
    default: return "¥";
  }
}

/** 按币种格式化金额；缺值给「—」（不要显示 0）。 */
export function currencyMoney(v: number | null | undefined, currency?: string): string {
  if (v == null || Number.isNaN(v)) return "—";
  const digits = Math.abs(v) >= 1000 ? 0 : 2;
  return `${currencySign(currency)}${v.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

/** Format a numeric value with the appropriate currency prefix for a given market. */
export function marketMoney(v?: number, market?: string): string {
  const prefix = market === "HK" ? "HK$" : market === "US" ? "$" : market === "CRYPTO" ? "₮" : "¥";
  return `${prefix}${(v ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Cost basis. Missing stays missing — never render as zero. */
export function formatCost(v: number | null | undefined, market?: string): string {
  if (v == null) return "未记录";
  return marketMoney(v, market);
}

/** Signed money for unrealized P&L. Missing stays a dash. */
export function formatPnlAmount(v: number | null | undefined, market?: string): string {
  if (v == null || Number.isNaN(v)) return "—";
  const body = marketMoney(Math.abs(v), market);
  if (v > 0) return `+${body}`;
  if (v < 0) return `-${body}`;
  return body;
}

/** 股票头像字符：优先取名称首字。
 *  A 股代码首位恒为 0/3/6，用 symbol.charAt(0) 当头像没有信息量
 *  （历史上每行都显示「0」）。 */
export function stockInitial(name?: string | null, symbol?: string | null): string {
  const n = (name ?? "").trim();
  if (n) return n.charAt(0).toUpperCase();
  const s = (symbol ?? "").trim();
  return s ? s.charAt(0).toUpperCase() : "?";
}

/** 按持仓市值占比计算权重（%）。
 *  后端 holdings 的 weight_pct / max_weight_pct 目前恒为 0（未实现），
 *  前端自算兜底，避免权重条全空、「最大权重 0.00%」。 */
export function computeWeights(items: { market_value?: number | null }[]): {
  weights: number[];
  maxWeight: number;
} {
  const values = items.map((it) => Math.max(0, Number(it.market_value ?? 0)));
  const total = values.reduce((a, b) => a + b, 0);
  const weights = values.map((v) => (total > 0 ? (v / total) * 100 : 0));
  return { weights, maxWeight: weights.length ? Math.max(...weights) : 0 };
}

export function weightUnavailable(item: {
  weight_pct?: number | null;
  quote?: { last?: number | null; degraded?: boolean } | null;
}): boolean {
  if (item.weight_pct == null) return true;
  return Boolean(item.quote?.degraded);
}

/** Format a number as percentage with sign. */
export function pct(v?: number): string {
  return `${(v ?? 0) >= 0 ? "+" : ""}${(v ?? 0).toFixed(2)}%`;
}

/** CSS class for price change (up/down). */
export function changeCls(cp?: number): string {
  return (cp ?? 0) >= 0 ? "up" : "down";
}

/** Format large numbers in 亿 (hundred millions). */
export function bigCN(v?: number): string {
  return v != null ? `¥${(v / 1e8).toFixed(2)}亿` : "-";
}
