import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, TextInput, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { fetchHoldings, searchStocks, upsertHolding } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { Sheet } from '../components/Sheet';
import { trendColor } from '../lib/colors';
import { currencyMoney, currencySign, marketLabel, quantityUnit, relativeTime } from '../lib/format';
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
  /** 加持仓弹层：搜索标的 → 数量 / 成本，货币交给后端按市场推断 */
  const [addVisible, setAddVisible] = useState(false);
  const [addQuery, setAddQuery] = useState('');
  const [addHits, setAddHits] = useState<{ symbol: string; name?: string; market?: string }[]>([]);
  const [addPick, setAddPick] = useState<{ symbol: string; name?: string; market?: string } | null>(null);
  const [addQty, setAddQty] = useState('');
  const [addCost, setAddCost] = useState('');
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

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

  // 无汇率时后端明确给 null（converted=false），**不能**当 0：否则总资产显示 ¥0，
  // 用户会以为资产清零。用 null 透传到渲染层，显示「—」并给出原因。
  const totalValue = summary?.total_value ?? null;
  const marketValue = summary?.market_value ?? null;
  const cash = summary?.available_cash ?? null;
  const cashPct = summary?.cash_pct ?? null;
  const holdingPct = cashPct == null ? null : Math.max(0, Math.min(100, 100 - cashPct));
  const fx = data?.fx;

  /** 折合金额：null → 「—」 */
  const cny = (v: number | null | undefined, digits = 0) => (v == null ? '—' : `¥${money(v, digits)}`);

  // 后端 weight_pct 目前恒为 0（未计算），这里按持仓市值自己算
  /** 分币种小计（后端已按当天汇率给，缺汇率时 cny 为 null） */
  const buckets = summary?.by_currency ?? [];

  /** 原币市值：优先 market_value_native，老后端没有就退回折合值 */
  const nativeValue = (it: HoldingItem) => it.market_value_native ?? it.market_value;

  /** 非人民币持仓：额外显示折合值，避免误以为是人民币计价 */
  const isForeign = (it: HoldingItem) => String(it.currency ?? 'CNY').toUpperCase() !== 'CNY';

  const weightOf = (it: HoldingItem): number | null => {
    if (marketValue == null || marketValue <= 0) return null;
    const mv = it.market_value;
    if (mv == null) return null;
    return (mv / marketValue) * 100;
  };
  const totalCost = items.reduce((s, it) => s + Number(it.cost ?? 0) * Number(it.quantity ?? 0), 0);
  const totalPnl = items.reduce((s, it) => s + Number(it.pnl_amount ?? 0), 0);
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
  const degraded = Number(data?.quotes_degraded_count ?? 0);

  const analyze = () => {
    setMenuVisible(false);
    const lines = items
      .map((it) => `${it.symbol} ${it.name}：${it.quantity} ${quantityUnit(it.market)}，成本 ${currencyMoney(it.cost, it.currency)}，现价 ${it.quote?.last ?? '—'}，浮盈亏 ${signed(it.pnl_amount)}（${signed(it.pnl_pct)}%）`)
      .join('\n');
    usePrefill.getState().set(
      `这是我的当前持仓，请做一次组合体检：\n${lines}\n\n总资产 ${totalValue == null ? '无当日汇率，未折算' : `¥${money(totalValue)}`}，持仓市值 ${marketValue == null ? '未折算' : `¥${money(marketValue)}`}，可用资金 ${cash == null ? '未知' : `¥${money(cash)}`}，持仓占比 ${holdingPct == null ? '未知' : `${holdingPct.toFixed(1)}%`}。\n请给出：集中度与风险点、每只的处置建议（继续持有/减仓/观察）、以及需要我补充的信息。数字以我给的为准，不要编造。`,
      { page: 'portfolio' }
    );
    navigation.navigate('Main', { screen: 'Chat' });
  };

  const searchTarget = async (q: string) => {
    setAddQuery(q);
    setAddPick(null);
    if (!q.trim()) { setAddHits([]); return; }
    try {
      const hits = await searchStocks(baseURL, token, q.trim());
      setAddHits(hits.slice(0, 12).map((h) => ({ symbol: h.symbol, name: h.name, market: h.market })));
    } catch {
      setAddHits([]);
    }
  };

  const submitAdd = async () => {
    const symbol = String(addPick?.symbol ?? addQuery).trim().toUpperCase();
    const qty = Number(addQty);
    if (!symbol) { setAddError('请先选择标的'); return; }
    if (!Number.isFinite(qty) || qty <= 0) { setAddError('数量要大于 0（币支持小数）'); return; }
    setAddBusy(true);
    setAddError(null);
    try {
      await upsertHolding(baseURL, token, {
        symbol,
        quantity: qty,
        cost: addCost.trim() ? Number(addCost) : undefined,
        // currency 留空由后端按 market 推断（CRYPTO → USDT）
      });
      setAddVisible(false);
      setAddQuery(''); setAddHits([]); setAddPick(null); setAddQty(''); setAddCost('');
      await load();
    } catch (e) {
      setAddError(e instanceof Error ? e.message : String(e));
    } finally {
      setAddBusy(false);
    }
  };

  const renderItem = ({ item }: { item: HoldingItem }) => {
    const pnlPct = Number(item.pnl_pct ?? 0);
    const color = trendColor(pnlPct);
    const weight = weightOf(item);  // null = 无汇率，算不出跨币种权重
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
          {/* 原币市值 + 折合 CNY：加密持仓的 market_value 是折算值，光看 ¥ 会以为按人民币计价 */}
          <Text style={[styles.mv, { color: t.text }]}>
            {currencyMoney(nativeValue(item), item.currency)}
          </Text>
        </View>

        <View style={styles.cardMid}>
          <Text style={[styles.meta, { color: t.sub }]}>
            {marketLabel(item.market)} · {money(item.quantity)} {quantityUnit(item.market)} · 成本{' '}
            {currencyMoney(item.cost, item.currency)}
          </Text>
          {isForeign(item) ? (
            <Text style={[styles.meta, { color: t.sub }]}>
              折合 ¥{money(item.market_value)}
            </Text>
          ) : null}
          <Text style={[styles.meta, { color: t.sub }]}>
            现价 {last != null ? money(last, 2) : '—'}
            {last != null && dayPct !== 0 ? `  ${signed(dayPct)}%` : ''}
            {stale ? '  ⚠️' : ''}
          </Text>
        </View>

        <View style={[styles.barWrap, { backgroundColor: t.sep }]}>
          <View style={[styles.bar, { width: `${Math.min(100, weight ?? 0)}%`, backgroundColor: t.accent }]} />
        </View>

        <View style={styles.cardBot}>
          <Text style={[styles.pnl, { color }]}>
            {signed(item.pnl_amount)} ({signed(pnlPct)}%)
          </Text>
          <Text style={[styles.meta, { color: t.sub }]}>
            权重 {weight == null ? '—' : `${weight.toFixed(1)}%`}
          </Text>
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
            <Text style={[styles.islandValue, { color: t.sub }]}>{cny(totalValue)}</Text>
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
                <Text style={[styles.sumValue, { color: t.text }]}>{cny(totalValue, 2)}</Text>
              </View>
              {totalValue == null ? (
                <Text style={[styles.fxWarn, { color: '#B45309' }]}>
                  无当日汇率，暂不折算 —— 分币种小计照常，折合总额与跨币种权重失效
                </Text>
              ) : null}
              {buckets.length > 1 || (buckets[0] && buckets[0].currency !== 'CNY') ? (
                <View style={[styles.curRow, { borderTopColor: t.sep }]}>
                  {buckets.map((b) => (
                    <Text key={String(b.currency)} style={[styles.curChip, { color: t.sub }]}>
                      {currencySign(b.currency)} {money(b.native)} · {b.count ?? 0} 项
                      {b.cny != null && marketValue ? ` · ${((b.cny / marketValue) * 100).toFixed(1)}%` : ''}
                      {b.cny == null ? '（无汇率）' : ''}
                    </Text>
                  ))}
                </View>
              ) : null}
              <View style={[styles.sumGrid, { borderTopColor: t.sep }]}>
                <Stat label="持仓市值" value={cny(marketValue)} />
                <Stat label="可用资金" value={cny(cash)} />
                <Stat label="持仓占比" value={holdingPct == null ? '—' : `${holdingPct.toFixed(1)}%`} />
                <Stat
                  label={`总盈亏（${items.length} 项）`}
                  value={`${signed(totalPnl)} (${signed(totalPnlPct)}%)`}
                  color={trendColor(totalPnl)}
                />
              </View>
            </View>

            {fx ? (
              <View style={styles.fxRow}>
                {fx.degraded ? (
                  <Text style={[styles.fxWarn, { color: '#B45309' }]}>
                    ⚠ 汇率不可用（{fx.degraded_reason ?? '上游失败'}）—— 分币种小计照常，折合总额与跨币种权重失效
                  </Text>
                ) : (
                  <Text style={[styles.fxText, { color: t.sub }]}>
                    当日汇率 {fx.as_of ?? '—'}
                    {fx.usd_cny != null ? ` · USD/CNY ${fx.usd_cny.toFixed(4)}` : ''}
                    {fx.hkd_cny != null ? ` · HKD/CNY ${fx.hkd_cny.toFixed(4)}` : ''}
                    {fx.usdt_usd != null ? ` · USDT/USD ${fx.usdt_usd.toFixed(4)}` : ''}
                  </Text>
                )}
              </View>
            ) : null}

            {degraded > 0 ? (
              <View style={styles.notice}>
                <Text style={[styles.noticeText, { color: t.sub }]}>
                  ⚠️ {degraded} 个标的的行情降级或过期，数据可能不是最新
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

      <Sheet visible={addVisible} onClose={() => setAddVisible(false)}>
        <Text style={[styles.sheetTitle, { color: t.sub }]}>添加持仓</Text>
        <View style={[styles.searchBox, { borderColor: t.sep }]}>
          <TextInput
            style={[styles.searchInput, { color: t.text }]}
            placeholder="搜索代码或名称，如 600519 / BTC"
            placeholderTextColor={t.sub}
            value={addQuery}
            onChangeText={(v) => void searchTarget(v)}
            autoCapitalize="characters"
            autoCorrect={false}
          />
        </View>
        {addPick ? (
          <Text style={[styles.meta, { color: t.sub }]}>
            已选 {addPick.symbol} {addPick.name ?? ''} {marketLabel(addPick.market)}
          </Text>
        ) : (
          addHits.map((h) => (
            <Pressable
              key={h.symbol}
              style={styles.addRow}
              onPress={() => { setAddPick(h); setAddHits([]); }}
            >
              <Text style={{ color: t.text }}>{h.symbol}</Text>
              <Text style={[styles.meta, { color: t.sub }]}>{h.name ?? ''} {marketLabel(h.market)}</Text>
            </Pressable>
          ))
        )}
        <View style={styles.addForm}>
          <TextInput
            style={[styles.searchBox, styles.addInput, { color: t.text, borderColor: t.sep }]}
            placeholder="数量（币支持小数）"
            placeholderTextColor={t.sub}
            keyboardType="decimal-pad"
            value={addQty}
            onChangeText={setAddQty}
          />
          <TextInput
            style={[styles.searchBox, styles.addInput, { color: t.text, borderColor: t.sep }]}
            placeholder="成本价（可选，原币）"
            placeholderTextColor={t.sub}
            keyboardType="decimal-pad"
            value={addCost}
            onChangeText={setAddCost}
          />
        </View>
        {addError ? <Text style={styles.error}>{addError}</Text> : null}
        <Pressable
          style={[styles.submit, { backgroundColor: t.accent }]}
          onPress={() => void submitAdd()}
          disabled={addBusy}
        >
          {addBusy ? <ActivityIndicator color="#fff" /> : <Text style={styles.submitText}>保存持仓</Text>}
        </Pressable>
      </Sheet>

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
          icon="add-circle-outline"
          label="添加持仓"
          hint="股票或加密资产都能加；加密按原币记录"
          onPress={() => {
            setMenuVisible(false);
            setAddVisible(true);
          }}
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
  searchBox: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8, marginTop: 8 },
  searchInput: { fontSize: 15, padding: 0 },
  addForm: { flexDirection: 'row', gap: 8, marginTop: 10 },
  addRow: { flexDirection: 'row', gap: 8, alignItems: 'baseline', paddingVertical: 8 },
  addInput: { flex: 1, paddingVertical: 8 },
  error: { color: '#d33', fontSize: 12, marginTop: 8 },
  submit: { borderRadius: 10, alignItems: 'center', paddingVertical: 12, marginTop: 12 },
  submitText: { color: '#fff', fontWeight: '600' },
  fxRow: { marginTop: 6 },
  fxText: { fontSize: 11, lineHeight: 16 },
  fxWarn: { fontSize: 11, lineHeight: 16 },
  curRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, paddingTop: 10 },
  curChip: { fontSize: 12, fontVariant: ['tabular-nums'] },
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
