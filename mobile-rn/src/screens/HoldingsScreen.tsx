import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { fetchHoldings } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { trendColor } from '../lib/colors';
import type { RootStackParamList } from '../navigation';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useConnection } from '../store/connection';
import type { HoldingItem, HoldingsResponse } from '../types';
import { useThemedStyles } from '../lib/tokens';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export default function HoldingsScreen() {
  const styles = useThemedStyles(baseStyles);
  const navigation = useNavigation<Nav>();
  const insets = useSafeAreaInsets();
  const { baseURL, token } = useConnection();
  const [data, setData] = useState<HoldingsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchHoldings(baseURL, token));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const unsub = navigation.addListener('focus', () => void load());
    return unsub;
  }, [navigation, load]);

  const summary = data?.summary;
  const items = data?.items ?? [];

  const renderItem = ({ item }: { item: HoldingItem }) => {
    const pnl = item.pnl_pct ?? 0;
    const color = trendColor(pnl);
    return (
      <Pressable style={styles.row} onPress={() => navigation.navigate('StockDetail', { symbol: item.symbol ?? '', name: item.name })}>
        <View style={styles.main}>
          <Text style={styles.symbol}>{item.symbol}</Text>
          <Text style={styles.name} numberOfLines={1}>
            {item.name}
          </Text>
        </View>
        <View style={styles.col}>
          <Text style={styles.val}>{item.market_value?.toFixed(0) ?? '—'}</Text>
          <Text style={styles.sub}>市值</Text>
        </View>
        <View style={[styles.col, { alignItems: 'flex-end' }]}>
          <Text style={[styles.val, { color }]}>
            {pnl >= 0 ? '+' : ''}
            {pnl.toFixed(2)}%
          </Text>
          <Text style={styles.sub}>{item.quantity ?? 0} 股</Text>
        </View>
      </Pressable>
    );
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <Text style={styles.title}>持仓</Text>
      {summary && (
        <View style={styles.summary}>
          <View style={styles.sumItem}>
            <Text style={styles.sumVal}>{summary.total_value?.toFixed(0) ?? '—'}</Text>
            <Text style={styles.sumLabel}>总市值</Text>
          </View>
          <View style={styles.sumItem}>
            <Text style={styles.sumVal}>{summary.available_cash?.toFixed(0) ?? '—'}</Text>
            <Text style={styles.sumLabel}>可用资金</Text>
          </View>
          <View style={styles.sumItem}>
            <Text style={styles.sumVal}>{summary.positions ?? 0}</Text>
            <Text style={styles.sumLabel}>持仓数</Text>
          </View>
          {data?.demo ? <Text style={styles.demo}>演示数据</Text> : null}
        </View>
      )}
      <FlatList
        data={items}
        keyExtractor={(i, idx) => i.symbol ?? String(idx)}
        renderItem={renderItem}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} />}
        ListEmptyComponent={
          error ? (
            <ErrorState message={error} onRetry={() => void load()} />
          ) : loading ? (
            <ActivityIndicator style={{ marginTop: 40 }} />
          ) : (
            <Text style={styles.muted}>暂无持仓</Text>
          )
        }
      />
    </View>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  title: { fontSize: 20, fontWeight: '700', paddingHorizontal: 16, paddingVertical: 12 },
  summary: { flexDirection: 'row', padding: 16, backgroundColor: '#f6f8fa', marginBottom: 8 },
  sumItem: { flex: 1, alignItems: 'center' },
  sumVal: { fontSize: 16, fontWeight: '700' },
  sumLabel: { fontSize: 12, color: '#999', marginTop: 4 },
  demo: { fontSize: 11, color: '#f59e0b', alignSelf: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#eee' },
  main: { flex: 1 },
  symbol: { fontSize: 16, fontWeight: '600' },
  name: { fontSize: 12, color: '#999', marginTop: 2 },
  col: { alignItems: 'flex-end', marginLeft: 12, minWidth: 72 },
  val: { fontSize: 14, fontWeight: '600' },
  sub: { fontSize: 11, color: '#999', marginTop: 2 },
  muted: { color: '#999', textAlign: 'center', marginTop: 40 },
});
