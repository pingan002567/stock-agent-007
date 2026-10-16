// 涨跌配色。iOS 参考实现全端统一用「绿涨红跌」
// （WatchlistView.swift:41 / HoldingsView.swift:63 / StockDetailView.swift:78）。
// 如需改回 A 股习惯的「红涨绿跌」，只需交换下面两行常量。
export const UP_COLOR = '#34C759';
export const DOWN_COLOR = '#FF3B30';

export function trendColor(pct: number | undefined | null): string {
  return (pct ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR;
}

export const SEVERITY_COLORS: Record<string, string> = {
  high: '#FF3B30',
  medium: '#FF9500',
  low: '#34C759',
};

export function severityColor(s?: string): string {
  return SEVERITY_COLORS[String(s ?? '').toLowerCase()] ?? '#8E8E93';
}

export const ACCENT = '#007AFF';
