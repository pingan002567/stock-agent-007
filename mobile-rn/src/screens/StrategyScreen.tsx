import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { fetchLatestBacktest, fetchStrategies, runBacktest } from '../api/client';
import { useConnection } from '../store/connection';
import type { BacktestRun, StrategyItem } from '../types';

export default function StrategyScreen() {
  const { baseURL, token } = useConnection();
  const [strategies, setStrategies] = useState<StrategyItem[]>([]);
  const [backtests, setBacktests] = useState<Record<string, BacktestRun | null>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
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
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (id: string) => {
    setRunning(id);
    try {
      const bt = await runBacktest(baseURL, token, id);
      setBacktests((b) => ({ ...b, [id]: bt }));
    } catch {
      /* ignore */
    } finally {
      setRunning(null);
    }
  };

  const renderMetrics = (bt?: BacktestRun | null) => {
    if (!bt) return <Text style={styles.muted}>暂无回测</Text>;
    const m = bt.metrics ?? {};
    return (
      <View style={styles.metrics}>
        <Text style={styles.metricLabel}>总收益 {fmtPct(m.total_return_pct)}</Text>
        <Text style={styles.metricLabel}>年化 {fmtPct(m.annualized_return_pct)}</Text>
        <Text style={styles.metricLabel}>最大回撤 {fmtPct(m.max_drawdown_pct)}</Text>
        <Text style={styles.metricLabel}>夏普 {m.sharpe_ratio?.toFixed(2) ?? '—'}</Text>
        <Text style={styles.metricLabel}>胜率 {fmtPct(m.win_rate)}</Text>
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
        ListEmptyComponent={loading ? <ActivityIndicator style={{ marginTop: 40 }} /> : <Text style={styles.muted}>暂无策略</Text>}
        contentContainerStyle={{ padding: 16 }}
      />
    </View>
  );
}

function fmtPct(v?: number): string {
  return v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
}

const styles = StyleSheet.create({
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
