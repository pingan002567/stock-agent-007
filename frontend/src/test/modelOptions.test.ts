import { describe, expect, it } from "vitest";
import { mergeModelOptions, modelCounts } from "@/lib/modelOptions";

const connected = [
  { id: "deepseek", name: "DeepSeek", models: [{ id: "deepseek-v4-pro", name: "V4 Pro" }] },
  { id: "openai", name: "OpenAI", models: [{ id: "gpt-6.1-terra", name: "GPT-6.1 Terra" }] },
];

describe("默认模型候选合并", () => {
  it("实时拉取优先，内置目录兜底，重复不出现两次", () => {
    const out = mergeModelOptions({
      connected,
      live: { deepseek: [{ id: "deepseek-flash", name: "V4.1 Flash" }, { id: "deepseek-v4-pro", name: "V4 Pro" }] },
    });
    expect(out.map((o) => o.value)).toEqual([
      "deepseek/deepseek-flash",
      "deepseek/deepseek-v4-pro", // 实时里有，目录就不再重复
      "openai/gpt-6.1-terra",
    ]);
    expect(out[0].source).toBe("live");
    expect(out[2].source).toBe("catalog");
  });

  it("当前选中的模型即使不在名单里也保留（否则下拉会把选择吞掉）", () => {
    const out = mergeModelOptions({
      connected,
      live: {},
      current: "openai/gpt-6.1-sol-pro",
    });
    expect(out[0]).toMatchObject({ value: "openai/gpt-6.1-sol-pro", source: "current" });
    expect(out.filter((o) => o.value === "openai/gpt-6.1-sol-pro")).toHaveLength(1);
  });

  it("没有实时数据时全部走目录", () => {
    const out = mergeModelOptions({ connected, live: {} });
    expect(out).toHaveLength(2);
    expect(out.every((o) => o.source === "catalog")).toBe(true);
  });

  it("计数优先实时", () => {
    expect(modelCounts({ connected, live: { deepseek: [{ id: "a", name: "A" }, { id: "b", name: "B" }] } }))
      .toEqual({ deepseek: { count: 2, source: "live" }, openai: { count: 1, source: "catalog" } });
  });
});
