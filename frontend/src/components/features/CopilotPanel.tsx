import React, { useRef, useCallback, useEffect, useMemo } from "react";
import { useAppState } from "@/hooks/useAppState";
import type { Screen } from "@/types";
import { parseCopilotEvent, EVENT_FINAL, EVENT_ERROR, EVENT_TOOL_CALL, EVENT_TOOL_RESULT, EVENT_PARTIAL_ANSWER } from "@/api/copilot";
import { parseTaskToolPayload } from "@/components/features/taskToolMeta";
import type { CopilotMessage } from "@/api/client";
import { useCopilotChat, extractToolResultText, type StreamToolCall } from "@/hooks/useCopilotChat";
import { useChatDetail } from "@/hooks/useChatDetail";
import { CopilotMessageItem, type ToolInfo } from "@/components/features/CopilotMessageItem";
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
  /** task 委派的子代理类型 */
  subagentType?: string;
  taskDescription?: string;
  taskPrompt?: string;
};

type GroupedItem =
  | { t: "msg"; msg: CopilotMessage; aborted?: boolean }
  | { t: "ai"; msg: CopilotMessage; tools: ToolItem[] };

function pairMessages(msgs: CopilotMessage[], activeRunId?: string | null): GroupedItem[] {
  // 识别已完成的 run（有 final_answer 或 error），并按 call_id 预收集 tool_result。
  // 不能按相邻位置配对：模型常一次批量发多个 tool_call，顺序是 call×N 再 result×N，
  // 相邻配对会全部落空、把成功的工具误判为失败。改为按 call_id 匹配。
  const completedRuns = new Set<string>();
  const lastFinalIndex = new Map<string, number>();
  const resultByCallId = new Map<string, Record<string, unknown>>();
  for (let idx = 0; idx < msgs.length; idx++) {
    const msg = msgs[idx];
    const ev = parseCopilotEvent(msg as unknown as Record<string, unknown>);
    if (msg.run_id) {
      if (msg.kind === "final_answer") {
        completedRuns.add(msg.run_id);
        lastFinalIndex.set(msg.run_id, idx);
      } else if (ev.type === EVENT_ERROR) {
        completedRuns.add(msg.run_id);
      }
    }
    if (ev.type === EVENT_TOOL_RESULT) {
      const cid = (ev.payload as Record<string, unknown>)?.call_id;
      if (cid) resultByCallId.set(String(cid), ev.payload as Record<string, unknown>);
    }
  }

  const out: GroupedItem[] = [];
  const pendingTools = new Map<string, ToolItem[]>();

  for (let i = 0; i < msgs.length; i++) {
    const msg = msgs[i];
    const ev = parseCopilotEvent(msg as unknown as Record<string, unknown>);
    const rid = msg.run_id || "";

    if (ev.type === EVENT_TOOL_CALL) {
      const p = ev.payload as Record<string, unknown>;
      const name = String(p?.tool || "tool");
      const cid = p?.call_id ? String(p.call_id) : "";
      const resultPayload = cid ? resultByCallId.get(cid) : undefined;
      const matched = !!resultPayload;
      const resultText = extractToolResultText(resultPayload);
      const failed = !matched && !!msg.run_id && completedRuns.has(msg.run_id);
      let subagentType: string | undefined;
      let taskDescription: string | undefined;
      let taskPrompt: string | undefined;
      if (name === "task") {
        const meta = parseTaskToolPayload(p);
        subagentType = meta.subagentType;
        taskDescription = meta.description;
        taskPrompt = meta.prompt;
      }
      const tools = pendingTools.get(rid) || [];
      tools.push({
        t: "tool", name, done: matched, failed, id: msg.message_id, created_at: msg.created_at,
        resultText, subagentType, taskDescription, taskPrompt,
      });
      pendingTools.set(rid, tools);
    } else if (ev.type === EVENT_TOOL_RESULT) {
      // 已在预扫描中按 call_id 收集，配对到对应 tool_call；此处跳过，不单独渲染。
      continue;
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
      // 无终局(final/error)且非进行中的 run:流被中断,给占位说明,别让消息悬空
      const aborted = !!msg.run_id && !completedRuns.has(msg.run_id) && msg.run_id !== activeRunId;
      out.push({ t: "msg", msg, aborted });
    }
  }

  return out;
}

/** 三栏布局的中栏常驻聊天(会话管理在 LeftSidebar; Composer 在 BottomBar) */
export function CopilotPanel() {
  const {
    copilotContextVersion,
    setCurrentScreen, setStock,
  } = useAppState();

  const {
    messages,
    sending, streamMessage, copiedId,
    handleCopy,
  } = useCopilotChat();

  const { openDetail } = useChatDetail();
  // 工具卡 → 右栏详情联动
  const handleToolClick = useMemo(() => {
    return (t: ToolInfo) => openDetail({
      id: t.id,
      name: t.name,
      status: t.failed ? "failed" : t.done ? "done" : "running",
      resultText: t.resultText,
      subagentType: t.subagentType,
      taskDescription: t.taskDescription,
      taskPrompt: t.taskPrompt,
    });
  }, [openDetail]);
  const handleStreamToolClick = useMemo(() => {
    return (t: StreamToolCall) => openDetail({
      id: t.callId,
      name: t.name,
      status: t.status,
      resultText: t.resultText,
      subagentType: t.subagentType,
      taskDescription: t.taskDescription,
      taskPrompt: t.taskPrompt,
    });
  }, [openDetail]);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, streamMessage, scrollToBottom]);

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
    const paired = pairMessages(messages, streamMessage?.runId);
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
              <CopilotMessageItem msg={item.msg} tools={item.tools} onToolClick={handleToolClick} />
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
          {item.t === "msg" && item.aborted && (
            <div className="msg-aborted">— 本轮已中断,未生成回答 —</div>
          )}
        </React.Fragment>
      );
    });
  }, [messages, streamMessage?.runId, copiedId, handleCopy, handleNavigate, handleApi, handleToolClick]);

  return (
    <aside className="copilot-panel copilot-panel-main">
      <div className="copilot-body">
        <div className="messages">
          <ContextCard key={`ctx-${copilotContextVersion}`} />

          {messages.length === 0 && !sending && (
            <div className="empty-state">
              <div style={{ fontWeight: 600, marginBottom: 6 }}>开始一段对话</div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>研究个股、检查持仓风险、跑回测,或随便聊聊</div>
            </div>
          )}

          {messageElements}

          {streamMessage && <CopilotStreamingMessage streamMessage={streamMessage} onToolClick={handleStreamToolClick} />}

          <div ref={messagesEndRef} />
        </div>
      </div>
    </aside>
  );
}
