import { useState, useRef, useCallback, useEffect, useMemo, createContext, useContext, createElement, type ReactNode } from "react";
import { useAppState } from "@/hooks/useAppState";
import {
  createSession,
  fetchSessions,
  fetchSessionMessages,
  sendMessage,
  createStreamUrl,
  updateSession,
  deleteSession,
  type UploadedFileInfo,
} from "@/api/copilot";
import type { CopilotSession, CopilotMessage } from "@/api/client";
import { skillTraceItems, type SkillTraceItem } from "@/api/copilot";
import { parseTaskToolArgs } from "@/components/features/taskToolMeta";
import {
  createHumanInputTextResponse,
  parseHumanInputRequest,
  type HumanInputResponse,
} from "@/lib/humanInput";
import { isUsableSessionTitle } from "@/lib/sessionTitle";

// ── Streaming message types ──

export interface StreamToolCall {
  callId: string;
  name: string;
  status: "running" | "done" | "failed";
  resultText?: string;
  /** task 委派时的子代理类型(subagent_type) */
  subagentType?: string;
  /** task 工具的 description 字段（短标题） */
  taskDescription?: string;
  /** task 工具的 prompt 字段（完整指令，展示截断） */
  taskPrompt?: string;
}

/** 思维链时间线步骤(deer-flow ChainOfThought 借鉴):推理与工具按到达顺序交错 */
export type StreamStep =
  | { kind: "reasoning"; id: string; text: string }
  | { kind: "tool"; id: string; tool: StreamToolCall };

export interface PlanTodo {
  content: string;
  status: "pending" | "in_progress" | "completed" | string;
}

export interface StreamMessage {
  runId: string;
  phase: "reasoning" | "tools" | "answering" | "final" | "error";
  reasoningText: string;
  /** plan_mode（write_todos）计划清单：AI 的多步计划与实时进度 */
  todos: PlanTodo[];
  /** 完整思维链：每条 reasoning 事件追加一段，供展开查看（reasoningText 只是最新一段） */
  reasoningLog: string[];
  skillTrace: SkillTraceItem[];
  tools: StreamToolCall[];
  /** 有序步骤流(时间线渲染用;tools 保留供旧消费方) */
  steps: StreamStep[];
  answerText: string;
  /** AI 反问澄清的问题文本（ask_clarification）；出现即等待用户下一条消息回答 */
  clarificationText: string | null;
  /** DeerFlow-native human_input_request；有则渲染 HumanInputCard */
  clarificationRequest: import("@/lib/humanInput").HumanInputRequest | null;
  finalPayload: Record<string, unknown> | null;
  errorText: string | null;
}

// ── Tool labels ──

const TOOL_LABELS: Record<string, string> = {
  get_stock_context: "个股分析",
  get_daily_history: "历史行情",
  search_stock_intel: "情报搜索",
  add_watchlist_item: "添加自选",
  list_watchlist: "查看自选",
  remove_watchlist_item: "删除自选",
  get_portfolio_snapshot: "持仓快照",
  upsert_holding: "调整持仓",
  remove_holding: "删除持仓",
  analyze_portfolio_risk: "组合风险",
  get_active_risk_policy: "风险策略",
  list_risk_policies: "风险策略列表",
  evaluate_policy_risk: "策略风险评估",
  generate_draft_order: "生成拟单",
  confirm_rebalance_draft: "确认草案",
  reject_rebalance_draft: "驳回草案",
  list_rebalance_drafts: "草案列表",
  get_rebalance_draft: "草案详情",
  create_pre_trade_review: "交易审查",
  list_pre_trade_reviews: "审查记录",
  list_paper_orders: "Paper 订单",
  get_paper_portfolio: "Paper 组合",
  analyze_paper_performance: "Paper 绩效",
  create_paper_portfolio_snapshot: "创建快照",
  list_decision_journal: "决策日志",
  get_decision_journal_entry: "决策条目",
  summarize_decision_outcomes: "决策总结",
  list_review_inbox: "待办列表",
  summarize_review_inbox: "待办总结",
  dismiss_inbox_item: "忽略待办",
  snooze_inbox_item: "稍后提醒",
  mark_inbox_item_done: "完成待办",
  get_industry_context: "行业格局",
  get_market_structure: "市场结构",
  get_monitor_events: "监控事件",
  get_monitor_rules: "监控规则",
  evaluate_monitor_rules: "评估规则",
  upsert_monitor_rule: "写盯盘规则",
  delete_monitor_rule: "删盯盘规则",
  list_strategies: "策略列表",
  run_strategy_backtest: "运行回测",
  get_backtest_result: "回测结果",
  list_report_templates: "报告模板",
  generate_report: "生成报告",
  get_report_quality: "报告质量",
  ask_clarification: "反问澄清",
  web_search: "全网搜索",
  web_fetch: "网页抓取",
  read_file: "读取资料",
  grep: "检索资料",
  glob: "查找文件",
  ls: "浏览目录",
  view_image: "查看图片",
  bash: "执行代码",
  write_file: "写文件",
  str_replace: "编辑文件",
  present_files: "交付文件",
  task: "子代理委派",
  write_todos: "执行计划",
};

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name;
}

/** 左栏会话副行：进行中的轻量进度（不展开思维链） */
export type SessionActivityKind =
  | "reasoning"
  | "tools"
  | "answering"
  | "clarification"
  | "error";

export interface SessionActivity {
  kind: SessionActivityKind;
  summary: string;
}

/** 从流式快照派生左栏文案；final 不计为活动态 */
export function summarizeSessionActivity(msg: StreamMessage): SessionActivity | null {
  if (msg.clarificationText || msg.clarificationRequest) {
    return { kind: "clarification", summary: "等待你的回复" };
  }
  if (msg.phase === "error" || msg.errorText) {
    return { kind: "error", summary: "出错 · 可重试" };
  }
  if (msg.phase === "final") return null;
  if (msg.phase === "answering") {
    return { kind: "answering", summary: "正在回复…" };
  }
  if (msg.phase === "tools") {
    const running = msg.tools.filter((t) => t.status === "running");
    if (running.length > 1) {
      return { kind: "tools", summary: `正在调用 · ${running.length} 个工具` };
    }
    const focus = running[0] ?? msg.tools[msg.tools.length - 1];
    if (focus) {
      return { kind: "tools", summary: `正在调用 · ${toolLabel(focus.name)}` };
    }
  }
  return { kind: "reasoning", summary: "正在思考…" };
}

/** tool_result 载荷 → 展示文本：优先 text/output/result；工具桥（stub/embedded）把
 * 结构化结果平铺在载荷顶层（{call_id, ...result}），此时序列化剩余载荷兜底，
 * 否则工具卡预览和右栏详情都拿不到内容。 */
export function extractToolResultText(payload: Record<string, unknown> | null | undefined): string | undefined {
  if (!payload) return undefined;
  const direct = payload.text ?? payload.output ?? payload.result;
  if (direct !== undefined && direct !== null && direct !== "") {
    return typeof direct === "string" ? direct : JSON.stringify(direct);
  }
  const rest = { ...payload };
  delete rest.call_id;
  return Object.keys(rest).length ? JSON.stringify(rest) : undefined;
}

// ── Hook ──
// 聊天状态是应用级单例（经 CopilotChatProvider 提供）：聊天主屏与业务页侧栏
// 共享同一份会话/消息；SSE 按 session_id 保活，切屏/切会话不断流（Stop/删除才关）。

function useCopilotChatState() {
  const {
    currentScreen, stock, setStock,
    setCopilotStreaming,
    setStreamingReasoningText,
    refreshCopilotContext,
    appDataCache,
    globalLoading,
    lastRefreshTime,
  } = useAppState();

  const [sessions, setSessions] = useState<CopilotSession[]>([]);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const currentSessionIdRef = useRef(currentSessionId);
  useEffect(() => { currentSessionIdRef.current = currentSessionId; }, [currentSessionId]);
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [reasoningText, setReasoningText] = useState<string>("");
  const [streamMessage, setStreamMessage] = useState<StreamMessage | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  /** 消息动作「填入输入框」：Composer 消费后清掉 */
  const [composerPrefill, setComposerPrefill] = useState<string | null>(null);
  const [toolOpen, setToolOpen] = useState<Set<string>>(new Set());

  // 按会话保活 SSE：切会话/新建对话不断开在途流，只切换视图；Stop/删除才关连接
  const streamsRef = useRef(new Map<string, EventSource>());
  const streamSnapshotsRef = useRef(new Map<string, StreamMessage>());
  /** 后台 error 在 snapshot 清掉后仍短暂留在左栏 */
  const stickyActivityRef = useRef<Record<string, SessionActivity>>({});
  const [sessionActivity, setSessionActivity] = useState<Record<string, SessionActivity>>({});
  const activityFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [draftSessionModel, setDraftSessionModel] = useState<string | null>(null);
  // 「新建对话」不立即建库(否则积累空会话):置起意向标记,首条消息时才真正创建
  const pendingNewRef = useRef(false);

  const viewingSession = useCallback((sid: string) => currentSessionIdRef.current === sid, []);

  const flushSessionActivity = useCallback(() => {
    activityFlushTimerRef.current = null;
    const next: Record<string, SessionActivity> = { ...stickyActivityRef.current };
    for (const [sid, snap] of streamSnapshotsRef.current) {
      const summary = summarizeSessionActivity(snap);
      if (summary) next[sid] = summary;
    }
    setSessionActivity((prev) => {
      const prevKeys = Object.keys(prev);
      const nextKeys = Object.keys(next);
      if (
        prevKeys.length === nextKeys.length
        && nextKeys.every((k) => prev[k]?.kind === next[k]?.kind && prev[k]?.summary === next[k]?.summary)
      ) {
        return prev;
      }
      return next;
    });
  }, []);

  const syncSessionActivity = useCallback((immediate = false) => {
    if (immediate) {
      if (activityFlushTimerRef.current) {
        clearTimeout(activityFlushTimerRef.current);
        activityFlushTimerRef.current = null;
      }
      flushSessionActivity();
      return;
    }
    if (activityFlushTimerRef.current) return;
    activityFlushTimerRef.current = setTimeout(flushSessionActivity, 280);
  }, [flushSessionActivity]);

  const syncGlobalStreaming = useCallback(() => {
    setCopilotStreaming(streamsRef.current.size > 0);
  }, [setCopilotStreaming]);

  const patchStream = useCallback((sid: string, updater: (prev: StreamMessage) => StreamMessage | null) => {
    const prev = streamSnapshotsRef.current.get(sid);
    if (!prev) return;
    const next = updater(prev);
    if (next) streamSnapshotsRef.current.set(sid, next);
    else streamSnapshotsRef.current.delete(sid);
    if (viewingSession(sid)) setStreamMessage(next);
    syncSessionActivity();
  }, [viewingSession, syncSessionActivity]);

  const bindStream = useCallback((sid: string, msg: StreamMessage) => {
    delete stickyActivityRef.current[sid];
    streamSnapshotsRef.current.set(sid, msg);
    // ES 登记前也先点亮全局 busy，避免 bind→open 间隙被当成空闲
    setCopilotStreaming(true);
    if (viewingSession(sid)) {
      setStreamMessage(msg);
      setReasoningText(msg.reasoningText || "");
      setSending(true);
    }
    syncSessionActivity(true);
  }, [viewingSession, setCopilotStreaming, syncSessionActivity]);

  const releaseStream = useCallback((sid: string, es?: EventSource | null) => {
    const current = streamsRef.current.get(sid);
    if (es && current && current !== es) return false;
    if (current) {
      streamsRef.current.delete(sid);
      try { current.close(); } catch { /* empty */ }
    }
    streamSnapshotsRef.current.delete(sid);
    syncGlobalStreaming();
    if (viewingSession(sid)) {
      setSending(false);
      setReasoningText("");
    }
    syncSessionActivity(true);
    return true;
  }, [viewingSession, syncGlobalStreaming, syncSessionActivity]);

  useEffect(() => () => {
    for (const es of streamsRef.current.values()) {
      try { es.close(); } catch { /* empty */ }
    }
    streamsRef.current.clear();
    streamSnapshotsRef.current.clear();
    if (activityFlushTimerRef.current) clearTimeout(activityFlushTimerRef.current);
  }, []);

  const currentSession = sessions.find((s) => s.session_id === currentSessionId);

  const globalDefaultModel = useMemo(() => {
    void globalLoading;
    const settings = appDataCache.current.settings as {
      llm_providers?: { default_model?: string | null };
    } | undefined;
    return settings?.llm_providers?.default_model ?? null;
  }, [appDataCache, globalLoading, lastRefreshTime]);

  const sessionModelRef = currentSession?.default_model
    ?? draftSessionModel
    ?? globalDefaultModel;

  const modelOptions = useMemo(() => {
    void globalLoading;
    const settings = appDataCache.current.settings as {
      llm_providers?: {
        connected?: Array<{ id: string; name: string; models: Array<{ id: string; name: string }> }>;
      };
    } | undefined;
    const rows: { value: string; label: string }[] = [];
    for (const provider of settings?.llm_providers?.connected ?? []) {
      for (const model of provider.models ?? []) {
        rows.push({
          value: `${provider.id}/${model.id}`,
          label: `${provider.name} · ${model.name}`,
        });
      }
    }
    return rows;
  }, [appDataCache, globalLoading, lastRefreshTime]);

  // memo 化：否则每次渲染重建，会让依赖它们的 handleSend 等 useCallback 全部失效
  const loadMessages = useCallback(async (sessionId: string, runId?: string) => {
    try {
      const items = await fetchSessionMessages(sessionId, runId);
      setMessages(items);
    } catch { /* empty */ }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const items = await fetchSessions();
      setSessions(items);
      // 用 ref 读取当前会话，避免把 currentSessionId 列进依赖而破坏 memo 稳定性
      if (items.length > 0 && !currentSessionIdRef.current) {
        setCurrentSessionId(items[0].session_id);
        loadMessages(items[0].session_id);
      }
    } catch { /* empty */ }
    finally { setSessionsLoaded(true); }
  }, [loadMessages]);

  // 挂载时加载会话列表；loadSessions 为异步加载，setState 发生在 await 之后，
  // 并非会触发级联渲染的同步 setState，这里属于规则的误报。
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { loadSessions(); }, [loadSessions]);

  useEffect(() => { refreshCopilotContext(); }, [currentScreen, stock, refreshCopilotContext]);

  const switchSession = useCallback(async (id: string) => {
    if (id === currentSessionId) return;
    // 不断开其他会话的在途 SSE，只切换视图并恢复目标会话的流式快照
    pendingNewRef.current = false;
    setDraftSessionModel(null);
    currentSessionIdRef.current = id;
    setCurrentSessionId(id);
    setMessages([]);
    setStreamingReasoningText("");
    delete stickyActivityRef.current[id];
    const snap = streamSnapshotsRef.current.get(id) ?? null;
    setStreamMessage(snap);
    setSending(streamsRef.current.has(id));
    setReasoningText(snap?.reasoningText || "");
    syncGlobalStreaming();
    syncSessionActivity(true);
    // 锚点跟随：切换会话时恢复该会话的 symbol 锚点(个股档案等页随 stock 联动)
    const anchor = sessions.find((s) => s.session_id === id)?.anchor_symbol;
    if (anchor) setStock(anchor);
    await loadMessages(id);
  }, [currentSessionId, sessions, setStock, loadMessages, setStreamingReasoningText, syncGlobalStreaming, syncSessionActivity]);

  const handleNewSession = useCallback(async () => {
    // 懒建:只清空视图并置新建意向；后台会话的 SSE 继续跑
    pendingNewRef.current = true;
    setDraftSessionModel(null);
    currentSessionIdRef.current = null;
    setCurrentSessionId(null);
    setMessages([]);
    setStreamingReasoningText("");
    setStreamMessage(null);
    setSending(false);
    setReasoningText("");
    syncGlobalStreaming();
  }, [setStreamingReasoningText, syncGlobalStreaming]);

  const handleRenameSession = useCallback(async (sid: string, val: string) => {
    const trimmed = val.trim();
    if (!trimmed || trimmed === sessions.find((s) => s.session_id === sid)?.title) return;
    try {
      await updateSession(sid, { title: trimmed });
      setSessions((prev) => prev.map((s) => s.session_id === sid ? { ...s, title: trimmed } : s));
    } catch { /* empty */ }
  }, [sessions]);

  const handleDeleteSession = useCallback(async (sid: string) => {
    try {
      delete stickyActivityRef.current[sid];
      releaseStream(sid);
      await deleteSession(sid);
      setSessions((prev) => prev.filter((s) => s.session_id !== sid));
      if (currentSessionId === sid) {
        const next = sessions.find((s) => s.session_id !== sid);
        currentSessionIdRef.current = next?.session_id || null;
        setCurrentSessionId(next?.session_id || null);
        setMessages([]);
        const snap = next ? (streamSnapshotsRef.current.get(next.session_id) ?? null) : null;
        setStreamMessage(snap);
        setSending(!!next && streamsRef.current.has(next.session_id));
        if (next) await loadMessages(next.session_id);
      }
    } catch { /* empty */ }
  }, [currentSessionId, sessions, loadMessages, releaseStream]);

  // 确保有当前会话（发消息/上传附件共用）：无则复用最近会话或新建
  const ensureSession = useCallback(async (): Promise<string> => {
    if (currentSessionIdRef.current) return currentSessionIdRef.current;
    let session: CopilotSession | undefined;
    if (!pendingNewRef.current) {
      const existing = await fetchSessions();
      session = existing[0];
    }
    if (!session) {
      session = await createSession("新会话", currentScreen, stock || null, draftSessionModel);
      setSessions((prev) => [session!, ...prev]);
    }
    pendingNewRef.current = false;
    setDraftSessionModel(null);
    currentSessionIdRef.current = session.session_id;
    setCurrentSessionId(session.session_id);
    return session.session_id;
  }, [currentScreen, stock, draftSessionModel]);

  const setSessionModel = useCallback(async (defaultModel: string) => {
    const sid = currentSessionIdRef.current;
    if (!sid) {
      setDraftSessionModel(defaultModel);
      return;
    }
    try {
      const updated = await updateSession(sid, { default_model: defaultModel });
      setSessions((prev) => prev.map((s) => (
        s.session_id === sid ? { ...s, default_model: updated.default_model ?? defaultModel } : s
      )));
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "更新会话模型失败");
    }
  }, []);

  // symbolOverride:「问 AI」快捷入口按卡片上下文指定锚点,不依赖全局 stock 的当前值
  const handleSend = useCallback(async (
    input: string,
    symbolOverride?: string,
    attachments: UploadedFileInfo[] = [],
    humanInputResponse?: HumanInputResponse | null,
  ) => {
    let text = input.trim();
    if (!text && !humanInputResponse) return;
    if (symbolOverride) setStock(symbolOverride);

    let sid: string;
    try {
      sid = await ensureSession();
    } catch {
      return;
    }
    // 同一会话禁止并发；其它会话可在后台继续流式回复
    if (streamsRef.current.has(sid)) return;

    const priorSnap = streamSnapshotsRef.current.get(sid);
    const openRequest = priorSnap?.clarificationRequest
      ?? (priorSnap?.clarificationText
        ? parseHumanInputRequest({ question: priorSnap.clarificationText, call_id: priorSnap.runId })
        : null);
    let responseMeta = humanInputResponse ?? null;
    if (openRequest && !responseMeta && text) {
      responseMeta = createHumanInputTextResponse(openRequest, text);
    }
    if (humanInputResponse && !text) {
      text = humanInputResponse.value;
    }
    delete stickyActivityRef.current[sid];

    const initialStream: StreamMessage = {
      runId: "",
      phase: "reasoning",
      reasoningText: "AI 正在思考...",
      reasoningLog: [],
      skillTrace: [],
      todos: [],
      tools: [],
      steps: [],
      answerText: "",
      clarificationText: null,
      clarificationRequest: null,
      finalPayload: null,
      errorText: null,
    };
    bindStream(sid, initialStream);

    try {
      const run = await sendMessage(
        sid,
        text,
        currentScreen,
        symbolOverride ?? stock,
        attachments,
        responseMeta,
      );
      bindStream(sid, { ...initialStream, runId: run.run_id });

      const userMsg: CopilotMessage = {
        message_id: `msg-${Date.now()}`,
        session_id: sid,
        role: "user",
        kind: "user_message",
        text,
        payload: attachments.length ? { attachments } : {},
        created_at: new Date().toISOString(),
        run_id: run.run_id,
      };
      // 乐观追加用户消息；本轮结束后会用服务端持久化消息整体对齐（见 final 处理）
      if (viewingSession(sid)) {
        setMessages((prev) => [...prev, userMsg]);
      }

      // 收集完整的流式数据
      let finalAnswerText = "";
      let finalPayload: Record<string, unknown> | null = null;
      let errorText: string | null = null;

      const es = new EventSource(createStreamUrl(sid, run.run_id));
      streamsRef.current.set(sid, es);
      syncGlobalStreaming();
      let settled = false;

      // Named keepalive from the backend. Must be a real EventSource event
      // (not an SSE comment) so WKWebView does not idle-cut the socket.
      es.addEventListener("ping", () => {});

      // 只处理title事件（更新session标题）
      es.addEventListener("title", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const t = String((data?.payload?.title as string) || "").trim();
          // 双保险：prompt envelope / JSON 泄漏不入会话列表
          if (t && sid && isUsableSessionTitle(t)) {
            setSessions((prev) => prev.map((s) =>
              s.session_id === sid ? { ...s, title: t } : s
            ));
          }
        } catch { /* empty */ }
      });

      // AI 反问澄清：DeerFlow-native human_input 卡片；下一条消息 / 卡片提交即回答
      es.addEventListener("clarification", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const payload = (data?.payload || {}) as Record<string, unknown>;
          const request = parseHumanInputRequest(payload);
          const q = request?.question || String(payload.question || "");
          if (q || request) {
            patchStream(sid, (prev) => ({
              ...prev,
              clarificationText: q || prev.clarificationText,
              clarificationRequest: request,
            }));
          }
        } catch { /* empty */ }
      });

      // 声明式技能链路：渲染 researcher→valuation→…→report 流水线
      es.addEventListener("skill_trace", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const items = skillTraceItems((data?.payload as Record<string, unknown>)?.items);
          if (items.length > 0) {
            patchStream(sid, (prev) => ({ ...prev, skillTrace: items }));
          }
        } catch { /* empty */ }
      });

      // 推理过程：实时更新流式气泡的推理文本，并累积完整思维链供展开查看
      es.addEventListener("reasoning", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const p = (data?.payload || {}) as Record<string, unknown>;
          const t = String(p.text || p.latest_text || "");
          // 只展示真实推理文本;裸 phase 名("values" 等快照占位)是噪声,不进气泡
          if (t) {
            patchStream(sid, (prev) => {
              const isNew = prev.reasoningLog[prev.reasoningLog.length - 1] !== t;
              const last = prev.steps[prev.steps.length - 1];
              let steps = prev.steps;
              if (isNew) {
                // 相邻推理步合并更新(快照会增量变长),遇到工具步后才开新推理步
                steps = last?.kind === "reasoning"
                  ? [...prev.steps.slice(0, -1), { ...last, text: t }]
                  : [...prev.steps, { kind: "reasoning" as const, id: `r-${prev.steps.length}`, text: t }];
              }
              return {
                ...prev,
                phase: "reasoning",
                reasoningText: t,
                reasoningLog: isNew ? [...prev.reasoningLog, t] : prev.reasoningLog,
                steps,
              };
            });
            if (viewingSession(sid)) setReasoningText(t);
          }
        } catch { /* empty */ }
      });

      // 工具调用开始：追加一张「进行中」工具卡；
      // write_todos（plan_mode 计划清单）单独渲染成 checklist，不进工具卡
      es.addEventListener("tool_call", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const p = (data?.payload || {}) as Record<string, unknown>;
          const callId = String(p.call_id || `${p.tool}-${Date.now()}`);
          const name = String(p.tool || "tool");
          if (name === "write_todos") {
            let args = p.arguments;
            if (typeof args === "string") {
              try { args = JSON.parse(args); } catch { args = {}; }
            }
            const todos = (args as { todos?: PlanTodo[] })?.todos;
            if (Array.isArray(todos)) {
              patchStream(sid, (prev) => ({ ...prev, todos }));
            }
            return;
          }
          let subagentType: string | undefined;
          let taskDescription: string | undefined;
          let taskPrompt: string | undefined;
          if (name === "task") {
            const meta = parseTaskToolArgs(p.arguments);
            subagentType = meta.subagentType;
            taskDescription = meta.description;
            taskPrompt = meta.prompt;
          }
          patchStream(sid, (prev) => {
            if (prev.tools.some((t) => t.callId === callId)) return prev;
            const tool: StreamToolCall = {
              callId, name, status: "running", subagentType, taskDescription, taskPrompt,
            };
            return {
              ...prev,
              phase: "tools",
              tools: [...prev.tools, tool],
              steps: [...prev.steps, { kind: "tool", id: callId, tool }],
            };
          });
        } catch { /* empty */ }
      });

      // 工具调用返回：把对应工具卡标记为完成
      es.addEventListener("tool_result", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const p = (data?.payload || {}) as Record<string, unknown>;
          const callId = String(p.call_id || "");
          const resultText = extractToolResultText(p);
          patchStream(sid, (prev) => ({
            ...prev,
            tools: prev.tools.map((t) => t.callId === callId ? { ...t, status: "done", resultText } : t),
            steps: prev.steps.map((st) => st.kind === "tool" && st.tool.callId === callId
              ? { ...st, tool: { ...st.tool, status: "done" as const, resultText } } : st),
          }));
        } catch { /* empty */ }
      });

      // 收集partial_answer文本，并实时流式显示
      es.addEventListener("partial_answer", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const t = (data?.payload?.text as string) || "";
          if (t) {
            finalAnswerText += t;
            patchStream(sid, (prev) => ({ ...prev, phase: "answering", answerText: prev.answerText + t }));
          }
        } catch { /* empty */ }
      });

      // 处理final事件
      es.addEventListener("final", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          finalPayload = data?.payload || null;
          // 如果没有partial_answer，使用conclusion
          if (!finalAnswerText && finalPayload) {
            finalAnswerText = (finalPayload.conclusion as string) || "";
          }
        } catch { /* empty */ }

        settled = true;
        if (streamsRef.current.get(sid) === es) {
          streamsRef.current.delete(sid);
          try { es.close(); } catch { /* empty */ }
        }
        syncGlobalStreaming();

        const snapBeforeClear = streamSnapshotsRef.current.get(sid);
        const waitingClarify = Boolean(
          snapBeforeClear?.clarificationRequest || snapBeforeClear?.clarificationText
          || (finalPayload as { clarification?: unknown } | null)?.clarification,
        );
        if (waitingClarify) {
          stickyActivityRef.current[sid] = { kind: "clarification", summary: "等待你的回复" };
        } else {
          delete stickyActivityRef.current[sid];
        }

        // 后台完成：清掉快照，切回该会话时靠 loadMessages 拿完整历史
        if (!viewingSession(sid)) {
          streamSnapshotsRef.current.delete(sid);
          syncSessionActivity(true);
          loadSessions();
          return;
        }

        // 先把流式气泡切到「完成」态，保留答案作为过渡，避免重载前闪空
        patchStream(sid, (prev) => ({ ...prev, phase: "final", answerText: finalAnswerText, finalPayload }));
        setReasoningText("");
        setSending(false);

        // 用服务端持久化消息整体对齐：含 tool_call/tool_result（→ 历史工具卡）与
        // 真实 message_id，同时清掉流式气泡。setMessages 与 setStreamMessage 在同一回调里，
        // React 自动批处理为单次渲染，不会出现答案重复或闪烁。
        const sessionId = sid;
        fetchSessionMessages(sessionId)
          .then((items) => {
            // 在途期间用户可能已新建/切换会话；若当前会话已不是本轮 run 的会话，
            // 丢弃这批历史消息，避免把旧会话的流信息覆盖进新对话。
            if (currentSessionIdRef.current !== sessionId) return;
            setMessages(items);
            streamSnapshotsRef.current.delete(sessionId);
            setStreamMessage(null);
            syncSessionActivity(true);
          })
          .catch(() => { /* 重载失败则保留流式气泡，答案仍可见 */ });
        loadSessions();
      });

      // 处理error事件
      es.addEventListener("error", (streamEvent: Event) => {
        // 浏览器原生 EventSource 在「连接层中断」时也会派发 error 事件，
        // 这类事件不带 data。只有带 data 的才是服务端真正发出的业务错误，
        // 否则误把一次网络抖动渲染成「错误: null」并杀掉整轮对话。
        if (settled || streamsRef.current.get(sid) !== es) return;
        const raw = (streamEvent as MessageEvent).data;
        if (raw === undefined || raw === null) {
          errorText = "连接中断，请重新发送消息";
        } else {
          try {
            const data = JSON.parse(raw);
            errorText = String(data?.payload?.error || "stream error");
          } catch {
            errorText = "stream error";
          }
        }

        stickyActivityRef.current[sid] = { kind: "error", summary: "出错 · 可重试" };
        releaseStream(sid, es);

        // 用户已切到别的会话：丢弃这条在途回调（后台也清掉快照）
        if (!viewingSession(sid)) {
          loadSessions();
          return;
        }

        // 创建错误消息
        const errorMsg: CopilotMessage = {
          message_id: `msg-error-${run.run_id.slice(-8)}`,
          session_id: sid,
          role: "assistant",
          kind: "final_answer",
          text: `错误: ${errorText}`,
          payload: { error: errorText },
          created_at: new Date().toISOString(),
          run_id: run.run_id,
        };
        setMessages((prev) => [...prev, errorMsg]);
        setStreamMessage(null);
        setReasoningText("");
        setSending(false);
        loadSessions();
      });
    } catch {
      releaseStream(sid);
      if (viewingSession(sid)) {
        setStreamMessage(null);
        setReasoningText("");
        setSending(false);
      }
    }
  }, [
    ensureSession, currentScreen, stock, setStock, loadSessions,
    bindStream, patchStream, releaseStream, syncGlobalStreaming, syncSessionActivity, viewingSession,
  ]);

  const handleStop = useCallback(() => {
    const sid = currentSessionIdRef.current;
    if (!sid) {
      setStreamMessage(null);
      setReasoningText("");
      setSending(false);
      return;
    }
    releaseStream(sid);
    setStreamMessage(null);
    void fetchSessionMessages(sid).then((items) => {
      if (currentSessionIdRef.current === sid) setMessages(items);
    });
  }, [releaseStream]);

  const handleCopy = useCallback(async (msg: CopilotMessage) => {
    try {
      await navigator.clipboard.writeText(msg.text || "");
      setCopiedId(msg.message_id);
      setTimeout(() => setCopiedId(null), 1500);
    } catch { /* empty */ }
  }, []);

  const handlePrefillComposer = useCallback((text: string) => {
    const t = text.trim();
    if (!t) return;
    setComposerPrefill(t);
  }, []);

  const clearComposerPrefill = useCallback(() => {
    setComposerPrefill(null);
  }, []);

  /** 按 run 或最近一条用户消息重试发送 */
  const handleRetry = useCallback(async (runId?: string | null) => {
    const users = messages.filter((m) => m.role === "user" && (m.text || "").trim());
    const target = runId
      ? [...users].reverse().find((m) => m.run_id === runId)
      : users[users.length - 1];
    if (!target?.text?.trim()) return;
    await handleSend(target.text);
  }, [messages, handleSend]);

  const toggleToolOpen = useCallback((id: string) => {
    setToolOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return {
    sessions,
    sessionsLoaded,
    currentSessionId,
    currentSession,
    messages,
    sending,
    reasoningText,
    streamMessage,
    sessionActivity,
    copiedId,
    composerPrefill,
    toolOpen,
    loadSessions,
    loadMessages,
    ensureSession,
    switchSession,
    handleNewSession,
    handleRenameSession,
    handleDeleteSession,
    handleSend,
    handleStop,
    handleCopy,
    handlePrefillComposer,
    clearComposerPrefill,
    handleRetry,
    toggleToolOpen,
    sessionModelRef,
    modelOptions,
    setSessionModel,
  };
}

export type CopilotChatValue = ReturnType<typeof useCopilotChatState>;

const CopilotChatContext = createContext<CopilotChatValue | null>(null);

export function CopilotChatProvider({ children }: { children: ReactNode }) {
  const value = useCopilotChatState();
  return createElement(CopilotChatContext.Provider, { value }, children);
}

export function useCopilotChat(): CopilotChatValue {
  const ctx = useContext(CopilotChatContext);
  if (!ctx) throw new Error("useCopilotChat must be used within CopilotChatProvider");
  return ctx;
}
