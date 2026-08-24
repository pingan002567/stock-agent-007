import { useCallback, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { uploadSessionFiles, type UploadedFileInfo } from "@/api/copilot";
import { useAppState } from "@/hooks/useAppState";
import { useCopilotChat } from "@/hooks/useCopilotChat";

/** 中栏底部 Composer（Cursor 式浮动输入卡）。 */
export function CopilotComposer() {
  const { appDataCache, globalLoading } = useAppState();
  const modelName = useMemo(() => {
    void globalLoading;
    return (appDataCache.current.settings as { agent_runtime?: { model_name?: string } } | undefined)
      ?.agent_runtime?.model_name || "AI 模型";
  }, [appDataCache, globalLoading]);

  const {
    currentSession,
    sending,
    handleSend: sendMessage,
    handleStop,
    ensureSession,
  } = useCopilotChat();

  const [input, setInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [sessionFiles, setSessionFiles] = useState<UploadedFileInfo[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const autoResize = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  const handleSend = () => {
    const text = input;
    if (!text.trim()) return;
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    setSessionFiles([]);
    sendMessage(text);
  };

  const [chipSessionId, setChipSessionId] = useState<string | null>(currentSession?.session_id ?? null);
  if ((currentSession?.session_id ?? null) !== chipSessionId) {
    setChipSessionId(currentSession?.session_id ?? null);
    setSessionFiles([]);
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleUpload = async (picked: FileList | null) => {
    if (!picked || picked.length === 0) return;
    const files = Array.from(picked);
    if (fileInputRef.current) fileInputRef.current.value = "";
    setUploading(true);
    try {
      const sid = await ensureSession();
      const result = await uploadSessionFiles(sid, files);
      setSessionFiles((prev) => [...prev, ...(result.files || [])]);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="copilot-composer">
      <div className="composer-card">
        {(sessionFiles.length > 0 || uploading) && (
          <div className="upload-chips">
            {sessionFiles.map((f, i) => (
              <span key={`${f.filename}-${i}`} className="upload-chip" title={f.markdown_file ? `已转 Markdown：${f.markdown_file}` : f.filename}>
                {f.filename}
                {f.markdown_file && <span className="upload-chip-ok">✓</span>}
              </span>
            ))}
            {uploading && <span className="upload-chip">上传中…</span>}
          </div>
        )}
        <textarea
          ref={inputRef}
          placeholder="输入追问，或描述你想做的事…"
          value={input}
          onChange={(e) => { setInput(e.target.value); autoResize(); }}
          onKeyDown={handleKeyDown}
          rows={1}
        />
        <div className="composer-bar">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            style={{ display: "none" }}
            onChange={(e) => void handleUpload(e.target.files)}
          />
          <button
            className="composer-add-btn"
            title="添加附件（PDF/Word/Excel/图片等，会话内可读）"
            disabled={uploading || sending}
            onClick={() => fileInputRef.current?.click()}
            type="button"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
          <span className="model-pill" title="当前模型（系统设置 → AI 模型）">{modelName}</span>
          <span className="composer-bar-spacer" />
          {sending ? (
            <button className="composer-send stop" onClick={handleStop} title="停止" type="button">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
            </button>
          ) : (
            <button className="composer-send" onClick={handleSend} disabled={!input.trim()} title="发送 (Enter)" type="button">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5,12 12,5 19,12" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
