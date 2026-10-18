import { useEffect, useMemo, useRef, useState } from "react";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import { useAppState } from "@/hooks/useAppState";
import { parseCopilotEvent, EVENT_TOOL_CALL } from "@/api/copilot";
import { parseTaskToolPayload } from "@/components/features/taskToolMeta";
import { displaySessionTitle } from "@/lib/sessionTitle";
import type { CopilotMessage } from "@/api/client";

function FoldLeftIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3" y="4" width="18" height="16" rx="2" /><line x1="9" y1="4" x2="9" y2="20" />
    </svg>
  );
}

function ToolGlyph() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
    </svg>
  );
}

function SubagentGlyph() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="5" y="7" width="14" height="11" rx="2" />
      <path d="M12 3v4M8 12h.01M16 12h.01M9 16h6" />
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

/** 会话运行状态：工具调用数 / 子代理数。都从已加载的消息里解析，不发新请求。 */
function useSessionStats(messages: CopilotMessage[]) {
  return useMemo(() => {
    let tools = 0;
    let subagents = 0;
    for (const m of messages) {
      const ev = parseCopilotEvent(m as unknown as Record<string, unknown>);
      if (ev.type !== EVENT_TOOL_CALL) continue;
      tools += 1;
      const meta = parseTaskToolPayload(ev.payload as Record<string, unknown> | undefined);
      if (meta.subagentType) subagents += 1;
    }
    return { tools, subagents, messages: messages.length };
  }, [messages]);
}

/** 中栏标题区（对齐 DSH）：标题 + 运行状态胶囊 + 更多菜单；下面一行是 对话 / 轨迹 tab。
 *  它现在只属于中栏 —— 左右两栏各自占满整个高度，不再被通栏顶栏推下来。 */
export function TopBar({
  onOpenSettings,
  onToggleLeft,
  onToggleDock,
  leftCollapsed,
}: {
  onOpenSettings: () => void;
  onToggleLeft: () => void;
  onToggleDock: () => void;
  leftCollapsed: boolean;
}) {
  const { currentSession, messages } = useCopilotChat();
  const { chatView, setChatView } = useAppState();
  const stats = useSessionStats(messages);
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

        {stats.tools > 0 && (
          <div className="topbar3-chips" data-tauri-drag-region="false">
            <button
              type="button"
              className={`topbar-chip${chatView === "trajectory" ? " on" : ""}`}
              title="查看执行轨迹"
              onClick={() => setChatView("trajectory")}
            >
              <ToolGlyph />
              {stats.tools} 个工具
            </button>
            {stats.subagents > 0 && (
              <button
                type="button"
                className={`topbar-chip${chatView === "trajectory" ? " on" : ""}`}
                title="查看子代理"
                onClick={() => setChatView("trajectory")}
              >
                <SubagentGlyph />
                {stats.subagents} 个子代理
              </button>
            )}
          </div>
        )}

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
