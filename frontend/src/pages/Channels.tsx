import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, apiDelete } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { RefreshButton } from "@/components/ui/RefreshButton";
import { formatTimeAgo } from "@/utils/format";

interface ProviderConfig { enabled?: boolean; bot_token?: string; app_token?: string; bot_id?: string; bot_secret?: string }
interface ChannelsConfig { require_binding?: boolean; telegram?: ProviderConfig; slack?: ProviderConfig; wecom?: ProviderConfig }
type ProviderId = "telegram" | "slack" | "wecom";
type ConfigField = "bot_token" | "app_token" | "bot_id" | "bot_secret";
type FieldDef = { key: ConfigField; label: string; placeholder: string };
interface Binding { channel: string; chat_id: string; label?: string; bound_at?: number }
interface ChannelStatus { running: boolean; channels: { name: string; running: boolean }[] }
interface ConnectState { provider: string; code: string; expiresAt: number; instruction: string }

export default function Channels() {
  const [config, setConfig] = useState<ChannelsConfig>({});
  const [status, setStatus] = useState<ChannelStatus | null>(null);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [connect, setConnect] = useState<ConnectState | null>(null);
  const [now, setNow] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [cfg, st, bd] = await Promise.all([
        apiGet<ChannelsConfig>("/api/channels/config").catch(() => ({})),
        apiGet<ChannelStatus>("/api/channels/status").catch(() => null),
        apiGet<{ items: Binding[] }>("/api/channels/bindings").then((r) => r.items).catch(() => []),
      ]);
      setConfig(cfg); setStatus(st); setBindings(bd);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void loadAll(); }, [loadAll]); // eslint-disable-line react-hooks/set-state-in-effect

  // tick for the connect-dialog countdown
  useEffect(() => {
    if (!connect) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [connect]);

  const setProvider = (provider: ProviderId, patch: Partial<ProviderConfig>) =>
    setConfig((c) => ({ ...c, [provider]: { ...(c[provider] ?? {}), ...patch } }));

  const saveProvider = async (provider: ProviderId) => {
    setSaving(provider);
    try {
      const p = config[provider] ?? {};
      await apiPost("/api/channels/config", { [provider]: { ...p, enabled: true } });
      await loadAll();
    } finally { setSaving(null); }
  };

  const toggleRequireBinding = async (value: boolean) => {
    setConfig((c) => ({ ...c, require_binding: value }));
    await apiPost("/api/channels/config", { require_binding: value });
  };

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };

  const startConnect = async (provider: string) => {
    const before = bindings.length;
    const res = await apiPost<{ code: string; expires_in: number; instruction: string }>("/api/channels/connect-code", {});
    const issuedAt = Date.now();
    setNow(issuedAt);
    setConnect({ provider, code: res.code, expiresAt: issuedAt + res.expires_in * 1000, instruction: res.instruction });
    stopPoll();
    pollRef.current = setInterval(async () => {
      const items = await apiGet<{ items: Binding[] }>("/api/channels/bindings").then((r) => r.items).catch(() => []);
      if (items.length > before) { setBindings(items); stopPoll(); setConnect(null); await loadAll(); }
    }, 2000);
  };

  const closeConnect = () => { stopPoll(); setConnect(null); };
  useEffect(() => () => stopPoll(), []);

  const unbind = async (b: Binding) => {
    await apiDelete(`/api/channels/bindings/${b.channel}/${b.chat_id}`);
    await loadAll();
  };

  const running = (name: string) => status?.channels.find((c) => c.name === name)?.running ?? false;
  const remainingSec = connect ? Math.max(0, Math.ceil((connect.expiresAt - now) / 1000)) : 0;

  const providerCard = (provider: ProviderId, title: string, icon: string, fields: FieldDef[]) => {
    const p = config[provider] ?? {};
    const configured = fields.every((f) => p[f.key]);
    return (
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-header">
          <div className="panel-title">{icon} {title}</div>
          <span className={`tag ${running(provider) ? "green" : configured ? "amber" : "gray"}`}>
            {running(provider) ? "● 运行中" : configured ? "● 已配置" : "○ 未配置"}
          </span>
        </div>
        <div className="panel-body" style={{ display: "grid", gap: 10 }}>
          {fields.map((f) => (
            <div key={f.key} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 90, fontSize: 12, color: "var(--muted)" }}>{f.label}</span>
              <input style={{ flex: 1 }} placeholder={f.placeholder}
                value={p[f.key] ?? ""} onChange={(e) => setProvider(provider, { [f.key]: e.target.value })} />
            </div>
          ))}
          <div style={{ display: "flex", gap: 8 }}>
            <button className="primary small" disabled={saving === provider} onClick={() => void saveProvider(provider)} type="button">
              {saving === provider ? "保存中…" : "保存"}
            </button>
            <button className="small" disabled={!configured} onClick={() => void startConnect(provider)} type="button">连接</button>
          </div>
        </div>
      </div>
    );
  };

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        <div className="market-hero">
          <div className="market-hero-header">
            <div className="market-title">
              <h1>IM 渠道</h1>
              <p>在 IM 里直接与投研助手对话，并接收盯盘告警。全程无需公网。</p>
            </div>
            <div className="hero-actions">
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
                <input type="checkbox" checked={config.require_binding ?? true} onChange={(e) => void toggleRequireBinding(e.target.checked)} />
                要求绑定
              </label>
              <RefreshButton refreshing={loading} onClick={() => void loadAll()} />
            </div>
          </div>
          <div className="market-stats">
            <div className="market-stat">
              <span className="market-stat-label">服务状态</span>
              <span className={`market-stat-value ${status?.running ? "up" : ""}`}>{status?.running ? "运行中" : "未运行"}</span>
              <span className="market-stat-change neutral">{(status?.channels.length ?? 0)} 个渠道</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">已绑定会话</span>
              <span className="market-stat-value">{bindings.length}</span>
              <span className="market-stat-change neutral">个</span>
            </div>
          </div>
        </div>

        <div className="two-col">
          <div>
            {providerCard("telegram", "Telegram", "📨", [{ key: "bot_token", label: "Bot Token", placeholder: "123:ABC..." }])}
            {providerCard("slack", "Slack", "💬", [
              { key: "bot_token", label: "Bot Token", placeholder: "xoxb-..." },
              { key: "app_token", label: "App Token", placeholder: "xapp-..." },
            ])}
            {providerCard("wecom", "企业微信", "🏢", [
              { key: "bot_id", label: "Bot ID", placeholder: "智能机器人 botId" },
              { key: "bot_secret", label: "Bot Secret", placeholder: "智能机器人 secret" },
            ])}
            <div className="muted" style={{ fontSize: 12 }}>钉钉 / 飞书 即将支持。</div>
          </div>

          <div className="panel">
            <div className="panel-header"><div className="panel-title">已绑定会话</div><span className="panel-badge">{bindings.length}</span></div>
            <div className="panel-body">
              {bindings.length === 0 ? (
                <div className="muted">暂无绑定。配置 Bot 后点「连接」生成连接码，在 IM 里发送 /connect &lt;code&gt;。</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {bindings.map((b) => (
                    <div key={`${b.channel}:${b.chat_id}`} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: 10, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>{b.channel} · {b.chat_id}</div>
                        <div style={{ fontSize: 11, color: "var(--muted)" }}>{b.label ? `用户 ${b.label} · ` : ""}{b.bound_at ? `绑定于 ${formatTimeAgo(new Date(b.bound_at * 1000).toISOString())}` : ""}</div>
                      </div>
                      <button className="small" style={{ color: "var(--red)" }} onClick={() => void unbind(b)} type="button">解绑</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {connect && (
        <div className="modal-overlay" style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }} onClick={closeConnect}>
          <div className="panel" style={{ width: 420, maxWidth: "90vw" }} onClick={(e) => e.stopPropagation()}>
            <div className="panel-header"><div className="panel-title">连接 {connect.provider}</div><button className="small" onClick={closeConnect} type="button">✕</button></div>
            <div className="panel-body" style={{ display: "grid", gap: 12 }}>
              <div>
                <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>连接码</div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <code style={{ flex: 1, padding: "8px 10px", background: "var(--bg-tertiary)", borderRadius: 6, wordBreak: "break-all", fontSize: 13 }}>{connect.code}</code>
                  <button className="small" onClick={() => void navigator.clipboard?.writeText(connect.code)} type="button">复制</button>
                </div>
              </div>
              <div style={{ fontSize: 13 }}>在 Bot 里发送：<code>/connect {connect.code}</code></div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>{connect.instruction}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--amber)" }} />
                {remainingSec > 0 ? `等待绑定… ${Math.floor(remainingSec / 60)}:${String(remainingSec % 60).padStart(2, "0")} 后过期` : "连接码已过期，请重新生成"}
              </div>
            </div>
          </div>
        </div>
      )}
    </PageContainer>
  );
}
