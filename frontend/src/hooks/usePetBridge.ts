import { useEffect, useMemo, useRef, useState } from "react";
import { useAppState } from "@/hooks/useAppState";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import { useToast } from "@/hooks/useToast";
import { stripInlineMarkdown } from "@/utils/format";
import { PET_ENABLED_KEY, PET_STATE_KEY, type PetPayload, type PetState } from "@/lib/petBridge";

/** done 在气泡里停留多久 */
const DONE_MS = 8000;
/** 新增高优待办时，alert 姿态持续多久（之后回 idle，角标仍显示数量） */
const ALERT_MS = 10000;
/** 报错姿态持续多久 */
const ERROR_MS = 8000;

type TauriGlobal = { core?: { invoke?: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> } };

/** 主窗口侧：把运行状态发布给桌宠窗口。
 *
 *  优先级：error(8s) > working > done(8s) > alert(10s, 仅新增高优时) > idle。
 *  - working 排最前：最能说明"正在发生什么"；高优待办数一直挂在角标上，不会被盖掉
 *  - alert 只在「高优数量增加」时触发：待办会一直在，否则宠物会永远惊恐脸
 */
export function usePetBridge() {
  const { copilotStreaming, appDataCache, lastRefreshTime } = useAppState();
  const { messages } = useCopilotChat();
  const { toasts } = useToast();

  // appDataCache 是 ref，读 .current 不会触发更新；跟着刷新时间重算
  const highCount = useMemo(() => {
    void lastRefreshTime;
    const s = appDataCache.current.inboxSummary as { high_count?: number } | undefined;
    return s?.high_count ?? 0;
  }, [appDataCache, lastRefreshTime]);

  // 三种"临时姿态"用布尔/对象状态 + 定时器收尾，避免在 render 里比较 Date.now()
  const [doneVisible, setDoneVisible] = useState(false);
  const [alertVisible, setAlertVisible] = useState(false);
  const [errorVisible, setErrorVisible] = useState<{ body: string } | null>(null);

  const prevStreaming = useRef(copilotStreaming);
  const prevHigh = useRef(highCount);
  const seenToastId = useRef(0);
  const timers = useRef<number[]>([]);

  const later = (fn: () => void, ms: number) => {
    timers.current.push(window.setTimeout(fn, ms));
  };

  // 流式结束（true -> false）= 一轮跑完
  useEffect(() => {
    if (prevStreaming.current && !copilotStreaming) {
      setDoneVisible(true);
      later(() => setDoneVisible(false), DONE_MS);
    }
    prevStreaming.current = copilotStreaming;
  }, [copilotStreaming]);

  // 只有「高优数量增加」才吓一跳
  useEffect(() => {
    if (highCount > prevHigh.current) {
      setAlertVisible(true);
      later(() => setAlertVisible(false), ALERT_MS);
    }
    prevHigh.current = highCount;
  }, [highCount]);

  // 报错：取最新一条 error toast
  useEffect(() => {
    const err = [...toasts].reverse().find((t) => t.type === "error");
    if (!err || err.id === seenToastId.current) return;
    seenToastId.current = err.id;
    setErrorVisible({ body: stripInlineMarkdown(err.message).slice(0, 48) });
    later(() => setErrorVisible(null), ERROR_MS);
  }, [toasts]);

  // 卸载时清掉所有定时器
  useEffect(() => {
    const list = timers.current;
    return () => list.forEach((t) => window.clearTimeout(t));
  }, []);

  /** 最后一条助手消息的前 30 字，作为 done 气泡的摘要 */
  const lastReply = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const m = messages[i];
      if (m.role !== "assistant" || !m.text) continue;
      const t = stripInlineMarkdown(m.text).replace(/\s+/g, " ").trim();
      if (t) return t.length > 30 ? `${t.slice(0, 30)}…` : t;
    }
    return "";
  }, [messages]);

  const { state, title, body } = useMemo<{ state: PetState; title?: string; body?: string }>(() => {
    if (errorVisible) return { state: "error", title: "❌ 出错了", body: errorVisible.body };
    if (copilotStreaming) return { state: "working", title: "正在想…", body: lastReply };
    if (doneVisible) return { state: "done", title: "✅ 回答好了", body: lastReply || "这一轮已经跑完" };
    if (alertVisible) return { state: "alert", title: "⚠ 新增高优待办", body: `${highCount} 条高优待处理` };
    return { state: "idle" };
  }, [errorVisible, copilotStreaming, doneVisible, lastReply, alertVisible, highCount]);

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
