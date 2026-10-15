import { useState } from "react";

/** 工具结果详情视图（由 FunctionDock 宿主渲染）。
 * JSON 结果结构化：对象→KV 树、对象数组→表格；非 JSON 全文展示。 */

/** 值 → 展示节点：对象/数组递归结构化，原始值直出。深层直接 JSON 兜底避免无限嵌套。 */
function renderValue(value: unknown, depth: number): React.ReactNode {
  if (value === null || value === undefined) return <span className="detail-null">—</span>;
  if (typeof value === "number") return <span className="detail-num">{value}</span>;
  if (typeof value === "boolean") return <span className="detail-num">{String(value)}</span>;
  if (typeof value === "string") return <span>{value}</span>;
  if (depth >= 3) return <pre className="detail-pre">{JSON.stringify(value, null, 2)}</pre>;

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="detail-null">[]</span>;
    // 对象数组 → 表格（列取首行键集合）
    if (typeof value[0] === "object" && value[0] !== null && !Array.isArray(value[0])) {
      const cols = Object.keys(value[0] as Record<string, unknown>).slice(0, 6);
      return (
        <div className="detail-table-wrap">
          <table className="detail-table">
            <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {(value as Record<string, unknown>[]).slice(0, 50).map((row, i) => (
                <tr key={i}>
                  {cols.map((c) => (
                    <td key={c}>
                      {typeof row[c] === "object" && row[c] !== null
                        ? JSON.stringify(row[c])
                        : String(row[c] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {value.length > 50 && <div className="detail-truncated">… 共 {value.length} 行，仅展示前 50 行</div>}
        </div>
      );
    }
    return (
      <ul className="detail-list">
        {value.slice(0, 50).map((v, i) => <li key={i}>{renderValue(v, depth + 1)}</li>)}
      </ul>
    );
  }

  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return <span className="detail-null">{"{}"}</span>;
  return (
    <div className="detail-kv">
      {entries.map(([k, v]) => (
        <div className="detail-kv-row" key={k}>
          <div className="detail-kv-key">{k}</div>
          <div className="detail-kv-val">{renderValue(v, depth + 1)}</div>
        </div>
      ))}
    </div>
  );
}

export function DetailBody({ resultText }: { resultText?: string }) {
  const [showRaw, setShowRaw] = useState(false);
  if (!resultText) return <div className="detail-empty">该工具没有返回内容</div>;

  let parsed: unknown = null;
  try {
    parsed = JSON.parse(resultText);
  } catch { /* 非 JSON 结果直接全文展示 */ }

  if (parsed === null || typeof parsed !== "object") {
    return <pre className="detail-pre">{resultText}</pre>;
  }
  return (
    <>
      {showRaw ? <pre className="detail-pre">{resultText}</pre> : renderValue(parsed, 0)}
      <button className="detail-raw-toggle" onClick={() => setShowRaw((v) => !v)}>
        {showRaw ? "结构化视图" : "查看原始 JSON"}
      </button>
    </>
  );
}
