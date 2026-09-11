import { describe, it, expect } from "vitest";
import {
  parseHumanInputRequest,
  createHumanInputOptionResponse,
  createHumanInputTextResponse,
  splitClarificationMarkdown,
} from "@/lib/humanInput";

describe("humanInput protocol", () => {
  it("parses choice_with_other from SSE-shaped payload", () => {
    const req = parseHumanInputRequest({
      version: 1,
      kind: "human_input_request",
      source: "ask_clarification",
      request_id: "clarification:c1",
      question: "选哪只？",
      input_mode: "choice_with_other",
      options: [
        { id: "opt-1", label: "茅台", value: "茅台" },
        { id: "opt-2", label: "五粮液", value: "五粮液" },
      ],
    });
    expect(req?.input_mode).toBe("choice_with_other");
    expect(req?.options).toHaveLength(2);
    const opt = createHumanInputOptionResponse(req!, req!.options![0]);
    expect(opt.response_kind).toBe("option");
    expect(opt.value).toBe("茅台");
  });

  it("falls back to free_text from question-only payload", () => {
    const req = parseHumanInputRequest({ question: "还缺什么？", call_id: "x" });
    expect(req?.input_mode).toBe("free_text");
    expect(req?.request_id).toBe("clarification:x");
    const text = createHumanInputTextResponse(req!, "补充一下仓位");
    expect(text.response_kind).toBe("text");
  });

  it("lifts numbered options out of markdown question blobs", () => {
    const split = splitClarificationMarkdown(
      "🧩 口径很宽，先确认范围。\n\n第 1 个问题：范围？\n1. 全市场\n2. 持仓",
    );
    expect(split.context).toContain("口径很宽");
    expect(split.question).toContain("范围");
    expect(split.options.map((o) => o.label)).toEqual(["全市场", "持仓"]);

    const req = parseHumanInputRequest({
      question: "🧩 口径很宽。\n\n第 1 个问题：范围？\n1. 全市场\n2. 持仓",
      call_id: "md1",
    });
    expect(req?.input_mode).toBe("choice_with_other");
    expect(req?.options).toHaveLength(2);
    expect(req?.question).not.toMatch(/^\s*1\./m);
  });
});
