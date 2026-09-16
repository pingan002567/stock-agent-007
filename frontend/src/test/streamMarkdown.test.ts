import { describe, expect, it } from "vitest";
import {
  STREAM_TAIL_PLAIN_TEXT_THRESHOLD,
  splitStableBlocks,
} from "@/lib/streamMarkdown";

describe("splitStableBlocks", () => {
  it("keeps a single paragraph as tail", () => {
    expect(splitStableBlocks("hello")).toEqual({ stable: [], tail: "hello" });
  });

  it("closes paragraphs on blank-line boundaries", () => {
    expect(splitStableBlocks("a\n\nb\n\nc")).toEqual({
      stable: ["a", "b"],
      tail: "c",
    });
  });

  it("does not split inside an open code fence", () => {
    const text = "intro\n\n```js\nconst x = 1\n\nconst y = 2";
    const { stable, tail } = splitStableBlocks(text);
    expect(stable).toEqual(["intro"]);
    expect(tail).toContain("```js");
    expect(tail).toContain("const y = 2");
  });

  it("closes a fence block then keeps trailing text as tail", () => {
    const text = "intro\n\n```js\nconst x = 1\n\nconst y = 2\n```\n\nafter";
    const { stable, tail } = splitStableBlocks(text);
    expect(stable[0]).toBe("intro");
    expect(stable[1]).toContain("```js");
    expect(stable[1]).toContain("```");
    expect(tail).toBe("after");
  });

  it("exports a plain-text threshold for long tails", () => {
    expect(STREAM_TAIL_PLAIN_TEXT_THRESHOLD).toBeGreaterThan(1000);
  });
});
