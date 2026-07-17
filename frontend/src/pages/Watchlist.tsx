import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiDelete } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage } from "@/components/ui/Loading";
import { PageHead } from "@/components/ui/PageHead";
import { useAppState } from "@/hooks/useAppState";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { inferMarket, marketMoney, pct, changeCls } from "@/utils/market";

interface WatchlistItem { symbol: string; name?: string; group?: string; tags?: string[]; monitored?: boolean; ai_score?: number; market?: string; price?: { last?: number; change_pct?: number } }
interface WatchlistGroup { name: string; color: string; sort_order: number }

export default function Watchlist() {
  const { setStock, appDataCache, globalLoading } = useAppState();
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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


  const filteredItems = useMemo(() => {
    if (!activeGroup) return items;
    return items.filter(i => (i.group ?? "默认") === activeGroup);
  }, [items, activeGroup]);

  const loadAll = async () => {
    setError(null);
    const hasData = items.length > 0;
    if (!hasData) setLoading(true);
    try {
      const response = await apiGet<WatchlistItem[]>("/api/watchlist");
      setItems(response);
      appDataCache.current.watchlist = response; // eslint-disable-line react-hooks/immutability
      const gs = await apiGet<WatchlistGroup[]>("/api/watchlist/groups").catch(() => [] as WatchlistGroup[]);
      setGroups(gs);
    } catch (err) { setError(err instanceof Error ? err.message : "加载自选失败"); } finally { setLoading(false); }
  };

  const mgr = useMemo(() => ({
    open: groupEditor === "manage",
    openPanel() { setGroupEditor("manage"); setDraftGroups(groups.map(g => ({...g}))); },
    closePanel() { setGroupEditor(null); setDraftGroups([]); },
  }), [groupEditor, groups]);

  const [draftGroups, setDraftGroups] = useState<WatchlistGroup[]>([]);

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

  const handleRemove = async (symbol: string) => { try { await apiDelete(`/api/watchlist/items/${encodeURIComponent(symbol)}`); await loadAll(); } catch { /* ignore */ } };
  const handleToggleMonitor = async (symbol: string) => { try { await apiPost(`/api/watchlist/${encodeURIComponent(symbol)}/monitor`, {}); await loadAll(); } catch { /* ignore */ } };

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        {error && <ErrorMessage message={error} />}
        <PageHead
          kpis={[
            { label: "自选", value: `${items.length} 只` },
            { label: "今日上涨", value: items.filter(i => (i.price?.change_pct ?? 0) > 0).length, tone: "up" },
            { label: "今日下跌", value: items.filter(i => (i.price?.change_pct ?? 0) < 0).length, tone: "down" },
            { label: "盯盘开启", value: items.filter(i => i.monitored).length },
          ]}
          actions={<>
            <AskAiButton prompt="点评我的自选池:近期哪些标的值得重点关注?" />
          </>}
        />

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
                {draftGroups.map((g) => (
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
