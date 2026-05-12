import { useAppState } from "@/hooks/useAppState";

export function LoadingOverlay() {
  const { globalLoading } = useAppState();

  if (!globalLoading) return null;

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
