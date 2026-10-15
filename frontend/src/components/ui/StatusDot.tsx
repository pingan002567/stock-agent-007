import type { ReactNode } from "react";

/** 状态圆点原语(设计规范 3.3):统一告警/门禁/任务状态的表达。
 * ok=绿(正常/通过) bad=红(告警/未通过) busy=琥珀(进行中) off=灰(暂停/停用) */
export function StatusDot({ tone, children }: { tone: "ok" | "bad" | "busy" | "off"; children?: ReactNode }) {
  return (
    <span className={`status-dot ${tone}`}>
      <i />
      {children}
    </span>
  );
}
