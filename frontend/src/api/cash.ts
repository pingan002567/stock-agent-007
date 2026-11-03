/** 现金与成交（P0：买入扣现金、不可透支）。 */
import { apiPost } from "@/api/client";

export interface TradeResult {
  replayed: boolean;
  ledger_id: string | null;
  balance_after: number | null;
  cash_delta: number;
  currency: string;
  quantity_after?: number;
  cost?: number | null;
  market_value?: number;
  amount: number;
  fee: number;
}

export interface TradeResponse {
  trade: TradeResult;
  currency: string;
  available_cash: number | null;
  summary: Record<string, unknown>;
}

export interface TradeRejection {
  code: "insufficient_cash" | "cash_not_recorded" | "insufficient_holding";
  message: string;
  currency?: string;
  required?: number;
  available?: number;
  shortfall?: number;
  symbol?: string;
  held?: number;
  requested?: number;
}

export function executeHoldingTrade(payload: {
  action: "buy" | "sell";
  symbol: string;
  quantity: number;
  fill_price: number;
  fee?: number;
  currency?: string;
  idempotency_key?: string;
  note?: string;
}): Promise<TradeResponse> {
  return apiPost<TradeResponse>("/api/holdings/trades", payload);
}

export function setAvailableCash(currency: string, amount: number | null) {
  return apiPost<{ available_cash: number | null; currency: string; summary: Record<string, unknown> }>(
    "/api/holdings/available-cash",
    { currency, amount },
  );
}

/** 从 409 响应里取出结构化拒绝原因（现金不足 / 未记录 / 持仓不足） */
export function parseTradeRejection(err: unknown): TradeRejection | null {
  // 鸭子类型而不是 instanceof：测试里 @/api/client 常被 mock，instanceof 会误判
  const detail = (err as { detail?: unknown })?.detail;
  if (typeof detail !== "string") return null;
  const idx = detail.indexOf("{");
  if (idx < 0) return null;
  try {
    const body = JSON.parse(detail.slice(idx)) as { detail?: TradeRejection };
    return body.detail?.code ? body.detail : null;
  } catch {
    return null;
  }
}

/** 拒绝原因 → 给用户看的一句话 */
export function tradeRejectionMessage(rej: TradeRejection): string {
  if (rej.code === "insufficient_cash") {
    const ccy = rej.currency ?? "";
    return `可用现金不足：需要 ${rej.required?.toFixed(2)} ${ccy}，可用 ${rej.available?.toFixed(2)} ${ccy}，还差 ${rej.shortfall?.toFixed(2)} ${ccy}`;
  }
  if (rej.code === "cash_not_recorded") {
    return `${rej.currency ?? ""} 现金还没记录 —— 先在持仓页填「可用资金」，否则无法记账`;
  }
  return rej.message || "成交被拒绝";
}
