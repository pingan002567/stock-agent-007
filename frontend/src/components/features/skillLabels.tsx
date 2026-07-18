/** 子代理技能名 → 中文标签(与 backend skill_specs.WORKBENCH_SKILLS 对齐;
 * 未知名回退 undefined 由调用方兜底显示原名) */
const SKILL_LABELS: Record<string, string> = {
  "stock-researcher": "AI 研究员",
  "valuation-analyst": "AI 估值分析师",
  "catalyst-tracker": "AI 催化剂追踪",
  "risk-officer": "AI 风控官",
  "strategy-analyst": "AI 策略分析师",
  "rebalance-planner": "AI 调仓规划师",
  "stock-monitor": "AI 盯盘员",
  "report-writer": "AI 报告员",
  "general-purpose": "通用子代理",
  bash: "命令行子代理",
};

export function skillLabelOf(name?: string): string | undefined {
  if (!name) return undefined;
  return SKILL_LABELS[name];
}
