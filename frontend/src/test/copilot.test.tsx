import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CopilotMessageItem } from "@/components/features/CopilotMessageItem";
import { CopilotToolCard } from "@/components/features/CopilotToolCard";
import { CopilotStreamingMessage } from "@/components/features/CopilotStreamingMessage";
import { pairMessages } from "@/components/features/CopilotPanel";
import { placeReasoningStep } from "@/lib/agentLoop";
import { toolLabel, type StreamMessage, type StreamStep } from "@/hooks/useCopilotChat";
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

  it("renders attachments on the user bubble, not as pending composer chips", () => {
    const msg = makeMsg({
      role: "user",
      kind: "user_message",
      text: "解读这份研报",
      payload: { attachments: [{ filename: "年报.pdf", size: 1200, markdown_file: "年报.md" }] },
    });
    const { container } = render(<CopilotMessageItem msg={msg} />);
    expect(container.querySelector(".msg-attachments")).toBeTruthy();
    expect(container.textContent).toContain("年报.pdf");
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

  it("完成时间移到气泡底部（头行不再挂时间）", () => {
    const msg = makeMsg({
      kind: "final_answer",
      text: "ok",
      payload: { type: "final_answer", conclusion: "ok" },
      created_at: "2026-10-23T08:35:34Z",
    });
    const { container } = render(<CopilotMessageItem msg={msg} />);
    // 头行不再显示时间
    expect(container.querySelector(".msg-label-time")).toBeNull();
    // 底部 meta 里出现完成时间
    expect(container.querySelector(".final-meta-time")?.textContent).toBeTruthy();
  });

  it("renders markdown links that the app can intercept", () => {
    const msg = makeMsg({
      kind: "final_answer",
      text: "见 [界面新闻](https://www.jiemian.com/article/1.html)",
      payload: { type: "final_answer", conclusion: "见 [界面新闻](https://www.jiemian.com/article/1.html)" },
    });
    const { container } = render(<CopilotMessageItem msg={msg} />);
    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toBe("https://www.jiemian.com/article/1.html");
    expect(link?.getAttribute("target")).toBeNull();
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
    rounds: 0,
    tools: [],
    steps: [],
    answerText: "",
    clarificationText: null,
    clarificationRequest: null,
    finalPayload: null,
    errorText: null,
    startedAt: Date.now(),
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
    // 时间线里完成态显示 ✓（紧凑状态点，非文字标签）
    expect(container.querySelector(".tl-state-dot.ok")?.textContent).toContain("✓");
  });

  it("流式中在气泡下方显示本轮已执行时长", () => {
    const sm = makeStream({ phase: "tools", startedAt: Date.now() - 65_000 });
    const { container } = render(<CopilotStreamingMessage streamMessage={sm} />);
    // 起始时间回溯 65s → 首次 tick 即显示「已执行 1 分 …」
    expect(container.textContent).toMatch(/已执行\s*1 分/);
  });

  it("结束后不再显示进行中的「已执行」计时器", () => {
    const sm = makeStream({ phase: "final", startedAt: Date.now() - 65_000 });
    const { container } = render(<CopilotStreamingMessage streamMessage={sm} />);
    expect(container.textContent).not.toContain("已执行");
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
    const user = paired.find((item) => item.t === "msg" && item.msg.message_id === "u1");
    expect(user?.t).toBe("msg");
    if (user && user.t === "msg") {
      expect(user.incomplete).toBe(true);
      expect(user.tools?.some((t) => t.name === "get_stock_context")).toBe(true);
    }
    expect(paired.some((item) => item.t === "ai")).toBe(false);
  });

  it("places incomplete process on the prior user turn, not an empty AI bubble", () => {
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
    const u1 = paired.find((item) => item.t === "msg" && item.msg.message_id === "u1");
    expect(u1?.t).toBe("msg");
    if (u1 && u1.t === "msg") {
      expect(u1.incomplete).toBe(true);
      expect(u1.tools?.length).toBe(1);
    }
    expect(paired.some((item) => item.t === "ai" && item.msg.kind === "partial_answer")).toBe(false);
    const u2Index = paired.findIndex((item) => item.t === "msg" && item.msg.message_id === "u2");
    const u1Index = paired.findIndex((item) => item.t === "msg" && item.msg.message_id === "u1");
    expect(u1Index).toBeLessThan(u2Index);
  });

  it("skips empty partial_answer shells", () => {
    const msgs = [
      makeMsg({ message_id: "u1", role: "user", kind: "user_message", text: "hi", run_id: "run_p" }),
      makeMsg({
        message_id: "p1", role: "assistant", kind: "partial_answer", text: "   ",
        run_id: "run_p",
      }),
    ];
    const paired = pairMessages(msgs);
    expect(paired.every((item) => item.t !== "msg" || item.msg.message_id !== "p1")).toBe(true);
  });

  it("merges clarification + final into one card with tools", () => {
    const msgs = [
      makeMsg({ message_id: "u1", role: "user", kind: "user_message", text: "问一下", run_id: "run_c" }),
      makeMsg({
        message_id: "t1", role: "assistant", kind: "tool_call", text: "",
        run_id: "run_c",
        payload: { tool: "ask_clarification", call_id: "c1" },
      }),
      makeMsg({
        message_id: "tr1", role: "assistant", kind: "tool_result", text: "",
        run_id: "run_c",
        payload: { tool: "ask_clarification", call_id: "c1", result: "ok" },
      }),
      makeMsg({
        message_id: "cl1", role: "assistant", kind: "clarification", text: "范围？",
        run_id: "run_c",
        payload: {
          kind: "human_input_request",
          question: "范围？",
          request_id: "clarification:c1",
          call_id: "c1",
          input_mode: "choice_with_other",
          options: [{ id: "opt-1", label: "A", value: "A" }],
        },
      }),
      makeMsg({
        message_id: "f1", role: "assistant", kind: "final_answer",
        text: "好，那我一次只问一个，按顺序来。第 1 个问题：",
        run_id: "run_c",
        payload: {
          conclusion: "好，那我一次只问一个，按顺序来。第 1 个问题：",
          confidence: "medium",
          evidence_refs: [1, 2, 3, 4],
        },
      }),
    ];
    const paired = pairMessages(msgs);
    const finals = paired.filter((item) => item.t === "ai" && item.msg.kind === "final_answer");
    expect(finals).toHaveLength(0);
    const clar = paired.find((item) => item.t === "msg" && item.msg.kind === "clarification");
    expect(clar).toBeTruthy();
    if (clar && clar.t === "msg") {
      expect(clar.tools?.some((t) => t.name === "ask_clarification")).toBe(true);
    }
  });
});

describe("历史轮次的 agent loop（reasoning 落库回放）", () => {
  function run(messages: CopilotMessage[]) {
    return pairMessages(messages);
  }

  it("把 reasoning 与 tool_call 按到达顺序还原成 steps，并算出轮次", () => {
    const msgs = [
      makeMsg({ message_id: "u1", role: "user", kind: "user_message", text: "BTC 能买吗", run_id: "run_r" }),
      makeMsg({
        message_id: "r1", role: "system", kind: "reasoning", text: "先看价格",
        run_id: "run_r", payload: { text: "先看价格" },
      }),
      makeMsg({
        message_id: "t1", role: "assistant", kind: "tool_call", text: "",
        run_id: "run_r", payload: { tool: "get_crypto_derivatives", call_id: "c1" },
      }),
      makeMsg({
        message_id: "x1", role: "tool", kind: "tool_result", text: "get_crypto_derivatives",
        run_id: "run_r", payload: { tool: "get_crypto_derivatives", call_id: "c1", result: { ok: 1 } },
      }),
      makeMsg({
        message_id: "r2", role: "system", kind: "reasoning", text: "费率偏挤",
        run_id: "run_r", payload: { text: "费率偏挤" },
      }),
      makeMsg({
        message_id: "t2", role: "assistant", kind: "tool_call", text: "",
        run_id: "run_r", payload: { tool: "get_market_sentiment", call_id: "c2" },
      }),
      makeMsg({
        message_id: "f1", role: "assistant", kind: "final_answer", text: "能买，别追高",
        run_id: "run_r", payload: { conclusion: "能买，别追高" },
      }),
    ];
    const ai = run(msgs).find((item) => item.t === "ai");
    expect(ai?.t).toBe("ai");
    if (ai?.t !== "ai") return;
    const steps = ai.steps ?? [];
    expect(steps.map((s) => s.kind)).toEqual(["reasoning", "tool", "reasoning", "tool"]);
    // 第一轮 / 第二轮：轮次按「思考→工具」递进
    const rounds = steps.filter((s) => s.kind === "tool").map((s) => s.kind === "tool" ? s.tool.round : null);
    expect(rounds).toEqual([1, 2]);
    // reasoning 文本按序保留
    expect(steps[0].kind === "reasoning" && steps[0].text).toBe("先看价格");
    expect(steps[2].kind === "reasoning" && steps[2].text).toBe("费率偏挤");
  });

  it("相邻重复的 reasoning 不重复入列（values 快照会反复推同一段）", () => {
    const msgs = [
      makeMsg({ message_id: "u1", role: "user", kind: "user_message", text: "hi", run_id: "run_d" }),
      makeMsg({ message_id: "r1", role: "system", kind: "reasoning", text: "同一段", run_id: "run_d", payload: { text: "同一段" } }),
      makeMsg({ message_id: "r2", role: "system", kind: "reasoning", text: "同一段", run_id: "run_d", payload: { text: "同一段" } }),
      makeMsg({ message_id: "f1", role: "assistant", kind: "final_answer", text: "好", run_id: "run_d", payload: { conclusion: "好" } }),
    ];
    const ai = run(msgs).find((item) => item.t === "ai");
    if (ai?.t !== "ai") throw new Error("no ai");
    expect((ai.steps ?? []).filter((s) => s.kind === "reasoning")).toHaveLength(1);
  });

  it("有 steps 时消息体渲染出「思考」行（不再只有工具）", () => {
    const steps: import("@/hooks/useCopilotChat").StreamStep[] = [
      { kind: "reasoning", id: "r1", text: "先看价格和合约面" },
      { kind: "tool", id: "t1", tool: { callId: "c1", name: "get_stock_context", status: "done", resultText: "最新价 80,895.7" } },
    ];
    const { container } = render(
      <CopilotMessageItem
        msg={makeMsg({ message_id: "f9", role: "assistant", kind: "final_answer", text: "能买", run_id: "run_z" })}
        tools={[{ name: "get_stock_context", done: true, failed: false, id: "t1", resultText: "最新价 80,895.7" }]}
        steps={steps}
      />,
    );
    expect(container.querySelector(".tl-think-label")?.textContent).toBe("思考");
    expect(container.textContent).toContain("先看价格和合约面");
  });
});

describe("历史工具结果解包", () => {
  it("从 result_preview.value 取出真实结果，不显示落库包装", async () => {
    const { persistedToolResultText } = await import("@/lib/persistedToolResult");
    const text = persistedToolResultText({
      tool: "get_daily_history",
      call_id: "c1",
      execution_mode: null,
      risk: null,
      result_preview: { value: '{"symbol":"TRX","items":[1,2]}' },
    });
    expect(text).toContain('"symbol": "TRX"');
    expect(text).not.toContain("result_preview");
    expect(text).not.toContain("execution_mode");
  });

  it("白名单预览对象直接显示，非 JSON 原样返回", async () => {
    const { persistedToolResultText, prettyMaybeJson } = await import("@/lib/persistedToolResult");
    expect(persistedToolResultText({ result_preview: { status: "ok", summary: "完成" } }))
      .toContain('"status": "ok"');
    expect(prettyMaybeJson("最新价 1680")).toBe("最新价 1680");
  });
});

describe("思考步落位（思考 → 工具）", () => {
  it("紧跟运行中工具到达的思考，插到该工具之前", () => {
    const steps: StreamStep[] = [
      { kind: "reasoning" as const, id: "r1", text: "先看价格" },
      { kind: "tool" as const, id: "t1", tool: { callId: "c1", name: "get_stock_context", status: "running" as const } },
    ];
    const out = placeReasoningStep(steps, { kind: "reasoning", id: "r2", text: "价格偏高，再看情绪" });
    expect(out.map((s) => s.kind)).toEqual(["reasoning", "reasoning", "tool"]);
  });

  it("逐工具定位：插到「第一个还在跑的工具」之前，已完成的工具留在上面", () => {
    // 真实序列 CALL,CALL,REASON,RESULT,RESULT + 后续再来一段思考：
    // 这段思考已经看过了第一张工具的结果，必须排在它之后
    const steps: StreamStep[] = [
      { kind: "reasoning" as const, id: "r0", text: "先看盘面" },
      { kind: "tool" as const, id: "t1", tool: { callId: "c1", name: "get_portfolio_snapshot", status: "done" as const } },
      { kind: "tool" as const, id: "t2", tool: { callId: "c2", name: "get_crypto_derivatives", status: "running" as const } },
    ];
    const out = placeReasoningStep(steps, { kind: "reasoning", id: "r2", text: "持仓只有 A 股，那再看币" });
    expect(out.map((s) => s.kind)).toEqual(["reasoning", "tool", "reasoning", "tool"]);
  });

  it("全部工具都在跑时，思考插到组首（计划型）", () => {
    const steps: StreamStep[] = [
      { kind: "tool" as const, id: "t1", tool: { callId: "c1", name: "get_portfolio_snapshot", status: "running" as const } },
      { kind: "tool" as const, id: "t2", tool: { callId: "c2", name: "get_monitor_events", status: "running" as const } },
    ];
    const out = placeReasoningStep(steps, { kind: "reasoning", id: "r1", text: "先取持仓和监控" });
    expect(out.map((s) => s.kind)).toEqual(["reasoning", "tool", "tool"]);
  });

  it("尾部工具组已全部返回 → 追加在后面（结果后的复盘思考）", () => {
    const steps: StreamStep[] = [
      { kind: "reasoning" as const, id: "r1", text: "先看价格" },
      { kind: "tool" as const, id: "t1", tool: { callId: "c1", name: "get_stock_context", status: "done" as const } },
      { kind: "tool" as const, id: "t2", tool: { callId: "c2", name: "get_market_sentiment", status: "done" as const } },
    ];
    const out = placeReasoningStep(steps, { kind: "reasoning", id: "r2", text: "结果出来了，偏贵" });
    expect(out.map((s) => s.kind)).toEqual(["reasoning", "tool", "tool", "reasoning"]);
  });

  it("尾部不是工具时直接追加（交给相邻合并处理）", () => {
    const steps: StreamStep[] = [{ kind: "reasoning" as const, id: "r1", text: "第一步" }];
    const out = placeReasoningStep(steps, { kind: "reasoning", id: "r2", text: "第一步续" });
    expect(out.map((s) => s.kind)).toEqual(["reasoning", "reasoning"]);
  });

  it("历史回放：一段思考已看过前两个工具的结果、第三个还没回 → 插到第三个之前", () => {
    // 截图故障：3 段思考全堆在最上面、工具全在下面。
    // 这里模拟「思考在 c1/c2 结果之后、c3 结果之前到达」——它该落在 c3 之前。
    const msgs = [
      makeMsg({ message_id: "u1", role: "user", kind: "user_message", text: "一起看", run_id: "run_p" }),
      ...["c1", "c2", "c3"].map((cid, i) =>
        makeMsg({
          message_id: `t${i}`, role: "assistant", kind: "tool_call", text: "", run_id: "run_p",
          payload: { tool: "get_portfolio_snapshot", call_id: cid },
        }),
      ),
      makeMsg({ message_id: "x1", role: "tool", kind: "tool_result", text: "ok", run_id: "run_p", payload: { call_id: "c1" } }),
      makeMsg({ message_id: "x2", role: "tool", kind: "tool_result", text: "ok", run_id: "run_p", payload: { call_id: "c2" } }),
      makeMsg({
        message_id: "r1", role: "system", kind: "reasoning", run_id: "run_p",
        text: "持仓只有 A 股，得再看币", payload: { text: "持仓只有 A 股，得再看币" },
      }),
      makeMsg({ message_id: "x3", role: "tool", kind: "tool_result", text: "ok", run_id: "run_p", payload: { call_id: "c3" } }),
      makeMsg({ message_id: "f1", role: "assistant", kind: "final_answer", text: "结论", run_id: "run_p", payload: { conclusion: "结论" } }),
    ];
    const ai = pairMessages(msgs).find((item) => item.t === "ai");
    if (ai?.t !== "ai") throw new Error("no ai");
    expect((ai.steps ?? []).map((s) => s.kind)).toEqual(["tool", "tool", "reasoning", "tool"]);
  });

  it("历史回放：一批 3 个工具、结果都还没到 → 思考插到组首", () => {
    // 截图里的真实错位：3 个工具的调用 + 结果，思考落在第 3 个之前
    const msgs = [
      makeMsg({ message_id: "u1", role: "user", kind: "user_message", text: "一起过一遍", run_id: "run_m" }),
      ...["c1", "c2", "c3"].map((cid, i) =>
        makeMsg({
          message_id: `t${i}`, role: "assistant", kind: "tool_call", text: "", run_id: "run_m",
          payload: { tool: i === 2 ? "get_market_sentiment" : "get_portfolio_snapshot", call_id: cid },
        }),
      ),
      makeMsg({
        message_id: "r1", role: "system", kind: "reasoning",
        text: "先取持仓、监控、市场情绪", run_id: "run_m",
        payload: { text: "先取持仓、监控、市场情绪" },
      }),
      ...["c1", "c2", "c3"].map((cid, i) =>
        makeMsg({
          message_id: `x${i}`, role: "tool", kind: "tool_result", text: "ok", run_id: "run_m",
          payload: { call_id: cid, result_preview: { ok: true } },
        }),
      ),
      makeMsg({ message_id: "f1", role: "assistant", kind: "final_answer", text: "结论", run_id: "run_m", payload: { conclusion: "结论" } }),
    ];
    const ai = pairMessages(msgs).find((item) => item.t === "ai");
    if (ai?.t !== "ai") throw new Error("no ai");
    expect((ai.steps ?? []).map((s) => s.kind)).toEqual(["reasoning", "tool", "tool", "tool"]);
  });

  it("历史回放：tool_call → reasoning → tool_result 重排成 思考 → 工具", () => {
    const msgs = [
      makeMsg({ message_id: "u1", role: "user", kind: "user_message", text: "ETH 费率", run_id: "run_o" }),
      makeMsg({
        message_id: "t1", role: "assistant", kind: "tool_call", text: "",
        run_id: "run_o", payload: { tool: "get_crypto_derivatives", call_id: "c1" },
      }),
      makeMsg({
        message_id: "r1", role: "system", kind: "reasoning", text: "这是个事实题，直接查",
        run_id: "run_o", payload: { text: "这是个事实题，直接查" },
      }),
      makeMsg({
        message_id: "x1", role: "tool", kind: "tool_result", text: "get_crypto_derivatives",
        run_id: "run_o", payload: { tool: "get_crypto_derivatives", call_id: "c1", result_preview: { value: '{"funding": 0.01}' } },
      }),
      makeMsg({ message_id: "f1", role: "assistant", kind: "final_answer", text: "费率 0.01%", run_id: "run_o", payload: { conclusion: "费率 0.01%" } }),
    ];
    const ai = pairMessages(msgs).find((item) => item.t === "ai");
    if (ai?.t !== "ai") throw new Error("no ai");
    expect((ai.steps ?? []).map((s) => s.kind)).toEqual(["reasoning", "tool"]);
  });
});
