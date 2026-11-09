import { createPortal } from "react-dom";

/** 把浮层挂到 body 下。
 *
 *  为什么必须 portal：`position: fixed` 的包含块会被**任何**带 transform/filter/
 *  perspective 的祖先劫持。页面入场动画 `.content > * { animation: fade-in }` 用的
 *  是 `transform: translateY(...)` + `fill-mode: both`，动画结束后 transform 仍然是
 *  `translateY(0)`（不是 none），于是弹窗会被限制在页面容器里——遮罩只盖住右侧面板、
 *  对话框在面板里居中，看起来像"弹窗错位"。
 */
export function ModalPortal({ children }: { children: React.ReactNode }) {
  if (typeof document === "undefined") return null;
  return createPortal(children, document.body);
}
