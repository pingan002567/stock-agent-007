import { describe, it, expect } from "vitest";
import { summarizeSessionActivity, type StreamMessage } from "@/hooks/useCopilotChat";

function base(overrides: Partial<StreamMessage> = {}): StreamMessage {
  return {
    runId: "r1",
    phase: "reasoning",
    reasoningText: "",
    reasoningLog: [],
    skillTrace: [],
    todos: [],
    tools: [],
    steps: [],
    answerText: "",
    clarificationText: null,
    clarificationRequest: null,
    finalPayload: null,
    errorText: null,
    ...overrides,
  };
}

describe("summarizeSessionActivity", () => {
  it("maps reasoning / answering / clarification / error", () => {
    expect(summarizeSessionActivity(base({ phase: "reasoning" }) )?.summary).toBe("正在思考…");
    expect(summarizeSessionActivity(base({ phase: "answering" }) )?.summary).toBe("正在回复…");
    expect(summarizeSessionActivity(base({
      phase: "tools",
      clarificationText: "持仓比例要多少？",
    }) )?.summary).toBe("等待你的回复");
    expect(summarizeSessionActivity(base({ phase: "error", errorText: "x" }) )?.summary).toBe("出错 · 可重试");
  });

  it("formats single and multi tool labels", () => {
    expect(summarizeSessionActivity(base({
      phase: "tools",
      tools: [{ callId: "1", name: "get_daily_history", status: "running" }],
    }) )?.summary).toBe("正在调用 · 历史行情");

    expect(summarizeSessionActivity(base({
      phase: "tools",
      tools: [
        { callId: "1", name: "get_daily_history", status: "running" },
        { callId: "2", name: "search_stock_intel", status: "running" },
        { callId: "3", name: "get_stock_context", status: "running" },
      ],
    }) )?.summary).toBe("正在调用 · 3 个工具");
  });

  it("ignores final phase", () => {
    expect(summarizeSessionActivity(base({ phase: "final", answerText: "done" }))).toBeNull();
  });
});
