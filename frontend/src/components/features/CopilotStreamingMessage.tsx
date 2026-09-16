import { useMemo } from "react";
import { type StreamMessage, type StreamToolCall } from "@/hooks/useCopilotChat";
import { CopilotFinalMeta, SkillTraceChain } from "@/components/features/CopilotFinalMeta";
import { ThoughtTimeline } from "@/components/features/ThoughtTimeline";
import { HumanInputCard } from "@/components/features/HumanInputCard";
import { StreamMarkdown } from "@/components/features/StreamMarkdown";
import { StreamAwaitingDots } from "@/components/features/StreamAwaitingDots";
import { useStreamAwaitingNextEvent } from "@/hooks/useStreamAwaitingNextEvent";
import { streamProgressKey } from "@/lib/chatShell";
import type { HumanInputResponse } from "@/lib/humanInput";

interface Props {
  streamMessage: StreamMessage;
  /** 提供时流式工具卡可点击（聊天中心主区 → 右栏详情联动） */
  onToolClick?: (tool: StreamToolCall) => void;
  /** Human Input Card 提交（选项 / 卡片内文本） */
  onClarifySubmit?: (response: HumanInputResponse, displayText: string) => void;
  clarifyPending?: boolean;
}

const PHASE_LABELS: Record<string, string> = {
  error: "出错",
  final: "完成",
  answering: "生成回答",
  tools: "调用工具",
  reasoning: "推理中",
};

const PHASE_COLORS: Record<string, string> = {
  error: "var(--red)",
  final: "var(--green)",
  answering: "var(--green)",
  tools: "var(--amber)",
  reasoning: "var(--blue)",
};

export function CopilotStreamingMessage({
  streamMessage,
  onToolClick,
  onClarifySubmit,
  clarifyPending,
}: Props) {
  const hasContent = streamMessage.answerText.length > 0 || streamMessage.phase === "final" || streamMessage.phase === "error";
  const phaseLabel = PHASE_LABELS[streamMessage.phase] || "推理中";
  const phaseColor = PHASE_COLORS[streamMessage.phase] || "var(--blue)";
  const streamingActive = streamMessage.phase !== "final" && streamMessage.phase !== "error";
  const clarificationRequest = streamMessage.clarificationRequest;

  const progressRevision = useMemo(
    () => streamProgressKey({
      phase: streamMessage.phase,
      answerText: streamMessage.answerText,
      toolCount: streamMessage.tools.length + streamMessage.steps.length,
      clarification: Boolean(streamMessage.clarificationRequest || streamMessage.clarificationText),
      errorText: streamMessage.errorText,
    }),
    [streamMessage],
  );

  const awaitingNext = useStreamAwaitingNextEvent(streamingActive, progressRevision);
  // 推理阶段顶部已有「推理中」，不再叠一层「思考中」
  const showAwaitingDots = awaitingNext
    && streamMessage.phase !== "reasoning"
    && !clarificationRequest
    && !streamMessage.clarificationText;

  return (
    <div className={`msg ai${hasContent ? "" : " streaming"}`}>
      <div className="msg-label">
        <span className="ai-disc">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
              <polyline points="4,17 10,11 13,14 20,6"/>
            </svg>
          </span>
        AI Copilot
        <span style={{ fontSize: 10, color: phaseColor, marginLeft: "auto", display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: phaseColor,
            boxShadow: `0 0 8px ${phaseColor}`,
            animation: streamingActive ? "pulse 1s infinite" : "none"
          }} />
          {phaseLabel}
        </span>
      </div>
      {streamMessage.phase !== "final" && <SkillTraceChain items={streamMessage.skillTrace} />}
      {streamMessage.todos.length > 0 && (
        <div className="plan-todos">
          <div className="plan-todos-title">📋 执行计划</div>
          {streamMessage.todos.map((todo, i) => (
            <div key={i} className={`plan-todo ${todo.status}`}>
              <span className="plan-todo-mark">
                {todo.status === "completed" ? "✓" : todo.status === "in_progress" ? "▸" : "·"}
              </span>
              {todo.content}
            </div>
          ))}
        </div>
      )}
      <ThoughtTimeline steps={streamMessage.steps} active={streamingActive} onToolClick={onToolClick} />
      {clarificationRequest && (
        <HumanInputCard
          request={clarificationRequest}
          pending={clarifyPending}
          onSubmit={onClarifySubmit
            ? (response) => {
                void onClarifySubmit(response, response.value);
              }
            : undefined}
        />
      )}
      {!clarificationRequest && streamMessage.clarificationText && (
        <div className="clarification-card">
          <div className="clarification-title">AI 需要你的补充信息</div>
          <div style={{ whiteSpace: "pre-wrap" }}>{streamMessage.clarificationText}</div>
          <div className="clarification-hint">直接在下方输入框回答即可继续</div>
        </div>
      )}
      {!clarificationRequest && !streamMessage.clarificationText && streamMessage.answerText && (
        <div className={streamMessage.phase === "final" ? "" : "cursor-blink"}>
          <StreamMarkdown
            text={streamMessage.answerText}
            streaming={streamingActive}
          />
        </div>
      )}
      {showAwaitingDots && (
        <StreamAwaitingDots
          label={streamMessage.phase === "tools" ? "工具执行中" : "继续生成中"}
        />
      )}
      {streamMessage.phase === "final"
        && streamMessage.finalPayload
        && !clarificationRequest
        && !streamMessage.clarificationText && (
        <CopilotFinalMeta payload={streamMessage.finalPayload} />
      )}
      {streamMessage.errorText && (
        <div style={{ color: "var(--red)" }}>⚠️ {streamMessage.errorText}</div>
      )}
    </div>
  );
}
