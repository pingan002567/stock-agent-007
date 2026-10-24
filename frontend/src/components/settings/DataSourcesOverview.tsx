/** 数据与情报的目录总览：一页说明「有哪些来源、各自什么状态」。
 *
 *  这一块只读：开关与凭证都在下面两个子区维护。放它是因为原来「数据源」页
 *  只讲行情 provider，新闻/舆情藏在另一个分区，用户不知道还有哪些源可用。
 */

export interface DataOverviewProps {
  providerStates?: Record<string, { enabled?: boolean }>;
  availableProviders?: Array<{ id?: string; name?: string; free?: boolean }>;
  intelSources?: { providers?: Record<string, { enabled?: boolean; provider?: string }> };
  availableIntelProviders?: Array<{ id?: string; name?: string; free?: boolean }>;
  availableSentimentProviders?: Array<{ id?: string; name?: string; free?: boolean }>;
  jumpTo: (id: string) => void;
}

function countOn(map?: Record<string, { enabled?: boolean }>): { on: number; total: number } {
  const entries = Object.values(map ?? {});
  return { on: entries.filter((v) => v?.enabled).length, total: entries.length };
}

export function DataSourcesOverview({
  providerStates,
  availableProviders = [],
  intelSources,
  availableIntelProviders = [],
  availableSentimentProviders = [],
  jumpTo,
}: DataOverviewProps) {
  const market = countOn(providerStates);
  const intelEnabled = Object.values(intelSources?.providers ?? {}).filter((v) => v?.enabled).length;
  const intelTotal = availableIntelProviders.length + availableSentimentProviders.length;
  const freeCount = availableProviders.filter((p) => p.free).length;

  const rows = [
    {
      id: "data-market",
      title: "行情与财务",
      value: `${market.on}/${market.total || availableProviders.length} 启用`,
      detail: market.total === 0
        ? "还没有启用任何行情 provider，报告会大面积降级。"
        : `覆盖 A 股 / 港股 / 美股行情与财报；其中 ${freeCount} 个免 Key 源。`,
      warn: market.on === 0,
    },
    {
      id: "data-intel",
      title: "新闻与舆情",
      value: intelEnabled > 0 ? `${intelEnabled} 个启用` : "未启用",
      detail: intelEnabled > 0
        ? "用于个股情报、市场情绪与「为什么涨」的归因。"
        : `共 ${intelTotal} 个可选源（含免费源）；不启用时情报类结论会标注「精度有限」。`,
      warn: intelEnabled === 0,
    },
  ];

  return (
    <div className="ov-card">
      <header className="ov-card-head">
        <span className="ov-card-title">来源总览</span>
        <span className="ov-card-hint">只读 · 开关与凭证在下面两区维护</span>
      </header>
      <div className="ov-tasks">
        {rows.map((row) => (
          <div className="ov-task" key={row.id}>
            <div className="ov-task-main">
              <div className="ov-task-title">
                <span className={`ov-dot ${row.warn ? "d-warn" : "d-ok"}`} />
                {row.title}
                <span className="ov-row-value">{row.value}</span>
              </div>
              <div className="ov-task-detail">{row.detail}</div>
            </div>
            <button className="ghost ov-task-go" type="button" onClick={() => jumpTo(row.id)}>
              查看 →
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
