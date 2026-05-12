import { toolLabel, type StreamMessage } from "@/hooks/useCopilotChat";

interface Props {
  streamMessage: StreamMessage;
}

const PHASE_LABELS: Record<string, string> = {
  error: "出错",
  final: "完成",
  answering: "正在分析",
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

export function CopilotStreamingMessage({ streamMessage }: Props) {
  const hasContent = streamMessage.answerText.length > 0 || streamMessage.phase === "final" || streamMessage.phase === "error";
  const phaseLabel = PHASE_LABELS[streamMessage.phase] || "推理中";
  const phaseColor = PHASE_COLORS[streamMessage.phase] || "var(--blue)";

  return (
    <div className={`msg ai${hasContent ? "" : " streaming"}`}>
      <div className="msg-label">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z" fill="currentColor"/>
          <circle cx="12" cy="12" r="3"/>
        </svg>
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
      {streamMessage.reasoningText && (
        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8, fontStyle: "italic" }}>
          {streamMessage.reasoningText.slice(-300)}
        </div>
      )}
      {streamMessage.tools.map((tool) => (
        <div key={tool.callId} className="tool-card" style={{ marginBottom: 4 }}>
          <div className="tool-card-header">
            <span className={`tool-dot ${tool.status === "done" ? "ok" : tool.status === "failed" ? "fail" : "busy"}`} />
            <span className="tool-name">{toolLabel(tool.name)}</span>
            <span className={`tool-status-text ${tool.status === "done" ? "success" : tool.status === "failed" ? "failed" : "running"}`}>
              {tool.status === "done" ? "✓ 完成" : tool.status === "failed" ? "⚠ 失败" : "⏳ 进行中"}
            </span>
          </div>
        </div>
      ))}
      {streamMessage.answerText && (
        <div className={streamMessage.phase === "final" ? "" : "cursor-blink"}>
          {streamMessage.answerText}
        </div>
      )}
      {streamMessage.errorText && (
        <div style={{ color: "var(--red)" }}>⚠️ {streamMessage.errorText}</div>
      )}
      <div className="msg-time">now</div>
    </div>
  );
}
