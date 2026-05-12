import { useState } from "react";
import { parseCopilotEvent } from "@/api/copilot";
import type { CopilotMessage } from "@/api/client";
import { MarkdownRenderer } from "@/components/features/MarkdownRenderer";
import { toolLabel } from "@/hooks/useCopilotChat";

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

interface ToolInfo {
  name: string;
  done: boolean;
  failed?: boolean;
  id: string;
  resultText?: string;
}

interface Props {
  msg: CopilotMessage;
  tools?: ToolInfo[];
}

export function CopilotMessageItem({ msg, tools }: Props) {
  const ev = parseCopilotEvent(msg as unknown as Record<string, unknown>);
  const isUser = msg.role === "user";
  const isFinal = msg.kind === "final_answer";
  const isErrorEvent = ev.type === "error";
  const [openTools, setOpenTools] = useState(false);
  const hasTools = tools && tools.length > 0;

  let body: React.ReactNode;
  let cls = "msg";

  if (isUser) {
    cls += " user";
    body = <MarkdownRenderer text={msg.text || ""} />;
  } else if (isFinal) {
    cls += " ai";
    const evPayload = ev.payload as Record<string, unknown>;
    const raw = (evPayload.conclusion as string) || msg.text || "";
    const doneCount = tools?.filter(t => t.done).length || 0;
    const failCount = tools?.filter(t => t.failed).length || 0;
    body = (
      <>
        {hasTools && (
          <div className="tool-list-wrap">
            <button className="tool-list-toggle" onClick={() => setOpenTools((v) => !v)}>
              <span className="tool-list-arrow">{openTools ? "▼" : "▶"}</span>
              <span className="tool-list-summary">
                调用了 {tools!.length} 个工具
                {doneCount > 0 && <span className="tool-count-ok"> · {doneCount} 完成</span>}
                {failCount > 0 && <span className="tool-count-fail"> · {failCount} 失败</span>}
              </span>
            </button>
            {openTools && (
              <div className="tool-list-body">
                {tools!.map((t) => (
                  <div key={t.id} className="tool-card">
                    <div className="tool-card-header">
                      <span className={`tool-dot ${t.failed ? "fail" : t.done ? "ok" : "busy"}`} />
                      <span className="tool-name">{toolLabel(t.name)}</span>
                      <span className={`tool-status-text ${t.failed ? "failed" : t.done ? "success" : "running"}`}>
                        {t.failed ? "⚠ 失败" : t.done ? "✓ 完成" : "⏳ 进行中"}
                      </span>
                    </div>
                    {t.resultText && (
                      <div className="tool-card-body">
                        {t.resultText.length > 200 ? t.resultText.slice(0, 200) + "…" : t.resultText}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <MarkdownRenderer text={stripToolCallTags(raw)} />
      </>
    );
  } else if (isErrorEvent) {
    cls += " error";
    const evPayload = ev.payload as Record<string, unknown>;
    const doneCount = tools?.filter(t => t.done).length || 0;
    const failCount = tools?.filter(t => t.failed).length || 0;
    body = (
      <>
        {hasTools && (
          <div className="tool-list-wrap">
            <button className="tool-list-toggle" onClick={() => setOpenTools((v) => !v)}>
              <span className="tool-list-arrow">{openTools ? "▼" : "▶"}</span>
              <span className="tool-list-summary">
                调用了 {tools!.length} 个工具
                {doneCount > 0 && <span className="tool-count-ok"> · {doneCount} 完成</span>}
                {failCount > 0 && <span className="tool-count-fail"> · {failCount} 失败</span>}
              </span>
            </button>
            {openTools && (
              <div className="tool-list-body">
                {tools!.map((t) => (
                  <div key={t.id} className="tool-card">
                    <div className="tool-card-header">
                      <span className={`tool-dot ${t.failed ? "fail" : t.done ? "ok" : "busy"}`} />
                      <span className="tool-name">{toolLabel(t.name)}</span>
                      <span className={`tool-status-text ${t.failed ? "failed" : t.done ? "success" : "running"}`}>
                        {t.failed ? "⚠ 失败" : t.done ? "✓ 完成" : "⏳ 进行中"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <>⚠️ {(evPayload.error as string) || msg.text || "error"}</>
      </>
    );
  } else if (ev.type === "partial_answer") {
    cls += " ai";
    body = <MarkdownRenderer text={msg.text || ""} />;
  } else {
    return null;
  }

  const time = (msg.created_at || "").slice(11, 19) || "";

  return (
    <div className={cls}>
      {!isUser && (
        <div className="msg-label">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z" fill="currentColor"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
          AI Copilot
        </div>
      )}
      {body}
      <div className="msg-time">{time}</div>
    </div>
  );
}
