import { describe, expect, it } from "vitest";
import {
  SAFE_BOTTOM_SPACING,
  STUCK_IDLE_MS,
  composerPaddingBottom,
  streamProgressKey,
  toolStatusesKey,
  workingDockCopy,
} from "@/lib/chatShell";

describe("chatShell", () => {
  it("pads message list below measured composer", () => {
    expect(composerPaddingBottom(120)).toBe(120 + SAFE_BOTTOM_SPACING);
    expect(composerPaddingBottom(-4)).toBe(SAFE_BOTTOM_SPACING);
  });

  it("uses a 90s stuck idle window", () => {
    expect(STUCK_IDLE_MS).toBe(90_000);
  });

  it("builds a stable stream progress fingerprint", () => {
    const a = streamProgressKey({
      phase: "tools",
      answerText: "hi",
      toolCount: 2,
      clarification: false,
    });
    const b = streamProgressKey({
      phase: "tools",
      answerText: "hi!",
      toolCount: 2,
      clarification: false,
    });
    expect(a).not.toBe(b);
    expect(streamProgressKey({ phase: "answering", answerText: "x" })).toContain("answering");
  });

  it("changes fingerprint when tool status flips", () => {
    const running = streamProgressKey({
      phase: "tools",
      toolCount: 1,
      toolStatuses: toolStatusesKey([{ callId: "c1", status: "running" }]),
    });
    const done = streamProgressKey({
      phase: "tools",
      toolCount: 1,
      toolStatuses: toolStatusesKey([{ callId: "c1", status: "done" }]),
    });
    expect(running).not.toBe(done);
  });

  it("labels working dock from live phase/tool", () => {
    expect(
      workingDockCopy({
        lastAt: Date.now(),
        status: "running",
        phase: "tool",
        currentTool: "web_search",
        alive: true,
      }).title,
    ).toContain("web_search");
    expect(
      workingDockCopy({
        lastAt: Date.now(),
        status: "running",
        phase: "llm",
        currentTool: null,
        alive: true,
      }).title,
    ).toContain("推理");
  });
});
