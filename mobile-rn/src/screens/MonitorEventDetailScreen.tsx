import { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import type { RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { fetchMonitorEvents, sendMonitorFeedback } from '../api/client';
import { useConnection } from '../store/connection';
import { EmptyState, ErrorState } from '../components/ErrorState';
import { severityColor } from '../lib/colors';
import { relativeTime } from '../lib/format';
import type { RootStackParamList } from '../navigation';
import type { MonitorEvent } from '../types';
import { useThemedStyles } from '../lib/tokens';

type Nav = NativeStackNavigationProp<RootStackParamList>;
type Route = RouteProp<RootStackParamList, 'MonitorEventDetail'>;

// MonitorScreen 跳转前把选中的事件放这里，详情页直接读取（避免多一次请求）
let stashed: MonitorEvent | null = null;
export function stashMonitorEvent(e: MonitorEvent) {
  stashed = e;
}

/** 事件详情（对齐 iOS Features/Monitor/MonitorEventDetailView） */
export default function MonitorEventDetailScreen() {
  const styles = useThemedStyles(baseStyles);
  const navigation = useNavigation<Nav>();
  const route = useRoute<Route>();
  const { baseURL, token } = useConnection();
  const [feedback, setFeedback] = useState<'useful' | 'useless' | null>(null);
  const [event, setEvent] = useState<MonitorEvent | null>(stashed);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // 深链进入（没有 stash）时按 eventId 回查
  useEffect(() => {
    const id = route.params?.eventId;
    if (!id || event?.event_id === id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        for (let page = 1; page <= 5; page += 1) {
          const r = await fetchMonitorEvents(baseURL, token, page, 30);
          const hit = r.items.find((x) => x.event_id === id);
          if (hit) {
            if (!cancelled) setEvent(hit);
            return;
          }
          if (r.items.length < 30) break;
        }
        if (!cancelled) setError('未找到该事件（可能已过期）');
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.params?.eventId]);

  const e = event;

  if (error) return <ErrorState message={error} />;
  if (loading && !e) return <EmptyState text="正在加载事件…" />;
  if (!e) return <EmptyState text="未找到该事件" />;

  const useful = async (wasUseful: boolean) => {
    setFeedback(wasUseful ? 'useful' : 'useless');
    if (e.rule_id) {
      try {
        await sendMonitorFeedback(baseURL, token, e.rule_id, wasUseful);
      } catch {
        /* ignore */
      }
    }
  };

  const evidence = Array.isArray(e.evidence) ? e.evidence : [];

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <View style={styles.head}>
        <View style={[styles.pill, { backgroundColor: `${severityColor(e.severity)}22` }]}>
          <Text style={[styles.pillText, { color: severityColor(e.severity) }]}>{e.severity ?? 'medium'}</Text>
        </View>
        <Text style={styles.time}>{relativeTime(e.triggered_at)}</Text>
      </View>

      <Text style={styles.title}>{e.title ?? e.symbol ?? '盯盘事件'}</Text>

      {e.symbol ? (
        <Pressable style={styles.stockLink} onPress={() => navigation.navigate('StockDetail', { symbol: e.symbol! })}>
          <Text style={styles.stockLinkText}>查看标的 {e.symbol} ›</Text>
        </Pressable>
      ) : null}

      <Section title="概要" value={e.message} />
      <Section title="触发规则" value={e.trigger_rule ?? e.rule_type} mono />
      <Section title="来源" value={e.source} />

      {evidence.length > 0 ? (
        <>
          <Text style={styles.sectionTitle}>证据</Text>
          {evidence.map((ev, i) => (
            <View key={i} style={styles.card}>
              <Text style={styles.mono} selectable>
                {typeof ev === 'string' ? ev : JSON.stringify(ev, null, 2)}
              </Text>
            </View>
          ))}
        </>
      ) : null}

      {e.suggested_actions && e.suggested_actions.length > 0 ? (
        <>
          <Text style={styles.sectionTitle}>建议动作</Text>
          {e.suggested_actions.map((a, i) => (
            <Text key={i} style={styles.action}>
              · {a}
            </Text>
          ))}
        </>
      ) : null}

      {e.payload && Object.keys(e.payload).length > 0 ? (
        <>
          <Text style={styles.sectionTitle}>载荷</Text>
          <View style={styles.card}>
            <Text style={styles.mono} selectable>
              {JSON.stringify(e.payload, null, 2)}
            </Text>
          </View>
        </>
      ) : null}

      <Text style={styles.sectionTitle}>这条事件有用吗？</Text>
      <View style={styles.feedbackRow}>
        <Pressable style={[styles.feedbackBtn, feedback === 'useful' && styles.feedbackActive]} onPress={() => void useful(true)}>
          <Text style={styles.feedbackText}>有用</Text>
        </Pressable>
        <Pressable
          style={[styles.feedbackBtn, feedback === 'useless' && styles.feedbackActive]}
          onPress={() => void useful(false)}
        >
          <Text style={styles.feedbackText}>没用</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

function Section({ title, value, mono }: { title: string; value?: string; mono?: boolean }) {
  const styles = useThemedStyles(baseStyles);
  if (!value) return null;
  return (
    <>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.card}>
        <Text style={mono ? styles.mono : styles.value} selectable>
          {value}
        </Text>
      </View>
    </>
  );
}

const baseStyles = StyleSheet.create({
  container: { padding: 16 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  pill: { borderRadius: 10, paddingHorizontal: 10, paddingVertical: 3 },
  pillText: { fontSize: 12, fontWeight: '600' },
  time: { fontSize: 12, color: '#8E8E93' },
  title: { fontSize: 18, fontWeight: '700', marginTop: 10 },
  stockLink: { marginTop: 8 },
  stockLinkText: { color: '#007AFF', fontSize: 14 },
  sectionTitle: { fontSize: 13, color: '#8E8E93', marginTop: 16, marginBottom: 6 },
  card: { backgroundColor: '#f7f8fa', borderRadius: 10, padding: 12 },
  value: { fontSize: 14, lineHeight: 21 },
  mono: { fontSize: 12, color: '#555', fontFamily: 'Menlo' },
  action: { fontSize: 14, color: '#333', marginBottom: 4 },
  feedbackRow: { flexDirection: 'row', gap: 12, marginTop: 4 },
  feedbackBtn: { borderWidth: 1, borderColor: '#ccc', borderRadius: 8, paddingHorizontal: 22, paddingVertical: 10 },
  feedbackActive: { borderColor: '#007AFF', backgroundColor: '#eef4ff' },
  feedbackText: { fontSize: 14, color: '#333' },
});
