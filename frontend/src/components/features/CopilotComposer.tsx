import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import {
  deleteSessionUpload,
  listSessionUploads,
  uploadSessionFiles,
  type UploadedFileInfo,
} from "@/api/copilot";
import type { HealthCheck } from "@/api/client";
import { ComposerStack } from "@/components/features/ComposerStack";
import { SessionModelPicker } from "@/components/features/SessionModelPicker";
import { useAppState } from "@/hooks/useAppState";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import { useToast } from "@/hooks/useToast";
import { adoptNewSessionDraft, composerDraftKey } from "@/lib/composerDraft";
import {
  CHAT_COMPOSER_HEIGHT_VAR,
  STUCK_IDLE_MS,
  streamProgressKey,
  toolStatusesKey,
  workingDockCopy,
} from "@/lib/chatShell";
import {
  UPLOADS_UNSUPPORTED_COPY,
  isImageUploadFilename,
  modelSupportsVision,
} from "@/lib/sessionUploads";
import { isMobileLayout } from "@/lib/connection";

function useOnline(): boolean {
  const [online, setOnline] = useState(
    () => (typeof navigator === "undefined" ? true : navigator.onLine),
  );
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

/** 中栏底部 Composer（Cursor 式浮动输入卡）+ 叠层 dock。 */
export function CopilotComposer() {
  const {
    currentSession,
    sending,
    streamMessage,
    streamLiveness,
    handleSend: sendMessage,
    handleStop,
    refreshRunStatus,
    ensureSession,
    sessionModelRef,
    modelOptions,
    setSessionModel,
    composerPrefill,
    clearComposerPrefill,
  } = useCopilotChat();
  const { appDataCache, globalLoading, lastRefreshTime } = useAppState();
  const { showToast } = useToast();
  const online = useOnline();

  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [uploading, setUploading] = useState(false);
  const [sessionFiles, setSessionFiles] = useState<UploadedFileInfo[]>([]);
  const [uploadsSupported, setUploadsSupported] = useState(true);
  const [dragOver, setDragOver] = useState(false);
  const [stuck, setStuck] = useState(false);
  const [contentIdle, setContentIdle] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stackRef = useRef<HTMLDivElement>(null);
  const dragCountRef = useRef(0);
  const progressKeyRef = useRef("");
  const progressAtRef = useRef(0);
  const contentAtRef = useRef(0);

  const runtimeStub = useMemo(() => {
    void globalLoading;
    void lastRefreshTime;
    const health = appDataCache.current.health as HealthCheck | undefined;
    return health?.agent_runtime?.active_client === "stub";
  }, [appDataCache, globalLoading, lastRefreshTime]);

  const canUpload = uploadsSupported && !runtimeStub;
  const visionOk = modelSupportsVision(sessionModelRef);

  const draftKey = composerDraftKey(currentSession?.session_id);
  const input = drafts[draftKey] ?? "";
  const setInput = (value: string) => {
    setDrafts((prev) => (prev[draftKey] === value ? prev : { ...prev, [draftKey]: value }));
  };

  const sessionIdRef = useRef<string | null>(currentSession?.session_id ?? null);
  const promoteDraftRef = useRef(false);

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
      if (prev) setSessionFiles([]);
      return;
    }
    if (prev && prev !== sid) setSessionFiles([]);
    if (prev == null && promoteDraftRef.current) {
      setDrafts((prevDrafts) => adoptNewSessionDraft(prevDrafts, sid));
    }
    promoteDraftRef.current = false;
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

  useEffect(() => {
    autoResize();
  }, [draftKey, input, autoResize]);

  useEffect(() => {
    if (!composerPrefill) return;
    setDrafts((prev) => ({ ...prev, [draftKey]: composerPrefill }));
    clearComposerPrefill();
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      autoResize();
    });
  }, [composerPrefill, clearComposerPrefill, draftKey, autoResize]);

  // 测量整块 composer（含 dock）高度，写入 CSS 变量供消息列表留底
  useEffect(() => {
    const el = stackRef.current;
    if (!el) return;
    const publish = () => {
      const h = Math.ceil(el.getBoundingClientRect().height);
      document.documentElement.style.setProperty(CHAT_COMPOSER_HEIGHT_VAR, `${h}px`);
    };
    publish();
    const ro = new ResizeObserver(publish);
    ro.observe(el);
    return () => {
      ro.disconnect();
      document.documentElement.style.removeProperty(CHAT_COMPOSER_HEIGHT_VAR);
    };
  }, []);

  // 流式卡住检测：内容指纹或后端心跳任一推进都重置；仅真正静默才 stuck。
  // 内容指纹闲置但心跳仍在 → working（长工具），避免误报「卡住」。
  useEffect(() => {
    if (!sending || !streamMessage) {
      setStuck(false);
      setContentIdle(false);
      progressKeyRef.current = "";
      return;
    }
    const key = streamProgressKey({
      phase: streamMessage.phase,
      answerText: streamMessage.answerText,
      toolCount: streamMessage.tools.length + streamMessage.steps.length,
      toolStatuses: toolStatusesKey(streamMessage.tools),
      clarification: Boolean(streamMessage.clarificationRequest || streamMessage.clarificationText),
      errorText: streamMessage.errorText,
    });
    const now = Date.now();
    if (key !== progressKeyRef.current) {
      progressKeyRef.current = key;
      progressAtRef.current = now;
      contentAtRef.current = now;
      setStuck(false);
      setContentIdle(false);
    }
    if (streamLiveness?.lastAt && streamLiveness.lastAt > progressAtRef.current) {
      progressAtRef.current = streamLiveness.lastAt;
      setStuck(false);
    }
    const CONTENT_IDLE_MS = 12_000;
    const tick = window.setInterval(() => {
      const nowTick = Date.now();
      const lastLive = Math.max(progressAtRef.current, streamLiveness?.lastAt ?? 0);
      const contentStale = nowTick - contentAtRef.current >= CONTENT_IDLE_MS;
      setContentIdle(contentStale);
      if (nowTick - lastLive >= STUCK_IDLE_MS) setStuck(true);
      else setStuck(false);
    }, 2000);
    return () => clearInterval(tick);
  }, [sending, streamMessage, streamLiveness]);

  // 页签重新可见时用后端 status 对齐 dock（SSE 可能已断但 run 仍在）
  useEffect(() => {
    if (!sending) return;
    const onVis = () => {
      if (document.visibilityState === "visible") void refreshRunStatus();
    };
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("focus", onVis);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("focus", onVis);
    };
  }, [sending, refreshRunStatus]);

  const waitingClarify = Boolean(
    streamMessage?.clarificationRequest || streamMessage?.clarificationText,
  );
  const stopping = streamLiveness?.status === "cancelling";
  const liveWorking = Boolean(
    streamLiveness?.alive
    && (streamLiveness.phase === "tool" || contentIdle),
  );
  const showWorking = sending && !stuck && !waitingClarify && !stopping && liveWorking;

  const docks = useMemo(() => {
    const list: {
      kind: "clarify" | "offline" | "stuck" | "working";
      title: string;
      detail?: string;
      actionLabel?: string;
      onAction?: () => void;
    }[] = [];
    if (!online) {
      list.push({
        kind: "offline",
        title: "网络已断开",
        detail: "恢复后再发送；已发送的请求可能卡住。",
      });
    }
    if (stopping && sending) {
      list.push({
        kind: "working",
        title: "正在停止…",
        detail: "已通知服务端取消本轮。",
      });
    } else if (stuck && sending) {
      list.push({
        kind: "stuck",
        title: "响应似乎卡住了",
        detail: "可停止本轮后重试，或检查远端连接。",
        actionLabel: "停止",
        onAction: handleStop,
      });
    } else if (showWorking) {
      const copy = workingDockCopy(streamLiveness);
      list.push({
        kind: "working",
        title: copy.title,
        detail: copy.detail,
        actionLabel: "停止",
        onAction: handleStop,
      });
    }
    if (waitingClarify && !stuck) {
      list.push({
        kind: "clarify",
        title: "AI 在等你回复",
        detail: "点上方选项，或在下方直接输入。",
      });
    }
    return list;
  }, [online, stuck, sending, waitingClarify, handleStop, showWorking, stopping, streamLiveness]);

  const handleSend = () => {
    const text = input;
    if (!text.trim()) return;
    if (!online) {
      showToast("当前离线，请恢复网络后再发送", "error");
      return;
    }
    const pending = sessionFiles;
    setInput("");
    setSessionFiles([]);
    if (inputRef.current) inputRef.current.style.height = "auto";
    void sendMessage(text, undefined, pending);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "Enter" || e.shiftKey) return;
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
      if (!currentSession?.session_id) promoteDraftRef.current = true;
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
    <div className="copilot-composer" ref={stackRef}>
      <ComposerStack docks={docks}>
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
            placeholder={
              waitingClarify
                ? "回答 AI 的问题…"
                : isMobileLayout()
                  ? "问 Stock Agent…"
                  : "输入追问，或描述你想做的事…"
            }
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
              <button className="composer-send" onClick={handleSend} disabled={!input.trim() || !online} title="发送 (Enter)" type="button">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <line x1="12" y1="19" x2="12" y2="5" />
                  <polyline points="5,12 12,5 19,12" />
                </svg>
              </button>
            )}
          </div>
        </div>
      </ComposerStack>
    </div>
  );
}
