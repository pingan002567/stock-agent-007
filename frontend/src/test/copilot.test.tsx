import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CopilotMessageItem } from "@/components/features/CopilotMessageItem";
import { CopilotToolCard } from "@/components/features/CopilotToolCard";
import { CopilotStreamingMessage } from "@/components/features/CopilotStreamingMessage";
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
  return {
    runId: "r-1",
    phase: "reasoning",
    reasoningText: "",
    tools: [],
    answerText: "",
    finalPayload: null,
    errorText: null,
    ...overrides,
  };
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
    expect(container.textContent).toContain("完成");
  });
});
