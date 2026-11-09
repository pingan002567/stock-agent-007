import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const apiGet = vi.fn();
vi.mock("@/api/client", () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  apiPut: vi.fn(),
}));

const cacheRef: { current: Record<string, unknown> } = { current: {} };
const state = { lastRefreshTime: "2026-11-09T01:00:00Z" as string | null };

vi.mock("@/hooks/useAppState", () => ({
  useAppState: () => ({
    appDataCache: cacheRef,
    globalLoading: false,
    lastRefreshTime: state.lastRefreshTime,
    setStock: vi.fn(),
    setCurrentScreen: vi.fn(),
  }),
}));

vi.mock("@/hooks/useCopilotChat", () => ({
  useCopilotChat: () => ({ askWithContext: vi.fn(), openPanel: vi.fn() }),
}));

import Watchlist from "@/pages/Watchlist";

const item = (last: number) => ([{
  symbol: "000963", name: "华东医药", market: "CN", group: "默认",
  monitored: false, quote_degraded: false,
  price: { last, change_pct: 1.2, degraded: false },
}]);

describe("自选页现价跟随全局轮询", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiGet.mockImplementation(async (url: string) =>
      url === "/api/watchlist" ? item(26.15) : []);
  });

  it("全局刷新后（lastRefreshTime 变化）直接吃缓存的最新价，不再等手动刷新", async () => {
    const { rerender } = render(<Watchlist />);
    await waitFor(() => expect(screen.getByText(/26\.1/)).toBeTruthy());

    // 模拟 useAppState 轮询完成：cache 更新 + lastRefreshTime 变化
    cacheRef.current.watchlist = item(27.72);
    state.lastRefreshTime = "2026-11-09T01:01:00Z";
    rerender(<Watchlist />);

    await waitFor(() => expect(screen.getByText(/27\.7/)).toBeTruthy());
  });
});
