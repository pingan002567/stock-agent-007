/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type ReactNode } from "react";

export type SettingsTabHint = "ai" | "ai-models" | "data";

interface AppActionsValue {
  openSettings: (tab?: SettingsTabHint) => void;
  openWorkspace: () => void;
}

const AppActionsContext = createContext<AppActionsValue | null>(null);

export function AppActionsProvider({
  children,
  openSettings,
  openWorkspace,
}: AppActionsValue & { children: ReactNode }) {
  return (
    <AppActionsContext.Provider value={{ openSettings, openWorkspace }}>
      {children}
    </AppActionsContext.Provider>
  );
}

export function useAppActions(): AppActionsValue {
  const ctx = useContext(AppActionsContext);
  if (!ctx) throw new Error("useAppActions must be used within AppActionsProvider");
  return ctx;
}
