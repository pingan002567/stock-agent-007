import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiDelete } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, TableSkeleton, PanelSkeleton } from "@/components/ui/Loading";
import { RefreshButton } from "@/components/ui/RefreshButton";
import { useAppState } from "@/hooks/useAppState";

interface Strategy {
  strategy_id: string; name: string; description?: string; strategy_type?: string;
  enabled?: boolean; risk_level?: string; tags?: string[];
}
interface BacktestRun {
  run_id: string; strategy_id?: string; status?: string;
  metrics?: Record<string, unknown>; signals?: unknown[]; risk_summary?: unknown;
  candidate_actions?: unknown[]; created_at?: string;
}

export default function Strategies() {
  const { appDataCache, globalLoading } = useAppState();
  const [items, setItems] = useState<Strategy[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [latestBacktest, setLatestBacktest] = useState<BacktestRun | null>(null);
  const [backtestDetail, setBacktestDetail] = useState<BacktestRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [backtestBusy] = useState(false);
  const [addingStrategy, setAddingStrategy] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("sector_watch");
  const [newRisk, setNewRisk] = useState("medium");
  const [newUniverse, setNewUniverse] = useState("AAPL, HK00700");
  const [newParams, setNewParams] = useState('{"lookback_days": 14, "momentum_threshold_pct": 2, "sector_limit_pct": 35}');

  // Populate from global cache once initial load completes
  useEffect(() => {
    if (globalLoading) return;
    const cache = appDataCache.current;
    if (cache.strategies !== undefined) {
      setItems((cache.strategies as { items: Strategy[] })?.items ?? []); // eslint-disable-line react-hooks/set-state-in-effect
      setLoading(false);
    }
  }, [globalLoading, appDataCache]);

  const loadAll = useCallback(async () => {
    setLoading(true); setError(null);
    try { const response = await apiGet<{ items: Strategy[] }>("/api/strategies"); setItems(response.items); }
    catch (err) { setError(err instanceof Error ? err.message : "加载策略失败"); } finally { setLoading(false); }
  }, []);

  const handleSelect = async (id: string) => {
    setSelectedId(id);
    setBacktests([]);
    setLatestBacktest(null);
    setBacktestDetail(null);
    try {
      const [bt, lb] = await Promise.all([
        apiGet<{ items: BacktestRun[] }>(`/api/strategies/${encodeURIComponent(id)}/backtests`).then((r) => r.items).catch(() => []),
        apiGet<{ run_id: string }>(`/api/strategies/${encodeURIComponent(id)}/backtests/latest`).catch(() => null),
      ]);
      setBacktests(bt);
      if (lb) { const detail = await apiGet<BacktestRun>(`/api/backtests/${lb.run_id}`).catch(() => null); setLatestBacktest(detail); }
    } catch { /* ignore */ }
  };

  const handleRunBacktest = async (id: string) => {
    setRunningId(id);
    try {
      const result = await apiPost<BacktestRun>(`/api/strategies/${encodeURIComponent(id)}/backtest`, {});
      if (selectedId === id) { setLatestBacktest(result); setBacktestDetail(result); }
    } catch (err) { setError(err instanceof Error ? err.message : "回测失败"); } finally { setRunningId(null); }
  };

  const handleAddStrategy = async () => {
    if (addingStrategy) return;
    setAddingStrategy(true);
    try {
      await apiPost("/api/strategies", {
        name: newName, strategy_type: newType, risk_level: newRisk,
        universe: newUniverse.split(",").map((s) => s.trim()), parameters: JSON.parse(newParams),
      });
      await loadAll();
    } catch (err) { setError(err instanceof Error ? err.message : "新增策略失败"); } finally { setAddingStrategy(false); }
  };

  const handleDeleteStrategy = async (id: string) => {
    if (!confirm("确定要删除这个策略吗？")) return;
    try {
      await apiDelete(`/api/strategies/${encodeURIComponent(id)}`);
      if (selectedId === id) {
        setSelectedId(null);
        setBacktests([]);
        setLatestBacktest(null);
        setBacktestDetail(null);
      }
      await loadAll();
    } catch (err) { setError(err instanceof Error ? err.message : "删除策略失败"); }
  };

  const handleLoadLatestBacktest = async () => {};

  const selected = items.find((s) => s.strategy_id === selectedId);

  const enabledCount = items.filter(s => s.enabled).length;

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        <div className="market-hero">
          <div className="market-hero-header">
            <div className="market-title">
              <h1>策略中心</h1>
              <p>管理投资策略，运行回测，分析历史表现。</p>
            </div>
            <div className="hero-actions">
              <RefreshButton refreshing={loading} onClick={() => void loadAll()} />
              <button onClick={() => void handleAddStrategy()} disabled={addingStrategy} type="button">
                {addingStrategy ? "添加中…" : "新增策略"}
              </button>
            </div>
          </div>
          <div className="market-stats">
            <div className="market-stat">
              <span className="market-stat-label">总策略</span>
              <span className="market-stat-value">{items.length}</span>
              <span className="market-stat-change neutral">全部策略</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">启用中</span>
              <span className="market-stat-value up">{enabledCount}</span>
              <span className="market-stat-change up">
                ↑ {items.length > 0 ? Math.round((enabledCount / items.length) * 100) : 0}%
              </span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">本月回测</span>
              <span className="market-stat-value">{backtests.length}</span>
              <span className="market-stat-change neutral">次</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">最近回测</span>
              <span className="market-stat-value">{latestBacktest ? "有" : "无"}</span>
              <span className="market-stat-change neutral">{latestBacktest?.status ?? "-"}</span>
            </div>
          </div>
        </div>

        <div className="kpi-grid">
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">总策略</span>
              <div className="kpi-icon blue">📊</div>
            </div>
            <div className="kpi-value">{items.length}</div>
            <div className="kpi-change neutral">全部策略</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">启用中</span>
              <div className="kpi-icon green">✅</div>
            </div>
            <div className="kpi-value" style={{ color: "var(--green)" }}>{enabledCount}</div>
            <div className="kpi-change up">{items.length > 0 ? Math.round((enabledCount / items.length) * 100) : 0}% 启用率</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">本月回测</span>
              <div className="kpi-icon amber">🔄</div>
            </div>
            <div className="kpi-value">{backtests.length}</div>
            <div className="kpi-change neutral">次</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">风险等级</span>
              <div className="kpi-icon" style={{ background: "rgba(139, 92, 246, 0.12)", color: "#8b5cf6" }}>⚡</div>
            </div>
            <div className="kpi-value">{selected?.risk_level ?? "-"}</div>
            <div className="kpi-change neutral">当前策略</div>
          </div>
        </div>

        <div className="two-col">
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                  <path d="M2 17l10 5 10-5"/>
                  <path d="M2 12l10 5 10-5"/>
                </svg>
                策略列表
                <span className="panel-badge">{items.length} 条</span>
              </div>
            </div>
            <div className="panel-body">
              {items.length === 0 ? (
                <div className="muted">暂无策略</div>
              ) : items.map((s) => (
                <div
                  key={s.strategy_id}
                  className="intel-item"
                  style={selectedId === s.strategy_id ? { background: "var(--hover-row)", borderLeft: "3px solid var(--blue)" } : {}}
                  onClick={() => void handleSelect(s.strategy_id)}
                >
                  <div className="intel-dot" style={{ background: s.enabled ? "var(--green)" : "var(--muted)" }} />
                  <div className="intel-content">
                    <div className="intel-title">{s.name}</div>
                    <div className="intel-desc">
                      {s.strategy_type ?? "-"} · {s.risk_level ?? "medium"} 风险 · {s.enabled ? "已启用" : "已禁用"}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 4 }}>
                    <button
                      className="small"
                      disabled={runningId === s.strategy_id}
                      onClick={(e) => { e.stopPropagation(); void handleRunBacktest(s.strategy_id); }}
                      type="button"
                    >
                      {runningId === s.strategy_id ? "回测中…" : "回测"}
                    </button>
                    <button
                      className="small"
                      style={{ color: "var(--red)" }}
                      onClick={(e) => { e.stopPropagation(); void handleDeleteStrategy(s.strategy_id); }}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="12" y1="5" x2="12" y2="19"/>
                    <line x1="5" y1="12" x2="19" y2="12"/>
                  </svg>
                  新增策略
                </div>
              </div>
              <div className="panel-body">
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div>
                    <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>策略名称</div>
                    <input
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      placeholder="输入策略名称"
                      style={{ width: "100%", height: 36, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 13 }}
                    />
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>策略类型</div>
                    <select
                      value={newType}
                      onChange={(e) => setNewType(e.target.value)}
                      style={{ width: "100%", height: 36, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 13 }}
                    >
                      <option value="concentration_control">集中度控制</option>
                      <option value="price_momentum">价格动量</option>
                      <option value="sector_watch">板块监控</option>
                    </select>
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>风险等级</div>
                    <select
                      value={newRisk}
                      onChange={(e) => setNewRisk(e.target.value)}
                      style={{ width: "100%", height: 36, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 13 }}
                    >
                      <option value="low">低风险</option>
                      <option value="medium">中风险</option>
                      <option value="high">高风险</option>
                    </select>
                  </div>
                  <button
                    className="primary"
                    onClick={() => void handleAddStrategy()}
                    disabled={addingStrategy || !newName.trim()}
                    type="button"
                    style={{ width: "100%", height: 40 }}
                  >
                    {addingStrategy ? "添加中…" : "新增策略"}
                  </button>
                </div>
              </div>
            </div>
            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                  </svg>
                  策略详情
                </div>
              </div>
              <div className="panel-body">
                {selected ? (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12 }}>
                    <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>名称</div>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{selected.name}</div>
                    </div>
                    <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>类型</div>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{selected.strategy_type ?? "-"}</div>
                    </div>
                    <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>风险等级</div>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{selected.risk_level ?? "medium"}</div>
                    </div>
                    <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>状态</div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: selected.enabled ? "var(--green)" : "var(--muted)" }}>
                        {selected.enabled ? "已启用" : "已禁用"}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="muted">点击左侧策略查看详情</div>
                )}
              </div>
            </div>

            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/>
                  </svg>
                  最近回测
                </div>
                {selected && (
                  <button
                    className="small primary"
                    disabled={runningId === selected.strategy_id}
                    onClick={() => void handleRunBacktest(selected.strategy_id)}
                    type="button"
                  >
                    {runningId === selected.strategy_id ? "回测中…" : "运行回测"}
                  </button>
                )}
              </div>
              <div className="panel-body">
                {latestBacktest ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12 }}>
                      <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                        <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>状态</div>
                        <div style={{ fontSize: 14, fontWeight: 600, color: latestBacktest.status === "completed" ? "var(--green)" : "var(--amber)" }}>
                          {latestBacktest.status ?? "-"}
                        </div>
                      </div>
                      <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                        <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>回测时间</div>
                        <div style={{ fontSize: 14, fontWeight: 600 }}>{latestBacktest.created_at?.slice(0, 16) ?? "-"}</div>
                      </div>
                    </div>
                    
                    {latestBacktest.metrics && (
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
                        {latestBacktest.metrics.total_return_pct !== undefined && (
                          <div style={{ padding: 10, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                            <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 4 }}>总收益率</div>
                            <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono)", color: latestBacktest.metrics.total_return_pct >= 0 ? "var(--green)" : "var(--red)" }}>
                              {latestBacktest.metrics.total_return_pct >= 0 ? "+" : ""}{latestBacktest.metrics.total_return_pct.toFixed(2)}%
                            </div>
                          </div>
                        )}
                        {latestBacktest.metrics.max_drawdown_pct !== undefined && (
                          <div style={{ padding: 10, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                            <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 4 }}>最大回撤</div>
                            <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--red)" }}>
                              -{latestBacktest.metrics.max_drawdown_pct.toFixed(2)}%
                            </div>
                          </div>
                        )}
                        {latestBacktest.metrics.sharpe_ratio !== undefined && (
                          <div style={{ padding: 10, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                            <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 4 }}>夏普比率</div>
                            <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono)" }}>
                              {latestBacktest.metrics.sharpe_ratio.toFixed(2)}
                            </div>
                          </div>
                        )}
                        {latestBacktest.metrics.win_rate !== undefined && (
                          <div style={{ padding: 10, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                            <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 4 }}>胜率</div>
                            <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono)" }}>
                              {latestBacktest.metrics.win_rate.toFixed(1)}%
                            </div>
                          </div>
                        )}
                        {latestBacktest.metrics.volatility_pct !== undefined && (
                          <div style={{ padding: 10, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                            <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 4 }}>波动率</div>
                            <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono)" }}>
                              {latestBacktest.metrics.volatility_pct.toFixed(2)}%
                            </div>
                          </div>
                        )}
                        {latestBacktest.metrics.sample_size !== undefined && (
                          <div style={{ padding: 10, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                            <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 4 }}>样本数</div>
                            <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono)" }}>
                              {latestBacktest.metrics.sample_size}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="muted">等待回测</div>
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
                  回测历史
                  <span className="panel-badge">{backtests.length} 次</span>
                </div>
              </div>
              <div className="panel-body">
                {backtests.length === 0 ? (
                  <div className="muted">暂无回测历史</div>
                ) : backtests.slice(0, 5).map((bt) => (
                  <div key={bt.run_id} className="intel-item">
                    <div className={`intel-dot ${bt.status === "completed" ? "success" : bt.status === "failed" ? "warning" : "info"}`} />
                    <div className="intel-content">
                      <div className="intel-title">{bt.run_id.slice(0, 12)}</div>
                      <div className="intel-desc">{bt.status ?? "-"}</div>
                    </div>
                    <div className="intel-time">{bt.created_at?.slice(0, 16) ?? ""}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}
