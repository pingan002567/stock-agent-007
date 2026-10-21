import { describe, expect, it } from "vitest";
import { toolParamSummary } from "@/components/features/taskToolMeta";

/** 步骤行里的「对象」抽取：个股代码 / 搜索词 / 策略名… */
describe("toolParamSummary", () => {
  it("优先取 symbol（历史消息的 arguments_preview 里也是这个键）", () => {
    expect(toolParamSummary({ symbol: "002467" })).toBe("002467");
  });

  it("没有 symbol 时取 code / ts_code", () => {
    expect(toolParamSummary({ code: "600519" })).toBe("600519");
    expect(toolParamSummary({ ts_code: "000963.SZ" })).toBe("000963.SZ");
  });

  it("搜索类工具取 query / keyword", () => {
    expect(toolParamSummary({ query: "六二三 减持" })).toBe("六二三 减持");
    expect(toolParamSummary({ keyword: "股东减持" })).toBe("股东减持");
  });

  it("数组只取前两个，长文本截断到 16 字", () => {
    expect(toolParamSummary({ symbols: ["002467", "000963", "600519"] })).toBe("002467 · 000963");
    expect(toolParamSummary({ query: "一二三四五六七八九十一二三四五六七八九十" })).toBe(
      "一二三四五六七八九十一二三四五六…",
    );
  });

  it("没有可用参数时返回空串（步骤行只显示工具名）", () => {
    expect(toolParamSummary(undefined)).toBe("");
    expect(toolParamSummary({})).toBe("");
    expect(toolParamSummary({ unrelated: 1 })).toBe("");
  });
});
