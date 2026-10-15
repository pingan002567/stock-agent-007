/** 头像色板（TeamClaw actor-color 模式）：10 色饱和而克制，
 * 按 id 哈希稳定取色——同一 actor 全应用同色；禁止灰色兜底。
 * 形状约定：AI = 圆角方块，人类 = 圆形（20px 下即可辨类型）。 */
const PALETTE = [
  "#e85a4a", // coral
  "#7a6cf5", // violet
  "#3a8f63", // green
  "#c98a3c", // amber
  "#3a6dbf", // blue
  "#a5527c", // plum
  "#1f8b94", // teal
  "#6a7a3a", // olive
  "#b56042", // terracotta
  "#5a6a7a", // slate
];

export function actorColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(h) % PALETTE.length];
}
