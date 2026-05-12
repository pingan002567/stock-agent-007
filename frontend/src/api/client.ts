const BASE = "";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, title: string, detail: string) {
    super(title);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type ApiErrorHandler = (err: ApiError) => void;
let _onApiError: ApiErrorHandler | null = null;

export function setOnApiError(handler: ApiErrorHandler | null) {
  _onApiError = handler;
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...options.headers },
      ...options,
    });
  } catch (err) {
    const msg = err instanceof TypeError ? "网络连接失败，请检查后端服务是否已启动" : `请求失败: ${err}`;
    const apiErr = new ApiError(0, "网络错误", msg);
    _onApiError?.(apiErr);
    throw apiErr;
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    const titles: Record<number, string> = {
      401: "认证失败",
      403: "权限不足",
      404: "接口不存在",
      422: "请求参数错误",
      500: "服务端异常",
      502: "网关错误",
      503: "服务暂时不可用",
    };
    const title = titles[res.status] || `HTTP ${res.status}`;
    const apiErr = new ApiError(res.status, title, `${res.status} ${res.statusText}: ${text}`);
    _onApiError?.(apiErr);
    throw apiErr;
  }
  return res.json();
}

export interface AgentRuntimeStatus {
  mode: string;
  available: boolean;
  active_client: string;
  degraded: boolean;
  degraded_reason: string | null;
  model_name: string;
  subagent_enabled: boolean;
  plan_mode: boolean;
  client_capabilities: string[];
  config_path: string | null;
  thinking_enabled: boolean;
}

export interface HealthCheck {
  status: string;
  runtime: string;
  agent_runtime: AgentRuntimeStatus;
  stock_domain: string;
  data_provider: Record<string, unknown>;
}

export interface StockContext {
  symbol: string;
  name: string;
  price: number;
  change: number;
  change_pct: number;
  market_cap: number;
  sector: string;
  [key: string]: unknown;
}

export interface Holding {
  symbol: string;
  name: string;
  quantity: number;
  cost_basis: number;
  current_price: number;
  market_value: number;
  weight_pct: number;
  [key: string]: unknown;
}

export interface PortfolioRisk {
  holdings: Holding[];
  total_value: number;
  risk_metrics: Record<string, unknown>;
  [key: string]: unknown;
}

export interface CopilotSession {
  session_id: string;
  title: string;
  created_at: string;
  message_count?: number;
}

export interface CopilotMessage {
  message_id: string;
  session_id: string;
  role: string;
  kind: string;
  text: string;
  payload: Record<string, unknown>;
  created_at: string;
  run_id: string | null;
}

export interface CopilotRun {
  run_id: string;
  task_id: string;
  session_id: string;
}

export interface Strategy {
  strategy_id: string;
  name: string;
  strategy_type: string;
  enabled: boolean;
  [key: string]: unknown;
}

export interface BacktestRun {
  run_id: string;
  strategy_id: string;
  status: string;
  metrics: Record<string, unknown>;
  created_at: string;
  [key: string]: unknown;
}

export interface MonitorEvent {
  event_id: string;
  title: string;
  severity: string;
  symbol: string;
  triggered_at: string;
  [key: string]: unknown;
}

export interface RebalanceDraft {
  draft_id: string;
  symbol: string;
  action: string;
  status: string;
  [key: string]: unknown;
}

export interface PreTradeReview {
  review_id: string;
  status: string;
  [key: string]: unknown;
}

export interface PaperOrder {
  order_id: string;
  status: string;
  [key: string]: unknown;
}

export interface Report {
  report_id: string;
  report_type: string;
  status: string;
  created_at: string;
  [key: string]: unknown;
}

export interface SettingsData {
  agent_runtime: AgentRuntimeStatus;
  runtime_config?: Record<string, unknown>;
  data_provider?: Record<string, unknown>;
  tools: Record<string, unknown>;
  risk_policy: Record<string, unknown>;
  profiles: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface OverviewData {
  total_value: number;
  holdings_count: number;
  risk_events: number;
  [key: string]: unknown;
}

export const apiGet = <T>(path: string) => api<T>(path);
export const apiPost = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
export const apiPut = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const apiDelete = <T>(path: string) => api<T>(path, { method: "DELETE" });
