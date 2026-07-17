import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, TableSkeleton } from "@/components/ui/Loading";
import { RefreshButton } from "@/components/ui/RefreshButton";
import { useAppState } from "@/hooks/useAppState";
import { pct } from "@/utils/market";

// === Types ===

interface HoldingItem {
  symbol: string;
  name?: string;
  quantity?: number;
  market_value?: number;
  weight_pct?: number;
  market?: string;
}

interface HoldingsResponse {
  items: HoldingItem[];
  summary?: {
    total_value?: number;
    positions?: number;
    max_weight_pct?: number;
    cash_pct?: number;
  };
}

interface RiskItem {
  kind?: string;
  symbol?: string;
  severity?: string;
  message?: string;
}

interface HoldingsRiskResponse {
  decision?: string;
  risk_count?: number;
  risks?: RiskItem[];
  sector_exposure?: Record<string, number>;
  risk_policy_ref?: { policy_id?: string; name?: string; version?: number };
}

// === Helpers ===

const money = (v?: number) =>
  v != null ? `¥${v.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}` : "—";

// === Component ===

export default function Holdings() {
  const { appDataCache, globalLoading } = useAppState();

  // Primary data
  const [holdings, setHoldings] = useState<HoldingsResponse | null>(null);
  const [risk, setRisk] = useState<HoldingsRiskResponse | null>(null);

  // UI state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftSymbol, setDraftSymbol] = useState("");

  // === loadAll: parallel fetch all data in one shot ===
  const loadAll = async () => {
    const hasData = holdings !== null;
    if (!hasData) setLoading(true);
    setError(null);
    try {
      const [hld, rsk] = await Promise.allSettled([
        apiGet<HoldingsResponse>("/api/holdings"),
        apiGet<HoldingsRiskResponse>("/api/holdings/risk"),
      ]);

      if (hld.status === "fulfilled") {
        setHoldings(hld.value);
        appDataCache.current.holdings = hld.value; // eslint-disable-line react-hooks/immutability
      }
      if (rsk.status === "fulfilled") {
        setRisk(rsk.value);
        appDataCache.current.holdingsRisk = rsk.value;  
      }

      if (hld.status === "rejected" && !hasData)
        setError("加载持仓失败");
    } catch (err) {
      if (!hasData) setError(err instanceof Error ? err.message : "加载持仓失败");
    } finally {
      setLoading(false);
    }
  };

  // === Cache-first + always refresh ===
  useEffect(() => {
    if (globalLoading) return;
    const cache = appDataCache.current;
    if (cache.holdings) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHoldings(cache.holdings as HoldingsResponse);
      setRisk(cache.holdingsRisk as HoldingsRiskResponse | null);
      setLoading(false);
    }
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [globalLoading]);

  // === Action handlers ===

  const handleRiskScan = async () => {
    setScanning(true);
    try {
      await apiPost("/api/holdings/risk");
      await loadAll();
    } catch { /* ignore */ }
    finally { setScanning(false); }
  };

  const handleDraft = async (symbol: string) => {
    if (!symbol.trim()) return;
    setDraftBusy(true);
    try {
      await apiPost("/api/rebalance-drafts", { symbol, target_weight_pct: 15 });
      setDraftSymbol("");
      await loadAll();
    } catch { /* ignore */ }
    finally { setDraftBusy(false); }
  };

  // === Main render ===

  // First load — skeleton
  if (loading && !holdings) {
    return (
      <PageContainer>
        <div className="page-stack">
          <div className="page-hero fade-in">
            <div><h2>持仓与风控</h2><p>以真实持仓为核心，展示仓位、集中度和风险扫描。</p></div>
          </div>
          <section className="detail-grid">
            <div><TableSkeleton rows={6} /></div>
            <div><TableSkeleton rows={4} /></div>
          </section>
        </div>
      </PageContainer>
    );
  }

  // Error with no data
  if (!loading && error && !holdings) {
    return <PageContainer><ErrorMessage message={error} /></PageContainer>;
  }

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        <div className="market-hero">
          <div className="market-hero-header">
            <div className="market-title">
              <h1>持仓管理</h1>
              <p>查看和管理您的投资组合，分析持仓风险和收益。</p>
            </div>
            <div className="hero-actions">
              <button className="primary" disabled={scanning} onClick={() => void handleRiskScan()} type="button">
                {scanning ? "扫描中…" : "风险扫描"}
              </button>
              <RefreshButton refreshing={loading} onClick={() => void loadAll()} />
            </div>
          </div>
          <div className="market-stats">
            <div className="market-stat">
              <span className="market-stat-label">总资产</span>
              <span className="market-stat-value">{money(holdings?.summary?.total_value)}</span>
              <span className="market-stat-change neutral">{holdings?.summary?.positions ?? 0} 只持仓</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">持仓数量</span>
              <span className="market-stat-value">{holdings?.summary?.positions ?? holdings?.items.length ?? 0}</span>
              <span className="market-stat-change neutral">只股票</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">最大权重</span>
              <span className="market-stat-value">{pct(holdings?.summary?.max_weight_pct)}</span>
              <span className="market-stat-change neutral">单股集中度</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">现金比例</span>
              <span className="market-stat-value">{pct(holdings?.summary?.cash_pct)}</span>
              <span className="market-stat-change neutral">可用资金</span>
            </div>
          </div>
        </div>

        <div className="kpi-grid">
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">持仓数量</span>
              <div className="kpi-icon blue">📊</div>
            </div>
            <div className="kpi-value">{holdings?.items.length ?? 0}</div>
            <div className="kpi-change neutral">只股票</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">总资产</span>
              <div className="kpi-icon green">💰</div>
            </div>
            <div className="kpi-value">{money(holdings?.summary?.total_value)}</div>
            <div className="kpi-change neutral">当前价值</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">最大权重</span>
              <div className="kpi-icon amber">⚖️</div>
            </div>
            <div className="kpi-value">{pct(holdings?.summary?.max_weight_pct)}</div>
            <div className="kpi-change neutral">单股集中度</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">风险评分</span>
              <div className="kpi-icon red">⚡</div>
            </div>
            <div className="kpi-value">{risk?.risks?.length ?? 0}</div>
            <div className="kpi-change neutral">项风险</div>
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
                <span className="panel-badge">{holdings?.items.length ?? 0} 只</span>
              </div>
            </div>
            <div className="panel-body" style={{ padding: 0 }}>
              {holdings && holdings.items.length > 0 ? (
                <table>
                  <thead>
                    <tr>
                      <th>股票</th>
                      <th>数量</th>
                      <th>市值</th>
                      <th>权重</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdings.items.map((item) => (
                      <tr key={item.symbol}>
                        <td>
                          <div className="stock-info">
                            <div className="stock-icon default">{item.symbol.charAt(0)}</div>
                            <div>
                              <div className="stock-name">{item.name ?? item.symbol}</div>
                              <div className="stock-code">{item.symbol}</div>
                            </div>
                          </div>
                        </td>
                        <td className="num">{item.quantity ?? 0}</td>
                        <td className="price-value">{money(item.market_value)}</td>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <div className="weight-bar">
                              <div className="weight-bar-fill" style={{ width: `${Math.min(item.weight_pct ?? 0, 100)}%` }} />
                            </div>
                            <span className="num" style={{ fontSize: 12 }}>{pct(item.weight_pct)}</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="muted" style={{ padding: 24 }}>暂无持仓记录</div>
              )}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                  <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                </svg>
                风险诊断
                <span className="panel-badge">{risk?.risks?.length ?? 0} 项</span>
              </div>
            </div>
            <div className="panel-body">
              {risk && risk.risks && risk.risks.length > 0 ? (
                risk.risks.map((r, i) => (
                  <div key={i} className="intel-item">
                    <div className={`intel-dot ${r.severity === "high" ? "warning" : r.severity === "medium" ? "info" : "success"}`} />
                    <div className="intel-content">
                      <div className="intel-title">{r.symbol ?? r.kind ?? "风险项"}</div>
                      <div className="intel-desc">{r.message ?? "暂无描述"}</div>
                    </div>
                    <div className="intel-time">{r.severity ?? "info"}</div>
                  </div>
                ))
              ) : (
                <div className="muted">暂无风险诊断</div>
              )}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14,2 14,8 20,8"/>
              </svg>
              生成调仓草案
            </div>
          </div>
          <div className="panel-body">
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <input
                value={draftSymbol}
                onChange={(e) => setDraftSymbol(e.target.value.toUpperCase())}
                placeholder="输入股票代码，如 AAPL"
                style={{ flex: 1 }}
              />
              <button className="primary" disabled={draftBusy || !draftSymbol.trim()}
                onClick={() => void handleDraft(draftSymbol.trim())}
                type="button">
                {draftBusy ? "生成中…" : "生成草案"}
              </button>
            </div>
            <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
              目标仓位 15%，生成后需人工确认或驳回。
            </div>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}
