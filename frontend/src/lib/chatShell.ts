/** Agent 聊天壳布局常量（借鉴 TeamClu LAYOUT_SPACING，防回归）。 */

/** 消息列表底部相对输入区额外留白（px） */
export const SAFE_BOTTOM_SPACING = 32;

/** 距底多少像素内视为「贴底」，新内容才自动滚到底 */
export const NEAR_BOTTOM_THRESHOLD = 150;

/** 流式无进度超过此时长则提示可能卡住 */
export const STUCK_IDLE_MS = 45_000;

export const CHAT_COMPOSER_HEIGHT_VAR = "--chat-composer-height";

export function composerPaddingBottom(composerHeightPx: number): number {
  return Math.max(0, Math.round(composerHeightPx)) + SAFE_BOTTOM_SPACING;
}

/** 用回答/工具/阶段拼进度指纹，用于卡住检测 */
export function streamProgressKey(parts: {
  phase?: string | null;
  answerText?: string | null;
  toolCount?: number;
  clarification?: boolean;
  errorText?: string | null;
}): string {
  return [
    parts.phase || "",
    String(parts.answerText?.length ?? 0),
    String(parts.toolCount ?? 0),
    parts.clarification ? "1" : "0",
    parts.errorText ? "1" : "0",
  ].join("|");
}
