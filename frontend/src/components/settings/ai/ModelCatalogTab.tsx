import { useEffect, useMemo, useState } from "react";
import { apiPut } from "@/api/client";
import { fetchLlmModels, llmErrorMessage, setDefaultLlmModel, testLlmConnection, type LlmModelRow, type LlmProvidersSnapshot } from "@/api/llmProviders";
import { mergeModelOptions } from "@/lib/modelOptions";
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
  const [selected, setSelected] = useState(snapshot.default_model || "");
  /** 实时拉取到的模型：provider_id → 模型行。没有的提供商退回内置目录。 */
  const [live, setLive] = useState<Record<string, LlmModelRow[]>>({});
  const [liveAt, setLiveAt] = useState<Record<string, string>>({});
  const [pulling, setPulling] = useState(false);
  const [pullError, setPullError] = useState("");

  const options = useMemo(
    () => mergeModelOptions({
      connected: snapshot.connected,
      live,
      current: snapshot.default_model || undefined,
    }),
    [snapshot.connected, snapshot.default_model, live],
  );

  // 首次进入自动拉一次（失败就静默用内置目录，不打扰）
  useEffect(() => {
    if (snapshot.connected.length === 0) return;
    let alive = true;
    void (async () => {
      const next: Record<string, LlmModelRow[]> = {};
      const at: Record<string, string> = {};
      for (const provider of snapshot.connected) {
        try {
          const result = await fetchLlmModels({ provider_id: provider.id });
          next[provider.id] = result.models;
          at[provider.id] = result.fetched_at;
        } catch {
          /* 静默失败：目录兜底 */
        }
      }
      if (alive && Object.keys(next).length > 0) {
        setLive(next);
        setLiveAt(at);
      }
    })();
    return () => { alive = false; };
  }, [snapshot.connected]);
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

  const pullModels = async () => {
    setPulling(true);
    setPullError("");
    const next: Record<string, LlmModelRow[]> = {};
    const at: Record<string, string> = {};
    const failures: string[] = [];
    for (const provider of snapshot.connected) {
      try {
        const result = await fetchLlmModels({ provider_id: provider.id });
        next[provider.id] = result.models;
        at[provider.id] = result.fetched_at;
      } catch (err) {
        failures.push(`${provider.name}: ${llmErrorMessage(err)}`);
      }
    }
    setLive(next);
    setLiveAt(at);
    if (failures.length > 0) setPullError(failures.join("；"));
    setPulling(false);
  };

  const liveSummary = useMemo(() => {
    const ids = Object.keys(live);
    if (ids.length === 0) return "候选来自内置目录（可能滞后）";
    const total = ids.reduce((n, id) => n + live[id].length, 0);
    const latest = Object.values(liveAt).sort().pop() ?? "";
    const when = latest ? new Date(latest).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : "";
    return `实时 ${total} 个 · 更新于 ${when}`;
  }, [live, liveAt]);

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
          {pullError && <div className="ws-error">部分提供商拉取失败：{pullError}</div>}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button className="primary" type="button" disabled={!dirty || saving || options.length === 0} onClick={() => void save()}>
              {saving ? "保存中…" : "保存"}
            </button>
            <button className="ghost" type="button" disabled={testing || options.length === 0} onClick={() => void test()}>
              {testing ? "测试中…" : "测试连接"}
            </button>
            <button
              className="ghost"
              type="button"
              disabled={pulling || snapshot.connected.length === 0}
              onClick={() => void pullModels()}
              title="用当前 Key 向厂商拉取此刻真实在售的模型"
            >
              {pulling ? "拉取中…" : "拉取可用模型"}
            </button>
            <span className="muted" style={{ fontSize: 11.5 }}>
              {liveSummary}
            </span>
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
