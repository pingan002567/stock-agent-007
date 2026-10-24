/** 配置概览的判定逻辑（纯函数，放 lib 以便单测与复用）。 */

export interface OverviewSettings {
  agent_runtime?: {
    mode?: string;
    available?: boolean;
    active_client?: string;
    degraded?: boolean;
    degraded_reason?: string | null;
    model_name?: string;
  };
  runtime_config?: Record<string, unknown>;
  risk_policy?: { active?: { name?: string; rules?: Record<string, unknown> } };
  data_sources?: {
    provider_states?: Record<string, { enabled?: boolean }>;
    provider_credentials?: Record<string, unknown>;
  };
  investor_profile?: { risk_level?: string };
  trading_controls?: { real_order?: string; paper_trading?: string };
  skills?: Array<{ enabled?: boolean }>;
}

export type OverviewTab =
  | "overview" | "ai" | "data" | "risk" | "channels" | "diag" | "appearance" | "workspace";

type Task = { enabled?: boolean };

export type Issue = {
  level: "block" | "warn" | "info";
  title: string;
  detail: string;
  tab: OverviewTab;
  action: string;
};

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** 收集「会阻塞使用」与「值得看一眼」的项。只列能落到具体分区的。 */
export function collectIssues(settings: OverviewSettings, tasks: Task[], tasksLoaded: boolean): Issue[] {
  const issues: Issue[] = [];
  const runtime = settings.agent_runtime;
  const apiReady = Boolean(settings.runtime_config?.has_api_key);

  if (!runtime?.available) {
    issues.push({
      level: "block",
      title: "AI 运行时未就绪",
      detail: "模型没有连上，对话与定时任务都跑不了。",
      tab: "ai",
      action: "去连接",
    });
  } else if (runtime.degraded) {
    issues.push({
      level: "warn",
      title: "运行时降级",
      detail: runtime.degraded_reason || "部分能力不可用，建议检查模型配置。",
      tab: "ai",
      action: "看详情",
    });
  } else if (!apiReady) {
    issues.push({
      level: "block",
      title: "缺少模型凭证",
      detail: "还没有填写任何提供商的 API Key。",
      tab: "ai",
      action: "去填写",
    });
  }

  // 风控档位：单票上限过高时提醒确认（真实的激进档会被这条命中）
  const rules = settings.risk_policy?.active?.rules ?? {};
  const single = num(rules.single_position_max_weight_pct);
  const sector = num(rules.sector_max_weight_pct);
  if (single !== null && single >= 50) {
    issues.push({
      level: "warn",
      title: `风控档位很激进（单票 ${single}%）`,
      detail: `当前生效「${settings.risk_policy?.active?.name ?? "未知"}」。单票允许到 ${single}%、行业 ${sector ?? "—"}% —— 确认这个口径仍然符合你的资金规模。`,
      tab: "risk",
      action: "看一眼",
    });
  }

  const states = settings.data_sources?.provider_states ?? {};
  const enabledProviders = Object.values(states).filter((v) => v?.enabled).length;
  if (enabledProviders === 0) {
    issues.push({
      level: "block",
      title: "没有启用任何数据源",
      detail: "行情、财务与情绪数据都拿不到，报告会大面积降级。",
      tab: "data",
      action: "去启用",
    });
  }

  // 没加载成功时不能断言「没有任务」—— 那是把网络失败说成配置缺失
  const enabledTasks = tasks.filter((t) => t.enabled !== false).length;
  if (tasksLoaded && enabledTasks === 0) {
    issues.push({
      level: "info",
      title: "没有启用的定时任务",
      detail: "盘前/盘中/收盘的自动简报都不会触发。",
      tab: "channels",
      action: "去配置",
    });
  }

  return issues;
}
