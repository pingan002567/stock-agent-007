import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, TextInput, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { addWatchlistItem, deleteWatchlistItem, fetchWatchlist, searchStocks } from '../api/client';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import type { StockSearchHit, WatchlistItem } from '../types';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export default function WatchlistScreen() {
  const navigation = useNavigation<Nav>();
  const { baseURL, token } = useConnection();
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<StockSearchHit[]>([]);
  const [searching, setSearching] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await fetchWatchlist(baseURL, token));
    } catch {
      /* ignore */
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

  const search = async (q: string) => {
    setQuery(q);
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      setResults(await searchStocks(baseURL, token, q.trim()));
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  const add = async (symbol: string, name: string) => {
    try {
      await addWatchlistItem(baseURL, token, symbol, name);
      setShowAdd(false);
      setQuery('');
      setResults([]);
      await load();
    } catch {
      /* ignore */
    }
  };

  const del = async (symbol: string) => {
    try {
      await deleteWatchlistItem(baseURL, token, symbol);
      await load();
    } catch {
      /* ignore */
    }
  };

  const renderItem = ({ item }: { item: WatchlistItem }) => {
    const pct = item.price?.change_pct ?? 0;
    const up = pct >= 0;
    const color = up ? '#e53935' : '#26a69a';
    return (
      <Pressable style={styles.row} onPress={() => navigation.navigate('StockDetail', { symbol: item.symbol, name: item.name })}>
        <View style={styles.main}>
          <Text style={styles.symbol}>{item.symbol}</Text>
          <Text style={styles.name} numberOfLines={1}>
            {item.name}
          </Text>
        </View>
        <View style={styles.right}>
          <Text style={[styles.price, { color }]}>
            {item.price?.last != null ? item.price.last.toFixed(2) : '—'}
          </Text>
          <Text style={[styles.change, { color }]}>
            {up ? '+' : ''}
            {pct.toFixed(2)}%
          </Text>
        </View>
        <Pressable onPress={() => void del(item.symbol)} hitSlop={10}>
          <Text style={styles.del}>✕</Text>
        </Pressable>
      </Pressable>
    );
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>自选</Text>
        <Pressable onPress={() => setShowAdd((v) => !v)}>
          <Text style={styles.addBtn}>{showAdd ? '关闭' : '＋ 添加'}</Text>
        </Pressable>
      </View>

      {showAdd && (
        <View style={styles.addPanel}>
          <TextInput style={styles.input} placeholder="搜索股票代码或名称" value={query} onChangeText={(t) => void search(t)} autoCapitalize="none" />
          {searching ? (
            <ActivityIndicator style={{ marginTop: 12 }} />
          ) : (
            <FlatList
              data={results}
              keyExtractor={(r) => r.symbol}
              style={{ maxHeight: 300 }}
              renderItem={({ item }) => (
                <Pressable style={styles.resultRow} onPress={() => void add(item.symbol, item.name ?? item.symbol)}>
                  <Text style={styles.resultSymbol}>{item.symbol}</Text>
                  <Text style={styles.resultName}>{item.name}</Text>
                  <Text style={styles.resultAdd}>＋</Text>
                </Pressable>
              )}
              ListEmptyComponent={query.trim() ? <Text style={styles.muted}>无结果</Text> : null}
            />
          )}
        </View>
      )}

      <FlatList
        data={items}
        keyExtractor={(i) => i.symbol}
        renderItem={renderItem}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} />}
        ListEmptyComponent={loading ? <ActivityIndicator style={{ marginTop: 40 }} /> : <Text style={styles.muted}>暂无自选</Text>}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12 },
  title: { fontSize: 20, fontWeight: '700' },
  addBtn: { color: '#007AFF', fontSize: 15 },
  addPanel: { paddingHorizontal: 16, paddingBottom: 8 },
  input: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 10, fontSize: 14 },
  resultRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#eee' },
  resultSymbol: { width: 100, fontWeight: '600', fontSize: 14 },
  resultName: { flex: 1, color: '#666', fontSize: 13 },
  resultAdd: { color: '#007AFF', fontSize: 16 },
  row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#eee' },
  main: { flex: 1 },
  symbol: { fontSize: 16, fontWeight: '600' },
  name: { fontSize: 12, color: '#999', marginTop: 2 },
  right: { alignItems: 'flex-end', marginRight: 12 },
  price: { fontSize: 15, fontWeight: '600' },
  change: { fontSize: 12, marginTop: 2 },
  del: { color: '#bbb', fontSize: 14, padding: 4 },
  muted: { color: '#999', textAlign: 'center', marginTop: 40 },
});
