import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { fetchHoldings } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { Sheet } from '../components/Sheet';
import { trendColor } from '../lib/colors';
import { relativeTime } from '../lib/format';
import { useThemedStyles, useTokens } from '../lib/tokens';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import { usePrefill } from '../store/prefill';
import type { HoldingItem, HoldingsResponse } from '../types';

type Nav = NativeStackNavigationProp<RootStackParamList>;

function money(v: unknown, digits = 0): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signed(v: unknown, digits = 2): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}`;
}

export default function HoldingsScreen() {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  const insets = useSafeAreaInsets();
  const navigation = useNavigation<Nav>();
  const { baseURL, token } = useConnection();

  const [data, setData] = useState<HoldingsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menuVisible, setMenuVisible] = useState(false);

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

  const totalValue = Number(summary?.total_value ?? 0);
  const marketValue = Number(summary?.market_value ?? 0);
  const cash = Number(summary?.available_cash ?? 0);
  const cashPct = Number(summary?.cash_pct ?? 0);
  const holdingPct = Math.max(0, Math.min(100, 100 - cashPct));

  // 后端 weight_pct 目前恒为 0（未计算），这里按持仓市值自己算
  const weightOf = (it: HoldingItem) => {
    const mv = Number(it.market_value ?? 0);
    return marketValue > 0 ? (mv / marketValue) * 100 : 0;
  };
  const totalCost = items.reduce((s, it) => s + Number(it.cost ?? 0) * Number(it.quantity ?? 0), 0);
  const totalPnl = items.reduce((s, it) => s + Number(it.pnl_amount ?? 0), 0);
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
  const degraded = Number(data?.quotes_degraded_count ?? 0);

  const analyze = () => {
    setMenuVisible(false);
    const lines = items
      .map((it) => `${it.symbol} ${it.name}：${it.quantity} 股，成本 ${it.cost}，现价 ${it.quote?.last ?? '—'}，浮盈亏 ${signed(it.pnl_amount)}（${signed(it.pnl_pct)}%）`)
      .join('\n');
    usePrefill.getState().set(
      `这是我的当前持仓，请做一次组合体检：\n${lines}\n\n总资产 ${money(totalValue)}，持仓市值 ${money(marketValue)}，可用资金 ${money(cash)}，持仓占比 ${holdingPct.toFixed(1)}%。\n请给出：集中度与风险点、每只的处置建议（继续持有/减仓/观察）、以及需要我补充的信息。数字以我给的为准，不要编造。`,
      { page: 'portfolio' }
    );
    navigation.navigate('Main', { screen: 'Chat' });
  };

  const renderItem = ({ item }: { item: HoldingItem }) => {
    const pnlPct = Number(item.pnl_pct ?? 0);
    const color = trendColor(pnlPct);
    const weight = weightOf(item);
    const last = item.quote?.last;
    const dayPct = Number(item.quote?.change_pct ?? 0);
    const stale = !!item.quote?.stale || !!item.quote?.degraded;

    return (
      <Pressable
        style={[styles.card, { backgroundColor: t.groupBg }]}
        onPress={() => navigation.navigate('StockDetail', { symbol: item.symbol ?? '', name: item.name })}
      >
        <View style={styles.cardTop}>
          <Text style={[styles.symbol, { color: t.text }]}>{item.symbol}</Text>
          <Text style={[styles.name, { color: t.sub }]} numberOfLines={1}>
            {item.name}
          </Text>
          <Text style={[styles.mv, { color: t.text }]}>¥{money(item.market_value)}</Text>
        </View>

        <View style={styles.cardMid}>
          <Text style={[styles.meta, { color: t.sub }]}>
            {money(item.quantity)} 股 · 成本 {money(item.cost, 2)}
          </Text>
          <Text style={[styles.meta, { color: t.sub }]}>
            现价 {last != null ? money(last, 2) : '—'}
            {last != null && dayPct !== 0 ? `  ${signed(dayPct)}%` : ''}
            {stale ? '  ⚠️' : ''}
          </Text>
        </View>

        <View style={[styles.barWrap, { backgroundColor: t.sep }]}>
          <View style={[styles.bar, { width: `${Math.min(100, weight)}%`, backgroundColor: t.accent }]} />
        </View>

        <View style={styles.cardBot}>
          <Text style={[styles.pnl, { color }]}>
            {signed(item.pnl_amount)} ({signed(pnlPct)}%)
          </Text>
          <Text style={[styles.meta, { color: t.sub }]}>权重 {weight.toFixed(1)}%</Text>
        </View>
      </Pressable>
    );
  };

  return (
    <View style={[styles.container, { backgroundColor: t.pageBg }]}>
      {/* 浅灰岛头部 */}
      <View style={[styles.headerWrap, { paddingTop: insets.top + 8 }]}>
        <View style={[styles.island, { backgroundColor: t.cardAlt }]}>
          <Text style={[styles.islandTitle, { color: t.text }]}>持仓</Text>
          {items.length > 0 ? (
            <Text style={[styles.islandValue, { color: t.sub }]}>¥{money(totalValue)}</Text>
          ) : null}
          {data?.demo ? <Text style={[styles.demoTag, { color: t.sub }]}>演示</Text> : null}
          <View style={styles.spacer} />
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

      <FlatList
        data={items}
        keyExtractor={(it) => it.symbol ?? String(Math.random())}
        contentContainerStyle={styles.listContent}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} tintColor={t.accent} />}
        ListHeaderComponent={
          <View>
            {/* 资产概览 */}
            <View style={[styles.summary, { backgroundColor: t.groupBg }]}>
              <View style={styles.sumTop}>
                <Text style={[styles.sumLabel, { color: t.sub }]}>总资产</Text>
                <Text style={[styles.sumValue, { color: t.text }]}>¥{money(totalValue, 2)}</Text>
              </View>
              <View style={[styles.sumGrid, { borderTopColor: t.sep }]}>
                <Stat label="持仓市值" value={`¥${money(marketValue)}`} />
                <Stat label="可用资金" value={`¥${money(cash)}`} />
                <Stat label="持仓占比" value={`${holdingPct.toFixed(1)}%`} />
                <Stat
                  label={`总盈亏（${items.length} 只）`}
                  value={`${signed(totalPnl)} (${signed(totalPnlPct)}%)`}
                  color={trendColor(totalPnl)}
                />
              </View>
            </View>

            {degraded > 0 ? (
              <View style={styles.notice}>
                <Text style={[styles.noticeText, { color: t.sub }]}>
                  ⚠️ {degraded} 只标的的行情降级或过期，数据可能不是最新
                </Text>
              </View>
            ) : null}

            <Text style={[styles.sectionTitle, { color: t.sub }]}>持仓明细</Text>
          </View>
        }
        ListEmptyComponent={
          loading ? (
            <ActivityIndicator style={{ marginTop: 40 }} />
          ) : (
            <View style={styles.empty}>
              <Text style={[styles.emptyText, { color: t.sub }]}>暂无持仓</Text>
              <Text style={[styles.emptyHint, { color: t.sub }]}>
                可以在对话里让 Agent 记录一笔持仓，或直接在服务端配置。
              </Text>
            </View>
          )
        }
        renderItem={renderItem}
      />

      <Sheet visible={menuVisible} onClose={() => setMenuVisible(false)}>
        <Text style={[styles.sheetTitle, { color: t.sub }]}>持仓</Text>
        <MenuItem
          icon="sparkles-outline"
          label="在对话中做组合体检"
          hint="带上当前持仓与资产数字提问"
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
          icon="server-outline"
          label="行情数据源"
          onPress={() => {
            setMenuVisible(false);
            navigation.navigate('DataSources');
          }}
        />
      </Sheet>
    </View>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  return (
    <View style={styles.stat}>
      <Text style={[styles.statLabel, { color: t.sub }]}>{label}</Text>
      <Text style={[styles.statValue, { color: color ?? t.text }]}>{value}</Text>
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
  islandValue: { fontSize: 13 },
  demoTag: { fontSize: 11, borderWidth: StyleSheet.hairlineWidth, borderColor: '#8E8E93', borderRadius: 6, paddingHorizontal: 5, paddingVertical: 1 },
  spacer: { flex: 1 },
  circleBtn: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  listContent: { paddingBottom: 30 },

  summary: { marginHorizontal: 16, borderRadius: 14, padding: 16, marginBottom: 14 },
  sumTop: { alignItems: 'flex-start' },
  sumLabel: { fontSize: 12.5 },
  sumValue: { fontSize: 28, fontWeight: '700', marginTop: 4, letterSpacing: -0.5 },
  sumGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    borderTopWidth: StyleSheet.hairlineWidth,
    marginTop: 14,
    paddingTop: 12,
  },
  stat: { width: '50%', paddingVertical: 6 },
  statLabel: { fontSize: 11.5 },
  statValue: { fontSize: 15, fontWeight: '600', marginTop: 3 },

  notice: { marginHorizontal: 16, marginBottom: 12 },
  noticeText: { fontSize: 11.5, lineHeight: 16 },
  sectionTitle: { fontSize: 12.5, marginLeft: 30, marginBottom: 8, letterSpacing: 0.3 },

  card: { marginHorizontal: 16, marginBottom: 10, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12 },
  cardTop: { flexDirection: 'row', alignItems: 'baseline', gap: 7 },
  symbol: { fontSize: 15, fontWeight: '700' },
  name: { fontSize: 12.5, flex: 1 },
  mv: { fontSize: 15, fontWeight: '600' },
  cardMid: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 7, gap: 10 },
  meta: { fontSize: 11.5 },
  barWrap: { height: 4, borderRadius: 2, marginTop: 10, overflow: 'hidden' },
  bar: { height: 4, borderRadius: 2 },
  cardBot: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 8 },
  pnl: { fontSize: 13, fontWeight: '600' },

  empty: { alignItems: 'center', paddingVertical: 50, paddingHorizontal: 32 },
  emptyText: { fontSize: 14 },
  emptyHint: { fontSize: 12, marginTop: 6, textAlign: 'center', lineHeight: 18 },

  sheetTitle: { fontSize: 12.5, textAlign: 'center', paddingTop: 8, paddingBottom: 10 },
  menuItem: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 22, paddingVertical: 14 },
  menuDisabled: { opacity: 0.4 },
  menuText: { flex: 1 },
  menuLabel: { fontSize: 15 },
  menuHint: { fontSize: 11.5, marginTop: 2 },
});
