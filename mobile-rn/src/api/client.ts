import type {
  BacktestRun,
  BackendMessage,
  CopilotRun,
  CopilotSession,
  CostSummary,
  FinancialItem,
  HealthResponse,
  HoldingItem,
  HoldingsResponse,
  IntelItem,
  InvestorProfile,
  LlmProvidersSnapshot,
  MarketRefreshConfig,
  MessagePage,
  MonitorEvent,
  MonitorRule,
  MonitorStatus,
  NotificationPrefs,
  ReportDetail,
  ReportSummary,
  ResearchTriggerResult,
  RunStatus,
  ScheduledTask,
  SessionUpload,
  StockContext,
  StockSearchHit,
  StrategyItem,
  UploadsResponse,
  WatchlistItem,
  WorkbenchSettings,
  HistoryBar,
} from '../types';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}

/** 401/403 回调：由 App 注册，用于把「令牌失效」暴露到界面上（对齐 iOS auth-failure 处理） */
let authFailureHandler: (() => void) | null = null;
export function setAuthFailureHandler(fn: (() => void) | null) {
  authFailureHandler = fn;
}

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
    if (res.status === 401 || res.status === 403) authFailureHandler?.();
    let detail = '';
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data?.detail === 'string') detail = data.detail;
    } catch {
      /* ignore */
    }
    if (!detail) {
      detail = res.status === 401 ? '访问令牌无效或已过期（HTTP 401）' : `请求被拒绝（HTTP ${res.status}）`;
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

function enc(v: string): string {
  return encodeURIComponent(v);
}

/* ================= 健康 / 连接 ================= */

export function probeHealth(baseURL: string, token: string): Promise<HealthResponse> {
  return request<HealthResponse>(baseURL, token, '/api/health');
}

/* ================= 会话 / 对话 ================= */

export async function fetchSessions(baseURL: string, token: string): Promise<CopilotSession[]> {
  const data = await request<{ items?: CopilotSession[] }>(baseURL, token, '/api/copilot/sessions');
  return data.items ?? [];
}

export function createSession(baseURL: string, token: string, title = '新对话'): Promise<CopilotSession> {
  return request<CopilotSession>(baseURL, token, '/api/copilot/sessions', {
    method: 'POST',
    json: { title, current_page: 'chat', anchor_symbol: null, authority_level: 'A4', default_model: null },
  });
}

export function renameSession(baseURL: string, token: string, id: string, title: string): Promise<CopilotSession> {
  return request<CopilotSession>(baseURL, token, `/api/copilot/sessions/${enc(id)}`, { method: 'PUT', json: { title } });
}

export function deleteSession(baseURL: string, token: string, id: string): Promise<unknown> {
  return request(baseURL, token, `/api/copilot/sessions/${enc(id)}`, { method: 'DELETE' });
}

export async function fetchMessages(
  baseURL: string,
  token: string,
  sessionId: string,
  opts: { limitTurns?: number; before?: string } = {}
): Promise<MessagePage> {
  const query: string[] = [];
  if (opts.limitTurns != null) query.push(`limit_turns=${opts.limitTurns}`);
  if (opts.before) query.push(`before=${encodeURIComponent(opts.before)}`);
  const qs = query.length ? `?${query.join('&')}` : '';
  const data = await request<{ items?: BackendMessage[]; has_more?: boolean; next_before?: string }>(
    baseURL,
    token,
    `/api/copilot/sessions/${enc(sessionId)}/messages${qs}`
  );
  return { items: data.items ?? [], has_more: data.has_more ?? false, next_before: (data.next_before as string) ?? null };
}

export function sendMessage(
  baseURL: string,
  token: string,
  sessionId: string,
  message: string,
  attachments: SessionUpload[] = [],
  humanInputResponse?: Record<string, unknown>,
  context?: { page?: string; symbol?: string }
): Promise<CopilotRun> {
  const body: Record<string, unknown> = {
    message,
    page: context?.page ?? 'chat',
    symbol: context?.symbol ?? '',
    authority_level: 'A4',
    client_message_id: `rn-${Date.now()}`,
    attachments: attachments.map((a) => ({ filename: a.filename, size: a.size, markdown_file: a.markdown_file })),
  };
  if (humanInputResponse) body['human_input_response'] = humanInputResponse;
  return request<CopilotRun>(baseURL, token, `/api/copilot/sessions/${enc(sessionId)}/messages`, { method: 'POST', json: body });
}

export function cancelRun(baseURL: string, token: string, sessionId: string, runId: string): Promise<unknown> {
  return request(baseURL, token, `/api/copilot/sessions/${enc(sessionId)}/runs/${enc(runId)}/cancel`, { method: 'POST' });
}

export function fetchRunStatus(baseURL: string, token: string, sessionId: string, runId: string): Promise<RunStatus> {
  return request<RunStatus>(baseURL, token, `/api/copilot/sessions/${enc(sessionId)}/runs/${enc(runId)}/status`);
}

export function streamURL(baseURL: string, token: string, sessionId: string, runId: string): string {
  const q = token ? `?access_token=${encodeURIComponent(token)}` : '';
  return `${baseURL}/api/copilot/sessions/${enc(sessionId)}/stream/${enc(runId)}${q}`;
}

export function listUploads(baseURL: string, token: string, sessionId: string): Promise<UploadsResponse> {
  return request<UploadsResponse>(baseURL, token, `/api/copilot/sessions/${enc(sessionId)}/uploads`);
}

export function deleteUpload(baseURL: string, token: string, sessionId: string, filename: string): Promise<unknown> {
  return request(baseURL, token, `/api/copilot/sessions/${enc(sessionId)}/uploads/${enc(filename)}`, { method: 'DELETE' });
}

export async function uploadFiles(
  baseURL: string,
  token: string,
  sessionId: string,
  files: { uri: string; name: string; mimeType: string }[]
): Promise<UploadsResponse> {
  const form = new FormData();
  for (const f of files) {
    form.append('files', { uri: f.uri, name: f.name, type: f.mimeType || 'application/octet-stream' } as unknown as Blob);
  }
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers['X-Workbench-Token'] = token;
  const res = await fetch(`${baseURL}/api/copilot/sessions/${enc(sessionId)}/uploads`, { method: 'POST', headers, body: form });
  if (!res.ok) throw new ApiError(`HTTP ${res.status}`);
  try {
    return (await res.json()) as UploadsResponse;
  } catch {
    return listUploads(baseURL, token, sessionId);
  }
}

/* ================= 自选 / 标的 ================= */

export async function fetchWatchlist(baseURL: string, token: string): Promise<WatchlistItem[]> {
  const data = await request<WatchlistItem[]>(baseURL, token, '/api/watchlist');
  return Array.isArray(data) ? data : [];
}

export function addWatchlistItem(baseURL: string, token: string, symbol: string, name: string): Promise<unknown> {
  return request(baseURL, token, '/api/watchlist/items', {
    method: 'POST',
    json: { symbol, name, group: '观察池', tags: [], monitored: false },
  });
}

export function deleteWatchlistItem(baseURL: string, token: string, symbol: string): Promise<unknown> {
  return request(baseURL, token, `/api/watchlist/items/${enc(symbol)}`, { method: 'DELETE' });
}

export async function searchStocks(baseURL: string, token: string, q: string): Promise<StockSearchHit[]> {
  const data = await request<{ items?: StockSearchHit[] }>(baseURL, token, `/api/stocks/search?q=${encodeURIComponent(q)}`);
  return data.items ?? [];
}

export function fetchStockContext(baseURL: string, token: string, symbol: string): Promise<StockContext> {
  return request<StockContext>(baseURL, token, `/api/stocks/${enc(symbol)}/context`);
}

export async function fetchStockHistory(baseURL: string, token: string, symbol: string, days = 90): Promise<HistoryBar[]> {
  const data = await request<{ items?: HistoryBar[] }>(baseURL, token, `/api/stocks/${enc(symbol)}/history?days=${days}`);
  return data.items ?? [];
}

export async function fetchStockIntel(baseURL: string, token: string, symbol: string): Promise<IntelItem[]> {
  const data = await request<{ items?: IntelItem[] }>(baseURL, token, `/api/stocks/${enc(symbol)}/intel`);
  return data.items ?? [];
}

export async function fetchStockFinancial(baseURL: string, token: string, symbol: string): Promise<FinancialItem[]> {
  const data = await request<{ items?: FinancialItem[]; degraded?: boolean }>(baseURL, token, `/api/stocks/${enc(symbol)}/financial`);
  return data.items ?? [];
}

export function triggerStockResearch(baseURL: string, token: string, symbol: string): Promise<ResearchTriggerResult> {
  return request<ResearchTriggerResult>(baseURL, token, `/api/stocks/${enc(symbol)}/research`, { method: 'POST', json: {} });
}

/* ================= 持仓 ================= */

/** 新增/修改单笔持仓。市值按「现价优先、否则成本」计算，**存原币**。
 *  currency 留空时后端按 market 推断（CN→CNY / HK→HKD / US→USD / CRYPTO→USDT）。 */
export function upsertHolding(
  baseURL: string,
  token: string,
  payload: { symbol: string; quantity: number; cost?: number; currency?: string },
): Promise<unknown> {
  return request(baseURL, token, '/api/holdings', { method: 'POST', json: payload });
}

export function fetchHoldings(baseURL: string, token: string): Promise<HoldingsResponse> {
  return request<HoldingsResponse>(baseURL, token, '/api/holdings');
}

/* ================= 盯盘 ================= */

export async function fetchMonitorEvents(baseURL: string, token: string, page = 1, pageSize = 30): Promise<{ items: MonitorEvent[]; total: number }> {
  const data = await request<{ items?: MonitorEvent[]; total?: number }>(
    baseURL,
    token,
    `/api/monitor/events?page=${page}&page_size=${pageSize}`
  );
  return { items: data.items ?? [], total: data.total ?? 0 };
}

export function fetchMonitorStatus(baseURL: string, token: string): Promise<MonitorStatus> {
  return request<MonitorStatus>(baseURL, token, '/api/monitor/status');
}

export function startMonitor(baseURL: string, token: string): Promise<MonitorStatus> {
  return request<MonitorStatus>(baseURL, token, '/api/monitor/start', { method: 'POST', json: {} });
}

export function pauseMonitor(baseURL: string, token: string): Promise<MonitorStatus> {
  return request<MonitorStatus>(baseURL, token, '/api/monitor/pause', { method: 'POST', json: {} });
}

export async function fetchMonitorRules(baseURL: string, token: string): Promise<MonitorRule[]> {
  const data = await request<{ items?: MonitorRule[] }>(baseURL, token, '/api/monitor/rules');
  return data.items ?? [];
}

export function upsertMonitorRule(baseURL: string, token: string, body: Record<string, unknown>): Promise<MonitorRule> {
  return request<MonitorRule>(baseURL, token, '/api/monitor/rules', { method: 'POST', json: body });
}

export function deleteMonitorRule(baseURL: string, token: string, id: string): Promise<unknown> {
  return request(baseURL, token, `/api/monitor/rules/${enc(id)}`, { method: 'DELETE' });
}

export function evaluateMonitorOnce(baseURL: string, token: string, force = false): Promise<Record<string, unknown>> {
  return request(baseURL, token, '/api/monitor/evaluate-once', { method: 'POST', json: { source: 'android_manual', force } });
}

export function sendMonitorFeedback(baseURL: string, token: string, ruleId: string, wasUseful: boolean): Promise<unknown> {
  return request(baseURL, token, '/api/monitor/feedback', { method: 'POST', json: { rule_id: ruleId, was_useful: wasUseful } });
}

/* ================= 策略 / 回测 ================= */

export async function fetchStrategies(baseURL: string, token: string): Promise<StrategyItem[]> {
  const data = await request<{ items?: StrategyItem[] }>(baseURL, token, '/api/strategies');
  return data.items ?? [];
}

export async function fetchLatestBacktest(baseURL: string, token: string, strategyId: string): Promise<BacktestRun | null> {
  try {
    return await request<BacktestRun>(baseURL, token, `/api/strategies/${enc(strategyId)}/backtests/latest`);
  } catch {
    return null;
  }
}

export function runBacktest(baseURL: string, token: string, strategyId: string): Promise<BacktestRun> {
  return request<BacktestRun>(baseURL, token, `/api/strategies/${enc(strategyId)}/backtest`, { method: 'POST', json: {} });
}

export function fetchBacktest(baseURL: string, token: string, runId: string): Promise<BacktestRun> {
  return request<BacktestRun>(baseURL, token, `/api/backtests/${enc(runId)}`);
}

/* ================= 定时任务 ================= */

export async function fetchScheduledTasks(baseURL: string, token: string): Promise<ScheduledTask[]> {
  const data = await request<{ items?: ScheduledTask[] }>(baseURL, token, '/api/scheduled-tasks');
  return data.items ?? [];
}

export function toggleScheduledTask(baseURL: string, token: string, taskId: string, enabled: boolean): Promise<ScheduledTask> {
  return request<ScheduledTask>(baseURL, token, `/api/scheduled-tasks/${enc(taskId)}/toggle`, { method: 'POST', json: { enabled } });
}

export function runScheduledTaskNow(baseURL: string, token: string, taskId: string): Promise<unknown> {
  return request(baseURL, token, `/api/scheduled-tasks/${enc(taskId)}/run-now`, { method: 'POST', json: {} });
}

/* ================= 报告 ================= */

export async function fetchReports(baseURL: string, token: string, page = 1, pageSize = 20): Promise<{ items: ReportSummary[]; total: number }> {
  const data = await request<{ items?: ReportSummary[]; total?: number }>(baseURL, token, `/api/reports?page=${page}&page_size=${pageSize}`);
  return { items: data.items ?? [], total: data.total ?? 0 };
}

export function fetchReport(baseURL: string, token: string, reportId: string): Promise<ReportDetail> {
  return request<ReportDetail>(baseURL, token, `/api/reports/${enc(reportId)}`);
}

/* ================= 设置 / 运行时 ================= */

export function fetchSettings(baseURL: string, token: string): Promise<WorkbenchSettings> {
  return request<WorkbenchSettings>(baseURL, token, '/api/settings');
}

/** 思考模式开关：后端 PUT /api/settings/runtime 是**整体覆盖** runtime 配置，
 *  所以要先取当前值再合并，且不能回传 api_key（凭证走用户级文件）。 */
export async function setThinkingEnabled(baseURL: string, token: string, enabled: boolean): Promise<unknown> {
  const settings = await fetchSettings(baseURL, token);
  const runtime = { ...((settings.runtime_config ?? {}) as Record<string, unknown>) };
  delete runtime.api_key;
  delete runtime.has_api_key;
  return request(baseURL, token, '/api/settings/runtime', {
    method: 'PUT',
    json: { ...runtime, thinking_enabled: enabled },
  });
}

/** 当前生效的风控策略（含 rules：单票/行业/ETF/加密上限等） */
export interface RiskPolicyRules {
  single_position_max_weight_pct?: number;
  sector_max_weight_pct?: number;
  etf_max_weight_pct?: number;
  crypto_max_weight_pct?: number;
  single_position_max_loss_pct_of_nav?: number;
  [key: string]: unknown;
}

export interface RiskPolicy {
  policy_id?: string;
  name?: string;
  description?: string;
  is_active?: boolean;
  rules?: RiskPolicyRules;
  [key: string]: unknown;
}

export async function fetchActiveRiskPolicy(baseURL: string, token: string): Promise<RiskPolicy | null> {
  try {
    return await request<RiskPolicy>(baseURL, token, '/api/risk-policies/active');
  } catch {
    return null;
  }
}

/** 更新风控策略：后端 PUT 收整条 RiskPolicy，所以要先取原值再合并 rules */
export async function updateRiskPolicy(
  baseURL: string,
  token: string,
  policy: RiskPolicy,
  rulesPatch: RiskPolicyRules,
): Promise<RiskPolicy> {
  const id = String(policy.policy_id ?? '');
  const body = {
    name: policy.name ?? '默认档',
    description: policy.description ?? '',
    is_active: policy.is_active ?? true,
    rules: { ...(policy.rules ?? {}), ...rulesPatch },
  };
  return request<RiskPolicy>(baseURL, token, `/api/risk-policies/${enc(id)}`, { method: 'PUT', json: body });
}

/** 情报与舆情配置：providers = { news_search: {provider,enabled,api_key}, social_sentiment: {...} } */
export interface IntelSourcesConfig {
  providers: Record<string, { provider?: string; enabled?: boolean; api_key?: string | null; label?: string; description?: string }>;
}

export function updateIntelSources(baseURL: string, token: string, config: IntelSourcesConfig): Promise<unknown> {
  return request(baseURL, token, '/api/settings/intel-sources', { method: 'PUT', json: config });
}

export function setSkillEnabled(baseURL: string, token: string, name: string, enabled: boolean): Promise<unknown> {
  return request(baseURL, token, '/api/settings/skills', { method: 'PUT', json: { name, enabled } });
}

export function updateMarketRefresh(baseURL: string, token: string, config: MarketRefreshConfig): Promise<MarketRefreshConfig> {
  return request<MarketRefreshConfig>(baseURL, token, '/api/settings/market-refresh', { method: 'PUT', json: config });
}

export function updateInvestorProfile(baseURL: string, token: string, profile: InvestorProfile): Promise<InvestorProfile> {
  return request<InvestorProfile>(baseURL, token, '/api/settings/investor-profile', { method: 'PUT', json: profile });
}

export function updateNotificationPrefs(baseURL: string, token: string, prefs: NotificationPrefs): Promise<NotificationPrefs> {
  return request<NotificationPrefs>(baseURL, token, '/api/settings/notification-prefs', { method: 'PUT', json: prefs });
}

export function updateDataSources(baseURL: string, token: string, config: Record<string, unknown>): Promise<unknown> {
  return request(baseURL, token, '/api/settings/data-provider', { method: 'PUT', json: config });
}

export function fetchLlmProviders(baseURL: string, token: string): Promise<LlmProvidersSnapshot> {
  return request<LlmProvidersSnapshot>(baseURL, token, '/api/settings/llm/providers');
}

export function setDefaultLlmModel(baseURL: string, token: string, modelRef: string): Promise<LlmProvidersSnapshot> {
  return request<LlmProvidersSnapshot>(baseURL, token, '/api/settings/llm/default-model', { method: 'PUT', json: { default_model: modelRef } });
}

export function connectLlmProvider(baseURL: string, token: string, providerId: string, apiKey?: string): Promise<LlmProvidersSnapshot> {
  const json: Record<string, unknown> = { provider_id: providerId };
  if (apiKey && apiKey.trim()) json.api_key = apiKey.trim();
  return request<LlmProvidersSnapshot>(baseURL, token, '/api/settings/llm/connect', { method: 'POST', json });
}

export function disconnectLlmProvider(baseURL: string, token: string, providerId: string): Promise<LlmProvidersSnapshot> {
  return request<LlmProvidersSnapshot>(baseURL, token, `/api/settings/llm/providers/${enc(providerId)}`, { method: 'DELETE' });
}

export async function fetchCostSummary(baseURL: string, token: string): Promise<CostSummary> {
  return request<CostSummary>(baseURL, token, '/api/runtime/cost-summary');
}
