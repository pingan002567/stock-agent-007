/** 工具结果一行摘要：行情 / 历史 / 回测等高频投资工具。 */

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function parsePayload(resultText: string | undefined): Record<string, unknown> | null {
  if (!resultText?.trim()) return null;
  try {
    const parsed: unknown = JSON.parse(resultText);
    const root = asRecord(parsed);
    if (!root) return null;
    // 工具桥偶发包一层 result
    const nested = asRecord(root.result);
    return nested ?? root;
  } catch {
    return null;
  }
}

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function fmtPct(value: number | null, digits = 2): string | null {
  if (value == null) return null;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

function fmtPrice(value: number | null): string | null {
  if (value == null) return null;
  return Number.isInteger(value) ? String(value) : value.toFixed(value >= 100 ? 2 : 3);
}

function pickMetrics(data: Record<string, unknown>): Record<string, unknown> {
  return asRecord(data.metrics) ?? data;
}

function summarizeQuoteLike(data: Record<string, unknown>): string | null {
  const symbol = String(data.symbol || data.name || "").trim();
  const priceObj = asRecord(data.price) ?? asRecord(data.quote) ?? data;
  const last = num(priceObj.last) ?? num(priceObj.close) ?? num(priceObj.price);
  const change = num(priceObj.change_pct) ?? num(data.change_pct);
  const parts = [
    symbol || null,
    last != null ? fmtPrice(last) : null,
    fmtPct(change),
  ].filter(Boolean);
  return parts.length >= 2 ? parts.join(" · ") : parts[0] ?? null;
}

function summarizeHistory(data: Record<string, unknown>): string | null {
  const symbol = String(data.symbol || "").trim();
  const summary = asRecord(data.summary) ?? data;
  const change = num(summary.change_pct);
  const closeObj = asRecord(summary.close);
  const latest = num(closeObj?.latest) ?? num(summary.close);
  const bars = num(summary.bars);
  const dd = num(summary.max_drawdown_pct);
  const period = asRecord(summary.period);
  const range = period?.start && period?.end ? `${period.start}→${period.end}` : null;
  const parts = [
    symbol || null,
    latest != null ? `收 ${fmtPrice(latest)}` : null,
    fmtPct(change),
    bars != null ? `${bars} 根` : null,
    dd != null ? `回撤 ${fmtPct(dd)}` : null,
    range,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

function summarizeBacktest(data: Record<string, unknown>): string | null {
  const metrics = pickMetrics(data);
  const total = num(metrics.total_return_pct);
  const dd = num(metrics.max_drawdown_pct);
  const sharpe = num(metrics.sharpe_ratio);
  const days = num(metrics.lookback_days);
  const symbol = String(data.symbol || "").trim();
  const parts = [
    symbol || null,
    total != null ? `收益 ${fmtPct(total)}` : null,
    dd != null ? `回撤 ${fmtPct(dd)}` : null,
    sharpe != null ? `夏普 ${sharpe.toFixed(2)}` : null,
    days != null ? `${days} 日` : null,
  ].filter(Boolean);
  return parts.length >= 2 ? parts.join(" · ") : parts[0] ?? null;
}

const QUOTE_TOOLS = new Set([
  "get_stock_context",
  "refresh_market_data",
  "get_realtime_quote",
]);

const HISTORY_TOOLS = new Set(["get_daily_history"]);

const BACKTEST_TOOLS = new Set([
  "run_strategy_backtest",
  "get_backtest_result",
]);

/** 返回一行摘要；无法识别时 null（调用方回退原截断文本）。 */
export function summarizeToolResult(toolName: string, resultText?: string): string | null {
  const data = parsePayload(resultText);
  if (!data) return null;
  if (QUOTE_TOOLS.has(toolName)) return summarizeQuoteLike(data);
  if (HISTORY_TOOLS.has(toolName)) return summarizeHistory(data);
  if (BACKTEST_TOOLS.has(toolName)) return summarizeBacktest(data);
  // 通用：若顶层像行情
  if (data.price || data.quote || (data.last != null && data.change_pct != null)) {
    return summarizeQuoteLike(data);
  }
  if (data.metrics || data.total_return_pct != null) {
    return summarizeBacktest(data);
  }
  if (data.summary || data.bars != null) {
    return summarizeHistory(data);
  }
  return null;
}
