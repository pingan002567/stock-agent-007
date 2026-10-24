import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/api/client";
import { useToast } from "@/hooks/useToast";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, TableSkeleton } from "@/components/ui/Loading";
import { PageHead } from "@/components/ui/PageHead";
import { useAppState } from "@/hooks/useAppState";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { AddHoldingDialog } from "@/components/features/AddHoldingDialog";
import { changeCls, computeWeights, currencyMoney, currencySign, inferMarket, pct, stockInitial } from "@/utils/market";

// === Types ===

interface HoldingItem {
  symbol: string;
  name?: string;
  quantity?: number;
  market_value?: number;
  weight_pct?: number | null;
  cost?: number | null;
  pnl_amount?: number | null;
  pnl_pct?: number | null;
  market?: string;
  /** 原币币种：CNY/HKD/USD/USDT */
  currency?: string;
  /** 原币市值（真相）；market_value 是折算后的人民币，拿不到汇率为 null */
  market_value_native?: number | null;
  quote?: {
    last?: number | null;
    change_pct?: number | null;
    degraded?: boolean;
    degraded_reason?: string | null;
    stale?: boolean;
  };
}

interface CurrencyBucket {
  currency: string;
  native: number;
  cny?: number | null;
  count: number;
}

interface FxPayload {
  as_of?: string;
  usd_cny?: number | null;
  hkd_cny?: number | null;
  usdt_usd?: number | null;
  degraded?: boolean;
  degraded_reason?: string | null;
  to_cny?: Record<string, number> | null;
}

interface HoldingsResponse {
  items: HoldingItem[];
  demo?: boolean;
  quotes_degraded_count?: number;
  quotes_total?: number;
  channel?: string;
  fx?: FxPayload;
  summary?: {
    total_value?: number | null;
    converted?: boolean;
    by_currency?: CurrencyBucket[];
    weights?: Record<string, number> | null;
    market_value?: number | null;
    positions?: number;
    max_weight_pct?: number;
    available_cash?: number | null;
    cash_pct?: number | null;
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

function AvailableCashValue({
  amount,
  onSave,
}: {
  amount: number | null | undefined;
  onSave: (amount: number | null) => Promise<void>;
}) {
  const { showToast } = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const commit = async () => {
    const text = draft.trim();
    if (text === "") {
      setBusy(true);
      try { await onSave(null); setEditing(false); }
      finally { setBusy(false); }
      return;
    }
    const value = Number(text.replace(/,/g, ""));
    if (!Number.isFinite(value) || value < 0) {
      showToast("可用资金需为不小于 0 的数字", "error");
      return;
    }
    setBusy(true);
    try { await onSave(value); setEditing(false); }
    finally { setBusy(false); }
  };

  if (!editing) {
    return (
      <button
        type="button"
        className="num"
        title="点击填写可用资金"
        style={{ background: "none", border: "none", padding: 0, color: "inherit", cursor: "text", font: "inherit" }}
        onClick={(ev) => {
          ev.stopPropagation();
          setDraft(amount == null ? "" : String(amount));
          setEditing(true);
        }}
      >
        {amount == null ? "未记录" : money(amount)}
      </button>
    );
  }
  return (
    <input
      autoFocus
      disabled={busy}
      value={draft}
      inputMode="decimal"
      aria-label="可用资金"
      onClick={(ev) => ev.stopPropagation()}
      onChange={(ev) => setDraft(ev.target.value)}
      onBlur={() => void commit()}
      onKeyDown={(ev) => {
        if (ev.key === "Enter") { ev.preventDefault(); void commit(); }
        if (ev.key === "Escape") setEditing(false);
      }}
      style={{ width: 96, height: 26, border: "1px solid var(--line)", borderRadius: 6, background: "var(--panel)", color: "var(--ink)", padding: "0 6px", fontSize: 13 }}
    />
  );
}

export default function Holdings() {
  const { showToast } = useToast();
  const { appDataCache, globalLoading, setStock, setCurrentScreen } = useAppState();
  const openStock = (symbol: string) => {
    setStock(symbol);
    setCurrentScreen("research");
  };

  // Primary data
  const [holdings, setHoldings] = useState<HoldingsResponse | null>(null);
  const [risk, setRisk] = useState<HoldingsRiskResponse | null>(null);

  // UI state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [adding, setAdding] = useState(false);

  // 后端 weight_pct / max_weight_pct 恒为 0（未实现），按持仓市值占比自算兜底
  const derived = computeWeights(holdings?.items ?? []);

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
        {error && <ErrorMessage message={error} />}
        {(holdings?.quotes_degraded_count ?? 0) > 0 && (
          <div className="panel" style={{ borderColor: "var(--amber)", background: "var(--amber-soft, rgba(245,158,11,.08))" }}>
            <div className="panel-body" style={{ fontSize: 13, color: "var(--amber)" }}>
              行情通道降级：{holdings?.quotes_degraded_count}/{holdings?.quotes_total ?? holdings?.items.length ?? 0} 只持仓报价不可用或已 degraded（Mode B）。仓位权重仍可用，现价相关判断请降置信度。
            </div>
          </div>
        )}
        <PageHead
          kpis={[
            { label: "总资产（折合）", value: money(holdings?.summary?.total_value ?? undefined),
              hint: holdings?.summary?.total_value == null ? "无当日汇率，暂不折算" : undefined,
              prompt: "我的持仓总资产构成如何?分币种分别是多少?" },
            { label: "持仓", value: `${holdings?.summary?.positions ?? holdings?.items.length ?? 0} 只` },
            { label: "最大权重", value: holdings?.summary?.converted === false
                ? "—"
                : `${(holdings?.summary?.max_weight_pct ?? derived.maxWeight).toFixed(2)}%`,
              tone: (holdings?.summary?.max_weight_pct ?? derived.maxWeight) >= 15 ? "down" : undefined,
              prompt: "我的持仓集中度是否过高?哪只需要减仓?" },
            { label: "可用资金", value: (
              <AvailableCashValue
                amount={holdings?.summary?.available_cash}
                onSave={async (amount) => {
                  try {
                    const saved = await apiPost<HoldingsResponse>("/api/holdings/available-cash", { amount });
                    setHoldings((prev) => prev ? { ...prev, summary: saved.summary } : prev);
                  } catch (err) {
                    showToast(err instanceof Error ? err.message : "可用资金保存失败", "error");
                    throw err;
                  }
                }}
              />
            ) },
            { label: "风险项", value: risk?.risks?.length ?? 0,
              tone: (risk?.risks?.length ?? 0) > 0 ? "down" : undefined,
              prompt: "解读当前持仓风险扫描结果,并给出应对建议" },
          ]}
          actions={<>
            <button className="small" onClick={() => setAdding(true)} type="button">+ 新增持仓</button>
            <button className="small" disabled={scanning} onClick={() => void handleRiskScan()} type="button">
              {scanning ? "扫描中…" : "风险扫描"}
            </button>
            <AskAiButton prompt="重新评估我的持仓风险,并给出调仓建议" />
          </>}
        />

        {holdings ? (
          <div className="fx-strip">
            <div className="curbar">
              {(holdings.summary?.by_currency ?? []).map((b) => {
                const pctOfBook =
                  b.cny != null && holdings.summary?.market_value
                    ? (b.cny / holdings.summary.market_value) * 100
                    : null;
                return (
                  <div className="cur-chip" key={b.currency}>
                    <span className="cur-sign">{currencySign(b.currency)}</span>
                    <span className="cur-name">{b.currency}</span>
                    <span className="cur-val num">{currencyMoney(b.native, b.currency)}</span>
                    {pctOfBook != null ? <span className="cur-pct num">{pctOfBook.toFixed(1)}%</span> : null}
                  </div>
                );
              })}
            </div>
            <div className="fx-line">
              {holdings.fx?.degraded ? (
                <span style={{ color: "var(--amber)" }}>
                  ⚠ 汇率不可用（{holdings.fx?.degraded_reason ?? "上游失败"}）—— 分币种小计照常，折合总额与跨币种权重失效
                </span>
              ) : (
                <>
                  <span>当日汇率 {holdings.fx?.as_of ?? "—"}</span>
                  <span>USD/CNY {holdings.fx?.usd_cny?.toFixed(4) ?? "—"}</span>
                  <span>HKD/CNY {holdings.fx?.hkd_cny?.toFixed(4) ?? "—"}</span>
                  <span>USDT/USD {holdings.fx?.usdt_usd?.toFixed(4) ?? "—"}</span>
                  <span className="muted">折算不落库，按当日汇率实时计算</span>
                </>
              )}
            </div>
          </div>
        ) : null}

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
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>标的</th>
                      <th>数量</th>
                      <th>成本</th>
                      <th>现价</th>
                      <th>市值</th>
                      <th>盈亏</th>
                      <th>当日</th>
                      <th>权重</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdings.items.map((item, idx) => {
                      const market = inferMarket(item.symbol, item.market);
                      const currency = item.currency || "CNY";
                      const nativeValue = item.market_value_native ?? null;
                      // 权重优先用后端（人民币口径）；降级时后端为 null，退回自算兜底
                      const serverWeights = holdings?.summary?.weights;
                      const weightPct = serverWeights?.[item.symbol] ?? derived.weights[idx] ?? 0;
                      const weightBad = !(Number(item.market_value) > 0) || weightPct <= 0;
                      const day = item.quote?.degraded ? null : item.quote?.change_pct;
                      return (
                      <tr
                        key={item.symbol}
                        className="row"
                        style={{ cursor: "pointer", ...(weightPct >= 15 && !weightBad ? { boxShadow: "inset 2px 0 0 var(--red)" } : {}) }}
                        onClick={() => openStock(item.symbol)}
                      >
                        <td>
                          <div className="stock-info">
                            <div className="stock-icon default">{stockInitial(item.name, item.symbol)}</div>
                            <div>
                              <div className="stock-name">
                                {item.name ?? item.symbol}
                                <span className={`mkt-badge mkt-${market}`}>{market}</span>
                              </div>
                              <div className="stock-code">{item.symbol}</div>
                            </div>
                          </div>
                        </td>
                        <td className="num">{item.quantity ?? 0}</td>
                        <td className="num">{item.cost == null ? "未记录" : currencyMoney(item.cost, currency)}</td>
                        <td className="num">
                          {item.quote?.degraded || item.quote?.last == null
                            ? "—"
                            : currencyMoney(item.quote.last, currency)}
                        </td>
                        <td className="price-value">
                          {nativeValue == null ? money(undefined) : currencyMoney(nativeValue, currency)}
                          {item.market_value != null && currency !== "CNY" ? (
                            <div className="muted" style={{ fontSize: 11, fontWeight: 400 }}>
                              ≈ {money(item.market_value)}
                            </div>
                          ) : null}
                        </td>
                        <td className="num">
                          {item.pnl_amount == null && item.pnl_pct == null ? "—" : (
                            <>
                              {item.pnl_amount != null && (
                                <div className={changeCls(item.pnl_amount)}>{item.pnl_amount == null ? "—" : `${item.pnl_amount > 0 ? "+" : ""}${currencyMoney(item.pnl_amount, currency)}`}</div>
                              )}
                              {item.pnl_pct != null && (
                                <div className={changeCls(item.pnl_pct)} style={{ fontSize: 12 }}>{pct(item.pnl_pct)}</div>
                              )}
                            </>
                          )}
                        </td>
                        <td className={`num ${day == null ? "" : changeCls(day)}`}>
                          {day == null ? "—" : pct(day)}
                        </td>
                        <td>
                          {weightBad ? (
                            <span className="muted" style={{ fontSize: 12 }}>权重不可用</span>
                          ) : (
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <div className="weight-bar">
                                <div className="weight-bar-fill" style={{ width: `${Math.min(weightPct, 100)}%` }} />
                              </div>
                              <span className="num" style={{ fontSize: 12 }}>{weightPct.toFixed(2)}%</span>
                            </div>
                          )}
                        </td>
                      </tr>
                      );
                    })}
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

      {adding ? (
        <AddHoldingDialog
          fx={holdings?.fx}
          bookCny={holdings?.summary?.market_value ?? null}
          onClose={() => setAdding(false)}
          onSaved={(payload) => {
            setHoldings(payload as HoldingsResponse);
            setAdding(false);
            showToast("持仓已保存", "success");
          }}
        />
      ) : null}
    </PageContainer>
  );
}
