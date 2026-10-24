import { describe, expect, it } from "vitest";
import { summarizeToolResult } from "@/lib/toolResultSummary";

describe("summarizeToolResult", () => {
  it("summarizes stock context quote", () => {
    const text = JSON.stringify({
      symbol: "AAPL",
      name: "Apple",
      price: { last: 190.5, change_pct: 1.24 },
    });
    expect(summarizeToolResult("get_stock_context", text)).toBe("AAPL · 190.50 · +1.24%");
  });

  it("summarizes daily history", () => {
    const text = JSON.stringify({
      symbol: "600519.SH",
      summary: {
        bars: 30,
        change_pct: -2.1,
        close: { latest: 1680.0, first: 1716.0 },
        max_drawdown_pct: -5.4,
        period: { start: "2026-08-01", end: "2026-09-15" },
      },
    });
    expect(summarizeToolResult("get_daily_history", text)).toContain("600519.SH");
    expect(summarizeToolResult("get_daily_history", text)).toContain("收 1680");
    expect(summarizeToolResult("get_daily_history", text)).toContain("-2.10%");
  });

  it("summarizes backtest metrics", () => {
    const text = JSON.stringify({
      metrics: {
        total_return_pct: 12.5,
        max_drawdown_pct: -8.2,
        sharpe_ratio: 1.35,
        lookback_days: 60,
      },
    });
    expect(summarizeToolResult("run_strategy_backtest", text)).toBe(
      "收益 +12.50% · 回撤 -8.20% · 夏普 1.35 · 60 日",
    );
  });

  it("returns null for unknown free text", () => {
    expect(summarizeToolResult("web_search", "hello world")).toBeNull();
  });

  it("包装型 payload 无可读字段时不返回「已完成」", () => {
    // 回归：兜底曾把状态词当摘要，轨迹里会与右侧 ✓ 重复
    const text = JSON.stringify({
      tool: "list_data_sources",
      execution_mode: "inline",
      result: { providers: [] },
    });
    expect(summarizeToolResult("list_data_sources", text)).toBeNull();
  });

  it("包装型 payload 有可读字段时仍取摘要", () => {
    const text = JSON.stringify({
      tool: "list_data_sources",
      execution_mode: "inline",
      result_preview: "3 个数据源可用",
    });
    expect(summarizeToolResult("list_data_sources", text)).toBe("3 个数据源可用");
  });
});
