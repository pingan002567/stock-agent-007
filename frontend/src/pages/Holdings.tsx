import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, TableSkeleton } from "@/components/ui/Loading";
import { PageHead } from "@/components/ui/PageHead";
import { useAppState } from "@/hooks/useAppState";
import { AskAiButton } from "@/components/ui/AskAiButton";
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
  demo?: boolean;
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
  const [clearingDemo, setClearingDemo] = useState(false);

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

  const handleClearDemo = async () => {
    if (!window.confirm("清空示例持仓？这不会删除自选里的观察标的。")) return;
    setClearingDemo(true);
    try {
      await apiPost("/api/holdings/clear-demo", {});
      await loadAll();
    } catch { /* ignore */ }
    finally { setClearingDemo(false); }
  };

  const handleRiskScan = async () => {
    setScanning(true);
    try {
      await apiPost("/api/holdings/risk");
      await loadAll();
    } catch { /* ignore */ }
    finally { setScanning(false); }
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
        <PageHead
          kpis={[
            { label: "总资产", value: money(holdings?.summary?.total_value),
              prompt: "我的持仓总资产构成如何?" },
            { label: "持仓", value: `${holdings?.summary?.positions ?? holdings?.items.length ?? 0} 只` },
            { label: "最大权重", value: pct(holdings?.summary?.max_weight_pct),
              tone: (holdings?.summary?.max_weight_pct ?? 0) >= 15 ? "down" : undefined,
              prompt: "我的持仓集中度是否过高?哪只需要减仓?" },
            { label: "现金", value: pct(holdings?.summary?.cash_pct) },
            { label: "风险项", value: risk?.risks?.length ?? 0,
              tone: (risk?.risks?.length ?? 0) > 0 ? "down" : undefined,
              prompt: "解读当前持仓风险扫描结果,并给出应对建议" },
          ]}
          actions={<>
            {holdings?.demo ? (
              <button className="small" disabled={clearingDemo} onClick={() => void handleClearDemo()} type="button">
                {clearingDemo ? "清空中…" : "清空示例持仓"}
              </button>
            ) : null}
            <button className="small" disabled={scanning} onClick={() => void handleRiskScan()} type="button">
              {scanning ? "扫描中…" : "风险扫描"}
            </button>
            <AskAiButton prompt="重新评估我的持仓风险,并给出调仓建议" />
          </>}
        />

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
                {holdings?.demo ? <span className="panel-badge">示例</span> : null}
              </div>
            </div>
            <div className="panel-body" style={{ padding: 0 }}>
              {holdings?.demo ? (
                <div className="muted" style={{ padding: "10px 16px", borderBottom: "1px solid var(--line)" }}>
                  当前是首次种子示例仓（茅台 / 腾讯 / AAPL），权重仅供演示，不是你的真仓。
                </div>
              ) : null}
              {holdings && holdings.items.length > 0 ? (
                <table className="data-table">
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
                      <tr key={item.symbol} style={(item.weight_pct ?? 0) >= 15 ? { boxShadow: "inset 2px 0 0 var(--red)" } : undefined}>
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

      </div>
    </PageContainer>
  );
}
