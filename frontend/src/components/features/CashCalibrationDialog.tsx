import { ModalPortal } from "@/components/ui/ModalPortal";
import { useState } from "react";
import { apiPost } from "@/api/client";

const CURRENCIES = ["CNY", "HKD", "USD", "USDT"] as const;

/** 多币种一键校准：把各币种现金设成券商实际值，保存后每个币种写一条 adjust 流水。 */
export function CashCalibrationDialog({
  current,
  onClose,
  onSaved,
}: {
  current?: Record<string, number>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const ccy of CURRENCIES) init[ccy] = current?.[ccy] != null ? String(current[ccy]) : "";
    return init;
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const amounts: Record<string, number> = {};
    for (const ccy of CURRENCIES) {
      const raw = (draft[ccy] ?? "").trim();
      if (raw === "") continue;
      const value = Number(raw.replace(/,/g, ""));
      if (!Number.isFinite(value) || value < 0) {
        setError(`${ccy} 需要是不小于 0 的数字`);
        setBusy(false);
        return;
      }
      amounts[ccy] = value;
    }
    if (Object.keys(amounts).length === 0) {
      setError("至少填一个币种");
      setBusy(false);
      return;
    }
    try {
      await apiPost("/api/holdings/cash-calibration", { amounts, note: "界面一键校准" });
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "校准失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalPortal>
    <div className="session-delete-modal" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="holding-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="holding-dialog-title">校准可用现金</div>
        <div className="holding-hint">
          对照券商 App 的实际可用资金填写。保存后每个币种都会写一条「校准」流水，可回溯。
          留空表示该币种不变。
        </div>
        <div className="holding-row">
          {CURRENCIES.map((ccy) => (
            <div className="holding-field" key={ccy}>
              <label>{ccy}</label>
              <input
                className="holding-input"
                inputMode="decimal"
                aria-label={`${ccy} 可用现金`}
                value={draft[ccy]}
                placeholder="不变"
                onChange={(e) => setDraft((prev) => ({ ...prev, [ccy]: e.target.value }))}
              />
            </div>
          ))}
        </div>
        {error ? <div className="holding-error">{error}</div> : null}
        <div className="holding-actions">
          <button type="button" className="session-delete-cancel" onClick={onClose} disabled={busy}>取消</button>
          <button type="button" className="session-delete-confirm" disabled={busy} onClick={() => void submit()}>
            {busy ? "保存中…" : "保存校准"}
          </button>
        </div>
      </div>
    </div>
    </ModalPortal>
  );
}
