import { describe, expect, it } from "vitest";
import { adoptNewSessionDraft, composerDraftKey } from "@/lib/composerDraft";

describe("composer drafts", () => {
  it("keys each session independently from a new chat", () => {
    expect(composerDraftKey(null)).toBe("");
    expect(composerDraftKey("session_a")).toBe("session_a");
  });

  it("moves the new-chat draft onto the session created from it", () => {
    expect(adoptNewSessionDraft({ "": "盘前追问" }, "session_a")).toEqual({
      "": "",
      session_a: "盘前追问",
    });
  });

  it("does not overwrite a session that already has a draft", () => {
    expect(adoptNewSessionDraft({ "": "新的", session_a: "旧的" }, "session_a")).toEqual({
      "": "新的",
      session_a: "旧的",
    });
  });
});
