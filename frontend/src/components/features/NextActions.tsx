interface SuggestedAction {
  label: string;
  icon: string;
  action_type: string;
  screen?: string;
  stock?: string;
  endpoint?: string;
  symbol?: string;
}

interface Props {
  actions: SuggestedAction[];
  onNavigate: (screen: string, stock: string | undefined) => void;
  onApi: (endpoint: string, symbol: string) => void;
}

export function NextActions({ actions, onNavigate, onApi }: Props) {
  if (!actions || actions.length === 0) return null;

  const handleClick = (a: SuggestedAction) => {
    if (a.action_type === "navigate") {
      onNavigate(a.screen || "overview", a.stock);
    } else if (a.action_type === "api") {
      onApi(a.endpoint || "", a.symbol || "");
    }
  };

  return (
    <div className="next-actions">
      {actions.map((a, i) => (
        <button
          key={`${a.label}-${i}`}
          className="action-chip"
          onClick={() => handleClick(a)}
          title={a.label}
        >
          <span className="action-icon">{a.icon}</span>
          <span className="action-label">{a.label}</span>
        </button>
      ))}
    </div>
  );
}
