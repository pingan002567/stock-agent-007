import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
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
import { PriceChart } from '../components/PriceChart';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import { usePrefill } from '../store/prefill';
import type { FinancialItem, HistoryBar, IntelItem, StockContext } from '../types';

type Nav = NativeStackNavigationProp<RootStackParamList>;
type Route = RouteProp<RootStackParamList, 'StockDetail'>;

export default function StockDetailScreen() {
  const navigation = useNavigation<Nav>();
  const route = useRoute<Route>();
  const { baseURL, token } = useConnection();
  const { symbol } = route.params;

  const [ctx, setCtx] = useState<StockContext | null>(null);
  const [history, setHistory] = useState<HistoryBar[]>([]);
  const [intel, setIntel] = useState<IntelItem[]>([]);
  const [financial, setFinancial] = useState<FinancialItem[]>([]);
  const [rangeDays, setRangeDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [researchMsg, setResearchMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
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
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [baseURL, token, symbol]);

  useEffect(() => {
    void load();
  }, [load]);

  const analyze = () => {
    usePrefill.getState().set(`分析 ${symbol}${ctx?.name ? ' ' + ctx.name : ''}`);
    navigation.navigate('Main', { screen: 'Chat' });
  };

  const research = async () => {
    setResearchMsg('研报生成中…');
    try {
      const r = await triggerStockResearch(baseURL, token, symbol);
      setResearchMsg(r.message ?? (r.report_id ? '研报已生成' : '已触发'));
      if (r.report_id) navigation.navigate('ReportDetail', { reportId: r.report_id });
    } catch {
      setResearchMsg('触发失败');
    }
  };

  if (loading) return <ActivityIndicator style={{ marginTop: 60 }} />;

  const price = ctx?.price;
  const pct = price?.change_pct ?? 0;
  const up = pct >= 0;
  const color = up ? '#e53935' : '#26a69a';
  const latestFin = financial[0];
  const latestReport = ctx?.latest_report;

  return (
    <ScrollView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.symbol}>{symbol}</Text>
        <Text style={styles.name}>{ctx?.name ?? ''}</Text>
        <View style={styles.quoteRow}>
          <Text style={[styles.price, { color }]}>{price?.last != null ? price.last.toFixed(2) : '—'}</Text>
          <Text style={[styles.change, { color }]}>
            {up ? '+' : ''}
            {pct.toFixed(2)}%
          </Text>
        </View>
        {ctx?.ai_state?.stance ? (
          <Text style={styles.aiState}>
            AI 观点：{ctx.ai_state.stance}
            {ctx.ai_state.risk_label ? ` · 风险 ${ctx.ai_state.risk_label}` : ''}
          </Text>
        ) : null}
      </View>

      <View style={styles.actions}>
        <Pressable style={styles.actionBtn} onPress={analyze}>
          <Text style={styles.actionText}>在对话中分析</Text>
        </Pressable>
        <Pressable style={[styles.actionBtn, styles.actionSecondary]} onPress={() => void research()}>
          <Text style={styles.actionTextSecondary}>生成研报</Text>
        </Pressable>
      </View>
      {researchMsg ? <Text style={styles.researchMsg}>{researchMsg}</Text> : null}

      <PriceChart items={history} market={ctx?.market} rangeDays={rangeDays} onRangeChange={setRangeDays} />

      {latestFin && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>最新财报（{latestFin.report_date ?? ''}）</Text>
          <Text style={styles.finLine}>营收 {latestFin.revenue?.toLocaleString() ?? '—'}</Text>
          <Text style={styles.finLine}>利润 {latestFin.profit?.toLocaleString() ?? '—'}</Text>
        </View>
      )}

      {latestReport?.report_id ? (
        <Pressable style={styles.card} onPress={() => navigation.navigate('ReportDetail', { reportId: latestReport.report_id! })}>
          <Text style={styles.cardTitle}>最新研报</Text>
          <Text style={styles.link}>{latestReport.generated_at ?? '查看'}</Text>
        </Pressable>
      ) : null}

      <View style={styles.card}>
        <Text style={styles.cardTitle}>资讯</Text>
        {intel.slice(0, 5).map((it, i) => (
          <View key={i} style={styles.intelRow}>
            <Text style={styles.intelTitle} numberOfLines={1}>
              {it.title}
            </Text>
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

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff', padding: 16 },
  header: { marginBottom: 12 },
  symbol: { fontSize: 24, fontWeight: '700' },
  name: { fontSize: 14, color: '#666', marginTop: 2 },
  quoteRow: { flexDirection: 'row', alignItems: 'baseline', marginTop: 8 },
  price: { fontSize: 28, fontWeight: '700' },
  change: { fontSize: 15, marginLeft: 10, fontWeight: '600' },
  aiState: { fontSize: 12, color: '#666', marginTop: 6 },
  actions: { flexDirection: 'row', gap: 10, marginBottom: 8 },
  actionBtn: { backgroundColor: '#007AFF', borderRadius: 8, paddingVertical: 10, paddingHorizontal: 16, flex: 1, alignItems: 'center' },
  actionSecondary: { backgroundColor: '#eef4ff' },
  actionText: { color: '#fff', fontWeight: '600' },
  actionTextSecondary: { color: '#007AFF', fontWeight: '600' },
  researchMsg: { color: '#f59e0b', fontSize: 12, marginBottom: 6 },
  card: { backgroundColor: '#f6f8fa', borderRadius: 10, padding: 12, marginTop: 12 },
  cardTitle: { fontSize: 14, fontWeight: '700', marginBottom: 8 },
  finLine: { fontSize: 13, color: '#444', marginBottom: 4 },
  link: { color: '#007AFF', fontSize: 13 },
  intelRow: { marginBottom: 8 },
  intelTitle: { fontSize: 13 },
  intelMeta: { fontSize: 11, color: '#999', marginTop: 2 },
  muted: { color: '#999', fontSize: 13 },
});
