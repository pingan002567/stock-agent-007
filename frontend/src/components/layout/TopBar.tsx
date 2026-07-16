import { useCopilotChat } from "@/hooks/useCopilotChat";

/** 统一顶栏（TeamClaw 式）：贯通三栏的细条——左端左栏折叠钮（桌面态红绿灯
 * 住在本行）、中段当前会话标题、右端右栏折叠钮。整条是窗口拖拽区。 */
export function TopBar({ leftCollapsed, onToggleLeft, dockCollapsed, onToggleDock }: {
  leftCollapsed: boolean;
  onToggleLeft: () => void;
  dockCollapsed: boolean;
  onToggleDock: () => void;
}) {
  const { currentSession } = useCopilotChat();
  return (
    <header className="topbar3" data-tauri-drag-region="">
      <div className="topbar3-seg topbar3-left" data-tauri-drag-region="">
        <button
          className={`topbar3-btn${leftCollapsed ? "" : " on"}`}
          onClick={onToggleLeft}
          title={leftCollapsed ? "展开会话栏" : "收起会话栏"}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <rect x="3" y="4" width="18" height="16" rx="2"/><line x1="9" y1="4" x2="9" y2="20"/>
          </svg>
        </button>
      </div>
      <div className="topbar3-seg topbar3-center" data-tauri-drag-region="">
        <span className="topbar3-title">{currentSession?.title || "新会话"}</span>
      </div>
      <div className="topbar3-seg topbar3-right">
        <button
          className={`topbar3-btn${dockCollapsed ? "" : " on"}`}
          onClick={onToggleDock}
          title={dockCollapsed ? "展开功能栏" : "收起功能栏"}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <rect x="3" y="4" width="18" height="16" rx="2"/><line x1="15" y1="4" x2="15" y2="20"/>
          </svg>
        </button>
      </div>
    </header>
  );
}
