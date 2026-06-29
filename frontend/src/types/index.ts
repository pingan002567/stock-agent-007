export type Screen =
  | "overview"
  | "watchlist"
  | "holdings"
  | "research"
  | "market"
  | "monitor"
  | "strategies"
  | "tasks"
  | "reports"
  | "settings"
  | "worldcup";

export interface AppState {
  currentScreen: Screen;
  currentScreenLabel: string;
  stock: string;
  copilotStreaming: boolean;
  streamingReasoningText: string;
}

export interface CopilotEvent {
  type: string;
  payload: Record<string, unknown>;
  text?: string;
  role?: string | null;
  created_at?: string | null;
}
