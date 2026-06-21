import { api } from "./client";
import type { CopilotSession, CopilotMessage, CopilotRun } from "./client";

// ── 规范化事件类型常量 ──
export const EVENT_FINAL = "final";
export const EVENT_ERROR = "error";
export const EVENT_TOOL_CALL = "tool_call";
export const EVENT_TOOL_RESULT = "tool_result";
export const EVENT_PARTIAL_ANSWER = "partial_answer";
export const EVENT_REASONING = "reasoning";
export const EVENT_SKILL_TRACE = "skill_trace";

export async function fetchSessions(): Promise<CopilotSession[]> {
  const data = await api<{ items: CopilotSession[] }>("/api/copilot/sessions");
  return data.items || [];
}

export async function fetchSessionMessages(sessionId: string, runId?: string): Promise<CopilotMessage[]> {
  const params = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  const data = await api<{ items: CopilotMessage[] }>(
    `/api/copilot/sessions/${encodeURIComponent(sessionId)}/messages${params}`
  );
  return data.items || [];
}

// Single-user local workbench: there is no per-session authority selector in
// the UI yet, so all copilot traffic runs at this default level. Centralize the
// value here instead of scattering the magic string across call sites.
export const DEFAULT_AUTHORITY_LEVEL = "A4";

export async function createSession(
  title: string,
  page: string = "overview",
  symbol: string | null = null,
): Promise<CopilotSession> {
  return api<CopilotSession>("/api/copilot/sessions", {
    method: "POST",
    body: JSON.stringify({
      title,
      current_page: page,
      anchor_symbol: symbol,
      authority_level: DEFAULT_AUTHORITY_LEVEL,
    }),
  });
}

export async function updateSession(
  sessionId: string,
  title: string,
): Promise<CopilotSession> {
  return api<CopilotSession>(`/api/copilot/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PUT",
    body: JSON.stringify({ title }),
  });
}

export async function deleteSession(sessionId: string): Promise<void> {
  await api(`/api/copilot/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export async function sendMessage(
  sessionId: string,
  message: string,
  page: string,
  symbol: string
): Promise<CopilotRun> {
  return api<CopilotRun>(
    `/api/copilot/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      body: JSON.stringify({
        message,
        page,
        symbol,
        authority_level: DEFAULT_AUTHORITY_LEVEL,
        client_message_id: `web-${Date.now()}`,
      }),
    }
  );
}

export function createStreamUrl(sessionId: string, runId: string): string {
  return `/api/copilot/sessions/${encodeURIComponent(sessionId)}/stream/${encodeURIComponent(runId)}`;
}

export function parseCopilotEvent(source: Record<string, unknown>) {
  if (!source) return { type: EVENT_FINAL, payload: {}, text: "" };
  if (source.type && source.payload) {
    return {
      type: source.type as string,
      payload: (source.payload as Record<string, unknown>) || {},
      text:
        (source.text as string) ||
        ((source.payload as Record<string, unknown>)?.text as string) ||
        ((source.payload as Record<string, unknown>)?.conclusion as string) ||
        "",
      role: (source.role as string) || null,
      created_at: (source.created_at as string) || null,
    };
  }
  const mapping: Record<string, string> = {
    skill_trace: EVENT_SKILL_TRACE,
    tool_call: EVENT_TOOL_CALL,
    tool_result: EVENT_TOOL_RESULT,
    partial_answer: EVENT_PARTIAL_ANSWER,
    reasoning: EVENT_REASONING,
    error: EVENT_ERROR,
    final_answer: EVENT_FINAL,
  };
  return {
    type: mapping[(source.kind as string) || ""] || "unknown",
    payload: (source.payload as Record<string, unknown>) || {},
    text: (source.text as string) || "",
    role: (source.role as string) || null,
    created_at: (source.created_at as string) || null,
  };
}
