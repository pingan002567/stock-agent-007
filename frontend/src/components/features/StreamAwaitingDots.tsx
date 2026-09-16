/** 流式短空档三点动画（与 stuck dock 区分）。 */
export function StreamAwaitingDots({ label = "继续生成中" }: { label?: string }) {
  return (
    <div
      className="stream-awaiting"
      role="status"
      aria-label={label}
      data-testid="stream-awaiting"
    >
      <span className="stream-awaiting-label">{label}</span>
      <span className="stream-awaiting-dots" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="stream-awaiting-dot"
            style={{ animationDelay: `${i * 160}ms` }}
          />
        ))}
      </span>
    </div>
  );
}
