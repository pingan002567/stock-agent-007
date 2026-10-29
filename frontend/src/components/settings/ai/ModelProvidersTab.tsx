import { useMemo, useState } from "react";
import {
  disconnectLlmProvider,
  fetchLlmModels,
  llmErrorMessage,
  sourceLabel,
  type LlmProvidersSnapshot,
} from "@/api/llmProviders";
import { ConnectProviderModal } from "./ConnectProviderModal";
import { CustomProviderModal } from "./CustomProviderModal";

export function ModelProvidersTab({
  snapshot,
  onRefresh,
  onAfterConnect,
}: {
  snapshot: LlmProvidersSnapshot;
  onRefresh: () => Promise<void> | void;
  /** 连接成功后跳转默认模型页（由 Settings 注入） */
  onAfterConnect?: () => void;
}) {
  const [connectId, setConnectId] = useState<string | null>(null);
  const [customOpen, setCustomOpen] = useState(false);
  /** 未连接提供商的模型预览：id → {models, loading, error} */
  const [preview, setPreview] = useState<Record<string, { models?: string[]; loading?: boolean; error?: string }>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const runtime = snapshot.runtime;
  const connectedIds = useMemo(
    () => new Set(snapshot.connected.map((item) => item.id)),
    [snapshot.connected],
  );
  /** 可以免 Key 预览的提供商：接口公开（OpenRouter / Ollama 这类） */
  const canPreview = (id: string) => id === "openrouter" || id === "ollama" || id === "siliconflow";

  const togglePreview = async (providerId: string) => {
    const current = preview[providerId];
    if (current?.models) {
      setPreview((prev) => ({ ...prev, [providerId]: {} }));
      return;
    }
    setPreview((prev) => ({ ...prev, [providerId]: { loading: true } }));
    try {
      const result = await fetchLlmModels({ provider_id: providerId });
      setPreview((prev) => ({ ...prev, [providerId]: { models: result.models.map((m) => m.id) } }));
    } catch (err) {
      setPreview((prev) => ({ ...prev, [providerId]: { error: llmErrorMessage(err) } }));
    }
  };

  const builtinProviders = useMemo(
    () => snapshot.catalog.filter((item) => !item.custom && !connectedIds.has(item.id)),
    [snapshot.catalog, connectedIds],
  );

  const disconnect = async (id: string, name: string) => {
    if (!window.confirm(`断开「${name}」？已保存的 Key 会从本机凭证中移除。`)) return;
    setBusyId(id);
    setError("");
    try {
      await disconnectLlmProvider(id);
      await onRefresh();
    } catch (err) {
      setError(llmErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="settings-stack">
      <div className="llm-runtime-strip">
        <span>当前 {runtime.provider_name && runtime.model_id
          ? `${runtime.provider_name} · ${runtime.model_id}`
          : (runtime.default_model || "未选择模型")}</span>
        {runtime.source && <span>来源 {sourceLabel(runtime.source)}</span>}
        <span>{runtime.connected ? "已连接" : "未连接"}</span>
      </div>

      {error && <div className="ws-error" style={{ marginBottom: 10 }}>{error}</div>}

      <div className="llm-provider-section">
        <h3 className="llm-section-title">已连接</h3>
        {snapshot.connected.length === 0 ? (
          <div className="llm-empty">还没有连接任何提供商。从下方内置列表选择，或添加自定义网关。</div>
        ) : (
          <div className="llm-provider-list">
            {snapshot.connected.map((item) => (
              <div key={item.id} className="llm-provider-row">
                <div className="llm-provider-lead">
                  <span className="llm-provider-icon">{item.name.charAt(0)}</span>
                  <div className="llm-provider-copy">
                    <div className="llm-provider-title-row">
                      <span className="llm-provider-name">{item.name}</span>
                      {item.source && <span className="llm-provider-tag">{sourceLabel(item.source)}</span>}
                    </div>
                  </div>
                </div>
                {item.can_disconnect ? (
                  <button
                    type="button"
                    className="ghost"
                    disabled={busyId === item.id}
                    onClick={() => void disconnect(item.id, item.name)}
                  >
                    {busyId === item.id ? "断开中…" : "断开"}
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>

      {builtinProviders.length > 0 && (
        <div className="llm-provider-section">
          <h3 className="llm-section-title">内置提供商</h3>
          <div className="llm-provider-list">
            {builtinProviders.map((item) => (
              <div key={item.id} className="llm-provider-row">
                <div className="llm-provider-lead">
                  <span className="llm-provider-icon">{item.name.charAt(0)}</span>
                  <div className="llm-provider-copy">
                    <div className="llm-provider-title-row">
                      <span className="llm-provider-name">{item.name}</span>
                    </div>
                    {item.note && <p className="llm-provider-desc">{item.note}</p>}
                    {preview[item.id]?.models && (
                      <div className="llm-provider-models">
                        {preview[item.id].models!.length} 个模型 ·{" "}
                        {preview[item.id].models!.slice(0, 6).join("、")}
                        {preview[item.id].models!.length > 6 ? " …" : ""}
                      </div>
                    )}
                    {preview[item.id]?.error && (
                      <div className="llm-provider-desc" style={{ color: "var(--red)" }}>
                        {preview[item.id]!.error}
                      </div>
                    )}
                  </div>
                </div>
                <div className="llm-provider-actions">
                  {canPreview(item.id) && (
                    <button
                      type="button"
                      className="ghost"
                      disabled={preview[item.id]?.loading}
                      onClick={() => void togglePreview(item.id)}
                      title="免 Key 预览该提供商此刻在售的模型"
                    >
                      {preview[item.id]?.loading
                        ? "拉取中…"
                        : preview[item.id]?.models ? "收起" : "预览模型"}
                    </button>
                  )}
                  <button type="button" className="primary" onClick={() => setConnectId(item.id)}>连接</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="llm-provider-section">
        <h3 className="llm-section-title">自定义提供商</h3>
        <div className="llm-provider-list">
          <div className="llm-provider-row">
            <div className="llm-provider-lead">
              <span className="llm-provider-icon">+</span>
              <div className="llm-provider-copy">
                <div className="llm-provider-title-row">
                  <span className="llm-provider-name">OpenAI 兼容网关</span>
                  <span className="llm-provider-tag">自定义</span>
                </div>
                <p className="llm-provider-desc">Base URL、模型列表与可选 Header。</p>
              </div>
            </div>
            <button type="button" className="primary" onClick={() => setCustomOpen(true)}>连接</button>
          </div>
        </div>
      </div>

      {connectId && (
        <ConnectProviderModal
          catalog={snapshot.catalog}
          providerId={connectId}
          onClose={() => setConnectId(null)}
          onConnected={() => { setConnectId(null); void onRefresh(); onAfterConnect?.(); }}
        />
      )}
      {customOpen && (
        <CustomProviderModal
          onClose={() => setCustomOpen(false)}
          onSaved={() => { setCustomOpen(false); void onRefresh(); onAfterConnect?.(); }}
        />
      )}
    </div>
  );
}
