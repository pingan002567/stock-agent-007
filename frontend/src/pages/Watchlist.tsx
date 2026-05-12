import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, apiDelete } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, TableSkeleton, EmptyState } from "@/components/ui/Loading";
import { useAppState } from "@/hooks/useAppState";
import { inferMarket, marketMoney, pct, changeCls } from "@/utils/market";

interface WatchlistItem { symbol: string; name?: string; group?: string; tags?: string[]; monitored?: boolean; ai_score?: number; market?: string; price?: { last?: number; change_pct?: number } }
interface SearchHit { symbol: string; name: string; market: string }
interface WatchlistGroup { name: string; color: string; sort_order: number }

export default function Watchlist() {
  const { setStock, appDataCache, globalLoading } = useAppState();
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"cards" | "table">("cards");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchHit[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  const [groups, setGroups] = useState<WatchlistGroup[]>([]);
  const [groupEditor, setGroupEditor] = useState<string | null>(null);
  const [groupEditName, setGroupEditName] = useState("");
  const [groupEditColor, setGroupEditColor] = useState("#6366f1");

  // Populate from global cache once initial load completes, then always refresh
  useEffect(() => {
    if (globalLoading) return;
    const cache = appDataCache.current;
    if (cache.watchlist) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setItems(cache.watchlist as WatchlistItem[]);
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/immutability
    void loadAll();
  }, [globalLoading, appDataCache]);

  // Click outside to close search dropdown
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setSearchOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const filteredItems = useMemo(() => {
    if (!activeGroup) return items;
    return items.filter(i => (i.group ?? "默认") === activeGroup);
  }, [items, activeGroup]);

  const groupedItems = useMemo(() => {
    const source = filteredItems;
    const map = new Map<string, WatchlistItem[]>();
    for (const item of source) {
      const g = item.group ?? "默认";
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(item);
    }
    return Array.from(map.entries());
  }, [filteredItems]);

  const loadAll = async () => {
    setError(null);
    const hasData = itemsRef.current.length > 0;
    if (!hasData) setLoading(true);
    try {
      const response = await apiGet<WatchlistItem[]>("/api/watchlist");
      setItems(response);
      appDataCache.current.watchlist = response; // eslint-disable-line react-hooks/immutability
      const gs = await apiGet<WatchlistGroup[]>("/api/watchlist/groups").catch(() => [] as WatchlistGroup[]);
      setGroups(gs);
    } catch (err) { setError(err instanceof Error ? err.message : "加载自选失败"); } finally { setLoading(false); }
  };

  const moveItem = async (symbol: string, dir: number) => {
    const idx = items.findIndex(i => i.symbol === symbol);
    if (idx < 0) return;
    const newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= items.length) return;
    const reordered = [...items];
    const [moved] = reordered.splice(idx, 1);
    reordered.splice(newIdx, 0, moved);
    setItems(reordered);
    await apiPost("/api/watchlist/reorder", { items: reordered.map((it, i) => ({ symbol: it.symbol, position: i })) });
  };

  const mgr = useMemo(() => ({
    open: groupEditor === "manage",
    openPanel() { setGroupEditor("manage"); setDraftGroups(groups.map(g => ({...g}))); setDragIdx(null); },
    closePanel() { setGroupEditor(null); setDraftGroups([]); setDragIdx(null); },
  }), [groupEditor, groups]);

  const [draftGroups, setDraftGroups] = useState<WatchlistGroup[]>([]);
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  const handleSaveGroups = async () => {
    const toDelete = groups.filter(g => !draftGroups.some(d => d.name === g.name));
    for (const g of toDelete) await apiDelete(`/api/watchlist/groups/${encodeURIComponent(g.name)}`);
    for (const g of draftGroups) {
      await fetch(`/api/watchlist/groups/${encodeURIComponent(g.name)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ color: g.color, sort_order: draftGroups.indexOf(g) }),
      }).catch(() => {});
    }
    mgr.closePanel();
    loadAll();
    setActiveGroup(null);
  };

  const handleSearch = useCallback((q: string) => {
    setSearchQuery(q);
    if (!q.trim()) { setSearchResults([]); setSearchOpen(false); return; }
    const lower = q.trim().toLowerCase();
    const hits = items.filter(i =>
      i.symbol.toLowerCase().includes(lower) ||
      (i.name ?? "").toLowerCase().includes(lower) ||
      (i.group ?? "默认").toLowerCase().includes(lower)
    ).map(i => ({ symbol: i.symbol, name: i.name ?? "", market: i.market ?? inferMarket(i.symbol) }));
    setSearchResults(hits);
    setSearchOpen(true);
  }, [items]);

  const handleRemove = async (symbol: string) => { try { await apiDelete(`/api/watchlist/items/${encodeURIComponent(symbol)}`); await loadAll(); } catch { /* ignore */ } };
  const handleToggleMonitor = async (symbol: string) => { try { await apiPost(`/api/watchlist/${encodeURIComponent(symbol)}/monitor`, {}); await loadAll(); } catch { /* ignore */ } };

  const groupColors = ["var(--blue)", "var(--green)", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"];

  const maxAbsChange = useMemo(() => {
    return Math.max(1, ...items.map((item) => Math.abs(item.price?.change_pct ?? 0)));
  }, [items]);

  const renderStockRow = (item: WatchlistItem) => {
    const cp = item.price?.change_pct ?? 0;
    const barPct = (Math.abs(cp) / maxAbsChange) * 100;
    const market = inferMarket(item.symbol);
    return (
      <div key={item.symbol} style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "8px 0", borderBottom: "1px solid var(--border)",
      }}>
        {/* Symbol + Name */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <button className="link" onClick={() => setStock(item.symbol)} type="button"
              style={{ fontWeight: 700, fontSize: 14, letterSpacing: "0.3px" }}>{item.symbol}</button>
            <span className="tag" style={{
              fontSize: 9, height: 16, lineHeight: "16px", padding: "0 4px",
              background: market === "CN" ? "#e8f5e9" : market === "HK" ? "#fff3e0" : "#e3f2fd",
              color: market === "CN" ? "#2e7d32" : market === "HK" ? "#e65100" : "#1565c0",
            }}>{market}</span>
            <span style={{ fontSize: 11, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.name ?? ""}</span>
          </div>
          {/* Change bar */}
          <div className="barline" style={{ marginTop: 3 }}>
            <div className="bar" style={{ flex: 1, background: "var(--bg-light)", borderRadius: 3, height: 5 }}>
              <div style={{
                width: `${barPct}%`, height: "100%", borderRadius: 3,
                background: cp >= 0 ? "var(--red)" : "var(--green)", opacity: 0.7,
              }} />
            </div>
          </div>
        </div>

        {/* Price */}
        {item.price?.last != null && (
          <div style={{ textAlign: "right", minWidth: 70 }}>
            <div className="num" style={{ fontSize: 13, fontWeight: 600 }}>{marketMoney(item.price.last, market)}</div>
          </div>
        )}

        {/* Change % */}
        <div style={{ textAlign: "right", minWidth: 55 }}>
          <span className={`num ${changeCls(cp)}`} style={{ fontSize: 13, fontWeight: 700 }}>{pct(cp)}</span>
        </div>

        {/* Tags + Monitor + Score */}
        <div style={{ display: "flex", gap: 4, alignItems: "center", flexShrink: 0 }}>
          {(item.tags ?? []).slice(0, 1).map((t) => (
            <span key={t} className="tag" style={{ fontSize: 9, height: 18, lineHeight: "18px" }}>{t}</span>
          ))}
          <span className={`tag ${item.monitored ? "up" : ""}`} style={{ cursor: "pointer", fontSize: 9, height: 18, lineHeight: "18px" }}
            onClick={() => void handleToggleMonitor(item.symbol)}>{item.monitored ? "盯" : "静"}</span>
          <span className="num" style={{ fontSize: 10, color: "var(--muted)", minWidth: 24, textAlign: "right" }}>{item.ai_score?.toFixed(1) ?? ""}</span>
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
          <button type="button" className="ghost" style={{ height: 22, fontSize: 10, padding: "0 6px" }}
            onClick={() => setStock(item.symbol)}>研</button>
          <button className="link" style={{ color: "var(--red)", fontSize: 13, padding: "0 4px", height: 22, lineHeight: "22px" }}
            onClick={() => void handleRemove(item.symbol)} type="button">×</button>
          <button className="ghost" style={{ height: 22, fontSize: 10, padding: "0 3px", opacity: 0.5 }}
            onClick={() => moveItem(item.symbol, -1)} title="上移" type="button">▲</button>
          <button className="ghost" style={{ height: 22, fontSize: 10, padding: "0 3px", opacity: 0.5 }}
            onClick={() => moveItem(item.symbol, 1)} title="下移" type="button">▼</button>
        </div>
      </div>
    );
  };

  const renderTable = () => (
    <div className="pad">
      <table>
        <thead><tr><th style={{width:32}}>#</th><th>股票</th><th>分组</th><th>行情</th><th>涨跌</th><th>标签</th><th>盯盘</th><th>操作</th></tr></thead>
        <tbody>{filteredItems.length === 0 ? (
          <tr><td colSpan={8}><EmptyState icon="watchlist" title="暂无自选股票" description="使用上方表单添加股票到自选池" /></td></tr>
        ) : filteredItems.map((item, idx) => {
          const cp = item.price?.change_pct ?? 0;
          return (
            <tr key={item.symbol} className="row">
              <td style={{ display: "flex", flexDirection: "column", gap: 0, alignItems: "center" }}>
                <button className="ghost" style={{ height: 14, fontSize: 8, padding: 0, lineHeight: 1, opacity: 0.3 }}
                  onClick={() => moveItem(item.symbol, -1)} title="上移" type="button">▲</button>
                <span style={{ fontSize: 9, color: "var(--muted)" }}>{idx + 1}</span>
                <button className="ghost" style={{ height: 14, fontSize: 8, padding: 0, lineHeight: 1, opacity: 0.3 }}
                  onClick={() => moveItem(item.symbol, 1)} title="下移" type="button">▼</button>
              </td>
              <td>
                <button className="link" onClick={() => setStock(item.symbol)} type="button" style={{ fontWeight: 600 }}>{item.symbol}</button>
                <span className="search-item-market" style={{ marginLeft: 4 }}>{inferMarket(item.symbol)}</span>
                <div className="muted" style={{ fontSize: 11 }}>{item.name ?? ""}</div>
              </td>
              <td className="muted">{item.group ?? "默认"}</td>
              <td>{item.price?.last != null ? <span className="num">{marketMoney(item.price.last, inferMarket(item.symbol))}</span> : <span className="muted">-</span>}</td>
              <td><span className={`num ${changeCls(cp)}`} style={{ fontWeight: 600 }}>{pct(cp)}</span></td>
              <td>{(item.tags ?? []).length === 0 ? <span className="muted" style={{ fontSize: 11 }}>-</span> : (item.tags ?? []).map((t) => <span key={t} className="tag" style={{ fontSize: 10 }}>{t}</span>)}</td>
              <td><span className={`tag ${item.monitored ? "up" : ""}`} style={{ cursor: "pointer", fontSize: 10 }} onClick={() => void handleToggleMonitor(item.symbol)}>{item.monitored ? "on" : "off"}</span></td>
              <td style={{ display: "flex", gap: 4 }}>
                <button className="ghost" style={{ height: 22, fontSize: 10, padding: "0 6px" }} onClick={() => setStock(item.symbol)} type="button">研</button>
                <button className="link" style={{ color: "var(--red)", fontSize: 11 }} onClick={() => void handleRemove(item.symbol)} type="button">删</button>
              </td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );

  const renderGroupCards = () => (
    <div className="page-stack">
      {groupedItems.length === 0 ? (
        renderGroupCards()
      ) : groupedItems.map(([group, groupItems], gi) => (
        <div key={group} className="panel" style={{ borderLeft: `3px solid ${groupColors[gi % groupColors.length]}` }}>
          <div className="head" style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)" }}>
            <span className="title">{group}</span>
            <span className="sub" style={{ fontSize: 11 }}>{groupItems.length} 只股票</span>
          </div>
          <div className="pad" style={{ padding: "4px 12px" }}>
            {groupItems.map(renderStockRow)}
          </div>
        </div>
      ))}
    </div>
  );

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        <div className="market-hero">
          <div className="market-hero-header">
            <div className="market-title">
              <h1>自选股</h1>
              <p>管理您的自选股列表，实时追踪关注的股票动态。</p>
            </div>
            <div className="hero-actions">
              <button className="primary" onClick={() => void loadAll()} disabled={loading} type="button">刷新数据</button>
            </div>
          </div>
          <div className="market-stats">
            <div className="market-stat">
              <span className="market-stat-label">自选数量</span>
              <span className="market-stat-value">{items.length}</span>
              <span className="market-stat-change neutral">只股票</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">今日上涨</span>
              <span className="market-stat-value up">{items.filter(i => (i.price?.change_pct ?? 0) > 0).length}</span>
              <span className="market-stat-change up">
                ↑ {items.length > 0 ? Math.round((items.filter(i => (i.price?.change_pct ?? 0) > 0).length / items.length) * 100) : 0}%
              </span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">今日下跌</span>
              <span className="market-stat-value down">{items.filter(i => (i.price?.change_pct ?? 0) < 0).length}</span>
              <span className="market-stat-change down">
                ↓ {items.length > 0 ? Math.round((items.filter(i => (i.price?.change_pct ?? 0) < 0).length / items.length) * 100) : 0}%
              </span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">盯盘开启</span>
              <span className="market-stat-value">{items.filter(i => i.monitored).length}</span>
              <span className="market-stat-change neutral">只</span>
            </div>
          </div>
        </div>

        {groups.length > 0 && (
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                </svg>
                分组筛选
              </div>
              <button className="small" onClick={() => mgr.openPanel()} type="button">管理分组</button>
            </div>
            <div className="panel-body">
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button
                  className={`followup-chip${activeGroup === null ? " active" : ""}`}
                  onClick={() => setActiveGroup(null)}
                  style={activeGroup === null ? { background: "var(--blue-soft)", borderColor: "var(--blue)", color: "var(--blue)" } : {}}
                >
                  全部 ({items.length})
                </button>
                {groups.map(g => (
                  <button
                    key={g.name}
                    className={`followup-chip${activeGroup === g.name ? " active" : ""}`}
                    onClick={() => setActiveGroup(g.name === activeGroup ? null : g.name)}
                    style={activeGroup === g.name ? { background: "var(--blue-soft)", borderColor: "var(--blue)", color: "var(--blue)" } : {}}
                  >
                    <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: g.color, marginRight: 4 }} />
                    {g.name} ({items.filter(i => (i.group ?? "默认") === g.name).length})
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {groupEditor === "manage" && (
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="3"/>
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                </svg>
                管理分组
              </div>
              <button className="small" onClick={() => mgr.closePanel()} type="button">关闭</button>
            </div>
            <div className="panel-body">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {draftGroups.map((g, idx) => (
                  <div key={g.name} style={{ display: "flex", gap: 8, alignItems: "center", padding: 8, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                    <span style={{ display: "inline-block", width: 12, height: 12, borderRadius: "50%", background: g.color, flexShrink: 0 }} />
                    <span style={{ flex: 1, fontSize: 13 }}>{g.name}</span>
                    <input type="color" value={g.color} onChange={(e) => {
                      setDraftGroups(prev => prev.map(d => d.name === g.name ? {...d, color: e.target.value} : d));
                    }} style={{ width: 28, height: 28, padding: 0, border: "none", cursor: "pointer" }} />
                    <button className="small" style={{ color: "var(--red)" }}
                      onClick={() => setDraftGroups(prev => prev.filter(d => d.name !== g.name))}>删除</button>
                  </div>
                ))}
                <div style={{ display: "flex", gap: 8, alignItems: "center", paddingTop: 8, borderTop: "1px solid var(--border)" }}>
                  <input value={groupEditName} onChange={e => setGroupEditName(e.target.value)} placeholder="新分组名" style={{ flex: 1 }} />
                  <input type="color" value={groupEditColor} onChange={e => setGroupEditColor(e.target.value)} style={{ width: 28, height: 28, padding: 0, border: "none" }} />
                  <button className="primary small" onClick={() => {
                    const n = groupEditName.trim();
                    if (n && !draftGroups.some(g => g.name === n)) {
                      setDraftGroups(prev => [...prev, {name: n, color: groupEditColor, sort_order: prev.length}]);
                      setGroupEditName("");
                    }
                  }}>添加</button>
                </div>
                <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", paddingTop: 8 }}>
                  <button className="primary small" onClick={handleSaveGroups}>保存</button>
                  <button className="small" onClick={() => mgr.closePanel()}>取消</button>
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/>
              </svg>
              自选列表
              <span className="panel-badge">{items.length} 只</span>
            </div>
            <div className="panel-actions">
              <button className={`small ${viewMode === "cards" ? "primary" : ""}`} onClick={() => setViewMode("cards")} type="button">卡片</button>
              <button className={`small ${viewMode === "table" ? "primary" : ""}`} onClick={() => setViewMode("table")} type="button">表格</button>
            </div>
          </div>
          <div className="panel-body" style={{ padding: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>股票</th>
                  <th>现价</th>
                  <th>涨跌幅</th>
                  <th>分组</th>
                  <th>盯盘</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.length === 0 ? (
                  <tr><td colSpan={6} className="muted" style={{ padding: 24 }}>暂无自选股票</td></tr>
                ) : filteredItems.map((item) => {
                  const cp = item.price?.change_pct ?? 0;
                  const market = inferMarket(item.symbol);
                  return (
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
                      <td className="price-value">{item.price?.last != null ? marketMoney(item.price.last, market) : "-"}</td>
                      <td><span className={`change-badge ${changeCls(cp)}`}>{pct(cp)}</span></td>
                      <td><span className="tag">{item.group ?? "默认"}</span></td>
                      <td>
                        <span
                          className={`tag ${item.monitored ? "green" : ""}`}
                          style={{ cursor: "pointer" }}
                          onClick={() => void handleToggleMonitor(item.symbol)}
                        >
                          {item.monitored ? "开启" : "关闭"}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 4 }}>
                          <button className="small" onClick={() => setStock(item.symbol)} type="button">详情</button>
                          <button className="small" style={{ color: "var(--red)" }} onClick={() => void handleRemove(item.symbol)} type="button">删除</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}
