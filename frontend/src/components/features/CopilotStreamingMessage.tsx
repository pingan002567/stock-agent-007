import { useState } from "react";
import { toolLabel, type StreamMessage, type StreamToolCall } from "@/hooks/useCopilotChat";
import { CopilotFinalMeta, SkillTraceChain } from "@/components/features/CopilotFinalMeta";

interface Props {
  streamMessage: StreamMessage;
  /** 提供时流式工具卡可点击（聊天中心主区 → 右栏详情联动） */
  onToolClick?: (tool: StreamToolCall) => void;
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

export function CopilotStreamingMessage({ streamMessage, onToolClick }: Props) {
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const hasContent = streamMessage.answerText.length > 0 || streamMessage.phase === "final" || streamMessage.phase === "error";
  const phaseLabel = PHASE_LABELS[streamMessage.phase] || "推理中";
  const phaseColor = PHASE_COLORS[streamMessage.phase] || "var(--blue)";
  const fullReasoning = streamMessage.reasoningLog.join("\n\n");
  const canExpandReasoning = fullReasoning.length > 300;

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
            animation: streamMessage.phase !== "final" && streamMessage.phase !== "error" ? "pulse 1s infinite" : "none"
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
      {streamMessage.reasoningText && (
        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8, fontStyle: "italic" }}>
          {reasoningOpen ? (
            <div style={{ whiteSpace: "pre-wrap" }}>{fullReasoning}</div>
          ) : (
            (fullReasoning || streamMessage.reasoningText).slice(-300)
          )}
          {canExpandReasoning && (
            <button className="final-meta-toggle" style={{ display: "block", marginTop: 4 }} onClick={() => setReasoningOpen((v) => !v)}>
              {reasoningOpen ? "▼ 收起完整思维链" : `▶ 展开完整思维链（${streamMessage.reasoningLog.length} 段）`}
            </button>
          )}
        </div>
      )}
      {streamMessage.tools.map((tool) => (
        <div
          key={tool.callId}
          className={`tool-card${onToolClick ? " clickable" : ""}`}
          style={{ marginBottom: 4 }}
          onClick={onToolClick ? () => onToolClick(tool) : undefined}
          title={onToolClick ? "查看完整结果" : undefined}
        >
          <div className="tool-card-header">
            <span className={`tool-dot ${tool.status === "done" ? "ok" : tool.status === "failed" ? "fail" : "busy"}`} />
            <span className="tool-name">{toolLabel(tool.name)}</span>
            <span className={`tool-status-text ${tool.status === "done" ? "success" : tool.status === "failed" ? "failed" : "running"}`}>
              {tool.status === "done" ? "✓ 完成" : tool.status === "failed" ? "⚠ 失败" : "⏳ 进行中"}
            </span>
          </div>
        </div>
      ))}
      {streamMessage.clarificationText && (
        <div className="clarification-card">
          <div className="clarification-title">AI 需要你的补充信息</div>
          <div style={{ whiteSpace: "pre-wrap" }}>{streamMessage.clarificationText}</div>
          <div className="clarification-hint">直接在下方输入框回答即可继续</div>
        </div>
      )}
      {streamMessage.answerText && (
        <div className={streamMessage.phase === "final" ? "" : "cursor-blink"}>
          {streamMessage.answerText}
        </div>
      )}
      {streamMessage.phase === "final" && streamMessage.finalPayload && (
        <CopilotFinalMeta payload={streamMessage.finalPayload} />
      )}
      {streamMessage.errorText && (
        <div style={{ color: "var(--red)" }}>⚠️ {streamMessage.errorText}</div>
      )}
      <div className="msg-time">now</div>
    </div>
  );
}
