import React, { useRef, useCallback, useEffect, useMemo, useState } from "react";
import { useAppState } from "@/hooks/useAppState";
import { parseCopilotEvent, EVENT_FINAL, EVENT_ERROR, EVENT_TOOL_CALL, EVENT_TOOL_RESULT, EVENT_PARTIAL_ANSWER, EVENT_CLARIFICATION } from "@/api/copilot";
import { parseTaskToolPayload } from "@/components/features/taskToolMeta";
import type { CopilotMessage, HealthCheck } from "@/api/client";
import { useCopilotChat, extractToolResultText, type StreamToolCall } from "@/hooks/useCopilotChat";
import { useChatDetail } from "@/hooks/useChatDetail";
import { CopilotMessageItem, type ToolInfo } from "@/components/features/CopilotMessageItem";
import { CopilotStreamingMessage } from "@/components/features/CopilotStreamingMessage";
import { ContextCard } from "@/components/features/ContextCard";
import { TurnFailureStatus } from "@/components/features/TurnFailureStatus";
import { useMobileLayout } from "@/hooks/useMobileLayout";
import { EMPTY_CHAT_COPY, isModelReady, STARTER_PROMPTS } from "@/lib/onboarding";
import { NEAR_BOTTOM_THRESHOLD, SAFE_BOTTOM_SPACING } from "@/lib/chatShell";
import type { HumanInputResponse } from "@/lib/humanInput";

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
  | {
      t: "msg";
      msg: CopilotMessage;
      /** 零输出中断：挂在用户消息下 */
      aborted?: boolean;
      /** 有工具过程但无 final：过程挂在对应用户轮次下 */
      incomplete?: boolean;
      tools?: ToolItem[];
    }
  | { t: "ai"; msg: CopilotMessage; tools: ToolItem[] };

/** 把未完成 run 的工具过程挂到对应用户消息上，禁止合成空 AI 气泡。 */
function attachIncompleteToUser(
  out: GroupedItem[],
  rid: string,
  tools: ToolItem[],
) {
  if (!rid || !tools.length) return;
  for (let j = out.length - 1; j >= 0; j--) {
    const item = out[j];
    if (item.t === "msg" && item.msg.role === "user" && item.msg.run_id === rid) {
      out[j] = {
        ...item,
        aborted: false,
        incomplete: true,
        tools: [...(item.tools || []), ...tools],
      };
      return;
    }
  }
}

export function pairMessages(msgs: CopilotMessage[], activeRunId?: string | null): GroupedItem[] {
  // 识别已完成的 run（有 final_answer 或 error），并按 call_id 预收集 tool_result。
  // 不能按相邻位置配对：模型常一次批量发多个 tool_call，顺序是 call×N 再 result×N，
  // 相邻配对会全部落空、把成功的工具误判为失败。改为按 call_id 匹配。
  const completedRuns = new Set<string>();
  const runsWithOutput = new Set<string>();
  const clarificationRuns = new Set<string>();
  const lastFinalIndex = new Map<string, number>();
  const resultByCallId = new Map<string, Record<string, unknown>>();
  for (let idx = 0; idx < msgs.length; idx++) {
    const msg = msgs[idx];
    const ev = parseCopilotEvent(msg as unknown as Record<string, unknown>);
    if (msg.run_id && msg.role !== "user") {
      runsWithOutput.add(msg.run_id);
    }
    if (msg.run_id) {
      if (msg.kind === "final_answer") {
        completedRuns.add(msg.run_id);
        lastFinalIndex.set(msg.run_id, idx);
      } else if (ev.type === EVENT_ERROR) {
        completedRuns.add(msg.run_id);
      }
      if (msg.kind === "clarification" || ev.type === EVENT_CLARIFICATION) {
        clarificationRuns.add(msg.run_id);
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
      // 澄清轮的开场白/半截正文也不单独成泡，正文在 Human Input Card
      if (rid && clarificationRuns.has(rid)) continue;
      // 空 partial 不占位（避免空气泡）
      if (!(msg.text || "").trim()) continue;
      out.push({ t: "msg", msg });
    } else if (ev.type === EVENT_CLARIFICATION || msg.kind === "clarification") {
      out.push({ t: "msg", msg, tools: [] });
    } else if (ev.type === EVENT_FINAL || ev.type === EVENT_ERROR) {
      const payload = (ev.payload || {}) as Record<string, unknown>;
      const isClarificationFinal = ev.type === EVENT_FINAL && (
        Boolean(payload.clarification) || (rid !== "" && clarificationRuns.has(rid))
      );
      // 跳过空的 / 澄清轮次的 final_answer（问题正文只在 Human Input Card）
      if (ev.type === EVENT_FINAL && (!msg.text || isClarificationFinal)) {
        const tools = pendingTools.get(rid) || [];
        pendingTools.delete(rid);
        if (tools.length) {
          for (let j = out.length - 1; j >= 0; j--) {
            const item = out[j];
            if (item.t === "msg" && item.msg.run_id === rid && item.msg.kind === "clarification") {
              out[j] = { ...item, tools: [...(item.tools || []), ...tools] };
              break;
            }
          }
        }
        continue;
      }
      // 跳过非最后一条 final_answer（修复重复 final 问题）
      if (ev.type === EVENT_FINAL && rid && lastFinalIndex.get(rid) !== i) continue;
      const tools = pendingTools.get(rid) || [];
      pendingTools.delete(rid);
      out.push({ t: "ai", msg, tools });
    } else if (msg.role === "user") {
      if (msg.run_id) {
        for (const [pendingRid, tools] of [...pendingTools.entries()]) {
          if (pendingRid === msg.run_id || completedRuns.has(pendingRid)) continue;
          attachIncompleteToUser(out, pendingRid, tools);
          pendingTools.delete(pendingRid);
        }
      }
      // 仅当 run 完全没有任何助手/工具输出时才视为「空失败」；有工具过程挂 incomplete。
      const aborted = !!msg.run_id
        && !completedRuns.has(msg.run_id)
        && msg.run_id !== activeRunId
        && !runsWithOutput.has(msg.run_id);
      out.push({ t: "msg", msg, aborted });
    }
  }

  for (const [rid, tools] of pendingTools) {
    if (!tools.length || completedRuns.has(rid)) continue;
    if (rid === activeRunId) continue;
    attachIncompleteToUser(out, rid, tools);
  }

  return out;
}

/** 三栏布局的中栏常驻聊天(会话管理在 LeftSidebar; Composer 在 BottomBar) */
export function CopilotPanel() {
  const mobile = useMobileLayout();
  const {
    copilotContextVersion,
    appDataCache, globalLoading, lastRefreshTime,
  } = useAppState();

  const {
    messages,
    sending, streamMessage,
    handleSend, handleRetry,
  } = useCopilotChat();

  const answeredByRequestId = useMemo(() => {
    const map = new Map<string, HumanInputResponse>();
    for (const m of messages) {
      if (m.role !== "user") continue;
      const raw = (m.payload as { human_input_response?: unknown } | undefined)?.human_input_response;
      if (!raw || typeof raw !== "object") continue;
      const r = raw as HumanInputResponse;
      if (r.kind === "human_input_response" && r.request_id && r.value) {
        map.set(r.request_id, r);
      }
    }
    return map;
  }, [messages]);

  const handleClarifySubmit = useCallback((response: HumanInputResponse, displayText: string) => {
    void handleSend(displayText, undefined, [], response);
  }, [handleSend]);

  const modelReady = useMemo(() => {
    void globalLoading;
    void lastRefreshTime;
    const health = appDataCache.current.health as HealthCheck | undefined;
    return isModelReady(health);
  }, [appDataCache, globalLoading, lastRefreshTime]);

  const { openDetail } = useChatDetail();
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
  const bodyRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const [showJumpBottom, setShowJumpBottom] = useState(false);

  const scrollToBottom = useCallback((smooth = true) => {
    messagesEndRef.current?.scrollIntoView({ behavior: smooth ? "smooth" : "auto" });
  }, []);

  const onBodyScroll = useCallback(() => {
    const el = bodyRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    const near = dist <= NEAR_BOTTOM_THRESHOLD;
    stickToBottomRef.current = near;
    setShowJumpBottom(!near && (messages.length > 0 || Boolean(streamMessage)));
  }, [messages.length, streamMessage]);

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    scrollToBottom();
  }, [messages, streamMessage, scrollToBottom]);

  const renderActions = useCallback((opts: {
    msg: CopilotMessage;
    showRetry?: boolean;
  }) => {
    const { msg, showRetry } = opts;
    if (!showRetry) return null;
    return (
      <div className="msg-actions">
        <button
          type="button"
          className="msg-action"
          disabled={sending}
          onClick={() => void handleRetry(msg.run_id)}
          title="用同一条用户消息重试"
        >
          重试
        </button>
      </div>
    );
  }, [handleRetry, sending]);

  const messageElements = useMemo(() => {
    const paired = pairMessages(messages, streamMessage?.runId);
    const dateFlags = new Array<boolean>(paired.length);
    let prevDate = "";
    for (let i = 0; i < paired.length; i++) {
      const p = paired[i];
      const ts = p.t === "ai" ? p.msg.created_at : p.msg.created_at;
      const msgDate = (ts || "").slice(0, 10);
      dateFlags[i] = msgDate !== "" && msgDate !== prevDate;
      if (msgDate) prevDate = msgDate;
    }

    // 仅最新一条失败轮可重试：后面已有新对话/更新失败时，旧失败降噪且不可重试
    const lastFailureIdx = (() => {
      for (let i = paired.length - 1; i >= 0; i--) {
        const p = paired[i];
        if (p.t === "msg" && (p.aborted || p.incomplete)) return i;
        if (p.t === "msg" && (
          p.msg.kind === "error"
          || parseCopilotEvent(p.msg as unknown as Record<string, unknown>).type === EVENT_ERROR
        )) return i;
        if (p.t === "ai" && (
          p.msg.kind === "error"
          || parseCopilotEvent(p.msg as unknown as Record<string, unknown>).type === EVENT_ERROR
        )) return i;
      }
      return -1;
    })();

    return paired.map((item, idx) => {
      const showHeader = dateFlags[idx];
      const ts = item.t === "ai" ? item.msg.created_at : item.msg.created_at;
      const msgDate = (ts || "").slice(0, 10);
      const isError = item.t === "msg" && (
        item.msg.kind === "error" || parseCopilotEvent(item.msg as unknown as Record<string, unknown>).type === EVENT_ERROR
      );
      const isAiError = item.t === "ai" && (
        item.msg.kind === "error" || parseCopilotEvent(item.msg as unknown as Record<string, unknown>).type === EVENT_ERROR
      );
      const isFailureTurn = item.t === "msg"
        && (Boolean(item.aborted) || Boolean(item.incomplete) || isError);
      const canRetryFailure = idx === lastFailureIdx && (isFailureTurn || isAiError);
      const failureStale = isFailureTurn && idx !== lastFailureIdx;

      if (item.t === "ai") {
        return (
          <React.Fragment key={item.msg.message_id}>
            {showHeader && <div className="date-divider">{dateHeader(msgDate)}</div>}
            <div className="msg-block">
              <CopilotMessageItem msg={item.msg} tools={item.tools} onToolClick={handleToolClick} />
              {renderActions({
                msg: item.msg,
                showRetry: canRetryFailure && isAiError,
              })}
            </div>
          </React.Fragment>
        );
      }

      const toolInfos = item.tools?.map((t) => ({
        name: t.name,
        done: t.done,
        failed: t.failed,
        id: t.id,
        resultText: t.resultText,
        subagentType: t.subagentType,
        taskDescription: t.taskDescription,
        taskPrompt: t.taskPrompt,
      }));

      return (
        <React.Fragment key={item.msg.message_id}>
          {showHeader && <div className="date-divider">{dateHeader(msgDate)}</div>}
          <div className="msg-block">
            <CopilotMessageItem
              msg={item.msg}
              tools={item.incomplete ? undefined : toolInfos}
              onToolClick={!item.incomplete && item.tools?.length ? handleToolClick : undefined}
              clarifiedResponse={
                item.msg.kind === "clarification"
                  ? answeredByRequestId.get(String(
                    (item.msg.payload as { request_id?: string })?.request_id
                    || `clarification:${(item.msg.payload as { call_id?: string })?.call_id || ""}`,
                  )) ?? null
                  : null
              }
              onClarifySubmit={
                item.msg.kind === "clarification"
                  && !answeredByRequestId.has(String(
                    (item.msg.payload as { request_id?: string })?.request_id
                    || `clarification:${(item.msg.payload as { call_id?: string })?.call_id || ""}`,
                  ))
                  ? handleClarifySubmit
                  : undefined
              }
              clarifyPending={item.msg.kind === "clarification" ? sending : undefined}
            />
            {renderActions({
              msg: item.msg,
              // incomplete/aborted 由 TurnFailureStatus 内重试，避免双按钮
              showRetry: canRetryFailure && !item.aborted && !item.incomplete,
            })}
          </div>
          {(item.aborted || item.incomplete) && (
            <TurnFailureStatus
              runId={item.msg.run_id}
              empty={Boolean(item.aborted) && !item.incomplete}
              tools={item.incomplete ? toolInfos : undefined}
              stale={failureStale}
              retryDisabled={sending || !canRetryFailure}
              onRetry={canRetryFailure ? () => void handleRetry(item.msg.run_id) : undefined}
              onToolClick={handleToolClick}
            />
          )}
        </React.Fragment>
      );
    });
  }, [
    messages, streamMessage?.runId, handleToolClick, answeredByRequestId,
    handleClarifySubmit, sending, renderActions, handleRetry,
  ]);

  return (
    <aside className="copilot-panel copilot-panel-main">
      <div
        className="copilot-body"
        ref={bodyRef}
        onScroll={onBodyScroll}
        style={{ paddingBottom: SAFE_BOTTOM_SPACING }}
      >
        <div className="messages">
          <ContextCard key={`ctx-${copilotContextVersion}`} />

          {messages.length === 0 && !sending && (
            <div className="empty-state">
              <div className="empty-kicker">Stock Agent</div>
              <div className="empty-title">{mobile ? "有什么可以帮你？" : EMPTY_CHAT_COPY.title}</div>
              <div className="empty-desc">{EMPTY_CHAT_COPY.desc}</div>
              <div className="starter-chips">
                {STARTER_PROMPTS.map((item) => (
                  <button
                    key={item.label}
                    type="button"
                    className="followup-chip"
                    title={modelReady ? item.label : "请先接上对话模型"}
                    disabled={sending || !modelReady}
                    onClick={() => void handleSend(item.prompt)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messageElements}

          {streamMessage && (
            <CopilotStreamingMessage
              streamMessage={streamMessage}
              onToolClick={handleStreamToolClick}
              onClarifySubmit={handleClarifySubmit}
              clarifyPending={sending}
            />
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>
      {showJumpBottom ? (
        <button
          type="button"
          className="jump-bottom"
          onClick={() => {
            stickToBottomRef.current = true;
            setShowJumpBottom(false);
            scrollToBottom();
          }}
        >
          回到底部
        </button>
      ) : null}
    </aside>
  );
}
