/** 页内确认，替代 window.confirm。样式沿用会话删除弹层。 */
export function ConfirmDialog({
  title,
  description,
  confirmLabel = "确认",
  busy = false,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: string;
  confirmLabel?: string;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="session-delete-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="session-delete-content">
        <div className="session-delete-title" id="confirm-title" style={{ marginTop: 20 }}>{title}</div>
        <div className="session-delete-desc">{description}</div>
        <div className="session-delete-actions">
          <button type="button" className="session-delete-cancel" disabled={busy} onClick={onCancel}>取消</button>
          <button type="button" className="session-delete-confirm" disabled={busy} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
