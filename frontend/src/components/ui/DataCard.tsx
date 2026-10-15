interface DataCardProps { title: string; value: string; detail?: string; className?: string; }

export function DataCard({ title, value, detail, className }: DataCardProps) {
  return (
    <div className={`card ${className || ""}`}>
      <h3>{title}</h3>
      <p><strong className="num">{value}</strong>{detail && <><br /><span className="muted">{detail}</span></>}</p>
    </div>
  );
}
