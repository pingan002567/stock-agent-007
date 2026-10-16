import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { fetchReports } from '../api/client';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import type { ReportSummary } from '../types';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export default function ReportsScreen() {
  const navigation = useNavigation<Nav>();
  const { baseURL, token } = useConnection();
  const [items, setItems] = useState<ReportSummary[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetchReports(baseURL, token, 1, 20);
      setItems(r.items);
      setTotal(r.total);
      setPage(1);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const more = async () => {
    if (loadingMore || items.length >= total) return;
    setLoadingMore(true);
    try {
      const r = await fetchReports(baseURL, token, page + 1, 20);
      setItems((prev) => [...prev, ...r.items]);
      setPage((p) => p + 1);
    } catch {
      /* ignore */
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <FlatList
      style={styles.container}
      data={items}
      keyExtractor={(r) => r.report_id}
      contentContainerStyle={{ padding: 16 }}
      renderItem={({ item }) => (
        <Pressable style={styles.card} onPress={() => navigation.navigate('ReportDetail', { reportId: item.report_id })}>
          <Text style={styles.title}>{item.title}</Text>
          <View style={styles.metaRow}>
            {item.symbol ? <Text style={styles.symbol}>{item.symbol}</Text> : null}
            {item.report_type ? <Text style={styles.type}>{item.report_type}</Text> : null}
            <Text style={styles.date}>{String(item.generated_at ?? '').slice(0, 10)}</Text>
          </View>
          {item.conclusion ? <Text style={styles.conclusion} numberOfLines={2}>{item.conclusion}</Text> : null}
        </Pressable>
      )}
      ListEmptyComponent={loading ? <ActivityIndicator style={{ marginTop: 40 }} /> : <Text style={styles.muted}>暂无报告</Text>}
      onEndReached={() => void more()}
      onEndReachedThreshold={0.3}
      ListFooterComponent={loadingMore ? <ActivityIndicator style={{ marginVertical: 16 }} /> : null}
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  card: { backgroundColor: '#f6f8fa', borderRadius: 10, padding: 14, marginBottom: 12 },
  title: { fontSize: 15, fontWeight: '700' },
  metaRow: { flexDirection: 'row', gap: 8, marginTop: 6 },
  symbol: { fontSize: 12, color: '#007AFF', fontWeight: '600' },
  type: { fontSize: 12, color: '#f59e0b' },
  date: { fontSize: 12, color: '#999' },
  conclusion: { fontSize: 13, color: '#555', marginTop: 8, lineHeight: 19 },
  muted: { color: '#999', textAlign: 'center', marginTop: 40 },
});
