import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/api/client";
import { useAppState } from "@/hooks/useAppState";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, PanelSkeleton, KpiSkeleton } from "@/components/ui/Loading";
import { RefreshButton } from "@/components/ui/RefreshButton";
import { inferMarket, marketMoney, pct, changeCls } from "@/utils/market";

interface IndexInfo { code?: string; name?: string; last?: number; change_pct?: number; turnover?: number; market?: string }
interface MarketReview {
  status?: string; summary?: string; indices?: IndexInfo[];
  breadth?: { rising_count?: number; falling_count?: number; flat_count?: number; sample_size?: number };
  turnover?: { a_share_total?: number };
}
interface SectorItem { sector: string; signal?: string; change_pct?: number; leader_stock?: string; leader_change_pct?: number }
interface TimelineEvent { time?: string; title?: string; summary?: string }

export default function Market() {
  const { appDataCache, globalLoading } = useAppState();
  const [review, setReview] = useState<MarketReview | null>(null);
  const [sectors, setSectors] = useState<SectorItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Populate from global cache once initial load completes
  useEffect(() => {
    if (globalLoading) return;
    const cache = appDataCache.current;
    if (cache.marketReview) {
      setReview(cache.marketReview as MarketReview); // eslint-disable-line react-hooks/set-state-in-effect
      setSectors((cache.marketSectors as { items: SectorItem[] })?.items ?? []);
      setTimeline((cache.marketTimeline as { items: TimelineEvent[] })?.items ?? []);
      setLoading(false);
    }
  }, [globalLoading, appDataCache]);

  const loadAll = useCallback(async () => {
    setRefreshing(true); setLoading(true); setError(null);
    try {
      const [mr, sd, tl] = await Promise.all([
        apiGet<MarketReview>("/api/market/review"),
        apiGet<{ items: SectorItem[] }>("/api/market/sectors").then((r) => r.items).catch(() => []),
        apiGet<{ items: TimelineEvent[] }>("/api/market/timeline").then((r) => r.items).catch(() => []),
      ]);
      setReview(mr); setSectors(sd); setTimeline(tl);
    } catch (err) { setError(err instanceof Error ? err.message : "加载市场概览失败"); } finally { setLoading(false); setRefreshing(false); }
  }, []);

  if (loading && !review) return (
    <PageContainer>
      <div className="page-stack">
        <div className="page-hero fade-in">
          <div><h2>市场与板块</h2><p>大盘复盘和板块热力...</p></div>
        </div>
        <section className="detail-grid">
          <div className="page-stack"><PanelSkeleton /><PanelSkeleton /></div>
          <div className="page-stack"><PanelSkeleton /><KpiSkeleton count={3} /></div>
        </section>
      </div>
    </PageContainer>
  );
  if (!loading && error && !review) return <PageContainer><ErrorMessage message={error} /></PageContainer>;

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        <div className="market-hero">
          <div className="market-hero-header">
            <div className="market-title">
              <h1>市场概览</h1>
              <p>实时追踪全球市场动态，分析板块轮动，发现投资机会。</p>
            </div>
            <div className="hero-actions">
              <RefreshButton refreshing={refreshing} onClick={() => void loadAll()} />
            </div>
          </div>
          <div className="market-stats">
            <div className="market-stat">
              <span className="market-stat-label">上涨股票</span>
              <span className="market-stat-value up">{review?.breadth?.rising_count ?? 0}</span>
              <span className="market-stat-change up">
                ↑ {review?.breadth?.sample_size ? Math.round(((review.breadth.rising_count ?? 0) / review.breadth.sample_size) * 100) : 0}%
              </span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">下跌股票</span>
              <span className="market-stat-value down">{review?.breadth?.falling_count ?? 0}</span>
              <span className="market-stat-change down">
                ↓ {review?.breadth?.sample_size ? Math.round(((review.breadth.falling_count ?? 0) / review.breadth.sample_size) * 100) : 0}%
              </span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">平盘</span>
              <span className="market-stat-value">{review?.breadth?.flat_count ?? 0}</span>
              <span className="market-stat-change neutral">只</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">成交额</span>
              <span className="market-stat-value">{marketMoney(review?.turnover?.a_share_total, "CN")}</span>
              <span className="market-stat-change neutral">A股</span>
            </div>
          </div>
        </div>

        <div className={`market-index ${refreshing ? 'refreshing-module' : ''}`}>
          {(review?.indices ?? []).slice(0, 4).map((idx) => (
            <div key={idx.code ?? idx.name} className="index-card">
              <div className="index-name">{idx.name}</div>
              <div className="index-value">{marketMoney(idx.last, idx.market || inferMarket(idx.code))}</div>
              <div className={`index-change ${changeCls(idx.change_pct)}`}>
                {idx.change_pct && idx.change_pct >= 0 ? "↑" : "↓"} {pct(idx.change_pct)}
              </div>
            </div>
          ))}
        </div>

        <div className={`kpi-grid ${refreshing ? 'refreshing-module' : ''}`}>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">成交额</span>
              <div className="kpi-icon blue">💰</div>
            </div>
            <div className="kpi-value">{marketMoney(review?.turnover?.a_share_total, "CN")}</div>
            <div className="kpi-change neutral">A股总成交</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">上涨家数</span>
              <div className="kpi-icon green">📈</div>
            </div>
            <div className="kpi-value">{review?.breadth?.rising_count ?? 0}</div>
            <div className="kpi-change up">只</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">下跌家数</span>
              <div className="kpi-icon red">📉</div>
            </div>
            <div className="kpi-value">{review?.breadth?.falling_count ?? 0}</div>
            <div className="kpi-change down">只</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">板块数量</span>
              <div className="kpi-icon amber">📊</div>
            </div>
            <div className="kpi-value">{sectors.length}</div>
            <div className="kpi-change neutral">个板块</div>
          </div>
        </div>

        <div className={`panel ${refreshing ? 'refreshing-module' : ''}`} style={{ marginBottom: 24 }}>
          <div className="panel-header">
            <div className="panel-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="7" height="7" rx="1"/>
                <rect x="14" y="3" width="7" height="7" rx="1"/>
                <rect x="3" y="14" width="7" height="7" rx="1"/>
                <rect x="14" y="14" width="7" height="7" rx="1"/>
              </svg>
              板块热力图
              <span className="panel-badge">{sectors.length} 板块</span>
            </div>
          </div>
          <div className="panel-body">
            <div className="sector-grid">
              {sectors.slice(0, 6).map((s) => {
                const cp = s.change_pct ?? 0;
                const maxAbs = Math.max(...sectors.map((x) => Math.abs(x.change_pct ?? 0)), 1);
                const barPct = (Math.abs(cp) / maxAbs) * 100;
                return (
                  <div key={s.sector} className="sector-card">
                    <div className="sector-name">{s.sector}</div>
                    <div className={`sector-change ${changeCls(cp)}`}>{pct(cp)}</div>
                    <div className="sector-stocks">
                      {s.leader_stock ? `${s.leader_stock} 领涨` : "暂无数据"}
                    </div>
                    <div className="sector-bar">
                      <div className={`sector-bar-fill ${cp >= 0 ? "up" : "down"}`} style={{ width: `${barPct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className={`two-col ${refreshing ? 'refreshing-module' : ''}`}>
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/>
                </svg>
                涨幅榜
                <span className="panel-badge">TOP 10</span>
              </div>
            </div>
            <div className="panel-body">
              <table>
                <thead>
                  <tr>
                    <th>板块</th>
                    <th>涨跌幅</th>
                    <th>领涨股</th>
                  </tr>
                </thead>
                <tbody>
                  {[...sectors].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0)).slice(0, 5).map((s) => (
                    <tr key={s.sector}>
                      <td><span className="tag">{s.sector}</span></td>
                      <td><span className={`num ${changeCls(s.change_pct)}`}>{pct(s.change_pct)}</span></td>
                      <td>{s.leader_stock ? `${s.leader_stock} ${pct(s.leader_change_pct)}` : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/>
                </svg>
                跌幅榜
                <span className="panel-badge">TOP 10</span>
              </div>
            </div>
            <div className="panel-body">
              <table>
                <thead>
                  <tr>
                    <th>板块</th>
                    <th>涨跌幅</th>
                    <th>领跌股</th>
                  </tr>
                </thead>
                <tbody>
                  {[...sectors].sort((a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0)).slice(0, 5).map((s) => (
                    <tr key={s.sector}>
                      <td><span className="tag">{s.sector}</span></td>
                      <td><span className={`num ${changeCls(s.change_pct)}`}>{pct(s.change_pct)}</span></td>
                      <td>{s.leader_stock ? `${s.leader_stock} ${pct(s.leader_change_pct)}` : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {timeline.length > 0 && (
          <div className={`panel ${refreshing ? 'refreshing-module' : ''}`}>
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10"/>
                  <polyline points="12,6 12,12 16,14"/>
                </svg>
                市场时间线
              </div>
            </div>
            <div className="panel-body">
              {timeline.slice(0, 5).map((ev, i) => (
                <div key={i} className="intel-item">
                  <div className={`intel-dot ${i === 0 ? "warning" : i === 1 ? "info" : "success"}`} />
                  <div className="intel-content">
                    <div className="intel-title">{ev.title}</div>
                    <div className="intel-desc">{ev.summary}</div>
                  </div>
                  <div className="intel-time">{ev.time ?? ""}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </PageContainer>
  );
}
