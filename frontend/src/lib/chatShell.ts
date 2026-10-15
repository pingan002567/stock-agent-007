/** Agent 聊天壳布局常量（借鉴 TeamClu LAYOUT_SPACING，防回归）。 */

/** 消息列表底部相对输入区额外留白（px） */
export const SAFE_BOTTOM_SPACING = 32;

/** 距底多少像素内视为「贴底」，新内容才自动滚到底 */
export const NEAR_BOTTOM_THRESHOLD = 150;

/** 流式无 SSE/心跳超过此时长则提示可能卡住（真正静默，非长工具执行） */
export const STUCK_IDLE_MS = 90_000;

export const CHAT_COMPOSER_HEIGHT_VAR = "--chat-composer-height";

export function composerPaddingBottom(composerHeightPx: number): number {
  return Math.max(0, Math.round(composerHeightPx)) + SAFE_BOTTOM_SPACING;
}

/** 用回答/工具状态/阶段拼进度指纹，用于内容推进检测 */
export function streamProgressKey(parts: {
  phase?: string | null;
  answerText?: string | null;
  toolCount?: number;
  /** per-tool status fingerprint so tool_result always counts as progress */
  toolStatuses?: string | null;
  clarification?: boolean;
  errorText?: string | null;
}): string {
  return [
    parts.phase || "",
    String(parts.answerText?.length ?? 0),
    String(parts.toolCount ?? 0),
    parts.toolStatuses || "",
    parts.clarification ? "1" : "0",
    parts.errorText ? "1" : "0",
  ].join("|");
}

/** Build tool status segment for streamProgressKey */
export function toolStatusesKey(
  tools: Array<{ callId?: string; id?: string; status?: string }> | null | undefined,
): string {
  if (!tools?.length) return "";
  return tools
    .map((t) => `${t.callId || t.id || ""}:${t.status || ""}`)
    .join(",");
}

export type RunLivePhase = "starting" | "llm" | "tool" | "awaiting_human" | "finishing" | string;

export interface RunLiveness {
  lastAt: number;
  status: string;
  phase: RunLivePhase;
  currentTool: string | null;
  alive: boolean;
}

export function workingDockCopy(liveness: RunLiveness | null | undefined): {
  title: string;
  detail?: string;
} {
  if (!liveness) {
    return { title: "正在生成…", detail: "连接正常，请稍候。" };
  }
  if (liveness.phase === "tool" && liveness.currentTool) {
    return {
      title: `正在执行 ${liveness.currentTool}…`,
      detail: "长工具调用中，心跳正常。",
    };
  }
  if (liveness.phase === "awaiting_human") {
    return { title: "等待你的回复", detail: "本轮已暂停在澄清步骤。" };
  }
  if (liveness.phase === "llm" || liveness.phase === "starting") {
    return { title: "模型推理中…", detail: "连接正常，请稍候。" };
  }
  return { title: "正在生成…", detail: "连接正常，请稍候。" };
}
