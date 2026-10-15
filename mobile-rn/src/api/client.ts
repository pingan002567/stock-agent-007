import type { CopilotRun, CopilotSession, HealthResponse } from '../types';

export class ApiError extends Error {}

async function request<T = unknown>(
  baseURL: string,
  token: string,
  path: string,
  init: RequestInit & { json?: unknown } = {}
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (token) headers['X-Workbench-Token'] = token;

  let body: BodyInit | undefined = init.body ?? undefined;
  if (init.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(init.json);
  }

  const res = await fetch(`${baseURL}${path}`, { ...init, headers, body });
  if (!res.ok) {
    throw new ApiError(`HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export function probeHealth(baseURL: string, token: string): Promise<HealthResponse> {
  return request<HealthResponse>(baseURL, token, '/api/health');
}

export function createSession(baseURL: string, token: string): Promise<CopilotSession> {
  return request<CopilotSession>(baseURL, token, '/api/copilot/sessions', {
    method: 'POST',
    json: {
      title: '新对话',
      current_page: 'chat',
      anchor_symbol: null,
      authority_level: 'A4',
      default_model: null,
    },
  });
}

export function sendMessage(
  baseURL: string,
  token: string,
  sessionId: string,
  message: string
): Promise<CopilotRun> {
  return request<CopilotRun>(baseURL, token, `/api/copilot/sessions/${sessionId}/messages`, {
    method: 'POST',
    json: {
      message,
      page: 'chat',
      symbol: '',
      authority_level: 'A4',
      client_message_id: `rn-${Date.now()}`,
    },
  });
}

export function streamURL(
  baseURL: string,
  token: string,
  sessionId: string,
  runId: string
): string {
  const q = token ? `?access_token=${encodeURIComponent(token)}` : '';
  return `${baseURL}/api/copilot/sessions/${sessionId}/stream/${runId}${q}`;
}
