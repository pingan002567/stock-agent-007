import { useEffect, useMemo, useState } from "react";
import { apiPut } from "@/api/client";
import { llmErrorMessage, setDefaultLlmModel, testLlmConnection, type LlmProvidersSnapshot } from "@/api/llmProviders";
import { ToggleSwitch } from "@/components/ui/ToggleSwitch";
import type { ConnectionTestResult } from "@/api/runtime";

export function ModelCatalogTab({
  snapshot,
  thinkingEnabled,
  runtimeConfig,
  onRefresh,
}: {
  snapshot: LlmProvidersSnapshot;
  thinkingEnabled: boolean;
  runtimeConfig: Record<string, unknown>;
  onRefresh: () => Promise<void> | void;
}) {
  const options = useMemo(() => {
    const rows: { value: string; label: string }[] = [];
    for (const provider of snapshot.connected) {
      for (const model of provider.models) {
        rows.push({
          value: `${provider.id}/${model.id}`,
          label: `${provider.name} · ${model.name}`,
        });
      }
    }
    return rows;
  }, [snapshot.connected]);

  const [selected, setSelected] = useState(snapshot.default_model || options[0]?.value || "");
  const [thinking, setThinking] = useState(thinkingEnabled);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setSelected(snapshot.default_model || options[0]?.value || "");
  }, [snapshot.default_model, options]);
  useEffect(() => { setThinking(thinkingEnabled); }, [thinkingEnabled]);

  const dirty = selected !== (snapshot.default_model || "") || thinking !== thinkingEnabled;

  const save = async () => {
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      if (selected !== snapshot.default_model) {
        await setDefaultLlmModel(selected);
      }
      if (thinking !== thinkingEnabled) {
        const { api_key: _omit, ...rest } = runtimeConfig;
        await apiPut("/api/settings/runtime", { ...rest, thinking_enabled: thinking });
      }
      await onRefresh();
    } catch (err) {
      setError(llmErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const [providerId, modelId] = selected.split("/", 2);
      setTestResult(await testLlmConnection({
        provider_id: providerId || undefined,
        model_name: modelId || undefined,
      }));
    } catch (err) {
      setTestResult({ ok: false, error: llmErrorMessage(err) });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="settings-stack">
      <div className="setting-card">
        <div className="setting-card-head">
          <div className="setting-card-heading">
            <div className="setting-card-title">默认模型</div>
            <div className="setting-card-desc">仅列出已连接提供商下的模型。Copilot 当前只使用这一组连接。</div>
          </div>
        </div>
        <div className="setting-card-body page-stack" style={{ gap: 12 }}>
          {options.length === 0 ? (
            <div className="llm-empty">请先在「提供商」里连接至少一家，才能选择默认模型。</div>
          ) : (
            <label className="page-stack" style={{ gap: 4 }}>
              <span className="muted" style={{ fontSize: 12 }}>模型</span>
              <select value={selected} onChange={(e) => setSelected(e.target.value)}>
                {options.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </label>
          )}
          <div className="llm-thinking-row">
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>Thinking（推理）</div>
              <div className="muted" style={{ fontSize: 12 }}>允许模型输出思维链。档案级偏好。</div>
            </div>
            <ToggleSwitch checked={thinking} onChange={setThinking} title="Thinking" />
          </div>
          {error && <div className="ws-error">{error}</div>}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button className="primary" type="button" disabled={!dirty || saving || options.length === 0} onClick={() => void save()}>
              {saving ? "保存中…" : "保存"}
            </button>
            <button className="ghost" type="button" disabled={testing || options.length === 0} onClick={() => void test()}>
              {testing ? "测试中…" : "测试连接"}
            </button>
            {testResult && (
              <span style={{ fontSize: 12, color: testResult.ok ? "var(--green)" : "var(--red)" }}>
                {testResult.ok
                  ? `连接成功 · ${testResult.model ?? ""} · ${testResult.latency_ms ?? ""}ms`
                  : `连接失败: ${testResult.error}`}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
