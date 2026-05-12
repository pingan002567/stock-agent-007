export function Loading({ text = "加载中…" }: { text?: string }) {
  return <div className="muted" style={{ textAlign: "center", padding: "24px 0" }}>{text}</div>;
}

export function ErrorMessage({ message }: { message: string }) {
  return <div style={{ textAlign: "center", color: "var(--red)", padding: "24px 0", fontSize: 13 }}>⚠️ {message}</div>;
}

/* ---------- Skeletons ---------- */

export function PanelSkeleton() {
  return (
    <div className="panel fade-in">
      <div className="head">
        <span className="skeleton skel-head" />
      </div>
      <div className="pad" style={{ display: "grid", gap: 8 }}>
        <div className="skeleton skel-card" />
        <div className="skeleton skel-card" />
      </div>
    </div>
  );
}

export function KpiSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="panel fade-in">
      <div className="head">
        <span className="skeleton skel-head" />
      </div>
      <div className="pad">
        <div className="overview-grid">
          {Array.from({ length: count }).map((_, i) => (
            <div key={i} className="card" style={{ minHeight: 72 }}>
              <div className="skeleton skel-head" style={{ width: "50%", height: 12, marginBottom: 8 }} />
              <div className="skeleton skel-kpi" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function TableSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="panel fade-in">
      <div className="head">
        <span className="skeleton skel-head" />
      </div>
      <div style={{ padding: "10px 12px" }}>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="skeleton skel-row" />
        ))}
      </div>
    </div>
  );
}

export function OverviewSkeleton() {
  return (
    <div className="page-stack">
      <div className="page-hero fade-in">
        <div><div className="skeleton skel-head" style={{ width: 100, height: 22, marginBottom: 8 }} /><div className="skeleton" style={{ width: 260, height: 12 }} /></div>
        <div style={{ display: "flex", gap: 8 }}><div className="skeleton" style={{ width: 80, height: 32, borderRadius: 7 }} /><div className="skeleton" style={{ width: 100, height: 32, borderRadius: 7 }} /></div>
      </div>
      <div className="grid">
        <div className="page-stack">
          <KpiSkeleton />
          <PanelSkeleton />
          <TableSkeleton />
        </div>
        <div className="page-stack">
          <PanelSkeleton />
          <KpiSkeleton count={3} />
          <TableSkeleton rows={3} />
        </div>
      </div>
    </div>
  );
}

/* ---------- Empty State ---------- */

const ICONS: Record<string, string> = {
  search: "\u{1F50D}",
  portfolio: "\u{1F4CA}",
  watchlist: "\u{1F4CB}",
  monitor: "\u{1F514}",
  strategy: "\u{1F9E9}",
  task: "\u{1F4CB}",
  report: "\u{1F4C4}",
  data: "\u{1F4CA}",
};

interface EmptyStateProps {
  icon?: string;
  title?: string;
  description?: string;
}

export function EmptyState({ icon = "data", title = "暂无数据", description }: EmptyStateProps) {
  return (
    <div className="empty-state fade-in">
      <div className="empty-icon">{ICONS[icon] || ICONS.data}</div>
      <div className="empty-title">{title}</div>
      {description && <div className="empty-desc">{description}</div>}
    </div>
  );
}
