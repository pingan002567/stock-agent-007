import { describe, expect, it } from "vitest";
import { currencyMoney, currencySign, inferMarket, marketCurrency } from "@/utils/market";

describe("inferMarket · 加密货币不能落到 US", () => {
  it("纯字母的币种判为 CRYPTO（历史上会被 /^[A-Z]{1,5}$/ 判成美股）", () => {
    expect(inferMarket("BTC")).toBe("CRYPTO");
    expect(inferMarket("ETH")).toBe("CRYPTO");
    expect(inferMarket("SOL")).toBe("CRYPTO");
    expect(inferMarket("btc")).toBe("CRYPTO");
  });

  it("后端给了 market 就以它为准", () => {
    expect(inferMarket("BTC", "CRYPTO")).toBe("CRYPTO");
    // 名字撞车的也不受影响：后端说是美股就是美股
    expect(inferMarket("LINK", "US")).toBe("US");
  });

  it("原有市场不受影响", () => {
    expect(inferMarket("600519")).toBe("CN");
    expect(inferMarket("000001")).toBe("CN");
    expect(inferMarket("HK00700")).toBe("HK");
    expect(inferMarket("AAPL")).toBe("US");
  });
});

describe("币种符号与金额", () => {
  it("USDT 用 ₮，不能用 $", () => {
    expect(currencySign("USDT")).toBe("₮");
    expect(currencySign("USD")).toBe("$");
    expect(currencySign("HKD")).toBe("HK$");
    expect(currencySign("CNY")).toBe("¥");
  });

  it("market 映射到原币币种", () => {
    expect(marketCurrency("CN")).toBe("CNY");
    expect(marketCurrency("HK")).toBe("HKD");
    expect(marketCurrency("US")).toBe("USD");
    expect(marketCurrency("CRYPTO")).toBe("USDT");
  });

  it("缺值给「—」而不是 0", () => {
    expect(currencyMoney(null, "USD")).toBe("—");
    expect(currencyMoney(undefined, "USDT")).toBe("—");
    expect(currencyMoney(80895.7, "USDT")).toBe("₮80,896");
    expect(currencyMoney(1.2, "USDT")).toBe("₮1.20");
  });
});
