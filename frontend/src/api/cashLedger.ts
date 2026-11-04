import { apiGet, apiUrl } from "@/api/client";
import { authHeaders } from "@/lib/connection";

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

/** 导出流水 CSV：用带鉴权头的 fetch 拿 blob 再触发下载（token 不进 URL）。 */
export async function downloadCashLedgerCsv(): Promise<void> {
  const res = await fetch(apiUrl("/api/holdings/cash-ledger.csv"), { headers: authHeaders() });
  if (!res.ok) throw new Error(`导出失败：HTTP ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "cash-ledger.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const CASH_REASON_LABEL: Record<string, string> = {
  buy: "买入",
  sell: "卖出",
  adjust: "校准",
  migrate: "迁移",
  fee: "费用",
  dividend: "分红",
};
