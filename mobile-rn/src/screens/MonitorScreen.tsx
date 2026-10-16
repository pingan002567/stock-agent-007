import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, TextInput, View } from 'react-native';
import {
  deleteMonitorRule,
  evaluateMonitorOnce,
  fetchMonitorEvents,
  fetchMonitorRules,
  fetchMonitorStatus,
  pauseMonitor,
  sendMonitorFeedback,
  startMonitor,
  upsertMonitorRule,
} from '../api/client';
import { useConnection } from '../store/connection';
import type { MonitorEvent, MonitorRule, MonitorStatus } from '../types';

export default function MonitorScreen() {
  const { baseURL, token } = useConnection();
  const [status, setStatus] = useState<MonitorStatus | null>(null);
  const [rules, setRules] = useState<MonitorRule[]>([]);
  const [events, setEvents] = useState<MonitorEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [sym, setSym] = useState('');
  const [threshold, setThreshold] = useState('3');
  const [severity, setSeverity] = useState('medium');
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, r, e] = await Promise.all([fetchMonitorStatus(baseURL, token), fetchMonitorRules(baseURL, token), fetchMonitorEvents(baseURL, token, 1, 30)]);
      setStatus(s);
      setRules(r);
      setEvents(e.items);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async () => {
    if (status?.status === 'running') await pauseMonitor(baseURL, token);
    else await startMonitor(baseURL, token);
    await load();
  };

  const evaluate = async () => {
    await evaluateMonitorOnce(baseURL, token, true);
    await load();
  };

  const addRule = async () => {
    if (!sym.trim()) return;
    await upsertMonitorRule(baseURL, token, {
      rule_type: 'price_change_pct_gt',
      symbol: sym.trim(),
      threshold: Number(threshold),
      severity,
      enabled: true,
      source: 'android',
    });
    setShowAdd(false);
    setSym('');
    await load();
  };

  const toggleRule = async (r: MonitorRule) => {
    await upsertMonitorRule(baseURL, token, { ...r, rule_id: r.rule_id, enabled: !r.enabled });
    await load();
  };

  const removeRule = async (id?: string) => {
    if (id) {
      await deleteMonitorRule(baseURL, token, id);
      await load();
    }
  };

  const feedback = async (ruleId?: string, useful?: boolean) => {
    if (ruleId) {
      await sendMonitorFeedback(baseURL, token, ruleId, !!useful);
    }
  };

  const sevColor = (s?: string) => (s === 'high' ? '#e53935' : s === 'medium' ? '#f59e0b' : '#26a69a');

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>盯盘</Text>
        <Pressable onPress={() => void toggle()}>
          <Text style={styles.link}>{status?.status === 'running' ? '⏸ 暂停' : '▶ 启动'}</Text>
        </Pressable>
        <Pressable onPress={() => void evaluate()}>
          <Text style={styles.link}>立即评估</Text>
        </Pressable>
        <Pressable onPress={() => setShowAdd((v) => !v)}>
          <Text style={styles.link}>＋规则</Text>
        </Pressable>
      </View>

      {status?.last_error ? <Text style={styles.error}>最近错误：{status.last_error}</Text> : null}

      {showAdd && (
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
          <Pressable style={styles.addBtn} onPress={() => void addRule()}>
            <Text style={styles.addBtnText}>保存规则</Text>
          </Pressable>
        </View>
      )}

      {rules.length > 0 && (
        <View style={styles.rules}>
          {rules.map((r) => (
            <View key={r.rule_id} style={styles.ruleRow}>
              <Text style={styles.ruleText}>
                {r.symbol} {r.trigger_rule ?? r.title ?? r.rule_type}
              </Text>
              <Pressable onPress={() => void toggleRule(r)}>
                <Text style={styles.link}>{r.enabled ? '关' : '开'}</Text>
              </Pressable>
              <Pressable onPress={() => void removeRule(r.rule_id)}>
                <Text style={styles.del}>删</Text>
              </Pressable>
            </View>
          ))}
        </View>
      )}

      <FlatList
        data={events}
        keyExtractor={(e) => e.event_id}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} />}
        ListEmptyComponent={loading ? <ActivityIndicator style={{ marginTop: 40 }} /> : <Text style={styles.muted}>暂无盯盘事件</Text>}
        renderItem={({ item }) => (
          <View style={styles.event}>
            <Pressable onPress={() => setExpanded((cur) => (cur === item.event_id ? null : item.event_id))}>
              <View style={styles.eventHead}>
                <Text style={[styles.sev, { color: sevColor(item.severity) }]}>{item.severity}</Text>
                <Text style={styles.eventSymbol}>{item.symbol}</Text>
                <Text style={styles.eventTitle} numberOfLines={1}>
                  {item.title}
                </Text>
              </View>
              <Text style={styles.eventTime}>{item.triggered_at}</Text>
            </Pressable>
            {expanded === item.event_id && (
              <View style={styles.eventBody}>
                <Text style={styles.eventMsg}>{item.message}</Text>
                <View style={styles.feedbackRow}>
                  <Pressable onPress={() => void feedback(item.rule_id, true)}>
                    <Text style={styles.link}>有用</Text>
                  </Pressable>
                  <Pressable onPress={() => void feedback(item.rule_id, false)}>
                    <Text style={styles.link}>无用</Text>
                  </Pressable>
                </View>
              </View>
            )}
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 16, paddingVertical: 12 },
  title: { fontSize: 20, fontWeight: '700', marginRight: 'auto' },
  link: { color: '#007AFF', fontSize: 14 },
  del: { color: '#c0392b', fontSize: 14 },
  error: { color: '#c0392b', fontSize: 12, paddingHorizontal: 16 },
  addPanel: { paddingHorizontal: 16, paddingBottom: 8 },
  input: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 10, fontSize: 14, marginBottom: 8 },
  sevRow: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  sevBtn: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: '#ddd' },
  sevActive: { borderColor: '#007AFF', backgroundColor: '#eef4ff' },
  sevText: { color: '#666', fontSize: 13 },
  sevTextActive: { color: '#007AFF' },
  addBtn: { backgroundColor: '#007AFF', borderRadius: 8, padding: 12, alignItems: 'center' },
  addBtnText: { color: '#fff', fontWeight: '600' },
  rules: { paddingHorizontal: 16, paddingBottom: 8 },
  ruleRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#eee' },
  ruleText: { flex: 1, fontSize: 13 },
  event: { paddingHorizontal: 16, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#eee' },
  eventHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sev: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase' },
  eventSymbol: { fontWeight: '700', fontSize: 14 },
  eventTitle: { flex: 1, fontSize: 13 },
  eventTime: { fontSize: 11, color: '#999', marginTop: 4 },
  eventBody: { marginTop: 8 },
  eventMsg: { fontSize: 13, color: '#444', lineHeight: 19 },
  feedbackRow: { flexDirection: 'row', gap: 16, marginTop: 8 },
  muted: { color: '#999', textAlign: 'center', marginTop: 40 },
});
