import { useEffect, useState } from "react";
import { AppStateProvider } from "@/hooks/useAppState";
import { CopilotChatProvider } from "@/hooks/useCopilotChat";
import { ChatDetailProvider } from "@/hooks/useChatDetail";
import { LeftSidebar } from "@/components/layout/LeftSidebar";
import { FunctionDock } from "@/components/layout/FunctionDock";
import { CopilotPanel } from "@/components/features/CopilotPanel";
import { SettingsModal } from "@/components/features/SettingsModal";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { ToastProvider, useToast } from "@/hooks/useToast";
import { setOnApiError } from "@/api/client";

/** 三栏骨架（doc/design/three-column-mockup.html）：
 * 左栏会话+设置 │ 中栏常驻聊天 │ 右侧功能坞（图标条 + 可展开业务面板）。
 * currentScreen 语义 = 右栏面板内容，"chat" 表示面板收起。
 * 系统设置走独立悬浮模态（TeamClaw 式），不占功能坞。 */
function AppShell() {
  const { showToast } = useToast();
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <div className="app">
      <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
        <LeftSidebar onOpenSettings={() => setSettingsOpen(true)} />
      </ErrorBoundary>
      <main className="center">
        <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
          <CopilotPanel variant="main" />
        </ErrorBoundary>
      </main>
      <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
        <FunctionDock />
      </ErrorBoundary>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
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
