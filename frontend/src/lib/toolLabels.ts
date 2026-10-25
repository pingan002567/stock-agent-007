/** 工具中文名：**后端是唯一真源**（`/api/settings.tools[].label`）。
 *
 *  这里保留一份静态表，只为三种情况兜底：旧后端没下发、设置请求失败、
 *  单测环境。真源在后端 `backend/config/tool_labels.py` —— 以前 Web 与安卓
 *  各存一份映射，实测 75 个工具里 Web 缺 24、安卓缺 27，聊天里直接显示英文名。
 */

const STATIC_TOOL_LABELS: Record<string, string> = {
  get_stock_context: "个股分析",
  get_daily_history: "历史行情",
  search_stock_intel: "情报搜索",
  add_watchlist_item: "添加自选",
  list_watchlist: "查看自选",
  remove_watchlist_item: "删除自选",
  get_portfolio_snapshot: "持仓快照",
  upsert_holding: "调整持仓",
  remove_holding: "删除持仓",
  analyze_portfolio_risk: "组合风险",
  get_active_risk_policy: "风险策略",
  list_risk_policies: "风险策略列表",
  update_risk_policy: "调整风险策略",
  create_risk_policy: "新建风险策略",
  activate_risk_policy: "切换风险策略",
  evaluate_policy_risk: "策略风险评估",
  generate_draft_order: "生成拟单",
  confirm_rebalance_draft: "确认草案",
  reject_rebalance_draft: "驳回草案",
  list_rebalance_drafts: "草案列表",
  get_rebalance_draft: "草案详情",
  create_pre_trade_review: "交易审查",
  list_pre_trade_reviews: "审查记录",
  list_paper_orders: "Paper 订单",
  get_paper_portfolio: "Paper 组合",
  analyze_paper_performance: "Paper 绩效",
  create_paper_portfolio_snapshot: "创建快照",
  list_decision_journal: "决策日志",
  get_decision_journal_entry: "决策条目",
  summarize_decision_outcomes: "决策总结",
  list_review_inbox: "待办列表",
  summarize_review_inbox: "待办总结",
  dismiss_inbox_item: "忽略待办",
  snooze_inbox_item: "稍后提醒",
  mark_inbox_item_done: "完成待办",
  get_industry_context: "行业格局",
  list_data_sources: "数据源目录",
  describe_data_capability: "数据能力说明",
  invoke_data_capability: "直调数据源",
  get_market_structure: "市场结构",
  get_monitor_events: "监控事件",
  get_monitor_rules: "监控规则",
  evaluate_monitor_rules: "评估规则",
  upsert_monitor_rule: "写盯盘规则",
  delete_monitor_rule: "删盯盘规则",
  list_strategies: "策略列表",
  run_strategy_backtest: "运行回测",
  get_backtest_result: "回测结果",
  list_report_templates: "报告模板",
  generate_report: "生成报告",
  get_report_quality: "报告质量",
  ask_clarification: "反问澄清",
  web_search: "全网搜索",
  web_fetch: "网页抓取",
  read_file: "读取资料",
  grep: "检索资料",
  glob: "查找文件",
  ls: "浏览目录",
  view_image: "查看图片",
  bash: "执行代码",
  write_file: "写文件",
  str_replace: "编辑文件",
  present_files: "交付文件",
  task: "子代理委派",
  write_todos: "执行计划",
};

/** 后端下发的工具中文名（`/api/settings.tools[].label`）。
 *
 *  以前 Web 与安卓各存一份映射，必然漂移（实测 75 个工具里 Web 缺 24、安卓缺 27）。
 *  现在真源在后端，这里只做缓存；静态表保留为离线/旧后端兜底。
 */
let remoteToolLabels: Record<string, string> | null = null;

/** 设置加载后调用：把后端下发的工具名装进缓存 */
export function primeToolLabels(labels: Record<string, string> | null | undefined): void {
  if (!labels) return;
  const next: Record<string, string> = {};
  for (const [name, label] of Object.entries(labels)) {
    if (name && typeof label === "string" && label) next[name] = label;
  }
  remoteToolLabels = Object.keys(next).length ? next : null;
}

export function toolLabel(name: string): string {
  return remoteToolLabels?.[name] || STATIC_TOOL_LABELS[name] || name;
}
