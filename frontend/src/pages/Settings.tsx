import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "@/api/client";
import {
  fetchCopilotRuns, fetchProviderEvents, fetchRuntimeMetrics, fetchRegressionCases,
  reconnectRuntime, testConnection,
  type CopilotRunLog, type ProviderEvent, type RuntimeMetricSnapshot,
  type RegressionCase, type ConnectionTestResult,
} from "@/api/runtime";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, PanelSkeleton, KpiSkeleton } from "@/components/ui/Loading";
import { RefreshButton } from "@/components/ui/RefreshButton";
import { useAppState } from "@/hooks/useAppState";

/* ---------- Types ---------- */

interface DataSourceProviderConfig {
  provider: string;
  label?: string;
  description?: string;
}
interface DataSourcesConfig {
  providers: Record<string, DataSourceProviderConfig>;
}
interface AvailableDataProvider {
  id: string;
  name: string;
  markets: string[];
  description: string;
  requirements?: string;
}

interface IntelProviderConfig {
  provider: string;
  api_key?: string | null;
  label?: string;
  description?: string;
}
interface IntelSourcesConfig {
  providers: Record<string, IntelProviderConfig>;
}
interface AvailableIntelProvider {
  id: string;
  name: string;
  category: string;
  markets: string[];
  api_key_required: boolean;
  description: string;
  requirements?: string;
}

interface SettingsData {
  agent_runtime?: { mode?: string; available?: boolean; active_client?: string; degraded?: boolean; degraded_reason?: string | null; model_name?: string; subagent_enabled?: boolean; plan_mode?: boolean };
  runtime_config?: Record<string, unknown>;
  models?: Array<{ name: string; provider?: string; role?: string }>;
  providers?: Array<{ name: string; display_name?: string; base_url?: string; status?: string }>;
  data_provider?: Record<string, unknown>;
  data_sources?: DataSourcesConfig;
  available_data_providers?: AvailableDataProvider[];
  intel_sources?: IntelSourcesConfig;
  available_intel_providers?: AvailableIntelProvider[];
  available_sentiment_providers?: AvailableIntelProvider[];
  tools?: Record<string, unknown> | Array<Record<string, unknown>>;
  risk_policy?: Record<string, unknown>;
  profiles?: Array<{ name?: string; description?: string }>;
  trading_controls?: { paper_trading?: string; real_order?: string };
}

type SettingTab = "general" | "ai" | "risk" | "stock" | "raw";

/* ---------- Helpers ---------- */

function ConfigRow({ label, value, mono }: { label: string; value: string | number; mono?: boolean }) {
  return (
    <div className="barline" style={{ padding: "6px 0" }}>
      <span className="muted" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
      <span />
      <span className={mono ? "num" : ""} style={{ textAlign: "right", wordBreak: "break-all" }}>{String(value)}</span>
    </div>
  );
}

function SectionCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="panel" style={{ marginBottom: 20 }}>
      <div className="panel-header">
        <div className="panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
          {title}
        </div>
        {subtitle && <span className="panel-badge">{subtitle}</span>}
      </div>
      <div className="panel-body">{children}</div>
    </div>
  );
}

function ConfigList({ data, showAll }: { data: Record<string, unknown>; showAll?: boolean }) {
  const entries = showAll ? Object.entries(data) : Object.entries(data).filter(([, v]) => v != null);
  if (entries.length === 0) return <div className="muted" style={{ padding: 8 }}>暂无数据</div>;
  return (
    <div className="page-stack" style={{ gap: 3 }}>
      {entries.map(([key, value]) => {
        const display = typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "");
        const isMulti = display.length > 80;
        return isMulti ? (
          <div key={key} style={{ padding: 10, borderRadius: 7, border: "1px solid var(--line)" }}>
            <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>{key}</div>
            <pre style={{ maxHeight: 160, fontSize: 11, margin: 0 }}>{display}</pre>
          </div>
        ) : (
          <ConfigRow key={key} label={key} value={display} mono />
        );
      })}
    </div>
  );
}

/* ---------- Risk Policy types ---------- */

interface RiskPolicyRules {
  single_position_max_weight_pct: number; single_position_warning_weight_pct: number;
  sector_max_weight_pct: number; draft_valid_hours: number;
  rebalance_min_delta_pct: number; monitor_default_cooldown_seconds: number;
}
interface RiskPolicy {
  policy_id: string; name: string; description: string;
  is_active: boolean; is_default: boolean; rules: RiskPolicyRules; version: number;
  created_at: string; updated_at: string;
}
interface RiskPolicyFormState { name: string; description: string; rules: RiskPolicyRules; }

const DEFAULT_RULES: RiskPolicyRules = {
  single_position_max_weight_pct: 15, single_position_warning_weight_pct: 12,
  sector_max_weight_pct: 35, draft_valid_hours: 24,
  rebalance_min_delta_pct: 2.0, monitor_default_cooldown_seconds: 3600,
};

function formatRules(rules?: Partial<RiskPolicyRules>) {
  if (!rules) return "-";
  return `单票上限 ${rules.single_position_max_weight_pct ?? "-"}% · 预警 ${rules.single_position_warning_weight_pct ?? "-"}% · 行业上限 ${rules.sector_max_weight_pct ?? "-"}% · 草案有效 ${rules.draft_valid_hours ?? "-"}h · 最小调仓 ${rules.rebalance_min_delta_pct ?? "-"}% · 盯盘冷却 ${rules.monitor_default_cooldown_seconds ?? "-"}s`;
}

function PolicyForm({ title, submitLabel, initial, saving, onSubmit, onCancel }: {
  title: string; submitLabel: string; initial: RiskPolicyFormState;
  saving: boolean; onSubmit: (v: RiskPolicyFormState) => Promise<void>; onCancel: () => void;
}) {
  const [form, setForm] = useState<RiskPolicyFormState>(initial);
  const upd = (k: keyof RiskPolicyRules, v: number) => setForm((p) => ({ ...p, rules: { ...p.rules, [k]: v } }));
  return (
    <div className="panel" style={{ marginTop: 10 }}>
      <div className="head"><span className="title">{title}</span></div>
      <div className="pad">
        <form className="page-stack" style={{ gap: 10 }} onSubmit={async (e) => { e.preventDefault(); await onSubmit(form); }}>
          <label className="page-stack" style={{ gap: 4 }}><span className="muted" style={{ fontSize: 12 }}>名称</span>
            <input value={form.name} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} required />
          </label>
          <label className="page-stack" style={{ gap: 4 }}><span className="muted" style={{ fontSize: 12 }}>描述</span>
            <input value={form.description} onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))} />
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
            {([["单只上限 (%)", "single_position_max_weight_pct"], ["预警阈值 (%)", "single_position_warning_weight_pct"], ["行业上限 (%)", "sector_max_weight_pct"], ["草案有效 (h)", "draft_valid_hours"], ["最小调仓差 (%)", "rebalance_min_delta_pct"], ["盯盘冷却 (s)", "monitor_default_cooldown_seconds"]] as const).map(([label, key]) => (
              <label key={key} className="page-stack" style={{ gap: 4 }}>
                <span className="muted" style={{ fontSize: 12 }}>{label}</span>
                <input type="number" step={key === "rebalance_min_delta_pct" ? "0.1" : "1"} value={form.rules[key]} onChange={(e) => upd(key, Number(e.target.value))} required />
              </label>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="submit" className="primary" disabled={saving}>{saving ? "保存中…" : submitLabel}</button>
            <button type="button" className="ghost" onClick={onCancel} disabled={saving}>取消</button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ==================== TABS ==================== */

/* ---------- 通用配置 ---------- */

function GeneralTab({
  settings, runtimeMetrics,
}: {
  settings: SettingsData;
  runtimeMetrics: RuntimeMetricSnapshot | null;
}) {
  const { darkMode, toggleDarkMode } = useAppState();
  return (
    <div className="two-col">
      <div>
        <SectionCard title="外观设置" subtitle="theme">
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: 12, background: "var(--bg-tertiary)", borderRadius: 8, cursor: "pointer" }} onClick={toggleDarkMode}>
            <div style={{ fontSize: 22, lineHeight: 1 }}>{darkMode ? "🌙" : "☀️"}</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{darkMode ? "暗色模式" : "亮色模式"}</div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>点击切换主题偏好</div>
            </div>
            <div style={{
              width: 44, height: 24, borderRadius: 12, padding: 2,
              background: darkMode ? "var(--blue)" : "var(--line)",
              transition: "background .15s ease",
            }}>
              <div style={{
                width: 20, height: 20, borderRadius: "50%", background: "#fff",
                transform: darkMode ? "translateX(20px)" : "translateX(0)",
                transition: "transform .15s ease",
                boxShadow: "0 1px 3px rgba(0,0,0,.2)",
              }} />
            </div>
          </div>
        </SectionCard>

        {settings.trading_controls && (
          <SectionCard title="交易控制" subtitle="trading safety">
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              {Object.entries(settings.trading_controls).map(([k, v]) => (
                <div key={k} style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>{k.replace(/_/g, " ")}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: v === "blocked" ? "var(--red)" : v === "sandbox_only" ? "var(--green)" : "var(--ink)" }}>
                    {String(v)}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
        )}

        {settings.agent_runtime && (
          <SectionCard title="Runtime 状态" subtitle="connection">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
              {Object.entries(settings.agent_runtime).slice(0, 6).map(([k, v]) => (
                <div key={k} style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>{k.replace(/_/g, " ")}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: k === "available" || k === "degraded" ? (v ? "var(--red)" : "var(--green)") : "var(--ink)" }}>
                    {typeof v === "boolean" ? (v ? "是" : "否") : String(v ?? "-")}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
        )}
      </div>

      <div>
        {runtimeMetrics && (
          <SectionCard title="运行摘要" subtitle="24小时">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12 }}>
              <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>数据源调用</div>
                <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "var(--font-mono)" }}>{runtimeMetrics.payload.provider?.total_calls ?? 0}</div>
                <div style={{ fontSize: 11, color: "var(--muted)" }}>失败 {runtimeMetrics.payload.provider?.failure_count ?? 0} · 回退 {runtimeMetrics.payload.provider?.fallback_count ?? 0}</div>
              </div>
              <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>平均耗时</div>
                <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "var(--font-mono)" }}>{runtimeMetrics.payload.provider?.avg_duration_ms ?? 0}毫秒</div>
              </div>
              <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Copilot 运行</div>
                <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "var(--font-mono)" }}>{runtimeMetrics.payload.copilot?.total_runs ?? 0}</div>
                <div style={{ fontSize: 11, color: "var(--muted)" }}>失败 {runtimeMetrics.payload.copilot?.failure_count ?? 0} · {runtimeMetrics.payload.copilot?.avg_tool_calls ?? 0} 工具/次</div>
              </div>
              <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>总成本</div>
                <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "var(--font-mono)" }}>${runtimeMetrics.payload.copilot?.total_cost?.toFixed(4) ?? "0.0000"}</div>
              </div>
            </div>
          </SectionCard>
        )}

        {runtimeMetrics?.payload.copilot && (
          <SectionCard title="AI 评测摘要" subtitle="质量指标">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
              <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>总运行</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "var(--font-mono)" }}>{runtimeMetrics.payload.copilot.total_runs ?? 0}</div>
              </div>
              <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>失败</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--red)" }}>{runtimeMetrics.payload.copilot.failure_count ?? 0}</div>
              </div>
              <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>平均延迟</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "var(--font-mono)" }}>{runtimeMetrics.payload.copilot.avg_latency_ms?.toFixed(0) ?? 0}毫秒</div>
              </div>
              <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Token 输入</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "var(--font-mono)" }}>{(runtimeMetrics.payload.copilot.usage_input_tokens ?? 0).toLocaleString()}</div>
              </div>
              <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Token 输出</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "var(--font-mono)" }}>{(runtimeMetrics.payload.copilot.usage_output_tokens ?? 0).toLocaleString()}</div>
              </div>
              <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>平均成本</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "var(--font-mono)" }}>${runtimeMetrics.payload.copilot.avg_cost?.toFixed(6) ?? "0.000000"}</div>
              </div>
            </div>
          </SectionCard>
        )}
      </div>
    </div>
  );
}

/* ---------- AI 配置 ---------- */

interface ModelOption {
  name: string;
  provider?: string;
  role?: string;
}

const MODEL_PROVIDER_BASE_URLS: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  deepseek: "https://api.deepseek.com",
  anthropic: "native SDK",
  gemini: "native or OpenAI-compatible",
};

function AiTab({
  settings, copilotRuns, runtimeMetrics, regressionCases, onSaveRuntimeConfig,
}: {
  settings: SettingsData;
  copilotRuns: CopilotRunLog[];
  runtimeMetrics: RuntimeMetricSnapshot | null;
  regressionCases: RegressionCase[];
  onSaveRuntimeConfig: (config: Record<string, unknown>) => Promise<void>;
}) {
  const rc = settings.runtime_config ?? {};
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState<string>((rc.base_url as string) ?? "");
  const [modelName, setModelName] = useState<string>((rc.model_name as string) ?? "");
  const [customModel, setCustomModel] = useState(false);
  const [thinking, setThinking] = useState<boolean>((rc.thinking_enabled as boolean) ?? true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testConnecting, setTestConnecting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [reconnecting, setReconnecting] = useState(false);

  const knownModels: ModelOption[] = (settings.models as ModelOption[]) ?? [];

  useEffect(() => {
    const r = settings.runtime_config ?? {};
    const storedModel = (r.model_name as string) ?? "";
    setBaseUrl((r.base_url as string) ?? "");
    setModelName(storedModel);
    setThinking((r.thinking_enabled as boolean) ?? true);
    setCustomModel(storedModel !== "" && !knownModels.some((m) => m.name === storedModel));
    setDirty(false);
  }, [settings.runtime_config]);

  const handleModelSelect = (name: string) => {
    if (name === "__custom__") {
      setCustomModel(true);
      return;
    }
    setCustomModel(false);
    setModelName(name);
    const model = knownModels.find((m) => m.name === name);
    if (model?.provider && MODEL_PROVIDER_BASE_URLS[model.provider]) {
      setBaseUrl(MODEL_PROVIDER_BASE_URLS[model.provider]);
    }
    markDirty();
  };

  const markDirty = () => { if (!dirty) setDirty(true); };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        ...rc,
        base_url: baseUrl || null,
        model_name: modelName || null,
        thinking_enabled: thinking,
      };
      if (apiKey) payload.api_key = apiKey;
      await onSaveRuntimeConfig(payload);
      setApiKey("");
      setDirty(false);
      // 后端会自动重连，显示成功状态
      setTestResult({ ok: true, model: modelName || undefined });
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "保存 AI 配置失败");
    } finally { setSaving(false); }
  };

  const handleTestConnection = async () => {
    setTestConnecting(true);
    setTestResult(null);
    try {
      const result = await testConnection({
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
        model_name: modelName || undefined,
      });
      setTestResult(result);
    } catch (err) {
      setTestResult({ ok: false, error: err instanceof Error ? err.message : "连接测试失败" });
    } finally { setTestConnecting(false); }
  };

  const ar = settings.agent_runtime;

  return (
    <div className="page-stack">

      <SectionCard title="AI Runtime 配置" subtitle="API Key / 模型 / 连接">
        <div className="page-stack" style={{ gap: 12 }}>
          <div className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>
            配置 AI 模型接入。API Key 可通过环境变量 <code>OPENAI_API_KEY</code> 设置，
            也可在此页输入并保存到本地数据库。环境变量优先级高于页面配置。
          </div>
          <label className="page-stack" style={{ gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>API Key</span>
            <input
              type="password" placeholder="sk-..." value={apiKey}
              onChange={(e) => { setApiKey(e.target.value); markDirty(); }}
              style={{ width: "100%", height: 34, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 13 }}
            />
          </label>
          <label className="page-stack" style={{ gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>Base URL</span>
            <input
              type="text" placeholder="https://api.deepseek.com/v1" value={baseUrl}
              onChange={(e) => { setBaseUrl(e.target.value); markDirty(); }}
              style={{ width: "100%", height: 34, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 13 }}
            />
          </label>
          <label className="page-stack" style={{ gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>模型</span>
            <select
              value={customModel ? "__custom__" : modelName}
              onChange={(e) => handleModelSelect(e.target.value)}
              style={{ width: "100%", height: 34, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 6px", fontSize: 13 }}
            >
              {modelName && !knownModels.some((m) => m.name === modelName) && (
                <option value={modelName}>{modelName} (当前)</option>
              )}
              {knownModels.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}{m.provider ? ` · ${m.provider}` : ""}{m.role ? ` (${m.role})` : ""}
                </option>
              ))}
              <option value="__custom__">自定义…</option>
            </select>
          </label>
          {customModel && (
            <label className="page-stack" style={{ gap: 4 }}>
              <span className="muted" style={{ fontSize: 12 }}>自定义模型名</span>
              <input
                type="text" placeholder="deepseek-chat" value={modelName}
                onChange={(e) => { setModelName(e.target.value); markDirty(); }}
                style={{ width: "100%", height: 34, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 13 }}
              />
            </label>
          )}
          {modelName && !customModel && (() => {
            const model = knownModels.find((m) => m.name === modelName);
            if (!model?.provider) return null;
            const provName = model.provider;
            const base = MODEL_PROVIDER_BASE_URLS[provName];
            if (!base) return null;
            return (
              <div className="muted" style={{ fontSize: 11, lineHeight: 1.4, padding: "2px 4px" }}>
                Provider: {provName} · Base URL: <code>{base}</code>
              </div>
            );
          })()}
          <div className="card" style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", cursor: "pointer" }}
            onClick={() => { setThinking(!thinking); markDirty(); }}>
            <span style={{ fontWeight: 600, fontSize: 13 }}>Thinking (推理)</span>
            <div style={{ marginLeft: "auto", width: 40, height: 22, borderRadius: 999, padding: 2,
              background: thinking ? "var(--blue)" : "var(--line)", transition: "background .15s ease" }}>
              <div style={{ width: 18, height: 18, borderRadius: "50%", background: "#fff",
                transform: thinking ? "translateX(18px)" : "translateX(0)", transition: "transform .15s ease",
                boxShadow: "0 1px 3px rgba(0,0,0,.15)" }} />
            </div>
          </div>
          {dirty && (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button className="primary" disabled={saving} onClick={handleSave} type="button">
                {saving ? "保存中…" : "保存 AI 配置"}
              </button>
              {saving && <span className="muted" style={{ fontSize: 12 }}>保存中…</span>}
            </div>
          )}
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button className="ghost" disabled={testConnecting} onClick={handleTestConnection} type="button" style={{ height: 32, fontSize: 12 }}>
              {testConnecting ? "测试中…" : "测试连接"}
            </button>
            {reconnecting && <span className="muted" style={{ fontSize: 12 }}>正在重连运行时…</span>}
            {testResult && (
              <span style={{ fontSize: 12, color: testResult.ok ? "var(--green)" : "var(--red)" }}>
                {testResult.ok
                  ? `连接成功 · ${testResult.model ?? ""} · ${testResult.latency_ms ?? ""}ms`
                  : `连接失败: ${testResult.error}`}
              </span>
            )}
          </div>
        </div>
      </SectionCard>

      {/* Runtime 状态 */}
      {ar && (
        <SectionCard title="Runtime 状态" subtitle="current connection">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 8 }}>
            {Object.entries(ar).map(([k, v]) => (
              <div key={k} className="card" style={{ padding: 10 }}>
                <h3>{k.replace(/_/g, " ")}</h3>
                <p>
                  <span className={`num ${k === "available" || k === "degraded" ? (v ? "down" : "up") : ""}`}>
                    {typeof v === "boolean" ? (v ? "是" : "否") : String(v ?? "-")}
                  </span>
                </p>
              </div>
            ))}
          </div>
        </SectionCard>
      )}

      {/* Skills */}
      <SectionCard title="Skills" subtitle="AI 能力">
        <ConfigList data={settings as unknown as Record<string, unknown>} />
      </SectionCard>

      {/* Copilot Runs */}
      {copilotRuns.length > 0 && (
        <SectionCard title="Copilot 运行记录" subtitle={`最新 ${Math.min(copilotRuns.length, 10)} 条`}>
          {copilotRuns.slice(0, 10).map((item) => (
            <div key={item.run_id} className="check" style={{ marginBottom: 3 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span className="num" style={{ fontSize: 12 }}>{item.run_id.slice(0, 14)}</span>
                  <span className={`tag ${item.status === "completed" ? "green" : "red"}`} style={{ fontSize: 11 }}>{item.status}</span>
                  {item.error_category && <span className="tag" style={{ fontSize: 11, background: "var(--amber-soft)", color: "var(--amber)" }}>{item.error_category}</span>}
                </div>
                <span className="muted" style={{ fontSize: 11 }}>{item.active_client} · {item.model_name ?? "default"} · {item.tool_call_count} tools</span>
                {item.cost != null && <span className="muted" style={{ fontSize: 11 }}> · ${item.cost.toFixed(6)}</span>}
                {item.latency_ms != null && <span className="muted" style={{ fontSize: 11 }}> · {item.latency_ms.toFixed(0)}ms</span>}
              </div>
            </div>
          ))}
        </SectionCard>
      )}

      {/* AI 评测摘要 */}
      {runtimeMetrics?.payload.copilot && (
        <SectionCard title="AI 评测摘要" subtitle="质量指标">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 8 }}>
            <div className="card" style={{ padding: 10 }}>
              <h3>总运行</h3>
              <p><span className="num">{runtimeMetrics.payload.copilot.total_runs ?? 0}</span></p>
            </div>
            <div className="card" style={{ padding: 10 }}>
              <h3>失败</h3>
              <p><span className="num" style={{ color: "var(--red)" }}>{runtimeMetrics.payload.copilot.failure_count ?? 0}</span></p>
            </div>
            <div className="card" style={{ padding: 10 }}>
              <h3>总成本</h3>
              <p><span className="num">${runtimeMetrics.payload.copilot.total_cost?.toFixed(4) ?? "0.0000"}</span></p>
            </div>
            <div className="card" style={{ padding: 10 }}>
              <h3>平均成本</h3>
              <p><span className="num">${runtimeMetrics.payload.copilot.avg_cost?.toFixed(6) ?? "0.000000"}</span></p>
            </div>
            <div className="card" style={{ padding: 10 }}>
              <h3>平均延迟</h3>
              <p><span className="num">{runtimeMetrics.payload.copilot.avg_latency_ms?.toFixed(0) ?? 0} ms</span></p>
            </div>
            <div className="card" style={{ padding: 10 }}>
              <h3>Token 输入</h3>
              <p><span className="num">{(runtimeMetrics.payload.copilot.usage_input_tokens ?? 0).toLocaleString()}</span></p>
            </div>
            <div className="card" style={{ padding: 10 }}>
              <h3>Token 输出</h3>
              <p><span className="num">{(runtimeMetrics.payload.copilot.usage_output_tokens ?? 0).toLocaleString()}</span></p>
            </div>
          </div>
          {runtimeMetrics.payload.copilot.error_distribution && Object.keys(runtimeMetrics.payload.copilot.error_distribution).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <h3 style={{ marginBottom: 8 }}>错误分布</h3>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {Object.entries(runtimeMetrics.payload.copilot.error_distribution).map(([cat, count]) => (
                  <div key={cat} className="card" style={{ padding: "8px 12px", display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="tag" style={{ background: "var(--red-soft)", color: "var(--red)" }}>{cat}</span>
                    <span className="num">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </SectionCard>
      )}

      {/* 回归评测用例 */}
      {regressionCases.length > 0 && (
        <SectionCard title="回归评测用例" subtitle={`共 ${regressionCases.length} 个`}>
          {regressionCases.map((c) => (
            <div key={c.case_id} className="check" style={{ marginBottom: 3 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span className="num" style={{ fontSize: 12 }}>{c.case_id}</span>
                  <span className="tag" style={{ fontSize: 11, background: c.mode === "full" ? "var(--amber-soft)" : "var(--blue-soft)", color: c.mode === "full" ? "var(--amber)" : "var(--blue)" }}>
                    {c.mode === "full" ? "full" : "structural"}
                  </span>
                  {c.requires_deerflow && <span className="tag" style={{ fontSize: 11 }}>需要 DeerFlow</span>}
                </div>
                <span className="muted" style={{ fontSize: 11 }}>{c.message} · page: {c.page}{c.symbol ? ` · symbol: ${c.symbol}` : ""}</span>
                {c.expected_tools && c.expected_tools.length > 0 && (
                  <span className="muted" style={{ fontSize: 11 }}> · tools: {c.expected_tools.join(", ")}</span>
                )}
              </div>
            </div>
          ))}
        </SectionCard>
      )}
    </div>
  );
}

/* ---------- 股票配置 ---------- */

function StockTab({
  settings, providerEvents, dataSources, availableProviders, onSaveDataSources, savingDataSources,
  intelSources, availableIntelProviders, availableSentimentProviders, onSaveIntelSources, savingIntelSources,
}: {
  settings: SettingsData;
  providerEvents: ProviderEvent[];
  dataSources: DataSourcesConfig;
  availableProviders: AvailableDataProvider[];
  onSaveDataSources: (config: DataSourcesConfig) => Promise<void>;
  savingDataSources: boolean;
  intelSources: IntelSourcesConfig;
  availableIntelProviders: AvailableIntelProvider[];
  availableSentimentProviders: AvailableIntelProvider[];
  onSaveIntelSources: (config: IntelSourcesConfig) => Promise<void>;
  savingIntelSources: boolean;
}) {
  const [localConfig, setLocalConfig] = useState<DataSourcesConfig>(dataSources);
  const [dirty, setDirty] = useState(false);

  // Sync when settings load
  useEffect(() => {
    setLocalConfig(dataSources);
    setDirty(false);
  }, [dataSources]);

  const handleProviderChange = (market: string, provider: string) => {
    setLocalConfig((prev) => ({
      ...prev,
      providers: {
        ...prev.providers,
        [market]: { ...prev.providers[market], provider },
      },
    }));
    setDirty(true);
  };

  const [localIntel, setLocalIntel] = useState<IntelSourcesConfig>(intelSources);
  const [intelDirty, setIntelDirty] = useState(false);

  useEffect(() => {
    setLocalIntel(intelSources);
    setIntelDirty(false);
  }, [intelSources]);

  const handleIntelProviderChange = (key: string, providerId: string) => {
    setLocalIntel((prev) => ({
      ...prev,
      providers: {
        ...prev.providers,
        [key]: { ...prev.providers[key], provider: providerId },
      },
    }));
    setIntelDirty(true);
  };

  const handleIntelApiKeyChange = (key: string, apiKey: string) => {
    setLocalIntel((prev) => ({
      ...prev,
      providers: {
        ...prev.providers,
        [key]: { ...prev.providers[key], api_key: apiKey || null },
      },
    }));
    setIntelDirty(true);
  };

  const marketLabels: Record<string, string> = { CN: "A 股", HK: "港股", US: "美股" };
  const marketIcons: Record<string, string> = { CN: "🇨🇳", HK: "🇭🇰", US: "🇺🇸" };

  return (
    <div className="page-stack">

      {/* 多市场数据源配置 */}
      <SectionCard title="多市场数据源配置" subtitle="per-market provider selection">
        <div className="page-stack" style={{ gap: 12 }}>
          <div className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>
            为每个市场选择数据提供源。AKShare 提供 A 股/港股/美股实时行情（需安装 akshare），
            模拟数据用于开发和演示环境。
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 10 }}>
            {["CN", "HK", "US"].map((market) => {
              const cfg = localConfig.providers?.[market] ?? { provider: "mock" };
              const current = cfg.provider;
              const availForMarket = availableProviders.filter((p) => p.markets.includes(market));
              return (
                <div key={market} className="card" style={{ padding: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                    <span style={{ fontSize: 18 }}>{marketIcons[market]}</span>
                    <strong style={{ fontSize: 14 }}>{marketLabels[market] ?? market}</strong>
                    <span style={{ fontSize: 11, color: "var(--muted)" }}>{market}</span>
                  </div>
                  <select
                    value={current}
                    onChange={(e) => handleProviderChange(market, e.target.value)}
                    style={{ width: "100%", height: 34, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 6px", fontSize: 13 }}
                  >
                    {availForMarket.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                  <div className="muted" style={{ fontSize: 11, marginTop: 6, lineHeight: 1.4 }}>
                    {availForMarket.find((p) => p.id === current)?.description ?? ""}
                  </div>
                </div>
              );
            })}
          </div>
          {dirty && (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button className="primary" disabled={savingDataSources}
                onClick={() => void onSaveDataSources(localConfig)} type="button">
                {savingDataSources ? "保存中…" : "保存数据源配置"}
              </button>
              {savingDataSources && <span className="muted" style={{ fontSize: 12 }}>保存中…</span>}
            </div>
          )}
        </div>
      </SectionCard>

      {/* 数据源实时状态 */}
      <SectionCard title="数据源实时状态" subtitle="stock data provider status">
        {settings.data_provider ? (() => {
          const dp = settings.data_provider!;
          const caps = (dp.capabilities as Record<string, { capability?: string; active_provider?: string; degraded?: boolean; degraded_reason?: string | null; coverage?: string }> | undefined) ?? {};
          return (
            <div className="page-stack" style={{ gap: 10 }}>
              <div className="barline" style={{ padding: "6px 0" }}>
                <span className="muted" style={{ fontSize: 12 }}>active_provider</span><span /><span className="num">{String(dp.active_provider ?? "-")}</span>
              </div>
              <div className="barline" style={{ padding: "6px 0" }}>
                <span className="muted" style={{ fontSize: 12 }}>fallback_provider</span><span /><span className="num">{String(dp.fallback_provider ?? "-")}</span>
              </div>
              {dp.degraded_reason ? (
                <div className="muted" style={{ fontSize: 11, lineHeight: 1.5, padding: "4px 0" }}>
                  ⚠️ {String(dp.degraded_reason)}
                </div>
              ) : null}
              <div style={{ fontSize: 12, fontWeight: 600, marginTop: 4 }}>各能力分发</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
                {Object.entries(caps).map(([key, cap]) => {
                  const provider = cap?.active_provider ?? "-";
                  const degraded = cap?.degraded ?? false;
                  const coverage = cap?.coverage ?? "";
                  return (
                    <div key={key} className="card" style={{ padding: 11 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                        <span style={{
                          width: 8, height: 8, borderRadius: "50%", display: "inline-block", flexShrink: 0,
                          background: degraded ? "var(--amber)" : "var(--green)",
                        }} />
                        <span className="num" style={{ fontSize: 12 }}>{key}</span>
                        <span className={`tag ${degraded ? "amber" : "green"}`} style={{ marginLeft: "auto", fontSize: 11 }}>{provider}</span>
                      </div>
                      <div className="muted" style={{ fontSize: 11, lineHeight: 1.5 }}>
                        {coverage ? `coverage: ${coverage}` : ""}
                        {degraded && cap?.degraded_reason ? <><br />{cap.degraded_reason}</> : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })() : (
          <div className="muted" style={{ padding: 8 }}>暂无数据源配置</div>
        )}
      </SectionCard>

      {/* 新闻与情报源配置 */}
      <SectionCard title="新闻与情报源配置" subtitle="news / intel search providers">
        <div className="page-stack" style={{ gap: 12 }}>
          <div className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>
            配置股票新闻搜索和舆情数据源。各 provider 独立配置，按列表顺序 fallback。
            如需设置 API Key，请填入相应字段（仅当前会话有效）。
          </div>
          {availableIntelProviders.length === 0 ? (
            <div className="muted" style={{ padding: 8 }}>暂无可用数据源</div>
          ) : (
            <div className="page-stack" style={{ gap: 10 }}>
              {/* 新闻搜索 providers */}
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>新闻搜索</div>
              {availableIntelProviders.map((prov) => {
                const cfg = localIntel.providers[prov.id] ?? { provider: "", api_key: null };
                const isSelected = cfg.provider === prov.id || cfg.provider === "" && prov.id === "mock";
                return (
                  <div key={prov.id} className="card" style={{ padding: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => handleIntelProviderChange(prov.id, isSelected ? "" : prov.id)}
                        style={{ accentColor: "var(--accent)" }}
                      />
                      <strong style={{ fontSize: 14 }}>{prov.name}</strong>
                      <span className="tag" style={{ fontSize: 10 }}>{prov.category}</span>
                    </div>
                    <div className="muted" style={{ fontSize: 11, lineHeight: 1.4, marginLeft: 24 }}>
                      {prov.description}
                    </div>
                    {prov.api_key_required && (
                      <div style={{ marginLeft: 24, marginTop: 6 }}>
                        <label style={{ fontSize: 11, color: "var(--muted)" }}>
                          API Key {prov.requirements ? `(${prov.requirements})` : ""}
                        </label>
                        <input
                          type="password"
                          placeholder="输入 API Key..."
                          value={cfg.api_key ?? ""}
                          onChange={(e) => handleIntelApiKeyChange(prov.id, e.target.value)}
                          style={{
                            width: "100%", height: 30, border: "1px solid var(--line)", borderRadius: 6,
                            background: "var(--panel)", color: "var(--ink)", padding: "0 8px", fontSize: 12, marginTop: 2,
                          }}
                        />
                      </div>
                    )}
                  </div>
                );
              })}

              {/* 舆情 providers */}
              {availableSentimentProviders.length > 0 && (
                <>
                  <div style={{ fontWeight: 600, fontSize: 13, marginTop: 8, marginBottom: 4 }}>舆情分析</div>
                  {availableSentimentProviders.map((prov) => {
                    const cfg = localIntel.providers[prov.id] ?? { provider: "", api_key: null };
                    const isSelected = cfg.provider === prov.id;
                    return (
                      <div key={prov.id} className="card" style={{ padding: 12 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => handleIntelProviderChange(prov.id, isSelected ? "" : prov.id)}
                            style={{ accentColor: "var(--accent)" }}
                          />
                          <strong style={{ fontSize: 14 }}>{prov.name}</strong>
                          <span className="tag" style={{ fontSize: 10 }}>{prov.category}</span>
                        </div>
                        <div className="muted" style={{ fontSize: 11, lineHeight: 1.4, marginLeft: 24 }}>
                          {prov.description}
                        </div>
                        {prov.api_key_required && (
                          <div style={{ marginLeft: 24, marginTop: 6 }}>
                            <label style={{ fontSize: 11, color: "var(--muted)" }}>
                              API Key {prov.requirements ? `(${prov.requirements})` : ""}
                            </label>
                            <input
                              type="password"
                              placeholder="输入 API Key..."
                              value={cfg.api_key ?? ""}
                              onChange={(e) => handleIntelApiKeyChange(prov.id, e.target.value)}
                              style={{
                                width: "100%", height: 30, border: "1px solid var(--line)", borderRadius: 6,
                                background: "var(--panel)", color: "var(--ink)", padding: "0 8px", fontSize: 12, marginTop: 2,
                              }}
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          )}
          {intelDirty && (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button className="primary" disabled={savingIntelSources}
                onClick={() => void onSaveIntelSources(localIntel)} type="button">
                {savingIntelSources ? "保存中…" : "保存情报源配置"}
              </button>
              {savingIntelSources && <span className="muted" style={{ fontSize: 12 }}>保存中…</span>}
            </div>
          )}
        </div>
      </SectionCard>

      {/* Tools */}
      {settings.tools && (
        <SectionCard title="工具注册表" subtitle="workbench tools">
          {(() => {
            const items = Array.isArray(settings.tools)
              ? settings.tools
              : Object.entries(settings.tools).map(([k, v]) => ({ name: k, ...(v as object) }));
            if (items.length === 0) return <div className="muted">暂无工具</div>;
            return (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
                {items.map((t: Record<string, unknown>, i: number) => {
                  const status = String(t.status ?? "-");
                  const isBlocked = status === "blocked";
                  const isActive = status === "enabled";
                  return (
                    <div key={i} className="card" style={{ padding: 11 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                        <span style={{
                          width: 8, height: 8, borderRadius: "50%", display: "inline-block", flexShrink: 0,
                          background: isBlocked ? "var(--red)" : isActive ? "var(--green)" : "var(--muted)",
                        }} />
                        <span className="num" style={{ fontSize: 12 }}>{String(t.name ?? `tool-${i}`)}</span>
                        <span className={`tag ${isBlocked ? "red" : isActive ? "green" : ""}`} style={{ marginLeft: "auto", fontSize: 11 }}>{status}</span>
                      </div>
                      <div className="muted" style={{ fontSize: 11, lineHeight: 1.5 }}>
                        {t.description ? String(t.description) : `domain: ${String(t.domain ?? "-")} · risk: ${String(t.risk ?? "-")}`}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })()}
        </SectionCard>
      )}

      {/* Provider Events */}
      {providerEvents.length > 0 && (
        <SectionCard title="Provider 事件" subtitle={`最新 ${Math.min(providerEvents.length, 8)} 条`}>
          {providerEvents.slice(0, 8).map((item) => (
            <div key={item.call_id} className="check" style={{ marginBottom: 3 }}>
              <div>
                <strong>{item.capability}</strong>
                <span className="muted" style={{ marginLeft: 6, fontSize: 11 }}>{item.provider}</span>
                <br /><span className="muted" style={{ fontSize: 11 }}>{item.market ?? "global"} · {item.created_at?.slice(11, 19) ?? ""}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className={`tag ${item.status === "success" ? "green" : item.status === "failed" ? "red" : ""}`} style={{ fontSize: 11 }}>{item.status}</span>
                <span className="num" style={{ fontSize: 11 }}>{item.duration_ms.toFixed(0)} ms</span>
              </div>
            </div>
          ))}
        </SectionCard>
      )}
    </div>
  );
}

/* ---------- 风控 ---------- */

function RiskTab({
  riskPolicies, showCreateForm, setShowCreateForm, editPolicyId, setEditPolicyId,
  savingPolicy, submitCreatePolicy, submitEditPolicy, activatePolicy, deletePolicy,
}: {
  riskPolicies: RiskPolicy[]; showCreateForm: boolean; setShowCreateForm: React.Dispatch<React.SetStateAction<boolean>>;
  editPolicyId: string | null; setEditPolicyId: React.Dispatch<React.SetStateAction<string | null>>;
  savingPolicy: boolean;
  submitCreatePolicy: (form: RiskPolicyFormState) => Promise<void>;
  submitEditPolicy: (id: string, form: RiskPolicyFormState) => Promise<void>;
  activatePolicy: (id: string) => Promise<void>;
  deletePolicy: (p: RiskPolicy) => Promise<void>;
}) {
  return (
    <SectionCard title="风控策略" subtitle="risk policy CRUD · 单票、行业、冷却规则">
      {showCreateForm ? (
        <div style={{ marginBottom: 10 }}>
          <PolicyForm title="新建" submitLabel="创建" initial={{ name: "", description: "", rules: { ...DEFAULT_RULES } }}
            saving={savingPolicy} onSubmit={submitCreatePolicy} onCancel={() => setShowCreateForm(false)} />
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <button type="button" className="ghost" style={{ height: 28, fontSize: 12, padding: "0 10px" }}
          onClick={() => { setShowCreateForm((v) => !v); setEditPolicyId(null); }} disabled={savingPolicy}>
          {showCreateForm ? "收起" : "+ 新建策略"}
        </button>
      </div>
      {riskPolicies.length === 0 ? (
        <div className="muted" style={{ padding: 8 }}>加载中…</div>
      ) : riskPolicies.map((p) => (
        <div key={p.policy_id} style={{
          padding: "8px 10px", marginBottom: 6, borderRadius: 7,
          border: p.is_active ? "1px solid var(--blue)" : "1px solid var(--line)",
          background: p.is_active ? "color-mix(in srgb, var(--blue) 6%, transparent)" : undefined,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap", minWidth: 0 }}>
              <strong style={{ fontSize: 13 }}>{p.name}</strong>
              {p.is_active ? <span className="tag green" style={{ fontSize: 10, height: 18, lineHeight: "18px" }}>active</span> : null}
              {p.is_default ? <span className="tag" style={{ fontSize: 10, height: 18, lineHeight: "18px" }}>default</span> : null}
              <span className="tag" style={{ fontSize: 10, height: 18, lineHeight: "18px" }}>v{p.version}</span>
              <span className="muted" style={{ fontSize: 11, marginLeft: 4 }}>{formatRules(p.rules)}</span>
            </div>
            <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
              <button type="button" className="ghost" style={{ height: 22, fontSize: 11, padding: "0 6px" }}
                onClick={() => { setShowCreateForm(false); setEditPolicyId(editPolicyId === p.policy_id ? null : p.policy_id); }} disabled={savingPolicy}>
                {editPolicyId === p.policy_id ? "收起" : "编辑"}
              </button>
              {!p.is_active ? <button type="button" className="primary" style={{ height: 22, fontSize: 11, padding: "0 8px" }}
                onClick={() => void activatePolicy(p.policy_id)} disabled={savingPolicy}>激活</button> : null}
              <button type="button" className="ghost" style={{ height: 22, fontSize: 11, padding: "0 6px" }}
                onClick={() => void deletePolicy(p)} disabled={savingPolicy}>删除</button>
            </div>
          </div>
          {editPolicyId === p.policy_id ? (
            <div style={{ marginTop: 8 }}>
              <PolicyForm title={`编辑 · ${p.name}`} submitLabel="保存"
                initial={{ name: p.name, description: p.description, rules: { ...p.rules } }}
                saving={savingPolicy}
                onSubmit={(f) => submitEditPolicy(p.policy_id, f)}
                onCancel={() => setEditPolicyId(null)} />
            </div>
          ) : null}
        </div>
      ))}
    </SectionCard>
  );
}

/* ---------- RAW JSON ---------- */

function RawTab({ data }: { data: SettingsData }) {
  return <pre style={{ maxHeight: 600, fontSize: 11, lineHeight: 1.6 }}>{JSON.stringify(data, null, 2)}</pre>;
}

/* ==================== MAIN ==================== */

const TABS: { key: SettingTab; label: string }[] = [
  { key: "general", label: "通用" },
  { key: "ai", label: "AI" },
  { key: "risk", label: "风控" },
  { key: "stock", label: "数据源" },
  { key: "raw", label: "原始 JSON" },
];

export default function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [runtimeMetrics, setRuntimeMetrics] = useState<RuntimeMetricSnapshot | null>(null);
  const [providerEvents, setProviderEvents] = useState<ProviderEvent[]>([]);
  const [copilotRuns, setCopilotRuns] = useState<CopilotRunLog[]>([]);
  const [regressionCases, setRegressionCases] = useState<RegressionCase[]>([]);
  const [activeTab, setActiveTab] = useState<SettingTab>("general");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [riskPolicies, setRiskPolicies] = useState<RiskPolicy[]>([]);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [editPolicyId, setEditPolicyId] = useState<string | null>(null);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [savingDataSources, setSavingDataSources] = useState(false);
  const [savingIntelSources, setSavingIntelSources] = useState(false);

  const loadPolicies = async () => {
    try { const r = await apiGet<{ items: RiskPolicy[] }>("/api/risk-policies"); setRiskPolicies(r.items); }
    catch { /* ignore */ }
  };

  const submitCreatePolicy = async (form: RiskPolicyFormState) => {
    setSavingPolicy(true);
    try { await apiPost("/api/risk-policies", form); setShowCreateForm(false); await loadPolicies(); }
    catch (err) { window.alert(err instanceof Error ? err.message : "创建失败"); }
    finally { setSavingPolicy(false); }
  };

  const submitEditPolicy = async (id: string, form: RiskPolicyFormState) => {
    setSavingPolicy(true);
    try { await apiPut(`/api/risk-policies/${id}`, form); setEditPolicyId(null); await loadPolicies(); }
    catch (err) { window.alert(err instanceof Error ? err.message : "更新失败"); }
    finally { setSavingPolicy(false); }
  };

  const activatePolicy = async (id: string) => {
    setSavingPolicy(true);
    try { await apiPost(`/api/risk-policies/${id}/activate`); await loadPolicies(); }
    catch (err) { window.alert(err instanceof Error ? err.message : "激活失败"); }
    finally { setSavingPolicy(false); }
  };

  const submitDataSources = async (config: DataSourcesConfig) => {
    setSavingDataSources(true);
    try {
      await apiPut("/api/settings/data-provider", config);
      await loadAll();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "保存数据源配置失败");
    } finally { setSavingDataSources(false); }
  };

  const submitIntelSources = async (config: IntelSourcesConfig) => {
    setSavingIntelSources(true);
    try {
      await apiPut("/api/settings/intel-sources", config);
      await loadAll();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "保存情报源配置失败");
    } finally { setSavingIntelSources(false); }
  };

  const submitRuntimeConfig = async (config: Record<string, unknown>) => {
    await apiPut("/api/settings/runtime", config);
    await loadAll();
  };

  const deletePolicy = async (p: RiskPolicy) => {
    if (!window.confirm(`确认删除策略「${p.name}」？`)) return;
    setSavingPolicy(true);
    try { await apiDelete(`/api/risk-policies/${p.policy_id}`); await loadPolicies(); }
    catch (err) { window.alert(err instanceof Error ? err.message : "删除失败"); }
    finally { setSavingPolicy(false); }
  };

  const loadAll = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const sd = await apiGet<SettingsData>("/api/settings");
      const [metrics, events, runs, cases] = await Promise.all([
        fetchRuntimeMetrics().catch(() => null),
        fetchProviderEvents().catch(() => []),
        fetchCopilotRuns().catch(() => []),
        fetchRegressionCases().catch(() => []),
      ]);
      setSettings(sd);
      setRuntimeMetrics(metrics);
      setProviderEvents(events);
      setCopilotRuns(runs);
      setRegressionCases(cases);
    } catch (err) { setError(err instanceof Error ? err.message : "加载设置失败"); } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void loadAll();
    void loadPolicies();
  }, [loadAll]);

  const renderTab = () => {
    if (!settings) return null;
    switch (activeTab) {
      case "general": return <GeneralTab settings={settings} runtimeMetrics={runtimeMetrics} />;
      case "ai": return <AiTab settings={settings} copilotRuns={copilotRuns} runtimeMetrics={runtimeMetrics} regressionCases={regressionCases} onSaveRuntimeConfig={submitRuntimeConfig} />;
      case "risk": return <RiskTab riskPolicies={riskPolicies} showCreateForm={showCreateForm} setShowCreateForm={setShowCreateForm} editPolicyId={editPolicyId} setEditPolicyId={setEditPolicyId} savingPolicy={savingPolicy} submitCreatePolicy={submitCreatePolicy} submitEditPolicy={submitEditPolicy} activatePolicy={activatePolicy} deletePolicy={deletePolicy} />;      case "stock": return (
        <StockTab
          settings={settings}
          providerEvents={providerEvents}
          dataSources={settings.data_sources ?? { providers: { CN: { provider: "akshare" }, HK: { provider: "akshare" }, US: { provider: "mock" } } }}
          availableProviders={settings.available_data_providers ?? []}
          onSaveDataSources={submitDataSources}
          savingDataSources={savingDataSources}
          intelSources={settings.intel_sources ?? { providers: {} }}
          availableIntelProviders={settings.available_intel_providers ?? []}
          availableSentimentProviders={settings.available_sentiment_providers ?? []}
          onSaveIntelSources={submitIntelSources}
          savingIntelSources={savingIntelSources}
        />
      );
      case "raw": return <RawTab data={settings} />;
    }
  };

  const runtimeStatus = settings?.agent_runtime?.status ?? (settings?.agent_runtime?.available ? "running" : "unknown");
  const activePolicyCount = riskPolicies.filter(p => p.is_active).length;
  const marketCount = Object.keys(settings?.data_sources?.providers ?? {}).length;

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        <div className="market-hero">
          <div className="market-hero-header">
            <div className="market-title">
              <h1>系统配置</h1>
              <p>管理 AI 模型、数据源、风控策略和系统参数。</p>
            </div>
            <div className="hero-actions">
              <RefreshButton refreshing={loading} onClick={() => void loadAll()} />
            </div>
          </div>
          <div className="market-stats">
            <div className="market-stat">
              <span className="market-stat-label">Runtime</span>
              <span className={`market-stat-value ${settings?.agent_runtime?.available ? "up" : ""}`}>
                {settings?.agent_runtime?.available ? "运行中" : "未知"}
              </span>
              <span className={`market-stat-change ${settings?.agent_runtime?.available ? "up" : "neutral"}`}>
                {settings?.agent_runtime?.available ? "● 正常运行" : "● 未知"}
              </span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">AI 模型</span>
              <span className="market-stat-value">{settings?.agent_runtime?.model_name ?? "未配置"}</span>
              <span className="market-stat-change up">● 已连接</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">数据源</span>
              <span className="market-stat-value">{marketCount} 市场</span>
              <span className="market-stat-change up">● 全部可用</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">风控策略</span>
              <span className="market-stat-value">{riskPolicies.length} 条</span>
              <span className="market-stat-change neutral">{activePolicyCount} 激活</span>
            </div>
          </div>
        </div>

        <div className="kpi-grid">
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">Runtime</span>
              <div className={`kpi-icon ${settings?.agent_runtime?.available ? "green" : "amber"}`}>●</div>
            </div>
            <div className="kpi-value" style={{ color: settings?.agent_runtime?.available ? "var(--green)" : "var(--amber)" }}>
              {settings?.agent_runtime?.available ? "运行中" : "未知"}
            </div>
            <div className="kpi-change neutral">正常运行</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">AI 模型</span>
              <div className="kpi-icon blue">🤖</div>
            </div>
            <div className="kpi-value">{settings?.agent_runtime?.model_name ?? "未配置"}</div>
            <div className="kpi-change up">● 已连接</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">数据源</span>
              <div className="kpi-icon amber">📊</div>
            </div>
            <div className="kpi-value">{marketCount} 市场</div>
            <div className="kpi-change up">● 全部可用</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">风控策略</span>
              <div className="kpi-icon" style={{ background: "rgba(139, 92, 246, 0.12)", color: "#8b5cf6" }}>🛡️</div>
            </div>
            <div className="kpi-value">{riskPolicies.length} 条</div>
            <div className="kpi-change neutral">{activePolicyCount} 激活</div>
          </div>
        </div>

        <div style={{ display: "flex", gap: 4, padding: 4, background: "var(--bg-secondary)", borderRadius: 12, border: "1px solid var(--line)" }}>
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              type="button"
              style={{
                flex: 1,
                padding: 10,
                background: activeTab === tab.key ? "var(--blue)" : "transparent",
                color: activeTab === tab.key ? "white" : "var(--muted)",
                border: "none",
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="page-stack">
            <PanelSkeleton /><KpiSkeleton count={3} /><PanelSkeleton />
          </div>
        ) : null}
        {!loading && error ? <ErrorMessage message={error} /> : null}

        {!loading && !error && settings ? (
          <div className="fade-in">
            {renderTab()}
          </div>
        ) : null}
      </div>
    </PageContainer>
  );
}
