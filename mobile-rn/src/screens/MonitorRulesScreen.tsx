import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { Swipeable } from 'react-native-gesture-handler';
import { Ionicons } from '@expo/vector-icons';
import { deleteMonitorRule, fetchMonitorRules, upsertMonitorRule } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { Sheet } from '../components/Sheet';
import { severityColor } from '../lib/colors';
import { useThemedStyles, useTokens } from '../lib/tokens';
import { useConnection } from '../store/connection';
import type { MonitorRule } from '../types';

const SEVERITIES = ['high', 'medium', 'low'] as const;

/** 规则类型：名字与后端一致（monitor_service 按 rule_type 分支） */
const RULE_TYPES = [
  { id: 'price_change_pct_gt', label: '涨跌幅', unit: '涨跌幅阈值（%）', placeholder: '3', hint: '例如 600519 / BTC' },
  { id: 'crypto_funding_rate_gt', label: '资金费率', unit: '资金费率阈值（%）', placeholder: '0.02', hint: '仅加密，例如 BTC' },
] as const;

/** rule_type 中文化：以前列表直接显示原始英文，其它端建的规则在手机上看不懂 */
const RULE_TYPE_LABELS: Record<string, string> = {
  price_change_pct_gt: '涨跌幅',
  price_above: '突破价位',
  price_below: '跌破价位',
  volume_spike: '放量',
  crypto_funding_rate_gt: '资金费率',
  single_position_weight_gt: '单票超限',
  pnl_pct_lt: '浮亏超限',
};

function ruleTypeLabel(raw?: string): string {
  const key = String(raw ?? '');
  return RULE_TYPE_LABELS[key] ?? (key || '规则');
}

export default function MonitorRulesScreen() {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  const { baseURL, token } = useConnection();

  const [rules, setRules] = useState<MonitorRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [showAdd, setShowAdd] = useState(false);
  const [sym, setSym] = useState('');
  const [threshold, setThreshold] = useState('3');
  const [severity, setSeverity] = useState<string>('medium');
  const [ruleType, setRuleType] = useState<string>(RULE_TYPES[0].id);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRules(await fetchMonitorRules(baseURL, token));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (r: MonitorRule) => {
    if (!r.rule_id) return;
    setBusyId(r.rule_id);
    const before = rules;
    setRules((prev) => prev.map((x) => (x.rule_id === r.rule_id ? { ...x, enabled: !x.enabled } : x)));
    try {
      await upsertMonitorRule(baseURL, token, { ...r, rule_id: r.rule_id, enabled: !r.enabled });
    } catch (e) {
      setRules(before);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (id?: string) => {
    if (!id) return;
    setBusyId(id);
    try {
      await deleteMonitorRule(baseURL, token, id);
      setRules((prev) => prev.filter((x) => x.rule_id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const add = async () => {
    const symbol = sym.trim();
    if (!symbol) return;
    try {
      const meta = RULE_TYPES.find((r) => r.id === ruleType) ?? RULE_TYPES[0];
      await upsertMonitorRule(baseURL, token, {
        rule_type: meta.id,
        title: `${symbol} ${meta.label}`,
        symbol: String(symbol).toUpperCase(),
        threshold: Number(threshold) || (meta.id === 'crypto_funding_rate_gt' ? 0.02 : 3),
        severity,
        enabled: true,
        source: 'android',
      });
      setShowAdd(false);
      setSym('');
      setThreshold('3');
      setSeverity('medium');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setShowAdd(false);
    }
  };

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (loading) return <ActivityIndicator style={{ marginTop: 60 }} />;

  const enabled = rules.filter((r) => r.enabled).length;

  return (
    <View style={[styles.container, { backgroundColor: t.pageBg }]}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={[styles.summary, { color: t.sub }]}>
          共 {rules.length} 条 · {enabled} 条启用
        </Text>

        {rules.length === 0 ? (
          <View style={styles.empty}>
            <Text style={[styles.emptyText, { color: t.sub }]}>还没有盯盘规则</Text>
            <Text style={[styles.emptyHint, { color: t.sub }]}>点下面的按钮加一条，例如「600519 跌超 3%」。</Text>
          </View>
        ) : (
          rules.map((r) => (
            <Swipeable
              key={r.rule_id}
              overshootRight={false}
              renderRightActions={() => (
                <Pressable style={styles.swipeAction} onPress={() => void remove(r.rule_id)}>
                  <Text style={styles.swipeActionText}>删除</Text>
                </Pressable>
              )}
            >
              <View style={[styles.card, { backgroundColor: t.groupBg }]}>
                <View style={styles.cardMain}>
                  <View style={styles.cardTop}>
                    <View style={[styles.pill, { backgroundColor: `${severityColor(r.severity)}22` }]}>
                      <Text style={[styles.pillText, { color: severityColor(r.severity) }]}>
                        {String(r.severity ?? 'medium')}
                      </Text>
                    </View>
                    <Text style={[styles.cardTitle, { color: t.text }]} numberOfLines={1}>
                      {r.title ?? r.symbol ?? '—'}
                    </Text>
                  </View>
                  {r.trigger_rule ? (
                    <Text style={[styles.trigger, { color: t.sub }]} numberOfLines={2}>
                      {r.trigger_rule}
                    </Text>
                  ) : (
                    <Text style={[styles.trigger, { color: t.sub }]}>
                      {ruleTypeLabel(r.rule_type)}
                      {r.symbol ? ` · ${r.symbol}` : ''}
                      {r.threshold != null ? ` · 阈值 ${r.threshold}` : ''}
                    </Text>
                  )}
                </View>
                {busyId === r.rule_id ? (
                  <ActivityIndicator size="small" />
                ) : (
                  <Switch value={r.enabled ?? true} onValueChange={() => void toggle(r)} trackColor={{ true: t.accent }} />
                )}
              </View>
            </Swipeable>
          ))
        )}

        <Pressable style={[styles.addBtn, { backgroundColor: t.accent }]} onPress={() => setShowAdd(true)}>
          <Ionicons name="add" size={19} color="#fff" />
          <Text style={styles.addText}>新建规则</Text>
        </Pressable>
      </ScrollView>

      <Sheet visible={showAdd} onClose={() => setShowAdd(false)}>
        <Text style={[styles.sheetTitle, { color: t.sub }]}>新建盯盘规则</Text>
        <View style={styles.form}>
          <Text style={[styles.label, { color: t.sub }]}>规则类型</Text>
          <View style={styles.sevRow}>
            {RULE_TYPES.map((rt) => {
              const on = ruleType === rt.id;
              return (
                <Pressable
                  key={rt.id}
                  style={[styles.sevBtn, { borderColor: on ? t.accent : t.sep, backgroundColor: on ? t.cardAlt : 'transparent' }]}
                  onPress={() => {
                    setRuleType(rt.id);
                    setThreshold(String(rt.placeholder));
                  }}
                >
                  <Text style={[styles.sevText, { color: on ? t.accent : t.sub }]}>{rt.label}</Text>
                </Pressable>
              );
            })}
          </View>

          <Text style={[styles.label, { color: t.sub }]}>标的代码</Text>
          <TextInput
            style={[styles.input, { color: t.text, borderColor: t.sep }]}
            placeholder={(RULE_TYPES.find((r) => r.id === ruleType) ?? RULE_TYPES[0]).hint}
            placeholderTextColor={t.sub}
            value={sym}
            onChangeText={setSym}
            autoCapitalize="characters"
            autoCorrect={false}
          />
          <Text style={[styles.label, { color: t.sub }]}>
            {(RULE_TYPES.find((r) => r.id === ruleType) ?? RULE_TYPES[0]).unit}
          </Text>
          <TextInput
            style={[styles.input, { color: t.text, borderColor: t.sep }]}
            placeholder={(RULE_TYPES.find((r) => r.id === ruleType) ?? RULE_TYPES[0]).placeholder}
            placeholderTextColor={t.sub}
            value={threshold}
            onChangeText={setThreshold}
            keyboardType="numeric"
          />
          <Text style={[styles.label, { color: t.sub }]}>级别</Text>
          <View style={styles.sevRow}>
            {SEVERITIES.map((s) => {
              const on = severity === s;
              return (
                <Pressable
                  key={s}
                  style={[styles.sevBtn, { borderColor: on ? t.accent : t.sep, backgroundColor: on ? t.cardAlt : 'transparent' }]}
                  onPress={() => setSeverity(s)}
                >
                  <Text style={[styles.sevText, { color: on ? t.accent : t.sub }]}>{s}</Text>
                </Pressable>
              );
            })}
          </View>
          <Pressable style={[styles.submit, { backgroundColor: t.accent }]} onPress={() => void add()}>
            <Text style={styles.submitText}>保存规则</Text>
          </Pressable>
        </View>
      </Sheet>
    </View>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1 },
  content: { paddingTop: 16, paddingBottom: 40 },
  summary: { fontSize: 12.5, marginHorizontal: 16, marginBottom: 10 },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: 16,
    marginBottom: 10,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    gap: 10,
  },
  cardMain: { flex: 1 },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cardTitle: { fontSize: 15, flexShrink: 1 },
  pill: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 2 },
  pillText: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  trigger: { fontSize: 11.5, marginTop: 5, lineHeight: 16 },
  swipeAction: { backgroundColor: '#FF3B30', justifyContent: 'center', paddingHorizontal: 22, marginBottom: 10, marginRight: 16, borderRadius: 12 },
  swipeActionText: { color: '#fff', fontWeight: '700' },
  empty: { alignItems: 'center', paddingVertical: 60, paddingHorizontal: 32 },
  emptyText: { fontSize: 14 },
  emptyHint: { fontSize: 12, marginTop: 6, textAlign: 'center', lineHeight: 18 },
  addBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginHorizontal: 16,
    marginTop: 6,
    borderRadius: 12,
    paddingVertical: 14,
  },
  addText: { color: '#fff', fontWeight: '600', fontSize: 15 },
  sheetTitle: { fontSize: 12.5, textAlign: 'center', paddingTop: 8, paddingBottom: 12 },
  form: { paddingHorizontal: 16 },
  label: { fontSize: 12, marginBottom: 6, marginTop: 10 },
  input: { borderWidth: StyleSheet.hairlineWidth, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
  sevRow: { flexDirection: 'row', gap: 8 },
  sevBtn: { flex: 1, borderWidth: 1, borderRadius: 9, paddingVertical: 9, alignItems: 'center' },
  sevText: { fontSize: 13 },
  submit: { borderRadius: 12, paddingVertical: 14, alignItems: 'center', marginTop: 20 },
  submitText: { color: '#fff', fontWeight: '600', fontSize: 15 },
});
