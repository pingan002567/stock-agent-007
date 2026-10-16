import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { fetchLatestBacktest, fetchStrategies, runBacktest } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { useConnection } from '../store/connection';
import type { BacktestRun, StrategyItem } from '../types';
import { useThemedStyles } from '../lib/tokens';

export default function StrategyScreen() {
  const styles = useThemedStyles(baseStyles);
  const { baseURL, token } = useConnection();
  const [strategies, setStrategies] = useState<StrategyItem[]>([]);
  const [backtests, setBacktests] = useState<Record<string, BacktestRun | null>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchStrategies(baseURL, token);
      setStrategies(list);
      const bt: Record<string, BacktestRun | null> = {};
      await Promise.all(
        list.map(async (s) => {
          bt[s.strategy_id] = await fetchLatestBacktest(baseURL, token, s.strategy_id);
        })
      );
      setBacktests(bt);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (id: string) => {
    setRunning(id);
    setError(null);
    try {
      const bt = await runBacktest(baseURL, token, id);
      setBacktests((b) => ({ ...b, [id]: bt }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(null);
    }
  };

  const renderMetrics = (bt?: BacktestRun | null) => {
    if (!bt) return <Text style={styles.muted}>暂无回测</Text>;
    const m = bt.metrics ?? {};
    // 胜率后端可能是 0-1 比例，也可能是 0-100 百分数；与 iOS 一致地归一到百分数
    const wr = m.win_rate;
    const wrPct = wr == null ? null : wr * (Math.abs(wr) <= 1 ? 100 : 1);
    return (
      <View style={styles.metrics}>
        <Text style={styles.metricLabel}>总收益 {signed(m.total_return_pct)}</Text>
        <Text style={styles.metricLabel}>年化 {signed(m.annualized_return_pct)}</Text>
        <Text style={styles.metricLabel}>最大回撤 {plain(m.max_drawdown_pct)}</Text>
        <Text style={styles.metricLabel}>夏普 {m.sharpe_ratio == null ? '—' : m.sharpe_ratio.toFixed(2)}</Text>
        <Text style={styles.metricLabel}>胜率 {wrPct == null ? '—' : `${wrPct.toFixed(1)}%`}</Text>
        {bt.degraded ? <Text style={styles.err}>降级：{bt.degraded_reason}</Text> : null}
      </View>
    );
  };

  const renderItem = ({ item }: { item: StrategyItem }) => (
    <View style={styles.card}>
      <View style={styles.head}>
        <Text style={styles.name}>{item.name}</Text>
        <Pressable onPress={() => void run(item.strategy_id)} disabled={running === item.strategy_id}>
          <Text style={styles.link}>{running === item.strategy_id ? '运行中…' : '运行回测'}</Text>
        </Pressable>
      </View>
      {item.description ? <Text style={styles.desc}>{item.description}</Text> : null}
      {renderMetrics(backtests[item.strategy_id])}
    </View>
  );

  return (
    <View style={styles.container}>
      <FlatList
        data={strategies}
        keyExtractor={(s) => s.strategy_id}
        renderItem={renderItem}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} />}
        ListEmptyComponent={
          error ? (
            <ErrorState message={error} onRetry={() => void load()} />
          ) : loading ? (
            <ActivityIndicator style={{ marginTop: 40 }} />
          ) : (
            <Text style={styles.muted}>暂无策略</Text>
          )
        }
        contentContainerStyle={{ padding: 16 }}
      />
    </View>
  );
}

function signed(v?: number): string {
  return v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
}

function plain(v?: number): string {
  return v == null ? '—' : `${v.toFixed(2)}%`;
}

const baseStyles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  card: { backgroundColor: '#f6f8fa', borderRadius: 10, padding: 14, marginBottom: 12 },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  name: { fontSize: 15, fontWeight: '700' },
  link: { color: '#007AFF', fontSize: 14 },
  desc: { fontSize: 12, color: '#666', marginTop: 6 },
  metrics: { marginTop: 10 },
  metricLabel: { fontSize: 13, color: '#444', marginBottom: 3 },
  err: { color: '#c0392b', fontSize: 12, marginTop: 4 },
  muted: { color: '#999', textAlign: 'center', marginTop: 40 },
});
