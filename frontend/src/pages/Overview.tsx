import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/api/client";
import { useAppState } from "@/hooks/useAppState";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, OverviewSkeleton } from "@/components/ui/Loading";
import { PageHead } from "@/components/ui/PageHead";
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
  latest_ops_briefing?: OpsBriefingCard | null;
  latest_discovery_briefing?: OpsBriefingCard | null;
  inbox_summary?: { open_count?: number; high_count?: number; overdue_count?: number };
}
interface OpsBriefingCard {
  report_id: string;
  title?: string;
  conclusion?: string;
  created_at?: string;
  quality_status?: string;
  session?: string;
  exception_count?: number;
  degraded?: boolean;
}
interface IndexInfo { code?: string; name?: string; last?: number; change_pct?: number }
interface ReportItem { report_id: string; title?: string; status?: string; created_at?: string }

export default function Overview() {
  const { appDataCache, globalLoading, setCurrentScreen } = useAppState();
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
          <PageHead
            kpis={[
              { label: "总资产", value: marketMoney(data.portfolio_summary?.total_value, "CN"),
                prompt: "我的组合总资产构成如何?最近变化的主要原因是什么?" },
              { label: "持仓", value: `${data.portfolio_summary?.positions ?? 0} 只` },
              { label: "最大权重", value: pct(data.portfolio_summary?.max_weight_pct),
                tone: (data.portfolio_summary?.max_weight_pct ?? 0) >= 15 ? "down" : undefined,
                prompt: "我的持仓集中度是否过高?哪只需要减仓?" },
              { label: "现金", value: pct(data.portfolio_summary?.cash_pct) },
              { label: "待办", value: data.inbox_summary?.open_count ?? 0,
                tone: (data.inbox_summary?.high_count ?? 0) > 0 ? "down" : undefined,
                prompt: "总结当前待办：高优有哪些、哪些来自值班失败或报告例外？" },
              { label: "高优告警", value: events.filter((e) => e.severity === "high").length,
                tone: events.some((e) => e.severity === "high") ? "down" : undefined,
                prompt: "分析当前高优告警的根因,并给出处理建议" },
            ]}
            actions={<AskAiButton prompt="今天我的组合表现如何?有什么需要关注的风险或机会?" />}
          />

          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14,2 14,8 20,8"/>
                </svg>
                今日简报
                {data.latest_ops_briefing?.exception_count ? (
                  <span className="panel-badge">{data.latest_ops_briefing.exception_count} 例外</span>
                ) : null}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" className="small" onClick={() => setCurrentScreen("monitor")}>待办</button>
                <button type="button" className="small" onClick={() => setCurrentScreen("reports")}>报告</button>
              </div>
            </div>
            <div className="panel-body">
              {data.latest_ops_briefing ? (
                <div
                  className="event-item"
                  role="button"
                  tabIndex={0}
                  onClick={() => setCurrentScreen("reports")}
                  onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") setCurrentScreen("reports"); }}
                  style={{ cursor: "pointer" }}
                >
                  <div className={`event-dot ${data.latest_ops_briefing.degraded || (data.latest_ops_briefing.exception_count ?? 0) > 0 ? "warning" : "info"}`} />
                  <div className="event-content">
                    <div className="event-title">{data.latest_ops_briefing.title}</div>
                    <div className="event-desc">{data.latest_ops_briefing.conclusion}</div>
                  </div>
                  <div className="event-time">{data.latest_ops_briefing.created_at?.slice(5, 16).replace("T", " ") ?? ""}</div>
                </div>
              ) : (
                <div className="muted">今日尚无值班简报。默认每天 08:30 盘前任务会自动生成；也可在「任务」页立即运行。</div>
              )}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10"/>
                  <path d="M12 8v4l2 2"/>
                </svg>
                今日机会
                {data.latest_discovery_briefing?.exception_count ? (
                  <span className="panel-badge">{data.latest_discovery_briefing.exception_count} 例外</span>
                ) : null}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" className="small" onClick={() => setCurrentScreen("tasks")}>任务</button>
                <button type="button" className="small" onClick={() => setCurrentScreen("settings")}>投资画像</button>
                <button type="button" className="small" onClick={() => setCurrentScreen("reports")}>报告</button>
              </div>
            </div>
            <div className="panel-body">
              {data.latest_discovery_briefing ? (
                <div
                  className="event-item"
                  role="button"
                  tabIndex={0}
                  onClick={() => setCurrentScreen("reports")}
                  onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") setCurrentScreen("reports"); }}
                  style={{ cursor: "pointer" }}
                >
                  <div className={`event-dot ${data.latest_discovery_briefing.degraded || (data.latest_discovery_briefing.exception_count ?? 0) > 0 ? "warning" : "info"}`} />
                  <div className="event-content">
                    <div className="event-title">{data.latest_discovery_briefing.title}</div>
                    <div className="event-desc">{data.latest_discovery_briefing.conclusion}</div>
                  </div>
                  <div className="event-time">{data.latest_discovery_briefing.created_at?.slice(5, 16).replace("T", " ") ?? ""}</div>
                </div>
              ) : (
                <div className="muted">
                  今日尚无机会发现。默认每个交易日 08:20 按投资画像扫全市场；可在「设置 → 工作区」配置风险档，或在「任务」页立即运行「盘前机会发现」。
                </div>
              )}
            </div>
          </div>

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
                    <div className="event-time">{ev.triggered_at?.slice(5, 16).replace("T", " ") ?? ""}</div>
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
