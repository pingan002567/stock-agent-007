import { CopilotComposer } from "@/components/features/CopilotComposer";

function CollapsedFoot({
  onOpenSettings,
  onOpenWorkspace,
}: {
  onOpenSettings: () => void;
  onOpenWorkspace: () => void;
}) {
  return (
    <div className="bottombar-collapsed-actions">
      <button className="left-foot-icon" onClick={onOpenWorkspace} title="切换工作区" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
        </svg>
      </button>
      <button className="left-foot-icon" onClick={onOpenSettings} title="系统设置" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l-.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </button>
    </div>
  );
}

/** 中栏底栏：Composer 浮动输入（Cursor 式），仅占 center 列。 */
export function BottomBar({
  leftCollapsed,
  onOpenSettings,
  onOpenWorkspace,
}: {
  leftCollapsed: boolean;
  onOpenSettings: () => void;
  onOpenWorkspace: () => void;
}) {
  return (
    <footer className="bottombar3">
      {leftCollapsed && (
        <CollapsedFoot onOpenSettings={onOpenSettings} onOpenWorkspace={onOpenWorkspace} />
      )}
      <CopilotComposer />
    </footer>
  );
}
