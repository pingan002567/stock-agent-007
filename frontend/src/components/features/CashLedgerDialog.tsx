import { ModalPortal } from "@/components/ui/ModalPortal";
import { useEffect, useState } from "react";
import { CASH_REASON_LABEL, fetchCashLedger, downloadCashLedgerCsv, type CashLedgerRow } from "@/api/cashLedger";

/** 资金流水：每笔买入/卖出/校准的变动与余额，用来对账。 */
export function CashLedgerDialog({ onClose }: { onClose: () => void }) {
  const [rows, setRows] = useState<CashLedgerRow[]>([]);
  const [cash, setCash] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const data = await fetchCashLedger(200);
        if (!alive) return;
        setRows(data.items ?? []);
        setCash(data.cash_by_currency ?? {});
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "加载失败");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  return (
    <ModalPortal>
    <div className="session-delete-modal" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="holding-dialog cash-ledger-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="holding-dialog-title">资金流水</div>
        <div className="cash-ledger-cash">
          {Object.keys(cash).length === 0 ? (
            <span className="muted">还没有记录现金</span>
          ) : (
            Object.entries(cash).map(([ccy, amount]) => (
              <span key={ccy} className="cash-chip">
                {ccy} <b className="num">{amount.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</b>
              </span>
            ))
          )}
        </div>
        {loading ? <div className="muted">加载中…</div> : null}
        {error ? <div className="holding-error">{error}</div> : null}
        {!loading && !error && rows.length === 0 ? (
          <div className="muted">还没有资金变动记录</div>
        ) : null}
        {rows.length > 0 ? (
          <div className="cash-ledger-scroll">
            <table className="data-table cash-ledger-table">
              <thead>
                <tr><th>时间</th><th>币种</th><th>变动</th><th>余额</th><th>类型</th><th>关联</th></tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.ledger_id}>
                    <td className="num">{row.created_at.slice(5, 16).replace("T", " ")}</td>
                    <td>{row.currency}</td>
                    <td className="num" style={{ color: row.delta < 0 ? "var(--loss)" : "var(--gain)" }}>
                      {row.delta > 0 ? "+" : ""}{row.delta.toFixed(2)}
                    </td>
                    <td className="num">{row.balance_after.toFixed(2)}</td>
                    <td>{CASH_REASON_LABEL[row.reason] ?? row.reason}</td>
                    <td className="muted">{row.ref_id || row.note || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <div className="holding-actions">
          <button
            type="button"
            className="session-delete-cancel"
            disabled={exporting || rows.length === 0}
            onClick={() => {
              setExporting(true);
              void downloadCashLedgerCsv()
                .catch((err) => setError(err instanceof Error ? err.message : "导出失败"))
                .finally(() => setExporting(false));
            }}
          >
            {exporting ? "导出中…" : "导出 CSV"}
          </button>
          <button type="button" className="session-delete-confirm" onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
    </ModalPortal>
  );
}
