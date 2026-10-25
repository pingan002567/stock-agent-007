import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { fetchActiveRiskPolicy, fetchSettings, updateInvestorProfile, updateRiskPolicy, type RiskPolicy } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { SettingsGroup } from '../components/SettingsList';
import { useThemedStyles, useTokens } from '../lib/tokens';
import { useConnection } from '../store/connection';

const RISKS = [
  { id: 'conservative', label: '保守', hint: '偏防御、质量与低波动' },
  { id: 'moderate', label: '普通', hint: '轮动主线与中等弹性' },
  { id: 'aggressive', label: '激进', hint: '主题催化与高弹性' },
];

const CAP_FIELDS: { key: string; label: string; hint: string }[] = [
  { key: 'single_position_max_weight_pct', label: '单票上限', hint: '超过的建议会被拦下' },
  { key: 'sector_max_weight_pct', label: '行业上限', hint: '行业集中度上限' },
  { key: 'etf_max_weight_pct', label: 'ETF 上限', hint: 'ETF 用独立上限' },
  { key: 'crypto_max_weight_pct', label: '加密上限', hint: '加密资产合计占 NAV 上限' },
];

export default function InvestorProfileScreen() {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  const { baseURL, token } = useConnection();

  const [risk, setRisk] = useState('moderate');
  const [notes, setNotes] = useState('');
  const [baseline, setBaseline] = useState({ risk: 'moderate', notes: '' });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  /** 风控上限：原来只能改风险偏好，改不了具体上限（加密上限尤其需要） */
  const [policy, setPolicy] = useState<RiskPolicy | null>(null);
  const [caps, setCaps] = useState<Record<string, string>>({});
  const [capsBase, setCapsBase] = useState<Record<string, string>>({});
  const [capsSaving, setCapsSaving] = useState(false);
  const [capsMessage, setCapsMessage] = useState('');


  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await fetchSettings(baseURL, token);
      const r = String(s.investor_profile?.risk_level ?? 'moderate');
      const n = String(s.investor_profile?.notes ?? '');
      setRisk(r);
      setNotes(n);
      setBaseline({ risk: r, notes: n });
      const active = await fetchActiveRiskPolicy(baseURL, token);
      setPolicy(active);
      const rules = (active?.rules ?? {}) as Record<string, unknown>;
      const nextCaps: Record<string, string> = {};
      for (const f of CAP_FIELDS) {
        const v = rules[f.key];
        nextCaps[f.key] = v == null ? '' : String(v);
      }
      setCaps(nextCaps);
      setCapsBase(nextCaps);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = risk !== baseline.risk || notes !== baseline.notes;
  const capsDirty = CAP_FIELDS.some((f) => (caps[f.key] ?? '') !== (capsBase[f.key] ?? ''));

  const saveCaps = async () => {
    if (!policy) return;
    setCapsSaving(true);
    setCapsMessage('');
    try {
      const patch: Record<string, number> = {};
      for (const f of CAP_FIELDS) {
        const raw = (caps[f.key] ?? '').trim();
        if (!raw) continue;
        const n = Number(raw);
        if (Number.isFinite(n) && n >= 0) patch[f.key] = n;
      }
      const updated = await updateRiskPolicy(baseURL, token, policy, patch);
      setPolicy(updated);
      const rules = (updated?.rules ?? {}) as Record<string, unknown>;
      const next: Record<string, string> = {};
      for (const f of CAP_FIELDS) next[f.key] = rules[f.key] == null ? '' : String(rules[f.key]);
      setCaps(next);
      setCapsBase(next);
      setCapsMessage('已生效');
      setTimeout(() => setCapsMessage(''), 1800);
    } catch (e) {
      setCapsMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setCapsSaving(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setMessage('');
    try {
      await updateInvestorProfile(baseURL, token, { risk_level: risk, notes });
      setBaseline({ risk, notes });
      setMessage('已保存');
      setTimeout(() => setMessage(''), 1800);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (loading) return <ActivityIndicator style={{ marginTop: 60 }} />;

  return (
    <ScrollView style={[styles.container, { backgroundColor: t.pageBg }]} contentContainerStyle={styles.content}>
      <SettingsGroup title="风险偏好" footer="影响 Agent 给结论时的弹性与仓位建议口径。">
        {RISKS.map((r, i) => {
          const on = risk === r.id;
          return (
            <Pressable
              key={r.id}
              style={[
                styles.riskRow,
                i < RISKS.length - 1 && { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: t.sep },
              ]}
              onPress={() => setRisk(r.id)}
            >
              <Ionicons
                name={on ? 'radio-button-on' : 'radio-button-off'}
                size={20}
                color={on ? t.accent : t.sub}
              />
              <View style={styles.riskText}>
                <Text style={[styles.riskLabel, { color: t.text }]}>{r.label}</Text>
                <Text style={[styles.riskHint, { color: t.sub }]}>{r.hint}</Text>
              </View>
            </Pressable>
          );
        })}
      </SettingsGroup>

      <SettingsGroup title="补充说明" footer="例如：偏好低波动、不参与题材炒作、单票不超过 20% 等。">
        <TextInput
          style={[styles.notes, { color: t.text, borderColor: t.sep }]}
          value={notes}
          onChangeText={setNotes}
          placeholder="写下你的投资约束与偏好"
          placeholderTextColor={t.sub}
          multiline
        />
      </SettingsGroup>

      {policy ? (
        <SettingsGroup
          title="风控上限"
          footer={`当前生效「${policy.name ?? '默认档'}」。上限直接决定建议仓位被拦在哪里：调低 → 超限变多，调高 → 风险放大。`}
        >
          {CAP_FIELDS.map((f, i) => (
            <View
              key={f.key}
              style={[
                styles.capRow,
                i < CAP_FIELDS.length - 1 && { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: t.sep },
              ]}
            >
              <View style={{ flex: 1 }}>
                <Text style={[styles.riskLabel, { color: t.text }]}>{f.label}</Text>
                <Text style={[styles.riskHint, { color: t.sub }]}>{f.hint}</Text>
              </View>
              <TextInput
                style={[styles.capInput, { color: t.text, borderColor: t.sep }]}
                keyboardType="decimal-pad"
                value={caps[f.key] ?? ''}
                onChangeText={(v) => setCaps((prev) => ({ ...prev, [f.key]: v }))}
                placeholder="—"
                placeholderTextColor={t.sub}
              />
              <Text style={[styles.riskHint, { color: t.sub }]}>%</Text>
            </View>
          ))}
          <View style={styles.actions}>
            <Pressable
              style={[styles.saveBtn, { backgroundColor: capsDirty ? t.accent : t.sep }, capsSaving && styles.disabled]}
              onPress={() => void saveCaps()}
              disabled={!capsDirty || capsSaving}
            >
              <Text style={[styles.saveText, !capsDirty && { color: t.sub }]}>
                {capsSaving ? '保存中…' : capsDirty ? '保存上限' : '没有改动'}
              </Text>
            </Pressable>
            {capsMessage ? <Text style={[styles.message, { color: t.accent }]}>{capsMessage}</Text> : null}
          </View>
        </SettingsGroup>
      ) : null}

      <View style={styles.actions}>
        <Pressable
          style={[styles.saveBtn, { backgroundColor: dirty ? t.accent : t.sep }, saving && styles.disabled]}
          onPress={() => void save()}
          disabled={!dirty || saving}
        >
          <Text style={[styles.saveText, !dirty && { color: t.sub }]}>
            {saving ? '保存中…' : dirty ? '保存' : '没有改动'}
          </Text>
        </Pressable>
        {message ? <Text style={[styles.message, { color: t.accent }]}>{message}</Text> : null}
      </View>
    </ScrollView>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1 },
  content: { paddingTop: 20, paddingBottom: 40 },
  riskRow: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 60, paddingHorizontal: 16, paddingVertical: 8 },
  riskText: { flex: 1 },
  riskLabel: { fontSize: 15 },
  riskHint: { fontSize: 11.5, marginTop: 3 },
  capRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 10 },
  capInput: { borderWidth: 1, borderRadius: 8, minWidth: 64, textAlign: 'right', paddingVertical: 6, paddingHorizontal: 8 },
  notes: { minHeight: 96, fontSize: 14.5, lineHeight: 21, padding: 14, textAlignVertical: 'top' },
  actions: { paddingHorizontal: 16, marginBottom: 24 },
  saveBtn: { borderRadius: 12, paddingVertical: 14, alignItems: 'center' },
  disabled: { opacity: 0.7 },
  saveText: { color: '#fff', fontWeight: '600', fontSize: 15 },
  message: { textAlign: 'center', fontSize: 13, marginTop: 10 },
});
