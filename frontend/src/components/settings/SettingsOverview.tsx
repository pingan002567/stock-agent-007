import { useEffect, useMemo, useState } from "react";
import { apiGet } from "@/api/client";
import { collectIssues, type OverviewSettings, type OverviewTab } from "@/lib/settingsOverview";

/** 配置概览：只回答两个问题 —— 「还差什么才能用」和「现在到底生效的是什么」。
 *
 *  刻意不在这里提供任何可编辑项：能改的都去对应分区，避免同一份配置两个入口。
 */

export function SettingsOverview({
  settings,
  onNavigate,
}: {
  settings: OverviewSettings;
  onNavigate: (tab: OverviewTab) => void;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [tasksLoaded, setTasksLoaded] = useState(false);
  useEffect(() => {
    let alive = true;
    apiGet<{ items?: Task[] }>("/api/tasks")
      .then((res) => { if (alive) { setTasks(res?.items ?? []); setTasksLoaded(true); } })
      .catch(() => { if (alive) setTasksLoaded(false); });
    return () => { alive = false; };
  }, []);

  const issues = useMemo(() => collectIssues(settings, tasks, tasksLoaded), [settings, tasks, tasksLoaded]);
  const blockers = issues.filter((i) => i.level !== "info").length;

  const runtime = settings.agent_runtime;
  const modelName = String(settings.runtime_config?.model_name || runtime?.model_name || "未配置");
  const thinking = settings.runtime_config?.thinking_enabled !== false;
  const providerTotal = Object.keys(settings.data_sources?.provider_states ?? {}).length;
  const providerOn = Object.values(settings.data_sources?.provider_states ?? {})
    .filter((v) => v?.enabled).length;
  const enabledTasks = tasks.filter((t) => t.enabled !== false).length;
  const skillsOn = (settings.skills ?? []).filter((s) => s.enabled).length;
  const rules = settings.risk_policy?.active?.rules ?? {};
  const realOrder = settings.trading_controls?.real_order;

  const dot = (ok: boolean, warn = false) => (ok ? "d-ok" : warn ? "d-warn" : "d-bad");

  return (
    <div className="ov">
      <div className="ov-hero">
        <div>
          <div className="ov-hero-title">
            {blockers === 0 ? "可正常使用" : `还有 ${blockers} 项待确认`}
          </div>
          <p className="ov-hero-desc">
            {blockers === 0
              ? "必配项都已就绪。下面是当前真正生效的值，改动请去对应分区。"
              : "下面只列会阻塞使用或影响结论的项，按顺序处理即可。"}
          </p>
        </div>
        <span className={`ov-pill ${blockers === 0 ? "ok" : "warn"}`}>
          {blockers === 0 ? "就绪" : "待处理"}
        </span>
      </div>

      {issues.length > 0 && (
        <section className="ov-card">
          <header className="ov-card-head">
            <span className="ov-card-title">待你确认</span>
            <span className="ov-card-hint">只列会阻塞使用或影响结论的</span>
          </header>
          <div className="ov-tasks">
            {issues.map((issue) => (
              <div className="ov-task" key={issue.title}>
                <div className="ov-task-main">
                  <div className="ov-task-title">
                    <span className={`tag ${issue.level === "block" ? "red" : issue.level === "warn" ? "amber" : ""}`}>
                      {issue.level === "block" ? "阻塞" : issue.level === "warn" ? "待确认" : "建议"}
                    </span>
                    {issue.title}
                  </div>
                  <div className="ov-task-detail">{issue.detail}</div>
                </div>
                <button className="ghost ov-task-go" type="button" onClick={() => onNavigate(issue.tab)}>
                  {issue.action} →
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="ov-card">
        <header className="ov-card-head">
          <span className="ov-card-title">当前生效</span>
          <span className="ov-card-hint">只读 · 改动请去对应分区</span>
        </header>
        <div className="ov-fields">
          <div className="ov-field">
            <div>
              <div className="ov-field-label">对话模型</div>
              <div className="ov-field-sub">{thinking ? "思考模式已开启（工具调用前会展示推理）" : "思考模式已关闭"}</div>
            </div>
            <div className="ov-field-value strong">{modelName}</div>
          </div>
          <div className="ov-field">
            <div>
              <div className="ov-field-label">风控档位</div>
              <div className="ov-field-sub">
                单票 {String(rules.single_position_max_weight_pct ?? "—")}% · 行业 {String(rules.sector_max_weight_pct ?? "—")}%
              </div>
            </div>
            <div className="ov-field-value">{settings.risk_policy?.active?.name ?? "默认档"}</div>
          </div>
          <div className="ov-field">
            <div>
              <div className="ov-field-label">投资画像</div>
              <div className="ov-field-sub">影响建议的激进程度与仓位口径</div>
            </div>
            <div className="ov-field-value">
              {RISK_LEVEL_LABEL[settings.investor_profile?.risk_level ?? ""] ?? settings.investor_profile?.risk_level ?? "未设置"}
            </div>
          </div>
          <div className="ov-field">
            <div>
              <div className="ov-field-label">定时任务</div>
              <div className="ov-field-sub">盘前简报 / 盘中报告 / 收盘体检等</div>
            </div>
            <div className="ov-field-value">{tasksLoaded ? `${enabledTasks} 个启用` : "—"}</div>
          </div>
        </div>
      </section>

      <section className="ov-card">
        <header className="ov-card-head">
          <span className="ov-card-title">健康度</span>
          <span className="ov-card-hint">点条目去对应分区</span>
        </header>
        <div className="ov-health">
          <button className="ov-health-row" type="button" onClick={() => onNavigate("ai")}>
            <span className={`ov-dot ${dot(Boolean(runtime?.available))}`} />
            <span>模型连通</span>
            <span className="ov-health-val">{runtime?.available ? runtime.active_client ?? "已连接" : "未连接"}</span>
          </button>
          <button className="ov-health-row" type="button" onClick={() => onNavigate("data")}>
            <span className={`ov-dot ${dot(providerOn > 0, true)}`} />
            <span>数据源</span>
            <span className="ov-health-val">{providerOn}/{providerTotal} 启用</span>
          </button>
          <button className="ov-health-row" type="button" onClick={() => onNavigate("ai")}>
            <span className={`ov-dot ${dot(skillsOn > 0, true)}`} />
            <span>技能</span>
            <span className="ov-health-val">{skillsOn} 个启用</span>
          </button>
          <button className="ov-health-row" type="button" onClick={() => onNavigate("risk")}>
            <span className={`ov-dot ${realOrder === "blocked" ? "d-ok" : "d-warn"}`} />
            <span>交易护栏</span>
            <span className="ov-health-val">{realOrder === "blocked" ? "只读" : String(realOrder ?? "未知")}</span>
          </button>
        </div>
      </section>
    </div>
  );
}
