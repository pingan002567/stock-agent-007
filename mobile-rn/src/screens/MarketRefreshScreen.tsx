import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { fetchSettings, updateMarketRefresh } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { SettingsGroup, SettingsRow } from '../components/SettingsList';
import { useThemedStyles, useTokens } from '../lib/tokens';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';

type Nav = NativeStackNavigationProp<RootStackParamList>;

const RANGES = {
  page: [30, 600] as [number, number],
  warmup: [120, 3600] as [number, number],
  cooldown: [30, 1800] as [number, number],
};

export default function MarketRefreshScreen() {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  const navigation = useNavigation<Nav>();
  const { baseURL, token } = useConnection();

  const [pageSec, setPageSec] = useState(30);
  const [warmupSec, setWarmupSec] = useState(300);
  const [cooldownSec, setCooldownSec] = useState(120);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await fetchSettings(baseURL, token);
      const mr = s.market_refresh;
      setPageSec(Number(mr?.page_refresh_seconds ?? 30));
      setWarmupSec(Number(mr?.warmup_seconds ?? 300));
      setCooldownSec(Number(mr?.manual_cooldown_seconds ?? 120));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    setMessage('');
    try {
      await updateMarketRefresh(baseURL, token, {
        page_refresh_seconds: clamp(pageSec, RANGES.page),
        warmup_seconds: clamp(warmupSec, RANGES.warmup),
        manual_cooldown_seconds: clamp(cooldownSec, RANGES.cooldown),
      });
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
      <SettingsGroup title="常用值">
        <View style={styles.presetRow}>
          {[30, 60, 120].map((p) => {
            const on = pageSec === p;
            return (
              <Pressable
                key={p}
                style={[styles.preset, { borderColor: on ? t.accent : t.sep, backgroundColor: on ? t.cardAlt : 'transparent' }]}
                onPress={() => setPageSec(p)}
              >
                <Text style={[styles.presetText, { color: on ? t.accent : t.sub }]}>{p} 秒</Text>
              </Pressable>
            );
          })}
        </View>
      </SettingsGroup>

      <SettingsGroup title="刷新参数" footer="预热时长影响首次取数是否走缓存；手动冷却限制「立即评估」的频率。">
        <Stepper label="页面刷新" value={pageSec} unit="秒" range={RANGES.page} step={10} onChange={setPageSec} />
        <Stepper label="预热时长" value={warmupSec} unit="秒" range={RANGES.warmup} step={30} onChange={setWarmupSec} />
        <Stepper label="手动冷却" value={cooldownSec} unit="秒" range={RANGES.cooldown} step={10} onChange={setCooldownSec} last />
      </SettingsGroup>

      <View style={styles.actions}>
        <Pressable style={[styles.saveBtn, { backgroundColor: t.accent }, saving && styles.disabled]} onPress={() => void save()} disabled={saving}>
          <Text style={styles.saveText}>{saving ? '保存中…' : '保存'}</Text>
        </Pressable>
        {message ? <Text style={[styles.message, { color: t.accent }]}>{message}</Text> : null}
      </View>

      <SettingsGroup title="数据源">
        <SettingsRow label="行情数据源" onPress={() => navigation.navigate('DataSources')} last />
      </SettingsGroup>
    </ScrollView>
  );
}

function clamp(v: number, [min, max]: [number, number]): number {
  return Math.min(max, Math.max(min, v));
}

function Stepper({
  label,
  value,
  unit,
  range,
  step,
  onChange,
  last,
}: {
  label: string;
  value: number;
  unit: string;
  range: [number, number];
  step: number;
  onChange: (v: number) => void;
  last?: boolean;
}) {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  return (
    <View
      style={[
        styles.stepperRow,
        !last && { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: t.sep },
      ]}
    >
      <Text style={[styles.stepperLabel, { color: t.text }]}>{label}</Text>
      <View style={styles.stepperCtl}>
        <Pressable style={[styles.stepBtn, { borderColor: t.sep }]} onPress={() => onChange(clamp(value - step, range))}>
          <Text style={[styles.stepText, { color: t.text }]}>－</Text>
        </Pressable>
        <Text style={[styles.stepValue, { color: t.text }]}>
          {value} {unit}
        </Text>
        <Pressable style={[styles.stepBtn, { borderColor: t.sep }]} onPress={() => onChange(clamp(value + step, range))}>
          <Text style={[styles.stepText, { color: t.text }]}>＋</Text>
        </Pressable>
      </View>
    </View>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1 },
  content: { paddingTop: 20, paddingBottom: 40 },
  presetRow: { flexDirection: 'row', gap: 8, padding: 16 },
  preset: { flex: 1, borderWidth: 1, borderRadius: 9, paddingVertical: 9, alignItems: 'center' },
  presetText: { fontSize: 13 },
  stepperRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 52, paddingHorizontal: 16 },
  stepperLabel: { fontSize: 15 },
  stepperCtl: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  stepBtn: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 14, paddingVertical: 4 },
  stepText: { fontSize: 15 },
  stepValue: { fontSize: 14, minWidth: 74, textAlign: 'center' },
  actions: { paddingHorizontal: 16, marginBottom: 24 },
  saveBtn: { borderRadius: 12, paddingVertical: 14, alignItems: 'center' },
  disabled: { opacity: 0.6 },
  saveText: { color: '#fff', fontWeight: '600', fontSize: 15 },
  message: { textAlign: 'center', fontSize: 13, marginTop: 10 },
});
