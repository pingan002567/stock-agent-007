import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage, TableSkeleton, PanelSkeleton } from "@/components/ui/Loading";
import { RefreshButton } from "@/components/ui/RefreshButton";
import { Pagination } from "@/components/ui/Pagination";
import { formatTimeAgo } from "@/utils/format";
import { useAppState } from "@/hooks/useAppState";

interface TaskItem { task_id: string; title: string; status?: string; source?: string; progress?: number; current_step?: string; created_at?: string }
interface TaskStep { step_id?: string; name?: string; status?: string; skill?: string; tool?: string; duration_ms?: number }
interface ToolExecution { execution_id?: string; tool_name?: string; status?: string; domain?: string; arguments?: Record<string, unknown> }

export default function Tasks() {
  const { appDataCache, globalLoading } = useAppState();
  const [items, setItems] = useState<TaskItem[]>([]);
  const [selectedTask, setSelectedTask] = useState<TaskItem | null>(null);
  const [steps, setSteps] = useState<TaskStep[]>([]);
  const [ledger, setLedger] = useState<ToolExecution[]>([]);
  const [taskStream, setTaskStream] = useState<string>("等待选择任务。");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [taskPage, setTaskPage] = useState(1);
  const [taskTotal, setTaskTotal] = useState(0);
  const taskPageSize = 8;

  const loadAll = useCallback(async (page: number = taskPage) => {
    setLoading(true); setError(null);
    try {
      const response = await apiGet<{ items: TaskItem[]; total: number }>(`/api/tasks?page=${page}&page_size=${taskPageSize}`);
      setItems(response.items); setTaskTotal(response.total);
    }
    catch (err) { setError(err instanceof Error ? err.message : "加载任务失败"); } finally { setLoading(false); }
  }, [taskPage, taskPageSize]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  const handleSelect = async (task: TaskItem) => {
    setSelectedTask(task); setTaskStream("加载中…");
    try {
      const [detail, stream] = await Promise.all([
        apiGet<{ tool_executions?: ToolExecution[]; steps?: TaskStep[] }>(`/api/tasks/${encodeURIComponent(task.task_id)}`).catch(() => ({ tool_executions: [], steps: [] })),
        apiGet<Record<string, unknown>>(`/api/tasks/${encodeURIComponent(task.task_id)}/stream`).then((r) => JSON.stringify(r, null, 2)).catch(() => "等待任务详情。"),
      ]);
      setSteps(detail.steps ?? []); setLedger(detail.tool_executions ?? []); setTaskStream(stream);
    } catch { /* ignore */ }
  };

  const runningCount = items.filter(t => t.status === "running").length;
  const completedCount = items.filter(t => t.status === "completed").length;
  const failedCount = items.filter(t => t.status === "failed").length;

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        <div className="market-hero">
          <div className="market-hero-header">
            <div className="market-title">
              <h1>Agent 任务中心</h1>
              <p>监控 AI Agent 执行状态，追踪任务进度和工具调用。</p>
            </div>
            <div className="hero-actions">
              <RefreshButton refreshing={loading} onClick={() => void loadAll()} />
            </div>
          </div>
          <div className="market-stats">
            <div className="market-stat">
              <span className="market-stat-label">总任务</span>
              <span className="market-stat-value">{items.length}</span>
              <span className="market-stat-change neutral">全部任务</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">运行中</span>
              <span className="market-stat-value" style={{ color: "var(--blue)" }}>{runningCount}</span>
              <span className="market-stat-change" style={{ color: "var(--blue)" }}>⏳ 进行中</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">已完成</span>
              <span className="market-stat-value up">{completedCount}</span>
              <span className="market-stat-change up">
                ↑ {items.length > 0 ? Math.round((completedCount / items.length) * 100) : 0}% 完成率
              </span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">失败</span>
              <span className="market-stat-value down">{failedCount}</span>
              <span className="market-stat-change down">{failedCount > 0 ? "↓ 需要处理" : "● 无失败"}</span>
            </div>
          </div>
        </div>

        <div className="kpi-grid">
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">总任务</span>
              <div className="kpi-icon blue">📋</div>
            </div>
            <div className="kpi-value">{items.length}</div>
            <div className="kpi-change neutral">全部任务</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">运行中</span>
              <div className="kpi-icon" style={{ background: "var(--blue-soft)", color: "var(--blue)" }}>⏳</div>
            </div>
            <div className="kpi-value" style={{ color: "var(--blue)" }}>{runningCount}</div>
            <div className="kpi-change" style={{ color: "var(--blue)" }}>进行中</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">已完成</span>
              <div className="kpi-icon green">✅</div>
            </div>
            <div className="kpi-value" style={{ color: "var(--green)" }}>{completedCount}</div>
            <div className="kpi-change up">{items.length > 0 ? Math.round((completedCount / items.length) * 100) : 0}% 完成率</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">失败</span>
              <div className="kpi-icon red">❌</div>
            </div>
            <div className="kpi-value" style={{ color: failedCount > 0 ? "var(--red)" : undefined }}>{failedCount}</div>
            <div className={`kpi-change ${failedCount > 0 ? "down" : "neutral"}`}>{failedCount > 0 ? "需要处理" : "无失败"}</div>
          </div>
        </div>

        <div className="two-col">
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14,2 14,8 20,8"/>
                </svg>
                任务队列
                <span className="panel-badge">{taskTotal} 条</span>
              </div>
            </div>
            <div className="panel-body">
              {items.length === 0 ? (
                <div className="muted">暂无任务</div>
              ) : items.map((t) => (
                <div
                  key={t.task_id}
                  className="intel-item"
                  style={selectedTask?.task_id === t.task_id ? { background: "var(--hover-row)", borderLeft: "3px solid var(--blue)" } : {}}
                  onClick={() => void handleSelect(t)}
                >
                  <div className={`intel-dot ${t.status === "running" ? "info" : t.status === "completed" ? "success" : t.status === "failed" ? "warning" : "info"}`} />
                  <div className="intel-content">
                    <div className="intel-title">{t.title}</div>
                    <div className="intel-desc">
                      来源: {t.source ?? "-"} · 进度: {t.current_step ?? `${t.progress ?? 0}%`} · {formatTimeAgo(t.created_at)}
                    </div>
                  </div>
                  <div className="intel-time" style={{ color: t.status === "running" ? "var(--blue)" : t.status === "completed" ? "var(--green)" : t.status === "failed" ? "var(--red)" : "var(--muted)" }}>
                    {t.status ?? "unknown"}
                  </div>
                </div>
              ))}
            </div>
            <Pagination
              total={taskTotal}
              pageSize={taskPageSize}
              current={taskPage}
              onChange={(page) => { setTaskPage(page); void loadAll(page); }}
            />
          </div>

          <div>
            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/>
                  </svg>
                  Skill Trace
                  <span className="panel-badge">{steps.length} 步</span>
                </div>
              </div>
              <div className="panel-body">
                {steps.length === 0 ? (
                  <div className="muted">选择任务查看详情</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {steps.map((s, i) => (
                      <div key={s.step_id ?? i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: 10, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ fontSize: 11, color: "var(--muted)", width: 20 }}>{i + 1}</span>
                          <span style={{ fontSize: 13, fontWeight: 600 }}>{s.name ?? s.skill ?? s.tool}</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          {s.duration_ms != null && <span style={{ fontSize: 11, color: "var(--muted)" }}>{s.duration_ms}ms</span>}
                          <span className={`tag ${s.status === "completed" ? "green" : s.status === "running" ? "" : ""}`} style={{ fontSize: 10 }}>
                            {s.status === "completed" ? "✅ 完成" : s.status === "running" ? "⏳ 进行中" : "⏸ 等待"}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                  </svg>
                  工具调用记录
                  <span className="panel-badge">{ledger.length} 次</span>
                </div>
              </div>
              <div className="panel-body">
                {ledger.length === 0 ? (
                  <div className="muted">等待任务详情</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {ledger.map((ex, i) => (
                      <div key={ex.execution_id ?? i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: 8, background: "var(--bg-tertiary)", borderRadius: 6, fontSize: 12 }}>
                        <span style={{ fontFamily: "var(--mono)" }}>{ex.tool_name}</span>
                        <span className={`tag ${ex.status === "succeeded" ? "green" : ex.status === "failed" ? "red" : ""}`} style={{ fontSize: 10 }}>
                          {ex.status === "succeeded" ? "✅" : ex.status === "failed" ? "❌" : "⏳"}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polygon points="13,2 3,14 12,14 11,22 21,10 12,10"/>
                  </svg>
                  任务事件
                </div>
              </div>
              <div className="panel-body">
                <pre style={{ maxHeight: 400, overflow: "auto", fontSize: 11, background: "var(--bg-tertiary)", padding: 12, borderRadius: 8 }}>{taskStream}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}
