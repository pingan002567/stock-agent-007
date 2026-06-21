import { useState, useRef, useCallback, useEffect } from "react";
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

// ── Streaming message types ──

export interface StreamToolCall {
  callId: string;
  name: string;
  status: "running" | "done" | "failed";
  resultText?: string;
}

export interface StreamMessage {
  runId: string;
  phase: "reasoning" | "tools" | "answering" | "final" | "error";
  reasoningText: string;
  tools: StreamToolCall[];
  answerText: string;
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
  get_monitor_events: "监控事件",
  get_monitor_rules: "监控规则",
  evaluate_monitor_rules: "评估规则",
  list_strategies: "策略列表",
  run_strategy_backtest: "运行回测",
  get_backtest_result: "回测结果",
  list_report_templates: "报告模板",
  generate_report: "生成报告",
  get_report_quality: "报告质量",
};

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name;
}

// ── Hook ──

export function useCopilotChat() {
  const {
    currentScreen, stock,
    setCopilotStreaming,
    setStreamingReasoningText,
    refreshCopilotContext,
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

  const currentSession = sessions.find((s) => s.session_id === currentSessionId);

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
    setCurrentSessionId(id);
    setMessages([]);
    setStreamingReasoningText("");
    setStreamMessage(null);
    setCopilotStreaming(false);
    setSending(false);
    await loadMessages(id);
  }, [currentSessionId, loadMessages, setCopilotStreaming, setStreamingReasoningText]);

  const handleNewSession = useCallback(async () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    sendingRef.current = false;
    try {
      const session = await createSession("新会话", currentScreen, stock || null);
      setSessions((prev) => [session, ...prev]);
      setCurrentSessionId(session.session_id);
      setMessages([]);
      setStreamingReasoningText("");
      setStreamMessage(null);
      setCopilotStreaming(false);
      setSending(false);
    } catch { /* empty */ }
  }, [currentScreen, stock, setCopilotStreaming, setStreamingReasoningText]);

  const handleRenameSession = useCallback(async (sid: string, val: string) => {
    const trimmed = val.trim();
    if (!trimmed || trimmed === sessions.find((s) => s.session_id === sid)?.title) return;
    try {
      await updateSession(sid, trimmed);
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

  const handleSend = useCallback(async (input: string) => {
    const text = input.trim();
    if (!text || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    setCopilotStreaming(true);
    setReasoningText("AI 正在思考...");
    setStreamMessage({
      runId: "",
      phase: "reasoning",
      reasoningText: "AI 正在思考...",
      tools: [],
      answerText: "",
      finalPayload: null,
      errorText: null,
    });

    try {
      let sid = currentSessionId;
      if (!sid) {
        const existing = await fetchSessions();
        const session = existing[0] ?? await createSession(`${stock} 对话`, currentScreen, stock || null);
        sid = session.session_id;
        setCurrentSessionId(sid);
      }

      const run = await sendMessage(sid, text, currentScreen, stock);

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
          if (t && sid) {
            setSessions((prev) => prev.map((s) =>
              s.session_id === sid ? { ...s, title: t } : s
            ));
          }
        } catch { /* empty */ }
      });

      // 推理过程：实时更新流式气泡的推理文本
      es.addEventListener("reasoning", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const p = (data?.payload || {}) as Record<string, unknown>;
          const t = String(p.text || p.latest_text || p.phase || "");
          if (t) setStreamMessage((prev) => prev ? { ...prev, phase: "reasoning", reasoningText: t } : prev);
        } catch { /* empty */ }
      });

      // 工具调用开始：追加一张「进行中」工具卡
      es.addEventListener("tool_call", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const p = (data?.payload || {}) as Record<string, unknown>;
          const callId = String(p.call_id || `${p.tool}-${Date.now()}`);
          const name = String(p.tool || "tool");
          setStreamMessage((prev) => {
            if (!prev) return prev;
            if (prev.tools.some((t) => t.callId === callId)) return prev;
            return { ...prev, phase: "tools", tools: [...prev.tools, { callId, name, status: "running" }] };
          });
        } catch { /* empty */ }
      });

      // 工具调用返回：把对应工具卡标记为完成
      es.addEventListener("tool_result", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const p = (data?.payload || {}) as Record<string, unknown>;
          const callId = String(p.call_id || "");
          setStreamMessage((prev) => prev ? {
            ...prev,
            tools: prev.tools.map((t) => t.callId === callId ? { ...t, status: "done" } : t),
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
            .then((items) => { setMessages(items); setStreamMessage(null); })
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
  }, [currentSessionId, currentScreen, stock, setCopilotStreaming, loadSessions]);

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
    switchSession,
    handleNewSession,
    handleRenameSession,
    handleDeleteSession,
    handleSend,
    handleStop,
    handleCopy,
    toggleToolOpen,
  };
}
