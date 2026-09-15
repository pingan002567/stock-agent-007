import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AppStateProvider, useAppState } from "@/hooks/useAppState";
import { AppActionsProvider, type SettingsTabHint } from "@/hooks/useAppActions";
import { CopilotChatProvider } from "@/hooks/useCopilotChat";
import { ChatDetailProvider, useChatDetail } from "@/hooks/useChatDetail";
import { TopBar } from "@/components/layout/TopBar";
import { BottomBar } from "@/components/layout/BottomBar";
import { LeftSidebar } from "@/components/layout/LeftSidebar";
import { FunctionDock } from "@/components/layout/FunctionDock";
import { CopilotPanel } from "@/components/features/CopilotPanel";
import { SettingsModal } from "@/components/features/SettingsModal";
import { WorkspaceModal } from "@/components/features/WorkspaceModal";
import { SetupWizard } from "@/components/features/SetupWizard";
import { ConnectionGate } from "@/components/features/ConnectionGate";
import { MobileShell } from "@/components/layout/MobileShell";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { ToastProvider, useToast } from "@/hooks/useToast";
import { useMobileLayout } from "@/hooks/useMobileLayout";
import { ApiError, setOnApiError } from "@/api/client";
import { fetchSetupStatus, type SetupStatus } from "@/api/setup";
import { interceptAnchorClick, isAppLocalHref, openExternalUrl } from "@/lib/openExternalUrl";
import { shouldShowSetupWizard } from "@/lib/onboarding";

/** 三栏骨架（doc/design/three-column-mockup.html）：
 * 左栏会话+设置 │ 中栏常驻聊天 │ 右侧功能坞（图标条 + 可展开业务面板）。
 * currentScreen 语义 = 右栏面板内容，"chat" 表示面板收起。
 * 系统设置走独立悬浮模态（TeamClaw 式），不占功能坞。 */
function AppShell({ onSwitchBackend }: { onSwitchBackend: () => void }) {
  const { showToast } = useToast();
  const { currentScreen, setCurrentScreen } = useAppState();
  const { open: detailOpen, closeDetail } = useChatDetail();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTabHint | undefined>();
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const openSettings = useCallback((tab?: SettingsTabHint) => {
    setSettingsTab(tab);
    setSettingsOpen(true);
  }, []);
  const closeSettings = useCallback(() => {
    setSettingsOpen(false);
    setSettingsTab(undefined);
  }, []);
  const openWorkspace = useCallback(() => setWorkspaceOpen(true), []);

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
    if (next) { closeDetail(); setCurrentScreen("chat"); }
    return next;
  });

  const panelOpen = !dockCollapsed && (detailOpen || currentScreen !== "chat");

  // 窄窗 + 右栏展开时临时收起左栏（不写 localStorage）
  useEffect(() => {
    if (panelOpen && window.innerWidth < 1280) setLeftCollapsed(true);
  }, [panelOpen]);

  // 桌面壳（Tauri 远程 IPC 已授权）：desktop 态——红绿灯住进顶栏、顶栏可拖拽
  useEffect(() => {
    if (window.__TAURI__) document.documentElement.classList.add("desktop");
  }, []);

  // 顶栏右段列宽与功能坞同步（列头对齐）：面板开 = 52+面板宽,坞收 = 仅按钮位
  const appCls = [
    "app",
    leftCollapsed ? "left-collapsed" : "",
    dockCollapsed ? "dock-collapsed" : "",
  ].filter(Boolean).join(" ");

  return (
    <AppActionsProvider
      openSettings={openSettings}
      openWorkspace={openWorkspace}
      switchBackend={onSwitchBackend}
    >
      <div className={appCls}>
        <TopBar
          leftCollapsed={leftCollapsed}
          onToggleLeft={toggleLeft}
          dockCollapsed={dockCollapsed}
          onToggleDock={toggleDock}
        />
        <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
          <LeftSidebar
            onOpenSettings={() => openSettings()}
            onOpenWorkspace={openWorkspace}
          />
        </ErrorBoundary>
        <main className="center">
          <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
            <CopilotPanel />
          </ErrorBoundary>
        </main>
        <ErrorBoundary onError={(e) => showToast(e.message, "error")}>
          {!dockCollapsed && <FunctionDock />}
        </ErrorBoundary>
        <BottomBar
          leftCollapsed={leftCollapsed}
          onOpenSettings={() => openSettings()}
          onOpenWorkspace={openWorkspace}
        />
        <SettingsModal open={settingsOpen} initialTab={settingsTab} onClose={closeSettings} />
        <WorkspaceModal open={workspaceOpen} onClose={() => setWorkspaceOpen(false)} />
      </div>
    </AppActionsProvider>
  );
}

function SetupGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void fetchSetupStatus().then((next) => {
      if (!cancelled) setStatus(next);
    }).catch((err) => {
      if (cancelled) return;
      // 旧后端没有这条接口时不要挡住主界面
      if (err instanceof ApiError && err.status === 404) {
        setStatus({ completed: true, required: false, model_connected: false, default_model: null });
        return;
      }
      setError(err instanceof Error ? err.message : "无法确认是否需要开始设置");
    });
    return () => { cancelled = true; };
  }, []);

  if (!status && !error) {
    return <div className="setup-boot">正在打开工作台…</div>;
  }
  if (error && !status) {
    return (
      <div className="setup-boot">
        <p>{error}</p>
        <button type="button" className="primary" onClick={() => window.location.reload()}>重试</button>
      </div>
    );
  }
  if (status && shouldShowSetupWizard(status)) {
    return <SetupWizard initialStatus={status} onFinished={() => setStatus({ ...status, completed: true, required: false })} />;
  }
  return <>{children}</>;
}

function AppContent() {
  const { showToast } = useToast();
  const mobile = useMobileLayout();
  const [bootEpoch, setBootEpoch] = useState(0);
  const [forceSelect, setForceSelect] = useState(false);
  const [ready, setReady] = useState(false);

  const handleConnected = useCallback(() => {
    setForceSelect(false);
    setBootEpoch((n) => n + 1);
    setReady(true);
  }, []);

  const switchBackend = useCallback(() => {
    setForceSelect(true);
    setReady(false);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("mobile", mobile);
    return () => document.documentElement.classList.remove("mobile");
  }, [mobile]);

  useEffect(() => {
    setOnApiError((err) => {
      // 404 错误不显示提醒
      if (err.status === 404) return;
      showToast(err.message, err.status >= 500 ? "error" : err.status === 0 ? "error" : "info");
    });
    return () => setOnApiError(null);
  }, [showToast]);
  useEffect(() => {
    const onClick = (ev: MouseEvent) => {
      interceptAnchorClick(ev);
    };
    document.addEventListener("click", onClick, true);
    document.addEventListener("auxclick", onClick, true);
    const origOpen = window.open.bind(window);
    window.open = ((url?: string | URL, target?: string, features?: string) => {
      const href = typeof url === "string" ? url : url?.toString();
      if (href && !isAppLocalHref(href)) {
        void openExternalUrl(href);
        return null;
      }
      return origOpen(url, target, features);
    }) as typeof window.open;
    return () => {
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("auxclick", onClick, true);
      window.open = origOpen;
    };
  }, []);

  if (!ready) {
    return <ConnectionGate forceSelect={forceSelect} onConnected={handleConnected} />;
  }

  return (
    <AppStateProvider key={bootEpoch}>
      <CopilotChatProvider>
        <ChatDetailProvider>
          <SetupGate>
            {mobile ? <MobileShell onSwitchBackend={switchBackend} /> : <AppShell onSwitchBackend={switchBackend} />}
          </SetupGate>
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
