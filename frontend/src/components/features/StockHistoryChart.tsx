import { useMemo, useRef, useState } from "react";
import { historyForChart } from "@/lib/sortStockSeries";

export type HistoryBar = {
  date?: string;
  day?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  amount?: number;
};

type RangeDays = 7 | 30 | 90;

const RANGES: { days: RangeDays; label: string }[] = [
  { days: 7, label: "1周" },
  { days: 30, label: "1月" },
  { days: 90, label: "3月" },
];

const W = 800;
const H = 320;
const PAD = { left: 58, right: 14, top: 12, priceBottom: 196, volTop: 214, volBottom: 292, bottom: 308 };

function formatPrice(value: number, market?: string) {
  const prefix = market === "HK" ? "HK$" : market === "US" ? "$" : "¥";
  const abs = Math.abs(value);
  if (abs >= 10000) return `${prefix}${(value / 10000).toFixed(2)}万`;
  if (abs >= 1000) return `${prefix}${value.toFixed(1)}`;
  if (abs >= 100) return `${prefix}${value.toFixed(2)}`;
  return `${prefix}${value.toFixed(3)}`;
}

function formatVolume(value: number) {
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function formatDateLabel(raw?: string) {
  if (!raw) return "—";
  const s = String(raw).slice(0, 10);
  const [, m, d] = s.split("-");
  return m && d ? `${m}/${d}` : s;
}

function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) {
    const pad = Math.max(min * 0.02, 0.01);
    min -= pad;
    max += pad;
  }
  const span = max - min;
  const step = span / Math.max(count - 1, 1);
  const mag = 10 ** Math.floor(Math.log10(step || 1));
  const norm = step / mag;
  const niceStep = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const start = Math.floor(min / niceStep) * niceStep;
  const ticks: number[] = [];
  for (let v = start; v <= max + niceStep * 0.5; v += niceStep) {
    if (v >= min - niceStep * 0.01) ticks.push(Number(v.toFixed(6)));
    if (ticks.length >= count + 1) break;
  }
  return ticks.length >= 2 ? ticks : [min, max];
}

function xAt(index: number, count: number) {
  const plotW = W - PAD.left - PAD.right;
  if (count <= 1) return PAD.left + plotW / 2;
  return PAD.left + (index / (count - 1)) * plotW;
}

export function StockHistoryChart({
  items,
  market,
  rangeDays,
  onRangeChange,
}: {
  items: HistoryBar[];
  market?: string;
  rangeDays: RangeDays;
  onRangeChange: (days: RangeDays) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const series = useMemo(() => {
    const asc = historyForChart(items);
    return asc.slice(-rangeDays);
  }, [items, rangeDays]);

  const stats = useMemo(() => {
    if (series.length === 0) return null;
    const closes = series.map((b) => b.close ?? 0);
    const highs = series.map((b) => b.high ?? b.close ?? 0);
    const lows = series.map((b) => b.low ?? b.close ?? 0);
    const volumes = series.map((b) => b.volume ?? 0);
    const first = closes[0] ?? 0;
    const last = closes[closes.length - 1] ?? 0;
    const changePct = first ? ((last - first) / first) * 100 : 0;
    return {
      changePct,
      high: Math.max(...highs),
      low: Math.min(...lows.filter((v) => v > 0)),
      last,
      avgVolume: volumes.reduce((a, b) => a + b, 0) / Math.max(volumes.length, 1),
    };
  }, [series]);

  const layout = useMemo(() => {
    if (series.length === 0) return null;
    const lows = series.map((b) => b.low ?? b.close ?? 0);
    const highs = series.map((b) => b.high ?? b.close ?? 0);
    const closes = series.map((b) => b.close ?? 0);
    const priceMin = Math.min(...lows);
    const priceMax = Math.max(...highs);
    const pad = (priceMax - priceMin || priceMax * 0.02 || 1) * 0.08;
    const yMin = priceMin - pad;
    const yMax = priceMax + pad;
    const priceTicks = niceTicks(yMin, yMax, 4);
    const volMax = Math.max(...series.map((b) => b.volume ?? 0), 1);

    const yPrice = (v: number) => {
      const t = (v - yMin) / (yMax - yMin || 1);
      return PAD.priceBottom - t * (PAD.priceBottom - PAD.top);
    };
    const yVol = (v: number) => {
      const t = v / volMax;
      return PAD.volBottom - t * (PAD.volBottom - PAD.volTop);
    };

    const linePts = series.map((b, i) => ({
      x: xAt(i, series.length),
      y: yPrice(b.close ?? 0),
      bar: b,
    }));
    const areaPath = [
      `M ${linePts[0]?.x ?? PAD.left} ${PAD.priceBottom}`,
      ...linePts.map((p) => `L ${p.x} ${p.y}`),
      `L ${linePts[linePts.length - 1]?.x ?? PAD.left} ${PAD.priceBottom}`,
      "Z",
    ].join(" ");
    const linePath = linePts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");

    const xLabels = [0, Math.floor((series.length - 1) / 2), series.length - 1]
      .filter((v, i, arr) => arr.indexOf(v) === i)
      .map((i) => ({ i, x: xAt(i, series.length), label: formatDateLabel(series[i]?.date) }));

    return { yMin, yMax, priceTicks, volMax, yPrice, yVol, linePts, areaPath, linePath, xLabels };
  }, [series]);

  const onMove = (clientX: number) => {
    if (!layout || !rootRef.current || series.length === 0) return;
    const rect = rootRef.current.getBoundingClientRect();
    const rel = ((clientX - rect.left) / rect.width) * W;
    let best = 0;
    let bestDist = Infinity;
    layout.linePts.forEach((p, i) => {
      const d = Math.abs(p.x - rel);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    setHoverIdx(best);
  };

  const active = hoverIdx != null ? series[hoverIdx] : series[series.length - 1];
  const activeIdx = hoverIdx ?? series.length - 1;
  const up = (stats?.changePct ?? 0) >= 0;

  if (!layout || !stats || series.length === 0) {
    return <div className="muted">暂无历史数据</div>;
  }

  const hoverX = layout.linePts[activeIdx]?.x ?? PAD.left;

  return (
    <div className="stock-history-chart" ref={rootRef}>
      <div className="stock-history-toolbar">
        <div className="stock-history-stats">
          <span className={`stock-history-change ${up ? "up" : "down"}`}>
            {up ? "+" : ""}{stats.changePct.toFixed(2)}%
          </span>
          <span className="stock-history-stat">
            高 <strong>{formatPrice(stats.high, market)}</strong>
          </span>
          <span className="stock-history-stat">
            低 <strong>{formatPrice(stats.low, market)}</strong>
          </span>
          <span className="stock-history-stat">
            均量 <strong>{formatVolume(stats.avgVolume)}</strong>
          </span>
        </div>
        <div className="time-range-btns">
          {RANGES.map((r) => (
            <button
              key={r.days}
              type="button"
              className={`time-range-btn${rangeDays === r.days ? " active" : ""}`}
              onClick={() => onRangeChange(r.days)}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="stock-history-tooltip">
        <span>{formatDateLabel(active?.date)}</span>
        <span>开 {formatPrice(active?.open ?? 0, market)}</span>
        <span>高 {formatPrice(active?.high ?? 0, market)}</span>
        <span>低 {formatPrice(active?.low ?? 0, market)}</span>
        <span>收 <strong>{formatPrice(active?.close ?? 0, market)}</strong></span>
        <span>量 {formatVolume(active?.volume ?? 0)}</span>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="stock-history-svg"
        onMouseMove={(e) => onMove(e.clientX)}
        onMouseLeave={() => setHoverIdx(null)}
        role="img"
        aria-label="历史价格与成交量走势"
      >
        <defs>
          <linearGradient id="stockHistoryArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--blue)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--blue)" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {layout.priceTicks.map((tick) => {
          const y = layout.yPrice(tick);
          return (
            <g key={tick}>
              <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y} className="stock-history-grid" />
              <text x={PAD.left - 8} y={y + 4} textAnchor="end" className="stock-history-axis-y">
                {formatPrice(tick, market)}
              </text>
            </g>
          );
        })}

        <line x1={PAD.left} y1={PAD.priceBottom} x2={W - PAD.right} y2={PAD.priceBottom} className="stock-history-axis" />
        <line x1={PAD.left} y1={PAD.volTop} x2={W - PAD.right} y2={PAD.volTop} className="stock-history-axis" />
        <line x1={PAD.left} y1={PAD.volBottom} x2={W - PAD.right} y2={PAD.volBottom} className="stock-history-axis" />

        {series.map((bar, i) => {
          const x = xAt(i, series.length);
          const bw = Math.max(2, (W - PAD.left - PAD.right) / series.length * 0.55);
          const bullish = (bar.close ?? 0) >= (bar.open ?? bar.close ?? 0);
          const y0 = layout.yVol(0);
          const y1 = layout.yVol(bar.volume ?? 0);
          return (
            <rect
              key={bar.date ?? i}
              x={x - bw / 2}
              y={Math.min(y0, y1)}
              width={bw}
              height={Math.abs(y0 - y1)}
              className={bullish ? "stock-history-vol-up" : "stock-history-vol-down"}
              rx={1}
            />
          );
        })}

        <path d={layout.areaPath} fill="url(#stockHistoryArea)" />
        <path d={layout.linePath} className="stock-history-line" fill="none" />

        {hoverIdx != null && (
          <>
            <line x1={hoverX} y1={PAD.top} x2={hoverX} y2={PAD.volBottom} className="stock-history-crosshair" />
            <circle cx={hoverX} cy={layout.linePts[activeIdx]?.y ?? 0} r={4} className="stock-history-dot" />
          </>
        )}

        {layout.xLabels.map(({ i, x, label }) => (
          <text key={i} x={x} y={H - 6} textAnchor="middle" className="stock-history-axis-x">
            {label}
          </text>
        ))}

        <text x={PAD.left} y={PAD.volTop - 4} className="stock-history-vol-label">
          成交量
        </text>
      </svg>
    </div>
  );
}
