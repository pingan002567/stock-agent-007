// 与后端 FastAPI 响应对齐（snake_case）。UI 用到的字段精确定义，其余用 index signature 兜底。

/* ---------- 通用 ---------- */

export interface HealthResponse {
  status: string;
  agent_runtime?: {
    active_client?: string;
    mode?: string;
    model_name?: string;
    degraded?: boolean;
    available?: boolean;
    [key: string]: unknown;
  };
  data_provider?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface Quote {
  last?: number;
  change_pct?: number;
  source?: string;
  degraded?: boolean;
  degraded_reason?: string | null;
  /** 行情过期（缓存太旧） */
  stale?: boolean;
  from_cache?: boolean;
  channel?: string;
  updated_at?: string;
  [key: string]: unknown;
}

/* ---------- 对话 ---------- */

export interface CopilotSession {
  session_id: string;
  title?: string;
  created_at?: string;
  last_message_at?: string;
  message_count?: number;
  [key: string]: unknown;
}

export interface CopilotRun {
  run_id: string;
  session_id?: string;
  task_id?: string;
  status?: string;
  message_id?: string;
  [key: string]: unknown;
}

export interface RunStatus {
  run_id: string;
  status?: string;
  phase?: string;
  current_tool?: string;
  alive?: boolean;
  [key: string]: unknown;
}

export interface BackendMessage {
  message_id?: string;
  session_id?: string;
  run_id?: string;
  role?: string;
  kind?: string;
  /** 消息正文（user_message / final_answer / reasoning 都在这里；tool_* 时是工具名） */
  text?: string;
  payload?: Record<string, unknown>;
  created_at?: string;
  [key: string]: unknown;
}

export interface MessagePage {
  items: BackendMessage[];
  has_more: boolean;
  next_before: string | null;
}

export interface SessionUpload {
  filename: string;
  size?: number;
  markdown_file?: boolean;
  [key: string]: unknown;
}

export interface UploadsResponse {
  supported?: boolean;
  files?: SessionUpload[];
  count?: number;
  [key: string]: unknown;
}

/* ---------- 自选 / 标的 ---------- */

export interface WatchlistItem {
  symbol: string;
  name?: string;
  group?: string;
  monitored?: boolean;
  market?: string;
  price?: Quote;
  quote_degraded?: boolean;
  [key: string]: unknown;
}

export interface StockSearchHit {
  symbol: string;
  name?: string;
  market?: string;
  [key: string]: unknown;
}

export interface StockContext {
  symbol: string;
  name?: string;
  market?: string;
  industry?: string;
  sector?: string;
  price?: Quote;
  summary?: string;
  relation?: { in_holdings?: boolean; in_watchlist?: boolean; monitored?: boolean };
  holding?: { quantity?: number; cost?: number; market_value?: number; pnl_pct?: number; weight_pct?: number };
  ai_state?: { stance?: string; score?: number; confidence?: number; risk_label?: string };
  latest_report?: { report_id?: string; generated_at?: string };
  research_status?: string;
  [key: string]: unknown;
}

export interface HistoryBar {
  date?: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  [key: string]: unknown;
}

export interface IntelItem {
  title?: string;
  source?: string;
  published_at?: string;
  url?: string;
  type?: string;
  [key: string]: unknown;
}

export interface FinancialItem {
  report_date?: string;
  report_type?: string;
  revenue?: number;
  profit?: number;
  total_assets?: number;
  total_liabilities?: number;
  [key: string]: unknown;
}

export interface ResearchTriggerResult {
  status?: string;
  message?: string;
  report_id?: string;
  task_id?: string;
  [key: string]: unknown;
}

/* ---------- 持仓 ---------- */

export interface HoldingItem {
  symbol?: string;
  name?: string;
  quantity?: number;
  /** 折合 CNY 的市值（后端按当天汇率折算，**不落库**） */
  market_value?: number;
  /** 原币市值；加密持仓的 market_value 是折合值，这里才是原币 */
  market_value_native?: number;
  /** 原币币种：CNY / USD / HKD… */
  currency?: string;
  /** CN / HK / US / CRYPTO */
  market?: string;
  cost?: number;
  pnl_pct?: number;
  pnl_amount?: number;
  weight_pct?: number;
  quote?: Quote;
  [key: string]: unknown;
}

export interface CurrencyBucket {
  currency?: string;
  /** 该币种的原币小计 */
  native?: number;
  /** 折合 CNY；无汇率时为 null（不按 1:1 硬算） */
  cny?: number | null;
  count?: number;
}

/** 当日汇率（后端按当天汇率折算，折算值不落库；拿不到汇率时折合类字段为 null） */
export interface FxInfo {
  as_of?: string;
  usd_cny?: number;
  hkd_cny?: number;
  usdt_usd?: number;
  degraded?: boolean;
  degraded_reason?: string;
}

export interface HoldingsSummary {
  /** 折合 CNY；**无汇率时为 null**，不能当 0 处理 */
  total_value?: number | null;
  market_value?: number | null;
  available_cash?: number | null;
  cash_pct?: number | null;
  /** 分币种小计：总资产折合的前提，缺汇率时 cny 为 null */
  by_currency?: CurrencyBucket[];
  positions?: number;
  max_weight_pct?: number;
  source?: string;
  [key: string]: unknown;
}

export interface HoldingsResponse {
  summary?: HoldingsSummary;
  /** 当日汇率与降级信息 */
  fx?: FxInfo;
  items?: HoldingItem[];
  demo?: boolean;
  quotes_degraded_count?: number;
  [key: string]: unknown;
}

/* ---------- 盯盘 ---------- */

export interface MonitorEvent {
  event_id: string;
  symbol?: string;
  title?: string;
  message?: string;
  severity?: string;
  triggered_at?: string;
  rule_id?: string;
  rule_type?: string;
  trigger_rule?: string;
  source?: string;
  evidence?: unknown[];
  suggested_actions?: string[];
  payload?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface MonitorStatus {
  status?: string;
  auto_start?: boolean;
  interval_seconds?: number;
  last_checked_at?: string;
  last_matched_at?: string;
  last_error?: string;
  [key: string]: unknown;
}

export interface MonitorRule {
  rule_id?: string;
  rule_type?: string;
  title?: string;
  symbol?: string;
  threshold?: number;
  keyword?: string;
  severity?: string;
  enabled?: boolean;
  cooldown_seconds?: number;
  trigger_rule?: string;
  source?: string;
  [key: string]: unknown;
}

/* ---------- 策略 / 回测 ---------- */

export interface StrategyItem {
  strategy_id: string;
  name?: string;
  strategy_type?: string;
  description?: string;
  [key: string]: unknown;
}

export interface BacktestMetrics {
  total_return_pct?: number;
  annualized_return_pct?: number;
  max_drawdown_pct?: number;
  sharpe_ratio?: number;
  win_rate?: number;
  [key: string]: unknown;
}

export interface BacktestRun {
  run_id: string;
  strategy_id?: string;
  strategy_name?: string;
  created_at?: string;
  metrics?: BacktestMetrics;
  degraded?: boolean;
  degraded_reason?: string;
  [key: string]: unknown;
}

/* ---------- 定时任务 ---------- */

export interface ScheduledTask {
  task_id: string;
  name?: string;
  prompt?: string;
  schedule?: string;
  enabled?: boolean;
  next_run_at?: string;
  last_run_at?: string;
  last_status?: string;
  last_error?: string;
  last_report_id?: string;
  last_run_id?: string;
  skip_reason?: string;
  [key: string]: unknown;
}

/* ---------- 报告 ---------- */

export interface ReportSummary {
  report_id: string;
  title?: string;
  symbol?: string;
  report_type?: string;
  conclusion?: string;
  generated_at?: string;
  [key: string]: unknown;
}

export interface ReportDetail extends ReportSummary {
  content?: string; // markdown
  [key: string]: unknown;
}

/* ---------- 设置 ---------- */

export interface SkillInfo {
  name?: string;
  /** 后端下发的中文名（能力名），优先于 name 显示 */
  label?: string;
  enabled?: boolean;
  locked?: boolean;
  [key: string]: unknown;
}

export interface MarketRefreshConfig {
  page_refresh_seconds?: number;
  warmup_seconds?: number;
  manual_cooldown_seconds?: number;
  [key: string]: unknown;
}

export interface InvestorProfile {
  risk_level?: string;
  notes?: string;
  [key: string]: unknown;
}

export interface NotificationPrefs {
  duty_completion_push?: boolean;
  [key: string]: unknown;
}

export interface LlmProviderInfo {
  id?: string;
  provider_id?: string;
  name?: string;
  connected?: boolean;
  models?: { id: string; name?: string }[];
  [key: string]: unknown;
}

export interface LlmProvidersSnapshot {
  connected?: LlmProviderInfo[];
  popular?: LlmProviderInfo[];
  catalog?: LlmProviderInfo[];
  default_model?: string;
  runtime?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface CostDay {
  date?: string;
  total_cost?: number;
  total_input_tokens?: number;
  total_output_tokens?: number;
  run_count?: number;
  models?: unknown[];
  [key: string]: unknown;
}

export interface CostSummary {
  days?: CostDay[];
  total?: { total_cost?: number; [key: string]: unknown };
  [key: string]: unknown;
}

export interface WorkbenchSettings {
  skills?: SkillInfo[];
  agent_runtime?: Record<string, unknown>;
  data_provider?: Record<string, unknown>;
  runtime_config?: Record<string, unknown>;
  trading_controls?: Record<string, unknown>;
  market_refresh?: MarketRefreshConfig;
  data_sources?: Record<string, unknown>;
  available_data_providers?: unknown[];
  provider_credential_schema?: Record<string, unknown>;
  llm_providers?: LlmProvidersSnapshot;
  investor_profile?: InvestorProfile;
  notification_prefs?: NotificationPrefs;
  [key: string]: unknown;
}

/* ---------- 客户端轮次模型（流式） ---------- */

export interface ToolChip {
  id: string;
  name: string;
  status: 'running' | 'done';
  resultPreview: string;
}

export interface ClarificationOption {
  id: string;
  label: string;
  value: string;
}

export interface Clarification {
  requestId: string;
  question: string;
  options: ClarificationOption[];
  inputMode: string;
  [key: string]: unknown;
}

export interface SkillTraceStep {
  step?: number;
  skill?: string;
  label?: string;
  status?: string;
  [key: string]: unknown;
}

export type AssistantPhase =
  | 'reasoning'
  | 'tools'
  | 'answering'
  | 'final'
  | 'clarification'
  | 'error';

/** 一轮里的有序步骤：思考与工具按到达顺序交错，用来还原「为什么调这个工具」。
 *
 *  纯文本字段（reasoningText / tools）保留给旧消费方；steps 是新渲染的真相。 */
export type AssistantStep =
  | { kind: 'reasoning'; text: string }
  | { kind: 'tool'; id: string; name: string };

export interface AssistantState {
  phase: AssistantPhase;
  reasoningText: string;
  tools: ToolChip[];
  /** 有序步骤流（思考 / 工具交错） */
  steps: AssistantStep[];
  answerText: string;
  clarification: Clarification | null;
  skillTrace: SkillTraceStep[];
  failed: boolean;
  streaming: boolean;
}

export interface Turn {
  id: string;
  userText: string;
  assistant: AssistantState | null;
  /** 用户消息的发送状态（历史消息为 undefined=已发送） */
  sendState?: 'pending' | 'sent' | 'failed';
}

export function emptyAssistant(): AssistantState {
  return {
    phase: 'reasoning',
    reasoningText: '',
    tools: [],
    steps: [],
    answerText: '',
    clarification: null,
    skillTrace: [],
    failed: false,
    streaming: false,
  };
}
