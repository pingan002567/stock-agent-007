/** 主窗口 ↔ 桌宠窗口的共享约定。
 *
 *  两个窗口同源（开发态是 localhost:5173，打包后是 tauri://localhost），
 *  所以用 localStorage + storage 事件同步状态，不需要额外的事件总线或插件。
 */

/** 桌宠的 5 个状态 */
export type PetState = "idle" | "working" | "done" | "alert" | "error";

/** 主窗口写、桌宠窗口读 */
export const PET_STATE_KEY = "pet.state";
/** 桌宠开关（"0" = 关） */
export const PET_ENABLED_KEY = "pet.enabled";
/** 桌宠右下角锚点（物理像素）—— 窗口大小随气泡变化，但锚点不变 */
export const PET_ANCHOR_KEY = "pet.pos.v3";

/** 只有这三个状态弹气泡；unread 只出角标（避免吵） */
export const BUBBLE_STATES: readonly PetState[] = ["alert", "done", "error"];

export type PetPayload = {
  state: PetState;
  title?: string;
  body?: string;
  /** 角标数字（高优待办数），0 = 不显示 */
  badge?: number;
  at: number;
};

/** 桌宠窗口两种尺寸：只有本体 / 带气泡 */
export const PET_SIZE = { base: { w: 132, h: 132 }, bubble: { w: 300, h: 236 } } as const;
