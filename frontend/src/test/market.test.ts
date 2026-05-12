import { describe, it, expect } from "vitest";
import { inferMarket, marketMoney, pct } from "@/utils/market";

describe("inferMarket", () => {
  it("returns CN for A-share codes", () => {
    expect(inferMarket("600519")).toBe("CN");
    expect(inferMarket("000001")).toBe("CN");
    expect(inferMarket("688256")).toBe("CN");
  });

  it("returns HK for HK-prefixed codes", () => {
    expect(inferMarket("HK00700")).toBe("HK");
    expect(inferMarket("HK09988")).toBe("HK");
  });

  it("returns US for alpha codes", () => {
    expect(inferMarket("AAPL")).toBe("US");
    expect(inferMarket("MSFT")).toBe("US");
    expect(inferMarket("TSLA")).toBe("US");
  });
});

describe("marketMoney", () => {
  it("formats CNY with ¥", () => {
    expect(marketMoney(1234.5, "CN")).toBe("¥1,234.50");
  });

  it("formats HKD with HK$", () => {
    expect(marketMoney(386.8, "HK")).toBe("HK$386.80");
  });

  it("formats USD with $", () => {
    expect(marketMoney(193.7, "US")).toBe("$193.70");
  });

  it("defaults to ¥ for unknown market", () => {
    expect(marketMoney(500, "JP")).toBe("¥500.00");
  });
});

describe("pct", () => {
  it("adds + for positive", () => {
    expect(pct(1.5)).toBe("+1.50%");
  });

  it("adds - for negative", () => {
    expect(pct(-2.35)).toBe("-2.35%");
  });

  it("handles zero", () => {
    expect(pct(0)).toBe("+0.00%");
  });
});
