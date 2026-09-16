import { useState } from "react";
import type { StreamStep, StreamToolCall } from "@/hooks/useCopilotChat";
import { ThoughtTimeline } from "@/components/features/ThoughtTimeline";
import type { ToolInfo } from "@/components/features/CopilotMessageItem";

type Props = {
  runId?: string | null;
  /** 空失败：无工具过程 */
  empty?: boolean;
  tools?: ToolInfo[];
  onRetry?: () => void;
  onToolClick?: (tool: ToolInfo) => void;
  retryDisabled?: boolean;
  /** 后面已有新对话时降噪 */
  stale?: boolean;
};

/** 失败轮次状态：挂在用户消息下，不渲染空 AI Copilot 头（对齐 DeerFlow）。 */
export function TurnFailureStatus({
  runId,
  empty = false,
  tools = [],
  onRetry,
  onToolClick,
  retryDisabled,
  stale = false,
}: Props) {
  const [open, setOpen] = useState(!stale && tools.length > 0 && tools.length <= 2);
  const hasProcess = tools.length > 0;
  const steps: StreamStep[] = tools.map((t) => ({
    kind: "tool" as const,
    id: t.id,
    tool: {
      callId: t.id,
      name: t.name,
      status: t.failed ? "failed" as const : t.done ? "done" as const : "running" as const,
      resultText: t.resultText,
      subagentType: t.subagentType,
      taskDescription: t.taskDescription,
      taskPrompt: t.taskPrompt,
    },
  }));
  const handleClick = onToolClick
    ? (t: StreamToolCall) => onToolClick({
        id: t.callId,
        name: t.name,
        done: t.status === "done",
        failed: t.status === "failed",
        resultText: t.resultText,
        subagentType: t.subagentType,
        taskDescription: t.taskDescription,
        taskPrompt: t.taskPrompt,
      })
    : undefined;

  return (
    <div
      className={`turn-failure${stale ? " stale" : ""}${empty ? " empty" : ""}`}
      data-run-id={runId || undefined}
    >
      <div className="turn-failure-bar">
        <span className="turn-failure-label">
          {empty
            ? "本轮未完成，未生成回答"
            : `本轮未完成${hasProcess ? ` · 已调用 ${tools.length} 个工具` : ""}`}
        </span>
        {hasProcess ? (
          <button
            type="button"
            className="turn-failure-toggle"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
          >
            {open ? "收起过程" : "查看过程"}
          </button>
        ) : null}
        {onRetry ? (
          <button
            type="button"
            className="turn-failure-retry"
            disabled={retryDisabled}
            onClick={onRetry}
          >
            重试
          </button>
        ) : stale ? (
          <span className="turn-failure-hint">已有后续对话</span>
        ) : null}
      </div>
      {hasProcess && open ? (
        <div className="turn-failure-process">
          <ThoughtTimeline steps={steps} active={false} onToolClick={handleClick} />
        </div>
      ) : null}
    </div>
  );
}
