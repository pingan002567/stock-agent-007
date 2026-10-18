import { useEffect, useMemo, useRef, useState } from "react";
import { useAppState } from "@/hooks/useAppState";
import { PET_ENABLED_KEY, PET_STATE_KEY, type PetPayload } from "@/lib/petBridge";
import type { PetState } from "@/components/pet/ShibaPet";

/** done 状态在气泡里停留多久 */
const DONE_MS = 8000;

type TauriGlobal = { core?: { invoke?: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> } };

/** 主窗口侧：把运行状态发布给桌宠窗口。
 *
 *  优先级：working > done(8s) > alert > idle。
 *  （设计稿里把 alert 排在最前，但 working 是瞬时的、最能说明"正在发生什么"，
 *    而且高优待办数一直挂在角标上，不会被盖掉。）
 */
export function usePetBridge() {
  const { copilotStreaming, appDataCache, lastRefreshTime } = useAppState();

  // appDataCache 是 ref，读 .current 不会触发更新；跟着刷新时间重算
  const highCount = useMemo(() => {
    // appDataCache 是 ref，读 .current 不会触发更新；靠 lastRefreshTime 变体驱动重算
    void lastRefreshTime;
    const s = appDataCache.current.inboxSummary as { high_count?: number } | undefined;
    return s?.high_count ?? 0;
  }, [appDataCache, lastRefreshTime]);

  const [doneVisible, setDoneVisible] = useState(false);
  const doneTimer = useRef<number | null>(null);
  const prevStreaming = useRef(copilotStreaming);

  // 流式结束（true -> false）= 一轮跑完，done 展示 8s
  useEffect(() => {
    if (prevStreaming.current && !copilotStreaming) {
      setDoneVisible(true);
      if (doneTimer.current) window.clearTimeout(doneTimer.current);
      doneTimer.current = window.setTimeout(() => setDoneVisible(false), DONE_MS);
    }
    prevStreaming.current = copilotStreaming;
    return () => {
      if (doneTimer.current) window.clearTimeout(doneTimer.current);
    };
  }, [copilotStreaming]);

  const { state, title, body } = useMemo<{ state: PetState; title?: string; body?: string }>(() => {
    if (copilotStreaming) return { state: "working", title: "正在想…" };
    if (doneVisible) return { state: "done", title: "✅ 回答好了", body: "这一轮已经跑完，回来看结果" };
    if (highCount > 0) return { state: "alert", title: "⚠ 高优待办", body: `${highCount} 条高优待处理` };
    return { state: "idle" };
  }, [copilotStreaming, doneVisible, highCount]);

  // 发布状态
  useEffect(() => {
    const payload: PetPayload = { state, title, body, badge: highCount, at: Date.now() };
    try {
      localStorage.setItem(PET_STATE_KEY, JSON.stringify(payload));
    } catch {
      /* 隐私模式下可能抛错，忽略 */
    }
  }, [state, title, body, highCount]);

  // 按开关显示桌宠窗口
  useEffect(() => {
    const invoke = (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__?.core?.invoke;
    if (!invoke) return;
    const enabled = localStorage.getItem(PET_ENABLED_KEY) !== "0";
    void invoke("pet_set_visible", { visible: enabled }).catch(() => {});
  }, []);
}
