import { useCallback, useEffect, useRef, useState } from "react";
import { apiDelete, apiGet, apiPost } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, PanelSkeleton, KpiSkeleton } from "@/components/ui/Loading";
import { Pagination } from "@/components/ui/Pagination";
import { formatTimeAgo } from "@/utils/format";
import { useAppState } from "@/hooks/useAppState";
import { useToast } from "@/hooks/useToast";
import { MarkdownRenderer as Markdown } from "@/components/features/MarkdownRenderer";

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
}

interface HistoryItem { date?: string; day?: number; open?: number; high?: number; low?: number; close?: number; volume?: number }
interface IntelItem { title?: string; summary?: string; source?: string; published_at?: string; updated_at?: string }
interface FinancialItem { report_date?: string; report_type?: string; revenue?: number; profit?: number; total_assets?: number; total_liabilities?: number }
interface FollowupItem { label?: string; prompt?: string; action?: string }

const money = (v?: number, market?: string) => {
  const prefix = market === "HK" ? "HK$" : market === "US" ? "$" : "¥";
  return `${prefix}${(v ?? 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
};
const pct = (v?: number) => `${(v ?? 0) >= 0 ? "+" : ""}${(v ?? 0).toFixed(2)}%`;
const changeCls = (cp?: number) => (cp ?? 0) >= 0 ? "up" : "down";

export default function Research() {
  const { stock, setStock, appDataCache, globalLoading } = useAppState();
  const { showToast } = useToast();
  const [input, setInput] = useState("");
  const [context, setContext] = useState<StockContext | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [intel, setIntel] = useState<IntelItem[]>([]);
  const [financial, setFinancial] = useState<FinancialItem[]>([]);
  const [followups, setFollowups] = useState<FollowupItem[]>([]);
  const [researchResult, setResearchResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [researchBusy, setResearchBusy] = useState(false);
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
      setHistory((cache.stockHistory as { items: HistoryItem[] })?.items ?? []); // eslint-disable-line react-hooks/set-state-in-effect
      setIntel((cache.stockIntel as { items: IntelItem[] })?.items ?? []); // eslint-disable-line react-hooks/set-state-in-effect
      setFinancial((cache.stockFinancial as { items: FinancialItem[] })?.items ?? []); // eslint-disable-line react-hooks/set-state-in-effect
      setFollowups((cache.stockFollowups as { items: FollowupItem[] })?.items ?? []); // eslint-disable-line react-hooks/set-state-in-effect
      setStockCacheSymbol(stock);
      setLoading(false);
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
    setLoading(true); setError(null); setContext(null);
    try {
      const [ctx, hist, int, fin, fu] = await Promise.all([
        apiGet<StockContext>(`/api/stocks/${encodeURIComponent(stock)}/context`),
        apiGet<{ items: HistoryItem[] }>(`/api/stocks/${encodeURIComponent(stock)}/history`).then((r) => r.items).catch(() => []),
        apiGet<{ items: IntelItem[] }>(`/api/stocks/${encodeURIComponent(stock)}/intel`).then((r) => r.items).catch(() => []),
        apiGet<{ items: FinancialItem[] }>(`/api/stocks/${encodeURIComponent(stock)}/financial`).then((r) => r.items).catch(() => []),
        apiGet<{ items: FollowupItem[] }>("/api/portfolio/copilot/followups").then((r) => r.items ?? []).catch(() => []),
      ]);
      setContext(ctx); setHistory(hist); setIntel(int); setFinancial(fin); setFollowups(fu);
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
        <section className="page-hero">
          <div>
            <h2>个股信息与深研</h2>
            <p>全局搜索进入这里，展示 StockContext，并可生成深研任务和报告。</p>
          </div>
          <div className="hero-actions">
            <button className="primary" disabled={researchBusy} onClick={() => void handleResearch()} type="button">{researchBusy ? "生成中…" : "生成深研报告"}</button>
          </div>
        </section>

        {/* autocomplete search */}
        <div className="stock-search" ref={wrapperRef}>
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

        {loading && !context ? (
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

            <div className="kpi-grid" style={{ marginTop: 24 }}>
              <div className="kpi-card">
                <div className="kpi-header">
                  <span className="kpi-label">持仓数量</span>
                  <div className="kpi-icon blue">📊</div>
                </div>
                <div className="kpi-value">{context.holding?.quantity ?? 0}</div>
                <div className="kpi-change neutral">股</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-header">
                  <span className="kpi-label">持仓市值</span>
                  <div className="kpi-icon green">💰</div>
                </div>
                <div className="kpi-value">{money(context.holding?.market_value, context.market)}</div>
                <div className="kpi-change neutral">当前价值</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-header">
                  <span className="kpi-label">权重占比</span>
                  <div className="kpi-icon amber">⚖️</div>
                </div>
                <div className="kpi-value">{pct(context.holding?.weight_pct)}</div>
                <div className="kpi-change neutral">组合占比</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-header">
                  <span className="kpi-label">持仓盈亏</span>
                  <div className="kpi-icon red">📈</div>
                </div>
                <div className="kpi-value">{context.holding?.pnl_pct != null ? pct(context.holding.pnl_pct) : "N/A"}</div>
                <div className={`kpi-change ${(context.holding?.pnl_pct ?? 0) >= 0 ? "up" : "down"}`}>
                  {(context.holding?.pnl_pct ?? 0) >= 0 ? "↑ 盈利" : "↓ 亏损"}
                </div>
              </div>
            </div>

            <div className="two-col" style={{ gap: 24 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                <div className="panel">
                  <div className="panel-header">
                    <div className="panel-title">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/>
                      </svg>
                      历史走势
                      <span className="panel-badge">30日</span>
                    </div>
                    <div className="time-range-btns">
                      <button className="time-range-btn">1周</button>
                      <button className="time-range-btn active">1月</button>
                      <button className="time-range-btn">3月</button>
                    </div>
                  </div>
                  <div className="panel-body">
                    {history.length === 0 ? (
                      <div className="muted">暂无历史数据</div>
                    ) : (
                      <>
                        <svg viewBox="0 0 600 100" style={{ width: "100%", height: 100, marginBottom: 16 }}>
                          {(() => {
                            const data = history.slice(-30);
                            const closes = data.map(x => x.close ?? 0);
                            const mx = Math.max(...closes); const mn = Math.min(...closes); const rng = mx - mn || 1;
                            const points = data.map((h, i) => `${(i / (data.length - 1)) * 580 + 10},${100 - ((h.close ?? 0) - mn) / rng * 80 - 10}`).join(" ");
                            return <polyline points={points} fill="none" stroke="var(--blue)" strokeWidth="2" />;
                          })()}
                        </svg>
                        <table>
                          <thead>
                            <tr><th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th><th>涨跌</th></tr>
                          </thead>
                          <tbody>
                            {history.slice(0, 5).map((h, idx) => {
                              // 计算涨跌：当前收盘价 vs 前一天收盘价
                              const prevItem = idx < history.length - 1 ? history[idx + 1] : null;
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
                      <div key={i} className="intel-item">
                        <div className={`intel-dot ${i === 0 ? "warning" : i === 1 ? "info" : "success"}`} />
                        <div className="intel-content">
                          <div className="intel-title">{item.title ?? "未命名情报"}</div>
                          <div className="intel-desc">{item.summary ?? "暂无摘要"}</div>
                        </div>
                        <div className="intel-time">{item.published_at ?? item.updated_at ?? ""}</div>
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
