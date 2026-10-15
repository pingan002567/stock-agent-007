import { useCallback, useEffect, useState } from "react";
import { AppActionsProvider } from "@/hooks/useAppActions";
import { useAppState } from "@/hooks/useAppState";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import { CopilotPanel } from "@/components/features/CopilotPanel";
import { CopilotComposer } from "@/components/features/CopilotComposer";
import { LeftSidebar } from "@/components/layout/LeftSidebar";
import { ScreenRenderer } from "@/pages/ScreenRenderer";
import { WorkspaceModal } from "@/components/features/WorkspaceModal";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { useToast } from "@/hooks/useToast";
import { displaySessionTitle } from "@/lib/sessionTitle";
import type { Screen } from "@/types";

const TABS: { screen: Screen; label: string; icon: string }[] = [
  { screen: "chat", label: "对话", icon: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" },
  { screen: "watchlist", label: "自选", icon: "M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" },
  { screen: "holdings", label: "持仓", icon: "M3 3v18h18M18.7 8l-5.1 5.2-2.8-2.7L7 14.3" },
  { screen: "monitor", label: "盯盘", icon: "M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0" },
  { screen: "settings", label: "设置", icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" },
];

/** Cursor iOS 式：全屏聊天、左滑会话抽屉、底栏 Tab。 */
export function MobileShell({ onSwitchBackend }: { onSwitchBackend: () => void }) {
  const { showToast } = useToast();
  const { currentScreen, setCurrentScreen } = useAppState();
  const { currentSession, handleNewSession } = useCopilotChat();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    const vv = window.visualViewport;
    const apply = () => {
      const kb = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
      root.style.setProperty("--kb", `${Math.round(kb)}px`);
      root.classList.toggle("kb-open", kb > 80);
    };
    apply();
    vv?.addEventListener("resize", apply);
    vv?.addEventListener("scroll", apply);
    return () => {
      vv?.removeEventListener("resize", apply);
      vv?.removeEventListener("scroll", apply);
      root.style.removeProperty("--kb");
      root.classList.remove("kb-open");
    };
  }, []);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  const openWorkspace = useCallback(() => {
    setDrawerOpen(false);
    setWorkspaceOpen(true);
  }, []);
  const openSettings = useCallback(() => {
    setDrawerOpen(false);
    setCurrentScreen("settings");
  }, [setCurrentScreen]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeDrawer(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [closeDrawer, drawerOpen]);

  const title = currentScreen === "chat"
    ? displaySessionTitle(currentSession?.title, "Stock Agent")
    : (TABS.find((t) => t.screen === currentScreen)?.label ?? "Stock Agent");

  return (
    <AppActionsProvider
      openSettings={openSettings}
      openWorkspace={openWorkspace}
      switchBackend={onSwitchBackend}
    >
      <div className="m-app">
        <header className="m-header">
          <button type="button" className="m-header-btn" aria-label="会话列表" onClick={() => setDrawerOpen(true)}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
              <rect x="3" y="4" width="18" height="16" rx="2" />
              <path d="M9 4v16" />
            </svg>
          </button>
          <div className="m-header-title">{title}</div>
          {currentScreen === "chat" ? (
            <button
              type="button"
              className="m-header-btn"
              aria-label="新对话"
              onClick={() => { void handleNewSession(); setCurrentScreen("chat"); }}
            >
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
                <path d="M12 5v14M5 12h14" />
              </svg>
            </button>
          ) : (
            <span className="m-header-btn" aria-hidden />
          )}
        </header>

        <div className="m-body">
          {currentScreen === "chat" ? (
            <>
              <div className="m-chat">
                <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
                  <CopilotPanel />
                </ErrorBoundary>
              </div>
              <div className="m-composer">
                <CopilotComposer />
              </div>
            </>
          ) : (
            <div className="m-page">
              <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
                <ScreenRenderer />
              </ErrorBoundary>
            </div>
          )}
        </div>

        <nav className="m-tabs" aria-label="主导航">
          {TABS.map((tab) => (
            <button
              key={tab.screen}
              type="button"
              className={`m-tab${currentScreen === tab.screen ? " on" : ""}`}
              onClick={() => setCurrentScreen(tab.screen)}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d={tab.icon} />
              </svg>
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>

        {drawerOpen ? (
          <div className="m-drawer-root">
            <button type="button" className="m-drawer-backdrop" aria-label="关闭" onClick={closeDrawer} />
            <div className="m-drawer" role="dialog" aria-label="会话">
              <LeftSidebar
                variant="drawer"
                onOpenSettings={openSettings}
                onOpenWorkspace={openWorkspace}
                onSessionPicked={() => { closeDrawer(); setCurrentScreen("chat"); }}
              />
            </div>
          </div>
        ) : null}

        <WorkspaceModal open={workspaceOpen} onClose={() => setWorkspaceOpen(false)} />
      </div>
    </AppActionsProvider>
  );
}
