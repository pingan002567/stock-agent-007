import { api, apiUrl } from "./client";
import { authHeaders, withAccessToken } from "@/lib/connection";
import type { CopilotSession, CopilotMessage, CopilotRun } from "./client";
import type { HumanInputResponse } from "@/lib/humanInput";

// ── 规范化事件类型常量 ──
export const EVENT_FINAL = "final";
export const EVENT_ERROR = "error";
export const EVENT_TOOL_CALL = "tool_call";
export const EVENT_TOOL_RESULT = "tool_result";
export const EVENT_PARTIAL_ANSWER = "partial_answer";
export const EVENT_REASONING = "reasoning";
export const EVENT_SKILL_TRACE = "skill_trace";
export const EVENT_CLARIFICATION = "clarification";

// ── skill_trace payload 条目（声明式技能链路，final payload 与 skill_trace 事件共用） ──
export interface SkillTraceItem {
  step?: number;
  skill?: string;
  label?: string;
  authority_level?: string;
  status?: string;
  purpose?: string;
  blocked_reason?: string | null;
}

export function skillTraceItems(v: unknown): SkillTraceItem[] {
  if (!Array.isArray(v)) return [];
  return v.filter((item): item is SkillTraceItem => !!item && typeof item === "object");
}

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
  defaultModel: string | null = null,
): Promise<CopilotSession> {
  return api<CopilotSession>("/api/copilot/sessions", {
    method: "POST",
    body: JSON.stringify({
      title,
      current_page: page,
      anchor_symbol: symbol,
      authority_level: DEFAULT_AUTHORITY_LEVEL,
      default_model: defaultModel,
    }),
  });
}

export async function updateSession(
  sessionId: string,
  patch: { title?: string; default_model?: string | null },
): Promise<CopilotSession> {
  return api<CopilotSession>(`/api/copilot/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PUT",
    body: JSON.stringify(patch),
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
  symbol: string,
  attachments: UploadedFileInfo[] = [],
  humanInputResponse?: HumanInputResponse | null,
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
        attachments,
        ...(humanInputResponse ? { human_input_response: humanInputResponse } : {}),
      }),
    }
  );
}

export interface UploadedFileInfo {
  filename: string;
  size: number;
  markdown_file?: string | null;
}

export interface SessionUploadsList {
  supported: boolean;
  files: UploadedFileInfo[];
  count: number;
}

async function readUploadError(res: Response, fallback: string): Promise<never> {
  let detail = `${res.status}`;
  try {
    const body = await res.json();
    detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? body);
  } catch { /* empty */ }
  throw new Error(`${fallback}: ${detail}`);
}

export async function uploadSessionFiles(
  sessionId: string,
  files: File[],
): Promise<{ success: boolean; files: UploadedFileInfo[]; message?: string }> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  // multipart 不能走 api() 包装（它会强制 JSON Content-Type），直接 fetch
  const res = await fetch(apiUrl(`/api/copilot/sessions/${encodeURIComponent(sessionId)}/uploads`), {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  if (!res.ok) await readUploadError(res, "上传失败");
  return res.json();
}

export function sessionUploadsFromHttp(
  status: number,
  body: Partial<SessionUploadsList> | null | undefined,
): SessionUploadsList {
  // 旧后端只有 POST /uploads，GET 是 FastAPI 通用 404 {"detail":"Not Found"}。
  // 切会话时不能因此弹红字；按空列表降级，上传成功仍可用 POST 返回值填芯片。
  if (status === 404) {
    return { supported: true, files: [], count: 0 };
  }
  return {
    supported: body?.supported !== false,
    files: body?.files || [],
    count: body?.count ?? (body?.files || []).length,
  };
}

export async function listSessionUploads(sessionId: string): Promise<SessionUploadsList> {
  // 不走 api()：stub 用 200 {supported:false} 表达能力，全局错误 toast 会误伤
  const res = await fetch(apiUrl(`/api/copilot/sessions/${encodeURIComponent(sessionId)}/uploads`), {
    headers: authHeaders(),
  });
  if (res.status === 404) return sessionUploadsFromHttp(404, null);
  if (!res.ok) await readUploadError(res, "读取附件失败");
  const body = await res.json() as SessionUploadsList;
  return sessionUploadsFromHttp(res.status, body);
}

export async function deleteSessionUpload(sessionId: string, filename: string): Promise<void> {
  const res = await fetch(
    apiUrl(`/api/copilot/sessions/${encodeURIComponent(sessionId)}/uploads/${encodeURIComponent(filename)}`),
    { method: "DELETE", headers: authHeaders() },
  );
  if (!res.ok) await readUploadError(res, "删除附件失败");
}

export function createStreamUrl(sessionId: string, runId: string): string {
  return withAccessToken(
    apiUrl(`/api/copilot/sessions/${encodeURIComponent(sessionId)}/stream/${encodeURIComponent(runId)}`),
  );
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
    clarification: EVENT_CLARIFICATION,
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
