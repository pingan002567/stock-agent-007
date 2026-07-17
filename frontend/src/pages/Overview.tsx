import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/api/client";
import { useAppState } from "@/hooks/useAppState";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, OverviewSkeleton } from "@/components/ui/Loading";
import { inferMarket, marketMoney, pct, changeCls } from "@/utils/market";

interface PortfolioSummary {
  total_value?: number; positions?: number; max_weight_pct?: number; cash_pct?: number;
}
interface WatchItem { symbol: string; name?: string; group?: string; monitored?: boolean }
interface HoldingSummary { symbol: string; name?: string; market_value?: number; weight_pct?: number; market?: string }
interface TaskItem { task_id: string; title: string; status?: string; created_at?: string }
interface MonitorEvent { event_id: string; title?: string; severity?: string; symbol?: string; triggered_at?: string }
interface OverviewData {
  portfolio_summary?: PortfolioSummary;
  watchlist?: WatchItem[]; holdings?: HoldingSummary[];
  tasks?: TaskItem[]; monitor_summary?: { event_count?: number; high_count?: number };
  market?: string;
}
interface IndexInfo { code?: string; name?: string; last?: number; change_pct?: number }

export default function Overview() {
  const { appDataCache, globalLoading } = useAppState();
  const [data, setData] = useState<OverviewData | null>(null);
  const [events, setEvents] = useState<MonitorEvent[]>([]);
  const [indices, setIndices] = useState<IndexInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  // Populate from global cache once initial load completes
  useEffect(() => {
    if (globalLoading) return;
    const cache = appDataCache.current;
    if (cache.overview) {
      setData(cache.overview as OverviewData);
      setEvents((cache.monitorEvents as { items: MonitorEvent[] })?.items ?? []);
      setIndices(((cache.marketReview as { indices?: IndexInfo[] })?.indices ?? []));
      setLoading(false);
    }
  }, [globalLoading, appDataCache]);

  const loadAll = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [ov, ev, mr] = await Promise.all([
        apiGet<OverviewData>("/api/overview"),
        apiGet<{ items: MonitorEvent[] }>("/api/monitor/events").catch(() => ({ items: [] })),
        apiGet<{ indices?: IndexInfo[] }>("/api/market/review").catch(() => ({ indices: [] })),
      ]);
      setData(ov); setEvents(ev.items ?? []); setIndices(mr.indices ?? []);
    } catch (err) { setError(err instanceof Error ? err.message : "加载总览失败"); } finally { setLoading(false); }
  }, []);

  const handleRiskScan = async () => { setScanning(true); try { await apiPost("/api/holdings/risk"); await loadAll(); } catch { /* ignore */ } finally { setScanning(false); } };

  return (
    <PageContainer>
      {loading && !data ? <OverviewSkeleton /> : null}
      {!loading && error && !data ? <ErrorMessage message={error} /> : null}
      {data ? (
        <div className="page-stack fade-in">
          <section className="page-hero">
            <div className="hero-content">
              <h2>投资组合概览</h2>
              <p>您的投资组合今日表现良好，建议关注持仓集中度和风险敞口。</p>
              <div className="hero-stats">
                <div className="hero-stat">
                  <span className="hero-stat-label">总资产</span>
                  <span className="hero-stat-value">{marketMoney(data.portfolio_summary?.total_value, "CN")}</span>
                  <span className="hero-stat-change neutral">{data.portfolio_summary?.positions ?? 0} 只持仓</span>
                </div>
                <div className="hero-stat">
                  <span className="hero-stat-label">持仓数量</span>
                  <span className="hero-stat-value">{data.portfolio_summary?.positions ?? 0}</span>
                  <span className="hero-stat-change neutral">分散投资</span>
                </div>
                <div className="hero-stat">
                  <span className="hero-stat-label">最大权重</span>
                  <span className="hero-stat-value">{pct(data.portfolio_summary?.max_weight_pct)}</span>
                  <span className="hero-stat-change neutral">现金 {pct(data.portfolio_summary?.cash_pct)}</span>
                </div>
              </div>
            </div>
            <div className="hero-actions">
              <button className="primary" onClick={() => void loadAll()} disabled={loading} type="button">刷新全部</button>
              <button onClick={() => void handleRiskScan()} disabled={scanning} type="button">{scanning ? "扫描中…" : "持仓风险扫描"}</button>
            </div>
          </section>

          {/* 指数条（原市场页并入：每股一列 mono 点位+涨跌） */}
          {indices.length > 0 && (
            <div className="panel">
              <div className="panel-body" style={{ display: "flex", padding: "10px 4px" }}>
                {indices.slice(0, 5).map((idx, i) => (
                  <div key={idx.code ?? idx.name ?? i} style={{ flex: 1, padding: "0 12px", borderLeft: i > 0 ? "1px solid var(--line-soft, var(--line))" : "none" }}>
                    <div className="muted" style={{ fontSize: 11 }}>{idx.name ?? idx.code}</div>
                    <div className="num" style={{ fontSize: 14, fontWeight: 600 }}>{idx.last?.toLocaleString() ?? "-"}</div>
                    <div className={`num ${changeCls(idx.change_pct)}`} style={{ fontSize: 11 }}>{pct(idx.change_pct)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="kpi-grid">
            <div className="kpi-card">
              <div className="kpi-header">
                <span className="kpi-label">持仓数量</span>
                <div className="kpi-icon blue">📊</div>
              </div>
              <div className="kpi-value">{data.portfolio_summary?.positions ?? 0}</div>
              <div className="kpi-change neutral">只股票</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-header">
                <span className="kpi-label">最大权重</span>
                <div className="kpi-icon amber">⚖️</div>
              </div>
              <div className="kpi-value">{pct(data.portfolio_summary?.max_weight_pct)}</div>
              <div className="kpi-change neutral">单股集中度</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-header">
                <span className="kpi-label">现金比例</span>
                <div className="kpi-icon green">💰</div>
              </div>
              <div className="kpi-value">{pct(data.portfolio_summary?.cash_pct)}</div>
              <div className="kpi-change neutral">可用资金</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-header">
                <span className="kpi-label">监控事件</span>
                <div className="kpi-icon red">🔔</div>
              </div>
              <div className="kpi-value">{events.length}</div>
              <div className="kpi-change neutral">条待处理</div>
            </div>
          </div>

          <div className="two-col">
            <div className="panel">
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M3 3v18h18"/>
                    <path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3"/>
                  </svg>
                  持仓明细
                  <span className="panel-badge">{(data.holdings ?? []).length} 只</span>
                </div>
                <div className="panel-actions">
                  <button className="small" onClick={() => void handleRiskScan()} disabled={scanning} type="button">
                    {scanning ? "扫描中…" : "风险扫描"}
                  </button>
                </div>
              </div>
              <div className="panel-body" style={{ padding: 0 }}>
                <table>
                  <thead>
                    <tr>
                      <th>股票</th>
                      <th>市值</th>
                      <th>权重</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.holdings ?? []).length === 0 ? (
                      <tr><td colSpan={3} className="muted" style={{ padding: 16 }}>暂无持仓</td></tr>
                    ) : (data.holdings ?? []).map((item) => {
                      const market = item.market || inferMarket(item.symbol);
                      return (
                        <tr key={item.symbol} className="row">
                          <td>
                            <div className="stock-info">
                              <div className="stock-icon default">{item.symbol.charAt(0)}</div>
                              <div>
                                <div className="stock-name">{item.name ?? item.symbol}</div>
                                <div className="stock-code">{item.symbol}</div>
                              </div>
                            </div>
                          </td>
                          <td><span className="price-value">{marketMoney(item.market_value, market)}</span></td>
                          <td>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <div className="weight-bar">
                                <div className="weight-bar-fill" style={{ width: `${Math.min(item.weight_pct ?? 0, 100)}%` }} />
                              </div>
                              <span className="num" style={{ fontSize: 12 }}>{pct(item.weight_pct)}</span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                    <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                  </svg>
                  监控事件
                  <span className="panel-badge">{events.length} 条</span>
                </div>
              </div>
              <div className="panel-body">
                {events.length === 0 ? (
                  <div className="muted">暂无盯盘事件</div>
                ) : events.slice(0, 5).map((ev) => (
                  <div key={ev.event_id} className="event-item">
                    <div className={`event-dot ${ev.severity === "high" ? "warning" : "info"}`} />
                    <div className="event-content">
                      <div className="event-title">{ev.title ?? ev.event_id}</div>
                      <div className="event-desc">{ev.symbol ?? "全市场"}</div>
                    </div>
                    <div className="event-time">{ev.triggered_at?.slice(5, 16) ?? ""}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </PageContainer>
  );
}
