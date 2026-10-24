/** 「什么事件会通知你」清单。
 *
 *  原来「通知通道」页只有通道配置，没有说清哪些事件会触发 —— 用户配完通道
 *  仍然不知道自己会不会被打扰。这里把触发源列清楚，并标明去哪里改。
 *  刻意不显示条数：数字要靠额外请求，拉不到就会说谎。
 */

const TRIGGERS = [
  {
    title: "定时任务完成",
    detail: "盘前简报 / 盘中报告 / 收盘体检 / 每日机会发现等跑完会推送摘要。",
    where: "系统与诊断 → 定时任务",
  },
  {
    title: "盯盘规则命中",
    detail: "价格、涨跌幅、量比、资金费率等阈值被触发时实时提醒。",
    where: "盯盘页（规则在那边维护）",
  },
  {
    title: "风控告警",
    detail: "单票超限、行业集中度超限、单票浮亏触及止损线。",
    where: "画像与风控",
  },
  {
    title: "拟单与审查待确认",
    detail: "调仓草案或 pre-trade review 需要你显式确认时才推送。",
    where: "持仓 / 调仓页",
  },
];

export function NotifyTriggers() {
  return (
    <div className="ov-card">
      <header className="ov-card-head">
        <span className="ov-card-title">什么事件会通知你</span>
        <span className="ov-card-hint">通道在下面配置 · 这里只说明触发源</span>
      </header>
      <div className="ov-tasks">
        {TRIGGERS.map((t) => (
          <div className="ov-task" key={t.title}>
            <div className="ov-task-main">
              <div className="ov-task-title">{t.title}</div>
              <div className="ov-task-detail">
                {t.detail}
                <span className="ov-task-where">改这里：{t.where}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
