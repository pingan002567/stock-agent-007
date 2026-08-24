import { useCallback, useEffect, useState } from "react";
import { api, apiPost } from "@/api/client";

interface WorkspaceInfo {
  name: string;
  data_dir: string;
  port?: number | null;
  switchable: boolean;
  service_mode?: "launchd" | "dev";
  service_loaded?: boolean;
  configured_data_dir?: string | null;
  recents: { dir: string; name: string; last_used?: string }[];
}

declare global {
  interface Window {
    __TAURI__?: {
      dialog?: { open?: (opts: Record<string, unknown>) => Promise<string | null> };
      core?: { invoke?: (cmd: string, payload?: Record<string, unknown>) => Promise<unknown> };
    };
  }
}

function normalizeDir(dir: string): string {
  return dir.replace(/\/$/, "");
}

async function resolveTargetDir(dir: string): Promise<string> {
  try {
    const r = await apiPost<{ data_dir: string }>("/api/workspace/resolve", { data_dir: dir });
    return normalizeDir(r.data_dir);
  } catch {
    return normalizeDir(dir);
  }
}

async function readDoctorPort(fallback: number): Promise<number> {
  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) return fallback;
  try {
    const d = await invoke("service_cli", { args: ["doctor"] }) as { port?: number; ok?: boolean };
    if (d?.port) return d.port;
  } catch { /* ignore */ }
  return fallback;
}

/** 轮询直到新后端报告目标 data_dir（/api/workspace 与 /api/health 双通道） */
async function waitForWorkspaceSwitch(
  targetDir: string,
  preferredPort: number,
  deadlineMs = 60000,
): Promise<{ ok: boolean; port: number }> {
  const target = normalizeDir(targetDir);
  const deadline = Date.now() + deadlineMs;
  let port = preferredPort;
  await new Promise((r) => setTimeout(r, 1200));

  while (Date.now() < deadline) {
    port = await readDoctorPort(port);
    try {
      const [wsRes, healthRes] = await Promise.all([
        fetch(`http://127.0.0.1:${port}/api/workspace`, { cache: "no-store" }),
        fetch(`http://127.0.0.1:${port}/api/health`, { cache: "no-store" }),
      ]);
      if (wsRes.ok) {
        const w = await wsRes.json() as { data_dir?: string };
        if (normalizeDir(w.data_dir ?? "") === target) return { ok: true, port };
      }
      if (healthRes.ok) {
        const h = await healthRes.json() as { data_dir?: string };
        if (normalizeDir(h.data_dir ?? "") === target) return { ok: true, port };
      }
    } catch { /* 服务重启中 */ }
    await new Promise((r) => setTimeout(r, 700));
  }
  return { ok: false, port };
}

function notifyWorkspaceChanged() {
  window.dispatchEvent(new CustomEvent("workspace-changed"));
}

/** 工作区切换器：Tauri 走 service_cli install；浏览器走 /api/workspace/switch。 */
export function WorkspaceModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [info, setInfo] = useState<WorkspaceInfo | null>(null);
  const [error, setError] = useState("");
  const [switching, setSwitching] = useState(false);
  const [manualDir, setManualDir] = useState("");

  const hasTauri = !!window.__TAURI__?.core?.invoke;
  const canSwitch = hasTauri || !!info?.switchable;

  const refreshInfo = useCallback(async () => {
    const w = await api<WorkspaceInfo>("/api/workspace", { cache: "no-store" });
    setInfo(w);
    return w;
  }, []);

  useEffect(() => {
    if (!open) return;
    setInfo(null);
    refreshInfo()
      .then(() => setError(""))
      .catch((e) => setError(String(e)));
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !switching) onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose, switching, refreshInfo]);

  const finishSwitch = useCallback(async (port: number, dir: string) => {
    const target = await resolveTargetDir(dir);
    const result = await waitForWorkspaceSwitch(target, port);
    if (!result.ok) {
      setError(
        "切换超时：服务未在 60 秒内切换到目标目录。"
        + " 请查看 ~/Library/Application Support/StockAgent/logs/switch.log",
      );
      setSwitching(false);
      try {
        await refreshInfo();
      } catch { /* ignore */ }
      return;
    }
    try { localStorage.setItem("sa.lastGoodPort", String(result.port)); } catch { /* ignore */ }
    notifyWorkspaceChanged();
    const invoke = window.__TAURI__?.core?.invoke;
    const url = `http://127.0.0.1:${result.port}/?_=${Date.now()}`;
    if (invoke) {
      try {
        await invoke("navigate", { url });
      } catch {
        window.location.replace(url);
      }
      return;
    }
    window.location.replace(url);
  }, [refreshInfo]);

  const doSwitch = useCallback(async (dir: string) => {
    setError("");
    setSwitching(true);
    const preferredPort = info?.port ?? 8686;
    try {
      const invoke = window.__TAURI__?.core?.invoke;
      if (invoke) {
        let r = await invoke("service_cli", {
          args: ["install", "--port", String(preferredPort), "--data-dir", dir],
        }) as { ok?: boolean; port?: number; data_dir?: string; backend_healthy?: boolean; error?: string };
        if (r?.ok === false) throw new Error(r?.error || "切换失败");
        if (!r?.port && !r?.data_dir) throw new Error(r?.error || "切换失败：service_cli 无有效响应");
        const port = r.port ?? preferredPort;
        const installedDir = r.data_dir ? await resolveTargetDir(r.data_dir) : await resolveTargetDir(dir);
        if (!r.backend_healthy) {
          const waited = await waitForWorkspaceSwitch(installedDir, port, 20000);
          if (!waited.ok) throw new Error("服务已注册但未通过健康检查，请稍后重试或查看 switch.log");
          await finishSwitch(waited.port, installedDir);
          return;
        }
        await finishSwitch(port, installedDir);
        return;
      }

      const r = await apiPost<{ ok: boolean; switching: boolean; detail?: string; port?: number; target?: string }>(
        "/api/workspace/switch", { data_dir: dir });
      if (!r.switching) {
        setSwitching(false);
        notifyWorkspaceChanged();
        await refreshInfo();
        onClose();
        return;
      }
      const port = r.port ?? preferredPort;
      const target = r.target ? await resolveTargetDir(r.target) : await resolveTargetDir(dir);
      await finishSwitch(port, target);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSwitching(false);
    }
  }, [finishSwitch, info, onClose, refreshInfo]);

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
            <div className="ws-hint">后台服务重启中，完成后自动刷新</div>
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
                {info?.service_mode === "dev" && info.configured_data_dir
                  && normalizeDir(info.configured_data_dir) !== normalizeDir(info.data_dir ?? "") ? (
                  <div className="ws-hint" style={{ marginTop: 8 }}>
                    已注册工作区为 {info.configured_data_dir}，但当前 dev 后端仍指向 {info.data_dir}。
                    请通过下方切换，或使用 ./start.sh（非 --dev）复用 launchd 后端。
                  </div>
                ) : null}
              </div>

              {info && !canSwitch && (
                <div className="ws-hint" style={{ marginBottom: 10 }}>
                  当前环境无法切换。请先运行
                  <code> python -m backend.service_cli install --data-dir &lt;目录&gt;</code>
                  注册服务，或使用 Tauri 桌面客户端。
                </div>
              )}

              {info?.recents && info.recents.length > 0 && (
                <>
                  <div className="ws-group">最近</div>
                  {info.recents.map((w) => (
                    <button key={w.dir} className="ws-item" disabled={!canSwitch}
                      onClick={() => void doSwitch(w.dir)}>
                      <span className="ws-item-name">{w.name}</span>
                      <span className="ws-item-dir">{w.dir}</span>
                    </button>
                  ))}
                </>
              )}

              <div className="ws-group">切换到其他目录</div>
              {hasNativePicker ? (
                <button className="ws-item" disabled={!canSwitch} onClick={() => void browse()}>
                  <span className="ws-item-name">浏览选择目录…</span>
                  <span className="ws-item-dir">新目录会初始化为空档案；含既有档案的目录直接接管</span>
                </button>
              ) : (
                <div className="ws-manual">
                  <input
                    placeholder="/path/to/workspace"
                    value={manualDir}
                    onChange={(e) => setManualDir(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && manualDir.trim()) void doSwitch(manualDir.trim()); }}
                  />
                  <button disabled={!canSwitch || !manualDir.trim()} onClick={() => void doSwitch(manualDir.trim())}>切换</button>
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
