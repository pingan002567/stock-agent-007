import { useEffect, useState } from "react";
import { AppStateProvider, useAppState } from "@/hooks/useAppState";
import { CopilotChatProvider } from "@/hooks/useCopilotChat";
import { ChatDetailProvider } from "@/hooks/useChatDetail";
import { Rail } from "@/components/layout/Rail";
import { ScreenRenderer } from "@/pages/ScreenRenderer";
import { CopilotPanel } from "@/components/features/CopilotPanel";
import { LoadingOverlay } from "@/components/ui/LoadingOverlay";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { ToastProvider, useToast } from "@/hooks/useToast";
import { setOnApiError } from "@/api/client";

function AppShell() {
  const [copilotOpen, setCopilotOpen] = useState(true);
  const { currentScreen } = useAppState();
  const { showToast } = useToast();
  // 聊天中心主屏（chat）里聊天就是主区，不再渲染右侧伴随面板；
  // 业务页保持原有可折叠侧栏。两处共享 CopilotChatProvider，切换不断流。
  const isChatScreen = currentScreen === "chat";
  return (
    <div className={`app${isChatScreen ? " chat-mode" : copilotOpen ? "" : " copilot-closed"}`}>
      <Rail />
      <main className="main">
        <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
          <ScreenRenderer />
        </ErrorBoundary>
      </main>
      {!isChatScreen && (
        <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
          <CopilotPanel open={copilotOpen} onToggle={() => setCopilotOpen((v) => !v)} />
        </ErrorBoundary>
      )}
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
          <LoadingOverlay />
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
