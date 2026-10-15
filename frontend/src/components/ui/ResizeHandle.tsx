import { useCallback, useEffect } from "react";

/** 面板宽度拖拽把手：像素 CSS 变量 + document 级 mousemove + min/max 钳制 + localStorage 持久化
 * （doc/DESKTOP_APP_PLAN.md §3.4：不用弹性比例，聊天/详情列有最佳阅读宽度）。
 * edge=left：把手在左缘，向左拖增宽（右侧功能面板）。edge=right：把手在右缘，向右拖增宽（左侧栏）。
 * 拖拽期间给 <html> 加 .resizing 关过渡动画。 */
export function ResizeHandle({ cssVar, storageKey, min, max, edge = "left" }: {
  cssVar: string;
  storageKey: string;
  min: number;
  max: number;
  edge?: "left" | "right";
}) {
  useEffect(() => {
    const saved = Number(localStorage.getItem(storageKey));
    if (saved >= min && saved <= max) {
      document.documentElement.style.setProperty(cssVar, `${saved}px`);
    }
  }, [cssVar, storageKey, min, max]);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = parseInt(
      getComputedStyle(document.documentElement).getPropertyValue(cssVar), 10,
    ) || min;
    document.documentElement.classList.add("resizing");

    const onMove = (ev: MouseEvent) => {
      const delta = edge === "right" ? ev.clientX - startX : startX - ev.clientX;
      const width = Math.min(max, Math.max(min, startWidth + delta));
      document.documentElement.style.setProperty(cssVar, `${width}px`);
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.documentElement.classList.remove("resizing");
      const final = parseInt(
        getComputedStyle(document.documentElement).getPropertyValue(cssVar), 10,
      );
      if (final) localStorage.setItem(storageKey, String(final));
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, [cssVar, storageKey, min, max, edge]);

  return (
    <div
      className={`resize-handle${edge === "right" ? " resize-handle-right" : ""}`}
      onMouseDown={onMouseDown}
    />
  );
}
