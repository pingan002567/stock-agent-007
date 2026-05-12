import { toolLabel } from "@/hooks/useCopilotChat";

interface Props {
  name: string;
  done: boolean;
  failed?: boolean;
  onToggle: () => void;
  open: boolean;
  resultText?: string;
}

export function CopilotToolCard({ name, done, failed, onToggle, open, resultText }: Props) {
  return (
    <div className={`msg-tool tool-collapsible${open ? " open" : ""}`}>
      <div className="tool-summary" onClick={onToggle}>
        <span className="tool-arrow">▶</span>
        <span className={`tool-dot ${failed ? "fail" : done ? "ok" : "busy"}`} />
        <span className="tool-name">{toolLabel(name)}<span className="tool-eng"> ({name})</span></span>
        <span className="tool-meta">{failed ? "失败" : done ? "完成" : "调用中…"}</span>
      </div>
      {open && done && resultText && (
        <div className="tool-result-detail">
          <pre>{resultText.length > 300 ? resultText.slice(0, 300) + "…" : resultText}</pre>
        </div>
      )}
    </div>
  );
}
