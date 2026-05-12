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
  currentSessionIdRef.current = currentSessionId;
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [reasoningText, setReasoningText] = useState<string>("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [toolOpen, setToolOpen] = useState<Set<string>>(new Set());

  const eventSourceRef = useRef<EventSource | null>(null);
  const sendingRef = useRef(false);

  const currentSession = sessions.find((s) => s.session_id === currentSessionId);

  useEffect(() => { loadSessions(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { refreshCopilotContext(); }, [currentScreen, stock, refreshCopilotContext]);

  async function loadSessions() {
    try {
      const items = await fetchSessions();
      setSessions(items);
      if (items.length > 0 && !currentSessionId) {
        setCurrentSessionId(items[0].session_id);
        loadMessages(items[0].session_id);
      }
    } catch { /* empty */ }
  }

  async function loadMessages(sessionId: string, runId?: string) {
    try {
      const items = await fetchSessionMessages(sessionId, runId);
      setMessages(items);
    } catch { /* empty */ }
  }

  const switchSession = useCallback(async (id: string) => {
    if (id === currentSessionId) return;
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    sendingRef.current = false;
    setCurrentSessionId(id);
    setMessages([]);
    setStreamingReasoningText("");
    setCopilotStreaming(false);
    setSending(false);
    await loadMessages(id);
  }, [currentSessionId, setCopilotStreaming, setStreamingReasoningText]);

  const handleNewSession = useCallback(async () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    sendingRef.current = false;
    try {
      const session = await createSession("新会话");
      setSessions((prev) => [session, ...prev]);
      setCurrentSessionId(session.session_id);
      setMessages([]);
      setStreamingReasoningText("");
      setCopilotStreaming(false);
      setSending(false);
    } catch { /* empty */ }
  }, [setCopilotStreaming, setStreamingReasoningText]);

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
  }, [currentSessionId, sessions]);

  const handleSend = useCallback(async (input: string) => {
    const text = input.trim();
    if (!text || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    setCopilotStreaming(true);
    setReasoningText("AI 正在思考...");

    try {
      let sid = currentSessionId;
      if (!sid) {
        const existing = await fetchSessions();
        const session = existing[0] ?? await createSession(`${stock} 对话`);
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
      // 清理之前run的中间消息，保留用户消息和final_answer，然后追加新消息
      setMessages((prev) => {
        const cleaned = prev.filter((m) => {
          if (m.kind === "user_message") return true;
          if (m.kind === "final_answer") return true;
          return false;
        });
        return [...cleaned, userMsg];
      });

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

      // 收集partial_answer文本
      es.addEventListener("partial_answer", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          const t = (data?.payload?.text as string) || "";
          if (t) {
            finalAnswerText += t;
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

        // 创建最终消息
        if (finalAnswerText) {
          const finalMsg: CopilotMessage = {
            message_id: `msg-final-${run.run_id.slice(-8)}`,
            session_id: sid,
            role: "assistant",
            kind: "final_answer",
            text: finalAnswerText,
            payload: finalPayload || {},
            created_at: new Date().toISOString(),
            run_id: run.run_id,
          };
          setMessages((prev) => [...prev, finalMsg]);
        }

        setReasoningText("");
        setCopilotStreaming(false);
        setSending(false);
        sendingRef.current = false;
        loadSessions();
      });

      // 处理error事件
      es.addEventListener("error", (streamEvent: Event) => {
        try {
          const data = JSON.parse((streamEvent as MessageEvent).data);
          errorText = String(data?.payload?.error || "stream error");
        } catch { /* empty */ }
        
        // 关闭EventSource
        es.close();
        eventSourceRef.current = null;

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
