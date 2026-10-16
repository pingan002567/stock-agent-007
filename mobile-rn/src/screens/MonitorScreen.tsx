import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  evaluateMonitorOnce,
  fetchMonitorEvents,
  fetchMonitorRules,
  fetchMonitorStatus,
  pauseMonitor,
  startMonitor,
} from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { SettingsGroup, SettingsNote, SettingsRow, SettingsSwitchRow } from '../components/SettingsList';
import { Sheet } from '../components/Sheet';
import { severityColor } from '../lib/colors';
import { relativeTime } from '../lib/format';
import { useThemedStyles, useTokens } from '../lib/tokens';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import { useMonitorUnread } from '../store/monitorUnread';
import type { MonitorEvent, MonitorRule, MonitorStatus } from '../types';
import { stashMonitorEvent } from './MonitorEventDetailScreen';

const PAGE_SIZE = 30;
type Filter = 'all' | 'unread' | 'high';

export default function MonitorScreen() {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  const insets = useSafeAreaInsets();
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const { baseURL, token } = useConnection();

  const [status, setStatus] = useState<MonitorStatus | null>(null);
  const [rules, setRules] = useState<MonitorRule[]>([]);
  const [events, setEvents] = useState<MonitorEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [menuVisible, setMenuVisible] = useState(false);
  const pageRef = useRef(1);

  const seen = useMonitorUnread((s) => s.seen);
  const unreadCount = useMonitorUnread((s) => s.unreadCount);
  const seenSet = new Set(seen);

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
      useMonitorUnread.getState().refreshFromEventIds(e.items.map((x) => x.event_id));
    } catch {
      /* 分页失败不打断已有列表 */
    } finally {
      setLoadingMore(false);
    }
  };

  const running = status?.status === 'running';

  const toggleRunning = async () => {
    try {
      if (running) await pauseMonitor(baseURL, token);
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

  const openEvent = (e: MonitorEvent) => {
    stashMonitorEvent(e);
    navigation.navigate('MonitorEventDetail', { eventId: e.event_id });
  };

  const markAllRead = () => useMonitorUnread.getState().markAllRead(events.map((e) => e.event_id));

  const highCount = events.filter((e) => String(e.severity ?? '').toLowerCase() === 'high').length;
  const enabledRules = rules.filter((r) => r.enabled).length;

  const filtered = events.filter((e) => {
    if (filter === 'unread') return !seenSet.has(e.event_id);
    if (filter === 'high') return String(e.severity ?? '').toLowerCase() === 'high';
    return true;
  });

  const FILTERS: { id: Filter; label: string; count: number }[] = [
    { id: 'all', label: '全部', count: events.length },
    { id: 'unread', label: '未读', count: unreadCount },
    { id: 'high', label: '高优先级', count: highCount },
  ];

  return (
    <View style={[styles.container, { backgroundColor: t.pageBg }]}>
      {/* 浅灰岛头部（与对话页一致） */}
      <View style={[styles.headerWrap, { paddingTop: insets.top + 8 }]}>
        <View style={[styles.island, { backgroundColor: t.cardAlt }]}>
          <Text style={[styles.islandTitle, { color: t.text }]}>盯盘</Text>
          {unreadCount > 0 ? <Text style={[styles.unreadBadge, { color: t.danger }]}>{unreadCount} 未读</Text> : null}
          <View style={styles.spacer} />
          <Pressable
            style={[styles.primaryBtn, { backgroundColor: running ? t.sep : t.accent }]}
            onPress={() => void toggleRunning()}
            hitSlop={4}
          >
            <Ionicons name={running ? 'pause' : 'play'} size={14} color={running ? t.text : '#fff'} />
            <Text style={[styles.primaryText, { color: running ? t.text : '#fff' }]}>
              {running ? '暂停' : '启动'}
            </Text>
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

      <FlatList
        data={filtered}
        keyExtractor={(e) => e.event_id}
        contentContainerStyle={styles.listContent}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} tintColor={t.accent} />}
        onEndReached={() => void loadMore()}
        onEndReachedThreshold={0.4}
        ListHeaderComponent={
          <View>
            <SettingsGroup title="运行状态">
              <SettingsSwitchRow
                label="盯盘运行中"
                hint={running ? '按间隔轮询规则，命中即产生事件' : '已暂停，不会再产生新事件'}
                value={running}
                onChange={() => void toggleRunning()}
              />
              <SettingsRow label="上次检查" value={status?.last_checked_at ? relativeTime(status.last_checked_at) : '—'} />
              <SettingsRow
                label="检查间隔"
                value={status?.interval_seconds != null ? `${status.interval_seconds} 秒` : '—'}
                last={!status?.last_error}
              />
              {status?.last_error ? <SettingsNote>⚠️ {status.last_error}</SettingsNote> : null}
            </SettingsGroup>

            <SettingsGroup title="规则">
              <SettingsRow
                icon="options-outline"
                label="盯盘规则"
                value={rules.length ? `${rules.length} 条 · ${enabledRules} 启用` : '还未配置'}
                onPress={() => navigation.navigate('MonitorRules')}
                last
              />
            </SettingsGroup>

            <View style={styles.filters}>
              {FILTERS.map((f) => {
                const on = filter === f.id;
                return (
                  <Pressable
                    key={f.id}
                    style={[styles.filter, { borderColor: on ? t.accent : t.sep, backgroundColor: on ? t.cardAlt : 'transparent' }]}
                    onPress={() => setFilter(f.id)}
                  >
                    <Text style={[styles.filterText, { color: on ? t.accent : t.sub }]}>
                      {f.label}
                      {f.count > 0 ? ` ${f.count}` : ''}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        }
        ListEmptyComponent={
          loading ? (
            <ActivityIndicator style={{ marginTop: 40 }} />
          ) : (
            <View style={styles.empty}>
              <Text style={[styles.emptyText, { color: t.sub }]}>
                {filter === 'all' ? '暂无盯盘事件' : '该筛选下没有事件'}
              </Text>
              <Text style={[styles.emptyHint, { color: t.sub }]}>
                {rules.length === 0 ? '先配置一条规则，命中后会在这里显示。' : '规则命中后会在这里显示。'}
              </Text>
            </View>
          )
        }
        ListFooterComponent={
          loadingMore ? (
            <ActivityIndicator style={{ marginVertical: 16 }} />
          ) : pageRef.current > 1 && events.length >= total ? (
            <Text style={[styles.footer, { color: t.sub }]}>没有更多了</Text>
          ) : null
        }
        renderItem={({ item }) => {
          const unread = !seenSet.has(item.event_id);
          return (
            <Pressable style={[styles.eventRow, { backgroundColor: t.groupBg }]} onPress={() => openEvent(item)}>
              <View style={styles.eventBody}>
                <View style={styles.eventTop}>
                  <View style={[styles.pill, { backgroundColor: `${severityColor(item.severity)}22` }]}>
                    <Text style={[styles.pillText, { color: severityColor(item.severity) }]}>
                      {String(item.severity ?? 'medium')}
                    </Text>
                  </View>
                  {item.symbol ? <Text style={[styles.eventSymbol, { color: t.text }]}>{item.symbol}</Text> : null}
                  <Text
                    style={[styles.eventTitle, { color: t.text }, unread && styles.eventTitleUnread]}
                    numberOfLines={1}
                  >
                    {item.title ?? '事件'}
                  </Text>
                  {unread ? <View style={[styles.dot, { backgroundColor: t.danger }]} /> : null}
                </View>
                <Text style={[styles.eventMeta, { color: t.sub }]} numberOfLines={2}>
                  {relativeTime(item.triggered_at)}
                  {item.message ? ` · ${item.message}` : ''}
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={16} color="#C7C7CC" />
            </Pressable>
          );
        }}
      />

      {/* ⋮ 更多 */}
      <Sheet visible={menuVisible} onClose={() => setMenuVisible(false)}>
        <Text style={[styles.sheetTitle, { color: t.sub }]}>盯盘</Text>
        <MenuItem
          icon="refresh-outline"
          label="立即评估一次"
          hint={loading ? '进行中…' : '不强推，按冷却策略执行'}
          disabled={loading}
          onPress={() => {
            setMenuVisible(false);
            void evaluate();
          }}
        />
        <MenuItem
          icon="add-circle-outline"
          label="新建规则"
          onPress={() => {
            setMenuVisible(false);
            navigation.navigate('MonitorRules');
          }}
        />
        <MenuItem
          icon="checkmark-done-outline"
          label="全部标为已读"
          hint={unreadCount > 0 ? `${unreadCount} 条未读` : '暂无未读'}
          disabled={unreadCount === 0}
          onPress={() => {
            setMenuVisible(false);
            markAllRead();
          }}
        />
        <MenuItem
          icon={running ? 'pause-circle-outline' : 'play-circle-outline'}
          label={running ? '暂停盯盘' : '启动盯盘'}
          onPress={() => {
            setMenuVisible(false);
            void toggleRunning();
          }}
        />
        <MenuItem
          icon="options-outline"
          label="管理规则"
          hint={rules.length ? `${rules.length} 条` : '暂无规则'}
          onPress={() => {
            setMenuVisible(false);
            navigation.navigate('MonitorRules');
          }}
        />
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
  unreadBadge: { fontSize: 12, fontWeight: '600' },
  spacer: { flex: 1 },
  primaryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  primaryText: { fontSize: 13, fontWeight: '600' },
  circleBtn: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  listContent: { paddingBottom: 30 },
  filters: { flexDirection: 'row', gap: 8, marginHorizontal: 16, marginBottom: 12 },
  filter: { flex: 1, borderWidth: 1, borderRadius: 9, paddingVertical: 8, alignItems: 'center' },
  filterText: { fontSize: 12.5 },
  eventRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 16,
    marginBottom: 8,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  eventBody: { flex: 1 },
  eventTop: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pill: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 2 },
  pillText: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  eventSymbol: { fontSize: 14, fontWeight: '700' },
  eventTitle: { flex: 1, fontSize: 14 },
  eventTitleUnread: { fontWeight: '700' },
  dot: { width: 8, height: 8, borderRadius: 4 },
  eventMeta: { fontSize: 11.5, marginTop: 5, lineHeight: 16 },
  empty: { alignItems: 'center', paddingVertical: 50, paddingHorizontal: 32 },
  emptyText: { fontSize: 14 },
  emptyHint: { fontSize: 12, marginTop: 6, textAlign: 'center', lineHeight: 18 },
  footer: { textAlign: 'center', fontSize: 12, marginVertical: 16 },
  sheetTitle: { fontSize: 12.5, textAlign: 'center', paddingTop: 8, paddingBottom: 10 },
  menuItem: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 22, paddingVertical: 14 },
  menuDisabled: { opacity: 0.4 },
  menuText: { flex: 1 },
  menuLabel: { fontSize: 15 },
  menuHint: { fontSize: 11.5, marginTop: 2 },
});
