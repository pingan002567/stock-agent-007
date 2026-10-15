import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/api/client";

interface Binding { channel: string; chat_id: string; label?: string; bound_at?: number; alerts_enabled?: boolean }
interface ConnectState { code: string; expiresAt: number; instruction: string }

/**
 * 平台无关的 IM 告警绑定面板：生成一次性连接码 → 用户在已配置的 Bot 里发
 * /connect <code> 完成绑定；绑定后的会话即接收盯盘告警。可嵌入任意页面。
 */
export function ChannelBindings() {
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [connect, setConnect] = useState<ConnectState | null>(null);
  const [now, setNow] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    const items = await apiGet<{ items: Binding[] }>("/api/channels/bindings").then((r) => r.items).catch(() => []);
    setBindings(items);
  }, []);

  useEffect(() => { void load(); }, [load]); // eslint-disable-line react-hooks/set-state-in-effect

  useEffect(() => {
    if (!connect) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [connect]);

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  useEffect(() => () => stopPoll(), []);

  const startConnect = async () => {
    const before = bindings.length;
    const res = await apiPost<{ code: string; expires_in: number; instruction: string }>("/api/channels/connect-code", {});
    const issuedAt = Date.now();
    setNow(issuedAt);
    setConnect({ code: res.code, expiresAt: issuedAt + res.expires_in * 1000, instruction: res.instruction });
    stopPoll();
    pollRef.current = setInterval(async () => {
      const items = await apiGet<{ items: Binding[] }>("/api/channels/bindings").then((r) => r.items).catch(() => []);
      if (items.length > before) { setBindings(items); stopPoll(); setConnect(null); }
    }, 2000);
  };

  const unbind = async (b: Binding) => {
    await apiDelete(`/api/channels/bindings/${b.channel}/${b.chat_id}`);
    await load();
  };

  const toggleAlerts = async (b: Binding, enabled: boolean) => {
    // optimistic flip, then persist
    setBindings((prev) => prev.map((x) => (x.channel === b.channel && x.chat_id === b.chat_id ? { ...x, alerts_enabled: enabled } : x)));
    await apiPatch(`/api/channels/bindings/${b.channel}/${b.chat_id}`, { alerts_enabled: enabled }).catch(() => void load());
  };

  const remaining = connect ? Math.max(0, Math.ceil((connect.expiresAt - now) / 1000)) : 0;
  const activeCount = bindings.filter((b) => b.alerts_enabled !== false).length;

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>已绑定 {bindings.length} 个会话，{activeCount} 个接收盯盘告警</span>
        <button className="small primary" onClick={() => void startConnect()} type="button">+ 绑定 IM</button>
      </div>
      {bindings.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {bindings.map((b) => (
            <div key={`${b.channel}:${b.chat_id}`} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 10px", background: "var(--bg-tertiary)", borderRadius: 6, fontSize: 12 }}>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{b.channel} · {b.chat_id}{b.label ? ` · ${b.label}` : ""}</span>
              <label style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer", color: b.alerts_enabled !== false ? "var(--text)" : "var(--muted)", flexShrink: 0 }} title="勾选后此会话接收盯盘告警">
                <input type="checkbox" checked={b.alerts_enabled !== false} onChange={(e) => void toggleAlerts(b, e.target.checked)} />
                接收告警
              </label>
              <button className="small" style={{ color: "var(--red)", flexShrink: 0 }} onClick={() => void unbind(b)} type="button">解绑</button>
            </div>
          ))}
        </div>
      )}

      {connect && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }} onClick={() => { stopPoll(); setConnect(null); }}>
          <div className="panel" style={{ width: 420, maxWidth: "90vw" }} onClick={(e) => e.stopPropagation()}>
            <div className="panel-header"><div className="panel-title">绑定 IM 接收告警</div><button className="small" onClick={() => { stopPoll(); setConnect(null); }} type="button">✕</button></div>
            <div className="panel-body" style={{ display: "grid", gap: 12 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <code style={{ flex: 1, padding: "8px 10px", background: "var(--bg-tertiary)", borderRadius: 6, wordBreak: "break-all", fontSize: 13 }}>{connect.code}</code>
                <button className="small" onClick={() => void navigator.clipboard?.writeText(connect.code)} type="button">复制</button>
              </div>
              <div style={{ fontSize: 13 }}>在已配置的 Bot 里发送：<code>/connect {connect.code}</code></div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>{connect.instruction}（未配置 Bot 请先到「设置→渠道」）</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--amber)" }} />
                {remaining > 0 ? `等待绑定… ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")} 后过期` : "连接码已过期，请重新生成"}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
