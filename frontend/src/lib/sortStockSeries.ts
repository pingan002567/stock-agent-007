type Dated = { date?: string; day?: number };
type Published = { published_at?: string; updated_at?: string };
type Financial = { report_date?: string };

function parseTime(raw?: string): number {
  if (!raw) return 0;
  const t = Date.parse(raw.replace(" ", "T"));
  return Number.isNaN(t) ? 0 : t;
}

export function sortHistoryNewestFirst<T extends Dated>(items: T[]): T[] {
  return [...items].sort((a, b) => parseTime(b.date) - parseTime(a.date));
}

export function sortIntelNewestFirst<T extends Published>(items: T[]): T[] {
  return [...items].sort(
    (a, b) =>
      parseTime(b.published_at ?? b.updated_at) - parseTime(a.published_at ?? a.updated_at),
  );
}

export function sortFinancialNewestFirst<T extends Financial>(items: T[]): T[] {
  return [...items].sort((a, b) => parseTime(b.report_date) - parseTime(a.report_date));
}

/** 折线图从左到右应为时间递增 */
export function historyForChart<T extends Dated>(items: T[]): T[] {
  return [...items].reverse();
}
