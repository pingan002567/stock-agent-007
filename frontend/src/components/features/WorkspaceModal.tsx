import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/api/client";

interface WorkspaceInfo {
  name: string;
  data_dir: string;
  switchable: boolean;
  recents: { dir: string; name: string; last_used?: string }[];
}

declare global {
  interface Window {
    __TAURI__?: { dialog?: { open?: (opts: Record<string, unknown>) => Promise<string | null> } };
  }
}

/** 工作区切换器（vault 式,方案 A）：当前档案 + 最近列表 + 选择新目录。
 * 切换 = 后端分离子进程重装 launchd 服务指向新目录,本端轮询健康后整页重载。 */
export function WorkspaceModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [info, setInfo] = useState<WorkspaceInfo | null>(null);
  const [error, setError] = useState("");
  const [switching, setSwitching] = useState(false);
  const [manualDir, setManualDir] = useState("");

  useEffect(() => {
    if (!open) return;
    apiGet<WorkspaceInfo>("/api/workspace")
      .then((w) => { setInfo(w); setError(""); })
      .catch((e) => setError(String(e)));
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !switching) onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose, switching]);

  const doSwitch = useCallback(async (dir: string) => {
    setError("");
    setSwitching(true);
    try {
      const r = await apiPost<{ ok: boolean; switching: boolean; detail?: string }>(
        "/api/workspace/switch", { data_dir: dir });
      if (!r.switching) { setSwitching(false); onClose(); return; }
      // 服务正在 bootout→bootstrap,轮询健康后整页重载进入新档案
      const deadline = Date.now() + 40000;
      await new Promise((r) => setTimeout(r, 1500));
      while (Date.now() < deadline) {
        try {
          const res = await fetch("/api/health", { cache: "no-store" });
          if (res.ok) { window.location.reload(); return; }
        } catch { /* 服务重启中 */ }
        await new Promise((r) => setTimeout(r, 600));
      }
      setError("切换超时:服务未在 40 秒内恢复,请查看日志");
      setSwitching(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSwitching(false);
    }
  }, [onClose]);

  const browse = useCallback(async () => {
    const dialogOpen = window.__TAURI__?.dialog?.open;
    if (!dialogOpen) return;
    try {
      const picked = await dialogOpen({ directory: true, title: "选择工作目录" });
      if (picked) void doSwitch(picked);
    } catch (e) { setError(String(e)); }
  }, [doSwitch]);

  if (!open) return null;
  const hasNativePicker = !!window.__TAURI__?.dialog?.open;

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !switching) onClose(); }}>
      <div className="ws-modal" role="dialog" aria-modal="true">
        {switching ? (
          <div className="ws-switching">
            <div className="spinner-ring" />
            <div>正在切换工作区…</div>
            <div className="ws-hint">后台服务重启中,完成后自动进入</div>
          </div>
        ) : (
          <>
            <div className="settings-modal-head" style={{ background: "transparent", borderBottom: "1px solid var(--line-soft)" }}>
              <span className="settings-modal-title">工作区</span>
              <button className="func-close" onClick={onClose} title="关闭 (Esc)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
              </button>
            </div>
            <div className="ws-body">
              <div className="ws-current">
                <div className="ws-row-name">
                  {info?.name ?? "…"}
                  <span className="ws-badge">当前</span>
                </div>
                <div className="ws-row-dir">{info?.data_dir ?? ""}</div>
              </div>

              {info && !info.switchable && (
                <div className="ws-hint" style={{ marginBottom: 10 }}>
                  当前为开发模式（无 launchd 服务）,切换请使用
                  <code> service_cli install --data-dir</code>
                </div>
              )}

              {info?.recents && info.recents.length > 0 && (
                <>
                  <div className="ws-group">最近</div>
                  {info.recents.map((w) => (
                    <button key={w.dir} className="ws-item" disabled={!info.switchable}
                      onClick={() => void doSwitch(w.dir)}>
                      <span className="ws-item-name">{w.name}</span>
                      <span className="ws-item-dir">{w.dir}</span>
                    </button>
                  ))}
                </>
              )}

              <div className="ws-group">切换到其他目录</div>
              {hasNativePicker ? (
                <button className="ws-item" disabled={!info?.switchable} onClick={() => void browse()}>
                  <span className="ws-item-name">浏览选择目录…</span>
                  <span className="ws-item-dir">新目录会初始化为空档案;含既有档案的目录直接接管</span>
                </button>
              ) : (
                <div className="ws-manual">
                  <input
                    placeholder="/path/to/workspace"
                    value={manualDir}
                    onChange={(e) => setManualDir(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && manualDir.trim()) void doSwitch(manualDir.trim()); }}
                  />
                  <button disabled={!info?.switchable || !manualDir.trim()} onClick={() => void doSwitch(manualDir.trim())}>切换</button>
                </div>
              )}
              {error && <div className="ws-error">{error}</div>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
