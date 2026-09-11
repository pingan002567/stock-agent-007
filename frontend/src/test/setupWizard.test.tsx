import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LlmProviderItem, LlmProvidersSnapshot } from "@/api/llmProviders";
import { SetupWizard } from "@/components/features/SetupWizard";
import { copyAvoidsJargon } from "@/lib/onboarding";

const fetchLlmProviders = vi.fn();
const setDefaultLlmModel = vi.fn();
const finishSetup = vi.fn();
const handleNewSession = vi.fn(async () => undefined);

vi.mock("@/api/llmProviders", () => ({
  fetchLlmProviders: (...args: unknown[]) => fetchLlmProviders(...args),
  setDefaultLlmModel: (...args: unknown[]) => setDefaultLlmModel(...args),
}));

vi.mock("@/api/setup", () => ({
  finishSetup: (...args: unknown[]) => finishSetup(...args),
}));

vi.mock("@/hooks/useCopilotChat", () => ({
  useCopilotChat: () => ({ handleNewSession }),
}));

const emptyRuntime = {
  default_model: null,
  provider_id: null,
  provider_name: null,
  model_id: null,
  source: null,
  connected: false,
};

function provider(partial: Partial<LlmProviderItem> = {}): LlmProviderItem {
  return {
    id: "deepseek",
    name: "DeepSeek",
    base_url: "https://api.deepseek.com",
    popular: true,
    requires_key: true,
    note: null,
    models: [{ id: "deepseek-chat", name: "DeepSeek Chat" }],
    connected: false,
    source: "api",
    can_disconnect: true,
    has_key: false,
    custom: false,
    ...partial,
  };
}

function snapshot(partial: Partial<LlmProvidersSnapshot> = {}): LlmProvidersSnapshot {
  const item = provider();
  return {
    connected: [],
    popular: [item],
    catalog: [item],
    default_model: null,
    runtime: emptyRuntime,
    ...partial,
  };
}

describe("SetupWizard", () => {
  beforeEach(() => {
    fetchLlmProviders.mockReset();
    setDefaultLlmModel.mockReset();
    finishSetup.mockReset();
    handleNewSession.mockClear();
  });

  it("keeps 下一步 disabled until a default model is chosen", async () => {
    fetchLlmProviders.mockResolvedValue(snapshot());
    render(
      <SetupWizard
        initialStatus={{ completed: false, required: true, model_connected: false, default_model: null }}
        onFinished={() => {}}
      />,
    );
    const next = await screen.findByRole("button", { name: "下一步" });
    await waitFor(() => expect(next).toBeDisabled());
    expect(screen.getByText("接上一个对话模型")).toBeTruthy();
    expect(copyAvoidsJargon(document.body.textContent ?? "")).toBe(true);
  });

  it("skips to 准备开始 when a default model is already set", async () => {
    const connected = provider({ connected: true, has_key: true });
    fetchLlmProviders.mockResolvedValue(snapshot({
      connected: [connected],
      catalog: [connected],
      default_model: "deepseek/deepseek-chat",
      runtime: { ...emptyRuntime, connected: true, default_model: "deepseek/deepseek-chat" },
    }));
    render(
      <SetupWizard
        initialStatus={{
          completed: false,
          required: true,
          model_connected: true,
          default_model: "deepseek/deepseek-chat",
        }}
        onFinished={() => {}}
      />,
    );
    expect(await screen.findByRole("button", { name: "进入工作台" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "下一步" })).toBeNull();
    expect(screen.getByText("准备你的工作台")).toBeTruthy();
    expect(copyAvoidsJargon(document.body.textContent ?? "")).toBe(true);
  });
});
