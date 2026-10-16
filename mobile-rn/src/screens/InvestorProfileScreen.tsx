import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { fetchSettings, updateInvestorProfile } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { SettingsGroup } from '../components/SettingsList';
import { useThemedStyles, useTokens } from '../lib/tokens';
import { useConnection } from '../store/connection';

const RISKS = [
  { id: 'conservative', label: '保守', hint: '偏防御、质量与低波动' },
  { id: 'moderate', label: '普通', hint: '轮动主线与中等弹性' },
  { id: 'aggressive', label: '激进', hint: '主题催化与高弹性' },
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
  notes: { minHeight: 96, fontSize: 14.5, lineHeight: 21, padding: 14, textAlignVertical: 'top' },
  actions: { paddingHorizontal: 16, marginBottom: 24 },
  saveBtn: { borderRadius: 12, paddingVertical: 14, alignItems: 'center' },
  disabled: { opacity: 0.7 },
  saveText: { color: '#fff', fontWeight: '600', fontSize: 15 },
  message: { textAlign: 'center', fontSize: 13, marginTop: 10 },
});
