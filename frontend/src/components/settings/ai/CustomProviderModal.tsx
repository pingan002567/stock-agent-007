import { useEffect, useState } from "react";
import { llmErrorMessage, upsertCustomLlmProvider } from "@/api/llmProviders";

const emptyModel = () => ({ id: "", name: "" });
const emptyHeader = () => ({ key: "", value: "" });

export function CustomProviderModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState([emptyModel()]);
  const [headers, setHeaders] = useState([emptyHeader()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await upsertCustomLlmProvider({
        id: id.trim(),
        name: name.trim(),
        base_url: baseUrl.trim(),
        api_key: apiKey.trim() || undefined,
        models: models.filter((m) => m.id.trim()),
        headers: headers
          .filter((h) => h.key.trim() && h.value.trim())
          .map((h) => ({ key: h.key.trim(), value: h.value.trim() })),
      });
      onSaved();
    } catch (err) {
      setError(llmErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div className="llm-dialog llm-dialog-wide" role="dialog" aria-modal="true">
        <div className="settings-modal-head">
          <span className="settings-modal-title">自定义提供商</span>
          <button className="func-close" onClick={onClose} title="关闭" type="button">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
        <div className="llm-dialog-body">
          <p className="llm-hint">任意 OpenAI 兼容网关（/v1/chat/completions）。ID 一旦保存请勿与内置提供商冲突。</p>
          <label className="page-stack" style={{ gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>提供商 ID</span>
            <input placeholder="acme" value={id} onChange={(e) => setId(e.target.value)} />
          </label>
          <label className="page-stack" style={{ gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>显示名称</span>
            <input placeholder="Acme LLM" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="page-stack" style={{ gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>Base URL</span>
            <input placeholder="https://llm.example.com/v1" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </label>
          <label className="page-stack" style={{ gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>API Key（可选）</span>
            <input type="password" placeholder="sk-…" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          </label>

          <div className="llm-field-label">模型</div>
          {models.map((m, i) => (
            <div key={i} className="llm-pair-row">
              <input placeholder="模型 ID" value={m.id} onChange={(e) => {
                const next = [...models]; next[i] = { ...m, id: e.target.value }; setModels(next);
              }} />
              <input placeholder="显示名" value={m.name} onChange={(e) => {
                const next = [...models]; next[i] = { ...m, name: e.target.value }; setModels(next);
              }} />
              <button type="button" className="ghost" disabled={models.length <= 1} onClick={() => setModels(models.filter((_, j) => j !== i))}>✕</button>
            </div>
          ))}
          <button type="button" className="ghost" onClick={() => setModels([...models, emptyModel()])}>添加模型</button>

          <div className="llm-field-label">请求头（可选）</div>
          {headers.map((h, i) => (
            <div key={i} className="llm-pair-row">
              <input placeholder="Header" value={h.key} onChange={(e) => {
                const next = [...headers]; next[i] = { ...h, key: e.target.value }; setHeaders(next);
              }} />
              <input placeholder="Value" value={h.value} onChange={(e) => {
                const next = [...headers]; next[i] = { ...h, value: e.target.value }; setHeaders(next);
              }} />
              <button type="button" className="ghost" disabled={headers.length <= 1} onClick={() => setHeaders(headers.filter((_, j) => j !== i))}>✕</button>
            </div>
          ))}
          <button type="button" className="ghost" onClick={() => setHeaders([...headers, emptyHeader()])}>添加 Header</button>

          {error && <div className="ws-error">{error}</div>}
          <button className="primary" type="button" disabled={busy} onClick={() => void save()}>
            {busy ? "保存中…" : "保存并连接"}
          </button>
        </div>
      </div>
    </div>
  );
}
