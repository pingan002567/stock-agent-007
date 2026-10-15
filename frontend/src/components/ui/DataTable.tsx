interface Column<T> { key: keyof T | string; label: string; render?: (value: unknown, row: T) => string; className?: string; }
interface DataTableProps<T> { columns: Column<T>[]; data: T[]; keyField: keyof T; emptyText?: string; }

export function DataTable<T extends Record<string, unknown>>({ columns, data, keyField, emptyText = "暂无数据" }: DataTableProps<T>) {
  if (!data.length) return <div className="muted" style={{ textAlign: "center", padding: "16px 0" }}>{emptyText}</div>;
  return (
    <table>
      <thead><tr>{columns.map((col) => (<th key={String(col.key)} className={col.className || ""}>{col.label}</th>))}</tr></thead>
      <tbody>{data.map((row) => (
        <tr key={String(row[keyField])} className="row">
          {columns.map((col) => {
            const val = row[col.key as keyof T];
            return <td key={String(col.key)} className={col.className || ""}>{col.render ? col.render(val, row) : String(val ?? "")}</td>;
          })}
        </tr>
      ))}</tbody>
    </table>
  );
}
