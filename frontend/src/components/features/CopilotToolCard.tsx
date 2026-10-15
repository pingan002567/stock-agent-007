import { toolLabel } from "@/hooks/useCopilotChat";
import { summarizeToolResult } from "@/lib/toolResultSummary";

interface Props {
  name: string;
  done: boolean;
  failed?: boolean;
  onToggle: () => void;
  open: boolean;
  resultText?: string;
}

export function CopilotToolCard({ name, done, failed, onToggle, open, resultText }: Props) {
  const oneLiner = done && resultText ? summarizeToolResult(name, resultText) : null;
  return (
    <div className={`msg-tool tool-collapsible${open ? " open" : ""}`}>
      <div className="tool-summary" onClick={onToggle}>
        <span className="tool-arrow">▶</span>
        <span className={`tool-dot ${failed ? "fail" : done ? "ok" : "busy"}`} />
        <span className="tool-name">{toolLabel(name)}<span className="tool-eng"> ({name})</span></span>
        <span className="tool-meta">{failed ? "失败" : done ? "完成" : "调用中…"}</span>
      </div>
      {oneLiner && !open ? (
        <div className="tool-one-liner">→ {oneLiner}</div>
      ) : null}
      {open && done && resultText && (
        <div className="tool-result-detail">
          {oneLiner ? <div className="tool-one-liner in-detail">→ {oneLiner}</div> : null}
          <pre>{resultText.length > 300 ? resultText.slice(0, 300) + "…" : resultText}</pre>
        </div>
      )}
    </div>
  );
}
