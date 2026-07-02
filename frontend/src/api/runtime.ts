import { apiDelete, apiGet, apiPost, apiPut } from "./client";

export interface RuntimeMetricSnapshot {
  snapshot_id: string;
  created_at: string;
  payload: {
    provider?: {
      total_calls?: number;
      failure_count?: number;
      fallback_count?: number;
      avg_duration_ms?: number;
      last_degraded_reason?: string | null;
    };
    copilot?: {
      total_runs?: number;
      failure_count?: number;
      avg_tool_calls?: number;
      usage_input_tokens?: number;
      usage_output_tokens?: number;
      total_cost?: number;
      avg_cost?: number;
      avg_latency_ms?: number;
      error_distribution?: Record<string, number>;
    };
  };
}

export interface ProviderEvent {
  call_id: string;
  capability: string;
  market?: string | null;
  provider: string;
  fallback_provider: string;
  status: string;
  degraded_reason?: string | null;
  duration_ms: number;
  created_at: string;
}

export interface CopilotRunLog {
  run_id: string;
  session_id?: string | null;
  task_id?: string | null;
  mode: string;
  active_client: string;
  model_name?: string | null;
  status: string;
  error_category?: string | null;
  runtime_error?: string | null;
  tool_call_count: number;
  usage_input_tokens?: number | null;
  usage_output_tokens?: number | null;
  cost?: number | null;
  latency_ms?: number | null;
  started_at?: string | null;
  created_at: string;
  updated_at: string;
}

export async function fetchRuntimeMetrics(): Promise<RuntimeMetricSnapshot> {
  return apiGet<RuntimeMetricSnapshot>("/api/runtime/metrics");
}

export async function fetchProviderEvents(): Promise<ProviderEvent[]> {
  const data = await apiGet<{ items: ProviderEvent[] }>("/api/runtime/provider-events");
  return data.items || [];
}

export async function fetchCopilotRuns(): Promise<CopilotRunLog[]> {
  const data = await apiGet<{ items: CopilotRunLog[] }>("/api/runtime/copilot-runs");
  return data.items || [];
}

export interface RegressionCase {
  case_id: string;
  message: string;
  page: string;
  symbol?: string;
  mode: string;
  requires_deerflow?: boolean;
  expected_tools?: string[];
}

export async function fetchRegressionCases(): Promise<RegressionCase[]> {
  const data = await apiGet<{ items: RegressionCase[] }>("/api/runtime/regression-cases");
  return data.items || [];
}

export interface ConnectionTestResult {
  ok: boolean;
  model?: string;
  base_url?: string;
  latency_ms?: number;
  error?: string;
}

export async function reconnectRuntime(): Promise<{ ok: boolean; agent_runtime: Record<string, unknown> }> {
  return apiPost("/api/runtime/reconnect", {});
}

export async function testConnection(payload: {
  api_key?: string;
  base_url?: string;
  model_name?: string;
}): Promise<ConnectionTestResult> {
  return apiPost("/api/runtime/test-connection", payload);
}

// ── AI 记忆管理 ──

export interface MemoryFact {
  id: string;
  content: string;
  category?: string;
  confidence?: number;
}

export interface MemoryStatus {
  supported: boolean;
  error?: string;
  config?: { enabled?: boolean; max_facts?: number; injection_enabled?: boolean };
  data?: { facts?: MemoryFact[]; user?: Record<string, unknown> };
}

export async function fetchMemoryStatus(): Promise<MemoryStatus> {
  return apiGet<MemoryStatus>("/api/runtime/memory");
}

export async function clearMemory(): Promise<{ supported: boolean }> {
  return apiDelete("/api/runtime/memory");
}

export async function createMemoryFact(payload: {
  content: string;
  category?: string;
  confidence?: number;
}): Promise<{ supported: boolean }> {
  return apiPost("/api/runtime/memory/facts", payload);
}

export async function updateMemoryFact(
  factId: string,
  payload: { content?: string; category?: string; confidence?: number },
): Promise<{ supported: boolean }> {
  return apiPut(`/api/runtime/memory/facts/${encodeURIComponent(factId)}`, payload);
}

export async function deleteMemoryFact(factId: string): Promise<{ supported: boolean }> {
  return apiDelete(`/api/runtime/memory/facts/${encodeURIComponent(factId)}`);
}
