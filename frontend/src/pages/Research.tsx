import { useCallback, useEffect, useRef, useState } from "react";
import { apiDelete, apiGet, apiPost } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, PanelSkeleton, KpiSkeleton } from "@/components/ui/Loading";
import { useAppState } from "@/hooks/useAppState";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { useToast } from "@/hooks/useToast";
import { MarkdownRenderer as Markdown } from "@/components/features/MarkdownRenderer";
import { StockHistoryChart } from "@/components/features/StockHistoryChart";
import {
  sortFinancialNewestFirst,
  sortHistoryNewestFirst,
  sortIntelNewestFirst,
} from "@/lib/sortStockSeries";
import { FUNNEL_EXAMPLE_STOCKS, RESEARCH_FUNNEL } from "@/lib/researchFunnel";

// --- types ---

interface StockSearchResult {
  symbol: string;
  name: string;
  market?: string;
  price?: number;
  change_pct?: number;
  sector?: string;
}

interface StockPrice {
  last?: number;
  change_pct?: number;
  updated_at?: string;
  source?: string;
}

interface StockRelation {
  in_watchlist?: boolean;
  in_holdings?: boolean;
  monitored?: boolean;
}

interface StockHolding {
  weight_pct?: number;
  quantity?: number;
  market_value?: number;
  pnl_pct?: number | null;
}

interface StockContext {
  symbol: string;
  name?: string;
  market?: string;
  industry?: string;
  sector?: string;
  price?: StockPrice;
  relation?: StockRelation;
  holding?: StockHolding;
  ai_state?: { score?: number; risk_label?: string; stance?: string; confidence?: string };
  latest_report?: { report_id?: string; generated_at?: string };
}

interface HistoryItem { date?: string; day?: number; open?: number; high?: number; low?: number; close?: number; volume?: number }
interface IntelItem { title?: string; summary?: string; source?: string; published_at?: string; updated_at?: string }
interface FinancialItem { report_date?: string; report_type?: string; revenue?: number; profit?: number; total_assets?: number; total_liabilities?: number }
interface FollowupItem { label?: string; prompt?: string; action?: string }

interface MarketStructureTechnical {
  degraded?: boolean;
  reason?: string | null;
  missing?: string[];
  bar_count?: number;
  as_of?: string;
  last?: number;
  ma5?: number | null;
  ma10?: number | null;
  ma20?: number | null;
  ma60?: number | null;
  ma_stack?: string | null;
  rsi14?: number | null;
  volume_ratio?: number | null;
  support_20?: number | null;
  resistance_20?: number | null;
  volume_note?: string | null;
}
interface MarketStructureChip {
  degraded?: boolean;
  reason?: string;
  quality?: string;
  profit_ratio?: number | null;
  trapped_ratio?: number | null;
  market_avg_cost?: number | null;
  price_vs_avg_cost_pct?: number | null;
  cost_90_low?: number | null;
  cost_90_high?: number | null;
  concentration_90?: number | null;
  as_of?: string;
  notes?: string[];
  proxy?: { vwap_20d?: number | null; volume_vs_20d?: number | null };
}
interface MarketStructureFlow {
  degraded?: boolean;
  reason?: string;
  main_net_1d?: number | null;
  main_net_5d?: number | null;
  as_of?: string;
}
interface MarketStructureSnapshot {
  degraded?: boolean;
  reason?: string;
  pe?: number | null;
  pb?: number | null;
  turnover_pct?: number | null;
  volume_ratio?: number | null;
  us_positioning?: {
    short_percent_of_float?: number | null;
    held_percent_institutions?: number | null;
    held_percent_insiders?: number | null;
    note?: string;
  };
}
interface MarketStructure {
  symbol?: string;
  market?: string;
  degraded?: boolean;
  technical?: MarketStructureTechnical;
  chip?: MarketStructureChip;
  flow?: MarketStructureFlow;
  snapshot?: MarketStructureSnapshot;
}

const money = (v?: number, market?: string) => {
  const prefix = market === "HK" ? "HK$" : market === "US" ? "$" : "¥";
  return `${prefix}${(v ?? 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
};
const pct = (v?: number) => `${(v ?? 0) >= 0 ? "+" : ""}${(v ?? 0).toFixed(2)}%`;
const changeCls = (cp?: number) => (cp ?? 0) >= 0 ? "up" : "down";
const ratioPct = (v?: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const numOrDash = (v?: number | null, digits = 2) => (v == null ? "—" : v.toFixed(digits));
const maStackLabel = (stack?: string | null) =>
  stack === "bullish" ? "多头排列" : stack === "bearish" ? "空头排列" : stack === "mixed" ? "交叉纠缠" : "—";

export default function Research() {
  const { stock, setStock, appDataCache, globalLoading } = useAppState();
  const { showToast } = useToast();
  const [input, setInput] = useState("");
  const [context, setContext] = useState<StockContext | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [intel, setIntel] = useState<IntelItem[]>([]);
  const [financial, setFinancial] = useState<FinancialItem[]>([]);
  const [marketStructure, setMarketStructure] = useState<MarketStructure | null>(null);
  const [followups, setFollowups] = useState<FollowupItem[]>([]);
  const [researchResult, setResearchResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [researchBusy, setResearchBusy] = useState(false);
  const [historyRangeDays, setHistoryRangeDays] = useState<7 | 30 | 90>(30);
  const [stockCacheSymbol, setStockCacheSymbol] = useState<string | null>(null);
  const [wlGroup, setWlGroup] = useState("默认");
  const [wlGroups, setWlGroups] = useState<{name:string;color:string}[]>([]);
  const [showWlGroup, setShowWlGroup] = useState(false);

  // search autocomplete
  const [searchResults, setSearchResults] = useState<StockSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [showDropdown, setShowDropdown] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (stock) setInput(stock);
    setShowDropdown(false);
  }, [stock]);

  // Populate from global cache once initial load completes
  useEffect(() => {
    if (globalLoading || !stock || !stock.trim()) return;
    const cache = appDataCache.current;
    if (cache.stockContext && stockCacheSymbol !== stock) {
      setContext(cache.stockContext as StockContext); // eslint-disable-line react-hooks/set-state-in-effect
      setHistory((cache.stockHistory as { items: HistoryItem[] })?.items ?? []);  
      setIntel((cache.stockIntel as { items: IntelItem[] })?.items ?? []);  
      setFinancial((cache.stockFinancial as { items: FinancialItem[] })?.items ?? []);  
      setFollowups((cache.stockFollowups as { items: FollowupItem[] })?.items ?? []);  
      setStockCacheSymbol(stock);
      setLoading(false);
      void apiGet<MarketStructure>(`/api/stocks/${encodeURIComponent(stock)}/market-structure`)
        .then(setMarketStructure)
        .catch(() => setMarketStructure(null));
    }
  }, [globalLoading, appDataCache, stock, stockCacheSymbol]);

  // Reload stock data when stock changes (user selected from search)
  useEffect(() => {
    if (globalLoading || !stock || !stock.trim()) return;
    if (stockCacheSymbol !== stock) {
      // eslint-disable-next-line react-hooks/immutability
      void loadAll();
    }
  }, [stock]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- debounced search ---
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = input.trim();
    if (!q) { setSearchResults([]); setShowDropdown(false); return; } // eslint-disable-line react-hooks/set-state-in-effect
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await apiGet<{ items: StockSearchResult[] }>(`/api/stocks/search?q=${encodeURIComponent(q)}`);
        const items = (res.items ?? []).slice(0, 20);
        setSearchResults(items);
        setSelectedIdx(0);
        setShowDropdown(items.length > 0);
      } catch {
        setSearchResults([]);
        setShowDropdown(false);
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [input]);

  // close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // --- search helpers ---

  const selectStock = (symbol: string) => {
    setShowDropdown(false);
    setSearchResults([]);
    setStock(symbol);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showDropdown || searchResults.length === 0) {
      if (e.key === "Enter" && input.trim()) {
        setStock(input.trim());
      }
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setSelectedIdx((prev) => Math.min(prev + 1, searchResults.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setSelectedIdx((prev) => Math.max(prev - 1, 0));
        break;
      case "Enter":
        e.preventDefault();
        selectStock(searchResults[selectedIdx].symbol);
        break;
      case "Escape":
        setShowDropdown(false);
        break;
    }
  };

  const loadAll = useCallback(async () => {
    setLoading(true); setError(null); setContext(null); setMarketStructure(null);
    try {
      const [ctx, hist, int, fin, ms, fu] = await Promise.all([
        apiGet<StockContext>(`/api/stocks/${encodeURIComponent(stock)}/context`),
        apiGet<{ items: HistoryItem[] }>(`/api/stocks/${encodeURIComponent(stock)}/history?days=90`).then((r) => r.items).catch(() => []),
        apiGet<{ items: IntelItem[] }>(`/api/stocks/${encodeURIComponent(stock)}/intel`).then((r) => r.items).catch(() => []),
        apiGet<{ items: FinancialItem[] }>(`/api/stocks/${encodeURIComponent(stock)}/financial`).then((r) => r.items).catch(() => []),
        apiGet<MarketStructure>(`/api/stocks/${encodeURIComponent(stock)}/market-structure`).catch(() => null),
        apiGet<{ items: FollowupItem[] }>("/api/portfolio/copilot/followups").then((r) => r.items ?? []).catch(() => []),
      ]);
      setContext(ctx);
      setHistory(sortHistoryNewestFirst(hist));
      setIntel(sortIntelNewestFirst(int));
      setFinancial(sortFinancialNewestFirst(fin));
      setMarketStructure(ms);
      setFollowups(fu);
      setStockCacheSymbol(stock);
    } catch (err) { setError(err instanceof Error ? err.message : "加载个股研究失败"); } finally { setLoading(false); }
  }, [stock]);

  // --- handlers ---

  const handleResearch = async () => {
    setResearchBusy(true); setResearchResult(null);
    try {
      const res = await apiPost<{ status?: string; task?: { task_id?: string }; report?: { report_id?: string }; message?: string; summary?: string }>(
        `/api/stocks/${encodeURIComponent(stock)}/research`, {}
      );
      
      if (res.status === "exists") {
        showToast(res.message ?? "任务进行中，请稍后查看", "info");
        setResearchResult(`⏳ ${res.message ?? "任务进行中，请稍后查看"}`);
      } else if (res.status === "recent") {
        showToast(res.message ?? "报告已存在", "info");
        setResearchResult(`ℹ️ ${res.message ?? "报告已存在"}`);
      } else if (res.status === "created") {
        showToast(res.message ?? "深研任务已创建，预计 2-3 分钟完成", "success");
        setResearchResult(`✅ ${res.message ?? "深研任务已创建"}`);
        await loadAll();
      } else {
        showToast(`研究任务已提交: ${res.task?.task_id}`, "success");
        setResearchResult(res.summary ?? `研究任务已提交: ${res.task?.task_id}`);
      }
    } catch (err) { 
      const errorMsg = err instanceof Error ? err.message : "研究请求失败";
      showToast(errorMsg, "error");
      setResearchResult(errorMsg);
    } finally { 
      setResearchBusy(false); 
    }
  };

  const handleWatchlistToggle = async () => {
    if (!context) return;
    try {
      if (context.relation?.in_watchlist) {
        await apiDelete(`/api/watchlist/items/${encodeURIComponent(stock)}`);
        const ctx = await apiGet<StockContext>(`/api/stocks/${encodeURIComponent(stock)}/context`);
        setContext(ctx);
      } else {
        await apiPost("/api/watchlist/items", { symbol: stock, name: context.name ?? stock, group: wlGroup });
        setShowWlGroup(false);
        const ctx = await apiGet<StockContext>(`/api/stocks/${encodeURIComponent(stock)}/context`);
        setContext(ctx);
      }
    } catch (err) { console.error("watchlist toggle failed", err); }
  };

  return (
    <PageContainer>
      <div className="page-stack">
        {/* 头部 = 搜索框 + 动作(页名在 func-head;设计稿 02) */}
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <div className="stock-search" ref={wrapperRef} style={{ flex: 1 }}>
          <div className="search-wrapper">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="搜索个股名称或代码，如 寒武纪 / 600519 / AAPL"
              onKeyDown={handleKeyDown}
              onFocus={() => { if (searchResults.length > 0) setShowDropdown(true); }}
            />
            {searching && <span className="search-spinner" />}
          </div>
          {showDropdown && searchResults.length > 0 && (
            <div className="search-dropdown">
              {searchResults.map((r, i) => (
                <div
                  key={r.symbol}
                  className={`search-item${i === selectedIdx ? " active" : ""}`}
                  onMouseDown={() => selectStock(r.symbol)}
                  onMouseEnter={() => setSelectedIdx(i)}
                >
                  <div className="stock-icon default" style={{ width: 32, height: 32, fontSize: 12 }}>
                    {r.symbol.charAt(0)}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className="search-item-code">{r.symbol}</span>
                      <span className="search-item-market">{r.market ?? ""}</span>
                    </div>
                    <div style={{ fontSize: 12, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {r.name} {r.sector ? `· ${r.sector}` : ""}
                    </div>
                  </div>
                  {r.price != null && (
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, fontFamily: "var(--mono)" }}>
                        {money(r.price, r.market)}
                      </div>
                      {r.change_pct != null && (
                        <div style={{ fontSize: 11, fontWeight: 600, color: r.change_pct >= 0 ? "var(--green)" : "var(--red)" }}>
                          {r.change_pct >= 0 ? "↑" : "↓"} {pct(r.change_pct)}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          <button className="small primary" disabled={researchBusy} onClick={() => void handleResearch()} type="button">{researchBusy ? "生成中…" : "深研报告"}</button>
          {stock && <AskAiButton prompt={`深入分析 ${stock} 的投资价值与主要风险`} symbol={stock} />}
        </div>
        </div>

        {!stock ? (
          <div className="panel"><div className="panel-body" style={{ textAlign: "center", padding: "40px 20px", color: "var(--muted)" }}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ opacity: 0.6, marginBottom: 8 }}>
              <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
            </svg>
            <div style={{ fontSize: 13, color: "var(--ink)", fontWeight: 600 }}>按漏斗做研究</div>
            <div style={{ fontSize: 12, marginTop: 6, lineHeight: 1.7 }}>
              {RESEARCH_FUNNEL.map((item) => (
                <div key={item.step}>{item.step} · {item.hint}</div>
              ))}
            </div>
            <div style={{ fontSize: 11, color: "var(--faint, var(--muted))", marginTop: 10 }}>搜一只股票，或点示例开始</div>
            <div className="funnel-chips" style={{ marginTop: 10, justifyContent: "center" }}>
              {FUNNEL_EXAMPLE_STOCKS.map((item) => (
                <button
                  key={item.symbol}
                  type="button"
                  className="followup-chip"
                  onClick={() => selectStock(item.symbol)}
                >
                  {item.name}
                </button>
              ))}
            </div>
          </div></div>
        ) : loading && !context ? (
          <section className="detail-grid">
            <div className="page-stack"><PanelSkeleton /><PanelSkeleton /><PanelSkeleton /></div>
            <div className="page-stack"><PanelSkeleton /><KpiSkeleton count={3} /><PanelSkeleton /></div>
          </section>
        ) : null}
        {!loading && error && !context ? <ErrorMessage message={error} /> : null}

        {context ? (
          <div className="fade-in">
            <div className="stock-hero">
              <div className="stock-hero-header">
                <div className="stock-brand">
                  <div className="stock-icon-lg">{context.symbol.charAt(0)}</div>
                  <div className="stock-title">
                    <h1>{context.name ?? context.symbol}</h1>
                    <div className="stock-subtitle">
                      {context.symbol} · {context.sector ?? context.industry ?? ""} · {context.market ?? ""}
                      <span className="stock-market-tag">{context.market ?? "未知"}</span>
                    </div>
                  </div>
                </div>
                <div className="hero-actions">
                  {context.relation?.in_watchlist ? (
                    <button type="button" className="watchlist-btn on" onClick={() => void handleWatchlistToggle()}>★ 已自选</button>
                  ) : showWlGroup ? (
                    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                      <select value={wlGroup} onChange={(e) => setWlGroup(e.target.value)}
                        style={{ height: 28, fontSize: 11, border: "1px solid var(--line)", borderRadius: 6, padding: "0 6px" }}>
                        {wlGroups.map(g => <option key={g.name} value={g.name}>{g.name}</option>)}
                      </select>
                      <button type="button" className="watchlist-btn" onClick={() => void handleWatchlistToggle()}>确认</button>
                      <button type="button" className="watchlist-btn" onClick={() => setShowWlGroup(false)}>取消</button>
                    </span>
                  ) : (
                    <button type="button" className="watchlist-btn" onClick={async () => {
                      const gs = await apiGet<{name:string;color:string}[]>("/api/watchlist/groups").catch(() => []);
                      setWlGroups(gs.length > 0 ? gs : [{name:"默认",color:"#6366f1"}]);
                      setWlGroup(gs[0]?.name ?? "默认");
                      setShowWlGroup(true);
                    }}>☆ 添加自选</button>
                  )}
                </div>
              </div>
              <div className="stock-stats">
                <div className="stock-stat">
                  <span className="stock-stat-label">现价</span>
                  <span className="stock-stat-value">{money(context.price?.last, context.market)}</span>
                  <span className={`stock-stat-change ${changeCls(context.price?.change_pct)}`}>
                    {context.price?.change_pct && context.price.change_pct >= 0 ? "↑" : "↓"} {pct(context.price?.change_pct)}
                  </span>
                </div>
                <div className="stock-stat">
                  <span className="stock-stat-label">持仓</span>
                  <span className="stock-stat-value">{context.holding?.quantity ?? 0} 股</span>
                  <span className="stock-stat-change neutral">{money(context.holding?.market_value, context.market)}</span>
                </div>
                <div className="stock-stat">
                  <span className="stock-stat-label">权重</span>
                  <span className="stock-stat-value">{pct(context.holding?.weight_pct)}</span>
                  {context.holding && (
                    <div className="weight-bar" style={{ width: 80, marginTop: 4 }}>
                      <div className="weight-bar-fill" style={{ width: `${Math.min(context.holding.weight_pct ?? 0, 100)}%` }} />
                    </div>
                  )}
                </div>
                <div className="stock-stat">
                  <span className="stock-stat-label">今日涨跌</span>
                  <span className={`stock-stat-value ${changeCls(context.price?.change_pct)}`}>{pct(context.price?.change_pct)}</span>
                  <span className="stock-stat-change neutral">实时数据</span>
                </div>
              </div>
            </div>

            {context.ai_state && (
              <div className="panel" style={{ marginTop: 16 }}>
                <div className="panel-header">
                  <div className="panel-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/><circle cx="12" cy="12" r="3"/>
                    </svg>
                    AI 观点
                    {context.latest_report?.generated_at && (
                      <span className="panel-badge">{context.latest_report.generated_at.slice(5, 10)} 复评</span>
                    )}
                  </div>
                  <AskAiButton prompt={`复评 ${context.symbol} 的 AI 观点:当前评分与立场是否仍成立?`} symbol={context.symbol} label="复评" />
                </div>
                <div className="panel-body">
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
                    <div><div className="muted" style={{ fontSize: 11 }}>评分</div><div className="num" style={{ fontSize: 16, fontWeight: 700 }}>{context.ai_state.score ?? "-"}</div></div>
                    <div><div className="muted" style={{ fontSize: 11 }}>立场</div><div style={{ fontSize: 13, fontWeight: 600 }}>{context.ai_state.stance ?? "-"}</div></div>
                    <div><div className="muted" style={{ fontSize: 11 }}>置信</div><div style={{ fontSize: 13, fontWeight: 600 }}>{context.ai_state.confidence ?? "-"}</div></div>
                    <div><div className="muted" style={{ fontSize: 11 }}>风险标签</div><div style={{ fontSize: 13, fontWeight: 600, color: context.ai_state.risk_label ? "var(--red)" : undefined }}>{context.ai_state.risk_label ?? "无"}</div></div>
                  </div>
                </div>
              </div>
            )}

            <div className="two-col" style={{ gap: 24 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                <div className="panel">
                  <div className="panel-header">
                    <div className="panel-title">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/>
                      </svg>
                      历史走势
                      <span className="panel-badge">{historyRangeDays}日</span>
                    </div>
                  </div>
                  <div className="panel-body">
                    {history.length === 0 ? (
                      <div className="muted">暂无历史数据</div>
                    ) : (
                      <>
                        <StockHistoryChart
                          items={history}
                          market={context.market}
                          rangeDays={historyRangeDays}
                          onRangeChange={setHistoryRangeDays}
                        />
                        <table style={{ marginTop: 16 }}>
                          <thead>
                            <tr><th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th><th>涨跌</th></tr>
                          </thead>
                          <tbody>
                            {history.slice(0, 5).map((h, idx, rows) => {
                              // 列表按日期从新到旧；涨跌 = 相对上一交易日（更旧的一条）
                              const prevItem = idx < rows.length - 1 ? rows[idx + 1] : null;
                              const prevClose = prevItem?.close ?? h.open;
                              const change = prevClose ? ((h.close ?? 0) - prevClose) / prevClose * 100 : 0;
                              return (
                                <tr key={h.date ?? h.day}>
                                  <td>{h.date ?? `T+${h.day}`}</td>
                                  <td className="num">{money(h.open, context.market)}</td>
                                  <td className="num">{money(h.high, context.market)}</td>
                                  <td className="num">{money(h.low, context.market)}</td>
                                  <td className="num">{money(h.close, context.market)}</td>
                                  <td className={`num ${change >= 0 ? "up" : "down"}`}>{change >= 0 ? "+" : ""}{change.toFixed(2)}%</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </>
                    )}
                  </div>
                </div>

                <MarketStructurePanel data={marketStructure} market={context.market} />

                <div className="panel">
                  <div className="panel-header">
                    <div className="panel-title">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14,2 14,8 20,8"/>
                      </svg>
                      深研结果
                    </div>
                    <button className="small primary" disabled={researchBusy} onClick={() => void handleResearch()} type="button">
                      {researchBusy ? "生成中…" : "重新生成"}
                    </button>
                  </div>
                  <div className="panel-body">
                    {researchResult ? (
                      <div className="research-report">
                        <div className="research-report-header">
                          <div className="research-report-conclusion">
                            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>投资结论</div>
                            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--blue)" }}>
                              {researchResult.includes("增持") ? "增持" : researchResult.includes("减持") ? "减持" : "观望"}
                            </div>
                          </div>
                          <div className="research-report-confidence">
                            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>置信度</div>
                            <div style={{ fontSize: 18, fontWeight: 700 }}>中</div>
                          </div>
                        </div>
                        <div className="research-report-content">
                          <Markdown text={researchResult} />
                        </div>
                      </div>
                    ) : (
                      <div className="muted">点击「生成深研报告」开始分析</div>
                    )}
                  </div>
                </div>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                <div className="panel">
                  <div className="panel-header">
                    <div className="panel-title">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                      </svg>
                      新闻/公告证据
                      <span className="panel-badge">{intel.length} 条</span>
                    </div>
                  </div>
                  <div className="panel-body">
                    {intel.length === 0 ? (
                      <div className="muted">暂无情报</div>
                    ) : intel.slice(0, 5).map((item, i) => (
                      <div key={i} className="tl-item">
                        <span className="tl-time">{(item.published_at ?? item.updated_at ?? "").slice(5, 10) || "—"}</span>
                        <div className="tl-body">
                          <div className="tl-title">{item.title ?? "未命名情报"}</div>
                          <div className="tl-desc">{item.summary ?? "暂无摘要"}</div>
                          {item.source && <div className="tl-src">来源: {item.source}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {financial.length > 0 && (
                  <div className="panel">
                    <div className="panel-header">
                      <div className="panel-title">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <rect x="3" y="3" width="7" height="7" rx="1"/>
                          <rect x="14" y="3" width="7" height="7" rx="1"/>
                          <rect x="3" y="14" width="7" height="7" rx="1"/>
                          <rect x="14" y="14" width="7" height="7" rx="1"/>
                        </svg>
                        财务数据
                        <span className="panel-badge">近{financial.length}期</span>
                      </div>
                    </div>
                    <div className="panel-body">
                      <div className="financial-chart">
                        {financial.slice(0, 4).map((item, i) => {
                          const revs = financial.slice(0, 4).map((x) => x.revenue ?? 0);
                          const mx = Math.max(...revs) || 1;
                          return (
                            <div key={i} className="financial-bar">
                              <div className="financial-bar-fill revenue" style={{ height: `${Math.max(((item.revenue ?? 0) / mx) * 100, 5)}%` }} />
                              <span className="financial-bar-label">{item.report_date?.slice(5, 7) ?? `Q${i + 1}`}</span>
                            </div>
                          );
                        })}
                      </div>
                      <table>
                        <thead>
                          <tr><th>报告期</th><th>营收</th><th>净利润</th><th>类型</th></tr>
                        </thead>
                        <tbody>
                          {financial.slice(0, 4).map((item, i) => (
                            <tr key={i}>
                              <td>{item.report_date ?? "未知"}</td>
                              <td className="num">{money(item.revenue, context.market)}</td>
                              <td className={`num ${(item.profit ?? 0) >= 0 ? "up" : "down"}`}>{money(item.profit, context.market)}</td>
                              <td><span className="tag">{item.report_type === "annual" ? "年报" : item.report_type === "quarterly" ? "季报" : item.report_type}</span></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                <div className="panel">
                  <div className="panel-header">
                    <div className="panel-title">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="10"/>
                        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
                        <line x1="12" y1="17" x2="12.01" y2="17"/>
                      </svg>
                      AI 追问建议
                    </div>
                  </div>
                  <div className="panel-body">
                    <div className="followup-grid">
                      {followups.length === 0 ? (
                        <div className="muted">暂无追问建议</div>
                      ) : followups.map((f, i) => (
                        <button key={i} className="followup-chip" type="button" title={f.prompt}>
                          {f.label ?? f.action ?? f.prompt}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </PageContainer>
  );
}

function MarketStructurePanel({ data, market }: { data: MarketStructure | null; market?: string }) {
  if (!data) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title">市场结构</div>
        </div>
        <div className="panel-body"><div className="muted">暂无市场结构数据</div></div>
      </div>
    );
  }
  const chip = data.chip;
  const tech = data.technical;
  const flow = data.flow;
  const snap = data.snapshot;
  const hasChip = Boolean(chip && !chip.degraded && (chip.profit_ratio != null || chip.market_avg_cost != null));
  const title = market === "CN" ? "市场结构" : "市场结构（非筹码）";
  const profit = chip?.profit_ratio;
  const trapped = chip?.trapped_ratio;
  const profitPct = profit != null ? Math.max(0, Math.min(100, profit * 100)) : 0;
  const trappedPct = trapped != null ? Math.max(0, Math.min(100, trapped * 100)) : Math.max(0, 100 - profitPct);

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 3v18h18"/>
            <path d="M7 14l4-4 4 4 5-6"/>
          </svg>
          {title}
          {tech?.as_of && <span className="panel-badge">{tech.as_of}</span>}
        </div>
      </div>
      <div className="panel-body">
        {hasChip ? (
          <div className="ms-chip">
            <div className="ms-chip-meta">
              <span>现价 {numOrDash(tech?.last)} vs 平均成本 {numOrDash(chip?.market_avg_cost)}</span>
              {chip?.price_vs_avg_cost_pct != null && (
                <span className={chip.price_vs_avg_cost_pct >= 0 ? "up" : "down"}>
                  {pct(chip.price_vs_avg_cost_pct)}
                </span>
              )}
            </div>
            <div className="ms-chip-bar" title="获利 / 套牢">
              <div className="ms-chip-profit" style={{ width: `${profitPct}%` }} />
              <div className="ms-chip-trapped" style={{ width: `${trappedPct}%` }} />
            </div>
            <div className="ms-chip-legend">
              <span className="up">获利 {ratioPct(profit)}</span>
              <span className="down">套牢 {ratioPct(trapped)}</span>
              {chip?.cost_90_low != null && chip?.cost_90_high != null && (
                <span className="muted">90% 成本 {numOrDash(chip.cost_90_low)}–{numOrDash(chip.cost_90_high)}</span>
              )}
            </div>
            {chip?.quality === "low" && (
              <div className="ms-quality-warn">筹码质量偏低（次新/无量/涨停），勿据此标高置信度</div>
            )}
          </div>
        ) : (
          <div className="ms-degraded">
            {chip?.reason || "本市场无筹码数据"}
            {chip?.proxy?.vwap_20d != null && (
              <span className="muted"> · 近20日均价 {numOrDash(chip.proxy.vwap_20d)}（非获利盘）</span>
            )}
          </div>
        )}

        <div className="ms-grid">
          <div>
            <div className="muted" style={{ fontSize: 11 }}>均线</div>
            <div>{maStackLabel(tech?.ma_stack)}</div>
            <div className="muted" style={{ fontSize: 11 }}>MA5 {numOrDash(tech?.ma5)} / MA20 {numOrDash(tech?.ma20)}</div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11 }}>RSI14</div>
            <div className="num">{numOrDash(tech?.rsi14)}</div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11 }}>量比</div>
            <div className="num">{numOrDash(tech?.volume_ratio, 3)}</div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11 }}>支撑 / 阻力（近20日）</div>
            <div className="num">{numOrDash(tech?.support_20)} / {numOrDash(tech?.resistance_20)}</div>
          </div>
        </div>
        {tech?.degraded && <div className="ms-degraded">{tech.reason}</div>}
        {tech?.volume_note && <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>{tech.volume_note}</div>}

        {market === "CN" && (
          flow?.degraded ? (
            <div className="ms-degraded" style={{ marginTop: 10 }}>{flow.reason}</div>
          ) : (
            <div className="ms-flow">
              主力净流入 1日 {numOrDash(flow?.main_net_1d)} · 5日 {numOrDash(flow?.main_net_5d)}
              {flow?.as_of && <span className="muted"> · {flow.as_of}</span>}
            </div>
          )
        )}

        {snap?.us_positioning && !snap.degraded && (
          <div className="ms-flow">
            空头占流通 {ratioPct(snap.us_positioning.short_percent_of_float)}
            {" · "}机构持股 {ratioPct(snap.us_positioning.held_percent_institutions)}
            <div className="muted" style={{ fontSize: 11 }}>{snap.us_positioning.note}</div>
          </div>
        )}
        {snap?.degraded && <div className="ms-degraded">{snap.reason}</div>}
      </div>
    </div>
  );
}
