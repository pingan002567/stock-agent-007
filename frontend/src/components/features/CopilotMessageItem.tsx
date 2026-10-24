import { parseCopilotEvent } from "@/api/copilot";
import type { CopilotMessage } from "@/api/client";
import { MarkdownRenderer } from "@/components/features/MarkdownRenderer";
import { formatLocalTime } from "@/utils/format";
import { CopilotFinalMeta } from "@/components/features/CopilotFinalMeta";
import { ThoughtTimeline } from "@/components/features/ThoughtTimeline";
import { isCommandTool } from "@/hooks/useCopilotChat";
import type { StreamStep, StreamToolCall } from "@/hooks/useCopilotChat";
import { attachmentsFromMessagePayload } from "@/lib/sessionUploads";
import { HumanInputCard } from "@/components/features/HumanInputCard";
import {
  parseHumanInputRequest,
  type HumanInputResponse,
} from "@/lib/humanInput";

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
  taskDescription?: string;
  taskPrompt?: string;
  args?: Record<string, unknown>;
}

interface Props {
  msg: CopilotMessage;
  tools?: ToolInfo[];
  /** 提供时工具卡可点击（聊天中心主区 → 右栏详情联动） */
  onToolClick?: (tool: ToolInfo) => void;
  /** 历史澄清卡的已答态（来自后续用户消息的 human_input_response） */
  clarifiedResponse?: HumanInputResponse | null;
  /** 未答澄清卡可交互（点选项 / 卡内提交） */
  onClarifySubmit?: (response: HumanInputResponse, displayText: string) => void;
  clarifyPending?: boolean;
  /** 本轮第一条用户消息的时间：用来算「用时」 */
  runStartedAt?: string;
}

/** final / error 两个分支共用的「调用了 N 个工具」折叠区 */
export function CopilotMessageItem({
  msg,
  tools,
  onToolClick,
  clarifiedResponse,
  onClarifySubmit,
  clarifyPending,
  runStartedAt,
}: Props) {
  const ev = parseCopilotEvent(msg as unknown as Record<string, unknown>);
  const isUser = msg.role === "user";
  const isFinal = msg.kind === "final_answer";
  const isErrorEvent = ev.type === "error";
  const isClarification = msg.kind === "clarification" || ev.type === "clarification";
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
      taskDescription: t.taskDescription, taskPrompt: t.taskPrompt, args: t.args,
      // 历史消息没存 kind：按工具名重新判定，bash 才能渲染成终端块
      kind: isCommandTool(t.name) ? "command" : "tool",
    },
  }));
  const handleTimelineClick = onToolClick
    ? (t: StreamToolCall) => onToolClick({
        id: t.callId, name: t.name, done: t.status === "done",
        failed: t.status === "failed", resultText: t.resultText, subagentType: t.subagentType,
        taskDescription: t.taskDescription, taskPrompt: t.taskPrompt, args: t.args,
      })
    : undefined;

/** 定时任务等系统触发的轮次：用户消息正文其实是整段研究员提示词。
 *  直接铺在气泡里既长又全是内部指令，所以拆成「来源标签 + 用户任务 + 折叠详情」。 */
function splitScheduledPrompt(text: string): { tag: string; task: string; rest: string } | null {
  const m = text.match(/^\[([^\]]{1,40})\]\s*/);
  if (!m) return null;
  const rest = text.slice(m[0].length).trim();
  const idx = rest.search(/用户任务[:：]/);
  return { tag: m[1], task: idx >= 0 ? rest.slice(idx).replace(/^用户任务[:：]\s*/, "").trim() : "", rest };
}

  /** 消息本地时间（用户气泡与 AI 完成时间都用它） */
  const time = formatLocalTime(msg.created_at);

  /** 本轮用时：final 消息时间 - 该轮第一条用户消息时间 */
  const durationMs =
    isFinal && runStartedAt
      ? new Date(msg.created_at).getTime() - new Date(runStartedAt).getTime()
      : undefined;

  let body: React.ReactNode;
  let cls = "msg";

  if (isUser) {
    cls += " user";
    const attachments = attachmentsFromMessagePayload(msg.payload);
    const scheduled = splitScheduledPrompt(msg.text || "");
    body = scheduled ? (
      <>
        <div className="sched-chip" title={scheduled.tag}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
          </svg>
          {scheduled.tag}
        </div>
        {scheduled.task ? <MarkdownRenderer text={scheduled.task} /> : null}
        <details className="sched-detail">
          <summary>查看完整指令（{scheduled.rest.length} 字）</summary>
          <div className="sched-detail-body">{scheduled.rest}</div>
        </details>
      </>
    ) : (
      <>
        {attachments.length > 0 && (
          <div className="upload-chips msg-attachments">
            {attachments.map((f) => (
              <span
                key={f.filename}
                className="upload-chip"
                title={f.markdown_file ? `已转 Markdown：${f.markdown_file}` : f.filename}
              >
                <span className="upload-chip-name">{f.filename}</span>
                {f.markdown_file ? <span className="upload-chip-ok">✓</span> : null}
              </span>
            ))}
          </div>
        )}
        <MarkdownRenderer text={msg.text || ""} />
      </>
    );
  } else if (isClarification) {
    cls += " ai";
    const request = parseHumanInputRequest(msg.payload)
      ?? parseHumanInputRequest({ question: msg.text, call_id: (msg.payload as { call_id?: string })?.call_id });
    body = (
      <>
        {hasTools && <ThoughtTimeline steps={toolSteps} active={false} onToolClick={handleTimelineClick} durationMs={durationMs} />}
        {request ? (
          <HumanInputCard
            request={request}
            answeredResponse={clarifiedResponse ?? null}
            pending={clarifyPending}
            onSubmit={
              clarifiedResponse || !onClarifySubmit
                ? undefined
                : (response) => {
                    void onClarifySubmit(response, response.value);
                  }
            }
          />
        ) : (
          <div className="clarification-card">
            <div className="clarification-title">AI 需要你的补充信息</div>
            <div style={{ whiteSpace: "pre-wrap" }}>{msg.text}</div>
            <div className="clarification-hint">直接在下方输入框回答即可继续</div>
          </div>
        )}
      </>
    );
  } else if (isFinal) {
    cls += " ai";
    const evPayload = ev.payload as Record<string, unknown>;
    // 澄清轮次的 final 只作收口标记；正文已在 Human Input Card，这里不重复渲染。
    if (evPayload.clarification) {
      return null;
    }
    const raw = (evPayload.conclusion as string) || msg.text || "";
    body = (
      <>
        {hasTools && <ThoughtTimeline steps={toolSteps} active={false} onToolClick={handleTimelineClick} durationMs={durationMs} />}
        <MarkdownRenderer text={stripToolCallTags(raw)} />
        <CopilotFinalMeta payload={evPayload} durationMs={durationMs} completedAt={time} />
      </>
    );
  } else if (isErrorEvent) {
    cls += " error";
    const evPayload = ev.payload as Record<string, unknown>;
    body = (
      <>
        {hasTools && <ThoughtTimeline steps={toolSteps} active={false} onToolClick={handleTimelineClick} durationMs={durationMs} />}
        <>⚠️ {(evPayload.error as string) || msg.text || "error"}</>
      </>
    );
  } else if (ev.type === "partial_answer") {
    cls += " ai";
    body = <MarkdownRenderer text={msg.text || ""} />;
  } else {
    return null;
  }

  return (
    <div className={cls}>
      {/* 便签体头行：只放身份；完成时间移到气泡底部「用时」右侧 */}
      {!isUser && (
        <div className="msg-label">
          <span className="ai-disc">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
              <polyline points="4,17 10,11 13,14 20,6"/>
            </svg>
          </span>
          AI Copilot
        </div>
      )}
      {body}
      {isUser && <div className="msg-time">{time}</div>}
    </div>
  );
}
