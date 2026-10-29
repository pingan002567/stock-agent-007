import { describe, expect, it } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { TrajectoryView } from "@/components/features/TrajectoryView";
import { ThoughtTimeline } from "@/components/features/ThoughtTimeline";
import { exitCodeOf, loopStats } from "@/lib/agentLoop";
import type { StreamStep, StreamToolCall } from "@/hooks/useCopilotChat";

function step(args?: Record<string, unknown>, name = "get_stock_context"): StreamStep {
  return {
    kind: "tool",
    id: "t1",
    tool: { callId: "c1", name, status: "done", args },
  };
}

function tool(over: Partial<StreamToolCall> = {}): StreamToolCall {
  return { callId: "c1", name: "get_stock_context", status: "done", ...over };
}

function toolStep(over: Partial<StreamToolCall> = {}, id = "t1"): StreamStep {
  return { kind: "tool", id, tool: tool({ callId: id, ...over }) };
}

function think(text: string, id = "r1"): StreamStep {
  return { kind: "reasoning", id, text };
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

  it("折叠头显示步数与用时", () => {
    const steps = Array.from({ length: 10 }, (_, i) => toolStep({}, `t${i}`));
    const { container } = render(<ThoughtTimeline steps={steps} active={false} durationMs={72_000} />);
    const head = container.querySelector(".loop-head")?.textContent ?? "";
    expect(head).toContain("调用 10 个工具");
    expect(head).toContain("1 分 12 秒");
  });
});

describe("agent loop 折叠", () => {
  it("流式中默认展开，完成后默认折叠", () => {
    const steps = [think("先看价格"), toolStep()];
    const live = render(<ThoughtTimeline steps={steps} active durationMs={3000} />);
    expect(live.container.querySelector(".agent-loop")?.classList.contains("open")).toBe(true);
    live.unmount();

    const done = render(<ThoughtTimeline steps={steps} active={false} durationMs={3000} />);
    expect(done.container.querySelector(".agent-loop")?.classList.contains("open")).toBe(false);
    // 折叠后正文仍在 DOM 里（只是不显示），点标题可展开
    fireEvent.click(done.container.querySelector(".loop-head")!);
    expect(done.container.querySelector(".agent-loop")?.classList.contains("open")).toBe(true);
  });

  it("流式时标题是「正在思考…」，完成后是统计", () => {
    const steps = [think("a"), toolStep(), think("b", "r2")];
    const live = render(<ThoughtTimeline steps={steps} active />);
    expect(live.container.querySelector(".loop-title")?.textContent).toBe("正在思考…");
    live.unmount();

    const done = render(<ThoughtTimeline steps={steps} active={false} durationMs={5000} />);
    const title = done.container.querySelector(".loop-title")?.textContent ?? "";
    expect(title).toContain("思考 2 步");
    expect(title).toContain("调用 1 个工具");
  });

  it("轨迹视图(expandAll)不显示折叠头且正文常显", () => {
    const { container } = render(<ThoughtTimeline steps={[think("a"), toolStep()]} active={false} expandAll />);
    expect(container.querySelector(".loop-head")).toBeNull();
    expect(container.querySelector(".agent-loop")?.classList.contains("open")).toBe(true);
  });
});

describe("工具节点：状态与输出", () => {
  it("降级用 ! 而不是 ✓", () => {
    const { container } = render(
      <ThoughtTimeline steps={[toolStep({ degraded: true, resultText: '{"degraded": true}' })]} active={false} expandAll />,
    );
    const dot = container.querySelector(".tl-state-dot");
    expect(dot?.textContent).toBe("!");
    expect(dot?.classList.contains("warn")).toBe(true);
  });

  it("失败用 ✕", () => {
    const { container } = render(
      <ThoughtTimeline steps={[toolStep({ status: "failed", resultText: "boom" })]} active={false} expandAll />,
    );
    expect(container.querySelector(".tl-state-dot")?.textContent).toBe("✕");
  });

  it("长结果渲染成 3 行块并可展开", () => {
    const long = JSON.stringify({ a: 1, b: 2, c: 3, d: 4, e: 5 }, null, 2);
    const { container } = render(<ThoughtTimeline steps={[toolStep({ resultText: long })]} active={false} expandAll />);
    const out = container.querySelector(".out");
    expect(out?.classList.contains("clamp")).toBe(true);
    fireEvent.click(container.querySelector(".out-more")!);
    expect(container.querySelector(".out")?.classList.contains("clamp")).toBe(false);
  });

  it("短结果压成一行，不占块", () => {
    const { container } = render(
      <ThoughtTimeline steps={[toolStep({ resultText: "最新价 1680.00" })]} active={false} expandAll />,
    );
    expect(container.querySelector(".out")).toBeNull();
    expect(container.querySelector(".tl-step-result")?.textContent).toContain("最新价");
  });

  it("显示单次耗时", () => {
    const { container } = render(
      <ThoughtTimeline steps={[toolStep({ durationMs: 840 })]} active={false} expandAll />,
    );
    expect(container.querySelector(".tool-tail")?.textContent).toContain("0.8s");
  });
});

describe("命令节点", () => {
  it("bash 渲染成终端块 + 命令行 + 输出", () => {
    const { container } = render(
      <ThoughtTimeline
        steps={[toolStep({
          name: "bash",
          kind: "command",
          args: { command: "ls -la /tmp" },
          resultText: "total 0\ndrwxrwxrwx 1 root root 0 tmp",
          durationMs: 320,
        })]}
        active={false}
        expandAll
      />,
    );
    expect(container.querySelector(".cmd-text")?.textContent).toBe("ls -la /tmp");
    expect(container.querySelector(".cmd-out")?.textContent).toContain("total 0");
  });

  it("exitCodeOf 认 JSON 字段与文本两种写法", () => {
    expect(exitCodeOf(tool({ resultText: '{"exit_code": 2, "stdout": ""}' }))).toBe(2);
    expect(exitCodeOf(tool({ resultText: "boom\nExit code: 1" }))).toBe(1);
    expect(exitCodeOf(tool({ resultText: "all good" }))).toBeNull();
  });
});

describe("loopStats", () => {
  it("命令单独计数，轮次取最大值", () => {
    const steps: StreamStep[] = [
      think("a"),
      toolStep({ round: 1 }, "t1"),
      think("b", "r2"),
      toolStep({ kind: "command", round: 2 }, "t2"),
      toolStep({ round: 2 }, "t3"),
    ];
    expect(loopStats(steps)).toEqual({ reasoning: 2, tools: 2, commands: 1, rounds: 2 });
  });

  it("没有工具时轮次为 0", () => {
    expect(loopStats([think("a")])).toEqual({ reasoning: 1, tools: 0, commands: 0, rounds: 0 });
  });
});

describe("轨迹页：思考也要出现", () => {
  it("GroupedItem 的 steps 被直接使用（不再只用 tools 重建）", () => {
    const items = [
      {
        t: "ai" as const,
        msg: {
          message_id: "m1", role: "assistant" as const, kind: "final_answer" as const,
          text: "结论", run_id: "run1", created_at: "2026-10-29T06:00:00Z", session_id: "s1",
        },
        tools: [],
        steps: [think("先看费率，再判断拥挤度"), toolStep()],
      },
    ];
    const { container } = render(
      <TrajectoryView items={items as never} streamMessage={null} />,
    );
    const text = container.textContent ?? "";
    // 思考正文必须出现；旧实现只渲染 tools，会把这段整条丢掉
    expect(text).toContain("先看费率，再判断拥挤度");
    expect(text).toContain("思考 1");
    expect(text).toContain("工具 1");
  });

  it("只有思考没有工具的轮次也要列出来", () => {
    const items = [
      {
        t: "ai" as const,
        msg: {
          message_id: "m2", role: "assistant" as const, kind: "final_answer" as const,
          text: "结论", run_id: "run2", created_at: "2026-10-29T06:10:00Z", session_id: "s1",
        },
        tools: [],
        steps: [think("这题不需要查数据，直接回答")],
      },
    ];
    const { container } = render(
      <TrajectoryView items={items as never} streamMessage={null} />,
    );
    expect(container.textContent ?? "").toContain("这题不需要查数据，直接回答");
  });
});
