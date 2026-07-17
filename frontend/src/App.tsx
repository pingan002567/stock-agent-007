import { useEffect, useState } from "react";
import { AppStateProvider, useAppState } from "@/hooks/useAppState";
import { CopilotChatProvider } from "@/hooks/useCopilotChat";
import { ChatDetailProvider, useChatDetail } from "@/hooks/useChatDetail";
import { TopBar } from "@/components/layout/TopBar";
import { LeftSidebar } from "@/components/layout/LeftSidebar";
import { FunctionDock } from "@/components/layout/FunctionDock";
import { CopilotPanel } from "@/components/features/CopilotPanel";
import { SettingsModal } from "@/components/features/SettingsModal";
import { WorkspaceModal } from "@/components/features/WorkspaceModal";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { ToastProvider, useToast } from "@/hooks/useToast";
import { setOnApiError } from "@/api/client";

/** 三栏骨架（doc/design/three-column-mockup.html）：
 * 左栏会话+设置 │ 中栏常驻聊天 │ 右侧功能坞（图标条 + 可展开业务面板）。
 * currentScreen 语义 = 右栏面板内容，"chat" 表示面板收起。
 * 系统设置走独立悬浮模态（TeamClaw 式），不占功能坞。 */
function AppShell() {
  const { showToast } = useToast();
  const { currentScreen, setCurrentScreen } = useAppState();
  const { open: detailOpen, closeDetail } = useChatDetail();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);

  // 顶栏统一控制左右栏折叠（TeamClaw 式），状态持久化
  const [leftCollapsed, setLeftCollapsed] = useState(
    () => localStorage.getItem("left-sidebar-collapsed") === "1",
  );
  const [dockCollapsed, setDockCollapsed] = useState(
    () => localStorage.getItem("func-dock-collapsed") === "1",
  );
  const toggleLeft = () => setLeftCollapsed((v) => {
    const next = !v;
    try { localStorage.setItem("left-sidebar-collapsed", next ? "1" : "0"); } catch { /* ignore */ }
    return next;
  });
  const toggleDock = () => setDockCollapsed((v) => {
    const next = !v;
    try { localStorage.setItem("func-dock-collapsed", next ? "1" : "0"); } catch { /* ignore */ }
    if (next) { closeDetail(); setCurrentScreen("chat"); } // 收起时联动关闭业务面板
    return next;
  });

  // 桌面壳（Tauri 远程 IPC 已授权）：desktop 态——红绿灯住进顶栏、顶栏可拖拽
  useEffect(() => {
    if (window.__TAURI__) document.documentElement.classList.add("desktop");
  }, []);

  // 顶栏右段列宽与功能坞同步（列头对齐）：面板开 = 52+面板宽,坞收 = 仅按钮位
  const panelOpen = !dockCollapsed && (detailOpen || currentScreen !== "chat");

  // 断点降级:窄窗下右栏展开会把中栏聊天挤到不可用,自动临时收起左栏
  // (不写 localStorage——这是布局联动,不是用户偏好)
  useEffect(() => {
    if (panelOpen && window.innerWidth < 1280) setLeftCollapsed(true);
  }, [panelOpen]);
  const appCls = [
    "app",
    leftCollapsed ? "left-collapsed" : "",
    dockCollapsed ? "dock-collapsed" : "",
    panelOpen ? "panel-open" : "",
  ].filter(Boolean).join(" ");

  return (
    <div className={appCls}>
      <TopBar
        leftCollapsed={leftCollapsed}
        onToggleLeft={toggleLeft}
        dockCollapsed={dockCollapsed}
        onToggleDock={toggleDock}
      />
      <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
        <LeftSidebar
          onOpenSettings={() => setSettingsOpen(true)}
          onOpenWorkspace={() => setWorkspaceOpen(true)}
        />
      </ErrorBoundary>
      <main className="center">
        <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
          <CopilotPanel variant="main" />
        </ErrorBoundary>
      </main>
      <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
        {!dockCollapsed && <FunctionDock />}
      </ErrorBoundary>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <WorkspaceModal open={workspaceOpen} onClose={() => setWorkspaceOpen(false)} />
    </div>
  );
}

function AppContent() {
  const { showToast } = useToast();
  useEffect(() => {
    setOnApiError((err) => {
      // 404 错误不显示提醒
      if (err.status === 404) return;
      showToast(err.message, err.status >= 500 ? "error" : err.status === 0 ? "error" : "info");
    });
    return () => setOnApiError(null);
  }, [showToast]);
  return (
    <AppStateProvider>
      <CopilotChatProvider>
        <ChatDetailProvider>
          <AppShell />
        </ChatDetailProvider>
      </CopilotChatProvider>
    </AppStateProvider>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <ErrorBoundary>
        <AppContent />
      </ErrorBoundary>
    </ToastProvider>
  );
}
