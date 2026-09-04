import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CopilotMessageItem } from "@/components/features/CopilotMessageItem";
import { CopilotToolCard } from "@/components/features/CopilotToolCard";
import { CopilotStreamingMessage } from "@/components/features/CopilotStreamingMessage";
import { pairMessages } from "@/components/features/CopilotPanel";
import { toolLabel, type StreamMessage } from "@/hooks/useCopilotChat";
import type { CopilotMessage } from "@/api/client";

describe("toolLabel", () => {
  it("returns known labels", () => {
    expect(toolLabel("get_stock_context")).toBe("个股分析");
    expect(toolLabel("analyze_portfolio_risk")).toBe("组合风险");
  });

  it("falls back to raw name for unknown tools", () => {
    expect(toolLabel("unknown_tool")).toBe("unknown_tool");
  });
});

function makeMsg(overrides: Partial<CopilotMessage> = {}): CopilotMessage {
  return {
    message_id: "msg-1",
    session_id: "s-1",
    run_id: null,
    role: "assistant",
    kind: "",
    text: "Hello",
    payload: {},
    created_at: "2026-05-31T10:00:00Z",
    ...overrides,
  };
}

describe("CopilotMessageItem", () => {
  it("renders user message", () => {
    const msg = makeMsg({ role: "user", text: "分析 AAPL" });
    const { container } = render(<CopilotMessageItem msg={msg} />);
    expect(container.querySelector(".msg.user")).toBeTruthy();
    expect(container.textContent).toContain("分析 AAPL");
  });

  it("renders final answer", () => {
    const msg = makeMsg({
      kind: "final_answer",
      text: "AAPL 风险较低",
      payload: { type: "final_answer", conclusion: "AAPL 风险较低" },
    });
    const { container } = render(<CopilotMessageItem msg={msg} />);
    expect(container.querySelector(".msg.ai")).toBeTruthy();
    expect(container.textContent).toContain("AAPL 风险较低");
  });

  it("renders partial answer", () => {
    const msg = makeMsg({
      kind: "partial_answer",
      text: "正在分析…",
      payload: { text: "正在分析…" },
    });
    const { container } = render(<CopilotMessageItem msg={msg} />);
    expect(container.querySelector(".msg.ai")).toBeTruthy();
    expect(container.textContent).toContain("正在分析…");
  });

  it("renders error event", () => {
    const msg = makeMsg({
      kind: "error",
      text: "API timeout",
      payload: { error: "API timeout" },
    });
    const { container } = render(<CopilotMessageItem msg={msg} />);
    expect(container.querySelector(".msg.error")).toBeTruthy();
    expect(container.textContent).toContain("API timeout");
  });
});

describe("CopilotToolCard", () => {
  it("renders running tool", () => {
    const { container } = render(
      <CopilotToolCard name="get_stock_context" done={false} onToggle={() => {}} open={false} />
    );
    expect(container.textContent).toContain("个股分析");
    expect(container.textContent).toContain("调用中…");
  });

  it("renders completed tool", () => {
    const { container } = render(
      <CopilotToolCard name="analyze_portfolio_risk" done={true} onToggle={() => {}} open={false} />
    );
    expect(container.textContent).toContain("组合风险");
    expect(container.textContent).toContain("完成");
  });

  it("renders failed tool", () => {
    const { container } = render(
      <CopilotToolCard name="get_stock_context" done={false} failed={true} onToggle={() => {}} open={false} />
    );
    expect(container.textContent).toContain("失败");
  });

  it("shows result when open and done", () => {
    const { container } = render(
      <CopilotToolCard name="get_stock_context" done={true} onToggle={() => {}} open={true} resultText="AAPL $150" />
    );
    expect(container.textContent).toContain("AAPL $150");
  });

  it("hides result when closed", () => {
    const { container } = render(
      <CopilotToolCard name="get_stock_context" done={true} onToggle={() => {}} open={false} resultText="AAPL $150" />
    );
    expect(container.querySelector(".tool-result-detail")).toBeNull();
  });
});

function makeStream(overrides: Partial<StreamMessage> = {}): StreamMessage {
  const base: StreamMessage = {
    runId: "r-1",
    phase: "reasoning",
    reasoningText: "",
    reasoningLog: [],
    skillTrace: [],
    todos: [],
    tools: [],
    steps: [],
    answerText: "",
    clarificationText: null,
    finalPayload: null,
    errorText: null,
    ...overrides,
  };
  // 时间线渲染读 steps:夹具从旧字段派生,保持用例只声明 reasoningText/tools
  if (base.steps.length === 0) {
    if (base.reasoningText) base.steps.push({ kind: "reasoning", id: "r-0", text: base.reasoningText });
    for (const tool of base.tools) base.steps.push({ kind: "tool", id: tool.callId, tool });
  }
  return base;
}

describe("CopilotStreamingMessage", () => {
  it("shows reasoning phase", () => {
    const sm = makeStream({ phase: "reasoning", reasoningText: "思考中…" });
    const { container } = render(<CopilotStreamingMessage streamMessage={sm} />);
    expect(container.textContent).toContain("推理中");
    expect(container.textContent).toContain("思考中…");
  });

  it("shows tools phase", () => {
    const sm = makeStream({
      phase: "tools",
      tools: [{ callId: "c1", name: "get_stock_context", status: "running" }],
    });
    const { container } = render(<CopilotStreamingMessage streamMessage={sm} />);
    expect(container.textContent).toContain("调用工具");
    expect(container.textContent).toContain("个股分析");
  });

  it("shows answering phase", () => {
    const sm = makeStream({ phase: "answering", answerText: "AAPL 当前价…" });
    const { container } = render(<CopilotStreamingMessage streamMessage={sm} />);
    expect(container.textContent).toContain("生成回答");
    expect(container.textContent).toContain("AAPL 当前价…");
  });

  it("shows error", () => {
    const sm = makeStream({ phase: "error", errorText: "连接超时" });
    render(<CopilotStreamingMessage streamMessage={sm} />);
    expect(screen.getByText(/连接超时/)).toBeTruthy();
  });

  it("shows tool done status", () => {
    const sm = makeStream({
      phase: "tools",
      tools: [{ callId: "c1", name: "get_stock_context", status: "done" }],
    });
    const { container } = render(<CopilotStreamingMessage streamMessage={sm} />);
    // 时间线里完成态显示 ✓(紧凑步行,非文字标签)
    expect(container.querySelector(".tl-step-state.ok")?.textContent).toContain("✓");
  });
});

describe("pairMessages", () => {
  it("marks zero-output runs as aborted", () => {
    const msgs = [
      makeMsg({ message_id: "u1", role: "user", kind: "user_message", text: "你好", run_id: "run_a" }),
    ];
    const paired = pairMessages(msgs);
    expect(paired).toHaveLength(1);
    expect(paired[0].t).toBe("msg");
    if (paired[0].t === "msg") expect(paired[0].aborted).toBe(true);
  });

  it("does not abort runs that already have tool output", () => {
    const msgs = [
      makeMsg({ message_id: "u1", role: "user", kind: "user_message", text: "简报", run_id: "run_b" }),
      makeMsg({
        message_id: "t1", role: "assistant", kind: "tool_call", text: "",
        run_id: "run_b", payload: { tool: "get_stock_context", call_id: "c1" },
      }),
    ];
    const paired = pairMessages(msgs);
    expect(paired.some((item) => item.t === "msg" && item.aborted)).toBe(false);
    expect(paired.some((item) => item.t === "ai" && item.incomplete)).toBe(true);
  });

  it("places incomplete runs before the next user turn", () => {
    const msgs = [
      makeMsg({ message_id: "u1", role: "user", kind: "user_message", text: "第一次", run_id: "run_1" }),
      makeMsg({
        message_id: "t1", role: "assistant", kind: "tool_call", text: "",
        run_id: "run_1", payload: { tool: "get_stock_context", call_id: "c1" },
      }),
      makeMsg({ message_id: "u2", role: "user", kind: "user_message", text: "第二次", run_id: "run_2" }),
      makeMsg({
        message_id: "f2", role: "assistant", kind: "final_answer", text: "好的",
        run_id: "run_2", payload: { conclusion: "好的" },
      }),
    ];
    const paired = pairMessages(msgs);
    const u2Index = paired.findIndex((item) => item.t === "msg" && item.msg.message_id === "u2");
    const incompleteIndex = paired.findIndex((item) => item.t === "ai" && item.incomplete);
    expect(incompleteIndex).toBeGreaterThan(-1);
    expect(incompleteIndex).toBeLessThan(u2Index);
  });
});
