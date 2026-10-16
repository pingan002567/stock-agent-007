import { useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Defs, G, Line, LinearGradient, Path, Rect, Stop, Text as SvgText } from 'react-native-svg';
import type { HistoryBar } from '../types';

const W = 800;
const H = 320;
const PAD = { left: 58, right: 14, top: 12, priceBottom: 196, volTop: 214, volBottom: 292, bottom: 308 };

const UP = '#e53935';
const DOWN = '#26a69a';
const BLUE = '#3b82f6';

const RANGES: { days: number; label: string }[] = [
  { days: 7, label: '1周' },
  { days: 30, label: '1月' },
  { days: 90, label: '3月' },
];

function formatPrice(value: number, market?: string) {
  const prefix = market === 'HK' ? 'HK$' : market === 'US' ? '$' : '¥';
  const abs = Math.abs(value);
  if (abs >= 10000) return `${prefix}${(value / 10000).toFixed(2)}万`;
  if (abs >= 1000) return `${prefix}${value.toFixed(1)}`;
  if (abs >= 100) return `${prefix}${value.toFixed(2)}`;
  return `${prefix}${value.toFixed(3)}`;
}

function formatVolume(value: number) {
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
}

function formatDateLabel(raw?: string) {
  if (!raw) return '—';
  const s = String(raw).slice(0, 10);
  const parts = s.split('-');
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : s;
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

export function PriceChart({
  items,
  market,
  rangeDays,
  onRangeChange,
}: {
  items: HistoryBar[];
  market?: string;
  rangeDays: number;
  onRangeChange: (days: number) => void;
}) {
  const series = useMemo(() => {
    const asc = [...items].sort((a, b) => String(a.date).localeCompare(String(b.date)));
    return asc.slice(-rangeDays);
  }, [items, rangeDays]);

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

    const linePts = series.map((b, i) => ({ x: xAt(i, series.length), y: yPrice(b.close ?? 0), bar: b }));
    const areaPath = [
      `M ${linePts[0]?.x ?? PAD.left} ${PAD.priceBottom}`,
      ...linePts.map((p) => `L ${p.x} ${p.y}`),
      `L ${linePts[linePts.length - 1]?.x ?? PAD.left} ${PAD.priceBottom}`,
      'Z',
    ].join(' ');
    const linePath = linePts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');

    const xLabels = [0, Math.floor((series.length - 1) / 2), series.length - 1]
      .filter((v, i, arr) => arr.indexOf(v) === i)
      .map((i) => ({ i, x: xAt(i, series.length), label: formatDateLabel(series[i]?.date) }));

    const first = closes[0] ?? 0;
    const last = closes[closes.length - 1] ?? 0;
    const changePct = first ? ((last - first) / first) * 100 : 0;
    const high = Math.max(...highs);
    const low = Math.min(...lows.filter((v) => v > 0));
    const avgVolume = series.reduce((a, b) => a + (b.volume ?? 0), 0) / Math.max(series.length, 1);

    return { priceTicks, yPrice, yVol, linePts, areaPath, linePath, xLabels, changePct, high, low, avgVolume };
  }, [series]);

  if (!layout || series.length === 0) {
    return <Text style={styles.muted}>暂无历史数据</Text>;
  }

  const up = layout.changePct >= 0;
  const trend = up ? UP : DOWN;

  return (
    <View style={styles.wrap}>
      <View style={styles.toolbar}>
        <View style={styles.stats}>
          <Text style={[styles.change, { color: trend }]}>
            {up ? '+' : ''}
            {layout.changePct.toFixed(2)}%
          </Text>
          <Text style={styles.stat}>高 {formatPrice(layout.high, market)}</Text>
          <Text style={styles.stat}>低 {formatPrice(layout.low, market)}</Text>
          <Text style={styles.stat}>均量 {formatVolume(layout.avgVolume)}</Text>
        </View>
        <View style={styles.ranges}>
          {RANGES.map((r) => (
            <Pressable key={r.days} style={[styles.rangeBtn, rangeDays === r.days && styles.rangeActive]} onPress={() => onRangeChange(r.days)}>
              <Text style={[styles.rangeText, rangeDays === r.days && styles.rangeTextActive]}>{r.label}</Text>
            </Pressable>
          ))}
        </View>
      </View>

      <Svg width="100%" height={260} viewBox={`0 0 ${W} ${H}`}>
        <Defs>
          <LinearGradient id="area" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0%" stopColor={BLUE} stopOpacity={0.28} />
            <Stop offset="100%" stopColor={BLUE} stopOpacity={0.02} />
          </LinearGradient>
        </Defs>

        {layout.priceTicks.map((tick) => (
          <G key={tick}>
            <Line x1={PAD.left} y1={layout.yPrice(tick)} x2={W - PAD.right} y2={layout.yPrice(tick)} stroke="#eee" strokeWidth={1} />
            <SvgText x={PAD.left - 8} y={layout.yPrice(tick) + 4} textAnchor="end" fontSize={11} fill="#999">
              {formatPrice(tick, market)}
            </SvgText>
          </G>
        ))}

        <Line x1={PAD.left} y1={PAD.priceBottom} x2={W - PAD.right} y2={PAD.priceBottom} stroke="#ddd" strokeWidth={1} />
        <Line x1={PAD.left} y1={PAD.volTop} x2={W - PAD.right} y2={PAD.volTop} stroke="#ddd" strokeWidth={1} />

        {series.map((bar, i) => {
          const x = xAt(i, series.length);
          const bw = Math.max(2, ((W - PAD.left - PAD.right) / series.length) * 0.55);
          const bullish = (bar.close ?? 0) >= (bar.open ?? bar.close ?? 0);
          const y0 = layout.yVol(0);
          const y1 = layout.yVol(bar.volume ?? 0);
          return (
            <Rect
              key={bar.date ?? i}
              x={x - bw / 2}
              y={Math.min(y0, y1)}
              width={bw}
              height={Math.abs(y0 - y1)}
              fill={bullish ? UP : DOWN}
              opacity={0.55}
              rx={1}
            />
          );
        })}

        <Path d={layout.areaPath} fill="url(#area)" />
        <Path d={layout.linePath} stroke={BLUE} strokeWidth={2} fill="none" />

        {layout.linePts.length > 0 && (
          <Circle cx={layout.linePts[layout.linePts.length - 1].x} cy={layout.linePts[layout.linePts.length - 1].y} r={4} fill={BLUE} />
        )}

        {layout.xLabels.map(({ i, x, label }) => (
          <SvgText key={i} x={x} y={H - 6} textAnchor="middle" fontSize={11} fill="#999">
            {label}
          </SvgText>
        ))}
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginVertical: 8 },
  toolbar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  stats: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  change: { fontSize: 15, fontWeight: '700' },
  stat: { fontSize: 12, color: '#666' },
  ranges: { flexDirection: 'row' },
  rangeBtn: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 6, borderWidth: 1, borderColor: '#ddd', marginLeft: 6 },
  rangeActive: { borderColor: '#007AFF', backgroundColor: '#eef4ff' },
  rangeText: { fontSize: 12, color: '#666' },
  rangeTextActive: { color: '#007AFF', fontWeight: '600' },
  muted: { color: '#999', textAlign: 'center', marginVertical: 40 },
});
