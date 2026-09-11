import { Suspense, lazy, useEffect } from "react";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

const Settings = lazy(() => import("@/pages/Settings"));

/** 系统设置：TeamClaw 式居中悬浮模态（遮罩+大窗），不占右栏功能坞。
 * Esc / 点遮罩 / 关闭按钮均可退出；内容懒加载复用现有 Settings 页。 */
export function SettingsModal({
  open,
  onClose,
  initialTab,
}: {
  open: boolean;
  onClose: () => void;
  initialTab?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="settings-modal" role="dialog" aria-modal="true">
        <div className="settings-modal-head">
          <span className="settings-modal-title">系统设置</span>
          <button className="func-close" onClick={onClose} title="关闭 (Esc)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
        <div className="settings-modal-body">
          <ErrorBoundary>
            <Suspense fallback={<div className="page-loading">加载中…</div>}>
              <Settings initialTab={initialTab} />
            </Suspense>
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
}
