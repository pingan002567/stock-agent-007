import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, TableSkeleton, EmptyState } from "@/components/ui/Loading";
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

interface DraftItem {
  draft_id: string;
  symbol: string;
  action?: string;
  status: string;
  target_weight_pct?: number;
  created_at?: string;
}

interface ReviewItem {
  review_id: string;
  draft_id?: string;
  symbol?: string;
  status?: string;
  created_at?: string;
}

interface PaperOrder {
  order_id: string;
  symbol?: string;
  side?: string;
  quantity?: number;
  status?: string;
  created_at?: string;
}

interface JournalEntry {
  entry_id: string;
  decision_id?: string;
  summary?: string;
  status?: string;
  created_at?: string;
}

interface InboxItem {
  item_key: string;
  title?: string;
  status?: string;
}

interface RiskPolicy {
  policy_id?: string;
  name?: string;
  version?: number;
  [key: string]: unknown;
}

// === Helpers ===

const money = (v?: number) =>
  v != null ? `¥${v.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}` : "—";

/** Format paper portfolio response into a one-line summary. */
function formatPaperPortfolioSummary(pp: unknown): string {
  if (!pp) return "";
  if (typeof pp === "string") return pp;
  const obj = pp as Record<string, unknown>;
  const parts: string[] = [];
  if (obj.total_value != null)
    parts.push(`总资产: ¥${Number(obj.total_value).toLocaleString()}`);
  if (obj.cash != null)
    parts.push(`现金: ¥${Number(obj.cash).toLocaleString()}`);
  if (obj.positions != null)
    parts.push(`持仓: ${obj.positions} 只`);
  if (obj.return_pct != null)
    parts.push(`收益: ${(Number(obj.return_pct) >= 0 ? "+" : "")}${Number(obj.return_pct).toFixed(2)}%`);
  return parts.length > 0 ? parts.join(" · ") : "";
}

// === Component ===

export default function Holdings() {
  const { setStock, appDataCache, globalLoading } = useAppState();

  // Primary data
  const [holdings, setHoldings] = useState<HoldingsResponse | null>(null);
  const [risk, setRisk] = useState<HoldingsRiskResponse | null>(null);

  // Secondary data (often empty)
  const [drafts, setDrafts] = useState<DraftItem[]>([]);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [paperOrders, setPaperOrders] = useState<PaperOrder[]>([]);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [inbox, setInbox] = useState<InboxItem[]>([]);
  const [activePolicy, setActivePolicy] = useState<RiskPolicy | null>(null);
  const [paperPortfolioText, setPaperPortfolioText] = useState("");

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
      const [
        hld, rsk, dr, rv, po, jn, ib, pp, ap,
      ] = await Promise.allSettled([
        apiGet<HoldingsResponse>("/api/holdings"),
        apiGet<HoldingsRiskResponse>("/api/holdings/risk"),
        apiGet<{ items: DraftItem[] }>("/api/rebalance-drafts").catch(() => ({ items: [] })),
        apiGet<{ items: ReviewItem[] }>("/api/pre-trade-reviews").catch(() => ({ items: [] })),
        apiGet<{ items: PaperOrder[] }>("/api/paper-orders").catch(() => ({ items: [] })),
        apiGet<{ items: JournalEntry[] }>("/api/decision-journal").catch(() => ({ items: [] })),
        apiGet<{ items: InboxItem[] }>("/api/review-inbox").catch(() => ({ items: [] })),
        apiGet<Record<string, unknown>>("/api/paper-portfolio")
          .then((r) => formatPaperPortfolioSummary(r))
          .catch(() => ""),
        apiGet<RiskPolicy>("/api/risk-policies/active").catch(() => null),
      ]);

      if (hld.status === "fulfilled") {
        setHoldings(hld.value);
        appDataCache.current.holdings = hld.value; // eslint-disable-line react-hooks/immutability
      }
      if (rsk.status === "fulfilled") {
        setRisk(rsk.value);
        appDataCache.current.holdingsRisk = rsk.value; // eslint-disable-line react-hooks/immutability
      }
      if (dr.status === "fulfilled") {
        setDrafts(dr.value.items ?? []);
        appDataCache.current.drafts = dr.value; // eslint-disable-line react-hooks/immutability
      }
      if (rv.status === "fulfilled") {
        setReviews(rv.value.items ?? []);
        appDataCache.current.preTradeReviews = rv.value; // eslint-disable-line react-hooks/immutability
      }
      if (po.status === "fulfilled") {
        setPaperOrders(po.value.items ?? []);
        appDataCache.current.paperOrders = po.value; // eslint-disable-line react-hooks/immutability
      }
      if (jn.status === "fulfilled") {
        setJournal(jn.value.items ?? []);
        appDataCache.current.journal = jn.value; // eslint-disable-line react-hooks/immutability
      }
      if (ib.status === "fulfilled") {
        setInbox(ib.value.items ?? []);
        appDataCache.current.inboxList = ib.value; // eslint-disable-line react-hooks/immutability
      }
      if (pp.status === "fulfilled") setPaperPortfolioText(pp.value);
      if (ap.status === "fulfilled") {
        setActivePolicy(ap.value);
        appDataCache.current.activePolicy = ap.value; // eslint-disable-line react-hooks/immutability
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
      setDrafts((cache.drafts as { items: DraftItem[] })?.items ?? []);
      setReviews((cache.preTradeReviews as { items: ReviewItem[] })?.items ?? []);
      setPaperOrders((cache.paperOrders as { items: PaperOrder[] })?.items ?? []);
      setJournal((cache.journal as { items: JournalEntry[] })?.items ?? []);
      setInbox((cache.inboxList as { items: InboxItem[] })?.items ?? []);
      setActivePolicy(cache.activePolicy as RiskPolicy | null);
      if (cache.paperPortfolio)
        setPaperPortfolioText(formatPaperPortfolioSummary(cache.paperPortfolio));
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

  const handleConfirmDraft = async (id: string) => {
    try {
      await apiPost(`/api/rebalance-drafts/${id}/confirm`);
      await loadAll();
    } catch { /* ignore */ }
  };

  const handleRejectDraft = async (id: string) => {
    try {
      await apiPost(`/api/rebalance-drafts/${id}/reject`);
      await loadAll();
    } catch { /* ignore */ }
  };

  // === Render helpers ===

  const renderHoldingsTable = () => {
    if (!holdings || holdings.items.length === 0)
      return (
        <div className="pad">
          <EmptyState icon="holdings" title="暂无持仓记录" description="导入持仓数据后即可在此查看。" />
        </div>
      );

    return (
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>数量</th>
            <th>市值</th>
            <th>仓位</th>
            <th>市场</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {holdings.items.map((item) => (
            <tr key={item.symbol} className="row">
              <td>
                <button className="link" onClick={() => setStock(item.symbol)} type="button"
                  style={{ fontWeight: 600, fontFamily: "var(--mono)" }}>
                  {item.symbol}
                </button>
                {item.name && <div className="muted" style={{ fontSize: 11 }}>{item.name}</div>}
              </td>
              <td className="num">{item.quantity ?? 0}</td>
              <td className="num">{money(item.market_value)}</td>
              <td className="num">{pct(item.weight_pct)}</td>
              <td>{item.market ? <span className="tag" style={{ fontSize: 10 }}>{item.market}</span> : <span className="muted" style={{ fontSize: 11 }}>—</span>}</td>
              <td>
                <button className="ghost" style={{ height: 22, fontSize: 10, padding: "0 6px" }}
                  onClick={() => setStock(item.symbol)} type="button">研</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  const renderRiskPanel = () => {
    if (!risk) return null;

    const policyName = activePolicy?.name ?? risk.risk_policy_ref?.policy_id ?? "默认";
    const risks = risk.risks ?? [];
    const sectorExp = risk.sector_exposure;

    return (
      <div className="panel">
        <div className="head">
          <span className="title">风险诊断</span>
          <span className="sub">策略: {policyName}</span>
        </div>
        <div className="pad">
          <div className="ticket" style={{ marginBottom: risks.length > 0 ? 12 : 0 }}>
            {risk.decision ?? "暂无风险结论"}
          </div>

          {risks.length > 0 && risks.map((r, i) => (
            <div key={i} className="check" style={{ marginTop: 6 }}>
              <span className={`tag ${r.severity === "high" ? "red" : "amber"}`}>
                {r.severity ?? "info"}
              </span>
              <div>
                <strong>{r.symbol ?? r.kind}</strong>
                {r.message && <div className="muted" style={{ fontSize: 12 }}>{r.message}</div>}
              </div>
            </div>
          ))}

          {sectorExp && Object.keys(sectorExp).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>板块暴露</div>
              {Object.entries(sectorExp).map(([sector, value]) => (
                <div key={sector} className="barline">
                  <span style={{ fontSize: 12 }}>{sector}</span>
                  <div className="bar" style={{ flex: 1 }}>
                    <span className="bar-fill" style={{ width: `${Math.min(value, 100)}%` }} />
                  </div>
                  <span className="num" style={{ fontSize: 12 }}>{pct(value)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderDrafts = () => {
    if (drafts.length === 0) return null;
    return (
      <div className="panel">
        <div className="head"><span className="title">拟单草案</span></div>
        <div className="pad">
          {drafts.map((d) => (
            <div key={d.draft_id} className="check">
              <div>
                <strong>{d.symbol}</strong> · {d.action ?? "调仓"} → {pct(d.target_weight_pct)}
                <div className="muted" style={{ fontSize: 12 }}>
                  {d.status}{d.created_at ? ` · ${d.created_at}` : ""}
                </div>
              </div>
              {d.status === "pending_user_confirmation" && (
                <div className="hero-actions" style={{ gap: 4 }}>
                  <button className="primary" onClick={() => void handleConfirmDraft(d.draft_id)}
                    type="button" style={{ background: "var(--green)", borderColor: "var(--green)", height: 28, fontSize: 12 }}>
                    确认
                  </button>
                  <button className="danger" onClick={() => void handleRejectDraft(d.draft_id)}
                    type="button" style={{ height: 28, fontSize: 12 }}>
                    驳回
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderPaperSandbox = () => {
    if (reviews.length === 0 && paperOrders.length === 0 && !paperPortfolioText) return null;
    return (
      <div className="panel">
        <div className="head"><span className="title">Paper Sandbox</span></div>
        <div className="pad">
          {reviews.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>交易前审查</div>
              {reviews.map((r) => (
                <div key={r.review_id} className="check">
                  <span>{r.symbol ?? r.draft_id} · {r.status}</span>
                  {r.created_at && <span className="muted" style={{ fontSize: 12 }}>{r.created_at}</span>}
                </div>
              ))}
            </div>
          )}
          {paperOrders.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>模拟订单</div>
              {paperOrders.map((o) => (
                <div key={o.order_id} className="check">
                  <span>{o.symbol} · {o.side} {o.quantity}</span>
                  <span className="tag" style={{ fontSize: 10 }}>{o.status}</span>
                </div>
              ))}
            </div>
          )}
          {paperPortfolioText && (
            <div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Portfolio 摘要</div>
              <div className="ticket" style={{ fontSize: 13 }}>{paperPortfolioText}</div>
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderJournal = () => {
    if (journal.length === 0) return null;
    return (
      <div className="panel">
        <div className="head"><span className="title">决策日志</span></div>
        <div className="pad">
          {journal.map((j) => (
            <div key={j.entry_id} className="check">
              <div>
                <strong>{j.summary ?? j.entry_id}</strong>
                {j.decision_id && <div className="muted" style={{ fontSize: 12 }}>{j.decision_id}</div>}
              </div>
              <span className="tag">{j.status}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderInbox = () => {
    if (inbox.length === 0) return null;
    return (
      <div className="panel">
        <div className="head"><span className="title">复核待办</span></div>
        <div className="pad">
          {inbox.map((item) => (
            <div key={item.item_key} className="check">
              <strong>{item.title ?? item.item_key}</strong>
              <span className="tag">{item.status}</span>
            </div>
          ))}
        </div>
      </div>
    );
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
              <button onClick={() => void loadAll()} disabled={loading} type="button">刷新数据</button>
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
