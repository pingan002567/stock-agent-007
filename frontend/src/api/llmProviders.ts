import { apiDelete, apiGet, apiPost, apiPut, ApiError } from "./client";
import type { ConnectionTestResult } from "./runtime";

export interface LlmModel {
  id: string;
  name: string;
}

export interface LlmProviderItem {
  id: string;
  name: string;
  base_url: string;
  popular: boolean;
  requires_key: boolean;
  note: string | null;
  models: LlmModel[];
  connected: boolean;
  source: "api" | "custom" | string | null;
  can_disconnect: boolean;
  has_key: boolean;
  custom: boolean;
}

export interface LlmRuntimeView {
  default_model: string | null;
  provider_id: string | null;
  provider_name: string | null;
  model_id: string | null;
  source: string | null;
  connected: boolean;
  agent_runtime?: Record<string, unknown> | null;
}

export interface LlmProvidersSnapshot {
  connected: LlmProviderItem[];
  popular: LlmProviderItem[];
  catalog: LlmProviderItem[];
  default_model: string | null;
  runtime: LlmRuntimeView;
}

export interface CustomProviderPayload {
  id: string;
  name: string;
  base_url: string;
  api_key?: string;
  models: LlmModel[];
  headers?: Record<string, string> | Array<{ key: string; value: string }>;
}

export function fetchLlmProviders(): Promise<LlmProvidersSnapshot> {
  return apiGet<LlmProvidersSnapshot>("/api/settings/llm/providers");
}

export function connectLlmProvider(providerId: string, apiKey?: string): Promise<LlmProvidersSnapshot> {
  return apiPost<LlmProvidersSnapshot>("/api/settings/llm/connect", {
    provider_id: providerId,
    api_key: apiKey || undefined,
  });
}

export function disconnectLlmProvider(providerId: string): Promise<LlmProvidersSnapshot> {
  return apiDelete<LlmProvidersSnapshot>(
    `/api/settings/llm/providers/${encodeURIComponent(providerId)}`,
  );
}

export function upsertCustomLlmProvider(payload: CustomProviderPayload): Promise<LlmProvidersSnapshot> {
  return apiPost<LlmProvidersSnapshot>("/api/settings/llm/custom", payload);
}

export function setDefaultLlmModel(defaultModel: string): Promise<LlmProvidersSnapshot> {
  return apiPut<LlmProvidersSnapshot>("/api/settings/llm/default-model", {
    default_model: defaultModel,
  });
}

export function testLlmConnection(payload: {
  provider_id?: string;
  api_key?: string;
  base_url?: string;
  model_name?: string;
} = {}): Promise<ConnectionTestResult> {
  return apiPost<ConnectionTestResult>("/api/settings/llm/test", payload);
}

export function sourceLabel(source: string | null | undefined): string {
  if (source === "api") return "API Key";
  if (source === "custom") return "自定义";
  return source || "";
}

export function llmErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      const raw = err.detail.includes("{") ? err.detail.slice(err.detail.indexOf("{")) : "";
      const parsed = raw ? JSON.parse(raw) as { detail?: unknown } : null;
      if (typeof parsed?.detail === "string") return parsed.detail;
      if (parsed?.detail && typeof parsed.detail === "object" && parsed.detail !== null && "error" in parsed.detail) {
        return String((parsed.detail as { error?: string }).error);
      }
    } catch { /* ignore */ }
    return err.detail || err.message;
  }
  return err instanceof Error ? err.message : String(err);
}
