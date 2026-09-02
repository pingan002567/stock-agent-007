import { useEffect, useState } from "react";
import { connectLlmProvider, llmErrorMessage, type LlmProviderItem } from "@/api/llmProviders";

/** 连接单个内置/已登记提供商：直接填 Key，不再经过选择器。 */
export function ConnectProviderModal({
  catalog,
  providerId,
  onClose,
  onConnected,
}: {
  catalog: LlmProviderItem[];
  providerId: string;
  onClose: () => void;
  onConnected: () => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const provider = catalog.find((p) => p.id === providerId) ?? null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const submit = async () => {
    if (!provider) return;
    setBusy(true);
    setError("");
    try {
      await connectLlmProvider(provider.id, apiKey.trim() || undefined);
      onConnected();
    } catch (err) {
      setError(llmErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!provider) {
    return (
      <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
        <div className="llm-dialog" role="dialog" aria-modal="true">
          <div className="settings-modal-head">
            <span className="settings-modal-title">连接提供商</span>
            <button className="func-close" onClick={onClose} title="关闭" type="button">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
            </button>
          </div>
          <div className="llm-dialog-body">
            <p className="llm-hint">未找到该提供商，请关闭后重试。</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div className="llm-dialog" role="dialog" aria-modal="true">
        <div className="settings-modal-head">
          <span className="settings-modal-title">连接 {provider.name}</span>
          <button className="func-close" onClick={onClose} title="关闭" type="button">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
        <div className="llm-dialog-body">
          <div className="llm-connect-lead">
            <span className="llm-provider-icon">{provider.name.charAt(0)}</span>
            <div>
              <div className="llm-provider-name">{provider.name}</div>
              <div className="llm-provider-desc">{provider.base_url}</div>
            </div>
          </div>
          {provider.note && <p className="llm-hint">{provider.note}</p>}
          {provider.requires_key ? (
            <label className="page-stack" style={{ gap: 4 }}>
              <span className="muted" style={{ fontSize: 12 }}>API Key</span>
              <input
                type="password"
                autoFocus
                placeholder={provider.has_key ? "已保存，留空则不修改" : "sk-…"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void submit(); }}
              />
            </label>
          ) : (
            <p className="llm-hint">此提供商通常无需 Key，连接后即可在默认模型里选择。</p>
          )}
          {error && <div className="ws-error">{error}</div>}
          <button
            className="primary"
            type="button"
            disabled={busy || (provider.requires_key && !apiKey.trim() && !provider.has_key)}
            onClick={() => void submit()}
          >
            {busy ? "连接中…" : "连接"}
          </button>
        </div>
      </div>
    </div>
  );
}
