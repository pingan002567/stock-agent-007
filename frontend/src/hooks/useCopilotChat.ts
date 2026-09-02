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
} from "@/api/copilot";
import type { CopilotSession, CopilotMessage } from "@/api/client";
import { skillTraceItems, type SkillTraceItem } from "@/api/copilot";
import { parseTaskToolArgs } from "@/components/features/taskToolMeta";

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
  finalPayload: Record<string, unknown> | null;
  errorText: string | null;
}

// ── Tool labels ──

const TOOL_LABELS: Record<string, string> = {
  get_stock_context: "个股分析",
  get_daily_history: "历史行情",
  search_stock_intel: "情报搜索",
  add_watchlist_item: "添加自选",
  remove_watchlist_item: "删除自选",
  get_portfolio_snapshot: "持仓快照",
  upsert_holding: "调整持仓",
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
// 共享同一份会话/消息/EventSource，切屏不断流、不状态分裂。

function useCopilotChatState() {
  const {
    currentScreen, stock, setStock,
    setCopilotStreaming,
    setStreamingReasoningText,
    refreshCopilotContext,
    appDataCache,
    globalLoading,
  } = useAppState();

  const [sessions, setSessions] = useState<CopilotSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const currentSessionIdRef = useRef(currentSessionId);
  useEffect(() => { currentSessionIdRef.current = currentSessionId; }, [currentSessionId]);
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [reasoningText, setReasoningText] = useState<string>("");
  const [streamMessage, setStreamMessage] = useState<StreamMessage | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [toolOpen, setToolOpen] = useState<Set<string>>(new Set());

  const eventSourceRef = useRef<EventSource | null>(null);
  const sendingRef = useRef(false);
  const [draftSessionModel, setDraftSessionModel] = useState<string | null>(null);
  // 「新建对话」不立即建库(否则积累空会话):置起意向标记,首条消息时才真正创建
  const pendingNewRef = useRef(false);

  const currentSession = sessions.find((s) => s.session_id === currentSessionId);

  const globalDefaultModel = useMemo(() => {
    void globalLoading;
    const settings = appDataCache.current.settings as {
      llm_providers?: { default_model?: string | null };
    } | undefined;
    return settings?.llm_providers?.default_model ?? null;
  }, [appDataCache, globalLoading]);

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
  }, [appDataCache, globalLoading]);

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
  }, [loadMessages]);

  // 挂载时加载会话列表；loadSessions 为异步加载，setState 发生在 await 之后，
  // 并非会触发级联渲染的同步 setState，这里属于规则的误报。
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { loadSessions(); }, [loadSessions]);

  useEffect(() => { refreshCopilotContext(); }, [currentScreen, stock, refreshCopilotContext]);

  const switchSession = useCallback(async (id: string) => {
    if (id === currentSessionId) return;
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    sendingRef.current = false;
    pendingNewRef.current = false;
    setDraftSessionModel(null);
    setCurrentSessionId(id);
    setMessages([]);
    setStreamingReasoningText("");
    setStreamMessage(null);
    setCopilotStreaming(false);
    setSending(false);
    // 锚点跟随：切换会话时恢复该会话的 symbol 锚点(个股档案等页随 stock 联动)
    const anchor = sessions.find((s) => s.session_id === id)?.anchor_symbol;
    if (anchor) setStock(anchor);
    await loadMessages(id);
  }, [currentSessionId, sessions, setStock, loadMessages, setCopilotStreaming, setStreamingReasoningText]);

  const handleNewSession = useCallback(async () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    sendingRef.current = false;
    // 懒建:只清空视图并置新建意向,首条消息时 ensureSession 才创建会话
    pendingNewRef.current = true;
    setDraftSessionModel(null);
    currentSessionIdRef.current = null;
    setCurrentSessionId(null);
    setMessages([]);
    setStreamingReasoningText("");
    setStreamMessage(null);
    setCopilotStreaming(false);
    setSending(false);
  }, [setCopilotStreaming, setStreamingReasoningText]);

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
      await deleteSession(sid);
      setSessions((prev) => prev.filter((s) => s.session_id !== sid));
      if (currentSessionId === sid) {
        const next = sessions.find((s) => s.session_id !== sid);
        setCurrentSessionId(next?.session_id || null);
        setMessages([]);
        if (next) await loadMessages(next.session_id);
      }
    } catch { /* empty */ }
  }, [currentSessionId, sessions, loadMessages]);

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
  const handleSend = useCallback(async (input: string, symbolOverride?: string) => {
    const text = input.trim();
    if (!text || sendingRef.current) return;
    if (symbolOverride) setStock(symbolOverride);
    sendingRef.current = true;
    setSending(true);
    setCopilotStreaming(true);
    setReasoningText("AI 正在思考...");
    setStreamMessage({
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
      finalPayload: null,
      errorText: null,
    });

    try {
      const sid = await ensureSession();

      const run = await sendMessage(sid, text, currentScreen, symbolOverride ?? stock);

      const userMsg: CopilotMessage = {
        message_id: `msg-${Date.now()}`,
        session_id: sid,
        role: "user",
        kind: "user_message",
        text,
        payload: {},
        created_at: new Date().toISOString(),
        run_id: run.run_id,
      };
      // 乐观追加用户消息；本轮结束后会用服务端持久化消息整体对齐（见 final 处理）
      setMessages((prev) => [...prev, userMsg]);

      // 收集完整的流式数据
      let finalAnswerText = "";
      let finalPayload: Record<string, unknown> | null = null;
      let errorText: string | null = null;

      const es = new EventSource(createStreamUrl(sid, run.run_id));
      eventSourceRef.current = es;

      // 只处理title事件（更新session标题）
      es.addEventListener("title", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const t = (data?.payload?.title as string) || "";
          // 双保险:JSON 形状的标题(prompt envelope 泄漏)不入会话列表
          if (t && sid && !t.trimStart().startsWith("{") && !t.trimStart().startsWith("[")) {
            setSessions((prev) => prev.map((s) =>
              s.session_id === sid ? { ...s, title: t } : s
            ));
          }
        } catch { /* empty */ }
      });

      // AI 反问澄清：展示问题卡片，等待用户以下一条消息回答
      es.addEventListener("clarification", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const q = String((data?.payload as Record<string, unknown>)?.question || "");
          if (q) setStreamMessage((prev) => prev ? { ...prev, clarificationText: q } : prev);
        } catch { /* empty */ }
      });

      // 声明式技能链路：渲染 researcher→valuation→…→report 流水线
      es.addEventListener("skill_trace", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const items = skillTraceItems((data?.payload as Record<string, unknown>)?.items);
          if (items.length > 0) {
            setStreamMessage((prev) => prev ? { ...prev, skillTrace: items } : prev);
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
            setStreamMessage((prev) => {
              if (!prev) return prev;
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
              setStreamMessage((prev) => prev ? { ...prev, todos } : prev);
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
          setStreamMessage((prev) => {
            if (!prev) return prev;
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
          setStreamMessage((prev) => prev ? {
            ...prev,
            tools: prev.tools.map((t) => t.callId === callId ? { ...t, status: "done", resultText } : t),
            steps: prev.steps.map((st) => st.kind === "tool" && st.tool.callId === callId
              ? { ...st, tool: { ...st.tool, status: "done" as const, resultText } } : st),
          } : prev);
        } catch { /* empty */ }
      });

      // 收集partial_answer文本，并实时流式显示
      es.addEventListener("partial_answer", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const t = (data?.payload?.text as string) || "";
          if (t) {
            finalAnswerText += t;
            setStreamMessage((prev) => prev ? { ...prev, phase: "answering", answerText: prev.answerText + t } : prev);
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
        
        // 关闭EventSource
        es.close();
        eventSourceRef.current = null;

        // 用户已切到别的会话：丢弃这条在途回调，避免把旧会话的结果串进当前视图
        if (currentSessionIdRef.current !== sid) return;

        // 先把流式气泡切到「完成」态，保留答案作为过渡，避免重载前闪空
        setStreamMessage((prev) => prev ? { ...prev, phase: "final", answerText: finalAnswerText, finalPayload } : prev);

        setReasoningText("");
        setCopilotStreaming(false);
        setSending(false);
        sendingRef.current = false;

        // 用服务端持久化消息整体对齐：含 tool_call/tool_result（→ 历史工具卡）与
        // 真实 message_id，同时清掉流式气泡。setMessages 与 setStreamMessage 在同一回调里，
        // React 自动批处理为单次渲染，不会出现答案重复或闪烁。
        const sessionId = sid;
        if (sessionId) {
          fetchSessionMessages(sessionId)
            .then((items) => {
              // 在途期间用户可能已新建/切换会话；若当前会话已不是本轮 run 的会话，
              // 丢弃这批历史消息，避免把旧会话的流信息覆盖进新对话。
              if (currentSessionIdRef.current !== sessionId) return;
              setMessages(items);
              setStreamMessage(null);
            })
            .catch(() => { /* 重载失败则保留流式气泡，答案仍可见 */ });
        } else {
          setStreamMessage(null);
        }
        loadSessions();
      });

      // 处理error事件
      es.addEventListener("error", (streamEvent: Event) => {
        // 浏览器原生 EventSource 在「连接层中断」时也会派发 error 事件，
        // 这类事件不带 data。只有带 data 的才是服务端真正发出的业务错误，
        // 否则误把一次网络抖动渲染成「错误: null」并杀掉整轮对话。
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

        // 关闭EventSource
        es.close();
        eventSourceRef.current = null;

        // 用户已切到别的会话：丢弃这条在途回调
        if (currentSessionIdRef.current !== sid) return;

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
        setCopilotStreaming(false);
        setSending(false);
        sendingRef.current = false;
        loadSessions();
      });
    } catch {
      sendingRef.current = false;
      setReasoningText("");
      setCopilotStreaming(false);
      setSending(false);
    }
  }, [ensureSession, currentScreen, stock, setCopilotStreaming, loadSessions]);

  const handleStop = useCallback(() => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    sendingRef.current = false;
    setReasoningText("");
    setStreamMessage(null);
    setCopilotStreaming(false);
    setSending(false);
  }, [setCopilotStreaming]);

  const handleCopy = useCallback(async (msg: CopilotMessage) => {
    try {
      await navigator.clipboard.writeText(msg.text || "");
      setCopiedId(msg.message_id);
      setTimeout(() => setCopiedId(null), 1500);
    } catch { /* empty */ }
  }, []);

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
    currentSessionId,
    currentSession,
    messages,
    sending,
    reasoningText,
    streamMessage,
    copiedId,
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
