import { useAppState } from "@/hooks/useAppState"

interface PriceInfo {
  change_pct?: number;
  last?: number;
  [key: string]: unknown;
}

interface HoldingItem {
  market_value?: number;
  [key: string]: unknown;
}

interface MonitorEventItem {
  severity?: string;
  [key: string]: unknown;
}

const pageIcons: Record<string, string> = {
  overview: "📊", watchlist: "⭐", holdings: "💼",
  research: "🔍", market: "📈", monitor: "👁",
  strategies: "📐", tasks: "📋", reports: "📄", settings: "⚙",
}

function formatNum(n: number): string {
  if (n >= 1_0000_0000) return (n / 1_0000_0000).toFixed(1) + "亿"
  if (n >= 1_0000) return (n / 1_0000).toFixed(1) + "万"
  return n.toLocaleString()
}

export function ContextCard() {
  const { currentScreen, currentScreenLabel, stock, appDataCache } = useAppState()
  const cache = appDataCache.current
  const health = cache.health as Record<string, unknown> | undefined

  const icon = pageIcons[currentScreen] || "📄"
  const degraded = health?.degraded as boolean | undefined

  return (
    <div className="context-card">
      <div className="context-card-page">
        <span>{icon}</span>
        <span>{currentScreenLabel}</span>
        {degraded && <span className="context-card-badge mock">mock</span>}
      </div>

      {/* Stock context if available */}
      {stock && currentScreen !== "overview" && (
        (() => {
          const ctx = cache.stockContext as Record<string, PriceInfo> | undefined
          if (!ctx?.price) return null
          const p = ctx.price as PriceInfo
          const chg = p.change_pct
          return (
            <div className="context-card-row">
              <span className="context-card-stock">
                {String(ctx.name || stock)}
                <span className={`change${chg != null ? (chg >= 0 ? " up" : " down") : ""}`}>
                  {chg != null ? `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%` : "--"}
                </span>
              </span>
              {p.last != null && <span className="context-card-value">¥{p.last.toFixed(2)}</span>}
            </div>
          )
        })()
      )}

      {/* Holdings summary */}
      {(() => {
        const hld = cache.holdings as { items?: Record<string, unknown>[] } | undefined
        if (!hld?.items?.length) return null
        const items = hld.items as HoldingItem[]
        const totalMv = items.reduce((s: number, i: HoldingItem) => s + (i.market_value || 0), 0)
        return (
          <div className="context-card-row">
            <span className="context-card-label">持仓</span>
            <span className="context-card-value">{items.length}</span>
            <span className="context-card-label">总市值</span>
            <span className="context-card-value">{formatNum(totalMv)}</span>
          </div>
        )
      })()}

      {/* Monitor summary */}
      {(() => {
        const ev = cache.monitorEvents as { items?: Record<string, unknown>[] } | undefined
        if (!ev?.items?.length) return null
        const events = ev.items as MonitorEventItem[]
        const high = events.filter((e: MonitorEventItem) => e.severity === "high").length
        return (
          <div className="context-card-row">
            <span className="context-card-label">盯盘</span>
            <span className="context-card-value">{events.length}</span>
            {high > 0 && <span className="context-card-badge" style={{ background: "var(--red-soft)", color: "var(--red)" }}>{high} 条高优</span>}
          </div>
        )
      })()}

      {/* Inbox summary */}
      {(() => {
        const ib = cache.inboxSummary as { open_count?: number; high_count?: number } | undefined
        if (!ib?.open_count) return null
        return (
          <div className="context-card-row">
            <span className="context-card-label">待办</span>
            <span className="context-card-value">{ib.open_count}</span>
            {(ib.high_count ?? 0) > 0 && <span className="context-card-badge" style={{ background: "var(--amber-soft)", color: "var(--amber)" }}>{ib.high_count} 条高优先级</span>}
          </div>
        )
      })()}

      {/* Runtime badges */}
      {(() => {
        const badges: string[] = []
        if (degraded) badges.push("数据降级")
        const settings = cache.settings as { agent_runtime?: { mode?: string } } | undefined
        const rt = settings?.agent_runtime
        if (rt?.mode === "stub") badges.push("AI 模拟模式")
        else if (rt?.mode === "embedded") badges.push("AI 嵌入模式")
        if (badges.length === 0) return null
        return (
          <div className="context-card-row">
            {badges.map((b) => (
              <span key={b} className="context-card-badge mock" style={{ fontSize: 10 }}>{b}</span>
            ))}
          </div>
        )
      })()}
    </div>
  )
}
