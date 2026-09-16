import type { ReactNode } from "react";

export type ComposerDockKind = "clarify" | "offline" | "stuck" | "info";

type Dock = {
  kind: ComposerDockKind;
  title: string;
  detail?: string;
  actionLabel?: string;
  onAction?: () => void;
};

/** 输入区上方叠层：澄清等待 / 离线 / 卡住，贴近 TeamClu ComposerStack。 */
export function ComposerStack({
  docks,
  children,
}: {
  docks: Dock[];
  children: ReactNode;
}) {
  return (
    <div className="composer-stack">
      {docks.length > 0 && (
        <div className="composer-docks" aria-live="polite">
          {docks.map((dock) => (
            <div key={dock.kind} className={`composer-dock composer-dock-${dock.kind}`}>
              <div className="composer-dock-text">
                <strong>{dock.title}</strong>
                {dock.detail ? <span>{dock.detail}</span> : null}
              </div>
              {dock.actionLabel && dock.onAction ? (
                <button type="button" className="composer-dock-action" onClick={dock.onAction}>
                  {dock.actionLabel}
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
      {children}
    </div>
  );
}
