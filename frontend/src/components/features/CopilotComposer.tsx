import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import {
  deleteSessionUpload,
  listSessionUploads,
  uploadSessionFiles,
  type UploadedFileInfo,
} from "@/api/copilot";
import type { HealthCheck } from "@/api/client";
import { SessionModelPicker } from "@/components/features/SessionModelPicker";
import { useAppState } from "@/hooks/useAppState";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import { useToast } from "@/hooks/useToast";
import {
  UPLOADS_UNSUPPORTED_COPY,
  isImageUploadFilename,
  modelSupportsVision,
} from "@/lib/sessionUploads";

/** 中栏底部 Composer（Cursor 式浮动输入卡）。 */
export function CopilotComposer() {
  const {
    currentSession,
    sending,
    handleSend: sendMessage,
    handleStop,
    ensureSession,
    sessionModelRef,
    modelOptions,
    setSessionModel,
  } = useCopilotChat();
  const { appDataCache, globalLoading, lastRefreshTime } = useAppState();
  const { showToast } = useToast();

  const [input, setInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [sessionFiles, setSessionFiles] = useState<UploadedFileInfo[]>([]);
  const [uploadsSupported, setUploadsSupported] = useState(true);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const dragCountRef = useRef(0);

  const runtimeStub = useMemo(() => {
    void globalLoading;
    void lastRefreshTime;
    const health = appDataCache.current.health as HealthCheck | undefined;
    return health?.agent_runtime?.active_client === "stub";
  }, [appDataCache, globalLoading, lastRefreshTime]);

  const canUpload = uploadsSupported && !runtimeStub;
  const visionOk = modelSupportsVision(sessionModelRef);

  const sessionIdRef = useRef<string | null>(currentSession?.session_id ?? null);

  const refreshUploads = useCallback(async (sessionId: string) => {
    const listed = await listSessionUploads(sessionId);
    setUploadsSupported(listed.supported);
    return listed;
  }, []);

  useEffect(() => {
    const sid = currentSession?.session_id ?? null;
    const prev = sessionIdRef.current;
    sessionIdRef.current = sid;
    if (!sid) {
      setUploadsSupported(!runtimeStub);
      // 离开已有会话（点「新对话」）才清未发送芯片；空态上传建会话时 prev=null，要保留。
      if (prev) setSessionFiles([]);
      return;
    }
    if (prev && prev !== sid) setSessionFiles([]);
    let cancelled = false;
    void listSessionUploads(sid).then((listed) => {
      if (cancelled) return;
      setUploadsSupported(listed.supported);
    }).catch((err) => {
      if (cancelled) return;
      showToast(err instanceof Error ? err.message : "读取附件失败", "error");
    });
    return () => { cancelled = true; };
  }, [currentSession?.session_id, runtimeStub, showToast]);

  const autoResize = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  const handleSend = () => {
    const text = input;
    if (!text.trim()) return;
    const pending = sessionFiles;
    setInput("");
    setSessionFiles([]);
    if (inputRef.current) inputRef.current.style.height = "auto";
    void sendMessage(text, undefined, pending);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "Enter" || e.shiftKey) return;
    // 输入法组字确认也会触发 Enter；组字中回车只上屏，不发送
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    handleSend();
  };

  const handleUploadFiles = async (picked: File[] | FileList | null) => {
    const files = picked ? Array.from(picked) : [];
    if (files.length === 0) return;
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (!canUpload) {
      showToast(UPLOADS_UNSUPPORTED_COPY, "info");
      return;
    }
    setUploading(true);
    try {
      const sid = await ensureSession();
      const uploaded = await uploadSessionFiles(sid, files);
      const listed = await refreshUploads(sid);
      const incoming = (uploaded.files || []).length
        ? uploaded.files
        : listed.files.filter((item) => files.some((file) => file.name === item.filename));
      setSessionFiles((prev) => {
        const seen = new Set(prev.map((item) => item.filename));
        return [...prev, ...incoming.filter((item) => !seen.has(item.filename))];
      });
    } catch (err) {
      showToast(err instanceof Error ? err.message : "上传失败", "error");
    } finally {
      setUploading(false);
    }
  };

  const handleRemove = async (filename: string) => {
    const sid = currentSession?.session_id;
    if (!sid) {
      setSessionFiles((prev) => prev.filter((item) => item.filename !== filename));
      return;
    }
    try {
      await deleteSessionUpload(sid, filename);
      setSessionFiles((prev) => prev.filter((item) => item.filename !== filename));
    } catch (err) {
      showToast(err instanceof Error ? err.message : "删除附件失败", "error");
    }
  };

  const openFilePicker = () => {
    if (!canUpload) {
      showToast(UPLOADS_UNSUPPORTED_COPY, "info");
      return;
    }
    fileInputRef.current?.click();
  };

  const onDragEnter = (e: DragEvent) => {
    e.preventDefault();
    dragCountRef.current += 1;
    setDragOver(true);
  };

  const onDragLeave = (e: DragEvent) => {
    e.preventDefault();
    dragCountRef.current -= 1;
    if (dragCountRef.current <= 0) {
      dragCountRef.current = 0;
      setDragOver(false);
    }
  };

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = canUpload ? "copy" : "none";
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    dragCountRef.current = 0;
    setDragOver(false);
    void handleUploadFiles(e.dataTransfer.files);
  };

  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData?.files ?? []);
    if (files.length === 0) return;
    e.preventDefault();
    void handleUploadFiles(files);
  };

  return (
    <div className="copilot-composer">
      <div
        className={`composer-card${dragOver ? " drag-over" : ""}`}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        onDragOver={onDragOver}
        onDrop={onDrop}
      >
        {(sessionFiles.length > 0 || uploading) && (
          <div className="upload-chips">
            {sessionFiles.map((f) => {
              const imageNoVision = isImageUploadFilename(f.filename) && !visionOk;
              return (
                <span
                  key={f.filename}
                  className="upload-chip"
                  title={
                    imageNoVision
                      ? "当前会话模型不能看图"
                      : f.markdown_file
                        ? `已转 Markdown：${f.markdown_file}`
                        : f.filename
                  }
                >
                  <span className="upload-chip-name">{f.filename}</span>
                  {f.markdown_file && <span className="upload-chip-ok">✓</span>}
                  {imageNoVision && <span className="upload-chip-warn">模型不能看图</span>}
                  <button
                    type="button"
                    className="upload-chip-del"
                    aria-label={`移除 ${f.filename}`}
                    onClick={() => void handleRemove(f.filename)}
                  >
                    ×
                  </button>
                </span>
              );
            })}
            {uploading && <span className="upload-chip">上传中…</span>}
          </div>
        )}
        <textarea
          ref={inputRef}
          placeholder="输入追问，或描述你想做的事…"
          value={input}
          onChange={(e) => { setInput(e.target.value); autoResize(); }}
          onKeyDown={handleKeyDown}
          onPaste={onPaste}
          rows={1}
        />
        <div className="composer-bar">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            style={{ display: "none" }}
            onChange={(e) => void handleUploadFiles(e.target.files)}
          />
          <button
            className="composer-add-btn"
            title={canUpload ? "添加附件（PDF/Word/Excel/图片等，会话内可读）" : UPLOADS_UNSUPPORTED_COPY}
            disabled={uploading || sending || !canUpload}
            onClick={openFilePicker}
            type="button"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
          <SessionModelPicker
            value={sessionModelRef}
            options={modelOptions}
            disabled={sending}
            onChange={setSessionModel}
          />
          <span className="composer-bar-spacer" />
          {sending ? (
            <button className="composer-send stop" onClick={handleStop} title="停止生成" type="button" aria-label="停止生成">
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
