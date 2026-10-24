/** 子代理技能名 → 中文标签(与 backend skill_specs.WORKBENCH_SKILLS 对齐;
 * 未知名回退 undefined 由调用方兜底显示原名) */
const SKILL_LABELS: Record<string, string> = {
  "stock-deep-dive": "个股深度研判",
  "crypto-dive": "加密资产研判",
  "valuation-check": "估值与财务体检",
  "catalyst-scan": "催化剂扫描",
  "portfolio-risk-audit": "持仓风险审查",
  "strategy-backtest": "策略回测评估",
  "rebalance-plan": "调仓方案拟制",
  "watch-rule-monitor": "盯盘规则巡检",
  "report-render": "报告成稿",
  "sector-rotation-digest": "板块轮动扫描",
  "market-sentiment": "市场情绪判读",
  "general-purpose": "通用子代理",
  bash: "命令行子代理",
};

export function skillLabelOf(name?: string): string | undefined {
  if (!name) return undefined;
  return SKILL_LABELS[name];
}
