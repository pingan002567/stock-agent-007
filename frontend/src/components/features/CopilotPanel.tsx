import React, { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { useAppState } from "@/hooks/useAppState";
import type { Screen } from "@/types";
import { parseCopilotEvent, EVENT_FINAL, EVENT_ERROR, EVENT_TOOL_CALL, EVENT_PARTIAL_ANSWER } from "@/api/copilot";
import type { CopilotMessage } from "@/api/client";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import { CopilotMessageItem } from "@/components/features/CopilotMessageItem";
import { CopilotStreamingMessage } from "@/components/features/CopilotStreamingMessage";
import { ContextCard } from "@/components/features/ContextCard";
import { NextActions } from "@/components/features/NextActions";

function dateHeader(dateStr: string): string {
  const d = new Date(dateStr);
  const today = new Date();
  const y = new Date(today);
  y.setDate(y.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "今天";
  if (d.toDateString() === y.toDateString()) return "昨天";
  const w = d.getTime();
  const tw = today.getTime();
  if (tw - w < 7 * 86400000) return ["周日","周一","周二","周三","周四","周五","周六"][d.getDay()];
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

type ToolItem = {
  t: "tool";
  name: string;
  done: boolean;
  failed?: boolean;
  id: string;
  created_at: string;
  resultText?: string;
};

type GroupedItem =
  | { t: "msg"; msg: CopilotMessage }
  | { t: "ai"; msg: CopilotMessage; tools: ToolItem[] };

function pairMessages(msgs: CopilotMessage[]): GroupedItem[] {
  // 识别已完成的 run（有 final_answer 或 error）
  const completedRuns = new Set<string>();
  // 记录每个 run 最后一条 final_answer 的 index
  const lastFinalIndex = new Map<string, number>();
  for (let idx = 0; idx < msgs.length; idx++) {
    const msg = msgs[idx];
    if (msg.run_id) {
      if (msg.kind === "final_answer") {
        completedRuns.add(msg.run_id);
        lastFinalIndex.set(msg.run_id, idx);
      } else {
        const ev = parseCopilotEvent(msg as unknown as Record<string, unknown>);
        if (ev.type === EVENT_ERROR) completedRuns.add(msg.run_id);
      }
    }
  }

  const out: GroupedItem[] = [];
  const pendingTools = new Map<string, ToolItem[]>();

  for (let i = 0; i < msgs.length; i++) {
    const msg = msgs[i];
    const ev = parseCopilotEvent(msg as unknown as Record<string, unknown>);
    const rid = msg.run_id || "";

    if (ev.type === EVENT_TOOL_CALL) {
      const name = String((ev.payload as Record<string, unknown>)?.tool || "tool");
      const next = i + 1 < msgs.length ? msgs[i + 1] : null;
      let resultText: string | undefined;
      let matched = false;
      if (next) {
        const nextEv = parseCopilotEvent(next as unknown as Record<string, unknown>);
        if (nextEv.type === "tool_result") {
          const np = nextEv.payload as Record<string, unknown>;
          const textResult = np.text || np.output || np.result || "";
          resultText = typeof textResult === "string" ? textResult : JSON.stringify(textResult);
          matched = true;
          i++;
        }
      }
      const failed = !matched && !!msg.run_id && completedRuns.has(msg.run_id);
      const tools = pendingTools.get(rid) || [];
      tools.push({ t: "tool", name, done: matched, failed, id: msg.message_id, created_at: msg.created_at, resultText });
      pendingTools.set(rid, tools);
    } else if (ev.type === EVENT_PARTIAL_ANSWER) {
      // 如果该 run 已完成，跳过 partial_answer
      if (msg.run_id && completedRuns.has(msg.run_id)) continue;
      out.push({ t: "msg", msg });
    } else if (ev.type === EVENT_FINAL || ev.type === EVENT_ERROR) {
      // 跳过空的 final_answer
      if (ev.type === EVENT_FINAL && !msg.text) continue;
      // 跳过非最后一条 final_answer（修复重复 final 问题）
      if (ev.type === EVENT_FINAL && rid && lastFinalIndex.get(rid) !== i) continue;
      const tools = pendingTools.get(rid) || [];
      pendingTools.delete(rid);
      out.push({ t: "ai", msg, tools });
    } else if (msg.role === "user") {
      out.push({ t: "msg", msg });
    }
  }

  return out;
}

export function CopilotPanel({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const {
    copilotContextVersion,
    setCurrentScreen, setStock, appDataCache,
  } = useAppState();

  const {
    currentSession, sessions,
    messages,
    sending, streamMessage, copiedId,
    switchSession, handleNewSession, handleRenameSession, handleDeleteSession,
    handleSend: sendMessage, handleStop,
    handleCopy,
  } = useCopilotChat();

  const [input, setInput] = useState("");
  const [sessionOpen, setSessionOpen] = useState(false);
  const [sessionRename, setSessionRename] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [sessionDelete, setSessionDelete] = useState<string | null>(null);

  const suggestions = [
    { text: "分析 AAPL 风险", icon: "📊" },
    { text: "查看持仓概况", icon: "💰" },
    { text: "今日市场动态", icon: "📈" },
    { text: "检查监控告警", icon: "🔔" },
  ];

  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sessionRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const autoResize = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, streamMessage, scrollToBottom]);

  useEffect(() => {
    if (!sessionOpen) return;
    const handler = (e: MouseEvent) => {
      if (sessionRef.current && !sessionRef.current.contains(e.target as Node)) setSessionOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [sessionOpen]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSend = () => {
    const text = input;
    if (!text.trim()) return;
    setInput("");
    if (inputRef.current) { inputRef.current.style.height = "auto"; }
    sendMessage(text);
  };

  const handleNavigate = useCallback((screen: string, stockParam?: string) => {
    if (stockParam) setStock(stockParam);
    setCurrentScreen(screen as Screen);
  }, [setStock, setCurrentScreen]);

  const handleApi = useCallback(async (endpoint: string, symbol: string) => {
    try {
      if (endpoint === "watchlist") {
        await fetch("/api/watchlist/items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol, name: symbol, market: "" }),
        });
      } else if (endpoint === "watchlist_remove") {
        await fetch(`/api/watchlist/items/${encodeURIComponent(symbol)}`, { method: "DELETE" });
      }
    } catch { /* empty */ }
  }, []);

  const messageElements = useMemo(() => {
    const paired = pairMessages(messages);
    /** Compute date-header flags by index — avoids let-reassignment in render */
    const dateFlags = new Array<boolean>(paired.length);
    let prevDate = "";
    for (let i = 0; i < paired.length; i++) {
      const p = paired[i];
      const ts = p.t === "ai" ? p.msg.created_at : p.msg.created_at;
      const msgDate = (ts || "").slice(0, 10);
      dateFlags[i] = msgDate !== "" && msgDate !== prevDate;
      if (msgDate) prevDate = msgDate;
    }

    return paired.map((item, idx) => {
      const showHeader = dateFlags[idx];
      const ts = item.t === "ai" ? item.msg.created_at : item.msg.created_at;
      const msgDate = (ts || "").slice(0, 10);

      if (item.t === "ai") {
        const evFinal = parseCopilotEvent(item.msg as unknown as Record<string, unknown>);
        const isFinalAnswer = item.msg.kind === "final_answer";
        const suggestedActions = isFinalAnswer
          ? ((evFinal.payload as { suggested_actions?: Array<{ label: string; icon: string; action_type: string; screen?: string; stock?: string; endpoint?: string; symbol?: string }> }).suggested_actions)
          : undefined;
        return (
          <React.Fragment key={item.msg.message_id}>
            {showHeader && <div className="date-divider">{dateHeader(msgDate)}</div>}
            <div style={{ position: "relative" }}>
              <CopilotMessageItem msg={item.msg} tools={item.tools} />
              <button className="msg-copy" onClick={() => handleCopy(item.msg)} title="复制">
                {copiedId === item.msg.message_id ? "已复制" : "复制"}
              </button>
            </div>
            {suggestedActions && suggestedActions.length > 0 && (
              <NextActions actions={suggestedActions} onNavigate={handleNavigate} onApi={handleApi} />
            )}
          </React.Fragment>
        );
      }

      return (
        <React.Fragment key={item.msg.message_id}>
          {showHeader && <div className="date-divider">{dateHeader(msgDate)}</div>}
          <div style={{ position: "relative" }}>
            <CopilotMessageItem msg={item.msg} />
            <button className="msg-copy" onClick={() => handleCopy(item.msg)} title="复制">
              {copiedId === item.msg.message_id ? "已复制" : "复制"}
            </button>
          </div>
        </React.Fragment>
      );
    });
  }, [messages, copiedId, handleCopy, handleNavigate, handleApi]);

  if (!open) {
    return <button className="copilot-tab" onClick={onToggle} title="展开 AI 对话">‹</button>;
  }

  return (
    <aside className="copilot-panel">
      <div className="copilot-head">
        <div ref={sessionRef} style={{ position: "relative" }}>
          <button
            className="session-trigger"
            onClick={() => setSessionOpen((v) => !v)}
            title="会话管理"
          >
            <span className="session-trigger-dot" />
            <span className="session-trigger-text">{currentSession?.title || "选择会话"}</span>
            <span className="session-trigger-arrow">▾</span>
          </button>
          {sessionOpen && (
            <div className="session-dropdown" style={{ right: 'auto', left: 0 }}>
              <div className="session-dropdown-header">
                <span className="session-dropdown-title">会话管理</span>
                <button className="session-dropdown-new" onClick={handleNewSession}>+ 新建</button>
              </div>
              <div className="session-dropdown-list">
                {sessions.map((s) => (
                  <div key={s.session_id}>
                    {sessionRename === s.session_id ? (
                      <div className="session-rename">
                        <input
                          className="session-rename-input"
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleRenameSession(s.session_id, renameValue);
                            if (e.key === "Escape") setSessionRename(null);
                          }}
                          onBlur={() => { handleRenameSession(s.session_id, renameValue); setSessionRename(null); }}
                          autoFocus
                        />
                      </div>
                    ) : (
                      <div
                        className={`session-item${s.session_id === currentSession?.session_id ? " active" : ""}`}
                        onClick={() => switchSession(s.session_id)}
                      >
                        <div className="session-item-content">
                          <div className="session-item-title">{s.title}</div>
                          <div className="session-item-meta">
                            {s.message_count ?? 0} 条消息
                          </div>
                        </div>
                        <div className="session-item-actions">
                          <button
                            className="session-action-btn"
                            title="重命名"
                            onClick={(e) => { e.stopPropagation(); setSessionRename(s.session_id); setRenameValue(s.title); }}
                          >✎</button>
                          <button
                            className="session-action-btn danger"
                            title="删除"
                            onClick={(e) => { e.stopPropagation(); setSessionDelete(s.session_id); }}
                          >✕</button>
                        </div>
                      </div>
                    )}
                    {sessionDelete === s.session_id && (
                      <div className="session-delete-modal">
                        <div className="session-delete-content">
                          <div className="session-delete-icon">⚠️</div>
                          <div className="session-delete-title">删除会话</div>
                          <div className="session-delete-desc">
                            确定要删除会话「{s.title}」吗？此操作将删除该会话下的所有消息，且不可恢复。
                          </div>
                          <div className="session-delete-actions">
                            <button className="session-delete-cancel" onClick={() => setSessionDelete(null)}>取消</button>
                            <button className="session-delete-confirm" onClick={() => { handleDeleteSession(s.session_id); setSessionDelete(null); }}>确认删除</button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="session-dropdown-footer">
                <button className="session-dropdown-clear">清空所有会话</button>
                <button className="session-dropdown-manage">管理</button>
              </div>
            </div>
          )}
        </div>
        <div className="copilot-title" style={{ flex: 1, justifyContent: "center" }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z" fill="currentColor"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
          <span>AI Copilot</span>
        </div>
        <button className="copilot-close-btn" onClick={onToggle} title="关闭 AI Chat">›</button>
      </div>

      <div className="copilot-body">
        <div className="messages">
          <ContextCard key={`ctx-${copilotContextVersion}`} />

          {messages.length === 0 && !sending && (
            <div className="empty-state">
              <div style={{ fontWeight: 600, marginBottom: 8 }}>AI 对话助手</div>
              {suggestions.map((s) => (
                <button
                  key={s.text}
                  className="suggestion-chip"
                  onClick={() => { setInput(s.text); inputRef.current?.focus(); }}
                >
                  {s.icon} {s.text}
                </button>
              ))}
              {Array.isArray((appDataCache.current.stockFollowups as { items?: Array<{ text: string; icon?: string }> } | undefined)?.items)
                && (appDataCache.current.stockFollowups as { items?: Array<{ text: string; icon?: string }> }).items!.length > 0 && (
                <>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 12, marginBottom: 6 }}>快捷追问</div>
                  {(appDataCache.current.stockFollowups as { items?: Array<{ text: string; icon?: string }> }).items!.map((item) => (
                    <button
                      key={`${item.icon || ""}-${item.text}`}
                      className="suggestion-chip"
                      onClick={() => { setInput(item.text); inputRef.current?.focus(); }}
                    >
                      {item.icon ? `${item.icon} ` : ""}{item.text}
                    </button>
                  ))}
                </>
              )}
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>或输入消息开始对话</div>
            </div>
          )}

          {messageElements}

          {streamMessage && <CopilotStreamingMessage streamMessage={streamMessage} />}

          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="copilot-input">
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <textarea
            ref={inputRef}
            placeholder="输入您的问题..."
            value={input}
            onChange={(e) => { setInput(e.target.value); autoResize(); }}
            onKeyDown={handleKeyDown}
            rows={1}
            style={{ flex: 1 }}
          />
          {sending ? (
            <button className="btn-stop" onClick={handleStop} title="停止生成" style={{ height: 40, padding: "0 14px" }}>
              ■
            </button>
          ) : (
            <button className="primary" onClick={handleSend} disabled={sending || !input.trim()} style={{ height: 40, padding: "0 14px" }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="22" y1="2" x2="11" y2="13"/>
                <polygon points="22,2 15,22 11,13 2,9"/>
              </svg>
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
