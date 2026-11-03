import { useState } from "react";
import { executeHoldingTrade, parseTradeRejection, tradeRejectionMessage } from "@/api/cash";
import { currencyMoney, currencySign } from "@/utils/market";

/** 卖出一笔持仓：回补现金（扣手续费），超过持有会被后端拒绝。 */
export function SellHoldingDialog({
  symbol,
  name,
  currency,
  held,
  onClose,
  onSold,
}: {
  symbol: string;
  name?: string;
  currency: string;
  held: number;
  onClose: () => void;
  onSold: (summary: Record<string, unknown>) => void;
}) {
  const [quantity, setQuantity] = useState(String(held));
  const [price, setPrice] = useState("");
  const [fee, setFee] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const qty = Number(quantity);
  const unit = Number(price);
  const canSubmit = qty > 0 && qty <= held && unit > 0 && !busy;
  const proceeds = qty > 0 && unit > 0 ? unit * qty - (Number(fee) || 0) : null;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await executeHoldingTrade({
        action: "sell",
        symbol,
        quantity: qty,
        fill_price: unit,
        fee: fee === "" ? 0 : Number(fee),
        currency,
      });
      onSold(result.summary);
      onClose();
    } catch (err) {
      const rej = parseTradeRejection(err);
      setError(rej ? tradeRejectionMessage(rej) : err instanceof Error ? err.message : "卖出失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="session-delete-modal" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="holding-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="holding-dialog-title">卖出 {name ?? symbol}</div>
        <div className="holding-hint">
          持有 <b className="num">{held}</b> · 卖出会按成交价回补 {currency} 现金（扣手续费）
        </div>
        <div className="holding-row">
          <div className="holding-field">
            <label>数量</label>
            <input
              className="holding-input"
              inputMode="decimal"
              value={quantity}
              autoFocus
              onChange={(e) => setQuantity(e.target.value)}
            />
          </div>
          <div className="holding-field">
            <label>成交价（{currencySign(currency)}）</label>
            <input
              className="holding-input"
              inputMode="decimal"
              value={price}
              placeholder="按真实成交价填"
              onChange={(e) => setPrice(e.target.value)}
            />
          </div>
          <div className="holding-field">
            <label>手续费（可空）</label>
            <input
              className="holding-input"
              inputMode="decimal"
              value={fee}
              placeholder="0"
              onChange={(e) => setFee(e.target.value)}
            />
          </div>
        </div>
        {proceeds != null ? (
          <div className="holding-preview">
            预计回补 <span className="num">{currencyMoney(proceeds, currency)}</span>（含手续费）
          </div>
        ) : null}
        {error ? <div className="holding-error">{error}</div> : null}
        <div className="holding-actions">
          <button type="button" className="session-delete-cancel" onClick={onClose} disabled={busy}>取消</button>
          <button type="button" className="session-delete-confirm" disabled={!canSubmit} onClick={() => void submit()}>
            {busy ? "卖出中…" : "确认卖出"}
          </button>
        </div>
      </div>
    </div>
  );
}
