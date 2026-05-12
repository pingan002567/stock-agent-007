/** Infer market from stock symbol.
 *  - HKxxxxx / xxxxx (5-digit) → "HK"
 *  - Pure alpha (AAPL, MSFT) → "US"
 *  - Numeric (600519, 000001) → "CN"
 */
export function inferMarket(symbol?: string): string {
  if (!symbol) return "CN";
  const s = symbol.toUpperCase();
  if (s.startsWith("HK")) return "HK";
  // 5 or 6 digit numeric → CN (A-share)
  if (/^\d{5,6}$/.test(s)) return "CN";
  // Pure alphabetic → US
  if (/^[A-Z]{1,5}$/.test(s)) return "US";
  return "CN";
}

/** Format a numeric value with the appropriate currency prefix for a given market. */
export function marketMoney(v?: number, market?: string): string {
  const prefix = market === "HK" ? "HK$" : market === "US" ? "$" : "¥";
  return `${prefix}${(v ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
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
