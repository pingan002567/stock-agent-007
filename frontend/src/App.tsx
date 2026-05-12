import { useEffect, useState } from "react";
import { AppStateProvider } from "@/hooks/useAppState";
import { Rail } from "@/components/layout/Rail";
import { ScreenRenderer } from "@/pages/ScreenRenderer";
import { CopilotPanel } from "@/components/features/CopilotPanel";
import { LoadingOverlay } from "@/components/ui/LoadingOverlay";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { ToastProvider, useToast } from "@/hooks/useToast";
import { setOnApiError } from "@/api/client";

function AppContent() {
  const [copilotOpen, setCopilotOpen] = useState(true);
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
      <LoadingOverlay />
      <div className={`app${copilotOpen ? "" : " copilot-closed"}`}>
        <Rail />
        <main className="main">
          <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
            <ScreenRenderer />
          </ErrorBoundary>
        </main>
        <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
          <CopilotPanel open={copilotOpen} onToggle={() => setCopilotOpen((v) => !v)} />
        </ErrorBoundary>
      </div>
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
