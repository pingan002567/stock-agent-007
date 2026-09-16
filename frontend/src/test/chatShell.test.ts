import { describe, expect, it } from "vitest";
import {
  SAFE_BOTTOM_SPACING,
  composerPaddingBottom,
  streamProgressKey,
} from "@/lib/chatShell";

describe("chatShell", () => {
  it("pads message list below measured composer", () => {
    expect(composerPaddingBottom(120)).toBe(120 + SAFE_BOTTOM_SPACING);
    expect(composerPaddingBottom(-4)).toBe(SAFE_BOTTOM_SPACING);
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
});
