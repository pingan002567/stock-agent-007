import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, apiDelete } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, PanelSkeleton, KpiSkeleton, EmptyState } from "@/components/ui/Loading";
import { RefreshButton } from "@/components/ui/RefreshButton";
import { Pagination } from "@/components/ui/Pagination";
import { formatTimeAgo } from "@/utils/format";

interface MonitorEvent {
  event_id: string; title?: string; severity?: string; symbol?: string;
  rule_id?: string; rule_type?: string; triggered_at?: string; evidence?: Record<string, unknown>[];
  suggested_actions?: string[]; payload?: Record<string, unknown>;
}
interface MonitorRule {
  rule_id: string; symbol?: string; rule_type?: string; severity?: string;
  enabled?: boolean; threshold?: number | null; cooldown_seconds?: number;
  keyword?: string | null; title?: string | null; trigger_rule?: string | null;
  metadata?: Record<string, unknown>;
}
interface MonitorStatus {
  status?: string; interval_seconds?: number; last_checked_at?: string | null;
  last_matched_at?: string | null; last_error?: string | null;
}

const RULE_TYPE_OPTIONS = [
  { value: "single_position_weight_gt", label: "仓位超限" },
  { value: "price_change_pct_gt", label: "涨跌幅超限" },
  { value: "ma_crossover", label: "均线金叉/死叉" },
  { value: "volume_spike", label: "成交量异常" },
  { value: "sector_correlation", label: "板块联动" },
  { value: "combined_condition", label: "复合条件" },
  { value: "data_provider_degraded", label: "数据源降级" },
  { value: "intel_keyword_match", label: "情报关键词" },
];

const SEVERITY_COLORS: Record<string, string> = { high: "red", medium: "amber", low: "gray" };

function severityBadge(s: string | undefined) {
  const cls = SEVERITY_COLORS[s ?? ""] || "gray";
  return <span className={`tag ${cls}`}>{s ?? "info"}</span>;
}

function ruleTypeLabel(t: string | undefined) {
  return RULE_TYPE_OPTIONS.find((o) => o.value === t)?.label ?? t ?? "unknown";
}

export default function Monitor() {
  const [events, setEvents] = useState<MonitorEvent[]>([]);
  const [rules, setRules] = useState<MonitorRule[]>([]);
  const [status, setStatus] = useState<MonitorStatus | null>(null);
  const [evalBusy, setEvalBusy] = useState(false);
  const [evalResult, setEvalResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null);
  const [showAddRule, setShowAddRule] = useState(false);
  const [ruleForm, setRuleForm] = useState<Partial<MonitorRule>>({ rule_type: "single_position_weight_gt", severity: "medium", enabled: true, cooldown_seconds: 3600 });
  const [ruleSaving, setRuleSaving] = useState(false);
  const [ruleSaveError, setRuleSaveError] = useState<string | null>(null);
  const [hintDismissed, setHintDismissed] = useState(false);
  const [feedbackDone, setFeedbackDone] = useState<Record<string, boolean>>({});
  const sseRef = useRef<EventSource | null>(null);
  const [eventPage, setEventPage] = useState(1);
  const [eventTotal, setEventTotal] = useState(0);
  const eventPageSize = 5;

  const loadAll = useCallback(async (page: number = eventPage, silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [evResp, rl, st] = await Promise.all([
        apiGet<{ items: MonitorEvent[]; total: number }>(`/api/monitor/events?page=${page}&page_size=${eventPageSize}`).catch(() => ({ items: [], total: 0 })),
        apiGet<{ items: MonitorRule[] }>("/api/monitor/rules").then((r) => r.items).catch(() => []),
        apiGet<MonitorStatus>("/api/monitor/status").catch(() => null),
      ]);
      setEvents(evResp.items); setEventTotal(evResp.total); setRules(rl); setStatus(st);
    } catch (err) { setError(err instanceof Error ? err.message : "加载盯盘中心失败"); } finally { if (!silent) setLoading(false); }
  }, [eventPage, eventPageSize]);

  // Keep the SSE handler pointing at the latest loadAll (current page) without
  // re-subscribing the EventSource on every page change.
  const loadAllRef = useRef(loadAll);
  useEffect(() => { loadAllRef.current = loadAll; }, [loadAll]);

  // 页面挂载时拉一次数据；SSE 负责后续实时更新
  useEffect(() => { void loadAll(); // eslint-disable-line react-hooks/set-state-in-effect
  }, [loadAll]);

  useEffect(() => {
    const es = new EventSource("/api/monitor/stream");
    // The SSE payload is the whole SSEEvent: { type, payload: {...} }.
    // "status" carries the status object directly; "events" signals that the
    // event set changed — silently refetch the current page so pagination and
    // totals stay consistent (the stream pushes an unpaginated top-20).
    es.addEventListener("events", () => { void loadAllRef.current(undefined, true); });
    es.addEventListener("status", (msg) => {
      try { const d = JSON.parse(msg.data); if (d.payload) setStatus(d.payload as MonitorStatus); } catch { void 0; }
    });
    sseRef.current = es;
    return () => { es.close(); sseRef.current = null; };
  }, []);

  const handleFeedback = async (ev: MonitorEvent, wasUseful: boolean) => {
    if (!ev.rule_id) return;
    setFeedbackDone((prev) => ({ ...prev, [ev.event_id]: true }));
    try { await apiPost("/api/monitor/feedback", { rule_id: ev.rule_id, was_useful: wasUseful }); } catch { void 0; }
  };

  const handleStart = async () => { try { await apiPost("/api/monitor/start"); await loadAll(); } catch { void 0; } };
  const handlePause = async () => { try { await apiPost("/api/monitor/pause"); await loadAll(); } catch { void 0; } };
  const handleEval = async () => {
    setEvalBusy(true); setEvalResult(null);
    // force=true so a manual evaluation isn't silently swallowed by cooldown.
    try { const res = await apiPost<Record<string, unknown>>("/api/monitor/evaluate-once", { force: true }); setEvalResult(JSON.stringify(res, null, 2)); await loadAll(); }
    catch (err) { setEvalResult(err instanceof Error ? err.message : "评估失败"); } finally { setEvalBusy(false); }
  };

  const handleToggleRule = async (rule: MonitorRule) => {
    try {
      await apiPost("/api/monitor/rules", { ...rule, enabled: !rule.enabled });
      await loadAll();
    } catch { void 0; }
  };

  const handleDeleteRule = async (ruleId: string) => {
    try { await apiDelete(`/api/monitor/rules/${ruleId}`); await loadAll(); } catch { void 0; }
  };

  const handleAddRule = async () => {
    setRuleSaving(true); setRuleSaveError(null);
    try {
      await apiPost("/api/monitor/rules", ruleForm);
      setShowAddRule(false);
      setRuleForm({ rule_type: "single_position_weight_gt", severity: "medium", enabled: true, cooldown_seconds: 3600 });
      await loadAll();
    } catch (err) { setRuleSaveError(err instanceof Error ? err.message : "保存规则失败"); } finally { setRuleSaving(false); }
  };

  const highCount = events.filter((e) => e.severity === "high").length;
  const hasDiagnosis = !hintDismissed && highCount > 0;

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        <div className="market-hero">
          <div className="market-hero-header">
            <div className="market-title">
              <h1>AI 盯盘中心</h1>
              <p>实时监控市场动态，智能识别交易机会和风险预警。</p>
            </div>
            <div className="hero-actions">
              <button className="primary" disabled={evalBusy} onClick={() => void handleEval()} type="button">
                {evalBusy ? "评估中…" : "手动评估"}
              </button>
              <button onClick={() => void handleStart()} type="button">启动盯盘</button>
              <button onClick={() => void handlePause()} type="button">暂停盯盘</button>
              <RefreshButton refreshing={loading} onClick={() => void loadAll()} />
            </div>
          </div>
          <div className="market-stats">
            <div className="market-stat">
              <span className="market-stat-label">盯盘状态</span>
              <span className={`market-stat-value ${status?.status === "running" ? "up" : ""}`}>
                {status?.status === "running" ? "运行中" : "已暂停"}
              </span>
              <span className={`market-stat-change ${status?.status === "running" ? "up" : "neutral"}`}>
                {status?.status === "running" ? "● 正常运行" : "● 已暂停"}
              </span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">监控周期</span>
              <span className="market-stat-value">{status?.interval_seconds ?? "-"}s</span>
              <span className="market-stat-change neutral">每分钟检查</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">今日事件</span>
              <span className="market-stat-value">{events.length}</span>
              <span className="market-stat-change neutral">条事件</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">高风险</span>
              <span className={`market-stat-value ${highCount > 0 ? "down" : ""}`}>{highCount}</span>
              <span className={`market-stat-change ${highCount > 0 ? "down" : "neutral"}`}>
                {highCount > 0 ? "↓ 需要关注" : "● 无风险"}
              </span>
            </div>
          </div>
        </div>

        <div className="kpi-grid">
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">盯盘状态</span>
              <div className={`kpi-icon ${status?.status === "running" ? "green" : "amber"}`}>●</div>
            </div>
            <div className="kpi-value" style={{ color: status?.status === "running" ? "var(--green)" : "var(--amber)" }}>
              {status?.status === "running" ? "运行中" : "已暂停"}
            </div>
            <div className="kpi-change neutral">正常运行</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">监控周期</span>
              <div className="kpi-icon blue">⏱</div>
            </div>
            <div className="kpi-value">{status?.interval_seconds ?? "-"}s</div>
            <div className="kpi-change neutral">每分钟检查</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">今日事件</span>
              <div className="kpi-icon amber">🔔</div>
            </div>
            <div className="kpi-value">{events.length}</div>
            <div className="kpi-change neutral">条事件</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">高风险</span>
              <div className="kpi-icon red">⚠️</div>
            </div>
            <div className="kpi-value" style={{ color: highCount > 0 ? "var(--red)" : undefined }}>{highCount}</div>
            <div className={`kpi-change ${highCount > 0 ? "down" : "neutral"}`}>
              {highCount > 0 ? "需要关注" : "无风险"}
            </div>
          </div>
        </div>

        {hasDiagnosis && (
          <div className="ticket fade-in" style={{ borderLeft: "4px solid var(--red)", padding: "12px 16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>⚠ 发现 {highCount} 条高风险盯盘事件，建议检查相关持仓风险</span>
            <button className="small" onClick={() => setHintDismissed(true)} type="button">忽略</button>
          </div>
        )}

        <div className="two-col">
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                  <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                </svg>
                监控事件
                <span className="panel-badge">{eventTotal} 条</span>
              </div>
            </div>
            <div className="panel-body">
              {events.length === 0 ? (
                <div className="muted">暂无盯盘事件，触发手动评估或等待后台循环检测</div>
              ) : events.map((ev) => (
                <div key={ev.event_id} className="intel-item" onClick={() => setExpandedEvent(expandedEvent === ev.event_id ? null : ev.event_id)}>
                  <div className={`intel-dot ${ev.severity === "high" ? "warning" : ev.severity === "medium" ? "info" : "success"}`} />
                  <div className="intel-content">
                    <div className="intel-title">{ev.title ?? ev.event_id}</div>
                    <div className="intel-desc">
                      {ev.symbol ?? "全市场"} · {ruleTypeLabel(ev.rule_type)} · {formatTimeAgo(ev.triggered_at)}
                    </div>
                    {expandedEvent === ev.event_id && (
                      <div style={{ marginTop: 8 }} onClick={(e) => e.stopPropagation()}>
                        {ev.suggested_actions && ev.suggested_actions.length > 0 && (
                          <div style={{ marginBottom: 8 }}>
                            {ev.suggested_actions.map((a, i) => (
                              <span key={i} className="tag" style={{ marginRight: 4, fontSize: 10 }}>{a}</span>
                            ))}
                          </div>
                        )}
                        {ev.rule_id && (
                          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--muted)" }}>
                            {feedbackDone[ev.event_id] ? (
                              <span>✓ 已反馈，谢谢</span>
                            ) : (
                              <>
                                <span>这条预警有用吗？</span>
                                <button className="small" onClick={() => void handleFeedback(ev, true)} type="button">👍 有用</button>
                                <button className="small" onClick={() => void handleFeedback(ev, false)} type="button">👎 无用</button>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="intel-time">{formatTimeAgo(ev.triggered_at)}</div>
                </div>
              ))}
            </div>
            <Pagination
              total={eventTotal}
              pageSize={eventPageSize}
              current={eventPage}
              onChange={(page) => { setEventPage(page); void loadAll(page); }}
            />
          </div>

          <div>
            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                  </svg>
                  盯盘规则
                  <span className="panel-badge">{rules.length} 条</span>
                </div>
                <button className="small primary" onClick={() => setShowAddRule(true)} type="button">+ 添加规则</button>
              </div>
              <div className="panel-body">
                {rules.length === 0 && !showAddRule ? (
                  <div className="muted">暂无规则</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {rules.map((rule) => (
                      <div key={rule.rule_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600 }}>{ruleTypeLabel(rule.rule_type)}</div>
                          <div style={{ fontSize: 11, color: "var(--muted)" }}>
                            {rule.symbol ?? "全市场"} · {rule.threshold != null ? `阈值 ${rule.threshold}` : ""} {rule.keyword ? `关键词 ${rule.keyword}` : ""} {rule.cooldown_seconds ? `· ${rule.cooldown_seconds}s冷却` : ""}
                          </div>
                        </div>
                        <div style={{ display: "flex", gap: 8 }}>
                          <button className="small" onClick={() => void handleToggleRule(rule)} type="button">
                            {rule.enabled ? "暂停" : "启用"}
                          </button>
                          <button className="small" style={{ color: "var(--red)" }} onClick={() => void handleDeleteRule(rule.rule_id)} type="button">删除</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {showAddRule && (
                  <div style={{ marginTop: 12, padding: 16, background: "var(--bg-tertiary)", borderRadius: 8, display: "grid", gap: 8 }}>
                    <select value={ruleForm.rule_type ?? "single_position_weight_gt"} onChange={(e) => setRuleForm({ ...ruleForm, rule_type: e.target.value })}>
                      {RULE_TYPE_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                    </select>
                    <input placeholder="symbol（空=全市场）" value={ruleForm.symbol ?? ""} onChange={(e) => setRuleForm({ ...ruleForm, symbol: e.target.value })} />
                    {(ruleForm.rule_type === "single_position_weight_gt" || ruleForm.rule_type === "price_change_pct_gt") && (
                      <input type="number" placeholder="threshold" value={ruleForm.threshold ?? ""} onChange={(e) => setRuleForm({ ...ruleForm, threshold: e.target.value ? Number(e.target.value) : null })} />
                    )}
                    {ruleForm.rule_type === "intel_keyword_match" && (
                      <input placeholder="keyword" value={ruleForm.keyword ?? ""} onChange={(e) => setRuleForm({ ...ruleForm, keyword: e.target.value })} />
                    )}
                    <input type="number" placeholder="cooldown seconds" value={ruleForm.cooldown_seconds ?? 3600} onChange={(e) => setRuleForm({ ...ruleForm, cooldown_seconds: Number(e.target.value) })} />
                    <select value={ruleForm.severity ?? "medium"} onChange={(e) => setRuleForm({ ...ruleForm, severity: e.target.value })}>
                      <option value="high">high</option>
                      <option value="medium">medium</option>
                      <option value="low">low</option>
                    </select>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button className="primary small" disabled={ruleSaving} onClick={() => void handleAddRule()} type="button">{ruleSaving ? "保存中…" : "添加"}</button>
                      <button className="small" onClick={() => { setShowAddRule(false); setRuleSaveError(null); }} type="button">取消</button>
                    </div>
                    {ruleSaveError && <div style={{ color: "var(--red)", fontSize: 12 }}>{ruleSaveError}</div>}
                  </div>
                )}
              </div>
            </div>

            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polygon points="13,2 3,14 12,14 11,22 21,10 12,10"/>
                  </svg>
                  手动评估
                </div>
              </div>
              <div className="panel-body">
                <button className="primary" disabled={evalBusy} onClick={() => void handleEval()} type="button" style={{ width: "100%", marginBottom: 12 }}>
                  {evalBusy ? "评估中…" : "执行手动评估"}
                </button>
                {evalResult && (
                  <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8, fontSize: 12, color: "var(--muted)" }}>
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 11 }}>{evalResult}</pre>
                  </div>
                )}
                {status?.last_error && (
                  <div style={{ marginTop: 8, fontSize: 11, color: "var(--red)" }}>
                    上次错误: {status.last_error}
                  </div>
                )}
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12,6 12,12 16,14"/>
                  </svg>
                  后台循环
                </div>
              </div>
              <div className="panel-body">
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                  <div style={{ width: 8, height: 8, borderRadius: "50%", background: status?.status === "running" ? "var(--green)" : "var(--amber)", boxShadow: status?.status === "running" ? "0 0 8px rgba(16, 185, 129, 0.4)" : "none" }} />
                  <span style={{ fontSize: 13, fontWeight: 600, color: status?.status === "running" ? "var(--green)" : "var(--amber)" }}>
                    {status?.status === "running" ? "运行中" : "已暂停"}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>
                  {status?.last_checked_at && <div>上次检查: {status.last_checked_at.slice(5, 19)}</div>}
                  {status?.last_matched_at && <div>上次匹配: {status.last_matched_at.slice(5, 19)}</div>}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}
