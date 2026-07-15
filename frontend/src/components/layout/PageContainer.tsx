export function PageContainer({ children }: { children: React.ReactNode }) {
  return (
    <>
      {/* 时钟/AI 状态/头像已上移至左栏品牌区（三栏布局），topbar 只留搜索 */}
      <header className="topbar">
        <div className="topbar-left">
          <div className="topbar-search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8"/>
              <path d="M21 21l-4.35-4.35"/>
            </svg>
            <input type="text" placeholder="搜索股票代码、名称或情报..." />
          </div>
        </div>
      </header>
      <section className="content">
        {children}
      </section>
    </>
  );
}
