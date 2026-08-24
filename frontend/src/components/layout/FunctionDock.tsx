import { useMemo, useState } from "react";
import { useAppState } from "@/hooks/useAppState";
import { useChatDetail } from "@/hooks/useChatDetail";
import { useCopilotChat, toolLabel } from "@/hooks/useCopilotChat";
import { skillLabelOf } from "@/components/features/skillLabels";
import { icons, navItems } from "@/components/layout/nav";
import { ScreenRenderer } from "@/pages/ScreenRenderer";
import { DetailBody } from "@/components/features/ChatDetailPanel";
import { ResizeHandle } from "@/components/ui/ResizeHandle";
import { formatTimeAgo } from "@/utils/format";

/** 三栏布局右侧功能坞：52px 常驻图标条（"平时收起"态）+ 可展开功能面板。
 * currentScreen 语义 = 面板内容；"chat" = 面板关闭。业务页面与工具卡详情
 * 共用同一面板宿主，宽度过渡不卸载（流式进行中不断渲染）。 */
export function FunctionDock() {
  const { currentScreen, setCurrentScreen, appDataCache, lastRefreshTime, globalLoading } = useAppState();
  const { detail, open: detailOpen, openDetail, closeDetail } = useChatDetail();
  const { currentSession } = useCopilotChat();


  // 会话切换后旧工具详情失去上下文，自动收起（render 期派生状态）
  const sid = currentSession?.session_id ?? null;
  const [detailSessionId, setDetailSessionId] = useState<string | null>(sid);
  if (sid !== detailSessionId) {
    setDetailSessionId(sid);
    if (detailOpen) closeDetail();
  }

  const inboxHigh = useMemo(() => {
    const summary = appDataCache.current.inboxSummary as { high_count?: number } | undefined;
    return summary?.high_count ?? 0;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appDataCache, lastRefreshTime]);

  const stripItems = navItems.filter((n) => n.screen !== "chat");
  const panelOpen = detailOpen || currentScreen !== "chat";
  const screenLabel = stripItems.find((n) => n.screen === currentScreen)?.label ?? "";
  const detailTitle = detailOpen && detail
    ? (detail.name === "task"
      ? (skillLabelOf(detail.subagentType) ?? detail.subagentType ?? "子代理委派")
      : toolLabel(detail.name))
    : "";
  const detailSub = detailOpen && detail
    ? (detail.name === "task"
      ? (detail.taskDescription || detail.taskPrompt?.slice(0, 80) || detail.subagentType || "task")
      : detail.name)
    : "";

  const handleStrip = (screen: (typeof stripItems)[number]["screen"]) => {
    if (detailOpen) closeDetail();
    if (currentScreen === screen && !detailOpen) {
      setCurrentScreen("chat"); // 再点同一入口 = 收起
    } else {
      setCurrentScreen(screen);
    }
  };

  const handleClose = () => {
    closeDetail();
    setCurrentScreen("chat");
  };

  return (
    <div className="func-dock">
      <section className={`func-panel${panelOpen ? " open" : ""}`}>
        {panelOpen && (
          <ResizeHandle cssVar="--func-panel-w" storageKey="func-panel-w" min={360} max={880} />
        )}
        <div className="func-inner">
          <div className="func-head" data-tauri-drag-region="">
            <span className="func-title">
              {detailOpen && detail ? detailTitle : screenLabel}
            </span>
            {detailOpen && detail && (
              <span className="func-sub">{detailSub}</span>
            )}
            {/* 数据新鲜度替代手动刷新按钮(设计规范 3.5) */}
            {!detailOpen && lastRefreshTime && (
              <span className="func-fresh">{formatTimeAgo(lastRefreshTime)}</span>
            )}
            <button className="func-close" onClick={handleClose} title="收起">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18l6-6-6-6"/></svg>
            </button>
          </div>
          <div className="func-body">
            {detailOpen && detail
              ? (
                <div className="detail-host">
                  {detail.name === "task" && (detail.taskDescription || detail.taskPrompt) && (
                    <div className="subagent-detail-brief">
                      {detail.taskDescription && (
                        <div className="subagent-detail-desc">{detail.taskDescription}</div>
                      )}
                      {detail.taskPrompt && (
                        <div className="subagent-detail-prompt">{detail.taskPrompt}</div>
                      )}
                    </div>
                  )}
                  <DetailBody key={detail.id} resultText={detail.resultText} />
                </div>
              )
              // 启动预加载只遮面板不遮全屏（聊天不受业务数据加载连坐）
              : globalLoading
                ? <div className="page-loading">数据加载中…</div>
                : currentScreen !== "chat" && <ScreenRenderer />}
          </div>
        </div>
      </section>

      <aside className="func-strip">
        {stripItems.map((item) => (
          <button
            key={item.screen}
            className={`strip-btn${!detailOpen && currentScreen === item.screen ? " active" : ""}`}
            onClick={() => handleStrip(item.screen)}
          >
            {icons[item.screen] ?? item.label[0]}
            {item.screen === "monitor" && inboxHigh > 0 && <span className="strip-badge" />}
            <span className="strip-tip">
              {item.label}{item.screen === "monitor" && inboxHigh > 0 ? ` · ${inboxHigh} 条高优` : ""}
            </span>
          </button>
        ))}
        <div className="strip-gap" />
        {/* 工具详情快捷回看：有详情内容时提供入口 */}
        {detail && (
          <button
            className={`strip-btn${detailOpen ? " active" : ""}`}
            onClick={() => (detailOpen ? closeDetail() : openDetail(detail))}
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h4"/></svg>
            <span className="strip-tip">工具结果 · {toolLabel(detail.name)}</span>
          </button>
        )}
      </aside>
    </div>
  );
}
