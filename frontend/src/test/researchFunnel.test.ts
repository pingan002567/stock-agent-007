import { describe, expect, it } from "vitest";
import { RESEARCH_FUNNEL } from "@/lib/researchFunnel";

describe("research funnel", () => {
  it("keeps the four-step welcome path", () => {
    expect(RESEARCH_FUNNEL.map((item) => item.step)).toEqual([
      "1. 圈候选",
      "2. 体检",
      "3. 深研",
      "4. 进自选",
    ]);
    expect(RESEARCH_FUNNEL[2].prompt).toContain("市场结构");
    expect(RESEARCH_FUNNEL[2].prompt).toContain("禁止写获利或套牢比例");
    expect(RESEARCH_FUNNEL[3].prompt).toContain("不要自动下单");
  });
});
