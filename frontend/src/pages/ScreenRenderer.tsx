import { Suspense, lazy } from "react";
import { useAppState } from "@/hooks/useAppState";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

const Overview = lazy(() => import("./Overview"));
const Watchlist = lazy(() => import("./Watchlist"));
const Holdings = lazy(() => import("./Holdings"));
const Research = lazy(() => import("./Research"));
const Monitor = lazy(() => import("./Monitor"));
const Strategies = lazy(() => import("./Strategies"));
const Tasks = lazy(() => import("./Tasks"));
const Reports = lazy(() => import("./Reports"));
const Settings = lazy(() => import("./Settings"));

const LOADING = <div className="page-loading">加载中…</div>;

export function ScreenRenderer() {
  const { currentScreen } = useAppState();
  const page = (() => {
    switch (currentScreen) {
      case "chat": return null; // chat = 右栏面板收起，中栏聊天由 App 常驻渲染
      case "overview": return <Overview />;
      case "watchlist": return <Watchlist />;
      case "holdings": return <Holdings />;
      case "research": return <Research />;
      case "monitor": return <Monitor />;
      case "strategies": return <Strategies />;
      case "tasks": return <Tasks />;
      case "reports": return <Reports />;
      case "settings": return <Settings />;
    }
  })();
  // key=currentScreen ensures ErrorBoundary remounts on page switch,
  // preventing error state from leaking across pages
  return <Suspense fallback={LOADING}>{page ? <ErrorBoundary key={currentScreen}>{page}</ErrorBoundary> : null}</Suspense>;
}
