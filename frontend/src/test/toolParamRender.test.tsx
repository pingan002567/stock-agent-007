import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { ThoughtTimeline } from "@/components/features/ThoughtTimeline";
import type { StreamStep } from "@/hooks/useCopilotChat";

function step(args?: Record<string, unknown>, name = "get_stock_context"): StreamStep {
  return {
    kind: "tool",
    id: "t1",
    tool: { callId: "c1", name, status: "done", args },
  };
}

describe("ThoughtTimeline 步骤行", () => {
  it("有参数时显示「对象」chip", () => {
    const { container } = render(<ThoughtTimeline steps={[step({ symbol: "002467" })]} active={false} />);
    const chip = container.querySelector(".tl-step-param");
    expect(chip?.textContent).toBe("002467");
  });

  it("搜索类工具取 query", () => {
    const { container } = render(
      <ThoughtTimeline steps={[step({ query: "六二三 减持" }, "search_stock_intel")]} active={false} />,
    );
    expect(container.querySelector(".tl-step-param")?.textContent).toBe("六二三 减持");
  });

  it("没有参数时不渲染 chip", () => {
    const { container } = render(<ThoughtTimeline steps={[step()]} active={false} />);
    expect(container.querySelector(".tl-step-param")).toBeNull();
  });

  it("折叠按钮旁显示「共 N 步 · 用时」", () => {
    const steps = Array.from({ length: 10 }, (_, i) => ({ ...step({ symbol: "002467" }), id: `t${i}` }));
    const { container } = render(<ThoughtTimeline steps={steps} active={false} durationMs={72_000} />);
    const meta = container.querySelector(".tl-collapse-meta")?.textContent ?? "";
    expect(meta).toContain("共 10 步");
    expect(meta).toContain("1 分 12 秒");
  });
});
