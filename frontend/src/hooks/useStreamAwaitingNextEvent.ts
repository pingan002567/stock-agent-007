import { useEffect, useState } from "react";

/** 有流但短暂无新内容时，显示「等待下一事件」提示的间隔 */
export const STREAM_AWAITING_NEXT_EVENT_MS = 500;

/**
 * 流式进行中、且 contentRevision 一段时间未变 → awaiting=true。
 * 用于短空档三点动画；与 45s stuck 区分。
 */
export function useStreamAwaitingNextEvent(
  active: boolean,
  contentRevision: number | string,
  idleMs: number = STREAM_AWAITING_NEXT_EVENT_MS,
): boolean {
  const [awaiting, setAwaiting] = useState(false);

  useEffect(() => {
    if (!active) {
      setAwaiting(false);
      return;
    }
    setAwaiting(false);
    const timer = window.setTimeout(() => setAwaiting(true), idleMs);
    return () => window.clearTimeout(timer);
  }, [active, contentRevision, idleMs]);

  return awaiting;
}
