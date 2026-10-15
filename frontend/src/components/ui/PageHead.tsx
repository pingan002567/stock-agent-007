import type { ReactNode } from "react";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import { useAppState } from "@/hooks/useAppState";
import { isMobileLayout } from "@/lib/connection";

/** 功能页统一头部(设计规范 3.2):无框 KPI 行 + 右侧动作区。
 * 页名由 func-head 承担,页面内不再重复大标题/hero 横幅。
 * KPI 带 prompt 时可点击=带预填问题开聊(数字即入口)。 */

export interface KpiItem {
  label: string;
  value: ReactNode;
  /** up=绿(涨/正向) down=红(跌/告警) 缺省=墨色 */
  tone?: "up" | "down";
  /** 点击该指标时发给 AI 的预填问题 */
  prompt?: string;
}

export function PageHead({ kpis, actions }: { kpis: KpiItem[]; actions?: ReactNode }) {
  const { handleSend, sending } = useCopilotChat();
  const { setCurrentScreen } = useAppState();
  return (
    <div className="page-head">
      <div className="page-kpis">
        {kpis.map((k) => (
          <div
            key={k.label}
            className={`kpi-item${k.prompt ? " clickable" : ""}`}
            title={k.prompt}
            onClick={k.prompt && !sending ? () => {
              if (isMobileLayout()) setCurrentScreen("chat");
              void handleSend(k.prompt!);
            } : undefined}
          >
            <div className="k">{k.label}</div>
            <div className={`v num${k.tone ? ` ${k.tone}` : ""}`}>{k.value}</div>
          </div>
        ))}
      </div>
      {actions && <div className="page-head-actions">{actions}</div>}
    </div>
  );
}
