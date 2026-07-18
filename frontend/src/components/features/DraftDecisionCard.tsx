import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/api/client";
import { StatusDot } from "@/components/ui/StatusDot";

/** 调仓草案决策卡(人在环审批):AI 只能提案——confirm 工具在 guardrail
 * denied 列表对模型封死,确认/驳回唯一路径是这里的按钮走 REST。
 * 挂载时拉取草案现状,历史消息里的卡片因此始终显示真实状态(而非
 * final payload 落库时的快照)。 */

interface DraftDetail {
  draft_id: string;
  symbol: string;
  name?: string;
  action?: string;
  current_weight_pct?: number;
  target_weight_pct?: number;
  delta_weight_pct?: number;
  status?: string;
  conclusion?: string;
  reasons?: string[];
  counter_reasons?: string[];
}

const STATUS_META: Record<string, { label: string; tone: "ok" | "bad" | "off" }> = {
  confirmed_no_execution: { label: "已确认 · 研究模式,不触发真实交易", tone: "ok" },
  rejected: { label: "已驳回", tone: "bad" },
  expired: { label: "已过期", tone: "off" },
};

const ACTION_LABEL: Record<string, string> = {
  INCREASE: "加仓", REDUCE: "减仓", OPEN: "建仓", CLOSE: "清仓", HOLD: "维持",
  increase: "加仓", reduce: "减仓", decrease: "减仓", open: "建仓", close: "清仓",
};

const pct = (v?: number) => (v == null ? "-" : `${v.toFixed(1)}%`);

export function DraftDecisionCard({ draftId }: { draftId: string }) {
  const [draft, setDraft] = useState<DraftDetail | null>(null);
  const [busy, setBusy] = useState<"confirm" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    apiGet<DraftDetail>(`/api/rebalance-drafts/${encodeURIComponent(draftId)}`)
      .then((d) => { if (alive) setDraft(d); })
      .catch(() => { /* 草案不存在(如已被清理)时不渲染卡片 */ });
    return () => { alive = false; };
  }, [draftId]);

  if (!draft) return null;
  const pending = draft.status === "pending_user_confirmation";
  const done = STATUS_META[draft.status ?? ""];

  const decide = async (action: "confirm" | "reject") => {
    setBusy(action);
    setError(null);
    try {
      const updated = await apiPost<DraftDetail>(
        `/api/rebalance-drafts/${encodeURIComponent(draftId)}/${action}`, { note: "" },
      );
      setDraft(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="decision-card">
      <div className="decision-card-head">
        <span className="decision-card-title">调仓草案</span>
        <span className="num decision-card-sym">{draft.symbol}</span>
        {draft.name && <span className="decision-card-name">{draft.name}</span>}
        {pending
          ? <span className="decision-card-badge">待确认</span>
          : done && <span style={{ marginLeft: "auto" }}><StatusDot tone={done.tone}>{done.label}</StatusDot></span>}
      </div>
      <div className="decision-card-fields">
        <div><span className="k">动作</span><span className="v">{ACTION_LABEL[draft.action ?? ""] ?? draft.action ?? "-"}</span></div>
        <div><span className="k">当前权重</span><span className="v num">{pct(draft.current_weight_pct)}</span></div>
        <div><span className="k">目标权重</span><span className="v num">{pct(draft.target_weight_pct)}</span></div>
        <div>
          <span className="k">变动</span>
          <span className={`v num ${(draft.delta_weight_pct ?? 0) >= 0 ? "up" : "down"}`}>
            {(draft.delta_weight_pct ?? 0) >= 0 ? "+" : ""}{pct(draft.delta_weight_pct)}
          </span>
        </div>
      </div>
      {draft.conclusion && <div className="decision-card-conclusion">{draft.conclusion}</div>}
      {pending && (
        <div className="decision-card-actions">
          <button type="button" className="decision-confirm" disabled={busy != null}
            onClick={() => void decide("confirm")}>
            {busy === "confirm" ? "确认中…" : "确认草案"}
          </button>
          <button type="button" className="decision-reject" disabled={busy != null}
            onClick={() => void decide("reject")}>
            {busy === "reject" ? "驳回中…" : "驳回"}
          </button>
          <span className="decision-card-hint">确认仅登记决策,不触发真实交易</span>
        </div>
      )}
      {error && <div className="decision-card-error">{error}</div>}
    </div>
  );
}
