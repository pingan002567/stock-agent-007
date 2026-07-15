import { useAppState } from "@/hooks/useAppState";

export function LoadingOverlay() {
  const { globalLoading, currentScreen } = useAppState();

  if (!globalLoading) return null;
  // 聊天中心：chat 首屏不依赖概览/行情预加载数据，不被全屏遮罩连坐；
  // 业务页保持原行为（rail 在加载期间已禁用，不会切进半加载页面）。
  if (currentScreen === "chat") return null;

  return (
    <div className="loading-overlay loading-overlay-active">
      <div className="loading-box" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()} role="presentation">
        <div className="loading-spinner" />
        <div className="loading-title">加载数据中</div>
        <div className="loading-sub">正在加载概览、自选、持仓、个股等数据…</div>
      </div>
    </div>
  );
}
