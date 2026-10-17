import type { ReactNode } from "react";

/**
 * KPI 卡片图标。
 *
 * 之前这些卡片直接用 emoji（📊 ✅ 🔄 ⚡ 📋 ⏳ ❌）当图标，问题：
 * - emoji 会被渲染成彩色方块/彩色字形，跟界面其余部分的线性图标（侧边栏、
 *   按钮）风格不一致；
 * - 不同平台的 emoji 字形差异很大（macOS / Windows / Linux 各画一套）；
 * - emoji 自带颜色，`.kpi-icon` 的颜色变量完全不起作用（截图中蓝/绿/琥珀
 *   底上出现的都是 emoji 自己的颜色）。
 *
 * 这里改成与 nav.tsx 一致的内联 SVG：24 viewBox、stroke=currentColor、
 * 无填充，颜色完全由外层 `.kpi-icon.blue|green|amber|red|violet` 决定。
 */
const PATHS: Record<string, ReactNode> = {
  /* 策略：层叠（策略栈） */
  layers: (
    <>
      <path d="M12 2 2 7l10 5 10-5-10-5z" />
      <path d="m2 17 10 5 10-5" />
      <path d="m2 12 10 5 10-5" />
    </>
  ),
  /* 已完成 / 启用 */
  checkCircle: (
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  /* 回测：循环刷新 */
  refresh: (
    <>
      <path d="M21 12a9 9 0 1 1-3-6.7" />
      <path d="M21 3v6h-6" />
    </>
  ),
  /* 风险：闪电 */
  zap: <path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" />,
  /* 任务：清单 */
  clipboard: (
    <>
      <rect x="8" y="2" width="8" height="4" rx="1" />
      <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
      <path d="M9 12h6M9 16h6" />
    </>
  ),
  /* 运行中：时钟 */
  clock: (
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v6l4 2" />
    </>
  ),
  /* 失败：叉圈 */
  xCircle: (
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="m15 9-6 6M9 9l6 6" />
    </>
  ),
};

export function KpiIcon({ name, size = 18 }: { name: keyof typeof PATHS; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  );
}
