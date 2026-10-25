import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Swipeable } from 'react-native-gesture-handler';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { addWatchlistItem, deleteWatchlistItem, fetchWatchlist, searchStocks } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { Sheet } from '../components/Sheet';
import { trendColor } from '../lib/colors';
import { marketLabel } from '../lib/format';
import { useThemedStyles, useTokens } from '../lib/tokens';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import { usePrefill } from '../store/prefill';
import type { StockSearchHit, WatchlistItem } from '../types';

type Nav = NativeStackNavigationProp<RootStackParamList>;

const DEFAULT_GROUP = '默认';

function money(v: unknown, digits = 2): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signed(v: unknown, digits = 2): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}`;
}

export default function WatchlistScreen() {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  const insets = useSafeAreaInsets();
  const navigation = useNavigation<Nav>();
  const { baseURL, token } = useConnection();

  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menuVisible, setMenuVisible] = useState(false);
  const [addVisible, setAddVisible] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<StockSearchHit[]>([]);
  const [searching, setSearching] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await fetchWatchlist(baseURL, token));
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

  // 后端把降级统计放在首条的 _mode_b 里
  const degradedCount = useMemo(() => {
    const meta = items[0]?._mode_b as { quotes_degraded_count?: number } | undefined;
    return Number(meta?.quotes_degraded_count ?? 0);
  }, [items]);

  const sections = useMemo(() => {
    const map = new Map<string, WatchlistItem[]>();
    for (const it of items) {
      const g = (it.group ?? '').trim() || DEFAULT_GROUP;
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(it);
    }
    return Array.from(map.entries());
  }, [items]);

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
      setAddVisible(false);
      setQuery('');
      setResults([]);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const confirmDelete = (item: WatchlistItem) => {
    Alert.alert('移出自选', `确定把 ${item.symbol}${item.name ? ` ${item.name}` : ''} 移出自选？`, [
      { text: '取消', style: 'cancel' },
      {
        text: '移出',
        style: 'destructive',
        onPress: () => {
          void (async () => {
            try {
              await deleteWatchlistItem(baseURL, token, item.symbol);
              await load();
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          })();
        },
      },
    ]);
  };

  const analyze = () => {
    setMenuVisible(false);
    const lines = items
      .map((it) => `${it.symbol} ${it.name ?? ''}：现价 ${it.price?.last ?? '—'}，当日 ${signed(it.price?.change_pct)}%`)
      .join('\n');
    usePrefill.getState().set(
      `这是我的自选股，请帮我做一次初筛：\n${lines}\n\n请给出：值得优先研究的 3 只及理由、各自的关注点与风险、以及需要我补充的信息。数字以我给的为准，不要编造。`,
      { page: 'watchlist' }
    );
    navigation.navigate('Main', { screen: 'Chat' });
  };

  const renderRow = (item: WatchlistItem, isLast: boolean) => {
    const pct = Number(item.price?.change_pct ?? 0);
    const color = trendColor(pct);
    const last = item.price?.last;
    const degraded = !!item.quote_degraded || !!item.price?.degraded;
    const stale = !!item.price?.stale;

    return (
      <Swipeable
        key={item.symbol}
        overshootRight={false}
        renderRightActions={() => (
          <Pressable style={styles.swipeAction} onPress={() => confirmDelete(item)}>
            <Text style={styles.swipeActionText}>移出</Text>
          </Pressable>
        )}
      >
        <Pressable
          style={[styles.card, { backgroundColor: t.groupBg }, isLast && styles.cardLast]}
          onPress={() => navigation.navigate('StockDetail', { symbol: item.symbol, name: item.name })}
        >
          <View style={styles.cardTop}>
            <Text style={[styles.symbol, { color: t.text }]}>{item.symbol}</Text>
            <Text style={[styles.name, { color: t.sub }]} numberOfLines={1}>
              {item.name}
            </Text>
            {item.monitored ? (
              <View style={[styles.tag, { borderColor: t.accent }]}>
                <Text style={[styles.tagText, { color: t.accent }]}>盯盘</Text>
              </View>
            ) : null}
            <Text style={[styles.price, { color: t.text }]}>{last != null ? money(last) : '—'}</Text>
          </View>

          <View style={styles.cardBot}>
            {item.market ? (
              <Text style={[styles.meta, { color: t.sub }]}>{marketLabel(item.market)}</Text>
            ) : null}
            {last != null ? (
              <Text style={[styles.change, { color }]}>{signed(pct)}%</Text>
            ) : (
              <Text style={[styles.meta, { color: t.sub }]}>暂无行情</Text>
            )}
            {degraded ? <Text style={[styles.meta, { color: t.sub }]}>⚠️ 降级</Text> : null}
            {!degraded && stale ? <Text style={[styles.meta, { color: t.sub }]}>缓存</Text> : null}
            <View style={styles.spacer} />
            <Ionicons name="chevron-forward" size={16} color="#C7C7CC" />
          </View>
        </Pressable>
      </Swipeable>
    );
  };

  return (
    <View style={[styles.container, { backgroundColor: t.pageBg }]}>
      {/* 浅灰岛头部（与对话/盯盘/持仓一致） */}
      <View style={[styles.headerWrap, { paddingTop: insets.top + 8 }]}>
        <View style={[styles.island, { backgroundColor: t.cardAlt }]}>
          <Text style={[styles.islandTitle, { color: t.text }]}>自选</Text>
          {items.length > 0 ? <Text style={[styles.islandCount, { color: t.sub }]}>{items.length} 只</Text> : null}
          <View style={styles.spacer} />
          <Pressable
            style={[styles.circleBtn, { backgroundColor: t.groupBg }]}
            onPress={() => setAddVisible(true)}
            hitSlop={4}
          >
            <Ionicons name="add" size={20} color={t.text} />
          </Pressable>
          <Pressable
            style={[styles.circleBtn, { backgroundColor: t.groupBg }]}
            onPress={() => setMenuVisible(true)}
            hitSlop={4}
          >
            <Ionicons name="ellipsis-vertical" size={18} color={t.text} />
          </Pressable>
        </View>
      </View>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} tintColor={t.accent} />}
      >
        {degradedCount > 0 ? (
          <Text style={[styles.notice, { color: t.sub }]}>
            ⚠️ {degradedCount}/{items.length} 只行情降级或过期，显示的是缓存值
          </Text>
        ) : null}

        {loading && items.length === 0 ? (
          <ActivityIndicator style={{ marginTop: 60 }} />
        ) : items.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="star-outline" size={40} color={t.sub} />
            <Text style={[styles.emptyText, { color: t.text }]}>还没有自选股</Text>
            <Text style={[styles.emptyHint, { color: t.sub }]}>
              点右上角「＋」搜索代码或名称添加；也可以在对话里让 Agent 帮你挑几只。
            </Text>
            <Pressable style={[styles.emptyBtn, { backgroundColor: t.accent }]} onPress={() => setAddVisible(true)}>
              <Text style={styles.emptyBtnText}>添加自选</Text>
            </Pressable>
          </View>
        ) : (
          sections.map(([group, list]) => (
            <View key={group} style={styles.section}>
              {sections.length > 1 || group !== DEFAULT_GROUP ? (
                <Text style={[styles.sectionTitle, { color: t.sub }]}>
                  {group} · {list.length}
                </Text>
              ) : null}
              <View style={[styles.groupBody, { backgroundColor: t.groupBg }]}>
                {list.map((it, i) => renderRow(it, i === list.length - 1))}
              </View>
            </View>
          ))
        )}
      </ScrollView>

      {/* ⋮ 更多 */}
      <Sheet visible={menuVisible} onClose={() => setMenuVisible(false)}>
        <Text style={[styles.sheetTitle, { color: t.sub }]}>自选</Text>
        <MenuItem
          icon="add-circle-outline"
          label="添加自选"
          onPress={() => {
            setMenuVisible(false);
            setAddVisible(true);
          }}
        />
        <MenuItem
          icon="sparkles-outline"
          label="在对话中分析自选"
          hint={items.length ? `带上 ${items.length} 只的现价与涨跌` : '先添加标的'}
          disabled={items.length === 0}
          onPress={analyze}
        />
        <MenuItem
          icon="refresh-outline"
          label="刷新行情"
          hint={loading ? '刷新中…' : undefined}
          disabled={loading}
          onPress={() => {
            setMenuVisible(false);
            void load();
          }}
        />
        <MenuItem
          icon="pulse-outline"
          label="去盯盘"
          hint="为自选设置触发条件"
          onPress={() => {
            setMenuVisible(false);
            navigation.navigate('Main', { screen: 'Monitor' });
          }}
        />
      </Sheet>

      {/* 添加标的 */}
      <Sheet visible={addVisible} onClose={() => setAddVisible(false)}>
        <Text style={[styles.sheetTitle, { color: t.sub }]}>添加自选</Text>
        <View style={styles.addForm}>
          <View style={[styles.searchBox, { borderColor: t.sep }]}>
            <Ionicons name="search" size={17} color={t.sub} />
            <TextInput
              style={[styles.searchInput, { color: t.text }]}
              placeholder="搜索代码或名称，如 600519 / 茅台"
              placeholderTextColor={t.sub}
              value={query}
              onChangeText={(v) => void search(v)}
              autoCapitalize="none"
              autoCorrect={false}
              autoFocus
            />
          </View>

          {searching ? <ActivityIndicator style={{ marginTop: 16 }} /> : null}

          {!searching && query.trim() && results.length === 0 ? (
            <Text style={[styles.noResult, { color: t.sub }]}>没有匹配的标的</Text>
          ) : null}

          {results.slice(0, 20).map((r) => {
            const already = items.some((x) => x.symbol === r.symbol);
            return (
              <Pressable
                key={r.symbol}
                style={[styles.resultRow, { borderTopColor: t.sep }]}
                onPress={() => (already ? undefined : void add(r.symbol, r.name ?? r.symbol))}
                disabled={already}
              >
                <View style={styles.resultText}>
                  <Text style={[styles.resultSymbol, { color: t.text }]}>{r.symbol}</Text>
                  <Text style={[styles.resultName, { color: t.sub }]} numberOfLines={1}>
                    {r.name}
                  </Text>
                </View>
                {already ? (
                  <Text style={[styles.resultAdded, { color: t.sub }]}>已在自选</Text>
                ) : (
                  <Ionicons name="add-circle" size={22} color={t.accent} />
                )}
              </Pressable>
            );
          })}
        </View>
      </Sheet>
    </View>
  );
}

function MenuItem({
  icon,
  label,
  hint,
  onPress,
  disabled,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  hint?: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  return (
    <Pressable style={[styles.menuItem, disabled && styles.menuDisabled]} onPress={onPress} disabled={disabled}>
      <Ionicons name={icon} size={20} color={t.text} />
      <View style={styles.menuText}>
        <Text style={[styles.menuLabel, { color: t.text }]}>{label}</Text>
        {hint ? <Text style={[styles.menuHint, { color: t.sub }]}>{hint}</Text> : null}
      </View>
    </Pressable>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1 },
  headerWrap: { paddingHorizontal: 10, paddingBottom: 8 },
  island: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderRadius: 26,
    paddingHorizontal: 14,
    paddingVertical: 6,
    minHeight: 50,
  },
  islandTitle: { fontSize: 17, fontWeight: '700' },
  islandCount: { fontSize: 13 },
  spacer: { flex: 1 },
  circleBtn: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  content: { paddingBottom: 30 },
  notice: { fontSize: 11.5, marginHorizontal: 16, marginBottom: 10, lineHeight: 16 },

  section: { marginBottom: 20 },
  sectionTitle: { fontSize: 12.5, marginLeft: 30, marginBottom: 7, letterSpacing: 0.3 },
  groupBody: { marginHorizontal: 16, borderRadius: 12, overflow: 'hidden' },

  card: { paddingHorizontal: 14, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#e5e5ea' },
  cardLast: { borderBottomWidth: 0 },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 7 },
  symbol: { fontSize: 15, fontWeight: '700' },
  name: { fontSize: 12.5, flex: 1 },
  tag: { borderWidth: StyleSheet.hairlineWidth, borderRadius: 6, paddingHorizontal: 5, paddingVertical: 1 },
  tagText: { fontSize: 10 },
  price: { fontSize: 15, fontWeight: '600' },
  cardBot: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 6 },
  meta: { fontSize: 11.5 },
  change: { fontSize: 12.5, fontWeight: '600' },
  swipeAction: { backgroundColor: '#FF3B30', justifyContent: 'center', paddingHorizontal: 22 },
  swipeActionText: { color: '#fff', fontWeight: '700' },

  empty: { alignItems: 'center', paddingTop: 70, paddingHorizontal: 40, gap: 10 },
  emptyText: { fontSize: 15, fontWeight: '600' },
  emptyHint: { fontSize: 12.5, textAlign: 'center', lineHeight: 19 },
  emptyBtn: { marginTop: 10, borderRadius: 12, paddingHorizontal: 28, paddingVertical: 12 },
  emptyBtnText: { color: '#fff', fontWeight: '600', fontSize: 14.5 },

  sheetTitle: { fontSize: 12.5, textAlign: 'center', paddingTop: 8, paddingBottom: 10 },
  menuItem: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 22, paddingVertical: 14 },
  menuDisabled: { opacity: 0.4 },
  menuText: { flex: 1 },
  menuLabel: { fontSize: 15 },
  menuHint: { fontSize: 11.5, marginTop: 2 },

  addForm: { paddingHorizontal: 16, paddingBottom: 10 },
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  searchInput: { flex: 1, fontSize: 15, padding: 0 },
  noResult: { fontSize: 12.5, textAlign: 'center', marginTop: 18 },
  resultRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  resultText: { flex: 1 },
  resultSymbol: { fontSize: 14.5, fontWeight: '600' },
  resultName: { fontSize: 12, marginTop: 2 },
  resultAdded: { fontSize: 12 },
});
