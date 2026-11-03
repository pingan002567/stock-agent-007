import { apiGet } from "@/api/client";

export interface CashLedgerRow {
  ledger_id: string;
  currency: string;
  delta: number;
  balance_after: number;
  reason: string;
  ref_type?: string | null;
  ref_id?: string | null;
  note?: string | null;
  created_at: string;
}

export interface CashLedgerResponse {
  items: CashLedgerRow[];
  cash_by_currency: Record<string, number>;
}

export function fetchCashLedger(limit = 100): Promise<CashLedgerResponse> {
  return apiGet<CashLedgerResponse>(`/api/holdings/cash-ledger?limit=${limit}`);
}

export const CASH_REASON_LABEL: Record<string, string> = {
  buy: "买入",
  sell: "卖出",
  adjust: "校准",
  migrate: "迁移",
  fee: "费用",
  dividend: "分红",
};
