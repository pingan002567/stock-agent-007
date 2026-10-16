import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Modal, Pressable, RefreshControl, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { Swipeable } from 'react-native-gesture-handler';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  deleteMonitorRule,
  evaluateMonitorOnce,
  fetchMonitorEvents,
  fetchMonitorRules,
  fetchMonitorStatus,
  pauseMonitor,
  startMonitor,
  upsertMonitorRule,
} from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { severityColor } from '../lib/colors';
import { relativeTime } from '../lib/format';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import { useMonitorUnread } from '../store/monitorUnread';
import type { MonitorEvent, MonitorRule, MonitorStatus } from '../types';
import { stashMonitorEvent } from './MonitorEventDetailScreen';
import { useThemedStyles } from '../lib/tokens';

const PAGE_SIZE = 30;

type Nav = NativeStackNavigationProp<RootStackParamList>;

export default function MonitorScreen() {
  const styles = useThemedStyles(baseStyles);
  const insets = useSafeAreaInsets();
  const navigation = useNavigation<Nav>();
  const { baseURL, token } = useConnection();

  const [status, setStatus] = useState<MonitorStatus | null>(null);
  const [rules, setRules] = useState<MonitorRule[]>([]);
  const [events, setEvents] = useState<MonitorEvent[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [sym, setSym] = useState('');
  const [threshold, setThreshold] = useState('3');
  const [severity, setSeverity] = useState('medium');
  const pageRef = useRef(1);

  const seen = useMonitorUnread((s) => s.seen);
  const unreadCount = useMonitorUnread((s) => s.unreadCount);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, r, e] = await Promise.all([
        fetchMonitorStatus(baseURL, token),
        fetchMonitorRules(baseURL, token),
        fetchMonitorEvents(baseURL, token, 1, PAGE_SIZE),
      ]);
      setStatus(s);
      setRules(r);
      setEvents(e.items);
      setPage(1);
      pageRef.current = 1;
      setTotal(e.total ?? e.items.length);
      useMonitorUnread.getState().refreshFromEventIds(e.items.map((x) => x.event_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const loadMore = async () => {
    if (loadingMore || loading || events.length >= total) return;
    setLoadingMore(true);
    try {
      const next = pageRef.current + 1;
      const e = await fetchMonitorEvents(baseURL, token, next, PAGE_SIZE);
      setEvents((prev) => {
        const ids = new Set(prev.map((x) => x.event_id));
        return [...prev, ...e.items.filter((x) => !ids.has(x.event_id))];
      });
      pageRef.current = next;
      setPage(next);
      useMonitorUnread.getState().refreshFromEventIds(e.items.map((x) => x.event_id));
    } catch {
      /* 分页失败不打断已有列表 */
    } finally {
      setLoadingMore(false);
    }
  };

  const toggle = async () => {
    try {
      if (status?.status === 'running') await pauseMonitor(baseURL, token);
      else await startMonitor(baseURL, token);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // 对齐 iOS：手动「立即评估」不强推（force: false）
  const evaluate = async () => {
    try {
      await evaluateMonitorOnce(baseURL, token, false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const addRule = async () => {
    if (!sym.trim()) return;
    try {
      await upsertMonitorRule(baseURL, token, {
        rule_type: 'price_change_pct_gt',
        title: `${sym.trim()} 涨跌幅`,
        symbol: sym.trim(),
        threshold: Number(threshold),
        severity,
        enabled: true,
        source: 'android',
      });
      setShowAdd(false);
      setSym('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const toggleRule = async (r: MonitorRule) => {
    if (!r.rule_id) return;
    setBusyId(r.rule_id);
    try {
      await upsertMonitorRule(baseURL, token, { ...r, rule_id: r.rule_id, enabled: !r.enabled });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const removeRule = async (id?: string) => {
    if (!id) return;
    setBusyId(id);
    try {
      await deleteMonitorRule(baseURL, token, id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const openEvent = (e: MonitorEvent) => {
    stashMonitorEvent(e);
    navigation.navigate('MonitorEventDetail', { eventId: e.event_id });
  };

  const openRules = () => setShowAdd((v) => !v);
  const unreadSet = new Set(seen);

  return (
    <View style={styles.container}>
      {/* 两行头部：一行标题+主操作，一行次操作。原先 6 个元素挤一行会溢出 */}
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <View style={styles.headerTop}>
          <Text style={styles.title}>盯盘</Text>
          {unreadCount > 0 ? <Text style={styles.unreadBadge}>{unreadCount} 未读</Text> : null}
          <View style={styles.spacer} />
          <Pressable
            style={[styles.primaryBtn, status?.status === 'running' && styles.primaryBtnPaused]}
            onPress={() => void toggle()}
            hitSlop={6}
          >
            <Text style={styles.primaryBtnText}>
              {status?.status === 'running' ? '⏸  暂停' : '▶  启动'}
            </Text>
          </Pressable>
        </View>

        <View style={styles.headerActions}>
          <Pressable onPress={() => void evaluate()} disabled={loading} hitSlop={6}>
            <Text style={[styles.link, loading && styles.linkDisabled]}>立即评估</Text>
          </Pressable>
          <Pressable onPress={openRules} hitSlop={6}>
            <Text style={styles.link}>＋ 规则</Text>
          </Pressable>
          {unreadCount > 0 ? (
            <Pressable
              onPress={() => useMonitorUnread.getState().markAllRead(events.map((e) => e.event_id))}
              hitSlop={6}
            >
              <Text style={styles.link}>全部已读</Text>
            </Pressable>
          ) : null}
        </View>
      </View>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <View style={styles.statusRow}>
        <Text style={styles.statusText}>
          状态 {status?.status ?? '—'}
          {status?.last_checked_at ? ` · 上次检查 ${relativeTime(status.last_checked_at)}` : ''}
        </Text>
      </View>
      {status?.last_error ? <Text style={styles.error}>最近错误：{status.last_error}</Text> : null}

      <Modal visible={showAdd} transparent animationType="slide" onRequestClose={() => setShowAdd(false)}>
        <Pressable style={styles.sheetBackdrop} onPress={() => setShowAdd(false)}>
          <Pressable style={styles.sheet} onPress={() => {}}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>新建盯盘规则</Text>
            <View style={styles.addPanel}>
          <TextInput style={styles.input} placeholder="股票代码" value={sym} onChangeText={setSym} autoCapitalize="none" />
          <TextInput style={styles.input} placeholder="涨跌幅阈值 %" value={threshold} onChangeText={setThreshold} keyboardType="numeric" />
          <View style={styles.sevRow}>
            {['high', 'medium', 'low'].map((s) => (
              <Pressable key={s} style={[styles.sevBtn, severity === s && styles.sevActive]} onPress={() => setSeverity(s)}>
                <Text style={[styles.sevText, severity === s && styles.sevTextActive]}>{s}</Text>
              </Pressable>
            ))}
          </View>
          <View style={styles.addRow}>
            <Pressable style={styles.addBtn} onPress={() => void addRule()}>
              <Text style={styles.addBtnText}>保存规则</Text>
            </Pressable>
            <Pressable style={styles.cancelBtn} onPress={() => setShowAdd(false)}>
              <Text style={styles.cancelText}>关闭</Text>
            </Pressable>
            </View>
            </View>
          </Pressable>
        </Pressable>
      </Modal>

      {rules.length > 0 ? (
        <View style={styles.rules}>
          {rules.map((r) => (
            <Swipeable
              key={r.rule_id}
              overshootRight={false}
              renderRightActions={() => (
                <Pressable style={styles.swipeAction} onPress={() => void removeRule(r.rule_id)}>
                  <Text style={styles.swipeActionText}>删除</Text>
                </Pressable>
              )}
            >
              <View style={styles.ruleRow}>
                <View style={styles.ruleBody}>
                  <Text style={styles.ruleText}>
                    {r.title ?? r.symbol} · {r.rule_type}
                  </Text>
                  {r.trigger_rule ? <Text style={styles.ruleTrigger}>{r.trigger_rule}</Text> : null}
                </View>
                {busyId === r.rule_id ? <ActivityIndicator size="small" /> : <Switch value={r.enabled ?? true} onValueChange={() => void toggleRule(r)} />}
              </View>
            </Swipeable>
          ))}
        </View>
      ) : null}

      <FlatList
        data={events}
        keyExtractor={(e) => e.event_id}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} />}
        onEndReached={() => void loadMore()}
        onEndReachedThreshold={0.4}
        ListEmptyComponent={
          loading ? <ActivityIndicator style={{ marginTop: 40 }} /> : <Text style={styles.muted}>暂无盯盘事件</Text>
        }
        ListFooterComponent={
          loadingMore ? <ActivityIndicator style={{ marginVertical: 16 }} /> : page > 1 && events.length >= total ? <Text style={styles.muted}>没有更多了</Text> : null
        }
        renderItem={({ item }) => {
          const unread = !unreadSet.has(item.event_id);
          return (
            <Pressable style={styles.event} onPress={() => openEvent(item)}>
              <View style={styles.eventHead}>
                <View style={[styles.pill, { backgroundColor: `${severityColor(item.severity)}22` }]}>
                  <Text style={[styles.pillText, { color: severityColor(item.severity) }]}>{item.severity ?? 'medium'}</Text>
                </View>
                <Text style={styles.eventSymbol}>{item.symbol}</Text>
                <Text style={[styles.eventTitle, unread && styles.eventTitleUnread]} numberOfLines={1}>
                  {item.title}
                </Text>
                {unread ? <View style={styles.dot} /> : null}
              </View>
              <Text style={styles.eventMeta}>
                {relativeTime(item.triggered_at)} · {item.message?.slice(0, 40) ?? ''}
              </Text>
            </Pressable>
          );
        }}
      />
    </View>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: { paddingHorizontal: 16, paddingBottom: 10 },
  headerTop: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 20, marginTop: 10 },
  spacer: { flex: 1 },
  title: { fontSize: 20, fontWeight: '700' },
  primaryBtn: {
    backgroundColor: '#007AFF',
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 6,
  },
  primaryBtnPaused: { backgroundColor: '#8E8E93' },
  primaryBtnText: { color: '#fff', fontSize: 13, fontWeight: '600' },
  linkDisabled: { opacity: 0.4 },
  unreadBadge: { color: '#FF3B30', fontSize: 13, fontWeight: '600' },
  link: { color: '#007AFF', fontSize: 13 },
  del: { color: '#c0392b', fontSize: 13 },
  swipeAction: { backgroundColor: '#FF3B30', justifyContent: 'center', paddingHorizontal: 22 },
  swipeActionText: { color: '#fff', fontWeight: '700' },
  sheetBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.35)', justifyContent: 'flex-end' },
  sheet: { backgroundColor: '#fff', borderTopLeftRadius: 16, borderTopRightRadius: 16, paddingBottom: 24 },
  sheetHandle: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: '#ccc', marginTop: 8 },
  sheetTitle: { fontSize: 16, fontWeight: '700', paddingHorizontal: 16, paddingTop: 12 },
  error: { color: '#c0392b', fontSize: 12, paddingHorizontal: 16, paddingBottom: 6 },
  statusRow: { paddingHorizontal: 16, paddingBottom: 6 },
  statusText: { fontSize: 12, color: '#8E8E93' },
  addPanel: { paddingHorizontal: 16, paddingBottom: 8 },
  input: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 10, fontSize: 14, marginBottom: 8 },
  sevRow: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  sevBtn: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: '#ddd' },
  sevActive: { borderColor: '#007AFF', backgroundColor: '#eef4ff' },
  sevText: { color: '#666', fontSize: 13 },
  sevTextActive: { color: '#007AFF' },
  addRow: { flexDirection: 'row', gap: 10 },
  addBtn: { flex: 1, backgroundColor: '#007AFF', borderRadius: 8, padding: 12, alignItems: 'center' },
  addBtnText: { color: '#fff', fontWeight: '600' },
  cancelBtn: { paddingHorizontal: 18, justifyContent: 'center' },
  cancelText: { color: '#666' },
  rules: { paddingHorizontal: 16, paddingBottom: 8 },
  ruleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#eee',
  },
  ruleBody: { flex: 1 },
  ruleText: { fontSize: 13 },
  ruleTrigger: { fontSize: 11, color: '#999', fontFamily: 'Menlo', marginTop: 2 },
  event: { paddingHorizontal: 16, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#eee' },
  eventHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pill: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 2 },
  pillText: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  eventSymbol: { fontWeight: '700', fontSize: 14 },
  eventTitle: { flex: 1, fontSize: 13 },
  eventTitleUnread: { fontWeight: '700' },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#FF3B30' },
  eventMeta: { fontSize: 11, color: '#999', marginTop: 4 },
  muted: { color: '#999', textAlign: 'center', marginVertical: 16 },
});
