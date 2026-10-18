import { useEffect, useRef, useState } from "react";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import { useAppState } from "@/hooks/useAppState";
import { displaySessionTitle } from "@/lib/sessionTitle";

function FoldLeftIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3" y="4" width="18" height="16" rx="2" /><line x1="9" y1="4" x2="9" y2="20" />
    </svg>
  );
}

function FoldRightIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3" y="4" width="18" height="16" rx="2" /><line x1="15" y1="4" x2="15" y2="20" />
    </svg>
  );
}

function DotsGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
      <circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" />
    </svg>
  );
}

/** 中栏标题区（对齐 DSH）：标题 + 更多菜单 +（功能栏收起时的）展开按钮；
 *  下面一行是 对话 / 轨迹 tab。它只属于中栏 —— 左右两栏各自占满整个高度。
 *  右侧顺序：[⋯] [⊡ 展开功能栏] —— 菜单在左、展开按钮在右（贴窗口右缘）。 */
export function TopBar({
  onOpenSettings,
  onToggleLeft,
  onToggleDock,
  leftCollapsed,
  dockCollapsed,
}: {
  onOpenSettings: () => void;
  onToggleLeft: () => void;
  onToggleDock: () => void;
  leftCollapsed: boolean;
  dockCollapsed: boolean;
}) {
  const { currentSession } = useCopilotChat();
  const { chatView, setChatView } = useAppState();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menuOpen]);

  return (
    <header className="topbar3" data-tauri-drag-region="deep">
      <div className="topbar3-r1" data-tauri-drag-region="deep">
        {leftCollapsed && (
          <button
            className="topbar3-btn"
            onClick={onToggleLeft}
            title="展开会话栏"
            data-tauri-drag-region="false"
          >
            <FoldLeftIcon />
          </button>
        )}
        <span className="topbar3-title">{displaySessionTitle(currentSession?.title)}</span>

        <span className="topbar3-spacer" />

        <div className="topbar3-menu-wrap" ref={menuRef} data-tauri-drag-region="false">
          <button
            className={`topbar3-btn${menuOpen ? " on" : ""}`}
            onClick={() => setMenuOpen((v) => !v)}
            title="更多"
          >
            <DotsGlyph />
          </button>
          {menuOpen && (
            <div className="topbar3-menu">
              <button
                type="button"
                className="topbar3-menu-item"
                onClick={() => { setMenuOpen(false); onToggleLeft(); }}
              >
                {leftCollapsed ? "展开会话栏" : "收起会话栏"}
              </button>
              <button
                type="button"
                className="topbar3-menu-item"
                onClick={() => { setMenuOpen(false); onToggleDock(); }}
              >
                收起 / 展开功能栏
              </button>
              <div className="topbar3-menu-sep" />
              <button
                type="button"
                className="topbar3-menu-item"
                onClick={() => { setMenuOpen(false); onOpenSettings(); }}
              >
                设置
              </button>
            </div>
          )}
        </div>

        {/* 功能栏整条收起时 Dock 不再渲染，展开入口留在这里（菜单左侧、贴右缘） */}
        {dockCollapsed && (
          <button
            className="topbar3-btn"
            onClick={onToggleDock}
            title="展开功能栏"
            data-tauri-drag-region="false"
          >
            <FoldRightIcon />
          </button>
        )}
      </div>

      <div className="topbar3-r2">
        <div className="topbar3-tabs" data-tauri-drag-region="false">
          <button
            type="button"
            className={`topbar3-tab${chatView === "chat" ? " on" : ""}`}
            onClick={() => setChatView("chat")}
          >
            对话
          </button>
          <button
            type="button"
            className={`topbar3-tab${chatView === "trajectory" ? " on" : ""}`}
            onClick={() => setChatView("trajectory")}
          >
            轨迹
          </button>
        </div>
      </div>
    </header>
  );
}
