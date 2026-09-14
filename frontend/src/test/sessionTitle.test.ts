import { describe, it, expect } from "vitest";
import { displaySessionTitle, isUsableSessionTitle } from "@/lib/sessionTitle";

describe("isUsableSessionTitle", () => {
  it("accepts normal user titles", () => {
    expect(isUsableSessionTitle("帮我做 A 股板块分析")).toBe(true);
    expect(isUsableSessionTitle("hello")).toBe(true);
  });

  it("rejects prompt envelope leaks", () => {
    expect(isUsableSessionTitle("<workbench_context> page: chat")).toBe(false);
    expect(isUsableSessionTitle('{"envelope_version":"v1"}')).toBe(false);
    expect(isUsableSessionTitle("page: chat authority: A2")).toBe(false);
  });

  it("falls back for display", () => {
    expect(displaySessionTitle("<workbench_context> page: ch")).toBe("新会话");
    expect(displaySessionTitle("板块分析")).toBe("板块分析");
    expect(displaySessionTitle("[定时任务·盘前简报 09-14 08:30]")).toBe("盘前简报 09-14");
  });
});
