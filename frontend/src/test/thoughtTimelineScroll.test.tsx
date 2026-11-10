import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ThoughtTimeline } from "@/components/features/ThoughtTimeline";
import type { StreamStep } from "@/hooks/useCopilotChat";

function reasoning(id: string, text: string): StreamStep {
  return { id, kind: "reasoning", text } as StreamStep;
}

const STEPS: StreamStep[] = Array.from({ length: 8 }, (_, i) =>
  reasoning(`s${i}`, `第 ${i + 1} 段思考内容，用来把窗口撑高。`),
);

describe("流式思维链窗口", () => {
  it("流式中：固定高度窗口存在（.live + .tl-scroll）", () => {
    const { container } = render(<ThoughtTimeline steps={STEPS} active />);
    expect(container.querySelector(".agent-loop.live")).not.toBeNull();
    expect(container.querySelector(".tl-scroll")).not.toBeNull();
  });

  it("完成后：不再固定窗口，恢复折叠全文", () => {
    const { container } = render(<ThoughtTimeline steps={STEPS} active={false} />);
    expect(container.querySelector(".agent-loop.live")).toBeNull();
  });

  it("用户上滚后新步骤只累加未读，点胶囊可恢复", async () => {
    const { container, rerender } = render(<ThoughtTimeline steps={STEPS} active />);
    const scroller = container.querySelector(".tl-scroll") as HTMLDivElement;

    // jsdom 里没有布局：手动给出"内容 800 / 视口 220"
    Object.defineProperty(scroller, "scrollHeight", { value: 800, configurable: true });
    Object.defineProperty(scroller, "clientHeight", { value: 220, configurable: true });
    scroller.scrollTop = 0;
    fireEvent.scroll(scroller);

    rerender(<ThoughtTimeline steps={[...STEPS, reasoning("s8", "新到的一条思考")]} active />);
    // 贴底/计数在 rAF 里更新，等一帧
    await waitFor(() => expect(screen.getByRole("button", { name: /条新思考/ })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /条新思考/ }));
    expect(screen.queryByRole("button", { name: /条新思考/ })).toBeNull();
  });
});
