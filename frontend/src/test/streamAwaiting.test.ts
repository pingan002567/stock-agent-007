import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  STREAM_AWAITING_NEXT_EVENT_MS,
  useStreamAwaitingNextEvent,
} from "@/hooks/useStreamAwaitingNextEvent";

describe("useStreamAwaitingNextEvent", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("stays false while inactive", () => {
    const { result } = renderHook(() => useStreamAwaitingNextEvent(false, "1"));
    act(() => {
      vi.advanceTimersByTime(STREAM_AWAITING_NEXT_EVENT_MS + 50);
    });
    expect(result.current).toBe(false);
  });

  it("becomes true after idle gap when active", () => {
    const { result } = renderHook(() => useStreamAwaitingNextEvent(true, "1"));
    expect(result.current).toBe(false);
    act(() => {
      vi.advanceTimersByTime(STREAM_AWAITING_NEXT_EVENT_MS + 10);
    });
    expect(result.current).toBe(true);
  });

  it("resets when content revision changes", () => {
    const { result, rerender } = renderHook(
      ({ rev }) => useStreamAwaitingNextEvent(true, rev),
      { initialProps: { rev: "a" } },
    );
    act(() => {
      vi.advanceTimersByTime(STREAM_AWAITING_NEXT_EVENT_MS + 10);
    });
    expect(result.current).toBe(true);
    rerender({ rev: "b" });
    expect(result.current).toBe(false);
    act(() => {
      vi.advanceTimersByTime(STREAM_AWAITING_NEXT_EVENT_MS + 10);
    });
    expect(result.current).toBe(true);
  });
});
