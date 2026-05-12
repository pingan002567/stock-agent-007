import { useAppState } from "@/hooks/useAppState";

export function PageContainer({ children }: { children: React.ReactNode }) {
  const { currentScreenLabel } = useAppState();
  return (
    <>
      <header className="topbar">
        <div className="topbar-left">
          <h1 className="topbar-title">AI Stock Workbench</h1>
          <div className="topbar-search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8"/>
              <path d="M21 21l-4.35-4.35"/>
            </svg>
            <input type="text" placeholder="搜索股票代码、名称或情报..." />
          </div>
        </div>
        <div className="topbar-right">
          <div className="topbar-status">
            <span className="topbar-status-dot"></span>
            <span>AI 就绪</span>
          </div>
          <div className="topbar-user">Z</div>
        </div>
      </header>
      <section className="content">
        {children}
      </section>
    </>
  );
}
