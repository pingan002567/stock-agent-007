import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiUrl } from "@/api/client";
import { PageContainer } from "@/components/layout/PageContainer";
import { ErrorMessage } from "@/components/ui/Loading";
import { PageHead } from "@/components/ui/PageHead";
import { Pagination } from "@/components/ui/Pagination";
import { formatTimeAgo } from "@/utils/format";
import { useAppState } from "@/hooks/useAppState";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { MarkdownRenderer } from "@/components/features/MarkdownRenderer";

interface ReportItem { report_id: string; title?: string; report_type?: string; status?: string; quality_score?: number; created_at?: string; source_label?: string }
interface ReportTemplate { template_id: string; name: string; report_type: string; source_types?: string[] }
interface ReportQuality { score?: number; checks?: Array<{ check?: string; passed?: boolean; detail?: string }> }

export default function Reports() {
  const { stock } = useAppState();
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [selectedReport, setSelectedReport] = useState<ReportItem | null>(null);
  const [quality, setQuality] = useState<ReportQuality | null>(null);
  const [reportPreview, setReportPreview] = useState<string | null>(null);
  const [, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [paperReportBusy, setPaperReportBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportPage, setReportPage] = useState(1);
  const [reportTotal, setReportTotal] = useState(0);
  const reportPageSize = 6;

  const loadAll = useCallback(async (page: number = reportPage) => {
    setLoading(true); setError(null);
    try {
      const [rdResp, td] = await Promise.all([
        apiGet<{ items: ReportItem[]; total: number }>(`/api/reports?page=${page}&page_size=${reportPageSize}`),
        apiGet<{ items: ReportTemplate[] }>("/api/report-templates"),
      ]);
      setReports(rdResp.items); setReportTotal(rdResp.total); setTemplates(td.items);
    } catch (err) { setError(err instanceof Error ? err.message : "加载报告失败"); } finally { setLoading(false); }
  }, [reportPage, reportPageSize]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  const handleSelectReport = async (r: ReportItem) => {
    setSelectedReport(r);
    setReportPreview(null);
    try {
      const [ql, full] = await Promise.all([
        apiGet<ReportQuality>(`/api/reports/${r.report_id}/quality`).catch(() => null),
        apiGet<{ content?: string }>(`/api/reports/${r.report_id}`).catch(() => null),
      ]);
      setQuality(ql);
      setReportPreview(full?.content ?? "（该报告没有正文内容）");
    } catch { /* ignore */ }
  };

  const handleGenerateStock = async () => {
    setGenerating(true); setError(null);
    try {
      const template = templates.find((t) => t.report_type === "stock_research") ?? templates[0];
      await apiPost("/api/reports/generate", {
        report_type: template?.report_type ?? "stock_research",
        source_type: template?.source_types?.[0] ?? "stock",
        source_id: stock, template_id: template?.template_id, title: `${stock} 研究报告`,
      });
      await loadAll();
    } catch (err) { setError(err instanceof Error ? err.message : "生成报告失败"); } finally { setGenerating(false); }
  };

  const handleGeneratePaperReport = async () => {
    setPaperReportBusy(true);
    try {
      await apiPost("/api/reports/generate", { report_type: "paper_portfolio_review", source_type: "paper_portfolio", source_id: "latest_snapshot", title: "Paper Portfolio 复盘报告" });
      await loadAll();
    } catch { /* ignore */ } finally { setPaperReportBusy(false); }
  };

  const handleRerunQuality = async () => {
    if (!selectedReport) return;
    try {
      await apiPost(`/api/reports/${selectedReport.report_id}/rerun-quality`, {});
      const ql = await apiGet<ReportQuality>(`/api/reports/${selectedReport.report_id}/quality`);
      setQuality(ql);
    } catch { /* ignore */ }
  };

  const scoredReports = reports.filter(r => r.quality_score != null);
  const avgQuality = scoredReports.length > 0 ? scoredReports.reduce((sum, r) => sum + (r.quality_score ?? 0), 0) / scoredReports.length : 0;
  const thisMonthReports = reports.filter(r => r.created_at && r.created_at.startsWith(new Date().toISOString().slice(0, 7))).length;

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        {error && <ErrorMessage message={error} />}
        <PageHead
          kpis={[
            { label: "报告", value: `${reports.length} 篇` },
            { label: "平均质量", value: `${avgQuality.toFixed(1)} 分` },
            { label: "本月", value: thisMonthReports },
            { label: "模板", value: templates.length },
          ]}
          actions={<>
            <button className="small primary" disabled={generating} onClick={() => void handleGenerateStock()} type="button">
              {generating ? "生成中…" : "股票报告"}
            </button>
            <button className="small" disabled={paperReportBusy} onClick={() => void handleGeneratePaperReport()} type="button">
              {paperReportBusy ? "生成中…" : "复盘报告"}
            </button>
            <AskAiButton prompt="生成一份最新的组合复盘报告" />
          </>}
        />

        <div className="two-col">
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14,2 14,8 20,8"/>
                </svg>
                历史报告
                <span className="panel-badge">{reportTotal} 份</span>
              </div>
            </div>
            <div className="panel-body">
              {reports.length === 0 ? (
                <div className="muted">暂无报告</div>
              ) : reports.map((r) => (
                <div
                  key={r.report_id}
                  className="intel-item"
                  style={selectedReport?.report_id === r.report_id ? { background: "var(--hover-row)", borderLeft: "3px solid var(--blue)" } : {}}
                  onClick={() => void handleSelectReport(r)}
                >
                  <div className={`intel-dot ${(r.quality_score ?? 0) >= 8 ? "success" : (r.quality_score ?? 0) >= 6 ? "warning" : "info"}`} />
                  <div className="intel-content">
                    <div className="intel-title">{r.title ?? r.report_id.slice(0, 8)}</div>
                    <div className="intel-desc">
                      {r.report_type} · {formatTimeAgo(r.created_at)}
                    </div>
                  </div>
                  <div className="intel-time" style={{ color: (r.quality_score ?? 0) >= 8 ? "var(--green)" : (r.quality_score ?? 0) >= 6 ? "var(--amber)" : "var(--muted)" }}>
                    {r.quality_score != null ? `${r.quality_score}/10` : "-"}
                  </div>
                </div>
              ))}
            </div>
            <Pagination
              total={reportTotal}
              pageSize={reportPageSize}
              current={reportPage}
              onChange={(page) => { setReportPage(page); void loadAll(page); }}
            />
          </div>

          <div>
            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                    <polyline points="22,4 12,14.01 9,11.01"/>
                  </svg>
                  质量检查
                  {quality && <span className="panel-badge">{quality.score ?? "-"}/10</span>}
                </div>
                <button className="small" onClick={() => void handleRerunQuality()} type="button">重跑检查</button>
              </div>
              <div className="panel-body">
                {quality ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {(quality.checks ?? []).map((c, i) => (
                      <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: 10, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ color: c.passed ? "var(--green)" : "var(--red)" }}>{c.passed ? "✓" : "✗"}</span>
                          <span style={{ fontSize: 13 }}>{c.check}</span>
                        </div>
                        <span className={`tag ${c.passed ? "green" : "red"}`} style={{ fontSize: 10 }}>{c.passed ? "通过" : "未通过"}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="muted">点击报告查看质量检查</div>
                )}
              </div>
            </div>

            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14,2 14,8 20,8"/>
                  </svg>
                  报告预览
                </div>
              </div>
              <div className="panel-body">
                {reportPreview ? (
                  <div style={{ padding: 16, background: "var(--bg-tertiary)", borderRadius: 8, fontSize: 13, lineHeight: 1.7, maxHeight: 360, overflow: "auto" }}>
                    <MarkdownRenderer text={reportPreview} />
                  </div>
                ) : (
                  <div className="muted">选择报告查看预览</div>
                )}
              </div>
            </div>

            {selectedReport && (
              <div className="panel">
                <div className="panel-header">
                  <div className="panel-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                      <polyline points="7,10 12,15 17,10"/>
                      <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                    导出
                  </div>
                </div>
                <div className="panel-body">
                  <div style={{ display: "flex", gap: 12 }}>
                    <a className="btn" style={{ flex: 1, textAlign: "center" }} href={apiUrl(`/api/reports/${selectedReport.report_id}/export?format=markdown`)} download>
                      导出 Markdown
                    </a>
                    <a className="btn" style={{ flex: 1, textAlign: "center" }} href={apiUrl(`/api/reports/${selectedReport.report_id}/export?format=pdf`)} download>
                      导出 PDF
                    </a>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </PageContainer>
  );
}
