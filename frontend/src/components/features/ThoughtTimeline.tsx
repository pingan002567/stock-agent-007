import { useState } from "react";
import { toolLabel, type StreamStep, type StreamToolCall } from "@/hooks/useCopilotChat";
import { toolParamSummary } from "@/components/features/taskToolMeta";
import { formatDuration } from "@/utils/format";
import { skillLabelOf } from "@/components/features/skillLabels";
import { ThinkingBlock } from "@/components/features/ThinkingBlock";
import { truncateText } from "@/components/features/taskToolMeta";
import { summarizeToolResult } from "@/lib/toolResultSummary";

/** 思维链时间线(借鉴 deer-flow ChainOfThought/SubtaskCard):
 * 推理与工具步按到达顺序交错,垂直连接线 + 图标;早期步骤折叠为
 * 「更早 N 步」,只展开最近几步;task 委派与其它工具同为紧凑单行。 */

const VISIBLE_TAIL = 4;

function ReasoningIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 3l1.9 5.7L19.6 10l-5.7 1.9L12 17.6l-1.9-5.7L4.4 10l5.7-1.9z"/>
    </svg>
  );
}

function ToolIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
    </svg>
  );
}

function SubagentIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="5" y="7" width="14" height="11" rx="2" />
      <path d="M12 3v4M8 12h.01M16 12h.01M9 16h6" />
    </svg>
  );
}

function taskEngLabel(tool: StreamToolCall): string {
  if (tool.subagentType) return tool.subagentType;
  if (tool.taskDescription) return truncateText(tool.taskDescription, 48);
  if (tool.taskPrompt) return truncateText(tool.taskPrompt, 48);
  return "task";
}

function toolResultLine(tool: StreamToolCall): string | null {
  if (tool.status !== "done" || !tool.resultText) return null;
  const summary = summarizeToolResult(tool.name, tool.resultText);
  if (summary) return summary;
  const raw = tool.resultText.replace(/\s+/g, " ").trim();
  // 结构化 payload 但取不到可读字段 → 不显示这一行：
  // 状态已由右侧 ✓/失败 表达，重复一遍「已完成」没有信息量，露原始 JSON 更糟
  if (!raw || raw.startsWith("{") || raw.startsWith("[")) return null;
  return truncateText(raw, 72);
}

function ToolStepRow({ tool, onClick }: { tool: StreamToolCall; onClick?: (t: StreamToolCall) => void }) {
  const running = tool.status === "running";
  const failed = tool.status === "failed";
  const resultLine = toolResultLine(tool);

  if (tool.name === "task") {
    const skillLabel = skillLabelOf(tool.subagentType) ?? toolLabel(tool.name);
    return (
      <div
        className={`tl-step subtask${running ? " running" : ""}`}
        onClick={onClick ? () => onClick(tool) : undefined}
        role={onClick ? "button" : undefined}
      >
        <span className="tl-step-icon subagent"><SubagentIcon /></span>
        <div className="tl-step-main">
          <div className="tl-step-row">
            <span className={`tl-step-label${running ? " shimmer" : ""}`}>{skillLabel}</span>
            {paramOf(tool) ? <span className="tl-step-param">{paramOf(tool)}</span> : null}
            <span className="tl-step-eng">{taskEngLabel(tool)}</span>
            <span className={`tl-step-state ${failed ? "bad" : running ? "busy" : "ok"}`}>
              {failed ? "失败" : running ? "…" : "✓"}
            </span>
          </div>
          {resultLine ? <div className="tl-step-result">→ {resultLine}</div> : null}
        </div>
      </div>
    );
  }

  return (
    <div className="tl-step" onClick={onClick ? () => onClick(tool) : undefined} role={onClick ? "button" : undefined}>
      <span className="tl-step-icon"><ToolIcon /></span>
      <div className="tl-step-main">
        <div className="tl-step-row">
          <span className={`tl-step-label${running ? " shimmer" : ""}`}>{toolLabel(tool.name)}</span>
          {paramOf(tool) ? <span className="tl-step-param">{paramOf(tool)}</span> : null}
          <span className="tl-step-eng">{tool.name}</span>
          <span className={`tl-step-state ${failed ? "bad" : running ? "busy" : "ok"}`}>
            {failed ? "失败" : running ? "…" : "✓"}
          </span>
        </div>
        {resultLine ? <div className="tl-step-result">→ {resultLine}</div> : null}
      </div>
    </div>
  );
}

/** 步骤行的"对象"：个股代码 / 搜索关键词等，取不到就不显示 */
function paramOf(tool: StreamToolCall): string {
  return toolParamSummary(tool.args);
}

export function ThoughtTimeline({ steps, active, onToolClick, expandAll = false, durationMs }: {
  steps: StreamStep[];
  /** 流式进行中(尾步高亮/shimmer) */
  active: boolean;
  onToolClick?: (t: StreamToolCall) => void;
  /** 轨迹视图用：默认展开全部步骤，不做「更早 N 步」折叠 */
  expandAll?: boolean;
  /** 本轮用时：显示在折叠按钮旁（16 步 · 1 分 12 秒） */
  durationMs?: number;
}) {
  const [showAll, setShowAll] = useState(expandAll);
  if (steps.length === 0) return null;
  const hiddenCount = expandAll || showAll ? 0 : Math.max(0, steps.length - VISIBLE_TAIL);
  const visible = steps.slice(hiddenCount);

  return (
    <div className="thought-timeline">
      {hiddenCount > 0 && (
        <button type="button" className="tl-collapse" onClick={() => setShowAll(true)}>
          展开更早 {hiddenCount} 步
          <span className="tl-collapse-meta">
            共 {steps.length} 步{(durationMs ?? 0) > 0 ? ` · ${formatDuration(durationMs ?? 0)}` : ""}
          </span>
        </button>
      )}
      {!expandAll && showAll && steps.length > VISIBLE_TAIL && (
        <button type="button" className="tl-collapse" onClick={() => setShowAll(false)}>
          收起早期步骤
        </button>
      )}
      <div className="tl-steps">
        {visible.map((step, i) => {
          const isLast = i === visible.length - 1;
          if (step.kind === "reasoning") {
            return (
              <div key={step.id} className="tl-step reasoning">
                <span className="tl-step-icon reasoning"><ReasoningIcon /></span>
                <div className="tl-step-main">
                  <ThinkingBlock
                    content={step.text}
                    streaming={active && isLast}
                  />
                </div>
              </div>
            );
          }
          return <ToolStepRow key={step.id} tool={step.tool} onClick={onToolClick} />;
        })}
      </div>
    </div>
  );
}
