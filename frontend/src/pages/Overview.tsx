import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/api/client";
import { useAppState } from "@/hooks/useAppState";
import { AskAiButton } from "@/components/ui/AskAiButton";
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
interface ReportItem { report_id: string; title?: string; status?: string; created_at?: string }

export default function Overview() {
  const { appDataCache, globalLoading } = useAppState();
  const [data, setData] = useState<OverviewData | null>(null);
  const [events, setEvents] = useState<MonitorEvent[]>([]);
  const [indices, setIndices] = useState<IndexInfo[]>([]);
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [ov, ev, mr, rp] = await Promise.all([
        apiGet<OverviewData>("/api/overview"),
        apiGet<{ items: MonitorEvent[] }>("/api/monitor/events").catch(() => ({ items: [] })),
        apiGet<{ indices?: IndexInfo[] }>("/api/market/review").catch(() => ({ indices: [] })),
        apiGet<{ items: ReportItem[] }>("/api/reports").catch(() => ({ items: [] })),
      ]);
      setData(ov); setEvents(ev.items ?? []); setIndices(mr.indices ?? []);
      setReports((rp.items ?? []).slice(0, 3));
    } catch (err) { setError(err instanceof Error ? err.message : "加载总览失败"); } finally { setLoading(false); }
  }, []);

  // Populate from global cache once initial load completes
  useEffect(() => {
    if (globalLoading) return;
    const cache = appDataCache.current;
    if (cache.overview) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 既有 cache-first 水合模式
      setData(cache.overview as OverviewData);
      setEvents((cache.monitorEvents as { items: MonitorEvent[] })?.items ?? []);
      setIndices(((cache.marketReview as { indices?: IndexInfo[] })?.indices ?? []));
      setReports((((cache.reports as { items?: ReportItem[] })?.items) ?? []).slice(0, 3));
      setLoading(false);
    }
    // 缓存兜底后仍拉一次最新(报告/事件此页刻度较粗,静默刷新)
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [globalLoading]);



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
              <AskAiButton prompt="今天我的组合表现如何?有什么需要关注的风险或机会?" />
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

          {reports.length > 0 && (
            <div className="panel">
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14,2 14,8 20,8"/>
                  </svg>
                  最近报告
                  <span className="panel-badge">{reports.length} 篇</span>
                </div>
              </div>
              <div className="panel-body">
                {reports.map((r) => (
                  <div key={r.report_id} className="event-item">
                    <div className={`event-dot ${r.status === "passed" || r.status === "completed" ? "info" : "warning"}`} />
                    <div className="event-content">
                      <div className="event-title">{r.title ?? r.report_id}</div>
                    </div>
                    <div className="event-time">{r.created_at?.slice(5, 16) ?? ""}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </PageContainer>
  );
}
