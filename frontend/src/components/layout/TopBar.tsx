import { useCopilotChat } from "@/hooks/useCopilotChat";

function FoldLeftIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <line x1="9" y1="4" x2="9" y2="20" />
    </svg>
  );
}

function FoldRightIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <line x1="15" y1="4" x2="15" y2="20" />
    </svg>
  );
}

/** 统一顶栏：与 .app 共用 --shell-cols，分段与左/中/右栏列边界对齐。
 * 栏收起时折叠钮移入中栏段，避免顶栏列宽与 body 网格错位。 */
export function TopBar({ leftCollapsed, onToggleLeft, dockCollapsed, onToggleDock }: {
  leftCollapsed: boolean;
  onToggleLeft: () => void;
  dockCollapsed: boolean;
  onToggleDock: () => void;
}) {
  const { currentSession } = useCopilotChat();

  const leftToggle = (
    <button
      className={`topbar3-btn${leftCollapsed ? "" : " on"}`}
      onClick={onToggleLeft}
      title={leftCollapsed ? "展开会话栏" : "收起会话栏"}
    >
      <FoldLeftIcon />
    </button>
  );

  const dockToggle = (
    <button
      className={`topbar3-btn${dockCollapsed ? "" : " on"}`}
      onClick={onToggleDock}
      title={dockCollapsed ? "展开功能栏" : "收起功能栏"}
    >
      <FoldRightIcon />
    </button>
  );

  const bothCollapsed = leftCollapsed && dockCollapsed;

  return (
    <header className="topbar3" data-tauri-drag-region="">
      {!bothCollapsed && !dockCollapsed && (
        <div className="topbar3-seg topbar3-left" data-tauri-drag-region="">
          {!leftCollapsed && leftToggle}
        </div>
      )}
      {!bothCollapsed && dockCollapsed && !leftCollapsed && (
        <div className="topbar3-seg topbar3-left" data-tauri-drag-region="">
          {leftToggle}
        </div>
      )}

      <div
        className={`topbar3-seg topbar3-center${bothCollapsed ? " topbar3-center-span" : ""}`}
        data-tauri-drag-region=""
      >
        {leftCollapsed && leftToggle}
        <span className="topbar3-title">{currentSession?.title || "新会话"}</span>
        {dockCollapsed && dockToggle}
      </div>

      {!dockCollapsed && (
        <div className="topbar3-seg topbar3-right">
          {dockToggle}
        </div>
      )}
    </header>
  );
}
