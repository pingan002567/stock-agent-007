import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "@/api/client";
import {
  fetchCopilotRuns, fetchProviderEvents, fetchRuntimeMetrics, fetchRegressionCases,
  fetchMemoryStatus, clearMemory, deleteMemoryFact, updateMemoryFact, createMemoryFact,
  fetchMcpConfig, updateMcpConfig,
  type CopilotRunLog, type ProviderEvent, type RuntimeMetricSnapshot,
  type RegressionCase, type MemoryStatus,
  type McpServerConfig,
} from "@/api/runtime";
import { ErrorMessage, PanelSkeleton, KpiSkeleton } from "@/components/ui/Loading";
import { ToggleSwitch } from "@/components/ui/ToggleSwitch";
import { useAppState } from "@/hooks/useAppState";
import ChannelsTab from "./Channels";
import { ModelProvidersTab } from "@/components/settings/ai/ModelProvidersTab";
import { ModelCatalogTab } from "@/components/settings/ai/ModelCatalogTab";
import type { LlmProvidersSnapshot } from "@/api/llmProviders";

/* ---------- Types ---------- */

interface DataSourceProviderConfig {
  provider: string;
  label?: string;
  description?: string;
}
interface DataSourcesConfig {
  providers: Record<string, DataSourceProviderConfig>;
  provider_credentials?: Record<string, Record<string, string | null>>;
  provider_states?: Record<string, { enabled: boolean }>;
}
interface ProviderCredentialField {
  key: string;
  label: string;
  env: string;
  secret?: boolean;
}
interface AvailableDataProvider {
  id: string;
  name: string;
  markets: string[];
  description: string;
  requirements?: string;
  free?: boolean;
  enabled_by_default?: boolean;
}

interface IntelProviderConfig {
  provider: string;
  enabled?: boolean;
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
  free?: boolean;
  description: string;
  requirements?: string;
}

function providerCredentialsComplete(
  providerId: string,
  credentialSchema: Record<string, ProviderCredentialField[]>,
  credentials: Record<string, Record<string, string | null>> | undefined,
): boolean {
  const fields = credentialSchema[providerId] ?? [];
  if (fields.length === 0) return true;
  return fields.every((field) => {
    const value = credentials?.[providerId]?.[field.key];
    return typeof value === "string" && value.trim().length > 0;
  });
}

function isMarketProviderUsable(
  provider: AvailableDataProvider,
  config: DataSourcesConfig,
  credentialSchema: Record<string, ProviderCredentialField[]>,
): boolean {
  const enabled = config.provider_states?.[provider.id]?.enabled ?? provider.enabled_by_default ?? provider.free ?? false;
  if (!enabled) return false;
  if (provider.free) return true;
  return providerCredentialsComplete(provider.id, credentialSchema, config.provider_credentials);
}

interface SettingsData {
  agent_runtime?: { mode?: string; available?: boolean; active_client?: string; degraded?: boolean; degraded_reason?: string | null; model_name?: string; subagent_enabled?: boolean; plan_mode?: boolean };
  runtime_config?: Record<string, unknown>;
  models?: Array<{ name: string; provider?: string; role?: string }>;
  providers?: Array<{ name: string; display_name?: string; base_url?: string; status?: string }>;
  data_provider?: Record<string, unknown>;
  data_sources?: DataSourcesConfig;
  available_data_providers?: AvailableDataProvider[];
  provider_credential_schema?: Record<string, ProviderCredentialField[]>;
  intel_sources?: IntelSourcesConfig;
  available_intel_providers?: AvailableIntelProvider[];
  available_sentiment_providers?: AvailableIntelProvider[];
  tools?: Record<string, unknown> | Array<Record<string, unknown>>;
  risk_policy?: Record<string, unknown>;
  profiles?: Array<{ name?: string; description?: string }>;
  trading_controls?: { paper_trading?: string; real_order?: string };
  skills?: SkillInfo[];
  llm_providers?: LlmProvidersSnapshot;
  market_refresh?: MarketRefreshConfig;
}

interface SkillInfo {
  name: string; label: string; description: string;
  authority: string; enabled: boolean; locked: boolean;
}

interface MarketRefreshConfig {
  page_refresh_seconds: number;
  warmup_seconds: number;
  manual_cooldown_seconds: number;
}

const REFRESH_PRESETS: Array<MarketRefreshConfig & { id: string; label: string }> = [
  { id: "relaxed", label: "宽松", page_refresh_seconds: 180, warmup_seconds: 900, manual_cooldown_seconds: 300 },
  { id: "standard", label: "标准", page_refresh_seconds: 60, warmup_seconds: 300, manual_cooldown_seconds: 120 },
  { id: "active", label: "积极", page_refresh_seconds: 30, warmup_seconds: 120, manual_cooldown_seconds: 60 },
];

function MarketRefreshCard({
  value, onSave, saving,
}: {
  value: MarketRefreshConfig;
  onSave: (next: MarketRefreshConfig) => Promise<void>;
  saving: boolean;
}) {
  const [local, setLocal] = useState<MarketRefreshConfig>(value);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    setLocal(value);
    setDirty(false);
  }, [value]);

  const setField = (key: keyof MarketRefreshConfig, raw: string) => {
    const parsed = Number(raw);
    setLocal((prev) => ({ ...prev, [key]: Number.isFinite(parsed) ? parsed : prev[key] }));
    setDirty(true);
  };

  return (
    <SectionCard
      title="刷新频率"
      description="页面刷新只打本机接口。行情预热会打上游全市场快照。同股补拉冷却限制手动和 AI 的 refresh_market_data。拉长间隔不会修好东财历史接口掐线。"
    >
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {REFRESH_PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className="ghost"
            onClick={() => {
              setLocal({
                page_refresh_seconds: preset.page_refresh_seconds,
                warmup_seconds: preset.warmup_seconds,
                manual_cooldown_seconds: preset.manual_cooldown_seconds,
              });
              setDirty(true);
            }}
          >
            {preset.label}
          </button>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
        {([
          ["页面刷新 (秒)", "page_refresh_seconds", "30–600，本机页面轮询"],
          ["行情预热 (秒)", "warmup_seconds", "120–3600，全市场快照"],
          ["同股补拉冷却 (秒)", "manual_cooldown_seconds", "30–1800，同一只股票"],
        ] as const).map(([label, key, hint]) => (
          <label key={key} className="page-stack" style={{ gap: 4 }}>
            <span style={{ fontSize: 12 }}>{label}</span>
            <input
              type="number"
              value={local[key]}
              onChange={(e) => setField(key, e.target.value)}
              style={{
                width: "100%", height: 32, border: "1px solid var(--line)", borderRadius: 7,
                background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 13,
              }}
            />
            <span className="muted" style={{ fontSize: 11 }}>{hint}</span>
          </label>
        ))}
      </div>
      {dirty ? (
        <div style={{ marginTop: 12 }}>
          <button className="primary" type="button" disabled={saving} onClick={() => void onSave(local)}>
            {saving ? "保存中…" : "保存刷新频率"}
          </button>
        </div>
      ) : null}
    </SectionCard>
  );
}

type SettingTab =
  | "appearance"
  | "workspace"
  | "channels"
  | "ai"
  | "ai-models"
  | "agent-skills"
  | "agent-memory"
  | "agent-mcp"
  | "data"
  | "intel"
  | "trade"
  | "risk"
  | "diag";

/** 右栏顶部说明（每个分区一句，降低「不知道改哪」的困惑） */
const TAB_META: Record<SettingTab, { title: string; desc: string }> = {
  appearance: { title: "外观", desc: "界面明暗与系统跟随。" },
  workspace: { title: "工作区", desc: "当前档案名称与本地数据目录。" },
  channels: { title: "通知通道", desc: "盯盘告警、邮件/Webhook 等外发渠道。" },
  ai: { title: "提供商", desc: "连接多家 OpenAI 兼容提供商。" },
  "ai-models": { title: "默认模型", desc: "从已连接提供商中选择 Copilot 默认模型与 Thinking 偏好。" },
  "agent-skills": { title: "技能", desc: "控制 AI 可委派的子代理技能开关。" },
  "agent-memory": { title: "记忆", desc: "AI 长期记住的用户事实，可纠偏或清空。" },
  "agent-mcp": { title: "MCP", desc: "无代码接入外部数据源与工具（保存后下一轮对话生效）。" },
  data: { title: "数据源", desc: "A 股 / 港股 / 美股的行情 provider 与实时分发状态。" },
  intel: { title: "情报", desc: "新闻搜索、舆情分析 provider 与 API Key。" },
  trade: { title: "交易", desc: "V1 交易护栏（只读）与纸上交易模式。" },
  risk: { title: "风控", desc: "单票上限、行业集中度、冷却期等可编辑策略规则。" },
  diag: { title: "运行诊断", desc: "运行时状态、对话记录与排障信息（只读）。" },
};

/* ---------- Helpers ---------- */

/** 设置卡原语（TeamClaw SettingCard/SectionHeader 形态）：
 * 头部 = 可选图标盒 + 标题/描述 + 右侧 mono 徽标；去掉了此前每卡雷同的齿轮图标。 */
function SectionCard({ title, subtitle, description, icon, children }: {
  title: string;
  subtitle?: string;
  description?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="setting-card">
      <div className="setting-card-head">
        {icon && <div className="setting-icon-box">{icon}</div>}
        <div className="setting-card-heading">
          <div className="setting-card-title">{title}</div>
          {description && <div className="setting-card-desc">{description}</div>}
        </div>
        {subtitle && <span className="setting-card-badge">{subtitle}</span>}
      </div>
      <div className="setting-card-body">{children}</div>
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

function SettingRow({ label, sub, children }: { label: React.ReactNode; sub?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="setting-row">
      <div className="setting-row-main">
        <div className="setting-row-label">{label}</div>
        {sub && <div className="setting-row-sub">{sub}</div>}
      </div>
      <div className="setting-row-ctl">{children}</div>
    </div>
  );
}

function AppearanceTab() {
  const { themeMode, setThemeMode } = useAppState();
  return (
    <div className="settings-stack">
      <SectionCard title="外观" description="界面明暗与系统跟随">
        <SettingRow label="主题模式" sub="跟随系统时随 macOS 自动切换">
          <div className="seg-ctl">
            {([["light", "白天"], ["dark", "夜晚"], ["system", "跟随系统"]] as const).map(([mode, label]) => (
              <button key={mode} type="button" className={themeMode === mode ? "on" : ""}
                onClick={() => setThemeMode(mode)}>{label}</button>
            ))}
          </div>
        </SettingRow>
      </SectionCard>
    </div>
  );
}

function WorkspaceTab() {
  const [ws, setWs] = useState<{ name?: string; data_dir?: string } | null>(null);
  useEffect(() => {
    let alive = true;
    const refresh = () => {
      apiGet<{ name?: string; data_dir?: string }>("/api/workspace")
        .then((w) => { if (alive) setWs(w); })
        .catch(() => { /* 旧后端无此接口 */ });
    };
    refresh();
    window.addEventListener("workspace-changed", refresh);
    return () => { alive = false; window.removeEventListener("workspace-changed", refresh); };
  }, []);
  return (
    <div className="settings-stack">
      <SectionCard title="工作区" description="档案名称与 SQLite 数据目录；切换入口在左栏底部">
        <SettingRow label="当前工作区">
          <span className="num" style={{ fontSize: 12 }}>{ws?.name ?? "-"}</span>
        </SettingRow>
        <SettingRow label="数据目录">
          <span className="num" style={{ fontSize: 11, color: "var(--muted)", wordBreak: "break-all", textAlign: "right" }}>{ws?.data_dir ?? "-"}</span>
        </SettingRow>
      </SectionCard>
    </div>
  );
}

/* ---------- AI 配置 ---------- */

function DefaultModelTab({
  settings, onRefresh,
}: {
  settings: SettingsData;
  onRefresh: () => Promise<void>;
}) {
  const snapshot = settings.llm_providers;
  const thinking = Boolean((settings.runtime_config as { thinking_enabled?: boolean } | undefined)?.thinking_enabled ?? true);

  if (!snapshot) {
    return <div className="llm-empty">无法加载提供商目录。</div>;
  }

  return (
    <ModelCatalogTab
      snapshot={snapshot}
      thinkingEnabled={thinking}
      runtimeConfig={settings.runtime_config ?? {}}
      onRefresh={onRefresh}
    />
  );
}

/* ---------- AI 记忆管理 ---------- */

function MemorySection() {
  const [memory, setMemory] = useState<MemoryStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [newFact, setNewFact] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setMemory(await fetchMemoryStatus());
    } catch {
      setMemory(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // 异步加载后 setState，非同步级联渲染（同 loadSessions 的规则误报）
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      await load();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "记忆操作失败");
    } finally {
      setBusy(false);
    }
  };

  const facts = memory?.data?.facts ?? [];
  // stub 模式（或 runtime 降级）没有记忆后端：隐藏区块而非报错
  if (!loading && !memory?.supported) return null;

  return (
    <SectionCard title="AI 记忆" subtitle="AI 记住的用户事实，可纠偏/清空">
      {loading ? (
        <span className="muted" style={{ fontSize: 12 }}>加载中…</span>
      ) : (
        <div className="page-stack" style={{ gap: 8 }}>
          {facts.length === 0 && (
            <span className="muted" style={{ fontSize: 12 }}>
              暂无记忆。AI 会在对话中自动记住你的偏好与事实（写入侧已开启），也可在下方手动添加。
            </span>
          )}
          {facts.map((fact) => (
            <div key={fact.id} className="check" style={{ alignItems: "center", gap: 8 }}>
              {editingId === fact.id ? (
                <>
                  <input
                    type="text" value={editText} onChange={(e) => setEditText(e.target.value)}
                    style={{ flex: 1, height: 30, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 12 }}
                  />
                  <button className="primary" disabled={busy || !editText.trim()} type="button" style={{ height: 28, fontSize: 12 }}
                    onClick={() => run(async () => { await updateMemoryFact(fact.id, { content: editText.trim() }); setEditingId(null); })}>
                    保存
                  </button>
                  <button className="ghost" type="button" style={{ height: 28, fontSize: 12 }} onClick={() => setEditingId(null)}>取消</button>
                </>
              ) : (
                <>
                  <div style={{ flex: 1 }}>
                    <span style={{ fontSize: 12 }}>{fact.content}</span>
                    <span className="muted" style={{ fontSize: 11, marginLeft: 8 }}>
                      {fact.category ?? "context"}
                      {fact.confidence != null && ` · ${(fact.confidence * 100).toFixed(0)}%`}
                    </span>
                  </div>
                  <button className="ghost" disabled={busy} type="button" style={{ height: 28, fontSize: 12 }}
                    onClick={() => { setEditingId(fact.id); setEditText(fact.content); }}>
                    编辑
                  </button>
                  <button className="ghost" disabled={busy} type="button" style={{ height: 28, fontSize: 12, color: "var(--red)" }}
                    onClick={() => run(() => deleteMemoryFact(fact.id))}>
                    删除
                  </button>
                </>
              )}
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="text" placeholder="手动添加一条事实，如：我偏好低估值蓝筹，仓位不超过 3 成" value={newFact}
              onChange={(e) => setNewFact(e.target.value)}
              style={{ flex: 1, height: 32, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 12 }}
            />
            <button className="primary" disabled={busy || !newFact.trim()} type="button" style={{ height: 30, fontSize: 12 }}
              onClick={() => run(async () => { await createMemoryFact({ content: newFact.trim(), confidence: 0.9 }); setNewFact(""); })}>
              添加
            </button>
            {facts.length > 0 && (
              <button className="ghost" disabled={busy} type="button" style={{ height: 30, fontSize: 12, color: "var(--red)" }}
                onClick={() => { if (window.confirm(`确认清空全部 ${facts.length} 条记忆？此操作不可撤销。`)) run(() => clearMemory()); }}>
                清空全部
              </button>
            )}
          </div>
        </div>
      )}
    </SectionCard>
  );
}

/* ---------- MCP 服务器管理 ---------- */

const EMPTY_MCP_FORM = { name: "", type: "stdio" as McpServerConfig["type"], command: "", args: "", url: "", description: "" };

// 官方 MCP reference servers（包名可验证）。Wind/Choice 等商用终端如提供
// MCP 服务端，按其文档手动填 stdio 命令或远程 URL。
const MCP_PRESETS: Array<{ label: string; form: typeof EMPTY_MCP_FORM }> = [
  {
    label: "网页抓取 fetch",
    form: { name: "fetch", type: "stdio", command: "uvx", args: "mcp-server-fetch", url: "", description: "通用网页抓取（官方 reference server）" },
  },
  {
    label: "本地文件 filesystem",
    form: { name: "filesystem", type: "stdio", command: "npx", args: "-y @modelcontextprotocol/server-filesystem ~/Documents", url: "", description: "读取本地目录（官方 reference server，注意目录授权范围）" },
  },
];

function McpSection() {
  const [servers, setServers] = useState<Record<string, McpServerConfig> | null>(null);
  const [supported, setSupported] = useState(true);
  const [busy, setBusy] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(EMPTY_MCP_FORM);

  const load = useCallback(async () => {
    try {
      const cfg = await fetchMcpConfig();
      setSupported(cfg.supported !== false);
      setServers(cfg.mcp_servers ?? {});
    } catch {
      setServers({});
    }
  }, []);

  // 异步加载后 setState，非同步级联渲染（同 loadSessions 的规则误报）
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const save = async (next: Record<string, McpServerConfig>) => {
    setBusy(true);
    try {
      const result = await updateMcpConfig(next);
      setServers(result.mcp_servers ?? next);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "MCP 配置保存失败");
      await load();
    } finally {
      setBusy(false);
    }
  };

  const handleAdd = () => {
    const name = form.name.trim();
    if (!name) return;
    const server: McpServerConfig = {
      enabled: true,
      type: form.type,
      description: form.description.trim(),
    };
    if (form.type === "stdio") {
      server.command = form.command.trim();
      server.args = form.args.trim() ? form.args.trim().split(/\s+/) : [];
    } else {
      server.url = form.url.trim();
    }
    setShowAdd(false);
    setForm(EMPTY_MCP_FORM);
    save({ ...(servers ?? {}), [name]: server });
  };

  if (!supported || servers === null) return null;
  const names = Object.keys(servers);

  return (
    <SectionCard title="MCP 服务器" subtitle="无代码接入外部数据源/工具（保存后下一轮对话生效）">
      <div className="page-stack" style={{ gap: 8 }}>
        {names.length === 0 && (
          <span className="muted" style={{ fontSize: 12 }}>
            未配置 MCP 服务器。可接入行情终端、内部数据库、文件系统等 MCP 生态工具，AI 对话中即可调用。
          </span>
        )}
        {names.map((name) => {
          const s = servers[name];
          return (
            <div key={name} className="check" style={{ alignItems: "center", gap: 8 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{name}</span>
                  <span className="tag" style={{ fontSize: 10 }}>{s.type}</span>
                  {!s.enabled && <span className="tag" style={{ fontSize: 10, background: "var(--red-soft)", color: "var(--red)" }}>已停用</span>}
                </div>
                <span className="muted" style={{ fontSize: 11, fontFamily: "var(--mono)" }}>
                  {s.type === "stdio" ? `${s.command ?? ""} ${(s.args ?? []).join(" ")}`.trim() : s.url ?? ""}
                </span>
                {s.description && <span className="muted" style={{ fontSize: 11 }}> · {s.description}</span>}
              </div>
              <button className="ghost" disabled={busy} type="button" style={{ height: 28, fontSize: 12 }}
                onClick={() => save({ ...servers, [name]: { ...s, enabled: !s.enabled } })}>
                {s.enabled ? "停用" : "启用"}
              </button>
              <button className="ghost" disabled={busy} type="button" style={{ height: 28, fontSize: 12, color: "var(--red)" }}
                onClick={() => {
                  if (!window.confirm(`确认删除 MCP 服务器「${name}」？`)) return;
                  const next = { ...servers };
                  delete next[name];
                  save(next);
                }}>
                删除
              </button>
            </div>
          );
        })}
        {showAdd ? (
          <div className="card page-stack" style={{ padding: 12, gap: 8 }}>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <span className="muted" style={{ fontSize: 11 }}>预设：</span>
              {MCP_PRESETS.map((preset) => (
                <button key={preset.form.name} className="ghost" type="button" style={{ height: 26, fontSize: 11 }}
                  onClick={() => setForm({ ...preset.form })}>
                  {preset.label}
                </button>
              ))}
              <span className="muted" style={{ fontSize: 11 }}>· Wind/Choice 等按厂商 MCP 文档手动填</span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <input type="text" placeholder="名称，如 wind-mcp" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                style={{ flex: 1, height: 30, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 12 }} />
              <select value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value as McpServerConfig["type"] })}
                style={{ height: 30, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 6px", fontSize: 12 }}>
                <option value="stdio">stdio（本地命令）</option>
                <option value="sse">sse（远程 SSE）</option>
                <option value="http">http（远程 HTTP）</option>
              </select>
            </div>
            {form.type === "stdio" ? (
              <div style={{ display: "flex", gap: 8 }}>
                <input type="text" placeholder="命令，如 uvx" value={form.command}
                  onChange={(e) => setForm({ ...form, command: e.target.value })}
                  style={{ width: 140, height: 30, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 12 }} />
                <input type="text" placeholder="参数（空格分隔），如 mcp-server-fetch" value={form.args}
                  onChange={(e) => setForm({ ...form, args: e.target.value })}
                  style={{ flex: 1, height: 30, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 12 }} />
              </div>
            ) : (
              <input type="text" placeholder="URL，如 https://host/mcp/sse" value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                style={{ height: 30, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 12 }} />
            )}
            <input type="text" placeholder="描述（可选）" value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              style={{ height: 30, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 12 }} />
            <div style={{ display: "flex", gap: 8 }}>
              <button className="primary" type="button" style={{ height: 30, fontSize: 12 }}
                disabled={busy || !form.name.trim() || (form.type === "stdio" ? !form.command.trim() : !form.url.trim())}
                onClick={handleAdd}>
                添加并保存
              </button>
              <button className="ghost" type="button" style={{ height: 30, fontSize: 12 }} onClick={() => setShowAdd(false)}>取消</button>
            </div>
          </div>
        ) : (
          <div>
            <button className="ghost" disabled={busy} type="button" style={{ height: 30, fontSize: 12 }} onClick={() => setShowAdd(true)}>
              + 添加 MCP 服务器
            </button>
          </div>
        )}
      </div>
    </SectionCard>
  );
}

/** 技能启停（TeamClaw 单一属主）：写 PUT /api/settings/skills →
 * 后端落 extensions_config.json 并重建 runtime，响应回传最新视图。 */
function SkillsSection({ initial }: { initial: SkillInfo[] }) {
  const [skills, setSkills] = useState<SkillInfo[]>(initial);
  const [busy, setBusy] = useState<string | null>(null);
  // props 变化时在渲染期间重置（react.dev「adjusting state when props change」）
  const [prevInitial, setPrevInitial] = useState(initial);
  if (prevInitial !== initial) { setPrevInitial(initial); setSkills(initial); }

  const toggle = async (name: string, enabled: boolean) => {
    setBusy(name);
    // 乐观更新，失败回滚为响应/原值
    setSkills((prev) => prev.map((s) => (s.name === name ? { ...s, enabled } : s)));
    try {
      const res = await apiPut<{ skills: SkillInfo[] }>("/api/settings/skills", { name, enabled });
      if (Array.isArray(res.skills)) setSkills(res.skills);
    } catch (err) {
      setSkills((prev) => prev.map((s) => (s.name === name ? { ...s, enabled: !enabled } : s)));
      window.alert(err instanceof Error ? err.message : "切换技能失败");
    } finally { setBusy(null); }
  };

  if (skills.length === 0) return null;
  return (
    <SectionCard title="技能" subtitle={`${skills.filter((s) => s.enabled).length}/${skills.length} 启用`}
      description="控制 AI 可委派的子代理技能；开关即时生效并重建运行时">
      <div className="page-stack" style={{ gap: 6 }}>
        {skills.map((s) => (
          <div key={s.name} className="card" style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", opacity: s.locked ? 0.55 : 1 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>{s.label}</span>
                <span className="num muted" style={{ fontSize: 11 }}>{s.name}</span>
                <span className="tag" style={{ fontSize: 10 }}>{s.authority}</span>
                {s.locked && <span className="tag" style={{ fontSize: 10 }}>锁定</span>}
              </div>
              {s.description && (
                <div className="muted" style={{ fontSize: 11, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.description}</div>
              )}
            </div>
            <ToggleSwitch
              checked={s.enabled}
              disabled={s.locked || busy === s.name}
              title={s.locked ? "该技能已锁定" : undefined}
              onChange={(v) => void toggle(s.name, v)}
            />
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

/* ---------- 行情 / 情报数据源 ---------- */

function MarketDataTab({
  settings, dataSources, availableProviders, credentialSchema, onSaveDataSources, savingDataSources,
  marketRefresh, onSaveMarketRefresh, savingMarketRefresh,
}: {
  settings: SettingsData;
  dataSources: DataSourcesConfig;
  availableProviders: AvailableDataProvider[];
  credentialSchema: Record<string, ProviderCredentialField[]>;
  onSaveDataSources: (config: DataSourcesConfig) => Promise<void>;
  savingDataSources: boolean;
  marketRefresh: MarketRefreshConfig;
  onSaveMarketRefresh: (next: MarketRefreshConfig) => Promise<void>;
  savingMarketRefresh: boolean;
}) {
  const [localConfig, setLocalConfig] = useState<DataSourcesConfig>(dataSources);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setLocalConfig({
      ...dataSources,
      provider_credentials: dataSources.provider_credentials ?? {},
      provider_states: dataSources.provider_states ?? {},
    });
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

  const handleProviderToggle = (providerId: string, enabled: boolean) => {
    setLocalConfig((prev) => ({
      ...prev,
      provider_states: {
        ...(prev.provider_states ?? {}),
        [providerId]: { enabled },
      },
    }));
    setDirty(true);
  };

  const handleCredentialChange = (providerId: string, field: string, value: string) => {
    setLocalConfig((prev) => ({
      ...prev,
      provider_credentials: {
        ...(prev.provider_credentials ?? {}),
        [providerId]: {
          ...(prev.provider_credentials?.[providerId] ?? {}),
          [field]: value || null,
        },
      },
    }));
    setDirty(true);
  };

  const marketDefaults: Record<string, string> = { CN: "eastmoney", HK: "eastmoney", US: "yfinance" };
  const marketLabels: Record<string, string> = { CN: "A 股", HK: "港股", US: "美股" };
  const marketIcons: Record<string, string> = { CN: "🇨🇳", HK: "🇭🇰", US: "🇺🇸" };

  const usableForMarket = (market: string) =>
    availableProviders.filter((p) => p.markets.includes(market) && isMarketProviderUsable(p, localConfig, credentialSchema));

  return (
    <div className="settings-stack">
      <MarketRefreshCard value={marketRefresh} onSave={onSaveMarketRefresh} saving={savingMarketRefresh} />
      <SectionCard title="数据源目录" description="仅已激活且配置完整的数据源可用于行情；免费源只需开关，付费源需填写 API 凭证">
        <div className="page-stack" style={{ gap: 10 }}>
          {availableProviders.map((provider) => {
            const enabled = localConfig.provider_states?.[provider.id]?.enabled
              ?? provider.enabled_by_default
              ?? provider.free
              ?? false;
            const fields = credentialSchema[provider.id] ?? [];
            const credsReady = provider.free || providerCredentialsComplete(provider.id, credentialSchema, localConfig.provider_credentials);
            const usable = enabled && credsReady;
            return (
              <div key={provider.id} className="card" style={{ padding: 12, opacity: enabled ? 1 : 0.72 }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 8 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <strong style={{ fontSize: 13 }}>{provider.name}</strong>
                      {provider.free ? (
                        <span className="tag green" style={{ fontSize: 10 }}>免费</span>
                      ) : (
                        <span className="tag amber" style={{ fontSize: 10 }}>需 API</span>
                      )}
                      {enabled && !credsReady ? (
                        <span className="tag amber" style={{ fontSize: 10 }}>待配置凭证</span>
                      ) : null}
                      {usable ? (
                        <span className="tag green" style={{ fontSize: 10 }}>可用</span>
                      ) : null}
                    </div>
                    <div className="muted" style={{ fontSize: 11, marginTop: 4, lineHeight: 1.45 }}>
                      {provider.description}
                    </div>
                    <div className="muted" style={{ fontSize: 10, marginTop: 4 }}>
                      市场：{provider.markets.join(" / ")}
                      {provider.requirements ? ` · ${provider.requirements}` : ""}
                    </div>
                  </div>
                  <ToggleSwitch
                    checked={enabled}
                    onChange={(checked) => handleProviderToggle(provider.id, checked)}
                    title={`${provider.name} 激活开关`}
                  />
                </div>
                {enabled && fields.length > 0 ? (
                  <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10, marginTop: 4 }}>
                    {fields.map((field) => (
                      <label key={field.key} className="page-stack" style={{ gap: 4, marginBottom: 8 }}>
                        <span className="muted" style={{ fontSize: 11 }}>
                          {field.label}
                          {field.env ? ` · 环境变量 ${field.env}` : ""}
                        </span>
                        <input
                          type={field.secret ? "password" : "text"}
                          placeholder={field.secret ? "留空则沿用环境变量" : ""}
                          value={localConfig.provider_credentials?.[provider.id]?.[field.key] ?? ""}
                          onChange={(e) => handleCredentialChange(provider.id, field.key, e.target.value)}
                          style={{
                            width: "100%", height: 32, border: "1px solid var(--line)", borderRadius: 7,
                            background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 12,
                          }}
                        />
                      </label>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </SectionCard>

      <SectionCard title="按市场分配" description="下拉列表仅显示已激活且可用的数据源">
        <div className="page-stack" style={{ gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
            {["CN", "HK", "US"].map((market) => {
              const cfg = localConfig.providers?.[market] ?? { provider: marketDefaults[market] ?? "eastmoney" };
              const current = cfg.provider;
              const availForMarket = usableForMarket(market);
              const selectedUsable = availForMarket.some((p) => p.id === current);
              const displayValue = selectedUsable ? current : (availForMarket[0]?.id ?? current);
              return (
                <div key={market} className="card" style={{ padding: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                    <span style={{ fontSize: 18 }}>{marketIcons[market]}</span>
                    <strong style={{ fontSize: 14 }}>{marketLabels[market] ?? market}</strong>
                    <span style={{ fontSize: 11, color: "var(--muted)" }}>{market}</span>
                  </div>
                  {availForMarket.length === 0 ? (
                    <div className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>
                      暂无可用数据源，请先在上方激活并配置至少一个支持 {marketLabels[market]} 的数据源。
                    </div>
                  ) : (
                    <>
                      <select
                        value={displayValue}
                        onChange={(e) => handleProviderChange(market, e.target.value)}
                        style={{ width: "100%", height: 34, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 6px", fontSize: 13 }}
                      >
                        {availForMarket.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}{p.free ? " · 免费" : ""}
                          </option>
                        ))}
                      </select>
                      <div className="muted" style={{ fontSize: 11, marginTop: 6, lineHeight: 1.4 }}>
                        {availForMarket.find((p) => p.id === displayValue)?.description ?? ""}
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
          {dirty && (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button className="primary" disabled={savingDataSources}
                onClick={() => void onSaveDataSources(localConfig)} type="button">
                {savingDataSources ? "保存中…" : "保存行情配置"}
              </button>
            </div>
          )}
        </div>
      </SectionCard>

      <SectionCard title="Provider 运行状态" description="当前生效 provider 与各能力分发（只读）">
        {settings.data_provider ? (() => {
          const dp = settings.data_provider!;
          const caps = (dp.capabilities as Record<string, { capability?: string; active_provider?: string; degraded?: boolean; degraded_reason?: string | null; coverage?: string }> | undefined) ?? {};
          return (
            <div className="page-stack" style={{ gap: 10 }}>
              <div className="barline" style={{ padding: "6px 0" }}>
                <span className="muted" style={{ fontSize: 12 }}>主 Provider</span><span /><span className="num">{String(dp.active_provider ?? "-")}</span>
              </div>
              <div className="barline" style={{ padding: "6px 0" }}>
                <span className="muted" style={{ fontSize: 12 }}>Fallback</span><span /><span className="num">{String(dp.fallback_provider ?? "-")}</span>
              </div>
              {dp.degraded_reason ? (
                <div className="muted" style={{ fontSize: 11, lineHeight: 1.5, padding: "4px 0" }}>
                  ⚠️ {String(dp.degraded_reason)}
                </div>
              ) : null}
              <div style={{ fontSize: 12, fontWeight: 600, marginTop: 4 }}>能力分发</div>
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
                        {coverage ? `覆盖: ${coverage}` : ""}
                        {degraded && cap?.degraded_reason ? <><br />{cap.degraded_reason}</> : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })() : (
          <div className="muted" style={{ padding: 8 }}>暂无 Provider 状态</div>
        )}
      </SectionCard>
    </div>
  );
}

function IntelTab({
  intelSources, availableIntelProviders, availableSentimentProviders, onSaveIntelSources, savingIntelSources,
}: {
  intelSources: IntelSourcesConfig;
  availableIntelProviders: AvailableIntelProvider[];
  availableSentimentProviders: AvailableIntelProvider[];
  onSaveIntelSources: (config: IntelSourcesConfig) => Promise<void>;
  savingIntelSources: boolean;
}) {
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

  const handleIntelEnabledChange = (key: string, enabled: boolean) => {
    setLocalIntel((prev) => ({
      ...prev,
      providers: {
        ...prev.providers,
        [key]: { ...prev.providers[key], enabled },
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

  const newsCfg = localIntel.providers?.news_search ?? { provider: "eastmoney", enabled: true, api_key: null };
  const sentimentCfg = localIntel.providers?.social_sentiment ?? { provider: "none", enabled: false, api_key: null };
  const newsEnabled = newsCfg.enabled !== false;

  return (
    <div className="settings-stack">
      <SectionCard title="新闻搜索" description="仅已激活的数据源可用；免费源标注「免费」，无需 API Key">
        {availableIntelProviders.length === 0 ? (
          <div className="muted" style={{ padding: 8 }}>暂无可用数据源</div>
        ) : (
          <div className="page-stack" style={{ gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <span className="muted" style={{ fontSize: 12 }}>启用新闻搜索</span>
              <ToggleSwitch
                checked={newsEnabled}
                onChange={(checked) => handleIntelEnabledChange("news_search", checked)}
                title="启用新闻搜索"
              />
            </div>
            {newsEnabled ? (
              <>
                <label className="page-stack" style={{ gap: 4 }}>
                  <span className="muted" style={{ fontSize: 12 }}>Provider</span>
                  <select
                    value={newsCfg.provider === "mock" ? "eastmoney" : newsCfg.provider}
                    onChange={(e) => handleIntelProviderChange("news_search", e.target.value)}
                    style={{ width: "100%", height: 34, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 6px", fontSize: 13 }}
                  >
                    {availableIntelProviders.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}{p.free ? " · 免费" : ""}
                      </option>
                    ))}
                  </select>
                </label>
                {availableIntelProviders.find((p) => p.id === newsCfg.provider)?.description && (
                  <div className="muted" style={{ fontSize: 11, lineHeight: 1.5 }}>
                    {availableIntelProviders.find((p) => p.id === newsCfg.provider)?.description}
                    {availableIntelProviders.find((p) => p.id === newsCfg.provider)?.free ? (
                      <span className="tag green" style={{ marginLeft: 8, fontSize: 10 }}>免费</span>
                    ) : null}
                  </div>
                )}
                {availableIntelProviders.find((p) => p.id === newsCfg.provider)?.api_key_required && (
                  <label className="page-stack" style={{ gap: 4 }}>
                    <span className="muted" style={{ fontSize: 12 }}>API Key</span>
                    <input
                      type="password"
                      placeholder="输入 API Key..."
                      value={newsCfg.api_key ?? ""}
                      onChange={(e) => handleIntelApiKeyChange("news_search", e.target.value)}
                      style={{ width: "100%", height: 32, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 10px", fontSize: 12 }}
                    />
                  </label>
                )}
              </>
            ) : (
              <div className="muted" style={{ fontSize: 11 }}>新闻搜索已关闭，Agent 将不会拉取个股新闻。</div>
            )}
          </div>
        )}
      </SectionCard>

      {availableSentimentProviders.length > 0 && (
        <SectionCard title="舆情分析" description="可选启用第三方舆情 API">
          <div className="page-stack" style={{ gap: 10 }}>
            <label className="page-stack" style={{ gap: 4 }}>
              <span className="muted" style={{ fontSize: 12 }}>Provider</span>
              <select
                value={sentimentCfg.provider}
                onChange={(e) => handleIntelProviderChange("social_sentiment", e.target.value)}
                style={{ width: "100%", height: 34, border: "1px solid var(--line)", borderRadius: 7, background: "var(--panel)", color: "var(--ink)", padding: "0 6px", fontSize: 13 }}
              >
                {availableSentimentProviders.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </label>
            {availableSentimentProviders.find((p) => p.id === sentimentCfg.provider)?.description && (
              <div className="muted" style={{ fontSize: 11, lineHeight: 1.5 }}>
                {availableSentimentProviders.find((p) => p.id === sentimentCfg.provider)?.description}
              </div>
            )}
          </div>
        </SectionCard>
      )}

      {intelDirty && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "0 0 8px" }}>
          <button className="primary" disabled={savingIntelSources}
            onClick={() => void onSaveIntelSources(localIntel)} type="button">
            {savingIntelSources ? "保存中…" : "保存情报源配置"}
          </button>
        </div>
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
    <SectionCard title="风控策略" description="单票上限、行业集中度、冷却期等规则；同时仅一条策略生效">
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

/* ---------- Agent：技能 / 记忆 / MCP ---------- */

function SkillsTab({ settings }: { settings: SettingsData }) {
  return (
    <div className="settings-stack">
      <SkillsSection initial={settings.skills ?? []} />
    </div>
  );
}

function MemoryTab() {
  return (
    <div className="settings-stack">
      <MemorySection />
    </div>
  );
}

function McpTab() {
  return (
    <div className="settings-stack">
      <McpSection />
    </div>
  );
}

function TradeOnlyTab({ settings }: { settings: SettingsData }) {
  const tc = settings.trading_controls;
  if (!tc) return <div className="llm-empty">暂无交易护栏配置。</div>;
  return (
    <div className="settings-stack">
      <SectionCard title="交易护栏" description="V1 研究模式安全锁定，本页只读">
        <SettingRow label="纸上交易" sub="模拟撮合，不触真钱">
          <span className="tag" style={{ color: "var(--green)" }}>{String(tc.paper_trading ?? "-")}</span>
        </SettingRow>
        <SettingRow label="真实下单" sub="执行代理锁定，本版本不可开启">
          <span className="tag" style={{ color: "var(--red)" }}>{String(tc.real_order ?? "blocked")}</span>
        </SettingRow>
      </SectionCard>
    </div>
  );
}

function RiskOnlyTab({
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
    <div className="settings-stack">
      <RiskTab
        riskPolicies={riskPolicies}
        showCreateForm={showCreateForm}
        setShowCreateForm={setShowCreateForm}
        editPolicyId={editPolicyId}
        setEditPolicyId={setEditPolicyId}
        savingPolicy={savingPolicy}
        submitCreatePolicy={submitCreatePolicy}
        submitEditPolicy={submitEditPolicy}
        activatePolicy={activatePolicy}
        deletePolicy={deletePolicy}
      />
    </div>
  );
}

function CollapsibleBlock({ label, defaultOpen = false, children }: {
  label: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button className="ghost" style={{ height: 26, fontSize: 12, marginBottom: open ? 8 : 0 }} type="button" onClick={() => setOpen((v) => !v)}>
        {open ? "收起" : "展开"} · {label}
      </button>
      {open ? children : null}
    </div>
  );
}

/* 诊断:只读观测区——Runtime 状态 / 运行记录 / 评测 / 回归 / Provider 事件 / 工具注册表 / 原始配置 */
function DiagTab({ settings, copilotRuns, runtimeMetrics, regressionCases, providerEvents }: {
  settings: SettingsData;
  copilotRuns: CopilotRunLog[];
  runtimeMetrics: RuntimeMetricSnapshot | null;
  regressionCases: RegressionCase[];
  providerEvents: ProviderEvent[];
}) {
  const ar = settings.agent_runtime;
  const [rawOpen, setRawOpen] = useState(false);
  const runtimeLabels: Record<string, string> = {
    mode: "运行模式", active_client: "客户端", model_name: "模型", available: "可用",
    degraded: "降级", degraded_reason: "降级原因", subagent_enabled: "子代理", plan_mode: "计划模式",
  };
  return (
    <div className="settings-stack">
      {ar && (
        <SectionCard title="Agent Runtime" description="完整运行时字段（排障用）">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 8 }}>
            {Object.entries(ar).map(([k, v]) => (
              <div key={k} className="card" style={{ padding: 10 }}>
                <h3 style={{ fontSize: 11, color: "var(--muted)", fontWeight: 500 }}>{runtimeLabels[k] ?? k.replace(/_/g, " ")}</h3>
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
      {/* Copilot Runs */}
      {copilotRuns.length > 0 && (
        <SectionCard title="Copilot 运行记录" description={`最近 ${Math.min(copilotRuns.length, 10)} 条对话运行`}>
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
        <SectionCard title="AI 质量指标" description="累计运行、成本与延迟统计">
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
        <SectionCard title="回归评测用例" description={`共 ${regressionCases.length} 个自动化用例`}>
          <CollapsibleBlock label="用例列表" defaultOpen={regressionCases.length <= 5}>
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
          </CollapsibleBlock>
        </SectionCard>
      )}
      {/* Tools */}
      {settings.tools && (
        <SectionCard title="工具注册表" description="Workbench 已注册 Agent 工具">
          <CollapsibleBlock label="工具列表">
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
          </CollapsibleBlock>
        </SectionCard>
      )}
      {/* Provider Events */}
      {providerEvents.length > 0 && (
        <SectionCard title="Provider 调用事件" description={`最近 ${Math.min(providerEvents.length, 8)} 条市场数据请求`}>
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
      <SectionCard title="原始配置 JSON" description="settings 全量快照，仅供排障">
        <button className="ghost" style={{ height: 26, fontSize: 12 }} type="button" onClick={() => setRawOpen((v) => !v)}>
          {rawOpen ? "收起" : "展开"}
        </button>
        {rawOpen && <pre style={{ maxHeight: 360, overflow: "auto", fontSize: 11, marginTop: 8 }}>{JSON.stringify(settings, null, 2)}</pre>}
      </SectionCard>
    </div>
  );
}


/* ==================== MAIN ==================== */

type NavItem = { key: SettingTab; label: string };
type NavGroupDef = { group: string; items: NavItem[] };

/** 左导航分区（TeamClaw 式设置页：左侧分区列表 + 右侧内容 + 底部版本） */
const NAV_GROUPS: NavGroupDef[] = [
  { group: "工作台", items: [
    { key: "appearance", label: "外观" },
    { key: "workspace", label: "工作区" },
    { key: "channels", label: "通知通道" },
  ]},
  { group: "AI Copilot", items: [
    { key: "ai", label: "提供商" },
    { key: "ai-models", label: "默认模型" },
    { key: "agent-skills", label: "技能" },
    { key: "agent-memory", label: "记忆" },
    { key: "agent-mcp", label: "MCP" },
  ]},
  { group: "数据服务", items: [
    { key: "data", label: "数据源" },
    { key: "intel", label: "情报" },
  ]},
  { group: "交易合规", items: [
    { key: "trade", label: "交易" },
    { key: "risk", label: "风控" },
  ]},
  { group: "系统", items: [
    { key: "diag", label: "运行诊断" },
  ]},
];

const APP_VERSION = "0.1.0";
const SETTING_TAB_KEYS = new Set<string>(NAV_GROUPS.flatMap((g) => g.items.map((i) => i.key)));

function initialSettingTab(tab?: string): SettingTab {
  return tab && SETTING_TAB_KEYS.has(tab) ? (tab as SettingTab) : "appearance";
}

export default function Settings({ initialTab }: { initialTab?: string } = {}) {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [runtimeMetrics, setRuntimeMetrics] = useState<RuntimeMetricSnapshot | null>(null);
  const [providerEvents, setProviderEvents] = useState<ProviderEvent[]>([]);
  const [copilotRuns, setCopilotRuns] = useState<CopilotRunLog[]>([]);
  const [regressionCases, setRegressionCases] = useState<RegressionCase[]>([]);
  const [activeTab, setActiveTab] = useState<SettingTab>(() => initialSettingTab(initialTab));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [riskPolicies, setRiskPolicies] = useState<RiskPolicy[]>([]);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [editPolicyId, setEditPolicyId] = useState<string | null>(null);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [savingDataSources, setSavingDataSources] = useState(false);
  const [savingMarketRefresh, setSavingMarketRefresh] = useState(false);
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

  const submitMarketRefresh = async (config: MarketRefreshConfig) => {
    setSavingMarketRefresh(true);
    try {
      const saved = await apiPut<MarketRefreshConfig>("/api/settings/market-refresh", config);
      window.dispatchEvent(new CustomEvent("market-refresh-changed", { detail: saved }));
      await loadAll();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "保存刷新频率失败");
    } finally {
      setSavingMarketRefresh(false);
    }
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
      case "appearance": return <AppearanceTab />;
      case "workspace": return <WorkspaceTab />;
      case "channels": return <ChannelsTab />;
      case "ai": return settings.llm_providers ? (
        <ModelProvidersTab
          snapshot={settings.llm_providers}
          onRefresh={loadAll}
          onAfterConnect={() => setActiveTab("ai-models")}
        />
      ) : (
        <div className="llm-empty">无法加载提供商目录。</div>
      );
      case "ai-models": return <DefaultModelTab settings={settings} onRefresh={loadAll} />;
      case "agent-skills": return <SkillsTab settings={settings} />;
      case "agent-memory": return <MemoryTab />;
      case "agent-mcp": return <McpTab />;
      case "data": return (
        <MarketDataTab
          settings={settings}
          dataSources={settings.data_sources ?? { providers: { CN: { provider: "eastmoney" }, HK: { provider: "eastmoney" }, US: { provider: "yfinance" } }, provider_credentials: {}, provider_states: {} }}
          availableProviders={settings.available_data_providers ?? []}
          credentialSchema={settings.provider_credential_schema ?? {}}
          onSaveDataSources={submitDataSources}
          savingDataSources={savingDataSources}
          marketRefresh={settings.market_refresh ?? { page_refresh_seconds: 60, warmup_seconds: 300, manual_cooldown_seconds: 120 }}
          onSaveMarketRefresh={submitMarketRefresh}
          savingMarketRefresh={savingMarketRefresh}
        />
      );
      case "intel": return (
        <IntelTab
          intelSources={settings.intel_sources ?? { providers: {} }}
          availableIntelProviders={settings.available_intel_providers ?? []}
          availableSentimentProviders={settings.available_sentiment_providers ?? []}
          onSaveIntelSources={submitIntelSources}
          savingIntelSources={savingIntelSources}
        />
      );
      case "trade": return <TradeOnlyTab settings={settings} />;
      case "risk": return (
        <RiskOnlyTab
          riskPolicies={riskPolicies}
          showCreateForm={showCreateForm}
          setShowCreateForm={setShowCreateForm}
          editPolicyId={editPolicyId}
          setEditPolicyId={setEditPolicyId}
          savingPolicy={savingPolicy}
          submitCreatePolicy={submitCreatePolicy}
          submitEditPolicy={submitEditPolicy}
          activatePolicy={activatePolicy}
          deletePolicy={deletePolicy}
        />
      );
      case "diag": return <DiagTab settings={settings} copilotRuns={copilotRuns} runtimeMetrics={runtimeMetrics} regressionCases={regressionCases} providerEvents={providerEvents} />;
    }
  };

  const runtimeOk = !!settings?.agent_runtime?.available;

  return (
    <div className="settings-layout">
      {/* 左导航：分区 + 底部版本（TeamClaw 式） */}
      <nav className="settings-nav">
        {NAV_GROUPS.map((g) => (
          <div key={g.group}>
            <div className="settings-nav-group">{g.group}</div>
            {g.items.map((item) => (
              <button
                key={item.key}
                className={`settings-nav-item${activeTab === item.key ? " active" : ""}`}
                onClick={() => setActiveTab(item.key)}
                type="button"
              >
                {item.label}
              </button>
            ))}
          </div>
        ))}
        <div className="settings-nav-gap" />
        <div className="settings-nav-foot">
          <span className={`settings-runtime-dot${runtimeOk ? " ok" : ""}`} />
          <span>{runtimeOk ? "服务运行中" : "服务未连接"}</span>
        </div>
        <div className="settings-nav-foot">
          <span>Stock Agent v{APP_VERSION}</span>
          <button
            className="settings-check-update"
            type="button"
            onClick={() => window.alert("自动更新随桌面打包（阶段 3）提供")}
          >检查更新</button>
        </div>
      </nav>

      {/* 右内容区：分区标题 + 内容（模态每次打开都重新挂载并全量加载，无需刷新按钮） */}
      <div className="settings-content">
        <div className="settings-content-head">
          <div className="settings-content-head-text">
            <span className="settings-content-title">{TAB_META[activeTab].title}</span>
            <p className="settings-content-desc">{TAB_META[activeTab].desc}</p>
          </div>
        </div>
        <div className="settings-content-body">
          {loading && <div className="page-stack"><PanelSkeleton /><KpiSkeleton count={3} /></div>}
          {!loading && error && <ErrorMessage message={error} />}
          {!loading && !error && settings && <div className="fade-in">{renderTab()}</div>}
        </div>
      </div>
    </div>
  );
}
