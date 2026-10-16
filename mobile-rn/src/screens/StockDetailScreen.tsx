import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import type { RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import {
  fetchStockContext,
  fetchStockFinancial,
  fetchStockHistory,
  fetchStockIntel,
  triggerStockResearch,
} from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { PriceChart } from '../components/PriceChart';
import { trendColor } from '../lib/colors';
import { formatMoney, relativeTime } from '../lib/format';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import { usePrefill } from '../store/prefill';
import type { FinancialItem, HistoryBar, IntelItem, StockContext } from '../types';
import { useThemedStyles } from '../lib/tokens';

type Nav = NativeStackNavigationProp<RootStackParamList>;
type Route = RouteProp<RootStackParamList, 'StockDetail'>;

export default function StockDetailScreen() {
  const styles = useThemedStyles(baseStyles);
  const navigation = useNavigation<Nav>();
  const route = useRoute<Route>();
  const { baseURL, token } = useConnection();
  const { symbol, name } = route.params;

  const [ctx, setCtx] = useState<StockContext | null>(null);
  const [history, setHistory] = useState<HistoryBar[]>([]);
  const [intel, setIntel] = useState<IntelItem[]>([]);
  const [financial, setFinancial] = useState<FinancialItem[]>([]);
  const [rangeDays, setRangeDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [researchMsg, setResearchMsg] = useState<string | null>(null);
  const [researching, setResearching] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [c, h, i, f] = await Promise.all([
        fetchStockContext(baseURL, token, symbol),
        fetchStockHistory(baseURL, token, symbol, 90),
        fetchStockIntel(baseURL, token, symbol),
        fetchStockFinancial(baseURL, token, symbol),
      ]);
      setCtx(c);
      setHistory(h);
      setIntel(i);
      setFinancial(f);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token, symbol]);

  useEffect(() => {
    void load();
  }, [load]);

  // 带上 page/symbol 上下文，后端才能知道这是从标的页发起的提问
  const analyze = () => {
    usePrefill.getState().set(
      `结合 ${symbol}${ctx?.name ?? name ? ` ${ctx?.name ?? name}` : ''} 的行情、财报与最新情报，给我一份要点式分析：结论、依据、风险与关注价位。数字要有出处，不要编造。`,
      { page: 'stock', symbol }
    );
    navigation.navigate('Main', { screen: 'Chat' });
  };

  const research = async () => {
    setResearching(true);
    setResearchMsg('研报生成中…');
    try {
      const r = await triggerStockResearch(baseURL, token, symbol);
      setResearchMsg(r.message ?? (r.report_id ? '研报已生成' : '已触发'));
      if (r.report_id) navigation.navigate('ReportDetail', { reportId: r.report_id });
    } catch (e) {
      setResearchMsg(e instanceof Error ? e.message : '触发失败');
    } finally {
      setResearching(false);
    }
  };

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (loading && !ctx) return <ActivityIndicator style={{ marginTop: 60 }} />;

  const price = ctx?.price;
  const pct = price?.change_pct ?? 0;
  const color = trendColor(pct);
  const latestFin = financial[0];
  const latestReport = ctx?.latest_report;
  const rel = ctx?.relation;
  const holding = ctx?.holding;

  return (
    <ScrollView
      style={styles.container}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} />}
    >
      <View style={styles.header}>
        <Text style={styles.symbol}>{symbol}</Text>
        <Text style={styles.name}>{ctx?.name ?? name ?? ''}</Text>

        <View style={styles.quoteRow}>
          <Text style={[styles.price, { color }]}>{price?.last != null ? price.last.toFixed(2) : '—'}</Text>
          <Text style={[styles.change, { color }]}>
            {pct >= 0 ? '+' : ''}
            {pct.toFixed(2)}%
          </Text>
        </View>

        {rel && (rel.in_watchlist || rel.in_holdings || rel.monitored) ? (
          <View style={styles.chips}>
            {rel.in_watchlist ? <Text style={styles.chip}>自选</Text> : null}
            {rel.in_holdings ? <Text style={styles.chip}>持仓</Text> : null}
            {rel.monitored ? <Text style={styles.chip}>盯盘</Text> : null}
          </View>
        ) : null}

        {ctx?.price?.source || ctx?.quote_degraded ? (
          <Text style={styles.degradedNote}>
            {ctx?.quote_degraded ? '⚠️ 行情降级' : ''}
            {ctx?.price?.source ? ` · 来源 ${String(ctx.price.source)}` : ''}
          </Text>
        ) : null}
      </View>

      <View style={styles.actions}>
        <Pressable style={styles.actionBtn} onPress={analyze}>
          <Text style={styles.actionText}>在对话中分析</Text>
        </Pressable>
        <Pressable style={[styles.actionBtn, styles.actionSecondary]} onPress={() => void research()} disabled={researching}>
          {researching ? (
            <ActivityIndicator size="small" />
          ) : (
            <Text style={styles.actionTextSecondary}>生成研报</Text>
          )}
        </Pressable>
      </View>
      {researchMsg ? <Text style={styles.researchMsg}>{researchMsg}</Text> : null}
      {ctx?.research_status ? <Text style={styles.researchMsg}>研究状态：{ctx.research_status}</Text> : null}

      <PriceChart items={history} market={ctx?.market} rangeDays={rangeDays} onRangeChange={setRangeDays} />

      {/* 概况 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>概况</Text>
        {ctx?.market ? <Row label="市场" value={String(ctx.market)} /> : null}
        {ctx?.industry ? <Row label="行业" value={String(ctx.industry)} /> : null}
        {ctx?.sector ? <Row label="板块" value={String(ctx.sector)} /> : null}
        {ctx?.ai_state?.stance ? <Row label="观点" value={String(ctx.ai_state.stance)} /> : null}
        {ctx?.ai_state?.risk_label ? <Row label="风险" value={String(ctx.ai_state.risk_label)} /> : null}
        {holding?.quantity ? <Row label="持仓数量" value={Number(holding.quantity).toFixed(2)} /> : null}
        {holding?.pnl_pct != null ? (
          <Row label="持仓盈亏" value={`${holding.pnl_pct >= 0 ? '+' : ''}${Number(holding.pnl_pct).toFixed(2)}%`} color={trendColor(holding.pnl_pct)} />
        ) : null}
        {ctx?.summary ? <Text style={styles.summary}>{String(ctx.summary)}</Text> : null}
      </View>

      {latestFin ? (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>最新财报（{latestFin.report_date ?? '—'}）</Text>
          <Row label="营收" value={formatMoney(latestFin.revenue)} />
          <Row
            label="利润"
            value={formatMoney(latestFin.profit)}
            color={latestFin.profit != null && latestFin.profit < 0 ? '#FF3B30' : undefined}
          />
          {latestFin.total_assets != null ? <Row label="总资产" value={formatMoney(latestFin.total_assets)} /> : null}
        </View>
      ) : null}

      {latestReport?.report_id ? (
        <Pressable style={styles.card} onPress={() => navigation.navigate('ReportDetail', { reportId: latestReport.report_id! })}>
          <Text style={styles.cardTitle}>最新研报</Text>
          <Text style={styles.link}>{relativeTime(latestReport.generated_at)} ›</Text>
        </Pressable>
      ) : null}

      <View style={styles.card}>
        <Text style={styles.cardTitle}>资讯</Text>
        {intel.slice(0, 5).map((it, i) => (
          <View key={i} style={styles.intelRow}>
            <Text style={styles.intelTitle}>{it.title}</Text>
            <Text style={styles.intelMeta}>
              {it.source} · {String(it.published_at ?? '').slice(0, 10)}
            </Text>
          </View>
        ))}
        {intel.length === 0 && <Text style={styles.muted}>暂无资讯</Text>}
      </View>
    </ScrollView>
  );
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  const styles = useThemedStyles(baseStyles);
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, color ? { color } : null]} selectable>
        {value}
      </Text>
    </View>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff', padding: 16 },
  header: { marginBottom: 12 },
  symbol: { fontSize: 24, fontWeight: '700' },
  name: { fontSize: 14, color: '#666', marginTop: 2 },
  quoteRow: { flexDirection: 'row', alignItems: 'baseline', marginTop: 8 },
  price: { fontSize: 28, fontWeight: '700' },
  change: { fontSize: 15, marginLeft: 10, fontWeight: '600' },
  chips: { flexDirection: 'row', gap: 6, marginTop: 8 },
  chip: {
    backgroundColor: '#eef4ff',
    color: '#007AFF',
    fontSize: 11,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 8,
    overflow: 'hidden',
  },
  degradedNote: { fontSize: 11, color: '#B26A00', marginTop: 6 },
  actions: { flexDirection: 'row', gap: 10, marginBottom: 8 },
  actionBtn: { backgroundColor: '#007AFF', borderRadius: 8, paddingVertical: 10, paddingHorizontal: 16, flex: 1, alignItems: 'center' },
  actionSecondary: { backgroundColor: '#eef4ff' },
  actionText: { color: '#fff', fontWeight: '600' },
  actionTextSecondary: { color: '#007AFF', fontWeight: '600' },
  researchMsg: { color: '#f59e0b', fontSize: 12, marginBottom: 6 },
  card: { backgroundColor: '#f6f8fa', borderRadius: 10, padding: 12, marginTop: 12 },
  cardTitle: { fontSize: 14, fontWeight: '700', marginBottom: 8 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4, gap: 12 },
  rowLabel: { fontSize: 13, color: '#666' },
  rowValue: { fontSize: 13, color: '#111', flex: 1, textAlign: 'right' },
  summary: { fontSize: 13, color: '#333', lineHeight: 20, marginTop: 8 },
  link: { color: '#007AFF', fontSize: 13 },
  intelRow: { marginBottom: 8 },
  intelTitle: { fontSize: 13 },
  intelMeta: { fontSize: 11, color: '#999', marginTop: 2 },
  muted: { color: '#999', fontSize: 13 },
});
