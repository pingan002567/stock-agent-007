/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import type { Screen } from "@/types";

export interface AppDataCache {
  overview?: unknown;
  monitorEvents?: unknown;
  inboxSummary?: unknown;
  inboxList?: unknown;
  drafts?: unknown;
  audit?: unknown;
  health?: unknown;
  runtimeMetrics?: unknown;
  watchlist?: unknown;
  holdings?: unknown;
  holdingsRisk?: unknown;
  preTradeReviews?: unknown;
  paperOrders?: unknown;
  journal?: unknown;
  paperPortfolio?: unknown;
  activePolicy?: unknown;
  marketReview?: unknown;
  marketSectors?: unknown;
  marketTimeline?: unknown;
  monitorRules?: unknown;
  monitorStatus?: unknown;
  strategies?: unknown;
  tasks?: unknown;
  reports?: unknown;
  reportTemplates?: unknown;
  settings?: unknown;
  /** 个股研究数据（缓存当前 stock） */
  stockContext?: unknown;
  stockHistory?: unknown;
  stockIntel?: unknown;
  stockFinancial?: unknown;
  stockFollowups?: unknown;
}

interface AppStateValue {
  currentScreen: Screen;
  setCurrentScreen: (s: Screen) => void;
  currentScreenLabel: string;
  stock: string;
  setStock: (s: string) => void;
  copilotStreaming: boolean;
  setCopilotStreaming: (v: boolean) => void;
  streamingReasoningText: string;
  setStreamingReasoningText: Dispatch<SetStateAction<string>>;
  copilotContextVersion: number;
  refreshCopilotContext: () => void;
  darkMode: boolean;
  toggleDarkMode: () => void;
  globalLoading: boolean;
  appDataCache: React.MutableRefObject<AppDataCache>;
  refreshAll: () => Promise<void>;
  lastRefreshTime: string | null;
  setLastRefreshTime: (v: string | null) => void;
}

const AppStateContext = createContext<AppStateValue | null>(null);

const screenLabels: Record<Screen, string> = {
  overview: "总览",
  watchlist: "自选",
  holdings: "持仓",
  research: "个股",
  market: "市场",
  monitor: "盯盘",
  strategies: "策略",
  tasks: "任务",
  reports: "报告",
  settings: "设置",
  worldcup: "世界杯",
};

function getInitialDarkMode(): boolean {
  try { return localStorage.getItem("stock-agent-dark") === "1"; } catch { return false; }
}

function applyDarkClass(dark: boolean) {
  document.documentElement.classList.toggle("dark", dark);
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [currentScreen, setCurrentScreen] = useState<Screen>("overview");
  const [stock, setStock] = useState("");
  const [copilotStreaming, setCopilotStreaming] = useState(false);
  const [streamingReasoningText, setStreamingReasoningText] = useState("");
  const [darkMode, setDarkMode] = useState(getInitialDarkMode);
  const [isInitialized, setIsInitialized] = useState(false);
  const [lastRefreshTime, setLastRefreshTime] = useState<string | null>(null);
  const [copilotContextVersion, setCopilotContextVersion] = useState(0);
  const appDataCache = useRef<AppDataCache>({});
  const refreshIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stockRef = useRef(stock);

  useEffect(() => { stockRef.current = stock; }, [stock]);

  useEffect(() => { applyDarkClass(darkMode); }, [darkMode]);

  const toggleDarkMode = () => {
    setDarkMode((prev) => {
      const next = !prev;
      try { localStorage.setItem("stock-agent-dark", next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });
  };

  const refreshAll = useCallback(async () => {
    const { apiGet } = await import("@/api/client");
    const { fetchRuntimeMetrics } = await import("@/api/runtime");
    const cache = appDataCache.current;

    const stockSymbol = stockRef.current;

    const [ov, me, ibs, ibl, dr, au, hc, metrics, wl, hld, hrk, prv, po, jn, pp, apol, mr, ms, mt, mrl, mst, str, tsk, rpt, rptt, stg, sctx, shist, sint, sfin, sfu] = await Promise.allSettled([
      apiGet("/api/overview"),
      apiGet<{ items: unknown[] }>("/api/monitor/events"),
      apiGet("/api/review-inbox/summary"),
      apiGet<{ items: unknown[] }>("/api/review-inbox"),
      apiGet<{ items: unknown[] }>("/api/rebalance-drafts"),
      apiGet<{ items: unknown[] }>("/api/audit"),
      apiGet("/api/health"),
      fetchRuntimeMetrics(),
      apiGet("/api/watchlist"),
      apiGet("/api/holdings"),
      apiGet("/api/holdings/risk"),
      apiGet<{ items: unknown[] }>("/api/pre-trade-reviews"),
      apiGet<{ items: unknown[] }>("/api/paper-orders"),
      apiGet<{ items: unknown[] }>("/api/decision-journal"),
      apiGet("/api/paper-portfolio"),
      apiGet("/api/risk-policies/active"),
      apiGet("/api/market/review"),
      apiGet("/api/market/sectors"),
      apiGet("/api/market/timeline"),
      apiGet<{ items: unknown[] }>("/api/monitor/rules"),
      apiGet("/api/monitor/status"),
      apiGet<{ items: unknown[] }>("/api/strategies"),
      apiGet<{ items: unknown[] }>("/api/tasks"),
      apiGet<{ items: unknown[] }>("/api/reports"),
      apiGet<{ items: unknown[] }>("/api/report-templates"),
      apiGet("/api/settings"),
      // 个股研究数据（按当前 stock 预加载，stock 为空时跳过）
      stockSymbol ? apiGet(`/api/stocks/${encodeURIComponent(stockSymbol)}/context`).catch(() => null) : Promise.resolve(null),
      stockSymbol ? apiGet<{ items: unknown[] }>(`/api/stocks/${encodeURIComponent(stockSymbol)}/history`).catch((): { items: unknown[] } => ({ items: [] })) : Promise.resolve({ items: [] }),
      stockSymbol ? apiGet<{ items: unknown[] }>(`/api/stocks/${encodeURIComponent(stockSymbol)}/intel`).catch((): { items: unknown[] } => ({ items: [] })) : Promise.resolve({ items: [] }),
      stockSymbol ? apiGet<{ items: unknown[] }>(`/api/stocks/${encodeURIComponent(stockSymbol)}/financial`).catch((): { items: unknown[] } => ({ items: [] })) : Promise.resolve({ items: [] }),
      apiGet<{ items: unknown[] }>("/api/portfolio/copilot/followups").catch((): { items: unknown[] } => ({ items: [{ text: "分析 AAPL 风险", icon: "🔍" }, { text: "生成调仓草案", icon: "📝" }, { text: "查看持仓风险", icon: "⚠️" }, { text: "运行策略回测", icon: "🧪" }] })),
    ]);

    if (ov.status === "fulfilled") cache.overview = ov.value;
    if (me.status === "fulfilled") cache.monitorEvents = me.value;
    if (ibs.status === "fulfilled") cache.inboxSummary = ibs.value;
    if (ibl.status === "fulfilled") cache.inboxList = ibl.value;
    if (dr.status === "fulfilled") cache.drafts = dr.value;
    if (au.status === "fulfilled") cache.audit = au.value;
    if (hc.status === "fulfilled") cache.health = hc.value;
    if (metrics.status === "fulfilled") cache.runtimeMetrics = metrics.value;
    if (wl.status === "fulfilled") cache.watchlist = wl.value;
    if (hld.status === "fulfilled") cache.holdings = hld.value;
    if (hrk.status === "fulfilled") cache.holdingsRisk = hrk.value;
    if (prv.status === "fulfilled") cache.preTradeReviews = prv.value;
    if (po.status === "fulfilled") cache.paperOrders = po.value;
    if (jn.status === "fulfilled") cache.journal = jn.value;
    if (pp.status === "fulfilled") cache.paperPortfolio = pp.value;
    if (apol.status === "fulfilled") cache.activePolicy = apol.value;
    if (mr.status === "fulfilled") cache.marketReview = mr.value;
    if (ms.status === "fulfilled") cache.marketSectors = ms.value;
    if (mt.status === "fulfilled") cache.marketTimeline = mt.value;
    if (mrl.status === "fulfilled") cache.monitorRules = mrl.value;
    if (mst.status === "fulfilled") cache.monitorStatus = mst.value;
    if (str.status === "fulfilled") cache.strategies = str.value;
    if (tsk.status === "fulfilled") cache.tasks = tsk.value;
    if (rpt.status === "fulfilled") cache.reports = rpt.value;
    if (rptt.status === "fulfilled") cache.reportTemplates = rptt.value;
    if (stg.status === "fulfilled") cache.settings = stg.value;
    if (sctx.status === "fulfilled") cache.stockContext = sctx.value;
    if (shist.status === "fulfilled") cache.stockHistory = shist.value;
    if (sint.status === "fulfilled") cache.stockIntel = sint.value;
    if (sfin.status === "fulfilled") cache.stockFinancial = sfin.value;
    if (sfu.status === "fulfilled") cache.stockFollowups = sfu.value;

    setLastRefreshTime(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    setIsInitialized(true);
  }, []);

  // Trigger initial load once on mount — setState is intentional for initialization
  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { void refreshAll(); }, []);

  // 全量数据后台自动刷新（首次加载完成后启动，每 60 秒一次）
  // refreshAll is stable (useCallback with []) — safe to omit from deps
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!isInitialized) return;
    refreshIntervalRef.current = setInterval(() => {
      void refreshAll();
    }, 60_000);
    return () => {
      if (refreshIntervalRef.current) clearInterval(refreshIntervalRef.current);
    };
  }, [isInitialized]);

  const refreshCopilotContext = useCallback(() => {
    setCopilotContextVersion((v) => v + 1);
  }, []);

  const globalLoading = useMemo(() => !isInitialized, [isInitialized]);
  const currentScreenLabel = screenLabels[currentScreen];

  return (
    <AppStateContext.Provider
      value={{
        currentScreen,
        setCurrentScreen,
        currentScreenLabel,
        stock,
        setStock,
        copilotStreaming,
        setCopilotStreaming,
        streamingReasoningText,
        setStreamingReasoningText,
        copilotContextVersion,
        refreshCopilotContext,
        darkMode,
        toggleDarkMode,
        globalLoading,
        appDataCache,
        refreshAll,
        lastRefreshTime,
        setLastRefreshTime,
      }}
    >
      {children}
    </AppStateContext.Provider>
  );
}

export function useAppState() {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error("useAppState must be used within AppStateProvider");
  return ctx;
}
