import type { StreamToolCall } from "@/hooks/useCopilotChat";
import { skillLabelOf } from "@/components/features/skillLabels";
import { truncateText } from "@/components/features/taskToolMeta";

function SubagentIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="5" y="7" width="14" height="11" rx="2" />
      <path d="M12 3v4M8 12h.01M16 12h.01M9 16h6" />
    </svg>
  );
}

function resultPreview(text: string | undefined): string | undefined {
  if (!text) return undefined;
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  try {
    const parsed = JSON.parse(trimmed) as Record<string, unknown>;
    const direct = parsed.text ?? parsed.output ?? parsed.result ?? parsed.conclusion;
    if (typeof direct === "string" && direct.trim()) {
      return truncateText(direct, 140);
    }
    if (typeof parsed.summary === "string") return truncateText(parsed.summary, 140);
  } catch { /* plain text */ }
  return truncateText(trimmed, 140);
}

/** 委派子代理任务卡：技能名 + 任务说明 + 状态 + 结果预览 */
export function SubagentTaskCard({
  tool,
  onClick,
}: {
  tool: StreamToolCall;
  onClick?: (t: StreamToolCall) => void;
}) {
  const running = tool.status === "running";
  const failed = tool.status === "failed";
  const done = tool.status === "done";
  const skillLabel = skillLabelOf(tool.subagentType) ?? tool.subagentType ?? "未指定子代理";
  const taskLine = tool.taskDescription
    || (tool.taskPrompt ? truncateText(tool.taskPrompt, 96) : undefined)
    || "主代理正在分配具体任务…";
  const promptExtra = tool.taskDescription && tool.taskPrompt && tool.taskPrompt !== tool.taskDescription
    ? truncateText(tool.taskPrompt, 160)
    : undefined;
  const preview = done ? resultPreview(tool.resultText) : undefined;

  return (
    <div
      className={`subagent-card${running ? " running" : ""}${failed ? " failed" : ""}${done ? " done" : ""}`}
      onClick={onClick ? () => onClick(tool) : undefined}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter") onClick(tool); } : undefined}
    >
      <div className="subagent-card-head">
        <span className="subagent-card-icon" aria-hidden><SubagentIcon /></span>
        <div className="subagent-card-titles">
          <div className="subagent-card-name">{skillLabel}</div>
          {tool.subagentType && skillLabelOf(tool.subagentType) && (
            <div className="subagent-card-slug">{tool.subagentType}</div>
          )}
        </div>
        <span className={`subagent-card-status ${failed ? "bad" : running ? "busy" : "ok"}`}>
          {failed ? "失败" : running ? "执行中" : "已完成"}
        </span>
      </div>
      <div className={`subagent-card-task${running ? " shimmer" : ""}`}>{taskLine}</div>
      {promptExtra && <div className="subagent-card-prompt">{promptExtra}</div>}
      {preview && (
        <div className="subagent-card-result">
          <span className="subagent-card-result-label">返回</span>
          {preview}
        </div>
      )}
      {onClick && (
        <div className="subagent-card-foot">
          <span className="subagent-card-link">在右侧查看完整结果</span>
        </div>
      )}
    </div>
  );
}
