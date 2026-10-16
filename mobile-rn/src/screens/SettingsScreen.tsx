import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import {
  connectLlmProvider,
  disconnectLlmProvider,
  fetchCostSummary,
  fetchLlmProviders,
  fetchSettings,
  setDefaultLlmModel,
  setSkillEnabled,
  updateInvestorProfile,
  updateMarketRefresh,
  updateNotificationPrefs,
} from '../api/client';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import { ACCENT_PRESETS, useTheme } from '../store/theme';
import type { CostSummary, LlmProvidersSnapshot, WorkbenchSettings } from '../types';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export default function SettingsScreen() {
  const navigation = useNavigation<Nav>();
  const { baseURL, token, disconnect } = useConnection();
  const { accentHex, scheme, setAccent, setScheme } = useTheme();
  const [settings, setSettings] = useState<WorkbenchSettings | null>(null);
  const [llm, setLlm] = useState<LlmProvidersSnapshot | null>(null);
  const [cost, setCost] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const [refreshSec, setRefreshSec] = useState('30');
  const [risk, setRisk] = useState('balanced');
  const [notes, setNotes] = useState('');
  const [connectKey, setConnectKey] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, l, c] = await Promise.all([fetchSettings(baseURL, token), fetchLlmProviders(baseURL, token), fetchCostSummary(baseURL, token)]);
      setSettings(s);
      setLlm(l);
      setCost(c);
      setRefreshSec(String(s.market_refresh?.page_refresh_seconds ?? 30));
      setRisk(String(s.investor_profile?.risk_level ?? 'balanced'));
      setNotes(String(s.investor_profile?.notes ?? ''));
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <ActivityIndicator style={{ marginTop: 60 }} />;

  const runtime = settings?.agent_runtime;
  const skills = settings?.skills ?? [];

  const toggleSkill = async (name: string, enabled: boolean) => {
    setSettings((s) => (s ? { ...s, skills: s.skills?.map((k) => (k.name === name ? { ...k, enabled } : k)) } : s));
    await setSkillEnabled(baseURL, token, name, enabled);
  };

  const saveMarketRefresh = async () => {
    await updateMarketRefresh(baseURL, token, { page_refresh_seconds: Number(refreshSec) });
  };

  const saveProfile = async () => {
    await updateInvestorProfile(baseURL, token, { risk_level: risk, notes });
  };

  const toggleNotify = async (v: boolean) => {
    setSettings((s) => (s ? { ...s, notification_prefs: { ...s.notification_prefs, duty_completion_push: v } } : s));
    await updateNotificationPrefs(baseURL, token, { duty_completion_push: v });
  };

  const connect = async (providerId: string) => {
    await connectLlmProvider(baseURL, token, providerId, connectKey[providerId]);
    setConnectKey((k) => ({ ...k, [providerId]: '' }));
    setLlm(await fetchLlmProviders(baseURL, token));
  };

  const disconnectP = async (providerId: string) => {
    setLlm(await disconnectLlmProvider(baseURL, token, providerId));
  };

  const setDefault = async (modelRef: string) => {
    setLlm(await setDefaultLlmModel(baseURL, token, modelRef));
  };

  const totalCost = cost?.total?.total_cost ?? 0;

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 16 }}>
      <Text style={styles.title}>设置</Text>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>运行状态</Text>
        <Text style={styles.line}>模型：{String(runtime?.model_name ?? '—')}</Text>
        <Text style={styles.line}>模式：{String(runtime?.mode ?? '—')}</Text>
        <Text style={styles.line}>客户端：{String(runtime?.active_client ?? '—')}</Text>
        <Text style={styles.line}>降级：{runtime?.degraded ? '是' : '否'}</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>外观</Text>
        <View style={styles.accentRow}>
          {ACCENT_PRESETS.map((p) => (
            <Pressable
              key={p.id}
              style={[styles.swatch, { backgroundColor: p.hex }, accentHex === p.hex && styles.swatchActive]}
              onPress={() => setAccent(p.hex)}
            />
          ))}
        </View>
        <View style={styles.schemeRow}>
          {(['system', 'light', 'dark'] as const).map((s) => (
            <Pressable key={s} style={[styles.schemeBtn, scheme === s && styles.schemeActive]} onPress={() => setScheme(s)}>
              <Text style={[styles.schemeText, scheme === s && styles.schemeTextActive]}>
                {s === 'system' ? '跟随系统' : s === 'light' ? '浅色' : '深色'}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>AI 技能</Text>
        {skills.map((k) => (
          <View key={k.name} style={styles.toggleRow}>
            <Text style={styles.toggleLabel}>{k.name}</Text>
            <Switch value={!!k.enabled} disabled={!!k.locked} onValueChange={(v) => void toggleSkill(String(k.name), v)} />
          </View>
        ))}
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>模型服务</Text>
        {llm?.connected?.map((p) => {
          const pid = p.id ?? p.provider_id ?? '';
          const isDefaultModel = (modelId: string) => llm.default_model === modelId || llm.default_model === `${pid}/${modelId}`;
          return (
            <View key={pid} style={styles.toggleRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.toggleLabel}>
                  {p.name}
                  {pid && (llm.default_model?.startsWith(pid) ? '（默认）' : '')}
                </Text>
                {p.models?.map((m) => (
                  <Text key={m.id} style={styles.modelLine} onPress={() => void setDefault(`${pid}/${m.id}`)}>
                    {m.name ?? m.id}
                    {isDefaultModel(m.id) ? ' ✓' : ''}
                  </Text>
                ))}
              </View>
              <Pressable onPress={() => void disconnectP(pid)}>
                <Text style={styles.danger}>断开</Text>
              </Pressable>
            </View>
          );
        })}
        {llm?.catalog?.map((p) => {
          const pid = p.id ?? p.provider_id ?? '';
          return (
            <View key={pid} style={styles.toggleRow}>
              <Text style={styles.toggleLabel}>{p.name}</Text>
              <TextInput
                style={styles.miniInput}
                placeholder="API Key（可选）"
                value={connectKey[pid] ?? ''}
                onChangeText={(t) => setConnectKey((k) => ({ ...k, [pid]: t }))}
                secureTextEntry
              />
              <Pressable onPress={() => void connect(pid)}>
                <Text style={styles.link}>连接</Text>
              </Pressable>
            </View>
          );
        })}
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>费用（累计 ¥{totalCost.toFixed(4)}）</Text>
        {(cost?.days ?? []).slice(-5).map((d) => (
          <Text key={d.date} style={styles.line}>
            {d.date} · ¥{d.total_cost?.toFixed(4)} · {d.run_count ?? 0} 次
          </Text>
        ))}
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>行情刷新（秒）</Text>
        <TextInput style={styles.input} value={refreshSec} onChangeText={setRefreshSec} keyboardType="numeric" />
        <Pressable style={styles.saveBtn} onPress={() => void saveMarketRefresh()}>
          <Text style={styles.saveText}>保存</Text>
        </Pressable>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>投资者画像</Text>
        <View style={styles.riskRow}>
          {['conservative', 'balanced', 'aggressive'].map((r) => (
            <Pressable key={r} style={[styles.riskBtn, risk === r && styles.riskActive]} onPress={() => setRisk(r)}>
              <Text style={[styles.riskText, risk === r && styles.riskTextActive]}>{r}</Text>
            </Pressable>
          ))}
        </View>
        <TextInput style={styles.input} placeholder="备注" value={notes} onChangeText={setNotes} multiline />
        <Pressable style={styles.saveBtn} onPress={() => void saveProfile()}>
          <Text style={styles.saveText}>保存</Text>
        </Pressable>
      </View>

      <View style={styles.card}>
        <View style={styles.toggleRow}>
          <Text style={styles.toggleLabel}>定时任务完成推送</Text>
          <Switch value={!!settings?.notification_prefs?.duty_completion_push} onValueChange={(v) => void toggleNotify(v)} />
        </View>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>更多</Text>
        <Pressable onPress={() => navigation.navigate('DataSources')} style={styles.navRow}>
          <Text style={styles.link}>行情数据源</Text>
        </Pressable>
        <Pressable onPress={() => navigation.navigate('Reports')} style={styles.navRow}>
          <Text style={styles.link}>研究报告</Text>
        </Pressable>
        <Pressable onPress={() => navigation.navigate('ScheduledTasks')} style={styles.navRow}>
          <Text style={styles.link}>定时任务</Text>
        </Pressable>
        <Pressable onPress={() => navigation.navigate('Strategy')} style={styles.navRow}>
          <Text style={styles.link}>策略回测</Text>
        </Pressable>
      </View>

      <Pressable style={styles.disconnectBtn} onPress={disconnect}>
        <Text style={styles.disconnectText}>断开并切换后端</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  title: { fontSize: 20, fontWeight: '700', marginBottom: 12 },
  card: { backgroundColor: '#f6f8fa', borderRadius: 10, padding: 14, marginBottom: 12 },
  cardTitle: { fontSize: 14, fontWeight: '700', marginBottom: 8 },
  line: { fontSize: 13, color: '#444', marginBottom: 4 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 4 },
  toggleLabel: { fontSize: 13, flex: 1 },
  modelLine: { fontSize: 12, color: '#007AFF', paddingVertical: 2 },
  danger: { color: '#c0392b', fontSize: 13 },
  link: { color: '#007AFF', fontSize: 14, paddingVertical: 8 },
  miniInput: { flex: 1, borderWidth: 1, borderColor: '#ddd', borderRadius: 6, padding: 6, fontSize: 12, marginHorizontal: 8 },
  input: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 10, fontSize: 14, marginTop: 6 },
  saveBtn: { backgroundColor: '#007AFF', borderRadius: 8, padding: 10, alignItems: 'center', marginTop: 10 },
  saveText: { color: '#fff', fontWeight: '600' },
  riskRow: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  riskBtn: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: '#ddd' },
  riskActive: { borderColor: '#007AFF', backgroundColor: '#eef4ff' },
  riskText: { color: '#666', fontSize: 13 },
  riskTextActive: { color: '#007AFF' },
  navRow: { paddingVertical: 4 },
  accentRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 12 },
  swatch: { width: 32, height: 32, borderRadius: 16, borderWidth: 2, borderColor: 'transparent' },
  swatchActive: { borderColor: '#333' },
  schemeRow: { flexDirection: 'row', gap: 8 },
  schemeBtn: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: '#ddd' },
  schemeActive: { borderColor: '#007AFF', backgroundColor: '#eef4ff' },
  schemeText: { color: '#666', fontSize: 13 },
  schemeTextActive: { color: '#007AFF' },
  disconnectBtn: { marginTop: 4, padding: 14, borderRadius: 10, borderWidth: 1, borderColor: '#c0392b', alignItems: 'center' },
  disconnectText: { color: '#c0392b', fontWeight: '600' },
});
