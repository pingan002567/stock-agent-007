import { useMemo } from "react";
import { useAppState } from "@/hooks/useAppState";
import { icons, navItems } from "@/components/layout/nav";
import { ScreenRenderer } from "@/pages/ScreenRenderer";
import { ResizeHandle } from "@/components/ui/ResizeHandle";
import { formatTimeAgo } from "@/utils/format";

/** 三栏布局右侧功能坞：52px 常驻图标条（"平时收起"态）+ 可展开功能面板。
 * currentScreen 语义 = 面板内容；"chat" = 面板关闭。宽度过渡不卸载
 * （流式进行中不断渲染）。工具结果不再有独立详情面板：内容就在对话里的工具块内联展开。 */
export function FunctionDock({ onToggleCollapse }: { onToggleCollapse?: () => void } = {}) {
  const { currentScreen, setCurrentScreen, appDataCache, lastRefreshTime, globalLoading } = useAppState();
  const inboxHigh = useMemo(() => {
    const summary = appDataCache.current.inboxSummary as { high_count?: number } | undefined;
    return summary?.high_count ?? 0;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appDataCache, lastRefreshTime]);

  const stripItems = navItems.filter((n) => n.screen !== "chat");
  const panelOpen = currentScreen !== "chat";
  const screenLabel = stripItems.find((n) => n.screen === currentScreen)?.label ?? "";

  const handleStrip = (screen: (typeof stripItems)[number]["screen"]) => {
    if (currentScreen === screen) {
      setCurrentScreen("chat"); // 再点同一入口 = 收起
    } else {
      setCurrentScreen(screen);
    }
  };

  const handleClose = () => {
    setCurrentScreen("chat");
  };
  const handleHead = handleClose;

  return (
    <div className="func-dock">
      <section className={`func-panel${panelOpen ? " open" : ""}`}>
        {panelOpen && (
          <ResizeHandle cssVar="--func-panel-w" storageKey="func-panel-w" min={360} max={880} />
        )}
        <div className="func-inner">
          <div className="func-head" data-tauri-drag-region="deep">
            <span className="func-title">
              {screenLabel}
            </span>
            {/* 数据新鲜度替代手动刷新按钮(设计规范 3.5) */}
            {lastRefreshTime && (
              <span className="func-fresh">{formatTimeAgo(lastRefreshTime)}</span>
            )}
            <button className="func-close" onClick={handleHead} title="收起" data-tauri-drag-region="false">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18l6-6-6-6"/></svg>
            </button>
          </div>
          <div className="func-body">
            {globalLoading
              // 启动预加载只遮面板不遮全屏（聊天不受业务数据加载连坐）
              ? <div className="page-loading">数据加载中…</div>
              : currentScreen !== "chat" && <ScreenRenderer />}
          </div>
        </div>
      </section>

      <aside className="func-strip">
        {onToggleCollapse ? (
          <button
            className="strip-btn"
            title="收起功能栏"
            onClick={onToggleCollapse}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <rect x="3" y="4" width="18" height="16" rx="2" /><line x1="15" y1="4" x2="15" y2="20" />
            </svg>
          </button>
        ) : null}
        {stripItems.map((item) => (
          <button
            key={item.screen}
            className={`strip-btn${currentScreen === item.screen ? " active" : ""}`}
            onClick={() => handleStrip(item.screen)}
          >
            {icons[item.screen] ?? item.label[0]}
            {item.screen === "monitor" && inboxHigh > 0 && <span className="strip-badge" />}
            <span className="strip-tip">
              {item.label}{item.screen === "monitor" && inboxHigh > 0 ? ` · 待审查 ${inboxHigh} 条高优` : ""}
            </span>
          </button>
        ))}
        <div className="strip-gap" />
      </aside>
    </div>
  );
}
