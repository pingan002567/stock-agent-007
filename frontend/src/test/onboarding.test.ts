import { describe, expect, it } from "vitest";
import {
  collectSetupCopy,
  copyAvoidsJargon,
  isModelReady,
  isSetupModelReady,
  shouldShowSetupWizard,
  STARTER_PROMPTS,
} from "@/lib/onboarding";

describe("setup wizard visibility", () => {
  it("shows only when this workspace still requires first-run setup", () => {
    expect(shouldShowSetupWizard(null)).toBe(false);
    expect(shouldShowSetupWizard({ required: true, completed: false })).toBe(true);
    expect(shouldShowSetupWizard({ required: false, completed: true })).toBe(false);
    expect(shouldShowSetupWizard({ required: true, completed: true })).toBe(false);
    expect(shouldShowSetupWizard({ required: false, completed: false })).toBe(false);
  });

  it("requires a connected service and a default model before the next step", () => {
    expect(isSetupModelReady({ model_connected: true, default_model: "deepseek/deepseek-chat" })).toBe(true);
    expect(isSetupModelReady({ model_connected: true, default_model: "" })).toBe(false);
    expect(isSetupModelReady({ model_connected: true, default_model: null })).toBe(false);
    expect(isSetupModelReady({ model_connected: false, default_model: "deepseek/deepseek-chat" })).toBe(false);
  });

  it("treats stub runtime as not ready for empty-chat prompts", () => {
    expect(isModelReady({ agent_runtime: { active_client: "stub" } })).toBe(false);
    expect(isModelReady({ agent_runtime: { active_client: "direct" } })).toBe(true);
    expect(isModelReady({ agent_runtime: { active_client: "embedded" } })).toBe(true);
  });
});

describe("first-run copy", () => {
  it("keeps empty-chat prompts in plain language", () => {
    expect(STARTER_PROMPTS.map((item) => item.label)).toEqual([
      "你现在能做什么？",
      "帮我看看这三笔演示持仓",
      "帮我找几只值得先了解的股票",
    ]);
    expect(copyAvoidsJargon(collectSetupCopy())).toBe(true);
  });
});
