import { parseCopilotEvent } from "@/api/copilot";
import type { CopilotMessage } from "@/api/client";
import { MarkdownRenderer } from "@/components/features/MarkdownRenderer";
import { formatLocalTime } from "@/utils/format";
import { CopilotFinalMeta } from "@/components/features/CopilotFinalMeta";
import { ThoughtTimeline } from "@/components/features/ThoughtTimeline";
import type { StreamStep, StreamToolCall } from "@/hooks/useCopilotChat";

/** 从 AI 回答文本中移除嵌入的 XML 式工具调用标签 */
function stripToolCallTags(text: string): string {
  let prev: string;
  let cleaned = text;
  do {
    prev = cleaned;
    cleaned = cleaned.replace(/<([a-z][a-z_0-9]+)>[\s\S]*?<\/\1>/g, "");
  } while (cleaned !== prev);
  cleaned = cleaned.replace(/<([a-z][a-z_0-9]+)\s*\/?>/g, "");
  return cleaned.trim();
}

export interface ToolInfo {
  name: string;
  done: boolean;
  failed?: boolean;
  id: string;
  resultText?: string;
  subagentType?: string;
}

interface Props {
  msg: CopilotMessage;
  tools?: ToolInfo[];
  /** 提供时工具卡可点击（聊天中心主区 → 右栏详情联动） */
  onToolClick?: (tool: ToolInfo) => void;
}

/** final / error 两个分支共用的「调用了 N 个工具」折叠区 */
export function CopilotMessageItem({ msg, tools, onToolClick }: Props) {
  const ev = parseCopilotEvent(msg as unknown as Record<string, unknown>);
  const isUser = msg.role === "user";
  const isFinal = msg.kind === "final_answer";
  const isErrorEvent = ev.type === "error";
  const hasTools = tools && tools.length > 0;
  // 持久化消息与流式共用思维链时间线形态(官方"过程即结果":收口不坍缩成计数条)。
  // 推理文本未落库,历史时间线只有工具步。
  const toolSteps: StreamStep[] = (tools ?? []).map((t) => ({
    kind: "tool" as const,
    id: t.id,
    tool: {
      callId: t.id, name: t.name,
      status: t.failed ? "failed" as const : t.done ? "done" as const : "running" as const,
      resultText: t.resultText, subagentType: t.subagentType,
    },
  }));
  const handleTimelineClick = onToolClick
    ? (t: StreamToolCall) => onToolClick({
        id: t.callId, name: t.name, done: t.status === "done",
        failed: t.status === "failed", resultText: t.resultText, subagentType: t.subagentType,
      })
    : undefined;

  let body: React.ReactNode;
  let cls = "msg";

  if (isUser) {
    cls += " user";
    body = <MarkdownRenderer text={msg.text || ""} />;
  } else if (isFinal) {
    cls += " ai";
    const evPayload = ev.payload as Record<string, unknown>;
    const raw = (evPayload.conclusion as string) || msg.text || "";
    body = (
      <>
        {hasTools && <ThoughtTimeline steps={toolSteps} active={false} onToolClick={handleTimelineClick} />}
        {Boolean(evPayload.clarification) && (
          <div className="clarification-hint" style={{ marginBottom: 4 }}>❓ AI 反问澄清 · 回复即可继续</div>
        )}
        <MarkdownRenderer text={stripToolCallTags(raw)} />
        <CopilotFinalMeta payload={evPayload} />
      </>
    );
  } else if (isErrorEvent) {
    cls += " error";
    const evPayload = ev.payload as Record<string, unknown>;
    body = (
      <>
        {hasTools && <ThoughtTimeline steps={toolSteps} active={false} onToolClick={handleTimelineClick} />}
        <>⚠️ {(evPayload.error as string) || msg.text || "error"}</>
      </>
    );
  } else if (ev.type === "partial_answer") {
    cls += " ai";
    body = <MarkdownRenderer text={msg.text || ""} />;
  } else {
    return null;
  }

  const time = formatLocalTime(msg.created_at);

  return (
    <div className={cls}>
      {/* 便签体头行：身份 + mono 时间（时间归入头行，正文下不再挂时间） */}
      {!isUser && (
        <div className="msg-label">
          <span className="ai-disc">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
              <polyline points="4,17 10,11 13,14 20,6"/>
            </svg>
          </span>
          AI Copilot
          <span className="msg-label-time">{time}</span>
        </div>
      )}
      {body}
      {isUser && <div className="msg-time">{time}</div>}
    </div>
  );
}
